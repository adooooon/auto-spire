"""Gymnasium environment for STS2 combat, scoped to a single fixed encounter.

Action space: Discrete(MAX_HAND * MAX_ENEMIES + 1)
  a < END_TURN -> play hand card a // MAX_ENEMIES at enemy slot a % MAX_ENEMIES
                  (slot = index into the living-enemy list, sent as its combatId;
                  only AnyEnemy cards use the slot — others are masked to slot 0)
  END_TURN     -> end turn

Observation space: Box(OBS_DIM,) float32 — see _encode() for the layout.

Episode = one combat against an encounter sampled uniformly from `encounters`
(NIBBITS_WEAK only by default; see ENCOUNTER_GROUPS for the Act 1 sets).
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
from sim.cards import CARDS, COMMONS, starter_deck
from sim.engine import MONSTERS

MAX_HAND = 10
MAX_ENEMIES = 4  # SLIMES_NORMAL
ENCOUNTER = "NIBBITS_WEAK"
WEAK_ENCOUNTERS = ("NIBBITS_WEAK", "SLIMES_WEAK", "SHRINKER_BEETLE_WEAK", "FUZZY_WURM_CRAWLER_WEAK")
NORMAL_ENCOUNTERS = ("NIBBITS_NORMAL", "SLIMES_NORMAL", "OVERGROWTH_CRAWLERS",
                     "MAWLER_NORMAL", "FLYCONID_NORMAL", "RUBY_RAIDERS_NORMAL",
                     "INKLETS_NORMAL", "CUBEX_CONSTRUCT_NORMAL", "VINE_SHAMBLER_NORMAL", "FOGMOG_NORMAL",
                     "SNAPPING_JAXFRUIT_NORMAL", "SLITHERING_STRANGLER_NORMAL")
ENCOUNTER_GROUPS = {"weak": WEAK_ENCOUNTERS, "normal": NORMAL_ENCOUNTERS, "act1": WEAK_ENCOUNTERS + NORMAL_ENCOUNTERS}


def parse_encounters(arg: str) -> list[str]:
    """CLI --encounters: a group name (weak/normal/act1) or comma-separated encounter ids."""
    return list(ENCOUNTER_GROUPS.get(arg) or arg.split(","))
MAX_STEPS = 100  # card plays count as steps; 0-cost cards (Anger) and draw make fights longer
END_TURN = MAX_HAND * MAX_ENEMIES

# Monster identity matters (which one applies Shrink, whose Strength stacks) and HP alone
# only hints at it; the one-hots cover every monster and card the sim models.
MONSTER_IDS = sorted(MONSTERS)
CARD_IDS = sorted(CARDS)
CARD_FEATURES = 6 + len(CARD_IDS)  # cost, can_play, is_attack, is_skill, is_power, upgraded + identity
# hp, block, energy, maxEnergy, shrunk, vulnerable, frail, tangled, constrict, strength, round
PLAYER_FEATURES = 11
PILE_FEATURES = 2 * len(CARD_IDS)  # per-card counts in draw and discard piles
# hp frac, hp, block, intent_damage, is_attack_intent, vulnerable, strength, artifact, slippery,
# is_alive + identity
ENEMY_FEATURES = 10 + len(MONSTER_IDS)
OBS_DIM = MAX_HAND * CARD_FEATURES + PLAYER_FEATURES + PILE_FEATURES + MAX_ENEMIES * ENEMY_FEATURES


def _encode_card(card: dict) -> list[float]:
    return [
        card["cost"] / 5.0,
        float(card["canPlay"]),
        float(card["type"] == "Attack"),
        float(card["type"] == "Skill"),
        float(card["type"] == "Power"),
        float(card["upgraded"]),
    ] + [float(card["id"] == cid) for cid in CARD_IDS]


def random_deck(rng: np.random.Generator) -> list[str]:
    """Starter deck minus 0-3 Strikes/Defends, plus 0-8 random Commons (with replacement) —
    roughly the decks an Act 1 run sees."""
    deck = starter_deck()
    for _ in range(rng.integers(0, 4)):
        deck.remove(rng.choice([c for c in deck if c != "BASH"]))
    return deck + list(rng.choice(COMMONS, size=rng.integers(0, 9)))


def _power(entity: dict, name: str) -> int:
    return next((p["amount"] for p in entity.get("powers") or [] if p["name"] == name), 0)


def _living(combat: dict) -> list[dict]:
    """Living enemies in list order — the slots actions target. A dead illusion stays in
    /combat's list (isAlive=false) until it revives, but can't be hit."""
    return [e for e in combat.get("enemies") or [] if e.get("isAlive")]


def _encode(combat: dict) -> np.ndarray:
    player = combat.get("player") or {}
    hand = player.get("hand") or []
    enemies = _living(combat)

    hand_feats: list[float] = []
    for i in range(MAX_HAND):
        hand_feats += _encode_card(hand[i]) if i < len(hand) else [0.0] * CARD_FEATURES

    player_feats = [
        player.get("hp", 0) / 100.0,
        player.get("block", 0) / 30.0,
        player.get("energy", 0) / 10.0,
        player.get("maxEnergy", 0) / 10.0,
        float(_power(player, "ShrinkPower") != 0),
        _power(player, "VulnerablePower") / 5.0,
        _power(player, "FrailPower") / 5.0,
        _power(player, "TangledPower") / 2.0,
        _power(player, "ConstrictPower") / 10.0,
        _power(player, "StrengthPower") / 5.0,
        combat.get("round", 0) / 20.0,
    ]
    pile_feats = [sum(c["id"] == cid for c in player.get(pile) or []) / 5.0
                  for pile in ("drawPile", "discardPile") for cid in CARD_IDS]

    enemy_feats: list[float] = []
    for i in range(MAX_ENEMIES):
        if i < len(enemies):
            e = enemies[i]
            intent = e.get("intent") or {}
            intents = intent.get("intents") or []
            atk = next((it for it in intents if it["type"] == "Attack"), None)
            enemy_feats += [
                e["hp"] / max(e["maxHp"], 1),
                e["hp"] / 50.0,
                e.get("block", 0) / 30.0,
                (atk["totalDamage"] if atk else 0) / 30.0,
                float(atk is not None),
                _power(e, "VulnerablePower") / 5.0,
                _power(e, "StrengthPower") / 10.0,
                float(_power(e, "ArtifactPower")),
                float(_power(e, "SlipperyPower")),
                1.0,
            ] + [float(e.get("modelId") == mid) for mid in MONSTER_IDS]
        else:
            enemy_feats += [0.0] * ENEMY_FEATURES

    return np.array(hand_feats + player_feats + pile_feats + enemy_feats, dtype=np.float32)


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
        random_decks: bool = False,
        heal: bool = True,  # False: HP carries over from the previous fight (multi-fight runs)
    ):
        super().__init__()
        self.encounters = [encounter] if isinstance(encounter, str) else list(encounter)
        self.client = client or AutoSpireClient()
        self.random_decks = random_decks
        self.heal = heal
        self.deck: list[str] | None = None  # fixed deck (e.g. a run's), overriding random/starter
        self.action_space = spaces.Discrete(END_TURN + 1)
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
                if self.heal:
                    self.client.exec("heal 999")
                # The deck persists across fights in a live run, so set it every episode.
                self.client.set_deck(self.deck or (random_deck(self.np_random) if self.random_decks else starter_deck()))
                self.client.exec(f"fight {self.np_random.choice(self.encounters)}", settle=0.5)
                if self.heal:
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

            if action < END_TURN:
                card, slot = divmod(int(action), MAX_ENEMIES)
                hand = (prev.get("player") or {}).get("hand") or []
                enemies = _living(prev)
                if card < len(hand) and hand[card]["targetType"] == "AnyEnemy" and slot < len(enemies):
                    result = self.client.play(card, enemies[slot]["combatId"])
                elif slot == 0:
                    result = self.client.play(card)
                else:  # slot on a non-targeted card, or no enemy in that slot
                    result = {"error": "invalid_target"}
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
            # last_full predates the final blow, so it can't tell a death from a win —
            # /state still carries the player after combat ends.
            try:
                player_hp = (self.client.state().get("player") or {})["hp"]
            except (requests.RequestException, KeyError):
                self._needs_restart = True
                return np.zeros(OBS_DIM, dtype=np.float32), -1.0, True, False, {"aborted": True}
            won = player_hp > 0
            enemy_hp = 0 if won else _total_enemy_hp(last_full)
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
        info = {"invalid_action": invalid, "won": won, "player_hp": player_hp}
        return obs, reward, terminated, truncated, info

    def action_masks(self) -> np.ndarray:
        """For sb3-contrib MaskablePPO: playable hand cards x living enemy slots
        (slot 0 only for cards that don't pick a target) + end turn (always legal).

        Without this a deterministic policy that picks an unplayable card gets
        the same observation back and repeats it until truncation."""
        hand = (self._combat.get("player") or {}).get("hand") or []
        n_enemies = min(len(_living(self._combat)), MAX_ENEMIES)
        mask = np.zeros(END_TURN + 1, dtype=bool)
        for i, c in enumerate(hand[:MAX_HAND]):
            if c["canPlay"]:
                slots = n_enemies if c["targetType"] == "AnyEnemy" else 1
                mask[i * MAX_ENEMIES:i * MAX_ENEMIES + max(slots, 1)] = True
        mask[END_TURN] = True
        return mask
