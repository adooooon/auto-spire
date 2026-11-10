# Act 2 boss: design

Date: 2026-11-09. Requested by the user: "beat it in most of the fights in the sim, and then be able to do it most of the time in the real game", and "put in any of the missing cards/artifacts", with card upgrades, the Neow and Act 2 Ancient relics, and the colorless cards that single-player allows included.

## Why

After Act 2 training (`docs/superpowers/specs/2026-11-06-act2-design.md`, "Results"), the agent clears Act 2 in 2.2% of runs. It wins 11 of the 117 Act 2 boss fights it reaches (9%), and the boss accounts for 106 of 384 Act 2 deaths. The sim still lacks parts of the game that matter more in Act 2: card upgrades, most potions, 25 relics, the Neow and Ancient relic offers, and colorless cards.

## Success

1. **Sim:** the agent wins more than 50% of the Act 2 boss fights it reaches in whole runs on generated maps. Measure over at least 300 boss fights (evaluate on more maps than the usual 500 if needed), and report each boss separately.
   - **Guard (my call):** the share of runs that reach the Act 2 boss (117 of 500 now) and the Act 2 clear rate (2.2%) must not fall. Otherwise a bot that dies earlier, so only strong runs arrive, would pass without getting better at bosses.
2. **Real game, staged:** more than 50% of staged real boss fights won (see stage 5).
3. **Real game, full runs:** a few full real runs as a final check.

## Anti-goals (user's)

A higher number counts as failure if it comes from the sim being easier than the game: a boss that's weaker than the real one, a missing rule that helps the player, or removing hard content. Gains must come from the sim matching the game more closely and the agent playing better.

## Constraints

- Act 1 must not get worse beyond noise: Act 1 clear no more than 4 points below the grown reference measured before retraining (my call, the same limit as earlier projects).
- Every new mechanic is checked against the live game, as the Hive monsters were (`sim.validate`, `live_check.py`-style staged checks). Write rules from the decompiled source (`decompiled/`), not from memory of Slay the Spire 1.
- Training needs AC power, the lid open, and `caffeinate -i`. It runs from a frozen worktree as a queue under `.superpowers/queue/` with `status.txt`, like `act2.sh`.
- Git: push only to the `mine` remote, never `origin`. Leave `mod/AutoSpire/obj/*` uncommitted. Don't change sim code in a checkout while a queue runs from it.

## Order (agreed with the user)

### 1. Boss analysis (read-only)

Find out why boss fights are lost before changing anything, so the result can be checked against it afterwards. Use the current models (`ppo_sts2_sim_act2_b_final` + `ppo_sts2_sim_act2_run_v1_final`). Report per boss (Kaiser Crab, Knowledge Demon, The Insatiable): fights reached and won, HP and max HP on arrival, deck size and makeup, relics, potions held and used, the turn of death, and damage taken per turn. Results go in this spec under "Analysis". No code changes beyond a throwaway or reusable analysis script.

### 2. Card upgrades

- **Upgraded versions** of every card the sim models (89), from each card's upgrade in the decompiled source. Check against the live game.
- **Rest sites** offer Heal or Smith (`SmithRestSiteOption`), and the run policy learns the choice and which card to upgrade. Rest-site relics that change these options come in here.
- **Upgraded cards wherever the game makes them:** card rewards (the upgrade roll grows with the act index, see "Card reward picks" in `docs/modding-approach.md`), shops, events, relics and card effects that upgrade.
- **Armaments** joins the Common pool, offers and shops.
- **Upgrade relics:** Whetstone, War Paint, Frozen Egg, Molten Egg, Toxic Egg, Girya, Shovel and others that need upgrades.
- **Inputs:** the combat and run observations tell an upgraded card from a plain one. Models grow into the new inputs and actions (`grow.py`), keeping their Act 1 results.
- **Live:** the mod reports whether each card is upgraded and can answer the Smith choice. `live.py` uses the run policy at rest sites instead of always healing.

### 3. Missing potions, relics and colorless cards

