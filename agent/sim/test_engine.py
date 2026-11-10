"""Self-check for the sim's ported rules: python -m sim.test_engine (from agent/)."""
import random
from dataclasses import replace

from .cards import DeckCard
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

from . import engine  # noqa: E402
from .cards import CHOICE_CARDS, COMMONS, RARES, UNCOMMONS, starter_deck, upgrade  # noqa: E402
from .potions import POTION_IDS  # noqa: E402


def _no_relic_trace() -> str:
    """Every fight state on seeded random play. Any change here means relic code leaked into relic-less fights.
    The hash predates the choice cards, so they (and Armaments, which Stoke / Infernal Blade can now make) are held out of the decks and of the generated pool: it still
    pins that every other card plays the same, RNG included."""
    h = hashlib.sha256()
    pool = [c for c in COMMONS + UNCOMMONS + RARES if c not in CHOICE_CARDS]
    generated, engine.GENERATED = engine.GENERATED, tuple(c for c in engine.GENERATED if c not in CHOICE_CARDS + ("ARMAMENTS",))
    for seed in range(66):
        rng = random.Random(seed)
        c = SimCombat(rng=random.Random(seed))
        c.potions = [rng.choice(POTION_IDS), None, rng.choice(POTION_IDS)]
        c.fight(ENCOUNTERS[seed % len(ENCOUNTERS)], starter_deck() + rng.choices(pool, k=6))
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
    engine.GENERATED = generated
    return h.hexdigest()


# History: with engine.upgrade a no-op, the old hash b3732604... still held after Aggression began upgrading its Attack.
# The hash then changed to this one. Known: Aggression's pick out of its own slot, and _take's `del pile[i]` index pick,
# can both reorder piles (an index pick leaves a different order than remove-first-equal); which of them moved it is not isolated.
assert _no_relic_trace() == "5679464b2188aadb9271b46cc22ca43759b52a7b9017b3e86b02a85bae9647bb"
# --- relics (sim/relics.py) ---------------------------------------------------------------------
from .relics import NOT_MODELED, RELIC_POOL, RELICS, relic_rarity  # noqa: E402
from .potions import MAX_POTION_SLOTS  # noqa: E402

assert [len(v) for v in RELIC_POOL.values()] == [26, 32, 38, 26]
assert len({r for v in RELIC_POOL.values() for r in v}) == 122 and len(RELICS) == 108 and len(NOT_MODELED) == 14
assert [len([r for r in v if r in RELICS]) for v in RELIC_POOL.values()] == [26, 30, 36, 16]
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
# GIRYA: Strength = times lifted, at every combat start (AfterRoomEntered).
assert rc("GIRYA", state={"girya": 2}).strength == 2 and rc("GIRYA").strength == 0
# BELLOWS: the turn-1 hand is upgraded; later turns are not. STONE_CRACKER: 2 upgradable draw-pile cards at combat start.
c = rc("BELLOWS", deck=["STRIKE_IRONCLAD"] * 20)
assert c.hand == ["STRIKE_IRONCLAD+"] * 5 and set(c.draw_pile) == {"STRIKE_IRONCLAD"}, (c.hand, c.draw_pile)
c.end_turn(); assert "STRIKE_IRONCLAD+" not in c.hand
c = rc("STONE_CRACKER", deck=["STRIKE_IRONCLAD"] * 10 + ["WOUND"] * 10)
assert sum(x == "STRIKE_IRONCLAD+" for x in c.hand + c.draw_pile) == 2 and "WOUND+" not in c.hand + c.draw_pile
# A discard prompt answered by base id takes the upgraded copy when no plain one is left (Bellows puts them there).
c = solo(["HEADBUTT"]); c.discard_pile = ["STRIKE_IRONCLAD+", "DEFEND_IRONCLAD"]; c.play_card(0, 1)
assert c.pending_choice["kind"] == "discard" and c.choose_discard("STRIKE_IRONCLAD").get("ok") and c.draw_pile[-1] == "STRIKE_IRONCLAD+"
# MINIATURE_CANNON: +3 damage on an upgraded Attack only.
for card, dmg in (("STRIKE_IRONCLAD", 6), ("STRIKE_IRONCLAD+", 9 + 3)):
    c = rc("MINIATURE_CANNON", deck=[card] * 20); e = c.enemies[0]; hp = e.hp + e.block
    c.play_card(0, 1); assert hp - (e.hp + e.block) == dmg, (card, hp - (e.hp + e.block))
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

# A lethal Charon exhaust at an autoplayed card's result pile: later autoplays of untargeted cards no-op.
for setup in ("stampede", "cascade"):
    st = {"nunchaku": 0, "pen_nib": 0}
    c = rc("CHARONS_ASHES", "NUNCHAKU", "PEN_NIB", state=st)
    c.enemies[0].hp, c.enemies[0].block = 3, 10  # Molten Fist's 10 is absorbed, Charon's 3 kills
    if setup == "stampede":  # then Howl from Beyond (AllEnemies) from the exhaust pile
        c.pw["StampedePower"], c.hand, c.exhaust_pile = 1, ["MOLTEN_FIST"], ["HOWL_FROM_BEYOND"]
        c.end_turn()
    else:
        c.hand, c.draw_pile, c.energy = ["CASCADE"], ["HOWL_FROM_BEYOND", "MOLTEN_FIST"], 2
        c.play_card(0)
    assert c.won and st == {"nunchaku": 1, "pen_nib": 1}, (setup, st)

# --- Task 3: damage-taken, HP and end-of-turn relics ---
def hurt(c, dmg, hits=1, dealer=True):
    """An enemy-side hit (powered when dealer is set), then back to the player's side."""
    side, c.side = c.side, "Enemy"
    for _ in range(hits):
        c._damage_player(dmg, dealer=c.enemies[0] if dealer else None)
    c.side = side


def eot(c):
    """End the turn without running the enemy's, so end-of-turn block and damage can be read."""
    c._run_enemy_turn = lambda: None
    c.end_turn()
    return c


def win(c):
    c.enemies[0].hp = 0
    c._check_win()
    return c


# BRONZE_SCALES: Thorns 3 per powered monster hit (2-hit Claw = 6 back); Constrict, Infection, self-damage deal none.
c = big(rc("BRONZE_SCALES", enc="MAWLER_NORMAL"))
assert c.pw["ThornsPower"] == 3 and c.enemies[0].move == "CLAW_MOVE"
c.end_turn()
assert c.enemies[0].max_hp - c.enemies[0].hp == 6 and c.player_hp == 72
c = big(rc("BRONZE_SCALES"))
c.constrict, c.hand = 3, ["INFECTION"]
eot(c)
c._lose_hp(2, from_card=True)
hurt(c, 3, dealer=False)
assert c.enemies[0].hp == c.enemies[0].max_hp and c.player_hp == 80 - 3 - 3 - 2 - 3
c.fight("NIBBITS_WEAK")  # the power is rebuilt, not stacked
assert c.pw["ThornsPower"] == 3
c = rc("BRONZE_SCALES")  # a Thorns kill doesn't stop the hit; the fight ends after it
c.enemies[0].hp = 3
hurt(c, 5)
assert c.player_hp == 75 and c.won and not c.in_combat
assert "ThornsPower" not in rc().pw

# CENTENNIAL_PUZZLE: first unblocked HP loss each fight draws 3; a fully blocked hit and the second loss don't.
c = rc("CENTENNIAL_PUZZLE")
c.player_block = 5
hurt(c, 5)
assert len(c.hand) == 5
c._lose_hp(1, from_card=True)
assert len(c.hand) == 8
hurt(c, 1)
assert len(c.hand) == 8
c.fight("NIBBITS_WEAK", ["DEFEND_IRONCLAD"] * 20)  # next fight, same relic
c._lose_hp(1)
assert len(c.hand) == 8

