"""Relics: every id the sim knows (RelicPools by rarity) and the ones it models.

Ids are the game's ModelId entries (UPPER_SNAKE of the class name). Effects live in SimCombat
(hook points in fight / _start_player_turn / end_turn ...). Unmodeled relics stay in the pool,
use up their reward and stock shops, but do nothing and can't be bought.
"""
RELIC_POOL = {
    "COMMON": ("AMETHYST_AUBERGINE", "ANCHOR", "BAG_OF_MARBLES", "BAG_OF_PREPARATION", "BLOOD_VIAL", "BOOK_OF_FIVE_RINGS",
               "BRONZE_SCALES", "CENTENNIAL_PUZZLE", "FESTIVE_POPPER", "GORGET", "HAPPY_FLOWER", "JUZU_BRACELET", "LANTERN",
               "MEAL_TICKET", "ODDLY_SMOOTH_STONE", "PENDULUM", "POTION_BELT", "RED_MASK", "RED_SKULL", "REGAL_PILLOW",
               "STRAWBERRY", "STRIKE_DUMMY", "VAJRA", "VENERABLE_TEA_SET", "WAR_PAINT", "WHETSTONE"),
    "UNCOMMON": ("AKABEKO", "BOWLER_HAT", "CANDELABRA", "ETERNAL_FEATHER", "GREMLIN_HORN", "HORN_CLEAT", "JOSS_PAPER",
                 "KUSARIGAMA", "LASTING_CANDY", "LETTER_OPENER", "LUCKY_FYSH", "MERCURY_HOURGLASS", "MINIATURE_CANNON",
                 "NUNCHAKU", "ORICHALCUM", "ORNAMENTAL_FAN", "PANTOGRAPH", "PAPER_PHROG", "PARRYING_SHIELD", "PEAR", "PEN_NIB",
                 "PERMAFROST", "PETRIFIED_TOAD", "PLANISPHERE", "REPTILE_TRINKET", "RIPPLE_BASIN", "SELF_FORMING_CLAY",
                 "SPARKLING_ROUGE", "STONE_CRACKER", "TINY_MAILBOX", "TUNING_FORK", "VAMBRACE"),
    "RARE": ("ART_OF_WAR", "BEATING_REMNANT", "BELLOWS", "CAPTAINS_WHEEL", "CHANDELIER", "CHARONS_ASHES", "CLOAK_CLASP",
             "DEMON_TONGUE", "FROZEN_EGG", "GAMBLING_CHIP", "GAME_PIECE", "GIRYA", "ICE_CREAM", "INTIMIDATING_HELMET", "KUNAI",
             "LIZARD_TAIL", "MANGO", "MEAT_ON_THE_BONE", "MOLTEN_EGG", "MUMMIFIED_HAND", "OLD_COIN", "POCKETWATCH",
             "PRAYER_WHEEL", "RAINBOW_RING", "RAZOR_TOOTH", "RUINED_HELMET", "SHOVEL", "SHURIKEN", "STONE_CALENDAR",
             "STURDY_CLAMP", "THE_COURIER", "TOXIC_EGG", "TUNGSTEN_ROD", "UNCEASING_TOP", "UNSETTLING_LAMP", "VEXING_PUZZLEBOX",
             "WHITE_BEAST_STATUE", "WHITE_STAR"),
    "SHOP": ("BELT_BUCKLE", "BREAD", "BRIMSTONE", "BURNING_STICKS", "CAULDRON", "CHEMICAL_X", "DINGY_RUG", "DOLLYS_MIRROR",
             "DRAGON_FRUIT", "GHOST_SEED", "GNARLED_HAMMER", "KIFUDA", "LAVA_LAMP", "LEES_WAFFLE", "MEMBERSHIP_CARD",
             "MINIATURE_TENT", "MYSTIC_LIGHTER", "ORRERY", "PUNCH_DAGGER", "RINGING_TRIANGLE", "ROYAL_STAMP", "SCREAMING_FLAGON",
             "SLING_OF_COURAGE", "THE_ABACUS", "TOOLBOX", "WING_CHARM"),
}
# ponytail: Miniature Tent lets the player take every rest option; rest() takes one. Razor Tooth upgrades the deck copy of every Attack/Skill played (the sim keeps in-combat upgrades off the deck),
# Lava Lamp upgrades all card rewards after a damage-free fight (needs per-fight damage tracking). Add when the deck matters.
NOT_MODELED = frozenset({
    "RAZOR_TOOTH", "LAVA_LAMP", "GNARLED_HAMMER", "KIFUDA", "PUNCH_DAGGER", "ROYAL_STAMP", "WING_CHARM",
    "GAMBLING_CHIP", "DOLLYS_MIRROR", "DINGY_RUG", "TOOLBOX", "LASTING_CANDY", "PETRIFIED_TOAD", "MINIATURE_TENT",
    "MYSTIC_LIGHTER",
})
UPGRADE_RELICS = frozenset({"WAR_PAINT", "WHETSTONE", "MINIATURE_CANNON", "STONE_CRACKER", "BELLOWS", "FROZEN_EGG", "MOLTEN_EGG", "TOXIC_EGG", "GIRYA", "SHOVEL"})
# ^ modeled with upgrades in the run (Task 4); a policy trained before has no inputs for them (env.combat_maps, run_env.run_maps)
RELICS = frozenset(r for ids in RELIC_POOL.values() for r in ids) - NOT_MODELED
RELIC_IDS = sorted(RELICS)
NOT_IN_SHOPS = frozenset({"AMETHYST_AUBERGINE", "BOWLER_HAT", "LUCKY_FYSH", "OLD_COIN", "THE_COURIER"})  # IsAllowedInShops => false


IRONCLAD_RELICS = frozenset({"BRIMSTONE", "CHARONS_ASHES", "DEMON_TONGUE", "PAPER_PHROG", "RED_SKULL", "RUINED_HELMET",
                             "SELF_FORMING_CLAY"})  # IroncladRelicPool minus Burning Blood; the shared bag (treasure) lacks them


def relic_rarity(relic: str) -> str:
    return next(r for r, ids in RELIC_POOL.items() if relic in ids)
