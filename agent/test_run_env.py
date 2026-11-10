"""Checks for the combat env's loop guard and the run policy env. Run from agent/: python test_run_env.py"""
from env import END_TURN, STS2CombatEnv
from env import N_ACTIONS as COMBAT_ACTIONS, OBS_DIM as COMBAT_OBS, POTION_ACTION, MAX_ENEMIES, _encode, random_relics
from sim.relics import RELIC_IDS
from sim.potions import POTION_IDS
assert COMBAT_OBS == 3122 and COMBAT_ACTIONS == 392  # + the colorless prompts (3 kinds, 3 generated one-hots, 7 sources; 3 + 1 + 143 + 1 actions), + the upgrade prompt and True Grit / Armaments as its sources, + 53 colorless cards, RetainHandPower and the 14 colorless powers
from env import CHOICE_FEATURES, POTION_FEATURES, PROMPT_FEATURES, RELIC_FEATURES, UPGRADE_FEATURES
POT0 = COMBAT_OBS - PROMPT_FEATURES - UPGRADE_FEATURES - CHOICE_FEATURES - RELIC_FEATURES  # where the relic block starts
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

# Relics: live /combat has no sim keys, so every appended feature is zero.
env = STS2CombatEnv(encounter="NIBBITS_WEAK", client=SimClient(seed=0), heal=False, episodes_per_restart=10**9)
env._episode_count = 1
env.relics, env.relic_state, env.potions = {"VAJRA", "POTION_BELT"}, {"pen_nib": 3}, ["BLOCK_POTION"] * 5
obs, _ = env.reset(seed=0)
live = {k: v for k, v in env._combat.items() if k not in ("simRelics", "relicCounters", "potionSlots")}
assert not _encode(live)[POT0:].any()
assert obs.max() <= 10
assert obs[POT0 + 2 * len(POTION_IDS) + RELIC_IDS.index("VAJRA")] == 1
pen = POT0 + 2 * len(POTION_IDS) + len(RELIC_IDS)
assert abs(obs[pen] - 0.3) < 1e-6
assert env.action_masks()[POTION_ACTION + 4 * MAX_ENEMIES]
env._combat = live
assert not env.action_masks()[POTION_ACTION:].any()
env.relics = {"VAJRA"}
env._combat = None
env.reset(seed=0)
assert not env.action_masks()[POTION_ACTION + 4 * MAX_ENEMIES:].any()
rng = np.random.default_rng(0)
seen, sizes = set(), set()
for i in range(5000):
    r, st = random_relics(rng)
    assert len(r) <= 6 and r <= set(RELIC_IDS)
    sizes.add(len(r))
    owner = {"lizard_used": "LIZARD_TAIL", "tea_set": "VENERABLE_TEA_SET"}
    cap = {"pen_nib": 9, "nunchaku": 9, "tuning_fork": 9, "happy_flower": 2, "pendulum": 2, "joss_paper": 4, "lizard_used": 1, "tea_set": 1}
    assert all(k in cap and 0 <= v <= cap[k] and owner.get(k, k.upper()) in r for k, v in st.items()), (r, st)
    seen |= r
assert seen == set(RELIC_IDS) and {0, 6} <= sizes

from run_env import CARD_INDEX, EVENT_OBS, N_ACTIONS, OBS_DIM, PICK, REMOVE, SHOP, SHOP_LEAVE, SHOP_REMOVE, UPGRADE_OBS, RunPolicyEnv
from sim.act import Shop

from run_env import SHOP_RELIC, potion_take_action, drink_action, POTION_TAKE_2, DRINK_2

assert N_ACTIONS == 327 and OBS_DIM == 2027  # +53 colorless card ids (was 221 / 1603). Act 2: 3 more bosses, an act flag, 2 more card ids; Armaments adds 1 action, 7 obs;  11 relics modeled in Task 4: +11 relic obs in the combat env, +44 in the run env; rest: 3 + 90 actions, 5 + 90 + 5 obs

# Smoke: random run decisions + random combat. Masks never empty, obs in bounds, every run ends.
renv, rng, floors = RunPolicyEnv(), np.random.default_rng(0), []
for seed in range(200):
    obs, _ = renv.reset(seed=seed)
    if seed % 4 == 0:
        renv.run.obtain("POTION_BELT", "elite")  # 5 slots must not change the observation size
        obs = renv._obs()
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

# Review focus 2: an offer of only unmodeled cards leaves only "skip".
renv.reset(seed=1)
renv.decision, renv.offered = "pick", ["NOT_A_CARD"]
assert np.flatnonzero(renv.action_masks()).tolist() == [PICK + 3]

# Review focus 3: a broke player in a shop can only leave; removal is masked once used.
renv.decision, renv.run.gold = "shop", 0
renv.run.shop = Shop(["NOT_A_CARD"] * 5, [50] * 5, 75)
assert np.flatnonzero(renv.action_masks()).tolist() == [SHOP_LEAVE]
renv.run.gold, renv.run.shop = 1000, Shop(["SHRUG_IT_OFF", None, "NOT_A_CARD", None, None], [50] * 5, 75)
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

# Hand of Greed's gold goes to the run after the fight.
import run_env as _run_env
renv.reset(seed=2)
gold, real_fight = renv.run.gold, _run_env.play_fight


def greedy(model, env, seed=None):
    env.reset(seed=seed)
    env.client._combat.gold_gained = 25
    return True, 0


_run_env.play_fight = greedy
try:
    renv.play(renv.run.normals[0])
finally:
    _run_env.play_fight = real_fight
assert renv.run.gold == gold + 25, (gold, renv.run.gold)

# Review focus 1: a sim error inside a fight ends the run as a loss.
renv.reset(seed=3)
renv.fight_env.client.exec = boom
_, _, done, _, info = renv.step(int(np.flatnonzero(renv.action_masks())[0]))
assert done and info["died_at"] == "A1:Monster" and not info["cleared"]

