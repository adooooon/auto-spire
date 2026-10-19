"""Checks for the combat env's loop guard and the run policy env. Run from agent/: python test_run_env.py"""
from env import END_TURN, STS2CombatEnv
from sim.engine import SimClient, SimLoopError

# Review focus 1: a sim infinite loop ends the episode as aborted instead of hanging or raising.
env = STS2CombatEnv(encounter="NIBBITS_WEAK", client=SimClient(seed=0), heal=False, episodes_per_restart=10**9)
env._episode_count = 1
env.reset(seed=0)


def boom(*args, **kwargs):
    raise SimLoopError("test")


env.client.end_turn = boom
_, reward, terminated, truncated, info = env.step(END_TURN)
assert terminated and not truncated and info.get("aborted") and reward == -1.0, info

import numpy as np

from run_env import CARD_INDEX, N_ACTIONS, OBS_DIM, PICK, REMOVE, SHOP, SHOP_LEAVE, SHOP_REMOVE, RunPolicyEnv
from sim.act import Shop

assert N_ACTIONS == 113

# Smoke: random run decisions + random combat. Masks never empty, obs in bounds, every run ends.
renv, rng, floors = RunPolicyEnv(), np.random.default_rng(0), []
for seed in range(200):
    obs, _ = renv.reset(seed=seed)
    done = trunc = False
    while not (done or trunc):
        assert obs.shape == (OBS_DIM,) and obs.min() >= -1 and obs.max() <= 10, (obs.min(), obs.max())
        mask = renv.action_masks()
        assert mask.shape == (N_ACTIONS,) and mask.any(), renv.decision
        obs, reward, done, trunc, info = renv.step(int(rng.choice(np.flatnonzero(mask))))
    assert done and not trunc, f"seed {seed} never ended"
    assert info["died_at"] or info["cleared"]
    floors.append(info["floor"])
assert np.mean(floors) > 1.5, np.mean(floors)  # random combat dies early, but climbs a little

# Review focus 5: same seed, same map.
a, b = RunPolicyEnv(), RunPolicyEnv()
a.reset(seed=11)
b.reset(seed=11)
assert [(n.col, n.row, n.type) for n in a.run.map.nodes()] == [(n.col, n.row, n.type) for n in b.run.map.nodes()]

# Review focus 2: an offer of only prompt cards leaves only "skip".
renv.reset(seed=1)
renv.decision, renv.offered = "pick", ["ARMAMENTS", "HEADBUTT", "BRAND"]
assert np.flatnonzero(renv.action_masks()).tolist() == [PICK + 3]

# Review focus 3: a broke player in a shop can only leave; removal is masked once used.
renv.decision, renv.run.gold = "shop", 0
renv.run.shop = Shop(["NOT_A_CARD"] * 5, [50] * 5, 75)
assert np.flatnonzero(renv.action_masks()).tolist() == [SHOP_LEAVE]
renv.run.gold, renv.run.shop = 1000, Shop(["SHRUG_IT_OFF", None, "ARMAMENTS", None, None], [50] * 5, 75)
assert np.flatnonzero(renv.action_masks()).tolist() == [SHOP, SHOP_REMOVE, SHOP_LEAVE]
renv.step(SHOP_REMOVE)
assert renv.decision == "remove" and renv.action_masks()[REMOVE + CARD_INDEX["BASH"]]
renv.step(REMOVE + CARD_INDEX["BASH"])
assert renv.decision == "shop" and "BASH" not in renv.run.deck and not renv.action_masks()[SHOP_REMOVE]

# Review focus 4: max HP goes into the fight and comes back out.
renv.reset(seed=2)
renv.run.hp, renv.run.max_hp = 50, 90
renv.play(renv.run.normals[0])
assert renv.run.max_hp == 90 and renv.fight_env.client._combat.player_max_hp == 90

# Review focus 1: a sim error inside a fight ends the run as a loss.
renv.reset(seed=3)
renv.fight_env.client.exec = boom
_, _, done, _, info = renv.step(int(np.flatnonzero(renv.action_masks())[0]))
assert done and info["died_at"] == "Monster" and not info["cleared"]

# MapRunModeEnv: fights chain through generated-map runs; HP carries between fights.
from run import MapRunModeEnv

menv, rng2 = MapRunModeEnv(run_model=None), np.random.default_rng(1)
fights = 0
for _ in range(30):
    obs, _ = menv.reset()
    hp_in = menv.client._combat.player_hp
    assert hp_in == menv.driver.run.hp
    done = False
    while not done:
        obs, _, term, trunc, info = menv.step(int(rng2.choice(np.flatnonzero(menv.action_masks()))))
        done = term or trunc
    fights += 1
assert fights == 30 and menv.driver.run is not None

# Review fix: "remove a card" commits (no cancel), so shop -> remove -> cancel can't loop forever.
renv.reset(seed=4)
renv.decision, renv.run.gold = "shop", 1000
renv.run.shop = Shop(["SHRUG_IT_OFF", None, None, None, None], [50] * 5, 75)
renv.step(SHOP_REMOVE)
assert not renv.action_masks()[REMOVE + len(CARD_INDEX)], "remove has no cancel"

# Review fix: train.py refuses flag combinations that would silently train the wrong thing.
import subprocess
import sys

