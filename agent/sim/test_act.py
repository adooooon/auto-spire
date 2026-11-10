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
    assert len(s.cards) == len(SHOP_SLOTS) + 2 and len(set(s.cards)) == len(s.cards)
    assert [card_type(c) for c in s.cards[:5]] == list(SHOP_SLOTS)
    assert s.removal_price == 75 + 25 * 2 and not s.removal_used
    assert all(23 <= p <= 181 for p in s.prices)

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
assert run.hp == 40  # entering heals nothing now
run.rest("HEAL")
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
# Run: no potion roll after the last boss; drink Blood; buy into a free slot.
run = Run(random.Random(5))
assert run.potions == [None, None, None] and run.potion_drop is None
v = run.potion_odds.value
run.act = 1
run.win("Boss")
run.act = 0
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
run.shop = Shop([None] * 5, [0] * 5, 75, relics=["ANCHOR", "KIFUDA", None], relic_prices=[175, 175, 0])
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
r = fresh("REGAL_PILLOW", seed=2); r.hp = 70; rest = room_of(r, "RestSite"); r.enter(rest); r.rest("HEAL"); assert r.hp == 80  # capped
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
r = fresh("MEAL_TICKET"); r.hp = 50; r.enter(room_of(r, "RestSite")); r.rest("HEAL"); assert r.hp == 50 + 24
r = fresh("REGAL_PILLOW"); r.hp = 1; r.enter(room_of(r, "RestSite")); assert r.hp == 1; r.rest("HEAL"); assert r.hp == 1 + 24 + 15
r = fresh("ETERNAL_FEATHER"); r.hp = 1; r.enter(room_of(r, "RestSite")); assert r.hp == 1 + 6; r.rest("HEAL"); assert r.hp == 1 + 6 + 24  # deck of 10
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
assert r.shop.cards[k] not in old[:k] + old[k + 1:] and r.shop.prices[k] >= 47 and len(set(r.shop.cards)) == 7
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
            assert r.shop.cards[k] != bought and len(set(r.shop.cards)) == 7, (seed, k)
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

# --- Act 2 ------------------------------------------------------------------------------------
from sim.act import HIVE_BOSSES, HIVE_ELITES, HIVE_NORMALS, HIVE_WEAK
from sim.events import HIVE_EVENT_ALLOWED

run = Run(random.Random(7))
run.hp, run.gold = 30, 200
deck = list(run.deck)
offered = run.win("Boss")
assert run.gold >= 300 and len(offered) == 3 and all(CARDS[c].rarity == "Rare" for c in offered if c in CARDS), offered
run.next_act()
m = run.map
assert run.act == 1 and run.node is m.start and run.hp == run.max_hp and run.deck == deck
assert m.boss.row == 15 and all(n.row <= 14 for n in m.nodes()) and all(n.type == "RestSite" for n in m.row(14))
assert all(n.type == "Treasure" for n in m.row(8)) and all(n.type == "Monster" for n in m.row(1))  # GetRowCount - 7
assert run.boss in HIVE_BOSSES and set(run.normals[:2]) <= set(HIVE_WEAK) and set(run.normals[2:]) <= set(HIVE_NORMALS)
assert set(run.elites) <= set(HIVE_ELITES) and len(run.normals) == 14
assert set(run.events) == set(HIVE_EVENT_ALLOWED) and "THE_LEGENDS_WERE_TRUE" not in run.events
assert run.encounter("Boss") == run.boss and run.encounter("Elite") in HIVE_ELITES
assert run.win("Boss") == []  # after Act 2's boss the sim's run ends
# A seed's Act 1 map doesn't change for having an Act 2.
assert [(n.col, n.row, n.type) for n in Run(random.Random(3)).map.nodes()] == [(n.col, n.row, n.type) for n in generate_map(random.Random(3)).nodes()]
print("act 2 checks ok")

