"""Run policy env: one episode is one Act 1 run, one step is one out-of-combat decision.

A path step into a fight plays the whole fight with a frozen combat policy (or random legal
moves when combat_model is None, for tests). Spec: docs/superpowers/specs/2026-10-18-run-foundation-design.md
"""
from __future__ import annotations

import random
import traceback
from collections import Counter

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from env import CARD_IDS, HIVE_CARDS, STS2CombatEnv
from grow import insert_map
from picker import play_fight
from sim.act import ALL_BOSSES, BOSSES, SHOP_POTIONS, SHOP_RELICS, SHOP_SLOTS, Run
from sim.cards import CARDS, CHOICE_CARDS, base_id
from sim.engine import SimClient
from sim.events import EVENT_OPTIONS, MODELED_EVENTS
from sim.map import BOSS_ROW, COLS, ROOM_TYPES
from sim.potions import MAX_POTION_SLOTS, POTION_IDS, POTION_SLOTS, POTIONS
from sim.relics import RELIC_IDS, RELICS, UPGRADE_RELICS

DECISIONS = ("path", "pick", "shop", "remove", "potion")
HEAD_DECISIONS = DECISIONS[:4]  # the original observation head; "potion" is flagged in the appended block
# Actions: [path: one per column][pick: 3 cards, skip][shop: one per slot, remove, leave]
# [remove: one per card id, then an unused cancel slot] -- then, appended for grow.py:
# [potion: put in slot 0-2, skip][shop: buy potion 0-2][path: drink Blood Potion in slot 0-2]
PATH = 0
PICK = PATH + COLS
SHOP = PICK + 4
SHOP_REMOVE, SHOP_LEAVE = SHOP + len(SHOP_SLOTS), SHOP + len(SHOP_SLOTS) + 1
REMOVE = SHOP_LEAVE + 1
POTION_TAKE = REMOVE + len(CARD_IDS) + 1
POTION_SKIP = POTION_TAKE + POTION_SLOTS
SHOP_POTION = POTION_SKIP + 1
DRINK = SHOP_POTION + SHOP_POTIONS
# then relics and the Potion Belt slots 3-4 (the numbering is split; use potion_take_action / drink_action):
# [shop: buy relic 0-2][potion: put in slot 3-4][path: drink Blood Potion in slot 3-4]
SHOP_RELIC = DRINK + POTION_SLOTS
POTION_TAKE_2 = SHOP_RELIC + SHOP_RELICS
DRINK_2 = POTION_TAKE_2 + MAX_POTION_SLOTS - POTION_SLOTS
EVENT = DRINK_2 + MAX_POTION_SLOTS - POTION_SLOTS  # [event: option 0-1]
N_ACTIONS = EVENT + EVENT_OPTIONS


def potion_take_action(slot: int) -> int:
    return POTION_TAKE + slot if slot < POTION_SLOTS else POTION_TAKE_2 + slot - POTION_SLOTS


def drink_action(slot: int) -> int:
    return DRINK + slot if slot < POTION_SLOTS else DRINK_2 + slot - POTION_SLOTS


def potion_take_slot(a: int) -> int:
    return a - POTION_TAKE if a < POTION_SKIP else a - POTION_TAKE_2 + POTION_SLOTS


def drink_slot(a: int) -> int:
    return a - DRINK if a < SHOP_RELIC else a - DRINK_2 + POTION_SLOTS


