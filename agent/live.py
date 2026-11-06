"""One real Act 1 in the live game: the run policy walks the game's own map, rewards, shops, events,
rest sites and treasure, and the combat model plays its fights. Nothing is staged with debug commands.

LiveRun fills the fields of sim.act.Run that RunPolicyEnv reads, so the policy sees the same observation
and mask as in training. Differences from the sim, all because the sim doesn't model them:
- Neow: the first option offering a modeled relic, else the first safe one. The sim has no Neow.
- Unmodeled events: the sim treats them as empty rooms. Here: leave if the event lets us, else the first safe option.
- Prompts the sim doesn't have (an event's card grid): the first option.
- A potion reward goes in the first open slot; if the policy names a full slot, that slot's potion is dropped first.
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

from sb3_contrib import MaskablePPO

from client import AutoSpireClient
from env import CARD_IDS, STS2CombatEnv, _encode, _ready
from run_env import (CARD_INDEX, DRINK, EVENT, PATH, PICK, POTION_SKIP, REMOVE, SHOP, SHOP_LEAVE, SHOP_POTION, SHOP_RELIC,
                     SHOP_REMOVE, RunPolicyEnv, drink_slot, potion_take_slot)
from sim.act import SHOP_POTIONS, SHOP_RELICS, SHOP_SLOTS, Shop
from sim.events import MODELED_EVENTS
from sim.map import Node
from sim.potions import POTIONS
from sim.relics import RELICS

SAFE_WORDS = ("LEAVE", "SKIP", "IGNORE", "REFUSE", "DECLINE", "WALK", "PASS")
BUSY_LIMIT = 90.0  # seconds with no screen to act on before giving up


class LiveRun:
    """What RunPolicyEnv reads from a sim Run, read from the game instead."""

    def __init__(self):
        self.hp = self.max_hp = self.gold = self.removals = 0
        self.deck, self.potions = [], []
        self.relics, self.relic_state = set(), {}
        self.node = self.map = self.boss = self.shop = None
        self.potion_drop = self.event = self.bridge_card = None
        self.event_opts = []

    def sync(self, state: dict) -> None:
        p = state["player"]
        self.hp, self.max_hp, self.gold = p["hp"], p["maxHp"], p["gold"]
        self.deck = [c["id"] for c in p["deck"] if c["id"] in CARD_INDEX]
        self.relics = {r["id"] for r in p["relics"]}
        self.potions = list(state["potionSlots"])

    def sync_map(self, details: dict) -> None:
        nodes = {(n["col"], n["row"]): Node(n["col"], n["row"], n["type"]) for n in details["points"]}
        for n in details["points"]:
            for c in n["children"]:
                nodes[n["col"], n["row"]].add_child(nodes[c["col"], c["row"]])
        boss = max(nodes.values(), key=lambda n: n.row)
        self.map = SimpleNamespace(grid={k: n for k, n in nodes.items() if n is not boss}, boss=boss)
        self.node = nodes[details["current"]["col"], details["current"]["row"]]
        self.boss = details["boss"]

    def choices(self) -> list[Node]:
        return sorted(self.node.children, key=lambda n: n.col)

    def price(self, raw: int) -> int:
        return raw  # MerchantEntry.Cost already has the discounts in it


def _pad(entries: list[dict], n: int) -> tuple[list, list]:
    entries = (entries + [{"id": None, "cost": 0}] * n)[:n]
    return [e.get("id") for e in entries], [e["cost"] for e in entries]


def _shop(d: dict) -> Shop:
    cards, prices = _pad(d["cards"], len(SHOP_SLOTS))
    relics, relic_prices = _pad(d["relics"], SHOP_RELICS)
    potions, potion_prices = _pad(d["potions"], SHOP_POTIONS)
    removal = d.get("removal") or {"used": True, "cost": 0}  # the mod leaves out null fields
    return Shop(cards, prices, removal["cost"], removal["used"], relics, relic_prices, potions, potion_prices)


def _event_opts(event: str, v: dict) -> list[tuple[int, int, int]]:
    """The same numbers as Run.start_event, read from the event's own rolled variables."""
    if event == "BYRDONIS_NEST":
        return [(0, 0, 7), (0, 0, 0)]
    if event == "JUNGLE_MAZE_ADVENTURE":
        return [(18, v["SoloGold"], 0), (0, v["JoinForcesGold"], 0)]
    if event == "SLIPPERY_BRIDGE":
        return [(0, 0, 0), (v["HpLoss"], 0, 0)]
    if event == "SUNKEN_STATUE":
        return [(0, 0, 0), (7, v["Gold"], 0)]
    return [(0, 0, 0), (8, 0, 0)]  # THE_LEGENDS_WERE_TRUE


def _fallback_option(options: list[dict]) -> int:
    """Index for an event the policy can't read."""
    safe = [i for i, o in enumerate(options) if not o["locked"] and not o["kills"]]
    usable = safe or [i for i, o in enumerate(options) if not o["locked"]]
    return next((i for i in usable if any(w in options[i]["key"] for w in SAFE_WORDS)),
                next((i for i in usable if options[i].get("relic") in RELICS), usable[0]))


