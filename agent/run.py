"""Whole Act 1 runs: HP and deck carry from fight to fight, with a card offer after each win.

ACT1_PATH is one representative route — 3 weak hallway fights, 5 normal, 2 elites, 3 rest sites,
the boss — with Burning Blood (the Ironclad's starter relic: +6 HP after each win) and rest
sites healing 30% of max HP (HealRestSiteOption.cs). ponytail: no events, shops, treasure,
relic/potion rewards or map choice; add them as the sim grows.

Compare pick strategies over simulated runs:
    python run.py --model models/ppo_sts2_sim_act1_run_v9_final.zip --runs 200
Play one real Act 1 in the live game, with the run policy making every choice (live.py):
    python run.py --model models/ppo_sts2_sim_act1_pc_v14_final.zip --run-model models/ppo_sts2_sim_run_policy_v7_final.zip --live
Compare on generated maps (shops, ? rooms), baseline vs a run policy:
    python run.py --model models/ppo_sts2_sim_act1_run_v9_final.zip --maps generated --run-model models/ppo_sts2_sim_run_policy_v1_final.zip --runs 500 --n 16

RunModeEnv is the training version: one fight per episode, but each fight starts where the run
left off (HP, deck grown by random picks), so the policy sees low-HP and late-run states.
"""
from __future__ import annotations

import argparse
import random
from collections import Counter
from multiprocessing import Pool

import gymnasium as gym
import numpy as np
from sb3_contrib import MaskablePPO

from env import BOSS_ENCOUNTERS, ELITE_ENCOUNTERS, NORMAL_ENCOUNTERS, WEAK_ENCOUNTERS, STS2CombatEnv
from picker import RarityOdds, offer, pick, play_fight
from run_env import (CARD_INDEX, EVENT, PATH, PICK, POTION_SKIP, REMOVE, SHOP_LEAVE, SHOP_REMOVE, RandomCombat,
                     RunPolicyEnv, potion_take_action)
from choice_test import is_good, is_junk
from sim.cards import CARDS, CHOICE_CARDS, starter_deck
from sim.engine import SimClient
from sim.events import EVENT_OPTIONS, MODELED_EVENTS
from sim.map import COLS
from sim.relics import RELICS, relic_rarity

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
        # HP lost carries into every later fight, so it costs 3x the damage-dealt reward here
        super().__init__(client=SimClient(), heal=False, episodes_per_restart=10**9, hp_weight=3.0, **kwargs)
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


class MapRunModeEnv(STS2CombatEnv):
    """Combat training on generated maps: one fight per episode, with the run policy making every
    choice between fights, so combat trains on the decks and HP the run policy actually builds."""

    def __init__(self, run_model: str | None = None, **kwargs):
        super().__init__(client=SimClient(), heal=False, episodes_per_restart=10**9, hp_weight=3.0, **kwargs)
        if run_model:
            import torch
            torch.set_num_threads(1)
            self.run_model = MaskablePPO.load(run_model, device="cpu")
        else:
            self.run_model = RandomCombat(np.random.default_rng())  # random legal run decisions
        self.driver = RunPolicyEnv()  # only its run logic is used; fights are this env's episodes
        self.driver.done = True  # start a run on the first reset

    def _next_fight(self) -> str:
        """Apply run-policy decisions until the next fight, starting a new run when one has ended."""
        d = self.driver
        while True:
            if d.done:
                d.reset(seed=int(self.np_random.integers(2**31)))
            action = int(self.run_model.predict(d._obs(), action_masks=d.action_masks(), deterministic=False)[0])
            if d.decision == "path" and action < PATH + COLS:  # drinking goes through d.step
                encounter = d.enter(action - PATH)
                if encounter:
                    return encounter
            else:
                d.step(action)

    def reset(self, *, seed=None, options=None):
        if seed is not None:
            self.np_random, _ = gym.utils.seeding.np_random(seed)
        encounter = self._next_fight()
        run, combat = self.driver.run, self.client._combat
        combat.player_hp, combat.player_max_hp = run.hp, run.max_hp
        self.encounters, self.deck, self.potions = [encounter], list(run.deck), list(run.potions)
        self.relics, self.relic_state = run.relics, run.relic_state
        self._episode_count = 1  # never full_restart: HP is synced from the run
        return super().reset(seed=seed, options=options)

    def step(self, action):
        obs, reward, terminated, truncated, info = super().step(action)
        if terminated or truncated:
            run, combat = self.driver.run, self.client._combat
            run.hp, run.max_hp, run.potions = combat.player_hp, combat.player_max_hp, list(combat.potions)
            self.driver.after_fight(bool(info.get("won")) and not truncated)
        return obs, reward, terminated, truncated, info


