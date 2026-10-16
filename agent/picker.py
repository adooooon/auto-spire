"""Card reward picks: score each option (skip, or each offered card the sim can play)
by simulating fights with the combat policy, and take the one that loses the least HP.

Every option is scored on the same seeds (common random numbers), so the comparison
isn't decided by luck of the draw. Offered cards the sim doesn't model (most
Uncommons/Rares, Armaments, Headbutt) can't be scored and are never picked.

Compare strategies on simulated mini-runs (HP carries over, an offer after each win):
    python picker.py --model models/ppo_sts2_sim_act1_decks_v5_final.zip --runs 200
Play the same mini-run in the live game, picking from its real reward screens:
    python picker.py --model models/ppo_sts2_sim_act1_decks_v5_final.zip --live
"""
from __future__ import annotations

import argparse
import random
from collections import Counter
from multiprocessing import Pool

import time

import numpy as np
from sb3_contrib import MaskablePPO

from client import AutoSpireClient

from env import NORMAL_ENCOUNTERS, WEAK_ENCOUNTERS, STS2CombatEnv
from sim.cards import CARDS, COMMONS, starter_deck
from sim.engine import SimClient

# The Ironclad Common reward pool; the last two open a card-choice prompt and aren't simulated.
REWARD_COMMONS = COMMONS + ("ARMAMENTS", "HEADBUTT")
# Roughly an Act 1 path's hallway: Burning Blood (the Ironclad's starter relic) heals 6 after
# each win, and a rest site heals 30% of max HP (HealRestSiteOption.cs). No elites/boss yet.
RUN = ["weak", "weak", "weak", "normal", "normal", "rest", "normal", "normal"]
RUN_FIGHTS = [r for r in RUN if r != "rest"]
BURNING_BLOOD_HEAL = 6
REST_HEAL = 24


class RarityOdds:
    """CardRarityOdds.cs for regular encounters at ascension 0: Rare 3% + an offset that
    starts at -5%, grows 1% per non-Rare roll (cap 40%) and resets on a Rare; Uncommon 37%."""

    def __init__(self):
        self.offset = -0.05

    def roll(self, rng: random.Random) -> str:
        r, rare = rng.random(), 0.03 + self.offset
        if r < rare:
            self.offset = -0.05
            return "RARE"
        self.offset = min(self.offset + 0.01, 0.4)
        return "UNCOMMON" if r < rare + 0.37 else "COMMON"


def offer(rng: random.Random, odds: RarityOdds) -> list[str]:
    """CardFactory.CreateForReward: 3 cards, no repeats. Uncommon/Rare are placeholders."""
    out: list[str] = []
    for _ in range(3):
        rarity = odds.roll(rng)
        out.append(rng.choice([c for c in REWARD_COMMONS if c not in out]) if rarity == "COMMON" else rarity)
    return out


def play_fight(model, env: STS2CombatEnv, seed: int | None = None) -> tuple[bool, int]:
    obs, _ = env.reset(seed=seed)
    hp0, done = env._combat["player"]["hp"], False
    while not done:
        action = int(model.predict(obs, action_masks=env.action_masks(), deterministic=True)[0])
        obs, _, terminated, truncated, info = env.step(action)
        done = terminated or truncated
    return bool(info.get("won")), hp0 - info["player_hp"]


def score_deck(model, deck: list[str], encounters, n: int, seed: int) -> float:
    """Mean HP lost per full-HP fight (a death loses everything) over n seeded fights."""
    env = STS2CombatEnv(encounter=list(encounters), random_decks=False)
    env.deck = deck
    total = 0
    for i in range(n):
        env.client = SimClient(seed=seed + i)
        env._episode_count = 1  # no periodic full_restart
        total += play_fight(model, env, seed=seed + i)[1]
    return total / n


def pick(model, deck: list[str], offered: list[str], encounters, n: int = 32, seed: int = 0) -> str | None:
    """The offered card (or None = skip) whose deck loses the least HP in simulation."""
    candidates = [None] + sorted({c for c in offered if c in CARDS})
    scores = {c: score_deck(model, deck + ([c] if c else []), encounters, n, seed) for c in candidates}
    return min(candidates, key=lambda c: scores[c])


_model = None


def _init(model_path: str) -> None:
    global _model
    _model = MaskablePPO.load(model_path)


