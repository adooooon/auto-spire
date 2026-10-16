"""Whole Act 1 runs: HP and deck carry from fight to fight, with a card offer after each win.

ACT1_PATH is one representative route — 3 weak hallway fights, 5 normal, 2 elites, 3 rest sites,
the boss — with Burning Blood (the Ironclad's starter relic: +6 HP after each win) and rest
sites healing 30% of max HP (HealRestSiteOption.cs). ponytail: no events, shops, treasure,
relic/potion rewards or map choice; add them as the sim grows.

Compare pick strategies over simulated runs:
    python run.py --model models/ppo_sts2_sim_act1_full_v6_final.zip --runs 200
Play one run in the live game, picking from its real reward screens:
    python run.py --model models/ppo_sts2_sim_act1_full_v6_final.zip --live

RunModeEnv is the training version: one fight per episode, but each fight starts where the run
left off (HP, deck grown by random picks), so the policy sees low-HP and late-run states.
"""
from __future__ import annotations

import argparse
import random
import time
from collections import Counter
from multiprocessing import Pool

import numpy as np
from sb3_contrib import MaskablePPO

from client import AutoSpireClient
from env import BOSS_ENCOUNTERS, ELITE_ENCOUNTERS, NORMAL_ENCOUNTERS, WEAK_ENCOUNTERS, STS2CombatEnv
from picker import RarityOdds, offer, pick, play_fight
from sim.cards import CARDS, starter_deck
from sim.engine import SimClient

ACT1_PATH = ["weak", "weak", "weak", "normal", "normal", "rest", "elite", "normal", "normal", "rest",
             "elite", "normal", "rest", "boss"]
NODE_ENCOUNTERS = {"weak": WEAK_ENCOUNTERS, "normal": NORMAL_ENCOUNTERS, "elite": ELITE_ENCOUNTERS,
                   "boss": BOSS_ENCOUNTERS}
FIGHTS = [n for n in ACT1_PATH if n != "rest"]
PICK_ENCOUNTERS = NORMAL_ENCOUNTERS + ELITE_ENCOUNTERS  # what a pick is scored against
BURNING_BLOOD_HEAL = 6
REST_HEAL = 24


def choose(strategy: str, model, deck: list[str], offered: list[str], rng: random.Random, n: int) -> str | None:
    pickable = [c for c in offered if c in CARDS]
    if strategy == "mc" and pickable:
        return pick(model, deck, offered, PICK_ENCOUNTERS, n=n, seed=rng.randrange(2**31))
    if strategy == "random":
        return rng.choice([None] + pickable)
    return None


class RunModeEnv(STS2CombatEnv):
    """Sim training env: one fight per episode, but fights chain through ACT1_PATH."""

    def __init__(self, **kwargs):
        super().__init__(client=SimClient(), heal=False, episodes_per_restart=10**9, **kwargs)
        self._rng = random.Random()
        self._node = len(ACT1_PATH)  # forces a new run on the first reset

    def reset(self, *, seed=None, options=None):
        if seed is not None:
            self._rng.seed(seed)
        if self._node >= len(ACT1_PATH):  # new run: full HP, starter deck
            self.client.full_restart()
            self._node, self.deck, self._odds = 0, starter_deck(), RarityOdds()
        while ACT1_PATH[self._node] == "rest":
            self.client._combat.heal(REST_HEAL)
            self._node += 1
        self.encounters = list(NODE_ENCOUNTERS[ACT1_PATH[self._node]])
        self._episode_count = 1  # keep the run's SimCombat
        return super().reset(seed=seed, options=options)

    def step(self, action):
        obs, reward, terminated, truncated, info = super().step(action)
        if terminated or truncated:
            if info.get("won"):
                self.client._combat.heal(BURNING_BLOOD_HEAL)
                choice = choose("random", None, self.deck, offer(self._rng, self._odds,
                                ACT1_PATH[self._node] == "elite"), self._rng, 0)
                self.deck = self.deck + ([choice] if choice else [])
                self._node += 1
            else:
                self._node = len(ACT1_PATH)  # run over
        return obs, reward, terminated, truncated, info


