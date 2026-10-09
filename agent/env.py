"""Gymnasium environment for STS2 combat, scoped to a single fixed encounter.

Action space: Discrete(MAX_HAND + 1)
  0..MAX_HAND-1 -> play the card at that hand index (mod auto-targets the
                   first hittable enemy for enemy-targeted cards)
  MAX_HAND      -> end turn

Observation space: Box(79,) float32 — see _encode() for the layout.

Episode = one combat against an encounter sampled uniformly from `encounters`
(NIBBITS_WEAK only by default; WEAK_ENCOUNTERS = all Act 1 weak fights).
Reset forces a clean fight via the game's own dev-console `fight` command,
which clears any pending screens (see docs/modding-approach.md), so this
works whether the previous episode ended in a win, a loss, or mid-turn.
"""
from __future__ import annotations

import time

import numpy as np
import gymnasium as gym
import requests
from gymnasium import spaces

from client import AutoSpireClient

MAX_HAND = 10
MAX_ENEMIES = 3
ENCOUNTER = "NIBBITS_WEAK"
WEAK_ENCOUNTERS = ("NIBBITS_WEAK", "SLIMES_WEAK", "SHRINKER_BEETLE_WEAK", "FUZZY_WURM_CRAWLER_WEAK")
MAX_STEPS = 60

CARD_FEATURES = 6  # cost, can_play, is_attack, is_skill, is_power, upgraded
PLAYER_FEATURES = 4  # hp, block, energy, maxEnergy
ENEMY_FEATURES = 5  # hp, block, intent_damage, is_attack_intent, is_alive
OBS_DIM = MAX_HAND * CARD_FEATURES + PLAYER_FEATURES + MAX_ENEMIES * ENEMY_FEATURES


def _encode_card(card: dict) -> list[float]:
    return [
        card["cost"] / 5.0,
        float(card["canPlay"]),
        float(card["type"] == "Attack"),
        float(card["type"] == "Skill"),
        float(card["type"] == "Power"),
        float(card["upgraded"]),
    ]


def _encode(combat: dict) -> np.ndarray:
    player = combat.get("player") or {}
    hand = player.get("hand") or []
    enemies = combat.get("enemies") or []

    hand_feats: list[float] = []
    for i in range(MAX_HAND):
        hand_feats += _encode_card(hand[i]) if i < len(hand) else [0.0] * CARD_FEATURES

    player_feats = [
        player.get("hp", 0) / 100.0,
        player.get("block", 0) / 30.0,
        player.get("energy", 0) / 10.0,
        player.get("maxEnergy", 0) / 10.0,
    ]

    enemy_feats: list[float] = []
    for i in range(MAX_ENEMIES):
        if i < len(enemies) and enemies[i].get("isAlive"):
            e = enemies[i]
            intent = e.get("intent") or {}
            intents = intent.get("intents") or []
            atk = next((it for it in intents if it["type"] == "Attack"), None)
            enemy_feats += [
                e["hp"] / max(e["maxHp"], 1),
                e.get("block", 0) / 30.0,
                (atk["totalDamage"] if atk else 0) / 30.0,
                float(atk is not None),
                1.0,
            ]
        else:
            enemy_feats += [0.0] * ENEMY_FEATURES

    return np.array(hand_feats + player_feats + enemy_feats, dtype=np.float32)


def _ready(combat: dict) -> bool:
    """Player can act and no queued action is still resolving (sim has no queue)."""
    return bool(combat.get("inCombat") and combat.get("isPlayPhase") and combat.get("actionsIdle", True))


def _total_enemy_hp(combat: dict) -> int:
    return sum(e["hp"] for e in (combat.get("enemies") or []) if e.get("isAlive"))


def _player_hp(combat: dict) -> int:
    return (combat.get("player") or {}).get("hp", 0)


