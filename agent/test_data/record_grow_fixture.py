"""Run from the part 1 checkout (326edb2) agent/: records part 1 layout states for test_data/grow_fixture.pkl.gz."""
import copy, gzip, pickle, sys
import numpy as np
from sb3_contrib import MaskablePPO
from env import STS2CombatEnv, ENCOUNTER_GROUPS, _encode
from run_env import RunPolicyEnv
from sim.engine import SimClient

rng = np.random.default_rng(0)
# Combat: random legal play on random decks with prompts, relics and potions; every 7th state plus every prompt.
cenv = STS2CombatEnv(encounter=list(ENCOUNTER_GROUPS["act1"] + ENCOUNTER_GROUPS["hive"]), client=SimClient(seed=0),
                     random_decks=True, prompt_practice=True, episodes_per_restart=10**9)
cenv._episode_count = 1
combat, step = [], 0
while len(combat) < 40 or sum(bool(c.get('choice')) for c, _ in combat) < 5:
    obs, _ = cenv.reset(seed=int(rng.integers(2**31)))
    done = False
    while not done:
        c = cenv.client.combat()
        if c.get("choice") or step % 7 == 0:
            combat.append((copy.deepcopy(c), _encode(c)))
        step += 1
        obs, _, done, trunc, _ = cenv.step(int(rng.choice(np.flatnonzero(cenv.action_masks()))))
        done = done or trunc
print("combat", len(combat), "prompts", sum(bool(c.get("choice")) for c, _ in combat), file=sys.stderr)

# Run: the part 1 run policy (stochastic) with the part 1 combat model; every decision's obs and mask, plus a few full states.
model = MaskablePPO.load("models/ppo_sts2_sim_boss_run_g1.zip", device="cpu")
renv = RunPolicyEnv(combat_model="models/ppo_sts2_sim_boss_g1.zip")
obs_l, mask_l, states, seen = [], [], [], {}
seed = 0
while len(obs_l) < 200 or len(seen) < 6:
    obs, _ = renv.reset(seed=seed)
    seed += 1
    done = trunc = False
    while not (done or trunc):
        m = renv.action_masks()
        if len(obs_l) < 200:
            obs_l.append(obs); mask_l.append(m)
        d = renv.decision
        if seen.get(d, 0) < 2 and (d != "path" or renv.run.act == 1):
            seen[d] = seen.get(d, 0) + 1
            run = copy.deepcopy(renv.run)
            run.event_allowed = None  # lambdas: not picklable, and _obs never reads them
            states.append({"run": run, "decision": d, "offered": list(renv.offered), "back": renv.back,
                           "obs": obs, "mask": m})
        a = int(model.predict(obs, action_masks=m, deterministic=False)[0])
        obs, _, done, trunc, _ = renv.step(a)
print("run obs", len(obs_l), "states", seen, "runs", seed, file=sys.stderr)
fx = {"combat": combat, "run_obs": np.array(obs_l), "run_mask": np.array(mask_l), "run_states": states}
with gzip.open(sys.argv[1], "wb") as f:
    pickle.dump(fx, f)
