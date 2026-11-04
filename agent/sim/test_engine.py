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

# Ironclad Uncommons and Rares (Mawler: 72 HP, opens CLAW 4x2).
c = solo(["WHIRLWIND"])
c.play_card(0)  # X = 3 energy: 3 x 5
assert c.enemies[0].hp == 72 - 15 and c.energy == 0
c = solo(["FEEL_NO_PAIN", "TRUE_GRIT", "STRIKE_IRONCLAD"])
c.play_card(0); c.play_card(0)  # 7 block, exhaust the Strike: +3
assert c.player_block == 10 and c.exhaust_pile == ["STRIKE_IRONCLAD"] and c.discard_pile == ["TRUE_GRIT"]
c = solo(["RUPTURE", "HEMOKINESIS", "STRIKE_IRONCLAD"])
c.play_card(0); c.play_card(0, 1)  # Strength comes after the card that cost the HP
assert c.enemies[0].hp == 72 - 15 and c.strength == 1 and c.player_hp == PLAYER_MAX_HP - 2
c.play_card(0, 1)
assert c.enemies[0].hp == 72 - 15 - 7
c = solo(["INFERNO"])
c.play_card(0); c.end_turn()  # Mawler's claw is blocked by nothing: 8 HP, then Inferno's 1 at turn start
assert c.player_hp == PLAYER_MAX_HP - 8 - 1 and c.enemies[0].hp == 72 - 6
c = solo(["UNMOVABLE", "DEFEND_IRONCLAD", "DEFEND_IRONCLAD"])
c.energy = 4
c.play_card(0); c.play_card(0); c.play_card(0)  # the first block card this turn is doubled
assert c.player_block == 10 + 5
c = solo(["TRUE_GRIT", "STRIKE_IRONCLAD"])
c.play_card(0)  # exhausts the Strike, so Evil Eye blocks twice
c.hand = ["EVIL_EYE"]
c.play_card(0)
assert c.player_block == 7 + 16
c = solo(["JUGGERNAUT", "DEFEND_IRONCLAD"])
c.play_card(0); c.play_card(0)
assert c.enemies[0].hp == 72 - 6
c = solo(["FLAME_BARRIER"])
c.play_card(0); c.end_turn()  # Claw 4x2 into 12 block: 4 back per hit
assert c.enemies[0].hp == 72 - 8 and c.player_hp == PLAYER_MAX_HP and "FlameBarrierPower" not in c.pw
c = solo(["STRIKE_IRONCLAD", "STRIKE_IRONCLAD", "STOMP"])
c.play_card(0, 1); c.play_card(0, 1)
assert c.cost("STOMP") == 1 and c.can_play("STOMP")
c = solo(["ONE_TWO_PUNCH", "STRIKE_IRONCLAD", "STRIKE_IRONCLAD"])
c.play_card(0); c.play_card(0, 1)
assert c.enemies[0].hp == 72 - 12 and "OneTwoPunchPower" not in c.pw
c.play_card(0, 1)
assert c.enemies[0].hp == 72 - 18
c = solo(["JUGGLING", "ANGER", "ANGER", "ANGER"])
c.play_card(0); c.play_card(0, 1); c.play_card(0, 1); c.play_card(0, 1)
assert c.hand == ["ANGER"]  # the 3rd Attack this turn is copied into hand
c = solo(["BATTLE_TRANCE", "POMMEL_STRIKE"])
c.play_card(0)
assert len(c.hand) == 4 and c.pw == {"NoDrawPower": 1}
c.play_card(c.hand.index("POMMEL_STRIKE"), 1)
assert len(c.hand) == 3
c.end_turn()
assert "NoDrawPower" not in c.pw and len(c.hand) == 5
c = solo(["BARRICADE", "DEFEND_IRONCLAD"])
c.energy = 4
c.play_card(0); c.play_card(0); c.end_turn()  # Claw 4x2 into 5 block: 2 left, kept
assert c.player_block == 0 and c.player_hp == PLAYER_MAX_HP - 3
c = solo(["COLOSSUS", "BASH"])
c.play_card(0); c.play_card(0, 1); c.end_turn()  # Vulnerable Mawler hits for half: 2 x 2 into 5 block
assert c.player_hp == PLAYER_MAX_HP and "ColossusPower" not in c.pw
c = solo(["UPPERCUT"])
c.play_card(0, 1)
assert c.enemies[0].weak == 1 and c.enemies[0].vulnerable == 1
assert c.combat_dict()["enemies"][0]["intent"]["intents"][0]["damage"] == 3  # 4 x 0.75
c.end_turn()
assert c.player_hp == PLAYER_MAX_HP - 6 and c.enemies[0].weak == 0
c = solo(["MANGLE"])
c.play_card(0, 1)
assert c.enemies[0].strength == -10 and c.enemies[0].mangle == 10
c.end_turn()
assert c.player_hp == PLAYER_MAX_HP and c.enemies[0].strength == 0
c = solo(["FEED"])
c.enemies[0].hp = 5
c.play_card(0, 1)
assert c.won and c.player_max_hp == PLAYER_MAX_HP + 3
c = solo(["PACTS_END", "PACTS_END"])
c.play_card(0)
assert c.enemies[0].hp == 72
c.exhaust_pile = ["WOUND"] * 3
c.play_card(0)
assert c.enemies[0].hp == 72 - 17
c = solo(["DARK_EMBRACE", "TRUE_GRIT", "STRIKE_IRONCLAD"])
c.play_card(0); c.play_card(0)  # exhausts the Strike, draws a Defend
assert c.hand == ["DEFEND_IRONCLAD"]
c = solo(["HELLRAISER"])
c.draw_pile = ["DEFEND_IRONCLAD"] * 4 + ["TWIN_STRIKE"]
c.play_card(0); c.end_turn()  # Claw 8, then the drawn Twin Strike plays itself
assert c.enemies[0].hp == 72 - 10 and "TWIN_STRIKE" in c.discard_pile and len(c.hand) == 4
c = solo(["PILLAGE"], encounter="CEREMONIAL_BEAST_BOSS")  # Ringing + Hellraiser: Strikes go to discard
c.ringing, c.pw["HellraiserPower"] = True, 1
c.draw_pile, c.discard_pile = ["STRIKE_IRONCLAD"] * 2, ["STRIKE_IRONCLAD"] * 3
c.play_card(0, 1)  # used to reshuffle forever; now stops after one pass
assert c.hand == [] and len(c.draw_pile) + len(c.discard_pile) == 6  # 5 Strikes + Pillage
c = solo(["RAMPAGE", "RAMPAGE"])
c.play_card(0, 1); c.play_card(0, 1)
assert c.enemies[0].hp == 72 - 9 - 14
c = solo(["EXPECT_A_FIGHT", "STRIKE_IRONCLAD", "BASH", "BLOODLETTING"])
c.play_card(0)  # 2 Attacks in hand: +2, then no more energy gain this turn
c.play_card(c.hand.index("BLOODLETTING"))
assert c.energy == 3
c = solo(["STONE_ARMOR"])
c.play_card(0); c.end_turn()  # 4 block at end of turn soaks the Claw's 8 down to 4
assert c.player_hp == PLAYER_MAX_HP - 4 and c.pw["PlatingPower"] == 3
c = solo(["INFERNAL_BLADE"])
c.play_card(0)
assert len(c.hand) == 1 and c.cost(c.hand[0]) == 0 and c.exhaust_pile == ["INFERNAL_BLADE"]
c = solo(["PRIMAL_FORCE", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD"])
c.play_card(0)
assert c.hand == ["GIANT_ROCK", "DEFEND_IRONCLAD"]
c = solo(["CRUELTY", "BASH", "STRIKE_IRONCLAD"])
c.energy = 4
c.play_card(0); c.play_card(0, 1); c.play_card(0, 1)  # 6 x 1.75
assert c.enemies[0].hp == 72 - 8 - 10
c = solo(["VICIOUS", "BASH"])
c.play_card(0); c.play_card(0, 1)
assert len(c.hand) == 1
c = solo(["TEAR_ASUNDER"])
c.end_turn()  # 2 unblocked Claw hits
c.hand = ["TEAR_ASUNDER"]
c.play_card(0, 1)
assert c.enemies[0].hp == 72 - 15
c = solo(["CASCADE"])
c.draw_pile = ["DEFEND_IRONCLAD", "STRIKE_IRONCLAD", "STRIKE_IRONCLAD"]
c.play_card(0)  # X = 3: plays the top 3 for free
assert c.enemies[0].hp == 72 - 12 and c.player_block == 5 and c.energy == 0

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
from env import END_TURN, STS2CombatEnv  # noqa: E402

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
    _, r, term, trunc, info = env.step(END_TURN)  # only ever end turn
    done = term or trunc
assert term and info["won"] is False and info["player_hp"] == 0 and r < 0, (info, r)
# A reshuffle loop (like Pillage under Ringing + Hellraiser was) raises instead of hanging.
from .engine import MAX_SHUFFLES, SimLoopError
c = solo(["DEFEND_IRONCLAD"])
c.draw_pile, c.discard_pile, c.shuffles = [], ["STRIKE_IRONCLAD"], MAX_SHUFFLES
try:
    c._take_top()
    raise AssertionError("expected SimLoopError")
except SimLoopError:
    pass
c.fight("NIBBITS_WEAK")
assert c.shuffles == 0  # the cap is per fight
# Potions (sim/potions.py; effects from Models/Potions/*.OnUse). Potion damage and Block Potion's
# block are Unpowered: block absorbs the damage, but Strength/Vulnerable/Weak/Dexterity/Frail don't apply.
from .potions import POTION_POOL, POTIONS

assert len(POTIONS) == 12 and all(p in POTION_POOL["COMMON"] for p in POTIONS)
assert all(len(v) == 16 for v in POTION_POOL.values())


def potion(pid, hand=("DEFEND_IRONCLAD",), encounter="MAWLER_NORMAL"):
    c = solo(list(hand), encounter)
    c.potions = [pid, None, None]
    return c


c = potion("BLOCK_POTION")
c.frail, c.dexterity = 2, 3
assert c.use_potion(0)["ok"] and c.player_block == 12 and c.potions == [None, None, None]
c = potion("DEXTERITY_POTION")
c.use_potion(0)
c.play_card(0)
assert c.player_block == 5 + 2
c = potion("DEXTERITY_POTION")
c.use_potion(0)
c.frail = 1
c.play_card(0)
assert c.player_block == (5 + 2) * 3 // 4  # Dexterity (additive) before Frail (multiplicative)
c = potion("SPEED_POTION")
c.use_potion(0)
c.play_card(0)
assert c.player_block == 10 and c.dexterity == 5
c.end_turn()
assert c.dexterity == 0 and c.temp_dexterity == 0
c = potion("ENERGY_POTION")
e0 = c.energy
c.use_potion(0)
assert c.energy == e0 + 2
c = potion("STRENGTH_POTION")
c.use_potion(0)
c.end_turn()
assert c.strength == 2
c = potion("FLEX_POTION")
c.use_potion(0)
assert c.strength == 5
c.end_turn()
assert c.strength == 0
c = potion("SWIFT_POTION", hand=())
c.use_potion(0)
assert len(c.hand) == 3
c = potion("FIRE_POTION")
m = c.enemies[0]
m.block, m.vulnerable, hp = 5, 2, m.hp
c.strength, c.weak = 3, 1
assert c.use_potion(0, 1)["ok"] and hp - m.hp == 15 and m.block == 0
c = potion("FIRE_POTION")
assert "error" in c.use_potion(0) and c.potions[0] == "FIRE_POTION"  # an enemy potion needs a target
c = potion("EXPLOSIVE_AMPOULE", encounter="SLIMES_NORMAL")
before = [(e.hp, e.block) for e in c.enemies]
c.use_potion(0)
assert [e.hp for e in c.enemies[:len(before)]] == [max(0, h - max(0, 10 - b)) for h, b in before]
c = potion("VULNERABLE_POTION")
c.use_potion(0, 1)
assert c.enemies[0].vulnerable == 3
c = potion("WEAK_POTION")
c.use_potion(0, 1)
assert c.enemies[0].weak == 3
c = potion("BLOOD_POTION")
c.player_hp, c.player_max_hp = 40, 83
c.use_potion(0)
assert c.player_hp == 40 + 16  # 20% of max HP, truncated (Creature.SetCurrentHpInternal)
# Review focus 2: a potion that kills the last enemy wins the fight.
c = potion("FIRE_POTION")
c.enemies[0].hp = 15
c.use_potion(0, 1)
assert c.won and not c.in_combat
c = potion(None)
assert "error" in c.use_potion(0)
# The client sets potions; they survive fight() and show up as potionSlots.
s = SimClient(seed=0)
s.set_potions(["FIRE_POTION"])
s.exec("fight NIBBITS_WEAK")
assert s.combat()["potionSlots"] == ["FIRE_POTION", None, None]
nib = s.combat()["enemies"][0]["combatId"]
assert s.exec(f"potion 0 {nib}")["ok"] and s.combat()["potionSlots"] == [None, None, None]
# Golden pin: relic-less fights must never change (relic code must not leak into them).
import hashlib  # noqa: E402

from .cards import COMMONS, RARES, UNCOMMONS, starter_deck  # noqa: E402
from .potions import POTION_IDS  # noqa: E402


def _no_relic_trace() -> str:
    """Every fight state on seeded random play. Any change here means relic code leaked into relic-less fights."""
    h = hashlib.sha256()
    for seed in range(66):
        rng = random.Random(seed)
        c = SimCombat(rng=random.Random(seed))
        c.potions = [rng.choice(POTION_IDS), None, rng.choice(POTION_IDS)]
        c.fight(ENCOUNTERS[seed % len(ENCOUNTERS)], starter_deck() + rng.choices(COMMONS + UNCOMMONS + RARES, k=6))
        for _ in range(300):
            if not c.in_combat:
                break
            playable = [i for i, x in enumerate(c.hand) if c.can_play(x)]
            try:
                if rng.random() < 0.05:
                    c.use_potion(rng.randrange(3), 1)  # an empty slot or dead target just returns an error
                c.play_card(rng.choice(playable)) if playable and rng.random() < 0.8 else c.end_turn()
            except SimLoopError:
                break
            h.update(repr((c.player_hp, c.player_block, c.energy, c.hand, c.round, [e.hp for e in c.enemies])).encode())
    return h.hexdigest()


assert _no_relic_trace() == "b373260410a683476a810544b86c91c65e3e3b3061ff8fe2763770e7baa63d93"
# --- relics (sim/relics.py) ---------------------------------------------------------------------
from .relics import NOT_MODELED, RELIC_POOL, RELICS, relic_rarity  # noqa: E402
from .potions import MAX_POTION_SLOTS  # noqa: E402

assert [len(v) for v in RELIC_POOL.values()] == [26, 32, 38, 26]
assert len({r for v in RELIC_POOL.values() for r in v}) == 122 and len(RELICS) == 97 and len(NOT_MODELED) == 25
assert [len([r for r in v if r in RELICS]) for v in RELIC_POOL.values()] == [24, 28, 30, 15]
assert relic_rarity("VAJRA") == "COMMON" and relic_rarity("BRIMSTONE") == "SHOP" and MAX_POTION_SLOTS == 5


def rc(*relics, deck=None, enc="NIBBITS_WEAK", state=None, hp=None, seed=0):
    c = SimCombat(rng=random.Random(seed))
    c.relics, c.relic_state = set(relics), {} if state is None else state
    if hp is not None:
        c.player_hp = hp
    c.fight(enc, deck or ["DEFEND_IRONCLAD"] * 20)
    return c


def energies(c, turns=3):
    """Energy at the start of each of the first `turns` turns, ending each turn unplayed."""
    out = []
    for _ in range(turns):
        out.append(c.energy)
        c.end_turn()
    return out


# GORGET: Plating 4 at turn 1 (3 on turn 2); its block at end of turn soaks 4 of the enemy's hit.
c, base = rc("GORGET"), rc()
assert c.pw["PlatingPower"] == 4
c.end_turn(), base.end_turn()
assert c.pw["PlatingPower"] == 3 and c.player_hp - base.player_hp == min(4, 80 - base.player_hp)
# ODDLY_SMOOTH_STONE: Defend gives 6.
c = rc("ODDLY_SMOOTH_STONE")
c.play_card(0)
assert c.player_block == 6
# VAJRA: Strike hits for 7.
c = rc("VAJRA", deck=["STRIKE_IRONCLAD"] * 20)
e = c.enemies[0]
hp = e.hp + e.block
c.play_card(0, 1)
assert hp - (e.hp + e.block) == 7
# SLING_OF_COURAGE: 2 Strength on elites only.
assert rc("SLING_OF_COURAGE", enc="BYRDONIS_ELITE").strength == 2 and rc("SLING_OF_COURAGE").strength == 0
# ANCHOR: 10 block survives into turn 1, then clears normally on turn 2.
c = rc("ANCHOR")
assert c.player_block == 10
c.end_turn()
assert c.player_block == 0
# PANTOGRAPH: heal 25 before a boss fight only.
assert rc("PANTOGRAPH", hp=30, enc="VANTOM_BOSS").player_hp == 55 and rc("PANTOGRAPH", hp=30).player_hp == 30
# BELT_BUCKLE: +2 Dexterity while no potions are held; once, not twice.
assert rc("BELT_BUCKLE").dexterity == 2
c = SimCombat(rng=random.Random(0))
c.relics, c.potions = {"BELT_BUCKLE"}, ["BLOCK_POTION", None, None]
c.fight("NIBBITS_WEAK")
assert c.dexterity == 0
c.use_potion(0)
assert c.dexterity == 2 and "error" in c.use_potion(0) and c.dexterity == 2
# A no-potion fight, then a potion fight on the same combat: the second starts at 0 and gets +2 once.
c = SimCombat(rng=random.Random(0))
c.relics = {"BELT_BUCKLE"}
c.fight("NIBBITS_WEAK")
assert c.dexterity == 2
c.potions = ["BLOCK_POTION", None, None]
c.fight("NIBBITS_WEAK")
assert c.dexterity == 0
c.use_potion(0)
assert c.dexterity == 2
# BAG_OF_MARBLES: 1 Vulnerable on every enemy at turn 1; Artifact negates it.
c = rc("BAG_OF_MARBLES", enc="SLIMES_WEAK")
assert len(c.enemies) > 1 and all(e.vulnerable == 1 for e in c.enemies)
c = rc("BAG_OF_MARBLES", enc="CUBEX_CONSTRUCT_NORMAL")
assert c.enemies[0].vulnerable == 0 and c.enemies[0].artifact == 0
c = rc("BAG_OF_MARBLES", "RED_MASK", enc="CUBEX_CONSTRUCT_NORMAL")  # Marbles first spends the Artifact charge
assert (c.enemies[0].vulnerable, c.enemies[0].weak, c.enemies[0].artifact) == (0, 1, 0)
c = rc("BAG_OF_MARBLES", "RED_MASK", enc="SLIMES_WEAK")
c.end_turn()  # turn 1 only: the debuffs tick down in the enemy turn and are not re-applied
assert all(e.vulnerable == 0 and e.weak == 0 for e in c.enemies)
# RED_MASK: 1 Weak on every enemy at turn 1.
c = rc("RED_MASK", enc="SLIMES_WEAK")
assert all(e.weak == 1 for e in c.enemies)


def blocks(c, turns=4):
    out = []
    for _ in range(turns):
        out.append(c.player_block)
        c.end_turn()
    return out


# HORN_CLEAT / CAPTAINS_WHEEL: block when turn 2 / turn 3 starts, after the clear.
assert blocks(rc("HORN_CLEAT")) == [0, 14, 0, 0] and blocks(rc("CAPTAINS_WHEEL")) == [0, 0, 18, 0]
# SPARKLING_ROUGE: +1 Strength and Dexterity on turn 3.
c = rc("SPARKLING_ROUGE")
c.end_turn()
assert (c.strength, c.dexterity) == (0, 0)
c.end_turn()
assert (c.strength, c.dexterity) == (1, 1)
c.end_turn()
assert (c.strength, c.dexterity) == (1, 1)  # turn 4
# STURDY_CLAMP: block is kept at the start of a turn, capped at 10.
for have, kept in ((15, 10), (7, 7)):
    c = rc("STURDY_CLAMP")
    c.round, c.player_block = 2, have
    c._start_player_turn()
    assert c.player_block == kept
c = rc("STURDY_CLAMP", deck=["DEFEND_IRONCLAD"] * 20)
c.pw["BarricadePower"] = 1  # ponytail: Barricade assumed to be the block-clear preventer before Sturdy Clamp
c.round, c.player_block = 2, 15
c._start_player_turn()
assert c.player_block == 15
# ICE_CREAM: unspent energy carries from turn 2 on (1 unspent on turn 1 gives 4).
c = rc("ICE_CREAM")
c.play_card(0), c.play_card(0)
c.end_turn()
assert c.energy == 4
c.energy = 2
c.fight("NIBBITS_WEAK", ["DEFEND_IRONCLAD"] * 20)  # fight() never resets energy: no carry-over into turn 1
assert c.energy == 3
# BREAD: turn 1 loses 2 (to 1), then max energy is 4.
assert energies(rc("BREAD"), 2) == [1, 4]
# ART_OF_WAR: +1 on turn 2 only after a turn with no Attack.
c = rc("ART_OF_WAR")
c.play_card(0)  # a Skill is not an Attack
c.end_turn()
assert c.energy == 4
c = rc("ART_OF_WAR")
c.end_turn()
assert c.energy == 4
c = rc("ART_OF_WAR", deck=["STRIKE_IRONCLAD"] * 20)
c.play_card(0, 1)
c.end_turn()
assert c.energy == 3 and rc("ART_OF_WAR").energy == 3
# VENERABLE_TEA_SET: the flag gives +2 once and clears.
st = {"tea_set": 1}
c = rc("VENERABLE_TEA_SET", state=st)
assert c.energy == 5 and st["tea_set"] == 0
c.end_turn()
assert c.energy == 3
# LANTERN / CANDELABRA / CHANDELIER: +1 on turn 1, +2 on turn 2, +3 on turn 3.
assert energies(rc("LANTERN")) == [4, 3, 3] and energies(rc("CANDELABRA")) == [3, 5, 3]
assert energies(rc("CHANDELIER"), 4) == [3, 3, 6, 3]
# HAPPY_FLOWER: every 3rd turn, counted across fights.
assert energies(rc("HAPPY_FLOWER")) == [3, 3, 4]
st = {"happy_flower": 2}
c = rc("HAPPY_FLOWER", state=st)
assert c.energy == 4 and st["happy_flower"] == 0
c.end_turn()
c.fight("NIBBITS_WEAK", ["DEFEND_IRONCLAD"] * 20)
assert st["happy_flower"] == 2  # round 2 -> 1, then the new fight's turn 1 -> 2


def hands(c, turns=2):
    out = []
    for _ in range(turns):
        out.append(len(c.hand))
        c.end_turn()
    return out


# BAG_OF_PREPARATION: 2 extra cards on turn 1 only.
assert hands(rc("BAG_OF_PREPARATION")) == [7, 5]
# POCKETWATCH: +3 cards if at most 3 were played last turn (turn 2 on).
c = rc("POCKETWATCH")
c.energy = 10
for _ in range(3):
    c.play_card(0)
c.end_turn()
assert len(c.hand) == 8
c = rc("POCKETWATCH")
c.energy = 10
for _ in range(4):
    c.play_card(0)
c.end_turn()
assert len(c.hand) == 5 and len(rc("POCKETWATCH").hand) == 5
# PENDULUM: draws 1 every 3rd turn, counted across fights.
assert hands(rc("PENDULUM"), 3) == [5, 5, 6]
assert len(rc("PENDULUM", state={"pendulum": 2}).hand) == 6
# FESTIVE_POPPER / MERCURY_HOURGLASS: damage to all enemies as turns start.
base = rc(enc="SLIMES_WEAK")
c = rc("FESTIVE_POPPER", enc="SLIMES_WEAK")
assert [b.hp - e.hp for b, e in zip(base.enemies, c.enemies)] == [min(b.hp, max(0, 9 - b.block)) for b in base.enemies]
hp1 = [e.hp for e in c.enemies]
c.end_turn()
assert [e.hp for e in c.enemies] == hp1
c, base = rc("MERCURY_HOURGLASS"), rc()
assert base.enemies[0].hp - c.enemies[0].hp == 3
c.end_turn()
assert base.enemies[0].hp - c.enemies[0].hp == 6
# BLOOD_VIAL: heal 2 at turn 1 only.
c = rc("BLOOD_VIAL", hp=50)
assert c.player_hp == 52
c.round, c.player_hp = 2, 50
c._start_player_turn()
assert c.player_hp == 50
# VEXING_PUZZLEBOX: a free generated card on turn 1 (6 cards in hand).
c = rc("VEXING_PUZZLEBOX")
assert len(c.hand) == 6 and c.cost(c.hand[-1]) == 0
c.end_turn()
assert len(c.hand) == 5
# BRIMSTONE: +2 Strength to the player, +1 to each enemy, every turn.
c = rc("BRIMSTONE")
assert (c.strength, c.enemies[0].strength) == (2, 1)
c.end_turn()
assert (c.strength, c.enemies[0].strength) == (4, 2)
# Played-card counters (Art of War / Pocketwatch's inputs).
c = rc()
c.hand, c.energy = ["STRIKE_IRONCLAD", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "INFLAME"], 10
for _ in range(4):
    c.play_card(0, 1)
assert (c.attacks_done, c.skills_done, c.powers_done, c.cards_played) == (2, 1, 1, 4)
c.end_turn()
assert (c.attacks_last, c.cards_last, c.attacks_done, c.skills_done, c.powers_done) == (2, 4, 0, 0, 0)
# Pocketwatch counts a card autoplayed after the turn ends (Dark Embrace draws a Strike Hellraiser plays).
c = rc("POCKETWATCH")
c.pw.update(HellraiserPower=1, DarkEmbracePower=1)
c.hand, c.energy = ["DEFEND_IRONCLAD"] * 3 + ["DAZED"], 10
c.draw_pile.append("STRIKE_IRONCLAD")
for _ in range(3):
    c.play_card(0)
c.end_turn()
assert c.cards_last == 4 and len(c.hand) == 5
# Juggernaut can win the fight off a turn-start block relic: no more turn setup.
c = rc("HORN_CLEAT", "PENDULUM", state={"pendulum": 0})
c.pw["JuggernautPower"] = 999
c.pw["CrimsonMantlePower"], c.crimson_self = 1, 7
c.end_turn()
assert c.won and c.player_block == 14 and c.relic_state["pendulum"] == 1  # no Crimson Mantle block, no Pendulum tick
# SimClient.set_relics shares the caller's state dict and Potion Belt widens the potion slots.
s, st = SimClient(seed=0), {"happy_flower": 2}
s.set_relics({"HAPPY_FLOWER", "POTION_BELT"}, st)
s.set_potions(["FIRE_POTION"])
assert len(s._combat.potions) == MAX_POTION_SLOTS
s.exec("fight NIBBITS_WEAK")
assert st["happy_flower"] == 0
s.exec("newrun")
assert s._combat.relics == set()

# --- Task 2: card-play, damage-dealt and exhaust relics ---
S, D, B = "STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "BASH"


def hand(c, *cards, energy=10):
    c.hand, c.energy = list(cards), energy
    return c


def dealt(c, i=0):
    """Damage the enemy took from the next play_card(i)."""
    e = c.enemies[0]
    hp = e.hp + e.block
    c.play_card(i, 1)
    return hp - e.hp - e.block


# PEN_NIB: the 10th Attack hits x2, the state wraps and carries into the next fight; a Skill doesn't count.
st = {"pen_nib": 8}
c = hand(rc("PEN_NIB", state=st), D, S, S, S)
c.enemies[0].hp = c.enemies[0].max_hp = 500
c.play_card(0)
assert st["pen_nib"] == 8
assert dealt(c) == 6 and st["pen_nib"] == 9
assert dealt(c) == 12 and st["pen_nib"] == 0
assert dealt(c) == 6 and st["pen_nib"] == 1
c2 = rc("PEN_NIB", state=st)
assert st["pen_nib"] == 1
# STRIKE_DUMMY: +3 on Strikes only.
c = hand(rc("STRIKE_DUMMY"), S, B)
assert dealt(c) == 9 and dealt(c) == 8
# PAPER_PHROG: Vulnerable x1.75.
c = hand(rc("PAPER_PHROG"), S)
c.enemies[0].vulnerable = 2
assert dealt(c) == 10
# AKABEKO: Vigor 8 on turn 1 only; every hit of one Attack, then spent.
c = hand(rc("AKABEKO"), "TWIN_STRIKE", S, S)
assert c.pw["VigorPower"] == 8
e = c.enemies[0]
e.hp = e.max_hp = 500
assert dealt(c) == 26 and "VigorPower" not in c.pw and dealt(c) == 6
c.end_turn()
assert "VigorPower" not in c.pw
# CHEMICAL_X: X + 2.
c = hand(rc("CHEMICAL_X"), "WHIRLWIND", energy=3)
e = c.enemies[0]
e.hp = e.max_hp = 500
hp = e.hp + e.block
c.play_card(0)
assert c.energy == 0 and hp - e.hp - e.block == 25
# INTIMIDATING_HELMET: +4 block only when 2+ energy was spent.
c = hand(rc("INTIMIDATING_HELMET"), B, S)
c.play_card(0, 1)
assert c.player_block == 4
c.play_card(0, 1)
assert c.player_block == 4
# NUNCHAKU: every 10th Attack +1 energy; Skills don't count; carried.
st = {"nunchaku": 8}
c = hand(rc("NUNCHAKU", state=st), D, S, S, energy=3)
c.play_card(0)
assert st["nunchaku"] == 8
c.play_card(0, 1)
assert (c.energy, st["nunchaku"]) == (1, 9)
c.play_card(0, 1)
assert (c.energy, st["nunchaku"]) == (1, 0)  # 1 - 1 + 1
assert rc("NUNCHAKU", state=st).relic_state["nunchaku"] == 0
# TUNING_FORK: 10th Skill +7 block, -10; Attacks don't count.
st = {"tuning_fork": 9}
c = hand(rc("TUNING_FORK", state=st), S, D)
c.play_card(0, 1)
assert st["tuning_fork"] == 9
c.play_card(0)
assert c.player_block == 12 and st["tuning_fork"] == 0
# KUSARIGAMA: each 3rd Attack 6 to a random enemy; Skills don't count; resets next turn.
c = hand(rc("KUSARIGAMA"), S, S, D, S, S, S, S)
c.enemies[0].hp = c.enemies[0].max_hp = 500
assert [dealt(c) for _ in range(2)] == [6, 6]
c.play_card(0)
assert dealt(c) == 12 and dealt(c) == 6  # third Attack: 6 + 6, the fourth: 6
c.end_turn()
hand(c, S, S, S)
assert [dealt(c) for _ in range(3)] == [6, 6, 12]
# LETTER_OPENER: each 3rd Skill 5 to all; Attacks don't count.
c = hand(rc("LETTER_OPENER", enc="SLIMES_WEAK"), D, S, D, D)
for e in c.enemies:
    e.hp = e.max_hp = 500
    e.block = 0
c.play_card(0), c.play_card(0, 1), c.play_card(0)  # Skill, Attack, Skill: two Skills so far
assert [e.hp for e in c.enemies] == [494] + [500] * (len(c.enemies) - 1)
hp = [e.hp for e in c.enemies]
c.play_card(0)  # the third Skill
assert [h - e.hp for h, e in zip(hp, c.enemies)] == [5] * len(hp)
# ORNAMENTAL_FAN / KUNAI / SHURIKEN: each 3rd Attack.
c = hand(rc("ORNAMENTAL_FAN", "KUNAI", "SHURIKEN"), S, S, D, S)
c.enemies[0].hp = c.enemies[0].max_hp = 500
c.play_card(0, 1), c.play_card(0, 1), c.play_card(0)
assert (c.player_block, c.dexterity, c.strength) == (5, 0, 0)  # Defend 5, nothing yet
c.play_card(0, 1)
assert (c.player_block, c.dexterity, c.strength) == (9, 1, 1)
c.end_turn()
hand(c, S, S, S)
for _ in range(2):
    c.play_card(0, 1)
assert (c.dexterity, c.strength) == (1, 1)  # the count reset
c.play_card(0, 1)
assert (c.dexterity, c.strength) == (2, 2)
# RAINBOW_RING: once a turn, when Attack, Skill and Power have all been played.
c = hand(rc("RAINBOW_RING"), S, D, "INFLAME", S, D, "INFLAME")
c.enemies[0].hp = c.enemies[0].max_hp = 500
c.play_card(0, 1), c.play_card(0)
assert (c.strength, c.dexterity) == (0, 0)
c.play_card(0)
assert (c.strength, c.dexterity) == (3, 1)  # Inflame's 2 + the ring's 1
c.play_card(0, 1), c.play_card(0), c.play_card(0)
assert (c.strength, c.dexterity) == (5, 1)  # not again this turn
c.end_turn()
hand(c, S, D, "INFLAME")
for _ in range(3):
    c.play_card(0, 1) if c.hand[0] == S else c.play_card(0)
assert (c.strength, c.dexterity) == (8, 2)
# PERMAFROST: the first Power each fight.
c = hand(rc("PERMAFROST"), "INFLAME", "INFLAME")
c.play_card(0)
assert c.player_block == 7
c.play_card(0)
assert c.player_block == 7
c = hand(rc("PERMAFROST"), "INFLAME")
c.play_card(0)
assert c.player_block == 7
# GAME_PIECE: a Power draws 1; a Skill doesn't.
c = hand(rc("GAME_PIECE"), D, "INFLAME")
c.play_card(0)
assert len(c.hand) == 1
c.play_card(0)
assert len(c.hand) == 1
# MUMMIFIED_HAND: a Power makes a costed hand card free; falls back to a free one.
c = hand(rc("MUMMIFIED_HAND"), "INFLAME", B)
c.play_card(0)
assert c.cost(B) == 0
c = hand(rc("MUMMIFIED_HAND"), "INFLAME", D)
c.play_card(0)
assert c.cost(D) == 0
# VAMBRACE: the first card to gain block doubles all of it, after Frail; the second doesn't.
c = hand(rc("VAMBRACE"), S, D, D)
c.play_card(0, 1)
c.play_card(0)
assert c.player_block == 10
c.play_card(0)
assert c.player_block == 15
c = hand(rc("VAMBRACE"), D)
c.frail = 1
c.play_card(0)
assert c.player_block == 7  # 5 * 3/4 * 2 = 7.5
c = hand(rc("VAMBRACE"), "EVIL_EYE", D)  # two block gains from one card both double
c.exhausted_this_turn = True
c.play_card(0)
assert c.player_block == 32
# UNSETTLING_LAMP: the first card applying a debuff doubles it; a potion doesn't trigger it.
c = hand(rc("UNSETTLING_LAMP"), B, B, B)
c.potions = ["WEAK_POTION", None, None]
c.use_potion(0, 1)
assert c.enemies[0].weak == 3
c.enemies[0].hp = c.enemies[0].max_hp = 500
c.play_card(0, 1)
assert c.enemies[0].vulnerable == 4
c.play_card(0, 1)
assert c.enemies[0].vulnerable == 6
# UNCEASING_TOP: an emptied hand after a play draws 1; not at end of turn.
c = hand(rc("UNCEASING_TOP"), D, D)
c.play_card(0)
assert len(c.hand) == 1
c.play_card(0)
assert len(c.hand) == 1
c.end_turn()
assert len(c.hand) == 5
# RUINED_HELMET: the first positive Strength gain each fight doubles; Vajra 1 -> 2, later gains don't.
c = rc("RUINED_HELMET", "VAJRA")
assert c.strength == 2
c._gain_strength(3)
assert c.strength == 5
c._gain_strength(0)
assert c.strength == 5
c = rc("RUINED_HELMET")
c._gain_strength(0)
c._gain_strength(-2)
assert c.strength == -2
c._gain_strength(1)
assert c.strength == 0  # -2 + 2
assert rc("RUINED_HELMET").rt == {} and rc("RUINED_HELMET")._gain_strength(1) is None
# ...and temporary Strength: the doubled gain stays, only the temp amount is taken back (TemporaryStrengthPower).
c = rc("RUINED_HELMET")
c.potions = ["FLEX_POTION", None, None]
c.use_potion(0)
assert c.strength == 10
c.end_turn()
assert c.strength == 5
# GREMLIN_HORN: any enemy dying gives +1 energy and a card.
c = hand(rc("GREMLIN_HORN"), S, D, D, energy=3)
c.enemies[0].hp = 1
c.play_card(0, 1)
assert c.won
c = rc("GREMLIN_HORN", enc="SLIMES_WEAK")
c.hand, c.energy = [S, D, D], 3
c.enemies[0].hp, c.enemies[0].block = 1, 0
c.play_card(0, 1)
assert c.energy == 3 and len(c.hand) == 3 and not c.won
c.energy = 3
c.enemies[1].hp = 100
c.play_card(0)
assert c.energy == 2
# THE_ABACUS: a reshuffle gives 6 block.
c = rc("THE_ABACUS")
c.draw_pile, c.discard_pile = [], [D, D]
c._draw(1)
assert c.player_block == 6
c._draw(1)
assert c.player_block == 6
# CHARONS_ASHES: every exhaust (Ethereal too) hits every enemy for 3.
c = hand(rc("CHARONS_ASHES", enc="SLIMES_WEAK"), "TRUE_GRIT", D, energy=3)
hp = [e.hp + e.block for e in c.enemies]
c._exhaust(D)
assert [h - e.hp - e.block for h, e in zip(hp, c.enemies)] == [3] * len(hp)
c = rc("CHARONS_ASHES")
c.hand = ["DAZED"]
hp = c.enemies[0].hp + c.enemies[0].block
c.end_turn()
assert hp - c.enemies[0].hp - c.enemies[0].block == 3
# JOSS_PAPER: the 5th exhaust draws; Ethereal ones count at turn end; carried.
st = {"joss_paper": 4}
c = hand(rc("JOSS_PAPER", state=st), D)
c.draw_pile = [S] * 5
c._exhaust(D)
assert len(c.hand) == 2 and st["joss_paper"] == 0
c._exhaust(D)
assert len(c.hand) == 2 and st["joss_paper"] == 1
assert rc("JOSS_PAPER", state=st).relic_state["joss_paper"] == 1
st = {"joss_paper": 4}
c = rc("JOSS_PAPER", state=st)
c.hand = ["DAZED"]
c.end_turn()
assert st["joss_paper"] == 0 and len(c.hand) == 5 + 1  # the Ethereal Dazed counted, drew 1, then 5
# BURNING_STICKS: the first exhausted Skill each fight leaves a copy in hand; Attacks don't.
c = hand(rc("BURNING_STICKS"), D)
c._exhaust(S)
assert c.hand == [D]
c._exhaust(D)
assert c.hand == [D, D]
c._exhaust(D)
assert c.hand == [D, D]
c = rc("BURNING_STICKS")
c.hand = []
c._exhaust(D)
assert c.hand == [D]
# REPTILE_TRINKET: a potion gives 3 Strength until the end of the turn.
c = rc("REPTILE_TRINKET")
c.potions = ["BLOCK_POTION", None, None]
c.use_potion(0)
assert c.strength == 3
c.end_turn()
assert c.strength == 0

# --- Task 2 fix round 1 ---
def big(c, hp=500):
    for e in c.enemies:
        e.hp = e.max_hp = hp
        e.block = 0
    return c


# UNCEASING_TOP: any play or potion (autoplay too) outside a card effect with an empty hand draws 1.
c = rc("UNCEASING_TOP")
c.hand, c.potions = [], ["BLOCK_POTION", None, None]
c.use_potion(0)  # the hand was already empty and stays empty: the source still checks
assert len(c.hand) == 1
c = rc()
c.hand, c.potions = [], ["BLOCK_POTION", None, None]
c.use_potion(0)
assert c.hand == []
c = big(rc("UNCEASING_TOP"))  # Hellraiser: the drawn Strike autoplays, the hand is empty again, so it draws again
c.pw["HellraiserPower"] = 1
c.hand, c.draw_pile = [D], [D, S]
c.play_card(0)
assert c.hand == [D] and c.draw_pile == []
c = big(rc("UNCEASING_TOP"))  # Havoc's nested autoplay doesn't check; Havoc's own end does
c.hand, c.draw_pile, c.energy = ["HAVOC"], [D, D, S], 3
c.play_card(0)
assert c.hand == [D] and c.exhaust_pile == [S] and c.draw_pile == [D]
base = rc("UNCEASING_TOP")  # Stampede plays the last Attack in AutoPostPlay: draws 1 (then 5 next turn)
base.pw["StampedePower"], base.hand = 1, [S]
n = len(base.draw_pile)
base.end_turn()
assert len(base.draw_pile) == n - 6
c = rc()
c.pw["StampedePower"], c.hand = 1, [S]
c.end_turn()
assert len(c.draw_pile) == n - 5
# INTIMIDATING_HELMET: every play of a repeated card, and autoplays by their cost.
c = hand(rc("INTIMIDATING_HELMET"), B)
c.pw["OneTwoPunchPower"] = 1
c.play_card(0, 1)
assert c.player_block == 8
c = big(rc("INTIMIDATING_HELMET"))
c.hand, c.draw_pile, c.energy = ["HAVOC"], [B], 3
c.play_card(0)
assert c.player_block == 4 and c.exhaust_pile == [B]
# BURNING_STICKS: Fiend Fire / Stoke exhaust a snapshot of the hand, not the copy.
c = big(rc("BURNING_STICKS", "JOSS_PAPER", "CHARONS_ASHES"))
c.hand, c.energy = ["FIEND_FIRE", D, D], 3
hp = c.enemies[0].hp
c.play_card(0, 1)
assert c.hand == [D] and c.exhaust_pile.count(D) == 2
assert c.relic_state["joss_paper"] == 3 and hp - c.enemies[0].hp == 14 + 3 * 3  # 2 hits of 7, 3 Charon hits
c = rc("BURNING_STICKS")
c.hand, c.energy = ["STOKE", D, D], 3
c.play_card(0)
assert c.exhaust_pile.count(D) == 2 and len(c.hand) == 3 and D in c.hand  # 2 generated + the Sticks copy
# CHARONS_ASHES: a lethal exhaust only makes the fight "ending"; the rest of the card and the counters still run.
st = {"joss_paper": 4}
c = hand(rc("CHARONS_ASHES", "JOSS_PAPER", state=st), D)
c.enemies[0].hp = 3
c._exhaust(D)
assert c.in_combat and st["joss_paper"] == 0 and len(c.hand) == 1  # wrapped, no draw
c._check_win()
assert c.won
st = {"tuning_fork": 3}
c = hand(rc("CHARONS_ASHES", "TUNING_FORK", state=st), "TRUE_GRIT", D, energy=3)
c.enemies[0].hp = 3
c.play_card(0)
assert c.won and st["tuning_fork"] == 4
st = {"joss_paper": 0}
c = hand(rc("CHARONS_ASHES", "JOSS_PAPER", state=st), "SECOND_WIND", D, D, D, energy=3)
c.enemies[0].hp = 3
c.play_card(0)
assert c.won and st["joss_paper"] == 1  # the later exhausts no-op
# THRASH eats a Strike: Strike Dummy counts for the eaten card, Pen Nib doubles it when Thrash is the 9th Attack.
c = big(rc("STRIKE_DUMMY"))
c.hand, c.energy = ["THRASH", S], 3
c.play_card(0, 1)
assert c.bonus_damage["THRASH"] == 9
c = big(rc("PEN_NIB", state={"pen_nib": 8}))
c.hand, c.energy = ["THRASH", S], 3
c.play_card(0, 1)
assert c.bonus_damage["THRASH"] == 12
c = big(rc("PEN_NIB", state={"pen_nib": 7}))
c.hand, c.energy = ["THRASH", S], 3
c.play_card(0, 1)
assert c.bonus_damage["THRASH"] == 6
# Nested autoplays keep the outer card: Pen Nib on Fiend Fire, Vambrace on Second Wind.
c = big(rc("PEN_NIB", state={"pen_nib": 9}))
c.pw.update(DarkEmbracePower=1, HellraiserPower=1)
c.hand, c.draw_pile, c.energy = ["FIEND_FIRE", D], [D, S], 3
hp = c.enemies[0].hp
c.play_card(0, 1)
assert hp - c.enemies[0].hp == 14 + 6  # Fiend Fire doubled, the Strike it drew not
c = big(rc("VAMBRACE"))
c.pw.update(DarkEmbracePower=1, HellraiserPower=1)
c.hand, c.draw_pile, c.energy = ["SECOND_WIND", D, D], [S, S], 3
c.play_card(0)
assert c.player_block == 20

print("sim self-check ok")
