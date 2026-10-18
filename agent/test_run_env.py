"""Checks for the combat env's loop guard and the run policy env. Run from agent/: python test_run_env.py"""
from env import STS2CombatEnv
from sim.engine import SimClient, SimLoopError

# Review focus 1: a sim infinite loop ends the episode as aborted instead of hanging or raising.
env = STS2CombatEnv(encounter="NIBBITS_WEAK", client=SimClient(seed=0), heal=False, episodes_per_restart=10**9)
env._episode_count = 1
env.reset(seed=0)


def boom(*args, **kwargs):
    raise SimLoopError("test")


env.client.end_turn = boom
_, reward, terminated, truncated, info = env.step(env.action_space.n - 1)  # END_TURN
assert terminated and not truncated and info.get("aborted") and reward == -1.0, info

print("run env checks ok")
