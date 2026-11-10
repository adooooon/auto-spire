"""Do the combat model's card choices make sense, and change with the situation? (prompt-cards spec, "The choice test")

    python choice_test.py models/ppo_sts2_sim_act1_pc_v13c.zip
Plays 200 fights per prompt card, always taking the most likely action, and scores four rows. Exits 0 either way.
"""
from __future__ import annotations

import argparse
import copy
import sys

import numpy as np

from env import (CARD_IDS, CHOOSE_DISCARD, CHOOSE_DRAW, CHOOSE_GENERATED, CHOOSE_HAND, CHOOSE_SKIP, ENCOUNTER_GROUPS, MAX_HAND,
                 STS2CombatEnv, _encode, random_deck)
from sim.cards import CARDS, base_id, card_to_dict

BASIC = ("STRIKE_IRONCLAD", "DEFEND_IRONCLAD")  # Bash is not basic
MIN_N = 30

is_junk = lambda c: CARDS[c].rarity == "Status"
is_good = lambda c: not is_junk(c) and base_id(c) not in BASIC  # non-basic, non-junk


def _rates(prompts: list[dict], group, distinct: bool) -> tuple[float, float]:
    """(share of picks in the group, mean share of options in the group) over prompts holding both kinds."""
    hit, chance = [], []
    for p in prompts:
        opts = list(dict.fromkeys(p["options"])) if distinct else p["options"]
        if any(map(group, opts)) and not all(map(group, opts)):
            hit.append(group(p["picked"]))
            chance.append(sum(map(group, opts)) / len(opts))
    return (float(np.mean(hit)), float(np.mean(chance))) if hit else (0.0, 0.0)


def score_junk(prompts):
    return _rates(prompts, is_junk, distinct=False)


def score_headbutt(prompts):
    # A discard prompt is answered by card id, so each distinct id is one action: random is over distinct ids.
    # Scored only where a good card and a basic-or-junk card are both there (any non-good card is basic or junk).
    return _rates(prompts, is_good, distinct=True)


def headbutt_subset(prompts):
    """Prompts a first-legal chooser can't pass: the lowest CARD_IDS id in the discard is basic or junk, and a good card is there too.
    (The grown model takes the first legal id, and the alphabetical order of CARD_IDS puts Bash before Strike and Wound.)"""
    return [p for p in prompts if not is_good(min(p["options"], key=CARD_IDS.index)) and any(map(is_good, p["options"]))]


def score_headbutt_subset(prompts):
    return score_headbutt(headbutt_subset(prompts))


def passes_junk(rate, chance): return rate > 0.5 and rate >= 2 * chance
def passes_headbutt(rate, chance): return rate >= 1.5 * chance
def passes_flip(rate): return rate > 0.5
def passes_hp(low, high): return round(low - high, 9) >= 0.10


def collect(model, card: str, fights: int = 200, seed: int = 0, env=None) -> list[dict]:
    """Prompts (2+ legal answers) from fights with a random deck + card + 2 Wounds; no relics or potions."""
    from sim.engine import SimClient
    rng = np.random.default_rng(seed)
    env = env or STS2CombatEnv(client=SimClient(seed=seed))
    out = []
    for f in range(fights):
        env.deck = random_deck(rng) + [card, "WOUND", "WOUND"]
        env.encounters = [str(rng.choice(ENCOUNTER_GROUPS["act1"]))]
        obs, _ = env.reset(seed=seed if f == 0 else None)
        done = False
        while not done:
            mask = env.action_masks()
            action = int(model.predict(obs, action_masks=mask, deterministic=True)[0])
            c = env._combat
            if c.get("choice") and mask.sum() >= 2:
                p, kind = c["player"], c["choice"]["kind"]
                if kind in ("hand", "upgrade", "hand_multi"):  # picked None: Purity's done
                    options, pick = [x["id"] for x in p["hand"][:MAX_HAND]], action - CHOOSE_HAND
                    picked = options[pick] if action < CHOOSE_DISCARD else None
                elif kind == "discard":
                    options, picked, pick = [x["id"] for x in p["discardPile"]], CARD_IDS[action - CHOOSE_DISCARD], action
                elif kind == "generated":  # picked None: skipped
                    options, pick = c["choice"]["options"], action - CHOOSE_GENERATED
                    picked = options[pick] if action < CHOOSE_SKIP else None
                else:  # draw
                    options, picked, pick = c["choice"]["options"], CARD_IDS[action - CHOOSE_DRAW], action
                out.append({"source": c["choice"]["source"], "options": options, "picked": picked, "pick": pick,
                            "combat": copy.deepcopy(c)})
            obs, _, term, trunc, _ = env.step(action)
            done = term or trunc
    return out


def from_card(prompts: list[dict], card: str) -> list[dict]:
    """Only the prompts the card under test opened (a random-deck card can open one too)."""
    return [p for p in prompts if p["source"] == card]


