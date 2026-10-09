using System;
using System.Collections.Generic;
using System.Linq;
using System.Net;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading;
using System.Threading.Tasks;
using Godot;
using MegaCrit.Sts2.Core.Assets;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Logging;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Modding;
using MegaCrit.Sts2.Core.DevConsole;
using MegaCrit.Sts2.Core.GameActions;
using MegaCrit.Sts2.Core.MonsterMoves.Intents;
using MegaCrit.Sts2.Core.Nodes;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Saves;

namespace AutoSpire;

[ModInitializer("Initialize")]
public static class AutoSpireMod
{
    private static HttpListener? _listener;
    private static CancellationTokenSource? _cts;
    private static DevConsole? _console;
    private const int Port = 31452;
    private static bool _initialized;

    public static void Initialize()
    {
        if (_initialized) return;
        _initialized = true;

        try
        {
            Log.Info("[AutoSpire] Initializing HTTP server...");
            // DevConsole's ctor calls ReflectionHelper.GetSubtypesInMods(), which throws if
            // ModManager hasn't finished Initialize() yet — and we're called synchronously
            // from inside that. Create it lazily on first actual use instead (see GetConsole()).
            _cts = new CancellationTokenSource();
            var thread = new Thread(RunServerSync)
            {
                IsBackground = true,
                Name = "AutoSpire-HTTP"
            };
            thread.Start();
            Log.Info($"[AutoSpire] HTTP server started on port {Port}");
        }
        catch (Exception ex)
        {
            Log.Error($"[AutoSpire] Init error: {ex}");
        }
    }

    private static void RunServerSync()
    {
        try
        {
            _listener = new HttpListener();
            _listener.Prefixes.Add($"http://localhost:{Port}/");
            _listener.Start();
            Log.Info($"[AutoSpire] Server listening on http://localhost:{Port}/");

            while (!_cts!.IsCancellationRequested)
            {
                try
                {
                    var context = _listener.GetContext();
                    ThreadPool.QueueUserWorkItem(_ => HandleRequest(context));
                }
                catch (HttpListenerException)
                {
                    break;
                }
            }
        }
        catch (Exception ex)
        {
            Log.Error($"[AutoSpire] Server error: {ex}");
        }
    }

    private static void HandleRequest(HttpListenerContext context)
    {
        try
        {
            var path = context.Request.Url?.AbsolutePath ?? "/";
            var method = context.Request.HttpMethod;

            object? result = (path, method) switch
            {
                ("/state", "GET") => OnMainThread(GetGameState),
                ("/combat", "GET") => OnMainThread(GetCombatState),
                ("/act", "POST") => HandleAction(context),
                ("/exec", "POST") => HandleExec(context),
                ("/ping", "GET") => new { status = "ok", mod = "AutoSpire" },
                _ => null
            };

            if (result == null)
            {
                Respond(context, 404, new { error = "not_found", path });
                return;
            }

            Respond(context, 200, result);
        }
        catch (Exception ex)
        {
            Log.Error($"[AutoSpire] Request error: {ex}");
            try { Respond(context, 500, new { error = ex.Message }); } catch { }
        }
    }

    // State reads touch non-thread-safe game objects (e.g. card.Title runs SmartFormat,
    // whose shared parser state corrupts under concurrent use and kills the combat turn
    // loop), so run them on the Godot main thread like every command already is.
    private static T? OnMainThread<T>(Func<T?> read)
    {
        var done = new ManualResetEventSlim(false);
        T? result = default;
        Exception? error = null;
        Godot.Callable.From(() =>
        {
            try { result = read(); }
            catch (Exception ex) { error = ex; }
            finally { done.Set(); }
        }).CallDeferred();
        if (!done.Wait(TimeSpan.FromSeconds(5)))
            throw new TimeoutException("main thread did not service state read within 5s");
        if (error != null)
            throw error;
        return result;
    }

