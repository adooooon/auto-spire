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
    colorless: bool = False  # ColorlessCardPool (not in any Ironclad pool, reward or shop slot)
    innate: bool = False  # CardKeyword.Innate: starts in the opening hand
    retain: bool = False  # CardKeyword.Retain: kept in hand at end of turn
    defend: bool = False  # CardTag.Defend (Fasten's bonus block)


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
    # Block 5, then chooses a card in hand to upgrade (all of them when upgraded): engine._special.
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
    # The 53 single-player ColorlessCardPool cards, in pool order (multiplayer-only ones left out). special=True ones are
    # data only until Tasks 2-4 of the colorless plan add their logic.
    CardDef("ALCHEMIZE", "Alchemize", "Skill", 1, "Self", rarity="Rare", colorless=True, exhaust=True, generated=False, special=True),
    CardDef("ANOINTED", "Anointed", "Skill", 1, "Self", rarity="Rare", colorless=True, exhaust=True, special=True),
    CardDef("AUTOMATION", "Automation", "Power", 1, "Self", rarity="Uncommon", colorless=True, special=True),
    CardDef("BEAT_DOWN", "Beat Down", "Skill", 3, "RandomEnemy", rarity="Rare", colorless=True, special=True),
    CardDef("BOLAS", "Bolas", "Attack", 0, "AnyEnemy", rarity="Rare", colorless=True, damage=3, special=True),
    CardDef("CALAMITY", "Calamity", "Power", 3, "Self", rarity="Rare", colorless=True, special=True),
    CardDef("CATASTROPHE", "Catastrophe", "Skill", 2, "Self", rarity="Uncommon", colorless=True, special=True),
    CardDef("DARK_SHACKLES", "Dark Shackles", "Skill", 0, "AnyEnemy", rarity="Uncommon", colorless=True, exhaust=True, special=True),
    CardDef("DISCOVERY", "Discovery", "Skill", 1, "Self", rarity="Uncommon", colorless=True, exhaust=True, special=True),
    CardDef("DRAMATIC_ENTRANCE", "Dramatic Entrance", "Attack", 0, "AllEnemies", rarity="Uncommon", colorless=True, damage=11, exhaust=True, innate=True),
    CardDef("ENTROPY", "Entropy", "Power", 1, "Self", rarity="Rare", colorless=True, special=True),
    CardDef("EQUILIBRIUM", "Equilibrium", "Skill", 2, "Self", rarity="Uncommon", colorless=True, block=13, powers=(("RetainHandPower", 1),)),
    CardDef("ETERNAL_ARMOR", "Eternal Armor", "Power", 3, "Self", rarity="Rare", colorless=True, special=True),
    CardDef("FASTEN", "Fasten", "Power", 1, "Self", rarity="Uncommon", colorless=True, special=True),
    CardDef("FINESSE", "Finesse", "Skill", 0, "Self", rarity="Uncommon", colorless=True, block=4, draw=1),
    CardDef("FISTICUFFS", "Fisticuffs", "Attack", 1, "AnyEnemy", rarity="Uncommon", colorless=True, damage=7, special=True),
    CardDef("FLASH_OF_STEEL", "Flash of Steel", "Attack", 0, "AnyEnemy", rarity="Uncommon", colorless=True, damage=5, draw=1),
    CardDef("GOLD_AXE", "Gold Axe", "Attack", 1, "AnyEnemy", rarity="Rare", colorless=True, special=True),
    CardDef("HAND_OF_GREED", "Hand of Greed", "Attack", 2, "AnyEnemy", rarity="Rare", colorless=True, damage=20, generated=False, special=True),
    CardDef("HIDDEN_GEM", "Hidden Gem", "Skill", 1, "Self", rarity="Rare", colorless=True, generated=False, special=True),
    CardDef("IMPATIENCE", "Impatience", "Skill", 0, "Self", rarity="Uncommon", colorless=True, special=True),
    CardDef("JACK_OF_ALL_TRADES", "Jack of All Trades", "Skill", 0, "Self", rarity="Uncommon", colorless=True, exhaust=True, special=True),
    CardDef("JACKPOT", "Jackpot", "Attack", 3, "AnyEnemy", rarity="Rare", colorless=True, damage=25, special=True),
    CardDef("MASTER_OF_STRATEGY", "Master of Strategy", "Skill", 0, "Self", rarity="Rare", colorless=True, draw=3, exhaust=True),
    CardDef("MAYHEM", "Mayhem", "Power", 2, "Self", rarity="Rare", colorless=True, special=True),
    CardDef("MIND_BLAST", "Mind Blast", "Attack", 1, "AnyEnemy", rarity="Uncommon", colorless=True, innate=True, special=True),
    CardDef("NOSTALGIA", "Nostalgia", "Power", 1, "Self", rarity="Rare", colorless=True, special=True),
    CardDef("OMNISLICE", "Omnislice", "Attack", 0, "AnyEnemy", rarity="Uncommon", colorless=True, damage=8, special=True),
    CardDef("PANACHE", "Panache", "Power", 0, "Self", rarity="Uncommon", colorless=True, special=True),
    CardDef("PANIC_BUTTON", "Panic Button", "Skill", 0, "Self", rarity="Uncommon", colorless=True, block=30, exhaust=True, special=True),
    CardDef("PREP_TIME", "Prep Time", "Power", 1, "Self", rarity="Uncommon", colorless=True, special=True),
    CardDef("PRODUCTION", "Production", "Skill", 0, "Self", rarity="Uncommon", colorless=True, energy=2, exhaust=True),
    CardDef("PROLONG", "Prolong", "Skill", 0, "Self", rarity="Uncommon", colorless=True, exhaust=True, special=True),
    CardDef("PROWESS", "Prowess", "Power", 1, "Self", rarity="Uncommon", colorless=True, powers=(("StrengthPower", 1), ("DexterityPower", 1))),
    CardDef("PURITY", "Purity", "Skill", 0, "Self", rarity="Uncommon", colorless=True, exhaust=True, retain=True, special=True),
    CardDef("REND", "Rend", "Attack", 2, "AnyEnemy", rarity="Rare", colorless=True, special=True),
    CardDef("RESTLESSNESS", "Restlessness", "Skill", 0, "Self", rarity="Uncommon", colorless=True, retain=True, special=True),
    CardDef("ROLLING_BOULDER", "Rolling Boulder", "Power", 3, "Self", rarity="Rare", colorless=True, special=True),
    CardDef("SALVO", "Salvo", "Attack", 1, "AnyEnemy", rarity="Rare", colorless=True, damage=12, powers=(("RetainHandPower", 1),)),
    CardDef("SCRAWL", "Scrawl", "Skill", 1, "Self", rarity="Rare", colorless=True, exhaust=True, special=True),
    CardDef("SECRET_TECHNIQUE", "Secret Technique", "Skill", 0, "Self", rarity="Rare", colorless=True, exhaust=True, special=True),
    CardDef("SECRET_WEAPON", "Secret Weapon", "Skill", 0, "Self", rarity="Rare", colorless=True, exhaust=True, special=True),
    CardDef("SEEKER_STRIKE", "Seeker Strike", "Attack", 1, "AnyEnemy", rarity="Uncommon", colorless=True, damage=9, strike=True, special=True),
    CardDef("SHOCKWAVE", "Shockwave", "Skill", 2, "AllEnemies", rarity="Uncommon", colorless=True, weak=3, vulnerable=3, exhaust=True),
    CardDef("SPLASH", "Splash", "Skill", 1, "Self", rarity="Uncommon", colorless=True, special=True),
    CardDef("STRATAGEM", "Stratagem", "Power", 1, "Self", rarity="Uncommon", colorless=True, special=True),
    CardDef("THE_BOMB", "The Bomb", "Skill", 2, "Self", rarity="Uncommon", colorless=True, special=True),
    CardDef("THE_GAMBIT", "The Gambit", "Skill", 0, "Self", rarity="Rare", colorless=True, block=50, special=True),
    CardDef("THINKING_AHEAD", "Thinking Ahead", "Skill", 0, "Self", rarity="Uncommon", colorless=True, exhaust=True, special=True),
    CardDef("THRUMMING_HATCHET", "Thrumming Hatchet", "Attack", 1, "AnyEnemy", rarity="Uncommon", colorless=True, damage=11, special=True),
    CardDef("ULTIMATE_DEFEND", "Ultimate Defend", "Skill", 1, "Self", rarity="Uncommon", colorless=True, block=11, defend=True),
    CardDef("ULTIMATE_STRIKE", "Ultimate Strike", "Attack", 1, "AnyEnemy", rarity="Uncommon", colorless=True, damage=14, strike=True),
    CardDef("VOLLEY", "Volley", "Attack", 0, "RandomEnemy", rarity="Uncommon", colorless=True, damage=10, x_cost=True),
]}
# CardDef field changes for the upgraded card, from each card's OnUpgrade (MaxUpgradeLevel is 1 for all of these;
# statuses and Wound have 0 and no entry). An empty entry is upgradable, but the upgrade changes no CardDef field: the
# comment says what the engine does with it. `special` cards read card.damage etc. where a field changes here.
UPGRADES: dict[str, dict] = {
    "STRIKE_IRONCLAD": dict(damage=9), "DEFEND_IRONCLAD": dict(block=8), "BASH": dict(damage=10, vulnerable=3),
    "ANGER": dict(damage=8), "BLOOD_WALL": dict(block=20), "BLOODLETTING": dict(energy=3),
    "BODY_SLAM": dict(cost=0), "BREAKTHROUGH": dict(damage=13), "CINDER": dict(damage=24), "HAVOC": dict(cost=0),
    "HEADBUTT": dict(damage=12), "IRON_WAVE": dict(block=7, damage=7), "MOLTEN_FIST": dict(damage=14),
    "PERFECTED_STRIKE": dict(damage_per_strike=3), "POMMEL_STRIKE": dict(damage=10, draw=2),
    "SETUP_STRIKE": dict(damage=9, temp_strength=3), "SHRUG_IT_OFF": dict(block=11),
    "SWORD_BOOMERANG": dict(hits=4), "THUNDERCLAP": dict(damage=7), "TREMBLE": dict(vulnerable=4),
    "TRUE_GRIT": dict(block=9),  # engine: the player chooses the card to exhaust
    "TWIN_STRIKE": dict(damage=7),
    "ARMAMENTS": {},  # engine: upgrade every upgradable card in hand instead of choosing one
    "ASHEN_STRIKE": {},  # engine: +4 per exhausted card
    "BLUDGEON": dict(damage=42),
    "BULLY": {},  # engine: +3 per Vulnerable
    "DISMANTLE": dict(damage=10),
    "FIGHT_ME": dict(damage=6),  # engine: 4 Strength to you, enemy still +1
    "HEMOKINESIS": dict(damage=20), "HOWL_FROM_BEYOND": dict(damage=21),
    "PILLAGE": dict(damage=9),
    "RAMPAGE": {},  # engine: +9 per play
    "SPITE": {},  # engine: 3 hits when HP was lost this turn
    "STOMP": dict(damage=15), "UNRELENTING": dict(damage=20), "UPPERCUT": dict(weak=2, vulnerable=2),
    "WHIRLWIND": dict(damage=8), "BATTLE_TRANCE": dict(draw=4),
    "BURNING_PACT": {},  # engine: draw 3
    "COLOSSUS": dict(block=8),
    "DOMINATE": {},  # engine: 2 Vulnerable
    "DRUM_OF_BATTLE": {},  # engine: 3 energy when it is exhausted
    "EVIL_EYE": {},  # engine: block 11
    "EXPECT_A_FIGHT": dict(cost=1),
    "FLAME_BARRIER": dict(block=16, powers=(("FlameBarrierPower", 6),)),
    "FORGOTTEN_RITUAL": {},  # engine: 4 energy
    "INFERNAL_BLADE": dict(cost=0),
    "RAGE": dict(powers=(("RagePower", 5),)),
    "SECOND_WIND": {},  # engine: 7 block per exhausted card
    "TAUNT": dict(block=8, vulnerable=2),
    "FEEL_NO_PAIN": dict(powers=(("FeelNoPainPower", 4),)), "INFERNO": dict(powers=(("InfernoPower", 9),)),
    "INFLAME": dict(powers=(("StrengthPower", 3),)),
    "JUGGLING": dict(innate=True),
    "RUPTURE": dict(powers=(("RupturePower", 2),)), "STAMPEDE": dict(cost=1),
    "STONE_ARMOR": dict(powers=(("PlatingPower", 6),)), "VICIOUS": dict(powers=(("ViciousPower", 2),)),
    "CONFLAGRATION": dict(hits=5),
    "FEED": dict(damage=12),  # engine: +4 max HP on a kill
    "FIEND_FIRE": dict(damage=10),
    "MANGLE": dict(damage=20),  # engine: Strength loss 15
    "PACTS_END": dict(damage=23),
    "TEAR_ASUNDER": dict(damage=7),
    "THRASH": dict(damage=6),
    "BRAND": {},  # engine: gain 2 Strength
    "CASCADE": {},  # engine: upgraded plays X+1 cards (see Cascade.cs IsUpgraded)
    "IMPERVIOUS": dict(block=40), "NOT_YET": dict(heal=13), "OFFERING": dict(draw=5),
    "ONE_TWO_PUNCH": dict(powers=(("OneTwoPunchPower", 2),)),
    "PRIMAL_FORCE": {},  # engine: the Giant Rocks it makes are upgraded (GIANT_ROCK+)
    "STOKE": {},  # engine: upgrade the cards it adds to hand
    "AGGRESSION": dict(innate=True),
    "BARRICADE": dict(cost=2), "CRIMSON_MANTLE": dict(powers=(("CrimsonMantlePower", 10),)),
    "CRUELTY": dict(powers=(("CrueltyPower", 50),)), "DARK_EMBRACE": dict(cost=1),
    "DEMON_FORM": dict(powers=(("DemonFormPower", 3),)), "HELLRAISER": dict(cost=1),
    "JUGGERNAUT": dict(powers=(("JuggernautPower", 8),)),
    "PYRE": dict(powers=(("PyrePower", 2),)),  # PyrePower amount is the energy per turn
    "UNMOVABLE": dict(cost=1), "GIANT_ROCK": dict(damage=20),
    # Colorless. Field changes from OnUpgrade; "engine:" notes say what a special card's logic reads.
    "ALCHEMIZE": dict(cost=0), "ANOINTED": dict(retain=True), "AUTOMATION": dict(cost=0),
    "BEAT_DOWN": {},  # engine: 4 cards instead of 3
    "BOLAS": dict(damage=4), "CALAMITY": dict(cost=2),
    "CATASTROPHE": {},  # engine: 3 cards instead of 2
    "DARK_SHACKLES": {},  # engine: Strength loss 15 instead of 9
    "DISCOVERY": dict(exhaust=False), "DRAMATIC_ENTRANCE": dict(damage=15), "ENTROPY": dict(innate=True),
    "EQUILIBRIUM": dict(block=16), "ETERNAL_ARMOR": {},  # engine: Plating 12 instead of 9
    "FASTEN": {},  # engine: extra Defend block 6 instead of 4
    "FINESSE": dict(block=7), "FISTICUFFS": dict(damage=9), "FLASH_OF_STEEL": dict(damage=8),
    "GOLD_AXE": dict(retain=True),
    "HAND_OF_GREED": dict(damage=25),  # engine: 25 gold on a kill
    "HIDDEN_GEM": {},  # engine: Replay 3 instead of 2
    "IMPATIENCE": {},  # engine: 3 cards instead of 2
    "JACK_OF_ALL_TRADES": {},  # engine: 2 cards instead of 1
    "JACKPOT": dict(damage=30),  # engine: the 3 cards it creates are upgraded
    "MASTER_OF_STRATEGY": dict(draw=4), "MAYHEM": dict(cost=1),
    "MIND_BLAST": dict(cost=0), "NOSTALGIA": dict(cost=0), "OMNISLICE": dict(damage=11),
    "PANACHE": {},  # engine: 14 damage instead of 10
    "PANIC_BUTTON": dict(block=40), "PREP_TIME": {},  # engine: 6 instead of 4
    "PRODUCTION": dict(energy=3), "PROLONG": dict(exhaust=False),
    "PROWESS": dict(powers=(("StrengthPower", 2), ("DexterityPower", 2))),
    "PURITY": {},  # engine: exhaust up to 5 cards instead of 3
    "REND": {},  # engine: 18 base, +8 per debuff instead of 15, +5
    "RESTLESSNESS": {},  # engine: 3 cards and 3 energy instead of 2 and 2
    "ROLLING_BOULDER": {},  # engine: 10 instead of 5
    "SALVO": dict(damage=16), "SCRAWL": dict(retain=True), "SECRET_TECHNIQUE": dict(exhaust=False),
    "SECRET_WEAPON": dict(exhaust=False), "SEEKER_STRIKE": dict(damage=12),
    "SHOCKWAVE": dict(weak=5, vulnerable=5),
    "SPLASH": {},  # engine: the 3 Attacks it offers are upgraded
    "STRATAGEM": dict(cost=0),
    "THE_BOMB": {},  # engine: 50 damage instead of 40
    "THE_GAMBIT": dict(block=75), "THINKING_AHEAD": dict(exhaust=False), "THRUMMING_HATCHET": dict(damage=14),
    "ULTIMATE_DEFEND": dict(block=15), "ULTIMATE_STRIKE": dict(damage=20), "VOLLEY": dict(damage=14),
}
UPGRADABLE = frozenset(UPGRADES)
for _id, _changes in UPGRADES.items():
    _c = CARDS[_id]
    CARDS[_id + "+"] = replace(_c, id=_id + "+", title=_c.title + "+", **_changes)  # CardModel.Title appends "+"


