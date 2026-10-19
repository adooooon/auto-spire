"""Grow a trained MaskablePPO into a bigger observation/action space (sub-project 2: potions).

Every old weight is copied; weights from new inputs and to new actions start at zero, so the grown
model acts exactly like the old one until training moves them. New inputs and actions must be
appended (old indices unchanged), as env.py and run_env.py do. From agent/:
    python grow.py models/ppo_sts2_sim_act1_map_v10_final.zip models/ppo_sts2_sim_act1_map_v10p.zip --env combat
    python grow.py models/ppo_sts2_sim_run_policy_v2_final.zip models/ppo_sts2_sim_run_policy_v2p.zip --env run
"""
from __future__ import annotations

import argparse

import torch
from sb3_contrib import MaskablePPO


def grow(old: MaskablePPO, env) -> MaskablePPO:
    new = MaskablePPO("MlpPolicy", env, n_steps=old.n_steps, batch_size=old.batch_size, n_epochs=old.n_epochs,
                      learning_rate=old.learning_rate, gamma=old.gamma, policy_kwargs=old.policy_kwargs,
                      device="cpu", verbose=1)
    state = new.policy.state_dict()
    for key, w in old.policy.state_dict().items():
        assert all(o <= n for o, n in zip(w.shape, state[key].shape)), (key, w.shape, state[key].shape)
        grown = torch.zeros_like(state[key])
        grown[tuple(slice(0, s) for s in w.shape)] = w
        state[key] = grown
    new.policy.load_state_dict(state)
    new.num_timesteps = old.num_timesteps
    return new


def _heads(model: MaskablePPO, obs: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    with torch.no_grad():
        pi, vf = model.policy.mlp_extractor(model.policy.extract_features(obs))
        return model.policy.action_net(pi), model.policy.value_net(vf)


def check(old: MaskablePPO, new: MaskablePPO, n: int = 256) -> bool:
    """Same logits on the old actions and same value, whatever the new inputs hold; new actions at 0."""
    obs = torch.randn(n, old.observation_space.shape[0])
    extra = torch.randn(n, new.observation_space.shape[0] - obs.shape[1])
    lo, vo = _heads(old, obs)
    ln, vn = _heads(new, torch.cat([obs, extra], 1))
    k = old.action_space.n
    return bool(torch.allclose(lo, ln[:, :k], atol=1e-5) and torch.allclose(vo, vn, atol=1e-5)
                and (ln[:, k:] == 0).all())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--env", choices=["combat", "run"], required=True)
    args = ap.parse_args()
    if args.env == "combat":
        from env import STS2CombatEnv
        from sim.engine import SimClient
        env = STS2CombatEnv(client=SimClient())
    else:
        from run_env import RunPolicyEnv
        env = RunPolicyEnv()
    old = MaskablePPO.load(args.old, device="cpu")
    new = grow(old, env)
    if not check(old, new):
        raise SystemExit("grow self-check failed; not saved")
    new.save(args.new)
    print(f"grow self-check ok: {old.observation_space.shape[0]}->{new.observation_space.shape[0]} inputs, "
          f"{old.action_space.n}->{new.action_space.n} actions, saved {args.new}")


if __name__ == "__main__":
    main()
