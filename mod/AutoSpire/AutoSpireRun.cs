using MegaCrit.Sts2.Core.Nodes.CommonUi;
using MegaCrit.Sts2.Core.Nodes.GodotExtensions;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Threading.Tasks;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Entities.CardRewardAlternatives;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Merchant;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.GameActions;
using MegaCrit.Sts2.Core.Helpers;
using MegaCrit.Sts2.Core.Map;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Multiplayer.Game;
using MegaCrit.Sts2.Core.Nodes;
using MegaCrit.Sts2.Core.Nodes.Rewards;
using MegaCrit.Sts2.Core.Nodes.Rooms;
using MegaCrit.Sts2.Core.Nodes.Screens;
using MegaCrit.Sts2.Core.Nodes.Screens.CardSelection;
using MegaCrit.Sts2.Core.Nodes.Screens.GameOverScreen;
using MegaCrit.Sts2.Core.Nodes.Screens.Map;
using MegaCrit.Sts2.Core.Nodes.Screens.Overlays;
using MegaCrit.Sts2.Core.Rewards;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.TestSupport;

namespace AutoSpire;

/// Answers every card prompt (Headbutt, Brand, shop removal, event grids) over /exec, through the
/// game's own test hook: CardSelectCmd skips its selection screens when a selector is set.
internal sealed class AgentSelector : MegaCrit.Sts2.Core.TestSupport.ICardSelector
{
    internal sealed record Pending(List<CardModel> Options, int Min, TaskCompletionSource<IEnumerable<CardModel>> Done);

    internal static Pending? Current;
    // The game clears the selector stack when a run ends (CardSelectCmd.Reset), so check each time.
    internal static void Install()
    {
        Current = null;
        if (CardSelectCmd.Selector == null) CardSelectCmd.PushSelector(new AgentSelector());
    }

    public Task<IEnumerable<CardModel>> GetSelectedCards(IEnumerable<CardModel> options, int minSelect, int maxSelect)
    {
        var list = options.ToList();
        if (list.Count == 0) return Task.FromResult(Enumerable.Empty<CardModel>());
        var pending = new Pending(list, minSelect, new TaskCompletionSource<IEnumerable<CardModel>>());
        Current = pending;
        return pending.Done.Task;
    }

    // Never reached: CardReward only asks this when it has no selection screen, and the local player always does.
    public CardRewardSelection GetSelectedCardReward(IReadOnlyList<CardCreationResult> options, IReadOnlyList<CardRewardAlternative> alternatives)
        => throw new InvalidOperationException("no card reward selector");
}

internal static class RunBridge
{
    private const BindingFlags Private = BindingFlags.NonPublic | BindingFlags.Instance;

    private static T? Field<T>(object owner, string name) where T : class =>
        owner.GetType().GetField(name, Private)?.GetValue(owner) as T;

    // --- state -----------------------------------------------------------------------------------

    internal static string Screen(RunState rs)
    {
        var top = NOverlayStack.Instance?.Peek();
        if (top is NGameOverScreen) return "gameOver";
        if (top is NCardRewardSelectionScreen) return "cardReward";
        if (AgentSelector.Current != null && !CombatManager.Instance.IsInProgress) return "choice";
        // An Ancient opens while the map is still up, at the start of an act.
        if (rs.CurrentRoom is EventRoom room && !room.LocalMutableEvent.IsFinished) return "event";
        // The rewards screen stays on the overlay stack under an open map.
        if (NMapScreen.Instance?.IsOpen == true) return NMapScreen.Instance.IsTravelEnabled ? "map" : "busy";
        if (top is NRewardsScreen) return "rewards";
        if (CombatManager.Instance.IsInProgress) return "combat";
        return rs.CurrentRoom?.RoomType switch
        {
            RoomType.Event => "event",
            RoomType.RestSite => "rest",
            RoomType.Shop => "shop",
            RoomType.Treasure => "treasure",
            _ => "busy",
        };
    }

    internal static object? Details(string screen, RunState rs) => screen switch
    {
        "map" => MapState(rs),  // the rl-agent-sim branch's live.py still reads it from here
        "event" => EventState(rs),
        "rest" => new
        {
            options = (rs.CurrentRoom as RestSiteRoom)?.Options.Select(o => o.OptionId).ToList(),
            proceed = NRun.Instance?.RestSiteRoom?.ProceedButton.IsEnabled ?? false,
        },
        "shop" => ShopState(rs),
        "treasure" => TreasureState(),
        _ => null,
    };

