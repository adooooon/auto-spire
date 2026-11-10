"""Why are Act 2 boss fights lost? Play policy runs on generated maps and log each Act 2 boss fight.

    python boss_report.py --model models/<combat>.zip --run-model models/<run>.zip --runs 1500 --n 16 --out boss.jsonl
    python boss_report.py --summarize boss.jsonl

One JSON line per boss fight: seed, boss, won, hp, max_hp (at arrival), deck, relics, potions (at arrival),
potions_used, turns, hp_by_turn (player HP at the start of each player turn). --n is accepted for run.py
parity; the policy strategy makes no MC card picks, so it is unused.
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from multiprocessing import Pool

import numpy as np
from sb3_contrib import MaskablePPO

from run_env import RunPolicyEnv
from sim.engine import HIVE_BOSSES

_model = _run_model = None


def _init(model_path: str, run_model_path: str) -> None:
    global _model, _run_model
    _model = MaskablePPO.load(model_path)
    _run_model = MaskablePPO.load(run_model_path)


class Recorder:
    """Stands in for the combat model: delegates predict, noting the round and HP at each player turn."""

    def __init__(self, model, env):
        self.model, self.env, self.hp_by_turn = model, env, []

    def predict(self, obs, **kwargs):
        combat = self.env.client._combat
        if combat.round > len(self.hp_by_turn):  # first decision of a new player turn
            self.hp_by_turn.append(combat.player_hp)
        return self.model.predict(obs, **kwargs)


class BossEnv(RunPolicyEnv):
    def __init__(self):
        super().__init__()
        self.fights: list[dict] = []

    def play(self, encounter: str) -> bool:
        if encounter not in HIVE_BOSSES:
            return super().play(encounter)
        run, model = self.run, self.combat
        rec = {"boss": encounter, "hp": run.hp, "max_hp": run.max_hp, "deck": list(run.deck),
               "relics": sorted(run.relics), "potions": [p for p in run.potions if p]}
        held = Counter(rec["potions"])
        self.combat = recorder = Recorder(model, self.fight_env)
        try:
            won = super().play(encounter)
        finally:
            self.combat = model
        rec.update(won=won, potions_used=sum((held - Counter(p for p in run.potions if p)).values()),
                   turns=len(recorder.hp_by_turn), hp_by_turn=recorder.hp_by_turn)
        self.fights.append(rec)
        return won


def boss_run(seed: int) -> list[dict]:
    env = BossEnv()
    env.combat = _model
    obs, _ = env.reset(seed=seed)
    done = truncated = False
    while not (done or truncated):
        action = int(_run_model.predict(obs, action_masks=env.action_masks(), deterministic=True)[0])
        obs, _, done, truncated, _ = env.step(action)
    return [{"seed": seed, **f} for f in env.fights]


def summarize(fights: list[dict]) -> None:
    for boss in HIVE_BOSSES:
        fs = [f for f in fights if f["boss"] == boss]
        if not fs:
            print(f"{boss}: no fights")
            continue
        losses = [f for f in fs if not f["won"]]
        deaths = [f["turns"] for f in losses]
        # damage per turn: HP lost from arrival to the last turn start, over the turns before it
        dmg = [(f["hp"] - f["hp_by_turn"][-1]) / (f["turns"] - 1) for f in fs if f["turns"] > 1]
        top = ", ".join(f"{c} {n}" for c, n in sum((Counter(f["deck"]) for f in fs), Counter()).most_common(10))
        print(f"{boss}: reached {len(fs)}, won {len(fs) - len(losses)} ({100 * (len(fs) - len(losses)) / len(fs):.0f}%)\n"
              f"  arrival hp {np.mean([f['hp'] for f in fs]):.1f}/{np.mean([f['max_hp'] for f in fs]):.1f}"
              f"  deck {np.mean([len(f['deck']) for f in fs]):.1f} cards  relics {np.mean([len(f['relics']) for f in fs]):.1f}"
              f"  potions held {np.mean([len(f['potions']) for f in fs]):.2f} used {np.mean([f['potions_used'] for f in fs]):.2f}\n"
              f"  turn of death: " + (f"median {statistics.median(deaths):g}, range {min(deaths)}-{max(deaths)}, sd {np.std(deaths):.1f}" if deaths else "n/a")
              + f"\n  mean damage per turn (pre-final turns): {np.mean(dmg) if dmg else 0:.1f}\n  top cards: {top}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model")
    ap.add_argument("--run-model")
    ap.add_argument("--runs", type=int, default=200)
    ap.add_argument("--n", type=int, default=16, help="unused by the policy strategy; run.py parity")
    ap.add_argument("--out")
    ap.add_argument("--summarize", help="print the table for an existing JSONL and exit")
    args = ap.parse_args()
    if args.summarize:
        return summarize([json.loads(line) for line in open(args.summarize)])
    if not (args.model and args.run_model and args.out):
        ap.error("--model, --run-model and --out are required")
    with Pool(initializer=_init, initargs=(args.model, args.run_model)) as pool:
        fights = [f for fs in pool.map(boss_run, range(args.runs)) for f in fs]
    with open(args.out, "w") as out:
        out.writelines(json.dumps(f) + "\n" for f in fights)
    print(f"{len(fights)} boss fights from {args.runs} runs -> {args.out}")
    summarize(fights)


if __name__ == "__main__":
    main()
