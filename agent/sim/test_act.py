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
    drops += any(k == "potion" for k, _ in run.pending)
    run.pending.clear()
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
from .relics import IRONCLAD_RELICS, NOT_IN_SHOPS, NOT_MODELED, RELIC_POOL, RELICS, relic_rarity

rng = random.Random(0)
rolls = Counter(roll_relic_rarity(rng) for _ in range(20000))
assert abs(rolls["COMMON"] / 20000 - 0.50) < 0.02 and abs(rolls["UNCOMMON"] / 20000 - 0.33) < 0.02
assert abs(rolls["RARE"] / 20000 - 0.17) < 0.02
bags, seen = RelicBags(random.Random(1)), []
for i in range(122):
    shared = i >= 26 and i % 2 == 0 and any(bags.bags["shared"].values())  # the shared bag runs out first
    seen.append(bags.pull("shared" if shared else "player", "SHOP", from_back=i % 3 == 0))
assert len(set(seen)) == 122 and set(seen) == {r for ids in RELIC_POOL.values() for r in ids}
assert [relic_rarity(r) for r in seen[:26]] == ["SHOP"] * 26 and relic_rarity(seen[26]) == "COMMON"
# Treasure (shared bag) never gives Ironclad relics; the player bag can.
tr = [RelicBags(random.Random(k)).pull("shared", roll_relic_rarity(random.Random(k))) for k in range(300)]
assert not set(tr) & IRONCLAD_RELICS
assert any(RelicBags(random.Random(k)).pull("player", "RARE") in IRONCLAD_RELICS for k in range(100))
b = RelicBags(random.Random(3))
r = b.pull("player", "SHOP", allowed=lambda x: x == "BELT_BUCKLE")
assert r == "BELT_BUCKLE" and not any(r in l for l in b.bags["shared"].values())
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



# ---- Task 6: run-level relics, price, reward queue ----
from .act import offer, REWARD_POOLS
from .map import Node


def fresh(*relics, seed=1):
    r = Run(random.Random(seed))
    r.relics |= set(relics)
    return r


def room_of(run, kind):
    n = next(n for n in run.map.nodes() if n.type == kind)
    run.node = n.parents[0]
    return n


# obtain effects
for rel, mx in (("STRAWBERRY", 87), ("PEAR", 90), ("MANGO", 94)):
    r = fresh(); r.obtain(rel, "treasure")
    assert (r.hp, r.max_hp) == (mx, mx), rel
r = fresh(); r.hp = 40; r.obtain("LEES_WAFFLE", "shop")
assert (r.hp, r.max_hp) == (87, 87)
r = fresh(); r.gold = 99; r.obtain("OLD_COIN", "elite"); assert r.gold == 399
r = fresh("DRAGON_FRUIT"); r.obtain("OLD_COIN", "elite"); assert r.max_hp == 81 and r.hp == 81  # chain through gain_gold
r = fresh(); r.potions[1] = "FIRE_POTION"; r.obtain("POTION_BELT", "shop")
assert r.potions == [None, "FIRE_POTION", None, None, None]
r = fresh(); r.obtain("ORRERY", "shop")
assert [k for k, _ in r.pending] == ["cards"] * 5 and all(len(o) == 3 for _, o in r.pending)
r = fresh(); r.obtain("CAULDRON", "shop")
assert [k for k, _ in r.pending] == ["potion"] * 5

# win: Aubergine every fight room, Prayer Wheel Monster only, White Star Elite only
for room in ("Monster", "Elite", "Boss"):
    a, b = fresh(seed=4), fresh("AMETHYST_AUBERGINE", seed=4)
    a.gold = b.gold = 0
    a.win(room); b.win(room)
    assert b.gold == a.gold + 15, room
r = fresh("PRAYER_WHEEL"); r.win("Monster"); assert sum(k == "cards" for k, _ in r.pending) == 1
for room in ("Elite", "Boss"):
    r = fresh("PRAYER_WHEEL"); r.win(room); assert not any(k == "cards" for k, _ in r.pending), room
