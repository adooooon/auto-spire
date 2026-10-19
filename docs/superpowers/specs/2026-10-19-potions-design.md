# Potions (design)

Date: 2026-10-19. Sub-project 2 of 5 in "fill in the rest of the run". It follows the run foundation (`2026-10-18-run-foundation-design.md`).

## Goal

Model potions in the sim: slots, fight drops, shop stock, use in combat and Blood Potion between fights. Retrain combat and the run policy to use them.

**Success:** on the same 500 seeded generated maps, combat v11 with run policy v3 clears Act 1 more often than v10 with run policy v2 without potions (**51.8%**).

**Scope:**
- **Sim only.** Live play masks potion actions off and leaves the potion features at zero.
- **12 potions:** the 11 direct-effect shared Commons plus Blood Potion (Ironclad's Common).
- **Unmodeled potions** still drop and still appear in shops, but can't be taken or bought, the same way prompt cards are handled. That keeps drop rates faithful. They are:
  - the 4 card-choice Commons (Attack, Skill, Power, Colorless Potion), which wait for sub-project 5's choice prompt
  - every Uncommon and Rare
- **Assumptions carried over:** Act 1, ascension 0, events and relics still empty.

## Game rules modeled

From the decompiled source. The exact values also go in `docs/game-architecture.md`.

| Potion (class) | Effect | Target | Use |
|---|---|---|---|
| `BlockPotion` | 12 block | self | combat |
| `DexterityPotion` | +2 Dexterity | self | combat |
| `SpeedPotion` | +5 Dexterity this turn | self | combat |
| `EnergyPotion` | +2 energy | self | combat |
| `StrengthPotion` | +2 Strength | self | combat |
| `FlexPotion` | +5 Strength this turn | self | combat |
| `SwiftPotion` | draw 3 | self | combat |
| `FirePotion` | 20 damage | one enemy | combat |
| `ExplosiveAmpoule` | 10 damage | all enemies | combat |
| `VulnerablePotion` | 3 Vulnerable | one enemy | combat |
| `WeakPotion` | 3 Weak | one enemy | combat |
| `BloodPotion` | heal 20% of max HP | self | any time |

- **Damage:** potion damage is `ValueProp.Unpowered`. How that interacts with Strength, Vulnerable and block is read from the damage pipeline during implementation and pinned by tests.
- **Dexterity** is new to the sim. It adds to each block card's block, Frail then reduces the result, and the temporary part ends with the turn.
- **Slots:** 3 to start (`Player.initialMaxPotionSlotCount`), empty.
- **Drops** (`PotionRewardOdds`):
  - The chance starts at 0.4. After a roll it falls 0.1 if a potion dropped, or rises 0.1 if not.
  - Elites add 0.25 × 0.5.
  - No roll after the boss.
- **Rarity** (`PotionFactory`): Rare ≤ 0.10, Uncommon ≤ 0.35, otherwise Common. The potion is then uniform within that rarity, over the shared pool plus Ironclad's.
- **Shop** (`MerchantInventory.PopulatePotionEntries`): 3 random potions, priced 50 / 75 / 100 by rarity × U(0.95, 1.05), rounded. A potion can only be bought into a free slot.

## Architecture

The two policies from sub-project 1 stay. Both observation and action spaces grow by appending, so the new features and actions come after the existing ones.

### `agent/sim/potions.py` and `engine.py`

- `POTIONS`: the 12 modeled potions with their effect, target kind and usage.
- `POTION_POOL`: every potion id by rarity, modeled or not, for drops and shops.
- `SimCombat`:
  - holds `potions` (3 slots, `None` = empty) and a `use_potion(slot, target)` that applies the effect and empties the slot
  - gains Dexterity, both permanent and this-turn, applied to block cards
- `SimClient`: `set_potions(list)`, used at fight start the same way `set_deck` is, plus an exec path for using a potion.

### `agent/env.py`: combat env

- **Observation:** 38 features appended:
  - each slot as a one-hot over the 12 potions (36)
  - Dexterity and this-turn Dexterity (2)
- **Actions:** appended after END_TURN, "use slot i on enemy position j". Self-targeted potions use position 0.
- **Mask:**
  - the slot holds a modeled potion, it's the player's turn, and an enemy target is alive
  - Blood Potion is allowed in combat too
  - live backend: always off
- **Potions:** a `potions` attribute, set the same way `deck` is. With `random_decks`, each fight starts with 0–3 random modeled potions.
- **Cost of use:** each use costs `POTION_COST` reward, so a fight-level policy doesn't spend every potion every fight. It starts at the value of about 5 HP under run mode's HP weighting, is marked as a tuning knob, and is tuned by the evaluation's potion-behavior numbers.

### `agent/grow.py`: growing a trained network

`grow.py <old.zip> <new.zip> --env combat|run` builds the larger MaskablePPO.
- Every existing weight is copied.
- First-layer weights from the new inputs start at zero in both the policy and value networks.
- The action head gets zero rows for the new actions.
- **Self-check:** on random potion-free observations, the grown model's action probabilities (over the old actions) and its value match the parent's.

### `agent/sim/act.py` and `agent/run_env.py`: run side

- **`Run`** gains `potions` (3 slots) and `potion_odds`.
  - `win(room)` also rolls the potion drop.
  - `make_shop` stocks 3 potions with prices.
- **Run env actions:** 10 appended, so 103 becomes 113.
  - **Potion decision** (4): after a won fight, if a modeled potion dropped. "Put it in slot i" discards whatever is there; or "skip". It comes after the card pick. An unmodeled drop is skipped without a decision.
  - **Shop** (3): "buy potion k", allowed when it's affordable, a modeled potion and a slot is free.
  - **Drink** (3): "drink slot i" at a path decision, for a Blood Potion when HP is below max.
- **Run env observation:** appended:
  - own slots (3 × 12)
  - the offered potion (12)
  - the shop's potion slots (3 × (12 + price / 100 + affordable))
- **Fights:** `play()` and `MapRunModeEnv` copy the run's potions into the fight and the leftover potions back out.
- **Baseline** (`run.py`): it takes a dropped potion into a free slot and otherwise skips. It never buys potions and never drinks Blood between fights. Combat uses the combat model, potions included.

## Training

1. **Grow:** v10 into `ppo_sts2_sim_act1_map_v10p`, and run policy v2 into `ppo_sts2_sim_run_policy_v2p`.
2. **Combat phase A:** about 10M steps on the Act 1 pool with random decks and random potions.
3. **Combat phase B:** 15M steps in run mode on generated maps, with v2p making the choices between fights. The result is **v11**.
4. **Run policy v3:** resume v2p with combat v11 for 3M steps. Further rounds only while they still help.

## Evaluation

- **Main comparison:** the 500 generated maps, baseline and policy, with v11 + v3 against v10 + v2 (51.8%).
- **Potion behavior:** potions used per fight, potions held at death, and use counts per potion. This tunes `POTION_COST`. Many deaths while holding potions mean the cost is too high.
- **Bosses:** v11's boss win rates with no potions against 2 random modeled potions.

## Error handling

- `grow.py` refuses to save if its self-check fails.
- **Unchanged from sub-project 1:**
  - `SimLoopError` ends a fight as aborted.
  - Exceptions during a fight in `run_env` end the run as a loss.
- Using a potion from an empty slot, or one the mask forbids, is an assertion error. The mask is the only gate.

## Testing

All tests are assert scripts, as before.
- **`sim/test_engine.py`:**
  - each potion's effect
  - Dexterity with and without Frail, and its this-turn part ending
  - potion damage against block and Vulnerable
- **`sim/test_act.py`:**
  - drop chance rising and falling
  - the elite bonus
  - the rarity split over many rolls
  - shop potion prices
  - no roll after the boss
- **`test_run_env.py`:**
  - buying a potion is masked with full slots
  - an unmodeled drop is skipped automatically
  - Blood Potion can only be drunk below max HP
  - potions carry into and out of fights
  - the combat mask: filled slot and live target only, never on the live backend
- **`grow.py` self-check:** run on both grown models.

## Out of scope

- live potion use and validation
- card-choice potions (sub-project 5)
- Uncommon and Rare potions
- relics that change potion slots or drops (sub-project 3)
- Fairy in a Bottle–style automatic potions
