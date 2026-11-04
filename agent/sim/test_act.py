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
                  card_type, encounter_queue, make_shop, RelicBags)
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
    s = make_shop(random.Random(seed), RarityOdds(), 2, RelicBags(random.Random(seed)))
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
run.shop = make_shop(random.Random(0), RarityOdds(), 0, RelicBags(random.Random(0)))
run.gold = 500
slot = next(i for i, c in enumerate(run.shop.cards) if c in CARDS)
card, price = run.shop.cards[slot], run.shop.prices[slot]
run.buy(slot)
assert run.deck[-1] == card and run.gold == 500 - price and run.shop.cards[slot] is None and run.spent == price
run.remove("STRIKE_IRONCLAD")
assert run.deck.count("STRIKE_IRONCLAD") == 4 and run.removals == 1 and run.shop.removal_used

from .act import PotionOdds, Shop, potion_rarity, roll_potions
from .potions import POTION_POOL


class Fixed:
    """An rng whose random() is a fixed value."""

    def __init__(self, v):
        self.v = v

    def random(self):
        return self.v


# Potion drops: 0.4 to start, -0.1 after a drop, +0.1 after none; elites +0.125.
o = PotionOdds()
assert o.roll(Fixed(0.39)) and abs(o.value - 0.3) < 1e-9
assert not o.roll(Fixed(0.35)) and abs(o.value - 0.4) < 1e-9
assert not PotionOdds().roll(Fixed(0.45)) and PotionOdds().roll(Fixed(0.45), elite=True)
# Rarity: Rare <= 0.10, Uncommon <= 0.35, else Common; multi-potion rolls don't repeat.
r = random.Random(0)
rar = Counter(potion_rarity(roll_potions(r)[0]) for _ in range(20000))
assert 0.62 < rar["COMMON"] / 20000 < 0.68 and 0.22 < rar["UNCOMMON"] / 20000 < 0.28 and 0.08 < rar["RARE"] / 20000 < 0.12, rar
assert all(len(set(roll_potions(random.Random(i), 3))) == 3 for i in range(200))
# Shop potions: 3, priced by rarity x U(0.95, 1.05).
band = {"COMMON": (48, 52), "UNCOMMON": (71, 79), "RARE": (95, 105)}
for seed in range(200):
    s = make_shop(random.Random(seed), RarityOdds(), 0, RelicBags(random.Random(seed)))
    assert len(s.potions) == 3 and len(set(s.potions)) == 3
    assert all(band[potion_rarity(p)][0] <= c <= band[potion_rarity(p)][1] for p, c in zip(s.potions, s.potion_prices))
# Run: no potion roll after the boss; drink Blood; buy into a free slot.
run = Run(random.Random(5))
assert run.potions == [None, None, None] and run.potion_drop is None
v = run.potion_odds.value
run.win("Boss")
assert run.potion_odds.value == v and run.potion_drop is None
drops = 0
for _ in range(400):
    run.win("Monster")
    drops += run.potion_drop is not None
assert 0.4 < drops / 400 < 0.6, drops  # converges on PotionRewardOdds.targetOdds = 0.5
run.potions, run.hp, run.max_hp = ["BLOOD_POTION", None, None], 40, 83
run.drink(0)
assert run.hp == 56 and run.potions == [None, None, None]
run.shop = Shop([None] * 5, [0] * 5, 75, potions=["FIRE_POTION", "ATTACK_POTION", None], potion_prices=[50, 50, 0])
run.gold, run.spent, run.potions = 60, 0, ["WEAK_POTION", None, None]
run.buy_potion(0)
assert run.potions == ["WEAK_POTION", "FIRE_POTION", None] and run.gold == 10 and run.spent == 50
assert run.shop.potions[0] is None
run.potion_drop = "BLOCK_POTION"
run.take_potion(0)  # replaces (discards) Weak Potion
assert run.potions[0] == "BLOCK_POTION" and run.potion_drop is None

# Relics: rarity roll, bags, shop stock, buying, elite and treasure drops.
from .act import roll_relic_rarity
from .relics import NOT_IN_SHOPS, NOT_MODELED, RELIC_POOL, RELICS, relic_rarity

rng = random.Random(0)
rolls = Counter(roll_relic_rarity(rng) for _ in range(20000))
assert abs(rolls["COMMON"] / 20000 - 0.50) < 0.02 and abs(rolls["UNCOMMON"] / 20000 - 0.33) < 0.02
assert abs(rolls["RARE"] / 20000 - 0.17) < 0.02
bags, seen = RelicBags(random.Random(1)), []
for i in range(122):
    seen.append(bags.pull("player" if i % 2 else "shared", "SHOP", from_back=i % 3 == 0))
assert len(set(seen)) == 122 and set(seen) == {r for ids in RELIC_POOL.values() for r in ids}
assert [relic_rarity(r) for r in seen[:26]] == ["SHOP"] * 26 and relic_rarity(seen[26]) == "COMMON"
# A rarity falls through when nothing in it passes the filter, not only when empty.
assert relic_rarity(RelicBags(random.Random(2)).pull("player", "SHOP", allowed=lambda r: relic_rarity(r) == "RARE")) == "RARE"
band = {"COMMON": (149, 201), "UNCOMMON": (191, 259), "RARE": (234, 316), "SHOP": (170, 230)}
stocked = set()
for seed in range(200):
    s = make_shop(random.Random(seed), RarityOdds(), 0, RelicBags(random.Random(seed + 1)))
    assert not set(s.relics) & NOT_IN_SHOPS and len(set(s.relics)) == 3 and relic_rarity(s.relics[2]) == "SHOP"
    assert all(band[relic_rarity(r)][0] <= p <= band[relic_rarity(r)][1] for r, p in zip(s.relics, s.relic_prices))
    stocked |= set(s.relics)
assert stocked & NOT_MODELED
run = Run(random.Random(9))
run.shop = Shop([None] * 5, [0] * 5, 75, relics=["ANCHOR", "WHETSTONE", None], relic_prices=[175, 175, 0])
run.gold = 174
for k, g in ((0, 174), (1, 500)):  # too poor; unmodeled
    run.gold = g
    try:
        run.buy_relic(k)
        raise SystemExit("illegal buy allowed")
    except AssertionError:
        pass
run.gold = 200
run.buy_relic(0)
assert run.gold == 25 and run.spent == 175 and run.shop.relics[0] is None and run.relic_log == [("ANCHOR", "shop")]
run = Run(random.Random(10))
run.win("Monster"); run.win("Boss")
assert run.relic_log == []
run.win("Elite")
assert len(run.relic_log) == 1 and run.relic_log[0][1] == "elite" and run.relics == {run.relic_log[0][0]}
t = next(n for n in run.map.nodes() if n.type == "Treasure")
run.node, run.gold = t.parents[0], 0
run.enter(t)
assert run.relic_log[-1][1] == "treasure" and len(run.relic_log) == 2 and 42 <= run.gold <= 52
# The bags don't touch a seed's map or encounter queue.
for seed in range(20):
    r, m = random.Random(seed), Run(random.Random(seed))
    mp = generate_map(r)
    assert m.normals == encounter_queue(r)[0] and [n.type for n in m.map.nodes()] == [n.type for n in mp.nodes()]

print("act self-check ok")