r = fresh("WHITE_STAR"); r.win("Monster"); assert not any(k == "cards" for k, _ in r.pending)
r = fresh("WHITE_STAR"); r.win("Boss"); assert r.pending == []
r = fresh("WHITE_STAR"); r.win("Elite")
extra = [o for k, o in r.pending if k == "cards"]
assert len(extra) == 1 and all(c in REWARD_POOLS["RARE"] for c in extra[0]) and r.card_odds.offset == -0.05
r = fresh("WHITE_STAR"); r.card_odds.offset = 0.2
offer(random.Random(0), r.card_odds, boss=True); assert r.card_odds.offset == -0.05
# White Beast Statue: potion every fight, odds still fall 0.1
r = fresh("WHITE_BEAST_STATUE")
for _ in range(20):
    r.win("Monster")
assert sum(k == "potion" for k, _ in r.pending) == 20 and abs(r.potion_odds.value - (0.4 - 2.0)) < 1e-9
o = PotionOdds(); assert o.roll(Fixed(0.99), force=True) and abs(o.value - 0.3) < 1e-9

# gold
r = fresh("BOWLER_HAT"); r.gold = 0; r.gain_gold(15); assert r.gold == 18
r = fresh("BOWLER_HAT"); r.gold = 0; r.gain_gold(10); assert r.gold == 12
r = fresh("DRAGON_FRUIT"); r.gain_gold(5); r.gain_gold(5); assert (r.hp, r.max_hp) == (82, 82)
r = fresh("BOWLER_HAT", "LUCKY_FYSH"); r.gold = 0; r.add_card("BASH"); assert r.gold == 18
r = fresh("LUCKY_FYSH"); r.gold = 0; r.add_card("BASH"); assert r.gold == 15 and r.deck[-1] == "BASH"
r.shop = Shop(["BASH"] + [None] * 4, [10] * 5, 75); r.gold = 100; r.buy(0); assert r.gold == 100 - 10 + 15
r = fresh("BOOK_OF_FIVE_RINGS"); r.hp = 30
for i in range(4):
    r.add_card("BASH")
assert r.hp == 30 and r.relic_state["book_of_five_rings"] == 4
r.add_card("BASH"); assert r.hp == 50
r = fresh("REGAL_PILLOW", seed=2); r.hp = 70; rest = room_of(r, "RestSite"); r.enter(rest); assert r.hp == 80  # capped
r = fresh(); r.relic_state.clear(); r.add_card("BASH"); assert r.relic_state == {}  # not held: no state

# enter
def visit(run, kind):
    """Enter a fresh `kind` node (a childless one, so the no-shop rule stays out of the way)."""
    n = Node(0, 2, kind)
    run.node = Node(0, 1, "Monster")
    run.node.children.append(n)
    return run.enter(n)


r = fresh("JUZU_BRACELET")
seen = Counter()
for i in range(500):
    r.unknown_odds, r.last_room = UnknownOdds(), None
    seen[visit(r, "Unknown")] += 1
assert "Monster" not in seen and len(seen) > 1, seen
assert any(visit(fresh(seed=i), "Unknown") == "Monster" for i in range(500))  # without Juzu it can roll Monster
r = fresh("PLANISPHERE")
for i in range(40):  # whatever the room rolls, +5
    r.hp = 50; r.last_room = None
    room = visit(r, "Unknown")
    assert r.hp == 55 or (room == "Treasure" and r.hp > 55), (room, r.hp)  # a treasure relic may add max HP
