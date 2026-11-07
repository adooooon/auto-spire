"""Act 1 "?" events: the pool the game draws from and the five the sim models.

The pool is Overgrowth.AllEvents + ModelDb.AllSharedEvents, minus shared events whose IsAllowed is false
in Act 1 (they would only be skipped). Unmodeled events stay in the pool with their real IsAllowed, so
they use up a "?" room as an empty room and the odds of meeting a modeled one stay right. Effects: Run in act.py.
"""
from .cards import CARDS

MODELED_EVENTS = ("BYRDONIS_NEST", "JUNGLE_MAZE_ADVENTURE", "SLIPPERY_BRIDGE", "SUNKEN_STATUE", "THE_LEGENDS_WERE_TRUE")
EVENT_OPTIONS = 2  # every modeled event offers two options


def _always(run) -> bool:
    return True


# id -> IsAllowed, on a Run about to enter the room (row r has r rooms in the history: RunManager creates the
# room before appending it). ponytail: "has a relic left in the bag" and IsTransformable are always true in Act 1.
EVENT_ALLOWED = {
    "AROMA_OF_CHAOS": _always,
    "BYRDONIS_NEST": _always,  # HasEventPet needs its own egg or an Ancient's relic; visited events don't repeat
    "DENSE_VEGETATION": _always,
    "JUNGLE_MAZE_ADVENTURE": _always,
    "LUMINOUS_CHOIR": lambda run: run.gold >= 149,
    "MORPHIC_GROVE": lambda run: run.gold >= 100 and len(run.deck) >= 2,
    "SAPPHIRE_SEED": _always,
    "SUNKEN_STATUE": _always,
    "TABLET_OF_TRUTH": _always,
    "UNREST_SITE": lambda run: run.hp * 10 <= run.max_hp * 7,
    "WELLSPRING": _always,
    "WHISPERING_HOLLOW": lambda run: run.gold >= 44,
    "WOOD_CARVINGS": lambda run: any(CARDS[c].rarity == "Basic" for c in run.deck),
    "BRAIN_LEECH": _always,
    "ROOM_FULL_OF_CHEESE": _always,
    "SELF_HELP_BOOK": _always,
    "SLIPPERY_BRIDGE": lambda run: run.node.row > 6 and bool(run.deck),
    "TEA_MASTER": lambda run: run.gold >= 150,
    "THE_FUTURE_OF_POTIONS": lambda run: sum(p is not None for p in run.potions) >= 2,
    "THE_LEGENDS_WERE_TRUE": lambda run: bool(run.deck) and run.hp >= 10,
    "THIS_OR_THAT": _always,
}

# Act 2's pool: Hive.AllEvents + the shared events allowed there. Only Slippery Bridge is modeled; the rest are empty
# rooms, as in Act 1. ponytail: IsAllowed conditions that need unmodeled state (Ranwid's relics, Fake Merchant,
# Amalgamator's Strikes and Defends, Field of Holes' enchantable cards) count as always true.
HIVE_EVENT_ALLOWED = {
    "AMALGAMATOR": _always, "BUGSLAYER": _always, "COLORFUL_PHILOSOPHERS": _always,
    "COLOSSAL_FLOWER": lambda run: run.hp >= 19,
    "FIELD_OF_MAN_SIZED_HOLES": _always, "INFESTED_AUTOMATON": _always, "LOST_WISP": _always, "SPIRIT_GRAFTER": _always,
    "THE_LANTERN_KEY": _always, "ZEN_WEAVER": _always,
    "BRAIN_LEECH": _always,
    "CRYSTAL_SPHERE": lambda run: run.gold >= 100,
    "DOLL_ROOM": _always, "FAKE_MERCHANT": _always, "POTION_COURIER": _always, "RANWID_THE_ELDER": _always,
    "RELIC_TRADER": lambda run: len(run.relics) >= 5,
    "ROOM_FULL_OF_CHEESE": _always, "SELF_HELP_BOOK": _always,
    "SLIPPERY_BRIDGE": lambda run: bool(run.deck),
    "STONE_OF_ALL_TIME": lambda run: any(run.potions),
    "SYMBIOTE": _always,
    "TEA_MASTER": lambda run: run.gold >= 150,
    "THE_FUTURE_OF_POTIONS": lambda run: sum(p is not None for p in run.potions) >= 2,
    "THIS_OR_THAT": _always,
    "WELCOME_TO_WONGOS": lambda run: run.gold >= 100,
}
