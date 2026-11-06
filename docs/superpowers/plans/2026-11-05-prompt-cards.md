# Prompt Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The sim models Headbutt, Burning Pact and Brand, the agent chooses a card when they ask, and a test shows whether those choices make sense.

**Architecture:** `SimCombat` pauses mid-card with a pending choice and resumes through two new client commands. The combat env adds choice actions and inputs. `grow.py` learns to insert inputs and actions by card id, so v13 and v6p keep their training.

**Tech Stack:** Python, MaskablePPO (sb3_contrib), gymnasium. Tests are plain `assert` scripts run from `agent/`.

**Spec:** `docs/superpowers/specs/2026-11-05-prompt-cards-design.md`

## Global Constraints

- Armaments stays unavailable: it stays in `PROMPT_CARDS` and `REWARD_POOLS`, and never enters `CARDS`.
- Sim only. Nothing under `mod/` changes, and live play must never play or pick the three cards.
- Card rules come from `decompiled/MegaCrit.Sts2.Core.Models.Cards/` and `.../Commands/CardSelectCmd.cs`. Mark any known gap with a `ponytail:` comment.
- The practice flags are off in evaluation and in combat phase B.
- No new dependencies. Run from `agent/` with `../.venv/bin/python`.
- Leave `mod/AutoSpire/obj/*` uncommitted. Push only when the user asks, and only to `mine`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **One-Two Punch on Headbutt:** it plays twice, so two prompts appear, one after the other. Task 2.
2. **Headbutt kills the last enemy:** no prompt, and the fight ends cleanly. Task 2.
3. **Brand at 1 HP:** the player dies with no prompt, and nothing stays pending. Task 2.
4. **An autoplayed prompt card (Havoc):** it can't pause, so it picks at random, and the fight goes on. Task 2.
5. **A live hand holding Headbutt:** it stays masked with no `simRelics` in the state, and a live pick can't take it. Task 3.

---

### Task 1: `grow.py` inserts by map

**Files:**
- Create: `agent/test_data/grow_fixture.pkl`
- Modify: `agent/grow.py`, `agent/test_grow.py`

**Interfaces:**
- Produces: `insert_map(segments: list, old_ids: list[str], new_ids: list[str]) -> list[int]`, where each segment is an int (that many fixed positions) or `"cards"` (one position per card id), returning each old position's new index.
- Produces: `grow(old, env, obs_map: list[int] | None = None, act_map: list[int] | None = None)` and `check(old, new, obs_map=None, act_map=None, n=256)`. `None` keeps today's append behavior.
- Produces: the fixture, a pickle of `{"combat": dict, "combat_obs": ndarray, "run": Run, "decision": str, "offered": list, "run_obs": ndarray, "run_mask": ndarray}`, used by Tasks 3 and 4.

- [ ] **Step 1: Save the fixture from the code as it stands, before any card changes**

Use a fight with deck `starter_deck() + ["BLOODLETTING", "TRUE_GRIT"]` and `SimClient(seed=3)`, with `combat = client.combat()`. For the run, use `RunPolicyEnv().reset(seed=5)`, set `decision = "shop"`, `run.shop = make_shop(run.rng, run.card_odds, run.removals, run.bags)` and gold 500, and put `"TRUE_GRIT"` in the deck. Try further seeds until the shop stocks no Headbutt, Burning Pact or Brand, and assert that, because those become modeled in Task 2 and would change the mask. Store `_encode(combat)`, `env._obs()` and `env.action_masks()`. If `Run` won't pickle, stop and report it.

Check: `git status` shows only the new `.pkl`, and it loads back with equal arrays.

- [ ] **Step 2: Write the failing tests in `agent/test_grow.py`**

```python
from grow import insert_map
assert insert_map([2, "cards", 1], ["A", "C"], ["A", "B", "C"]) == [0, 1, 2, 4, 5]
assert insert_map(["cards", "cards"], ["A"], ["0", "A"]) == [1, 3]

obs_map, act_map = [0, 1, 3, 4, 5, 7], [0, 2, 3]  # 6 -> 9 inputs, 3 -> 5 actions, spread through
small = MaskablePPO("MlpPolicy", Toy(6, 3), policy_kwargs={"net_arch": [16, 16]}, n_steps=64, batch_size=32, device="cpu")
big = grow(small, Toy(9, 5), obs_map, act_map)
assert check(small, big, obs_map, act_map)
with torch.no_grad():
    big.policy.mlp_extractor.policy_net[0].weight[0, 3] += 1.0  # a position that should hold old input 2
assert not check(small, big, obs_map, act_map)
```

