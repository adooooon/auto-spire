"""Self-checks for the Act 1 run model (map, rules). Run from agent/: python -m sim.test_act"""
import random
from collections import Counter

from .map import BOSS_ROW, LAST_ROW, TREASURE_ROW, generate_map, gaussian_int

NEIGHBOR = {"Elite", "RestSite", "Treasure", "Shop"}
SIBLING = {"RestSite", "Unknown", "Elite", "Shop"}  # Monster too in the game, but Monster is the default fill

counts = Counter()
for seed in range(300):
    m = generate_map(random.Random(seed))
    nodes = m.nodes()
    # Every room is reachable from the start and reaches the boss.
    seen, todo = set(), [m.start]
    while todo:
        n = todo.pop()
        if id(n) not in seen:
            seen.add(id(n))
            todo += n.children
    assert all(id(n) in seen for n in nodes) and id(m.boss) in seen
    assert all(n.children for n in nodes), "dead end"
    assert m.boss.row == BOSS_ROW and m.start.type == "Ancient" and m.boss.type == "Boss"
    # Fixed floors.
    assert all(n.type == "Monster" for n in m.row(1))
    assert all(n.type == "Treasure" for n in m.row(TREASURE_ROW))
    assert all(n.type == "RestSite" for n in m.row(LAST_ROW))
    assert all(n.children == [m.boss] for n in m.row(LAST_ROW))
    # Placement rules (StandardActMap.IsValidPointType) on assigned rooms.
    for n in nodes:
        assert n.type != "Unassigned"
        if n.fixed:
            continue
        assert not (n.row < 6 and n.type in ("RestSite", "Elite")), n
        assert not (n.row >= LAST_ROW - 2 and n.type == "RestSite"), n
        if n.type in NEIGHBOR:
            assert all(o.type != n.type for o in n.parents + n.children), n
        if n.type in SIBLING:
            assert all(s is n or s.type != n.type for p in n.parents for s in p.children), n
    # Edges only go to the next row, at most one column over.
    for n in nodes:
        assert all(c.row == n.row + 1 and (c is m.boss or abs(c.col - n.col) <= 1) for c in n.children)
    t = Counter(n.type for n in nodes if not n.fixed)
    assert t["Elite"] <= 5 and t["Shop"] <= 3 and t["Unknown"] <= 14 and t["RestSite"] <= 7
    counts.update(t)
assert counts["Elite"] / 300 >= 4.0 and counts["Shop"] / 300 >= 2.5 and counts["Unknown"] / 300 >= 9, counts

# Review focus 5: same seed, same map.
a, b = generate_map(random.Random(7)), generate_map(random.Random(7))
assert [(n.col, n.row, n.type, [(c.col, c.row) for c in n.children]) for n in a.nodes()] == \
       [(n.col, n.row, n.type, [(c.col, c.row) for c in n.children]) for n in b.nodes()]

g = Counter(gaussian_int(random.Random(i), 7, 1, 6, 7) for i in range(2000))
assert set(g) == {6, 7} and g[7] > g[6]  # Overgrowth rest count: N(7, 1) clamped to 6-7

print("act self-check ok")