r.hp = 50; visit(r, "Monster"); assert r.hp == 50
r = fresh("MEAL_TICKET"); r.hp = 50; r.enter(room_of(r, "Shop")); assert r.hp == 65
r = fresh("MEAL_TICKET"); r.hp = 50; r.enter(room_of(r, "RestSite")); assert r.hp == 50 + 24
r = fresh("REGAL_PILLOW"); r.hp = 1; r.enter(room_of(r, "RestSite")); assert r.hp == 1 + 24 + 15
r = fresh("ETERNAL_FEATHER"); r.hp = 1; r.enter(room_of(r, "RestSite")); assert r.hp == 1 + 6 + 24  # deck of 10
r = fresh("ETERNAL_FEATHER"); r.hp = 1; r.enter(room_of(r, "Shop")); assert r.hp == 1
r = fresh("TINY_MAILBOX"); r.enter(room_of(r, "RestSite")); assert [k for k, _ in r.pending] == ["potion"] * 2
r = fresh("TINY_MAILBOX"); r.enter(room_of(r, "Shop")); assert r.pending == []
r = fresh("VENERABLE_TEA_SET"); r.enter(room_of(r, "RestSite")); assert r.relic_state["tea_set"] == 1
r = fresh("VENERABLE_TEA_SET"); r.enter(room_of(r, "Shop")); assert "tea_set" not in r.relic_state
r = fresh("DRAGON_FRUIT"); r.gold = 0; r.enter(room_of(r, "Treasure"))
assert r.max_hp == 81 and 42 <= r.gold <= 52

# price
r = fresh()
assert r.price(200) == 200
r.relics = {"MEMBERSHIP_CARD"}; assert r.price(200) == 100 and r.price(175) == 87
r.relics = {"THE_COURIER"}; assert r.price(200) == 160 and r.price(175) == 140
r.relics = {"MEMBERSHIP_CARD", "THE_COURIER"}; assert r.price(200) == 80 and r.price(175) == 70 and r.price(99) == 39
r = fresh(); r.shop = Shop([None] * 5, [0] * 5, 75, relics=["MEMBERSHIP_CARD", "ANCHOR", None], relic_prices=[200, 175, 0])
r.gold = 300; r.buy_relic(0); assert r.gold == 100 and r.spent == 200  # full price for itself
assert r.price(r.shop.relic_prices[1]) == 87
# every charge goes through price
r = fresh("MEMBERSHIP_CARD"); r.deck.append("STRIKE_IRONCLAD")
r.shop = Shop(["BASH"] + [None] * 4, [100] * 5, 75, potions=["FIRE_POTION", None, None], potion_prices=[50, 0, 0])
r.gold = 1000
r.buy(0); r.buy_potion(0); r.remove("STRIKE_IRONCLAD")
assert r.gold == 1000 - 50 - 25 - 37 and r.spent == 112

# Courier restock
r = fresh("THE_COURIER", seed=6)
r.shop = make_shop(random.Random(6), r.card_odds, 0, r.bags); r.gold = 9999
old = list(r.shop.cards)
k = next(i for i, c in enumerate(old) if c in CARDS)
r.buy(k)
assert r.shop.cards[k] is not None and card_type(r.shop.cards[k]) == SHOP_SLOTS[k]
assert r.shop.cards[k] not in old[:k] + old[k + 1:] and r.shop.prices[k] >= 47 and len(set(r.shop.cards)) == 5
r.buy_potion(1)
assert r.shop.potions[1] is not None
r.buy_relic(0)
assert r.shop.relics[0] is not None and r.shop.relic_prices[0] > 0 and r.shop.relics[0] not in r.relics
r.remove("STRIKE_IRONCLAD"); assert r.shop.removal_used
r = fresh(seed=6)  # no Courier: slots stay empty
r.shop = make_shop(random.Random(6), r.card_odds, 0, r.bags); r.gold = 9999
k = next(i for i, c in enumerate(r.shop.cards) if c in CARDS)
r.buy(k); r.buy_potion(1); r.buy_relic(0)
assert r.shop.cards[k] is None and r.shop.potions[1] is None and r.shop.relics[0] is None