- [ ] **Step 3: Run it and see it fail**

Run: `../.venv/bin/python test_grow.py`
Expected: `ImportError` on `insert_map`.

- [ ] **Step 4: Implement `insert_map`, and the map arguments on `grow` and `check`**

The input layers of both `mlp_extractor` nets take `grown[:, obs_map] = w`. `action_net.weight` takes `grown[act_map, :] = w`, and `action_net.bias` takes `grown[act_map] = w`. Hidden layers and `value_net` copy as they are. `check` feeds random values at all new inputs and compares logits at `act_map`; all other logits must be 0.

- [ ] **Step 5: Run it and see it pass**

Run: `../.venv/bin/python test_grow.py`
Expected: `grow checks ok`.

- [ ] **Step 6: Commit**

`git add agent/grow.py agent/test_grow.py agent/test_data/grow_fixture.pkl`, message `grow.py: insert new inputs and actions by map`.

### Task 2: The three cards and the pending choice in the sim

**Files:**
- Modify: `agent/sim/cards.py`, `agent/sim/engine.py`, `agent/sim/act.py`, `agent/sim/test_engine.py`

**Interfaces:**
- Produces in `sim/cards.py`: `CHOICE_CARDS = ("BRAND", "BURNING_PACT", "HEADBUTT")`.
- Produces on `SimCombat`: `pending_choice: dict | None` (`{"kind": "hand" | "discard", "source": card_id}`); `choose_card(hand_index: int) -> dict`; `choose_discard(card_id: str) -> dict`; `choice_log: list[tuple[str, str, tuple[str, ...]]]` of (source, picked, options), for paused prompts only, cleared by `fight`. `combat_dict()` gains `"choice"`: the pending dict or `None`.
- Produces on `SimClient.exec`: `choose <i>` and `choose_discard <id>`.
- Produces in `sim/act.py`: `PROMPT_CARDS = {"ARMAMENTS": "Skill"}`, `REWARD_POOLS["COMMON"] = COMMONS + ("ARMAMENTS",)`, with `UNCOMMON` and `RARE` being just `UNCOMMONS` and `RARES`.

- [ ] **Step 1: Write the failing tests, appended to `agent/sim/test_engine.py`, using its `solo()` helper**