_model = None


def _init(model_path: str) -> None:
    global _model
    _model = MaskablePPO.load(model_path)


def sim_run(args: tuple[str, int, int]) -> dict:
    strategy, seed, n = args
    rng = random.Random(seed)
    odds, deck = RarityOdds(), starter_deck()
    env = STS2CombatEnv(client=SimClient(seed=seed), heal=False)
    env._episode_count = 1  # keep the SimCombat (and its HP) across fights
    combat, won, died_at = env.client._combat, 0, None
    for node in ACT1_PATH:
        if node == "rest":
            combat.heal(REST_HEAL)
            continue
        env.encounters, env.deck = list(NODE_ENCOUNTERS[node]), deck
        ok, _ = play_fight(_model, env, seed=rng.randrange(2**31))
        if not ok:
            died_at = node
            break
        won += 1
        combat.heal(BURNING_BLOOD_HEAL)
        if node != "boss":
            choice = choose(strategy, _model, deck, offer(rng, odds, node == "elite"), rng, n)
            deck = deck + ([choice] if choice else [])
    return {"strategy": strategy, "won": won, "cleared": won == len(FIGHTS), "died_at": died_at,
            "hp": combat.player_hp if won == len(FIGHTS) else 0, "deck": deck[10:]}


def live_run(model_path: str, n: int) -> None:
    """One run in the live game. Burning Blood is the game's own; rest sites are `heal 24`."""
    model = MaskablePPO.load(model_path)
    rng = random.Random()
    client = AutoSpireClient()
    env = STS2CombatEnv(client=client, heal=False)  # first reset full_restarts into a fresh run
    deck = starter_deck()
    for node in ACT1_PATH:
        if node == "rest":
            client.exec(f"heal {REST_HEAL}")
            print(f"rest: -> {client.state()['player']['hp']} HP")
            continue
        env.encounters, env.deck = list(NODE_ENCOUNTERS[node]), deck
        ok, _ = play_fight(model, env)
        if not ok:
            print(f"{node} fight lost — run over")
            return
        if node == "boss":
            break
        rewards = None
        for _ in range(40):  # the rewards screen opens shortly after the win
            rewards = client.state().get("rewards")
            if rewards:
                break
            time.sleep(0.25)
        offered = next(([c["id"] for c in r["cards"]] for r in rewards or [] if r.get("cards")), [])
        choice = choose("mc", model, deck, offered, rng, n)
        deck = deck + ([choice] if choice else [])
        print(f"{node} won, {client.state()['player']['hp']} HP; offered {offered} -> {choice or 'skip'}")
    print(f"Act 1 cleared: {client.state()['player']['hp']} HP, deck +{deck[10:]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--runs", type=int, default=200)
    ap.add_argument("--n", type=int, default=24, help="fights simulated per pick candidate")
    ap.add_argument("--strategies", default="skip,random,mc")
    ap.add_argument("--live", action="store_true", help="play one run in the live game instead")
    args = ap.parse_args()
    if args.live:
        return live_run(args.model, args.n)
    strategies = args.strategies.split(",")
    with Pool(initializer=_init, initargs=(args.model,)) as pool:
        results = pool.map(sim_run, [(s, seed, args.n) for s in strategies for seed in range(args.runs)])
    for s in strategies:
        rs = [r for r in results if r["strategy"] == s]
        died = Counter(r["died_at"] for r in rs if r["died_at"])
        print(f"{s:7} cleared={np.mean([r['cleared'] for r in rs]):.1%}  fights_won={np.mean([r['won'] for r in rs]):.2f}"
              f"/{len(FIGHTS)}  end_hp={np.mean([r['hp'] for r in rs]):.1f}  died_at={dict(died)}")


if __name__ == "__main__":
    main()