# reward queue
r = fresh()
assert r.next_reward() is None
r.pending = [("cards", ["A"]), ("potion", "NOT_A_REAL_POTION"), ("potion", "FIRE_POTION"), ("cards", ["B"])]
assert r.next_reward() == ("cards", ["A"]) and r.potion_drop is None
assert r.next_reward() == ("potion", "FIRE_POTION") and r.potion_drop == "FIRE_POTION"
r.potion_drop = None
assert r.next_reward() == ("cards", ["B"]) and r.next_reward() is None
r.pending = [("potion", "NOT_A_REAL_POTION")]
assert r.next_reward() is None and r.potion_drop is None and r.pending == []
r = fresh(); r.win("Boss"); assert r.pending == []
for seed in range(50):
    r = fresh(seed=seed); r.win("Monster"); assert len(r.pending) <= 1 and all(k == "potion" for k, _ in r.pending)

# ---- Task 6 fixes ----
# 1. Orrery: base odds (Rare < 0.03, Uncommon < 0.37), the rarity offset never moves.
for off in (-0.05, 0.2):
    r = fresh(); r.card_odds.offset = off; r.obtain("ORRERY", "shop")
    assert r.card_odds.offset == off and len(r.pending) == 5
rb = Counter(RarityOdds().roll_base(Fixed(x)) for x in (0.029, 0.03, 0.369, 0.37, 0.99))
assert rb == {"RARE": 1, "UNCOMMON": 2, "COMMON": 2}, rb
rg = random.Random(0); ro = RarityOdds()
c = Counter(ro.roll_base(rg) for _ in range(20000))
assert abs(c["RARE"] / 20000 - 0.03) < 0.01 and abs(c["UNCOMMON"] / 20000 - 0.34) < 0.02 and ro.offset == -0.05, c
# 2. Courier refill never re-offers the card just bought (it still counts as taken).
for seed in range(150):
    r = fresh("THE_COURIER", seed=seed)
    r.shop = make_shop(random.Random(seed), r.card_odds, 0, r.bags); r.gold = 9999
    for k in range(5):
        if r.shop.cards[k] in CARDS:
            bought = r.shop.cards[k]
            r.buy(k)
            assert r.shop.cards[k] != bought and len(set(r.shop.cards)) == 5, (seed, k)
# 3. Relics won from an elite don't touch that elite's rewards, only the next one.
r = fresh(seed=2)
r.bags.pull = lambda *a, **k: "WHITE_STAR"
r.win("Elite")
assert not any(k == "cards" for k, _ in r.pending)
r.bags.pull = lambda *a, **k: "ANCHOR"
r.pending.clear(); r.win("Elite")
assert sum(k == "cards" for k, _ in r.pending) == 1
r = fresh(seed=2); r.bags.pull = lambda *a, **k: "WHITE_BEAST_STATUE"
r.potion_odds.value = -5.0  # never drops by chance
r.win("Elite"); assert r.pending == [] and abs(r.potion_odds.value + 5.0 - 0.1) < 1e-9
r.win("Elite"); assert [k for k, _ in r.pending] == ["potion"]
# 4. A chest's gold is awarded before its relic.
r = fresh(seed=2); r.gold = 0; r.bags.pull = lambda *a, **k: "BOWLER_HAT"
r.enter(room_of(r, "Treasure")); assert 42 <= r.gold <= 52 and "BOWLER_HAT" in r.relics
r = fresh(seed=2); r.bags.pull = lambda *a, **k: "DRAGON_FRUIT"
r.enter(room_of(r, "Treasure")); assert r.max_hp == 80 and "DRAGON_FRUIT" in r.relics

print("act self-check ok")

# --- events: each against its source in decompiled/MegaCrit.Sts2.Core.Models.Events ---------------------
from .act import QUEST_CARD, Run, potion_rarity
from .cards import CARDS
from .engine import PLAYER_MAX_HP
from .events import EVENT_ALLOWED, MODELED_EVENTS
from .relics import RELICS


def ev(name, **kw):
    r = Run(random.Random(7))
    for k, v in kw.items():
        setattr(r, k, v)
    r.start_event(name)
    assert r.event == name
    return r


assert len(EVENT_ALLOWED) == 21 and set(MODELED_EVENTS) <= set(EVENT_ALLOWED)
assert sorted(Run(random.Random(1)).events) == sorted(EVENT_ALLOWED)
assert Run(random.Random(1)).events != Run(random.Random(2)).events

