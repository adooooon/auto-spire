"""Self-check for the sim's ported rules: python -m sim.test_engine (from agent/)."""
import random

from .engine import MONSTERS, SimCombat, SimClient, pick_move, player_attack_damage, ENCOUNTERS

# Damage: floor(base * 1.5 vuln * 0.7 shrink), exact.
assert player_attack_damage(6, False, False) == 6
assert player_attack_damage(6, True, False) == 9
assert player_attack_damage(6, False, True) == 4  # 4.2
assert player_attack_damage(6, True, True) == 6  # 6.3
assert player_attack_damage(20, False, True) == 14  # float 20*0.7 would floor to 13

rng = random.Random(0)
# CannotRepeat on both branches => strict alternation after a random first move.
leaf = MONSTERS["LEAF_SLIME_S"]
log = [pick_move(leaf.first, [], rng)]
for _ in range(20):
    log.append(pick_move(leaf.follow[log[-1]], log, rng))
assert all(a != b for a, b in zip(log, log[1:])), log
# Twig M: Pokey Pounce at most twice in a row, Sticky Shot never twice in a row.
twig = MONSTERS["TWIG_SLIME_M"]
log = [twig.first]
for _ in range(500):
    log.append(pick_move(twig.follow[log[-1]], log, rng))
s = "".join("P" if m == "POKEY_POUNCE_MOVE" else "S" for m in log)
assert "PPP" not in s and "SS" not in s and "PP" in s, s[:40]

# Flyconid: cooldowns can zero every branch; the game then falls back to the first one.
fly = MONSTERS["FLYCONID"]
assert pick_move(fly.follow["SMASH_MOVE"], ["VULNERABLE_SPORES_MOVE", "FRAIL_SPORES_MOVE", "SMASH_MOVE"], rng) \
    == "VULNERABLE_SPORES_MOVE"
# Mawler: Roar at most once per fight.
log = ["CLAW_MOVE"]
for _ in range(200):
    log.append(pick_move(MONSTERS["MAWLER"].follow[log[-1]], log, rng))
assert log.count("ROAR_MOVE") <= 1, log

# Slimed: costs 1, draws 1, exhausts.
c = SimCombat(rng=random.Random(1))
c.fight("NIBBITS_WEAK")
c.hand[0] = "SLIMED"
n = len(c.hand)
c.play_card(0)
assert c.energy == 2 and len(c.hand) == n and c.exhaust_pile == ["SLIMED"]

# Targeting: hits the chosen combatId; dead/out-of-range targets are rejected.
c = SimCombat(rng=random.Random(3))
c.fight("SLIMES_WEAK")
c.hand[0] = "STRIKE_IRONCLAD"
hp = [e.hp for e in c.enemies]
c.play_card(0, 3)
assert [e.hp for e in c.enemies] == hp[:2] + [max(0, hp[2] - 6)], (hp, [e.hp for e in c.enemies])
c.enemies[1].hp = 0
c.hand[0] = "STRIKE_IRONCLAD"
assert c.play_card(0, 2)["error"] == "invalid_target" and c.play_card(0, 9)["error"] == "invalid_target"

# Killing the Shrinker Beetle removes the player's Shrink (ShrinkPower.AfterDeath).
c = SimCombat(rng=random.Random(5))
c.fight("OVERGROWTH_CRAWLERS")
c.shrunk, c.enemies[0].hp, c.hand[0] = True, 1, "STRIKE_IRONCLAD"
c.play_card(0, 1)
assert not c.shrunk and c.in_combat

# Slippery: first HP loss capped at 1. Artifact: eats Bash's Vulnerable.
c = SimCombat(rng=random.Random(6))
c.fight("INKLETS_NORMAL")
hp = c.enemies[0].hp
c.hand[0] = "STRIKE_IRONCLAD"
c.play_card(0, 1)
assert c.enemies[0].hp == hp - 1 and c.enemies[0].slippery == 0
c = SimCombat(rng=random.Random(6))
c.fight("CUBEX_CONSTRUCT_NORMAL")
assert c.enemies[0].block == 13 and c.enemies[0].artifact == 1
c.hand[0] = "BASH"
c.play_card(0, 1)
assert c.enemies[0].vulnerable == 0 and c.enemies[0].artifact == 0 and c.enemies[0].block == 5