# MapRunModeEnv: fights chain through generated-map runs; HP carries between fights.
from run import MapRunModeEnv
from run_env import RandomCombat

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
assert cenv.action_space.n == COMBAT_ACTIONS == 392 and COMBAT_OBS == 3122
# Review focus 1: live play (no potionSlots in /combat) never offers a potion.
cenv._combat = {"player": {"hand": []}, "enemies": [{"isAlive": True, "combatId": 1}, {"isAlive": True, "combatId": 2}]}
assert not cenv.action_masks()[POTION_ACTION:].any()
cenv._combat["potionSlots"] = ["FIRE_POTION", "ATTACK_POTION", "BLOCK_POTION"]
assert np.flatnonzero(cenv.action_masks()[POTION_ACTION:]).tolist() == [0, 1, 2 * MAX_ENEMIES]  # Fire x2 targets, Block on 0
# Review focus 2: a potion that ends the fight is a win, minus the use cost.
cenv.potions = ["EXPLOSIVE_AMPOULE", None, None]
obs, _ = cenv.reset(seed=0)
assert obs.shape == (COMBAT_OBS,) and obs[POT0 - POTION_FEATURES + POTION_IDS.index("EXPLOSIVE_AMPOULE")] == 1
alive = [e for e in cenv.client._combat.enemies if e.is_alive]
for e in alive:
    e.hp = 5
cenv._combat = cenv.client.combat()
_, r, term, _, info = cenv.step(POTION_ACTION)
assert term and info["won"] and cenv.client._combat.potions == [None, None, None]
assert abs(r - (5 * len(alive) / 10 + 5.0 - POTION_COST_HP / 10)) < 1e-6, r

# Run env potions (sub-project 2).
from run_env import HEAD_DECISIONS, DRINK, POTION_SKIP, POTION_TAKE, SHOP_POTION

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
renv.decision, renv.offered, renv.run.pending = "pick", ["ARMAMENTS", "HEADBUTT", "BRAND"], [("potion", "ATTACK_POTION")]
renv.step(PICK + 3)
assert renv.decision == "path" and renv.run.potion_drop is None
renv.decision, renv.run.pending = "pick", [("potion", "WEAK_POTION")]
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


# --- Relics (sub-project 3) ---
from sim.act import SHOP_RELICS
from sim.relics import NOT_MODELED

assert POTION_TAKE_2 == SHOP_RELIC + SHOP_RELICS and DRINK_2 == POTION_TAKE_2 + 2
assert [potion_take_action(i) for i in range(5)] == [POTION_TAKE + i for i in range(3)] + [POTION_TAKE_2, POTION_TAKE_2 + 1]
assert [drink_action(i) for i in range(5)] == [DRINK + i for i in range(3)] + [DRINK_2, DRINK_2 + 1]


def shop_env(relics, prices, gold, held=()):
    e = RunPolicyEnv()
    e.reset(seed=0)
    e.run.relics |= set(held)
    e.run.shop = Shop([None] * 5, [0] * 5, 75, relics=relics, relic_prices=prices)
    e.run.gold, e.decision, e.back = gold, "shop", "shop"
    return e


# Orrery bought mid-shop runs its 5 picks, then returns to the shop.
renv = shop_env(["ORRERY", "MEMBERSHIP_CARD", "POTION_BELT"], [200, 100, 100], 1000)
renv.step(SHOP_RELIC)
for _ in range(5):
    assert renv.decision == "pick"
    renv.step(PICK + 3)
assert renv.decision == "shop" and renv.run.gold == 800

# Masks: unmodeled relic never legal; unaffordable relic masked; Membership Card halves entries (mask and obs).
unm = sorted(NOT_MODELED)[0]
renv = shop_env([unm, "MEMBERSHIP_CARD", "POTION_BELT"], [10, 100, 120], 110)
assert renv.action_masks()[SHOP_RELIC:SHOP_RELIC + 3].tolist() == [False, True, False]
renv.step(SHOP_RELIC + 1)
assert renv.run.gold == 10 and renv.run.relics == {"MEMBERSHIP_CARD"}
renv.run.gold = 60
assert renv.action_masks()[SHOP_RELIC + 2]  # 120 -> 60: affordable only at half price
o = renv._obs()
base = OBS_DIM - UPGRADE_OBS - 1 - EVENT_OBS - 3 * (len(RELIC_IDS) + 2)
assert abs(o[base + 2 * (len(RELIC_IDS) + 2) + len(RELIC_IDS)] - 0.6) < 1e-6
assert not o[base:base + len(RELIC_IDS)].any() and o[base + len(RELIC_IDS)] > 0  # unmodeled: no one-hot, price shown
assert o[base - len(RELIC_IDS) + RELIC_IDS.index("MEMBERSHIP_CARD")] == 1
renv.step(SHOP_RELIC + 2)
assert renv.run.gold == 0 and len(renv.run.potions) == 5

# Potion Belt: slots 3-4 usable.
renv.reset(seed=1)
renv.run.potions = ["FIRE_POTION"] * 3
renv.decision, renv.run.gold = "shop", 1000
renv.run.shop = Shop([None] * 5, [0] * 5, 75, potions=["BLOCK_POTION", None, None], potion_prices=[10, 0, 0])
assert not renv.action_masks()[SHOP_POTION]
renv.run.obtain("POTION_BELT", "shop")
assert renv.action_masks()[SHOP_POTION]
renv.decision, renv.run.potion_drop = "potion", "WEAK_POTION"
assert renv.action_masks()[potion_take_action(4)] and renv.action_masks()[potion_take_action(3)]
renv.step(potion_take_action(4))
assert renv.run.potions[4] == "WEAK_POTION"
renv.decision, renv.run.potions[4], renv.run.hp = "path", "BLOOD_POTION", 10
assert renv.action_masks()[drink_action(4)]
renv.step(drink_action(4))
assert renv.run.potions[4] is None and renv.run.hp > 10
renv.reset(seed=1)
renv.run.potions = [None] * 3
renv.decision, renv.run.potion_drop = "potion", "WEAK_POTION"
assert not renv.action_masks()[POTION_TAKE_2:POTION_TAKE_2 + 2].any()

# Cauldron with full slots: 5 potion decisions in a row, unmodeled skipped.
renv.reset(seed=2)
renv.run.potions = ["FIRE_POTION"] * 3
renv.run.pending = [("potion", "WEAK_POTION"), ("potion", "ATTACK_POTION"), ("potion", "FIRE_POTION")] + [("potion", "BLOCK_POTION")] * 2
renv._advance()
seen = 0
while renv.decision == "potion":
    assert renv.action_masks()[POTION_SKIP] and renv.action_masks()[POTION_TAKE:POTION_TAKE + 3].all()
    seen += 1
    renv.step(POTION_SKIP)