_model = None
_run_model = None


def _init(model_path: str, run_model_path: str | None = None) -> None:
    global _model, _run_model
    _model = MaskablePPO.load(model_path)
    _run_model = MaskablePPO.load(run_model_path) if run_model_path else None


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


def baseline_action(env: RunPolicyEnv, rng: random.Random, n: int) -> int:
    """The pre-run-policy way to play: random path, MC card picks, remove a Strike when affordable."""
    mask = env.action_masks()
    if env.decision == "path":
        return int(rng.choice(np.flatnonzero(mask[PATH:PATH + COLS]))) + PATH
    if env.decision == "pick":
        choice = choose("mc", _model, env.run.deck, env.offered, rng, n)
        return PICK + (env.offered.index(choice) if choice else 3)
    if env.decision == "shop":
        return SHOP_REMOVE if mask[SHOP_REMOVE] and "STRIKE_IRONCLAD" in env.run.deck else SHOP_LEAVE
    if env.decision == "event":
        return EVENT + rng.randrange(EVENT_OPTIONS)
    if env.decision == "potion":  # take it into a free slot, never replace
        return potion_take_action(env.run.potions.index(None)) if None in env.run.potions else POTION_SKIP
    return REMOVE + CARD_INDEX["STRIKE_IRONCLAD"]


def generated_run(args: tuple[str, int, int]) -> dict:
    """One run on generated map `seed`: every strategy sees the same map and encounter queue."""
    strategy, seed, n = args
    env = RunPolicyEnv()
    env.combat = _model
    obs, _ = env.reset(seed=seed)
    rng, done, truncated, info = random.Random(seed), False, False, {}
    while not (done or truncated):
        if strategy == "policy":
            action = int(_run_model.predict(obs, action_masks=env.action_masks(), deterministic=True)[0])
        else:
            action = baseline_action(env, rng, n)
        obs, _, done, truncated, info = env.step(action)
    return {"strategy": strategy, **info}


def honesty(rs: list[dict]) -> str:
    """Do rolled relic drops match the game's odds? Treasure's pool lacks the Ironclad relics, so its unmodeled share differs."""
    parts = []
    for src, expect in (("elite", 11.6), ("treasure", 12.3)):
        drops = [r for run in rs for r, s in run["relic_log"] if s == src]
        share = lambda f: f"{100 * sum(f(r) for r in drops) / max(len(drops), 1):.0f}%"
        parts.append(f"{src} n={len(drops)} " + " ".join(f"{k}={share(lambda r, k=k: relic_rarity(r) == k.upper())}"
                     for k in ("common", "uncommon", "rare")) + f" unmodeled={share(lambda r: r not in RELICS)}"
                     f" (expect 50/33/17, {expect})")
    return "honesty: " + " | ".join(parts) + f" | bought n={sum(s == 'shop' for run in rs for _, s in run['relic_log'])}"


