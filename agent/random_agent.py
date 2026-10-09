"""Smoke test: play a few episodes with random actions to validate the env end-to-end.

Tolerates occasional transient HTTP stalls against the live game (see
docs/modding-approach.md) by aborting just the affected episode — via a
full_restart(), since a mid-episode stall is exactly the animation/CPU
backlog symptom that restart is meant to clear — rather than crashing the
whole run. A real train.py should follow the same pattern.
"""
from __future__ import annotations

import requests

from client import AutoSpireClient
from env import STS2CombatEnv

N_EPISODES = 6


def main():
    client = AutoSpireClient()
    if not client.ping():
        raise SystemExit("AutoSpire mod not reachable at localhost:31452 — is the game running?")

    env = STS2CombatEnv(client=client, episodes_per_restart=3)
    ep = 0
    while ep < N_EPISODES:
        try:
            obs, info = env.reset()
            total_reward = 0.0
            steps = 0
            terminated = truncated = False
            while not (terminated or truncated):
                action = env.action_space.sample()
                obs, reward, terminated, truncated, info = env.step(action)
                total_reward += reward
                steps += 1
            outcome = "WIN" if info.get("won") else "LOSS" if info.get("won") is False else "TRUNCATED"
            print(f"episode {ep}: steps={steps} total_reward={total_reward:.2f} outcome={outcome}")
            ep += 1
        except (requests.RequestException, TimeoutError) as exc:
            print(f"episode {ep}: ABORTED ({exc!r}) — forcing a full restart and retrying")
            env._episode_count = 0  # force next reset() to full_restart()
            ep += 1  # count the aborted attempt so a persistently broken env still terminates


if __name__ == "__main__":
    main()