    private static void Respond(HttpListenerContext context, int status, object body)
    {
        var json = JsonSerializer.SerializeToUtf8Bytes(body, SerializerOptions);
        context.Response.StatusCode = status;
        context.Response.ContentType = "application/json";
        context.Response.OutputStream.Write(json);
        context.Response.Close();
    }

    // --- State Reading ---

    private static object GetGameState()
    {
        var runState = RunManager.Instance.DebugOnlyGetState();
        if (runState == null)
            return new { phase = "menu", inRun = false };

        var player = LocalContext.GetMe(runState);
        var combatMgr = CombatManager.Instance;

        return new
        {
            phase = combatMgr.IsInProgress ? "combat" : "map",
            inRun = true,
            floor = runState.TotalFloor,
            actIndex = runState.CurrentActIndex,
            actFloor = runState.ActFloor,
            roomType = runState.CurrentRoom?.RoomType.ToString(),
            player = player != null ? SerializePlayer(player) : null,
            combat = combatMgr.IsInProgress ? GetCombatState() : null
        };
    }

    private static object? GetCombatState()
    {
        var combatMgr = CombatManager.Instance;
        if (!combatMgr.IsInProgress)
            return new { inCombat = false };

        var state = combatMgr.DebugOnlyGetState();
        if (state == null)
            return new { inCombat = false };

        var player = LocalContext.GetMe(state);

        return new
        {
            inCombat = true,
            isPlayPhase = IsPlayPhase(player),
            // False while a queued play/end-turn is still resolving: /exec only enqueues, so
            // without this an agent can read the pre-action state and repeat its action.
            actionsIdle = RunManager.Instance.ActionQueueSet.IsEmpty && !RunManager.Instance.ActionExecutor.IsRunning,
            round = state.RoundNumber,
            currentSide = state.CurrentSide.ToString(),
            player = player != null ? SerializePlayerCombat(player) : null,
            enemies = state.Enemies.Select(SerializeCreature).ToList()
        };
    }

    // CombatManager.IsPlayPhase was removed upstream; phase is now tracked per-player.
    private static bool IsPlayPhase(Player? player)
    {
        return player?.PlayerCombatState?.Phase == PlayerTurnPhase.Play;
    }

    private static object SerializePlayer(Player player)
    {
        return new
        {
            hp = player.Creature.CurrentHp,
            maxHp = player.Creature.MaxHp,
            block = player.Creature.Block,
            gold = player.Gold,
            character = player.Character?.Id.Entry,
            relics = player.Relics.Select(SerializeRelic).ToList(),
            potions = player.Potions.Select(SerializePotion).ToList(),
            deck = player.Deck.Cards.Select(SerializeCard).ToList()
        };
    }

    private static object SerializePlayerCombat(Player player)
    {
        var pcs = player.PlayerCombatState;
        if (pcs == null)
            return SerializePlayer(player);

        return new
        {
            hp = player.Creature.CurrentHp,
            maxHp = player.Creature.MaxHp,
            block = player.Creature.Block,
            gold = player.Gold,
            energy = pcs.Energy,
            maxEnergy = pcs.MaxEnergy,
            stars = pcs.Stars,
            hand = pcs.Hand.Cards.Select(SerializeCard).ToList(),
            drawPile = pcs.DrawPile.Cards.Select(SerializeCard).ToList(),
            discardPile = pcs.DiscardPile.Cards.Select(SerializeCard).ToList(),
            exhaustPile = pcs.ExhaustPile.Cards.Select(SerializeCard).ToList(),
            powers = player.Creature.Powers.Select(SerializePower).ToList(),
            relics = player.Relics.Select(SerializeRelic).ToList(),
            potions = player.Potions.Select(SerializePotion).ToList(),
            deck = player.Deck.Cards.Select(SerializeCard).ToList()
        };
    }

