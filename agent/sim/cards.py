"""Card definitions ported from the game's decompiled source.

Sources (see ../../decompiled/MegaCrit.Sts2.Core.Models.Cards/): the Ironclad
starter cards, the status cards Act 1 monsters add, and the whole Ironclad pool
(IroncladCardPool.cs) except the multiplayer-only Demonic Shield and Tank. CARDS also holds
an "<ID>+" for every upgradable card (UPGRADES, from each card's OnUpgrade).

The generic fields resolve in this order, which matches every card using them:
self HP loss -> block -> damage -> Vulnerable/Weak -> temporary Strength -> draw ->
energy -> heal -> exhaust a random hand card -> copy to discard -> autoplay -> powers.
Cards with their own logic (`special`) are handled by id in engine.SimCombat._special.
CHOICE_CARDS ask the player to choose another card (engine.SimCombat.pending_choice).
"""
from __future__ import annotations

from dataclasses import dataclass, replace


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
    CardDef("TOXIC", "Toxic", "Status", 1, "None", rarity="Status", exhaust=True, end_turn_damage=5, generated=False),
    # Each copy costs 1 more each time it's played (engine: CardCopy).
    CardDef("FRANTIC_ESCAPE", "Frantic Escape", "Status", 1, "Self", rarity="Status", special=True, generated=False),
    # Ironclad Commons.
    CardDef("ANGER", "Anger", "Attack", 0, "AnyEnemy", rarity="Common", damage=6, copy_to_discard=True),
    CardDef("BLOOD_WALL", "Blood Wall", "Skill", 2, "Self", rarity="Common", hp_loss=2, block=16),
    CardDef("BLOODLETTING", "Bloodletting", "Skill", 0, "Self", rarity="Common", hp_loss=3, energy=2),
    CardDef("BODY_SLAM", "Body Slam", "Attack", 1, "AnyEnemy", rarity="Common", damage_from_block=True),
    CardDef("BREAKTHROUGH", "Breakthrough", "Attack", 1, "AllEnemies", rarity="Common", hp_loss=1, damage=9),
    CardDef("CINDER", "Cinder", "Attack", 2, "AnyEnemy", rarity="Common", damage=18, exhaust_random=True),
    # Havoc's Exhaust is only a hover tip: Havoc itself is discarded; the card it plays is exhausted.
    CardDef("HAVOC", "Havoc", "Skill", 1, "Self", rarity="Common", autoplay_top=True),
    CardDef("HEADBUTT", "Headbutt", "Attack", 1, "AnyEnemy", rarity="Common", damage=9, special=True),
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
    # Chooses a card in hand to upgrade (all of them when upgraded). The block is generic; ponytail: the engine
    # skips the upgrade until the sim plays upgrades (_special does nothing for it).
    CardDef("ARMAMENTS", "Armaments", "Skill", 1, "Self", rarity="Common", block=5, special=True),
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
    CardDef("BURNING_PACT", "Burning Pact", "Skill", 1, "Self", rarity="Uncommon", special=True),
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
    CardDef("BRAND", "Brand", "Skill", 0, "Self", rarity="Rare", special=True),
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
# CardDef field changes for the upgraded card, from each card's OnUpgrade (MaxUpgradeLevel is 1 for all of these;
# statuses and Wound have 0 and no entry). An empty entry is upgradable, but the upgrade changes no CardDef field: the
# comment says what the engine (Task 3) must do. For `special` cards the engine hardcodes some numbers; those are named.
UPGRADES: dict[str, dict] = {
    "STRIKE_IRONCLAD": dict(damage=9), "DEFEND_IRONCLAD": dict(block=8), "BASH": dict(damage=10, vulnerable=3),
    "ANGER": dict(damage=8), "BLOOD_WALL": dict(block=20), "BLOODLETTING": dict(energy=3),
    "BODY_SLAM": dict(cost=0), "BREAKTHROUGH": dict(damage=13), "CINDER": dict(damage=24), "HAVOC": dict(cost=0),
    "HEADBUTT": dict(damage=12), "IRON_WAVE": dict(block=7, damage=7), "MOLTEN_FIST": dict(damage=14),
    "PERFECTED_STRIKE": dict(damage_per_strike=3), "POMMEL_STRIKE": dict(damage=10, draw=2),
    "SETUP_STRIKE": dict(damage=9, temp_strength=3), "SHRUG_IT_OFF": dict(block=11),
    "SWORD_BOOMERANG": dict(hits=4), "THUNDERCLAP": dict(damage=7), "TREMBLE": dict(vulnerable=4),
    "TRUE_GRIT": dict(block=9), "TWIN_STRIKE": dict(damage=7),
    "ARMAMENTS": {},  # engine: upgrade every upgradable card in hand instead of choosing one
    "ASHEN_STRIKE": {},  # engine: +4 per exhausted card (hardcoded 3)
    "BLUDGEON": dict(damage=42),
    "BULLY": {},  # engine: +3 per Vulnerable (hardcoded 2)
    "DISMANTLE": dict(damage=10),  # engine hardcodes 8: read card.damage
    "FIGHT_ME": dict(damage=6),  # engine hardcodes damage 5 and Strength 3/1: upgraded 6, 4 Strength to you, enemy still +1
    "HEMOKINESIS": dict(damage=20), "HOWL_FROM_BEYOND": dict(damage=21),
    "PILLAGE": dict(damage=9),  # engine hardcodes 6: read card.damage
    "RAMPAGE": {},  # engine: +9 per play (hardcoded 5)
    "SPITE": {},  # engine: 3 hits when HP was lost this turn (hardcoded 2)
    "STOMP": dict(damage=15), "UNRELENTING": dict(damage=20), "UPPERCUT": dict(weak=2, vulnerable=2),
    "WHIRLWIND": dict(damage=8), "BATTLE_TRANCE": dict(draw=4),
    "BURNING_PACT": {},  # engine: draw 3 (hardcoded 2)
    "COLOSSUS": dict(block=8),
    "DOMINATE": {},  # engine: 2 Vulnerable (hardcoded 1)
    "DRUM_OF_BATTLE": {},  # engine: 3 energy when it is exhausted (hardcoded 2)
    "EVIL_EYE": {},  # engine: block 11 (hardcoded 8)
    "EXPECT_A_FIGHT": dict(cost=1),
    "FLAME_BARRIER": dict(block=16, powers=(("FlameBarrierPower", 6),)),
    "FORGOTTEN_RITUAL": {},  # engine: 4 energy (hardcoded 3)
    "INFERNAL_BLADE": dict(cost=0),
    "RAGE": dict(powers=(("RagePower", 5),)),
    "SECOND_WIND": {},  # engine: 7 block per exhausted card (hardcoded 5)
    "TAUNT": dict(block=8, vulnerable=2),
    "FEEL_NO_PAIN": dict(powers=(("FeelNoPainPower", 4),)), "INFERNO": dict(powers=(("InfernoPower", 9),)),
    "INFLAME": dict(powers=(("StrengthPower", 3),)),
    "JUGGLING": {},  # engine: Innate (starts in the opening hand); CardDef has no innate field
    "RUPTURE": dict(powers=(("RupturePower", 2),)), "STAMPEDE": dict(cost=1),
    "STONE_ARMOR": dict(powers=(("PlatingPower", 6),)), "VICIOUS": dict(powers=(("ViciousPower", 2),)),
    "CONFLAGRATION": dict(hits=5),
    "FEED": dict(damage=12),  # engine hardcodes damage 10 and max HP 3: upgraded 12 and 4
    "FIEND_FIRE": dict(damage=10),  # engine hardcodes 7: read card.damage
    "MANGLE": dict(damage=20),  # engine hardcodes damage 15 and Strength loss 10: upgraded 20 and 15
    "PACTS_END": dict(damage=23),  # engine hardcodes 17: read card.damage
    "TEAR_ASUNDER": dict(damage=7),  # engine hardcodes 5: read card.damage
    "THRASH": dict(damage=6),
    "BRAND": {},  # engine: gain 2 Strength (hardcoded 1)
    "CASCADE": {},  # engine: upgraded plays X+1 cards (see Cascade.cs IsUpgraded)
    "IMPERVIOUS": dict(block=40), "NOT_YET": dict(heal=13), "OFFERING": dict(draw=5),
    "ONE_TWO_PUNCH": dict(powers=(("OneTwoPunchPower", 2),)),
    "PRIMAL_FORCE": {},  # engine: the Giant Rocks it makes are upgraded (GIANT_ROCK+)
    "STOKE": {},  # engine: upgrade the cards it adds to hand
    "AGGRESSION": {},  # engine: Innate
    "BARRICADE": dict(cost=2), "CRIMSON_MANTLE": dict(powers=(("CrimsonMantlePower", 10),)),
    "CRUELTY": dict(powers=(("CrueltyPower", 50),)), "DARK_EMBRACE": dict(cost=1),
    "DEMON_FORM": dict(powers=(("DemonFormPower", 3),)), "HELLRAISER": dict(cost=1),
    "JUGGERNAUT": dict(powers=(("JuggernautPower", 8),)),
    "PYRE": dict(powers=(("PyrePower", 2),)),  # PyrePower amount is the energy per turn
    "UNMOVABLE": dict(cost=1), "GIANT_ROCK": dict(damage=20),
}
UPGRADABLE = frozenset(UPGRADES)
for _id, _changes in UPGRADES.items():
    _c = CARDS[_id]
    CARDS[_id + "+"] = replace(_c, id=_id + "+", title=_c.title + "+", **_changes)  # CardModel.Title appends "+"