# Upgrades in the run. BASELINE: Act 1 map hash, first encounters, boss and first 3 offers per seed, captured from HEAD 24cf704
# (before upgrades existed). The upgrade roll must not move any of it at act 0.
import hashlib
BASELINE = {
    0: ('9c08dffe', ['FUZZY_WURM_CRAWLER_WEAK', 'SHRINKER_BEETLE_WEAK', 'SLIMES_WEAK', 'FOGMOG_NORMAL'], ['BYGONE_EFFIGY_ELITE', 'PHROG_PARASITE_ELITE'], 'VANTOM_BOSS', [['BREAKTHROUGH', 'POMMEL_STRIKE', 'IRON_WAVE'], ['MOLTEN_FIST', 'BLUDGEON', 'ANGER'], ['BURNING_PACT', 'JUGGLING', 'BREAKTHROUGH']]),
    1: ('48aa48c5', ['NIBBITS_WEAK', 'SLIMES_WEAK', 'FUZZY_WURM_CRAWLER_WEAK', 'SLIMES_NORMAL'], ['BYGONE_EFFIGY_ELITE', 'BYRDONIS_ELITE'], 'THE_KIN_BOSS', [['ARMAMENTS', 'HOWL_FROM_BEYOND', 'SHRUG_IT_OFF'], ['TRUE_GRIT', 'STONE_ARMOR', 'THUNDERCLAP'], ['UPPERCUT', 'OFFERING', 'STAMPEDE']]),
    2: ('bf4a063f', ['FUZZY_WURM_CRAWLER_WEAK', 'SHRINKER_BEETLE_WEAK', 'NIBBITS_WEAK', 'SLIMES_NORMAL'], ['PHROG_PARASITE_ELITE', 'BYGONE_EFFIGY_ELITE'], 'THE_KIN_BOSS', [['WHIRLWIND', 'TREMBLE', 'VICIOUS'], ['BREAKTHROUGH', 'ASHEN_STRIKE', 'DRUM_OF_BATTLE'], ['STONE_ARMOR', 'BULLY', 'SETUP_STRIKE']]),
    3: ('468c5aa2', ['SLIMES_WEAK', 'NIBBITS_WEAK', 'FUZZY_WURM_CRAWLER_WEAK', 'SLIMES_NORMAL'], ['BYGONE_EFFIGY_ELITE', 'BYRDONIS_ELITE'], 'THE_KIN_BOSS', [['VICIOUS', 'UPPERCUT', 'SWORD_BOOMERANG'], ['INFERNO', 'BREAKTHROUGH', 'COLOSSUS'], ['BLOODLETTING', 'PRIMAL_FORCE', 'BURNING_PACT']]),
    4: ('99225357', ['SHRINKER_BEETLE_WEAK', 'FUZZY_WURM_CRAWLER_WEAK', 'SLIMES_WEAK', 'SLITHERING_STRANGLER_NORMAL'], ['BYRDONIS_ELITE', 'PHROG_PARASITE_ELITE'], 'THE_KIN_BOSS', [['IRON_WAVE', 'TREMBLE', 'FIGHT_ME'], ['SETUP_STRIKE', 'TWIN_STRIKE', 'PERFECTED_STRIKE'], ['SECOND_WIND', 'BLOODLETTING', 'RAGE']]),
    5: ('84e47693', ['FUZZY_WURM_CRAWLER_WEAK', 'SHRINKER_BEETLE_WEAK', 'NIBBITS_WEAK', 'FLYCONID_NORMAL'], ['BYGONE_EFFIGY_ELITE', 'BYRDONIS_ELITE'], 'THE_KIN_BOSS', [['JUGGLING', 'BLOOD_WALL', 'HAVOC'], ['HAVOC', 'THUNDERCLAP', 'TRUE_GRIT'], ['SETUP_STRIKE', 'BREAKTHROUGH', 'PERFECTED_STRIKE']]),
    6: ('60de06ad', ['SLIMES_WEAK', 'SHRINKER_BEETLE_WEAK', 'NIBBITS_WEAK', 'MAWLER_NORMAL'], ['BYRDONIS_ELITE', 'PHROG_PARASITE_ELITE'], 'THE_KIN_BOSS', [['INFERNAL_BLADE', 'BREAKTHROUGH', 'BATTLE_TRANCE'], ['ARMAMENTS', 'SPITE', 'THUNDERCLAP'], ['THUNDERCLAP', 'SWORD_BOOMERANG', 'FEEL_NO_PAIN']]),
    7: ('be408782', ['FUZZY_WURM_CRAWLER_WEAK', 'NIBBITS_WEAK', 'SLIMES_WEAK', 'INKLETS_NORMAL'], ['BYRDONIS_ELITE', 'BYGONE_EFFIGY_ELITE'], 'THE_KIN_BOSS', [['THUNDERCLAP', 'VICIOUS', 'STONE_ARMOR'], ['BODY_SLAM', 'TWIN_STRIKE', 'COLOSSUS'], ['ANGER', 'BURNING_PACT', 'THUNDERCLAP']]),
    8: ('cf6d85e4', ['SHRINKER_BEETLE_WEAK', 'NIBBITS_WEAK', 'FUZZY_WURM_CRAWLER_WEAK', 'MAWLER_NORMAL'], ['PHROG_PARASITE_ELITE', 'BYGONE_EFFIGY_ELITE'], 'CEREMONIAL_BEAST_BOSS', [['TREMBLE', 'SWORD_BOOMERANG', 'CINDER'], ['TWIN_STRIKE', 'TREMBLE', 'CINDER'], ['MOLTEN_FIST', 'SHRUG_IT_OFF', 'TREMBLE']]),
    9: ('1d4c4eb6', ['NIBBITS_WEAK', 'SLIMES_WEAK', 'SHRINKER_BEETLE_WEAK', 'INKLETS_NORMAL'], ['PHROG_PARASITE_ELITE', 'BYGONE_EFFIGY_ELITE'], 'CEREMONIAL_BEAST_BOSS', [['THUNDERCLAP', 'TRUE_GRIT', 'PERFECTED_STRIKE'], ['TREMBLE', 'SWORD_BOOMERANG', 'WHIRLWIND'], ['THUNDERCLAP', 'BLOOD_WALL', 'PILLAGE']]),
}

