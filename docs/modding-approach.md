# Modding Approach

## Chosen strategy: .NET Harmony patching

Since STS2 ships with HarmonyLib and runs on .NET 9, we can write a C# mod DLL that patches game methods at runtime. This is the same technique used by BepInEx, SMAPI, and most .NET game modding frameworks.

## Goal: CommunicationMod for STS2

Build a mod that:
1. Hooks into game state (combat, cards, enemies, events, map)
2. Exposes state as JSON over a local WebSocket server
3. Accepts commands (play card, end turn, choose event option, etc.)
4. An external Python client connects and drives the game

## Built-in Mod Loading System

**STS2 has a complete, official mod loading system.** No need for BepInEx or startup hooks.

### How it works (`ModManager.Initialize()`)

1. **Mod directory scanning**: Looks for `.pck` files recursively in `<game_dir>/mods/`
2. **Steam Workshop**: Also loads subscribed Workshop items (app ID `2868840`)
3. **For each `.pck` file found**:
   - Checks if the player has agreed to mod loading (`PlayerAgreedToModLoading` in settings)
   - Checks if the mod is disabled in settings
   - Loads a companion DLL with the same name (e.g. `mymod.pck` + `mymod.dll`)
   - DLL is loaded via `AssemblyLoadContext.LoadFromAssemblyPath()`
   - Loads the PCK into Godot via `ProjectSettings.LoadResourcePack()`
   - Reads `res://mod_manifest.json` from the PCK
   - If the DLL has classes with `[ModInitializer("MethodName")]` attribute, calls those static methods
   - If NO `ModInitializerAttribute` found, falls back to `Harmony.PatchAll(assembly)` automatically
4. **Assembly resolution**: `HandleAssemblyResolveFailure()` automatically resolves references to `sts2` and `0Harmony` assemblies

### Mod Manifest Format (`mod_manifest.json`)

```json
{
  "pck_name": "mymod",
  "name": "My Mod Display Name",
  "author": "AuthorName",
  "description": "What the mod does",
  "version": "1.0.0"
}
```

### Key Classes

| Class | Purpose |
|---|---|
| `ModManager` | Static class, loads/manages all mods, fires `OnModDetected` event |
| `Mod` | Mod instance: `pckName`, `modSource`, `wasLoaded`, `manifest`, `assembly` |
| `ModManifest` | JSON-deserialized manifest with name, author, version, etc. |
| `ModInitializerAttribute` | `[ModInitializer("Init")]` on a class — specifies static init method to call |
| `ModHelper` | `AddModelToPool<TPoolType, TModelType>()` — lets mods add content to game pools |
| `ModSettings` | Per-mod enable/disable tracking in player settings |
| `ModSource` | Enum: `None`, `ModsDirectory`, `SteamWorkshop` |
| `DisabledMod` | Serializable record of disabled mod name + source |

### Loading Approaches for Our Mod

