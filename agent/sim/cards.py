"""Card definitions ported from the game's decompiled source.

Sources (see ../../decompiled/MegaCrit.Sts2.Core.Models.Cards/):
  StrikeIronclad.cs, DefendIronclad.cs, Bash.cs, Slimed.cs, Dazed.cs
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CardDef:
    id: str
    title: str
    type: str  # "Attack" | "Skill" | "Status"
    cost: int  # -1 = Unplayable
    target_type: str  # "AnyEnemy" | "Self" | "None"
    damage: int = 0
    block: int = 0
    vulnerable: int = 0  # stacks applied to target on hit
    draw: int = 0
    exhaust: bool = False
    ethereal: bool = False  # exhausted if still in hand at end of turn


STARTER_CARDS: dict[str, CardDef] = {
    "STRIKE_IRONCLAD": CardDef("STRIKE_IRONCLAD", "Strike", "Attack", 1, "AnyEnemy", damage=6),
    "DEFEND_IRONCLAD": CardDef("DEFEND_IRONCLAD", "Defend", "Skill", 1, "Self", block=5),
    "BASH": CardDef("BASH", "Bash", "Attack", 2, "AnyEnemy", damage=8, vulnerable=2),
    # Status card slimes shuffle into the discard pile: 1 energy, draw 1, Exhaust.
    "SLIMED": CardDef("SLIMED", "Slimed", "Status", 1, "None", draw=1, exhaust=True),
    # Status card Eye With Teeth shuffles into the discard pile: Unplayable, Ethereal.
    "DAZED": CardDef("DAZED", "Dazed", "Status", -1, "None", ethereal=True),
}


def starter_deck() -> list[str]:
    """5x Strike, 4x Defend, 1x Bash — the Ironclad's starting deck."""
    return ["STRIKE_IRONCLAD"] * 5 + ["DEFEND_IRONCLAD"] * 4 + ["BASH"]


def card_cost(card_id: str, tangled: int = 0) -> int:
    """Energy cost with modifiers: Tangled adds its amount to Attack cards (TangledPower.cs)."""
    c = STARTER_CARDS[card_id]
    return c.cost + tangled if c.type == "Attack" else c.cost


def card_to_dict(card_id: str, energy: int, tangled: int = 0) -> dict:
    c = STARTER_CARDS[card_id]
    cost = card_cost(card_id, tangled)
    return {
        "id": c.id,
        "name": c.title.replace(" ", "") + ("Ironclad" if c.id.endswith("IRONCLAD") else ""),
        "title": c.title,
        "type": c.type,
        "rarity": "Status" if c.type == "Status" else "Basic",
        "cost": cost,
        "canPlay": 0 <= cost <= energy,
        "targetType": c.target_type,
        "upgraded": False,
        "upgradeLevel": 0,
        "keywords": ["Exhaust"] * c.exhaust + ["Ethereal", "Unplayable"] * c.ethereal,
    }
