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

from .act import (BOSSES, ELITES, NORMALS, SHOP_SLOTS, STARTING_GOLD, TAGS, WEAK, RarityOdds, Run, UnknownOdds,
                  card_type, encounter_queue, make_shop)
from .cards import CARDS

# Encounter queue: 3 weak then 12 regular, no back-to-back repeats or shared tags where avoidable.
for seed in range(200):
    normals, elites, boss = encounter_queue(random.Random(seed))
    assert len(normals) == 15 and all(e in WEAK for e in normals[:3]) and all(e in NORMALS for e in normals[3:])
    assert len(elites) == 15 and all(e in ELITES for e in elites) and boss in BOSSES
    for a, b in zip(normals, normals[1:]):
        assert a != b
    for i, (a, b) in enumerate(zip(normals[3:], normals[4:])):  # a near-empty bag may only hold tag-sharers
        assert i >= 9 or not (TAGS.get(a, set()) & TAGS.get(b, set())), (a, b)

# "?" rooms: the rolled type resets and unrolled ones grow, so over 20k back-to-back rolls events are ~47%.
u, rolls = UnknownOdds(), Counter()
r = random.Random(0)
for _ in range(20000):
    rolls[u.roll(r, set())] += 1
assert 0.40 < rolls["Event"] / 20000 < 0.55 and rolls["Monster"] > rolls["Shop"] > rolls["Treasure"] > 0, rolls
u = UnknownOdds()
assert u.roll(random.Random(1), {"Shop"}) in ("Monster", "Treasure", "Event") and u.odds["Shop"] == 0.03

# Shop: 5 slots of the right types, no duplicates, prices by rarity with jitter, one half-price.
for seed in range(200):
    s = make_shop(random.Random(seed), RarityOdds(), removals=2)
    assert len(s.cards) == len(SHOP_SLOTS) and len(set(s.cards)) == len(s.cards)
    assert [card_type(c) for c in s.cards] == list(SHOP_SLOTS)
    assert s.removal_price == 75 + 25 * 2 and not s.removal_used
    assert all(23 <= p <= 158 for p in s.prices)

# Run: start, gold rewards, rest heal on max HP (review focus 4), buying and removing.
run = Run(random.Random(3))
assert run.gold == STARTING_GOLD and run.hp == run.max_hp == 80 and len(run.deck) == 10 and run.node is run.map.start
assert {n.row for n in run.choices()} == {1}
room = run.enter(run.choices()[0])
assert room == "Monster" and run.encounter(room) in WEAK
offered = run.win("Monster")
assert len(offered) == 3 and 99 + 10 <= run.gold <= 99 + 20
run.hp, run.max_hp = 40, 90  # say a Feed raised max HP during a fight
rest = next(n for n in run.map.nodes() if n.type == "RestSite")
run.node = rest.parents[0]
run.enter(rest)
assert run.hp == 40 + 27  # 30% of the new max
run.shop = make_shop(random.Random(0), RarityOdds(), 0)
run.gold = 500
slot = next(i for i, c in enumerate(run.shop.cards) if c in CARDS)
card, price = run.shop.cards[slot], run.shop.prices[slot]
run.buy(slot)
assert run.deck[-1] == card and run.gold == 500 - price and run.shop.cards[slot] is None and run.spent == price
run.remove("STRIKE_IRONCLAD")
assert run.deck.count("STRIKE_IRONCLAD") == 4 and run.removals == 1 and run.shop.removal_used

print("act self-check ok")