assert seen == 4 and renv.decision == "path" and renv.run.potion_drop is None

# Elite drop of an unmodeled relic: next decision is pick, relic in relic_log.
renv.reset(seed=3)
renv.run.bags.pull = lambda *a, **k: unm
renv.room = "Elite"
renv.run.node = renv.run.map.start
renv.run.potion_odds.roll = lambda *a, **k: False
renv.after_fight(True)
assert (unm, "elite") in renv.run.relic_log and renv.decision == "pick"
renv.step(PICK + 3)
assert renv.decision == "path"

# Carry through play: Pen Nib count, Lizard Tail flag, Strawberry max HP.
renv.reset(seed=4)
renv.run.obtain("STRAWBERRY", "elite")
renv.run.relics |= {"PEN_NIB", "LIZARD_TAIL"}
renv.run.relic_state.update(pen_nib=5, lizard_used=1)
assert renv.run.max_hp == 87
renv.play(renv.run.normals[0])
assert renv.fight_env.client._combat.player_max_hp == 87 and renv.run.max_hp == 87
p1 = renv.run.relic_state["pen_nib"]
assert renv.run.relic_state["lizard_used"] == 1 and p1 != 5, renv.run.relic_state
renv.play(renv.run.normals[1])  # second fight: counts on from p1, not from 5 or 0
assert renv.run.relic_state["lizard_used"] == 1 and renv.run.max_hp >= 87
assert renv.run.relic_state["pen_nib"] != p1, renv.run.relic_state

# Potion Belt must not change the observation size or move earlier indices.
renv.reset(seed=4)
renv.decision, renv.run.potion_drop = "potion", "WEAK_POTION"
before = renv._obs()
renv.run.obtain("POTION_BELT", "elite")
after = renv._obs()
assert after.shape == (OBS_DIM,)
cut = OBS_DIM - UPGRADE_OBS - 1 - EVENT_OBS - (2 * len(POTION_IDS) + len(RELIC_IDS) + 3 * (len(RELIC_IDS) + 2))
assert (after[:cut] == before[:cut]).all()

# MapRunModeEnv takes Hand of Greed's gold after a fight too: the same fight with and without it differs by that gold.
after = []
for greed in (0, 25):
    menv = MapRunModeEnv(run_model=None)
    menv.reset(seed=5)
    c = menv.client._combat
    c.gold_gained = greed
    for e in c.enemies:
        e.hp = 0
    c._check_win()
    _, _, term, trunc, _ = menv.step(int(np.flatnonzero(menv.action_masks())[0]))
    assert term or trunc
    after.append(menv.driver.run.gold)
assert after[1] - after[0] == 25, after

# Carry through MapRunModeEnv reset/step.
menv = MapRunModeEnv(run_model=None)
menv.driver.done = False
menv.driver.reset(seed=5)
menv.driver.run.obtain("STRAWBERRY", "elite")
menv.driver.run.relics |= {"PEN_NIB", "LIZARD_TAIL"}
menv.driver.run.relic_state.update(pen_nib=5, lizard_used=1)
menv.reset(seed=5)
c = menv.client._combat
assert c.player_max_hp == menv.driver.run.max_hp >= 87 and c.relic_state is menv.driver.run.relic_state, (c.player_max_hp, menv.driver.run.max_hp)
n0 = menv.driver.run.relic_state["pen_nib"]
assert n0 == 5
done = False
while not done:
    _, _, term, trunc, info = menv.step(int(rng2.choice(np.flatnonzero(menv.action_masks()))))
    done = term or trunc
st = menv.driver.run.relic_state
assert st["lizard_used"] == 1 and st["pen_nib"] != 5, st
assert menv.driver.run.max_hp == menv.client._combat.player_max_hp >= 87

# Bounds: Old Coin gold stays within the observation range.
renv.reset(seed=6)
renv.run.gold = 5000
assert renv._obs().max() <= 10
assert renv._obs()[len(HEAD_DECISIONS) + 2] == 10

# info keys
_, _, _, _, info = renv.step(int(np.flatnonzero(renv.action_masks())[0]))
assert {"relic_log", "relics_held", "elites_fought"} <= set(info)
import pickle
pickle.dumps(info)

# Baseline plays a whole run with Potion Belt held, no illegal action.
import run as runmod

runmod._model = RandomCombat(np.random.default_rng(0))
benv = RunPolicyEnv()
benv.reset(seed=8)
benv.run.obtain("POTION_BELT", "elite")
brng, done, trunc = __import__("random").Random(0), False, False
while not (done or trunc):
    _, _, done, trunc, info = benv.step(runmod.baseline_action(benv, brng, 1))
assert done

# Report: the honesty line counts per source from relic_log.
line = runmod.honesty([{"relic_log": [("VAJRA", "elite"), ("LANTERN", "elite"), ("RAZOR_TOOTH", "treasure"), ("ORRERY", "shop")]}])
assert line == ("honesty: elite n=2 common=100% uncommon=0% rare=0% unmodeled=0% (expect 50/33/17, 11.6) | "
                "treasure n=1 common=0% uncommon=0% rare=100% unmodeled=100% (expect 50/33/17, 12.3) | bought n=1"), line

print("run env checks ok")

# --- events ---------------------------------------------------------------------------------------------
from run_env import EVENT, EVENT_OBS, PATH, REST
E0 = OBS_DIM - UPGRADE_OBS - 1 - EVENT_OBS  # where the event block starts
from sim.events import EVENT_OPTIONS, MODELED_EVENTS

assert REST == EVENT + EVENT_OPTIONS == 181 and EVENT_OBS == 1 + 5 + 6 + len(CARD_INDEX)
renv = RunPolicyEnv()
obs, _ = renv.reset(seed=11)
assert not obs[E0:E0 + EVENT_OBS].any()  # all zero off an event, so a grown model sees what it knew


def enter_event(env, name):
    """Force the next path step onto `name`, through the real enter()."""
    node = env.run.choices()[0]
    node.type = "Unknown"
    env.run.unknown_odds.roll = lambda rng, block: "Event"
    env.run.events[:] = [name] + [e for e in env.run.events if e != name]
    env.run.events_visited = 0
    env.step(PATH + node.col)
    assert env.run.events_seen[-1] == name


