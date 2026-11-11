"""Stage the paths a real run rarely reaches, in the live game, and compare them with the sim's rules.

Unlike a real run this uses debug commands (fight, event, room, gold). It prints one PASS or FAIL per check.
    python live_check.py --run-model models/ppo_sts2_sim_run_policy_v6pc.zip --model models/ppo_sts2_sim_act1_pc_v13c.zip
"""
from __future__ import annotations

import argparse
import random
import time
import traceback
from collections import Counter, defaultdict
from types import SimpleNamespace

import numpy as np

from env import (CARD_IDS, CHOOSE_DISCARD, CHOOSE_DONE, CHOOSE_DRAW, CHOOSE_GENERATED, CHOOSE_HAND, CHOOSE_SKIP, END_TURN, MAX_ENEMIES,
                 MAX_HAND, STS2CombatEnv, _ready)
from live import LiveGame, _cid, _event_opts
from run_env import CARD_INDEX, OBS_DIM as RUN_OBS_DIM, PICK, REST, REST_OPTIONS, SHOP_COLORLESS_ACTION, SMITH
from sim.act import COLORLESS_PRICE, SHOP_COLORLESS, SHOP_SLOTS, Run
from sim.cards import COLORLESS_RARES, COLORLESS_UNCOMMONS, UPGRADABLE
from sim.engine import SimClient
from sim.validate import ids, load


def pile(p: dict, name: str) -> list[str]:
    return [c["id"] for c in p.get(name) or []]


def power(p: dict, name: str) -> int:
    return next((x["amount"] for x in p.get("powers") or [] if x["name"] == name), 0)


class Fixed:
    """A run model with a known answer, so a check takes live.py's own path: `pick(mask)` names the action, which the
    mask must allow."""

    def __init__(self, pick):
        self.pick = pick

    def predict(self, obs, action_masks, deterministic=True):
        a = self.pick(action_masks)
        assert obs.shape == (RUN_OBS_DIM,) and action_masks[a], f"action {a} is masked"
        return a, None


def first_pick(mask) -> int:
    """The first modeled card offered; for any other decision (a potion reward) the last legal action, its skip."""
    picks = [k for k in range(PICK, PICK + 3) if mask[k]]
    return picks[0] if picks else int(np.flatnonzero(mask)[-1])


