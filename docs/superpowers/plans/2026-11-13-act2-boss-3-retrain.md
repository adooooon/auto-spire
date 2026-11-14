# Act 2 boss, part 3: retrain and evaluate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retrain the combat and run policies on the expanded sim (upgrades and colorless cards) and measure them against the Act 2 boss goal, in time for the user's Project Expo poster.

**Architecture:** Two small training-input fixes first: random training decks get upgrades, Armaments and colorless cards, and the bot sees every copy of a power that can stack as separate copies. Then a queue script runs the same three training stages as the Act 2 queue (combat A, combat B in whole runs, run policy R) from the grown g2 models, from a frozen worktree. Then an evaluation in the spec's terms.

**Tech Stack:** Python 3 (agent/, gymnasium, sb3-contrib MaskablePPO), zsh queue script.

**Spec:** `docs/superpowers/specs/2026-11-09-act2-boss-design.md`, stage 4 (retrain and evaluate in the sim). Plans 2b and 2c are put off until after the Expo (user's call, 2026-11-13): this retrain uses what's modeled now.

## Global Constraints

- **Deadline:** the user's Project Expo. Everything done by 2026-11-24, with results ready for the poster by about 2026-11-20. The training budget below fits that with slack. Don't add stages.
- **Success 1 (spec):** the agent wins more than 50% of the Act 2 boss fights it reaches, over at least 300 boss fights, reported per boss.
- **Guard (spec):** the share of runs that reach the Act 2 boss and the Act 2 clear rate must not fall below the reference.
- **Act 1 (spec):** clear no more than 4 points below the grown reference, 81.0% (g2, Part 2a results).
- **Gate (spec):** if success 1 or its guard is missed, stop and report before any real-game work, and bring the boss-practice decision to the user.
- **Anti-goal (spec):** gains must come from the sim matching the game more closely and the agent playing better, never from the sim being easier.
- **Training rules:**
  - AC power, lid open, `caffeinate -i`.
  - Run from a frozen worktree as a queue under `~/projects/sts2-rl-bot/auto-spire/.superpowers/queue/` with `status.txt`, like `act2.sh`.
  - Don't change sim code in a checkout while its queue runs.
- **Git:**
  - Work in a new worktree `auto-spire-retrain` on branch `retrain`, from `rl-agent-sim` at 8a2b3f3 or later. Symlink `.venv`, `decompiled` and `agent/models` from the main checkout.
  - Push only to `mine`, never `origin`. Leave `mod/AutoSpire/obj/*` uncommitted. Never commit model zips.
- **Commands:**
  - Run from `agent/` with `PY=~/projects/sts2-rl-bot/auto-spire/.venv/bin/python`.
  - The five self-checks are `$PY -m sim.test_engine`, `$PY -m sim.test_act`, `$PY -m test_run_env`, `$PY -m test_grow` and `$PY -m test_choice_test`. Each prints `... ok` and exits 0.
- **Commits:** follow the repo's style (`Env: ...`, `Queue: ...`, `Docs: ...`) and end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Training decks and real decks match in kind:**
   - Random training decks must only hold cards a run can produce.
   - They must not hold `NOT_BUYABLE` cards (Splash, Alchemize), statuses as deck cards, or upgraded copies of cards that can't be upgraded.
   - Test in Task 1.
2. **A grown model's old inputs keep their values:** the instanced-power change alters values in existing inputs, not the layout. With a single copy of each power, the observation must stay exactly as before. Test in Task 1.
3. **A queue stage fails or the laptop loses AC power:** the queue waits for AC before each stage, stops on a non-zero exit with `STOPPED at <stage>` in `status.txt`, and can resume from the failed stage. Check in Task 2.
4. **A stage starts from the wrong model:** each stage resumes from the previous stage's `_final.zip`, and the grown g2 models are the only inputs. Check in Task 2's dry run.
5. **Reading the results:** the boss win rate is counted over boss fights reached, with the guard numbers next to it, so a bot that dies earlier can't look better. Task 4 reports both.

---

### Task 1: Training decks and stackable-power observation

**Files:**
- Modify: `agent/env.py` (`random_deck`, `_power`)
- Test: `agent/test_run_env.py`

**Interfaces:**
- Produces:
  - `random_deck(rng, prompt_practice=False) -> list[str]`, which now also deals:
    - Upgrades: each card in the deck (starter cards included) becomes `upgrade(card)` with chance 0.2. That's my call, between Act 1's 0 and Act 2's 0.25 reward roll plus Smith.
    - Armaments in the Common pool (`COMMONS` leaves it out on purpose, for seeds).
    - With chance 0.5, 1–2 random colorless cards from `COLORLESS` minus `NOT_BUYABLE`, Uncommon 75% and Rare 25% (my call; shops stock one of each).
  - With `prompt_practice`, the seeded prompt card is drawn from `CHOICE_CARDS + ("ARMAMENTS",) + COLORLESS_PROMPT_CARDS`, instead of `CHOICE_CARDS` alone.
  - `_power(entity, name)` sums the amounts of every instance of a stackable power (`AutomationPower`, `PanachePower`, `RollingBoulderPower`). For `TheBombPower` it returns the smallest amount, the turns until the next Bomb goes off. It is unchanged for every other power.

- [ ] **Step 1: Write the failing tests** in `test_run_env.py`:
  - Over 2,000 `random_deck` draws: the upgraded share of upgradable cards is within 0.17–0.23. At least one deck holds `"ARMAMENTS"`. The share of decks with a colorless card is within 0.45–0.55. No deck holds a `NOT_BUYABLE` card or an upgraded non-upgradable id.
  - With `prompt_practice=True`, `"DISCOVERY"` (or another colorless prompt card) and `"ARMAMENTS"` each appear.
  - `_power` with two `RollingBoulderPower` entries (5 and 10) returns 15. With two `TheBombPower` entries (3 and 1) it returns 1. With one entry of any power, it returns that entry's amount.
  - Review Focus 2: a combat observation from a fixed seeded fight with one copy of each power is identical before and after (record it at the start of this task).
- [ ] **Step 2:** Run `$PY -m test_run_env`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run all five self-checks. Expected: all ok.
- [ ] **Step 5:** Commit (`Env: training decks with upgrades and colorless cards; every copy of stackable powers observed`).

### Task 2: The retrain queue

**Files:**
- Create: `.superpowers/queue/boss.sh` in the main checkout (git-ignored, like `act2.sh`)
- Modify: none in git

**Interfaces:**
- Consumes: Task 1's commit, and `models/ppo_sts2_sim_boss_g2.zip` and `models/ppo_sts2_sim_boss_run_g2.zip`.
- Produces: models `ppo_sts2_sim_boss_a_final.zip` (combat A), `ppo_sts2_sim_boss_b_final.zip` (combat B) and `ppo_sts2_sim_boss_run_v1_final.zip` (run policy), with logs `boss_train_a.log`, `boss_train_b.log`, `boss_train_r.log`, `boss_eval.log`, `boss_report.log` and `boss_analysis_v1.jsonl` in the queue directory.

- [ ] **Step 1:** Create the frozen worktree `~/projects/sts2-rl-bot/auto-spire-retraint`, detached at Task 1's commit, with the same three symlinks.
- [ ] **Step 2:** Write `boss.sh`. Copy `act2.sh`'s `stage()` function: it waits for AC, runs under `caffeinate -i`, logs start and end with `rc`, and stops on failure. No `until` wait at the top. Stages, run from the frozen worktree's `agent/` (step counts are my call, sized to the deadline: Act 2's 30M-step stage A took 39 hours):
  - `boss_train_a`: `train.py --backend sim --encounters hive,act1 --random-decks --prompt-practice --resume models/ppo_sts2_sim_boss_g2.zip --n-envs 6 --net 256 256 --timesteps 20000000 --name ppo_sts2_sim_boss_a`
  - `boss_train_b`: `train.py --backend sim --run-mode --run-model models/ppo_sts2_sim_boss_run_g2.zip --resume models/ppo_sts2_sim_boss_a_final.zip --n-envs 6 --net 256 256 --timesteps 20000000 --name ppo_sts2_sim_boss_b`
  - `boss_train_r`: `train.py --backend sim --run-policy --event-practice --combat-model models/ppo_sts2_sim_boss_b_final.zip --resume models/ppo_sts2_sim_boss_run_g2.zip --n-envs 6 --net 256 256 --timesteps 6000000 --name ppo_sts2_sim_boss_run_v1`
  - `boss_eval`: `run.py --model models/ppo_sts2_sim_boss_b_final.zip --maps generated --run-model models/ppo_sts2_sim_boss_run_v1_final.zip --runs 500 --n 16`
  - `boss_report`: `boss_report.py --model models/ppo_sts2_sim_boss_b_final.zip --run-model models/ppo_sts2_sim_boss_run_v1_final.zip --runs 1500 --n 16 --out <queue>/boss_analysis_v1.jsonl`
  - It ends by writing `BOSS RETRAIN DONE` to `status.txt`.
- [ ] **Step 3: Dry run.** Run a copy of `boss.sh` with `--timesteps 20000`, `--runs 10` and a `_smoke` suffix on every name and log. Expected: every stage logs `rc=0`, each stage loads the previous stage's `_smoke_final.zip` (Review Focus 4), and no traceback. Delete the smoke models and logs afterwards.
- [ ] **Step 4:** Check that a failing stage stops the queue (Review Focus 3): run the dry-run copy with a bad `--resume` path on stage B. Expected: `STOPPED at boss_train_b_smoke` in `status.txt`, and the later stages don't run.
- [ ] **Step 5:** Nothing to commit (the queue directory is git-ignored). Record the script's path and the frozen commit in `docs/superpowers/specs/2026-11-09-act2-boss-design.md` under a new "Part 3 results" heading as "Run", and commit that line (`Docs: part 3 retrain queue`).

### Task 3: Run the retrain

**Files:** none (the queue runs in the background)

- [ ] **Step 1:** Check `pmset -g batt` shows AC power, and ask the user to keep the lid open. Start `nohup zsh ~/projects/sts2-rl-bot/auto-spire/.superpowers/queue/boss.sh &`.
- [ ] **Step 2:** Watch `status.txt` every few hours, not more often. On `STOPPED at <stage>`, read the stage's log tail. Fix the cause in the `retrain` worktree (not the frozen one), move the frozen worktree to the fix commit, and resume from the failed stage, as `act2_resume.sh` did. Note each stop in `status.txt`.
- [ ] **Step 3:** When `BOSS RETRAIN DONE` appears, confirm all five stages logged `rc=0`. Expected total: about 40 hours (A about 26, B about 4, R about 7, evals about 1).

### Task 4: Results and the gate

**Files:**
- Modify: `docs/superpowers/specs/2026-11-09-act2-boss-design.md` ("Part 3 results")

- [ ] **Step 1:** Write "Part 3 results" in the style of "Part 1 results":
  - The eval row (Act 1, Act 2, average floor, gold spent, potions used, relics, deaths by place) next to the g2 reference.
  - `stuck` and crashes.
  - Boss reachers and boss wins in the 500-run eval.
  - The 1,500-run per-boss table next to the reference, part 1 and part 2a. Run `$PY boss_report.py --summarize <queue>/boss_analysis_v1.jsonl` for the per-boss HP-by-turn table, and compare it with the stage 1 analysis.
- [ ] **Step 2: Gate.** State plainly whether success 1 is met (above 50% of boss fights, at least 300 fights, per boss), whether the guard holds (boss-reach share and Act 2 clear not below the reference), and whether Act 1 is within 4 points of 81.0%. If any is missed, say so in the results and stop: the boss-practice decision goes to the user (spec stage 4).
- [ ] **Step 3:** Export the numbers the poster needs as one CSV in the scratchpad, not in git:
  - Act 1 and Act 2 clear rates and boss win rates for the reference, part 1, part 2a and part 3.
  - Per-boss win rates.
  - Training reward per stage, read from the `train.py` logs.
- [ ] **Step 4:** Commit (`Docs: Act 2 boss part 3 results`). Report to the user, who decides about merging, real-game stages and poster content.