    internal static object MapState(RunState rs)
    {
        var map = rs.Map;
        var points = map.GetAllMapPoints().Concat(new[] { map.StartingMapPoint, map.BossMapPoint }).Distinct();
        var cur = rs.CurrentMapPoint ?? map.StartingMapPoint;
        return new
        {
            current = new { cur.coord.col, cur.coord.row },
            atStart = rs.CurrentMapPoint == null,  // a new act: the first move is onto its Ancient
            points = points.Select(p => new
            {
                p.coord.col,
                p.coord.row,
                type = p.PointType.ToString(),
                children = p.Children.Select(c => new { c.coord.col, c.coord.row }).ToList(),
            }).ToList(),
            boss = rs.Act.BossEncounter.Id.Entry,
        };
    }

    private static object? EventState(RunState rs)
    {
        if (rs.CurrentRoom is not EventRoom room) return null;
        var ev = room.LocalMutableEvent;
        var card = ev.GetType().GetProperty("RandomCardToLose", Private)?.GetValue(ev) as CardModel;
        return new
        {
            id = ev.Id.Entry,
            finished = ev.IsFinished,
            atRisk = card?.Id.Entry,
            vars = ev.DynamicVars.ToDictionary(kv => kv.Key, kv => kv.Value.BaseValue),
            options = ev.CurrentOptions.Select(o => new
            {
                key = o.TextKey,
                locked = o.IsLocked,
                proceed = o.IsProceed,
                relic = o.Relic?.Id.Entry,
                kills = o.WillKillPlayer?.Invoke(LocalContext.GetMe(rs)!) ?? false,
            }).ToList(),
        };
    }

    private static object? ShopState(RunState rs)
    {
        if (rs.CurrentRoom is not MerchantRoom room) return null;
        NRun.Instance?.MerchantRoom?.OpenInventory();  // so a watcher sees the purchases
        var inv = room.GetLocalInventory();
        var removal = inv.CardRemovalEntry;
        return new
        {
            cards = inv.CharacterCardEntries.Select(e => new { id = e.IsStocked ? e.CreationResult?.Card.Id.Entry : null, cost = e.Cost }).ToList(),
            relics = inv.RelicEntries.Select(e => new { id = e.Model?.Id.Entry, cost = e.Cost }).ToList(),
            potions = inv.PotionEntries.Select(e => new { id = e.Model?.Id.Entry, cost = e.Cost }).ToList(),
            removal = removal == null ? null : new { used = removal.Used, cost = removal.Cost },
        };
    }

    private static object? TreasureState()
    {
        var room = NRun.Instance?.TreasureRoom;
        if (room == null) return null;
        return new
        {
            opened = (bool)room.GetType().GetField("_hasChestBeenOpened", Private)!.GetValue(room)!,
            relics = RunManager.Instance.TreasureRoomRelicSynchronizer.CurrentRelics?.Select(r => r.Id.Entry).ToList(),
            proceed = room.ProceedButton.IsEnabled,
        };
    }

    internal static object? Choice(Player? player)
    {
        var pending = AgentSelector.Current;
        if (pending == null || player == null) return null;
        var pcs = player.PlayerCombatState;
        string kind = pcs != null && pending.Options.All(pcs.Hand.Cards.Contains) ? "hand"
            : pcs != null && pending.Options.All(pcs.DiscardPile.Cards.Contains) ? "discard" : "deck";
        return new
        {
            kind,
            source = CombatManager.Instance.History.CardPlaysStarted.LastOrDefault()?.CardPlay.Card.Id.Entry,
            options = pending.Options.Select(c => c.Id.Entry).ToList(),
        };
    }

    /// The reward buttons still on screen; `reward <index>` clicks one.
    internal static List<NRewardButton>? RewardButtons()
    {
        if (NOverlayStack.Instance?.Peek() is not NRewardsScreen screen) return null;
        return Field<List<Godot.Control>>(screen, "_rewardButtons")?.OfType<NRewardButton>().ToList();
    }

    // --- commands, all run on the main thread ------------------------------------------------------