def read_choice(model, env, combat: dict) -> int:
    """The action the model takes at this combat state, read the way play reads it. Leaves env as it was."""
    saved, env._combat = env._combat, combat
    try:
        return int(model.predict(_encode(combat), action_masks=env.action_masks(), deterministic=True)[0])
    finally:
        env._combat = saved


def swap_rate(model, env, prompts, seed=0) -> tuple[float, int]:
    """At hand prompts with no junk: Wound replaces a card that wasn't picked; share of reads that move to it."""
    rng = np.random.default_rng(seed)
    moved = []
    for p in prompts:
        if p["combat"]["choice"]["kind"] != "hand" or any(map(is_junk, p["options"])):
            continue
        assert read_choice(model, env, p["combat"]) - CHOOSE_HAND == p["pick"], "replay of a prompt changed the pick"
        i = int(rng.choice([j for j in range(len(p["options"])) if j != p["pick"]]))
        c = copy.deepcopy(p["combat"])
        c["player"]["hand"][i] = card_to_dict("WOUND", -1, False)  # same hand length
        moved.append(read_choice(model, env, c) == CHOOSE_HAND + i)
    return (float(np.mean(moved)) if moved else 0.0), len(moved)


def hp_rates(model, env, prompts) -> tuple[float, float, int]:
    """Block-card share of picks at 15% and 100% HP, over discard prompts holding an attack and a block card."""
    shares = ([], [])
    for p in prompts:
        o = set(p["options"])
        atk, blk = {c for c in o if CARDS[c].type == "Attack"}, {c for c in o if CARDS[c].block > 0}
        if p["combat"]["choice"]["kind"] != "discard" or not any(a != b for a in atk for b in blk):
            continue
        for s, frac in zip(shares, (0.15, 1.0)):
            c = copy.deepcopy(p["combat"])
            c["player"]["hp"] = int(frac * c["player"]["maxHp"])
            s.append(CARD_IDS[read_choice(model, env, c) - CHOOSE_DISCARD] in blk)
    n = len(shares[0])
    return (float(np.mean(shares[0])), float(np.mean(shares[1])), n) if n else (0.0, 0.0, 0)


def print_verdict(rows) -> str:
    """A row below MIN_N is LOW N, not a pass, whatever its rates."""
    rows = [(name, n, text, ok and n >= MIN_N, "LOW N" if n < MIN_N else None) for name, n, text, ok in rows]
    for name, n, text, ok, low in rows:
        print(f"{name}: n={n}  {text}  {low or ('PASS' if ok else 'FAIL')}")
    verdict = "ALL PASS" if all(r[3] for r in rows) else "NOT ALL PASS"
    print(verdict)
    return verdict


def main(path: str, headbutt_fights: int = 200):
    from sb3_contrib import MaskablePPO
    from sim.engine import SimClient
    model = MaskablePPO.load(path)
    env = STS2CombatEnv(client=SimClient(seed=0))
    prompts = {c: from_card(collect(model, c, fights=headbutt_fights if c == "HEADBUTT" else 200, seed=i), c)
               for i, c in enumerate(("BURNING_PACT", "BRAND", "HEADBUTT"))}
    rows = []  # (name, n, text, passed)
    parts = [(c, score_junk(prompts[c]), len([p for p in prompts[c] if score_junk([p]) != (0.0, 0.0)])) for c in ("BURNING_PACT", "BRAND")]
    rows.append(("1 junk", min(n for *_, n in parts), "  ".join(f"{c} {r:.0%} vs random {ch:.0%}" for c, (r, ch), _ in parts),
                 all(passes_junk(*rc) for _, rc, _ in parts)))
    sw = [(c, *swap_rate(model, env, prompts[c])) for c in ("BURNING_PACT", "BRAND")]
    rows.append(("2 swap", min(n for _, _, n in sw), "  ".join(f"{c} {r:.0%}" for c, r, _ in sw), all(passes_flip(r) and n for _, r, n in sw)))
    sub = headbutt_subset(prompts["HEADBUTT"])
    r, ch = score_headbutt(sub)
    ro, cho = score_headbutt(prompts["HEADBUTT"])
    rows.append(("3 headbutt", len(sub), f"non-basic non-junk {r:.0%} vs random {ch:.0%} (prompts whose first legal id is basic/junk; "
                 f"info only, all {len([p for p in prompts['HEADBUTT'] if score_headbutt([p]) != (0.0, 0.0)])} mixed prompts: {ro:.0%} vs random {cho:.0%})",
                 passes_headbutt(r, ch) and len(sub) > 0))
    lo, hi, n4 = hp_rates(model, env, prompts["HEADBUTT"])
    rows.append(("4 headbutt hp", n4, f"block card at 15% HP {lo:.0%}, at 100% HP {hi:.0%}", passes_hp(lo, hi) and n4 > 0))
    print_verdict(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--headbutt-fights", type=int, default=200)
    a = ap.parse_args()
    main(a.model, a.headbutt_fights)
