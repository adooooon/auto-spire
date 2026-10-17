"""Card reward picks: score each option (skip, or each offered card the sim can play)
by simulating fights with the combat policy, and take the one that loses the least HP.

Every option is scored on the same seeds (common random numbers), so the comparison
isn't decided by luck of the draw. Offered cards the sim doesn't model (Armaments,
Headbutt, Burning Pact, Brand: card-choice prompts) can't be scored and are never picked.

Runs that use this (sim and live) live in run.py.
"""
from __future__ import annotations

import random

from env import STS2CombatEnv
from sim.cards import CARDS, COMMONS, RARES, UNCOMMONS
from sim.engine import SimClient

# The Ironclad reward pools by rarity; the extras open a card-choice prompt and aren't simulated.
REWARD_POOLS = {"COMMON": COMMONS + ("ARMAMENTS", "HEADBUTT"), "UNCOMMON": UNCOMMONS + ("BURNING_PACT",),
                "RARE": RARES + ("BRAND",)}


class RarityOdds:
    """CardRarityOdds.cs at ascension 0. Regular fights: Rare 3% + an offset that starts at -5%,
    grows 1% per non-Rare roll (cap 40%) and resets on a Rare; Uncommon 37%. Elites: Rare 10%
    + offset, Uncommon 40%. One instance per run (the offset carries)."""

    def __init__(self):
        self.offset = -0.05

    def roll(self, rng: random.Random, elite: bool = False) -> str:
        r, rare = rng.random(), (0.10 if elite else 0.03) + self.offset
        if r < rare:
            self.offset = -0.05
            return "RARE"
        self.offset = min(self.offset + 0.01, 0.4)
        return "UNCOMMON" if r < rare + (0.40 if elite else 0.37) else "COMMON"


def offer(rng: random.Random, odds: RarityOdds, elite: bool = False) -> list[str]:
    """CardFactory.CreateForReward: 3 cards, no repeats."""
    out: list[str] = []
    for _ in range(3):
        out.append(rng.choice([c for c in REWARD_POOLS[odds.roll(rng, elite)] if c not in out]))
    return out


def play_fight(model, env: STS2CombatEnv, seed: int | None = None) -> tuple[bool, int]:
    obs, _ = env.reset(seed=seed)
    hp0, done = env._combat["player"]["hp"], False
    while not done:
        action = int(model.predict(obs, action_masks=env.action_masks(), deterministic=True)[0])
        obs, _, terminated, truncated, info = env.step(action)
        done = terminated or truncated
    if info.get("aborted"):  # live API failure; the env would full_restart (a new run) next reset
        raise RuntimeError(f"fight aborted: {info.get('error', 'reading final HP failed')}")
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