```python
# Headbutt: 9 damage, then a discard card goes on top of the draw pile.
c = solo(["HEADBUTT", "STRIKE_IRONCLAD"])
c.discard_pile = ["BASH", "DEFEND_IRONCLAD"]
hp = c.enemies[0].hp
assert c.play_card(0, 1)["ok"]
assert c.pending_choice == {"kind": "discard", "source": "HEADBUTT"} and c.enemies[0].hp == hp - 9 and c.energy == 2
assert c.combat_dict()["choice"] == c.pending_choice
assert c.play_card(0, 1)["error"] == "choice_pending" and c.end_turn()["error"] == "choice_pending"
assert c.choose_discard("BASH")["ok"]
assert c.draw_pile[-1] == "BASH" and c.pending_choice is None and c.discard_pile == ["DEFEND_IRONCLAD", "HEADBUTT"]
assert c.choice_log == [("HEADBUTT", "BASH", ("BASH", "DEFEND_IRONCLAD"))]

# Burning Pact: exhaust from hand, then draw 2.
c = solo(["BURNING_PACT", "WOUND", "STRIKE_IRONCLAD"])
c.play_card(0)
assert c.pending_choice["kind"] == "hand" and c.hand == ["WOUND", "STRIKE_IRONCLAD"]
assert c.choose_card(0)["ok"]
assert c.exhaust_pile == ["WOUND"] and len(c.hand) == 3 and c.discard_pile == ["BURNING_PACT"]

# Brand: lose 1 HP first, exhaust, then 1 Strength. Costs 0.
c = solo(["BRAND", "WOUND", "BASH"])
hp, s = c.player_hp, c.strength
c.play_card(0)
assert c.player_hp == hp - 1 and c.energy == 3 and c.strength == s
c.choose_card(1)
assert c.exhaust_pile == ["BASH"] and c.strength == s + 1

# CardSelectCmd: one legal card is taken with no prompt; none means the rest still resolves.
c = solo(["BURNING_PACT", "WOUND"]); c.play_card(0)
assert c.pending_choice is None and c.exhaust_pile == ["WOUND"] and len(c.hand) == 2 and not c.choice_log
c = solo(["BRAND"]); s = c.strength; c.play_card(0)
assert c.pending_choice is None and c.strength == s + 1 and not c.exhaust_pile
c = solo(["HEADBUTT"]); c.play_card(0, 1)
assert c.pending_choice is None and c.discard_pile == ["HEADBUTT"]

# Review focus 1: One-Two Punch plays Headbutt twice, so two prompts.
c = solo(["HEADBUTT"]); c.discard_pile = ["BASH", "DEFEND_IRONCLAD", "STRIKE_IRONCLAD"]
c.pw["OneTwoPunchPower"] = 1
c.play_card(0, 1); c.choose_discard("BASH")
assert c.pending_choice == {"kind": "discard", "source": "HEADBUTT"}
c.choose_discard("DEFEND_IRONCLAD")
assert c.pending_choice is None and c.draw_pile[-2:] == ["BASH", "DEFEND_IRONCLAD"] and c.discard_pile == ["STRIKE_IRONCLAD", "HEADBUTT"]

# Review focus 2: killing the last enemy ends the fight with no prompt.
c = solo(["HEADBUTT"]); c.discard_pile = ["BASH", "DEFEND_IRONCLAD"]; c.enemies[0].hp = 1
c.play_card(0, 1)
assert not c.in_combat and c.pending_choice is None

# Review focus 3: Brand at 1 HP is lethal before the prompt.
c = solo(["BRAND", "WOUND", "BASH"]); c.player_hp = 1
c.play_card(0)
assert not c.in_combat and c.pending_choice is None

# Review focus 4: an autoplay can't pause. Havoc plays Headbutt and it picks at random.
c = solo(["HAVOC"]); c.draw_pile = ["HEADBUTT"]; c.discard_pile = ["BASH", "DEFEND_IRONCLAD"]
c.play_card(0)
assert c.pending_choice is None and c.in_combat and "HEADBUTT" in c.exhaust_pile and len(c.draw_pile) == 1

# A new fight clears a pending choice.
c = solo(["BRAND", "WOUND", "BASH"]); c.play_card(0); c.fight("MAWLER_NORMAL")
assert c.pending_choice is None and not c.choice_log

# Client commands, and all three enter the generated pool and the reward pools.
client = SimClient(seed=1); client.exec("fight MAWLER_NORMAL"); cc = client._combat
cc.hand, cc.discard_pile = ["BRAND", "WOUND", "BASH"], []
client.play(0); assert client.exec("choose 0")["ok"] and cc.exhaust_pile == ["WOUND"]
cc.hand, cc.discard_pile = ["HEADBUTT"], ["BASH", "WOUND"]
client.play(0, 1); assert client.exec("choose_discard WOUND")["ok"] and cc.draw_pile[-1] == "WOUND"
from sim.act import PROMPT_CARDS, REWARD_POOLS
from sim.cards import CHOICE_CARDS, GENERATED
assert set(CHOICE_CARDS) <= set(GENERATED) and "ARMAMENTS" not in CARDS and PROMPT_CARDS == {"ARMAMENTS": "Skill"}
assert "HEADBUTT" in REWARD_POOLS["COMMON"] and REWARD_POOLS["COMMON"].count("ARMAMENTS") == 1
assert "BURNING_PACT" in REWARD_POOLS["UNCOMMON"] and "BRAND" in REWARD_POOLS["RARE"]
```

- [ ] **Step 2: Run them and see them fail**

Run: `../.venv/bin/python -m sim.test_engine`
Expected: `AssertionError` or `KeyError` on `HEADBUTT`.

- [ ] **Step 3: Add the card definitions**

Headbutt: Attack, cost 1, AnyEnemy, Common, damage 9. Burning Pact: Skill, cost 1, Self, Uncommon. Brand: Skill, cost 0, Self, Rare. All three use `special=True`. Update the `cards.py` docstring and the `GENERATED` `ponytail:` comment, then remove the two moved ids from `PROMPT_CARDS` and `REWARD_POOLS`.

