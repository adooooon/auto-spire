# Events: design

Date: 2026-11-05. Sub-project 4 of 5 in "fill in the rest of the run". It follows relics (`2026-11-04-relics-design.md`).

## Why

The run policy should learn when an event's deal is worth taking. Until now a "?" room that rolled an event was an empty room.

- **Success (user):** the policy's choices clearly change with its situation, even if the clear rate stays about flat. `run.py` reports each event's option rate split by HP and gold, beside the 500-map clear rate.
- **Failure:** an event quietly differs from the game, or the odds get bent to flatter the agent.

## Scope (user's choice: the 5 that fit today)

21 events can appear in Act 1: Overgrowth's 13 and 8 of the shared ones. The rest of the shared list have an `IsAllowed` that's false in Act 1. All 21 stay in the pool with their real `IsAllowed`; 16 are empty rooms.

The five and their options are in `docs/game-architecture.md`, "Events": Byrdonis Nest, Jungle Maze, Slippery Bridge, Sunken Statue and The Legends Were True.

Not in scope: curses, transforms, upgrades, enchantments, colorless cards, event fights, live play (`mod/`), and retraining combat. 12 of the 21 were an option (curses, transforms and Room Full of Cheese added); the user chose 5.

## Known limits

- Byrdonis Nest, Sunken Statue and The Legends Were True each have an option whose payoff lies outside what's modeled, so that option looks worse than it is in a full run. Expect the policy to learn to avoid them. That is correct for Act 1 only.
- Option 1 isn't the risky one in every event: Jungle Maze's HP cost is option 0.
- In two 60-run samples, 22% and 31% of events met were modeled. The 500-map evals will give a firmer number.

## Calls made without the user

- Egg and Map are a Wound in the sim: same behavior in a fight, and no new card id, so combat models need no regrowing.
- Only the run policy retrains (v6e), from the best relic pair by clear rate. Combat sees no new input.
- Lethal options stay legal, as in the game. Dying in an event ends the run with no clear bonus.
- Reference: the grown model with no retraining (`e0`). Its zero logits always pick option 0, so it's a floor, not a neutral player.

## Training

Queued in `.superpowers/queue/events.sh` of the main checkout, after the relic queue: grow, 500-map reference, 4M steps of run policy, 500-map eval. Code is in the `events` worktree and uncommitted.

## Results (2026-11-05)

Same 500 generated maps, picker N = 16, combat v13. Without events, v13 + v3r cleared 80.0%.

| Run policy | Clear | Avg floor | Gold spent | Potions used | Relics | Elites | Relics bought | Died: boss / elite / monster |
|---|---|---|---|---|---|---|---|---|
| e0 (grown, always option 0) | 76.2% | 15.7 | 138 | 2.10 | 1.66 | 0.60 | 5 | 94 / 13 / 12 |
| v6e (+4M steps) | 79.4% | 15.8 | 136 | 2.08 | 1.75 | 0.56 | 52 | 87 / 5 / 11 |

The relics column leaves out Sword of Stone, which does nothing in Act 1. The 3.2-point gain is within noise (under 4 points). 28% of events met were modeled, about 0.5 per run.

**The success test was not met.** At each of the 270 modeled event decisions v6e reached (Slippery Bridge counts each hold as a decision), HP alone or gold alone was changed and its choice re-read (`.superpowers/queue/event_probe.py` in the main checkout; its log is beside it). HP ran from 15% to 100% of max, gold from 0 to 400.

| Event | Option 1 chosen | Choice flips with HP | Choice flips with gold |
|---|---|---|---|
| Byrdonis Nest | 0% of 62 | 0% of states | 2% |
| Jungle Maze | 100% of 53 | 0% | 0% |
| Slippery Bridge | 38% of 32 | 3% | 9% |
| Sunken Statue | 25% of 63 | 5% | 21% |
| The Legends Were True | 100% of 60 | 0% | 0% |

- v6e learned a fixed answer per event, with no sign of weighing HP. At 15% HP it still pays 8 HP for a potion, and at full HP with no gold it still refuses 18 HP for about 100 extra gold.
- The one situational effect is gold in Sunken Statue, in the sensible direction: the richer it is, the less it takes the gold (35% at 0 gold, 19% at 400, as a mean probability).
- Likely cause, not tested: very few events are met below half HP (7 of 270 decisions in the eval; average HP at an event is 92% of max), so training has little to learn from.

**Review (2026-11-05), not changed:** the event observation shows raw HP and gold, not values after Tungsten Rod or Bowler Hat, because the policy also sees those relics and they are rare. `Run.lose_hp` repeats the Tungsten Rod and Lizard Tail rules from `SimCombat`; sharing them would mean editing the combat code the models were trained on.

**Second round (v6p):** the same 4M steps from e0, with `--event-practice`. In training only, half of modeled events start from random HP (10 to max) and gold (0-400). The 500-map eval and the probe stay on real runs.

| Run policy | Clear | Avg floor | Gold spent | Potions used | Relics | Elites | Relics bought | Died: boss / elite / monster |
|---|---|---|---|---|---|---|---|---|
| v6p | 79.8% | 15.8 | 123 | 2.04 | 1.69 | 0.57 | 37 | 86 / 9 / 6 |

Share of decisions where the choice flips when only HP or only gold changes, v6e then v6p:

| Event | Option 1 chosen | Flips with HP | Flips with gold |
|---|---|---|---|
| Byrdonis Nest | 0% then 0% | 0% then 0% | 2% then 0% |
| Jungle Maze | 100% then 100% | 0% then 0% | 0% then 0% |
| Slippery Bridge | 38% then 45% | 3% then 12% | 9% then 18% |
| Sunken Statue | 25% then 8% | 5% then 3% | 21% then 0% |
| The Legends Were True | 100% then 98% | 0% then 0% | 0% then 0% |

**The success test is still not met.** Practice moved only Slippery Bridge, in a sensible direction: it holds on 35% of the time at 15% HP and 48% at full HP, and 55% at 0 gold and 38% at 400. Sunken Statue lost its gold effect, and four of the five events now have a near-fixed answer. At 15% HP it still pays 8 HP for a potion (96% probability). So rare low-HP states were at most a small part of the cause. Why the rest didn't move is untested. v6p is kept: its clear rate is level with v6e (0.4 points) and it is the only one that responds to HP at all.

Elite drops in the v6p eval read 22% rare and 15% unmodeled against 17% and 11.6% (n = 278), about 2 standard errors. Rare also reads 19-21% in the other event evals and 20% in v13 + v5, before events, but those evals share map seeds, so they aren't independent samples. The events diff doesn't touch `roll_relic_rarity` or the relic bags, so this is read as noise. No large-sample test was run.