# SELF_FORMING_CLAY: +3 per HP loss (any source); the next block clear grants it once.
c = rc("SELF_FORMING_CLAY")
c.player_block = 5
hurt(c, 5)
assert "SelfFormingClayPower" not in c.pw
c._lose_hp(1, from_card=True)
hurt(c, 1)
assert c.pw["SelfFormingClayPower"] == 6
c.player_block = 100
c.end_turn()
assert c.player_block == 6 and "SelfFormingClayPower" not in c.pw
c.player_block = 100
c.end_turn()
assert c.player_block == 0

# DEMON_TONGUE: the first HP loss each player-side turn is healed back; an enemy-side hit never is.
c = rc("DEMON_TONGUE", hp=50)
hand(c, "BLOODLETTING", "BLOODLETTING")
c.play_card(0)
assert c.player_hp == 50
c.play_card(0)
assert c.player_hp == 47
c.player_block = 100
c.end_turn()
assert c.player_hp == 47
hurt(c, 4)
assert c.player_hp == 43  # enemy side: not healed, and it doesn't use up the turn's heal
c._lose_hp(3, from_card=True)
assert c.player_hp == 43  # new turn, first loss: net 0

# TUNGSTEN_ROD: -1 per HP loss (floor 0); a 1-damage loss triggers nothing at all.
c = rc("TUNGSTEN_ROD", "CENTENNIAL_PUZZLE", "SELF_FORMING_CLAY", "DEMON_TONGUE")
n = c.hp_loss_events
c.player_hp = 50
c._lose_hp(1, from_card=True)
hurt(c, 1, hits=8)
assert c.player_hp == 50 and len(c.hand) == 5 and c.hp_loss_events == n and not c.hp_lost_this_turn
assert not c.pw.get("SelfFormingClayPower")
hurt(c, 6)
assert c.player_hp == 45 and c.hp_loss_events == n + 1 and len(c.hand) == 8

# BEATING_REMNANT: at most 20 HP lost per turn cycle (enemy hits count), resets at the next player turn.
c = rc("BEATING_REMNANT")
c._lose_hp(26, from_card=True)
assert c.player_hp == 60
c._lose_hp(5)
assert c.player_hp == 60
c.player_block = 100
c.end_turn()
c._lose_hp(15)
hurt(c, 15)
assert c.player_hp == 60 - 20
c = rc("BEATING_REMNANT", "TUNGSTEN_ROD")  # Tungsten first: 26 -> 25 -> capped to 20
c._lose_hp(26)
assert c.player_hp == 60 and c.rt["remnant"] == 20

# LIZARD_TAIL: a lethal hit once per run leaves max_hp // 2; AfterDamageReceived relics don't see it.
st = {}
c = rc("LIZARD_TAIL", "CENTENNIAL_PUZZLE", "SELF_FORMING_CLAY", "DEMON_TONGUE", state=st, hp=1)
hurt(c, 5)
assert c.player_hp == 40 and c.in_combat and st["lizard_used"] == 1
assert len(c.hand) == 5 and not c.pw.get("SelfFormingClayPower")
c.player_hp = 1
hurt(c, 5)
assert c.player_hp == 0 and not c.in_combat and c.won is False
c = rc("LIZARD_TAIL", state=st, hp=1)  # the flag carries into the next fight
c._lose_hp(3, from_card=True)
assert not c.in_combat
c = rc("LIZARD_TAIL", state={}, hp=3)  # card self-damage too; 81 max -> 40
c.player_max_hp = 81
c._lose_hp(3, from_card=True)
assert c.player_hp == 40 and c.in_combat
c = rc("LIZARD_TAIL", hp=5)  # only when lethal
hurt(c, 3)
assert c.player_hp == 2 and "lizard_used" not in c.relic_state

# RED_SKULL: +3 Strength while 2 * hp <= max_hp; no stacking, follows heal and loss, rebuilt each fight.
assert rc("RED_SKULL", hp=40).strength == 3 and rc("RED_SKULL", hp=41).strength == 0
c = rc("RED_SKULL", hp=41)
c.heal(1)
assert c.strength == 0
c._lose_hp(2)
assert c.player_hp == 40 and c.strength == 3
c._lose_hp(5)
c.heal(1)
assert c.player_hp == 36 and c.strength == 3
c.heal(5)
assert c.player_hp == 41 and c.strength == 0
c._lose_hp(1)
assert c.strength == 3
c.fight("NIBBITS_WEAK")  # same hp, new fight: 3, not 6
assert c.strength == 3
c = rc("RED_SKULL", "LIZARD_TAIL", hp=1)
c._lose_hp(1)
assert c.strength == 3 and c.player_hp == 40
c = rc("RED_SKULL", "RUINED_HELMET", hp=40)  # the first positive Strength gain is doubled (PowerCmd.Apply)
assert c.strength == 6
c.heal(5)
assert c.strength == 3

# MEAT_ON_THE_BONE: a win at hp <= max_hp // 2 heals 12; not above it, not on a loss.
assert win(rc("MEAT_ON_THE_BONE", hp=40)).player_hp == 52
assert win(rc("MEAT_ON_THE_BONE", hp=41)).player_hp == 41
c = rc("MEAT_ON_THE_BONE", hp=40)
c.player_max_hp = 81
assert win(c).player_hp == 52
assert win(rc("MEAT_ON_THE_BONE", hp=36)).player_hp == 48
c = rc("MEAT_ON_THE_BONE", hp=40)
c._end_combat(won=False)
assert c.player_hp == 40
assert win(rc(hp=40)).player_hp == 40

# End of turn: Orichalcum reads block before Plating (Gorget); 6 only at 0 block.
assert eot(rc("ORICHALCUM", "GORGET")).player_block == 10
c = rc("ORICHALCUM", "GORGET")
c.player_block = 1
assert eot(c).player_block == 1 + 4
# CLOAK_CLASP: 1 block per card in hand.
assert eot(rc("CLOAK_CLASP")).player_block == 5
c = rc("CLOAK_CLASP")
c.hand = []
assert eot(c).player_block == 0
# RIPPLE_BASIN: 4 block if no Attack was played this turn, per turn.
assert eot(rc("RIPPLE_BASIN")).player_block == 4
c = hand(rc("RIPPLE_BASIN"), S, D)
c.play_card(0, 1)
assert eot(c).player_block == 0
c = hand(rc("RIPPLE_BASIN"), D, S)
c.play_card(1, 1)
c.end_turn()
assert c.round == 2 and eot(c).player_block == 4  # turn 2 had no Attack: the counter reset
# SCREAMING_FLAGON: 20 to all enemies at end of turn with an empty hand only.
c = big(rc("SCREAMING_FLAGON", enc="RUBY_RAIDERS_NORMAL"))
assert len(c.enemies) > 1
c.hand = []
eot(c)
assert all(e.hp == 480 for e in c.enemies)
assert eot(big(rc("SCREAMING_FLAGON"))).enemies[0].hp == 500
c = rc("SCREAMING_FLAGON")  # lethal: the enemy turn doesn't run
c.hand = []
c.enemies[0].hp = 20
c.end_turn()
assert c.won and c.player_hp == 80 and c.round == 1
# STONE_CALENDAR: 52 to all enemies at the end of turn 7 only.
for r, d in ((6, 0), (7, 52), (8, 0)):
    c = big(rc("STONE_CALENDAR"))
    c.round = r
    assert eot(c).enemies[0].hp == 500 - d, r
c = rc("STONE_CALENDAR", "SCREAMING_FLAGON", "CLOAK_CLASP", "PARRYING_SHIELD")
c.round, c.hand = 7, []
c.enemies[0].hp = 52
c.end_turn()
assert c.won and c.round == 7 and c.player_hp == 80
# PARRYING_SHIELD: block >= 10 after the side's turn: 6 to a random enemy.
for b, d in ((10, 6), (9, 0)):
    c = big(rc("PARRYING_SHIELD"))
    c.player_block = b
    assert eot(c).enemies[0].hp == 500 - d, b
