"""Train a PPO agent (MaskablePPO: only playable cards can be chosen) on STS2CombatEnv.

This drives the live game over HTTP, so each step costs real wall-clock time
(~0.15-0.3s) and episodes run ~45-60 steps. Scoped as a toy run: enough
total_timesteps to see the agent start learning something (avoid invalid
plays, prioritize damage/survival), not a from-scratch strong-play budget.

Usage:
    python train.py                          # fresh run, default budget
    python train.py --timesteps 20000         # longer run
    python train.py --resume models/ppo_sts2_8000_steps.zip   # continue training
    python train.py --backend sim --timesteps 500000          # fast Python sim (agent/sim/)
"""
from __future__ import annotations

import argparse
from pathlib import Path

from sb3_contrib import MaskablePPO
from stable_baselines3.common.callbacks import CheckpointCallback
from stable_baselines3.common.monitor import Monitor

from client import AutoSpireClient
from env import WEAK_ENCOUNTERS, STS2CombatEnv
from sim.engine import SimClient

MODEL_DIR = Path(__file__).parent / "models"
LOG_DIR = Path(__file__).parent / "tb_logs"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timesteps", type=int, default=8000)
    parser.add_argument("--episodes-per-restart", type=int, default=40)
    parser.add_argument("--encounters", default="NIBBITS_WEAK",
                        help='comma-separated encounter ids, or "weak" for all Act 1 weak fights')
    parser.add_argument("--backend", choices=["live", "sim"], default="live")
    parser.add_argument("--resume", type=str, default=None, help="path to a .zip checkpoint to continue training from")
    args = parser.parse_args()
    encounters = WEAK_ENCOUNTERS if args.encounters == "weak" else args.encounters.split(",")

    MODEL_DIR.mkdir(exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)

    sim = args.backend == "sim"
    client = SimClient() if sim else AutoSpireClient()
    if not client.ping():
        raise SystemExit("AutoSpire mod not reachable at localhost:31452 — is the game running?")

    env = Monitor(STS2CombatEnv(encounter=encounters, client=client, episodes_per_restart=args.episodes_per_restart))

    if args.resume:
        model = MaskablePPO.load(args.resume, env=env, tensorboard_log=str(LOG_DIR))
        print(f"Resumed from {args.resume}")
    else:
        model = MaskablePPO(
            "MlpPolicy",
            env,
            # Small obs/action space and a slow, single live-game env: collect
            # a policy-update batch every ~256 steps (~1 minute) rather than
            # SB3's default 2048 (~7+ minutes before the first update).
            n_steps=2048 if sim else 256,
            batch_size=64,
            n_epochs=4,
            learning_rate=3e-4,
            gamma=0.99,
            verbose=1,
            tensorboard_log=str(LOG_DIR),
        )

    checkpoint_callback = CheckpointCallback(
        save_freq=50_000 if sim else 500,
        save_path=str(MODEL_DIR),
        name_prefix=f"ppo_sts2_{args.backend}_{args.encounters}",
    )

    try:
        model.learn(
            total_timesteps=args.timesteps,
            callback=checkpoint_callback,
            reset_num_timesteps=args.resume is None,
        )
    finally:
        final_path = MODEL_DIR / f"ppo_sts2_{args.backend}_{args.encounters}_final"
        model.save(str(final_path))
        print(f"Saved final model to {final_path}.zip")


if __name__ == "__main__":
    main()