    private static object SerializeCard(CardModel card)
    {
        return new
        {
            id = card.Id.Entry,
            name = card.GetType().Name,
            title = card.Title?.ToString(),
            type = card.Type.ToString(),
            rarity = card.Rarity.ToString(),
            cost = card.EnergyCost.GetWithModifiers(CostModifiers.All),
            canPlay = card.CanPlay(),
            targetType = card.TargetType.ToString(),
            upgraded = card.IsUpgraded,
            upgradeLevel = card.CurrentUpgradeLevel,
            keywords = card.Keywords.Select(k => k.ToString()).ToList()
        };
    }

    private static object SerializeCreature(Creature creature)
    {
        var result = new Dictionary<string, object?>
        {
            ["combatId"] = creature.CombatId,
            ["name"] = creature.Name,
            ["modelId"] = creature.ModelId.Entry,
            ["hp"] = creature.CurrentHp,
            ["maxHp"] = creature.MaxHp,
            ["block"] = creature.Block,
            ["isAlive"] = creature.IsAlive,
            ["isStunned"] = creature.IsStunned,
            ["powers"] = creature.Powers.Select(SerializePower).ToList()
        };

        if (creature.Monster?.NextMove is { } nextMove)
        {
            var targets = creature.CombatState?.Allies ?? Array.Empty<Creature>();
            result["intent"] = new
            {
                moveId = nextMove.Id,
                intents = nextMove.Intents.Select(i => SerializeIntent(i, targets, creature)).ToList()
            };
        }

        return result;
    }

    private static object SerializeIntent(AbstractIntent intent, IEnumerable<Creature> targets, Creature owner)
    {
        var result = new Dictionary<string, object?>
        {
            ["type"] = intent.IntentType.ToString(),
            ["className"] = intent.GetType().Name
        };

        if (intent is AttackIntent attack)
        {
            try
            {
                result["damage"] = attack.GetSingleDamage(targets, owner);
                result["hits"] = attack.Repeats > 0 ? attack.Repeats : 1;
                result["totalDamage"] = attack.GetTotalDamage(targets, owner);
            }
            catch { /* damage calc may fail outside normal context */ }
        }

        return result;
    }

    private static object SerializePower(PowerModel power)
    {
        return new
        {
            id = power.Id.Entry,
            name = power.GetType().Name,
            type = power.Type.ToString(),
            amount = power.Amount
        };
    }

    private static object SerializeRelic(RelicModel relic)
    {
        return new
        {
            id = relic.Id.Entry,
            name = relic.GetType().Name,
            counter = relic.StackCount
        };
    }

    private static object SerializePotion(PotionModel potion)
    {
        return new
        {
            id = potion.Id.Entry,
            name = potion.GetType().Name,
            targetType = potion.TargetType.ToString(),
            rarity = potion.Rarity.ToString()
        };
    }

    // --- Exec: text command interface ---

    private static object HandleExec(HttpListenerContext context)
    {
        using var reader = new System.IO.StreamReader(context.Request.InputStream);
        var cmd = reader.ReadToEnd().Trim();

        if (string.IsNullOrEmpty(cmd))
            return new { error = "empty_command" };

        Log.Info($"[AutoSpire] exec: {cmd}");

        var parts = cmd.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        var verb = parts[0].ToLowerInvariant();

        try
        {
            return verb switch
            {
                // Shorthand combat commands
                "play" => ExecPlay(parts),
                "end" => ExecEndTurn(),
                "potion" => ExecPotion(parts),
                // Starts a fresh singleplayer run without touching the main menu UI —
                // lets a training loop fully automate "launch game -> in a run" with no
                // human clicking, e.g. after a periodic restart to clear engine resource buildup.
                "newrun" => ExecNewRun(parts),
                // Pass through to game's dev console (kill, godmode, draw, energy, gold, etc.)
                _ => ExecConsole(cmd)
            };
        }
        catch (Exception ex)
        {
            return new { error = ex.Message, command = cmd };
        }
    }