- [ ] **Step 4: Implement the pause**

Split `_play` so one play can stop after `_resolve` and pick up where it left off:
- `play_card` sets `self._pausable = True` just for its `_play` call. `_autoplay` sets it to `False` and restores it afterwards.
- `_special` runs a card's effects up to the prompt, then calls `_ask(kind, source)`. `_ask` reads the options. It applies `_finish_choice(source, None)` when combat is ending or there are no options, and auto-picks when there's one option. With 2+ options it picks with `self.rng.choice` when not pausable (with a `ponytail:` comment), else sets `pending_choice`.
- `_finish_choice(source, picked)` holds what follows the prompt. Burning Pact: exhaust the card if there is one, then `_draw(2)`. Brand: exhaust, then `_gain_strength(1)`. Headbutt: `draw_pile.append(picked)`.
- When `_resolve` returns with a choice pending, `_play` stores what the rest of the play needs (card, target, x, force_exhaust, energy_value, plays left, `mine`, `outer`) and returns with `_effect_depth` still raised. `play_card` returns `{"ok": True, "choice": pending_choice}`.
- `choose_card` and `choose_discard` validate the input, log to `choice_log`, clear pending, run `_finish_choice`, lower `_effect_depth`, then continue with AfterCardPlayed, any further plays, the result pile and `_check_win`. Invalid input returns `{"error": "invalid_choice"}`.
- `play_card`, `use_potion` and `end_turn` return `{"error": "choice_pending"}` while pending. `fight` clears `pending_choice` and `choice_log`.

Headbutt's damage uses `_hit`, as generic cards do, so Pen Nib and Strength apply. Brand's HP loss uses `_lose_hp(1, from_card=True)`.

- [ ] **Step 5: Run the sim tests and see them pass**

Run: `../.venv/bin/python -m sim.test_engine && ../.venv/bin/python -m sim.test_act`
Expected: `sim self-check ok`, `act self-check ok`, `event checks ok`.

- [ ] **Step 6: Commit**

`git add agent/sim`, message `Sim: Headbutt, Burning Pact and Brand, with a pending card choice`.

### Task 3: Combat env, grow maps and live safety

**Files:**
- Modify: `agent/env.py`, `agent/sim/validate.py`, `agent/run.py`, `agent/picker.py`, `agent/train.py`, `agent/grow.py`, `agent/test_run_env.py`

**Interfaces:**
- Consumes: `CHOICE_CARDS`, `combat_dict()["choice"]`, the client commands (Task 2); `insert_map` (Task 1).
- Produces in `env.py`: `CHOOSE_HAND = POTION_ACTION + MAX_POTION_SLOTS * MAX_ENEMIES`, `CHOOSE_DISCARD = CHOOSE_HAND + MAX_HAND`, `N_ACTIONS = CHOOSE_DISCARD + len(CARD_IDS)`; `CHOICE_FEATURES = 2 + len(CHOICE_CARDS)`, appended last to `OBS_DIM` (hand flag, discard flag, source one-hot).
- Produces in `env.py`: `combat_maps() -> tuple[list[int], list[int]]`; `random_deck(rng, prompt_practice: bool = False)`; `STS2CombatEnv(..., prompt_practice: bool = False)`.
- Produces in `grow.py`: `--insert-cards`, which passes `combat_maps()` to `grow` and `check` for `--env combat`. Task 4 adds `run_maps()` for `--env run`.
- Produces in `train.py`: `--prompt-practice`.

- [ ] **Step 1: Write the failing tests, appended to `agent/test_run_env.py`**