# Tangled: Attacks cost +1 for one player turn.
c = SimCombat(rng=random.Random(7))
c.fight("VINE_SHAMBLER_NORMAL")
c.enemies[0].move = "GRASPING_VINES_MOVE"
c.end_turn()
assert c.tangled == 1 and c.combat_dict()["player"]["hand"][0]["cost"] in (1, 2, 3)
assert all(h["cost"] == 2 for h in c.combat_dict()["player"]["hand"] if h["id"] == "STRIKE_IRONCLAD")
c.end_turn()
assert c.tangled == 0

# Constrict: blockable damage at the end of the player's turn; gone when the Strangler dies.
c = SimCombat(rng=random.Random(8))
c.fight("SLITHERING_STRANGLER_NORMAL")
c.constrict, c.player_block, hp = 3, 1, c.player_hp
c.enemies[-1].move = "CONSTRICT"
for e in c.enemies[:-1]:
    e.hp = 0
c.end_turn()
assert c.player_hp == hp - 2 and c.constrict == 6, (c.player_hp, hp, c.constrict)
c.enemies[-1].hp, c.hand[0] = 1, "STRIKE_IRONCLAD"
c.play_card(0, len(c.enemies))
assert not c.in_combat and c.won and c.constrict == 0

# Fogmog: summons an Eye (acts next turn); the Eye revives, Dazed is Ethereal, and killing
# Fogmog wins with the Eye alive.
c = SimCombat(rng=random.Random(9))
c.fight("FOGMOG_NORMAL")
c.end_turn()
eye = c.enemies[0]  # summons go in front (FogmogNormal.Slots)
assert eye.defn.model_id == "EYE_WITH_TEETH" and eye.move == "DISTRACT_MOVE" and "DAZED" not in c.discard_pile
c.end_turn()
assert sum(pile.count("DAZED") for pile in (c.draw_pile, c.hand, c.discard_pile, c.exhaust_pile)) == 3
eye.hp = 1
c.hand[0] = "STRIKE_IRONCLAD"
c.play_card(0, 1)
assert not eye.is_alive and eye.in_combat and c.in_combat and eye.move == "REVIVE_MOVE"
assert [e["isAlive"] for e in c.combat_dict()["enemies"]] == [False, True]
c.hand.append("DAZED")
c.end_turn()
assert eye.hp == eye.max_hp and eye.move == "DISTRACT_MOVE" and "DAZED" in c.exhaust_pile
c.enemies[1].hp, c.hand[0] = 1, "STRIKE_IRONCLAD"
c.play_card(0, 2)
assert c.won and eye.is_alive
w = __import__("collections").Counter(pick_move(MONSTERS["FOGMOG"].follow["SWIPE_MOVE"], ["SWIPE_MOVE"], rng)
                                       for _ in range(5000))
assert 0.36 < w["SWIPE_RANDOM_MOVE"] / 5000 < 0.44, w

# Every encounter runs to completion under a random policy.
for enc in ENCOUNTERS:
    sim = SimClient(seed=2)
    for _ in range(50):
        sim.exec("fight " + enc)
        while sim.combat()["inCombat"]:
            hand = sim.combat()["player"]["hand"]
            playable = [i for i, h in enumerate(hand) if h["canPlay"]]
            (sim.play(rng.choice(playable)) if playable and rng.random() < 0.8 else sim.end_turn())

from env import ENCOUNTER_GROUPS  # noqa: E402

assert set(ENCOUNTER_GROUPS["act1"]) == set(ENCOUNTERS), "env encounter groups out of sync with the sim"

# Env: every masked-legal action is accepted by the sim (no invalid actions).
from env import STS2CombatEnv  # noqa: E402

env = STS2CombatEnv(encounter=list(ENCOUNTERS), client=SimClient(seed=4))
for _ in range(100):
    env.reset()
    done = False
    while not done:
        _, _, term, trunc, info = env.step(int(rng.choice(env.action_masks().nonzero()[0])))
        assert not info.get("invalid_action"), info
        done = term or trunc
# Env: dying is a loss (the last in-combat snapshot still shows HP > 0).
env = STS2CombatEnv(encounter="OVERGROWTH_CRAWLERS", client=SimClient(seed=1))
env.reset()
done = False
while not done:
    _, r, term, trunc, info = env.step(env.action_space.n - 1)  # only ever end turn
    done = term or trunc
assert term and info["won"] is False and info["player_hp"] == 0 and r < 0, (info, r)
print("sim self-check ok")