for bad in (["--backend", "sim", "--run-policy"], ["--backend", "sim", "--run-model", "x.zip"], ["--run-policy", "--combat-model", "x.zip"]):
    p = subprocess.run([sys.executable, "train.py", *bad, "--timesteps", "0", "--name", "guard_check"], capture_output=True, text=True)
    assert p.returncode == 2 and "error:" in p.stderr, (bad, p.returncode, p.stderr[-300:])

# Combat env potions (sub-project 2).
from env import N_ACTIONS as COMBAT_ACTIONS, OBS_DIM as COMBAT_OBS, POTION_ACTION, POTION_COST_HP
from sim.potions import POTION_IDS

cenv = STS2CombatEnv(encounter="NIBBITS_WEAK", client=SimClient(seed=1), heal=False, episodes_per_restart=10**9)
cenv._episode_count = 1
assert cenv.action_space.n == COMBAT_ACTIONS == END_TURN + 1 + 12 and COMBAT_OBS == 1358 + 38
# Review focus 1: live play (no potionSlots in /combat) never offers a potion.
cenv._combat = {"player": {"hand": []}, "enemies": [{"isAlive": True, "combatId": 1}, {"isAlive": True, "combatId": 2}]}
assert not cenv.action_masks()[POTION_ACTION:].any()
cenv._combat["potionSlots"] = ["FIRE_POTION", "ATTACK_POTION", "BLOCK_POTION"]
assert np.flatnonzero(cenv.action_masks()[POTION_ACTION:]).tolist() == [0, 1, 8]  # Fire x2 targets, Block on 0
# Review focus 2: a potion that ends the fight is a win, minus the use cost.
cenv.potions = ["EXPLOSIVE_AMPOULE", None, None]
obs, _ = cenv.reset(seed=0)
assert obs.shape == (COMBAT_OBS,) and obs[-38 + POTION_IDS.index("EXPLOSIVE_AMPOULE")] == 1
alive = [e for e in cenv.client._combat.enemies if e.is_alive]
for e in alive:
    e.hp = 5
cenv._combat = cenv.client.combat()
_, r, term, _, info = cenv.step(POTION_ACTION)
assert term and info["won"] and cenv.client._combat.potions == [None, None, None]
assert abs(r - (5 * len(alive) / 10 + 5.0 - POTION_COST_HP / 10)) < 1e-6, r

# Run env potions (sub-project 2).
from run_env import DRINK, POTION_SKIP, POTION_TAKE, SHOP_POTION

# Review focus 3: shop potions need a free slot and a modeled potion.
renv.reset(seed=6)
renv.decision, renv.run.gold = "shop", 1000
renv.run.potions = ["FIRE_POTION", "FIRE_POTION", "FIRE_POTION"]
renv.run.shop = Shop([None] * 5, [50] * 5, 75, potions=["BLOCK_POTION", "ATTACK_POTION", None], potion_prices=[50, 50, 0])
assert not renv.action_masks()[SHOP_POTION:SHOP_POTION + 3].any()
renv.run.potions[1] = None
assert renv.action_masks()[SHOP_POTION:SHOP_POTION + 3].tolist() == [True, False, False]
renv.step(SHOP_POTION)
assert renv.run.potions[1] == "BLOCK_POTION" and renv.decision == "shop"
# Review focus 3: an unmodeled drop is skipped without a decision; a modeled one asks where it goes.
renv.decision, renv.offered, renv.run.potion_drop = "pick", ["ARMAMENTS", "HEADBUTT", "BRAND"], "ATTACK_POTION"
renv.step(PICK + 3)
assert renv.decision == "path" and renv.run.potion_drop is None
renv.decision, renv.run.potion_drop = "pick", "WEAK_POTION"
renv.step(PICK + 3)
assert renv.decision == "potion"
assert np.flatnonzero(renv.action_masks()).tolist() == [POTION_TAKE, POTION_TAKE + 1, POTION_TAKE + 2, POTION_SKIP]
renv.step(POTION_TAKE + 2)  # replaces the Fire Potion in slot 2
assert renv.run.potions == ["FIRE_POTION", "BLOCK_POTION", "WEAK_POTION"] and renv.decision == "path"
# Blood Potion between fights: only below max HP; drinking keeps the path decision.
renv.run.potions, renv.run.hp, renv.run.max_hp = ["BLOOD_POTION", None, None], 80, 80
assert not renv.action_masks()[DRINK]
renv.run.hp = 40
assert renv.action_masks()[DRINK]
renv.step(DRINK)
assert renv.run.hp == 56 and renv.run.potions == [None, None, None] and renv.decision == "path"
assert renv.used["BLOOD_POTION"] == 1  # drinks between fights count as uses too


# Review focus 5: potions go into the fight and what's left comes back; uses are counted.
class PotionFirst:
    """A combat model that uses a potion whenever one is legal."""

    def predict(self, obs, action_masks, deterministic=True):
        legal = np.flatnonzero(action_masks)
        potions = legal[legal >= POTION_ACTION]
        return (potions[0] if len(potions) else legal[0]), None


renv.reset(seed=7)
renv.combat = PotionFirst()
renv.run.potions = ["FIRE_POTION", "BLOCK_POTION", None]
renv.play(renv.run.normals[0])
held = [p for p in renv.run.potions if p]
assert renv.used["FIRE_POTION"] == 1 and sum(renv.used.values()) + len(held) == 2, (renv.used, held)

print("run env checks ok")