for name in MODELED_EVENTS:
    renv.reset(seed=11)
    if name == "SLIPPERY_BRIDGE":
        for child in renv.run.node.children:
            child.row = 7
        renv.run.deck.append("ANGER")
    enter_event(renv, name)
    assert renv.decision == "event", name
    m = renv.action_masks()
    assert m[EVENT] and m[EVENT + 1] and m.sum() == 2
    o = renv._obs()
    tail = o[E0:E0 + EVENT_OBS]
    assert tail[0] == 1 and tail[1 + MODELED_EVENTS.index(name)] == 1 and o.shape == (OBS_DIM,)
    if name == "SLIPPERY_BRIDGE":
        assert tail[12 + CARD_INDEX["ANGER"]] == 1
    if name == "SUNKEN_STATUE":
        assert tail[6 + 3] == 7 / 80 and 1.0 < tail[6 + 4] < 1.3

# The Legends Were True: choosing the potion leads to the potion decision (if modeled), then back to the path.
for seed in range(40):
    renv.reset(seed=seed)
    enter_event(renv, "THE_LEGENDS_WERE_TRUE")
    renv.step(EVENT + 1)
    assert renv.run.event is None and renv.decision in ("potion", "path") and not renv.done
    if renv.decision == "potion":
        assert renv.run.potion_drop
        renv.step(renv.action_masks().nonzero()[0][-1])
    assert renv.decision == "path"
    assert renv.action_masks()[PATH:PATH + 7].any()

# Dying in an event ends the run like a lost fight, with no clear bonus.
renv.reset(seed=11)
renv.run.hp = 5
enter_event(renv, "SUNKEN_STATUE")
o, rew, done, trunc, info = renv.step(EVENT + 1)
assert done and rew == 0 and not info["cleared"] and info["died_at"] == "A1:Event"
assert info["event_log"][0][:3] == ("SUNKEN_STATUE", 1, 5) and info["events_seen"] == ["SUNKEN_STATUE"]
assert renv.action_masks().any()

# An unmodeled event is an empty room.
renv.reset(seed=11)
enter_event(renv, "TEA_MASTER" if renv.run.gold >= 150 else "THIS_OR_THAT")
assert renv.decision == "path" and renv.run.event is None
# Event practice (training only): half of modeled events start from random HP and gold, unmodeled ones never.
penv = RunPolicyEnv(event_practice=True)
changed = 0
for i in range(200):
    penv.reset(seed=i)
    penv.run.hp, penv.run.gold = 40, 77
    enter_event(penv, "THE_LEGENDS_WERE_TRUE")
    assert penv.decision == "event" and penv.run.event == "THE_LEGENDS_WERE_TRUE"
    assert 10 <= penv.run.hp <= penv.run.max_hp and 0 <= penv.run.gold <= 400
    changed += (penv.run.hp, penv.run.gold) != (40, 77)
assert 70 <= changed <= 130, changed
penv.reset(seed=1)
penv.run.hp, penv.run.gold = 40, 77
enter_event(penv, "THIS_OR_THAT")  # an unmodeled event: an empty room
assert (penv.run.hp, penv.run.gold) == (40, 77)
for i in range(20):  # off by default, so evaluation stays on real runs
    renv.reset(seed=i)
    renv.run.hp, renv.run.gold = 40, 77
    enter_event(renv, "THE_LEGENDS_WERE_TRUE")
    assert (renv.run.hp, renv.run.gold) == (40, 77)
print("event env checks ok")

import gzip
import pickle
from env import CHOOSE_DISCARD, CHOOSE_HAND, CHOICE_FEATURES, CARD_IDS, UPGRADE_FEATURES, combat_maps, random_deck
from sim.cards import CHOICE_CARDS
from sim.cards import card_to_dict
fx = pickle.load(gzip.open("test_data/grow_fixture.pkl.gz"))  # recorded before upgrades (test_data/record_grow_fixture.py)

# Every old input has the same value at its new index, and new inputs read 0 with no new cards.
obs_map, act_map = combat_maps()
assert len(fx["combat"]) >= 40 and sum(bool(c.get("choice")) for c, _ in fx["combat"]) >= 5
for c, old in fx["combat"]:
    new_obs = _encode(c)
    assert np.array_equal(new_obs[obs_map], old)
    assert not np.delete(new_obs, obs_map).any()
assert len(act_map) == 190 and COMBAT_OBS == len(new_obs)  # the pre-upgrade action count
assert act_map[:CHOOSE_DISCARD] == list(range(CHOOSE_DISCARD)) and CHOOSE_DISCARD + CARD_IDS.index("ARMAMENTS") not in act_map


def choice_env(hand, discard=(), draw=None):
    env = STS2CombatEnv(encounter="MAWLER_NORMAL", client=SimClient(seed=0))
    env.deck, env.potions, env.relics, env.relic_state = list(hand), [], set(), {}
    env._episode_count = 1
    env.reset(seed=0)
    c = env.client._combat
    c.hand, c.discard_pile, c.energy = list(hand), list(discard), 3
    if draw is not None:
        c.draw_pile = list(draw)
    env._combat = env.client.combat()
    return env, c


# A hand prompt: only the legal slots are open, and the action resolves it.
env, c = choice_env(["BURNING_PACT", "WOUND", "BASH"])
env.step(0)
m = env.action_masks()
assert m.nonzero()[0].tolist() == [CHOOSE_HAND, CHOOSE_HAND + 1]
obs = _encode(env._combat)
C0 = COMBAT_OBS - PROMPT_FEATURES - UPGRADE_FEATURES - CHOICE_FEATURES  # where the prompt block starts
U0 = C0 + CHOICE_FEATURES  # the upgrade prompt block
assert obs[C0] == 1 and obs[C0 + 2 + CHOICE_CARDS.index("BURNING_PACT")] == 1 and not obs[C0 + CHOICE_FEATURES:].any()
env.step(CHOOSE_HAND + 1)
assert c.exhaust_pile == ["BASH"] and c.pending_choice is None and env.action_masks()[END_TURN]

# A discard prompt: open by card id.
env, c = choice_env(["HEADBUTT"], ["BASH", "WOUND", "WOUND"])
env.step(0)
m = env.action_masks()
assert m.nonzero()[0].tolist() == sorted(CHOOSE_DISCARD + CARD_IDS.index(x) for x in ("BASH", "WOUND"))
env.step(CHOOSE_DISCARD + CARD_IDS.index("BASH"))
assert c.draw_pile[-1] == "BASH"

