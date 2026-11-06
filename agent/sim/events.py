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
