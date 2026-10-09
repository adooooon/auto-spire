"""Evaluate a PPO checkpoint (or a random baseline) on STS2CombatEnv.

Usage:
    python evaluate.py --model models/ppo_sts2_sim_final.zip --backend sim --episodes 1000
    python evaluate.py --model random --backend sim --episodes 1000
    python evaluate.py --model models/ppo_sts2_sim_final.zip --backend live --episodes 20
"""
from __future__ import annotations

import argparse

import numpy as np
from stable_baselines3 import PPO

from client import AutoSpireClient
from env import STS2CombatEnv
from sim.engine import SimClient


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help='path to a .zip checkpoint, or "random"')
    parser.add_argument("--backend", choices=["live", "sim"], default="sim")
    parser.add_argument("--episodes", type=int, default=100)
    args = parser.parse_args()

    client = SimClient(seed=0) if args.backend == "sim" else AutoSpireClient()
    env = STS2CombatEnv(client=client)
    model = None if args.model == "random" else PPO.load(args.model)

    wins, aborted, rewards, lengths, invalid = 0, 0, [], [], 0
    for _ in range(args.episodes):
        obs, _ = env.reset()
        total, steps, done = 0.0, 0, False
        while not done:
            action = env.action_space.sample() if model is None else int(model.predict(obs, deterministic=True)[0])
            obs, reward, terminated, truncated, info = env.step(action)
            total += reward
            steps += 1
            invalid += info.get("invalid_action", False)
            done = terminated or truncated
        wins += bool(info.get("won"))
        aborted += bool(info.get("aborted"))
        rewards.append(total)
        lengths.append(steps)

    n = args.episodes
    print(f"{args.model} on {args.backend}: win_rate={wins / n:.1%}  mean_reward={np.mean(rewards):.2f}  "
          f"mean_len={np.mean(lengths):.1f}  invalid_actions/ep={invalid / n:.2f}  aborted={aborted}")


if __name__ == "__main__":
    main()
