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

## Not in scope

- Act 3, Ascension, other characters.
- Making any boss or fight easier, or skipping hard content (anti-goal).

## Left to the builder

- Branch and worktree layout. Follow the `act2` pattern: a working worktree and a frozen copy for training.
- How the analysis is computed, observation encoding, network size, step counts and training stages.
- The debug commands for staging live fights. Check the dev console (`MegaCrit.Sts2.Core.DevConsole`) for setting the deck, upgrading cards and starting a chosen encounter.
- Where each new rule is documented. Follow `CLAUDE.md`'s doc scopes, with results in this spec.