class Check:
    def __init__(self, game: LiveGame, only: str = ""):
        self.game, self.client = game, game.client
        self.results: list[tuple[str, bool, str]] = []
        self.only = only  # run just the checks whose name holds this

    def do(self, cmd: str, settle: float = 0.3) -> dict:
        r = self.client.exec(cmd, settle=settle)
        assert "error" not in r and r.get("ok", True), f"{cmd}: {r}"
        return r

    def wait(self, test, what: str, timeout: float = 20.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            s = self.client.state()
            if test(s):
                return s
            time.sleep(0.2)
        raise AssertionError(f"timed out waiting for {what}; screen {s.get('screen')}")

    def run(self, name: str, fn) -> None:
        if self.only not in name:
            return
        try:
            fn()
            self.results.append((name, True, ""))
            print(f"PASS {name}", flush=True)
        except Exception as exc:  # noqa: BLE001 - one failed check must not hide the rest
            self.results.append((name, False, repr(exc)))
            print(f"FAIL {name}: {exc!r}", flush=True)
            traceback.print_exc()

    # --- prompt cards, through the same env.step the combat model uses ----------------------------------

    def fight_with(self, card: str, discard: tuple[str, ...] = (), draw: tuple[str, ...] = ()) -> tuple:
        self.do("fight NIBBITS_WEAK", settle=0.5)
        self.client.wait_for(_ready, timeout=30.0)
        for c in discard:
            self.do(f"card {c} Discard")
        for c in draw:
            self.do(f"card {c} Draw")
        self.do(f"card {card} Hand")
        self.do("energy 5")
        combat = self.client.wait_for(_ready, timeout=15.0)
        env = self.game.fight
        env._combat, env._steps = combat, 0
        hand = pile(combat["player"], "hand")
        assert card in hand, (card, hand)
        return env, combat, hand.index(card) * MAX_ENEMIES

    def finish_fight(self) -> None:
        self.do("win")
        self.wait(lambda s: s["screen"] != "combat", "the fight to end")

    def play_to_prompt(self, env, action: int, kind: str) -> dict:
        env.step(action)
        combat = env._combat
        assert (combat.get("choice") or {}).get("kind") == kind, combat.get("choice")
        return combat

    def burning_pact(self) -> None:
        env, _, a = self.fight_with("BURNING_PACT")
        combat = self.play_to_prompt(env, a, "hand")
        assert combat["choice"]["source"] == "BURNING_PACT", combat["choice"]
        assert env.action_masks()[CHOOSE_HAND]
        p = combat["player"]
        picked, size = pile(p, "hand")[0], len(pile(p, "hand"))
        env.step(CHOOSE_HAND)
        p = env._combat["player"]
        assert picked in pile(p, "exhaustPile"), pile(p, "exhaustPile")
        assert len(pile(p, "hand")) == size + 1, "exhausted 1, drew 2"
        self.finish_fight()

    def brand(self) -> None:
        env, combat, a = self.fight_with("BRAND")
        hp = combat["player"]["hp"]
        p = self.play_to_prompt(env, a, "hand")["player"]
        assert p["hp"] == hp - 1, "HP is lost before the prompt"
        picked = pile(p, "hand")[0]
        env.step(CHOOSE_HAND)
        p = env._combat["player"]
        assert picked in pile(p, "exhaustPile") and power(p, "StrengthPower") == 1, p.get("powers")
        self.finish_fight()

    def headbutt(self) -> None:
        env, combat, a = self.fight_with("HEADBUTT", ("STRIKE_IRONCLAD", "DEFEND_IRONCLAD"))
        hp = sum(e["hp"] for e in combat["enemies"])
        combat = self.play_to_prompt(env, a, "discard")
        assert sum(e["hp"] for e in combat["enemies"]) == hp - 9, "damage comes before the prompt"
        assert combat["choice"]["source"] == "HEADBUTT", combat["choice"]
        mask = env.action_masks()
        assert mask[CHOOSE_DISCARD + CARD_IDS.index("DEFEND_IRONCLAD")] and mask[CHOOSE_DISCARD + CARD_IDS.index("STRIKE_IRONCLAD")]
        env.step(CHOOSE_DISCARD + CARD_IDS.index("DEFEND_IRONCLAD"))
        before = Counter(pile(env._combat["player"], "hand"))
        self.do("draw 1", settle=0.5)
        after = Counter(pile(self.client.wait_for(_ready, timeout=15.0)["player"], "hand"))
        assert after - before == Counter(["DEFEND_IRONCLAD"]), "the chosen card is on top of the draw pile"
        self.finish_fight()

    # --- the five modeled events: each option's numbers must match Run.start_event ------------------------

    def open_event(self, event: str) -> dict:
        self.do("close_map")
        self.do(f"event {event}", settle=0.5)
        s = self.wait(lambda s: s["screen"] == "event" and s.get("details") and s["details"]["id"] == event
                      and s["details"].get("options") and not s["details"]["finished"], f"event {event}")
        return s

    def leave_event(self) -> None:
        """Answer whatever the event left behind, as a run would, until the map opens."""
        g = self.game
        g.seen = set()
        deadline = time.monotonic() + 45.0
        while time.monotonic() < deadline:
            s = self.client.state()
            g.run.sync(s)
            if s["screen"] == "map":
                return
            if s["screen"] == "event" and s.get("details"):
                g.do_event(s["details"])
            elif s["screen"] == "rewards":
                g.do_rewards(s["rewards"])
            elif s["screen"] == "choice":
                g.do_choice(s["choice"])
            else:
                time.sleep(0.2)
        raise AssertionError(f"never got back to the map from {s['screen']}")

    def event_option(self, event: str, option: int, expect) -> None:
        def check():
            self.do("heal 999")
            if event == "SLIPPERY_BRIDGE":
                self.do("card INFLAME Deck")
            s = self.open_event(event)
            d, before = s["details"], s["player"]
            hp_loss, gold, max_hp = _event_opts(event, d["vars"])[option]
            self.do(f"option {option}", settle=0.5)
            s = self.wait(lambda s: (s["player"]["hp"], s["player"]["gold"], len(s["player"]["deck"]), len(s["player"]["relics"]))
                          != (before["hp"], before["gold"], len(before["deck"]), len(before["relics"])), "the option to take effect")
            time.sleep(1.0)
            s = self.client.state()
            p = s["player"]
            assert p["hp"] - before["hp"] == max_hp - hp_loss, ("hp", before["hp"], p["hp"], hp_loss, max_hp)
            assert p["maxHp"] - before["maxHp"] == max_hp, ("maxHp", before["maxHp"], p["maxHp"])
            assert p["gold"] - before["gold"] == int(gold), ("gold", before["gold"], p["gold"], gold)
            if expect:
                expect(before, p, d, s)
            if event == "SLIPPERY_BRIDGE" and option == 1:  # hold on again costs 1 more, then let the card go
                assert s["details"]["vars"]["HpLoss"] == hp_loss + 1, s["details"]["vars"]
                self.do("option 0", settle=0.5)
            self.leave_event()
        self.run(f"event {event} option {option}", check)

    @staticmethod
    def gained(card: str):
        def test(before, p, d, s):
            assert (Counter(pile(p, "deck")) - Counter(pile(before, "deck"))) == Counter([card]), pile(p, "deck")
        return test

    @staticmethod
    def lost_at_risk(before, p, d, s):
        assert (Counter(map(_cid, before["deck"])) - Counter(map(_cid, p["deck"]))) == Counter([d["atRisk"]]), d.get("atRisk")

    @staticmethod
    def sword(before, p, d, s):
        assert "SWORD_OF_STONE" in {r["id"] for r in p["relics"]}, p["relics"]

    # --- colorless cards: their prompts, Hand of Greed's gold, the shop's colorless slots -------------------

    def colorless_prompt(self, card: str, answers, draw: tuple[str, ...] = ()) -> None:
        """Play `card` live and in the sim from the same state, through the same env.step actions: `answers` maps each
        open prompt to the next action. Both must ask the same prompt, allow the action, and end with the same hand
        (ids and costs), piles and energy."""
        env, combat, a = self.fight_with(card, draw=draw)
        sim = SimClient()
        sim._combat = load(combat, defaultdict(list))
        senv = STS2CombatEnv(client=sim)
        senv._combat = sim.combat()
        senv.step(a)
        env.step(a)
        for answer in answers:
            live, mine = env._combat.get("choice"), senv._combat.get("choice")
            assert live and mine and (live["kind"], live["source"]) == (mine["kind"], mine["source"]), (live, mine)
            if live["kind"] == "generated":  # new random cards: the sim offers what the game offered
                offered = ids({"id": i, "upgraded": u, "cost": 0} for i, u in zip(live["options"], live["upgraded"]))
                sim._combat._options = mine["options"] = offered
            elif live["kind"] == "draw":
                assert sorted(map(_cid, ({"id": i, "upgraded": u} for i, u in zip(live["options"], live["upgraded"])))) \
                    == sorted(mine["options"]), (live, mine)
            act = answer(live)
            assert env.action_masks()[act] and senv.action_masks()[act], (act, live)
            info = env.step(act)[-1]
            assert not info.get("aborted"), info
            senv.step(act)
        assert not env._combat.get("choice") and not senv._combat.get("choice"), (env._combat.get("choice"), senv._combat.get("choice"))
        p, s = env._combat["player"], senv._combat["player"]
        # Discovery's pick is free. Unmodeled cards (Spoils Map) are Wounds in the sim: their cost isn't compared.
        hand = lambda q: [(i, c["cost"] if i != "WOUND" else None) for i, c in zip(ids(q["hand"]), q["hand"])]  # noqa: E731
        assert hand(p) == hand(s), (hand(p), hand(s))
        assert ids(p["drawPile"]) == ids(s["drawPile"])[::-1], (ids(p["drawPile"]), ids(s["drawPile"]))  # live: top first
        for k in ("discardPile", "exhaustPile"):
            assert ids(p[k]) == ids(s[k]), (k, ids(p[k]), ids(s[k]))
        assert p["energy"] == s["energy"], (p["energy"], s["energy"])
        self.finish_fight()

    def entropy_after_armaments(self) -> None:
        """Entropy's turn-start prompt is a hand prompt from ENTROPY, even when the last card played was Armaments (whose
        prompt is "upgrade")."""
        env, combat, a = self.fight_with("ARMAMENTS")
        self.do("power ENTROPY_POWER 1 0")
        env._combat = self.client.wait_for(lambda c: _ready(c) and power(c["player"], "EntropyPower") == 1, timeout=15.0)
        env.step(a)
        if env._combat.get("choice"):  # Armaments' own prompt: any upgradable card
            assert env._combat["choice"]["kind"] == "upgrade", env._combat["choice"]
            env.step(int(np.flatnonzero(env.action_masks())[0]))
        env.step(END_TURN)
        choice = env._combat.get("choice")
        assert choice and (choice["kind"], choice["source"]) == ("hand", "ENTROPY"), choice
        assert env.action_masks()[CHOOSE_HAND], "the env can answer it"
        env.step(CHOOSE_HAND)
        assert not env._combat.get("choice"), env._combat.get("choice")
        self.finish_fight()

    def hand_of_greed(self) -> None:
        """A fatal hit gains Gold 20, as the sim's gold_gained, even though it ends the fight."""
        env, combat, a = self.fight_with("HAND_OF_GREED")
        target = next(e for e in combat["enemies"] if e["isAlive"])
        self.do(f"damage {target['hp'] - 5} {1 + combat['enemies'].index(target)}")  # creature 0 is the player
        combat = env._combat = self.client.wait_for(
            lambda c: _ready(c) and any(e["combatId"] == target["combatId"] and e["hp"] == 5 for e in c["enemies"]), timeout=15.0)
        sim = SimClient()
        sim._combat = load(combat, defaultdict(list))
        senv = STS2CombatEnv(client=sim)
        senv._combat = sim.combat()
        gold = self.client.state()["player"]["gold"]
        senv.step(a)
        env.step(a)
        s = self.wait(lambda s: s["player"]["gold"] != gold, "Hand of Greed's gold")
        assert sim._combat.gold_gained == s["player"]["gold"] - gold == 20, (sim._combat.gold_gained, gold, s["player"]["gold"])
        if self.client.combat().get("inCombat"):
            self.finish_fight()

    def shop_colorless(self) -> None:
        """The two colorless slots come after the five typed ones, priced as the sim's; one is bought through
        LiveGame.do_shop."""
        s = self.open_shop()
        cards = s["details"]["cards"]
        assert len(cards) == len(SHOP_SLOTS) + len(SHOP_COLORLESS), cards
        for e, rarity in zip(cards[len(SHOP_SLOTS):], SHOP_COLORLESS):
            assert e["id"] in (COLORLESS_UNCOMMONS if rarity == "Uncommon" else COLORLESS_RARES), (rarity, e)
            price = COLORLESS_PRICE[rarity]
            assert round(price * 0.95) <= e["cost"] <= round(price * 1.05), (rarity, e)
        g = self.game
        g.run.sync(s)
        before, gold = Counter(map(_cid, s["player"]["deck"])), s["player"]["gold"]
        slots = [SHOP_COLORLESS_ACTION + k for k in range(len(SHOP_COLORLESS))]
        asked = []
        model, g.run_model = g.run_model, Fixed(lambda m: asked.append(next(a for a in slots if m[a])) or asked[-1])
        try:
            g.do_shop(s["details"])
        finally:
            g.run_model = model
        bought = cards[len(SHOP_SLOTS) + asked[0] - SHOP_COLORLESS_ACTION]
        s = self.wait(lambda s: s["player"]["gold"] != gold, "the purchase")
        assert s["player"]["gold"] == gold - bought["cost"], (gold, bought)
        assert Counter(map(_cid, s["player"]["deck"])) - before == Counter([_cid(bought)]), (bought, pile(s["player"], "deck"))
        assert g.run.shop.cards[len(SHOP_SLOTS):] == [_cid(e) for e in cards[len(SHOP_SLOTS):]], g.run.shop.cards
        self.do("proceed")
        self.wait(lambda s: s["screen"] == "map", "the map")

    # --- shop and potions ---------------------------------------------------------------------------------

    def open_shop(self) -> dict:
        self.do("gold 999")
        self.do("close_map")
        self.do("room Shop", settle=0.5)
        return self.wait(lambda s: s["screen"] == "shop" and s.get("details"), "the shop")

    def shop_relic(self) -> None:
        s = self.open_shop()
        i, entry = next((i, e) for i, e in enumerate(s["details"]["relics"]) if e.get("id"))
        gold = s["player"]["gold"]
        self.do(f"buy relic {i}")
        s = self.wait(lambda s: s["player"]["gold"] != gold, "the purchase")
        assert s["player"]["gold"] == gold - entry["cost"], (gold, entry)
        assert entry["id"] in {r["id"] for r in s["player"]["relics"]}, entry

    def shop_removal(self) -> None:
        s = self.open_shop()
        cost, gold, deck = s["details"]["removal"]["cost"], s["player"]["gold"], Counter(pile(s["player"], "deck"))
        self.game.pending_remove = "STRIKE_IRONCLAD"
        self.do("buy removal", settle=0.5)
        s = self.wait(lambda s: s["screen"] == "choice", "the removal prompt")
        self.game.do_choice(s["choice"])
        s = self.wait(lambda s: s["player"]["gold"] != gold, "the removal")
        assert s["player"]["gold"] == gold - cost, (gold, cost)
        assert deck - Counter(pile(s["player"], "deck")) == Counter(["STRIKE_IRONCLAD"]), pile(s["player"], "deck")
        s = self.wait(lambda s: s["screen"] == "shop" and s.get("details"), "the shop again")
        assert s["details"]["removal"]["used"], s["details"]["removal"]
        self.do("proceed")
        self.wait(lambda s: s["screen"] == "map", "the map")

    def removal_plain_first(self) -> None:
        """STRIKE+ ahead of STRIKE in the deck: removing STRIKE takes the plain copy, as Run.remove does."""
        deck = [c for c in map(_cid, self.client.state()["player"]["deck"]) if c.removesuffix("+") != "STRIKE_IRONCLAD"]
        self.client.set_deck(deck + ["STRIKE_IRONCLAD+", "STRIKE_IRONCLAD"])  # upgrade_deck takes the first copy added
        s = self.open_shop()
        strikes = [c["upgraded"] for c in s["player"]["deck"] if c["id"] == "STRIKE_IRONCLAD"]
        assert strikes == [True, False], strikes
        g = self.game
        g.run.sync(s)
        sim = Run(random.Random(0))
        sim.deck, sim.gold, sim.shop = list(g.run.deck), 999, SimpleNamespace(removal_price=0, removal_used=False)
        sim.remove("STRIKE_IRONCLAD")
        g.pending_remove = "STRIKE_IRONCLAD"
        self.do("buy removal", settle=0.5)
        c = self.wait(lambda s: s["screen"] == "choice", "the removal prompt")["choice"]
        assert len(c["upgraded"]) == len(c["options"]) and True in c["upgraded"], c
        g.do_choice(c)
        s = self.wait(lambda s: s["screen"] == "shop" and s.get("details") and s["details"]["removal"]["used"], "the removal")
        g.run.sync(s)
        assert Counter(g.run.deck) == Counter(sim.deck), (sorted(g.run.deck), sorted(sim.deck))
        self.do("proceed")
        self.wait(lambda s: s["screen"] == "map", "the map")

    def potions(self) -> None:
        self.clear_potions()
        for p in ("BLOOD_POTION", "SPEED_POTION", "ENERGY_POTION"):
            self.do(f"potion {p}", settle=0.5)
        slots = self.client.state()["potionSlots"]
        assert slots == ["BLOOD_POTION", "SPEED_POTION", "ENERGY_POTION"], slots
        self.do("drop_potion 1", settle=0.5)
        s = self.wait(lambda s: s["potionSlots"][1] is None, "the drop")
        assert s["potionSlots"] == ["BLOOD_POTION", None, "ENERGY_POTION"], s["potionSlots"]
        # Blood Potion between fights: 20% of max HP, truncated (Run.drink), and the slots keep their places.
        self.open_event("JUNGLE_MAZE_ADVENTURE")
        self.do("option 0", settle=0.5)
        self.wait(lambda s: s["player"]["hp"] < s["player"]["maxHp"], "the HP loss")
        time.sleep(1.0)
        self.leave_event()
        before = self.client.state()["player"]
        self.do("potion 0", settle=0.5)
        s = self.wait(lambda s: s["potionSlots"][0] is None, "the potion to be drunk")
        time.sleep(1.0)
        s = self.client.state()
        assert s["player"]["hp"] == min(before["maxHp"], before["hp"] + before["maxHp"] * 20 // 100), (before["hp"], s["player"]["hp"])
        assert s["potionSlots"] == [None, None, "ENERGY_POTION"], s["potionSlots"]

    def clear_potions(self) -> None:
        for i, p in enumerate(self.client.state()["potionSlots"]):
            if p:
                self.do(f"drop_potion {i}", settle=0.5)

    # --- upgrades: Armaments in a real fight, the rest site's options, upgraded rewards -------------------

    def armaments(self, upgraded: bool) -> None:
        env, combat, a = self.fight_with("ARMAMENTS")
        i = a // MAX_ENEMIES
        if upgraded:
            self.do(f"upgrade {i}")  # the dev console's: a hand card by index
            combat = env._combat = self.client.wait_for(lambda c: _ready(c) and c["player"]["hand"][i]["upgraded"], timeout=15.0)
        sim = load(combat, defaultdict(list))
        assert sim.play_card(i).get("ok")
        env.step(a)
        choice = env._combat.get("choice")
        if sim.pending_choice:
            assert choice and (choice["kind"], choice["source"]) == (sim.pending_choice["kind"], sim.pending_choice["source"]), choice
            mask = env.action_masks()
            slots = [k for k in range(MAX_HAND) if mask[CHOOSE_HAND + k]]
            assert slots == [k for k, c in enumerate(sim.hand) if c in UPGRADABLE], (slots, sim.hand)
            sim.choose_card(slots[-1])
            env.step(CHOOSE_HAND + slots[-1])
        else:
            assert not choice, choice
        p = env._combat["player"]
        assert ids(p["hand"]) == sim.hand, (ids(p["hand"]), sim.hand)  # unmodeled cards (Byrdonis Egg) are Wounds in both
        assert p["block"] == sim.combat_dict()["player"]["block"], (p["block"], sim.combat_dict()["player"]["block"])
        self.finish_fight()

    def rest_site(self, pick, relics: tuple[str, ...] = ()) -> tuple[dict, dict, Run]:
        """Open a rest site and take `pick(sim run)`'s action through LiveGame.do_rest, on the live game and on a sim
        Run with the same deck and relics. (before, after, sim)."""
        for r in relics:
            self.do(f"relic {r}", settle=0.5)
        self.do("close_map")
        self.do("room RestSite", settle=0.5)
        s = self.wait(lambda s: s["screen"] == "rest" and (s.get("details") or {}).get("options"), "the rest site")
        g = self.game
        g.run.sync(s)
        g.seen = set()
        sim = Run(random.Random(0))
        sim.deck, sim.relics, sim.relic_state = list(g.run.deck), set(g.run.relics), {}
        modeled = [o for o in s["details"]["options"] if o in ("HEAL", "SMITH", "LIFT", "DIG")]  # not Byrdonis Egg's HATCH
        assert modeled == sim.rest_options(), (s["details"]["options"], sim.rest_options())
        a = pick(sim)
        model, g.run_model = g.run_model, Fixed(lambda m: a)
        try:
            g.do_rest(s["details"])
        finally:
            g.run_model = model
        sim.rest("SMITH", CARD_IDS[a - SMITH]) if a >= SMITH else sim.rest(REST_OPTIONS[a - REST])
        self.wait(lambda t: t["screen"] == "rest" and (t.get("details") or {}).get("proceed"), "the option to finish")
        time.sleep(1.0)
        after = self.client.state()
        self.do("proceed")
        self.wait(lambda s: s["screen"] == "map", "the map")
        return s, after, sim

    def smith(self) -> None:
        picked = []

        def bash(sim):  # Slippery Bridge can have taken BASH: then the first upgradable card
            picked.append("BASH" if "BASH" in sim.deck else next(c for c in sim.deck if c in UPGRADABLE))
            return SMITH + CARD_INDEX[picked[0]]
        before, after, sim = self.rest_site(bash)
        g = self.game
        g.run.sync(after)
        assert Counter(g.run.deck) == Counter(sim.deck), (sorted(g.run.deck), sorted(sim.deck))
        assert Counter(g.run.deck) - Counter(map(_cid, before["player"]["deck"])) == Counter([picked[0] + "+"]), sorted(g.run.deck)
        assert after["player"]["hp"] == before["player"]["hp"]

    def lift(self) -> None:
        _, _, sim = self.rest_site(lambda sim: REST + REST_OPTIONS.index("LIFT"), relics=("GIRYA",))
        self.do("fight NIBBITS_WEAK", settle=0.5)
        c = self.client.wait_for(_ready, timeout=30.0)
        lifts = sim.relic_state["girya"]
        assert lifts == 1 and c["relicCounters"].get("girya") == lifts, c.get("relicCounters")
        assert power(c["player"], "StrengthPower") == lifts, c["player"].get("powers")  # Girya.AfterRoomEntered
        self.finish_fight()

    def dig(self) -> None:
        before, after, sim = self.rest_site(lambda sim: REST + REST_OPTIONS.index("DIG"), relics=("SHOVEL",))
        n = len(before["player"]["relics"])
        assert len(after["player"]["relics"]) == n + 1 == len(sim.relics), (n, after["player"]["relics"], sim.relics)
        assert Counter(map(_cid, after["player"]["deck"])) == Counter(map(_cid, before["player"]["deck"]))

    def upgraded_reward(self) -> None:
        """With all three Eggs every offer is upgraded (TryModifyCardRewardOptionsLate). Last: they also upgrade
        cards added to the deck."""
        for r in ("MOLTEN_EGG", "TOXIC_EGG", "FROZEN_EGG"):
            self.do(f"relic {r}", settle=0.5)
        self.do("fight NIBBITS_WEAK", settle=0.5)
        self.client.wait_for(_ready, timeout=30.0)
        self.finish_fight()
        g = self.game
        g.seen, g.policy.offered = set(), []
        before = Counter(map(_cid, self.client.state()["player"]["deck"]))
        model, g.run_model = g.run_model, Fixed(first_pick)
        try:
            deadline = time.monotonic() + 45.0
            while (s := self.client.state())["screen"] != "map":
                assert time.monotonic() < deadline, f"stuck on {s['screen']}"
                g.run.sync(s)
                if s["screen"] == "rewards":
                    g.do_rewards(s["rewards"])
                elif s["screen"] == "cardReward":
                    g.act(f"pick {g.pending_pick}")
                else:
                    time.sleep(0.2)
        finally:
            g.run_model = model
        offered = g.policy.offered
        assert offered and all(c.endswith("+") for c in offered), offered
        gained = Counter(map(_cid, self.client.state()["player"]["deck"])) - before
        assert gained == Counter([offered[g.pending_pick]]), (gained, offered)

    # ------------------------------------------------------------------------------------------------------

    def all(self) -> int:
        self.client.full_restart()
        self.run("Burning Pact prompt", self.burning_pact)
        self.run("Brand prompt", self.brand)
        self.run("Headbutt prompt", self.headbutt)
        self.event_option("BYRDONIS_NEST", 0, None)
        self.event_option("BYRDONIS_NEST", 1, self.gained("BYRDONIS_EGG"))
        self.event_option("JUNGLE_MAZE_ADVENTURE", 0, None)
        self.event_option("JUNGLE_MAZE_ADVENTURE", 1, None)
        self.event_option("SLIPPERY_BRIDGE", 0, self.lost_at_risk)
        self.event_option("SLIPPERY_BRIDGE", 1, None)
        self.event_option("SUNKEN_STATUE", 0, self.sword)
        self.event_option("SUNKEN_STATUE", 1, None)
        self.event_option("THE_LEGENDS_WERE_TRUE", 0, self.gained("SPOILS_MAP"))
        self.event_option("THE_LEGENDS_WERE_TRUE", 1, None)
        self.run("shop relic", self.shop_relic)
        self.run("shop removal", self.shop_removal)
        self.run("shop removal: plain copy first", self.removal_plain_first)
        self.run("potion drop and Blood Potion", self.potions)
        self.run("Armaments prompt", lambda: self.armaments(False))
        self.run("ARMAMENTS+", lambda: self.armaments(True))
        self.run("rest: Smith", self.smith)
        self.run("rest: Girya's Lift", self.lift)
        self.run("rest: Shovel's Dig", self.dig)
        self.run("Discovery: pick", lambda: self.colorless_prompt("DISCOVERY", [lambda c: CHOOSE_GENERATED + 1]))
        self.run("Discovery: skip", lambda: self.colorless_prompt("DISCOVERY", [lambda c: CHOOSE_SKIP]))
        self.run("Purity: 2 picks, then done", lambda: self.colorless_prompt(
            "PURITY", [lambda c: CHOOSE_HAND + 0, lambda c: CHOOSE_HAND + 1, lambda c: CHOOSE_DONE]))
        self.run("Secret Weapon", lambda: self.colorless_prompt(
            "SECRET_WEAPON", [lambda c: CHOOSE_DRAW + CARD_IDS.index(c["options"][-1])], draw=("STRIKE_IRONCLAD", "BASH")))
        self.run("Thinking Ahead", lambda: self.colorless_prompt("THINKING_AHEAD", [lambda c: CHOOSE_HAND + 1]))
        self.run("Entropy prompt after Armaments", self.entropy_after_armaments)
        self.run("Hand of Greed: gold from a fatal hit", self.hand_of_greed)
        self.run("shop: colorless slots", self.shop_colorless)
        self.run("upgraded card reward", self.upgraded_reward)
        failed = [r for r in self.results if not r[1]]
        print(f"{len(self.results) - len(failed)}/{len(self.results)} passed")
        for name, _, why in failed:
            print(f"  FAILED {name}: {why[:200]}")
        return len(failed)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--run-model", required=True)
    ap.add_argument("--only", default="", help="run just the checks whose name holds this")
    args = ap.parse_args()
    raise SystemExit(min(Check(LiveGame(args.model, args.run_model), args.only).all(), 1))
