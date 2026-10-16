"""Self-check for the sim's ported rules: python -m sim.test_engine (from agent/)."""
import random

from .engine import PLAYER_MAX_HP, MONSTERS, SimCombat, SimClient, pick_move, player_attack_damage, ENCOUNTERS

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

# Ironclad Commons.
def solo(hand, encounter="MAWLER_NORMAL", seed=10):
    """A fight with a known hand, empty piles and 3 energy."""
    c = SimCombat(rng=random.Random(seed))
    c.fight(encounter)
    c.hand, c.draw_pile, c.discard_pile, c.exhaust_pile = list(hand), ["DEFEND_IRONCLAD"] * 5, [], []
    c.player_block = 0
    return c


c = solo(["TWIN_STRIKE", "SETUP_STRIKE", "STRIKE_IRONCLAD"])
hp = c.enemies[0].hp
c.play_card(0, 1)  # Twin Strike 5x2
c.play_card(0, 1)  # Setup Strike 7, then +2 Strength this turn
c.play_card(0, 1)  # Strike 6+2
assert hp - c.enemies[0].hp == 10 + 7 + 8 and c.strength == 2
c.end_turn()
assert c.strength == 0 and c.temp_strength == 0
c = solo(["IRON_WAVE", "BODY_SLAM"])
hp = c.enemies[0].hp
c.play_card(0, 1)
c.play_card(0, 1)  # Body Slam = current block (5)
assert hp - c.enemies[0].hp == 10 and c.player_block == 5
c = solo(["PERFECTED_STRIKE"])
c.draw_pile, hp = ["STRIKE_IRONCLAD"] * 3, c.enemies[0].hp
c.play_card(0, 1)  # 6 + 2 * (3 Strikes + itself)
assert hp - c.enemies[0].hp == 14
c = solo(["BASH", "MOLTEN_FIST"])
c.play_card(0, 1)
c.play_card(0, 1)  # Vulnerable 2 doubled to 4; Exhaust
assert c.enemies[0].vulnerable == 4 and c.exhaust_pile == ["MOLTEN_FIST"]
c = solo(["THUNDERCLAP", "BREAKTHROUGH"], "SLIMES_NORMAL")
hps = [e.hp for e in c.enemies]
c.play_card(0)
c.play_card(0)
assert all(e.vulnerable == 1 for e in c.enemies if e.is_alive) and c.player_hp == PLAYER_MAX_HP - 1
assert [max(0, h - 4 - 13) for h in hps] == [e.hp for e in c.enemies]  # 4, then 9 x1.5
c = solo(["BLOODLETTING", "BLOOD_WALL"])
c.play_card(0)
assert c.energy == 5 and c.player_hp == PLAYER_MAX_HP - 3
c.play_card(0)
assert c.player_block == 16 and c.player_hp == PLAYER_MAX_HP - 5
c = solo(["ANGER", "SHRUG_IT_OFF"])
c.play_card(0, 1)
assert sorted(c.discard_pile) == ["ANGER", "ANGER"] and c.energy == 3
c.play_card(0)
assert c.player_block == 8 and c.hand == ["DEFEND_IRONCLAD"]
c = solo(["CINDER", "DEFEND_IRONCLAD", "DEFEND_IRONCLAD"])
c.play_card(0, 1)
assert len(c.hand) == 1 and c.exhaust_pile == ["DEFEND_IRONCLAD"]
c = solo(["HAVOC"])
c.draw_pile = ["DEFEND_IRONCLAD", "TWIN_STRIKE"]  # top is the end
hp = c.enemies[0].hp
c.play_card(0)  # plays the top card (Twin Strike) for free and exhausts it; Havoc is discarded
assert hp - c.enemies[0].hp == 10 and c.energy == 2 and c.exhaust_pile == ["TWIN_STRIKE"] and c.discard_pile == ["HAVOC"]
c = solo(["TREMBLE"], "CUBEX_CONSTRUCT_NORMAL")
c.play_card(0, 1)  # Artifact eats it
assert c.enemies[0].vulnerable == 0 and c.enemies[0].artifact == 0
c = solo(["SWORD_BOOMERANG"], "SLIMES_NORMAL")
total = sum(e.hp for e in c.enemies)
c.play_card(0)
assert total - sum(e.hp for e in c.enemies) <= 9 and len(c.discard_pile) == 1

# Elites and bosses.
c = solo(["STRIKE_IRONCLAD"] * 3, "BYGONE_EFFIGY_ELITE")  # Slow: +10% per card already played
c.play_card(0, 1); c.play_card(0, 1); c.play_card(0, 1)
assert c.enemies[0].max_hp - c.enemies[0].hp == 6 + 6 + 7  # 6, 6.6, 7.2
c.end_turn()
assert c.cards_played == 0
c = solo([], "BYRDONIS_ELITE")
c.end_turn()
assert c.enemies[0].strength == 1  # Territorial, after its turn
c = solo(["STRIKE_IRONCLAD"], "PHROG_PARASITE_ELITE")
c.enemies[0].hp = 1
c.play_card(0, 1)
spawned = [e for e in c.enemies if e.is_alive]
assert c.in_combat and [e.move for e in spawned] == ["SPAWNED_MOVE"] * 4
c.end_turn()
assert [e.move for e in spawned] == ["NASTY_BITE_MOVE", "WRIGGLE_MOVE", "NASTY_BITE_MOVE", "WRIGGLE_MOVE"]
c = solo(["INFECTION", "DEFEND_IRONCLAD"], "PHROG_PARASITE_ELITE")
c.enemies[0].move = "INFECT_MOVE"
c.end_turn()  # 3 from the held Infection; the Phrog's turn adds 3 more to the discard pile
assert c.player_hp == PLAYER_MAX_HP - 3 and c.discard_pile.count("INFECTION") + c.hand.count("INFECTION") \
    + c.draw_pile.count("INFECTION") == 4
c = solo(["STRIKE_IRONCLAD"], "CEREMONIAL_BEAST_BOSS")
c.end_turn()  # STAMP: Plow 150
beast = c.enemies[0]
assert beast.plow == 150 and beast.move == "PLOW_MOVE"
c.end_turn()
beast.hp, c.hand[0] = 155, "STRIKE_IRONCLAD"
c.play_card(0, 1)
assert beast.plow == 0 and beast.strength == 0 and beast.move == "STUNNED"
c.end_turn(); c.end_turn()  # stunned turn, then BEAST_CRY: Ringing
assert c.ringing and beast.move == "STOMP_MOVE"
c.hand = ["STRIKE_IRONCLAD", "STRIKE_IRONCLAD"]
c.play_card(0, 1)
assert c.play_card(0, 1)["error"] == "card_not_playable" and not c.combat_dict()["player"]["hand"][0]["canPlay"]
c = solo(["STRIKE_IRONCLAD"], "THE_KIN_BOSS")
assert [e.move for e in c.enemies] == ["POWER_DANCE_MOVE", "QUICK_SLASH_MOVE", "ORB_OF_FRAILTY_MOVE"]
c.weak, hp = 1, c.enemies[2].hp
c.play_card(0, 3)  # Weak: 6 * 0.75 = 4.5 -> 4
assert hp - c.enemies[2].hp == 4
c.enemies[2].hp, c.hand = 1, ["STRIKE_IRONCLAD"]
c.play_card(0, 3)
assert c.won and c.enemies[0].is_alive  # followers are minions

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

env = STS2CombatEnv(encounter=list(ENCOUNTERS), client=SimClient(seed=4), random_decks=True)
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