```python
import pickle
from env import CHOOSE_DISCARD, CHOOSE_HAND, CHOICE_FEATURES, END_TURN, combat_maps, random_deck
from sim.cards import CHOICE_CARDS
fx = pickle.load(open("test_data/grow_fixture.pkl", "rb"))

# Every old input has the same value at its new index, and new inputs read 0 with no new cards.
obs_map, act_map = combat_maps()
new_obs = _encode(fx["combat"])
assert np.array_equal(new_obs[obs_map], fx["combat_obs"])
assert not np.delete(new_obs, obs_map).any()
assert act_map == list(range(CHOOSE_HAND)) and COMBAT_OBS == len(new_obs)

def choice_env(hand, discard=()):
    env = STS2CombatEnv(encounter="MAWLER_NORMAL", client=SimClient(seed=0))
    env.deck, env.potions, env.relics, env.relic_state = list(hand), [], set(), {}
    env._episode_count = 1
    env.reset(seed=0)
    c = env.client._combat
    c.hand, c.discard_pile, c.energy = list(hand), list(discard), 3
    env._combat = env.client.combat()
    return env, c

# A hand prompt: only the legal slots are open, and the action resolves it.
env, c = choice_env(["BURNING_PACT", "WOUND", "BASH"])
env.step(0)
m = env.action_masks()
assert m.nonzero()[0].tolist() == [CHOOSE_HAND, CHOOSE_HAND + 1]
obs = _encode(env._combat)
assert obs[-CHOICE_FEATURES] == 1 and obs[-CHOICE_FEATURES + 2 + CHOICE_CARDS.index("BURNING_PACT")] == 1
env.step(CHOOSE_HAND + 1)
assert c.exhaust_pile == ["BASH"] and c.pending_choice is None and env.action_masks()[END_TURN]

# A discard prompt: open by card id.
env, c = choice_env(["HEADBUTT"], ["BASH", "WOUND", "WOUND"])
env.step(0)
m = env.action_masks()
assert m.nonzero()[0].tolist() == sorted(CHOOSE_DISCARD + CARD_IDS.index(x) for x in ("BASH", "WOUND"))
env.step(CHOOSE_DISCARD + CARD_IDS.index("BASH"))
assert c.draw_pile[-1] == "BASH"

# Review focus 5: live has no simRelics, so the three cards stay masked and a live pick can't take them.
live = {k: v for k, v in env.client.combat().items() if k != "simRelics"}
live["choice"] = None
live["player"]["hand"] = [card_to_dict("BRAND", 0, True)]
env._combat = live
assert not env.action_masks()[0]
from run import live_offer
assert live_offer(["BRAND", "BASH", "ARMAMENTS"]) == ["BASH", "ARMAMENTS"]

# Prompt practice, in decks only and only when asked.
rng = np.random.default_rng(0)
decks = [random_deck(rng, prompt_practice=True) for _ in range(4000)]
assert 0.50 < np.mean([any(x in CHOICE_CARDS for x in d) for d in decks]) < 0.68
assert 0.20 < np.mean(["WOUND" in d for d in decks]) < 0.30
assert all(d.count("WOUND") <= 2 for d in decks)
assert set(CHOICE_CARDS) <= {x for d in decks for x in d}
assert not any("WOUND" in random_deck(rng) for _ in range(500))
print("choice env checks ok")
```

Import `card_to_dict` and `CARD_IDS` at the top of this block if they aren't already imported. Adding 3 cards also changes this file's size asserts: update `N_ACTIONS == 122` to `N_ACTIONS == 125`, and the `OBS_DIM` expression to the new card count. Change only those constants, and only those lines.

- [ ] **Step 2: Run it and see it fail**

Run: `../.venv/bin/python test_run_env.py`
Expected: `ImportError` on `CHOOSE_DISCARD`.

- [ ] **Step 3: Implement the env, maps and practice**

- `CARD_IDS` stays `sorted(CARDS)`.
- `_encode` appends the choice block from `combat.get("choice")`.
- `step` sends `exec(f"choose {a - CHOOSE_HAND}")` or `exec(f"choose_discard {CARD_IDS[a - CHOOSE_DISCARD]}")`, checked before the potion branch.
- `action_masks`: during a choice, only legal choice actions are open. Otherwise the rule becomes `c["canPlay"] and c["id"] in CARDS and (c["id"] not in CHOICE_CARDS or "simRelics" in self._combat)`.
- `random_deck` with practice: with probability 0.5 add one card from `CHOICE_CARDS`, chosen evenly, and with probability 0.5 of those also add 1 or 2 Wounds (evenly).

```python
def combat_maps():
    old_ids = sorted(set(CARD_IDS) - set(CHOICE_CARDS))
    rest = MAX_ENEMIES * ENEMY_FEATURES + POTION_FEATURES + RELIC_FEATURES
    return (insert_map([6, "cards"] * MAX_HAND + [PLAYER_FEATURES] + ["cards"] * 3 + [rest], old_ids, CARD_IDS),
            list(range(CHOOSE_HAND)))
```

