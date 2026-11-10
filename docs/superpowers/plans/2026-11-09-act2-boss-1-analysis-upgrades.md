# Act 2 boss, part 1: boss analysis and card upgrades — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure why Act 2 boss fights are lost, then add card upgrades (upgraded cards, Smith at rest sites, upgraded rewards, Armaments, upgrade relics) to the sim, the agent and live play.

**Architecture:** An upgraded card is its own id, the base id plus `+` (`"BASH+"`), with its own `CardDef` in `sim/cards.py`. The engine, run and decks carry these ids unchanged. Observations stay keyed by base id: combat uses the existing `upgraded` card feature, and the run observation gains an upgraded-count vector. Models grow into the new inputs and actions with `grow.py`.

**Tech Stack:** Python 3 (agent/, gymnasium, sb3-contrib MaskablePPO), C# Harmony mod (mod/AutoSpire/), decompiled game source in `decompiled/`.

**Spec:** `docs/superpowers/specs/2026-11-09-act2-boss-design.md` (stages 1 and 2). Later stages get their own plans: part 2 potions, relics, colorless cards and Neow/Ancient; part 3 retrain; part 4 live.

## Global Constraints

- Gains must come from the sim matching the game more closely, never from the sim being easier (spec, anti-goals).
- Write every rule from `decompiled/` (each card's `OnUpgrade`, `CardFactory.RollForUpgrade`, `SmithRestSiteOption`), not from Slay the Spire 1.
- Every new mechanic is checked against the live game (`sim.validate`, `live_check.py`).
- Act 1 clear no more than 4 points below the grown reference.
- Push only to `mine`, never `origin`. Leave `mod/AutoSpire/obj/*` uncommitted. Don't change sim code in a checkout while a queue runs from it.
- Work in a new worktree `auto-spire-boss` on branch `boss`, from `rl-agent-sim` at 54740cf or later.
- Commands run from `agent/` with `PY=~/projects/sts2-rl-bot/auto-spire/.venv/bin/python`. Self-checks are modules: `$PY -m sim.test_engine`, `$PY -m sim.test_act`, `$PY -m test_run_env`, `$PY -m test_grow`, `$PY -m test_choice_test`. Each prints one `... ok` line and exits 0.
- Commit messages follow the repo's style (`Sim: ...`, `Run env: ...`, `Live: ...`, `Docs: ...`) and end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Docs follow `CLAUDE.md`'s scopes. Game rules go in `docs/game-architecture.md` (new section "Card upgrades"), progress in `docs/modding-approach.md`, and results in the spec.

## Review Focus

1. **An upgraded id reaching a lookup keyed by base id** (`CARD_INDEX`, `REMOVE` actions, the picker, shops, events, `validate.py`): every path must map with `base_id()` or crash loudly in tests. Task 5 runs 300 random-policy runs with upgrade-heavy decks.
2. **In-combat upgrades leaking into the run deck** (Armaments, Aggression): they last for that combat only. Test in Task 3.
3. **Thieving Hopper stealing an upgraded card:** `run.deck.remove(card)` must get the same `"X+"` id that's in the deck. Test in Task 3.
4. **Smith with nothing to upgrade:** the option is disabled (`Deck.UpgradableCardCount == 0`), and cards with `MaxUpgradeLevel` 0 (Slimed, Wound, other statuses and curses) are never offered. Test in Task 4.
5. **Act 1 seeds:** the reward upgrade roll is only made when its chance is above 0, so Act 1 maps and fights keep their seeds (my call, to keep evaluations comparable). Test in Task 4.

---

### Task 1: Boss analysis (spec stage 1)

**Files:**
- Create: `agent/boss_report.py`
- Modify: `docs/superpowers/specs/2026-11-09-act2-boss-design.md` (add "Analysis")

**Interfaces:**
- Produces: `python boss_report.py --model <combat.zip> --run-model <run.zip> --runs N --n 16 --out <file.jsonl>`. It writes one JSON line per Act 2 boss fight: `{"seed", "boss", "won", "hp", "max_hp", "deck", "relics", "potions", "potions_used", "turns", "hp_by_turn"}`. Part 4 reuses these lines as staged live states, so `deck`, `relics` and `potions` must be exact run state.
- Consumes: `run.generated_run`'s loop with `strategy="policy"`, and `RunPolicyEnv.play`.

- [ ] **Step 1:** Write `boss_report.py`. Wrap `RunPolicyEnv.play` so that for encounters in `HIVE_BOSSES` it records arrival state, then steps the fight itself (as `picker.play_fight` does), reading turn number and player HP from `env.client._combat` at each player turn. No changes to engine, env or run code. Use `multiprocessing` with `_init` the way `run.py` does.
- [ ] **Step 2:** Run with `--model models/ppo_sts2_sim_act2_b_final.zip --run-model models/ppo_sts2_sim_act2_run_v1_final.zip --runs 1500 --n 16 --out ~/projects/sts2-rl-bot/auto-spire/.superpowers/queue/boss_analysis.jsonl`. Expected: about 350 boss fights (117 per 500 runs), with exit 0. Needs AC power and `caffeinate -i`.
- [ ] **Step 3:** Print and write per boss: fights reached and won, mean arrival HP and max HP, deck size and its 10 most common cards, relic count, potions held and used, turn of death (median and spread), and mean damage taken per turn. Add these under a new "Analysis (2026-11-xx)" section in the spec, with 3–5 plain findings (for example "Knowledge Demon kills by turn 4 in most losses").
- [ ] **Step 4:** Commit `boss_report.py` and the spec (`Docs: Act 2 boss analysis`).

### Task 2: Upgraded card definitions

**Files:**
- Modify: `agent/sim/cards.py`
- Test: `agent/sim/test_engine.py`

**Interfaces:**
- Produces: in `sim/cards.py`:
  - `UPGRADES: dict[str, dict]`, the `CardDef` field changes per base id, read from each card's `OnUpgrade`.
  - `CARDS` also holds `"<ID>+"` for every upgradable card, built with `dataclasses.replace`.
  - `base_id(cid: str) -> str`, `is_upgraded(cid: str) -> bool`, and `upgrade(cid: str) -> str`, which returns `cid + "+"` if upgradable, else `cid` unchanged.
  - `UPGRADABLE: frozenset[str]`, the base ids whose `MaxUpgradeLevel` is above 0.
  - `card_to_dict("BASH+", ...)` returns `id` `"BASH"`, `upgraded: True`, `upgradeLevel: 1`, and the game's upgraded title (check the format live).
- Every list of base cards (`COMMONS`, `UNCOMMONS`, `RARES`, `GENERATED`, `env.CARD_IDS`, `run_env.CARD_IDS`) stays base-only.

- [ ] **Step 1: Write the failing tests** in `sim/test_engine.py`:

```python
from .cards import CARDS, UPGRADABLE, base_id, is_upgraded, upgrade, card_to_dict
assert CARDS["STRIKE_IRONCLAD+"].damage == 9 and CARDS["DEFEND_IRONCLAD+"].block == 8
assert (CARDS["BASH+"].damage, CARDS["BASH+"].vulnerable) == (10, 3)
assert CARDS["BODY_SLAM+"].cost == 0 and CARDS["HEADBUTT+"].damage == 12 and CARDS["ANGER+"].damage == 8
assert upgrade("SLIMED") == "SLIMED" and "WOUND" not in UPGRADABLE
assert upgrade("BASH+") == "BASH+" and base_id("BASH+") == "BASH" and is_upgraded("BASH+") and not is_upgraded("BASH")
assert all(c + "+" in CARDS for c in UPGRADABLE)
d = card_to_dict("BASH+", 2, True)
assert d["id"] == "BASH" and d["upgraded"] and d["upgradeLevel"] == 1
```

- [ ] **Step 2:** Run `$PY -m sim.test_engine`. Expected: FAIL on the import.
- [ ] **Step 3:** Implement. Fill `UPGRADES` for every card in `CARDS` from `decompiled/MegaCrit.Sts2.Core.Models.Cards/<Card>.cs`. A `special` card whose upgrade changes logic rather than a field gets an empty entry plus a comment naming what the engine must do (Task 3). Add the missing Ironclad Armaments as a `CardDef` (Common, 1, Self, block 5, `special=True`).
- [ ] **Step 4:** Run `$PY -m sim.test_engine`. Expected: `sim self-check ok`.
- [ ] **Step 5:** Commit (`Sim: upgraded card definitions`).

### Task 3: The engine plays upgraded cards

**Files:**
- Modify: `agent/sim/engine.py` (`_special` by `base_id`, Armaments, Aggression at line ~1754, `_steal`), `agent/sim/validate.py:228`
- Test: `agent/sim/test_engine.py`

**Interfaces:**
- Consumes: Task 2's `base_id`, `is_upgraded`, `upgrade`.
- Produces: `SimCombat` handles any `"X+"` in deck, hand and piles. Armaments asks through `_ask("upgrade", "ARMAMENTS")` with the hand's upgradable cards. `choose_card` answers it like Burning Pact. `ARMAMENTS+` upgrades every upgradable hand card without asking. In-combat upgrades replace the id in the pile for this fight only.

- [ ] **Step 1: Write the failing tests:**
  - A fight with `deck=["BASH+"] * 10` whose first play hits a 0-block enemy for 10 and applies 3 Vulnerable.
  - Armaments in hand with Strike: playing it holds `pending_choice`, and choosing Strike turns that hand slot into `"STRIKE_IRONCLAD+"`.
  - `ARMAMENTS+` upgrades every upgradable hand card.
  - After the fight, the deck passed to `fight()` is unchanged (no `+` added).
  - Aggression returns its card upgraded.
  - A Thieving Hopper steal from a deck holding `"BASH+"` puts `"BASH+"` in `combat.stolen`.
  - For every `special` card, playing its upgraded id runs without error, and every effect the source changes differs from the base.
- [ ] **Step 2:** Run `$PY -m sim.test_engine`. Expected: FAIL.
- [ ] **Step 3:** Implement. `_special` and every id check (`cid == "X"`, `in (...)`) go through `base_id`. Grep `engine.py` for each quoted card id to find them. Remove the "no upgrades" ponytail notes this resolves (engine.py:21–22, :1754, validate.py:228).
- [ ] **Step 4:** Run `$PY -m sim.test_engine`, then `$PY -m sim.test_act`. Expected: both ok.
- [ ] **Step 5: Live check.** Find the dev console command that upgrades a deck card (`MegaCrit.Sts2.Core.DevConsole`). Extend `AutoSpireClient.set_deck()` to set upgraded cards. Run `sim.validate` on random decks where half the cards are upgraded, over the Act 1 and Hive encounters. Expected: no mismatches beyond those already known (Tough Egg's Hatch counter). Record the step count in `docs/modding-approach.md`.
- [ ] **Step 6:** Commit (`Sim: play upgraded cards and Armaments`).

### Task 4: Upgrades in the run

**Files:**
- Modify: `agent/sim/act.py` (`REST_HEAL` area, `move` at line ~371, `offer`, `win`, `Run.add_card`, Armaments in `REWARD_POOLS["COMMON"]` and shops), `agent/sim/relics.py`
- Test: `agent/sim/test_act.py`

**Interfaces:**
- Produces:
  - `Run.rest_options() -> list[str]`, a subset of `["HEAL", "SMITH", "LIFT", "DIG"]` in that order, with `SMITH` only if the deck has an upgradable card.
  - `Run.rest(option: str, card: str | None = None) -> None`, where `card` is a base id in the deck.
  - Entering a `RestSite` no longer heals by itself. The env calls `rest`.
  - `Run.upgrade_card(base: str) -> None` upgrades one un-upgraded copy.
  - `offer()` upgrades each non-Rare card with chance `act * 0.25` (`UpgradedCardOddScaling`, A0), rolling only when the chance is above 0, and applies `ModifyCardRewardUpgradeOdds` relics.
  - Shop cards are never upgraded (`RollForUpgrade(..., -999999999)`).
  - Relics from the source: Whetstone, War Paint, Frozen Egg, Molten Egg, Toxic Egg, Girya (`LIFT`) and Shovel (`DIG`), plus any other relic whose only missing piece was upgrades. Each comes off the unmodeled list in `relics.py`.

- [ ] **Step 1: Write the failing tests** in `sim/test_act.py`:
  - Over 4,000 Act 2 offers (`run.act = 1`), the non-Rare upgraded share is within 0.22–0.28, and Rares are never upgraded.
  - With `run.act = 0`: 0 upgraded, and the Act 1 map, queue and first 3 offers for seeds 0–9 match the values before this task (capture them before changing the code).
  - Shop cards are never upgraded.
  - `rest("SMITH", "BASH")` turns one `"BASH"` into `"BASH+"`. `rest_options()` leaves out `SMITH` when every deck card is upgraded or not upgradable.
  - `rest("HEAL")` heals 30% of max HP, plus Regal Pillow as before.
  - Picking up Whetstone upgrades 2 random un-upgraded Attacks, and Molten Egg makes an added Attack upgraded.
  - Girya's `LIFT` and Shovel's `DIG` follow the source's counts and effects.
- [ ] **Step 2:** Run `$PY -m sim.test_act`. Expected: FAIL.
- [ ] **Step 3:** Implement. Check the 6 modeled events (`sim/events.py`) for upgrade effects and model any you find.
- [ ] **Step 4:** Run `$PY -m sim.test_act` and `$PY -m sim.test_engine`. Expected: both ok.
- [ ] **Step 5:** Document the rules in `docs/game-architecture.md`, "Card upgrades": the upgrade roll, Smith, shops, the relics, and Armaments. Commit (`Sim: upgrades in the run (Smith, rewards, relics)`).

### Task 5: Run policy and combat env learn upgrades

**Files:**
- Modify: `agent/run_env.py`, `agent/env.py`, `agent/grow.py`, `agent/run.py` (`baseline_action`)
- Test: `agent/test_run_env.py`, `agent/test_grow.py`

**Interfaces:**
- Consumes: Task 4's `rest_options`, `rest`, and `upgrade_card`.
- Produces:
  - `DECISIONS` gains `"rest"` at the end, with `HEAD_DECISIONS` unchanged.
  - New actions appended after `EVENT`: `REST = EVENT + EVENT_OPTIONS` (`HEAL`, `LIFT`, `DIG`), then `SMITH = REST + 3` followed by `len(CARD_IDS)` slots indexed by `CARD_INDEX[base]`. `N_ACTIONS` grows to match.
  - Observation blocks appended: a `rest` flag plus the 4 option-available flags, deck upgraded counts (`len(CARD_IDS)`, 0.5 per copy like the deck vector), and an upgraded flag per offer and shop slot.
  - Every `CARD_INDEX[c]` use goes through `base_id`.
  - Combat: `CARD_IDS` stays base-only and identity uses `base_id(card["id"])`. The Armaments `upgrade` choice uses the hand-slot choice actions.
  - `grow.py` maps the new blocks by name, so a grown model acts the same on old inputs.
  - `baseline_action` picks `HEAL` below 50% HP, else `SMITH` on the first upgradable non-basic card, else `HEAL` (my call, a simple baseline).

- [ ] **Step 1: Write the failing tests:**
  - `test_run_env`: at a rest site the mask allows exactly the `rest_options()` and, for `SMITH`, only the deck's upgradable base ids. Stepping `SMITH + CARD_INDEX["BASH"]` upgrades it. A deck holding `"BASH+"` lets `REMOVE + CARD_INDEX["BASH"]` remove it. `OBS_DIM` matches `_obs().shape`.
  - Review Focus 1: 300 runs with a random legal policy, each deck seeded with 6 upgraded cards, finish without an exception.
  - `test_grow`: a model grown from `ppo_sts2_sim_act2_run_v1_final.zip` gives the same action as the original on 200 recorded old observations (the existing fixture pattern).
- [ ] **Step 2:** Run `$PY -m test_run_env` and `$PY -m test_grow`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run all five self-checks. Expected: all ok.
- [ ] **Step 5:** Commit (`Run env: rest choices and upgraded cards`).

### Task 6: Live play with upgrades

**Files:**
- Modify: `mod/AutoSpire/AutoSpireRun.cs`, `mod/AutoSpire/AutoSpireMod.cs`, `agent/live.py`, `agent/client.py`, `agent/live_check.py`
- Docs: `docs/modding-approach.md`

**Interfaces:**
- Consumes: Task 5's `rest` decision and actions.
- Produces:
  - `/state` `player.deck` and `rewards` report `upgraded` per card (hand cards already do, `AutoSpireMod.cs:305`).
  - `/exec rest SMITH <deck index>` upgrades through `SmithRestSiteOption` and the `CardSelectCmd.Selector` hook, the same way prompts are answered now. `LIFT` and `DIG` work the same way.
  - `LiveRun` builds deck ids with `+` from `upgraded`. `live.py` asks the run policy at rest sites instead of always healing, and plays Armaments' `upgrade` prompt.

- [ ] **Step 1:** Add staged checks to `live_check.py`:
  - Smith upgrades the chosen card, and `/state` shows it upgraded.
  - An upgraded reward card arrives as `"X+"`.
  - Armaments and `ARMAMENTS+` in a real fight match the sim's hand after the play.
  - Girya's `LIFT` and Shovel's `DIG` match the sim.
- [ ] **Step 2:** Run `$PY live_check.py` with the game running. Expected: the new checks fail.
- [ ] **Step 3:** Implement. Build with `mod/build.sh`.
- [ ] **Step 4:** Run `$PY live_check.py`. Expected: every check passes (16 old plus the new ones), with no `[ERROR]` lines from the mod in `godot.log`.
- [ ] **Step 5:** Commit (`Live: Smith, upgraded cards and Armaments`). Leave `mod/AutoSpire/obj/*` out.

### Task 7: Grow the models and check nothing regressed

**Files:**
- Modify: `docs/superpowers/specs/2026-11-09-act2-boss-design.md` (add "Part 1 results")

- [ ] **Step 1:** Grow both models: `$PY grow.py models/ppo_sts2_sim_act2_b_final.zip models/ppo_sts2_sim_boss_g1.zip --env combat --insert-cards` and `$PY grow.py models/ppo_sts2_sim_act2_run_v1_final.zip models/ppo_sts2_sim_boss_run_g1.zip --env run --insert-cards`. Expected: both exit 0.
- [ ] **Step 2:** Evaluate: `$PY run.py --model models/ppo_sts2_sim_boss_g1.zip --maps generated --run-model models/ppo_sts2_sim_boss_run_g1.zip --runs 500 --n 16`. Expected: no crashes and `stuck=0`, with Act 1 within 4 points of 79.0%. The untrained model meets upgrades for the first time, so Act 2 may move either way. Record it as part 3's starting point.
- [ ] **Step 3:** Run `boss_report.py` on the grown pair (1,500 runs) and compare with Task 1's table in "Part 1 results".
- [ ] **Step 4:** Commit (`Docs: Act 2 boss part 1 results`). Report to the user, who decides when part 2 starts.