# Byrdonis Nest: +7 max HP, or an Unplayable card.
r = ev("BYRDONIS_NEST", hp=50)
r.choose_event(0)
assert (r.hp, r.max_hp, r.event) == (50 + 7, PLAYER_MAX_HP + 7, None)
r = ev("BYRDONIS_NEST")
n = len(r.deck)
r.choose_event(1)
assert r.deck[-1] == QUEST_CARD and len(r.deck) == n + 1 and CARDS[QUEST_CARD].cost == -1

# Jungle Maze: solo is 18 HP for 135-165 gold, joining is free for 35-65; GainGold truncates after Bowler Hat.
for s in range(200):
    r = Run(random.Random(s))
    r.start_event("JUNGLE_MAZE_ADVENTURE")
    (hp, solo, _), (_, join, _) = r.event_opts
    assert hp == 18 and 135 <= solo < 165 and 35 <= join < 65
r.hp, g = 50, r.gold
r.choose_event(0)
assert r.hp == 32 and r.gold == g + int(solo)
r = ev("JUNGLE_MAZE_ADVENTURE", hp=18, gold=10)  # damage comes first, so a death takes no gold
r.choose_event(0)
assert r.hp == 0 and r.gold == 10
r = ev("JUNGLE_MAZE_ADVENTURE", gold=0, hp=5)
join = r.event_opts[1][1]
r.choose_event(1)
assert r.hp == 5 and r.gold == int(join)
r = ev("JUNGLE_MAZE_ADVENTURE", gold=0)  # (int)(150.7 * 1.25), not int(150.7) * 5 // 4
r.relics.add("BOWLER_HAT")
r.event_opts = [(18, 150.7, 0), (0, 50, 0)]
r.choose_event(0)
assert r.gold == 188

# Sunken Statue: the sword does nothing; diving pays gold first, then 7 HP.
r = ev("SUNKEN_STATUE")
r.choose_event(0)
assert "SWORD_OF_STONE" in r.relics and r.relic_log[-1] == ("SWORD_OF_STONE", "event") and "SWORD_OF_STONE" not in RELICS
golds = set()
for s in range(300):
    r = Run(random.Random(s))
    r.start_event("SUNKEN_STATUE")
    golds.add(r.event_opts[1][1])
assert golds == set(range(101, 122))
r = ev("SUNKEN_STATUE", hp=7, gold=0)
r.relics.add("DRAGON_FRUIT")  # gold first: Dragon Fruit's +1 max HP also heals 1, so 7 damage leaves 1
r.choose_event(1)
assert r.hp == 1 and r.gold > 0

# The Legends Were True: the Unplayable map, or 8 HP for a potion picked uniformly from both pools.
r = ev("THE_LEGENDS_WERE_TRUE", hp=40)
r.choose_event(1)
assert r.hp == 32 and r.pending[-1][0] == "potion" and r.event is None
r = ev("THE_LEGENDS_WERE_TRUE", hp=40)
r.choose_event(0)
assert r.hp == 40 and r.deck[-1] == QUEST_CARD and not r.pending
picks = Counter()
for s in range(4800):
    r = Run(random.Random(s))
    r.start_event("THE_LEGENDS_WERE_TRUE")
    r.hp = 40
    r.choose_event(1)
    picks[potion_rarity(r.pending[-1][1])] += 1
assert all(1400 < picks[k] < 1800 for k in ("COMMON", "UNCOMMON", "RARE")), picks  # 16 of each, not rarity-weighted

