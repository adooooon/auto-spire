# Run foundation: generated maps, shops, and a run policy (design)

Date: 2026-10-18. Sub-project 1 of 5 in "fill in the rest of the run".

## Goal

Make simulated Act 1 runs realistic enough that the agent trains and is scored on proper runs, with a learned **run policy** making every out-of-combat choice. Live runs are unchanged: they keep spawning fights through the console.

**Success:** on 500 seeded generated maps, the run policy (with v9 combat) clears Act 1 more often than the baseline (v9 combat, random path, MC card picker, remove a Strike when affordable) using the same combat policy.

## The five sub-projects

Each one gets its own spec → plan → implementation.

1. **Run foundation** (this spec): generated maps, room types, gold, shop cards and card removal, the run policy env.
2. **Potions:** slots, drops, shop stock, and "use potion" combat actions. The combat policy is retrained. The 15 Common shared potions come first.
3. **Relics:** engine hooks, relic rewards (elite, treasure), and shop relics. Combat is retrained. The 26 Common relics come first.
4. **Events:** the 13 Overgrowth events plus Neow, with options chosen by the run policy.
5. **Prompt cards:** Armaments, Headbutt, Brand and Burning Pact. This adds a card-choice sub-action in the sim and in the mod.

Assumptions throughout:
- Act 1 (Overgrowth) only, ending at the boss.
- Ascension 0.
- Rest sites stay heal-only (no smithing).
- The fixed-route score and the MC picker stay as baselines.

## Architecture

Approach A has two policies, with combat nested in the run.

- **Combat policy:** the existing MaskablePPO on `STS2CombatEnv`. It's unchanged in this sub-project apart from a step cap.
- **Run policy:** a new MaskablePPO on `agent/run_env.py`. One episode is one run, and one step is one decision. A step that enters a fight plays the whole fight with a frozen combat policy.

## Components

### `agent/sim/map.py`: Act 1 map generation

A Python port of `StandardActMap` for Overgrowth:
- **Shape:** 15 room floors (`BaseNumberOfRooms`), plus Neow's floor first and the boss floor last.
- **Grid:** 7 columns with crossing paths.
- **Room counts** follow `MapPointTypeCounts` and Overgrowth's `GetMapPointTypes`: 5 elites, 3 shops, 10–14 Unknown rooms (Gaussian 12, σ1), and 6–7 rest sites (Gaussian 7, σ1, clamped to 6–7).
- **Placement** follows the game's rules (`StandardActMap.IsValidPointType`), including the fixed floors: the first room floor is a monster, there's a treasure floor partway up, and the floor before the boss is a rest.
- **RNG:** Python's `random`, seeded per run. Maps follow the game's distribution, not exact game seeds.
- **Output:** a list of nodes `(floor, col, type)` and edges to the next floor.
- **Skipped:** `MapPostProcessing` only re-centers and spreads columns and never changes edges. `MapPathPruning` removes duplicate parallel segments (same endpoints, same room types) and needs every path through the map enumerated, which is about a second per map in Python. It's marked `ponytail:` in the code, to port if map statistics drift from the game's.

### `agent/sim/act.py`: run state and rooms

**Run state:**
- HP and max HP, gold, the deck
- the map and the current node
- `RarityOdds` (reused from `picker.py`)
- `UnknownMapPointOdds` state
- the encounter queue
- shop removals used

**Encounter queue:** ported from `ActModel`. The first monster rooms draw weak encounters, then normal encounters without repeats; elites come from their own bag. The boss is drawn at run start.

**Rooms:**

| Room | Effect |
|---|---|
| Monster, Elite, Boss | A sim fight by the combat policy, with HP and the deck carried over. Burning Blood +6 on a win. Gold from `GoldReward`: each encounter's own `MinGoldReward`–`MaxGoldReward`, then a card offer from `offer()`. |
| RestSite | Heal 30% of max HP (`HealRestSiteOption`). |
| Shop | 5 Ironclad cards from `MerchantInventory` (Attack, Attack, Skill, Skill, Power; shop rarity odds Rare 9% + offset, Uncommon 37%): price 50/75/150 by rarity × U(0.95, 1.05), one card at half price. Card removal is 75 + 25 × removals used (`MerchantCardRemovalEntry`). No colorless cards, potions or relics yet. |
| Unknown | Resolved with `UnknownMapPointOdds`: base 10% monster, 2% treasure, 3% shop, otherwise an event. The chances shift as the game's do. |
| Event, Treasure, Ancient (Neow) | Empty placeholders until sub-projects 3 and 4. |

**Known gap until sub-project 4:** while events are empty, Unknown rooms are mostly free. The run policy will over-value them. Retraining after events land corrects this.

The exact numbers (per-encounter gold ranges, shop slot counts and rarities, sale discount, rest count, Unknown odds increments) are read from the decompiled source during implementation and noted in `docs/game-architecture.md`.

### `agent/run_env.py`: run policy env

**Actions:** one flat `Discrete` space of 101 actions, masked to the current decision.

| Decision | Actions | When |
|---|---|---|
| Path | 7, one per map column (only the connected next nodes are allowed) | after every room |
| Card pick | 3 offered + skip | after a won fight |
| Shop | buy slot 0–4, remove a card, leave | on entering a shop, repeated until leave |
| Remove | one per `CARD_IDS` entry (allowed if it's in the deck), plus cancel | after "remove a card" |

Rest sites and Unknown rooms resolve without a decision.

**Observation:**
- decision type (one-hot)
- HP / max HP, gold / 100, floor / 17, removals used
- deck counts per card id (84)
- the boss (one-hot, 3)
- offered cards or shop slots as card-id one-hots, with price and affordability for shop slots
- the next 5 floors × 7 columns of the map, each cell holding its room type (one-hot) and whether it's reachable from the current node

**Reward:** +0.1 per floor completed and +1 for beating the boss. Death ends the episode.

**Combat inside:** one `STS2CombatEnv(SimClient)` per env, with the combat model loaded once per subprocess.

## Training

1. **Run policy v1:** `train.py --run-policy --combat-model <v9 zip>` with 6 envs, combat frozen.
2. **Combat retrain:** `RunModeEnv` switches from `ACT1_PATH` to generated maps, with decisions made by the run policy instead of random picks. Resume from v9 to get v10.
3. **Run policy v2** on v10, if step 2 moved the numbers. Further rounds happen only while each one still helps.

## Evaluation

`run.py` gets a generated-map mode: the same 500 seeded maps per strategy.
- **baseline:** random path, MC card picker, remove a Strike when affordable, then leave the shop.
- **policy:** the run policy makes every choice.

It reports clear rate, floors reached, where runs died, and gold spent. The old fixed-route evaluation stays for continuity.

## Error handling

- **Step cap:** `STS2CombatEnv` gets one, so a sim infinite loop ends the episode as a loss (logged) instead of hanging training. The Pillage hang cost a night.
- **Sim exceptions:** in `run_env.py`, an exception during a fight ends that run as a loss and is logged. It doesn't crash the vector env.

## Testing

- `agent/sim/test_act.py`, assert-based in the style of `test_engine.py`:
  - map invariants: every node is reachable from the start and reaches the boss; room counts; the fixed floors
  - Unknown-room frequencies over many draws
  - weak encounters before normal ones
  - shop price ranges and the rising removal cost
- A smoke test for `run_env.py`: 200 runs with random masked actions, with no exceptions, no empty masks and no runs that never end.

## Out of scope

- potions, relics, events and Neow (later sub-projects)
- smithing at rest sites
- live map navigation
- colorless shop cards
- Acts 2–3
- ascension