c = big(rc("PARRYING_SHIELD"))  # ponytail order: Constrict (a power) hits first and drops 10 below the line
c.player_block, c.constrict = 10, 3
assert eot(c).enemies[0].hp == 500
st = {}
c = rc("PARRYING_SHIELD", "JOSS_PAPER", state=st)  # lethal: Joss's Ethereal count is already banked
c.hand, c.player_block = ["DAZED", D], 10
c.enemies[0].hp = 6
c.end_turn()
assert c.won and c.player_hp == 80 and st["joss_paper"] == 1
# RINGING_TRIANGLE: turn 1's hand is held (draw tops it up to 10), later turns flush.
c = rc("RINGING_TRIANGLE")
old = list(c.hand) + [B, B]
c.hand = list(old)
c.end_turn()
assert c.round == 2 and c.hand[:7] == old and len(c.hand) == 10
c.end_turn()
assert len(c.hand) == 5
c = rc()
c.end_turn()
assert len(c.hand) == 5 and c.round == 2
# GHOST_SEED: basic Strike / Defend are Ethereal; Bash and other Strike-tagged cards aren't.
c = hand(rc("GHOST_SEED"), S, D, B, "POMMEL_STRIKE")
eot(c)
assert c.exhaust_pile == [S, D] and c.discard_pile == [B, "POMMEL_STRIKE"]
c = hand(rc(), S, D)
eot(c)
assert c.exhaust_pile == [] and c._is_ethereal("DAZED") and not c._is_ethereal(S)
c = rc("GHOST_SEED")
assert c._is_ethereal(S) and c._is_ethereal(D) and not c._is_ethereal(B)

# Fix round 1: a card drawn by Centennial mid-loop isn't a turn-end card; Demon Tongue heals past Inferno's kill.
c = rc("CENTENNIAL_PUZZLE")
c.hand, c.draw_pile = ["INFECTION"], ["DEFEND_IRONCLAD", "DEFEND_IRONCLAD", "INFECTION"]
eot(c)
assert c.player_hp == 77
for relics, hp, end in ((("DEMON_TONGUE",), 50, 50), (("DEMON_TONGUE", "MEAT_ON_THE_BONE"), 42, 42)):
    c = rc(*relics, hp=hp)
    c.pw["InfernoPower"], c.inferno_self = 5, 3
    c.enemies[0].hp, c.enemies[0].block = 5, 0
    hand(c, "BLOODLETTING")
    c.play_card(0)
    assert c.won and c.player_hp == end, (relics, c.player_hp)

# Headbutt: 9 damage, then a discard card goes on top of the draw pile.
c = solo(["HEADBUTT", "STRIKE_IRONCLAD"])
c.discard_pile = [DeckCard("BASH"), DeckCard("DEFEND_IRONCLAD")]
hp = c.enemies[0].hp
assert c.play_card(0, 1)["ok"]
assert c.pending_choice == {"kind": "discard", "source": "HEADBUTT"} and c.enemies[0].hp == hp - 9 and c.energy == 2
assert c.combat_dict()["choice"] == c.pending_choice
assert c.play_card(0, 1)["error"] == "choice_pending" and c.end_turn()["error"] == "choice_pending"
assert c.choose_discard("BASH")["ok"]
assert c.draw_pile[-1] == "BASH" and c.pending_choice is None and c.discard_pile == ["DEFEND_IRONCLAD", "HEADBUTT"]
assert isinstance(c.draw_pile[-1], DeckCard)  # the pick keeps its deck identity, so Hopper can still steal it
assert c.choice_log == [("HEADBUTT", "BASH", ("BASH", "DEFEND_IRONCLAD"))]

# Burning Pact: exhaust from hand, then draw 2.
c = solo(["BURNING_PACT", "WOUND", "STRIKE_IRONCLAD"])
c.play_card(0)
assert c.pending_choice["kind"] == "hand" and c.hand == ["WOUND", "STRIKE_IRONCLAD"]
assert c.choose_card(0)["ok"]
assert c.exhaust_pile == ["WOUND"] and len(c.hand) == 3 and c.discard_pile == ["BURNING_PACT"]

# Brand: lose 1 HP first, exhaust, then 1 Strength. Costs 0.
c = solo(["BRAND", "WOUND", "BASH"])
hp, s = c.player_hp, c.strength
c.play_card(0)
assert c.player_hp == hp - 1 and c.energy == 3 and c.strength == s
c.choose_card(1)
assert c.exhaust_pile == ["BASH"] and c.strength == s + 1

# CardSelectCmd: one legal card is taken with no prompt; none means the rest still resolves.
c = solo(["BURNING_PACT", "WOUND"]); c.play_card(0)
assert c.pending_choice is None and c.exhaust_pile == ["WOUND"] and len(c.hand) == 2 and not c.choice_log
c = solo(["BRAND"]); s = c.strength; c.play_card(0)
assert c.pending_choice is None and c.strength == s + 1 and not c.exhaust_pile
c = solo(["HEADBUTT"]); c.play_card(0, 1)
assert c.pending_choice is None and c.discard_pile == ["HEADBUTT"]

# Review focus 1: One-Two Punch plays Headbutt twice, so two prompts.
c = solo(["HEADBUTT"]); c.discard_pile = ["BASH", "DEFEND_IRONCLAD", "STRIKE_IRONCLAD"]
c.pw["OneTwoPunchPower"] = 1
c.play_card(0, 1); c.choose_discard("BASH")
assert c.pending_choice == {"kind": "discard", "source": "HEADBUTT"}
c.choose_discard("DEFEND_IRONCLAD")
assert c.pending_choice is None and c.draw_pile[-2:] == ["BASH", "DEFEND_IRONCLAD"] and c.discard_pile == ["STRIKE_IRONCLAD", "HEADBUTT"]

# Review focus 2: killing the last enemy ends the fight with no prompt.
c = solo(["HEADBUTT"]); c.discard_pile = ["BASH", "DEFEND_IRONCLAD"]; c.enemies[0].hp = 1
c.play_card(0, 1)
assert not c.in_combat and c.pending_choice is None

# Review focus 3: Brand at 1 HP is lethal before the prompt.
c = solo(["BRAND", "WOUND", "BASH"]); c.player_hp = 1
c.play_card(0)
assert not c.in_combat and c.pending_choice is None

# Review focus 4: an autoplay can't pause. Havoc plays Headbutt and it picks at random.
c = solo(["HAVOC"]); c.draw_pile = ["HEADBUTT"]; c.discard_pile = ["BASH", "DEFEND_IRONCLAD"]
c.play_card(0)
assert c.pending_choice is None and c.in_combat and "HEADBUTT" in c.exhaust_pile and len(c.draw_pile) == 1

# A new fight clears a pending choice.
c = solo(["BRAND", "WOUND", "BASH"]); c.play_card(0); c.fight("MAWLER_NORMAL")
assert c.pending_choice is None and not c.choice_log

# Client commands, and all three enter the generated pool and the reward pools.
client = SimClient(seed=1); client.exec("fight MAWLER_NORMAL"); cc = client._combat
cc.hand, cc.discard_pile = ["BRAND", "WOUND", "BASH"], []
client.play(0); assert client.exec("choose 0")["ok"] and cc.exhaust_pile == ["WOUND"]
cc.hand, cc.discard_pile = ["HEADBUTT"], ["BASH", "WOUND"]
client.play(0, 1); assert client.exec("choose_discard WOUND")["ok"] and cc.draw_pile[-1] == "WOUND"
from sim.act import REWARD_POOLS
from sim.cards import CARDS, CHOICE_CARDS, GENERATED, UPGRADABLE, base_id, is_upgraded, upgrade, card_to_dict
assert set(CHOICE_CARDS) <= set(GENERATED) and "ARMAMENTS" in GENERATED  # the game includes it (FilterForCombat)
assert REWARD_POOLS["COMMON"] == ('ANGER', 'BLOODLETTING', 'BLOOD_WALL', 'BODY_SLAM', 'BREAKTHROUGH', 'CINDER', 'HAVOC', 'HEADBUTT',
    'IRON_WAVE', 'MOLTEN_FIST', 'PERFECTED_STRIKE', 'POMMEL_STRIKE', 'SETUP_STRIKE', 'SHRUG_IT_OFF', 'SWORD_BOOMERANG',
    'THUNDERCLAP', 'TREMBLE', 'TRUE_GRIT', 'TWIN_STRIKE', 'ARMAMENTS')  # unchanged by adding Armaments to CARDS