    internal static object Exec(string verb, string[] parts)
    {
        int Arg(int i) => int.Parse(parts[i]);
        var rs = RunManager.Instance.DebugOnlyGetState() ?? throw new InvalidOperationException("not_in_run");
        var me = LocalContext.GetMe(rs) ?? throw new InvalidOperationException("no_player");
        switch (verb)
        {
            case "map":
            {
                var point = rs.Map.GetPoint(Arg(1), Arg(2)) ?? throw new InvalidOperationException("no_such_point");
                var vote = new MapVote { coord = point.coord, mapGenerationCount = RunManager.Instance.MapSelectionSynchronizer.MapGenerationCount };
                RunManager.Instance.ActionQueueSynchronizer.RequestEnqueue(
                    new VoteForMapCoordAction(me, new MapLocation(rs.CurrentMapCoord, rs.CurrentActIndex), vote));
                break;
            }
            case "reward":
                (RewardButtons() ?? throw new InvalidOperationException("no_rewards"))[Arg(1)].ForceClick();
                break;
            case "pick":
            {
                if (NOverlayStack.Instance?.Peek() is not NCardRewardSelectionScreen screen)
                    throw new InvalidOperationException("no_card_reward");
                Field<TaskCompletionSource<int?>>(screen, "_completionSource")!.SetResult(Arg(1));
                break;
            }
            case "close_map": // for live_check: the debug `event` and `room` commands leave the map open
                NMapScreen.Instance?.Close();
                break;
            case "proceed":
                Proceed();
                break;
            case "option": // an event option; `event <ID>` stays the dev console's
            {
                var ev = ((EventRoom)rs.CurrentRoom!).LocalMutableEvent;
                if (ev.IsFinished && ev.CurrentOptions.Count == 0) TaskHelper.RunSafely(NEventRoom.Proceed());
                else NEventRoom.Instance!.OptionButtonClicked(ev.CurrentOptions[Arg(1)], Arg(1));
                break;
            }
            case "rest":
                TaskHelper.RunSafely(RunManager.Instance.RestSiteSynchronizer.ChooseLocalOption(Arg(1)));
                break;
            case "chest":
            {
                var chest = Field<NButton>(NRun.Instance!.TreasureRoom!, "_chestButton");
                chest!.ForceClick();
                break;
            }
            case "chest_relic":
                RunManager.Instance.TreasureRoomRelicSynchronizer.PickRelicLocally(Arg(1));
                break;
            case "buy":
                Buy(rs, parts[1], parts.Length > 2 ? Arg(2) : 0);
                break;
            case "drop_potion":
            {
                var potion = me.PotionSlots[Arg(1)] ?? throw new InvalidOperationException("empty_slot");
                TaskHelper.RunSafely(PotionCmd.Discard(potion));
                break;
            }
            case "choose": // hand index, as in the sim
            {
                var hand = me.PlayerCombatState!.Hand.Cards;
                var options = AgentSelector.Current!.Options;
                int i = Arg(1);
                // ponytail: a hand slot the prompt doesn't allow takes its first option; the env's mask opens the whole hand.
                Resolve(i < hand.Count && options.Contains(hand[i]) ? hand[i] : options[0]);
                break;
            }
            case "choose_discard": // card id, as in the sim
                Resolve(AgentSelector.Current!.Options.First(c => c.Id.Entry == parts[1]));
                break;
            case "choose_option":
                Resolve(AgentSelector.Current!.Options[Arg(1)]);
                break;
            case "upgrade_deck": // a deck card by id, as Smith does; the dev console's `upgrade` takes hand cards only
            {
                var card = me.Deck.Cards.FirstOrDefault(c => c.Id.Entry == parts[1] && c.IsUpgradable)
                    ?? throw new InvalidOperationException("no_upgradable_card");
                CardCmd.Upgrade(card, CardPreviewStyle.None);
                break;
            }
            default:
                throw new InvalidOperationException("unknown_command");
        }
        return new { ok = true };
    }

    private static void Resolve(CardModel card)
    {
        var pending = AgentSelector.Current!;
        AgentSelector.Current = null;
        var picked = new List<CardModel> { card };
        picked.AddRange(pending.Options.Where(c => c != card).Take(Math.Max(0, pending.Min - 1)));
        pending.Done.SetResult(picked);
    }

    private static void Proceed()
    {
        if (NOverlayStack.Instance?.Peek() is NRewardsScreen screen)
        {
            Field<NProceedButton>(screen, "_proceedButton")!.ForceClick();
            return;
        }
        if (NRun.Instance?.TreasureRoom is { } treasure)
        {
            treasure.ProceedButton.ForceClick();
            return;
        }
        NMapScreen.Instance!.Open();  // what the rest site and shop buttons do, minus the shop's first-visit tutorial
    }

    private static void Buy(RunState rs, string what, int i)
    {
        var inv = ((MerchantRoom)rs.CurrentRoom!).GetLocalInventory();
        Task<bool> task = what switch
        {
            "card" => inv.CharacterCardEntries[i].OnTryPurchaseWrapper(inv),
            "relic" => inv.RelicEntries[i].OnTryPurchaseWrapper(inv),
            "potion" => inv.PotionEntries[i].OnTryPurchaseWrapper(inv),
            "removal" => inv.CardRemovalEntry!.OnTryPurchaseWrapper(inv),
            _ => throw new InvalidOperationException("usage: buy card|relic|potion|removal [index]"),
        };
        TaskHelper.RunSafely(task);
    }
}
