"""Pure-Python combat simulator: Ironclad's starter deck vs. Act 1 (Overgrowth)
weak encounters — NIBBITS_WEAK, SLIMES_WEAK, SHRINKER_BEETLE_WEAK,
FUZZY_WURM_CRAWLER_WEAK.

Ported directly from decompiled game source rather than guessed at (ascension
0 values): monsters from decompiled/MegaCrit.Sts2.Core.Models.Monsters/, encounter
rosters from .../Models.Encounters/, move selection from
.../MonsterMoves.MonsterMoveStateMachine/RandomBranchState.cs. Exposes the same
interface AutoSpireClient does (state/combat/exec/play/end_turn/wait_for/
full_restart/ping) so STS2CombatEnv works unmodified with either backend.

Damage: the game keeps damage as a decimal through all modifiers
(Hook.ModifyDamage), then block absorbs min(block, dmg) and HP loss is
truncated to int (Creature.LoseHpInternal) — for non-negative damage vs.
integer block that equals flooring first, which is what we do (in exact
integer math, so 0.7 * 1.5 products don't hit float error).

Known simplifications (acceptable for this scope — starter deck only, no card
rewards mid-episode, Act 1 weak fights only):
  - No relics, potions, or player powers other than Shrink.
  - Enemy-targeted cards hit the first living enemy, matching the mod's
    auto-target (combatState.HittableEnemies.FirstOrDefault()).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .cards import STARTER_CARDS, card_to_dict, starter_deck

PLAYER_MAX_HP = 80
PLAYER_MAX_ENERGY = 3
HAND_DRAW_COUNT = 5


@dataclass(frozen=True)
class Move:
    intent: str  # "Attack" | "Buff" | "Debuff" | "Status" — env only reads "Attack"
    damage: int = 0
    block: int = 0  # gained by the monster, after its attack
    strength: int = 0  # gained by the monster
    shrink: bool = False  # applies infinite Shrink to the player (ShrinkPower.cs: -30% attack damage)
    slimed: int = 0  # Slimed status cards added to the player's discard pile


# A RandomBranchState: equal-weight choice among (move, max consecutive uses).
# Weight is 0 if the last `max` logged moves were all this move — that's the
# CannotRepeat (max=1) / CanRepeatXTimes rule in RandomBranchState.GetStateWeight.
Branch = tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class MonsterDef:
    model_id: str
    name: str
    hp: tuple[int, int]  # inclusive (Creature.cs rolls MaxInitialHp + 1 exclusive)
    moves: dict[str, Move]
    first: str | Branch
    follow: dict[str, str | Branch]


_LEAF_S_RAND: Branch = (("TACKLE_MOVE", 1), ("GOOP_MOVE", 1))
_TWIG_M_RAND: Branch = (("POKEY_POUNCE_MOVE", 2), ("STICKY_SHOT_MOVE", 1))

MONSTERS: dict[str, MonsterDef] = {m.model_id: m for m in [
    # Nibbit.cs — always alone in NibbitsWeak, so the fixed (not-alone-branch) cycle.
    MonsterDef("NIBBIT", "Nibbit", (42, 46), {
        "BUTT_MOVE": Move("Attack", damage=12),
        "SLICE_MOVE": Move("Attack", damage=6, block=5),
        "HISS_MOVE": Move("Buff", strength=2),
    }, "BUTT_MOVE", {"BUTT_MOVE": "SLICE_MOVE", "SLICE_MOVE": "HISS_MOVE", "HISS_MOVE": "BUTT_MOVE"}),
    MonsterDef("SHRINKER_BEETLE", "Shrinker Beetle", (38, 40), {
        "SHRINKER_MOVE": Move("Debuff", shrink=True),
        "CHOMP_MOVE": Move("Attack", damage=7),
        "STOMP_MOVE": Move("Attack", damage=13),
    }, "SHRINKER_MOVE", {"SHRINKER_MOVE": "CHOMP_MOVE", "CHOMP_MOVE": "STOMP_MOVE", "STOMP_MOVE": "CHOMP_MOVE"}),
    MonsterDef("FUZZY_WURM_CRAWLER", "Fuzzy Wurm Crawler", (55, 57), {
        "FIRST_ACID_GOOP": Move("Attack", damage=4),
        "INHALE": Move("Buff", strength=7),
        "ACID_GOOP": Move("Attack", damage=4),
    }, "FIRST_ACID_GOOP", {"FIRST_ACID_GOOP": "INHALE", "INHALE": "ACID_GOOP", "ACID_GOOP": "FIRST_ACID_GOOP"}),
    MonsterDef("LEAF_SLIME_S", "Leaf Slime (S)", (11, 15), {
        "TACKLE_MOVE": Move("Attack", damage=3),
        "GOOP_MOVE": Move("Status", slimed=1),
    }, _LEAF_S_RAND, {"TACKLE_MOVE": _LEAF_S_RAND, "GOOP_MOVE": _LEAF_S_RAND}),
    MonsterDef("TWIG_SLIME_S", "Twig Slime (S)", (7, 11), {
        "TACKLE_MOVE": Move("Attack", damage=4),
    }, "TACKLE_MOVE", {"TACKLE_MOVE": "TACKLE_MOVE"}),
    MonsterDef("LEAF_SLIME_M", "Leaf Slime (M)", (32, 35), {
        "CLUMP_SHOT": Move("Attack", damage=8),
        "STICKY_SHOT": Move("Status", slimed=2),
    }, "STICKY_SHOT", {"STICKY_SHOT": "CLUMP_SHOT", "CLUMP_SHOT": "STICKY_SHOT"}),
    MonsterDef("TWIG_SLIME_M", "Twig Slime (M)", (26, 28), {
        "POKEY_POUNCE_MOVE": Move("Attack", damage=11),
        "STICKY_SHOT_MOVE": Move("Status", slimed=1),
    }, "STICKY_SHOT_MOVE", {"POKEY_POUNCE_MOVE": _TWIG_M_RAND, "STICKY_SHOT_MOVE": _TWIG_M_RAND}),
]}


def encounter_roster(encounter: str, rng: random.Random) -> list[str]:
    if encounter == "SLIMES_WEAK":  # SlimesWeak.cs: small, medium, the *other* small
        small = rng.sample(["LEAF_SLIME_S", "TWIG_SLIME_S"], 2)
        return [small[0], rng.choice(["LEAF_SLIME_M", "TWIG_SLIME_M"]), small[1]]
    rosters = {
        "NIBBITS_WEAK": ["NIBBIT"],
        "SHRINKER_BEETLE_WEAK": ["SHRINKER_BEETLE"],
        "FUZZY_WURM_CRAWLER_WEAK": ["FUZZY_WURM_CRAWLER"],
    }
    if encounter not in rosters:
        raise ValueError(f"sim does not model encounter {encounter!r} (only {ENCOUNTERS})")
    return rosters[encounter]


ENCOUNTERS = ("NIBBITS_WEAK", "SLIMES_WEAK", "SHRINKER_BEETLE_WEAK", "FUZZY_WURM_CRAWLER_WEAK")


def pick_move(spec: str | Branch, log: list[str], rng: random.Random) -> str:
    if isinstance(spec, str):
        return spec
    moves = [m for m, _ in spec]
    weights = [0 if len(log) >= n and all(x == m for x in log[-n:]) else 1 for m, n in spec]
    return rng.choices(moves, weights)[0]


def player_attack_damage(base: int, target_vulnerable: bool, shrunk: bool) -> int:
    """floor(base * 1.5[Vulnerable] * 0.7[Shrink]) in exact integer math."""
    return base * (3 if target_vulnerable else 2) * (7 if shrunk else 10) // 20


@dataclass
class _Enemy:
    defn: MonsterDef
    hp: int
    max_hp: int
    move: str  # upcoming move (its intent is what the player sees)
    block: int = 0
    strength: int = 0
    vulnerable: int = 0
    log: list[str] = field(default_factory=list)  # performed moves, for RandomBranchState repeat rules

    @property
    def is_alive(self) -> bool:
        return self.hp > 0


@dataclass
class SimCombat:
    player_hp: int = PLAYER_MAX_HP
    player_max_hp: int = PLAYER_MAX_HP
    player_block: int = 0
    shrunk: bool = False
    energy: int = 0
    round: int = 1
    in_combat: bool = False
    is_play_phase: bool = False
    won: bool | None = None
    hand: list[str] = field(default_factory=list)
    draw_pile: list[str] = field(default_factory=list)
    discard_pile: list[str] = field(default_factory=list)
    exhaust_pile: list[str] = field(default_factory=list)
    enemies: list[_Enemy] = field(default_factory=list)
    rng: random.Random = field(default_factory=random.Random)

    def heal(self, amount: int) -> None:
        self.player_hp = min(self.player_max_hp, self.player_hp + amount)

    def fight(self, encounter: str) -> None:
        self.enemies = []
        for model_id in encounter_roster(encounter, self.rng):
            d = MONSTERS[model_id]
            hp = self.rng.randint(*d.hp)
            self.enemies.append(_Enemy(d, hp, hp, pick_move(d.first, [], self.rng)))
        self.draw_pile = starter_deck()
        self.rng.shuffle(self.draw_pile)
        self.hand, self.discard_pile, self.exhaust_pile = [], [], []
        self.player_block = 0
        self.shrunk = False
        self.round = 1
        self.in_combat = True
        self.won = None
        self._start_player_turn()

    def _draw(self, count: int) -> None:
        for _ in range(count):
            if not self.draw_pile:
                if not self.discard_pile:
                    return
                self.draw_pile = self.discard_pile
                self.discard_pile = []
                self.rng.shuffle(self.draw_pile)
            self.hand.append(self.draw_pile.pop())

    def _start_player_turn(self) -> None:
        self.player_block = 0  # block clears at the start of your own turn, not the enemy's
        self.energy = PLAYER_MAX_ENERGY
        self._draw(HAND_DRAW_COUNT)
        self.is_play_phase = True

    def play_card(self, hand_index: int) -> dict:
        if not self.in_combat or not self.is_play_phase:
            return {"error": "not_play_phase"}
        if hand_index < 0 or hand_index >= len(self.hand):
            return {"error": "invalid_card_index", "max": len(self.hand) - 1}
        card_id = self.hand[hand_index]
        card = STARTER_CARDS[card_id]
        if card.cost > self.energy:
            return {"error": "card_not_playable", "card": card_id}

        self.energy -= card.cost
        self.hand.pop(hand_index)

        target = next((e for e in self.enemies if e.is_alive), None)
        if card.damage and target:
            dmg = player_attack_damage(card.damage, target.vulnerable > 0, self.shrunk)
            absorbed = min(target.block, dmg)
            target.block -= absorbed
            target.hp = max(0, target.hp - (dmg - absorbed))
        if card.vulnerable and target and target.is_alive:
            target.vulnerable += card.vulnerable
        if card.block:
            self.player_block += card.block
        if card.draw:
            self._draw(card.draw)
        (self.exhaust_pile if card.exhaust else self.discard_pile).append(card_id)

        if not any(e.is_alive for e in self.enemies):
            self._end_combat(won=True)
        return {"ok": True, "played": card.title, "index": hand_index}

    def end_turn(self) -> dict:
        if not self.in_combat or not self.is_play_phase:
            return {"error": "not_play_phase"}
        self.discard_pile.extend(self.hand)
        self.hand = []
        self.is_play_phase = False
        self._run_enemy_turn()
        return {"ok": True}

    def _run_enemy_turn(self) -> None:
        alive = [e for e in self.enemies if e.is_alive]
        for e in alive:
            e.block = 0  # block clears at the start of the enemy's own turn
        for e in alive:
            mv = e.defn.moves[e.move]
            if mv.damage:
                self._damage_player(mv.damage + e.strength)
                if not self.in_combat:
                    return
            e.block += mv.block
            e.strength += mv.strength
            self.shrunk |= mv.shrink
            self.discard_pile += ["SLIMED"] * mv.slimed
            e.log.append(e.move)
            e.move = pick_move(e.defn.follow[e.move], e.log, self.rng)

        for e in alive:
            e.vulnerable = max(0, e.vulnerable - 1)  # ticks down after the enemy's turn ends
        self.round += 1
        self._start_player_turn()

    def _damage_player(self, dmg: int) -> None:
        absorbed = min(self.player_block, dmg)
        self.player_block -= absorbed
        self.player_hp -= dmg - absorbed
        if self.player_hp <= 0:
            self.player_hp = 0
            self._end_combat(won=False)

    def _end_combat(self, won: bool) -> None:
        self.in_combat = False
        self.is_play_phase = False
        self.won = won

    def _enemy_dict(self, i: int, e: _Enemy) -> dict:
        mv = e.defn.moves[e.move]
        intents = (
            [{"type": "Attack", "className": "SingleAttackIntent", "damage": mv.damage + e.strength,
              "hits": 1, "totalDamage": mv.damage + e.strength}]
            if mv.damage else [{"type": mv.intent, "className": f"{mv.intent}Intent"}]
        )
        powers = []
        if e.strength:
            powers.append({"id": "STRENGTH", "name": "StrengthPower", "type": "Buff", "amount": e.strength})
        if e.vulnerable:
            powers.append({"id": "VULNERABLE", "name": "VulnerablePower", "type": "Debuff", "amount": e.vulnerable})
        return {
            "combatId": i + 1,
            "name": e.defn.name,
            "modelId": e.defn.model_id,
            "hp": e.hp,
            "maxHp": e.max_hp,
            "block": e.block,
            "isAlive": e.is_alive,
            "isStunned": False,
            "powers": powers,
            "intent": {"moveId": e.move, "intents": intents},
        }

    def combat_dict(self) -> dict:
        if not self.in_combat:
            return {"inCombat": False}
        cards = lambda pile: [card_to_dict(c, self.energy) for c in pile]  # noqa: E731
        return {
            "inCombat": True,
            "isPlayPhase": self.is_play_phase,
            "round": self.round,
            "currentSide": "Player" if self.is_play_phase else "Enemy",
            "player": {
                "hp": self.player_hp,
                "maxHp": self.player_max_hp,
                "block": self.player_block,
                "gold": 99,
                "energy": self.energy,
                "maxEnergy": PLAYER_MAX_ENERGY,
                "stars": 0,
                "hand": cards(self.hand),
                "drawPile": cards(self.draw_pile),
                "discardPile": cards(self.discard_pile),
                "exhaustPile": cards(self.exhaust_pile),
                "powers": [{"id": "SHRINK", "name": "ShrinkPower", "type": "Debuff", "amount": -1}] if self.shrunk else [],
                "relics": [],
                "potions": [],
                "deck": cards(starter_deck()),
            },
            # The live game drops dead enemies from the list (combatIds stay stable).
            "enemies": [self._enemy_dict(i, e) for i, e in enumerate(self.enemies) if e.is_alive],
        }


class SimClient:
    """AutoSpireClient-compatible interface backed by SimCombat, for use as
    STS2CombatEnv(client=SimClient()) — see docs/modding-approach.md Phase A."""

    def __init__(self, seed: int | None = None):
        self._combat = SimCombat(rng=random.Random(seed))

    def ping(self) -> bool:
        return True

    def state(self) -> dict:
        return {"phase": "combat" if self._combat.in_combat else "map", "inRun": True}

    def combat(self) -> dict:
        return self._combat.combat_dict()

    def exec(self, cmd: str, settle: float = 0.0, timeout: float | None = None, retries: int | None = None) -> dict:
        parts = cmd.split()
        verb = parts[0].lower() if parts else ""
        if verb == "heal":
            self._combat.heal(int(parts[1]) if len(parts) > 1 else 999)
            return {"ok": True}
        if verb == "fight":
            self._combat.fight(parts[1] if len(parts) > 1 else "NIBBITS_WEAK")
            return {"ok": True}
        if verb == "newrun":
            self._combat = SimCombat(rng=self._combat.rng)
            return {"ok": True}
        if verb == "play":
            return self._combat.play_card(int(parts[1]))
        if verb == "end":
            return self._combat.end_turn()
        return {"error": "unknown_command", "cmd": cmd}

    def play(self, hand_index: int) -> dict:
        return self._combat.play_card(hand_index)

    def end_turn(self) -> dict:
        return self._combat.end_turn()

    def wait_for(self, predicate, poll_interval: float = 0.0, timeout: float = 0.0) -> dict:
        # The sim resolves synchronously — nothing to poll for.
        combat = self.combat()
        if not predicate(combat):
            raise TimeoutError(f"sim state never satisfied predicate: {combat}")
        return combat

    def full_restart(self, character: str = "IRONCLAD", boot_timeout: float = 0.0) -> None:
        self._combat = SimCombat(rng=self._combat.rng)