CARD_INDEX = {c: i for i, c in enumerate(CARD_IDS)}
POTION_INDEX = {p: i for i, p in enumerate(POTION_IDS)}
FIGHTS = ("Monster", "Elite", "Boss")
LOOKAHEAD = 5  # map rows shown ahead of the current node
SLOT_FEATURES = len(CARD_IDS) + 2  # card one-hot, price / 100, affordable
CELL_FEATURES = len(ROOM_TYPES) + 1  # room type one-hot, reachable from here
SHOP_POTION_FEATURES = len(POTION_IDS) + 2  # potion one-hot, price / 100, buyable
RELIC_INDEX = {r: i for i, r in enumerate(RELIC_IDS)}
SHOP_RELIC_FEATURES = len(RELIC_IDS) + 2  # relic one-hot (zero if unmodeled), price / 100, buyable
# Appended: potion-decision flag, own slots, the offered potion, the shop's potions.
POTION_OBS = 1 + POTION_SLOTS * len(POTION_IDS) + len(POTION_IDS) + SHOP_POTIONS * SHOP_POTION_FEATURES
# Appended after that: Potion Belt slots 3-4, relics held, the shop's relics.
RELIC_OBS = (MAX_POTION_SLOTS - POTION_SLOTS) * len(POTION_IDS) + len(RELIC_IDS) + SHOP_RELICS * SHOP_RELIC_FEATURES
# Appended after that: event-decision flag, which event, each option's HP loss / gold / max HP, Slippery Bridge's card.
EVENT_OBS = 1 + len(MODELED_EVENTS) + EVENT_OPTIONS * 3 + len(CARD_IDS)
OBS_DIM = (len(HEAD_DECISIONS) + 5 + len(CARD_IDS) + len(ALL_BOSSES) + len(SHOP_SLOTS) * SLOT_FEATURES + 2
           + LOOKAHEAD * COLS * CELL_FEATURES + POTION_OBS + RELIC_OBS + EVENT_OBS + 1)  # + 1: which act
FLOOR_REWARD, CLEAR_REWARD = 0.1, 1.0
MAX_DECISIONS = 500  # a run is ~40 decisions; this only stops a broken env


class RandomCombat:
    """Stands in for a combat model in tests: a random legal action."""

    def __init__(self, rng: np.random.Generator):
        self.rng = rng

    def predict(self, obs, action_masks, deterministic=True):
        return self.rng.choice(np.flatnonzero(action_masks)), None


class RunPolicyEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, combat_model: str | None = None, event_practice: bool = False):
        super().__init__()
        self.event_practice = event_practice  # training only: real runs rarely meet an event at low HP
        self.action_space = spaces.Discrete(N_ACTIONS)
        self.observation_space = spaces.Box(low=-1.0, high=10.0, shape=(OBS_DIM,), dtype=np.float32)
        if combat_model:
            import torch
            from sb3_contrib import MaskablePPO
            torch.set_num_threads(1)  # n_envs of these share the CPU
            self.combat = MaskablePPO.load(combat_model, device="cpu")
        else:
            self.combat = RandomCombat(np.random.default_rng(0))
        self.fight_env = STS2CombatEnv(client=SimClient(), heal=False, episodes_per_restart=10**9)
        self.fight_env._episode_count = 1  # never full_restart: HP is synced from the run
        self.run: Run | None = None

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.run = Run(random.Random(int(self.np_random.integers(2**31))))
        self.fight_env.client = SimClient(seed=self.run.rng.randrange(2**31))
        self.decision, self.offered, self.room, self.back = "path", [], "Ancient", "path"
        self.done, self.cleared, self.steps, self.acts_cleared = False, False, 0, 0
        self.used: Counter = Counter()  # potion uses this run, by id
        self.choice_log: list = []  # (source, picked, options) of every card prompt in this run's fights
        return self._obs(), {}

    # --- the pieces MapRunModeEnv (run.py) reuses ------------------------------------------------

    def enter(self, col: int) -> str | None:
        """Path action: move to the child in that column. The encounter if it's a fight, else None."""
        node = next(n for n in self.run.choices() if n.col == col)
        self.room = self.run.enter(node)
        if self.room == "RestSite":
            self.run.rest("HEAL")  # Task 5: the policy picks
        self.run.elites_fought += self.room == "Elite"
        if self.room in FIGHTS:
            return self.run.encounter(self.room)
        self.back = "shop" if self.room == "Shop" else "path"
        if self.run.event:
            self.decision = "event"
            if self.event_practice and self.run.rng.random() < 0.5:  # HP >= 10: The Legends Were True's IsAllowed
                self.run.hp, self.run.gold = self.run.rng.randint(10, self.run.max_hp), self.run.rng.randint(0, 400)
            return None
        self._advance()  # Treasure and Rest can queue rewards (Tiny Mailbox)
        return None

    def _advance(self) -> None:
        """The next queued reward is the decision, else back to where the rewards started."""
        reward = self.run.next_reward()
        if reward is None:
            self.decision = self.back
        elif reward[0] == "cards":
            self.offered, self.decision = reward[1], "pick"
        else:
            self.decision = "potion"

    def after_fight(self, won: bool) -> tuple[float, bool]:
        """Reward and done after a fight; on a win, the card offer becomes the next decision."""
        if not won:
            self.done = True
            return 0.0, True
        offered = self.run.win(self.room)
        reward = FLOOR_REWARD
        if self.room == "Boss":
            reward += CLEAR_REWARD
            if self.run.act == 1:  # Act 2's boss: the end of the sim's run
                self.done = self.cleared = True
                return reward, True
            self.acts_cleared += 1
            self.run.next_act()
        self.offered, self.decision, self.back = offered, "pick", "path"
        return reward, False

    def play(self, encounter: str) -> bool:
        """One fight with HP, max HP, deck and potions carried in and out. A sim error ends it as a loss."""
        run, env = self.run, self.fight_env
        combat = env.client._combat
        combat.player_hp, combat.player_max_hp = run.hp, run.max_hp
        env.encounters, env.deck, env.potions = [encounter], list(run.deck), list(run.potions)
        env.relics, env.relic_state = run.relics, run.relic_state
        before = Counter(p for p in run.potions if p)
        try:
            won = play_fight(self.combat, env, seed=run.rng.randrange(2**31))[0]
        except Exception:  # noqa: BLE001 - one bad sim state must not kill a 6-env training run
            traceback.print_exc()
            return False
        combat = env.client._combat
        self.choice_log += combat.choice_log
        run.fight_hit = combat.lamp_hit
        run.hp, run.max_hp, run.potions = combat.player_hp, combat.player_max_hp, list(combat.potions)
        for card in combat.stolen:  # Thieving Hopper escaped with it
            run.deck.remove(card)
        self.used += before - Counter(p for p in run.potions if p)
        return won

    # --- gym API ---------------------------------------------------------------------------------

    def step(self, action: int):
        a = int(action)
        assert self.action_masks()[a], f"illegal action {a} for {self.decision}"
        self.steps += 1
        reward = 0.0
        if self.decision == "path" and a >= DRINK:
            self.run.drink(drink_slot(a))
            self.used["BLOOD_POTION"] += 1
        elif self.decision == "path":
            encounter = self.enter(a - PATH)
            if encounter is None:
                reward = FLOOR_REWARD
            else:
                reward, _ = self.after_fight(self.play(encounter))
        elif self.decision == "pick":
            if a - PICK < 3:
                self.run.add_card(self.offered[a - PICK])
            self._advance()
        elif self.decision == "potion":
            if a == POTION_SKIP:
                self.run.potion_drop = None
            else:
                self.run.take_potion(potion_take_slot(a))
            self._advance()
        elif self.decision == "event":
            self.run.choose_event(a - EVENT)
            if self.run.hp <= 0:
                self.done = True
            elif not self.run.event:
                self._advance()  # The Legends Were True can queue a potion
        elif self.decision == "shop":
            if a == SHOP_LEAVE:
                self.decision = self.back = "path"
            elif a == SHOP_REMOVE:
                self.decision = "remove"
            elif a >= SHOP_RELIC:
                self.run.buy_relic(a - SHOP_RELIC)
                self._advance()  # Orrery and Cauldron queue rewards
            elif a >= SHOP_POTION:
                self.run.buy_potion(a - SHOP_POTION)
            else:
                self.run.buy(a - SHOP)
        else:  # remove
            if a - REMOVE < len(CARD_IDS):
                self.run.remove(CARD_IDS[a - REMOVE])
            self.decision = "shop"
        truncated = not self.done and self.steps >= MAX_DECISIONS
        info = {"act": self.run.act, "acts_cleared": self.acts_cleared + self.cleared, "floor": self.run.node.row, "cleared": self.cleared, "gold": self.run.gold, "spent": self.run.spent,
                "died_at": f"A{self.run.act + 1}:{self.room}" if self.done and not self.cleared else None, "deck": list(self.run.deck),
                "potions_used": sum(self.used.values()), "potions_held": sum(p is not None for p in self.run.potions),
                "used": dict(self.used), "relic_log": list(self.run.relic_log),
                "relics_held": sorted(self.run.relics), "elites_fought": self.run.elites_fought,
                "events_seen": list(self.run.events_seen), "event_log": list(self.run.event_log),
                "choice_log": list(self.choice_log)}
        return self._obs(), reward, self.done, truncated, info

    def action_masks(self) -> np.ndarray:
        m = np.zeros(N_ACTIONS, dtype=bool)
        run = self.run
        if self.done:
            m[PATH + run.node.col] = True  # never consulted; keeps the mask non-empty after the end
        elif self.decision == "path":
            for n in run.choices():
                m[PATH + n.col] = True
            for i, p in enumerate(run.potions):
                m[drink_action(i)] = p == "BLOOD_POTION" and run.hp < run.max_hp
        elif self.decision == "pick":
            for i, c in enumerate(self.offered):
                m[PICK + i] = c in CARDS
            m[PICK + 3] = True
        elif self.decision == "shop":
            s = run.shop
            for i, (c, p) in enumerate(zip(s.cards, s.prices)):
                m[SHOP + i] = c in CARDS and run.gold >= run.price(p)
            m[SHOP_REMOVE] = not s.removal_used and run.gold >= run.price(s.removal_price)
            for k, (p, price) in enumerate(zip(s.potions, s.potion_prices)):
                m[SHOP_POTION + k] = p in POTIONS and run.gold >= run.price(price) and None in run.potions
            for k, (r, price) in enumerate(zip(s.relics, s.relic_prices)):
                m[SHOP_RELIC + k] = r in RELICS and run.gold >= run.price(price)
            m[SHOP_LEAVE] = True
        elif self.decision == "potion":
            for i in range(len(run.potions)):
                m[potion_take_action(i)] = True
            m[POTION_SKIP] = True
        elif self.decision == "event":
            m[EVENT:EVENT + EVENT_OPTIONS] = True
        else:
            for c in set(run.deck):  # no cancel: shop -> remove -> cancel would let a deterministic policy loop
                m[REMOVE + CARD_INDEX[base_id(c)]] = True
        return m

    def _obs(self) -> np.ndarray:
        run = self.run
        head = [float(d == self.decision) for d in HEAD_DECISIONS]
        head += [run.hp / 80, run.max_hp / 80, min(run.gold / 100, 10), run.node.row / BOSS_ROW, run.removals / 5]
        deck = np.zeros(len(CARD_IDS))
        for c in run.deck:
            deck[CARD_INDEX[base_id(c)]] += 0.5
        boss = [float(b == run.boss) for b in ALL_BOSSES]
        slots = np.zeros((len(SHOP_SLOTS), SLOT_FEATURES))
        removal = [0.0, 0.0]
        if self.decision == "pick":
            for i, c in enumerate(self.offered):
                if c in CARD_INDEX:
                    slots[i, CARD_INDEX[c]] = 1
        elif self.decision in ("shop", "remove"):
            s = run.shop
            for i, (c, p) in enumerate(zip(s.cards, s.prices)):
                if c in CARD_INDEX:
                    slots[i, CARD_INDEX[c]], slots[i, -2], slots[i, -1] = 1, run.price(p) / 100, run.gold >= run.price(p)
            removal = [run.price(s.removal_price) / 100, float(not s.removal_used and run.gold >= run.price(s.removal_price))]
        grid = np.zeros((LOOKAHEAD, COLS, CELL_FEATURES))
        reach, todo = set(), list(run.node.children)
        while todo:
            n = todo.pop()
            if id(n) not in reach and n.row <= run.node.row + LOOKAHEAD:
                reach.add(id(n))
                todo += n.children
        for n in list(run.map.grid.values()) + [run.map.boss]:
            k = n.row - run.node.row - 1
            if 0 <= k < LOOKAHEAD:
                grid[k, n.col, ROOM_TYPES.index(n.type)] = 1
                grid[k, n.col, -1] = id(n) in reach
        own = [float(p == pid) for p in run.potions[:POTION_SLOTS] for pid in POTION_IDS]
        drop = [float(self.decision == "potion" and run.potion_drop == pid) for pid in POTION_IDS]
        shop_p = np.zeros((SHOP_POTIONS, SHOP_POTION_FEATURES))
        if self.decision in ("shop", "remove"):
            for k, (p, price) in enumerate(zip(run.shop.potions, run.shop.potion_prices)):
                if p in POTION_INDEX:
                    shop_p[k, POTION_INDEX[p]], shop_p[k, -2] = 1, run.price(price) / 100
                    shop_p[k, -1] = run.gold >= run.price(price) and None in run.potions
        potion_obs = [float(self.decision == "potion")] + own + drop + list(shop_p.ravel())
        belt = [float(p == pid) for p in run.potions[POTION_SLOTS:] for pid in POTION_IDS]
        belt += [0.0] * ((MAX_POTION_SLOTS - len(run.potions)) * len(POTION_IDS))
        held = [float(r in run.relics) for r in RELIC_IDS]
        shop_r = np.zeros((SHOP_RELICS, SHOP_RELIC_FEATURES))
        if self.decision in ("shop", "remove"):
            for k, (r, price) in enumerate(zip(run.shop.relics, run.shop.relic_prices)):
                if r:  # unmodeled: zero one-hot, but the price shows the slot is taken
                    if r in RELIC_INDEX:
                        shop_r[k, RELIC_INDEX[r]] = 1
                    shop_r[k, -2], shop_r[k, -1] = run.price(price) / 100, r in RELICS and run.gold >= run.price(price)
        event_obs = np.zeros(EVENT_OBS)
        if run.event:
            event_obs[0] = 1
            event_obs[1 + MODELED_EVENTS.index(run.event)] = 1
            k = 1 + len(MODELED_EVENTS)
            for i, (hp, gold, max_hp) in enumerate(run.event_opts):
                event_obs[k + 3 * i:k + 3 * i + 3] = hp / 80, gold / 100, max_hp / 80
            if run.event == "SLIPPERY_BRIDGE":
                event_obs[k + 3 * EVENT_OPTIONS + CARD_INDEX[base_id(run.deck[run.bridge_card])]] = 1
        return np.concatenate([head, np.minimum(deck, 10), boss, slots.ravel(), removal, grid.ravel(),
                               potion_obs, belt, held, shop_r.ravel(), event_obs, [float(getattr(run, "act", 0))]]).astype(np.float32)


def run_maps() -> tuple[list[int], list[int]]:
    """(obs_map, act_map) for grow.py: where a run policy trained before Act 2 keeps its inputs and actions."""
    old_ids = sorted(set(CARD_IDS) - HIVE_CARDS)
    old_relics = [r for r in RELIC_IDS if r not in UPGRADE_RELICS]
    lead = 2 + LOOKAHEAD * COLS * CELL_FEATURES + POTION_OBS + (MAX_POTION_SLOTS - POTION_SLOTS) * len(POTION_IDS)  # up to the relics held
    tail = 1 + len(MODELED_EVENTS) + EVENT_OPTIONS * 3  # after the shop's relics
    obs = [len(HEAD_DECISIONS) + 5, "cards", (list(BOSSES), list(ALL_BOSSES))] + ["cards", 2] * len(SHOP_SLOTS)
    obs += [lead, (old_relics, RELIC_IDS)] + [(old_relics, RELIC_IDS), 2] * SHOP_RELICS + [tail, "cards"]
    return insert_map(obs, old_ids, CARD_IDS), insert_map([REMOVE, "cards", N_ACTIONS - REMOVE - len(CARD_IDS)], old_ids, CARD_IDS)