assert not any(is_upgraded(c) for c in GENERATED + REWARD_POOLS["COMMON"] + REWARD_POOLS["UNCOMMON"] + REWARD_POOLS["RARE"])

# Upgraded cards (OnUpgrade in the decompiled source).
assert CARDS["STRIKE_IRONCLAD+"].damage == 9 and CARDS["DEFEND_IRONCLAD+"].block == 8
assert (CARDS["BASH+"].damage, CARDS["BASH+"].vulnerable) == (10, 3)
assert CARDS["BODY_SLAM+"].cost == 0 and CARDS["HEADBUTT+"].damage == 12 and CARDS["ANGER+"].damage == 8
assert upgrade("SLIMED") == "SLIMED" and "WOUND" not in UPGRADABLE
assert upgrade("BASH+") == "BASH+" and upgrade("BASH") == "BASH+" and base_id("BASH+") == "BASH"
assert is_upgraded("BASH+") and not is_upgraded("BASH")
assert all(c + "+" in CARDS for c in UPGRADABLE) and "ARMAMENTS" in UPGRADABLE
assert CARDS["BASH+"].id == "BASH+" and CARDS["BASH+"].title == "Bash+"
d = card_to_dict("BASH+", 2, True)
assert d["id"] == "BASH" and d["upgraded"] and d["upgradeLevel"] == 1 and d["title"] == "Bash+"
d = card_to_dict("BASH", 2, True)
assert d["upgraded"] is False and d["upgradeLevel"] == 0 and d["title"] == "Bash"
# Armaments with nothing to upgrade still blocks.
c = solo(["ARMAMENTS"]); c.play_card(0); assert c.player_block == 5, c.player_block
assert "BURNING_PACT" in REWARD_POOLS["UNCOMMON"] and "BRAND" in REWARD_POOLS["RARE"]

# Invalid answers change nothing; so does an answer with no prompt open.
c = solo(["BRAND", "WOUND", "BASH"]); c.play_card(0)
assert c.choose_card(2)["error"] == c.choose_card(-1)["error"] == c.choose_discard("WOUND")["error"] == "invalid_choice"
assert c.pending_choice and c.use_potion(0)["error"] == "choice_pending" and not c.choice_log
c = solo(["STRIKE_IRONCLAD"])
assert c.choose_card(0)["error"] == c.choose_discard("BASH")["error"] == "invalid_choice"

# A pause keeps the play open: Rupture's Strength for Brand's HP pays out after the card, and the effect depth
# comes back to 0 (Unceasing Top needs that). A new fight drops an abandoned play's depth.
c = solo(["BRAND", "WOUND", "BASH"]); s = c.strength; c.pw["RupturePower"] = 2
c.play_card(0)
assert c._effect_depth == 1 and c.strength == s and c.cards_played == 0
c.choose_card(0)
assert c._effect_depth == 0 and c.strength == s + 3 and c.cards_played == 1 and c._rupture is None
c = solo(["BRAND", "WOUND", "BASH"]); c.relics = {"UNCEASING_TOP"}
c.play_card(0); c.choose_card(0); c.play_card(0, 1)
assert c.hand == ["DEFEND_IRONCLAD"] and c._effect_depth == 0  # Bash emptied the hand: Top drew
c = solo(["BRAND", "WOUND", "BASH"]); c.play_card(0); c.fight("MAWLER_NORMAL")
assert c._effect_depth == 0 and c._rupture is None

# Exhaust goes through the hooks. A lethal exhaust (Charon's Ashes) makes the fight ending: no draw, no Strength.
c = solo(["BURNING_PACT", "DRUM_OF_BATTLE", "WOUND"]); c.pw["FeelNoPainPower"] = 3
c.play_card(0); c.choose_card(0)
assert c.player_block == 3 and c.energy == 4 and c.exhausted_this_turn
c = solo(["BURNING_PACT", "WOUND", "BASH"]); c.relics = {"CHARONS_ASHES"}; c.enemies[0].hp, c.enemies[0].block = 3, 0
c.play_card(0); c.choose_card(0)
assert not c.in_combat and c.won and len(c.hand) == 1

# Headbutt's damage takes Strength and Pen Nib like any attack.
c = solo(["HEADBUTT"]); c.strength = 2; c.relics, c.relic_state = {"PEN_NIB"}, {"pen_nib": 9}; hp = c.enemies[0].hp
c.play_card(0, 1)
assert c.enemies[0].hp == hp - 22

# Thieving Hopper takes only cards with a DeckVersion: a generated Uncommon outranks Basics but is never stolen.
c = SimCombat(rng=random.Random(7))
c.fight("THIEVING_HOPPER_WEAK", ["STRIKE_IRONCLAD"] * 10)
c.discard_pile.append("INFERNAL_BLADE")
c._steal(c.enemies[0])
assert c.stolen == ["STRIKE_IRONCLAD"] and "INFERNAL_BLADE" in c.discard_pile, c.stolen

# --- Upgraded cards in combat (each card's OnUpgrade / IsUpgraded branch) ---
c = SimCombat(rng=random.Random(3))
c.fight("MAWLER_NORMAL", ["BASH+"] * 10)
e = c.enemies[0]; hp = e.hp; assert e.block == 0
c.play_card(0, 1)
assert hp - e.hp == 10 and e.vulnerable == 3, (hp - e.hp, e.vulnerable)

