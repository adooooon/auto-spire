# Prompt cards: design

Date: 2026-11-05. Sub-project 5 of 5 in "fill in the rest of the run". It follows events (`2026-11-05-events-design.md`).

## Why

Headbutt, Brand and Burning Pact ask the player to choose another card. The sim doesn't model them, so they can appear in offers but can't be taken. The agent should be able to play them and choose well.

- **Success (user):** the agent's card choices visibly make sense, even if the clear rate stays flat.
- **Failure:** a card quietly differs from the game, or the test passes only because of states built for the test and not because of what the agent learned.

Events taught the lesson behind this design: the agent can learn one fixed answer and look fine on clear rate, and a rare situation gets little training. So practice is built into training, and the test checks that a choice changes when the hand changes.

## Scope

| Card | Rarity | Cost | Effect, in order |
|---|---|---|---|
| Headbutt | Common | 1 | 9 damage, then choose a card from the discard pile to put on top of the draw pile |
| Burning Pact | Uncommon | 1 | choose a card in hand to exhaust, then draw 2 |
| Brand | Rare | 0 | lose 1 HP (Unblockable, Unpowered), choose a card in hand to exhaust, then gain 1 Strength |

Rules from `CardSelectCmd` (`decompiled/MegaCrit.Sts2.Core.Commands/CardSelectCmd.cs`): the player must choose exactly 1 card, with no cancel. With no legal cards, nothing happens and the rest of the card still resolves. With exactly 1 legal card, it's chosen with no prompt. If combat is ending, there's no prompt, as when Headbutt kills the last enemy.

**Not in scope (user's choice): Armaments.** Its choice is which card to upgrade, and the sim has no upgrades. It stays unavailable in offers and shops, as it is today. Upgrades are their own later project.

Also not in scope: live play. `mod/` stays as it is, and `live_run` and `sim/validate.py` must keep treating all four cards as unmodeled, because the mod can't answer the prompt.

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
