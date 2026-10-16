"""Card definitions ported from the game's decompiled source.

Sources (see ../../decompiled/MegaCrit.Sts2.Core.Models.Cards/): the Ironclad
starter cards, the Slimed/Dazed statuses, and the Ironclad Common pool
(IroncladCardPool.cs) except Armaments and Headbutt, which open a card-choice
prompt the mod can't answer yet. Unupgraded only.

On play, effects resolve in a fixed order that matches every card here:
self HP loss -> block -> damage -> Vulnerable -> temporary Strength -> draw ->
energy -> exhaust a random hand card -> add a copy to the discard pile.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CardDef:
    id: str
    title: str
    type: str  # "Attack" | "Skill" | "Status"
    cost: int  # -1 = Unplayable
    target_type: str  # "AnyEnemy" | "AllEnemies" | "RandomEnemy" | "Self" | "None"
    damage: int = 0
    hits: int = 1  # RandomEnemy cards pick a fresh target per hit
    block: int = 0
    vulnerable: int = 0  # applied to the target (AllEnemies: every hittable enemy)
    draw: int = 0
    exhaust: bool = False
    ethereal: bool = False  # exhausted if still in hand at end of turn
    strike: bool = False  # CardTag.Strike (Perfected Strike counts these)
    hp_loss: int = 0  # unblockable self-damage, before anything else
    energy: int = 0  # gained
    temp_strength: int = 0  # TemporaryStrengthPower: Strength until the end of this turn
    damage_per_strike: int = 0  # Perfected Strike: + this per Strike-tagged card in combat
    damage_from_block: bool = False  # Body Slam: damage = current block
    double_vulnerable: bool = False  # Molten Fist: re-apply the target's current Vulnerable
    exhaust_random: bool = False  # Cinder / True Grit: exhaust a random card from hand
    autoplay_top: bool = False  # Havoc: play the top draw-pile card for free, then exhaust it
    copy_to_discard: bool = False  # Anger: add a copy of itself to the discard pile


CARDS: dict[str, CardDef] = {c.id: c for c in [
    CardDef("STRIKE_IRONCLAD", "Strike", "Attack", 1, "AnyEnemy", damage=6, strike=True),
    CardDef("DEFEND_IRONCLAD", "Defend", "Skill", 1, "Self", block=5),
    CardDef("BASH", "Bash", "Attack", 2, "AnyEnemy", damage=8, vulnerable=2),
    # Status card slimes shuffle into the discard pile: 1 energy, draw 1, Exhaust.
    CardDef("SLIMED", "Slimed", "Status", 1, "None", draw=1, exhaust=True),
    # Status card Eye With Teeth shuffles into the discard pile: Unplayable, Ethereal.
    CardDef("DAZED", "Dazed", "Status", -1, "None", ethereal=True),
    # Ironclad Commons.
    CardDef("ANGER", "Anger", "Attack", 0, "AnyEnemy", damage=6, copy_to_discard=True),
    CardDef("BLOOD_WALL", "Blood Wall", "Skill", 2, "Self", hp_loss=2, block=16),
    CardDef("BLOODLETTING", "Bloodletting", "Skill", 0, "Self", hp_loss=3, energy=2),
    CardDef("BODY_SLAM", "Body Slam", "Attack", 1, "AnyEnemy", damage_from_block=True),
    CardDef("BREAKTHROUGH", "Breakthrough", "Attack", 1, "AllEnemies", hp_loss=1, damage=9),
    CardDef("CINDER", "Cinder", "Attack", 2, "AnyEnemy", damage=18, exhaust_random=True),
    # Havoc's Exhaust is only a hover tip: Havoc itself is discarded; the card it plays is exhausted.
    CardDef("HAVOC", "Havoc", "Skill", 1, "Self", autoplay_top=True),
    CardDef("IRON_WAVE", "Iron Wave", "Attack", 1, "AnyEnemy", block=5, damage=5),
    CardDef("MOLTEN_FIST", "Molten Fist", "Attack", 1, "AnyEnemy", damage=10, double_vulnerable=True, exhaust=True),
    CardDef("PERFECTED_STRIKE", "Perfected Strike", "Attack", 2, "AnyEnemy", damage=6, damage_per_strike=2,
            strike=True),
    CardDef("POMMEL_STRIKE", "Pommel Strike", "Attack", 1, "AnyEnemy", damage=9, draw=1, strike=True),
    CardDef("SETUP_STRIKE", "Setup Strike", "Attack", 1, "AnyEnemy", damage=7, temp_strength=2, strike=True),
    CardDef("SHRUG_IT_OFF", "Shrug It Off", "Skill", 1, "Self", block=8, draw=1),
    CardDef("SWORD_BOOMERANG", "Sword Boomerang", "Attack", 1, "RandomEnemy", damage=3, hits=3),
    CardDef("THUNDERCLAP", "Thunderclap", "Attack", 1, "AllEnemies", damage=4, vulnerable=1),
    CardDef("TREMBLE", "Tremble", "Skill", 1, "AnyEnemy", vulnerable=3, exhaust=True),
    CardDef("TRUE_GRIT", "True Grit", "Skill", 1, "Self", block=7, exhaust_random=True),
    CardDef("TWIN_STRIKE", "Twin Strike", "Attack", 1, "AnyEnemy", damage=5, hits=2, strike=True),
]}
COMMONS = tuple(sorted(cid for cid in CARDS if cid not in (
    "STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "BASH", "SLIMED", "DAZED")))


def starter_deck() -> list[str]:
    """5x Strike, 4x Defend, 1x Bash — the Ironclad's starting deck."""
    return ["STRIKE_IRONCLAD"] * 5 + ["DEFEND_IRONCLAD"] * 4 + ["BASH"]


def card_cost(card_id: str, tangled: int = 0) -> int:
    """Energy cost with modifiers: Tangled adds its amount to Attack cards (TangledPower.cs)."""
    c = CARDS[card_id]
    return c.cost + tangled if c.type == "Attack" else c.cost


def card_to_dict(card_id: str, energy: int, tangled: int = 0) -> dict:
    c = CARDS[card_id]
    cost = card_cost(card_id, tangled)
    return {
        "id": c.id,
        "name": c.title.replace(" ", "") + ("Ironclad" if c.id.endswith("IRONCLAD") else ""),
        "title": c.title,
        "type": c.type,
        "rarity": "Status" if c.type == "Status" else "Common" if c.id in COMMONS else "Basic",
        "cost": cost,
        "canPlay": 0 <= cost <= energy,
        "targetType": c.target_type,
        "upgraded": False,
        "upgradeLevel": 0,
        "keywords": ["Exhaust"] * c.exhaust + ["Ethereal", "Unplayable"] * c.ethereal,
    }
