"""Gymnasium environment for STS2 combat, scoped to a single fixed encounter.

Action space: Discrete(N_ACTIONS)
  a < END_TURN -> play hand card a // MAX_ENEMIES at enemy slot a % MAX_ENEMIES
                  (slot = index into the living-enemy list, sent as its combatId;
                  only AnyEnemy cards use the slot — others are masked to slot 0)
  END_TURN     -> end turn
  a > END_TURN -> use potion slot (a - POTION_ACTION) // MAX_ENEMIES at enemy slot % MAX_ENEMIES
                  (sim only: masked off when /combat has no potionSlots, i.e. live)
  CHOOSE_HAND + i      -> answer a hand card prompt with hand card i (sim only)
  CHOOSE_DISCARD + k   -> answer a discard prompt with CARD_IDS[k] (sim only)

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
from grow import insert_map
from sim.cards import CARDS, CHOICE_CARDS, COMMONS, RARES, UNCOMMONS, starter_deck
from sim.engine import ENEMY_PW, HIVE_ENCOUNTERS, HIVE_MONSTERS, MONSTERS, SimLoopError
from sim.potions import MAX_POTION_SLOTS, POTION_IDS, POTION_SLOTS, POTIONS
from sim.relics import RELIC_IDS

MAX_HAND = 10
MAX_ENEMIES = 6  # OvicopterNormal.Slots
ENCOUNTER = "NIBBITS_WEAK"
WEAK_ENCOUNTERS = ("NIBBITS_WEAK", "SLIMES_WEAK", "SHRINKER_BEETLE_WEAK", "FUZZY_WURM_CRAWLER_WEAK")
NORMAL_ENCOUNTERS = ("NIBBITS_NORMAL", "SLIMES_NORMAL", "OVERGROWTH_CRAWLERS",
                     "MAWLER_NORMAL", "FLYCONID_NORMAL", "RUBY_RAIDERS_NORMAL",
                     "INKLETS_NORMAL", "CUBEX_CONSTRUCT_NORMAL", "VINE_SHAMBLER_NORMAL", "FOGMOG_NORMAL",
                     "SNAPPING_JAXFRUIT_NORMAL", "SLITHERING_STRANGLER_NORMAL")
ELITE_ENCOUNTERS = ("BYGONE_EFFIGY_ELITE", "BYRDONIS_ELITE", "PHROG_PARASITE_ELITE")
BOSS_ENCOUNTERS = ("VANTOM_BOSS", "CEREMONIAL_BEAST_BOSS", "THE_KIN_BOSS")
ENCOUNTER_GROUPS = {"hive": HIVE_ENCOUNTERS, "weak": WEAK_ENCOUNTERS, "normal": NORMAL_ENCOUNTERS, "hallway": WEAK_ENCOUNTERS + NORMAL_ENCOUNTERS,
                    "elite": ELITE_ENCOUNTERS, "boss": BOSS_ENCOUNTERS,
                    "act1": WEAK_ENCOUNTERS + NORMAL_ENCOUNTERS + ELITE_ENCOUNTERS + BOSS_ENCOUNTERS}


def parse_encounters(arg: str) -> list[str]:
    """CLI --encounters: comma-separated encounter ids and/or group names (weak/normal/hallway/elite/boss/act1)."""
    return [enc for part in arg.split(",") for enc in ENCOUNTER_GROUPS.get(part, (part,))]
MAX_STEPS = 250  # card plays count as steps; bosses (Ceremonial Beast: 252 HP) take many turns
END_TURN = MAX_HAND * MAX_ENEMIES

# Monster identity matters (which one applies Shrink, whose Strength stacks) and HP alone
# only hints at it; the one-hots cover every monster and card the sim models.
MONSTER_IDS = sorted(MONSTERS)
CARD_IDS = sorted(CARDS)
CARD_FEATURES = 6 + len(CARD_IDS)  # cost, can_play, is_attack, is_skill, is_power, upgraded + identity
# hp, block, energy, maxEnergy, shrunk, vulnerable, frail, tangled, constrict, strength, weak,
# ringing, cards played this turn, round, + the amount of each power the player's cards apply.
# ponytail: "exhausted / lost HP this turn" (Evil Eye, Spite, ...) aren't in /combat, so not observed.
PLAYER_POWERS = sorted(({name for c in CARDS.values() for name, _ in c.powers} - {"StrengthPower"})
                       | {"TenderPower", "TaintedPower", "SurroundedPower", "DisintegrationPower"})  # put there by Hive monsters
PLAYER_FEATURES = 14 + len(PLAYER_POWERS)
PILE_FEATURES = 3 * len(CARD_IDS)  # per-card counts in draw, discard and exhaust piles
# hp frac, hp, block, intent_damage, is_attack_intent, vulnerable, strength, artifact, slippery,
# plow, weak, mangle, is_alive + identity
ENEMY_FEATURES = 13 + len(MONSTER_IDS) + len(ENEMY_PW)
# Appended after everything above so grown models keep their old inputs (grow.py):
# potion slots (one-hot per slot), Dexterity, this-turn Dexterity.
POTION_FEATURES = POTION_SLOTS * len(POTION_IDS) + 2
RELIC_COUNTERS = (("pen_nib", 10), ("nunchaku", 10), ("tuning_fork", 10), ("happy_flower", 3), ("pendulum", 3),
                  ("joss_paper", 5), ("lizard_used", 1), ("tea_set", 1))
RELIC_POWERS = (("ThornsPower", 5), ("VigorPower", 10), ("SelfFormingClayPower", 5))
# Appended after POTION_FEATURES: slots 3-4 one-hot, relic multi-hot, counters, this turn's Attacks and Skills mod 3, powers.
RELIC_FEATURES = (MAX_POTION_SLOTS - POTION_SLOTS) * len(POTION_IDS) + len(RELIC_IDS) + len(RELIC_COUNTERS) + 2 + len(RELIC_POWERS)
# Appended last: a card prompt is open (hand, discard), and which card asked.
CHOICE_FEATURES = 2 + len(CHOICE_CARDS)
OBS_DIM = (MAX_HAND * CARD_FEATURES + PLAYER_FEATURES + PILE_FEATURES + MAX_ENEMIES * ENEMY_FEATURES + POTION_FEATURES
           + RELIC_FEATURES + CHOICE_FEATURES)
POTION_ACTION = END_TURN + 1  # potion actions come after END_TURN, so old action indices are unchanged
# Card prompts: pick hand slot i, or a discard-pile card by id. Appended after the potion block.
CHOOSE_HAND = POTION_ACTION + MAX_POTION_SLOTS * MAX_ENEMIES  # slots 3-4 extend the potion block
CHOOSE_DISCARD = CHOOSE_HAND + MAX_HAND
N_ACTIONS = CHOOSE_DISCARD + len(CARD_IDS)
# ponytail: a fight-level reward can't see that a potion saved now helps a later fight, so each use
# costs this much HP's worth (x hp_weight). Tune from run.py's potions_used / held_at_death numbers.
POTION_COST_HP = 5


def _encode_card(card: dict) -> list[float]:
    return [
        card["cost"] / 5.0,
        float(card["canPlay"]),
        float(card["type"] == "Attack"),
        float(card["type"] == "Skill"),
        float(card["type"] == "Power"),
        float(card["upgraded"]),
    ] + [float(card["id"] == cid) for cid in CARD_IDS]


HIVE_PLAYER_POWERS = {"TenderPower", "TaintedPower", "SurroundedPower", "DisintegrationPower"}
HIVE_CARDS = {"TOXIC", "FRANTIC_ESCAPE"}
OLD_MAX_ENEMIES = 4


def combat_maps() -> tuple[list[int], list[int]]:
    """(obs_map, act_map) for grow.py: where a model trained before Act 2 keeps its inputs and actions."""
    old_cards = sorted(set(CARD_IDS) - HIVE_CARDS)
    old_monsters = [m for m in MONSTER_IDS if m not in HIVE_MONSTERS]
    old_powers = [p for p in PLAYER_POWERS if p not in HIVE_PLAYER_POWERS]
    enemy = [13, (old_monsters, MONSTER_IDS), ("skip", len(ENEMY_PW))]
    obs = insert_map([6, "cards"] * MAX_HAND + [PLAYER_FEATURES - len(PLAYER_POWERS), (old_powers, PLAYER_POWERS)] + ["cards"] * 3
                     + enemy * OLD_MAX_ENEMIES + [("skip", (MAX_ENEMIES - OLD_MAX_ENEMIES) * ENEMY_FEATURES)]
                     + [POTION_FEATURES + RELIC_FEATURES + CHOICE_FEATURES], old_cards, CARD_IDS)
    slots = lambda first, n: [first + i * MAX_ENEMIES + s for i in range(n) for s in range(OLD_MAX_ENEMIES)]  # noqa: E731
    act = slots(0, MAX_HAND) + [END_TURN] + slots(POTION_ACTION, MAX_POTION_SLOTS) + list(range(CHOOSE_HAND, CHOOSE_HAND + MAX_HAND))
    act += [CHOOSE_DISCARD + CARD_IDS.index(c) for c in old_cards]
    return obs, act


def random_deck(rng: np.random.Generator, prompt_practice: bool = False) -> list[str]:
    """Starter deck minus 0-3 Strikes/Defends, plus 0-8 random Ironclad cards (with replacement) —
    roughly the decks an Act 1 run sees. Rarity 60/30/10%: Rares oversampled vs. the ~3% of offers
    so the policy learns to play them."""
    deck = starter_deck()
    for _ in range(rng.integers(0, 4)):
        deck.remove(rng.choice([c for c in deck if c != "BASH"]))
    pools = [COMMONS, UNCOMMONS, RARES]
    deck += [str(rng.choice(pools[rng.choice(3, p=[0.6, 0.3, 0.1])])) for _ in range(rng.integers(0, 9))]
    if prompt_practice and rng.random() < 0.5:  # the prompt cards are rare in offers, so seed them in
        deck.append(str(rng.choice(CHOICE_CARDS)))
        if rng.random() < 0.5:  # Wounds give Burning Pact and Brand something worth exhausting
            deck += ["WOUND"] * int(rng.integers(1, 3))
    return deck


def random_potions(rng: np.random.Generator, slots: int = POTION_SLOTS) -> list[str]:
    """0-slots random modeled potions, for random-deck training (so every potion gets practice)."""
    return [str(rng.choice(POTION_IDS)) for _ in range(rng.integers(0, slots + 1))]


def random_relics(rng: np.random.Generator) -> tuple[set[str], dict[str, int]]:
    """0-6 random modeled relics with random carried counters, so timing relics get practice at every count."""
    held = {str(r) for r in rng.choice(RELIC_IDS, rng.integers(0, 7), replace=False)}
    owner = {"lizard_used": "LIZARD_TAIL", "tea_set": "VENERABLE_TEA_SET"}
    return held, {k: int(rng.integers(0, max(n, 2))) for k, n in RELIC_COUNTERS
                  if owner.get(k, k.upper()) in held}

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
        _power(player, "WeakPower") / 5.0,
        float(_power(player, "RingingPower") != 0),
        combat.get("cardsPlayedThisTurn", 0) / 10.0,
        combat.get("round", 0) / 20.0,
    ] + [min(_power(player, name), 25) / 5.0 for name in PLAYER_POWERS]
    pile_feats = [sum(c["id"] == cid for c in player.get(pile) or []) / 5.0
                  for pile in ("drawPile", "discardPile", "exhaustPile") for cid in CARD_IDS]

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
                _power(e, "PlowPower") / 100.0,
                _power(e, "WeakPower") / 5.0,
                _power(e, "ManglePower") / 10.0,
                1.0,
            ] + [float(e.get("modelId") == mid) for mid in MONSTER_IDS] + [min(_power(e, name), 25) / 5.0 for name in ENEMY_PW]
        else:
            enemy_feats += [0.0] * ENEMY_FEATURES

    slots = combat.get("potionSlots") or []
    potion_feats = [float(i < len(slots) and slots[i] == pid) for i in range(POTION_SLOTS) for pid in POTION_IDS]
    potion_feats += [_power(player, "DexterityPower") / 5.0, _power(player, "SpeedPotionPower") / 5.0]

    held = set(combat.get("simRelics") or [])
    ctr = combat.get("relicCounters") or {}
    relic_feats = [float(i < len(slots) and slots[i] == pid) for i in range(POTION_SLOTS, MAX_POTION_SLOTS) for pid in POTION_IDS]
    relic_feats += [float(r in held) for r in RELIC_IDS]
    relic_feats += [ctr.get(k, 0) / n for k, n in RELIC_COUNTERS]
    relic_feats += [ctr.get("attacks", 0) % 3 / 3.0, ctr.get("skills", 0) % 3 / 3.0]
    relic_feats += [_power(player, name) / n for name, n in RELIC_POWERS]

    choice = combat.get("choice") or {}
    choice_feats = [float(choice.get("kind") == "hand"), float(choice.get("kind") == "discard")]
    choice_feats += [float(choice.get("source") == cid) for cid in CHOICE_CARDS]

    return np.array(hand_feats + player_feats + pile_feats + enemy_feats + potion_feats + relic_feats + choice_feats,
                    dtype=np.float32)


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
        prompt_practice: bool = False,  # random decks include the card-prompt cards (training only)
        heal: bool = True,  # False: HP carries over from the previous fight (multi-fight runs)
        hp_weight: float = 1.0,  # HP lost costs hp_weight x what dealing that much damage earns
    ):
        super().__init__()
        self.encounters = [encounter] if isinstance(encounter, str) else list(encounter)
        self.client = client or AutoSpireClient()
        self.random_decks = random_decks
        self.prompt_practice = prompt_practice
        self.heal = heal
        self.hp_weight = hp_weight
        self.deck: list[str] | None = None  # fixed deck (e.g. a run's), overriding random/starter
        self.relics: set[str] | None = None  # fixed starting relics (a run's), overriding random
        self.relic_state: dict | None = None
        self.potions: list[str | None] | None = None  # fixed starting potions (a run's), overriding random
        self.action_space = spaces.Discrete(N_ACTIONS)
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
                set_relics = getattr(self.client, "set_relics", None)  # sim only; before set_potions (Potion Belt)
                deck = self.deck or (random_deck(self.np_random, self.prompt_practice) if self.random_decks else starter_deck())
                if not set_relics and not self.deck:  # the live mod can't answer a card prompt
                    deck = [c for c in deck if c not in CHOICE_CARDS]
                self.client.set_deck(deck)
                relics, state = (self.relics, self.relic_state) if self.relics is not None else (
                    random_relics(self.np_random) if self.random_decks else (set(), {}))
                if set_relics:
                    set_relics(relics, state if state is not None else {})
                set_potions = getattr(self.client, "set_potions", None)  # sim only
                if set_potions:
                    set_potions(self.potions if self.potions is not None else
                                random_potions(self.np_random, MAX_POTION_SLOTS if "POTION_BELT" in relics else POTION_SLOTS)
                                if self.random_decks else [])
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

            used_potion = False
            if action >= CHOOSE_DISCARD:
                result = self.client.exec(f"choose_discard {CARD_IDS[int(action) - CHOOSE_DISCARD]}")
            elif action >= CHOOSE_HAND:
                result = self.client.exec(f"choose {int(action) - CHOOSE_HAND}")
            elif action < END_TURN:
                card, slot = divmod(int(action), MAX_ENEMIES)
                hand = (prev.get("player") or {}).get("hand") or []
                enemies = _living(prev)
                if card < len(hand) and hand[card]["targetType"] == "AnyEnemy" and slot < len(enemies):
                    result = self.client.play(card, enemies[slot]["combatId"])
                elif slot == 0:
                    result = self.client.play(card)
                else:  # slot on a non-targeted card, or no enemy in that slot
                    result = {"error": "invalid_target"}
            elif action == END_TURN:
                result = self.client.end_turn()
            else:
                pslot, slot = divmod(int(action) - POTION_ACTION, MAX_ENEMIES)
                potions = prev.get("potionSlots") or []
                pid = potions[pslot] if pslot < len(potions) else None
                enemies = _living(prev)
                if POTIONS.get(pid) == "enemy" and slot < len(enemies):
                    result = self.client.exec(f"potion {pslot} {enemies[slot]['combatId']}")
                elif pid in POTIONS and POTIONS[pid] != "enemy" and slot == 0:
                    result = self.client.exec(f"potion {pslot}")
                else:
                    result = {"error": "invalid_potion"}
                used_potion = "error" not in result
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
        except (requests.RequestException, TimeoutError, SimLoopError) as exc:
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

        reward = (prev_enemy_hp - enemy_hp) / 10.0 - self.hp_weight * (prev_player_hp - player_hp) / 10.0
        if invalid:
            reward -= 0.1
        if used_potion:
            reward -= POTION_COST_HP * self.hp_weight / 10.0
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
        mask = np.zeros(N_ACTIONS, dtype=bool)
        choice = self._combat.get("choice")
        if choice:  # a card prompt is open: only its answers are legal
            if choice["kind"] == "hand":
                mask[CHOOSE_HAND:CHOOSE_HAND + min(len(hand), MAX_HAND)] = True
            else:
                for c in (self._combat.get("player") or {}).get("discardPile") or []:
                    if c["id"] in CARD_IDS:  # the live game can hold cards the sim doesn't have
                        mask[CHOOSE_DISCARD + CARD_IDS.index(c["id"])] = True
            return mask
        for i, c in enumerate(hand[:MAX_HAND]):
            # Armaments can't be played (the sim has no upgrades). The other prompt cards need a client that
            # answers prompts: the sim and the mod report simRelics, older clients don't.
            if c["canPlay"] and c["id"] in CARDS and (c["id"] not in CHOICE_CARDS or "simRelics" in self._combat):
                slots = n_enemies if c["targetType"] == "AnyEnemy" else 1
                mask[i * MAX_ENEMIES:i * MAX_ENEMIES + max(slots, 1)] = True
        for i, pid in enumerate((self._combat.get("potionSlots") or [])[:MAX_POTION_SLOTS]):
            if pid in POTIONS:  # unmodeled potions and live play (no potionSlots) stay masked
                slots = n_enemies if POTIONS[pid] == "enemy" else 1
                mask[POTION_ACTION + i * MAX_ENEMIES:POTION_ACTION + i * MAX_ENEMIES + slots] = True
        mask[END_TURN] = True
        return mask
