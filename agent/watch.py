"""Watch a trained PPO model play STS2 combat live (no further training).

Loads a checkpoint and runs it deterministically against the live game for a
few episodes, printing each action/outcome so you can watch alongside it.

Usage:
    python watch.py                                   # uses models/ppo_sts2_final.zip
    python watch.py --model models/ppo_sts2_500_steps.zip
    python watch.py --episodes 10
"""
from __future__ import annotations

import argparse
from pathlib import Path

import requests
from stable_baselines3 import PPO

from client import AutoSpireClient
from env import STS2CombatEnv, MAX_HAND

MODEL_DIR = Path(__file__).parent / "models"
DEFAULT_MODEL = MODEL_DIR / "ppo_sts2_final.zip"


def describe_action(action: int) -> str:
    return "end_turn" if action >= MAX_HAND else f"play hand[{action}]"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, default=str(DEFAULT_MODEL))
    parser.add_argument("--episodes", type=int, default=5)
    args = parser.parse_args()

    client = AutoSpireClient()
    if not client.ping():
        print("AutoSpire mod not reachable — relaunching the game...")
        client.full_restart()
        print("Game is back up and a fresh run has started.")

    model = PPO.load(args.model)
    print(f"Loaded model: {args.model}")

    env = STS2CombatEnv(client=client, episodes_per_restart=args.episodes + 1)
    ep = 0
    while ep < args.episodes:
        try:
            obs, info = env.reset()
            total_reward = 0.0
            steps = 0
            terminated = truncated = False
            while not (terminated or truncated):
                action, _ = model.predict(obs, deterministic=True)
                action = int(action)
                obs, reward, terminated, truncated, info = env.step(action)
                total_reward += reward
                steps += 1
                print(f"  step {steps}: {describe_action(action)} -> reward={reward:+.2f}"
                      + ("  [invalid]" if info.get("invalid_action") else ""))
            outcome = "WIN" if info.get("won") else "LOSS" if info.get("won") is False else "TRUNCATED"
            print(f"episode {ep}: steps={steps} total_reward={total_reward:.2f} outcome={outcome}\n")
            ep += 1
        except (requests.RequestException, TimeoutError) as exc:
            print(f"episode {ep}: ABORTED ({exc!r}) — forcing a full restart and retrying")
            env._episode_count = 0
            ep += 1


if __name__ == "__main__":
    main()
