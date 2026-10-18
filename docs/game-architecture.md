# STS2 Game Architecture

What we know about Slay the Spire 2's internals. Update this as we decompile and explore.

## Engine

- Custom Godot 4.5.1 Mono build called "MegaDot v4.5.1.m.8.mono"
- .NET 9.0 runtime (osx-arm64)
- Godot binary has full C++ symbols (not stripped)

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| GodotSharp | 4.5.1 | Godot C# bindings |
| 0Harmony | 2.4.2 | Runtime method patching (modding) |
| MonoMod.Backports | 1.1.2 | Low-level .NET patching utilities |
| Steamworks.NET | 1.0.0 | Steam integration |
| Sentry | 5.0.0 | Error reporting |
| FMOD | - | Audio (native dylib) |
| SmartFormat | 3.3.0 | String formatting/localization |
| Spine | - | 2D skeletal animation (native GDExtension) |

## Game DLL: sts2.dll

The main game logic. C# assembly, fully decompilable with ILSpy.

### Known classes/namespaces

#### AutoSlay — Built-in Automation System (`MegaCrit.Sts2.Core.AutoSlay`)

The game ships with a complete built-in automation/testing framework. See detailed analysis below in [AutoSlay System](#autoslay-system).

#### Core Game Classes (discovered via AutoSlay references)

| Class/Namespace | Purpose |
|---|---|
| `RunManager.Instance` | Singleton managing run state; has `DebugOnlyGetState()` returning `RunState`, `RoomEntered` event |
| `RunState` | Run state: `TotalFloor`, `CurrentRoom`, `CurrentActIndex`, `ActFloor`, `VisitedMapCoords`, `Acts`, `CurrentRoomCount`, `BaseRoom` |
| `CombatManager.Instance` | Singleton for combat: `IsInProgress`, `IsPlayPhase`, `DebugOnlyGetState()` returning `CombatState`, `CheckWinCondition()` |
| `CombatState` | Combat state: `HittableEnemies`, `Enemies`, `PlayerCreatures` |
| `NGame.Instance` | Root game node singleton; has `DebugSeedOverride`, `GetTree()` |
| `SaveManager.Instance` | Saves: `PrefsSave` (has `FastMode`), `SetFtuesEnabled()`, `ObtainEpochOverride()` |
| `NOverlayStack.Instance` | UI overlay stack: `Peek()`, `ScreenCount`, `Remove()` |
| `NMapScreen.Instance` | Map screen: `IsOpen`, `IsVisibleInTree()` |
| `NModalContainer.Instance` | Modal dialogs: `OpenModal` |
| `LocalContext.GetMe(RunState)` | Gets local `Player` from run state |
| `Player` | Player: `Creature`, `Potions`, `HasOpenPotionSlots` |
| `Creature` | Creature: `IsAlive`, `Powers`, `CombatState` |
| `CardModel` | Card: `Id.Entry`, `CanPlay()`, `TargetType`, `CombatState` |
| `PotionModel` | Potion: `Id.Entry`, `TargetType`, `EnqueueManualUse()` |
| `AbstractRoom` | Room: `RoomType` |
| `RoomType` (enum) | `Monster`, `Elite`, `Boss`, `Event`, `Shop`, `Treasure`, `RestSite`, `Unassigned` |
| `PileType` (enum) | Card pile types; `.GetPile(player)` returns `CardPile` |
| `CardPile` | Has `Cards` list of `CardModel` |
| `MapPoint` / `MapCoord` | Map nodes: `coord` (row/col), `Children` |
| `NonInteractiveMode` | Has `AutoSlayerCheck` delegate |

#### Key Command Classes

| Class | Methods |
|---|---|
| `CardCmd` | `AutoPlay(context, card, target)` — plays a card programmatically |
| `PlayerCmd` | `EndTurn(player, canBackOut)` — ends the player's turn |
| `PowerCmd` | `Apply<T>(creature, amount, source, ...)` — applies a power; `Remove(power)` |
| `CreatureCmd` | `Kill(creatures)` — kills creatures directly |
| `CardSelectCmd` | `UseSelector(ICardSelector)` — injects custom card selection logic |

#### Built-in Mod System (`MegaCrit.Sts2.Core.Modding`)

See detailed analysis in [modding-approach.md](modding-approach.md#built-in-mod-loading-system).

#### Dev Console (`MegaCrit.Sts2.Core.DevConsole`)

See detailed analysis in [modding-approach.md](modding-approach.md#dev-console-commands).

#### Hooks System (`MegaCrit.Sts2.Core.Hooks`)

See detailed analysis in [modding-approach.md](modding-approach.md#hooks-system).

#### Debug Utilities (`MegaCrit.Sts2.Core.Debug`)

| Class | Purpose |
|---|---|
| `DebugSettings` | `DevSkip` reads `STS2_DEV_SKIP` env var; `IgnorePackedImages` always false |
| `DebugHotkey` | StringName constants for debug hotkeys (hide UI elements, speed controls, unlock chars) |
| `DebugActMap` | Test node for generating random act maps |
| `SentryService` | Error reporting; disables when mods loaded; `AttachGameState()` dumps rich game state |
| `ReleaseInfo/ReleaseInfoManager` | Build version/branch/commit/date tracking |

### Key systems to map

- [x] Combat state management — `CombatManager`, `CombatState`, play phase polling (see AutoSlay)
- [x] Card data model — `CardModel`, `CardPile`, `PileType`, `TargetType`
- [x] Player state — `Player`, `Creature`, `Potions`, `HasOpenPotionSlots`
- [x] Event/choice system — `NEventOptionButton`, `Option.IsLocked`, `Option.IsProceed`
- [x] Map/pathing system — `MapPoint`, `MapCoord`, `VisitedMapCoords`, `NMapPoint`
- [x] Modding system — `ModManager`, `ModManifest`, PCK+DLL loading, Harmony auto-patching
- [x] Dev console — 39 built-in commands, extensible via mods
- [x] Hooks system — 60+ game event hooks on `AbstractModel`
- [x] Enemy data model — `MonsterModel`, `MoveState`, `AbstractIntent`, `AttackIntent`
- [x] Core entity models — full property-level analysis of all game entities
- [ ] Save/serialization (how state is persisted)

## Core Entity Data Model

Documented from decompiled source in `decompiled/`. These are the concrete property names accessible via Harmony patches or reflection.

### Creature (`MegaCrit.Sts2.Core.Entities.Creatures.Creature`)

Base entity for both players and monsters.

| Property | Type | Notes |
|---|---|---|
| `Block` | `int` | Current block (0-999, cleared each turn) |
| `CurrentHp` | `int` | Current HP |
| `MaxHp` | `int` | Maximum HP |
| `IsAlive` / `IsDead` | `bool` | HP > 0 |
| `IsMonster` / `IsPlayer` | `bool` | Type check |
| `IsStunned` | `bool` | NextMove.Id == "STUNNED" |
| `IsHittable` | `bool` | Alive and not hook-protected |
| `IsEnemy` / `IsPrimaryEnemy` / `IsSecondaryEnemy` | `bool` | Side checks |
| `Side` | `CombatSide` | Player or Enemy |
| `CombatId` | `uint?` | Unique combat identifier |
| `Name` | `string` | Resolved display name |
| `Monster` | `MonsterModel?` | Non-null for monsters |
| `Player` | `Player?` | Non-null for players |
| `ModelId` | `ModelId` | Canonical identifier |
| `Powers` | `IReadOnlyList<PowerModel>` | Active buffs/debuffs |
| `CombatState` | `CombatState?` | Current combat context |
| `PetOwner` / `IsPet` | `Player?` / `bool` | Pet companion system |
| `Pets` | `IReadOnlyList<Creature>` | Via PlayerCombatState |

Events: `BlockChanged`, `CurrentHpChanged`, `MaxHpChanged`, `PowerApplied`, `PowerIncreased`, `PowerDecreased`, `PowerRemoved`, `Died`, `Revived`

### Player (`MegaCrit.Sts2.Core.Entities.Players.Player`)

| Property | Type | Notes |
|---|---|---|
| `Character` | `CharacterModel` | Which character (Deprived, etc.) |
| `Creature` | `Creature` | The player's Creature entity |
| `Gold` | `int` | Current gold |
| `MaxEnergy` | `int` | Base max energy for the run |
| `Deck` | `CardPile` | Persistent deck (PileType.Deck) |
| `Relics` | `IReadOnlyList<RelicModel>` | All relics |
| `PotionSlots` | `IReadOnlyList<PotionModel?>` | Slots (null = empty) |
| `Potions` | `IEnumerable<PotionModel>` | Non-null potions only |
| `MaxPotionCount` | `int` | Current slot count (starts at 3) |
| `HasOpenPotionSlots` | `bool` | Any empty slots |
| `PlayerCombatState` | `PlayerCombatState?` | Only during combat |
| `RunState` | `IRunState` | Run context |
| `BaseOrbSlotCount` | `int` | Orb capacity |
| `NetId` | `ulong` | Network/multiplayer ID |
| `Osty` | `Creature?` | Pet companion |
| `IsOstyAlive` | `bool` | Pet alive check |

### PlayerCombatState (`MegaCrit.Sts2.Core.Entities.Players.PlayerCombatState`)

Active only during combat. This is where the hand/draw/discard piles live.

| Property | Type | Notes |
|---|---|---|
| `Hand` | `CardPile` | Current hand (max 10 cards) |
| `DrawPile` | `CardPile` | Draw pile |
| `DiscardPile` | `CardPile` | Discard pile |
| `ExhaustPile` | `CardPile` | Exhaust pile |
| `PlayPile` | `CardPile` | Cards being played |
| `AllPiles` | `IReadOnlyList<CardPile>` | All 5 combat piles |
| `AllCards` | `IEnumerable<CardModel>` | All cards across piles |
| `Energy` | `int` | Current energy this turn |
| `MaxEnergy` | `int` | Effective max (after hooks) |
| `Stars` | `int` | Star resource (STS2 mechanic) |
| `OrbQueue` | `OrbQueue` | Orb slots |
| `Pets` | `IReadOnlyList<Creature>` | Pet creatures |

Methods: `HasCardsToPlay()`, `HasEnoughResourcesFor(card, out reason)`

### CardModel (`MegaCrit.Sts2.Core.Models.CardModel`) — abstract

Each card is a subclass. Constructor: `CardModel(int canonicalEnergyCost, CardType type, CardRarity rarity, TargetType targetType, bool shouldShowInCardLibrary = true)`

| Property | Type | Notes |
|---|---|---|
| `Id` | `ModelId` | Canonical card identifier |
| `Title` | `string` | Display name (with "+" if upgraded) |
| `Type` | `CardType` | Attack, Skill, Power, Status, Curse, Quest |
| `Rarity` | `CardRarity` | Basic, Common, Uncommon, Rare, Ancient, Event, Token, Status, Curse, Quest |
| `TargetType` | `TargetType` | None, Self, AnyEnemy, AllEnemies, RandomEnemy, AnyPlayer, AnyAlly, AllAllies, TargetedNoCreature, Osty |
| `EnergyCost` | `CardEnergyCost` | Energy cost object (see below) |
| `BaseStarCost` / `CurrentStarCost` | `int` | Star cost (-1 = no star cost) |
| `HasStarCostX` | `bool` | X star cost |
| `Keywords` | `IReadOnlySet<CardKeyword>` | Exhaust, Ethereal, Innate, Unplayable, Retain, Sly, Eternal |
| `Tags` | `IEnumerable<CardTag>` | Strike, Defend, Minion, OstyAttack, Shiv |
| `CurrentUpgradeLevel` / `MaxUpgradeLevel` | `int` | Upgrade tracking |
| `IsUpgraded` / `IsUpgradable` | `bool` | Upgrade status |
| `BaseReplayCount` | `int` | Extra plays |
| `Owner` | `Player` | Owning player |
| `Pile` | `CardPile?` | Current pile |
| `IsInCombat` | `bool` | In a combat pile |
| `IsPlayable` | `bool` | (protected virtual) |
| `IsRemovable` | `bool` | !Eternal keyword |
| `Enchantment` | `EnchantmentModel?` | Card enchantment |
| `Affliction` | `AfflictionModel?` | Card affliction |
| `DynamicVars` | `DynamicVarSet` | Runtime values (damage, block) |
| `Pool` | `CardPoolModel` | Character pool |
| `CombatState` | `CombatState?` | Combat context |
| `ExhaustOnNextPlay` | `bool` | Temporary exhaust |
| `ShouldRetainThisTurn` / `IsSlyThisTurn` | `bool` | Turn-scoped keywords |
| `CurrentTarget` | `Creature?` | Current target |
| `DeckVersion` | `CardModel?` | Link to deck copy |
| `HasBeenRemovedFromState` | `bool` | Removed from run |

#### CardEnergyCost (`MegaCrit.Sts2.Core.Entities.Cards.CardEnergyCost`)

| Property/Method | Type | Notes |
|---|---|---|
| `Canonical` | `int` | Original base cost |
| `CostsX` | `bool` | Is X-cost card |
| `GetWithModifiers(CostModifiers.All)` | `int` | Effective cost with all modifiers |
| `GetAmountToSpend()` | `int` | Actual amount to pay (X = all energy) |
| `CapturedXValue` | `int` | Resolved X value (only for X-cost) |
| `HasLocalModifiers` | `bool` | Has temporary cost changes |

### CardPile (`MegaCrit.Sts2.Core.Entities.Cards.CardPile`)

| Property | Type | Notes |
|---|---|---|
| `Type` | `PileType` | None, Draw, Hand, Discard, Exhaust, Play, Deck |
| `Cards` | `IReadOnlyList<CardModel>` | Cards in this pile |
| `IsEmpty` | `bool` | No cards |
| `IsCombatPile` | `bool` | Not Deck or None |
| `UpgradableCardCount` | `int` | Cards that can be upgraded |
| `maxCardsInHand` | `const int = 10` | Hand size limit |

### PowerModel (`MegaCrit.Sts2.Core.Models.PowerModel`) — abstract

| Property | Type | Notes |
|---|---|---|
| `Id` | `ModelId` | Power identifier |
| `Type` | `PowerType` | Buff or Debuff |
| `StackType` | `PowerStackType` | Counter (stacks) or Single |
| `Amount` | `int` | Stack count / duration |
| `AmountOnTurnStart` | `int` | Snapshot at turn start |
| `DisplayAmount` | `int` | Visual amount |
| `AllowNegative` | `bool` | Can go below 0 |
| `Owner` | `Creature` | Who has this power |
| `Applier` / `Target` | `Creature?` | Source and target |
| `IsVisible` | `bool` | Should display in UI |
| `IsInstanced` | `bool` | Multiple instances allowed |

### RelicModel (`MegaCrit.Sts2.Core.Models.RelicModel`) — abstract

| Property | Type | Notes |
|---|---|---|
| `Id` | `ModelId` | Relic identifier |
| `Rarity` | `RelicRarity` | Starter, Common, Uncommon, Rare, Shop, Event, Ancient |
| `Owner` | `Player` | Owning player |
| `Status` | `RelicStatus` | Normal, Active, Disabled |
| `IsUsedUp` | `bool` | One-time relic consumed |
| `IsMelted` / `IsWax` | `bool` | Wax relic system |
| `IsStackable` / `StackCount` | `bool` / `int` | Stackable relics |
| `FloorAddedToDeck` | `int` | When obtained |
| `MerchantCost` | `int` | Shop price (200-300 by rarity) |
| `DisplayAmount` | `int` | Counter display |
| `HasBeenRemovedFromState` | `bool` | Removed from run |

### PotionModel (`MegaCrit.Sts2.Core.Models.PotionModel`) — abstract

| Property | Type | Notes |
|---|---|---|
| `Id` | `ModelId` | Potion identifier |
| `Rarity` | `PotionRarity` | Common, Uncommon, Rare, Event, Token |
| `Usage` | `PotionUsage` | CombatOnly, AnyTime, Automatic |
| `TargetType` | `TargetType` | Targeting for use |
| `Owner` | `Player` | Owning player |
| `IsQueued` | `bool` | Queued for use |
| `CanBeGeneratedInCombat` | `bool` | Can appear mid-combat |
| `HasBeenRemovedFromState` | `bool` | Used/discarded |

### MonsterModel (`MegaCrit.Sts2.Core.Models.MonsterModel`) — abstract

| Property | Type | Notes |
|---|---|---|
| `Id` | `ModelId` | Monster identifier |
| `MinInitialHp` / `MaxInitialHp` | `int` | HP range |
| `Creature` | `Creature` | The creature entity |
| `CombatState` | `CombatState` | Combat context |
| `NextMove` | `MoveState` | Current planned move |
| `IntendsToAttack` | `bool` | Has Attack/DeathBlow intent |
| `IsPerformingMove` | `bool` | Currently executing |
| `SpawnedThisTurn` | `bool` | Just spawned (skips first turn) |
| `MoveStateMachine` | `MonsterMoveStateMachine?` | AI state machine |

### MoveState (`MegaCrit.Sts2.Core.MonsterMoves.MonsterMoveStateMachine.MoveState`)

| Property | Type | Notes |
|---|---|---|
| `Id` / `StateId` | `string` | Move identifier |
| `Intents` | `IReadOnlyList<AbstractIntent>` | What the move does |
| `FollowUpStateId` | `string?` | Next state after this move |
| `MustPerformOnceBeforeTransitioning` | `bool` | Lock to this move |
| `CanTransitionAway` | `bool` | Can change moves |

### AbstractIntent / AttackIntent

`IntentType` enum: Attack, Buff, Debuff, DebuffStrong, Defend, Escape, Heal, Hidden, Summon, Sleep, Stun, StatusCard, CardDebuff, DeathBlow, Unknown

`AttackIntent` adds:
- `Func<decimal>? DamageCalc` — damage calculation function
- `int Repeats` — extra hits (0 = single hit)
- `int GetTotalDamage(targets, owner)` — total damage (abstract)
- `int GetSingleDamage(targets, owner)` — per-hit after hooks

### Run State

#### IRunState / RunState (`MegaCrit.Sts2.Core.Runs`)

| Property | Type | Notes |
|---|---|---|
| `Players` | `IReadOnlyList<Player>` | All players |
| `Acts` | `IReadOnlyList<ActModel>` | Act definitions |
| `CurrentActIndex` | `int` | Which act (0-indexed) |
| `Act` | `ActModel` | Current act |
| `Map` | `ActMap` | Current map |
| `CurrentMapCoord` / `CurrentMapPoint` | `MapCoord?` / `MapPoint?` | Position |
| `CurrentLocation` | `RunLocation` | Full location |
| `ActFloor` / `TotalFloor` | `int` | Floor progress |
| `CurrentRoom` / `BaseRoom` | `AbstractRoom?` | Current room |
| `IsGameOver` | `bool` | All players dead |
| `AscensionLevel` | `int` | Difficulty |
| `Rng` | `RunRngSet` | RNG seeds |
| `Modifiers` | `IReadOnlyList<ModifierModel>` | Active modifiers |
| `ExtraFields` | `ExtraRunFields` | Additional state |

#### CombatState (`MegaCrit.Sts2.Core.Combat.CombatState`)

| Property | Type | Notes |
|---|---|---|
| `Allies` | `IReadOnlyList<Creature>` | Player-side creatures |
| `Enemies` | `IReadOnlyList<Creature>` | Enemy-side creatures |
| `Creatures` | `IReadOnlyList<Creature>` | All creatures |
| `PlayerCreatures` | `IReadOnlyList<Creature>` | Only player creatures |
| `Players` | `IReadOnlyList<Player>` | Players in combat |
| `HittableEnemies` | `IReadOnlyList<Creature>` | Alive + hittable enemies |
| `RoundNumber` | `int` | Current round |
| `CurrentSide` | `CombatSide` | Player or Enemy turn |
| `Encounter` | `EncounterModel?` | Encounter definition |
| `RunState` | `IRunState` | Parent run |

### Access Strategy for Mod

Key singleton access points:
- `RunManager.Instance` -> `DebugOnlyGetState()` -> `RunState` (run-level state)
- `CombatManager.Instance` -> `DebugOnlyGetState()` -> `CombatState` (combat-level state)
- `RunState.Players[0]` -> `Player` -> `Creature` (player entity)
- `Player.PlayerCombatState` -> `Hand`, `DrawPile`, `DiscardPile`, `Energy`, `Stars`
- `CombatState.Enemies` -> each `Creature` -> `Monster` -> `NextMove` -> `Intents`
- `AttackIntent.DamageCalc()` / `GetSingleDamage()` for damage numbers
- `CardModel.EnergyCost.GetWithModifiers(CostModifiers.All)` for effective card cost
- `CardModel.CanPlay()` to check if a card is playable
- `PotionModel.EnqueueManualUse(target)` to use potions programmatically
- `CardCmd.AutoPlay(context, card, target)` to play cards programmatically

## AutoSlay System

### Overview

AutoSlay is MegaCrit's **built-in automation/QA testing framework** that can play complete runs autonomously. It is a fully async, polling-based system that navigates the main menu, selects a character, plays through all rooms floor-by-floor, handles every screen/overlay, and quits the game when done.

### Architecture

**Pattern**: Async polling loop with handler dispatch.

The core loop in `AutoSlayer.PlayRunAsync()`:
1. Wait for game init, configure settings (fast mode, unlock all characters, set seed)
2. Navigate main menu: abandon existing run if needed, click Singleplayer, pick random character
3. Main floor loop (`while TotalFloor < 49`):
   - Get current room type from `RunState.CurrentRoom.RoomType`
   - Dispatch to appropriate `IRoomHandler`
   - After combat rooms: wait for rewards screen
   - Drain all overlay screens via `DrainOverlayScreensAsync()` (dispatches to `IScreenHandler`s)
   - Handle special post-room logic (rest site proceed, event proceed, boss act transitions)
   - Navigate map via `MapScreenHandler`

**No event loop or signals for coordination** — it uses `async/await` with `WaitHelper.Until()` polling at 100ms intervals. The one exception is `MapScreenHandler` which subscribes to `RunManager.Instance.RoomEntered` event.

### Activation

- `AutoSlayer.Start(seed, logFile)` — starts an async run
- Sets `IsActive = true`, `NonInteractiveMode.AutoSlayerCheck` returns `IsActive`
- Sets `SaveManager.Instance.PrefsSave.FastMode = FastModeType.Fast`
- Disables FTUEs, unlocks all epochs (characters)
- Uses a deterministic `Rng` seeded from the seed string
- On completion/failure, calls `NGame.Instance.GetTree().Quit(exitCode)`

### How it reads game state

- **Run state**: `RunManager.Instance.DebugOnlyGetState()` returns `RunState` with floor, act, room, visited coords
- **Combat state**: `CombatManager.Instance.IsInProgress`, `IsPlayPhase`, `DebugOnlyGetState()` for enemies/creatures
- **UI state**: Polls Godot scene tree nodes by absolute path (e.g. `/root/Game/RootSceneContainer/Run/RoomContainer/EventRoom`)
- **Overlay stack**: `NOverlayStack.Instance.Peek()` and `ScreenCount`
- **Buttons/options**: `UiHelper.FindAll<T>(node)` recursive search, then checks `IsEnabled`, `Visible`, `IsLocked`

### How it sends commands/actions

Two distinct mechanisms:

1. **Direct game commands** (bypasses UI):
   - `CardCmd.AutoPlay(context, card, target)` — plays cards
   - `PlayerCmd.EndTurn(player, canBackOut)` — ends turn
   - `PowerCmd.Apply<T>(creature, amount, source)` — applies buffs (999 Plating, 999 Regen for invincibility)
   - `CreatureCmd.Kill(creatures)` — kills enemies directly
   - `PotionModel.EnqueueManualUse(target)` — uses potions

2. **UI simulation** (clicks buttons):
   - `UiHelper.Click(button)` calls `button.ForceClick()` (not mouse simulation)
   - `EmitSignal(SignalName.Pressed, ...)` / `EmitSignal(SignalName.Released, ...)` for card holders and clickable controls
   - Node path navigation: `root.GetNode<T>(path)`, `GetNodeOrNull<T>(path)`

### Combat Strategy

The combat handler is **not intelligent** — it's a QA stress-test tool:
- Applies 999 Plating + 999 Regen at combat start (effectively invincible)
- Uses all potions at start of each turn
- Plays random playable cards at random targets
- Ends turn when no more playable cards remain
- For event combat: also applies 100 Strength and directly kills enemies via `CreatureCmd.Kill()`

### Handler Registry

**Room Handlers** (`IRoomHandler` — dispatched by `RoomType`):
| RoomType | Handler | Strategy |
|---|---|---|
| Monster, Elite, Boss | `CombatRoomHandler` | Apply buffs, play random cards |
| Event | `EventRoomHandler` | Click random unlocked options, handle Ancient dialogue, FakeMerchant |
| Shop | `ShopRoomHandler` | Buy all affordable items randomly (except card removal) |
| Treasure | `TreasureRoomHandler` | Open chest, pick up all relics |
| RestSite | `RestSiteRoomHandler` | Pick random enabled option |

**Screen Handlers** (`IScreenHandler` — dispatched by `Type`):
| Screen Type | Handler | Strategy |
|---|---|---|
| `NRewardsScreen` | `RewardsScreenHandler` | Click all reward buttons (skip potions if full) |
| `NCardRewardSelectionScreen` | `CardRewardScreenHandler` | Pick random card |
| `NDeckUpgradeSelectScreen` | `DeckUpgradeScreenHandler` | Upgrade random card |
| `NDeckTransformSelectScreen` | `DeckTransformScreenHandler` | Transform random card |
| `NDeckEnchantSelectScreen` | `DeckEnchantScreenHandler` | Enchant random card |
| `NDeckCardSelectScreen` | `DeckCardSelectScreenHandler` | Select random cards |
| `NSimpleCardSelectScreen` | `SimpleCardSelectScreenHandler` | Select random cards |
| `NChooseACardSelectionScreen` | `ChooseACardScreenHandler` | Pick random card |
| `NChooseABundleSelectionScreen` | `ChooseABundleScreenHandler` | Pick random bundle |
| `NChooseARelicSelection` | `ChooseARelicScreenHandler` | Pick random relic |
| `NGameOverScreen` | `GameOverScreenHandler` | Click continue, then return to main menu |
| `NCrystalSphereScreen` | `CrystalSphereScreenHandler` | Click random hidden cells, then proceed |

### Helper Classes

- **`UiHelper`**: `Click(button)` via `ForceClick()`, `FindAll<T>(node)` recursive node search, `FindFirst<T>(node)`
- **`WaitHelper`**: `Until(condition, ct, timeout)` polls at 100ms, `ForNode<T>(root, path)` waits for node existence+visibility+enabled, `WithTimeout()` wraps async operations, `ForTask()` waits for task completion. Includes `DumpSceneTreeContext()` for debugging.
- **`Watchdog`**: Tracks last activity time, throws `AutoSlayTimeoutException` if no progress for 30s, logs warnings every 5s
- **`AutoSlayCardSelector`**: Implements `ICardSelector` for random card selection when game prompts for card choices (injected via `CardSelectCmd.UseSelector()`)

### Timeouts (from `AutoSlayConfig`)

| Config | Value |
|---|---|
| `runTimeout` | 25 minutes |
| `defaultRoomTimeout` | 2 minutes |
| `defaultScreenTimeout` | 30 seconds |
| `gameInitTimeout` | 10 seconds |
| `pollingInterval` | 100ms |
| `buttonClickDelay` | 100ms |
| `maxFloor` | 49 |
| `watchdogTimeout` | 30 seconds |

## Act 1 runs (map, rooms, shop)

Ported to the sim in `agent/sim/map.py` and `agent/sim/act.py`.

- **Map** (`Map/StandardActMap.cs`):
  - **Grid:** 7 columns. Row 0 is the Ancient (Neow), rows 1–15 are rooms (`Overgrowth.BaseNumberOfRooms`) and row 16 is the boss.
  - **Paths:** 7 paths start on row 1, the second always on a new column. Each path steps to column −1, 0 or +1 in shuffled order, skipping a step that would cross the neighbor's diagonal.
  - **Fixed rows:** row 1 is all Monster, row 9 (rows − 7) all Treasure, row 15 all RestSite.
  - **Random rooms:** a queue of RestSite × N(7,1)∈[6,7], Shop × 3, Elite × 5 and Unknown × N(12,1)∈[10,14] is placed at random. Up to 3 passes are made over unassigned points, and invalid types rotate to the back of the queue. Leftover points become Monster.
  - **Placement rules:** no RestSite or Elite below row 6, and no RestSite in rows 13+. Elite, RestSite, Treasure and Shop can't sit next to the same type (parent or child). RestSite, Monster, Unknown, Elite and Shop can't sit beside the same type (siblings, meaning a parent's other children).
  - **After generation:** `MapPathPruning` removes duplicate parallel segments, and `MapPostProcessing` moves columns only.
- **Encounters** (`ActModel.GenerateRooms`):
  - The monster-room queue is 3 weak encounters, then 12 regular ones, each drawn from a refilling bag that avoids the previous encounter and any shared `EncounterTag`.
  - Elites come from their own bag (15 deep).
  - The boss is drawn at run start, but a not-yet-seen boss is forced first (`BossDiscoveryOrder`: Vantom, Ceremonial Beast, Kin).
- **"?" rooms** (`Odds/UnknownMapPointOdds.cs`):
  - Base odds are Monster 10%, Treasure 2%, Shop 3%, otherwise Event; Elite is −1, so never.
  - A rolled type resets to its base, and each unrolled allowed type grows by its base.
  - Shop is blacklisted after a shop, or when every next point is a shop (`RunManager.BuildRoomTypeBlacklist`).
  - On a profile's first run, the first two "?" rooms are events and the third is a monster.
- **Gold:** the Ironclad starts with 99. Fights pay Monster 10–20, Elite 35–45, Boss 100 (`EncounterModel.Min/MaxGoldReward`).
- **Shop** (`Entities/Merchant/`):
  - **Character cards:** 5 slots typed Attack, Attack, Skill, Skill, Power. Rarity uses the shop odds (Rare 9% + the card-rarity offset, which this roll doesn't advance; Uncommon 37%). If a type has no card of that rarity, it falls to the next rarity (Common → Uncommon → Rare → Common). Already-stocked cards are excluded.
  - **Price:** 50/75/150 by rarity × U(0.95, 1.05), rounded; colorless cards ×1.15. One random character card is half price.
  - **Other stock:** 2 colorless cards (Uncommon, Rare), 3 relics (2 rolled + 1 Shop rarity) and 3 potions.
  - **Card removal:** once per shop, 75 + 25 per removal used this run.
- **Rest site:** heals 30% of max HP (`HealRestSiteOption`).

## File structure

### PCK contents

_TODO: Extract and document after running gdre_tools or similar_

### Save files

Located at `~/Library/Application Support/SlayTheSpire2/steam/<steam_id>/`

- `profile.save` / `profile.save.backup`
- `settings.save` / `settings.save.backup`
- Per-profile directory (e.g. `profile1/`)

### Logs

`~/Library/Application Support/SlayTheSpire2/logs/godot.log`

Useful log lines observed:
- AtlasManager loads: `card_atlas` (840 sprites), `relic_atlas` (336), `power_atlas` (268), `potion_atlas` (63), `intent_atlas` (310)
- ModelIdSerializationCache: 19 categories, 1597 entries, 57 epochs
- Save system: PrefsSave v2, ProfileSave v2, SerializableProgress v21, RunHistory v8, SerializableRun v14, SettingsSave v4
