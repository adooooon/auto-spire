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

# Every encounter runs to completion under a random policy.
for enc in ENCOUNTERS:
    sim = SimClient(seed=2)
    for _ in range(50):
        sim.exec("fight " + enc)
        while sim.combat()["inCombat"]:
            hand = sim.combat()["player"]["hand"]
            playable = [i for i, h in enumerate(hand) if h["canPlay"]]
            (sim.play(rng.choice(playable)) if playable and rng.random() < 0.8 else sim.end_turn())

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
print("sim self-check ok")
