"""Act 1 (Overgrowth) map generation, ported from StandardActMap.cs.

Row 0 is the Ancient (Neow), rows 1-15 are rooms (Overgrowth.BaseNumberOfRooms = 15) and row
16 is the boss. 7 columns. Seeded by Python's random: the same distribution as the game's maps,
not the same maps for a given game seed.

ponytail: MapPostProcessing is skipped. It only re-centers and spreads columns and never changes
edges. MapPathPruning (which removes duplicate parallel segments with the same endpoints and room
types, then repairs room counts) is skipped too: it enumerates every path, about a second per map
in Python. Port it if map statistics drift from the game's.
"""
from __future__ import annotations

import math
import random

COLS, LAST_ROW = 7, 15
BOSS_ROW = LAST_ROW + 1
TREASURE_ROW = BOSS_ROW - 7  # GetRowCount() - 7
ROOM_TYPES = ("Monster", "Elite", "RestSite", "Shop", "Treasure", "Unknown", "Boss")
NUM_ELITES, NUM_SHOPS = 5, 3  # MapPointTypeCounts at ascension 0

_LOWER = {"RestSite", "Elite"}  # not below row 6
_UPPER = {"RestSite"}  # not in the last 3 rows (the last row is all rest sites anyway)
_NEIGHBOR = {"Elite", "RestSite", "Treasure", "Shop"}  # not next to the same type
_SIBLING = {"RestSite", "Monster", "Unknown", "Elite", "Shop"}  # not beside the same type


class Node:
    __slots__ = ("col", "row", "type", "fixed", "children", "parents")

    def __init__(self, col: int, row: int, type: str = "Unassigned"):
        self.col, self.row, self.type, self.fixed = col, row, type, False
        self.children: list[Node] = []
        self.parents: list[Node] = []

    def add_child(self, child: Node) -> None:
        if child not in self.children:
            self.children.append(child)
            child.parents.append(self)

    def __repr__(self) -> str:
        return f"Node({self.col},{self.row},{self.type})"


class ActMap:
    def __init__(self):
        self.grid: dict[tuple[int, int], Node] = {}
        self.start = Node(COLS // 2, 0, "Ancient")
        self.boss = Node(COLS // 2, BOSS_ROW, "Boss")

    def point(self, col: int, row: int) -> Node:
        if (col, row) not in self.grid:
            self.grid[col, row] = Node(col, row)
        return self.grid[col, row]

    def row(self, r: int) -> list[Node]:
        return sorted((n for n in self.grid.values() if n.row == r), key=lambda n: n.col)

    def nodes(self) -> list[Node]:
        return sorted(self.grid.values(), key=lambda n: (n.row, n.col))


def gaussian_int(rng: random.Random, mean: int, sd: int, lo: int, hi: int) -> int:
    """Rng.NextGaussianInt: Box-Muller, rounded (banker's, like Math.Round), rejected until in range."""
    while True:
        u1, u2 = 1.0 - rng.random(), 1.0 - rng.random()
        v = round(mean + sd * math.sqrt(-2.0 * math.log(u1)) * math.sin(2.0 * math.pi * u2))
        if lo <= v <= hi:
            return v


def _invalid_crossover(m: ActMap, cur: Node, col: int) -> bool:
    """A diagonal step may not cross the neighbor's diagonal step the other way."""
    d = col - cur.col
    if d == 0:
        return False
    nb = m.grid.get((col, cur.row))
    return nb is not None and any(ch.col - nb.col == -d for ch in nb.children)


def _path(m: ActMap, rng: random.Random, p: Node) -> None:
    while p.row < LAST_ROW:
        for d in rng.sample((-1, 0, 1), 3):
            col = min(max(p.col + d, 0), COLS - 1)
            if not _invalid_crossover(m, p, col):
                break
        else:
            raise RuntimeError(f"no next node from {p}")
        nxt = m.point(col, p.row + 1)
        p.add_child(nxt)
        p = nxt


def _valid(t: str, n: Node) -> bool:
    if n.row < 6 and t in _LOWER:
        return False
    if n.row >= LAST_ROW - 2 and t in _UPPER:
        return False
    if t in _NEIGHBOR and any(o.type == t for o in n.parents + n.children):
        return False
    if t in _SIBLING and any(s is not n and s.type == t for p in n.parents for s in p.children):
        return False
    return True


def _next_valid(queue: list[str], n: Node) -> str:
    """GetNextValidPointType: the first queued type valid here; invalid ones rotate to the back."""
    for _ in range(len(queue)):
        t = queue.pop(0)
        if _valid(t, n):
            return t
        queue.append(t)
    return "Unassigned"


def generate_map(rng: random.Random) -> ActMap:
    rests = gaussian_int(rng, 7, 1, 6, 7)  # Overgrowth.GetMapPointTypes
    unknowns = gaussian_int(rng, 12, 1, 10, 14)  # MapPointTypeCounts.StandardRandomUnknownCount
    m = ActMap()
    starts: list[Node] = []
    for i in range(COLS):
        p = m.point(rng.randrange(COLS), 1)
        if i == 1:  # the second path starts somewhere new
            while p in starts:
                p = m.point(rng.randrange(COLS), 1)
        if p not in starts:
            starts.append(p)
        _path(m, rng, p)
    for n in m.row(LAST_ROW):
        n.add_child(m.boss)
    for n in m.row(1):
        m.start.add_child(n)

    for row, t in ((LAST_ROW, "RestSite"), (TREASURE_ROW, "Treasure"), (1, "Monster")):
        for n in m.row(row):
            n.type, n.fixed = t, True
    queue = ["RestSite"] * rests + ["Shop"] * NUM_SHOPS + ["Elite"] * NUM_ELITES + ["Unknown"] * unknowns
    for _ in range(3):  # AssignRemainingTypesToRandomPoints
        if not queue:
            break
        spots = [n for n in m.nodes() if n.type == "Unassigned"]
        rng.shuffle(spots)
        for n in spots:
            if not queue:
                break
            n.type = _next_valid(queue, n)
    for n in m.nodes():
        if n.type == "Unassigned":
            n.type = "Monster"
    return m