The simplest approach:
1. Create `mymod.pck` (can be minimal/empty Godot PCK with just `mod_manifest.json`)
2. Create `mymod.dll` (our C# mod assembly referencing `sts2.dll` and `0Harmony.dll`)
3. Place both in `<game_dir>/mods/`
4. Either use `[ModInitializer]` for custom init, or let Harmony auto-patch

The game will auto-resolve references to `sts2` and `0Harmony`, so our DLL only needs to reference those.

### Mod Console Commands

The `DevConsole` constructor includes: `ReflectionHelper.GetSubtypesInMods<AbstractConsoleCmd>()` — meaning **mods can register their own console commands** by simply subclassing `AbstractConsoleCmd` in their assembly.

### Command Line Args

- `--nomods` — skips mod initialization entirely

## Loading mechanism (RESOLVED)

Use the built-in mod system. No external tools needed.

- [x] Built-in mod system via `<game_dir>/mods/` directory (PCK + DLL)
- [ ] ~~`DOTNET_STARTUP_HOOKS` environment variable~~ (not needed)
- [ ] ~~BepInEx for Godot/.NET~~ (not needed)
- [ ] ~~Patching sts2.runtimeconfig.json~~ (not needed)
- [ ] ~~GDExtension that bootstraps C# code~~ (not needed)
- [ ] ~~Modifying the game's entry point~~ (not needed)

## Harmony patching basics

```csharp
// Prefix: runs before the original method
[HarmonyPatch(typeof(SomeGameClass), "SomeMethod")]
class MyPatch {
    static void Prefix(SomeGameClass __instance) {
        // read state from __instance
    }

    static void Postfix(ref ReturnType __result) {
        // modify return value or react to method completion
    }
}
```

## Alternative tools explored

See `docs/research.md` for full analysis. Summary:
- Frida: good for prototyping, can attach to running game
- Godot remote debugger: possible but protocol is undocumented
- PCK modding: game logic is in C# not GDScript, so limited value
- OS-level input: fallback only, no state reading
- Screenshots: last resort

## Dev Console Commands

The game has 39 built-in console commands. Most are debug-only (not available in release builds) but `open`, `cloud`, `log`, and `getlogs` are available in release. The `DevConsole` constructor also loads subtypes from mods, so **our mod can add custom commands**.

### Command Reference

| Command | Args | Description | Networked | Debug-Only |
|---|---|---|---|---|
| `achievement` | `<unlock\|revoke\|check> [id]` | Unlock/revoke achievements | No | Yes |
| `act` | `<int\|string>` | Jump to act by index or replace current act | Yes | Yes |
| `afflict` | `<id> [amount] [hand-index]` | Apply affliction to hand card | Yes | Yes |
| `ancient` | `<id> <choice>` | Open ancient event with forced choice | Yes | Yes |
| `art` | `<type>` | List content missing art (affliction/card/enchantment/power/relic) | No | Yes |
| `block` | `<amount> [target-index]` | Give block to creature (0=player) | Yes | Yes |
| `card` | `<card-id> [pile]` | Spawn card into pile (hand default). SCREAMING_SNAKE_CASE | Yes | Yes |
| `cloud` | `delete` | Delete all Steam cloud saves | No | No |
| `damage` | `<amount> [target-index]` | Damage enemies or specific creature | Yes | Yes |
| `die` | | Kill the player | Yes | Yes |
| `draw` | `[count]` | Draw cards (default 1) | Yes | Yes |
| `dump` | | Dump Model ID database to logs | No | Yes |
| `enchant` | `<id> [amount] [hand-index]` | Enchant a hand card | Yes | Yes |
| `energy` | `<amount>` | Add energy to player | Yes | Yes |
| `event` | `<id>` | Jump to specific event | Yes | Yes |
| `fight` | `<id>` | Jump to specific encounter | Yes | Yes |
| `getlogs` | `[name]` | Zip logs and open directory | No | No |
| `godmode` | | Toggle invincibility (9999 Strength/Buffer/Regen) | Yes | Yes |
| `gold` | `<amount>` | Add/remove gold | Yes | Yes |
| `heal` | `<amount> [index]` | Heal player or ally | Yes | Yes |
| `instant` | | Toggle instant animation mode | No | Yes |
| `kill` | `[index\|all]` | Kill enemies | Yes | Yes |
| `leaderboard` | `[upload\|random] ...` | Manipulate leaderboard scores | No | Yes |
| `log` | `[type] <level>` | Set log level for log types | No | No |
| `log-history` | | Save command history to file | No | Yes |
| `multiplayer` | `[test]` | Open multiplayer menu or test scene | No | Yes |
| `open` | `logs\|saves\|root\|build-logs\|loc-override` | Open directory in file manager | No | No |
| `potion` | `<id>` | Add potion to belt. SCREAMING_SNAKE_CASE | Yes | Yes |
| `power` | `<id> <amount> <target-index>` | Apply power to creature | Yes | Yes |
| `relic` | `[add\|remove] <id>` | Add or remove relic | Yes | Yes |
| `remove_card` | `<id> [pile]` | Remove card from hand or deck | Yes | Yes |
| `room` | `<RoomType>` | Jump to room type | Yes | Yes |
| `sentry` | `<test\|message\|exception\|crash\|status>` | Test Sentry error reporting | No | Yes |
| `stars` | `<amount>` | Add stars (in combat) | Yes | Yes |
| `trailer` | | Toggle trailer mode (show/hide UI via hotkeys) | No | Yes |
| `travel` | | Toggle free map travel | Yes | Yes |
| `unlock` | `<cards\|potions\|relics\|monsters\|events\|epochs\|ascensions\|all>` | Mark content as discovered | No | Yes |
| `upgrade` | `[hand-index]` | Upgrade card in hand | Yes | Yes |
| `win` | | Win current combat (kill all enemies) | Yes | Yes |

### Key APIs Used by Console Commands

These show what programmatic operations the game supports:
- `ModelDb.AllCards`, `AllRelics`, `AllPotions`, `AllEncounters`, `AllEvents`, `AllAncients`, `AllPowers`, `Monsters`, `Acts`, `AllCharacters` — access to all game content
- `RunManager.Instance.EnterRoomDebug(roomType)`, `EnterRoom(room)`, `EnterAct(index)` — room/act navigation
- `CombatManager.Instance.DebugOnlyGetState()` — combat state access
- `CombatManager.Instance.CheckWinCondition()` — trigger win check
- `PileType.Hand.GetPile(player).Cards` — hand inspection
- `CardCmd.Upgrade(card)`, `CardCmd.Enchant(enchantment, card, amount)`, `CardCmd.Afflict(affliction, card, amount)` — card manipulation
- `CreatureCmd.Kill(creature)`, `CreatureCmd.Heal(creature, amount)`, `CreatureCmd.Damage(...)`, `CreatureCmd.GainBlock(...)` — creature manipulation
- `PlayerCmd.GainGold(amount, player)`, `PlayerCmd.GainEnergy(amount, player)`, `PlayerCmd.GainStars(amount, player)` — player resource manipulation
- `PotionCmd.TryToProcure(potion, player)` — add potions
- `RelicCmd.Obtain(relic, player)`, `RelicCmd.Remove(relic)` — relic manipulation
- `CardPileCmd.Add(card, pile)`, `CardPileCmd.Draw(context, count, player)`, `CardPileCmd.RemoveFromCombat(card)`, `CardPileCmd.RemoveFromDeck(card)` — card pile manipulation
- `PowerCmd.Apply(power, creature, amount)`, `PowerCmd.ModifyAmount(power, amount)`, `PowerCmd.Remove<T>(creature)` — power manipulation
- `SaveManager.Instance.PrefsSave.FastMode = FastModeType.Instant` — animation speed control

## Hooks System

The `Hook` static class (`MegaCrit.Sts2.Core.Hooks`) dispatches 60+ game events to all `AbstractModel` instances that are registered as "hook listeners" in the current run/combat state. These are **not modding hooks in the Harmony sense** — they are the game's internal event system used by relics, powers, and cards to react to game events.

### How Hooks Work

Each hook method:
1. Iterates `runState.IterateHookListeners(combatState)` or `combatState.IterateHookListeners()`
2. For each `AbstractModel` listener, calls the corresponding virtual method
3. Calls `model.InvokeExecutionFinished()` after each listener

The listeners are `AbstractModel` subclasses (relics, powers, cards, etc.) that override the virtual hook methods. They are **not extensible through a subscribe/unsubscribe API** — the iteration order comes from the game's internal model registration.

### Hook Categories

**Combat Flow**: `BeforeCombatStart`/Late, `AfterCombatEnd`, `AfterCombatVictory`/Early, `BeforePlayPhaseStart`, `AfterPlayerTurnStart`/Early/Late, `BeforeSideTurnStart`, `AfterSideTurnStart`, `BeforeTurnEnd`/VeryEarly/Late, `AfterTakingExtraTurn`

**Cards**: `BeforeCardPlayed`, `AfterCardPlayed`/Late, `BeforeCardAutoPlayed`, `AfterCardDrawn`/Early, `AfterCardDiscarded`, `AfterCardExhausted`, `AfterCardRetained`, `AfterCardChangedPiles`/Late, `AfterCardEnteredCombat`, `AfterCardGeneratedForCombat`, `BeforeCardRemoved`

**Damage/Block**: `BeforeAttack`, `AfterAttack`, `BeforeDamageReceived`, `AfterDamageReceived`/Late, `AfterDamageGiven`, `BeforeBlockGained`, `AfterBlockGained`, `AfterBlockBroken`, `AfterBlockCleared`

**Creatures**: `AfterCreatureAddedToCombat`, `AfterCurrentHpChanged`, `BeforeDeath`, `AfterDeath`, `AfterDiedToDoom`

**Powers**: `BeforePowerAmountChanged`, `AfterPowerAmountChanged`

**Resources**: `AfterEnergyReset`/Late, `AfterEnergySpent`, `AfterGoldGained`, `AfterStarsGained`, `AfterStarsSpent`, `AfterForge`

**Cards/Hand**: `BeforeHandDraw`/Late, `AfterHandEmptied`, `AfterShuffle`, `BeforeFlush`/Late

**Orbs**: `AfterOrbChanneled`, `AfterOrbEvoked`

**Potions**: `AfterPotionDiscarded`, `AfterPotionProcured`, `BeforePotionUsed`, `AfterPotionUsed`

**Map/Run**: `AfterActEntered`, `BeforeRoomEntered`, `AfterRoomEntered`, `AfterMapGenerated`, `AfterItemPurchased`, `BeforeRewardsOffered`, `AfterRewardTaken`, `AfterRestSiteHeal`, `AfterRestSiteSmith`

**Modifiers**: `AfterModifyingBlockAmount`, `AfterModifyingCardPlayCount`, `AfterModifyingCardRewardOptions`, `AfterModifyingDamageAmount`, `AfterModifyingHandDraw`, `AfterModifyingOrbPassiveTriggerCount`, `AfterModifyingPowerAmountGiven`/Received, `AfterModifyingRewards`, `AfterModifyingHpLostBeforeOsty`, `AfterModifyingHpLostAfterOsty`

**Prevention**: `AfterPreventingBlockClear`, `AfterPreventingDeath`, `AfterPreventingDraw`

**Other**: `AfterSummon`, `AfterOstyRevived`

### Modding Relevance

While we cannot directly add hook listeners through this system (they require being registered `AbstractModel` instances in the game state), we can:
1. **Harmony-patch the `Hook` methods** to intercept any game event
2. **Harmony-patch `AbstractModel` virtual methods** to add behavior to existing game objects
3. Use the hooks as a reference for what events the game fires and when

### ModifyDamageHookType

Flags enum: `None=0`, `Additive=2`, `Multiplicative=4`, `All=6`

## Mod API Summary

The game provides these extension points for mods:
1. **PCK + DLL loading** — drop files in `mods/` directory
2. **`[ModInitializer]` attribute** — custom initialization entry point
3. **Auto Harmony patching** — fallback if no initializer found
4. **`ModHelper.AddModelToPool()`** — add custom cards/relics/etc. to game pools
5. **Custom console commands** — subclass `AbstractConsoleCmd` in mod assembly
6. **Modded localization tables** — place in `res://<pck_name>/localization/<lang>/<file>`
7. **`ModManager.OnMetricsUpload`** — hook into run metrics

## Debug Features

- **`STS2_DEV_SKIP`** env var: enables `DebugSettings.DevSkip`
- **Debug hotkeys**: hide/show individual UI elements (combat UI, hand, HP bars, intents, etc.), speed controls, unlock characters
- **`shouldAllowDebugCommands`**: flag in `DevConsole` constructor controls whether debug-only commands are available
- **`FastModeType.Instant`**: skip all animations

## Progress log

### 2026-03-16: First mod build + PCK format debugging

**DLL loading: WORKS.** The game finds our PCK in `Contents/MacOS/mods/`, loads `AutoSpire.dll` via `AssemblyLoadContext`, and the assembly loads without errors. The `[ModInitializer("Initialize")]` attribute is properly detected.

**PCK manifest loading: NOT WORKING YET.** `ProjectSettings.LoadResourcePack()` returns true (no error), but `ResourceLoader.Exists("res://mod_manifest.json")` returns false. Our hand-rolled PCK writer has a format issue.

#### What we tried:
- **v2 PCK, absolute offsets (files_base=0)**: DLL loads, PCK loads, but manifest not found
- **v3 PCK (matching game's format)**: Crashes the engine with `Unreferenced static string` errors — do NOT use v3
- **v2 PCK, relative offsets (files_base=data_offset, file offset=0)**: Deployed, not yet tested

#### PCK format notes (Godot 4 pack v2):
- Magic: `GDPC`, version: `2`, engine: `4.5.1`
- `files_base_offset` field at header offset 0x18 (int64): when loading, Godot adds this to each file's offset
- Per-file entry has: path_len(4) + path(padded) + offset(8) + size(8) + md5(16) + flags(4)
- The flags(4) per-file field is v2-only — v1 doesn't have it

#### Next steps:
- [ ] Test the relative-offset PCK (files_base=164, file offset=0)
- [ ] If still failing: install Godot editor to create PCK properly, or find a working community PCK tool
- [ ] Alternative: skip PCK entirely — Harmony-patch `ModManager.TryLoadModFromPck` to bypass manifest check

#### Mod architecture (ready once PCK loads):
- HTTP server on `localhost:31452` (background thread)
- `GET /ping` — health check
- `GET /state` — full game state JSON (run + combat + player)
- `GET /combat` — combat-specific state
- `POST /act` — send commands (play_card, end_turn, use_potion)
- Uses `RunManager.Instance.DebugOnlyGetState()` and `CombatManager.Instance.DebugOnlyGetState()` for state
- Uses `CardCmd.AutoPlay()`, `PlayerCmd.EndTurn()`, `PotionModel.EnqueueManualUse()` for commands

### 2026-09-15: Game updated since last session — mod loading rewritten, working again

The game patched since the 2026-03-16 session. Two breaking changes found by re-decompiling `sts2.dll` (see `decompiled/`, gitignored, regenerate with the ilspycmd command below):

**1. Mod discovery no longer uses PCK scanning at all.** `ModManager.Initialize()` now scans `mods/` for `*.json` manifest files directly (not `*.pck`). The new manifest schema uses `id` (not `pck_name`), and adds explicit `has_pck` / `has_dll` booleans — so a DLL-only mod with `has_pck: false` needs **no PCK file whatsoever**. This makes the whole `ModBootstrap`/Harmony-patch-the-loader workaround (and the Godot PCK-export step in `build.sh`) unnecessary. Deleted both. Current layout: `mods/AutoSpire/manifest.json` + `mods/AutoSpire/AutoSpire.dll`, loaded via the normal `[ModInitializer]` path.

**2. `CombatManager.IsPlayPhase` was removed.** Turn phase is now tracked per-player via `player.PlayerCombatState.Phase` (`PlayerTurnPhase` enum: `None, Start, AutoPrePlay, Play, AutoPostPlay, End`), presumably for multiplayer support. Fixed by replacing all `CombatManager.Instance.IsPlayPhase` checks with a local `IsPlayPhase(Player? player) => player?.PlayerCombatState?.Phase == PlayerTurnPhase.Play` helper.

**3. New gotcha: `DevConsole`'s constructor throws if called too early.** It calls `ReflectionHelper.GetSubtypesInMods<T>()`, which throws `InvalidOperationException` if `ModManager` hasn't finished its own `Initialize()` yet. Our mod's `[ModInitializer]`-attributed `Initialize()` runs *synchronously from inside* `ModManager.Initialize()`, so constructing `DevConsole` there fails silently (caught, logged, but it aborted the whole init — including starting the HTTP listener). Fixed by constructing `_console` lazily on first `/exec` call instead (still marshaled onto the Godot main thread via `CallDeferred`, since `DevConsole` likely touches the scene tree).

### 2026-09-16: Fast custom simulator (`agent/sim/`) built and validated against the live game

Ported Ironclad's starter deck (Strike/Defend/Bash), VulnerablePower, StrengthPower, and Nibbit's move state machine directly from decompiled source (see `agent/sim/engine.py` docstring for the exact file-by-file mapping) into a pure-Python `SimCombat`/`SimClient`. `SimClient` duck-types `AutoSpireClient`'s interface exactly, so `STS2CombatEnv(client=SimClient())` works with **zero changes to `env.py`**. Throughput: ~26,000 steps/sec vs. the live game's ~1-5 steps/sec — a 5,000x+ speedup, and no restart-automation machinery needed since there's no engine to backlog.

Validated with `agent/sim/validate.py`: same scripted policy run against both backends. Nibbit's starting HP and hand-shuffle order are randomized in both with no shared seed control via the mod, so this doesn't diff exact HP numbers — it diffs the mechanics. All matched exactly: Strike -6, Defend +5 block, Bash -8 (+2 Vulnerable applied after, not before, matching `Bash.cs`'s command order), BUTT_MOVE -12, SLICE_MOVE -6 with Nibbit gaining +5 block, Hiss granting Nibbit +2 Strength (confirmed: a later BUTT_MOVE dealt 14, not 12, after a Hiss). Move cycle order (BUTT→SLICE→HISS→repeat) matched in both.

One real timing quirk found, not a mechanics bug: in the live trace, Bash's damage showed up one `/combat` poll *later* than in the sim (energy dropped immediately, but `enemy.hp` lagged by one log entry). Bash's `OnPlay` does a `DamageCmd.Attack` *and* a separate deferred `PowerCmd.Apply<VulnerablePower>` (see `Bash.cs`); Strike only does the former. `env.py`'s post-action poll loop (`step()`) exits as soon as `isPlayPhase` is true again — which it already was, since playing a card doesn't change phase — so it can return before a multi-part card's second effect has fully resolved. Net effect: reward attribution for a card like Bash can occasionally land one step later than the action that caused it, not lost — `prev_enemy_hp`/`enemy_hp` are read fresh each `step()`, so a delayed HP change is still captured, just attributed to whichever action comes next. Not worth fixing for this scope (starter deck only has one multi-effect card), but worth knowing if combat rotation expands to cards with more deferred sub-effects.

All four HTTP endpoints (`/ping`, `/state`, `/combat`, `/exec`) verified working end-to-end against a live run: state reads (deck/hand/enemy intent with real damage numbers), `exec play <idx> <targetId>` (energy spent, damage dealt), `exec end` (enemy turn resolves, HP changes correctly), and `exec instant` (toggles `FastModeType.Instant`, the animation-skip mode — this is our SuperFastMode-equivalent for training throughput).

Redecompile command (needed dotnet runtime 8.0 installed alongside the 9.0 SDK, since `ilspycmd` 9.1.0 targets net8.0):
```bash
.dotnet-tools/ilspycmd "$HOME/Library/Application Support/Steam/steamapps/common/Slay the Spire 2/SlayTheSpire2.app/Contents/Resources/data_sts2_macos_arm64/sts2.dll" -p -o ./decompiled/
```

### 2026-10-09: State reads moved to the main thread (fixes a wedged combat turn loop)

During a live eval, a fight froze mid-combat (`inCombat=true`, `isPlayPhase=false`, permanently). `godot.log` showed SmartFormat errors on the main thread — `InvalidOperationException: Collection was modified` in `SmartFormatter.Format`, then `ArgumentOutOfRangeException` in `SmartFormat.Core.Parsing.Selector.get_Operator` from `CardPileCmd.Draw` → `NCard.UpdateVisuals` — which faulted `CombatManager.SetupPlayerTurn` so the player turn never started. Cause: `/state` and `/combat` ran on the HttpListener's thread-pool thread, and `SerializeCard` reads `card.Title`, which goes through `LocManager.SmartFormat`; SmartFormat's shared parser state is not thread-safe. Fix: `OnMainThread()` in `AutoSpireMod.cs` marshals both reads via `CallDeferred`, same as all commands. Rule: **nothing in the mod touches game objects off the main thread, reads included.** `env.step()` now also aborts an episode if the turn never comes back to the player within 8s, instead of silently continuing.

Second bug found the same day: `/exec play|end` only *enqueues* the action (via `ActionQueueSynchronizer.RequestEnqueue` on the main thread) and returns, so `env.step()`'s first `/combat` poll often saw the pre-action state with `isPlayPhase=true` and handed the policy a stale observation — it then repeated the action, which the game silently dropped. Symptom: every `exec:` line doubled in `godot.log`, live episodes ~2x longer than sim (23.6 vs 12.5 steps), and two wins misreported as non-wins. Fix: `/combat` now includes `actionsIdle` (`ActionQueueSet.IsEmpty && !ActionExecutor.IsRunning`), and `env.py`'s `_ready()` waits for it. After the fix, live matched sim: 20/20 wins, 12.9 steps/ep, 196 play commands = 196 cards played, 62 end-turns = 62 enemy moves, 0 errors.

### 2026-10-09: Sim extended to all Act 1 weak encounters

`agent/sim/engine.py` now models NIBBITS_WEAK, SLIMES_WEAK, SHRINKER_BEETLE_WEAK and FUZZY_WURM_CRAWLER_WEAK (all seven monsters, ascension 0), with monsters as data (`MONSTERS`) and move selection ported from `RandomBranchState.GetStateWeight` (CannotRepeat / CanRepeatXTimes). New mechanics: multiple enemies, Shrink (player attacks ×0.7), the Slimed status card (1 energy, draw 1, Exhaust). Live-game facts learned while validating:
- **Dead enemies are removed from `/combat`'s `enemies` list** (combatIds of the survivors stay stable) — the sim matches this so observation slots line up.
- **Power `id`s are not the bare names** — match powers by `name` (`VulnerablePower`, `StrengthPower`, `ShrinkPower`).
- **Damage rounding**: modifiers multiply as decimals (`Hook.ModifyDamage`), HP loss is truncated (`Creature.LoseHpInternal`) — equivalent to flooring before block for integer block.
- **Enemy turns with a Slimed card preview can take >8s** with the window backgrounded — `env.step()` now waits up to 20s.

`agent/sim/validate.py` is now a one-step check: load each live "before" state into the sim, apply the same action, diff against the live "after" (everything except post-draw hand contents; random enemy moves checked for legality). Result: 127 steps over 12 live fights (3 per encounter, all 4 slime variants seen), 0 mismatches. `python -m sim.test_engine` covers the rules that are easy to get subtly wrong (rounding, repeat limits, Slimed).

Initially enemy-targeted cards always hit the first living enemy (the mod's auto-target), so the agent couldn't focus a specific slime — fixed by target selection, below.

Training switched to sb3-contrib `MaskablePPO` with `env.action_masks()` (playable hand cards + end turn): the unmasked policy won 19/20 live fights, and the miss was a SLIMES_WEAK fight where it chose the same unplayable card 58 times until truncation. The masked model (`ppo_sts2_sim_weak_final`, 500k sim steps over all four weak encounters) went 100% in sim on each encounter (1,000 episodes each) and **20/20 live** (mean 12.1 steps, 0 invalid actions, 0 errors in `godot.log`). The direct binary launch in `full_restart` needs the Steam client running — otherwise Steamworks init fails with "Could not determine Steam client install directory" and the game shows an error popup instead of the menu.

### 2026-10-09: Target selection

The mod's `play <idx> <targetId>` already took an optional target; the env now uses it. Action space is `Discrete(MAX_HAND * MAX_ENEMIES + 1)` = 31: card `a // 3` at enemy slot `a % 3`, where the slot indexes the living-enemy list (stable within a step, since dead enemies are dropped) and is sent as that enemy's `combatId`. `action_masks()` opens every living slot for `AnyEnemy` cards and only slot 0 for the rest, so there are no duplicate actions. Enemy features gained absolute HP and Vulnerable (7 per enemy), since "which one dies first" is not visible from the HP fraction alone. `sim.validate` now plays random targets: 41 live slime steps hitting combatIds 1/2/3, 0 mismatches. Retrained 1M sim steps: 100% sim win rate on every weak encounter, **20/20 live** (mean 10.0 steps vs 12.1 untargeted, 0 invalid, 0 errors). In SLIMES_WEAK it learned to ignore the medium slime and kill both smalls first, usually the Twig Slime S (attacks every turn) — the old auto-target hit the medium second.

### 2026-10-09: Sim extended to Act 1 normal encounters

Added NIBBITS_NORMAL, SLIMES_NORMAL (4 slimes, so `MAX_ENEMIES` = 4), OVERGROWTH_CRAWLERS, MAWLER_NORMAL, FLYCONID_NORMAL and RUBY_RAIDERS_NORMAL (3 distinct of 5 raiders) — 10 Act 1 encounters total (the other 6 normals were added 2026-10-15, below); `--encounters weak|normal|act1` selects groups. Game rules learned from source and confirmed live:
- **Shrink is removed when its applier dies** (`ShrinkPower.AfterDeath`) — killing the Shrinker Beetle first in OVERGROWTH_CRAWLERS restores full attack damage.
- **A debuff newly applied to the player skips its next tick** (`PowerCmd.Apply` sets `SkipNextDurationTick` for player-side debuffs; stacking onto an existing one doesn't). Vulnerable and Frail both tick at the end of the *enemy* turn, so a fresh Vulnerable 3 lasts 3 full player turns.
- **`AddBranch(state, int, MoveRepeatType)` takes a cooldown, not a weight** (Flyconid's 3 and 2), and `UseOnlyOnce` zeroes a move once it's in the log (Mawler's Roar).
- **When every branch weight is 0, `GetNextState` returns the first branch** (`NextFloat(0)` = 0 satisfies `num <= 0` immediately). Flyconid hits this after Vulnerable → Frail → Smash.
- Nibbit's opener depends on its slot: alone → BUTT, NibbitsNormal front → SLICE, back → HISS.
- Live intent damage includes the player's Vulnerable (×1.5 per hit, floored).

The observation gained player Shrink/Vulnerable/Frail. `sim.validate` now also checks player debuffs and intent damage (when sim and live picked the same move): 356 live steps over all 10 encounters, 0 mismatches.

**Bug found: deaths were scored as wins** (in `env.py` since the first version). Once combat ends `/combat` returns only `{"inCombat": false}`, and the env decided the outcome from the last in-combat snapshot — which predates the killing blow, so the player always still had HP. Deaths got +5 instead of −5, in training and in sim evals (live evals were unaffected in practice: they were cross-checked against `godot.log`'s "has won against" lines). Fix: on termination the env reads the player's final HP from `/state`, which still carries the player after combat (confirmed live: HP 0, `won=False`). Re-scored, the model trained under the bug was really 91.6% on OVERGROWTH_CRAWLERS and 99.8% on RUBY_RAIDERS_NORMAL, not 100%.

Act 1 model (`ppo_sts2_sim_act1_final`, 3M sim steps over all 10 encounters), sim, 500 fights each — win rate / HP lost per fight (of 80):

| Encounter | Win | HP lost | | Encounter | Win | HP lost |
|---|---|---|---|---|---|---|
| NIBBITS_WEAK | 100% | 12.3 | | SLIMES_NORMAL | 100% | 44.1 |
| SLIMES_WEAK | 100% | 12.1 | | OVERGROWTH_CRAWLERS | 94.6% | 69.0 |
| SHRINKER_BEETLE_WEAK | 100% | 8.0 | | MAWLER_NORMAL | 100% | 27.2 |
| FUZZY_WURM_CRAWLER_WEAK | 100% | 7.4 | | FLYCONID_NORMAL | 100% | 32.7 |
| NIBBITS_NORMAL | 100% | 34.3 | | RUBY_RAIDERS_NORMAL | 100% | 46.6 |

Win rate is saturated except OVERGROWTH_CRAWLERS; HP lost is the number to push down, since in a real run HP carries between fights (`evaluate.py` now reports it).

Live, 24 fights over the 6 normal encounters (2–8 of each, sampled): **24/24 wins**, mean 34.2 HP lost (the sim predicts ~38 for that mix), 19.8 steps/fight, 0 invalid actions, 0 errors in `godot.log`.

### 2026-10-14: Closing the OVERGROWTH_CRAWLERS gap (v2 model)

The v1 model always killed the Fuzzy Wurm Crawler first and won 94.6% of OVERGROWTH_CRAWLERS fights at ~69 HP lost; all failures were real deaths (none hit `MAX_STEPS`). A scripted greedy policy did far worse either way (Beetle-first 56%, Wurm-first 15%), so the agent wasn't missing an obvious line — but its observation was missing what this fight turns on: the Wurm's stacking Strength is only visible through attack intents (invisible while it Inhales), monster identity (who applies Shrink) could only be guessed from HP, and there was nothing about the draw pile. Added: enemy Strength, a monster-identity one-hot over the sim's `MONSTERS`, per-card draw/discard pile counts, and the round number (`OBS_DIM` 164). `train.py --n-envs 8` runs parallel sim envs (`SubprocVecEnv`, ~5.5k steps/s); trained 10M steps.

v2 (`ppo_sts2_sim_act1_v2_final`), sim, 1,000 fights each — win rate / HP lost (v1 HP lost in parentheses):

| Encounter | Win | HP lost | | Encounter | Win | HP lost |
|---|---|---|---|---|---|---|
| NIBBITS_WEAK | 100% | 11.8 (12.3) | | SLIMES_NORMAL | 100% | **27.3** (44.1) |
| SLIMES_WEAK | 100% | 10.8 (12.1) | | OVERGROWTH_CRAWLERS | **100%** | **39.0** (69.0) |
| SHRINKER_BEETLE_WEAK | 100% | 6.9 (8.0) | | MAWLER_NORMAL | 100% | 26.5 (27.2) |
| FUZZY_WURM_CRAWLER_WEAK | 100% | 7.5 (7.4) | | FLYCONID_NORMAL | 100% | 33.5 (32.7) |
| NIBBITS_NORMAL | 100% | 39.9 (34.3) | | RUBY_RAIDERS_NORMAL | 100% | 43.0 (46.6) |

It flipped strategy: it now kills the Shrinker Beetle first in every OVERGROWTH_CRAWLERS fight (500/500), removing Shrink, instead of racing the Wurm. NIBBITS_NORMAL got slightly worse (34.3 → 39.9). Live: **10/10 OVERGROWTH_CRAWLERS** (mean 32.9 HP lost vs v1's ~69 in sim) and **20/20 over all 10 Act 1 encounters** (21.6 HP lost, 0 invalid actions); every win confirmed in `godot.log`, 0 errors.

### 2026-10-15: Sim covers all 16 Act 1 weak + normal encounters

Added INKLETS_NORMAL, CUBEX_CONSTRUCT_NORMAL, VINE_SHAMBLER_NORMAL, FOGMOG_NORMAL, SNAPPING_JAXFRUIT_NORMAL and SLITHERING_STRANGLER_NORMAL. Still not modeled: elites and bosses. Game rules learned from source and confirmed live:
- **Slippery** (Inklets, 1 stack): the next HP loss of ≥1 after block is capped at 1, then the stack is spent (`ModifyHpLostAfterOsty` + `AfterDamageReceived`).
- **Artifact** (Cubex, 1): negates the next debuff applied to it — Bash's Vulnerable — and spends a charge. Cubex also starts with 13 block (`AfterAddedToRoom`), which clears at the start of its first turn.
- **Tangled** (Vine Shambler): Attack cards cost +amount; removed at the end of the player's next turn. `/combat`'s card `cost` already includes it (`EnergyCost.GetWithModifiers`).
- **Constrict** (Slithering Strangler, +3 per use, stacks): damage at the end of the *player's* turn. It's `ValueProp.Unpowered`, not `Unblockable`, so block absorbs it and Vulnerable doesn't apply. Removed when the Strangler dies.
- **Summons and illusions** (Fogmog): `ILLUSION_MOVE` adds an Eye With Teeth. Creatures are ordered by encounter slot and `FogmogNormal.Slots` = `["illusion", "fogmog"]`, so the Eye goes **in front** of Fogmog in `/combat` and acts first. `ExecuteEnemyTurn` iterates a snapshot, so a summon first acts the turn after. The Eye has IllusionPower + MinionPower: when killed it **stays in `/combat`'s enemy list with `isAlive=false`** (the one exception to "dead enemies are removed"), loses its debuffs, and on its next turn performs `REVIVE_MOVE` (heal to full) then resumes `DISTRACT_MOVE` (3 Dazed into the discard pile). Combat ends when no *primary* enemy is alive (`CombatManager.IsEnding`), so killing Fogmog wins with the Eye alive.
- **Dazed**: Unplayable (cost −1), Ethereal (exhausted if still in hand at end of turn).
- Weighted branches exist: Fogmog's `SWIPE_RANDOM` 0.4 / `HEADBUTT` 0.6. `CanRepeatForever` (Strangler) never zeroes a weight. Inklet builds an `INIT_RAND` it never uses: the opener is JAB, or WHIRLWIND for the middle Inklet.

Env: action slots and observations now index *living* enemies only (`env._living()`), since a dead illusion can't be targeted. The observation gained player Tangled/Constrict and enemy Artifact/Slippery. `sim.validate` now pairs enemies by list position (summons shift ids) and checks Dazed counts, attack costs (when hands match), Tangled/Constrict/Artifact/Slippery and the enemy list itself. Result: 173 + 160 + the Inklets/Cubex/Vine runs, 0 mismatches. The Eye revived 12 times in those fights (`godot.log`: "EYE_WITH_TEETH performing move REVIVE_MOVE").

v3 (`ppo_sts2_sim_act1_v3_final`, 15M steps over all 16, 64×64 net): 100% in sim on all 6 new encounters (HP lost 24–39) and **18/18 live** on them (24.3 HP lost, 0 errors). But it regressed on two old ones vs v2 — OVERGROWTH_CRAWLERS 99.1% / 63.9 HP lost (back to killing the Wurm first) and SLIMES_NORMAL 42.8 HP lost — so v4 retrains with a 256×256 net (`train.py --net 256 256`).

v4 (`ppo_sts2_sim_act1_v4_final`, 20M steps, 256×256): the bigger net fixed the regressions — capacity, not the 16-encounter mix, was the problem (the 11.7M checkpoint already had them fixed). Sim, 1,000 fights each — all **100%**, HP lost per fight:

| Encounter | HP lost | | Encounter | HP lost |
|---|---|---|---|---|
| NIBBITS_WEAK | 6.3 | | RUBY_RAIDERS_NORMAL | 36.6 |
| SLIMES_WEAK | 8.2 | | INKLETS_NORMAL | 20.9 |
| SHRINKER_BEETLE_WEAK | 7.6 | | CUBEX_CONSTRUCT_NORMAL | 37.7 |
| FUZZY_WURM_CRAWLER_WEAK | 7.0 | | VINE_SHAMBLER_NORMAL | 33.4 |
| NIBBITS_NORMAL | 31.4 | | FOGMOG_NORMAL | 23.7 |
| SLIMES_NORMAL | 22.8 | | SNAPPING_JAXFRUIT_NORMAL | 34.8 |
| OVERGROWTH_CRAWLERS | 38.3 | | SLITHERING_STRANGLER_NORMAL | 29.9 |
| MAWLER_NORMAL | 25.0 | | FLYCONID_NORMAL | 28.2 |

Live, 32 fights sampled across all 16 (13 encounters came up): **32/32 wins**, 16.8 HP lost, 0 invalid actions, 0 errors in `godot.log`. Training took ~5h wall-clock on battery with a sleep in the middle; the 256×256 update step (main process) is the bottleneck, not the sim workers.

### 2026-10-16: Decks beyond the starter cards (Ironclad Commons)

The sim now models 18 of the 20 Ironclad Commons (`sim/cards.py`): Anger, Blood Wall, Bloodletting, Body Slam, Breakthrough, Cinder, Havoc, Iron Wave, Molten Fist, Perfected Strike, Pommel Strike, Setup Strike, Shrug It Off, Sword Boomerang, Thunderclap, Tremble, True Grit, Twin Strike. Unupgraded only. **Armaments and Headbutt are left out**: they open a card-choice prompt (`CardSelectCmd`) that the mod has no command to answer.
- **Deck control, live**: the dev console's `card <ID> Deck` and `remove_card <ID> Deck` (via `/exec` passthrough) edit the run's deck between fights. Edits persist for the rest of the run, so `AutoSpireClient.set_deck()` diffs against `/state`'s `player.deck` and the env sets the deck every episode. `SimClient.set_deck()` mirrors it.
- **`env.random_deck`**: the starter deck minus 0–3 Strikes/Defends (never Bash), plus 0–8 random Commons. Use `--random-decks` on train/evaluate. The observation gained a card-identity one-hot per hand slot and player Strength. `MAX_STEPS` went from 60 to 100.
- **Mod bug found and fixed**: `ExecPlay` auto-targeted any card whose `TargetType` string contained "Enemy". That included `RandomEnemy` (Sword Boomerang), and **the game silently drops a RandomEnemy card played with a target**: `/exec` returned ok, but nothing happened and there was no "playing card" line in `godot.log`. `AllEnemies` escaped by luck, since "Enemies" doesn't contain "Enemy". Now only `AnyEnemy` is auto-targeted.
- Rules confirmed live:
  - **Havoc's "Exhaust" is only a hover tip.** Havoc itself is discarded, and the card it autoplays (the *top* of the draw pile) is exhausted, unplayable ones included. `/combat` lists `drawPile` **top-first**, while the sim draws from the end, so `sim.validate.load()` reverses it.
  - Setup Strike's +2 is `TemporaryStrengthPower`, which shows as `StrengthPower` + `SetupStrikePower` and is removed at the end of the player's turn.
  - Perfected Strike counts Strike-tagged cards in every pile plus itself.
  - Breakthrough / Blood Wall / Bloodletting HP loss is unblockable.
  - Cinder / True Grit (unupgraded) exhaust a random hand card.
- `sim.validate` now uses random decks and random playable cards (or `--deck a,b,c`), and skips only the comparisons a random pick changes. Result: 327 steps over all 16 encounters + 46 steps with a forced deck of the rarely drawn cards, 0 mismatches. Plus a Havoc/Dazed check, 4/4 exact pile matches.

v5 (`ppo_sts2_sim_act1_decks_v5_final`, 30M steps with `--random-decks`, 256×256, ~2h on AC power), sim, 500 random-deck fights per encounter: 100% on 15/16 and 99.6% on OVERGROWTH_CRAWLERS; HP lost 2.8–25.0 per fight (weak 3–6, normals 14–25). On the plain starter deck across all 16: 100%, 23.2 HP lost (v4's per-encounter average was ~24.5), so learning the new cards didn't cost starter-deck play. Live, random decks over all 16 (13 came up), 27.9M-step checkpoint: **20/20 wins**, 6.6 HP lost, 0 invalid actions, 0 errors. It played 18 different cards: Perfected Strike 14×, Anger 14×, Cinder 9×, Molten Fist 7×, down to Havoc and Bloodletting once each.

### 2026-10-16: Card reward picks (`agent/picker.py`)

- **Reading rewards, live**: `/state` now has `rewards` whenever the post-combat `NRewardsScreen` is the top overlay (`NOverlayStack.Instance.Peek()`). Its `RewardsSet` is the private `_rewardsSet`, read by reflection. Each reward gives its type (`GoldReward`, `PotionReward`, `CardReward`, …), and card rewards also list the offered cards (same shape as hand cards). The agent never clicks the screen: it adds its pick with `card <ID> Deck`, and the next `fight` clears the screen.
- **Reward generation** (`CardFactory.CreateForReward`, `CardRarityOdds`): 3 distinct cards from the character pool. Each card rolls Rare 3% + a pity offset (starts −5%, +1% per non-Rare roll, cap 40%, reset on a Rare), Uncommon 37%, else Common. Act 1 offers are never upgraded: the upgrade roll's base chance is 0 and only grows with the act index. So most real offers include an Uncommon the sim can't play yet.
- **The picker**: for each option (skip, or each offered card the sim models), simulate N full-HP fights over the normal encounters with the v5 combat policy, using the same seeds for every option. Take the option with the least mean HP lost (a death counts as all HP lost). Unmodeled offers are never picked. This needs no training; it's a one-step lookahead using the combat policy as the evaluator.
- **Mini-run harness**: 3 weak + 4 normal fights, HP carries over. Burning Blood (`BurningBlood.cs`, the starter relic) heals 6 after each win, and a rest site partway heals 30% of max HP (`HealRestSiteOption`, 24). Offers use the game's odds. Uncommon/Rare slots are placeholders and Armaments/Headbutt can't be played, so roughly half the slots are unpickable, like live. 200 runs per strategy, N = 24:

| Strategy | Survive all 7 | Fights won | HP at end | Cards added |
|---|---|---|---|---|
| Always skip | 53.5% | 6.44 | 10.9 | 0 |
| Random pick | 86.5% | 6.83 | 34.1 | 3.8 |
| **Simulated pick** | **98.5%** | 6.99 | **51.6** | 5.1 |

  Its favourite is Anger (0-cost damage), then a spread of efficient attacks and Shrug It Off. It rarely takes Blood Wall, Havoc or Body Slam.
- **Live** (originally `python picker.py --live`, now `python run.py --live`): the same mini-run in the real game, picking from real reward screens. 7/7 fights won, ended at 72/80 HP, took Setup Strike ×2, Anger, Iron Wave, True Grit, and skipped twice. In the game, Burning Blood's heal lands *after* the reward screen appears (even at the start of the next fight), so the live log's per-fight HP-lost numbers are off by its 6.

### 2026-10-16: Act 1 elites and bosses

The sim covers all 22 Act 1 encounters: 4 weak, 12 normal, 3 elites and 3 bosses. Groups: `--encounters elite`, `boss`, `hallway` (weak+normal), `act1` (all); comma lists mix groups and ids. `MAX_STEPS` is now 250. Rules from source, all confirmed live:
- **Bygone Effigy** (127 HP): SLEEP → WAKE (+10 Strength) → SLASHES 13 forever. Its `SLEEP_MOVE_2` is in the state list, but nothing leads to it. **SlowPower**: it takes ×(1 + 0.1·n) damage, where n = cards the player has already played this turn. The counter resets at the start of the enemy turn.
- **Byrdonis** (81–84): SWOOP 17 ↔ PECK 3×3. **TerritorialPower** 1: gains 1 Strength at the end of each of its turns.
- **Phrog Parasite** (61–64): INFECT (3 Infection) ↔ LASH 4×4. **InfestedPower**: on death it spawns 4 **Wrigglers** (17–21 HP) in slots `wriggler1..4`, stunned (`SPAWNED_MOVE`). It also returns `ShouldStopCombatFromEnding`, so the fight continues. Each Wriggler's opener depends on its slot: 1/3 NASTY_BITE 6, 2/4 WRIGGLE (+2 Strength, 1 Infection). Then they alternate.
- **Infection**: Unplayable status. If it's in hand at end of turn it deals 3 damage (Unpowered, so block applies and Vulnerable doesn't).
- **Vantom** (173): Slippery **8**. INK_BLOT 7 → INKY_LANCE 6×2 → DISMEMBER 26 + 3 **Wounds** (Unplayable, no effect) → PREPARE +2 Strength.
- **Ceremonial Beast** (252):
  - Phase 1: STAMP (Plow 150 on itself) → PLOW 18 +2 Strength, repeated.
  - **PlowPower**: once unblocked damage leaves it at **≤ its Plow amount**, it loses all Strength, Plow is removed, and it's stunned.
  - `CreatureCmd.Stun` → `Creature.StunInternal` builds a fresh move state with id **`STUNNED`** (the Beast's own `STUN_MOVE` is never used). Its follow-up is the given `nextMoveId`, here BEAST_CRY.
  - Phase 2: BEAST_CRY (**Ringing**) → STOMP 15 → CRUSH 17 +3 Strength.
- **RingingPower**: on the player's next turn every card is afflicted, and `ShouldPlay` refuses a second card play. `/combat` gains `cardsPlayedThisTurn` (from `CombatManager.History.CardPlaysStarted`), which feeds both Ringing and Slow.
- **The Kin**: KIN_PRIEST (190): ORB_OF_FRAILTY 8 + Frail 1 → ORB_OF_WEAKNESS 8 + **Weak** 1 → BEAM 3×3 → RITUAL +2 Strength. Two KIN_FOLLOWERs (58–59, **MinionPower**, so not needed to win): QUICK_SLASH 5 → BOOMERANG 2×2 → POWER_DANCE +2 Strength. The slot-1 follower opens with the dance.
- **Weak** on the player: their attacks deal ×0.75. It ticks like Vulnerable/Frail.

Live validation (random decks, random play): 196 steps over Phrog/Vantom/Beast/Kin and 4 Effigy/Byrdonis fights, 0 mismatches. A forced damage deck reached Beast phase 2 in 3/3 fights: 82 steps, 0 mismatches. The one `godot.log` error in these runs was the game's own `VfxCmd` inside `CreatureCmd.Heal` (a disposed `Marker2D`), probably Burning Blood firing as `fight` swaps the room.

### Open problem: `fight`/`room` debug commands leak resources under repeated use

Built a first Gymnasium env (`agent/`) using `fight NIBBITS_WEAK` (via `/exec`) as the episode-reset mechanism, since `EnterRoomDebug` (which both the `fight` and `room` console commands call) does `ClearScreens()` before entering — meaning it force-dismisses any pending reward/game-over screen and drops straight into a fresh combat, no UI clicking ever required. This part works great and is validated: a random-action agent completed a real win (44 steps) with correct energy/damage/HP bookkeeping the whole way.

**The problem:** the game's CPU usage climbs steadily with each `fight` reset — observed 197% → 654%+ across roughly 50-90 resets — and eventually HTTP requests (even plain `GET /combat` reads with no game-state mutation) start stalling for 5-15+ seconds. A screenshot mid-stall showed overlapping "Player Turn" banners and duplicate card-play animations rendered simultaneously, i.e. an animation/transition backlog, not a true deadlock (the process stays in the `R` running state, not blocked). `/ping` (which doesn't touch game state) kept responding instantly throughout, confirming the HTTP layer itself is fine — the game's main thread specifically falls behind.

The source itself hints at this: `EnterRoomDebug`'s doc comment says "Should only be used in tests or dev commands, never in real flows" — it's a QA/debug shortcut, not built to be called thousands of times per training run. Adding a settle delay after each `/exec` call (`client.py`'s `exec(..., settle=0.15)`, `0.5` after `fight`) did not fix it, only delayed the eventual stall.

**Resolved (2026-09-16): periodic full-process restart, fully automated.**

Went with the "restart the game process every N episodes" workaround rather than root-causing the underlying leak (still unknown — not investigated further). The real engineering work was making the restart itself reliable and fully unattended, since naively doing "pkill + relaunch + click Singleplayer" defeats the purpose of an automated training loop. Three problems had to be solved, in order:

1. **No UI-free way to start a run.** Solved by adding a new `/exec newrun [CHARACTER]` command to the mod (`ExecNewRun`/`StartNewRunAsync` in `AutoSpireMod.cs`), reimplementing the sequence from `NSceneBootstrapper.StartNewRun()` (a dev-editor-only class we can't use directly in a shipped build — it needs a `BootstrapSettings.cs` file that doesn't exist outside the Godot editor project). The sequence: build a `Player` via `Player.CreateForNewRun(character, ...)`, a `RunState` via `RunState.CreateForTest(...)` (a convenience overload with sane defaults — don't need `NSceneBootstrapper`'s more elaborate `IBootstrapSettings` machinery), then `RunManager.Instance.SetUpNewSingleplayer(runState, shouldSave: false)` → `PreloadManager.LoadRunAssets(...)` → `RunManager.Instance.Launch()` → `NGame.Instance.RootSceneContainer.SetCurrentScene(NRun.Create(runState))` → `RunManager.Instance.EnterAct(0)`. This lands on the Act 1 map, `inRun: true`, no main menu interaction required at all. `shouldSave: false` so training runs don't clobber the real save file.

2. **`AssetSets.Act` null on the very first combat after a fresh `newrun`.** `EnterAct(0)`'s `SetActInternal` should already call `PreloadManager.LoadActAssets(State.Act)` (which sets the static `AssetSets.Act`), but the first `fight` command right after a bootstrap-path `newrun` reliably hit a `NullReferenceException` in `PreloadManager.LoadRoomCombatAssets` reading it. Root cause not fully pinned down (didn't dig further once the fix worked) — worked around by calling `PreloadManager.LoadActAssets(runState.Act)` again, explicitly, right after `EnterAct(0)` in `StartNewRunAsync`. Idempotent, cheap, fixed it.

3. **Two race conditions in the Python-side restart orchestration** (`AutoSpireClient.full_restart()` in `agent/client.py`):
   - The mod's HTTP server (and `/state` reporting `phase: "menu"`) comes up well before the game's own boot-time asset preload (`MainMenuEssentials`, `Common`, etc.) actually finishes. Calling `newrun` while that's still in flight races the engine's own `PreloadManager` calls and corrupts startup (`NullReferenceException` in `RunManager.ClearScreens()`, "Encountered error on game startup"). Total time-to-main-menu varies hugely by system load — observed anywhere from ~900ms to 13.5s+ — so a fixed sleep isn't reliable. Fixed by watching `godot.log` for the engine's own `"Time to main menu:"` line instead of guessing a delay.
     - Subtlety: **the log truncates on launch, it does not append** (despite earlier appearances to the contrary from less careful observation). A baseline "marker count" must be captured *after* confirming we're reading the new process's log (i.e. after its `/ping` first responds), not before the kill/relaunch — otherwise the post-relaunch count never exceeds the stale pre-relaunch baseline and the wait spuriously times out forever.
   - The mod's server-side `newrun` handler can legitimately take 5-13+ seconds (asset preloading), longer than the Python client's default 5s HTTP timeout. The client would time out and **retry** while the first attempt was still running server-side, kicking off a second concurrent `StartNewRunAsync` racing the first — this was the actual cause of several of the corrupted-startup crashes, not the asset-loading itself. Fixed by giving `newrun` specifically a long client-side timeout (45s) and `retries=1` (never retry it), and bumping the mod's own internal wait from 20s to 40s for headroom.

With all three fixed, `agent/env.py`'s `STS2CombatEnv(episodes_per_restart=N)` runs indefinitely: every Nth episode reset calls `client.full_restart()` (~30s, fully automated) instead of the lighter in-run `fight`-command reset, and CPU/animation backlog never gets the chance to accumulate. Validated over 6 episodes / 2 restarts with zero manual intervention and zero aborts.