class STS2CombatEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(
        self,
        encounter: str | tuple[str, ...] | list[str] = ENCOUNTER,
        client: AutoSpireClient | None = None,
        episodes_per_restart: int = 40,
    ):
        super().__init__()
        self.encounters = [encounter] if isinstance(encounter, str) else list(encounter)
        self.client = client or AutoSpireClient()
        self.action_space = spaces.Discrete(MAX_HAND + 1)
        self.observation_space = spaces.Box(low=-1.0, high=10.0, shape=(OBS_DIM,), dtype=np.float32)
        self._steps = 0
        self._combat: dict = {}  # last observed state, for action_masks()
        # The live game's CPU/animation backlog only clears on a full process
        # restart (see docs/modding-approach.md) — periodically pay that cost
        # instead of letting every episode's `fight` reset degrade further.
        self.episodes_per_restart = episodes_per_restart
        self._episode_count = 0
        # Set by step() when a live-game HTTP call fails mid-episode, so the
        # *next* reset() forces a full_restart() regardless of the counter —
        # a connection hiccup is exactly the animation/CPU-backlog symptom
        # full_restart() is meant to clear, so treat it as a signal, not
        # just noise to retry past.
        self._needs_restart = False

    def reset(self, *, seed=None, options=None, max_attempts: int = 3):
        super().reset(seed=seed)
        for attempt in range(max_attempts):
            try:
                if self._needs_restart or self._episode_count % self.episodes_per_restart == 0:
                    self.client.full_restart()  # lands inRun=true on the Act 1 map, not yet in combat
                    self._needs_restart = False
                self.client.exec("heal 999")
                self.client.exec(f"fight {self.np_random.choice(self.encounters)}", settle=0.5)
                self.client.exec("heal 999")
                combat = self.client.wait_for(_ready, timeout=15.0)
                self._episode_count += 1
                self._steps = 0
                self._combat = combat
                return _encode(combat), {}
            except (requests.RequestException, TimeoutError) as exc:
                print(f"[env] reset() attempt {attempt} failed: {exc!r} — forcing full_restart and retrying")
                self._needs_restart = True
        raise RuntimeError(f"STS2CombatEnv.reset() failed after {max_attempts} attempts")

    def step(self, action: int):
        self._steps += 1
        try:
            prev = self.client.combat()
            prev_enemy_hp = _total_enemy_hp(prev)
            prev_player_hp = _player_hp(prev)

            if action < MAX_HAND:
                result = self.client.play(action)
            else:
                result = self.client.end_turn()
            invalid = "error" in result

            # Poll until it's the player's turn to act again, or combat has
            # ended. /combat stops returning player/enemy data once inCombat
            # flips to false, so track the last full snapshot to determine
            # win vs. loss.
            last_full = prev
            combat = prev
            # Enemy turns that add status cards (Slimed) play a preview animation and
            # have been seen to take >8s with the window in the background.
            deadline = time.monotonic() + 20.0
            while time.monotonic() < deadline:
                combat = self.client.combat()
                if not combat.get("inCombat"):
                    break
                last_full = combat
                if _ready(combat):
                    break
                time.sleep(0.05)
            else:
                raise TimeoutError("turn never returned to the player (game turn loop wedged?)")
        except (requests.RequestException, TimeoutError) as exc:
            # Live-game connection hiccup mid-episode (see docs/modding-approach.md
            # for the animation/CPU-backlog symptom this comes from) — end this
            # episode early instead of crashing the whole training run.
            # reset() will see _needs_restart and force a full_restart() next time.
            self._needs_restart = True
            return np.zeros(OBS_DIM, dtype=np.float32), -1.0, True, False, {"aborted": True, "error": repr(exc)}

        terminated = not combat.get("inCombat", False)
        truncated = (not terminated) and self._steps >= MAX_STEPS

        if terminated:
            enemy_hp = _total_enemy_hp(last_full)
            player_hp = _player_hp(last_full)
            won = player_hp > 0
        else:
            enemy_hp = _total_enemy_hp(combat)
            player_hp = _player_hp(combat)
            won = None

        reward = (prev_enemy_hp - enemy_hp) / 10.0 - (prev_player_hp - player_hp) / 10.0
        if invalid:
            reward -= 0.1
        if terminated:
            reward += 5.0 if won else -5.0
        if truncated:
            reward -= 1.0

        self._combat = combat
        obs = _encode(combat) if not terminated else np.zeros(OBS_DIM, dtype=np.float32)
        info = {"invalid_action": invalid, "won": won}
        return obs, reward, terminated, truncated, info

    def action_masks(self) -> np.ndarray:
        """For sb3-contrib MaskablePPO: playable hand cards + end turn (always legal).

        Without this a deterministic policy that picks an unplayable card gets
        the same observation back and repeats it until truncation."""
        hand = (self._combat.get("player") or {}).get("hand") or []
        mask = np.zeros(MAX_HAND + 1, dtype=bool)
        mask[:min(len(hand), MAX_HAND)] = [c["canPlay"] for c in hand[:MAX_HAND]]
        mask[MAX_HAND] = True
        return mask