def event_report(rs: list[dict]) -> str:
    """Does the policy's choice change with its situation? Option 1's rate, split at half HP and at 100 gold."""
    seen = [e for run in rs for e in run["events_seen"]]
    lines = [f"events: {len(seen) / max(len(rs), 1):.2f} per run, {100 * sum(e in MODELED_EVENTS for e in seen) / max(len(seen), 1):.0f}% modeled"]
    log = [c for run in rs for c in run["event_log"]]
    rate = lambda cs: f"{100 * np.mean([c[1] for c in cs]):.0f}% of {len(cs)}" if cs else "n=0"
    for event in MODELED_EVENTS:
        cs = [c for c in log if c[0] == event]
        low, rich = [c for c in cs if c[2] * 2 < c[3]], [c for c in cs if c[4] >= 100]
        lines.append(f"  {event}{' (per hold decision)' if event == 'SLIPPERY_BRIDGE' else ''}: option 1 {rate(cs)} | HP<50% {rate(low)} | HP>=50% {rate([c for c in cs if c[2] * 2 >= c[3]])}"
                     f" | gold>=100 {rate(rich)} | gold<100 {rate([c for c in cs if c[4] < 100])}")
    return "\n".join(lines)


def choice_report(rs: list[dict]) -> str:
    """What the run's fights asked the policy to pick: per prompt card, count and share that took a junk card
    (Headbutt: a non-basic, non-junk card), among prompts offering both kinds."""
    log = [c for run in rs for c in run["choice_log"]]
    parts = []
    for card in CHOICE_CARDS:
        cs = [c for c in log if c[0] == card]
        is_kind = is_good if card == "HEADBUTT" else is_junk
        mixed = [c for c in cs if len({is_kind(o) for o in c[2]}) == 2]
        share = f"{100 * sum(is_kind(c[1]) for c in mixed) / len(mixed):.0f}% of {len(mixed)}" if mixed else "n=0"
        parts.append(f"{card}: {len(cs)} ({'non-basic non-junk' if card == 'HEADBUTT' else 'junk'} {share})")
    return "choices: " + " | ".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--runs", type=int, default=200)
    ap.add_argument("--n", type=int, default=24, help="fights simulated per pick candidate")
    ap.add_argument("--strategies", default="skip,random,mc")
    ap.add_argument("--live", action="store_true", help="play one run in the live game instead")
    ap.add_argument("--maps", choices=["fixed", "generated"], default="fixed",
                    help="fixed: ACT1_PATH; generated: sim/map.py maps with shops and ? rooms")
    ap.add_argument("--run-model", default=None, help="run policy zip (adds the 'policy' strategy on generated maps)")
    args = ap.parse_args()
    if args.live:
        if not args.run_model:
            ap.error("--live needs --run-model")
        from live import live_run
        return live_run(args.model, args.run_model)
    if args.maps == "generated":
        strategies = ["baseline"] + (["policy"] if args.run_model else [])
        with Pool(initializer=_init, initargs=(args.model, args.run_model)) as pool:
            results = pool.map(generated_run, [(s, seed, args.n) for s in strategies for seed in range(args.runs)])
        for s in strategies:
            rs = [r for r in results if r["strategy"] == s]
            died = Counter(r["died_at"] for r in rs if r["died_at"])
            died_runs = [r for r in rs if r["died_at"]]
            used = sum((Counter(r["used"]) for r in rs), Counter())
            print(f"{s:8} cleared={np.mean([r['cleared'] for r in rs]):.1%}  floor={np.mean([r['floor'] for r in rs]):.1f}"
                  f"/16  spent={np.mean([r['spent'] for r in rs]):.0f}  died_at={dict(died)}"
                  f"  stuck={sum(not r['cleared'] and not r['died_at'] for r in rs)}"  # hit MAX_DECISIONS
                  f"  potions_used={np.mean([r['potions_used'] for r in rs]):.2f}"
                  f"  held_at_death={np.mean([r['potions_held'] for r in died_runs]) if died_runs else 0:.2f}"
                  f"  relics={np.mean([sum(x != 'SWORD_OF_STONE' for x in r['relics_held']) for r in rs]):.2f}"
                  f"  elites={np.mean([r['elites_fought'] for r in rs]):.2f}")
            print("         " + honesty(rs))
            print(event_report(rs))
            print(choice_report(rs))
            print(f"         used: {dict(used.most_common())}")
        return
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
