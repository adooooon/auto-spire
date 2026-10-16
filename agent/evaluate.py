"""Evaluate a MaskablePPO checkpoint (or a random baseline) on STS2CombatEnv.

Usage:
    python evaluate.py --model models/ppo_sts2_sim_final.zip --backend sim --episodes 1000
    python evaluate.py --model random --backend sim --episodes 1000
    python evaluate.py --model models/ppo_sts2_sim_final.zip --backend live --episodes 20
"""
from __future__ import annotations

import argparse

import numpy as np
from sb3_contrib import MaskablePPO

from client import AutoSpireClient
from env import STS2CombatEnv, parse_encounters
from sim.engine import SimClient


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help='path to a .zip checkpoint, or "random"')
    parser.add_argument("--encounters", default="NIBBITS_WEAK",
                        help='comma-separated encounter ids, or a group: weak, normal, act1')
    parser.add_argument("--backend", choices=["live", "sim"], default="sim")
    parser.add_argument("--random-decks", action="store_true", help="starter deck +/- random Commons each episode")
    parser.add_argument("--episodes", type=int, default=100)
    args = parser.parse_args()
    encounters = parse_encounters(args.encounters)

    client = SimClient(seed=0) if args.backend == "sim" else AutoSpireClient()
    env = STS2CombatEnv(encounter=encounters, client=client, random_decks=args.random_decks)
    model = None if args.model == "random" else MaskablePPO.load(args.model)

    wins, aborted, rewards, lengths, invalid, hp_lost = 0, 0, [], [], 0, []
    for _ in range(args.episodes):
        obs, _ = env.reset()
        start_hp = env._combat["player"]["hp"]
        total, steps, done = 0.0, 0, False
        while not done:
            action = env.action_space.sample() if model is None else int(model.predict(obs, action_masks=env.action_masks(), deterministic=True)[0])
            obs, reward, terminated, truncated, info = env.step(action)
            total += reward
            steps += 1
            invalid += info.get("invalid_action", False)
            done = terminated or truncated
        wins += bool(info.get("won"))
        aborted += bool(info.get("aborted"))
        rewards.append(total)
        lengths.append(steps)
        if not info.get("aborted"):
            hp_lost.append(start_hp - info["player_hp"])

    n = args.episodes
    print(f"{args.model} on {args.backend}: win_rate={wins / n:.1%}  mean_reward={np.mean(rewards):.2f}  "
          f"mean_len={np.mean(lengths):.1f}  hp_lost={np.mean(hp_lost):.1f}  invalid_actions/ep={invalid / n:.2f}  aborted={aborted}")


if __name__ == "__main__":
    main()