    // play <cardIndex> [targetId]
    private static object ExecPlay(string[] parts)
    {
        if (parts.Length < 2 || !int.TryParse(parts[1], out var cardIndex))
            return new { error = "usage: play <cardIndex> [targetId]" };

        uint? targetId = parts.Length >= 3 && uint.TryParse(parts[2], out var tid) ? tid : null;

        var combatState = CombatManager.Instance.DebugOnlyGetState();
        if (combatState == null) return new { error = "not_in_combat" };

        var player = LocalContext.GetMe(combatState);
        if (player?.PlayerCombatState == null) return new { error = "no_player" };
        if (!IsPlayPhase(player)) return new { error = "not_play_phase" };

        var hand = player.PlayerCombatState.Hand.Cards;
        if (cardIndex < 0 || cardIndex >= hand.Count)
            return new { error = "invalid_card_index", max = hand.Count - 1 };

        var card = hand[cardIndex];
        if (!card.CanPlay())
            return new { error = "card_not_playable", card = card.Id.Entry };

        Creature? target = null;
        if (targetId.HasValue)
        {
            target = combatState.Enemies.FirstOrDefault(e => e.CombatId == targetId.Value)
                  ?? combatState.Allies.FirstOrDefault(e => e.CombatId == targetId.Value);
            if (target == null) return new { error = "invalid_target", targetId };
        }
        else if (card.TargetType.ToString().Contains("Enemy"))
        {
            // Auto-target first hittable enemy if none specified
            target = combatState.HittableEnemies.FirstOrDefault();
        }

        // Use PlayCardAction (same as UI) — this spends energy properly
        // Must enqueue from the main thread since it touches the scene tree
        var action = new PlayCardAction(card, target);
        var cardTitle = card.Title?.ToString();
        var targetName = target?.Name;
        Godot.Callable.From(() => RunManager.Instance.ActionQueueSynchronizer.RequestEnqueue(action))
            .CallDeferred();
        return new { ok = true, played = cardTitle, index = cardIndex, target = targetName };
    }

    private static object ExecEndTurn()
    {
        var combatState = CombatManager.Instance.DebugOnlyGetState();
        if (combatState == null) return new { error = "not_in_combat" };

        var player = LocalContext.GetMe(combatState);
        if (player == null) return new { error = "no_player" };
        if (!IsPlayPhase(player)) return new { error = "not_play_phase" };

        Godot.Callable.From(() => PlayerCmd.EndTurn(player, canBackOut: false))
            .CallDeferred();
        return new { ok = true };
    }

    // potion <index> [targetId]
    private static object ExecPotion(string[] parts)
    {
        if (parts.Length < 2 || !int.TryParse(parts[1], out var potionIndex))
            return new { error = "usage: potion <index> [targetId]" };

        uint? targetId = parts.Length >= 3 && uint.TryParse(parts[2], out var tid) ? tid : null;

        var combatState = CombatManager.Instance.DebugOnlyGetState();
        var player = combatState != null ? LocalContext.GetMe(combatState) : null;
        if (player == null)
        {
            var runState = RunManager.Instance.DebugOnlyGetState();
            if (runState != null) player = LocalContext.GetMe(runState);
        }
        if (player == null) return new { error = "no_player" };

        var potions = player.Potions.ToList();
        if (potionIndex < 0 || potionIndex >= potions.Count)
            return new { error = "invalid_potion_index", max = potions.Count - 1 };

        var potion = potions[potionIndex];
        Creature? target = null;
        if (targetId.HasValue && combatState != null)
        {
            target = combatState.Enemies.FirstOrDefault(e => e.CombatId == targetId.Value);
        }

        Godot.Callable.From(() => potion.EnqueueManualUse(target)).CallDeferred();
        return new { ok = true, used = potion.Id.Entry };
    }

