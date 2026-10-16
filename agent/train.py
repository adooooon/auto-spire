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
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.vec_env import SubprocVecEnv

from client import AutoSpireClient
from env import STS2CombatEnv, parse_encounters
from sim.engine import SimClient

MODEL_DIR = Path(__file__).parent / "models"
LOG_DIR = Path(__file__).parent / "tb_logs"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timesteps", type=int, default=8000)
    parser.add_argument("--episodes-per-restart", type=int, default=40)
    parser.add_argument("--encounters", default="NIBBITS_WEAK",
                        help='comma-separated encounter ids, or a group: weak, normal, act1')
    parser.add_argument("--backend", choices=["live", "sim"], default="live")
    parser.add_argument("--name", default=None, help="model name (default: ppo_sts2_<backend>_<encounters>)")
    parser.add_argument("--net", type=int, nargs="+", default=[64, 64], help="hidden layer sizes (policy and value)")
    parser.add_argument("--random-decks", action="store_true", help="starter deck +/- random Commons each episode")
    parser.add_argument("--run-mode", action="store_true",
                        help="sim only: fights chain through an Act 1 run (HP/deck carry over); see run.py")
    parser.add_argument("--n-envs", type=int, default=1, help="parallel sim envs (sim backend only)")
    parser.add_argument("--resume", type=str, default=None, help="path to a .zip checkpoint to continue training from")
    args = parser.parse_args()
    encounters = parse_encounters(args.encounters)
    name = args.name or f"ppo_sts2_{args.backend}_{args.encounters}"

    MODEL_DIR.mkdir(exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)

    sim = args.backend == "sim"
    client = SimClient() if sim else AutoSpireClient()
    if not client.ping():
        raise SystemExit("AutoSpire mod not reachable at localhost:31452 — is the game running?")

    if sim and args.run_mode:
        from run import RunModeEnv
        env = make_vec_env(RunModeEnv, n_envs=args.n_envs, vec_env_cls=SubprocVecEnv if args.n_envs > 1 else None)
    elif sim and args.n_envs > 1:
        env = make_vec_env(lambda: STS2CombatEnv(encounter=encounters, client=SimClient(), random_decks=args.random_decks),
                           n_envs=args.n_envs, vec_env_cls=SubprocVecEnv)
    else:
        env = Monitor(STS2CombatEnv(encounter=encounters, client=client, episodes_per_restart=args.episodes_per_restart,
                                    random_decks=args.random_decks))

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
            batch_size=64 * args.n_envs,  # keep minibatches-per-update constant as envs scale
            n_epochs=4,
            learning_rate=3e-4,
            gamma=0.99,
            policy_kwargs={"net_arch": args.net},
            verbose=1,
            tensorboard_log=str(LOG_DIR),
        )

    checkpoint_callback = CheckpointCallback(
        save_freq=50_000 if sim else 500,
        save_path=str(MODEL_DIR),
        name_prefix=name,
    )

    try:
        model.learn(
            total_timesteps=args.timesteps,
            callback=checkpoint_callback,
            reset_num_timesteps=args.resume is None,
        )
    finally:
        final_path = MODEL_DIR / f"{name}_final"
        model.save(str(final_path))
        print(f"Saved final model to {final_path}.zip")


if __name__ == "__main__":
    main()