def run(args: tuple[str, int, int]) -> dict:
    """One simulated mini-run: hallway fights with HP carrying over, an offer after each win."""
    strategy, seed, n = args
    rng = random.Random(seed)
    odds, deck = RarityOdds(), starter_deck()
    env = STS2CombatEnv(client=SimClient(seed=seed), heal=False)
    env._episode_count = 1  # keep the SimCombat (and its HP) across fights
    won = 0
    combat = env.client._combat
    for kind in RUN:
        if kind == "rest":
            combat.heal(REST_HEAL)
            continue
        env.encounters = list(WEAK_ENCOUNTERS if kind == "weak" else NORMAL_ENCOUNTERS)
        env.deck = deck
        ok, _ = play_fight(_model, env, seed=rng.randrange(2**31))
        if not ok:
            break
        won += 1
        combat.heal(BURNING_BLOOD_HEAL)
        offered = offer(rng, odds)
        pickable = [c for c in offered if c in CARDS]
        if strategy == "random":
            choice = rng.choice([None] + pickable)
        elif strategy == "mc":
            choice = pick(_model, deck, offered, NORMAL_ENCOUNTERS, n=n, seed=rng.randrange(2**31))
        else:  # skip
            choice = None
        if choice:
            deck = deck + [choice]
    return {"strategy": strategy, "won": won, "survived": won == len(RUN_FIGHTS),
            "hp": combat.player_hp if won == len(RUN_FIGHTS) else 0, "added": len(deck) - 10, "deck": deck[10:]}


def live_run(model_path: str, n: int) -> None:
    """The mini-run in the live game. Burning Blood is the game's own; rest sites are `heal 24`."""
    model = MaskablePPO.load(model_path)
    rng = random.Random()
    client = AutoSpireClient()
    env = STS2CombatEnv(client=client, heal=False)  # first reset full_restarts into a fresh run
    deck = starter_deck()
    for kind in RUN:
        if kind == "rest":
            client.exec(f"heal {REST_HEAL}")
            print(f"rest: +{REST_HEAL} -> {client.state()['player']['hp']} HP")
            continue
        env.encounters = list(WEAK_ENCOUNTERS if kind == "weak" else NORMAL_ENCOUNTERS)
        env.deck = deck
        ok, lost = play_fight(model, env)
        if not ok:
            print(f"{kind} fight lost — run over")
            return
        rewards = None
        for _ in range(40):  # the rewards screen opens shortly after the win
            rewards = client.state().get("rewards")
            if rewards:
                break
            time.sleep(0.25)
        offered = next((([c["id"] for c in r["cards"]]) for r in rewards or [] if r.get("cards")), [])
        choice = pick(model, deck, offered, NORMAL_ENCOUNTERS, n=n, seed=rng.randrange(2**31)) if offered else None
        if choice:
            deck = deck + [choice]
        print(f"{kind} fight won (-{lost} HP, now {client.state()['player']['hp']}); offered {offered} -> {choice or 'skip'}")
    print(f"run complete: {client.state()['player']['hp']} HP, deck +{deck[10:]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--runs", type=int, default=200)
    ap.add_argument("--n", type=int, default=32, help="fights simulated per pick candidate")
    ap.add_argument("--strategies", default="skip,random,mc")
    ap.add_argument("--live", action="store_true", help="play one mini-run in the live game instead")
    args = ap.parse_args()
    if args.live:
        return live_run(args.model, args.n)
    jobs = [(s, seed, args.n) for s in args.strategies.split(",") for seed in range(args.runs)]
    with Pool(initializer=_init, initargs=(args.model,)) as pool:
        results = pool.map(run, jobs)
    for s in args.strategies.split(","):
        rs = [r for r in results if r["strategy"] == s]
        print(f"{s:7} survived={np.mean([r['survived'] for r in rs]):.1%}  fights_won={np.mean([r['won'] for r in rs]):.2f}"
              f"/{len(RUN_FIGHTS)}  end_hp={np.mean([r['hp'] for r in rs]):.1f}  cards_added={np.mean([r['added'] for r in rs]):.1f}")
        if s != "skip":
            print("         picks:", ", ".join(f"{c} {n}" for c, n in Counter(c for r in rs for c in r["deck"]).most_common()))


if __name__ == "__main__":
    main()