- [ ] **Step 4: Keep live play away from the three cards**

- `run.py`: add `live_offer(offered: list[str]) -> list[str]`, dropping `CHOICE_CARDS`, and use it in `live_run` before `choose("mc", ...)`.
- `validate.py`: `ids()` and the two `in CARDS` checks treat `CHOICE_CARDS` as unmodeled.
- `picker.py`: update the docstring so it names only Armaments as unmodeled.
- `train.py`: add `--prompt-practice`, passed to both `STS2CombatEnv` calls. Add the same keyword to `STS2CombatEnv`, used by `reset` when `random_decks` is on.

- [ ] **Step 5: Run the checks and see them pass**

Run: `../.venv/bin/python test_run_env.py 2>/dev/null | tail -1 && ../.venv/bin/python -c "import run, picker, train"`
Expected: `choice env checks ok`, with no import error.

- [ ] **Step 6: Commit**

`git add agent`, message `Combat env: choice actions and inputs, prompt practice, live stays masked`.

### Task 4: Run policy, the report and the grown models

**Files:**
- Modify: `agent/run_env.py`, `agent/run.py`, `agent/test_run_env.py`

**Interfaces:**
- Consumes: `insert_map`, `CHOICE_CARDS`, `choice_log`, the fixture.
- Produces in `run_env.py`: `run_maps() -> tuple[list[int], list[int]]`; `info["choice_log"]`, the whole run's (source, picked, options).
- Produces in `run.py`: `choice_report(rs: list[dict]) -> str`, printed after `event_report`.

- [ ] **Step 1: Write the failing tests, appended to `agent/test_run_env.py`**

```python
from run_env import REMOVE, run_maps
obs_map, act_map = run_maps()
renv.reset(seed=1)
renv.run, renv.decision, renv.offered = fx["run"], fx["decision"], fx["offered"]
renv.back = "path"
new_obs = renv._obs()
assert np.array_equal(new_obs[obs_map], fx["run_obs"])
assert not np.delete(new_obs, obs_map).any()
assert np.array_equal(renv.action_masks()[act_map], fx["run_mask"])
old_ids = sorted(set(CARD_IDS) - set(CHOICE_CARDS))
assert act_map[REMOVE + old_ids.index("TRUE_GRIT")] == REMOVE + CARD_IDS.index("TRUE_GRIT")

# The three cards can be picked; Armaments can't.
renv.reset(seed=1)
renv.decision, renv.offered = "pick", ["HEADBUTT", "ARMAMENTS", "BRAND"]
m = renv.action_masks()
assert m[PICK] and not m[PICK + 1] and m[PICK + 2]

# Choices made in a run's fights reach info, and the report reads them.
from run import choice_report
line = choice_report([{"choice_log": [("BRAND", "WOUND", ("WOUND", "BASH")), ("HEADBUTT", "BASH", ("BASH", "WOUND"))]}])
assert "BRAND: 1" in line and "junk 100%" in line and "HEADBUTT: 1" in line
print("run choice checks ok")
```

- [ ] **Step 2: Run it and see it fail**

Run: `../.venv/bin/python test_run_env.py 2>/dev/null | tail -3`
Expected: `ImportError` on `run_maps`.

- [ ] **Step 3: Implement**

```python
def run_maps():
    old_ids = sorted(set(CARD_IDS) - set(CHOICE_CARDS))
    tail = 2 + LOOKAHEAD * COLS * CELL_FEATURES + POTION_OBS + RELIC_OBS + 1 + len(MODELED_EVENTS) + EVENT_OPTIONS * 3
    obs = [len(HEAD_DECISIONS) + 5, "cards", len(BOSSES)] + ["cards", 2] * len(SHOP_SLOTS) + [tail, "cards"]
    return insert_map(obs, old_ids, CARD_IDS), insert_map([REMOVE, "cards", N_ACTIONS - REMOVE - len(CARD_IDS)], old_ids, CARD_IDS)
```