    // newrun [CHARACTER] — mirrors what NSceneBootstrapper.StartNewRun() does in dev builds,
    // reimplemented here since that class needs an editor-only settings file we don't have
    // in a shipped build. Errors (e.g. a run is already active) surface via the "error" field.
    private static object ExecNewRun(string[] parts)
    {
        var characterArg = parts.Length >= 2 ? parts[1].ToUpperInvariant() : "IRONCLAD";
        var done = new ManualResetEventSlim(false);
        Exception? error = null;

        Godot.Callable.From(() =>
        {
            _ = StartNewRunAsync(characterArg, done, ex => error = ex);
        }).CallDeferred();

        if (!done.Wait(TimeSpan.FromSeconds(40)))
            return new { error = "timeout_starting_run" };
        if (error != null)
            return new { error = error.ToString() };
        return new { ok = true, character = characterArg };
    }

    private static async Task StartNewRunAsync(string characterArg, ManualResetEventSlim done, Action<Exception> onError)
    {
        try
        {
            CharacterModel character = characterArg switch
            {
                "IRONCLAD" => ModelDb.Character<MegaCrit.Sts2.Core.Models.Characters.Ironclad>(),
                "SILENT" => ModelDb.Character<MegaCrit.Sts2.Core.Models.Characters.Silent>(),
                "REGENT" => ModelDb.Character<MegaCrit.Sts2.Core.Models.Characters.Regent>(),
                "NECROBINDER" => ModelDb.Character<MegaCrit.Sts2.Core.Models.Characters.Necrobinder>(),
                "DEFECT" => ModelDb.Character<MegaCrit.Sts2.Core.Models.Characters.Defect>(),
                _ => ModelDb.Character<MegaCrit.Sts2.Core.Models.Characters.Ironclad>(),
            };

            var player = Player.CreateForNewRun(character, SaveManager.Instance.GenerateUnlockStateFromProgress(), 1uL);
            var runState = RunState.CreateForTest(
                new List<Player> { player },
                gameMode: GameMode.Standard,
                ascensionLevel: 0);

            // shouldSave: false — this is a training run, not a real save-file playthrough.
            RunManager.Instance.SetUpNewSingleplayer(runState, shouldSave: false);
            await PreloadManager.LoadRunAssets(new List<CharacterModel> { character });
            RunManager.Instance.Launch();

            var game = NGame.Instance ?? throw new InvalidOperationException("NGame.Instance is null");
            game.RootSceneContainer.SetCurrentScene(NRun.Create(runState));
            await RunManager.Instance.EnterAct(0);
            // Belt-and-suspenders: AssetSets.Act (set inside LoadActAssets, which
            // EnterAct's SetActInternal should already call) has been observed null
            // when entering the first combat right after this bootstrap path, causing
            // a NullReferenceException in PreloadManager.LoadRoomCombatAssets. Cheap
            // and idempotent to just ensure it directly.
            await PreloadManager.LoadActAssets(runState.Act);
        }
        catch (Exception ex)
        {
            onError(ex);
        }
        finally
        {
            done.Set();
        }
    }

    // Pass to game's dev console: kill, godmode, draw, energy, gold, damage, etc.
    private static object ExecConsole(string cmd)
    {
        CmdResult result = default;
        Exception? initError = null;
        var done = new ManualResetEventSlim(false);
        Godot.Callable.From(() =>
        {
            try
            {
                // Constructed lazily (and on the main thread) since DevConsole's ctor calls
                // ReflectionHelper.GetSubtypesInMods(), which requires ModManager to have
                // finished initializing — true by the time any /exec call can arrive.
                _console ??= new DevConsole(shouldAllowDebugCommands: true);
                result = _console.ProcessCommand(cmd);
            }
            catch (Exception ex)
            {
                initError = ex;
            }
            finally
            {
                done.Set();
            }
        }).CallDeferred();
        done.Wait(TimeSpan.FromSeconds(5));
        if (initError != null)
            return new { error = initError.Message };
        return new { ok = result.success, message = result.msg };
    }

