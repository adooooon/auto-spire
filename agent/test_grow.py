"""Checks for grow.py on toy envs. Run from agent/: python test_grow.py"""
import gymnasium as gym
import numpy as np
import torch
from gymnasium import spaces
from sb3_contrib import MaskablePPO

from grow import check, grow


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
print("grow checks ok")