class LiveGame:
    def __init__(self, model_path: str, run_model_path: str, client: AutoSpireClient | None = None):
        self.combat_model = MaskablePPO.load(model_path, device="cpu")
        self.run_model = MaskablePPO.load(run_model_path, device="cpu")
        self.client = client or AutoSpireClient()
        self.run = LiveRun()
        self.policy = RunPolicyEnv()  # only its observation and mask are used
        self.policy.run, self.policy.done = self.run, False
        self.fight = STS2CombatEnv(client=self.client, heal=False)
        self.seen: set = set()  # rewards and rooms already handled on this floor
        self.floor = None
        self.pending_pick = self.pending_remove = None
        self.last_room = None

    # --- talking to the game ------------------------------------------------------------------------

    def act(self, cmd: str, wait: float = 15.0) -> bool:
        """Send a command and wait for the game state to change. False if it never did."""
        before = json.dumps(self.client.state(), sort_keys=True)
        result = self.client.exec(cmd)
        if "error" in result:
            raise RuntimeError(f"{cmd}: {result['error']}")
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            time.sleep(0.2)
            if json.dumps(self.client.state(), sort_keys=True) != before:
                return True
        print(f"  (no change after {cmd})")
        return False

    def ask(self, decision: str) -> int:
        self.policy.decision = decision
        obs, mask = self.policy._obs(), self.policy.action_masks()
        return int(self.run_model.predict(obs, action_masks=mask, deterministic=True)[0])

    # --- screens ------------------------------------------------------------------------------------

    def play_fight(self) -> None:
        env = self.fight
        env._steps = 0
        while True:
            combat = self.client.wait_for(lambda c: _ready(c) or not c.get("inCombat"), timeout=30.0)
            if not combat.get("inCombat"):
                return
            env._combat, env._steps = combat, 0
            obs = _encode(combat)
            while True:
                choice = env._combat.get("choice")
                unreadable = choice and (choice["kind"] == "deck" or (
                    choice["kind"] == "discard" and not set(choice["options"]) & set(CARD_IDS)))
                if unreadable:  # a prompt the combat model has no action for
                    print(f"  prompt from {choice['source']}: took {choice['options'][0]}")
                    self.client.exec("choose_option 0")
                    break
                action = int(self.combat_model.predict(obs, action_masks=env.action_masks(), deterministic=True)[0])
                obs, _, terminated, truncated, info = env.step(action)
                if info.get("aborted"):
                    raise RuntimeError(f"fight aborted: {info.get('error')}")
                if terminated:
                    return
                if truncated:
                    break

    def do_rewards(self, rewards: list[dict]) -> None:
        for i, r in enumerate(rewards):
            key = (r["type"], r.get("potion"), r.get("relic"), tuple(c["id"] for c in r.get("cards") or []))
            if key in self.seen:
                continue
            self.seen.add(key)
            if r["type"] in ("GoldReward", "RelicReward"):
                if r.get("relic"):
                    print(f"  relic: {r['relic']}" + ("" if r["relic"] in RELICS else " (not modeled)"))
                self.act(f"reward {i}")
            elif r["type"] == "PotionReward":
                self.do_potion(i, r.get("potion"))
            elif r["type"] == "CardReward":
                self.do_card_reward(i, [c["id"] for c in r["cards"]])
            else:
                print(f"  skipped a {r['type']}")
            return
        self.act("proceed")

    def do_potion(self, i: int, potion: str) -> None:
        if potion not in POTIONS:
            print(f"  potion {potion}: not modeled, skipped")
            return
        self.run.potion_drop = potion
        a = self.ask("potion")
        self.run.potion_drop = None
        if a == POTION_SKIP:
            print(f"  potion {potion}: skipped")
            return
        slot = potion_take_slot(a)
        if self.run.potions[slot]:
            self.act(f"drop_potion {slot}")
        print(f"  potion {potion}: taken")
        self.act(f"reward {i}")

    def do_card_reward(self, i: int, offered: list[str]) -> None:
        self.policy.offered = offered[:3]
        a = self.ask("pick") - PICK
        choice = self.policy.offered[a] if a < len(self.policy.offered) else None
        print(f"  cards {offered}: {choice or 'skip'}")
        if choice:
            self.pending_pick = a
            self.act(f"reward {i}")

    def do_event(self, d: dict) -> None:
        options = d["options"]
        if d["finished"] or not options or any(o["proceed"] for o in options):
            self.act(f"option {next((i for i, o in enumerate(options) if o['proceed']), 0)}")
        elif d["id"] in MODELED_EVENTS and len(options) == 2:
            self.run.event, self.run.event_opts = d["id"], _event_opts(d["id"], d["vars"])
            self.run.bridge_card = None
            if d.get("atRisk") in self.run.deck:
                self.run.bridge_card = self.run.deck.index(d["atRisk"])
            elif d["id"] == "SLIPPERY_BRIDGE":  # the policy reads run.deck[bridge_card]; an unmodeled card can't show
                self.run.event = None
            a = self.ask("event") - EVENT if self.run.event else _fallback_option(options)
            self.run.event = None
            print(f"  event {d['id']}: {options[a]['key'].rsplit('.', 1)[-1]}")
            self.act(f"option {a}")
        else:
            a = _fallback_option(options)
            print(f"  event {d['id']} (not modeled): {options[a]['key'].rsplit('.', 1)[-1]}")
            self.act(f"option {a}")

    def do_shop(self, d: dict) -> None:
        self.run.shop = _shop(d)
        a = self.ask("shop")
        cmd = None
        if a == SHOP_REMOVE:
            self.pending_remove = CARD_IDS[self.ask("remove") - REMOVE]
            print(f"  shop: remove {self.pending_remove}")
            self.run.removals += 1
            cmd = "buy removal"
        elif a >= SHOP_RELIC:
            print(f"  shop: relic {self.run.shop.relics[a - SHOP_RELIC]}")
            cmd = f"buy relic {a - SHOP_RELIC}"
        elif a >= SHOP_POTION:
            print(f"  shop: potion {self.run.shop.potions[a - SHOP_POTION]}")
            cmd = f"buy potion {a - SHOP_POTION}"
        elif a != SHOP_LEAVE:
            print(f"  shop: card {self.run.shop.cards[a - SHOP]}")
            cmd = f"buy card {a - SHOP}"
        if cmd is None or not self.act(cmd):  # leaving, or the game refused the purchase
            self.act("proceed")

    def do_choice(self, choice: dict) -> None:
        options = choice["options"]
        i = options.index(self.pending_remove) if self.pending_remove in options else 0
        if self.pending_remove is None:
            print(f"  prompt: took {options[0]} of {len(options)}")
        self.pending_remove = None
        self.act(f"choose_option {i}")

    def do_treasure(self, d: dict) -> None:
        if not d["opened"]:
            self.act("chest")
        elif d.get("relics") and "relic" not in self.seen:
            self.seen.add("relic")
            print(f"  chest: {d['relics'][0]}" + ("" if d["relics"][0] in RELICS else " (not modeled)"))
            self.act("chest_relic 0")
        elif d["proceed"] and "relic" in self.seen:
            self.act("proceed")
        else:
            time.sleep(0.25)

    def do_map(self, d: dict) -> None:
        self.run.sync_map(d)
        a = self.ask("path")
        if a >= DRINK:
            slot = drink_slot(a)
            print(f"  drank {self.run.potions[slot]}")
            self.act(f"potion {slot}")
            return
        node = next(n for n in self.run.node.children if n.col == a - PATH)
        print(f"floor {node.row}: {node.type}  ({self.run.hp}/{self.run.max_hp} HP, {self.run.gold} gold)")
        self.act(f"map {node.col} {node.row}")

    # --- the run ------------------------------------------------------------------------------------

    def play(self) -> bool:
        self.client.full_restart()
        idle_since = time.monotonic()
        while True:
            s = self.client.state()
            screen, details = s.get("screen"), s.get("details")
            if not s.get("inRun"):
                raise RuntimeError("the run ended unexpectedly")
            self.run.sync(s)
            if s["floor"] != self.floor:
                self.floor, self.seen = s["floor"], set()
            if screen in ("combat", "gameOver") or self.run.hp <= 0:
                if screen == "combat":
                    room = s["roomType"]
                    self.play_fight()
                    p = self.client.state()["player"]
                    if p["hp"] <= 0:
                        print(f"died in a {room} fight on floor {self.floor}")
                        return False
                    print(f"  won, {p['hp']}/{p['maxHp']} HP")
                    if room == "Boss":
                        print(f"Act 1 cleared: {p['hp']}/{p['maxHp']} HP, {len(p['deck'])} cards, relics {sorted(self.run.relics)}")
                        return True
                else:
                    print(f"died on floor {self.floor}")
                    return False
            elif screen == "rewards":
                self.do_rewards(s["rewards"])
            elif screen == "cardReward":
                self.act(f"pick {self.pending_pick}")
            elif screen == "choice":
                self.do_choice(s["choice"])
            elif screen == "event" and details:
                self.do_event(details)
            elif screen == "rest" and details:
                if "rested" not in self.seen:
                    self.seen.add("rested")
                    print(f"  rest: {self.run.hp}/{self.run.max_hp} HP")
                    self.act(f"rest {details['options'].index('HEAL')}")
                elif details["proceed"]:
                    self.act("proceed")
                else:
                    time.sleep(0.25)
            elif screen == "shop" and details:
                self.do_shop(details)
            elif screen == "treasure" and details:
                self.do_treasure(details)
            elif screen == "map" and details:
                self.do_map(details)
            else:
                if time.monotonic() - idle_since > BUSY_LIMIT:
                    raise RuntimeError(f"stuck on screen {screen}: {json.dumps(s)[:600]}")
                time.sleep(0.25)
                continue
            idle_since = time.monotonic()


def live_run(model_path: str, run_model_path: str) -> bool:
    return LiveGame(model_path, run_model_path).play()
