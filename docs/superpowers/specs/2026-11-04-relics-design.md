# Relics (design)

Date: 2026-11-04. Sub-project 3 of 5 in "fill in the rest of the run". It follows potions (`2026-10-19-potions-design.md`).

## Goal

Model relics in the sim: effects, elite and treasure drops, and shop stock. Retrain combat and the run policy to use them.

The user's goal is the **highest clear rate on the 500 generated maps, with relic odds as honest as the game's**. They chose this over the biggest possible number. So good relics must stay as rare as they really are.

**Success:**
- **Main bar:** the retrained models clear more than the current best models (v11 + v3, grown) do with relics switched on and no retraining. That reference is measured first (see "Evaluation"). Relics make the game easier without any learning, so the old 66.6% is not a fair bar and is only shown for context.
- **Honesty check:** drop rates and pool sizes match the game's, including every relic we don't model.

## Non-goals and anti-goals

- **Anti-goal: an inflated number.** Removing duds from the pool, or giving unmodeled relics an effect they don't have, would raise the number and is a failure even if it "works".
- **Anti-goal: quiet rule errors.** A wrongly modeled relic teaches bad habits with no visible symptom. Each relic gets its own test against its decompiled source.
- **Not in scope:**
  - live play: it keeps relic features at zero and relic actions masked off, as potions do
  - card upgrades, enchantments, colorless cards, rest-site choices, events and Neow
  - other characters' relics
  - Act 2 and later

## Assumptions carried over

Act 1, ascension 0, all epochs unlocked, no tutorial rewards, empty event rooms, no Neow. Burning Blood stays as it is: applied between fights.

## Game rules modeled

From the decompiled source (`decompiled/MegaCrit.Sts2.Core.*`). The exact values also go in `docs/game-architecture.md`.

- **Pool:** `SharedRelicPool` + `IroncladRelicPool`, rarities Common, Uncommon, Rare and Shop: 26 + 32 + 38 + 26 = **122 relics**.
- **Grab bags** (`RelicGrabBag`): one shuffled list per rarity, and two bags:
  - The player bag serves elites (pull from the front) and shops (pull from the back).
  - The shared bag serves treasure rooms (pull from the front), with its own shuffle.
  - A relic pulled from either bag is removed from both. No relic repeats in a run.
  - If a rarity is empty, it falls through Shop → Common → Uncommon → Rare.
- **Rarity roll** (`RelicFactory.RollRarity`): under 0.5 Common, under 0.83 Uncommon, otherwise Rare.
- **Elites** (`RewardsSet`): always one relic. Bosses give none.
- **Treasure rooms** (`OneOffSynchronizer`, `TreasureRoomRelicSynchronizer`): one relic plus `NextInt(42, 53)` gold. They replace the current empty placeholder.
- **Shops** (`MerchantInventory.PopulateRelicEntries`):
  - 3 relics: 2 rolled rarities and 1 Shop rarity, skipping relics with `IsAllowedInShops => false`.
  - Price: 175 / 225 / 275 / 200 (Common / Uncommon / Rare / Shop) × U(0.85, 1.15), rounded (`MerchantRelicEntry.CalcCost`).
- **Unmodeled relics** still drop, use up that reward and stock shops, so the odds stay right. They do nothing, and they can't be bought. Potions already work this way.

## Relics in scope

The builder reads each relic's source, which is the authority for exact timing. This table sets the scope.

**Modeled: 97.**