# Armaments: block 5, then pick one upgradable hand card to upgrade in its slot.
c = solo(["ARMAMENTS", "WOUND", "DEFEND_IRONCLAD", "STRIKE_IRONCLAD"])
c.play_card(0)
assert c.player_block == 5 and c.pending_choice == {"kind": "upgrade", "source": "ARMAMENTS"}
assert c.choose_card(0)["error"] == "invalid_choice" and c.pending_choice  # Wound can't be upgraded
assert c.choose_card(2)["ok"] and c.pending_choice is None
assert c.hand == ["WOUND", "DEFEND_IRONCLAD", "STRIKE_IRONCLAD+"] and c.discard_pile == ["ARMAMENTS"], c.hand
assert c.choice_log == [("ARMAMENTS", "STRIKE_IRONCLAD", ("DEFEND_IRONCLAD", "STRIKE_IRONCLAD"))]
c = solo(["ARMAMENTS", "BASH+", "STRIKE_IRONCLAD"]); c.play_card(0)  # one option: no prompt
assert c.pending_choice is None and c.hand == ["BASH+", "STRIKE_IRONCLAD+"]
client = SimClient(seed=1); client.exec("fight MAWLER_NORMAL"); cc = client._combat
cc.hand = ["ARMAMENTS", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD"]
client.play(0); assert client.exec("choose 1")["ok"] and cc.hand == ["STRIKE_IRONCLAD", "DEFEND_IRONCLAD+"]
# Armaments+: every upgradable hand card, no prompt.
c = solo(["ARMAMENTS+", "STRIKE_IRONCLAD", "WOUND", "BASH+", "DEFEND_IRONCLAD"]); c.play_card(0)
assert c.pending_choice is None and c.player_block == 5
assert c.hand == ["STRIKE_IRONCLAD+", "WOUND", "BASH+", "DEFEND_IRONCLAD+"] and c.discard_pile == ["ARMAMENTS+"]
# In-combat upgrades are this fight's only: the deck passed to fight() is untouched.
deck = ["ARMAMENTS+"] + ["STRIKE_IRONCLAD"] * 9
c = SimCombat(rng=random.Random(4)); c.fight("MAWLER_NORMAL", deck)
c.hand = ["ARMAMENTS+", "STRIKE_IRONCLAD"]; c.play_card(0)
assert c.hand == ["STRIKE_IRONCLAD+"] and deck == ["ARMAMENTS+"] + ["STRIKE_IRONCLAD"] * 9

# Aggression upgrades the Attack it returns (an upgraded one stays as it is).
c = big(solo([])); c.discard_pile = ["STRIKE_IRONCLAD"]; c.pw["AggressionPower"] = 1
c.end_turn()
assert "STRIKE_IRONCLAD+" in c.hand and "STRIKE_IRONCLAD" not in c.hand + c.discard_pile, c.hand
c = big(solo([])); c.discard_pile = ["BASH+"]; c.pw["AggressionPower"] = 1; c.end_turn()
assert "BASH+" in c.hand
# Innate (Aggression+ and Juggling+): in the opening hand.
for _ in range(5):
    c = SimCombat(rng=random.Random(_)); c.fight("MAWLER_NORMAL", ["JUGGLING+", "AGGRESSION+"] + ["DEFEND_IRONCLAD"] * 20)
    assert {"JUGGLING+", "AGGRESSION+"} <= set(c.hand) and len(c.hand) == 5, c.hand

# True Grit+ chooses the card to exhaust (base True Grit takes a random one).
c = solo(["TRUE_GRIT+", "WOUND", "BASH", "STRIKE_IRONCLAD"]); c.play_card(0)
assert c.player_block == 9 and c.pending_choice == {"kind": "hand", "source": "TRUE_GRIT"}
assert c.choose_card(1)["ok"] and c.exhaust_pile == ["BASH"] and c.hand == ["WOUND", "STRIKE_IRONCLAD"]
assert c.discard_pile == ["TRUE_GRIT+"] and c.pending_choice is None
c = solo(["TRUE_GRIT", "WOUND", "BASH"]); c.play_card(0)
assert c.pending_choice is None and len(c.exhaust_pile) == 1

# Thieving Hopper steals the deck's upgraded card as it is.
c = SimCombat(rng=random.Random(7)); c.fight("THIEVING_HOPPER_WEAK", ["BASH+"] * 10)
c._steal(c.enemies[0])
assert c.stolen == ["BASH+"], c.stolen
# The deck's only copy: stolen as it is (it once came back as "UPPERCUT", not in the deck).
c = SimCombat(rng=random.Random(7)); c.fight("THIEVING_HOPPER_WEAK", ["UPPERCUT+"] + ["STRIKE_IRONCLAD"] * 9)
c.draw_pile += c.hand; c.hand = []  # the opening hand is out of reach
c._steal(c.enemies[0])
assert c.stolen == ["UPPERCUT+"] and "UPPERCUT+" not in c.draw_pile, c.stolen
# A deck copy upgraded this fight (Armaments) keeps its DeckVersion: the deck loses the plain card it came from,
# not one of the deck's own UPPERCUT+ (both in the exhaust pile, out of reach).
c = SimCombat(rng=random.Random(7)); c.fight("THIEVING_HOPPER_WEAK", ["UPPERCUT"] + ["UPPERCUT+"] * 2 + ["STRIKE_IRONCLAD"] * 7)
c.draw_pile += c.hand; c.hand = []  # the opening hand is out of reach
c.exhaust_pile += [c.draw_pile.pop(c.draw_pile.index("UPPERCUT+")) for _ in range(2)]
i = c.draw_pile.index("UPPERCUT"); c.draw_pile[i] = upgrade(c.draw_pile[i])  # in its slot, as Stone Cracker does
c._steal(c.enemies[0])
assert c.stolen == ["UPPERCUT"] and "UPPERCUT+" not in c.draw_pile, c.stolen
# A generated copy of a deck card's id has no DeckVersion: with the deck's copy exhausted, a Strike goes instead.
c = SimCombat(rng=random.Random(7)); c.fight("THIEVING_HOPPER_WEAK", ["UPPERCUT"] + ["STRIKE_IRONCLAD"] * 9)
c.draw_pile += c.hand; c.hand = []  # the opening hand is out of reach
c.exhaust_pile.append(c.draw_pile.pop(c.draw_pile.index("UPPERCUT")))
c.discard_pile.append("UPPERCUT")
c._steal(c.enemies[0])
assert c.stolen == ["STRIKE_IRONCLAD"] and c.discard_pile == ["UPPERCUT"], c.stolen

# Upgraded ids go through every id check: Stomp's discount, Ghost Seed, Howl from Beyond, Thrash eating Ashen Strike.
c = solo(["STRIKE_IRONCLAD", "STOMP+"]); c.play_card(0, 1); assert c.cost("STOMP+") == 2
c = solo(["STRIKE_IRONCLAD+"]); c.relics = {"GHOST_SEED"}; assert c._is_ethereal("STRIKE_IRONCLAD+")
c = big(solo([])); c.exhaust_pile = ["HOWL_FROM_BEYOND+"]; c._run_enemy_turn = lambda: None; c.end_turn()
assert c.enemies[0].hp == 500 - 21 and c.discard_pile == ["HOWL_FROM_BEYOND+"]
c = big(solo(["THRASH", "ASHEN_STRIKE+"])); c.exhaust_pile = ["WOUND"] * 2; c.rng = random.Random(0)
c.play_card(0, 1); assert c.bonus_damage["THRASH"] == 6 + 4 * 2, c.bonus_damage  # read before it joins the exhaust pile
c = solo(["BURNING_PACT", "DRUM_OF_BATTLE+", "WOUND"]); c.play_card(0); c.choose_card(0)
assert c.energy == 3 - 1 + 3  # Drum of Battle+'s exhaust: Energy 2, +1


def upgraded(cid, hand=(), setup=lambda c: None, target=1, pick=0):
    """Play cid and cid+ from the same start (after setup); answer a prompt with hand slot / discard pick."""
    out = []
    for x in (cid, cid + "+"):
        c = big(solo([x, *hand], seed=5)); c.energy = 10
        setup(c)
        c.play_card(0, target)
        if c.pending_choice:
            c.choose_card(pick) if c.pending_choice["kind"] != "discard" else c.choose_discard(c.discard_pile[pick])
        assert c.pending_choice is None, (x, c.pending_choice)
        out.append(c)
    return out


dmg = lambda c: 500 - c.enemies[0].hp  # noqa: E731
vuln2 = lambda c: setattr(c.enemies[0], "vulnerable", 2)  # noqa: E731
wounds = lambda n: lambda c: setattr(c, "exhaust_pile", ["WOUND"] * n)  # noqa: E731
# card: (hand, setup, measure, base value, upgraded value), the numbers from <Card>.cs's vars and OnUpgrade.
SPECIAL = {
    "ASHEN_STRIKE": ((), wounds(2), dmg, 6 + 3 * 2, 6 + 4 * 2),
    "BULLY": ((), vuln2, dmg, (4 + 2 * 2) * 3 // 2, (4 + 3 * 2) * 3 // 2),
    "DISMANTLE": ((), None, dmg, 8, 10),
    "FIGHT_ME": ((), None, lambda c: (dmg(c), c.strength, c.enemies[0].strength), (10, 3, 1), (12, 4, 1)),
    "PILLAGE": ((), None, dmg, 6, 9),
    "RAMPAGE": ((), None, lambda c: (dmg(c), c.bonus_damage), (9, {"RAMPAGE": 5}), (9, {"RAMPAGE+": 9})),
    "THRASH": ((), None, dmg, 8, 12),
    "SPITE": ((), lambda c: setattr(c, "hp_lost_this_turn", True), dmg, 10, 15),
    "FEED": ((), lambda c: setattr(c.enemies[0], "hp", 10), lambda c: c.player_max_hp - PLAYER_MAX_HP, 3, 4),
    "FIEND_FIRE": (("WOUND", "WOUND"), None, dmg, 14, 20),
    "MANGLE": ((), None, lambda c: (dmg(c), c.enemies[0].mangle), (15, 10), (20, 15)),
    "PACTS_END": ((), wounds(3), dmg, 17, 23),
    "TEAR_ASUNDER": ((), None, dmg, 5, 7),
    "DOMINATE": ((), None, lambda c: (c.enemies[0].vulnerable, c.strength), (1, 1), (2, 2)),
    "EVIL_EYE": ((), None, lambda c: c.player_block, 8, 11),
    "EXPECT_A_FIGHT": (("STRIKE_IRONCLAD",) * 2, None, lambda c: c.energy, 10, 11),
    "FORGOTTEN_RITUAL": ((), lambda c: setattr(c, "exhausted_this_turn", True), lambda c: c.energy, 12, 13),
    "INFERNAL_BLADE": ((), None, lambda c: (c.energy, any(x.endswith("+") for x in c.hand)), (9, False), (10, False)),
    "SECOND_WIND": (("WOUND", "DEFEND_IRONCLAD"), None, lambda c: c.player_block, 10, 14),
    "CASCADE": ((), lambda c: setattr(c, "energy", 2), lambda c: c.player_block, 10, 15),
    "PRIMAL_FORCE": (("STRIKE_IRONCLAD",), None, lambda c: c.hand, ["GIANT_ROCK"], ["GIANT_ROCK+"]),
    "HEADBUTT": ((), None, dmg, 9, 12),
    "BURNING_PACT": (("WOUND", "STRIKE_IRONCLAD"), None, lambda c: len(c.hand), 3, 4),
    "BRAND": (("WOUND", "STRIKE_IRONCLAD"), None, lambda c: c.strength, 1, 2),
    "ARMAMENTS": (("STRIKE_IRONCLAD", "DEFEND_IRONCLAD"), None, lambda c: c.hand,
                  ["STRIKE_IRONCLAD+", "DEFEND_IRONCLAD"], ["STRIKE_IRONCLAD+", "DEFEND_IRONCLAD+"]),
    "STOKE": (("WOUND", "WOUND"), None, lambda c: sum(map(is_upgraded, c.hand)), 0, 2),
}
assert set(SPECIAL) == {c for c in UPGRADABLE if CARDS[c].special and not CARDS[c].colorless}
for cid, (hand_, setup, measure, want_b, want_u) in SPECIAL.items():
    b, u = upgraded(cid, hand_, setup or (lambda c: None))
    assert (measure(b), measure(u)) == (want_b, want_u), (cid, measure(b), measure(u))


# Lava Lamp's TookDamageThisCombat: a blockable hit that gets through sets lamp_hit; blocked hits and card self-damage don't.
c = solo(["STRIKE_IRONCLAD"]); assert not c.lamp_hit
c.player_block = 5; c._damage_player(4); assert not c.lamp_hit and c.player_hp == 80
c._damage_player(4); assert c.lamp_hit and c.player_hp == 77
c = solo(["STRIKE_IRONCLAD"]); c._lose_hp(3, from_card=True); assert not c.lamp_hit  # Unblockable self-damage
c.fight("MAWLER_NORMAL"); assert not c.lamp_hit
# Colorless cards (ColorlessCardPool minus multiplayer-only): data, Innate, Retain, RetainHandPower and the generic ones.
from sim.cards import COLORLESS, COLORLESS_GENERATED, COLORLESS_RARES, COLORLESS_UNCOMMONS, NOT_BUYABLE, UPGRADES  # noqa: E402
assert len(COLORLESS) == 53 and COLORLESS == COLORLESS_UNCOMMONS + COLORLESS_RARES and len(set(COLORLESS)) == 53
assert COLORLESS[:3] == ("AUTOMATION", "CATASTROPHE", "DARK_SHACKLES") and COLORLESS_RARES[:2] == ("ALCHEMIZE", "ANOINTED")
assert all(CARDS[c].colorless and c in UPGRADES and c + "+" in CARDS for c in COLORLESS)
assert NOT_BUYABLE == {"SPLASH", "ALCHEMIZE"} and "SPLASH" not in COLORLESS_GENERATED and "HAND_OF_GREED" not in COLORLESS_GENERATED
from sim.cards import COMMONS, RARES, UNCOMMONS  # noqa: E402
assert not any(CARDS[c].colorless for c in GENERATED + COMMONS + UNCOMMONS + RARES)  # Ironclad pools only
for cid, spec in {"ULTIMATE_STRIKE": (1, "Attack", "Uncommon", "AnyEnemy"), "THE_BOMB": (2, "Skill", "Uncommon", "Self"),
                  "ANOINTED": (1, "Skill", "Rare", "Self"), "VOLLEY": (0, "Attack", "Uncommon", "RandomEnemy"),
                  "ETERNAL_ARMOR": (3, "Power", "Rare", "Self"), "BEAT_DOWN": (3, "Skill", "Rare", "RandomEnemy"),
                  "SPLASH": (1, "Skill", "Uncommon", "Self"), "JACKPOT": (3, "Attack", "Rare", "AnyEnemy")}.items():
    d = CARDS[cid]
    assert (d.cost, d.type, d.rarity, d.target_type) == spec, cid
# Innate: the opening hand holds Dramatic Entrance, Mind Blast and Entropy+ out of a 25-card deck.
c = SimCombat(rng=random.Random(2)); c.fight("MAWLER_NORMAL", ["STRIKE_IRONCLAD"] * 20 + ["DRAMATIC_ENTRANCE", "MIND_BLAST", "ENTROPY+"])
assert {"DRAMATIC_ENTRANCE", "MIND_BLAST", "ENTROPY+"} <= set(c.hand), c.hand
c = SimCombat(rng=random.Random(2)); c.fight("MAWLER_NORMAL", ["STRIKE_IRONCLAD"] * 20 + ["JUGGLING+", "AGGRESSION+", "ENTROPY"])
assert {"JUGGLING+", "AGGRESSION+"} <= set(c.hand) and "ENTROPY" not in c.hand, c.hand  # base Entropy isn't Innate
# Retain keeps a card; the rest is flushed. Equilibrium keeps the whole hand one turn; Ethereal still exhausts.
c = solo(["RESTLESSNESS", "STRIKE_IRONCLAD"]); c.end_turn()
assert "RESTLESSNESS" in c.hand and "STRIKE_IRONCLAD" not in c.hand and "STRIKE_IRONCLAD" in c.discard_pile
c = solo(["EQUILIBRIUM", "STRIKE_IRONCLAD", "DAZED"]); c.play_card(0); assert c.player_block == 13 and c.pw["RetainHandPower"] == 1
c.end_turn()
assert "STRIKE_IRONCLAD" in c.hand and "DAZED" in c.exhaust_pile and not c.pw.get("RetainHandPower")
c.end_turn(); assert "STRIKE_IRONCLAD" not in c.hand  # one turn only
c = solo(["SALVO+", "STRIKE_IRONCLAD"]); hp = c.enemies[0].hp; c.play_card(0, 1)
assert c.enemies[0].hp == hp - 16 and c.pw["RetainHandPower"] == 1
c.end_turn(); assert "STRIKE_IRONCLAD" in c.hand
# Generic colorless cards.
def hp_lost(hand, **kw):
    c = solo(hand, **kw); c.energy = 10; hp = c.enemies[0].hp; c.play_card(0, 1); return c, hp - c.enemies[0].hp
c, d = hp_lost(["ULTIMATE_STRIKE"]); assert d == 14 and c.energy == 9
assert hp_lost(["ULTIMATE_STRIKE+"])[1] == 20
assert hp_lost(["PERFECTED_STRIKE", "ULTIMATE_STRIKE"])[1] == 6 + 2 * 2 + 0  # Perfected + Ultimate are Strikes; draw pile has none
c, d = hp_lost(["FLASH_OF_STEEL", "STRIKE_IRONCLAD"]); assert d == 5 and len(c.hand) == 2 and c.energy == 10
c = solo(["FINESSE+"]); c.play_card(0); assert c.player_block == 7 and len(c.hand) == 1
c = solo(["MASTER_OF_STRATEGY"]); c.play_card(0); assert len(c.hand) == 3 and c.exhaust_pile == ["MASTER_OF_STRATEGY"] and c.energy == 3
c = solo(["PRODUCTION+"]); c.play_card(0); assert c.energy == 6 and c.exhaust_pile == ["PRODUCTION+"]
c = solo(["ULTIMATE_DEFEND"]); c.play_card(0); assert c.player_block == 11 and c.energy == 2
c = solo(["DRAMATIC_ENTRANCE+"], "SLIMES_WEAK")
for e in c.enemies:
    e.hp = e.max_hp = 100
hps = [e.hp for e in c.enemies]; c.play_card(0)
assert [h - e.hp for h, e in zip(hps, c.enemies)] == [15] * len(hps) and c.exhaust_pile == ["DRAMATIC_ENTRANCE+"]
c = solo(["SHOCKWAVE"], "SLIMES_WEAK"); c.energy = 3; c.play_card(0)
assert all((e.weak, e.vulnerable) == (3, 3) for e in c.enemies) and c.energy == 1
c = solo(["PROWESS+"]); c.play_card(0); assert (c.strength, c.dexterity) == (2, 2)
c = solo(["VOLLEY", "DEFEND_IRONCLAD"]); c.enemies[0].hp = c.enemies[0].max_hp = 100; c.energy = 3; c.play_card(0)
assert c.enemies[0].hp == 70 and c.energy == 0  # X = 3 hits of 10
c = solo(["VOLLEY"], "SLIMES_WEAK"); c.energy = 2
for e in c.enemies:
    e.hp = e.max_hp = 100
hps = sum(e.hp for e in c.enemies); c.play_card(0)
assert hps - sum(e.hp for e in c.enemies) == 20
# Colorless cards with their own logic (Dark Shackles, Panic Button and Prolong are powers: plan task 3).
RARES_ = [x for x in CARDS if CARDS[x].rarity == "Rare" and not CARDS[x].colorless and not is_upgraded(x)]
COLORLESS_SPECIAL = {  # card: (hand, setup, measure, base value, upgraded value) from <Card>.cs
    "ANOINTED": ((), lambda c: setattr(c, "draw_pile", [RARES_[0]]), lambda c: CARDS[c.exhaust_pile[0]].retain, False, True),
    "BEAT_DOWN": ((), lambda c: setattr(c, "discard_pile", [S] * 5), dmg, 18, 24),
    "BOLAS": ((), None, dmg, 3, 4),
    "CATASTROPHE": ((), lambda c: setattr(c, "draw_pile", [S] * 5), dmg, 12, 18),
    "FISTICUFFS": ((), None, lambda c: (dmg(c), c.player_block), (7, 7), (9, 9)),
    "GOLD_AXE": ((), None, lambda c: CARDS[c.discard_pile[-1]].retain, False, True),
    "HAND_OF_GREED": ((), lambda c: setattr(c.enemies[0], "hp", 20), lambda c: c.gold_gained, 20, 25),
    "HIDDEN_GEM": ((), lambda c: setattr(c, "draw_pile", [DeckCard(S)]), lambda c: tuple(c.replays.values()), (2,), (3,)),
    "IMPATIENCE": ((D,), None, lambda c: len(c.hand), 3, 4),
    "JACK_OF_ALL_TRADES": ((), None, lambda c: len(c.hand), 1, 2),
    "JACKPOT": ((), None, lambda c: (dmg(c), len(c.hand)), (25, 3), (30, 3)),
    "MIND_BLAST": ((), None, lambda c: c.energy, 9, 10),
    "OMNISLICE": ((), None, dmg, 8, 11),
    "REND": ((), None, dmg, 15, 18),
    "RESTLESSNESS": ((), None, lambda c: (len(c.hand), c.energy), (2, 12), (3, 13)),
    "SCRAWL": ((), lambda c: setattr(c, "draw_pile", [D] * 20), lambda c: CARDS[c.exhaust_pile[0]].retain, False, True),
    "THRUMMING_HATCHET": ((), None, dmg, 11, 14),
}
assert len(COLORLESS_SPECIAL) == 17
for cid, (hand_, setup, measure, want_b, want_u) in COLORLESS_SPECIAL.items():
    b, u = upgraded(cid, hand_, setup or (lambda c: None))
    assert (measure(b), measure(u)) == (want_b, want_u), (cid, measure(b), measure(u))
# Anointed: a random Rare from the draw pile for each free hand slot (10 - hand), straight to hand.
c = solo(["ANOINTED"] + [D] * 8); c.draw_pile = [S, RARES_[0], RARES_[1], S, RARES_[2]]; c.play_card(0)
assert sorted(x for x in c.hand if x != D) == sorted(x for x in c.hand if x in RARES_) and len([x for x in c.hand if x in RARES_]) == 2
assert len(c.draw_pile) == 3 and sum(x in RARES_ for x in c.draw_pile) == 1 and c.exhaust_pile == ["ANOINTED"]
c = solo(["ANOINTED"] + [D] * 9); c.draw_pile = [RARES_[0]]; c.play_card(0); assert len(c.hand) == 10 and not c.draw_pile
# Beat Down: 3 (4) random Attacks from the discard pile, free; Skills and Unplayable cards stay.
c = big(solo(["BEAT_DOWN"])); c.discard_pile = [S, D, "WOUND", S, S, S]; c.energy = 3; c.play_card(0, 1)
assert dmg(c) == 18 and c.energy == 0 and c.discard_pile.count(S) == 4 and "WOUND" in c.discard_pile
c = big(solo(["BEAT_DOWN"])); c.discard_pile = [S, D]; c.play_card(0, 1); assert dmg(c) == 6
# Bolas / Thrumming Hatchet come back to hand at the next turn start, and only if played last turn.
for cid, d in (("BOLAS", 3), ("THRUMMING_HATCHET", 11)):
    c = big(solo([DeckCard(cid), DeckCard(cid), D])); c.draw_pile = [D] * 40
    assert dealt(c) == d
    c.end_turn()  # one copy played; the other (in hand) is discarded unplayed
    assert c.hand.count(cid) == 1 and c.discard_pile.count(cid) == 1, (cid, c.hand, c.discard_pile)
    c.end_turn()  # not played this turn: the discarded one stays there
    assert c.hand.count(cid) == 0 and c.discard_pile.count(cid) == 2, (cid, c.hand, c.discard_pile)
c = big(solo([DeckCard("BOLAS")])); c.play_card(0, 1); c.draw_pile = c.draw_pile + [c.discard_pile.pop()]  # reshuffled away, hand full
c.hand = ["RESTLESSNESS"] * 10; c._start_player_turn()
assert len(c.hand) == 10 and c.discard_pile == ["BOLAS"] and "BOLAS" not in c.draw_pile
c = big(solo([DeckCard("BOLAS")])); c.play_card(0, 1); c.hand = []; c._start_player_turn(); assert "BOLAS" in c.hand
# Catastrophe: 2 (3) random playable draw-pile cards, free; with only Unplayable ones left it plays one of those.
c = big(solo(["CATASTROPHE"])); c.draw_pile = [S, S, "WOUND", S]; c.energy = 2; c.play_card(0, 1)
assert dmg(c) == 12 and sorted(c.draw_pile) == sorted([S, "WOUND"])
c = big(solo(["CATASTROPHE"])); c.draw_pile = ["DAZED"]; c.play_card(0, 1); assert not c.draw_pile and "DAZED" in c.discard_pile
c = big(solo(["CATASTROPHE"])); c.draw_pile = []; c.play_card(0, 1); assert dmg(c) == 0
# Fisticuffs: block equals the damage dealt, blocked and overkill included, with Dexterity and Frail.
c = big(solo(["FISTICUFFS"])); c.enemies[0].block = 5; c.play_card(0, 1)
assert c.player_block == 7 and c.enemies[0].max_hp - c.enemies[0].hp == 2
c = solo(["FISTICUFFS"], "SLIMES_WEAK"); c.enemies[0].hp = 3; c.enemies[1].hp = 100; c.play_card(0, 1); assert c.player_block == 7
c = big(solo(["FISTICUFFS"])); c.dexterity = 2; c.frail = 1; c.play_card(0, 1); assert c.player_block == 9 * 3 // 4
# Gold Axe: 1 damage per card play finished this combat (earlier turns too), not counting itself.
c = big(solo([D, D, "GOLD_AXE", "GOLD_AXE"])); c.energy = 10; c.play_card(0); c.play_card(0)
assert dealt(c) == 2 and dealt(c) == 3
c = big(solo([D, "GOLD_AXE"])); c.play_card(0); c.end_turn(); c.hand = ["GOLD_AXE"]; c.energy = 3; assert dealt(c) == 1
# Hand of Greed: gold on a kill (not a minion).
c = solo(["HAND_OF_GREED"]); c.enemies[0].hp = 20; c.play_card(0, 1); assert c.won and c.gold_gained == 20
c = solo(["HAND_OF_GREED+"]); c.enemies[0].hp = 25; c.play_card(0, 1); assert c.won and c.gold_gained == 25
c = big(solo(["HAND_OF_GREED"])); c.play_card(0, 1); assert c.gold_gained == 0
c = solo(["HAND_OF_GREED"], "SLIMES_WEAK"); c.enemies[0].defn = replace(c.enemies[0].defn, minion=True); c.enemies[0].hp = 5
c.play_card(0, 1); assert not c.enemies[0].is_alive and c.gold_gained == 0
c.fight("MAWLER_NORMAL"); assert c.gold_gained == 0
# Hidden Gem: Replay on an Attack / Skill / Power in the draw pile (Status only as a fallback), plays 1 + Replay times.
c = big(solo(["HIDDEN_GEM"])); pick = DeckCard(S); c.draw_pile = ["SLIMED", pick]; c.play_card(0)
assert c.replays == {id(pick): 2}
c.hand = [pick]; c.draw_pile = []; assert dealt(c) == 18
c = big(solo(["HIDDEN_GEM+"])); pick = DeckCard(S); c.draw_pile = [pick]; c.play_card(0); c.hand = [pick]; assert dealt(c) == 24
c = solo(["HIDDEN_GEM"]); slimed = DeckCard("SLIMED"); c.draw_pile = ["DAZED", slimed]; c.play_card(0); assert c.replays == {id(slimed): 2}
c = solo(["HIDDEN_GEM"]); c.draw_pile = ["DAZED"]; c.play_card(0); assert not c.replays
c = solo(["HIDDEN_GEM"]); c.draw_pile = []; c.play_card(0); assert not c.replays
c = big(solo(["HIDDEN_GEM"])); c.draw_pile = [DeckCard(S)]; c.play_card(0); c.pw["OneTwoPunchPower"] = 1; c.hand = [c.draw_pile[0]]
assert dealt(c) == 24  # 1 + Replay 2 + One-Two Punch's 1
# Impatience: draws only with no Attack in hand.
c = solo(["IMPATIENCE", D]); c.play_card(0); assert len(c.hand) == 3
c = solo(["IMPATIENCE", S]); c.play_card(0); assert len(c.hand) == 1
# Jack of All Trades: distinct colorless cards from the generatable pool, never itself; a full hand sends them to discard.
from sim.cards import COLORLESS_GENERATED as CG  # noqa: E402
for seed in range(60):
    c = solo(["JACK_OF_ALL_TRADES+"], seed=seed); c.play_card(0)
    assert len(set(c.hand)) == 2 and set(c.hand) <= set(CG) - {"JACK_OF_ALL_TRADES"}, c.hand
c = solo(["JACK_OF_ALL_TRADES"] + [D] * 10); c.play_card(0)
assert len(c.hand) == 10 and len(c.discard_pile) == 1 and c.discard_pile[0] in CG and c.exhaust_pile == ["JACK_OF_ALL_TRADES"]
# Jackpot: 3 random 0-cost non-X Ironclad cards (upgraded if Jackpot is).
for cid, up in (("JACKPOT", False), ("JACKPOT+", True)):
    for seed in range(20):
        c = big(solo([cid], seed=seed)); c.energy = 3; c.play_card(0, 1)
        assert len(c.hand) == 3 and all(base_id(x) in GENERATED and CARDS[base_id(x)].cost == 0 and not CARDS[x].x_cost for x in c.hand), c.hand
        assert all(is_upgraded(x) == (up and base_id(x) in UPGRADABLE) for x in c.hand), c.hand
c = big(solo(["JACKPOT"] + [D] * 9)); c.energy = 3; c.play_card(0, 1); assert len(c.hand) == 10 and len(c.discard_pile) == 3  # Jackpot + 2 overflow
c = solo(["JACKPOT"]); c.enemies[0].hp = 25; c.play_card(0, 1); assert c.won and not c.hand  # nothing is created once the fight is over
# Mind Blast: 1 per draw-pile card; Innate (tested above); upgraded costs 0.
c = big(solo(["MIND_BLAST"])); c.draw_pile = [D] * 7; c.play_card(0, 1); assert dmg(c) == 7
c = big(solo(["MIND_BLAST"])); c.draw_pile = [D] * 7; c.strength = 2; c.play_card(0, 1); assert dmg(c) == 7 + 2
assert CARDS["MIND_BLAST"].innate and CARDS["MIND_BLAST+"].cost == 0 and CARDS["MIND_BLAST+"].innate
# Omnislice: the target takes a powered hit; every other enemy takes what it took (blocked and overkill too), Unpowered.
c = big(solo(["OMNISLICE"], "SLIMES_WEAK")); c.strength = 3; c.enemies[0].vulnerable = 2
for e in c.enemies[1:]:
    e.vulnerable, e.weak = 2, 1
c.play_card(0, 1)
assert [500 - e.hp for e in c.enemies] == [16] * len(c.enemies), [500 - e.hp for e in c.enemies]
c = solo(["OMNISLICE+"], "SLIMES_WEAK"); c.enemies[0].hp, c.enemies[0].block = 3, 0
for e in c.enemies[1:]:
    e.hp = e.max_hp = 100; e.block = 0
c.play_card(0, 1)
assert all(100 - e.hp == 11 for e in c.enemies[1:]) and not c.enemies[0].is_alive  # overkill counts
c = big(solo(["OMNISLICE"], "SLIMES_WEAK")); c.enemies[0].block = 5; c.play_card(0, 1)
assert all(500 - e.hp == 8 for e in c.enemies[1:])  # blocked damage counts
# Rend: 15 + 5 (18 + 8) per non-temporary debuff, then the usual damage modifiers.
c = big(solo(["REND"])); c.enemies[0].vulnerable, c.enemies[0].weak = 2, 1; c.play_card(0, 1); assert dmg(c) == (15 + 10) * 3 // 2
c = big(solo(["REND+"])); c.enemies[0].vulnerable, c.enemies[0].weak = 2, 1; c.play_card(0, 1); assert dmg(c) == (18 + 16) * 3 // 2
c = big(solo(["REND"])); c.play_card(0, 1); assert dmg(c) == 15
# Mangle's own power is temporary and doesn't count; the negative Strength it applies is a separate debuff that does.
c = big(solo(["REND"])); c.enemies[0].mangle, c.enemies[0].strength = 5, -5; c.play_card(0, 1); assert dmg(c) == 20
c = big(solo(["REND"])); c.enemies[0].strength = 5; c.play_card(0, 1); assert dmg(c) == 15  # positive Strength is a buff
c = big(solo(["REND"])); c.enemies[0].artifact = 1; c.play_card(0, 1); assert dmg(c) == 15
# Restlessness: only when it is the only card in hand.
c = solo(["RESTLESSNESS"]); c.play_card(0); assert len(c.hand) == 2 and c.energy == 5
c = solo(["RESTLESSNESS", D]); c.play_card(0); assert len(c.hand) == 1 and c.energy == 3
# Scrawl: draw to a full hand.
c = solo(["SCRAWL", D, D]); c.draw_pile = [D] * 20; c.play_card(0); assert len(c.hand) == 10 and c.exhaust_pile == ["SCRAWL"]
c = solo(["SCRAWL"] + [D] * 9); c.draw_pile = [D] * 20; c.play_card(0); assert len(c.hand) == 10
print("colorless card checks ok")
print("lava lamp engine checks ok")
print("sim self-check ok")