# An upgrade prompt (Armaments): only the upgradable slots are open, and the action upgrades that slot.
env, c = choice_env(["ARMAMENTS", "WOUND", "BASH+", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD"])
env.step(0)
assert env.action_masks().nonzero()[0].tolist() == [CHOOSE_HAND + 2, CHOOSE_HAND + 3]
obs = _encode(env._combat)
assert obs[U0:U0 + UPGRADE_FEATURES].tolist() == [1, 0, 1]  # the upgrade prompt, asked by Armaments
assert not obs[C0:U0].any() and not obs[U0 + UPGRADE_FEATURES:].any()  # not a hand or discard prompt
env.step(CHOOSE_HAND + 3)
assert c.hand == ["WOUND", "BASH+", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD+"] and c.pending_choice is None

# True Grit+ asks which hand card to exhaust: a hand prompt, with True Grit as its source.
env, c = choice_env(["TRUE_GRIT+", "WOUND", "BASH"])
env.step(0)
obs = _encode(env._combat)
assert obs[C0] == 1 and obs[U0:U0 + UPGRADE_FEATURES].tolist() == [0, 1, 0]

# The colorless prompts (appended actions and the last obs block): each kind's mask holds exactly its legal answers.
from env import CHOOSE_DONE, CHOOSE_DRAW, CHOOSE_GENERATED, CHOOSE_SKIP, COLORLESS_PROMPT_CARDS, N_ACTIONS as CA
assert (CHOOSE_GENERATED, CHOOSE_SKIP, CHOOSE_DRAW, CHOOSE_DONE, CA) == \
    (CHOOSE_DISCARD + len(CARD_IDS), CHOOSE_DISCARD + len(CARD_IDS) + 3, CHOOSE_DISCARD + len(CARD_IDS) + 4,
     CHOOSE_DISCARD + 2 * len(CARD_IDS) + 4, CHOOSE_DISCARD + 2 * len(CARD_IDS) + 5)
P0, NC = COMBAT_OBS - PROMPT_FEATURES, len(CARD_IDS)
SRC0 = P0 + 3 + 3 * NC
assert PROMPT_FEATURES == 3 + 3 * NC + len(COLORLESS_PROMPT_CARDS) and "STRATAGEM" not in COLORLESS_PROMPT_CARDS


def prompt_obs(env, kind, source):
    obs = _encode(env._combat)
    assert obs.shape == (COMBAT_OBS,) == env.observation_space.shape
    assert obs[P0:P0 + 3].tolist() == [float(kind == k) for k in ("generated", "draw", "hand_multi")]
    assert obs[SRC0:].tolist() == [float(source == s) for s in COLORLESS_PROMPT_CARDS]
    return obs


env, c = choice_env(["DISCOVERY"])  # generated: the 3 options and skip
env.step(0); opts = c.pending_choice["options"]
assert env.action_masks().nonzero()[0].tolist() == [CHOOSE_GENERATED, CHOOSE_GENERATED + 1, CHOOSE_GENERATED + 2, CHOOSE_SKIP]
obs = prompt_obs(env, "generated", "DISCOVERY")
assert not obs[C0:P0].any() and obs[P0 + 3:SRC0].sum() == 3
assert [int(np.flatnonzero(obs[P0 + 3 + k * NC:P0 + 3 + (k + 1) * NC])[0]) for k in range(3)] == [CARD_IDS.index(o) for o in opts]
env.step(CHOOSE_GENERATED + 2); assert c.hand == [opts[2]] and c.pending_choice is None and env.action_masks()[END_TURN]
env, c = choice_env(["DISCOVERY"]); env.step(0); env.step(CHOOSE_SKIP); assert c.hand == [] and c.pending_choice is None
env, c = choice_env(["SECRET_TECHNIQUE"], draw=["STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "SHRUG_IT_OFF", "DEFEND_IRONCLAD"])  # draw, by id
env.step(0)
assert env.action_masks().nonzero()[0].tolist() == sorted(CHOOSE_DRAW + CARD_IDS.index(x) for x in ("DEFEND_IRONCLAD", "SHRUG_IT_OFF"))
prompt_obs(env, "draw", "SECRET_TECHNIQUE")
env.step(CHOOSE_DRAW + CARD_IDS.index("SHRUG_IT_OFF")); assert c.hand == ["SHRUG_IT_OFF"] and c.pending_choice is None
env, c = choice_env(["SEEKER_STRIKE"], draw=["STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "BASH", "ANGER", "SHRUG_IT_OFF"])
env.step(0); opts = c.pending_choice["options"]
assert env.action_masks().nonzero()[0].tolist() == sorted(CHOOSE_DRAW + CARD_IDS.index(x) for x in opts)
prompt_obs(env, "draw", "SEEKER_STRIKE")
env.step(CHOOSE_DRAW + CARD_IDS.index(opts[0])); assert c.hand == [opts[0]] and c.pending_choice is None
env, c = choice_env(["PURITY", "WOUND", "BASH"])  # hand_multi: the hand slots and done
env.step(0)
assert env.action_masks().nonzero()[0].tolist() == [CHOOSE_HAND, CHOOSE_HAND + 1, CHOOSE_DONE]
prompt_obs(env, "hand_multi", "PURITY")
env.step(CHOOSE_HAND); assert env.action_masks().nonzero()[0].tolist() == [CHOOSE_HAND, CHOOSE_DONE]
env.step(CHOOSE_DONE); assert c.exhaust_pile == ["WOUND", "PURITY"] and c.hand == ["BASH"] and c.pending_choice is None
env, c = choice_env(["THINKING_AHEAD", "WOUND"], draw=["STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "BASH"])  # hand, its own source
env.step(0)
assert env.action_masks().nonzero()[0].tolist() == [CHOOSE_HAND, CHOOSE_HAND + 1, CHOOSE_HAND + 2]
assert prompt_obs(env, None, "THINKING_AHEAD")[C0] == 1
env.step(CHOOSE_HAND); assert c.draw_pile[-1] == "WOUND"
env, c = choice_env(["ENTROPY"], draw=["STRIKE_IRONCLAD"] * 10)  # Entropy's hand prompt opens at the next turn start
env.step(0); env.step(END_TURN)
assert env.action_masks().nonzero()[0].tolist() == [CHOOSE_HAND + i for i in range(5)]
assert prompt_obs(env, None, "ENTROPY")[C0] == 1
env.step(CHOOSE_HAND + 1); assert c.hand[1] != "STRIKE_IRONCLAD" and c.pending_choice is None and env.action_masks()[END_TURN]

# Review focus 5: live has no simRelics, so the three cards stay masked and a live pick can't take them.
live = {k: v for k, v in env.client.combat().items() if k != "simRelics"}
live["choice"] = None
live["player"]["hand"] = [card_to_dict(c, 0, True) for c in ("BRAND", "BRAND+", "ARMAMENTS", "TRUE_GRIT+", "ARMAMENTS+", "TRUE_GRIT")]
env._combat = live
assert env.action_masks()[:6 * MAX_ENEMIES:MAX_ENEMIES].tolist() == [False] * 4 + [True] * 2
live["player"]["hand"] = [card_to_dict(x, 0, True) for x in COLORLESS_PROMPT_CARDS + ("STRATAGEM",)]  # Stratagem picks at random
assert env.action_masks()[:8 * MAX_ENEMIES:MAX_ENEMIES].tolist() == [False] * 7 + [True]

# Prompt practice, in decks only and only when asked.
rng = np.random.default_rng(0)
decks = [random_deck(rng, prompt_practice=True) for _ in range(4000)]
assert 0.50 < np.mean([any(x in CHOICE_CARDS for x in d) for d in decks]) < 0.68
assert 0.20 < np.mean(["WOUND" in d for d in decks]) < 0.30
assert all(d.count("WOUND") <= 2 for d in decks)
assert set(CHOICE_CARDS) <= {x for d in decks for x in d}
assert not any("WOUND" in random_deck(rng) for _ in range(500))
print("choice env checks ok")

from run_env import REMOVE, run_maps
obs_map, act_map = run_maps()
renv.reset(seed=1)
assert {s["decision"] for s in fx["run_states"]} == {"path", "pick", "shop", "remove", "potion", "event"}
from run_env import SHOP_RELIC, SLOT_FEATURES
from sim.act import ALL_BOSSES
from sim.relics import UPGRADE_RELICS
S0 = len(HEAD_DECISIONS) + 5 + len(CARD_IDS) + len(ALL_BOSSES)  # the offer / shop slots
R0 = OBS_DIM - UPGRADE_OBS - 1 - EVENT_OBS - 3 * (len(RELIC_IDS) + 2)  # the shop's relics


def became_modeled(env, decision):
    """Armaments was a placeholder before upgrades (not in CARDS) and the upgrade relics were unmodeled: an old state's slot
    holding one read no identity and couldn't be taken. Now it can, so its price / buyable inputs and its action may differ
    (old indices), and its one-hot is set (a new index). Returns those old-input, new-input and action indices."""
    shop = decision in ("shop", "remove")
    cards = env.run.shop.cards if shop else env.offered if decision == "pick" else []
    arm = [i for i, c in enumerate(cards) if c == "ARMAMENTS"]
    rel = [k for k, r in enumerate(env.run.shop.relics if shop else []) if r in UPGRADE_RELICS]
    old = {S0 + i * SLOT_FEATURES + SLOT_FEATURES - j for i in arm for j in (1, 2)} | {R0 + k * (len(RELIC_IDS) + 2) + len(RELIC_IDS) + 1 for k in rel}
    new = {S0 + i * SLOT_FEATURES + CARD_INDEX["ARMAMENTS"] for i in arm}
    new |= {R0 + k * (len(RELIC_IDS) + 2) + RELIC_IDS.index(env.run.shop.relics[k]) for k in rel}
    act = {(SHOP if shop else PICK) + i for i in arm} | {SHOP_RELIC + k for k in rel}
    return old, new, act


not_old = np.isin(np.arange(OBS_DIM), obs_map, invert=True)
for s in fx["run_states"]:  # old states, read by the new env
    renv.run, renv.decision, renv.offered, renv.back = s["run"], s["decision"], s["offered"], s["back"]
    new_obs, new_mask = renv._obs(), renv.action_masks()
    ok_old, ok_new, ok_act = became_modeled(renv, s["decision"])
    assert set(np.array(obs_map)[new_obs[obs_map] != s["obs"]]) <= ok_old, s["decision"]
    assert set(np.flatnonzero(not_old & (new_obs != 0))) <= ok_new, s["decision"]
    assert set(np.array(act_map)[new_mask[act_map] != s["mask"]]) <= ok_act and not np.delete(new_mask, act_map).any(), s["decision"]
assert fx["run_obs"].shape == (200, len(obs_map)) and fx["run_mask"].shape == (200, len(act_map)) == (200, 127)
from env import UPGRADE_CARDS
old_ids = sorted(set(CARD_IDS) - UPGRADE_CARDS)  # a model before upgrades lacks Armaments and the colorless cards
assert act_map[REMOVE + old_ids.index("TRUE_GRIT")] == REMOVE + CARD_IDS.index("TRUE_GRIT")

# All three cards can be picked.
renv.reset(seed=1)
renv.decision, renv.offered = "pick", ["HEADBUTT", "ARMAMENTS", "BRAND"]
m = renv.action_masks()
assert m[PICK] and m[PICK + 1] and m[PICK + 2]

# Choices made in a run's fights reach info, and the report reads them.
from run import choice_report
line = choice_report([{"choice_log": [("BRAND", "WOUND", ("WOUND", "BASH")), ("HEADBUTT", "BASH", ("BASH", "WOUND"))]}])
assert "BRAND: 1 (junk 100% of 1)" in line and "HEADBUTT: 1 (non-basic non-junk 100% of 1)" in line
line = choice_report([{"choice_log": [("HEADBUTT", "WOUND", ("WOUND", "BASH")), ("BRAND", "BASH", ("BASH", "BASH"))]}])
assert "HEADBUTT: 1 (non-basic non-junk 0% of 1)" in line and "BRAND: 1 (junk n=0)" in line
print("run choice checks ok")

# --- rest sites and upgraded cards -----------------------------------------------------------------------
import time
from collections import Counter
from run_env import REST, REST_OPTIONS, SMITH
from sim.act import SHOP_SLOTS
from sim.cards import is_upgraded, upgrade
from sim.relics import UPGRADE_RELICS

assert REST_OPTIONS == ("HEAL", "LIFT", "DIG") and SMITH == REST + 3 and N_ACTIONS == SMITH + len(CARD_IDS)
U0 = OBS_DIM - UPGRADE_OBS  # rest flag, Heal/Smith/Lift/Dig available, deck upgraded counts, slot upgraded flags


def enter_rest(env, deck, relics=()):
    """Through the real enter(): the next path step is a rest site."""
    env.reset(seed=1)
    env.run.deck, env.run.hp = list(deck), 30
    env.run.relics |= set(relics)
    node = env.run.choices()[0]
    node.type = "RestSite"
    env.step(PATH + node.col)
    assert env.decision == "rest" and env.run.hp == 30  # entering no longer heals


# The mask is exactly rest_options(), and Smith only the deck's un-upgraded upgradable base ids.
enter_rest(renv, ["BASH", "BASH+", "STRIKE_IRONCLAD+", "WOUND", "DEFEND_IRONCLAD"], ["GIRYA"])
assert renv.run.rest_options() == ["HEAL", "SMITH", "LIFT"]
assert np.flatnonzero(renv.action_masks()).tolist() == [REST, REST + 1] + sorted(SMITH + CARD_INDEX[c] for c in ("BASH", "DEFEND_IRONCLAD"))
o = renv._obs()
assert o.shape == (OBS_DIM,) and o[U0:U0 + 5].tolist() == [1, 1, 1, 1, 0] and not o[:len(HEAD_DECISIONS)].any()
up = o[U0 + 5:U0 + 5 + len(CARD_IDS)]
assert up[CARD_INDEX["BASH"]] == up[CARD_INDEX["STRIKE_IRONCLAD"]] == 0.5 and up.sum() == 1
renv.step(SMITH + CARD_INDEX["BASH"])
assert sorted(renv.run.deck) == ["BASH+", "BASH+", "DEFEND_IRONCLAD", "STRIKE_IRONCLAD+", "WOUND"] and renv.decision == "path"
assert renv.run.hp == 30 and not renv._obs()[U0:U0 + 5].any()
# Nothing to Smith: no Smith actions. Lift counts on Girya; Dig obtains a relic.
enter_rest(renv, ["BASH+", "WOUND"], ["GIRYA", "SHOVEL"])
assert np.flatnonzero(renv.action_masks()).tolist() == [REST, REST + 1, REST + 2]
renv.step(REST + 1)
assert renv.run.relic_state["girya"] == 1 and renv.run.hp == 30
enter_rest(renv, ["BASH"], ["SHOVEL"])
renv.step(REST + 2)
assert renv.run.relic_log[-1][1] == "dig" and renv.decision in ("path", "pick", "potion")
enter_rest(renv, ["BASH"])
assert np.flatnonzero(renv.action_masks()).tolist() == [REST, SMITH + CARD_INDEX["BASH"]]
renv.step(REST)
assert renv.run.hp == 30 + int(renv.run.max_hp * 0.3) and renv.decision == "path"

# A deck holding only "BASH+" removes it by the base id.
renv.reset(seed=1)
renv.decision, renv.run.gold, renv.run.deck = "shop", 1000, ["BASH+", "STRIKE_IRONCLAD"]
renv.run.shop = Shop(["ANGER+", "BASH", None, None, None], [50] * 5, 75)
o = renv._obs()
assert o[S0 + CARD_INDEX["ANGER"]] == 1 and o[S0 + SLOT_FEATURES - 2] == 0.5 and o[S0 + SLOT_FEATURES + CARD_INDEX["BASH"]] == 1
assert o[-len(SHOP_SLOTS):].tolist() == [1, 0, 0, 0, 0] and renv.action_masks()[SHOP]
renv.step(SHOP_REMOVE)
assert np.flatnonzero(renv.action_masks()).tolist() == sorted(REMOVE + CARD_INDEX[c] for c in ("BASH", "STRIKE_IRONCLAD"))
renv.step(REMOVE + CARD_INDEX["BASH"])
assert renv.run.deck == ["STRIKE_IRONCLAD"] and renv.decision == "shop"
# An upgraded offer: identity at its base id, the flag in its slot, and picking adds the upgraded card.
renv.decision, renv.offered = "pick", ["ANGER", "BASH+", "NOT_A_CARD"]
o = renv._obs()
assert o[S0 + CARD_INDEX["ANGER"]] == 1 and o[S0 + SLOT_FEATURES + CARD_INDEX["BASH"]] == 1
assert o[-len(SHOP_SLOTS):].tolist() == [0, 1, 0, 0, 0] and renv.action_masks()[PICK + 1] and not renv.action_masks()[PICK + 2]
renv.step(PICK + 1)
assert renv.run.deck[-1] == "BASH+"

# Baseline: Heal below half HP, else Smith the first upgradable non-basic card, else Heal.
brng = __import__("random").Random(0)
enter_rest(renv, ["STRIKE_IRONCLAD", "WOUND", "ANGER+", "INFLAME", "SHRUG_IT_OFF"])
renv.run.hp = renv.run.max_hp // 2
assert runmod.baseline_action(renv, brng, 1) == SMITH + CARD_INDEX["INFLAME"]
renv.run.hp -= 1
assert runmod.baseline_action(renv, brng, 1) == REST
enter_rest(renv, ["STRIKE_IRONCLAD", "BASH", "ANGER+"])
renv.run.hp = renv.run.max_hp
assert runmod.baseline_action(renv, brng, 1) == REST

# Review focus 1: 300 random-policy runs, each deck seeded with 6 upgraded cards (a third also hold 3 upgrade relics), end
# without an exception. Fights count as wins so every run reaches rest sites, shops and Act 2's upgraded offers; a
# third of them first play a real random-policy fight against Thieving Hopper, whose steal leaves the run deck.
t0 = time.time()
fenv, frng, seen = RunPolicyEnv(), np.random.default_rng(5), Counter()
real_play = fenv.play


def win(encounter):
    if frng.integers(3) == 0:
        deck, hp = Counter(fenv.run.deck), fenv.run.hp
        real_play("THIEVING_HOPPER_WEAK")
        stolen = fenv.fight_env.client._combat.stolen
        assert Counter(fenv.run.deck) == deck - Counter(stolen) and len(stolen) <= 1, (stolen, deck)
        seen["stolen"] += len(stolen)
        seen["stolen upgraded"] += sum(map(is_upgraded, stolen))
        fenv.run.hp = hp
    fenv.run.fight_hit = bool(frng.integers(2))  # Lava Lamp lights after a fight with no hit
    return True


fenv.play = win
for seed in range(300):
    fenv.reset(seed=seed)
    run = fenv.run
    for i in frng.choice(len(run.deck), 6, replace=False):
        run.deck[i] = upgrade(run.deck[i])
    if seed % 3 == 0:
        for r in frng.choice(sorted(UPGRADE_RELICS), 3, replace=False):
            run.obtain(str(r), "elite")
    obs, done, trunc = fenv._obs(), False, False
    while not (done or trunc):
        mask = fenv.action_masks()
        assert obs.shape == (OBS_DIM,) and obs.min() >= -1 and obs.max() <= 10 and mask.any(), fenv.decision
        a, d = int(frng.choice(np.flatnonzero(mask))), fenv.decision
        seen[d] += 1
        if d == "rest":
            seen["SMITH" if a >= SMITH else REST_OPTIONS[a - REST]] += 1
        elif d == "remove":
            seen["remove upgraded"] += CARD_IDS[a - REMOVE] not in run.deck
        elif d == "pick" and a < PICK + 3:
            seen["pick upgraded"] += is_upgraded(fenv.offered[a - PICK])
        elif d == "shop" and a < SHOP_REMOVE:
            seen["buy upgraded"] += is_upgraded(run.shop.cards[a - SHOP])
        obs, _, done, trunc, info = fenv.step(a)
    assert done and info["cleared"], seed
assert all(seen[k] for k in ("HEAL", "SMITH", "LIFT", "DIG", "remove", "remove upgraded", "pick upgraded", "buy upgraded", "stolen", "stolen upgraded")), seen
print(f"rest and upgrade checks ok ({time.time() - t0:.0f}s for 300 runs: {dict(seen)})")

# A client without set_relics (the live game) never gets a prompt card in a random deck.
from sim.cards import CHOICE_CARDS as _CC
class _Live:
    def __init__(self): self._c = SimClient(seed=0)
    def __getattr__(self, n):
        if n in ("set_relics", "set_potions"): raise AttributeError(n)
        return getattr(self._c, n)
    def set_deck(self, d): self.last = d; self._c.set_deck(d)
_live = _Live()
_e = STS2CombatEnv(client=_live, random_decks=True, prompt_practice=True, heal=False)
for _s in range(60):
    _e.reset(seed=_s)
    assert not set(_live.last) & set(_CC), _live.last
print("live deck strip ok")

# Live run: the game's state fills what the policy reads, and its fallback for unreadable events is safe.
from live import LiveRun, _event_opts, _fallback_option, _shop
from run_env import OBS_DIM as RUN_OBS_DIM

live_env = RunPolicyEnv()
live = LiveRun()
live.sync({"player": {"hp": 50, "maxHp": 80, "gold": 200, "deck": [{"id": "BASH"}, {"id": "NOT_A_SIM_CARD"}],
                      "relics": [{"id": "GORGET"}]}, "potionSlots": ["SPEED_POTION", None, None]})
live.sync_map({"current": {"col": 3, "row": 0}, "boss": "VANTOM_BOSS", "points": [
    {"col": 3, "row": 0, "type": "Ancient", "children": [{"col": 2, "row": 1}, {"col": 4, "row": 1}]},
    {"col": 2, "row": 1, "type": "Monster", "children": [{"col": 3, "row": 16}]},
    {"col": 4, "row": 1, "type": "Unknown", "children": [{"col": 3, "row": 16}]},
    {"col": 3, "row": 16, "type": "Boss", "children": []}]})
live_env.run, live_env.done, live_env.decision, live_env.offered = live, False, "path", []
assert live.deck == ["BASH"] and live_env._obs().shape == (RUN_OBS_DIM,)
assert list(np.flatnonzero(live_env.action_masks())) == [PATH + 2, PATH + 4]
live.shop = _shop({"cards": [{"id": "BASH", "cost": 50}, {"cost": 60}], "relics": [], "potions": []})
live_env.decision = "shop"
assert len(live.shop.cards) == 5 and live.shop.removal_used and live_env.action_masks()[SHOP]
assert _event_opts("JUNGLE_MAZE_ADVENTURE", {"SoloGold": 140, "JoinForcesGold": 55}) == [(18, 140, 0), (0, 55, 0)]
opt = lambda key, **kw: {"key": key, "locked": False, "kills": False, **kw}
assert _fallback_option([opt("A"), opt("B.LEAVE")]) == 1
assert _fallback_option([opt("A", kills=True), opt("B")]) == 1
assert _fallback_option([opt("A"), opt("B", relic="GORGET")]) == 1
# Upgrades: "X+" ids from the upgraded flag, the live rest mask, and removal taking the plain copy first (Run.remove).
from live import _removal_index
from run_env import REST, SMITH
live.sync({"player": {"hp": 50, "maxHp": 80, "gold": 200, "relics": [], "deck": [
    {"id": "BASH", "upgraded": True}, {"id": "STRIKE_IRONCLAD", "upgraded": True}, {"id": "STRIKE_IRONCLAD", "upgraded": False}]},
    "potionSlots": [None] * 3})
assert live.deck == ["BASH+", "STRIKE_IRONCLAD+", "STRIKE_IRONCLAD"]
live.rest_opts, live_env.decision = ["HEAL", "SMITH", "HATCH"], "rest"
assert list(np.flatnonzero(live_env.action_masks())) == [REST, SMITH + CARD_INDEX["STRIKE_IRONCLAD"]]
assert _shop({"cards": [{"id": "BASH", "upgraded": True, "cost": 50}], "relics": [], "potions": []}).cards[0] == "BASH+"
assert _removal_index(["STRIKE_IRONCLAD", "BASH", "STRIKE_IRONCLAD"], [True, False, False], "STRIKE_IRONCLAD") == 2
assert _removal_index(["STRIKE_IRONCLAD", "BASH"], [True, False], "STRIKE_IRONCLAD") == 0
assert _removal_index(["BASH"], [False], "INFLAME") == 0 and _removal_index(["BASH"], [False], None) == 0
print("live run mapping ok")