| Rarity | Relics |
|---|---|
| Common (24) | Amethyst Aubergine, Anchor, Bag of Marbles, Bag of Preparation, Blood Vial, Book of Five Rings, Bronze Scales, Centennial Puzzle, Festive Popper, Gorget, Happy Flower, Juzu Bracelet, Lantern, Meal Ticket, Oddly Smooth Stone, Pendulum, Potion Belt, Red Mask, Red Skull, Regal Pillow, Strawberry, Strike Dummy, Vajra, Venerable Tea Set |
| Uncommon (28) | Akabeko, Bowler Hat, Candelabra, Eternal Feather, Gremlin Horn, Horn Cleat, Joss Paper, Kusarigama, Letter Opener, Lucky Fysh, Mercury Hourglass, Nunchaku, Orichalcum, Ornamental Fan, Pantograph, Paper Phrog, Parrying Shield, Pear, Pen Nib, Permafrost, Planisphere, Reptile Trinket, Ripple Basin, Self-Forming Clay, Sparkling Rouge, Tiny Mailbox, Tuning Fork, Vambrace |
| Rare (30) | Art of War, Beating Remnant, Captain's Wheel, Chandelier, Charon's Ashes, Cloak Clasp, Demon Tongue, Game Piece, Ice Cream, Intimidating Helmet, Kunai, Lizard Tail, Mango, Meat on the Bone, Mummified Hand, Old Coin, Pocketwatch, Prayer Wheel, Rainbow Ring, Ruined Helmet, Shuriken, Stone Calendar, Sturdy Clamp, The Courier, Tungsten Rod, Unceasing Top, Unsettling Lamp, Vexing Puzzlebox, White Beast Statue, White Star |
| Shop (15) | Belt Buckle, Bread, Brimstone, Burning Sticks, Cauldron, Chemical X, Dragon Fruit, Ghost Seed, Lee's Waffle, Membership Card, Orrery, Ringing Triangle, Screaming Flagon, Sling of Courage, The Abacus |

**Not modeled: 25.** They stay in the pool as no-effect drops.

| Why | Relics |
|---|---|
| Card upgrades (10) | War Paint, Whetstone, Miniature Cannon, Stone Cracker, Bellows, Frozen Egg, Molten Egg, Toxic Egg, Razor Tooth, Lava Lamp |
| Enchantments (5) | Gnarled Hammer, Kifuda, Punch Dagger, Royal Stamp, Wing Charm |
| Choosing a card (2) | Gambling Chip, Dolly's Mirror |
| Colorless cards (2) | Dingy Rug, Toolbox |
| Rest-site choices (2) | Girya, Shovel |
| 4-card reward offers (1) | Lasting Candy |
| A new potion, the rock (1) | Petrified Toad |
| Truly no effect in this sim (2) | Miniature Tent (no other rest option exists), Mystic Lighter (no enchanted cards exist) |

Add them when the part they need exists.

## New mechanics the relics need

These go in the sim alongside the relics:
- **Powers:** Thorns (Bronze Scales), Vigor (Akabeko), Self-Forming Clay's next-turn block, Reptile Trinket's temporary Strength.
- **Death prevention:** Lizard Tail (`ShouldDieLate`).
- **HP-loss changes:** Tungsten Rod, Beating Remnant (`ModifyHpLostAfterOsty`).
- **Turn start changes:** Ice Cream (no energy reset), Ringing Triangle (no hand flush on turn 1), Sturdy Clamp (keep up to 10 block), Bag of Preparation and Pocketwatch (extra hand draw).
- **Energy and X-cost:** Bread, Chemical X.
- **Run-level:** max-HP changes, gold multipliers and triggers, the rest-site heal bonus, Juzu Bracelet's change to `?` rooms, Meal Ticket, Pantograph, Planisphere.
- **Shop price changes:** Membership Card, The Courier (including its restock of bought entries).
- **Queued rewards:** Prayer Wheel, White Star and Orrery add card picks. Cauldron and Tiny Mailbox add potion picks. All use the existing pick and potion decisions, offered one after another.
- **Potion slots:** Potion Belt takes the player to 5.
- **Ethereal on specific cards:** Ghost Seed (basic Strikes and Defends).
- **Generated cards:** Vexing Puzzlebox draws from the sim's existing `GENERATED` pool, like Infernal Blade. It can't generate a card the sim doesn't model, which is a small simplification to mark in code.

## Architecture

The two policies stay. Observation and action spaces grow by appending, so `grow.py` still applies.

### `agent/sim/relics.py`, `engine.py` and `act.py`

