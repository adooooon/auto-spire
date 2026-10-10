"""Pure-Python combat simulator: Ironclad's starter deck vs. Act 1 (Overgrowth)
weak and normal encounters — see ENCOUNTERS.

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
rewards mid-episode, Act 1 fights only):
  - No relics, potions, or player powers other than Shrink, Vulnerable, Frail.
  - Enemy-targeted cards hit the enemy with the given combatId, or the first
    living enemy if none is given (the mod's auto-target,
    combatState.HittableEnemies.FirstOrDefault()).
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
    hits: int = 1  # MultiAttackIntent hit count (each hit is reduced by block separately)
    vulnerable: int = 0  # Vulnerable applied to the player
    frail: int = 0  # Frail applied to the player


# A RandomBranchState: equal-weight choice among (move, max consecutive uses[, cooldown]).
# Weight is 0 if the last `max` logged moves were all this move — that's the
# CannotRepeat (max=1) / CanRepeatXTimes rule in RandomBranchState.GetStateWeight —
# or, for max=ONCE (UseOnlyOnce), if it was ever used; and also 0 if it is among the
# last `cooldown` moves. Careful: AddBranch(state, int, MoveRepeatType) takes a
# *cooldown*, not a weight.
Branch = tuple[tuple, ...]
ONCE = 0


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
_MAWLER_RAND: Branch = (("RIP_AND_TEAR_MOVE", 1), ("ROAR_MOVE", ONCE), ("CLAW_MOVE", 1))
_FLYCONID_RAND: Branch = (("VULNERABLE_SPORES_MOVE", 1, 3), ("FRAIL_SPORES_MOVE", 1, 2), ("SMASH_MOVE", 1))

MONSTERS: dict[str, MonsterDef] = {m.model_id: m for m in [
    # Nibbit.cs — alone (NibbitsWeak) it opens with BUTT; NibbitsNormal overrides the opener per slot.
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
    MonsterDef("MAWLER", "Mawler", (72, 72), {
        "RIP_AND_TEAR_MOVE": Move("Attack", damage=14),
        "ROAR_MOVE": Move("Debuff", vulnerable=3),
        "CLAW_MOVE": Move("Attack", damage=4, hits=2),
    }, "CLAW_MOVE", dict.fromkeys(("RIP_AND_TEAR_MOVE", "ROAR_MOVE", "CLAW_MOVE"), _MAWLER_RAND)),
    MonsterDef("FLYCONID", "Flyconid", (47, 49), {
        "VULNERABLE_SPORES_MOVE": Move("Debuff", vulnerable=2),
        "FRAIL_SPORES_MOVE": Move("Attack", damage=8, frail=2),
        "SMASH_MOVE": Move("Attack", damage=11),
    }, (("FRAIL_SPORES_MOVE", 1, 2), ("SMASH_MOVE", 1)),
        dict.fromkeys(("VULNERABLE_SPORES_MOVE", "FRAIL_SPORES_MOVE", "SMASH_MOVE"), _FLYCONID_RAND)),
    # Ruby Raiders (RubyRaidersNormal.cs picks 3 distinct of these 5).
    MonsterDef("ASSASSIN_RUBY_RAIDER", "Assassin Raider", (18, 23), {
        "KILLSHOT_MOVE": Move("Attack", damage=10),
    }, "KILLSHOT_MOVE", {"KILLSHOT_MOVE": "KILLSHOT_MOVE"}),
    MonsterDef("AXE_RUBY_RAIDER", "Axe Raider", (20, 22), {
        "SWING_1": Move("Attack", damage=5, block=5),
        "SWING_2": Move("Attack", damage=5, block=5),
        "BIG_SWING": Move("Attack", damage=12),
    }, "SWING_1", {"SWING_1": "SWING_2", "SWING_2": "BIG_SWING", "BIG_SWING": "SWING_1"}),
    MonsterDef("BRUTE_RUBY_RAIDER", "Brute Raider", (30, 33), {
        "BEAT_MOVE": Move("Attack", damage=7),
        "ROAR_MOVE": Move("Buff", strength=3),
    }, "BEAT_MOVE", {"BEAT_MOVE": "ROAR_MOVE", "ROAR_MOVE": "BEAT_MOVE"}),
    MonsterDef("CROSSBOW_RUBY_RAIDER", "Crossbow Raider", (18, 21), {
        "FIRE_MOVE": Move("Attack", damage=14),
        "RELOAD_MOVE": Move("Defend", block=3),
    }, "RELOAD_MOVE", {"RELOAD_MOVE": "FIRE_MOVE", "FIRE_MOVE": "RELOAD_MOVE"}),
    MonsterDef("TRACKER_RUBY_RAIDER", "Tracker Raider", (21, 25), {
        "TRACK_MOVE": Move("Debuff", frail=2),
        "HOUNDS_MOVE": Move("Attack", damage=1, hits=8),
    }, "TRACK_MOVE", {"TRACK_MOVE": "HOUNDS_MOVE", "HOUNDS_MOVE": "HOUNDS_MOVE"}),
]}
RUBY_RAIDERS = ("AXE_RUBY_RAIDER", "ASSASSIN_RUBY_RAIDER", "BRUTE_RUBY_RAIDER", "CROSSBOW_RUBY_RAIDER", "TRACKER_RUBY_RAIDER")


def encounter_roster(encounter: str, rng: random.Random) -> list[str]:
    """Monster ids in slot order; "ID:MOVE" overrides the opening move."""
    small = rng.sample(["LEAF_SLIME_S", "TWIG_SLIME_S"], 2)
    if encounter == "SLIMES_WEAK":  # SlimesWeak.cs: small, medium, the *other* small
        return [small[0], rng.choice(["LEAF_SLIME_M", "TWIG_SLIME_M"]), small[1]]
    rosters = {
        "NIBBITS_WEAK": ["NIBBIT"],
        "SHRINKER_BEETLE_WEAK": ["SHRINKER_BEETLE"],
        "FUZZY_WURM_CRAWLER_WEAK": ["FUZZY_WURM_CRAWLER"],
        # NibbitsNormal.cs: front opens SLICE, back opens HISS (Nibbit's not-alone branch).
        "NIBBITS_NORMAL": ["NIBBIT:SLICE_MOVE", "NIBBIT:HISS_MOVE"],
        "SLIMES_NORMAL": ["TWIG_SLIME_M", "LEAF_SLIME_M", *small],
        "OVERGROWTH_CRAWLERS": ["SHRINKER_BEETLE", "FUZZY_WURM_CRAWLER"],
        "MAWLER_NORMAL": ["MAWLER"],
        "FLYCONID_NORMAL": [rng.choice(["LEAF_SLIME_M", "TWIG_SLIME_M"]), "FLYCONID"],
        "RUBY_RAIDERS_NORMAL": rng.sample(RUBY_RAIDERS, 3),
    }
    if encounter not in rosters:
        raise ValueError(f"sim does not model encounter {encounter!r} (only {ENCOUNTERS})")
    return rosters[encounter]


ENCOUNTERS = ("NIBBITS_WEAK", "SLIMES_WEAK", "SHRINKER_BEETLE_WEAK", "FUZZY_WURM_CRAWLER_WEAK",
              "NIBBITS_NORMAL", "SLIMES_NORMAL", "OVERGROWTH_CRAWLERS",
              "MAWLER_NORMAL", "FLYCONID_NORMAL", "RUBY_RAIDERS_NORMAL")


def legal_moves(spec: str | Branch, log: list[str]) -> list[str]:
    """Moves a branch can pick next, in branch order (RandomBranchState.GetStateWeight)."""
    if isinstance(spec, str):
        return [spec]

    def ok(m: str, n: int, cooldown: int = 0) -> bool:
        if cooldown and m in log[-cooldown:]:
            return False
        if n == ONCE:
            return m not in log
        return not (len(log) >= n and all(x == m for x in log[-n:]))

    # GetNextState: with total weight 0, NextFloat(0) = 0 and the loop returns the first branch.
    return [b[0] for b in spec if ok(*b)] or [spec[0][0]]


def pick_move(spec: str | Branch, log: list[str], rng: random.Random) -> str:
    return rng.choice(legal_moves(spec, log))


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
    vulnerable: int = 0  # player's: monster attacks x1.5
    frail: int = 0  # player's: card block x0.75
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
        for entry in encounter_roster(encounter, self.rng):
            model_id, _, first = entry.partition(":")
            d = MONSTERS[model_id]
            hp = self.rng.randint(*d.hp)
            self.enemies.append(_Enemy(d, hp, hp, first or pick_move(d.first, [], self.rng)))
        self.draw_pile = starter_deck()
        self.rng.shuffle(self.draw_pile)
        self.hand, self.discard_pile, self.exhaust_pile = [], [], []
        self.player_block = 0
        self.shrunk = False
        self.vulnerable = self.frail = 0
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

    def play_card(self, hand_index: int, target_id: int | None = None) -> dict:
        if not self.in_combat or not self.is_play_phase:
            return {"error": "not_play_phase"}
        if hand_index < 0 or hand_index >= len(self.hand):
            return {"error": "invalid_card_index", "max": len(self.hand) - 1}
        card_id = self.hand[hand_index]
        card = STARTER_CARDS[card_id]
        if card.cost > self.energy:
            return {"error": "card_not_playable", "card": card_id}
        if target_id is None:
            target = next((e for e in self.enemies if e.is_alive), None)
        else:  # combatId = index + 1, see _enemy_dict
            target = self.enemies[target_id - 1] if 0 < target_id <= len(self.enemies) else None
            if target is None or not target.is_alive:
                return {"error": "invalid_target", "targetId": target_id}

        self.energy -= card.cost
        self.hand.pop(hand_index)

        if card.damage and target:
            dmg = player_attack_damage(card.damage, target.vulnerable > 0, self.shrunk)
            absorbed = min(target.block, dmg)
            target.block -= absorbed
            target.hp = max(0, target.hp - (dmg - absorbed))
            # ShrinkPower.AfterDeath: Shrink goes away when its applier dies.
            # ponytail: assumes one Shrink source per fight (true for all Act 1 rosters).
            if not target.is_alive and any(m.shrink for m in target.defn.moves.values()):
                self.shrunk = False
        if card.vulnerable and target and target.is_alive:
            target.vulnerable += card.vulnerable
        if card.block:
            self.player_block += card.block * 3 // 4 if self.frail else card.block
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
        # PowerCmd.Apply: a debuff newly applied to the player skips its next tick-down,
        # so it survives the end of the enemy turn that applied it.
        fresh = set()
        for e in alive:
            mv = e.defn.moves[e.move]
            for _ in range(mv.hits if mv.damage else 0):
                self._damage_player(self.monster_hit_damage(mv.damage + e.strength))
                if not self.in_combat:
                    return
            e.block += mv.block
            e.strength += mv.strength
            self.shrunk |= mv.shrink
            self.discard_pile += ["SLIMED"] * mv.slimed
            for name in ("vulnerable", "frail"):
                if getattr(mv, name):
                    if not getattr(self, name):
                        fresh.add(name)
                    setattr(self, name, getattr(self, name) + getattr(mv, name))
            e.log.append(e.move)
            e.move = pick_move(e.defn.follow[e.move], e.log, self.rng)

        for e in alive:
            e.vulnerable = max(0, e.vulnerable - 1)  # ticks down after the enemy's turn ends
        for name in ("vulnerable", "frail"):  # the player's tick at the same point
            if name not in fresh:
                setattr(self, name, max(0, getattr(self, name) - 1))
        self.round += 1
        self._start_player_turn()

    def monster_hit_damage(self, base: int) -> int:
        return base * 3 // 2 if self.vulnerable else base

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
        hit = self.monster_hit_damage(mv.damage + e.strength)
        intents = (
            [{"type": "Attack", "className": "MultiAttackIntent" if mv.hits > 1 else "SingleAttackIntent",
              "damage": hit, "hits": mv.hits, "totalDamage": hit * mv.hits}]
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
                "powers": [{"id": n.upper(), "name": n, "type": "Debuff", "amount": a} for n, a in (
                    ("ShrinkPower", -1 if self.shrunk else 0), ("VulnerablePower", self.vulnerable),
                    ("FrailPower", self.frail)) if a],
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
        return {"phase": "combat" if self._combat.in_combat else "map", "inRun": True,
                "player": {"hp": self._combat.player_hp}}

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
            return self._combat.play_card(int(parts[1]), int(parts[2]) if len(parts) > 2 else None)
        if verb == "end":
            return self._combat.end_turn()
        return {"error": "unknown_command", "cmd": cmd}

    def play(self, hand_index: int, target_id: int | None = None) -> dict:
        return self._combat.play_card(hand_index, target_id)

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