from .act import Run, Shop, offer
from .cards import CARDS, UPGRADABLE, base_id, is_upgraded

for seed, (h, normals, elites, boss, offers) in BASELINE.items():
    r = Run(random.Random(seed))
    assert hashlib.md5(repr([(n.row, n.col, n.type) for n in r.map.nodes()]).encode()).hexdigest()[:8] == h, seed
    assert (r.normals[:4], r.elites[:2], r.boss) == (normals, elites, boss), seed
    assert [offer(r.rng, r.card_odds) for _ in range(3)] == offers, seed  # act 0: no upgrade roll, same draws
assert not any(is_upgraded(c) for s in range(30) for c in offer(random.Random(s), RarityOdds(), act=0))

# Reward upgrades: act x 0.25 for non-Rares, never Rares.
rng, odds, tot, up, rare_up = random.Random(5), RarityOdds(), 0, 0, 0
for _ in range(4000):
    o = offer(rng, odds, act=1)
    assert len({base_id(c) for c in o}) == len(o), o  # the game blacklists by base card
    for c in o:
        if CARDS[base_id(c)].rarity == "Rare":
            rare_up += is_upgraded(c)
        else:
            tot, up = tot + 1, up + is_upgraded(c)
assert rare_up == 0 and 0.22 <= up / tot <= 0.28, (up, tot, rare_up)
r = Run(random.Random(0)); r.act = 1
assert any(is_upgraded(c) for _ in range(60) for c in r.win("Monster"))  # Run.win passes the act through

# Shops never upgrade; Armaments is stockable.
for s in range(200):
    shop = make_shop(random.Random(s), RarityOdds(), 0, RelicBags(random.Random(s)))
    assert not any(is_upgraded(c) for c in shop.cards)

# Smith and Heal.
r = fresh(); r.deck = ["BASH", "STRIKE_IRONCLAD", "BASH"]
assert r.rest_options() == ["HEAL", "SMITH"]
r.rest("SMITH", "BASH"); assert r.deck == ["BASH+", "STRIKE_IRONCLAD", "BASH"]
r.rest("SMITH", "BASH"); assert r.deck == ["BASH+", "STRIKE_IRONCLAD", "BASH+"]
r.rest("SMITH", "STRIKE_IRONCLAD"); assert all(is_upgraded(c) for c in r.deck)
assert r.rest_options() == ["HEAL"]
r.deck = ["BASH+", "WOUND", "ASCENDERS_BANE"] if "ASCENDERS_BANE" in CARDS else ["BASH+", "WOUND"]
assert r.rest_options() == ["HEAL"]  # nothing upgradable
r = fresh(); r.hp = 1; r.rest("HEAL"); assert r.hp == 1 + 24  # 30% of 80, truncated
r = fresh("REGAL_PILLOW"); r.hp = 1; r.rest("HEAL"); assert r.hp == 1 + 24 + 15