    // --- Action Handling (legacy JSON API) ---

    private static object HandleAction(HttpListenerContext context)
    {
        using var reader = new System.IO.StreamReader(context.Request.InputStream);
        var body = reader.ReadToEnd();
        var action = JsonSerializer.Deserialize<ActionRequest>(body, SerializerOptions);

        if (action == null)
            return new { error = "invalid_request" };

        return action.Type switch
        {
            "play_card" => PlayCard(action),
            "end_turn" => EndTurn(),
            "use_potion" => UsePotion(action),
            _ => new { error = "unknown_action", type = action.Type }
        };
    }

    private static object PlayCard(ActionRequest action)
    {
        var combatState = CombatManager.Instance.DebugOnlyGetState();
        if (combatState == null)
            return new { error = "not_in_combat" };

        var player = LocalContext.GetMe(combatState);
        if (player?.PlayerCombatState == null)
            return new { error = "no_player" };

        if (!IsPlayPhase(player))
            return new { error = "not_play_phase" };

        var hand = player.PlayerCombatState.Hand.Cards;
        if (action.CardIndex < 0 || action.CardIndex >= hand.Count)
            return new { error = "invalid_card_index", max = hand.Count - 1 };

        var card = hand[action.CardIndex];
        if (!card.CanPlay())
            return new { error = "card_not_playable", cardId = card.Id.Entry };

        Creature? target = null;
        if (action.TargetId.HasValue)
        {
            target = combatState.Enemies
                .FirstOrDefault(e => e.CombatId == action.TargetId.Value);
            if (target == null)
                return new { error = "invalid_target", targetId = action.TargetId };
        }

        var playAction = new PlayCardAction(card, target);
        Godot.Callable.From(() => RunManager.Instance.ActionQueueSynchronizer.RequestEnqueue(playAction))
            .CallDeferred();

        return new { ok = true, played = card.Id.Entry };
    }

    private static object EndTurn()
    {
        var combatState = CombatManager.Instance.DebugOnlyGetState();
        if (combatState == null)
            return new { error = "not_in_combat" };

        var player = LocalContext.GetMe(combatState);
        if (player == null)
            return new { error = "no_player" };

        if (!IsPlayPhase(player))
            return new { error = "not_play_phase" };

        Godot.Callable.From(() => PlayerCmd.EndTurn(player, canBackOut: false))
            .CallDeferred();
        return new { ok = true };
    }

    private static object UsePotion(ActionRequest action)
    {
        var combatState = CombatManager.Instance.DebugOnlyGetState();
        var player = combatState != null ? LocalContext.GetMe(combatState) : null;

        if (player == null)
        {
            var runState = RunManager.Instance.DebugOnlyGetState();
            if (runState != null)
                player = LocalContext.GetMe(runState);
        }

        if (player == null)
            return new { error = "no_player" };

        var potions = player.Potions.ToList();
        if (action.PotionIndex < 0 || action.PotionIndex >= potions.Count)
            return new { error = "invalid_potion_index", max = potions.Count - 1 };

        var potion = potions[action.PotionIndex];

        Creature? target = null;
        if (action.TargetId.HasValue && combatState != null)
        {
            target = combatState.Enemies
                .FirstOrDefault(e => e.CombatId == action.TargetId.Value);
        }

        Godot.Callable.From(() => potion.EnqueueManualUse(target)).CallDeferred();
        return new { ok = true, used = potion.Id.Entry };
    }

    private static readonly JsonSerializerOptions SerializerOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull
    };
}

public class ActionRequest
{
    [JsonPropertyName("type")]
    public string Type { get; set; } = "";

    [JsonPropertyName("cardIndex")]
    public int CardIndex { get; set; }

    [JsonPropertyName("potionIndex")]
    public int PotionIndex { get; set; }

    [JsonPropertyName("targetId")]
    public uint? TargetId { get; set; }
}