def is_upgraded(cid: str) -> bool:
    return cid.endswith("+")


def base_id(cid: str) -> str:
    return cid[:-1] if is_upgraded(cid) else cid


def upgrade(cid: str) -> str:
    """The upgraded id, or cid unchanged if it's upgraded already or can't be (statuses, Wound)."""
    return cid + "+" if cid in UPGRADABLE else cid


# ponytail: COMMONS leaves Armaments out; act.REWARD_POOLS appends it last so seeded offers keep their order.
COMMONS, UNCOMMONS, RARES = (tuple(sorted(cid for cid in CARDS if CARDS[cid].rarity == r and cid != "ARMAMENTS" and not is_upgraded(cid)))
                              for r in ("Common", "Uncommon", "Rare"))
# CardFactory.FilterForCombat: what Stoke / Infernal Blade draw from (uniformly, unlocked pool).
# ponytail: the game's pool also has Armaments; left out until the sim plays its upgrade choice.
GENERATED = tuple(c for c in COMMONS + UNCOMMONS + RARES if CARDS[c].generated)
CHOICE_CARDS = ("BRAND", "BURNING_PACT", "HEADBUTT")


def starter_deck() -> list[str]:
    """5x Strike, 4x Defend, 1x Bash — the Ironclad's starting deck."""
    return ["STRIKE_IRONCLAD"] * 5 + ["DEFEND_IRONCLAD"] * 4 + ["BASH"]


def card_to_dict(card_id: str, cost: int, can_play: bool) -> dict:
    """cost/can_play come from the engine (SimCombat.cost), which knows this turn's modifiers."""
    c = CARDS[card_id]
    up, base = is_upgraded(card_id), CARDS[base_id(card_id)]
    return {
        "id": base_id(card_id),
        "name": base.title.replace(" ", "") + ("Ironclad" if base.id.endswith("IRONCLAD") else ""),
        "title": c.title,
        "type": c.type,
        "rarity": c.rarity,
        "cost": cost,
        "canPlay": can_play,
        "targetType": c.target_type,
        "upgraded": up,
        "upgradeLevel": int(up),
        "keywords": ["Exhaust"] * c.exhaust + ["Ethereal", "Unplayable"] * c.ethereal,
    }
