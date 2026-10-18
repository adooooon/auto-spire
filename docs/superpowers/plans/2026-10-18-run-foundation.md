# Run Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simulated Act 1 runs on generated maps, with gold, shops (cards and card removal) and a learned run policy that makes every out-of-combat choice, played on top of a frozen combat policy.

**Architecture:**
- **`sim/map.py`** generates Overgrowth maps (a port of `StandardActMap`).
- **`sim/act.py`** holds the run between fights: gold, deck, HP, encounter queue, "?" rolls, shop, rewards.
- **`run_env.py`** is a Gymnasium env where one step is one decision. Fights inside it are played by a frozen MaskablePPO combat model through the existing `STS2CombatEnv` + `SimClient`.
- **`train.py`** trains the run policy.
- **`run.py`** scores the run policy against a scripted baseline on the same seeded maps.
- **`MapRunModeEnv`** then retrains combat on the decks the run policy builds.

**Tech Stack:** Python 3.13 (`.venv`), gymnasium, stable-baselines3 + sb3-contrib MaskablePPO, numpy, torch (CPU).

**Spec:** `docs/superpowers/specs/2026-10-18-run-foundation-design.md`

## Global Constraints

- Work in `/Users/adenhsu/projects/sts2-rl-bot/auto-spire` on branch `rl-agent-sim`. Never push.
- Python is `../.venv/bin/python`, run from `agent/`. Never `pip install` outside `.venv`.
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Leave `mod/AutoSpire/obj/*` uncommitted.
- Never commit `decompiled/`, game binaries or models (`agent/models/` is gitignored).
- Game facts go in `docs/game-architecture.md`, progress and results in `docs/modding-approach.md`. Don't duplicate between them.
- Act 1 (Overgrowth) only, ascension 0. Rest sites stay heal-only, and there are no potions, relics or events (they're empty placeholders).
- Tests are assert-based scripts in the style of `agent/sim/test_engine.py`. No pytest.
- `ponytail:` comments mark deliberate simplifications, naming the ceiling and the upgrade path.

## Review Focus

1. **A sim exception inside a fight** (like the Pillage hang): the run ends as a loss and the env keeps working. Pinned in Task 1 (combat env) and Task 4 (run env).
2. **A card offer made only of unmodeled prompt cards** (Armaments, Headbutt, Brand, Burning Pact): only "skip" is legal, and the mask is never empty. Pinned in Task 4.
3. **A shop the player can't afford anything in**: only "leave" is legal, and removal is masked once used or unaffordable. Pinned in Task 4.
4. **Max HP changed by a fight** (Feed): it carries to later fights, and rest sites heal 30% of the new max. Pinned in Task 3 (rest) and Task 4 (fight sync).
5. **Same seed, same map:** baseline and policy are compared on identical maps. Pinned in Task 2 (map) and Task 4 (env reset).

---

## File structure

| File | Status | Responsibility |
|---|---|---|
| `agent/sim/engine.py` | modify | `SimLoopError` guard on reshuffles |
| `agent/env.py` | modify | catch `SimLoopError` → aborted episode |
| `agent/sim/map.py` | create | Overgrowth map generation |
| `agent/sim/act.py` | create | run state, encounter queue, "?" odds, shop, rewards; `RarityOdds`/`offer`/`REWARD_POOLS` move here from `picker.py` |
| `agent/picker.py` | modify | import `RarityOdds`, `offer`, `REWARD_POOLS` from `sim.act` |
| `agent/sim/test_act.py` | create | map and run-rule self-checks |
| `agent/run_env.py` | create | `RunPolicyEnv` |
| `agent/test_run_env.py` | create | env guard + run env smoke tests |
| `agent/train.py` | modify | `--run-policy --combat-model`, `--run-model` |
| `agent/run.py` | modify | `--maps generated` evaluation; `MapRunModeEnv` |
| `docs/game-architecture.md` | modify | "Act 1 runs" game facts |
| `docs/modding-approach.md` | modify | results |

---

### Task 1: Fail-safe for sim infinite loops

**Files:**
- Modify: `agent/sim/engine.py` (module constants near `MAX_HAND_SIZE`; `SimCombat.fight` at ~line 445; `SimCombat._take_top` at ~line 780)
- Modify: `agent/env.py:26-27` (imports) and `agent/env.py:228-276` (`step`'s `except`)
- Modify: `agent/sim/test_engine.py` (append before the final `print`)
- Create: `agent/test_run_env.py`

**Interfaces:**
- Produces: `sim.engine.SimLoopError(RuntimeError)` and `sim.engine.MAX_SHUFFLES = 1000`. `STS2CombatEnv.step` returns `(zeros, -1.0, True, False, {"aborted": True, "error": ...})` when the sim raises it.

- [ ] **Step 1: Write the failing tests**

Append to `agent/sim/test_engine.py`, just before `print("sim self-check ok")`:

```python
# A reshuffle loop (like Pillage under Ringing + Hellraiser was) raises instead of hanging.
from .engine import MAX_SHUFFLES, SimLoopError
c = solo(["DEFEND_IRONCLAD"])
c.draw_pile, c.discard_pile, c.shuffles = [], ["STRIKE_IRONCLAD"], MAX_SHUFFLES
try:
    c._take_top()
    raise AssertionError("expected SimLoopError")
except SimLoopError:
    pass
c.fight("NIBBITS_WEAK")
assert c.shuffles == 0  # the cap is per fight
```

Create `agent/test_run_env.py`:

```python
"""Checks for the combat env's loop guard and the run policy env. Run from agent/: python test_run_env.py"""
from env import STS2CombatEnv
from sim.engine import SimClient, SimLoopError

# Review focus 1: a sim infinite loop ends the episode as aborted instead of hanging or raising.
env = STS2CombatEnv(encounter="NIBBITS_WEAK", client=SimClient(seed=0), heal=False, episodes_per_restart=10**9)
env._episode_count = 1
env.reset(seed=0)


def boom(*args, **kwargs):
    raise SimLoopError("test")


env.client.end_turn = boom
_, reward, terminated, truncated, info = env.step(env.action_space.n - 1)  # END_TURN
assert terminated and not truncated and info.get("aborted") and reward == -1.0, info

print("run env checks ok")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd agent && ../.venv/bin/python -m sim.test_engine`
Expected: `ImportError: cannot import name 'MAX_SHUFFLES'`

Run: `cd agent && ../.venv/bin/python test_run_env.py`
Expected: `ImportError: cannot import name 'SimLoopError'`

- [ ] **Step 3: Implement**

In `agent/sim/engine.py`, after `MAX_HAND_SIZE = 10`:

```python
MAX_SHUFFLES = 1000  # per fight; real fights reshuffle a handful of times


class SimLoopError(RuntimeError):
    """MAX_SHUFFLES reshuffles in one fight: an infinite draw loop (Pillage under Ringing +
    Hellraiser was one). STS2CombatEnv ends the episode instead of hanging training."""
```

In `SimCombat.fight`, next to `self.round = 1`:

```python
        self.shuffles = 0
```

In `SimCombat._take_top`, after `self.shuffles += 1`:

```python
            if self.shuffles > MAX_SHUFFLES:
                raise SimLoopError(f"{self.shuffles} reshuffles in one fight")
```

In `agent/env.py`, change `from sim.engine import MONSTERS` to:

```python
from sim.engine import MONSTERS, SimLoopError
```

and in `STS2CombatEnv.step` change `except (requests.RequestException, TimeoutError) as exc:` to:

```python
        except (requests.RequestException, TimeoutError, SimLoopError) as exc:
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd agent && ../.venv/bin/python -m sim.test_engine && ../.venv/bin/python test_run_env.py`
Expected: `sim self-check ok` then `run env checks ok`

- [ ] **Step 5: Commit**

```bash
git add agent/sim/engine.py agent/env.py agent/sim/test_engine.py agent/test_run_env.py
git commit -m "Sim: raise SimLoopError after 1000 reshuffles in a fight; env ends the episode

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Act 1 map generation

**Files:**
- Create: `agent/sim/map.py`
- Create: `agent/sim/test_act.py`

**Interfaces:**
- Produces:
  - `sim.map.COLS = 7`, `LAST_ROW = 15`, `BOSS_ROW = 16`, `TREASURE_ROW = 9`
  - `ROOM_TYPES = ("Monster", "Elite", "RestSite", "Shop", "Treasure", "Unknown", "Boss")`
  - class `Node` with `col: int`, `row: int`, `type: str`, `fixed: bool`, `children: list[Node]`, `parents: list[Node]`
  - class `ActMap` with `grid: dict[tuple[int, int], Node]` (room rows 1–15), `start: Node` (row 0, type `"Ancient"`), `boss: Node` (row 16), `row(r) -> list[Node]` (sorted by col), and `nodes() -> list[Node]`
  - `generate_map(rng: random.Random) -> ActMap`
  - `gaussian_int(rng, mean, sd, lo, hi) -> int`

- [ ] **Step 1: Write the failing test**

Create `agent/sim/test_act.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd agent && ../.venv/bin/python -m sim.test_act`
Expected: `ModuleNotFoundError: No module named 'sim.map'`

- [ ] **Step 3: Implement `agent/sim/map.py`**

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd agent && ../.venv/bin/python -m sim.test_act`
Expected: `act self-check ok`

If the average-count line fails, print `counts / 300` and compare with the queue sizes. A big shortfall means `_valid`/`_next_valid` differs from `StandardActMap.GetNextValidPointType`; re-read it rather than lowering the bound.

- [ ] **Step 5: Commit**

```bash
git add agent/sim/map.py agent/sim/test_act.py
git commit -m "Sim: Act 1 map generation (StandardActMap port)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Run rules: encounters, "?" rooms, shop, rewards, rest

**Files:**
- Create: `agent/sim/act.py`
- Modify: `agent/picker.py:12-45` (move `REWARD_POOLS`, `RarityOdds`, `offer` out; import them back)
- Modify: `agent/sim/test_act.py` (append before the final `print`)
- Modify: `docs/game-architecture.md` (new section at the end of the game-systems part, before `## File structure`)

**Interfaces:**
- Consumes: `sim.map.generate_map`, `Node`, `ActMap`; `sim.cards.CARDS`, `COMMONS`, `UNCOMMONS`, `RARES`, `starter_deck`; `sim.engine.ENCOUNTERS`, `PLAYER_MAX_HP`.
- Produces:
  - Moved verbatim from `picker.py`: `sim.act.REWARD_POOLS`, `RarityOdds` (plus new `roll_shop(rng) -> str`), `offer(rng, odds, elite=False) -> list[str]`.
  - Encounter constants: `WEAK`, `NORMALS`, `ELITES`, `BOSSES` (tuples of encounter ids), `TAGS`.
  - `encounter_queue(rng) -> tuple[list[str], list[str], str]`.
  - `UnknownOdds` with `roll(rng, blacklist) -> str`, one of `"Monster" | "Treasure" | "Shop" | "Event"`.
  - `Shop` dataclass with `cards: list[str | None]`, `prices: list[int]`, `removal_price: int`, `removal_used: bool`.
  - `make_shop(rng, odds, removals) -> Shop`.
  - `Run(rng)` with:
    - attributes `rng`, `map`, `node`, `hp`, `max_hp`, `gold`, `deck`, `removals`, `spent`, `boss`, `shop`, `last_room`
    - methods `choices() -> list[Node]`, `enter(node) -> str` (room type), `encounter(room) -> str`, `win(room) -> list[str]` (the card offer), `buy(slot)`, `remove(card)`
  - Constants: `SHOP_SLOTS`, `STARTING_GOLD`, `GOLD`, `REST_HEAL`, `BURNING_BLOOD_HEAL`, `PROMPT_CARDS`.

- [ ] **Step 1: Write the failing tests**

Append to `agent/sim/test_act.py`, before `print("act self-check ok")`:

```python
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
    for a, b in zip(normals[3:], normals[4:]):
        assert not (TAGS.get(a, set()) & TAGS.get(b, set())), (a, b)

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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd agent && ../.venv/bin/python -m sim.test_act`
Expected: `ModuleNotFoundError: No module named 'sim.act'`

- [ ] **Step 3: Implement `agent/sim/act.py`**

```python
"""One Act 1 run between fights: map position, HP, gold, deck, encounters, "?" rooms, shops,
rewards. Fights aren't here; run_env.py plays them with the combat policy and copies HP in and
out. Numbers are from the decompiled source; see docs/game-architecture.md, "Act 1 runs".
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from .cards import CARDS, COMMONS, RARES, UNCOMMONS, starter_deck
from .engine import ENCOUNTERS, PLAYER_MAX_HP
from .map import ActMap, Node, generate_map

STARTING_GOLD = 99  # Ironclad.StartingGold
GOLD = {"Monster": (10, 20), "Elite": (35, 45), "Boss": (100, 100)}  # EncounterModel.Min/MaxGoldReward
BURNING_BLOOD_HEAL = 6
REST_HEAL = 0.3  # HealRestSiteOption: 30% of max HP
CARD_PRICE = {"COMMON": 50, "UNCOMMON": 75, "RARE": 150}  # MerchantCardEntry.GetCost
SHOP_SLOTS = ("Attack", "Attack", "Skill", "Skill", "Power")  # MerchantInventory._coloredCardTypes
REMOVAL_PRICE, REMOVAL_STEP = 75, 25  # MerchantCardRemovalEntry: +25 per removal used
NEXT_RARITY = {"COMMON": "UNCOMMON", "UNCOMMON": "RARE", "RARE": "COMMON"}  # GetNextHighestRarityWithWrapping

# The Ironclad pool by rarity. These open a card-choice prompt the sim can't play yet, so they're
# offered and stocked like any card but can't be picked or bought.
PROMPT_CARDS = {"ARMAMENTS": "Skill", "HEADBUTT": "Attack", "BURNING_PACT": "Skill", "BRAND": "Skill"}
REWARD_POOLS = {"COMMON": COMMONS + ("ARMAMENTS", "HEADBUTT"), "UNCOMMON": UNCOMMONS + ("BURNING_PACT",),
                "RARE": RARES + ("BRAND",)}

WEAK = tuple(e for e in ENCOUNTERS if e.endswith("_WEAK"))
ELITES = tuple(e for e in ENCOUNTERS if e.endswith("_ELITE"))
BOSSES = tuple(e for e in ENCOUNTERS if e.endswith("_BOSS"))
NORMALS = tuple(e for e in ENCOUNTERS if e not in WEAK + ELITES + BOSSES)
TAGS = {"NIBBITS_WEAK": {"Nibbit"}, "SLIMES_WEAK": {"Slimes"}, "SHRINKER_BEETLE_WEAK": {"Shrinker"},  # EncounterModel.Tags
        "FUZZY_WURM_CRAWLER_WEAK": {"Crawler"}, "SLIMES_NORMAL": {"Slimes"}, "OVERGROWTH_CRAWLERS": {"Crawler", "Shrinker"},
        "FLYCONID_NORMAL": {"Mushroom", "Slimes"}, "SNAPPING_JAXFRUIT_NORMAL": {"Mushroom"}}


def card_type(card_id: str) -> str:
    return CARDS[card_id].type if card_id in CARDS else PROMPT_CARDS[card_id]


class RarityOdds:
    """CardRarityOdds.cs at ascension 0. Regular fights: Rare 3% + an offset that starts at -5%,
    grows 1% per non-Rare roll (cap 40%) and resets on a Rare; Uncommon 37%. Elites: Rare 10%
    + offset, Uncommon 40%. One instance per run (the offset carries)."""

    def __init__(self):
        self.offset = -0.05

    def roll(self, rng: random.Random, elite: bool = False) -> str:
        r, rare = rng.random(), (0.10 if elite else 0.03) + self.offset
        if r < rare:
            self.offset = -0.05
            return "RARE"
        self.offset = min(self.offset + 0.01, 0.4)
        return "UNCOMMON" if r < rare + (0.40 if elite else 0.37) else "COMMON"

    def roll_shop(self, rng: random.Random) -> str:
        """CardRarityOddsType.Shop, RollWithoutChangingFutureOdds: Rare 9% + offset, Uncommon 37%."""
        r, rare = rng.random(), 0.09 + self.offset
        return "RARE" if r < rare else "UNCOMMON" if r < rare + 0.37 else "COMMON"


def offer(rng: random.Random, odds: RarityOdds, elite: bool = False) -> list[str]:
    """CardFactory.CreateForReward: 3 cards, no repeats."""
    out: list[str] = []
    for _ in range(3):
        out.append(rng.choice([c for c in REWARD_POOLS[odds.roll(rng, elite)] if c not in out]))
    return out


def _grab(rng: random.Random, bag: list[str], pool: tuple[str, ...], last: str | None) -> str:
    """GrabBag.GrabAndRemove via AddWithoutRepeatingTags: avoid the last encounter and its tags."""
    if not bag:
        bag.extend(pool)
    ok = [e for e in bag if e != last and not (TAGS.get(e, set()) & TAGS.get(last, set()))]
    e = rng.choice(ok or bag)
    bag.remove(e)
    return e


def encounter_queue(rng: random.Random, rooms: int = 15, weak: int = 3) -> tuple[list[str], list[str], str]:
    """ActModel.GenerateRooms: monster rooms draw 3 weak then regular encounters, elites from
    their own bag; the boss is fixed at run start."""
    normals: list[str] = []
    bag: list[str] = []
    for _ in range(weak):
        normals.append(_grab(rng, bag, WEAK, normals[-1] if normals else None))
    bag = []
    for _ in range(weak, rooms):
        normals.append(_grab(rng, bag, NORMALS, normals[-1]))
    elites: list[str] = []
    bag = []
    for _ in range(15):
        elites.append(_grab(rng, bag, ELITES, elites[-1] if elites else None))
    return normals, elites, rng.choice(BOSSES)


class UnknownOdds:
    """UnknownMapPointOdds.Roll: a rolled type resets to its base odds and each unrolled allowed
    type grows by its base, so "?" rooms rarely stay events forever. Elite odds are -1: never.
    ponytail: the first-run tutorial override (events for the first two "?") is left out."""
    BASE = {"Monster": 0.10, "Treasure": 0.02, "Shop": 0.03}

    def __init__(self):
        self.odds = dict(self.BASE)

    def roll(self, rng: random.Random, blacklist: set[str]) -> str:
        r, acc, room = rng.random(), 0.0, "Event"
        for t, p in self.odds.items():
            if t in blacklist:
                continue
            acc += p
            if r <= acc:
                room = t
                break
        for t, base in self.BASE.items():
            if t == room:
                self.odds[t] = base
            elif t not in blacklist:
                self.odds[t] += base
        return room


@dataclass
class Shop:
    cards: list[str | None]  # one per SHOP_SLOTS entry; None once bought
    prices: list[int]
    removal_price: int
    removal_used: bool = False


def make_shop(rng: random.Random, odds: RarityOdds, removals: int) -> Shop:
    """MerchantInventory.PopulateCharacterCardEntries: 5 typed slots, no repeats, one half price.
    Colorless cards, relics and potions aren't stocked yet."""
    sale = rng.randrange(len(SHOP_SLOTS))
    cards: list[str | None] = []
    prices: list[int] = []
    for i, ctype in enumerate(SHOP_SLOTS):
        rarity = odds.roll_shop(rng)
        for _ in range(3):  # CardFactory.GetNextAllowedRarity
            pool = [c for c in REWARD_POOLS[rarity] if card_type(c) == ctype and c not in cards]
            if pool:
                break
            rarity = NEXT_RARITY[rarity]
        cards.append(rng.choice(pool))
        price = round(CARD_PRICE[rarity] * rng.uniform(0.95, 1.05))  # Mathf.RoundToInt: banker's, like round()
        prices.append(price // 2 if i == sale else price)
    return Shop(cards, prices, REMOVAL_PRICE + REMOVAL_STEP * removals)


class Run:
    """An Act 1 run between fights. HP lives here; run_env copies it into each SimCombat and back."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.map: ActMap = generate_map(rng)
        self.normals, self.elites, self.boss = encounter_queue(rng)
        self.node: Node = self.map.start
        self.hp = self.max_hp = PLAYER_MAX_HP
        self.gold, self.deck, self.removals, self.spent = STARTING_GOLD, starter_deck(), 0, 0
        self.card_odds, self.unknown_odds = RarityOdds(), UnknownOdds()
        self.last_room: str | None = None
        self.shop: Shop | None = None

    def choices(self) -> list[Node]:
        return sorted(self.node.children, key=lambda n: n.col)

    def enter(self, node: Node) -> str:
        """Move to a child of the current node and resolve its room type (rest heals, shops stock)."""
        assert node in self.node.children, (node, self.node)
        room = node.type
        if room == "Unknown":  # RunManager.BuildRoomTypeBlacklist
            no_shop = self.last_room == "Shop" or (node.children and all(c.type == "Shop" for c in node.children))
            room = self.unknown_odds.roll(self.rng, {"Shop"} if no_shop else set())
        self.node, self.last_room = node, room
        if room == "RestSite":
            self.hp = min(self.max_hp, self.hp + int(self.max_hp * REST_HEAL))
        elif room == "Shop":
            self.shop = make_shop(self.rng, self.card_odds, self.removals)
        return room

    def encounter(self, room: str) -> str:
        if room == "Boss":
            return self.boss
        queue, pool = (self.elites, ELITES) if room == "Elite" else (self.normals, NORMALS)
        return queue.pop(0) if queue else self.rng.choice(pool)

    def win(self, room: str) -> list[str]:
        """After a won fight: Burning Blood, gold, and the card offer (none after the boss)."""
        self.hp = min(self.max_hp, self.hp + BURNING_BLOOD_HEAL)
        self.gold += self.rng.randint(*GOLD[room])
        return [] if room == "Boss" else offer(self.rng, self.card_odds, room == "Elite")

    def buy(self, slot: int) -> None:
        s = self.shop
        card, price = s.cards[slot], s.prices[slot]
        assert card in CARDS and self.gold >= price, (card, price, self.gold)
        self.gold -= price
        self.spent += price
        self.deck.append(card)
        s.cards[slot] = None

    def remove(self, card: str) -> None:
        s = self.shop
        assert not s.removal_used and self.gold >= s.removal_price and card in self.deck
        self.gold -= s.removal_price
        self.spent += s.removal_price
        self.deck.remove(card)
        self.removals += 1
        s.removal_used = True
```

In `agent/picker.py`:
- Delete the `REWARD_POOLS` dict, the `RarityOdds` class and the `offer` function (lines 18–45).
- Change `from sim.cards import CARDS, COMMONS, RARES, UNCOMMONS` to `from sim.cards import CARDS`.
- Add, so `run.py`'s `from picker import RarityOdds, offer, ...` keeps working:

```python
from sim.act import REWARD_POOLS, RarityOdds, offer  # noqa: F401  (run.py imports these from here)
```

In `docs/game-architecture.md`, run `grep -n "Act 1 runs\|MerchantInventory\|UnknownMapPointOdds" docs/game-architecture.md` first to avoid duplicating anything. Then add before `## File structure`:

```markdown
## Act 1 runs (map, rooms, shop)

Ported to the sim in `agent/sim/map.py` and `agent/sim/act.py`.

- **Map** (`Map/StandardActMap.cs`):
  - **Grid:** 7 columns. Row 0 is the Ancient (Neow), rows 1–15 are rooms (`Overgrowth.BaseNumberOfRooms`) and row 16 is the boss.
  - **Paths:** 7 paths start on row 1, the second always on a new column. Each path steps to column −1, 0 or +1 in shuffled order, skipping a step that would cross the neighbor's diagonal.
  - **Fixed rows:** row 1 is all Monster, row 9 (rows − 7) all Treasure, row 15 all RestSite.
  - **Random rooms:** a queue of RestSite × N(7,1)∈[6,7], Shop × 3, Elite × 5 and Unknown × N(12,1)∈[10,14] is placed at random. Up to 3 passes are made over unassigned points, and invalid types rotate to the back of the queue. Leftover points become Monster.
  - **Placement rules:** no RestSite or Elite below row 6, and no RestSite in rows 13+. Elite, RestSite, Treasure and Shop can't sit next to the same type (parent or child). RestSite, Monster, Unknown, Elite and Shop can't sit beside the same type (siblings, meaning a parent's other children).
  - **After generation:** `MapPathPruning` removes duplicate parallel segments, and `MapPostProcessing` moves columns only.
- **Encounters** (`ActModel.GenerateRooms`):
  - The monster-room queue is 3 weak encounters, then 12 regular ones, each drawn from a refilling bag that avoids the previous encounter and any shared `EncounterTag`.
  - Elites come from their own bag (15 deep).
  - The boss is drawn at run start, but a not-yet-seen boss is forced first (`BossDiscoveryOrder`: Vantom, Ceremonial Beast, Kin).
- **"?" rooms** (`Odds/UnknownMapPointOdds.cs`):
  - Base odds are Monster 10%, Treasure 2%, Shop 3%, otherwise Event; Elite is −1, so never.
  - A rolled type resets to its base, and each unrolled allowed type grows by its base.
  - Shop is blacklisted after a shop, or when every next point is a shop (`RunManager.BuildRoomTypeBlacklist`).
  - On a profile's first run, the first two "?" rooms are events and the third is a monster.
- **Gold:** the Ironclad starts with 99. Fights pay Monster 10–20, Elite 35–45, Boss 100 (`EncounterModel.Min/MaxGoldReward`).
- **Shop** (`Entities/Merchant/`):
  - **Character cards:** 5 slots typed Attack, Attack, Skill, Skill, Power. Rarity uses the shop odds (Rare 9% + the card-rarity offset, which this roll doesn't advance; Uncommon 37%). If a type has no card of that rarity, it falls to the next rarity (Common → Uncommon → Rare → Common). Already-stocked cards are excluded.
  - **Price:** 50/75/150 by rarity × U(0.95, 1.05), rounded; colorless cards ×1.15. One random character card is half price.
  - **Other stock:** 2 colorless cards (Uncommon, Rare), 3 relics (2 rolled + 1 Shop rarity) and 3 potions.
  - **Card removal:** once per shop, 75 + 25 per removal used this run.
- **Rest site:** heals 30% of max HP (`HealRestSiteOption`).
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd agent && ../.venv/bin/python -m sim.test_act && ../.venv/bin/python -m sim.test_engine && ../.venv/bin/python -c "import run, picker; print('imports ok')"`
Expected: `act self-check ok`, `sim self-check ok`, `imports ok`

- [ ] **Step 5: Commit**

```bash
git add agent/sim/act.py agent/sim/test_act.py agent/picker.py docs/game-architecture.md
git commit -m "Sim: Act 1 run rules (encounter queue, ? rooms, shop, gold, rest)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Run policy env

**Files:**
- Create: `agent/run_env.py`
- Modify: `agent/test_run_env.py` (append before the final `print`)

**Interfaces:**
- Consumes:
  - `sim.act`: `Run`, `Shop`, `SHOP_SLOTS`, `BOSSES`
  - `sim.map`: `COLS`, `ROOM_TYPES`
  - `env`: `CARD_IDS`, `STS2CombatEnv`
  - `picker.play_fight(model, env, seed) -> (won, hp_lost)` (raises `RuntimeError` on aborted fights)
  - `sim.engine.SimClient`
- Produces:
  - `run_env.RunPolicyEnv(combat_model: str | None = None)`, a `gym.Env` with `action_masks()`. With `combat_model=None` it fights with random legal moves (tests only).
  - Attributes `run: Run`, `decision: str` (one of `DECISIONS`), `offered: list[str]`, `room: str`, `done: bool`, `combat` (an object with `.predict(obs, action_masks=, deterministic=)`).
  - Methods `enter(col) -> str | None` (the encounter if the room is a fight), `after_fight(won) -> tuple[float, bool]` and `play(encounter) -> bool`.
  - Constants: `DECISIONS`, `PATH`, `PICK`, `SHOP`, `SHOP_REMOVE`, `SHOP_LEAVE`, `REMOVE`, `N_ACTIONS` (= 103), `OBS_DIM`, `CARD_INDEX`, `FLOOR_REWARD`, `CLEAR_REWARD`.
  - `info` keys on every step: `floor`, `cleared`, `died_at` (room type or None), `gold`, `spent`, `deck`.

- [ ] **Step 1: Write the failing tests**

Append to `agent/test_run_env.py`, before `print("run env checks ok")`:

```python
import numpy as np

from run_env import CARD_INDEX, N_ACTIONS, OBS_DIM, PICK, REMOVE, SHOP, SHOP_LEAVE, SHOP_REMOVE, RunPolicyEnv
from sim.act import Shop

assert N_ACTIONS == 103

# Smoke: random run decisions + random combat. Masks never empty, obs in bounds, every run ends.
renv, rng, floors = RunPolicyEnv(), np.random.default_rng(0), []
for seed in range(200):
    obs, _ = renv.reset(seed=seed)
    done = trunc = False
    while not (done or trunc):
        assert obs.shape == (OBS_DIM,) and obs.min() >= -1 and obs.max() <= 10, (obs.min(), obs.max())
        mask = renv.action_masks()
        assert mask.shape == (N_ACTIONS,) and mask.any(), renv.decision
        obs, reward, done, trunc, info = renv.step(int(rng.choice(np.flatnonzero(mask))))
    assert done and not trunc, f"seed {seed} never ended"
    assert info["died_at"] or info["cleared"]
    floors.append(info["floor"])
assert np.mean(floors) > 1.5, np.mean(floors)  # random combat dies early, but climbs a little

# Review focus 5: same seed, same map.
a, b = RunPolicyEnv(), RunPolicyEnv()
a.reset(seed=11)
b.reset(seed=11)
assert [(n.col, n.row, n.type) for n in a.run.map.nodes()] == [(n.col, n.row, n.type) for n in b.run.map.nodes()]

# Review focus 2: an offer of only prompt cards leaves only "skip".
renv.reset(seed=1)
renv.decision, renv.offered = "pick", ["ARMAMENTS", "HEADBUTT", "BRAND"]
assert np.flatnonzero(renv.action_masks()).tolist() == [PICK + 3]

# Review focus 3: a broke player in a shop can only leave; removal is masked once used.
renv.decision, renv.run.gold = "shop", 0
renv.run.shop = Shop(["NOT_A_CARD"] * 5, [50] * 5, 75)
assert np.flatnonzero(renv.action_masks()).tolist() == [SHOP_LEAVE]
renv.run.gold, renv.run.shop = 1000, Shop(["SHRUG_IT_OFF", None, "ARMAMENTS", None, None], [50] * 5, 75)
assert np.flatnonzero(renv.action_masks()).tolist() == [SHOP, SHOP_REMOVE, SHOP_LEAVE]
renv.step(SHOP_REMOVE)
assert renv.decision == "remove" and renv.action_masks()[REMOVE + CARD_INDEX["BASH"]]
renv.step(REMOVE + CARD_INDEX["BASH"])
assert renv.decision == "shop" and "BASH" not in renv.run.deck and not renv.action_masks()[SHOP_REMOVE]

# Review focus 4: max HP goes into the fight and comes back out.
renv.reset(seed=2)
renv.run.hp, renv.run.max_hp = 50, 90
renv.play(renv.run.normals[0])
assert renv.run.max_hp == 90 and renv.fight_env.client._combat.player_max_hp == 90

# Review focus 1: a sim error inside a fight ends the run as a loss.
renv.reset(seed=3)
renv.fight_env.client.exec = boom
_, _, done, _, info = renv.step(int(np.flatnonzero(renv.action_masks())[0]))
assert done and info["died_at"] == "Monster" and not info["cleared"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd agent && ../.venv/bin/python test_run_env.py`
Expected: `ModuleNotFoundError: No module named 'run_env'`

- [ ] **Step 3: Implement `agent/run_env.py`**

```python
"""Run policy env: one episode is one Act 1 run, one step is one out-of-combat decision.

A path step into a fight plays the whole fight with a frozen combat policy (or random legal
moves when combat_model is None, for tests). Spec: docs/superpowers/specs/2026-10-18-run-foundation-design.md
"""
from __future__ import annotations

import random
import traceback

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from env import CARD_IDS, STS2CombatEnv
from picker import play_fight
from sim.act import BOSSES, SHOP_SLOTS, Run
from sim.cards import CARDS
from sim.engine import SimClient
from sim.map import BOSS_ROW, COLS, ROOM_TYPES

DECISIONS = ("path", "pick", "shop", "remove")
# Actions: [path: one per column][pick: 3 cards, skip][shop: one per slot, remove, leave][remove: one per card id, cancel]
PATH = 0
PICK = PATH + COLS
SHOP = PICK + 4
SHOP_REMOVE, SHOP_LEAVE = SHOP + len(SHOP_SLOTS), SHOP + len(SHOP_SLOTS) + 1
REMOVE = SHOP_LEAVE + 1
N_ACTIONS = REMOVE + len(CARD_IDS) + 1
CARD_INDEX = {c: i for i, c in enumerate(CARD_IDS)}
FIGHTS = ("Monster", "Elite", "Boss")
LOOKAHEAD = 5  # map rows shown ahead of the current node
SLOT_FEATURES = len(CARD_IDS) + 2  # card one-hot, price / 100, affordable
CELL_FEATURES = len(ROOM_TYPES) + 1  # room type one-hot, reachable from here
OBS_DIM = (len(DECISIONS) + 5 + len(CARD_IDS) + len(BOSSES) + len(SHOP_SLOTS) * SLOT_FEATURES + 2
           + LOOKAHEAD * COLS * CELL_FEATURES)
FLOOR_REWARD, CLEAR_REWARD = 0.1, 1.0
MAX_DECISIONS = 500  # a run is ~40 decisions; this only stops a broken env


class RandomCombat:
    """Stands in for a combat model in tests: a random legal action."""

    def __init__(self, rng: np.random.Generator):
        self.rng = rng

    def predict(self, obs, action_masks, deterministic=True):
        return self.rng.choice(np.flatnonzero(action_masks)), None


class RunPolicyEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, combat_model: str | None = None):
        super().__init__()
        self.action_space = spaces.Discrete(N_ACTIONS)
        self.observation_space = spaces.Box(low=-1.0, high=10.0, shape=(OBS_DIM,), dtype=np.float32)
        if combat_model:
            import torch
            from sb3_contrib import MaskablePPO
            torch.set_num_threads(1)  # n_envs of these share the CPU
            self.combat = MaskablePPO.load(combat_model, device="cpu")
        else:
            self.combat = RandomCombat(np.random.default_rng(0))
        self.fight_env = STS2CombatEnv(client=SimClient(), heal=False, episodes_per_restart=10**9)
        self.fight_env._episode_count = 1  # never full_restart: HP is synced from the run
        self.run: Run | None = None

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.run = Run(random.Random(int(self.np_random.integers(2**31))))
        self.fight_env.client = SimClient(seed=self.run.rng.randrange(2**31))
        self.decision, self.offered, self.room = "path", [], "Ancient"
        self.done, self.cleared, self.steps = False, False, 0
        return self._obs(), {}

    # --- the pieces MapRunModeEnv (run.py) reuses ------------------------------------------------

    def enter(self, col: int) -> str | None:
        """Path action: move to the child in that column. The encounter if it's a fight, else None."""
        node = next(n for n in self.run.choices() if n.col == col)
        self.room = self.run.enter(node)
        if self.room in FIGHTS:
            return self.run.encounter(self.room)
        self.decision = "shop" if self.room == "Shop" else "path"
        return None

    def after_fight(self, won: bool) -> tuple[float, bool]:
        """Reward and done after a fight; on a win, the card offer becomes the next decision."""
        if not won:
            self.done = True
            return 0.0, True
        offered = self.run.win(self.room)
        if self.room == "Boss":
            self.done = self.cleared = True
            return FLOOR_REWARD + CLEAR_REWARD, True
        self.offered, self.decision = offered, "pick"
        return FLOOR_REWARD, False

    def play(self, encounter: str) -> bool:
        """One fight with HP, max HP and deck carried in and out. A sim error ends it as a loss."""
        run, env = self.run, self.fight_env
        combat = env.client._combat
        combat.player_hp, combat.player_max_hp = run.hp, run.max_hp
        env.encounters, env.deck = [encounter], list(run.deck)
        try:
            won = play_fight(self.combat, env, seed=run.rng.randrange(2**31))[0]
        except Exception:  # noqa: BLE001 - one bad sim state must not kill a 6-env training run
            traceback.print_exc()
            return False
        combat = env.client._combat
        run.hp, run.max_hp = combat.player_hp, combat.player_max_hp
        return won

    # --- gym API ---------------------------------------------------------------------------------

    def step(self, action: int):
        a = int(action)
        assert self.action_masks()[a], f"illegal action {a} for {self.decision}"
        self.steps += 1
        reward = 0.0
        if self.decision == "path":
            encounter = self.enter(a - PATH)
            if encounter is None:
                reward = FLOOR_REWARD
            else:
                reward, _ = self.after_fight(self.play(encounter))
        elif self.decision == "pick":
            if a - PICK < 3:
                self.run.deck.append(self.offered[a - PICK])
            self.decision = "path"
        elif self.decision == "shop":
            if a == SHOP_LEAVE:
                self.decision = "path"
            elif a == SHOP_REMOVE:
                self.decision = "remove"
            else:
                self.run.buy(a - SHOP)
        else:  # remove
            if a - REMOVE < len(CARD_IDS):
                self.run.remove(CARD_IDS[a - REMOVE])
            self.decision = "shop"
        truncated = not self.done and self.steps >= MAX_DECISIONS
        info = {"floor": self.run.node.row, "cleared": self.cleared, "gold": self.run.gold, "spent": self.run.spent,
                "died_at": self.room if self.done and not self.cleared else None, "deck": list(self.run.deck)}
        return self._obs(), reward, self.done, truncated, info

    def action_masks(self) -> np.ndarray:
        m = np.zeros(N_ACTIONS, dtype=bool)
        run = self.run
        if self.done:
            m[PATH + run.node.col] = True  # never consulted; keeps the mask non-empty after the end
        elif self.decision == "path":
            for n in run.choices():
                m[PATH + n.col] = True
        elif self.decision == "pick":
            for i, c in enumerate(self.offered):
                m[PICK + i] = c in CARDS
            m[PICK + 3] = True
        elif self.decision == "shop":
            s = run.shop
            for i, (c, p) in enumerate(zip(s.cards, s.prices)):
                m[SHOP + i] = c in CARDS and run.gold >= p
            m[SHOP_REMOVE] = not s.removal_used and run.gold >= s.removal_price
            m[SHOP_LEAVE] = True
        else:
            for c in set(run.deck):
                m[REMOVE + CARD_INDEX[c]] = True
            m[REMOVE + len(CARD_IDS)] = True
        return m

    def _obs(self) -> np.ndarray:
        run = self.run
        head = [float(d == self.decision) for d in DECISIONS]
        head += [run.hp / 80, run.max_hp / 80, run.gold / 100, run.node.row / BOSS_ROW, run.removals / 5]
        deck = np.zeros(len(CARD_IDS))
        for c in run.deck:
            deck[CARD_INDEX[c]] += 0.5
        boss = [float(b == run.boss) for b in BOSSES]
        slots = np.zeros((len(SHOP_SLOTS), SLOT_FEATURES))
        removal = [0.0, 0.0]
        if self.decision == "pick":
            for i, c in enumerate(self.offered):
                if c in CARD_INDEX:
                    slots[i, CARD_INDEX[c]] = 1
        elif self.decision in ("shop", "remove"):
            s = run.shop
            for i, (c, p) in enumerate(zip(s.cards, s.prices)):
                if c in CARD_INDEX:
                    slots[i, CARD_INDEX[c]], slots[i, -2], slots[i, -1] = 1, p / 100, run.gold >= p
            removal = [s.removal_price / 100, float(not s.removal_used and run.gold >= s.removal_price)]
        grid = np.zeros((LOOKAHEAD, COLS, CELL_FEATURES))
        reach, todo = set(), list(run.node.children)
        while todo:
            n = todo.pop()
            if id(n) not in reach and n.row <= run.node.row + LOOKAHEAD:
                reach.add(id(n))
                todo += n.children
        for n in list(run.map.grid.values()) + [run.map.boss]:
            k = n.row - run.node.row - 1
            if 0 <= k < LOOKAHEAD:
                grid[k, n.col, ROOM_TYPES.index(n.type)] = 1
                grid[k, n.col, -1] = id(n) in reach
        return np.concatenate([head, np.minimum(deck, 10), boss, slots.ravel(), removal, grid.ravel()]).astype(np.float32)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd agent && ../.venv/bin/python test_run_env.py`
Expected: `run env checks ok`. The test also prints one traceback from the deliberate `boom` fight; that's expected.

- [ ] **Step 5: Commit**

```bash
git add agent/run_env.py agent/test_run_env.py
git commit -m "Run policy env: map paths, card picks, shop buys and removal over sim fights

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Train the run policy

**Files:**
- Modify: `agent/train.py:42-66` (arguments and env selection)

**Interfaces:**
- Consumes: `run_env.RunPolicyEnv(combat_model)`.
- Produces: `train.py --backend sim --run-policy --combat-model <zip>`, which saves `models/<name>_final.zip` with a 103-action, `OBS_DIM`-input policy.

- [ ] **Step 1: Write the failing check**

Run: `cd agent && ../.venv/bin/python train.py --backend sim --run-policy --combat-model models/ppo_sts2_sim_act1_run_v9_final.zip --n-envs 2 --net 256 256 --timesteps 4096 --name smoke_run_policy`
Expected: `error: unrecognized arguments: --run-policy --combat-model ...`

- [ ] **Step 2: Implement**

In `agent/train.py`, after the `--run-mode` argument:

```python
    parser.add_argument("--run-policy", action="store_true",
                        help="sim only: train the run policy (run_env.py) over a frozen --combat-model")
    parser.add_argument("--combat-model", default=None, help="combat model zip that plays fights for --run-policy")
```

Replace the `if sim and args.run_mode:` line with:

```python
    if sim and args.run_policy:
        from run_env import RunPolicyEnv
        env = make_vec_env(lambda: RunPolicyEnv(combat_model=args.combat_model), n_envs=args.n_envs,
                           vec_env_cls=SubprocVecEnv if args.n_envs > 1 else None)
    elif sim and args.run_mode:
```

- [ ] **Step 3: Run the check to verify it works**

Run the Step 1 command again.
Expected: training logs with `ep_rew_mean` and `fps`, then `Saved final model to .../smoke_run_policy_final.zip`. Note the fps; the spec estimates about 30 runs/s at 6 envs.

Then delete the smoke artifacts: `rm agent/models/smoke_run_policy_*`

- [ ] **Step 4: Commit**

```bash
git add agent/train.py
git commit -m "train.py: --run-policy --combat-model trains the run policy

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Generated-map evaluation (baseline vs run policy)

**Files:**
- Modify: `agent/run.py` (imports; `_init`; new `baseline_action`, `generated_run`; `main` arguments and report)

**Interfaces:**
- Consumes:
  - `run_env`: `RunPolicyEnv`, `PATH`, `PICK`, `SHOP_REMOVE`, `SHOP_LEAVE`, `REMOVE`, `CARD_INDEX`
  - `picker.pick(model, deck, offered, encounters, n, seed)`
  - `PICK_ENCOUNTERS` (already in `run.py`)
- Produces: `python run.py --model <combat zip> --maps generated [--run-model <run zip>] --runs N --n 16`. It prints one line per strategy: `cleared=…% floor=… spent=… died_at={...}`.

- [ ] **Step 1: Write the failing check**

Run: `cd agent && ../.venv/bin/python run.py --model models/ppo_sts2_sim_act1_run_v9_final.zip --maps generated --runs 4 --n 2`
Expected: `error: unrecognized arguments: --maps generated`

- [ ] **Step 2: Implement**

In `agent/run.py`, add to the imports:

```python
from run_env import CARD_INDEX, PICK, REMOVE, SHOP_LEAVE, SHOP_REMOVE, RunPolicyEnv
```

Replace `_model = None` / `_init`:

```python
_model = None
_run_model = None


def _init(model_path: str, run_model_path: str | None = None) -> None:
    global _model, _run_model
    _model = MaskablePPO.load(model_path)
    _run_model = MaskablePPO.load(run_model_path) if run_model_path else None
```

Add after `sim_run`:

```python
def baseline_action(env: RunPolicyEnv, rng: random.Random, n: int) -> int:
    """The pre-run-policy way to play: random path, MC card picks, remove a Strike when affordable."""
    mask = env.action_masks()
    if env.decision == "path":
        return int(rng.choice(np.flatnonzero(mask)))
    if env.decision == "pick":
        choice = choose("mc", _model, env.run.deck, env.offered, rng, n)
        return PICK + (env.offered.index(choice) if choice else 3)
    if env.decision == "shop":
        return SHOP_REMOVE if mask[SHOP_REMOVE] and "STRIKE_IRONCLAD" in env.run.deck else SHOP_LEAVE
    return REMOVE + CARD_INDEX["STRIKE_IRONCLAD"]


def generated_run(args: tuple[str, int, int]) -> dict:
    """One run on generated map `seed`: every strategy sees the same map and encounter queue."""
    strategy, seed, n = args
    env = RunPolicyEnv()
    env.combat = _model
    obs, _ = env.reset(seed=seed)
    rng, done, truncated, info = random.Random(seed), False, False, {}
    while not (done or truncated):
        if strategy == "policy":
            action = int(_run_model.predict(obs, action_masks=env.action_masks(), deterministic=True)[0])
        else:
            action = baseline_action(env, rng, n)
        obs, _, done, truncated, info = env.step(action)
    return {"strategy": strategy, **info}
```

In `main`, add the arguments:

```python
    ap.add_argument("--maps", choices=["fixed", "generated"], default="fixed",
                    help="fixed: ACT1_PATH; generated: sim/map.py maps with shops and ? rooms")
    ap.add_argument("--run-model", default=None, help="run policy zip (adds the 'policy' strategy on generated maps)")
```

and replace the body after `if args.live: ...` with:

```python
    if args.maps == "generated":
        strategies = ["baseline"] + (["policy"] if args.run_model else [])
        with Pool(initializer=_init, initargs=(args.model, args.run_model)) as pool:
            results = pool.map(generated_run, [(s, seed, args.n) for s in strategies for seed in range(args.runs)])
        for s in strategies:
            rs = [r for r in results if r["strategy"] == s]
            died = Counter(r["died_at"] for r in rs if r["died_at"])
            print(f"{s:8} cleared={np.mean([r['cleared'] for r in rs]):.1%}  floor={np.mean([r['floor'] for r in rs]):.1f}"
                  f"/16  spent={np.mean([r['spent'] for r in rs]):.0f}  died_at={dict(died)}")
        return
    strategies = args.strategies.split(",")
    with Pool(initializer=_init, initargs=(args.model,)) as pool:
        results = pool.map(sim_run, [(s, seed, args.n) for s in strategies for seed in range(args.runs)])
    for s in strategies:
        rs = [r for r in results if r["strategy"] == s]
        died = Counter(r["died_at"] for r in rs if r["died_at"])
        print(f"{s:7} cleared={np.mean([r['cleared'] for r in rs]):.1%}  fights_won={np.mean([r['won'] for r in rs]):.2f}"
              f"/{len(FIGHTS)}  end_hp={np.mean([r['hp'] for r in rs]):.1f}  died_at={dict(died)}")
```

Update the module docstring's usage block with:

```
Compare on generated maps (shops, ? rooms), baseline vs a run policy:
    python run.py --model models/ppo_sts2_sim_act1_run_v9_final.zip --maps generated --run-model models/ppo_sts2_sim_run_policy_v1_final.zip --runs 500 --n 16
```

- [ ] **Step 3: Run the check to verify it works**

Run the Step 1 command again.
Expected: one `baseline cleared=…  floor=…/16  spent=…  died_at={...}` line, with no traceback.

Then run the fixed route once to confirm it's unchanged: `../.venv/bin/python run.py --model models/ppo_sts2_sim_act1_run_v9_final.zip --runs 4 --n 2`
Expected: the usual `skip/random/mc` lines.

- [ ] **Step 4: Commit**

```bash
git add agent/run.py
git commit -m "run.py: --maps generated scores baseline vs run policy on seeded maps

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Combat retraining on run-policy runs (MapRunModeEnv)

**Files:**
- Modify: `agent/run.py` (new class after `RunModeEnv`)
- Modify: `agent/train.py` (`--run-model` argument; env selection)
- Modify: `agent/test_run_env.py` (append before the final `print`)

**Interfaces:**
- Consumes: `RunPolicyEnv.enter`, `after_fight`, `action_masks`, `_obs`, `step`, `run`, `decision`, `done`; `run_env.PATH`.
- Produces:
  - `run.MapRunModeEnv(run_model: str | None)`, an `STS2CombatEnv` subclass. One episode is one fight, and the run policy makes the choices between fights. `run_model=None` means random run decisions (tests).
  - `train.py --run-mode --run-model <zip>`.

- [ ] **Step 1: Write the failing test**

Append to `agent/test_run_env.py`, before `print("run env checks ok")`:

```python
# MapRunModeEnv: fights chain through generated-map runs; HP carries between fights.
from run import MapRunModeEnv

menv, rng2 = MapRunModeEnv(run_model=None), np.random.default_rng(1)
fights = 0
for _ in range(30):
    obs, _ = menv.reset()
    hp_in = menv.client._combat.player_hp
    assert hp_in == menv.driver.run.hp
    done = False
    while not done:
        obs, _, term, trunc, info = menv.step(int(rng2.choice(np.flatnonzero(menv.action_masks()))))
        done = term or trunc
    fights += 1
assert fights == 30 and menv.driver.run is not None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd agent && ../.venv/bin/python test_run_env.py`
Expected: `ImportError: cannot import name 'MapRunModeEnv'`

- [ ] **Step 3: Implement**

In `agent/run.py`, extend the run_env import to `from run_env import CARD_INDEX, PATH, PICK, REMOVE, SHOP_LEAVE, SHOP_REMOVE, RandomCombat, RunPolicyEnv`. Then add after `RunModeEnv`:

```python
class MapRunModeEnv(STS2CombatEnv):
    """Combat training on generated maps: one fight per episode, with the run policy making every
    choice between fights, so combat trains on the decks and HP the run policy actually builds."""

    def __init__(self, run_model: str | None = None, **kwargs):
        super().__init__(client=SimClient(), heal=False, episodes_per_restart=10**9, hp_weight=3.0, **kwargs)
        if run_model:
            import torch
            torch.set_num_threads(1)
            self.run_model = MaskablePPO.load(run_model, device="cpu")
        else:
            self.run_model = RandomCombat(np.random.default_rng())  # random legal run decisions
        self.driver = RunPolicyEnv()  # only its run logic is used; fights are this env's episodes
        self.driver.done = True  # start a run on the first reset

    def _next_fight(self) -> str:
        """Apply run-policy decisions until the next fight, starting a new run when one has ended."""
        d = self.driver
        while True:
            if d.done:
                d.reset(seed=int(self.np_random.integers(2**31)))
            action = int(self.run_model.predict(d._obs(), action_masks=d.action_masks(), deterministic=False)[0])
            if d.decision == "path":
                encounter = d.enter(action - PATH)
                if encounter:
                    return encounter
            else:
                d.step(action)

    def reset(self, *, seed=None, options=None):
        if seed is not None:
            self.np_random, _ = gym.utils.seeding.np_random(seed)
        encounter = self._next_fight()
        run, combat = self.driver.run, self.client._combat
        combat.player_hp, combat.player_max_hp = run.hp, run.max_hp
        self.encounters, self.deck = [encounter], list(run.deck)
        self._episode_count = 1  # never full_restart: HP is synced from the run
        return super().reset(seed=seed, options=options)

    def step(self, action):
        obs, reward, terminated, truncated, info = super().step(action)
        if terminated or truncated:
            run, combat = self.driver.run, self.client._combat
            run.hp, run.max_hp = combat.player_hp, combat.player_max_hp
            self.driver.after_fight(bool(info.get("won")) and not truncated)
        return obs, reward, terminated, truncated, info
```

Add `import gymnasium as gym` to `run.py`'s imports.

In `agent/train.py`, after `--combat-model`:

```python
    parser.add_argument("--run-model", default=None,
                        help="with --run-mode: train combat on generated maps, run decisions by this run policy")
```

and change the `elif sim and args.run_mode:` branch body to:

```python
        from run import MapRunModeEnv, RunModeEnv
        make = (lambda: MapRunModeEnv(run_model=args.run_model)) if args.run_model else RunModeEnv
        env = make_vec_env(make, n_envs=args.n_envs, vec_env_cls=SubprocVecEnv if args.n_envs > 1 else None)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd agent && ../.venv/bin/python test_run_env.py && ../.venv/bin/python -m sim.test_act && ../.venv/bin/python -m sim.test_engine`
Expected: `run env checks ok`, `act self-check ok`, `sim self-check ok`

Then smoke-test training: `../.venv/bin/python train.py --backend sim --run-mode --run-model models/smoke.zip --resume models/ppo_sts2_sim_act1_run_v9_final.zip --n-envs 2 --net 256 256 --timesteps 4096 --name smoke_maprun`. First train a tiny run policy at `models/smoke.zip` with the Task 5 command, using `--timesteps 4096 --name smoke`, and rename `models/smoke_final.zip` to `models/smoke.zip`.
Expected: training logs, then `Saved final model`. Afterwards: `rm agent/models/smoke*`

- [ ] **Step 5: Commit**

```bash
git add agent/run.py agent/train.py agent/test_run_env.py
git commit -m "MapRunModeEnv: combat training on generated maps with run-policy decisions

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Train, evaluate, document

**Files:**
- Modify: `docs/modding-approach.md` (new section at the end of the progress log, before `### Open problem: ...`)

No code changes. Each training command runs in the background under `caffeinate -i`, logging to the session scratchpad. Check that the Mac is on AC power (`pmset -g batt`) before starting, since battery halves throughput.

- [ ] **Step 1: Baseline on generated maps**

Run: `cd agent && ../.venv/bin/python run.py --model models/ppo_sts2_sim_act1_run_v9_final.zip --maps generated --runs 500 --n 16`
Record the `baseline` line.

- [ ] **Step 2: Train run policy v1** (combat v9 frozen)

Run: `caffeinate -i ../.venv/bin/python -u train.py --backend sim --run-policy --combat-model models/ppo_sts2_sim_act1_run_v9_final.zip --n-envs 6 --net 256 256 --timesteps 3000000 --name ppo_sts2_sim_run_policy_v1`
3M decisions is about 75k runs. Watch `ep_rew_mean`: it's roughly floors × 0.1 + clears. If it's still rising at the end, resume for another 3M with `--resume models/ppo_sts2_sim_run_policy_v1_final.zip`.

- [ ] **Step 3: Evaluate v1**

Run: `../.venv/bin/python run.py --model models/ppo_sts2_sim_act1_run_v9_final.zip --maps generated --run-model models/ppo_sts2_sim_run_policy_v1_final.zip --runs 500 --n 16`
Success for the sub-project: `policy` cleared > `baseline` cleared.

- [ ] **Step 4: Retrain combat on run-policy runs → v10**

Run: `caffeinate -i ../.venv/bin/python -u train.py --backend sim --run-mode --run-model models/ppo_sts2_sim_run_policy_v1_final.zip --resume models/ppo_sts2_sim_act1_run_v9_final.zip --n-envs 6 --net 256 256 --timesteps 15000000 --name ppo_sts2_sim_act1_map_v10`
Then evaluate with `--model models/ppo_sts2_sim_act1_map_v10_final.zip` and the same `--run-model` (Step 3 command).

- [ ] **Step 5: Run policy v2 on v10, if v10 moved the numbers**

If Step 4's `policy` clear rate rose, train `ppo_sts2_sim_run_policy_v2` with `--resume models/ppo_sts2_sim_run_policy_v1_final.zip --combat-model models/ppo_sts2_sim_act1_map_v10_final.zip` for 3M steps. Evaluate it the same way. Stop when a round stops helping.

- [ ] **Step 6: Document and commit**

Add to `docs/modding-approach.md` a section `### 2026-10-18: Generated maps, shops and a run policy`. It should cover:
- what the sim run now includes, and the empty event/treasure/Neow placeholders
- the skipped map pruning
- a results table: strategy × clear rate, average floor, gold spent, where runs died (baseline, policy v1, v10 + v1, v2 if trained)
- the training settings used

Point to `docs/game-architecture.md` for the game rules rather than repeating them.

```bash
git add docs/modding-approach.md
git commit -m "Docs: run policy on generated maps, results

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