`play()` extends a per-run list from `self.fight_env.client._combat.choice_log` after each fight, and `reset` clears it. Add the `--env run` branch of `--insert-cards`. `choice_report` prints, per card, the count and the share of prompts that chose a junk card (`CARDS[c].rarity == "Status"`) among prompts offering junk and non-junk.

- [ ] **Step 4: Run the whole suite and grow the real models**

Run: `sh ../.superpowers/sdd/2026-11-04-relics/suite.sh`
Expected: ends `suite ok`.

Run: `../.venv/bin/python grow.py models/ppo_sts2_sim_act1_rel_v13_final.zip models/ppo_sts2_sim_act1_pc_v13c.zip --env combat --insert-cards`
Run: `../.venv/bin/python grow.py models/ppo_sts2_sim_run_policy_v6p_final.zip models/ppo_sts2_sim_run_policy_v6pc.zip --env run --insert-cards`
Expected: both print `grow self-check ok`.

Then run 40 maps as a smoke test and confirm the clear rate is near 80%, not near 0: `../.venv/bin/python run.py --model models/ppo_sts2_sim_act1_pc_v13c.zip --maps generated --run-model models/ppo_sts2_sim_run_policy_v6pc.zip --runs 40 --n 2`. A wrong map shows up here.

- [ ] **Step 5: Commit**

`git add agent`, message `Run policy: pick the three cards, report their choices, grow by card id`.

### Task 5: The choice test

**Files:**
- Create: `agent/choice_test.py`, `agent/test_choice_test.py`

**Interfaces:**
- Consumes: `STS2CombatEnv`, `random_deck`, `_encode`, `card_to_dict`, `CHOICE_CARDS`.
- Produces: `score_junk(prompts: list[dict]) -> tuple[float, float]` (rate, random rate); `score_headbutt(prompts) -> tuple[float, float]`; `passes_junk(rate, chance) -> bool`, true when `rate > 0.5 and rate >= 2 * chance`; `passes_headbutt(rate, chance) -> bool`, true when `rate >= 1.5 * chance`; `passes_flip(rate) -> bool`, true when `rate > 0.5`; `passes_hp(low, high) -> bool`, true when `low - high >= 0.10`.
- Produces: `collect(model, card, fights=200, seed=0) -> list[dict]`, each with `source`, `options`, `picked`, `combat`. CLI: `python choice_test.py <combat_model.zip>`.

- [ ] **Step 1: Write the failing test in `agent/test_choice_test.py`**

```python
from choice_test import passes_flip, passes_headbutt, passes_hp, passes_junk, score_headbutt, score_junk

hand = lambda picked: {"source": "BRAND", "options": ["WOUND", "BASH", "BASH", "BASH"], "picked": picked}
assert score_junk([hand("WOUND")] * 3 + [hand("BASH")]) == (0.75, 0.25)
assert passes_junk(0.75, 0.25) and not passes_junk(0.25, 0.25)  # a random chooser fails
assert not passes_junk(0.5, 0.1)  # the bar is over 50%
assert not passes_junk(0.6, 0.4)  # and twice chance
assert score_junk([{"source": "BRAND", "options": ["BASH", "BASH"], "picked": "BASH"}]) == (0.0, 0.0)  # no junk: not scored

disc = lambda picked: {"source": "HEADBUTT", "options": ["BASH", "STRIKE_IRONCLAD", "WOUND", "DEFEND_IRONCLAD"], "picked": picked}
assert score_headbutt([disc("BASH")] * 3 + [disc("WOUND")]) == (0.75, 0.25)
assert passes_headbutt(0.75, 0.25) and not passes_headbutt(0.3, 0.25)
assert passes_flip(0.51) and not passes_flip(0.5)
assert passes_hp(0.5, 0.4) and not passes_hp(0.5, 0.45)
print("choice test checks ok")
```

Bash counts as non-basic here: basic means Strike or Defend, as the spec says.

- [ ] **Step 2: Run it and see it fail**

Run: `../.venv/bin/python test_choice_test.py`
Expected: `ModuleNotFoundError: choice_test`.

- [ ] **Step 3: Implement `agent/choice_test.py`**

`collect` plays each fight with a deck of `random_deck(rng) + [card, "WOUND", "WOUND"]`, across `ENCOUNTER_GROUPS["act1"]`, with no relics or potions, always taking the highest-probability action. Before each action it records prompts with 2+ options, keeping a `copy.deepcopy` of the combat dict. Read each pick back from the action taken.