- `sim/relics.py`: `RELIC_POOL` (all 122 ids by rarity), `RELICS` (the modeled ids), and any per-relic constants. Mirrors `sim/potions.py`.
- **Relic state lives on `Run` and carries across fights**, because some counters do in the game (Pen Nib, Nunchaku, Tuning Fork, Happy Flower, Pendulum, Lizard Tail's used flag, Joss Paper, Book of Five Rings). `SimClient` takes it at fight start and hands it back, as it does for potions.
- `SimCombat` calls hooks at the points where the game does. Where the source doesn't fix an order, mark the assumption with a `ponytail:` comment, as the engine already does.
- `act.py`: grab bags, elite and treasure drops, shop relics.
- **Max HP must sync** between `Run` and each fight.

### Observations and actions (appended)

- **Combat env:** a multi-hot of modeled relics, the counters that matter for timing (for example Pen Nib's count), and the 2 extra potion slots.
- **Run env:** a multi-hot of modeled relics, the 3 shop relic slots (relic one-hot, price / 100, buyable), and the 2 extra potion slots.
- **Run actions:** buy shop relic 0–2, plus the actions for potion slots 3–4.
- **Automatic pickups need no action:** elite and treasure relics are taken automatically.

Exact feature layout is left to the builder.

## Training

Same shape as potions. Naming: grown models **v11r** and **v3r**, then **v13a**, **v13** and **run policy v5**. (v12 and v4 were an unused earlier round.)

1. **Grow** v11 and v3 into the new spaces, with new weights at zero.
2. **Reference:** evaluate v11r + v3r with relics on. The new relic-buying actions start at zero weight, so v3r buys relics semi-arbitrarily here. That is part of what the reference measures, as with potions, and should be reported as such.
3. **Combat phase A:** Act 1 pool with random decks, random potions and random relics. Random relic sets should be a plausible run's size, so every relic gets practice. Start at about 15M steps.
4. **Combat phase B:** run mode on generated maps with v3r making choices, about 20M steps. Result: **v13**.
5. **Run policy v5:** resume v3r with v13 fighting, about 4M decisions.
6. **Further rounds** only while each gains clearly more than noise (one standard error on 500 runs is about 2 points).

Step counts are starting points. The builder extends them if the learning curve is still climbing. Expect more than the 7 hours potions took.

Training runs in the background under `caffeinate -i`, with AC power checked first.

## Evaluation

The same 500 generated maps per row, picker N = 16.

- **Results table:**
  - v11 + v3 without relics (66.6%, for context)
  - v11r + v3r with relics (the reference and main bar)
  - v13 + v3r
  - v13 + v5
- **Each row:** clear rate, average floor, gold spent, potions used, relics per run, elites fought per run, and where runs died.
- **Honesty report:** over all runs, the share of relics obtained by rarity and the share that were unmodeled, against the expected odds.
- **Bosses:** the best combat model against each boss, with 0 relics and with a typical run's relics.

## Error handling

Unchanged from earlier sub-projects:
- `SimLoopError` ends a fight as aborted.
- Exceptions during a fight in `run_env` end the run as a loss.
- Masks are the only gate on forbidden actions, and the `Run` methods assert.
- `grow.py` refuses to save if its self-check fails.

## Testing

All tests are assert scripts, as before, run by the existing suite.
- **`sim/test_engine.py`:** each modeled relic's effect and timing, including counters that carry across fights.
- **`sim/test_act.py`:**
  - the rarity split over many rolls
  - no repeats across both bags
  - the fall-through when a rarity is empty
  - unmodeled relics staying in the pool
  - shop prices and the `IsAllowedInShops` filter
  - treasure gold
- **`test_run_env.py`:**
  - buying a relic is masked when too expensive or unmodeled
  - queued rewards are offered in order
  - Potion Belt's slots work in both envs
  - relic state and max HP carry through fights
  - the mask stays off on the live backend
- **Regression:** with no relics held, a fight plays exactly as it did before.
- **`sim/validate.py`** compares against the live game, which has no relic support here. So per-relic tests against the source are the main defense.

## Left to the builder

- batching the relic work and the order of batches
- exact feature layout and counters shown to the models
- hook order where the source doesn't fix it (marked in code)
- how the honesty report is computed
- `POTION_COST`-style tuning, if the numbers call for it