# Slippery Bridge: first roll skips Basic cards; holding costs 3, 4, 5 ... and never re-offers that card id or copy.
deck = ["STRIKE_IRONCLAD", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "BASH", "ANGER", "ANGER", "BLOODLETTING"]
for s in range(100):
    r = Run(random.Random(s))
    r.deck = list(deck)
    r.start_event("SLIPPERY_BRIDGE")
    assert r.deck[r.bridge_card] in ("ANGER", "BLOODLETTING")
    r.hp, first = 50, r.deck[r.bridge_card]
    r.choose_event(1)
    assert r.hp == 47 and r.event == "SLIPPERY_BRIDGE" and r.deck[r.bridge_card] != first and r.event_opts[1][0] == 4
    r.choose_event(1)
    assert r.hp == 43 and r.event_opts[1][0] == 5
    at_risk, n = r.deck[r.bridge_card], len(r.deck)
    r.choose_event(0)
    assert r.event is None and len(r.deck) == n - 1 and r.deck.count(at_risk) == deck.count(at_risk) - 1
r = Run(random.Random(3))  # all Basic: falls back to the whole deck
r.deck = ["STRIKE_IRONCLAD", "DEFEND_IRONCLAD"]
r.start_event("SLIPPERY_BRIDGE")
assert r.bridge_card in (0, 1)
r = Run(random.Random(3))  # everything skipped: a skipped card comes back
r.deck = ["ANGER"]
r.start_event("SLIPPERY_BRIDGE")
r.hp = 80
for _ in range(3):
    r.choose_event(1)
assert r.bridge_card == 0 and r.event == "SLIPPERY_BRIDGE"
r = ev("SLIPPERY_BRIDGE", hp=3, deck=list(deck))  # a lethal hold ends the run
r.choose_event(1)
assert r.hp == 0

# Damage outside combat: Tungsten Rod applies, Beating Remnant doesn't, Lizard Tail saves once.
r = ev("SUNKEN_STATUE", hp=50)
r.relics |= {"TUNGSTEN_ROD", "BEATING_REMNANT"}
r.lose_hp(30)
assert r.hp == 21
r = Run(random.Random(1))
r.relics.add("LIZARD_TAIL")
r.hp = 5
r.lose_hp(8)
assert r.hp == PLAYER_MAX_HP // 2 and r.relic_state["lizard_used"] == 1
r.hp = 5
r.lose_hp(8)
assert r.hp == 0
r = Run(random.Random(1))
r.relics.add("TUNGSTEN_ROD")
r.hp = 10
r.lose_hp(1)
assert r.hp == 10

# Pull order: IsAllowed and seen events are skipped, the skipped stay behind, and nothing repeats until all are seen.
r = Run(random.Random(5))
r.events = ["TEA_MASTER", "UNREST_SITE", "SUNKEN_STATUE", "THIS_OR_THAT"]
r.gold, r.hp = 0, r.max_hp
assert r.pull_event() == "SUNKEN_STATUE" and r.pull_event() == "THIS_OR_THAT"
r.gold, r.hp = 200, 10  # now allowed: the index wraps back to them
assert r.pull_event() == "TEA_MASTER" and r.pull_event() == "UNREST_SITE"
assert r.pull_event() in r.events  # all seen: the game logs a warning and repeats
r = Run(random.Random(5))
r.events = ["SLIPPERY_BRIDGE", "THIS_OR_THAT"]
r.node = next(n for n in r.map.grid.values() if n.row == 6)
assert r.pull_event() == "THIS_OR_THAT"  # TotalFloor 6 is not > 6
r = Run(random.Random(5))
r.events = ["SLIPPERY_BRIDGE", "THIS_OR_THAT"]
r.node = next(n for n in r.map.grid.values() if n.row == 7)
assert r.pull_event() == "SLIPPERY_BRIDGE"
assert not EVENT_ALLOWED["THE_LEGENDS_WERE_TRUE"](type("R", (), {"deck": ["BASH"], "hp": 9}))
assert EVENT_ALLOWED["UNREST_SITE"](type("R", (), {"hp": 56, "max_hp": 80}))  # exactly 70%
assert not EVENT_ALLOWED["UNREST_SITE"](type("R", (), {"hp": 57, "max_hp": 80}))

# Unmodeled events are empty rooms that still use up the pool.
r = Run(random.Random(5))
r.start_event("TEA_MASTER")
assert r.event is None
print("event checks ok")
