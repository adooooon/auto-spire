"""Pure-Python combat simulator, scoped to exactly what STS2CombatEnv trains on
today: Ironclad's starter deck vs. a solo Nibbit (the NIBBITS_WEAK encounter).

Ported directly from decompiled game source rather than guessed at — see
docs/modding-approach.md Phase A for the file-by-file mapping. Exposes the
same interface AutoSpireClient does (state/combat/exec/play/end_turn/
wait_for/full_restart/ping) so STS2CombatEnv works unmodified with either
backend: `STS2CombatEnv(client=SimClient())` vs `STS2CombatEnv(client=AutoSpireClient())`.

Known simplifications (acceptable for this scope — starter deck only, no
card rewards mid-episode, single encounter):
  - No Entangled/Unplayable/other keyword restrictions (starter deck has none).
  - Damage rounding uses floor, matching standard genre convention; the
    exact STS2 rounding rule was not independently re-derived from source.
  - No relics, potions, or player powers (none are reachable in this scope).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .cards import STARTER_CARDS, card_to_dict, starter_deck

PLAYER_MAX_HP = 80
PLAYER_MAX_ENERGY = 3
HAND_DRAW_COUNT = 5

# Nibbit (decompiled/MegaCrit.Sts2.Core.Models.Monsters/Nibbit.cs), ascension 0,
# always IsAlone=true for the NIBBITS_WEAK encounter (NibbitsWeak.cs).
NIBBIT_MIN_HP = 42
NIBBIT_MAX_HP = 46
BUTT_DAMAGE = 12
SLICE_DAMAGE = 6
SLICE_BLOCK = 5
HISS_STRENGTH_GAIN = 2
MOVE_CYCLE = ["BUTT_MOVE", "SLICE_MOVE", "HISS_MOVE"]  # fixed FollowUpState chain when alone

ENCOUNTERS = {"NIBBITS_WEAK"}


def _apply_damage(base_damage: int, attacker_strength: int, defender_vulnerable: int) -> int:
    """(base + Strength) * 1.5 if Vulnerable, floored — see VulnerablePower.cs /
    StrengthPower.cs ModifyDamageAdditive/Multiplicative."""
    dmg = base_damage + attacker_strength
    if defender_vulnerable > 0:
        dmg = dmg * 1.5
    return max(0, math.floor(dmg))


@dataclass
class _Enemy:
    hp: int
    max_hp: int
    block: int = 0
    strength: int = 0
    vulnerable: int = 0
    move_index: int = 0  # position in MOVE_CYCLE for the *upcoming* move

    @property
    def is_alive(self) -> bool:
        return self.hp > 0

    @property
    def upcoming_move(self) -> str:
        return MOVE_CYCLE[self.move_index % len(MOVE_CYCLE)]


@dataclass
class SimCombat:
    player_hp: int = PLAYER_MAX_HP
    player_max_hp: int = PLAYER_MAX_HP
    player_block: int = 0
    energy: int = 0
    round: int = 1
    in_combat: bool = False
    is_play_phase: bool = False
    won: bool | None = None
    hand: list[str] = field(default_factory=list)
    draw_pile: list[str] = field(default_factory=list)
    discard_pile: list[str] = field(default_factory=list)
    enemy: _Enemy | None = None
    rng: random.Random = field(default_factory=random.Random)

    def heal(self, amount: int) -> None:
        self.player_hp = min(self.player_max_hp, self.player_hp + amount)

    def fight(self, encounter: str) -> None:
        if encounter not in ENCOUNTERS:
            raise ValueError(f"sim does not model encounter {encounter!r} (only {ENCOUNTERS})")
        self.draw_pile = starter_deck()
        self.rng.shuffle(self.draw_pile)
        self.hand = []
        self.discard_pile = []
        self.player_block = 0
        self.round = 1
        self.in_combat = True
        self.won = None
        self.enemy = _Enemy(hp=self.rng.randint(NIBBIT_MIN_HP, NIBBIT_MAX_HP), max_hp=0)
        self.enemy.max_hp = self.enemy.hp
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
        self.discard_pile.append(card_id)

        if card.damage:
            dmg = _apply_damage(card.damage, attacker_strength=0, defender_vulnerable=self.enemy.vulnerable)
            absorbed = min(self.enemy.block, dmg)
            self.enemy.block -= absorbed
            self.enemy.hp -= dmg - absorbed
        if card.block:
            self.player_block += card.block
        if card.vulnerable:
            self.enemy.vulnerable += card.vulnerable

        if self.enemy.hp <= 0:
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
        e = self.enemy
        e.block = 0  # block clears at the start of the enemy's own turn
        move = e.upcoming_move

        if move == "BUTT_MOVE":
            self._damage_player(BUTT_DAMAGE, e.strength)
        elif move == "SLICE_MOVE":
            self._damage_player(SLICE_DAMAGE, e.strength)
            if self.in_combat:
                e.block += SLICE_BLOCK
        elif move == "HISS_MOVE":
            e.strength += HISS_STRENGTH_GAIN

        if not self.in_combat:
            return

        e.vulnerable = max(0, e.vulnerable - 1)  # ticks down after the enemy's turn ends
        e.move_index += 1
        self.round += 1
        self._start_player_turn()

    def _damage_player(self, base_damage: int, attacker_strength: int) -> None:
        dmg = _apply_damage(base_damage, attacker_strength, defender_vulnerable=0)  # player never gets Vulnerable here
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

    def combat_dict(self) -> dict:
        if not self.in_combat:
            return {"inCombat": False}
        e = self.enemy
        intent = {
            "moveId": e.upcoming_move,
            "intents": (
                [{"type": "Attack", "className": "SingleAttackIntent",
                  "damage": _apply_damage(BUTT_DAMAGE if e.upcoming_move == "BUTT_MOVE" else SLICE_DAMAGE, e.strength, 0),
                  "hits": 1,
                  "totalDamage": _apply_damage(BUTT_DAMAGE if e.upcoming_move == "BUTT_MOVE" else SLICE_DAMAGE, e.strength, 0)}]
                if e.upcoming_move in ("BUTT_MOVE", "SLICE_MOVE")
                else [{"type": "Buff", "className": "BuffIntent"}]
            ),
        }
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
                "hand": [card_to_dict(c, self.energy) for c in self.hand],
                "drawPile": [card_to_dict(c, self.energy) for c in self.draw_pile],
                "discardPile": [card_to_dict(c, self.energy) for c in self.discard_pile],
                "exhaustPile": [],
                "powers": [],
                "relics": [],
                "potions": [],
                "deck": [card_to_dict(c, self.energy) for c in starter_deck()],
            },
            "enemies": [{
                "combatId": 1,
                "name": "Nibbit",
                "modelId": "NIBBIT",
                "hp": e.hp,
                "maxHp": e.max_hp,
                "block": e.block,
                "isAlive": e.is_alive,
                "isStunned": False,
                "powers": ([{"id": "STRENGTH", "name": "StrengthPower", "type": "Buff", "amount": e.strength}] if e.strength else [])
                + ([{"id": "VULNERABLE", "name": "VulnerablePower", "type": "Debuff", "amount": e.vulnerable}] if e.vulnerable else []),
                "intent": intent,
            }],
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