def is_upgraded(cid: str) -> bool:
    return cid.endswith("+")


def base_id(cid: str) -> str:
    return cid[:-1] if is_upgraded(cid) else cid


class DeckCard(str):
    """A combat copy of a run-deck card (CardModel.DeckVersion is set): deck is that deck card's id. Upgrading it
    this fight keeps the link; generated cards and clones are plain strs, with no deck card."""

    def __new__(cls, cid: str, deck: str | None = None):
        card = super().__new__(cls, cid)
        card.deck = deck or cid
        return card


def upgrade(cid: str) -> str:
    """The upgraded id, or cid unchanged if it's upgraded already or can't be (statuses, Wound)."""
    if cid not in UPGRADABLE:
        return cid
    return DeckCard(cid + "+", cid.deck) if isinstance(cid, DeckCard) else cid + "+"


# ponytail: COMMONS leaves Armaments out; act.REWARD_POOLS appends it last so seeded offers keep their order.
COMMONS, UNCOMMONS, RARES = (tuple(sorted(cid for cid in CARDS if CARDS[cid].rarity == r and cid != "ARMAMENTS" and not is_upgraded(cid)
                                           and not CARDS[cid].colorless))
                              for r in ("Common", "Uncommon", "Rare"))
# CardFactory.FilterForCombat: what Stoke / Infernal Blade draw from (uniformly, unlocked pool).
# Armaments is last (it isn't in COMMONS), so the draws over the other cards keep their order.
GENERATED = tuple(c for c in COMMONS + UNCOMMONS + RARES + ("ARMAMENTS",) if CARDS[c].generated)
# ColorlessCardPool order (Anointed etc. are Rare, the rest Uncommon). The shop sells all but NOT_BUYABLE.
COLORLESS_UNCOMMONS, COLORLESS_RARES = (tuple(c for c in CARDS if CARDS[c].colorless and CARDS[c].rarity == r and not is_upgraded(c))
                                        for r in ("Uncommon", "Rare"))
COLORLESS = COLORLESS_UNCOMMONS + COLORLESS_RARES
NOT_BUYABLE = frozenset({"SPLASH", "ALCHEMIZE"})
# Colorless cards Jack of All Trades etc. can create (CanBeGeneratedInCombat; Splash is left out).
COLORLESS_GENERATED = tuple(c for c in COLORLESS if CARDS[c].generated and c != "SPLASH")
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
        "keywords": ["Exhaust"] * c.exhaust + ["Ethereal", "Unplayable"] * c.ethereal + ["Retain"] * c.retain + ["Innate"] * c.innate,
    }
