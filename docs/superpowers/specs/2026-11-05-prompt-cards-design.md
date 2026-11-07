# Prompt cards: design

Date: 2026-11-05. Sub-project 5 of 5 in "fill in the rest of the run". It follows events (`2026-11-05-events-design.md`).

## Why

Headbutt, Brand and Burning Pact ask the player to choose another card. The sim doesn't model them, so they can appear in offers but can't be taken. The agent should be able to play them and choose well.

- **Success (user):** the agent's card choices visibly make sense, even if the clear rate stays flat.
- **Failure:** a card quietly differs from the game, or the test passes only because of states built for the test and not because of what the agent learned.

Events taught the lesson behind this design: the agent can learn one fixed answer and look fine on clear rate, and a rare situation gets little training. So practice is built into training, and the test checks that a choice changes when the hand changes.

## Scope

Headbutt, Burning Pact and Brand. The cards and the `CardSelectCmd` rules are in `docs/game-architecture.md`, "Card choices".

**Not in scope (user's choice): Armaments.** Its choice is which card to upgrade, and the sim has no upgrades. It stays unavailable in offers and shops, as it is today. Upgrades are their own later project.

Also not in scope: live play. `mod/` stays as it is, and `live_run` and `sim/validate.py` must keep treating all four cards as unmodeled, because the mod can't answer the prompt. (Superseded on 2026-11-06: the mod now answers every prompt, see "Results".)

## What must be built

- **Sim (`agent/sim/`):** the three cards, a pending-choice state in `SimCombat` while a card is mid-resolution, and a way to resolve it through `SimClient`. Exhaust hooks and top-of-draw must go through the existing paths. The three cards join `COMMONS`, `UNCOMMONS` and `RARES`, so they enter reward pools and random decks, and `GENERATED` where their source allows it. Check each against the decompiled source and add tests for each rule above.
- **Combat env (`agent/env.py`):** new actions to choose a hand slot (10) and a discard card by id, masked to what's legal, with every other action masked during a choice. New observations: a choice flag and which card is asking. The hand and discard counts are already observed.
- **Run policy:** the three cards can be picked and bought. `PROMPT_CARDS` keeps Armaments.
- **`agent/grow.py`:** needs a new ability. Card ids are `sorted(CARDS)` and appear inside hand slots, piles, deck, shop slots and run actions, so 3 new ids land in the middle of existing indices. `grow.py` only appends today. It must map every old input and action to its new index by name and leave new ones at zero. A model trained for 130M steps must not be thrown away, and a test must show a grown model acts the same as its parent on states with none of the new cards.
- **Report (`agent/run.py`):** per-card choice counts from real runs, beside the 500-map clear rate.

## Training

Run from a separate worktree so sim code stays frozen, as with events. Each stage uses 6 envs and a 256×256 network, on AC power, under `caffeinate -i`.

1. Grow combat v13 and run policy v6p.
2. **Reference:** the grown pair, 500 generated maps, N = 16. Zero logits choose the first legal card, so this is a floor and not a neutral player.
3. **Combat phase A:** 15M steps with random decks, with prompt practice (below).
4. **Combat phase B:** 20M steps on real runs with the grown run policy.
5. **Run policy:** 4M decisions with the new combat model, with `--event-practice`, since v6p was trained with it.
6. Evaluate on 500 maps, N = 16, then run the choice test. Expect about 12-15 hours in total.

**Prompt practice (phase A only, off in phases B and evaluation):** half of random decks get one of the three cards, chosen evenly, and half of those also get 1-2 Wounds. Without this, `random_deck` would include Brand in about 2% of fights and Burning Pact in about 3%.

## The choice test

Run on the final combat model: 200 fights per card, with a random deck plus that card and 2 Wounds, across Act 1 encounters, always taking the highest-probability action. Junk means a Status or Curse card; basic means Strike or Defend.

| Check | Pass |
|---|---|
| Burning Pact and Brand, at choices with junk and non-junk in hand | chooses junk over 50% of the time and at least 2× the random rate |
| The same two cards, swap test: at choices with no junk, replace one card it didn't choose with a Wound and read the choice again | moves to the Wound over 50% of the time |
| Headbutt, at choices with a non-basic, non-junk card and a basic or junk card in discard | chooses non-basic, non-junk at least 1.5× the random rate |
| Headbutt, HP test: at choices with an attack and a block card in discard, read the choice at 15% HP and at 100% HP | picks the block card at least 10 points more often at 15% HP |

Success means all four rows pass. Report the same counts from real runs too, for honesty, even though they'll be small. The clear rate should stay within noise of the reference; a drop of 4 points or more is a failure to investigate.

## Known limits

- Exhausting junk isn't always best. A card that's useless this fight can be a better exhaust than a Wound that will rarely be drawn again. The bars sit at 50% and not higher for this reason.
- The test decks are built for the test. They show the agent can tell cards apart, and the real-run counts are the check that it does so in play.

## Calls made without the user

- Choice test design and its bars.
- Prompt practice.
- Retraining both combat and run policy, with the same step counts as relics.
- Autoplayed prompt cards (Havoc and similar) may resolve their choice at random, with a `ponytail:` comment, if a pending choice can't be held through those paths. The builder should check the source and report it either way.
- The three cards join `GENERATED` only if the source's filter allows them.

## Results (2026-11-06)

**The choice test was not met: 1 of 4 rows passed.** The clear rate held. The agent is better than the floor on three rows, but its Headbutt choice doesn't respond to HP at all.

### Clear rate

Same 500 generated maps, picker N = 16.

| Pair | Clear | Avg floor | Gold spent | Potions used | Relics | Elites | Relics bought | Died: boss / elite / monster |
|---|---|---|---|---|---|---|---|---|
| Reference: grown v13c + v6pc | 80.4% | 15.8 | 126 | 1.99 | 1.68 | 0.54 | 46 | 81 / 7 / 10 |
| v14 + v7 | 81.4% | 15.8 | 126 | 1.89 | 1.73 | 0.57 | 54 | 77 / 8 / 8 |

The 1.0-point gain is within noise, and well inside the 4-point limit.

### Choice test

The first run had n = 22 on row 2, so the rerun used 1,000 fights each for Burning Pact and Brand and 400 for Headbutt. These are the rerun's numbers. The floor is grown v13c, before any training.

| Row | Floor | v14 | Bar | Result |
|---|---|---|---|---|
| 1. Junk over non-junk (n = 290 or more per card) | Pact 33% vs random 38%, Brand 39% vs 37% | Pact 61% vs 46%, Brand 66% vs 42% | over 50% and at least 2× random | FAIL |
| 2. Swap: moves to a new Wound (n = 106 or more per card) | 0% | Pact 41%, Brand 47% | over 50% | FAIL |
| 3. Headbutt: non-basic, non-junk (n = 51) | 0% vs 41% | 80% vs 37% | at least 1.5× random | PASS |
| 4. Headbutt: block card at low HP (n = 314) | 28% at 15% HP, 28% at full | 26% at 15% HP, 26% at full | at least 10 points higher at 15% HP | FAIL |

- **Row 1** clears 50% but reaches only 1.3× and 1.6× random. These test hands hold enough junk that 2× random means 92% and 84%, higher than the "Known limits" section expects. That's a flaw in the bar, but the row fails as written, and row 2 fails with no such bar.
- **Row 2** is the sharper miss. The agent often keeps its choice when a Wound appears, so it isn't reliably reading junk as junk.
- **Row 3 changed from the spec's text.** It scores only prompts whose first legal card id is basic or junk. As written, a floor model passed at 80% vs 46%, because card ids are alphabetical and the first legal card is usually a good one. The 1.5× bar is unchanged. Across all 313 mixed prompts, v14 reads 85% vs 46%, for information only.
- **Row 4** shows no effect from HP. Why isn't tested.

### Real runs

From the 500-map evals, the prompts each card opened:

| Card | Reference prompts | Reference rate | v14 + v7 prompts | v14 + v7 rate |
|---|---|---|---|---|
| Headbutt | 370 | non-basic, non-junk 74% of 334 | 459 | 95% of 401 |
| Burning Pact | 199 | junk 64% of 14 | 6 | no prompt had both |
| Brand | 17 | junk 0% of 1 | 20 | junk 50% of 2 |

Headbutt is a clear gain in real play. Burning Pact and Brand have too few real choices to judge, so the junk behavior isn't confirmed in real runs. Burning Pact fell from 199 prompts to 6, so the new pair rarely plays it. Why isn't tested.

### What's kept

`ppo_sts2_sim_act1_pc_v14_final` and `ppo_sts2_sim_run_policy_v7_final`, since the clear rate held and Headbutt improved. Act 2 grows from this pair.

### Calls made during the build

| Call | Cost if wrong |
|---|---|
| Worked directly on `rl-agent-sim`, not a new worktree; training ran from a detached one | Commits can move to a branch |
| Started training with no further stop, since the plan was approved | The queue could be stopped with no lost work |
| `test_engine`'s env test used a test-only answering client until Task 3 | That one test skipped env choice actions until then |
| Autoplayed prompt cards pick at random | A small gap when Havoc or similar plays one of the three |
| Row 3 scored on a subset, as above | The subset is small: n = 51 at 400 fights |
| The queue passed `--headbutt-fights 400`, since the default gave n = 29 | Seconds |
| `random_agent.py` stays unmasked: a toy script, not used in training | A possible invalid live command if someone runs it |
| The queue spelled paths `${C}_v13c`, since zsh reads `$C_v13c` as a variable | None |
