"""Card definitions ported from the game's decompiled source.

Sources (see ../../decompiled/MegaCrit.Sts2.Core.Models.Cards/): the Ironclad
starter cards, the status cards Act 1 monsters add, and the whole Ironclad pool
(IroncladCardPool.cs) except Armaments, Headbutt, Brand and Burning Pact (they open a
card-choice prompt the mod can't answer yet) and the multiplayer-only Demonic Shield and
Tank. Unupgraded only.

The generic fields resolve in this order, which matches every card using them:
self HP loss -> block -> damage -> Vulnerable/Weak -> temporary Strength -> draw ->
energy -> heal -> exhaust a random hand card -> copy to discard -> autoplay -> powers.
Cards with their own logic (`special`) are handled by id in engine.SimCombat._special.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CardDef:
    id: str
    title: str
    type: str  # "Attack" | "Skill" | "Power" | "Status"
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
    end_turn_damage: int = 0  # Infection: blockable damage to the player if in hand at end of turn
    rarity: str = "Basic"  # "Basic" | "Common" | "Uncommon" | "Rare" | "Status" | "Token"
    weak: int = 0  # Weak applied to the target (Uppercut applies it before its Vulnerable)
    heal: int = 0
    x_cost: bool = False  # spends all energy; X = energy spent (autoplays: current energy)
    powers: tuple[tuple[str, int], ...] = ()  # (power class name, amount) applied to the player, last
    special: bool = False  # OnPlay has card-specific logic in the engine
    generated: bool = True  # CardModel.CanBeGeneratedInCombat (Stoke / Infernal Blade can create it)


CARDS: dict[str, CardDef] = {c.id: c for c in [
    CardDef("STRIKE_IRONCLAD", "Strike", "Attack", 1, "AnyEnemy", damage=6, strike=True),
    CardDef("DEFEND_IRONCLAD", "Defend", "Skill", 1, "Self", block=5),
    CardDef("BASH", "Bash", "Attack", 2, "AnyEnemy", damage=8, vulnerable=2),
    # Status card slimes shuffle into the discard pile: 1 energy, draw 1, Exhaust.
    CardDef("SLIMED", "Slimed", "Status", 1, "None", rarity="Status", draw=1, exhaust=True),
    # Status card Eye With Teeth shuffles into the discard pile: Unplayable, Ethereal.
    CardDef("DAZED", "Dazed", "Status", -1, "None", rarity="Status", ethereal=True),
    # Phrog Parasite / Wriggler: Unplayable; 3 damage (Unpowered, so blockable) if held at end of turn.
    CardDef("INFECTION", "Infection", "Status", -1, "None", rarity="Status", end_turn_damage=3),
    # Vantom's Dismember: Unplayable, does nothing else.
    CardDef("WOUND", "Wound", "Status", -1, "None", rarity="Status"),
    # Ironclad Commons.
    CardDef("ANGER", "Anger", "Attack", 0, "AnyEnemy", rarity="Common", damage=6, copy_to_discard=True),
    CardDef("BLOOD_WALL", "Blood Wall", "Skill", 2, "Self", rarity="Common", hp_loss=2, block=16),
    CardDef("BLOODLETTING", "Bloodletting", "Skill", 0, "Self", rarity="Common", hp_loss=3, energy=2),
    CardDef("BODY_SLAM", "Body Slam", "Attack", 1, "AnyEnemy", rarity="Common", damage_from_block=True),
    CardDef("BREAKTHROUGH", "Breakthrough", "Attack", 1, "AllEnemies", rarity="Common", hp_loss=1, damage=9),
    CardDef("CINDER", "Cinder", "Attack", 2, "AnyEnemy", rarity="Common", damage=18, exhaust_random=True),
    # Havoc's Exhaust is only a hover tip: Havoc itself is discarded; the card it plays is exhausted.
    CardDef("HAVOC", "Havoc", "Skill", 1, "Self", rarity="Common", autoplay_top=True),
    CardDef("IRON_WAVE", "Iron Wave", "Attack", 1, "AnyEnemy", rarity="Common", block=5, damage=5),
    CardDef("MOLTEN_FIST", "Molten Fist", "Attack", 1, "AnyEnemy", rarity="Common", damage=10, double_vulnerable=True, exhaust=True),
    CardDef("PERFECTED_STRIKE", "Perfected Strike", "Attack", 2, "AnyEnemy", rarity="Common", damage=6, damage_per_strike=2,
            strike=True),
    CardDef("POMMEL_STRIKE", "Pommel Strike", "Attack", 1, "AnyEnemy", rarity="Common", damage=9, draw=1, strike=True),
    CardDef("SETUP_STRIKE", "Setup Strike", "Attack", 1, "AnyEnemy", rarity="Common", damage=7, temp_strength=2, strike=True),
    CardDef("SHRUG_IT_OFF", "Shrug It Off", "Skill", 1, "Self", rarity="Common", block=8, draw=1),
    CardDef("SWORD_BOOMERANG", "Sword Boomerang", "Attack", 1, "RandomEnemy", rarity="Common", damage=3, hits=3),
    CardDef("THUNDERCLAP", "Thunderclap", "Attack", 1, "AllEnemies", rarity="Common", damage=4, vulnerable=1),
    CardDef("TREMBLE", "Tremble", "Skill", 1, "AnyEnemy", rarity="Common", vulnerable=3, exhaust=True),
    CardDef("TRUE_GRIT", "True Grit", "Skill", 1, "Self", rarity="Common", block=7, exhaust_random=True),
    CardDef("TWIN_STRIKE", "Twin Strike", "Attack", 1, "AnyEnemy", rarity="Common", damage=5, hits=2, strike=True),
    # Ironclad Uncommons. special=True: the engine's _special has the rest of the card.
    CardDef("ASHEN_STRIKE", "Ashen Strike", "Attack", 1, "AnyEnemy", rarity="Uncommon", damage=6, strike=True,
            special=True),  # +3 damage per card in the exhaust pile
    CardDef("BLUDGEON", "Bludgeon", "Attack", 3, "AnyEnemy", rarity="Uncommon", damage=32),
    CardDef("BULLY", "Bully", "Attack", 0, "AnyEnemy", rarity="Uncommon", damage=4, special=True),  # +2 per Vulnerable
    CardDef("DISMANTLE", "Dismantle", "Attack", 1, "AnyEnemy", rarity="Uncommon", damage=8, special=True),  # 2 hits if Vulnerable
    CardDef("FIGHT_ME", "Fight Me!", "Attack", 2, "AnyEnemy", rarity="Uncommon", damage=5, hits=2, special=True),
    CardDef("HEMOKINESIS", "Hemokinesis", "Attack", 1, "AnyEnemy", rarity="Uncommon", hp_loss=2, damage=15),
    # Also autoplays from the exhaust pile at the end of each of your turns (engine.end_turn).
    CardDef("HOWL_FROM_BEYOND", "Howl from Beyond", "Attack", 3, "AllEnemies", rarity="Uncommon", damage=16),
    CardDef("PILLAGE", "Pillage", "Attack", 1, "AnyEnemy", rarity="Uncommon", damage=6, special=True),
    CardDef("RAMPAGE", "Rampage", "Attack", 1, "AnyEnemy", rarity="Uncommon", damage=9, special=True),
    CardDef("SPITE", "Spite", "Attack", 0, "AnyEnemy", rarity="Uncommon", damage=5, special=True),
    CardDef("STOMP", "Stomp", "Attack", 3, "AllEnemies", rarity="Uncommon", damage=12),  # -1 cost per Attack this turn
    CardDef("UNRELENTING", "Unrelenting", "Attack", 2, "AnyEnemy", rarity="Uncommon", damage=14,
            powers=(("FreeAttackPower", 1),)),
    CardDef("UPPERCUT", "Uppercut", "Attack", 2, "AnyEnemy", rarity="Uncommon", damage=13, weak=1, vulnerable=1),
    CardDef("WHIRLWIND", "Whirlwind", "Attack", 0, "AllEnemies", rarity="Uncommon", damage=5, x_cost=True),
    CardDef("BATTLE_TRANCE", "Battle Trance", "Skill", 0, "Self", rarity="Uncommon", draw=3,
            powers=(("NoDrawPower", 1),)),
    CardDef("COLOSSUS", "Colossus", "Skill", 1, "Self", rarity="Uncommon", block=5, powers=(("ColossusPower", 1),)),
    CardDef("DOMINATE", "Dominate", "Skill", 1, "AnyEnemy", rarity="Uncommon", vulnerable=1, exhaust=True, special=True),
    # Its Exhaust is only a hover tip: when something else exhausts it, gain 2 energy.
    CardDef("DRUM_OF_BATTLE", "Drum of Battle", "Skill", 1, "Self", rarity="Uncommon", draw=2),
    CardDef("EVIL_EYE", "Evil Eye", "Skill", 1, "Self", rarity="Uncommon", block=8, special=True),
    CardDef("EXPECT_A_FIGHT", "Expect a Fight", "Skill", 2, "Self", rarity="Uncommon", special=True,
            powers=(("NoEnergyGainPower", 1),)),
    CardDef("FLAME_BARRIER", "Flame Barrier", "Skill", 2, "Self", rarity="Uncommon", block=12,
            powers=(("FlameBarrierPower", 4),)),
    CardDef("FORGOTTEN_RITUAL", "Forgotten Ritual", "Skill", 1, "Self", rarity="Uncommon", exhaust=True, special=True),
    CardDef("INFERNAL_BLADE", "Infernal Blade", "Skill", 1, "Self", rarity="Uncommon", exhaust=True, special=True),
    CardDef("RAGE", "Rage", "Skill", 0, "Self", rarity="Uncommon", powers=(("RagePower", 3),)),
    CardDef("SECOND_WIND", "Second Wind", "Skill", 1, "Self", rarity="Uncommon", special=True),
    CardDef("TAUNT", "Taunt", "Skill", 1, "AnyEnemy", rarity="Uncommon", block=7, vulnerable=1),
    CardDef("FEEL_NO_PAIN", "Feel No Pain", "Power", 1, "Self", rarity="Uncommon", powers=(("FeelNoPainPower", 3),)),
    CardDef("INFERNO", "Inferno", "Power", 1, "Self", rarity="Uncommon", powers=(("InfernoPower", 6),)),
    CardDef("INFLAME", "Inflame", "Power", 1, "Self", rarity="Uncommon", powers=(("StrengthPower", 2),)),
    CardDef("JUGGLING", "Juggling", "Power", 1, "Self", rarity="Uncommon", powers=(("JugglingPower", 1),)),
    CardDef("RUPTURE", "Rupture", "Power", 1, "Self", rarity="Uncommon", powers=(("RupturePower", 1),)),
    CardDef("STAMPEDE", "Stampede", "Power", 2, "Self", rarity="Uncommon", powers=(("StampedePower", 1),)),
    CardDef("STONE_ARMOR", "Stone Armor", "Power", 1, "Self", rarity="Uncommon", powers=(("PlatingPower", 4),)),
    CardDef("VICIOUS", "Vicious", "Power", 1, "Self", rarity="Uncommon", powers=(("ViciousPower", 1),)),
    # Ironclad Rares.
    CardDef("CONFLAGRATION", "Conflagration", "Attack", 1, "AllEnemies", rarity="Rare", damage=2, hits=4),
    CardDef("FEED", "Feed", "Attack", 1, "AnyEnemy", rarity="Rare", damage=10, exhaust=True, special=True,
            generated=False),  # +3 max HP on a kill
    CardDef("FIEND_FIRE", "Fiend Fire", "Attack", 2, "AnyEnemy", rarity="Rare", damage=7, exhaust=True, special=True),
    CardDef("MANGLE", "Mangle", "Attack", 3, "AnyEnemy", rarity="Rare", damage=15, special=True),
    CardDef("PACTS_END", "Pact's End", "Attack", 0, "AllEnemies", rarity="Rare", damage=17, special=True),
    CardDef("TEAR_ASUNDER", "Tear Asunder", "Attack", 2, "AnyEnemy", rarity="Rare", damage=5, special=True),
    CardDef("THRASH", "Thrash", "Attack", 1, "AnyEnemy", rarity="Rare", damage=4, hits=2, special=True),
    CardDef("CASCADE", "Cascade", "Skill", 0, "Self", rarity="Rare", x_cost=True, special=True),
    CardDef("IMPERVIOUS", "Impervious", "Skill", 2, "Self", rarity="Rare", block=30, exhaust=True),
    CardDef("NOT_YET", "Not Yet", "Skill", 2, "Self", rarity="Rare", heal=10, exhaust=True, generated=False),
    CardDef("OFFERING", "Offering", "Skill", 0, "Self", rarity="Rare", hp_loss=6, energy=2, draw=3, exhaust=True),
    CardDef("ONE_TWO_PUNCH", "One-Two Punch", "Skill", 1, "Self", rarity="Rare", powers=(("OneTwoPunchPower", 1),)),
    CardDef("PRIMAL_FORCE", "Primal Force", "Skill", 0, "Self", rarity="Rare", special=True),
    CardDef("STOKE", "Stoke", "Skill", 1, "Self", rarity="Rare", special=True),
    CardDef("AGGRESSION", "Aggression", "Power", 1, "Self", rarity="Rare", powers=(("AggressionPower", 1),)),
    CardDef("BARRICADE", "Barricade", "Power", 3, "Self", rarity="Rare", powers=(("BarricadePower", 1),)),
    CardDef("CRIMSON_MANTLE", "Crimson Mantle", "Power", 1, "Self", rarity="Rare",
            powers=(("CrimsonMantlePower", 8),)),
    CardDef("CRUELTY", "Cruelty", "Power", 1, "Self", rarity="Rare", powers=(("CrueltyPower", 25),)),
    CardDef("DARK_EMBRACE", "Dark Embrace", "Power", 2, "Self", rarity="Rare", powers=(("DarkEmbracePower", 1),)),
    CardDef("DEMON_FORM", "Demon Form", "Power", 3, "Self", rarity="Rare", powers=(("DemonFormPower", 2),)),
    CardDef("HELLRAISER", "Hellraiser", "Power", 2, "Self", rarity="Rare", powers=(("HellraiserPower", 1),)),
    CardDef("JUGGERNAUT", "Juggernaut", "Power", 2, "Self", rarity="Rare", powers=(("JuggernautPower", 6),)),
    CardDef("PYRE", "Pyre", "Power", 2, "Self", rarity="Rare", powers=(("PyrePower", 1),)),
    CardDef("UNMOVABLE", "Unmovable", "Power", 2, "Self", rarity="Rare", powers=(("UnmovablePower", 1),)),
    # Primal Force turns Attacks in hand into this.
    CardDef("GIANT_ROCK", "Giant Rock", "Attack", 1, "AnyEnemy", rarity="Token", damage=16),
]}
COMMONS, UNCOMMONS, RARES = (tuple(sorted(cid for cid in CARDS if CARDS[cid].rarity == r))
                              for r in ("Common", "Uncommon", "Rare"))
# CardFactory.FilterForCombat: what Stoke / Infernal Blade draw from (uniformly, unlocked pool).
# ponytail: the game's pool also has the 4 prompt cards the sim doesn't model.
GENERATED = tuple(c for c in COMMONS + UNCOMMONS + RARES if CARDS[c].generated)


def starter_deck() -> list[str]:
    """5x Strike, 4x Defend, 1x Bash — the Ironclad's starting deck."""
    return ["STRIKE_IRONCLAD"] * 5 + ["DEFEND_IRONCLAD"] * 4 + ["BASH"]


def card_to_dict(card_id: str, cost: int, can_play: bool) -> dict:
    """cost/can_play come from the engine (SimCombat.cost), which knows this turn's modifiers."""
    c = CARDS[card_id]
    return {
        "id": c.id,
        "name": c.title.replace(" ", "") + ("Ironclad" if c.id.endswith("IRONCLAD") else ""),
        "title": c.title,
        "type": c.type,
        "rarity": c.rarity,
        "cost": cost,
        "canPlay": can_play,
        "targetType": c.target_type,
        "upgraded": False,
        "upgradeLevel": 0,
        "keywords": ["Exhaust"] * c.exhaust + ["Ethereal", "Unplayable"] * c.ethereal,
    }