- **All 36 missing potions** (every Uncommon and Rare, plus Attack, Skill, Power and Colorless Potion).
- **The remaining relics** (25 of 122 before stage 2, minus those added there).
- **Colorless cards (user's call: all but multiplayer-only):** the 53 cards of `ColorlessCardPool` (64) without `CardMultiplayerConstraint.MultiplayerOnly`. The 11 left out: Beacon of Hope, Believe In You, Coordinate, Gang Up, Huddle Up, Intercept, Knockdown, Lift, Mimic, Rally, Tag Team. Each with its upgrade. They appear in shops and wherever relics, potions or cards produce them (Dingy Rug, Toolbox, Colorless Potion, Discovery and similar), filtered for one player as the game does (`FilterForPlayerCount`).
- **Neow and Ancient relics (user's call):** the sim gets Neow at the start of Act 1 and the Act 2 Ancient's relic offer, with their real options, and the run policy learns the choice. `live.py` drops its fixed Neow rule for the policy. Check in the source which Ancients can appear in Act 2 (the live check met Pael).

Stage 3 is now about as big as stage 2. If one item would take far more work than the rest (for example a potion that rewrites core rules), the builder may leave it out with a `ponytail:` comment and say why in the Results. That's a fallback, not a plan.

### 4. Retrain and evaluate in the sim

Grow the current models, measure a grown reference, then retrain combat and run policy as in the Act 2 queue (stages A, B and R, step counts left to the builder). Evaluate as in success 1. Compare per-boss results with stage 1's analysis.

If the bot still loses to one boss after this, the next step is boss-specific practice: training fights against that boss from realistic arrival states. That's a follow-up decision for the user, not part of this run.

**Gate (my call):** if the sim misses success 1 or its guard, stop and report before any real-game fights, and bring the boss-practice decision to the user. The live tooling for stage 5 (mod Smith support, upgraded-card reporting, staging commands) is built while training runs, so the gate costs no time.

### 5. Real game

- **Staged boss fights first.** Debug commands set up the real game in states taken from sim runs that reached the Act 2 boss (deck with upgrades, relics including Neow and Ancient ones, potions, HP), then start that boss. The bot plays the fight for real. My call: 30 fights, 10 per boss. Success is more than 50% won overall, reported per boss.
- **Then a few full real runs.** My call: 5 runs with the final models. These are too few to measure a rate, so report them without a bar. Each must play through without `[ERROR]` lines in `godot.log` from the mod.

## Analysis (2026-11-09)

Data: `ppo_sts2_sim_act2_b_final` (combat) and `ppo_sts2_sim_act2_run_v1_final` (run), 1,500 runs on generated maps at commit 969cae9, 331 Act 2 boss fights in `~/projects/sts2-rl-bot/auto-spire/.superpowers/queue/boss_analysis.jsonl`. Summary: `python boss_report.py --summarize <that file>` from `agent/`.

| Boss | Reached | Won | Arrival HP / max | Deck | Relics | Potions held / used | Turn of death (median, range) |
|---|---|---|---|---|---|---|---|
| Kaiser Crab | 104 | 0 (0%) | 63.9 / 82.8 | 24.3 | 4.6 | 0.62 / 0.61 | 5 (2-11) |
| Knowledge Demon | 103 | 10 (10%) | 64.8 / 82.3 | 24.9 | 4.4 | 0.91 / 0.86 | 6 (3-8) |
| The Insatiable | 124 | 11 (9%) | 64.0 / 83.2 | 25.0 | 4.7 | 0.78 / 0.67 | 6 (3-10) |

Mean HP lost on each turn, over fights that lasted past that turn (turns 1 to 6):

| Boss | T1 | T2 | T3 | T4 | T5 | T6 |
|---|---|---|---|---|---|---|
| Kaiser Crab | 7.8 | 19.7 | 6.5 | 26.0 | 7.9 | 11.3 |
| Knowledge Demon | 0.2 | 16.8 | 22.6 | 9.9 | 3.0 | 20.7 |
| The Insatiable | 0.5 | 10.5 | 20.9 | 0.5 | 14.3 | 9.1 |

Ten most common cards in the decks, with copy counts over all fights at that boss:

- Kaiser Crab: Strike 513, Defend 403, Anger 162, Bash 102, Twin Strike 80, Pommel Strike 70, Perfected Strike 69, Iron Wave 65, Shrug It Off 56, Unrelenting 54.
- Knowledge Demon: Strike 511, Defend 402, Anger 161, Bash 103, Twin Strike 84, Iron Wave 68, Pommel Strike 64, Fight Me 62, Taunt 58, Inflame 57.
- The Insatiable: Strike 613, Defend 486, Anger 183, Bash 124, Iron Wave 101, Twin Strike 96, Pommel Strike 74, Inflame 71, Unrelenting 69, Rage 68.

Findings:

1. The bot wins 21 of 331 boss fights (6%). Kaiser Crab is never beaten (0 of 104).
2. Damage comes in spikes. Kaiser Crab costs 19.7 HP on turn 2 and 26.0 on turn 4, against 6.5 on turn 3. The Insatiable costs 20.9 on turn 3 and 0.5 on turn 4. Knowledge Demon costs 22.6 on turn 3 and 20.7 on turn 6. Median death is turn 5 or 6.
3. Fights that start with more HP are won more often. Fights that start at 75 HP or more are won 16 of 129 times (12%). Fights that start below 75 are won 5 of 202 times (2.5%). Mean arrival HP is 77.9 in wins and 63.3 in losses, while max HP is about 82 in both.
4. Decks do not separate wins from losses. Wins average 24.3 cards and 8.8 Strikes and Defends. Losses average 24.8 cards and 8.9. Strike and Defend are the two most common cards at every boss.
5. Potions are rarely left unused. The bot holds 0.6 to 0.9 potions on arrival. A potion was unused at death in 18 of 310 losses (1 Kaiser Crab, 4 Knowledge Demon, 13 The Insatiable).

Player HP at the start of the last turn of a loss: median 13, 221 of 310 at 20 or less, 19 at 40 or more.

## Part 1 results (2026-11-10)

Grow commands, run from `agent/`, both exit 0:

- `grow.py models/ppo_sts2_sim_act2_b_final.zip models/ppo_sts2_sim_boss_g1.zip --env combat --insert-cards` gave "grow self-check ok: 1952->1979 inputs, 190->191 actions".
- `grow.py models/ppo_sts2_sim_act2_run_v1_final.zip models/ppo_sts2_sim_boss_run_g1.zip --env run --insert-cards` gave "grow self-check ok: 1452->1603 inputs, 127->221 actions".

Same 500 generated maps, picker N = 16 (`run.py --model models/ppo_sts2_sim_boss_g1.zip --maps generated --run-model models/ppo_sts2_sim_boss_run_g1.zip --runs 500 --n 16`, exit 0):

| Pair | Act 1 | Act 2 | Avg floor | Gold spent | Potions used | Relics | Died: A1 boss / A2 monster / A2 elite / A2 boss |
|---|---|---|---|---|---|---|---|
| Reference: act2_b + act2_run_v1 | 79.0% | 2.2% | 10.9 | 289 | 3.79 | 2.91 | 93 / 205 / 73 / 106 |
| boss_g1 + boss_run_g1 | 79.4% | 1.6% | 10.8 | 294 | 3.76 | 2.89 | 91 / 194 / 82 / 113 |

- Act 1 is 0.4 points above the reference, well within 4 points. `stuck=0`, and no fight crashed (no traceback in the log).
- Of the runs that reached the Act 2 boss, 8 of 121 won (7%), against 11 of 117 (9%) for the reference. The denominator here is boss reachers in the 500-run eval.

Boss analysis (`boss_report.py` on the same pair, 1,500 runs, 337 boss fights in `~/projects/sts2-rl-bot/auto-spire/.superpowers/queue/boss_analysis_g1.jsonl`, exit 0), against the analysis above:

| Boss | Reference won | g1 won |
|---|---|---|
| Kaiser Crab | 0 / 104 (0%) | 3 / 116 (3%) |
| Knowledge Demon | 10 / 103 (10%) | 7 / 117 (6%) |
| The Insatiable | 11 / 124 (9%) | 15 / 104 (14%) |
| All | 21 / 331 (6%) | 25 / 337 (7%) |

The rest logits of the grown run model start at zero, and generated-map eval predicts with `deterministic=True` (`run.py:211`), so it picks HEAL at every rest site, the same as the old auto-heal.

The 500-run eval and the 1,500-run report use different denominators: 8 of 121 boss reachers in the eval, and 25 of 337 boss fights in the report. The Act 2 clear change (2.2% to 1.6%, 11 vs 8 of 500) and the per-boss changes are within sampling noise at these sizes. g1 is untrained on upgrades. These numbers were measured before the two fixes after them (Act 2 offers deduped by base card, Headbutt keeping its deck copy), which touch only Act 2 offers and Headbutt-then-Hopper fights.

This pair, boss_g1 + boss_run_g1, is part 3's starting point.

The first eval crashed on `run.deck.remove` after a Thieving Hopper fight: `_steal` recorded the base id of the deck's last upgraded copy (UPPERCUT for UPPERCUT+), and commit 879f235 fixed it by having each combat copy of a deck card carry its deck card.

## Not in scope

- Act 3, Ascension, other characters.
- Making any boss or fight easier, or skipping hard content (anti-goal).

## Left to the builder

- Branch and worktree layout. Follow the `act2` pattern: a working worktree and a frozen copy for training.
- How the analysis is computed, observation encoding, network size, step counts and training stages.
- The debug commands for staging live fights. Check the dev console (`MegaCrit.Sts2.Core.DevConsole`) for setting the deck, upgrading cards and starting a chosen encounter.
- Where each new rule is documented. Follow `CLAUDE.md`'s doc scopes, with results in this spec.
