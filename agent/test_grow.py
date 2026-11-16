"""Checks for grow.py on toy envs. Run from agent/: python test_grow.py"""
import gymnasium as gym
import numpy as np
import torch
from gymnasium import spaces
from sb3_contrib import MaskablePPO

from grow import check, grow, insert_map


class Toy(gym.Env):
    def __init__(self, n_obs: int, n_act: int):
        self.observation_space = spaces.Box(-1, 1, (n_obs,), np.float32)
        self.action_space = spaces.Discrete(n_act)

    def reset(self, *, seed=None, options=None):
        return np.zeros(self.observation_space.shape, np.float32), {}

    def step(self, action):
        return np.zeros(self.observation_space.shape, np.float32), 0.0, True, False, {}

    def action_masks(self):
        return np.ones(self.action_space.n, dtype=bool)


old = MaskablePPO("MlpPolicy", Toy(6, 3), policy_kwargs={"net_arch": [16, 16]}, n_steps=64, batch_size=32, device="cpu")
old.num_timesteps = 123
new = grow(old, Toy(9, 5))
# Review focus 4: the grown model is the old one, with new inputs ignored and new actions at logit 0.
assert check(old, new) and new.num_timesteps == 123 and new.action_space.n == 5
with torch.no_grad():
    new.policy.mlp_extractor.policy_net[0].weight[0, 0] += 1.0  # as if one old weight weren't carried over
assert not check(old, new)
assert insert_map([2, "cards", 1], ["A", "C"], ["A", "B", "C"]) == [0, 1, 2, 4, 5]
assert insert_map(["cards", "cards"], ["A"], ["0", "A"]) == [1, 3]

obs_map, act_map = [0, 1, 3, 4, 5, 7], [0, 2, 3]  # 6 -> 9 inputs, 3 -> 5 actions, spread through
small = MaskablePPO("MlpPolicy", Toy(6, 3), policy_kwargs={"net_arch": [16, 16]}, n_steps=64, batch_size=32, device="cpu")
big = grow(small, Toy(9, 5), obs_map, act_map)
assert check(small, big, obs_map, act_map)
with torch.no_grad():
    big.policy.mlp_extractor.policy_net[0].weight[0, 3] += 1.0  # a position that should hold old input 2
assert not check(small, big, obs_map, act_map)

# The real part 3 pair (698b7ae), grown into the potion layout, acts as before on states its own layout recorded
# (test_data/record_grow_fixture.py): the run policy on 200 decisions of its play, the combat model on random fights.
import gzip
import pickle
from env import N_ACTIONS as COMBAT_ACTIONS, STS2CombatEnv, _encode, combat_maps
from run_env import N_ACTIONS, RunPolicyEnv, run_maps
from sim.engine import SimClient

fx = pickle.load(gzip.open("test_data/grow_fixture.pkl.gz"))
run_old = MaskablePPO.load("models/ppo_sts2_sim_boss_run_v1_final.zip", device="cpu")
obs_map, act_map = run_maps()
run_new = grow(run_old, RunPolicyEnv(), obs_map, act_map)
assert check(run_old, run_new, obs_map, act_map)
obs = np.zeros((200, run_new.observation_space.shape[0]), np.float32)
obs[:, obs_map] = fx["run_obs"]
mask = np.zeros((200, N_ACTIONS), bool)
mask[:, act_map] = fx["run_mask"]
before = run_old.predict(fx["run_obs"], action_masks=fx["run_mask"], deterministic=True)[0]
after = run_new.predict(obs, action_masks=mask, deterministic=True)[0]
assert (np.array(act_map)[before] == after).all() and len(set(before.tolist())) > 5

c_old = MaskablePPO.load("models/ppo_sts2_sim_boss_b_final.zip", device="cpu")
obs_map, act_map = combat_maps()
c_new = grow(c_old, STS2CombatEnv(client=SimClient()), obs_map, act_map)
assert check(c_old, c_new, obs_map, act_map)
old_obs = np.array([o for _, o in fx["combat"]])
mask = np.zeros((len(old_obs), COMBAT_ACTIONS), bool)
mask[:, act_map] = True  # every old action open: the new ones sit at logit 0, which could beat the old ones
before = c_old.predict(old_obs, deterministic=True)[0]
after = c_new.predict(np.array([_encode(c) for c, _ in fx["combat"]]), action_masks=mask, deterministic=True)[0]
assert (np.array(act_map)[before] == after).all() and len(set(before.tolist())) > 5
print("grow checks ok")