# Whetstone / War Paint: 2 random un-upgraded Attacks / Skills now.
r = fresh(); r.deck = ["STRIKE_IRONCLAD"] * 5 + ["DEFEND_IRONCLAD"] * 4 + ["BASH"]; r.obtain("WHETSTONE", "treasure")
assert sum(is_upgraded(c) for c in r.deck) == 2 and all(CARDS[c].type == "Attack" for c in r.deck if is_upgraded(c))
r = fresh(); r.deck = ["STRIKE_IRONCLAD"] * 5 + ["DEFEND_IRONCLAD"] * 4 + ["BASH"]; r.obtain("WAR_PAINT", "treasure")
assert sum(is_upgraded(c) for c in r.deck) == 2 and all(CARDS[c].type == "Skill" for c in r.deck if is_upgraded(c))
r = fresh(); r.deck = ["BASH+", "DEFEND_IRONCLAD"]; r.obtain("WHETSTONE", "treasure"); assert r.deck == ["BASH+", "DEFEND_IRONCLAD"]
r = fresh(); r.deck = ["BASH", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD"]; r.obtain("WHETSTONE", "treasure")
assert r.deck == ["BASH+", "STRIKE_IRONCLAD+", "DEFEND_IRONCLAD"]  # fewer than 2 left: all of them

# Eggs upgrade the matching type as it is added (rewards and purchases alike).
for egg, kind in (("MOLTEN_EGG", "Attack"), ("TOXIC_EGG", "Skill"), ("FROZEN_EGG", "Power")):
    r = fresh(egg); r.deck = []
    for c in ("BASH", "DEFEND_IRONCLAD", "INFLAME"):
        r.add_card(c)
    assert r.deck == [c + "+" if CARDS[c].type == kind else c for c in ("BASH", "DEFEND_IRONCLAD", "INFLAME")], (egg, r.deck)
r = fresh("MOLTEN_EGG"); r.add_card("BASH+"); assert r.deck[-1] == "BASH+"

# Girya: LIFT up to 3 times, then gone; the count is the fight's Strength. Shovel: DIG is a relic, any number of times.
r = fresh("GIRYA")
for i in range(3):
    assert "LIFT" in r.rest_options(); r.rest("LIFT"); assert r.relic_state["girya"] == i + 1
assert "LIFT" not in r.rest_options()
r = fresh("SHOVEL"); r.deck = ["BASH+"]
assert r.rest_options() == ["HEAL", "DIG"]
r.rest("DIG"); r.rest("DIG")
assert len(r.relic_log) == 2 and all(src == "dig" for _, src in r.relic_log) and len(r.relics) == 3
r = fresh("GIRYA", "SHOVEL"); assert r.rest_options() == ["HEAL", "SMITH", "LIFT", "DIG"]
print("upgrade checks ok")

# Eggs upgrade the offered and shop cards themselves (any rarity), at the same price; no Egg: nothing upgraded.
from .act import egg_upgrade
assert egg_upgrade("BASH", {"MOLTEN_EGG"}) == "BASH+" and egg_upgrade("BASH", {"TOXIC_EGG"}) == "BASH"
assert egg_upgrade("INFLAME", {"FROZEN_EGG"}) == "INFLAME+" and egg_upgrade("BASH+", {"MOLTEN_EGG"}) == "BASH+"
for egg, kind in (("MOLTEN_EGG", "Attack"), ("TOXIC_EGG", "Skill"), ("FROZEN_EGG", "Power")):
    r = fresh(egg); r.act = 0
    seen = [c for _ in range(300) for c in r.win("Monster")] + [c for _ in range(100) for c in r.win("Boss")]
    assert all(is_upgraded(c) == (CARDS[base_id(c)].type == kind) for c in seen), egg
    assert any(is_upgraded(c) and CARDS[base_id(c)].rarity == "Rare" for c in seen), egg  # Rares too
    for s in range(100):
        sh = make_shop(random.Random(s), RarityOdds(), 0, RelicBags(random.Random(s)), {egg})
        assert all(is_upgraded(c) == (CARDS[base_id(c)].type == kind) for c in sh.cards), egg
        plain = make_shop(random.Random(s), RarityOdds(), 0, RelicBags(random.Random(s)))
        assert [base_id(c) for c in sh.cards] == plain.cards and sh.prices == plain.prices  # same draws, same prices
r = fresh("MOLTEN_EGG"); r.gold = 999; r.shop = make_shop(random.Random(3), RarityOdds(), 0, RelicBags(random.Random(3)), {"MOLTEN_EGG"})
slot = next(i for i, c in enumerate(r.shop.cards) if is_upgraded(c)); up = r.shop.cards[slot]; r.buy(slot); assert r.deck[-1] == up  # not upgraded twice

# Lava Lamp: after a fight with no blockable hit, every offered card (Rares too) is upgraded; after a hit, none.
r = fresh("LAVA_LAMP"); r.fight_hit = False
offered = [c for _ in range(100) for c in r.win("Monster")]
assert offered and all(is_upgraded(c) for c in offered if c in UPGRADABLE or c + "+" in CARDS)
r = fresh("LAVA_LAMP"); r.fight_hit = True
assert not any(is_upgraded(c) for _ in range(50) for c in r.win("Monster"))
r = fresh(); r.fight_hit = False
assert not any(is_upgraded(c) for _ in range(50) for c in r.win("Monster"))  # no lamp
r = fresh("LAVA_LAMP"); r.fight_hit = False; r.win("Elite")
r.shop = make_shop(random.Random(1), RarityOdds(), 0, RelicBags(random.Random(1)), r.relics)
assert not any(is_upgraded(c) for c in r.shop.cards)  # shops: not a CombatRoom
print("egg and lava lamp checks ok")

# --- colorless shop slots ---------------------------------------------------------------------------------
from .act import SHOP_COLORLESS
from .cards import COLORLESS, NOT_BUYABLE
seen = set()
for seed in range(2000):
    s = make_shop(random.Random(seed), RarityOdds(), 0, RelicBags(random.Random(seed)))
    for card, price, rarity in zip(s.cards[5:], s.prices[5:], SHOP_COLORLESS):
        assert card in COLORLESS and CARDS[card].rarity == rarity, (card, rarity)
        assert round((86 if rarity == "Uncommon" else 172) * 0.95) <= price <= round((86 if rarity == "Uncommon" else 172) * 1.05) + 1
        seen.add(card)
    assert s.cards[5] != s.cards[6]
assert seen >= set(COLORLESS) - {"SPLASH", "ALCHEMIZE"} and seen & NOT_BUYABLE  # unbuyable ones still stock

# Buying: into the deck; The Courier restocks the same rarity; the unbuyable can't be bought.
r = fresh(); r.gold = 500
r.shop = make_shop(random.Random(3), RarityOdds(), 0, RelicBags(random.Random(3)))
r.shop.cards[5], r.shop.prices[5] = "MAYHEM", 172
r.buy(5)
assert r.deck[-1] == "MAYHEM" and r.gold == 500 - 172 and r.shop.cards[5] is None
r = fresh("THE_COURIER"); r.gold = 500
r.shop = make_shop(random.Random(4), RarityOdds(), 0, RelicBags(random.Random(4)))
r.shop.cards[6] = "MAYHEM"; r.buy(6)
assert r.shop.cards[6] != "MAYHEM" and CARDS[r.shop.cards[6]].rarity == "Rare" and CARDS[r.shop.cards[6]].colorless
r.shop.cards[5] = "SPLASH"
try:
    r.buy(5); raise SystemExit("bought Splash")
except AssertionError:
    pass
r = fresh("MOLTEN_EGG"); r.shop = make_shop(random.Random(5), RarityOdds(), 0, RelicBags(random.Random(5)), r.relics)
assert all(is_upgraded(c) or c in ("SPLASH", "ALCHEMIZE") or CARDS[c].type != "Attack" for c in r.shop.cards[5:])
print("colorless shop checks ok")
