"""Run policy env: one episode is one Act 1 run, one step is one out-of-combat decision.

A path step into a fight plays the whole fight with a frozen combat policy (or random legal
moves when combat_model is None, for tests). Spec: docs/superpowers/specs/2026-10-18-run-foundation-design.md
"""
from __future__ import annotations

import random
import traceback

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from env import CARD_IDS, STS2CombatEnv
from picker import play_fight
from sim.act import BOSSES, SHOP_SLOTS, Run
from sim.cards import CARDS
from sim.engine import SimClient
from sim.map import BOSS_ROW, COLS, ROOM_TYPES

DECISIONS = ("path", "pick", "shop", "remove")
# Actions: [path: one per column][pick: 3 cards, skip][shop: one per slot, remove, leave][remove: one per card id, then an unused cancel slot]
PATH = 0
PICK = PATH + COLS
SHOP = PICK + 4
SHOP_REMOVE, SHOP_LEAVE = SHOP + len(SHOP_SLOTS), SHOP + len(SHOP_SLOTS) + 1
REMOVE = SHOP_LEAVE + 1
N_ACTIONS = REMOVE + len(CARD_IDS) + 1
CARD_INDEX = {c: i for i, c in enumerate(CARD_IDS)}
FIGHTS = ("Monster", "Elite", "Boss")
LOOKAHEAD = 5  # map rows shown ahead of the current node
SLOT_FEATURES = len(CARD_IDS) + 2  # card one-hot, price / 100, affordable
CELL_FEATURES = len(ROOM_TYPES) + 1  # room type one-hot, reachable from here
OBS_DIM = (len(DECISIONS) + 5 + len(CARD_IDS) + len(BOSSES) + len(SHOP_SLOTS) * SLOT_FEATURES + 2
           + LOOKAHEAD * COLS * CELL_FEATURES)
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

    def __init__(self, combat_model: str | None = None):
        super().__init__()
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
        self.decision, self.offered, self.room = "path", [], "Ancient"
        self.done, self.cleared, self.steps = False, False, 0
        return self._obs(), {}

    # --- the pieces MapRunModeEnv (run.py) reuses ------------------------------------------------

    def enter(self, col: int) -> str | None:
        """Path action: move to the child in that column. The encounter if it's a fight, else None."""
        node = next(n for n in self.run.choices() if n.col == col)
        self.room = self.run.enter(node)
        if self.room in FIGHTS:
            return self.run.encounter(self.room)
        self.decision = "shop" if self.room == "Shop" else "path"
        return None

    def after_fight(self, won: bool) -> tuple[float, bool]:
        """Reward and done after a fight; on a win, the card offer becomes the next decision."""
        if not won:
            self.done = True
            return 0.0, True
        offered = self.run.win(self.room)
        if self.room == "Boss":
            self.done = self.cleared = True
            return FLOOR_REWARD + CLEAR_REWARD, True
        self.offered, self.decision = offered, "pick"
        return FLOOR_REWARD, False

    def play(self, encounter: str) -> bool:
        """One fight with HP, max HP and deck carried in and out. A sim error ends it as a loss."""
        run, env = self.run, self.fight_env
        combat = env.client._combat
        combat.player_hp, combat.player_max_hp = run.hp, run.max_hp
        env.encounters, env.deck = [encounter], list(run.deck)
        try:
            won = play_fight(self.combat, env, seed=run.rng.randrange(2**31))[0]
        except Exception:  # noqa: BLE001 - one bad sim state must not kill a 6-env training run
            traceback.print_exc()
            return False
        combat = env.client._combat
        run.hp, run.max_hp = combat.player_hp, combat.player_max_hp
        return won

    # --- gym API ---------------------------------------------------------------------------------

    def step(self, action: int):
        a = int(action)
        assert self.action_masks()[a], f"illegal action {a} for {self.decision}"
        self.steps += 1
        reward = 0.0
        if self.decision == "path":
            encounter = self.enter(a - PATH)
            if encounter is None:
                reward = FLOOR_REWARD
            else:
                reward, _ = self.after_fight(self.play(encounter))
        elif self.decision == "pick":
            if a - PICK < 3:
                self.run.deck.append(self.offered[a - PICK])
            self.decision = "path"
        elif self.decision == "shop":
            if a == SHOP_LEAVE:
                self.decision = "path"
            elif a == SHOP_REMOVE:
                self.decision = "remove"
            else:
                self.run.buy(a - SHOP)
        else:  # remove
            if a - REMOVE < len(CARD_IDS):
                self.run.remove(CARD_IDS[a - REMOVE])
            self.decision = "shop"
        truncated = not self.done and self.steps >= MAX_DECISIONS
        info = {"floor": self.run.node.row, "cleared": self.cleared, "gold": self.run.gold, "spent": self.run.spent,
                "died_at": self.room if self.done and not self.cleared else None, "deck": list(self.run.deck)}
        return self._obs(), reward, self.done, truncated, info

    def action_masks(self) -> np.ndarray:
        m = np.zeros(N_ACTIONS, dtype=bool)
        run = self.run
        if self.done:
            m[PATH + run.node.col] = True  # never consulted; keeps the mask non-empty after the end
        elif self.decision == "path":
            for n in run.choices():
                m[PATH + n.col] = True
        elif self.decision == "pick":
            for i, c in enumerate(self.offered):
                m[PICK + i] = c in CARDS
            m[PICK + 3] = True
        elif self.decision == "shop":
            s = run.shop
            for i, (c, p) in enumerate(zip(s.cards, s.prices)):
                m[SHOP + i] = c in CARDS and run.gold >= p
            m[SHOP_REMOVE] = not s.removal_used and run.gold >= s.removal_price
            m[SHOP_LEAVE] = True
        else:
            for c in set(run.deck):  # no cancel: shop -> remove -> cancel would let a deterministic policy loop
                m[REMOVE + CARD_INDEX[c]] = True
        return m

    def _obs(self) -> np.ndarray:
        run = self.run
        head = [float(d == self.decision) for d in DECISIONS]
        head += [run.hp / 80, run.max_hp / 80, run.gold / 100, run.node.row / BOSS_ROW, run.removals / 5]
        deck = np.zeros(len(CARD_IDS))
        for c in run.deck:
            deck[CARD_INDEX[c]] += 0.5
        boss = [float(b == run.boss) for b in BOSSES]
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
                    slots[i, CARD_INDEX[c]], slots[i, -2], slots[i, -1] = 1, p / 100, run.gold >= p
            removal = [s.removal_price / 100, float(not s.removal_used and run.gold >= s.removal_price)]
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
        return np.concatenate([head, np.minimum(deck, 10), boss, slots.ravel(), removal, grid.ravel()]).astype(np.float32)