The four rows, using the spec's definitions:
1. **Junk:** `score_junk` on Burning Pact and Brand prompts, each card alone.
2. **Swap:** at prompts with no junk, replace a hand card other than the one picked with `card_to_dict("WOUND", -1, False)`, read the choice again with `env._combat` set to that dict, and report the share moving to the Wound.
3. **Headbutt rate:** `score_headbutt` on prompts with both groups.
4. **Headbutt HP:** at prompts with an attack and a block card (`CARDS[c].block > 0`) in discard, set `player.hp` to `int(0.15 * maxHp)` and then `maxHp`, read the choice at each, and report block-card share at each.

Print one line per row with n, the measured value and PASS or FAIL, then `ALL PASS` or `NOT ALL PASS`. Exit 0 either way. Print a warning on any row with n below 30.

- [ ] **Step 4: Run it and see it pass, then run the CLI on the grown model**

Run: `../.venv/bin/python test_choice_test.py`
Expected: `choice test checks ok`.

Run: `../.venv/bin/python choice_test.py models/ppo_sts2_sim_act1_pc_v13c.zip`
Expected: it finishes and prints all four rows. The grown model always chooses the first legal card, so these rows should sit near chance. Record the output in the ledger as the floor.

- [ ] **Step 5: Commit**

`git add agent/choice_test.py agent/test_choice_test.py`, message `choice_test.py: do card choices make sense and change with the situation`.

### Task 6: Train, test, document

**Files:**
- Create: `.superpowers/queue/prompt_cards.sh` (untracked)
- Modify: `docs/modding-approach.md`, `docs/game-architecture.md`, `docs/superpowers/specs/2026-11-05-prompt-cards-design.md`

- [ ] **Step 1: Run a whole-branch review before any training**

A sim bug found after training wastes about 15 hours. Fix what's real and commit.

- [ ] **Step 2: Write and start the queue, from a frozen copy**

Run: `git worktree add --detach ../auto-spire-pc HEAD && ln -s ../../auto-spire/agent/models ../auto-spire-pc/agent/models`

The script follows `events_v6p.sh`: the same `stage` function, waits for AC power, and each stage runs under `caffeinate -i`, from `../auto-spire-pc/agent`, with `C=models/ppo_sts2_sim_act1_pc` and `R=models/ppo_sts2_sim_run_policy`:

```
ref:     run.py --model $C_v13c.zip --maps generated --run-model $R_v6pc.zip --runs 500 --n 16
phase A: train.py --backend sim --encounters act1 --random-decks --prompt-practice --resume $C_v13c.zip --n-envs 6 --net 256 256 --timesteps 15000000 --name ppo_sts2_sim_act1_pc_v14a
phase B: train.py --backend sim --run-mode --run-model $R_v6pc.zip --resume $C_v14a_final.zip --n-envs 6 --net 256 256 --timesteps 20000000 --name ppo_sts2_sim_act1_pc_v14
run:     train.py --backend sim --run-policy --event-practice --combat-model $C_v14_final.zip --resume $R_v6pc.zip --n-envs 6 --net 256 256 --timesteps 4000000 --name ppo_sts2_sim_run_policy_v7
eval:    run.py --model $C_v14_final.zip --maps generated --run-model $R_v7_final.zip --runs 500 --n 16
test:    choice_test.py $C_v14_final.zip
```

- [ ] **Step 3: Read the results against the spec**

Success means `ALL PASS` from the choice test. The clear rate should stay within 4 points of the reference. Report the real-run counts from `choice_report` too, and say plainly if a row failed. If a row has n below 30, raise `fights` for that card and rerun only the test.

- [ ] **Step 4: Document and commit**

- `docs/game-architecture.md`: a "Card choices" section with the `CardSelectCmd` rules and the three cards, and point the spec's table to it, so the rules live in one place.
- `docs/modding-approach.md`: `### 2026-11-05: Prompt cards`, with a short summary and a pointer to the spec's "Results".
- The spec: a "Results" section with the clear-rate table (reference and v14 + v7), the choice test rows, the real-run counts and the kept models.
- `README` and the `sim/engine.py` docstring: update anything that still calls these cards unmodeled.

`git add docs agent`, message `Docs: prompt cards results`.
