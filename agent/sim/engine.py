"""Pure-Python combat simulator: the Ironclad (whole card pool, see cards.py) vs. every Act 1
encounter (see ENCOUNTERS).

Ported directly from decompiled game source rather than guessed at (ascension
0 values): monsters from decompiled/MegaCrit.Sts2.Core.Models.Monsters/, encounter
rosters from .../Models.Encounters/, move selection from
.../MonsterMoves.MonsterMoveStateMachine/RandomBranchState.cs, cards and powers from
.../Models.Cards/ and .../Models.Powers/, turn order from Combat/CombatManager.cs. Exposes
the same interface AutoSpireClient does (state/combat/exec/play/end_turn/wait_for/
full_restart/ping) so STS2CombatEnv works unmodified with either backend.

Damage: the game keeps damage as a decimal through all modifiers
(Hook.ModifyDamage), then block absorbs min(block, dmg) and HP loss is
truncated to int (Creature.LoseHpInternal) — for non-negative damage vs.
integer block that equals flooring first, which is what we do (in exact
integer math, so 0.7 * 1.5 products don't hit float error). Damage from powers
(Juggernaut, Flame Barrier, Inferno, Constrict, Infection) is Unpowered: no
Strength/Vulnerable/Weak.

Known simplifications:
  - Relics are modeled in sim/relics.py (Burning Blood is applied by run.py between fights); 12 of the potions (sim/potions.py).
  - An upgraded card is the id "X+" (cards.UPGRADES); id checks go through cards.base_id. In-combat upgrades
    (Armaments, Aggression, Stoke+, Primal Force+) replace the id in its pile for this fight only.
  - Enemy-targeted cards hit the enemy with the given combatId, or the first
    living enemy if none is given (the mod's auto-target,
    combatState.HittableEnemies.FirstOrDefault()).
  - Hook order among same-timing powers is assumed where the source doesn't fix it (marked).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .cards import CARDS, GENERATED, UPGRADABLE, DeckCard, base_id, card_to_dict, is_upgraded, starter_deck, upgrade
from .potions import MAX_POTION_SLOTS, POTION_SLOTS, POTIONS

PLAYER_MAX_HP = 80
PLAYER_MAX_ENERGY = 3
HAND_DRAW_COUNT = 5
MAX_HAND_SIZE = 10  # CardPile.MaxCardsInHand: draws stop, generated cards go to the discard pile
INNATE = frozenset({"JUGGLING+", "AGGRESSION+"})  # their OnUpgrade adds CardKeyword.Innate
MAX_SHUFFLES = 1000  # per fight; real fights reshuffle a handful of times


class CardCopy(str):
    """A card id whose copy costs more: Frantic Escape adds 1 to the copy that was played (AddThisCombat)."""
    extra = 0


def frantic_escape(extra: int) -> str:
    copy = CardCopy("FRANTIC_ESCAPE")
    copy.extra = extra
    return copy


class SimLoopError(RuntimeError):
    """MAX_SHUFFLES reshuffles in one fight: an infinite draw loop (Pillage under Ringing +
    Hellraiser was one). STS2CombatEnv ends the episode instead of hanging training."""


@dataclass(frozen=True)
class Move:
    intent: str  # "Attack" | "Buff" | "Debuff" | "Status" — env only reads "Attack"
    damage: int = 0
    block: int = 0  # gained by the monster, after its attack
    strength: int = 0  # gained by the monster
    shrink: bool = False  # applies infinite Shrink to the player (ShrinkPower.cs: -30% attack damage)
    slimed: int = 0  # Slimed status cards added to the player's discard pile
    hits: int = 1  # MultiAttackIntent hit count (each hit is reduced by block separately)
    vulnerable: int = 0  # Vulnerable applied to the player
    frail: int = 0  # Frail applied to the player
    tangled: int = 0  # Tangled applied to the player (Attack cards cost +amount until their turn ends)
    constrict: int = 0  # Constrict applied to the player (blockable damage at the end of their turn)
    dazed: int = 0  # Dazed status cards added to the player's discard pile
    summon: str = ""  # monster id added to combat (acts from next turn)
    revive: bool = False  # IllusionPower's REVIVE_MOVE: heal to full
    infection: int = 0  # Infection status cards added to the player's discard pile
    wound: int = 0  # Wound status cards added to the player's discard pile
    weak: int = 0  # Weak applied to the player (their attacks x0.75)
    ringing: bool = False  # RingingPower on the player: one card play on their next turn
    plow: int = 0  # PlowPower applied to itself (Ceremonial Beast)
    toxic: int = 0  # Toxic status cards added to the player's hand
    effect: str = ""  # move logic that fits no field: SimCombat._move_effect


# A RandomBranchState: weighted choice among (move, max consecutive uses[, cooldown[, weight]]).
# Weight is 0 if the last `max` logged moves were all this move — that's the
# CannotRepeat (max=1) / CanRepeatXTimes rule in RandomBranchState.GetStateWeight —
# or, for max=ONCE (UseOnlyOnce), if it was ever used; and also 0 if it is among the
# last `cooldown` moves. Careful: AddBranch(state, int, MoveRepeatType) takes a
# *cooldown*, not a weight.
Branch = tuple[tuple, ...]
ONCE = 0
FOREVER = 10**6  # MoveRepeatType.CanRepeatForever


@dataclass(frozen=True)
class MonsterDef:
    model_id: str
    name: str
    hp: tuple[int, int]  # inclusive (Creature.cs rolls MaxInitialHp + 1 exclusive)
    moves: dict[str, Move]
    first: str | Branch
    follow: dict[str, str | Branch]
    start_block: int = 0  # AfterAddedToRoom block (clears at the start of its first turn)
    artifact: int = 0  # ArtifactPower: negates that many debuffs
    slippery: int = 0  # SlipperyPower: that many HP losses are capped at 1
    # IllusionPower (+ MinionPower): not needed to win, stays in combat when killed and
    # revives to full HP on its next turn.
    illusion: bool = False
    minion: bool = False  # MinionPower without the illusion revive (Kin Followers)
    slow: bool = False  # SlowPower: takes +10% damage per card the player played this turn
    territorial: int = 0  # TerritorialPower: gains this much Strength at the end of its turns
    on_death_spawn: tuple[str, ...] = ()  # InfestedPower: monsters spawned (stunned) on death
    powers: tuple[tuple[str, int], ...] = ()  # applied in AfterAddedToRoom, kept in _Enemy.pw (Hive monsters)
    reattach: bool = False  # ReattachPower: stays in combat when killed, unhittable, heals back while another segment lives


_LEAF_S_RAND: Branch = (("TACKLE_MOVE", 1), ("GOOP_MOVE", 1))
_TWIG_M_RAND: Branch = (("POKEY_POUNCE_MOVE", 2), ("STICKY_SHOT_MOVE", 1))
_MAWLER_RAND: Branch = (("RIP_AND_TEAR_MOVE", 1), ("ROAR_MOVE", ONCE), ("CLAW_MOVE", 1))
_FLYCONID_RAND: Branch = (("VULNERABLE_SPORES_MOVE", 1, 3), ("FRAIL_SPORES_MOVE", 1, 2), ("SMASH_MOVE", 1))
_INKLET_RAND: Branch = (("PIERCING_GAZE_MOVE", 1), ("WHIRLWIND_MOVE", 1))
_FOGMOG_BRANCH: Branch = (("SWIPE_RANDOM_MOVE", 1, 0, 0.4), ("HEADBUTT_MOVE", 1, 0, 0.6))
_STRANGLER_RAND: Branch = (("THWACK", FOREVER), ("LASH", FOREVER))
_EXOSKELETON_RAND: Branch = (("SKITTER_MOVE", 1), ("MANDIBLES_MOVE", 1))
_HUNTER_RAND: Branch = (("BITE_MOVE", 1), ("PUNCTURE_MOVE", 2))
_OBSCURA_RAND: Branch = (("PIERCING_GAZE_MOVE", 1), ("SAIL_MOVE", 1), ("HARDENING_STRIKE_MOVE", 1))
_SEGMENT_RAND: Branch = (("WRITHE_MOVE", 1), ("BULK_MOVE", 1), ("CONSTRICT_MOVE", 1))
# Wriggler.cs INIT_MOVE: by slot, wriggler1/3 BITE and wriggler2/4 WRIGGLE.
WRIGGLER_SLOT_OPENERS = ("NASTY_BITE_MOVE", "WRIGGLE_MOVE", "NASTY_BITE_MOVE", "WRIGGLE_MOVE")

MONSTERS: dict[str, MonsterDef] = {m.model_id: m for m in [
    # Nibbit.cs — alone (NibbitsWeak) it opens with BUTT; NibbitsNormal overrides the opener per slot.
    MonsterDef("NIBBIT", "Nibbit", (42, 46), {
        "BUTT_MOVE": Move("Attack", damage=12),
        "SLICE_MOVE": Move("Attack", damage=6, block=5),
        "HISS_MOVE": Move("Buff", strength=2),
    }, "BUTT_MOVE", {"BUTT_MOVE": "SLICE_MOVE", "SLICE_MOVE": "HISS_MOVE", "HISS_MOVE": "BUTT_MOVE"}),
    MonsterDef("SHRINKER_BEETLE", "Shrinker Beetle", (38, 40), {
        "SHRINKER_MOVE": Move("Debuff", shrink=True),
        "CHOMP_MOVE": Move("Attack", damage=7),
        "STOMP_MOVE": Move("Attack", damage=13),
    }, "SHRINKER_MOVE", {"SHRINKER_MOVE": "CHOMP_MOVE", "CHOMP_MOVE": "STOMP_MOVE", "STOMP_MOVE": "CHOMP_MOVE"}),
    MonsterDef("FUZZY_WURM_CRAWLER", "Fuzzy Wurm Crawler", (55, 57), {
        "FIRST_ACID_GOOP": Move("Attack", damage=4),
        "INHALE": Move("Buff", strength=7),
        "ACID_GOOP": Move("Attack", damage=4),
    }, "FIRST_ACID_GOOP", {"FIRST_ACID_GOOP": "INHALE", "INHALE": "ACID_GOOP", "ACID_GOOP": "FIRST_ACID_GOOP"}),
    MonsterDef("LEAF_SLIME_S", "Leaf Slime (S)", (11, 15), {
        "TACKLE_MOVE": Move("Attack", damage=3),
        "GOOP_MOVE": Move("Status", slimed=1),
    }, _LEAF_S_RAND, {"TACKLE_MOVE": _LEAF_S_RAND, "GOOP_MOVE": _LEAF_S_RAND}),
    MonsterDef("TWIG_SLIME_S", "Twig Slime (S)", (7, 11), {
        "TACKLE_MOVE": Move("Attack", damage=4),
    }, "TACKLE_MOVE", {"TACKLE_MOVE": "TACKLE_MOVE"}),
    MonsterDef("LEAF_SLIME_M", "Leaf Slime (M)", (32, 35), {
        "CLUMP_SHOT": Move("Attack", damage=8),
        "STICKY_SHOT": Move("Status", slimed=2),
    }, "STICKY_SHOT", {"STICKY_SHOT": "CLUMP_SHOT", "CLUMP_SHOT": "STICKY_SHOT"}),
    MonsterDef("TWIG_SLIME_M", "Twig Slime (M)", (26, 28), {
        "POKEY_POUNCE_MOVE": Move("Attack", damage=11),
        "STICKY_SHOT_MOVE": Move("Status", slimed=1),
    }, "STICKY_SHOT_MOVE", {"POKEY_POUNCE_MOVE": _TWIG_M_RAND, "STICKY_SHOT_MOVE": _TWIG_M_RAND}),
    MonsterDef("MAWLER", "Mawler", (72, 72), {
        "RIP_AND_TEAR_MOVE": Move("Attack", damage=14),
        "ROAR_MOVE": Move("Debuff", vulnerable=3),
        "CLAW_MOVE": Move("Attack", damage=4, hits=2),
    }, "CLAW_MOVE", dict.fromkeys(("RIP_AND_TEAR_MOVE", "ROAR_MOVE", "CLAW_MOVE"), _MAWLER_RAND)),
    MonsterDef("FLYCONID", "Flyconid", (47, 49), {
        "VULNERABLE_SPORES_MOVE": Move("Debuff", vulnerable=2),
        "FRAIL_SPORES_MOVE": Move("Attack", damage=8, frail=2),
        "SMASH_MOVE": Move("Attack", damage=11),
    }, (("FRAIL_SPORES_MOVE", 1, 2), ("SMASH_MOVE", 1)),
        dict.fromkeys(("VULNERABLE_SPORES_MOVE", "FRAIL_SPORES_MOVE", "SMASH_MOVE"), _FLYCONID_RAND)),
    # Ruby Raiders (RubyRaidersNormal.cs picks 3 distinct of these 5).
    MonsterDef("ASSASSIN_RUBY_RAIDER", "Assassin Raider", (18, 23), {
        "KILLSHOT_MOVE": Move("Attack", damage=10),
    }, "KILLSHOT_MOVE", {"KILLSHOT_MOVE": "KILLSHOT_MOVE"}),
    MonsterDef("AXE_RUBY_RAIDER", "Axe Raider", (20, 22), {
        "SWING_1": Move("Attack", damage=5, block=5),
        "SWING_2": Move("Attack", damage=5, block=5),
        "BIG_SWING": Move("Attack", damage=12),
    }, "SWING_1", {"SWING_1": "SWING_2", "SWING_2": "BIG_SWING", "BIG_SWING": "SWING_1"}),
    MonsterDef("BRUTE_RUBY_RAIDER", "Brute Raider", (30, 33), {
        "BEAT_MOVE": Move("Attack", damage=7),
        "ROAR_MOVE": Move("Buff", strength=3),
    }, "BEAT_MOVE", {"BEAT_MOVE": "ROAR_MOVE", "ROAR_MOVE": "BEAT_MOVE"}),
    MonsterDef("CROSSBOW_RUBY_RAIDER", "Crossbow Raider", (18, 21), {
        "FIRE_MOVE": Move("Attack", damage=14),
        "RELOAD_MOVE": Move("Defend", block=3),
    }, "RELOAD_MOVE", {"RELOAD_MOVE": "FIRE_MOVE", "FIRE_MOVE": "RELOAD_MOVE"}),
    MonsterDef("TRACKER_RUBY_RAIDER", "Tracker Raider", (21, 25), {
        "TRACK_MOVE": Move("Debuff", frail=2),
        "HOUNDS_MOVE": Move("Attack", damage=1, hits=8),
    }, "TRACK_MOVE", {"TRACK_MOVE": "HOUNDS_MOVE", "HOUNDS_MOVE": "HOUNDS_MOVE"}),
    # Inklet.cs: INIT_RAND is built but unused — the opener is JAB (WHIRLWIND for the middle one).
    MonsterDef("INKLET", "Inklet", (11, 17), {
        "JAB_MOVE": Move("Attack", damage=3),
        "WHIRLWIND_MOVE": Move("Attack", damage=2, hits=3),
        "PIERCING_GAZE_MOVE": Move("Attack", damage=10),
    }, "JAB_MOVE", {"JAB_MOVE": _INKLET_RAND, "WHIRLWIND_MOVE": "JAB_MOVE", "PIERCING_GAZE_MOVE": "JAB_MOVE"},
        slippery=1),
    MonsterDef("CUBEX_CONSTRUCT", "Cubex Construct", (65, 65), {
        "CHARGE_UP_MOVE": Move("Buff", strength=2),
        "REPEATER_BLAST_MOVE": Move("Attack", damage=7, strength=2),
        "REPEATER_BLAST_MOVE_2": Move("Attack", damage=7, strength=2),
        "EXPEL_MOVE": Move("Attack", damage=5, hits=2),
    }, "CHARGE_UP_MOVE", {"CHARGE_UP_MOVE": "REPEATER_BLAST_MOVE", "REPEATER_BLAST_MOVE": "REPEATER_BLAST_MOVE_2",
                          "REPEATER_BLAST_MOVE_2": "EXPEL_MOVE", "EXPEL_MOVE": "REPEATER_BLAST_MOVE"},
        start_block=13, artifact=1),
    MonsterDef("VINE_SHAMBLER", "Vine Shambler", (61, 61), {
        "SWIPE_MOVE": Move("Attack", damage=6, hits=2),
        "GRASPING_VINES_MOVE": Move("Attack", damage=8, tangled=1),
        "CHOMP_MOVE": Move("Attack", damage=16),
    }, "SWIPE_MOVE", {"SWIPE_MOVE": "GRASPING_VINES_MOVE", "GRASPING_VINES_MOVE": "CHOMP_MOVE", "CHOMP_MOVE": "SWIPE_MOVE"}),
    MonsterDef("FOGMOG", "Fogmog", (74, 74), {
        "ILLUSION_MOVE": Move("Summon", summon="EYE_WITH_TEETH"),
        "SWIPE_MOVE": Move("Attack", damage=8, strength=1),
        "SWIPE_RANDOM_MOVE": Move("Attack", damage=8, strength=1),
        "HEADBUTT_MOVE": Move("Attack", damage=14),
    }, "ILLUSION_MOVE", {"ILLUSION_MOVE": "SWIPE_MOVE", "SWIPE_MOVE": _FOGMOG_BRANCH,
                         "SWIPE_RANDOM_MOVE": "HEADBUTT_MOVE", "HEADBUTT_MOVE": "SWIPE_MOVE"}),
    MonsterDef("EYE_WITH_TEETH", "Eye With Teeth", (6, 6), {
        "DISTRACT_MOVE": Move("Status", dazed=3),
        "REVIVE_MOVE": Move("Heal", revive=True),
    }, "DISTRACT_MOVE", {"DISTRACT_MOVE": "DISTRACT_MOVE", "REVIVE_MOVE": "DISTRACT_MOVE"}, illusion=True),
    MonsterDef("SNAPPING_JAXFRUIT", "Snapping Jaxfruit", (31, 33), {
        "ENERGY_ORB_MOVE": Move("Attack", damage=3, strength=2),
    }, "ENERGY_ORB_MOVE", {"ENERGY_ORB_MOVE": "ENERGY_ORB_MOVE"}),
    MonsterDef("SLITHERING_STRANGLER", "Slithering Strangler", (53, 55), {
        "CONSTRICT": Move("Debuff", constrict=3),
        "THWACK": Move("Attack", damage=7, block=5),
        "LASH": Move("Attack", damage=12),
    }, "CONSTRICT", {"CONSTRICT": _STRANGLER_RAND, "THWACK": "CONSTRICT", "LASH": "CONSTRICT"}),
    # --- Act 1 elites ---
    # BygoneEffigy.cs: SLEEP_MOVE_2 is in the state list but nothing transitions to it.
    MonsterDef("BYGONE_EFFIGY", "Bygone Effigy", (127, 127), {
        "SLEEP_MOVE": Move("Sleep"),
        "WAKE_MOVE": Move("Buff", strength=10),
        "SLASHES_MOVE": Move("Attack", damage=13),
    }, "SLEEP_MOVE", {"SLEEP_MOVE": "WAKE_MOVE", "WAKE_MOVE": "SLASHES_MOVE", "SLASHES_MOVE": "SLASHES_MOVE"},
        slow=True),
    MonsterDef("BYRDONIS", "Byrdonis", (81, 84), {
        "SWOOP_MOVE": Move("Attack", damage=17),
        "PECK_MOVE": Move("Attack", damage=3, hits=3),
    }, "SWOOP_MOVE", {"SWOOP_MOVE": "PECK_MOVE", "PECK_MOVE": "SWOOP_MOVE"}, territorial=1),
    MonsterDef("PHROG_PARASITE", "Phrog Parasite", (61, 64), {
        "INFECT_MOVE": Move("Status", infection=3),
        "LASH_MOVE": Move("Attack", damage=4, hits=4),
    }, "INFECT_MOVE", {"INFECT_MOVE": "LASH_MOVE", "LASH_MOVE": "INFECT_MOVE"}, on_death_spawn=("WRIGGLER",) * 4),
    # Spawned stunned (SPAWNED_MOVE does nothing), then its slot's opener (WRIGGLER_SLOT_OPENERS).
    MonsterDef("WRIGGLER", "Wriggler", (17, 21), {
        "SPAWNED_MOVE": Move("Stun"),
        "NASTY_BITE_MOVE": Move("Attack", damage=6),
        "WRIGGLE_MOVE": Move("Buff", strength=2, infection=1),
    }, "SPAWNED_MOVE", {"NASTY_BITE_MOVE": "WRIGGLE_MOVE", "WRIGGLE_MOVE": "NASTY_BITE_MOVE"}),
    # --- Act 1 bosses ---
    MonsterDef("VANTOM", "Vantom", (173, 173), {
        "INK_BLOT_MOVE": Move("Attack", damage=7),
        "INKY_LANCE_MOVE": Move("Attack", damage=6, hits=2),
        "DISMEMBER_MOVE": Move("Attack", damage=26, wound=3),
        "PREPARE_MOVE": Move("Buff", strength=2),
    }, "INK_BLOT_MOVE", {"INK_BLOT_MOVE": "INKY_LANCE_MOVE", "INKY_LANCE_MOVE": "DISMEMBER_MOVE",
                         "DISMEMBER_MOVE": "PREPARE_MOVE", "PREPARE_MOVE": "INK_BLOT_MOVE"}, slippery=8),
    # Phase 1 STAMP (Plow 150 on itself) then PLOW forever. When unblocked damage leaves it at or
    # below its Plow amount, PlowPower strips its Strength and stuns it into phase 2.
    MonsterDef("CEREMONIAL_BEAST", "Ceremonial Beast", (252, 252), {
        "STAMP_MOVE": Move("Buff", plow=150),
        "PLOW_MOVE": Move("Attack", damage=18, strength=2),
        # CreatureCmd.Stun -> Creature.StunInternal builds a fresh "STUNNED" state (its own
        # STUN_MOVE is never used), followed by the given nextMoveId (BEAST_CRY_MOVE).
        "STUNNED": Move("Stun"),
        "BEAST_CRY_MOVE": Move("Debuff", ringing=True),
        "STOMP_MOVE": Move("Attack", damage=15),
        "CRUSH_MOVE": Move("Attack", damage=17, strength=3),
    }, "STAMP_MOVE", {"STAMP_MOVE": "PLOW_MOVE", "PLOW_MOVE": "PLOW_MOVE",
                      "BEAST_CRY_MOVE": "STOMP_MOVE", "STOMP_MOVE": "CRUSH_MOVE", "CRUSH_MOVE": "BEAST_CRY_MOVE"}),
    MonsterDef("KIN_PRIEST", "Kin Priest", (190, 190), {
        "ORB_OF_FRAILTY_MOVE": Move("Attack", damage=8, frail=1),
        "ORB_OF_WEAKNESS_MOVE": Move("Attack", damage=8, weak=1),
        "BEAM_MOVE": Move("Attack", damage=3, hits=3),
        "RITUAL_MOVE": Move("Buff", strength=2),
    }, "ORB_OF_FRAILTY_MOVE", {"ORB_OF_FRAILTY_MOVE": "ORB_OF_WEAKNESS_MOVE", "ORB_OF_WEAKNESS_MOVE": "BEAM_MOVE",
                               "BEAM_MOVE": "RITUAL_MOVE", "RITUAL_MOVE": "ORB_OF_FRAILTY_MOVE"}),
    # MinionPower: not needed to win. TheKinBoss's slot1 follower opens with POWER_DANCE.
    MonsterDef("KIN_FOLLOWER", "Kin Follower", (58, 59), {
        "QUICK_SLASH_MOVE": Move("Attack", damage=5),
        "BOOMERANG_MOVE": Move("Attack", damage=2, hits=2),
        "POWER_DANCE_MOVE": Move("Buff", strength=2),
    }, "QUICK_SLASH_MOVE", {"QUICK_SLASH_MOVE": "BOOMERANG_MOVE", "BOOMERANG_MOVE": "POWER_DANCE_MOVE",
                            "POWER_DANCE_MOVE": "QUICK_SLASH_MOVE"}, minion=True),
    # --- Act 2: the Hive. Ascension 0 values from Models/Monsters.
    MonsterDef("BOWLBUG_EGG", "Bowlbug Egg", (21, 22), {
        "BITE_MOVE": Move("Attack", damage=7, block=7),
    }, "BITE_MOVE", {"BITE_MOVE": "BITE_MOVE"}),
    MonsterDef("BOWLBUG_NECTAR", "Bowlbug Nectar", (35, 38), {
        "THRASH_MOVE": Move("Attack", damage=3),
        "BUFF_MOVE": Move("Buff", strength=15),
        "THRASH2_MOVE": Move("Attack", damage=3),
    }, "THRASH_MOVE", {"THRASH_MOVE": "BUFF_MOVE", "BUFF_MOVE": "THRASH2_MOVE", "THRASH2_MOVE": "THRASH2_MOVE"}),
    # ImbalancedPower: a Headbutt that's fully blocked stuns it (engine: _run_enemy_turn).
    MonsterDef("BOWLBUG_ROCK", "Bowlbug Rock", (45, 48), {
        "HEADBUTT_MOVE": Move("Attack", damage=15),
        "STUNNED": Move("Stun"),
    }, "HEADBUTT_MOVE", {"HEADBUTT_MOVE": "HEADBUTT_MOVE"}, powers=(("ImbalancedPower", 1),)),
    MonsterDef("BOWLBUG_SILK", "Bowlbug Silk", (40, 43), {
        "THRASH_MOVE": Move("Attack", damage=4, hits=2),
        "TOXIC_SPIT_MOVE": Move("Debuff", weak=1),
    }, "TOXIC_SPIT_MOVE", {"THRASH_MOVE": "TOXIC_SPIT_MOVE", "TOXIC_SPIT_MOVE": "THRASH_MOVE"}),
    MonsterDef("CHOMPER", "Chomper", (60, 64), {
        "CLAMP_MOVE": Move("Attack", damage=8, hits=2),
        "SCREECH_MOVE": Move("Status", dazed=3),
    }, "CLAMP_MOVE", {"CLAMP_MOVE": "SCREECH_MOVE", "SCREECH_MOVE": "CLAMP_MOVE"}, artifact=2),
    MonsterDef("EXOSKELETON", "Exoskeleton", (24, 28), {
        "SKITTER_MOVE": Move("Attack", damage=1, hits=3),
        "MANDIBLES_MOVE": Move("Attack", damage=8),
        "ENRAGE_MOVE": Move("Buff", strength=2),
    }, _EXOSKELETON_RAND, {"SKITTER_MOVE": _EXOSKELETON_RAND, "MANDIBLES_MOVE": "ENRAGE_MOVE",
                           "ENRAGE_MOVE": _EXOSKELETON_RAND}, powers=(("HardToKillPower", 9),)),
    MonsterDef("HUNTER_KILLER", "Hunter Killer", (121, 121), {
        "TENDERIZING_GOOP_MOVE": Move("Debuff", effect="tender"),
        "BITE_MOVE": Move("Attack", damage=17),
        "PUNCTURE_MOVE": Move("Attack", damage=7, hits=3),
    }, "TENDERIZING_GOOP_MOVE", {"TENDERIZING_GOOP_MOVE": _HUNTER_RAND, "BITE_MOVE": _HUNTER_RAND,
                                 "PUNCTURE_MOVE": _HUNTER_RAND}),
    MonsterDef("MYTE", "Myte", (61, 67), {
        "TOXIC_MOVE": Move("Status", toxic=2),
        "BITE_MOVE": Move("Attack", damage=13),
        "SUCK_MOVE": Move("Attack", damage=4, strength=2),
    }, "TOXIC_MOVE", {"TOXIC_MOVE": "BITE_MOVE", "BITE_MOVE": "SUCK_MOVE", "SUCK_MOVE": "TOXIC_MOVE"}),
    MonsterDef("SPINY_TOAD", "Spiny Toad", (116, 119), {
        "PROTRUDING_SPIKES_MOVE": Move("Buff", effect="spikes"),
        "SPIKE_EXPLOSION_MOVE": Move("Attack", damage=23, effect="unspike"),
        "TONGUE_LASH_MOVE": Move("Attack", damage=17),
    }, "PROTRUDING_SPIKES_MOVE", {"PROTRUDING_SPIKES_MOVE": "SPIKE_EXPLOSION_MOVE",
                                  "SPIKE_EXPLOSION_MOVE": "TONGUE_LASH_MOVE", "TONGUE_LASH_MOVE": "PROTRUDING_SPIKES_MOVE"}),
    # BurrowedPower: its block doesn't clear; breaking the block stuns it (STUNNED, then BITE_MOVE).
    MonsterDef("TUNNELER", "Tunneler", (87, 87), {
        "BITE_MOVE": Move("Attack", damage=13),
        "BURROW_MOVE": Move("Buff", block=32, effect="burrow"),
        "BELOW_MOVE": Move("Attack", damage=23),
        "STUNNED": Move("Stun"),
    }, "BITE_MOVE", {"BITE_MOVE": "BURROW_MOVE", "BURROW_MOVE": "BELOW_MOVE", "BELOW_MOVE": "BELOW_MOVE"}),
    # The stolen card is in SimCombat.stolen; killing the Hopper returns it, its escape keeps it.
    MonsterDef("THIEVING_HOPPER", "Thieving Hopper", (79, 79), {
        "THIEVERY_MOVE": Move("Attack", damage=17, effect="steal"),
        "FLUTTER_MOVE": Move("Buff", effect="flutter"),
        "HAT_TRICK_MOVE": Move("Attack", damage=21),
        "NAB_MOVE": Move("Attack", damage=14),
        "ESCAPE_MOVE": Move("Escape", effect="escape"),
        "STUNNED": Move("Stun"),
    }, "THIEVERY_MOVE", {"THIEVERY_MOVE": "FLUTTER_MOVE", "FLUTTER_MOVE": "HAT_TRICK_MOVE", "HAT_TRICK_MOVE": "NAB_MOVE",
                         "NAB_MOVE": "ESCAPE_MOVE", "ESCAPE_MOVE": "ESCAPE_MOVE"}, powers=(("EscapeArtistPower", 5),)),
    MonsterDef("LOUSE_PROGENITOR", "Louse Progenitor", (134, 136), {
        "WEB_CANNON_MOVE": Move("Attack", damage=9, frail=2),
        "CURL_AND_GROW_MOVE": Move("Defend", block=14, strength=5),
        "POUNCE_MOVE": Move("Attack", damage=14),
    }, "WEB_CANNON_MOVE", {"WEB_CANNON_MOVE": "CURL_AND_GROW_MOVE", "CURL_AND_GROW_MOVE": "POUNCE_MOVE",
                           "POUNCE_MOVE": "WEB_CANNON_MOVE"}, powers=(("CurlUpPower", 14),)),
    # After Tenderizer: Lay Eggs while at most 3 of its side are alive, else Nutritional Paste (_next_move).
    MonsterDef("OVICOPTER", "Ovicopter", (124, 130), {
        "LAY_EGGS_MOVE": Move("Summon", effect="lay_eggs"),
        "SMASH_MOVE": Move("Attack", damage=16),
        "TENDERIZER_MOVE": Move("Attack", damage=7, vulnerable=2),
        "NUTRITIONAL_PASTE_MOVE": Move("Buff", strength=3),
    }, "LAY_EGGS_MOVE", {"LAY_EGGS_MOVE": "SMASH_MOVE", "SMASH_MOVE": "TENDERIZER_MOVE",
                         "TENDERIZER_MOVE": "SUMMON_BRANCH_STATE", "NUTRITIONAL_PASTE_MOVE": "SMASH_MOVE"}),
    MonsterDef("TOUGH_EGG", "Tough Egg", (14, 18), {
        "HATCH_MOVE": Move("Summon", effect="hatch"),
        "NIBBLE_MOVE": Move("Attack", damage=4),
    }, "HATCH_MOVE", {"HATCH_MOVE": "NIBBLE_MOVE", "NIBBLE_MOVE": "NIBBLE_MOVE"}, minion=True),
    # PlatingPower + SlumberPower: asleep until 3 turns pass or 3 hits land (_slumber).
    MonsterDef("SLUMBERING_BEETLE", "Slumbering Beetle", (86, 86), {
        "SNORE_MOVE": Move("Sleep"),
        "ROLL_OUT_MOVE": Move("Attack", damage=16, strength=2),
        "STUNNED": Move("Stun"),
    }, "SNORE_MOVE", {"SNORE_MOVE": "SNORE_MOVE", "ROLL_OUT_MOVE": "ROLL_OUT_MOVE"},
        powers=(("PlatingPower", 15), ("SlumberPower", 3))),
    MonsterDef("THE_OBSCURA", "The Obscura", (123, 123), {
        "ILLUSION_MOVE": Move("Summon", summon="PARAFRIGHT"),
        "PIERCING_GAZE_MOVE": Move("Attack", damage=10),
        "SAIL_MOVE": Move("Buff", effect="wail"),
        "HARDENING_STRIKE_MOVE": Move("Attack", damage=6, block=6),
    }, "ILLUSION_MOVE", {"ILLUSION_MOVE": _OBSCURA_RAND, "PIERCING_GAZE_MOVE": _OBSCURA_RAND, "SAIL_MOVE": _OBSCURA_RAND,
                         "HARDENING_STRIKE_MOVE": _OBSCURA_RAND}),
    MonsterDef("PARAFRIGHT", "Parafright", (21, 21), {
        "SLAM_MOVE": Move("Attack", damage=16),
        "REVIVE_MOVE": Move("Heal", revive=True),
    }, "SLAM_MOVE", {"SLAM_MOVE": "SLAM_MOVE", "REVIVE_MOVE": "SLAM_MOVE"}, illusion=True),
    # --- Act 2 elites ---
    MonsterDef("ENTOMANCER", "Entomancer", (145, 145), {
        "PHEROMONE_SPIT_MOVE": Move("Buff", effect="pheromone"),
        "BEES_MOVE": Move("Attack", damage=3, hits=7),
        "SPEAR_MOVE": Move("Attack", damage=18),
    }, "BEES_MOVE", {"BEES_MOVE": "SPEAR_MOVE", "SPEAR_MOVE": "PHEROMONE_SPIT_MOVE", "PHEROMONE_SPIT_MOVE": "BEES_MOVE"},
        powers=(("PersonalHivePower", 1),)),
    MonsterDef("INFESTED_PRISM", "Infested Prism", (161, 161), {
        "JAB_MOVE": Move("Attack", damage=15),
        "RADIATE_MOVE": Move("Attack", damage=11, block=11),
        "WHIRLWIND_MOVE": Move("Attack", damage=5, hits=3),
        "PULSATE_MOVE": Move("Attack", damage=8, block=20, effect="spark"),
    }, "JAB_MOVE", {"JAB_MOVE": "RADIATE_MOVE", "RADIATE_MOVE": "WHIRLWIND_MOVE", "WHIRLWIND_MOVE": "PULSATE_MOVE",
                    "PULSATE_MOVE": "JAB_MOVE"}, powers=(("VitalSparkPower", 2),)),
    *[MonsterDef(f"DECIMILLIPEDE_SEGMENT_{part}", "Decimillipede Segment", (40, 46), {
        "WRITHE_MOVE": Move("Attack", damage=5, hits=2),
        "BULK_MOVE": Move("Attack", damage=6, strength=2),
        "CONSTRICT_MOVE": Move("Attack", damage=8, weak=1),
        "DEAD_MOVE": Move("Sleep"),
        "REATTACH_MOVE": Move("Heal", effect="reattach"),
    }, "WRITHE_MOVE", {"CONSTRICT_MOVE": "BULK_MOVE", "BULK_MOVE": "WRITHE_MOVE", "WRITHE_MOVE": "CONSTRICT_MOVE",
                       "DEAD_MOVE": "REATTACH_MOVE", "REATTACH_MOVE": _SEGMENT_RAND},
        powers=(("ReattachPower", 25),), reattach=True) for part in ("FRONT", "MIDDLE", "BACK")],
    # --- Act 2 bosses ---
    MonsterDef("CRUSHER", "Crusher", (209, 209), {
        "THRASH_MOVE": Move("Attack", damage=12),
        "ENLARGING_STRIKE_MOVE": Move("Attack", damage=4),
        "BUG_STING_MOVE": Move("Attack", damage=6, hits=2, weak=2, frail=2),
        "ADAPT_MOVE": Move("Buff", strength=2),
        "GUARDED_STRIKE_MOVE": Move("Attack", damage=12, block=18),
    }, "THRASH_MOVE", {"THRASH_MOVE": "ENLARGING_STRIKE_MOVE", "ENLARGING_STRIKE_MOVE": "BUG_STING_MOVE",
                       "BUG_STING_MOVE": "ADAPT_MOVE", "ADAPT_MOVE": "GUARDED_STRIKE_MOVE", "GUARDED_STRIKE_MOVE": "THRASH_MOVE"},
        powers=(("BackAttackLeftPower", 1), ("CrabRagePower", 1))),
    MonsterDef("ROCKET", "Rocket", (199, 199), {
        "TARGETING_RETICLE_MOVE": Move("Attack", damage=3),
        "PRECISION_BEAM_MOVE": Move("Attack", damage=18),
        "CHARGE_UP_MOVE": Move("Buff", strength=2),
        "LASER_MOVE": Move("Attack", damage=31),
        "RECHARGE_MOVE": Move("Sleep"),
    }, "TARGETING_RETICLE_MOVE", {"TARGETING_RETICLE_MOVE": "PRECISION_BEAM_MOVE", "PRECISION_BEAM_MOVE": "CHARGE_UP_MOVE",
                                  "CHARGE_UP_MOVE": "LASER_MOVE", "LASER_MOVE": "RECHARGE_MOVE", "RECHARGE_MOVE": "TARGETING_RETICLE_MOVE"},
        powers=(("BackAttackRightPower", 1), ("CrabRagePower", 1))),
    MonsterDef("KNOWLEDGE_DEMON", "Knowledge Demon", (379, 379), {
        "CURSE_OF_KNOWLEDGE_MOVE": Move("Debuff", effect="curse"),
        "SLAP_MOVE": Move("Attack", damage=17),
        "KNOWLEDGE_OVERWHELMING_MOVE": Move("Attack", damage=8, hits=3),
        "PONDER_MOVE": Move("Attack", damage=11, strength=2, effect="ponder"),
    }, "CURSE_OF_KNOWLEDGE_MOVE", {"CURSE_OF_KNOWLEDGE_MOVE": "SLAP_MOVE", "SLAP_MOVE": "KNOWLEDGE_OVERWHELMING_MOVE",
                                   "KNOWLEDGE_OVERWHELMING_MOVE": "PONDER_MOVE", "PONDER_MOVE": "CURSE_BRANCH"}),
    MonsterDef("THE_INSATIABLE", "The Insatiable", (321, 321), {
        "LIQUIFY_GROUND_MOVE": Move("Buff", effect="liquify"),
        "THRASH_MOVE": Move("Attack", damage=8, hits=2),
        "THRASH_MOVE_2": Move("Attack", damage=8, hits=2),
        "LUNGING_BITE_MOVE": Move("Attack", damage=28),
        "SALIVATE_MOVE": Move("Buff", strength=2),
    }, "LIQUIFY_GROUND_MOVE", {"LIQUIFY_GROUND_MOVE": "THRASH_MOVE", "THRASH_MOVE": "LUNGING_BITE_MOVE",
                               "LUNGING_BITE_MOVE": "SALIVATE_MOVE", "SALIVATE_MOVE": "THRASH_MOVE_2", "THRASH_MOVE_2": "THRASH_MOVE"}),
]}
SEGMENT_STARTS = ("WRITHE_MOVE", "BULK_MOVE", "CONSTRICT_MOVE")
RUBY_RAIDERS = ("AXE_RUBY_RAIDER", "ASSASSIN_RUBY_RAIDER", "BRUTE_RUBY_RAIDER", "CROSSBOW_RUBY_RAIDER", "TRACKER_RUBY_RAIDER")


def hive_roster(encounter: str, rng: random.Random) -> list[str]:
    """Act 2's rosters, apart from encounter_roster because its dict rolls every entry: adding to it would move
    the RNG of every Act 1 fight."""
    if encounter == "BOWLBUGS_WEAK":
        return ["BOWLBUG_ROCK", rng.choice(["BOWLBUG_EGG", "BOWLBUG_NECTAR"])]
    if encounter == "BOWLBUGS_NORMAL":
        return ["BOWLBUG_ROCK", *rng.sample(["BOWLBUG_EGG", "BOWLBUG_SILK", "BOWLBUG_NECTAR"], 2)]
    if encounter == "DECIMILLIPEDE_ELITE":  # the segments open on consecutive moves of Writhe, Bulk, Constrict
        start = rng.randrange(3)
        return [f"DECIMILLIPEDE_SEGMENT_{part}:{SEGMENT_STARTS[(start + i) % 3]}" for i, part in enumerate(("FRONT", "MIDDLE", "BACK"))]
    return {
        "CHOMPERS_NORMAL": ["CHOMPER", "CHOMPER:SCREECH_MOVE"],
        "EXOSKELETONS_WEAK": ["EXOSKELETON:SKITTER_MOVE", "EXOSKELETON:MANDIBLES_MOVE", "EXOSKELETON:ENRAGE_MOVE"],
        "EXOSKELETONS_NORMAL": ["EXOSKELETON:SKITTER_MOVE", "EXOSKELETON:MANDIBLES_MOVE", "EXOSKELETON:ENRAGE_MOVE", "EXOSKELETON"],
        "HUNTER_KILLER_NORMAL": ["HUNTER_KILLER"],
        "LOUSE_PROGENITOR_NORMAL": ["LOUSE_PROGENITOR"],
        "MYTES_NORMAL": ["MYTE:TOXIC_MOVE", "MYTE:SUCK_MOVE"],
        "OVICOPTER_NORMAL": ["OVICOPTER"],
        "SLUMBERING_BEETLE_NORMAL": ["BOWLBUG_ROCK", "BOWLBUG_SILK", "SLUMBERING_BEETLE"],
        "SPINY_TOAD_NORMAL": ["SPINY_TOAD"],
        "THE_OBSCURA_NORMAL": ["THE_OBSCURA"],
        "THIEVING_HOPPER_WEAK": ["THIEVING_HOPPER"],
        "TUNNELER_WEAK": ["TUNNELER"],
        "ENTOMANCER_ELITE": ["ENTOMANCER"],
        "INFESTED_PRISMS_ELITE": ["INFESTED_PRISM"],
        "KAISER_CRAB_BOSS": ["CRUSHER", "ROCKET"],
        "KNOWLEDGE_DEMON_BOSS": ["KNOWLEDGE_DEMON"],
        "THE_INSATIABLE_BOSS": ["THE_INSATIABLE"],
    }[encounter]


def encounter_roster(encounter: str, rng: random.Random) -> list[str]:
    """Monster ids in slot order; "ID:MOVE" overrides the opening move."""
    if encounter in HIVE_ENCOUNTERS:
        return hive_roster(encounter, rng)
    small = rng.sample(["LEAF_SLIME_S", "TWIG_SLIME_S"], 2)
    if encounter == "SLIMES_WEAK":  # SlimesWeak.cs: small, medium, the *other* small
        return [small[0], rng.choice(["LEAF_SLIME_M", "TWIG_SLIME_M"]), small[1]]
    rosters = {
        "NIBBITS_WEAK": ["NIBBIT"],
        "SHRINKER_BEETLE_WEAK": ["SHRINKER_BEETLE"],
        "FUZZY_WURM_CRAWLER_WEAK": ["FUZZY_WURM_CRAWLER"],
        # NibbitsNormal.cs: front opens SLICE, back opens HISS (Nibbit's not-alone branch).
        "NIBBITS_NORMAL": ["NIBBIT:SLICE_MOVE", "NIBBIT:HISS_MOVE"],
        "SLIMES_NORMAL": ["TWIG_SLIME_M", "LEAF_SLIME_M", *small],
        "OVERGROWTH_CRAWLERS": ["SHRINKER_BEETLE", "FUZZY_WURM_CRAWLER"],
        "MAWLER_NORMAL": ["MAWLER"],
        "FLYCONID_NORMAL": [rng.choice(["LEAF_SLIME_M", "TWIG_SLIME_M"]), "FLYCONID"],
        "RUBY_RAIDERS_NORMAL": rng.sample(RUBY_RAIDERS, 3),
        "INKLETS_NORMAL": ["INKLET", "INKLET:WHIRLWIND_MOVE", "INKLET"],
        "CUBEX_CONSTRUCT_NORMAL": ["CUBEX_CONSTRUCT"],
        "VINE_SHAMBLER_NORMAL": ["VINE_SHAMBLER"],
        "FOGMOG_NORMAL": ["FOGMOG"],
        "SNAPPING_JAXFRUIT_NORMAL": ["SNAPPING_JAXFRUIT", "FLYCONID"],
        # SlitheringStranglerNormal.cs: a Jaxfruit, a medium slime, or two small slimes (with
        # replacement), then the Strangler.
        "BYGONE_EFFIGY_ELITE": ["BYGONE_EFFIGY"],
        "BYRDONIS_ELITE": ["BYRDONIS"],
        "PHROG_PARASITE_ELITE": ["PHROG_PARASITE"],
        "VANTOM_BOSS": ["VANTOM"],
        "CEREMONIAL_BEAST_BOSS": ["CEREMONIAL_BEAST"],
        "THE_KIN_BOSS": ["KIN_FOLLOWER:POWER_DANCE_MOVE", "KIN_FOLLOWER", "KIN_PRIEST"],
        "SLITHERING_STRANGLER_NORMAL": rng.choice([
            ["SNAPPING_JAXFRUIT"], [rng.choice(["LEAF_SLIME_M", "TWIG_SLIME_M"])],
            [rng.choice(["LEAF_SLIME_S", "TWIG_SLIME_S"]) for _ in range(2)]]) + ["SLITHERING_STRANGLER"],
    }
    if encounter not in rosters:
        raise ValueError(f"sim does not model encounter {encounter!r} (only {ENCOUNTERS + HIVE_ENCOUNTERS})")
    return rosters[encounter]


ENCOUNTERS = ("NIBBITS_WEAK", "SLIMES_WEAK", "SHRINKER_BEETLE_WEAK", "FUZZY_WURM_CRAWLER_WEAK",
              "NIBBITS_NORMAL", "SLIMES_NORMAL", "OVERGROWTH_CRAWLERS",
              "MAWLER_NORMAL", "FLYCONID_NORMAL", "RUBY_RAIDERS_NORMAL",
              "INKLETS_NORMAL", "CUBEX_CONSTRUCT_NORMAL", "VINE_SHAMBLER_NORMAL", "FOGMOG_NORMAL",
              "SNAPPING_JAXFRUIT_NORMAL", "SLITHERING_STRANGLER_NORMAL",
              "BYGONE_EFFIGY_ELITE", "BYRDONIS_ELITE", "PHROG_PARASITE_ELITE",
              "VANTOM_BOSS", "CEREMONIAL_BEAST_BOSS", "THE_KIN_BOSS")
HIVE_WEAK = ("BOWLBUGS_WEAK", "EXOSKELETONS_WEAK", "THIEVING_HOPPER_WEAK", "TUNNELER_WEAK")
HIVE_NORMALS = ("BOWLBUGS_NORMAL", "CHOMPERS_NORMAL", "EXOSKELETONS_NORMAL", "HUNTER_KILLER_NORMAL", "LOUSE_PROGENITOR_NORMAL",
                "MYTES_NORMAL", "OVICOPTER_NORMAL", "SLUMBERING_BEETLE_NORMAL", "SPINY_TOAD_NORMAL", "THE_OBSCURA_NORMAL")
HIVE_ELITES = ("DECIMILLIPEDE_ELITE", "ENTOMANCER_ELITE", "INFESTED_PRISMS_ELITE")
HIVE_BOSSES = ("KAISER_CRAB_BOSS", "KNOWLEDGE_DEMON_BOSS", "THE_INSATIABLE_BOSS")
HIVE_ENCOUNTERS = HIVE_WEAK + HIVE_NORMALS + HIVE_ELITES + HIVE_BOSSES
HIVE_MONSTERS = ("BOWLBUG_EGG", "BOWLBUG_NECTAR", "BOWLBUG_ROCK", "BOWLBUG_SILK", "CHOMPER", "EXOSKELETON", "HUNTER_KILLER", "MYTE",
                 "SPINY_TOAD", "TUNNELER", "THIEVING_HOPPER", "LOUSE_PROGENITOR", "OVICOPTER", "TOUGH_EGG", "SLUMBERING_BEETLE",
                 "THE_OBSCURA", "PARAFRIGHT", "ENTOMANCER", "INFESTED_PRISM", "DECIMILLIPEDE_SEGMENT_FRONT", "DECIMILLIPEDE_SEGMENT_MIDDLE",
                 "DECIMILLIPEDE_SEGMENT_BACK", "CRUSHER", "ROCKET", "KNOWLEDGE_DEMON", "THE_INSATIABLE")


def branch_weights(spec: str | Branch, log: list[str]) -> dict[str, float]:
    """Nonzero-weight moves a branch can pick next, in branch order (RandomBranchState.GetStateWeight)."""
    if isinstance(spec, str):
        return {spec: 1.0}

    def weight(m: str, n: int, cooldown: int = 0, w: float = 1.0) -> float:
        if cooldown and m in log[-cooldown:]:
            return 0.0
        if n == ONCE:
            return 0.0 if m in log else w
        return 0.0 if len(log) >= n and all(x == m for x in log[-n:]) else w

    weights = {b[0]: weight(*b) for b in spec}
    # GetNextState: with total weight 0, NextFloat(0) = 0 and the loop returns the first branch.
    return {m: w for m, w in weights.items() if w} or {spec[0][0]: 1.0}


def legal_moves(spec: str | Branch, log: list[str]) -> list[str]:
    return list(branch_weights(spec, log))


def pick_move(spec: str | Branch, log: list[str], rng: random.Random) -> str:
    weights = branch_weights(spec, log)
    return rng.choices(list(weights), list(weights.values()))[0]


def player_attack_damage(base: int, target_vulnerable: bool, shrunk: bool, weak: bool = False,
                         slow_cards: int | None = None, cruelty: int = 0, mult: int = 1, div: int = 1) -> int:
    """floor(base * (1.5 + cruelty%)[target Vulnerable] * 0.7[Shrink] * 0.75[Weak] * (1 + 0.1n)[target
    Slow, n cards played this turn]) in exact integer math (Hook.ModifyDamage multiplies decimals, then
    truncates). Cruelty raises the Vulnerable multiplier by its amount in percent (CrueltyPower).
    mult: Pen Nib's x2, applied with the other multipliers."""
    num = base * ((150 + cruelty) if target_vulnerable else 100) * (7 if shrunk else 10) * (3 if weak else 4)
    num *= (10 + (slow_cards or 0)) * mult
    return max(0, num // (100 * 10 * 4 * 10 * div))


@dataclass
class _Enemy:
    defn: MonsterDef
    hp: int
    max_hp: int
    move: str  # upcoming move (its intent is what the player sees)
    block: int = 0
    strength: int = 0
    vulnerable: int = 0
    weak: int = 0  # its attacks x0.75 (Uppercut)
    mangle: int = 0  # ManglePower: Strength lost until the end of its next turn
    artifact: int = 0
    slippery: int = 0
    plow: int = 0
    next_override: str | None = None  # CreatureCmd.Stun's nextMoveId: the move after the current one
    pw: dict[str, int] = field(default_factory=dict)  # MonsterDef.powers and what they've become
    log: list[str] = field(default_factory=list)  # performed moves, for RandomBranchState repeat rules

    @property
    def is_alive(self) -> bool:
        return self.hp > 0

    @property
    def in_combat(self) -> bool:
        """Dead illusions stay in combat (IllusionPower.ShouldCreatureBeRemovedFromCombatAfterDeath)."""
        return self.is_alive or self.defn.illusion or (self.defn.reattach and "reviving" in self.pw)

    @classmethod
    def spawn(cls, d: MonsterDef, rng: random.Random, first: str = "") -> "_Enemy":
        hp = rng.randint(*d.hp)
        return cls(d, hp, hp, first or pick_move(d.first, [], rng), block=d.start_block,
                   artifact=d.artifact, slippery=d.slippery, pw=dict(d.powers))


SINGLE_POWERS = {"BarricadePower", "NoDrawPower", "NoEnergyGainPower", "HellraiserPower"}  # PowerStackType.Single
# Removed at the end of the player's turn (AfterSideTurnEnd on their side).
TURN_POWERS = ("RagePower", "NoDrawPower", "NoEnergyGainPower", "OneTwoPunchPower")
# Combat history the live /combat doesn't expose; sim.validate carries these over between steps.
# What each Hive conditional branch can lead to (engine: _next_move), for sim.validate.
BRANCHES = {"SUMMON_BRANCH_STATE": ["LAY_EGGS_MOVE", "NUTRITIONAL_PASTE_MOVE"], "CURSE_BRANCH": ["CURSE_OF_KNOWLEDGE_MOVE", "SLAP_MOVE"]}
# Powers on Hive monsters, kept in _Enemy.pw. sim.validate loads them from the live /combat.
ENEMY_PW = ("HardToKillPower", "ThornsPower", "ImbalancedPower", "BurrowedPower", "CurlUpPower", "PlatingPower", "SlumberPower",
            "PersonalHivePower", "VitalSparkPower", "ReattachPower", "EscapeArtistPower", "FlutterPower", "SwipePower", "HatchPower",
            "CrabRagePower", "BackAttackLeftPower", "BackAttackRightPower", "SandpitPower")
HISTORY_FIELDS = ("tender_plays", "facing", "exhausted_this_turn", "hp_lost_this_turn", "attack_plays", "block_plays", "free_cards",
                  "hp_loss_events", "bonus_damage", "crimson_self", "inferno_self")


@dataclass
class SimCombat:
    player_hp: int = PLAYER_MAX_HP
    player_max_hp: int = PLAYER_MAX_HP
    player_block: int = 0
    shrunk: bool = False
    vulnerable: int = 0  # player's: monster attacks x1.5
    frail: int = 0  # player's: card block x0.75
    tangled: int = 0  # player's: Attack cards cost +tangled; removed at the end of their turn
    constrict: int = 0  # player's: takes this much (blockable) damage at the end of their turn
    strength: int = 0  # player's, added to every attack hit
    temp_strength: int = 0  # the part of `strength` that goes away at the end of their turn
    dexterity: int = 0  # player's, added to card block before Frail (DexterityPower)
    temp_dexterity: int = 0  # the part of `dexterity` that goes away at the end of their turn (SpeedPotionPower)
    potions: list = field(default_factory=lambda: [None] * POTION_SLOTS)  # kept across fights; None = empty
    weak: int = 0  # player's: their attacks x0.75
    relics: set = field(default_factory=set)  # ids held (sim/relics.py); unmodeled ids are never checked
    # Carried across fights; the same dict object as Run.relic_state (pen_nib, happy_flower, tea_set ...).
    relic_state: dict = field(default_factory=dict)
    rt: dict = field(default_factory=dict)  # per-fight relic state, replaced in fight()
    ringing: bool = False  # player's: only one card play this turn; removed at the end of it
    cards_played: int = 0  # this player turn (SlowPower's counter; RingingPower's check)
    attacks_done: int = 0  # Attacks / Skills / Powers finished this turn (AfterCardPlayed)
    skills_done: int = 0
    powers_done: int = 0
    cards_done: int = 0  # cards finished since the last turn start (includes autoplays after the turn ends)
    attacks_last: int = 0  # Attacks played last turn, stored at AfterSideTurnEnd (Art of War)
    cards_last: int = 0  # cards_done at this turn's start (Pocketwatch: BeforeSideTurnStart)
    energy: int = 0
    round: int = 1
    in_combat: bool = False
    is_play_phase: bool = False
    won: bool | None = None
    hand: list[str] = field(default_factory=list)
    draw_pile: list[str] = field(default_factory=list)
    discard_pile: list[str] = field(default_factory=list)
    exhaust_pile: list[str] = field(default_factory=list)
    enemies: list[_Enemy] = field(default_factory=list)
    rng: random.Random = field(default_factory=random.Random)
    # The player's other powers by class name (as /combat names them), e.g. {"FeelNoPainPower": 3}.
    pw: dict[str, int] = field(default_factory=dict)
    crimson_self: int = 0  # CrimsonMantlePower / InfernoPower self-damage: +1 per copy played
    inferno_self: int = 0
    side: str = "Player"  # CombatState.CurrentSide: Rupture/Inferno and "this turn" checks need it
    # History ("this turn" = this round's player side, CombatHistoryEntry.HappenedThisTurn).
    exhausted_this_turn: bool = False  # Evil Eye, Forgotten Ritual
    hp_lost_this_turn: bool = False  # Spite
    tender_plays: int = 0  # TenderPower: Strength and Dexterity lost this turn, returned at its end
    facing: str = "Right"  # SurroundedPower: x1.5 from the arm behind the player
    stolen: list = field(default_factory=list)  # Thieving Hopper: cards gone from the deck unless it's killed
    attack_plays: int = 0  # this turn, per play (One-Two Punch counts twice): Stomp, Juggling
    block_plays: list[int] = field(default_factory=list)  # card plays that gained block this turn (Unmovable)
    free_cards: list[str] = field(default_factory=list)  # free this turn (Infernal Blade's card)
    hp_loss_events: int = 0  # unblocked hits/losses this combat (Tear Asunder)
    lamp_hit: bool = False  # a blockable hit got through this combat (Lava Lamp's TookDamageThisCombat)
    # ponytail: per card id, not per copy (Rampage/Thrash grow per instance; two copies share here).
    bonus_damage: dict[str, int] = field(default_factory=dict)
    shuffles: int = 0  # discard -> draw reshuffles (sim.validate: draws after one are random)
    _play_id: int = 0  # the card play being resolved; restored after a nested autoplay
    _play_seq: int = 0  # last id handed out, so nested plays never reuse one
    _effect_depth: int = 0  # CombatManager's card/potion effect depth (Unceasing Top's empty-hand check)
    _post_play: bool = False  # AutoPostPlay: Stampede / Howl autoplays at the end of the turn
    _rupture: int | None = None  # Strength owed for HP lost to the card being played (RupturePower)
    _ethereal_exhausts: int = 0  # Dark Embrace draws for these after the hand flush
    # A card waiting on the player's choice: {"kind": "hand" | "discard", "source": card_id}.
    pending_choice: dict | None = None
    choice_log: list[tuple[str, str, tuple[str, ...]]] = field(default_factory=list)  # (source, picked, options), paused prompts only
    _pausable: bool = False  # the play being resolved may stop at a prompt (not an autoplay)
    _paused: tuple | None = None  # what the rest of a paused play needs, see _run_plays

    @property
    def max_energy(self) -> int:
        return PLAYER_MAX_ENERGY + self.pw.get("PyrePower", 0) + ("BREAD" in self.relics and self.round > 1)

    def heal(self, amount: int) -> None:
        self.player_hp = min(self.player_max_hp, self.player_hp + amount)
        self._red_skull()

    def _red_skull(self) -> None:
        """RedSkull.AfterCurrentHpChanged: +3 Strength while hp <= half of max, taken back above it."""
        if "RED_SKULL" in self.relics and self.in_combat:
            low = 2 * self.player_hp <= self.player_max_hp
            if low != bool(self.rt.get("skull")):
                self.rt["skull"] = low
                self._gain_strength(3 if low else -3)

    def _is_ethereal(self, card_id: str) -> bool:
        return CARDS[card_id].ethereal or ("GHOST_SEED" in self.relics and base_id(card_id) in ("STRIKE_IRONCLAD", "DEFEND_IRONCLAD"))

    def fight(self, encounter: str, deck: list[str] | None = None) -> None:
        # A play abandoned at a prompt never finishes, so its depth and Rupture count go too.
        self.tender_plays, self.facing, self.stolen = 0, "Right", []
        self.pending_choice, self.choice_log, self._paused, self._effect_depth, self._rupture = None, [], None, 0, None
        self.enemies = []
        for entry in encounter_roster(encounter, self.rng):
            model_id, _, first = entry.partition(":")
            self.enemies.append(_Enemy.spawn(MONSTERS[model_id], self.rng, first))
        self.draw_pile = [DeckCard(c) for c in deck or starter_deck()]  # draw_pile[-1] is the top card
        self.rng.shuffle(self.draw_pile)
        self.hand, self.discard_pile, self.exhaust_pile = [], [], []
        self.player_block = 0
        self.shrunk = False
        self.vulnerable = self.frail = self.tangled = self.constrict = 0
        self.strength = self.temp_strength = self.weak = self.cards_played = 0
        self.dexterity = self.temp_dexterity = 0
        self.ringing = False
        self.pw, self.bonus_damage = {}, {}
        self.crimson_self = self.inferno_self = self.hp_loss_events = 0
        self.lamp_hit = False
        self.round = 1
        self.shuffles = 0
        self.in_combat = True
        self.won = None
        self.rt = {}
        self.attacks_done = self.skills_done = self.powers_done = self.attacks_last = self.cards_last = self.cards_done = 0
        R = self.relics
        # AfterRoomEntered, then BeforeCombatStart (CombatRoom.StartCombat).
        elite, boss = encounter.endswith("_ELITE"), encounter.endswith("_BOSS")
        if "GORGET" in R:
            self._apply_power("PlatingPower", 4)
        if "BRONZE_SCALES" in R:
            self._apply_power("ThornsPower", 3)
        if "ODDLY_SMOOTH_STONE" in R:
            self.dexterity += 1
        if "VAJRA" in R:
            self._gain_strength(1)
        if "SLING_OF_COURAGE" in R and elite:
            self._gain_strength(2)
        if "ANCHOR" in R:
            self._gain_block(10)
        if self.relic_state.get("girya"):  # Girya.AfterRoomEntered: Strength = times lifted
            self._gain_strength(self.relic_state["girya"])
        if "STONE_CRACKER" in R:  # upgrades 2 random upgradable draw-pile cards (this fight only)
            ups = [i for i, c in enumerate(self.draw_pile) if c in UPGRADABLE]
            for i in self.rng.sample(ups, min(2, len(ups))):
                self.draw_pile[i] = upgrade(self.draw_pile[i])
        if "PANTOGRAPH" in R and boss:
            self.heal(25)
        if "BELT_BUCKLE" in R and not any(self.potions):
            self.dexterity += 2
        self._red_skull()
        self._start_player_turn()

    # --- cards -----------------------------------------------------------------------------------

    def cost(self, card_id: str) -> int:
        """Energy cost with this turn's modifiers (X-cost cards show 0)."""
        c = CARDS[card_id]
        if c.x_cost or card_id in self.free_cards:
            return 0
        if card_id == "FRANTIC_ESCAPE":
            return c.cost + getattr(card_id, "extra", 0)
        if c.type != "Attack":
            return c.cost
        if self.pw.get("FreeAttackPower"):  # TryModifyEnergyCostInCombatLate: after Tangled
            return 0
        base = max(0, c.cost - self.attack_plays) if base_id(card_id) == "STOMP" else c.cost  # EnergyCost.AddThisTurn
        return base + self.tangled  # TangledPower

    def can_play(self, card_id: str) -> bool:
        c = CARDS[card_id]
        return (c.cost >= 0 or c.x_cost) and self.cost(card_id) <= self.energy and \
            not (self.ringing and self.cards_played)

    def play_card(self, hand_index: int, target_id: int | None = None) -> dict:
        if self.pending_choice:
            return {"error": "choice_pending"}
        if not self.in_combat or not self.is_play_phase:
            return {"error": "not_play_phase"}
        if hand_index < 0 or hand_index >= len(self.hand):
            return {"error": "invalid_card_index", "max": len(self.hand) - 1}
        card_id = self.hand[hand_index]
        card = CARDS[card_id]
        if not self.can_play(card_id):
            return {"error": "card_not_playable", "card": card_id}
        if target_id is None:
            target = next((e for e in self.enemies if e.is_alive), None)
        else:  # combatId = index + 1, see _enemy_dict
            target = self.enemies[target_id - 1] if 0 < target_id <= len(self.enemies) else None
            if target is None or not target.is_alive:
                return {"error": "invalid_target", "targetId": target_id}

            self._face(target)  # SurroundedPower.BeforeCardPlayed
        x = self.energy if card.x_cost else 0
        spent = x if card.x_cost else self.cost(card_id)
        self.energy -= spent
        if card_id in self.free_cards:
            self.free_cards.remove(card_id)
        self.hand.pop(hand_index)
        self._pausable = True
        self._play(card_id, target, x, energy_value=spent)
        self._pausable = False
        self._check_win()
        if self.pending_choice:
            return {"ok": True, "choice": self.pending_choice}
        return {"ok": True, "played": card.title, "index": hand_index}

    def choose_card(self, hand_index: int) -> dict:
        """Answer a pending "hand" or "upgrade" prompt with the card at hand_index (upgrade: an upgradable one)."""
        kind = (self.pending_choice or {}).get("kind")
        if kind not in ("hand", "upgrade") or not 0 <= hand_index < len(self.hand) or \
                (kind == "upgrade" and self.hand[hand_index] not in UPGRADABLE):
            return {"error": "invalid_choice"}
        options = tuple(c for c in self.hand if kind == "hand" or c in UPGRADABLE)
        return self._resume_play(self._take(kind, hand_index), options)

    def choose_discard(self, card_id: str) -> dict:
        """Answer a pending "discard" prompt with a card in the discard pile. The env names base ids: a plain copy
        is taken first, else the upgraded one (ponytail: the policy can't pick the upgraded copy over a plain one)."""
        if card_id not in self.discard_pile:
            card_id += "+"
        if not self.pending_choice or self.pending_choice["kind"] != "discard" or card_id not in self.discard_pile:
            return {"error": "invalid_choice"}
        options = tuple(self.discard_pile)
        self.discard_pile.remove(card_id)
        return self._resume_play(card_id, options)

    def _resume_play(self, picked: str, options: tuple[str, ...]) -> dict:
        """The rest of the play that stopped at the prompt: AfterCardPlayed, further plays, result pile."""
        self.choice_log.append((self.pending_choice["source"], picked, options))
        self.pending_choice = None
        card_id, target, x, force_exhaust, energy_value, plays_left, mine, outer = self._paused
        self._finish_choice(card_id, picked)  # only the card being played pauses, so it's the prompt's source
        self._effect_depth -= 1
        self._paused = None
        self._pausable = True  # One-Two Punch's second play asks again
        if self._after_resolve(CARDS[card_id], mine, outer):
            self._run_plays(card_id, target, x, force_exhaust, energy_value, plays_left)
        self._pausable = False
        self._check_win()
        return {"ok": True, "choice": self.pending_choice}

    def use_potion(self, slot: int, target_id: int | None = None) -> dict:
        """PotionModel.OnUse for the modeled potions; target_id is an enemy combatId (enemy potions only).
        Potion damage and Block Potion's block are Unpowered: block absorbs the damage, but Strength,
        Vulnerable, Weak, Shrink, Dexterity and Frail don't apply (ValuePropExtensions.IsPoweredAttack)."""
        if self.pending_choice:
            return {"error": "choice_pending"}
        if not self.in_combat or not self.is_play_phase:
            return {"error": "not_play_phase"}
        if not 0 <= slot < len(self.potions) or self.potions[slot] not in POTIONS:
            return {"error": "invalid_potion", "slot": slot}
        pid, target = self.potions[slot], None
        if POTIONS[pid] == "enemy":
            target = self.enemies[target_id - 1] if target_id and 0 < target_id <= len(self.enemies) else None
            if target is None or not target.is_alive:
                return {"error": "invalid_target", "targetId": target_id}
        self.potions[slot] = None
        self._effect_depth += 1
        if pid == "BLOCK_POTION":
            self._gain_block(12)
        elif pid == "DEXTERITY_POTION":
            self.dexterity += 2
        elif pid == "SPEED_POTION":
            self.dexterity += 5
            self.temp_dexterity += 5
        elif pid == "ENERGY_POTION":
            self._gain_energy(2)
        elif pid == "STRENGTH_POTION":
            self._gain_strength(2)
        elif pid == "FLEX_POTION":
            self._gain_strength(5)
            self.temp_strength += 5
        elif pid == "SWIFT_POTION":
            self._draw(3)
        elif pid == "FIRE_POTION":
            self._damage_enemy(target, 20)
        elif pid == "EXPLOSIVE_AMPOULE":
            for e in self._hittable():  # HittableEnemies, read once before the hits
                self._damage_enemy(e, 10)
        elif pid == "VULNERABLE_POTION":
            self._debuff(target, "vulnerable", 3, card=False)
        elif pid == "WEAK_POTION":
            self._debuff(target, "weak", 3, card=False)
        elif pid == "BLOOD_POTION":
            self.heal(self.player_max_hp * 20 // 100)  # 20% of max HP, truncated
        self._effect_depth -= 1
        # AfterPotionUsed. ponytail: relic order assumed Reptile Trinket, then Belt Buckle.
        # ponytail: no mid-fight potion gain yet, so "applied" is implied by holding one at the start.
        if "REPTILE_TRINKET" in self.relics and self.in_combat:
            self._gain_strength(3)
            self.temp_strength += 3  # ponytail: Ruined Helmet doubles the gain, not this (TemporaryStrengthPower takes back its own amount)
        if "BELT_BUCKLE" in self.relics and not any(self.potions):
            self.dexterity += 2
        self._check_win()
        self._check_empty_hand()  # after AfterPotionUsed
        return {"ok": True, "used": pid, "slot": slot}

    def _check_win(self) -> None:
        # CombatManager.IsEnding: won once no *primary* enemy (non-minion) is alive.
        if self.in_combat and not any(e.is_alive and not (e.defn.illusion or e.defn.minion) for e in self.enemies):
            self._end_combat(won=True)

    def _play(self, card_id: str, target: _Enemy | None, x: int = 0, force_exhaust: bool = False,
              energy_value: int | None = None) -> None:
        """CardModel.OnPlayWrapper: the card is "in play" (in no pile) until its result pile."""
        card = CARDS[card_id]
        attack = card.type == "Attack"
        plays = 1
        if attack and self.pw.get("OneTwoPunchPower"):  # ModifyCardPlayCount, then Decrement
            plays = 2
            self._decrement("OneTwoPunchPower")
        self._run_plays(card_id, target, x, force_exhaust, energy_value, plays)

    def _run_plays(self, card_id: str, target: _Enemy | None, x: int, force_exhaust: bool, energy_value: int | None,
                   plays: int) -> None:
        card = CARDS[card_id]
        attack = card.type == "Attack"
        for plays_left in range(plays - 1, -1, -1):
            self._play_seq += 1
            mine = self._play_id = self._play_seq
            # BeforeCardPlayed. Intimidating Helmet reads the card's energy value (an autoplay spends 0 but costs its cost).
            if "INTIMIDATING_HELMET" in self.relics and \
                    (x if card.x_cost else self.cost(card_id) if energy_value is None else energy_value) >= 2:
                self._gain_block(4)
                self._check_win()  # Juggernaut
                if not self.in_combat:
                    return
            if attack:
                self._decrement("FreeAttackPower")
                self.attack_plays += 1
                if "PEN_NIB" in self.relics:  # counts every attack play; the 10th is doubled
                    self.relic_state["pen_nib"] = (self.relic_state.get("pen_nib", 0) + 1) % 10
                    if not self.relic_state["pen_nib"]:
                        self.rt["pen_play"] = self._play_id
            outer, self._rupture = self._rupture, 0
            self._effect_depth += 1
            try:
                self._resolve(card_id, target, x)
            finally:
                if not self.pending_choice:  # a paused play is still resolving: _resume_play lowers it
                    self._effect_depth -= 1
            if self.pending_choice:
                self._paused = (card_id, target, x, force_exhaust, energy_value, plays_left, mine, outer)
                return
            if not self._after_resolve(card, mine, outer):
                return
        if card.type != "Power":  # Powers: PileType.None, removed from combat
            if card.exhaust or force_exhaust:
                self._exhaust(card_id)
            else:
                self.discard_pile.append(frantic_escape(getattr(card_id, "extra", 0) + 1) if card_id == "FRANTIC_ESCAPE" else card_id)
        self._check_empty_hand()

    def _after_resolve(self, card, mine: int, outer: int | None) -> bool:
        """AfterCardPlayed for one play. False if the fight is over."""
        attack = card.type == "Attack"
        self._play_id = mine
        owed, self._rupture = self._rupture, outer
        if not self.in_combat:
            return False
        self.cards_played += 1
        self.cards_done += 1
        if attack:
            self.attacks_done += 1
        elif card.type == "Skill":
            self.skills_done += 1
        elif card.type == "Power":
            self.powers_done += 1
        if attack and self.pw.get("RagePower"):
            self._gain_block(self.pw["RagePower"])
        if attack and self.pw.get("JugglingPower") and self.attack_plays == 3:  # 3rd Attack this turn
            for _ in range(self.pw["JugglingPower"]):
                self._add_to_hand(card.id)  # CreateClone
        self._gain_strength(owed)
        if self.rt.pop("curl", None):  # CurlUpPower.AfterCardPlayed
            for e in self._hittable():
                if e.pw.get("CurlUpPower"):
                    e.block += e.pw.pop("CurlUpPower")
        if self.pw.get("TenderPower"):
            self.strength -= 1
            self.dexterity -= 1
            self.tender_plays += 1
        if card.type == "Skill":  # VitalSparkPower: every Skill is Tainted while the Prism lives
            for e in self._hittable():
                if e.pw.get("VitalSparkPower"):
                    self._apply_power("TaintedPower", e.pw["VitalSparkPower"])
        self._after_card_relics(card)
        self._check_win()
        return self.in_combat

    def _check_empty_hand(self) -> None:
        """CombatManager.CheckForEmptyHand -> Unceasing Top: after a card play or potion (autoplays too) that isn't
        nested in another effect, if the hand is empty (not "just became"), in the Play or AutoPostPlay phase."""
        if "UNCEASING_TOP" in self.relics and self.in_combat and not self._effect_depth and not self.hand \
                and (self.is_play_phase or self._post_play):
            self._draw(1)

    def _after_card_relics(self, card) -> None:
        """AfterCardPlayed relics (the counters in attacks_done etc. are already bumped).
        ponytail: relic order assumed as written here, after the powers; the game's is the player's relic list order."""
        R, st, rt = self.relics, self.relic_state, self.rt
        if card.type == "Attack":
            if "NUNCHAKU" in R:
                st["nunchaku"] = (st.get("nunchaku", 0) + 1) % 10
                if not st["nunchaku"]:
                    self._gain_energy(1)
            third = self.attacks_done % 3 == 0
            if "ORNAMENTAL_FAN" in R and third:
                self._gain_block(4)
            if "KUNAI" in R and third:
                self.dexterity += 1
            if "SHURIKEN" in R and third:
                self._gain_strength(1)
            if "KUSARIGAMA" in R and third and self._hittable():
                self._damage_enemy(self.rng.choice(self._hittable()), 6)
                self._check_win()
        elif card.type == "Skill":
            if "TUNING_FORK" in R:
                st["tuning_fork"] = st.get("tuning_fork", 0) + 1
                if st["tuning_fork"] >= 10:
                    self._gain_block(7)
                    st["tuning_fork"] -= 10
            if "LETTER_OPENER" in R and self.skills_done % 3 == 0:
                self._damage_all(5)
        elif card.type == "Power":
            if "PERMAFROST" in R and not rt.get("permafrost"):
                rt["permafrost"] = 1
                self._gain_block(7)
            if "GAME_PIECE" in R and self.in_combat:
                self._draw(1)
            if "MUMMIFIED_HAND" in R and self.hand:
                # Source fallback order: costed (base and now) -> costed now -> costed base -> any.
                tiers = [[c for c in self.hand if CARDS[c].cost > 0 and self.cost(c) > 0],
                         [c for c in self.hand if self.cost(c) > 0],
                         [c for c in self.hand if CARDS[c].cost > 0], self.hand]
                pick = next(t for t in tiers if t)
                self.free_cards.append(self.rng.choice(pick))  # ponytail: free per card id, not per copy
        if not self.in_combat:
            return
        if "RAINBOW_RING" in R and rt.get("rainbow") != self.round and \
                self.attacks_done and self.skills_done and self.powers_done:
            rt["rainbow"] = self.round  # once a turn
            self._gain_strength(1)
            self.dexterity += 1

    def _autoplay(self, card_id: str, force_exhaust: bool = False) -> None:
        """CardCmd.AutoPlay of a card already taken out of its pile: free, random target, X = energy."""
        if self._ending():  # CardCmd.AutoPlay returns at once once the fight is over or ending
            return
        c = CARDS[card_id]
        hittable = self._hittable()
        if (c.cost < 0 and not c.x_cost) or (self.ringing and self.cards_played) or \
                (c.target_type == "AnyEnemy" and not hittable):
            # MoveToResultPileWithoutPlaying. ponytail: an Unplayable card a forced exhaust (Havoc)
            # autoplays is assumed to land in the exhaust pile like the forced-exhaust play would.
            if c.exhaust or force_exhaust:
                self._exhaust(card_id)
            elif c.type != "Power":
                self.discard_pile.append(card_id)
            return
        target = self.rng.choice(hittable) if c.target_type == "AnyEnemy" else None
        outer, pausable = self._play_id, self._pausable
        self._pausable = False
        self._play(card_id, target, self.energy, force_exhaust)
        self._play_id = outer  # Pen Nib / Vambrace / Lamp keep the outer card
        self._pausable = pausable

    def _resolve(self, card_id: str, target: _Enemy | None, x: int) -> None:
        """A card's OnPlay: the generic fields in the order documented in cards.py, or _special."""
        card = CARDS[card_id]
        if card.x_cost and "CHEMICAL_X" in self.relics:  # ModifyXValue
            x += 2
        if card.special:
            self._special(card_id, target, x)
        else:
            self._generic(card, target, x)
        if self.in_combat:
            for name, amount in card.powers:
                self._apply_power(name, amount)

    def _generic(self, card, target: _Enemy | None, x: int) -> None:
        if card.hp_loss:
            self._lose_hp(card.hp_loss, from_card=True)
            if not self.in_combat:
                return
        if card.block:
            self._gain_block(card.block, card=True)
        if card.damage or card.damage_from_block:
            base = self.player_block if card.damage_from_block else card.damage
            if card.damage_per_strike:  # PlayerCombatState.AllCards: every pile plus the card in play
                piles = self.hand + self.draw_pile + self.discard_pile + self.exhaust_pile
                base += card.damage_per_strike * (sum(CARDS[c].strike for c in piles) + card.strike)
            self._hit(card, target, base, x if card.x_cost else card.hits)
        if card.weak or card.vulnerable:
            for t in self._hittable() if card.target_type == "AllEnemies" else [target] if target else []:
                if t.is_alive and card.weak:
                    self._debuff(t, "weak", card.weak)
                if t.is_alive and card.vulnerable:
                    self._debuff(t, "vulnerable", card.vulnerable)
        if card.double_vulnerable and target and target.is_alive and target.vulnerable:
            self._debuff(target, "vulnerable", target.vulnerable)
        self._gain_strength(card.temp_strength)
        self.temp_strength += card.temp_strength
        if card.draw:
            self._draw(card.draw)
        if card.energy:
            self._gain_energy(card.energy)
        if card.heal:
            self.heal(card.heal)
        if card.id == "TRUE_GRIT+":  # IsUpgraded: the player chooses (CardSelectCmd.FromHand), the card's last effect
            self._ask("hand", card.id)
        elif card.exhaust_random and self.hand:  # Rng.CombatCardSelection.NextItem(hand)
            self._exhaust(self.hand.pop(self.rng.randrange(len(self.hand))))
        if card.copy_to_discard:
            self.discard_pile.append(card.id)
        if card.autoplay_top:  # Havoc: CardPileCmd.AutoPlayFromDrawPile(1, Top, forceExhaust)
            top = self._take_top()
            if top:
                self._autoplay(top, force_exhaust=True)

    def _special(self, cid: str, target: _Enemy | None, x: int) -> None:
        """Upgraded numbers come from each card's OnUpgrade: a CardDef field (card.damage) where cards.UPGRADES
        changes it, else `up` (1 for an "X+") times the upgrade step."""
        if cid == "FRANTIC_ESCAPE":  # the sand pit gets 1 further away; this costs 1 more
            for e in self.enemies:
                if e.pw.get("SandpitPower"):
                    e.pw["SandpitPower"] += 1
            return
        card, b, up = CARDS[cid], base_id(cid), int(is_upgraded(cid))
        if b == "ASHEN_STRIKE":
            self._hit(card, target, self._ashen_damage(cid))
        elif b == "BULLY":  # ExtraDamage 2, +1
            self._hit(card, target, 4 + (2 + up) * (target.vulnerable if target else 0))
        elif b == "DISMANTLE":
            self._hit(card, target, card.damage, 2 if target and target.vulnerable else 1)
        elif b == "FIGHT_ME":  # Strength 3, +1; the enemy's 1 is not upgraded
            self._hit(card, target, card.damage, 2)
            self._gain_strength(3 + up)
            if target and target.is_alive:
                target.strength += 1
        elif b == "PILLAGE":  # draw until a non-Attack (or a full hand / nothing to draw)
            self._hit(card, target, card.damage)
            # ponytail: capped at one pass over the piles. Uncapped (as in the game's do/while),
            # Hellraiser Strikes that Ringing sends straight to discard reshuffle forever.
            for _ in range(len(self.draw_pile) + len(self.discard_pile)):
                drawn = self._draw_one()
                if not (drawn and CARDS[drawn].type == "Attack" and len(self.hand) < MAX_HAND_SIZE and self.in_combat):
                    break
        elif b in ("RAMPAGE", "THRASH"):
            self._hit(card, target, card.damage + self.bonus_damage.get(cid, 0), card.hits)
            if b == "RAMPAGE":  # Increase 5, +4
                self.bonus_damage[cid] = self.bonus_damage.get(cid, 0) + 5 + 4 * up
            else:  # exhaust a random Attack in hand; gain its damage (Hook.ModifyDamage, no target)
                attacks = [i for i, c in enumerate(self.hand) if CARDS[c].type == "Attack"]
                if attacks:
                    eaten = self.hand.pop(self.rng.choice(attacks))
                    e = CARDS[eaten]
                    base = self._ashen_damage(eaten) if base_id(eaten) == "ASHEN_STRIKE" else \
                        e.damage + self.bonus_damage.get(eaten, 0)
                    # Hook.ModifyDamage with the eaten card as source: Strike Dummy, and Pen Nib if it's the 9th Attack.
                    base += 3 if "STRIKE_DUMMY" in self.relics and e.strike else 0
                    gain = player_attack_damage(base + self.strength, False, self.shrunk, self.weak > 0,
                                                mult=2 if "PEN_NIB" in self.relics and
                                                self.relic_state.get("pen_nib") == 9 else 1)
                    self.bonus_damage[cid] = self.bonus_damage.get(cid, 0) + gain
                    self._exhaust(eaten)
        elif b == "SPITE":  # Repeat 2, +1
            self._hit(card, target, card.damage, 2 + up if self.hp_lost_this_turn else 1)
        elif b == "FEED":  # ShouldOwnerDeathTriggerFatal: not for minions/illusions. MaxHp 3, +1
            fatal = target is not None and target.is_alive and not (target.defn.minion or target.defn.illusion)
            self._hit(card, target, card.damage)
            if fatal and not target.is_alive:
                self.player_max_hp += 3 + up  # CreatureCmd.GainMaxHp also heals that much
                self.heal(3 + up)
        elif b == "FIEND_FIRE":
            n = len(self.hand)
            for c in list(self.hand):  # a snapshot: cards added meanwhile (Burning Sticks) stay
                self.hand.remove(c)
                self._exhaust(c)
            self._hit(card, target, card.damage, n)
        elif b == "MANGLE":  # StrengthLoss 10, +5
            self._hit(card, target, card.damage)
            if target and target.is_alive:
                self._debuff(target, "mangle", 10 + 5 * up)
        elif b == "PACTS_END":
            if len(self.exhaust_pile) >= 3:
                self._hit(card, target, card.damage)
        elif b == "TEAR_ASUNDER":
            self._hit(card, target, card.damage, 1 + self.hp_loss_events)
        elif b == "DOMINATE":  # VulnerablePower 1, +1
            if target and target.is_alive:
                self._debuff(target, "vulnerable", 1 + up)
                self._gain_strength(target.vulnerable)
        elif b == "EVIL_EYE":  # Block 8, +3
            for _ in range(2 if self.exhausted_this_turn else 1):
                self._gain_block(8 + 3 * up, card=True)
        elif b == "EXPECT_A_FIGHT":
            self._gain_energy(sum(CARDS[c].type == "Attack" for c in self.hand))
        elif b == "FORGOTTEN_RITUAL":  # Energy 3, +1
            if self.exhausted_this_turn:
                self._gain_energy(3 + up)
        elif b == "INFERNAL_BLADE":  # a random Ironclad Attack, free this turn
            atk = self.rng.choice([c for c in GENERATED if CARDS[c].type == "Attack"])
            self.free_cards.append(atk)
            self._add_to_hand(atk)
        elif b == "SECOND_WIND":  # Block 5, +2
            for c in [c for c in self.hand if CARDS[c].type != "Attack"]:
                self.hand.remove(c)
                self._exhaust(c)
                self._gain_block(5 + 2 * up, card=True)
        elif b == "CASCADE":  # AutoPlayFromDrawPile(X, Top, forceExhaust: false); upgraded X + 1
            for _ in range(x + up):
                top = self._take_top()
                if not top or not self.in_combat:
                    break
                self._autoplay(top)
        elif b == "PRIMAL_FORCE":  # upgraded: the Giant Rocks are upgraded
            rock = "GIANT_ROCK+" if up else "GIANT_ROCK"
            self.hand = [rock if CARDS[c].type == "Attack" else c for c in self.hand]
        elif b == "HEADBUTT":
            self._hit(card, target, card.damage)
            self._ask("discard", cid)
        elif b == "BURNING_PACT":
            self._ask("hand", cid)
        elif b == "BRAND":
            self._lose_hp(1, from_card=True)
            self._ask("hand", cid)
        elif b == "ARMAMENTS":
            self._gain_block(card.block, card=True)
            if up:  # every upgradable hand card, no prompt
                self.hand = [upgrade(c) for c in self.hand]
            else:
                self._ask("upgrade", cid)
        elif b == "STOKE":
            n = len(self.hand)
            for c in list(self.hand):
                self.hand.remove(c)
                self._exhaust(c)
            for _ in range(n):  # CardFactory.GetForCombat: uniform, repeats allowed; upgraded: all upgraded
                c = self.rng.choice(GENERATED)
                self._add_to_hand(upgrade(c) if up else c)
        else:
            raise KeyError(f"no special logic for {cid}")

    def _ashen_damage(self, cid: str) -> int:
        """Ashen Strike: 6 + ExtraDamage (3, upgraded +1) per card in the exhaust pile."""
        return 6 + (3 + is_upgraded(cid)) * len(self.exhaust_pile)

    def _ask(self, kind: str, source: str) -> None:
        """CardSelectCmd.FromHand / FromCombatPile / FromHandForUpgrade, choosing exactly 1: nothing if the fight is
        ending or there are no options, no prompt for 1 option, else the player picks and the play stops here until
        they do. kind "upgrade" offers the upgradable hand cards and upgrades the pick in its slot."""
        pile = self.discard_pile if kind == "discard" else self.hand
        slots = [i for i, c in enumerate(pile) if kind != "upgrade" or c in UPGRADABLE]
        if self._ending() or not slots:
            self._finish_choice(source, None)
        elif len(slots) == 1:
            self._finish_choice(source, self._take(kind, slots[0]))
        elif self._pausable:
            self.pending_choice = {"kind": kind, "source": base_id(source)}
        else:
            # ponytail: the game prompts the player here too (only Whispering Earring has a selector). Autoplays
            # nest inside other effects, so pausing one needs a stack of paused plays; add it if Havoc's pick matters.
            self._finish_choice(source, self._take(kind, self.rng.choice(slots)))

    def _take(self, kind: str, i: int) -> str:
        """The picked card: out of its pile, or for "upgrade" upgraded where it is. Returns the card as offered."""
        pile = self.discard_pile if kind == "discard" else self.hand
        picked = pile[i]
        if kind == "upgrade":
            pile[i] = upgrade(picked)
        else:
            del pile[i]
        return picked

    def _finish_choice(self, source: str, picked: str | None) -> None:
        """The rest of the card after its prompt. picked is already out of its pile (or upgraded in it)."""
        b = base_id(source)
        if b == "HEADBUTT":
            if picked:
                self.draw_pile.append(picked)  # CardPilePosition.Top
            return
        if b == "ARMAMENTS":
            return
        if picked:
            self._exhaust(picked)
        if self._ending() or b == "TRUE_GRIT":  # CardPileCmd.Draw and PowerCmd.Apply no-op once the fight is ending
            return
        if b == "BURNING_PACT":  # Cards 2, +1
            self._draw(2 + is_upgraded(source))
        else:  # Brand: Strength 1, +1
            self._gain_strength(1 + is_upgraded(source))

    def _hit(self, card, target: _Enemy | None, base: int, hits: int = 1) -> None:
        # Vigor and Strike Dummy add to the base like Strength; Pen Nib doubles the attack it fires on.
        base += self.pw.get("VigorPower", 0) + (3 if "STRIKE_DUMMY" in self.relics and card.strike else 0)
        base += 3 if "MINIATURE_CANNON" in self.relics and is_upgraded(card.id) else 0  # ModifyDamageAdditive
        mult = 2 if self.rt.get("pen_play") == self._play_id else 1
        cruelty = self.pw.get("CrueltyPower", 0) + (25 if "PAPER_PHROG" in self.relics else 0)
        for _ in range(hits):
            if card.target_type == "AllEnemies":
                targets = self._hittable()
            elif card.target_type == "RandomEnemy":
                targets = [self.rng.choice(self._hittable())] if self._hittable() else []
            else:
                targets = [target] if target and target.is_alive else []
            for t in targets:
                if t.pw.get("ThornsPower"):  # BeforeDamageReceived; Unpowered, so block applies
                    self._damage_player(t.pw["ThornsPower"])
                    if not self.in_combat:
                        return
                dmg = player_attack_damage(base + self.strength, t.vulnerable > 0, self.shrunk, self.weak > 0,
                                           self.cards_played if t.defn.slow else None, cruelty, mult,
                                           2 if t.pw.get("FlutterPower") else 1)
                self._damage_enemy(t, dmg, attack=True)
            if not self.in_combat:
                return
        self.pw.pop("VigorPower", None)  # AfterAttack: Vigor is spent by the attack

    def _apply_power(self, name: str, amount: int) -> None:
        if name == "StrengthPower":
            self._gain_strength(amount)
            return
        self.pw[name] = 1 if name in SINGLE_POWERS else self.pw.get(name, 0) + amount
        if name == "CrimsonMantlePower":  # IncrementSelfDamage
            self.crimson_self += 1
        elif name == "InfernoPower":
            self.inferno_self += 1

    def _decrement(self, name: str) -> None:
        if self.pw.get(name):
            self.pw[name] -= 1
            if not self.pw[name]:
                del self.pw[name]

    def _hittable(self) -> list[_Enemy]:
        return [e for e in self.enemies if e.is_alive]

    def _debuff(self, e: _Enemy, name: str, amount: int, card: bool = True) -> None:
        """Vulnerable / Weak / Mangle on an enemy. ArtifactPower negates it and spends a charge.
        card: applied by a card (Unsettling Lamp); potions and relics pass False."""
        if card and "UNSETTLING_LAMP" in self.relics:
            # The first card to apply a debuff doubles all its debuffs, even one Artifact then negates
            # (BeforePowerAmountChanged runs first). ponytail: "that card" = the play id, so a nested autoplay isn't it.
            if self.rt.setdefault("lamp", self._play_id) == self._play_id:
                amount *= 2
        if e.artifact:
            e.artifact -= 1
            return
        if name == "mangle":  # ManglePower is a TemporaryStrengthPower: Strength down until its turn ends
            e.mangle += amount
            e.strength -= amount
            return
        setattr(e, name, getattr(e, name) + amount)
        if name == "vulnerable" and self.pw.get("ViciousPower"):
            self._draw(self.pw["ViciousPower"])

    def _gain_strength(self, amount: int) -> None:
        if amount > 0 and "RUINED_HELMET" in self.relics and not self.rt.get("helmet"):
            self.rt["helmet"] = 1  # TryModifyPowerAmountReceived: the first positive gain is doubled
            amount *= 2
        self.strength += amount

    def _damage_all(self, amount: int) -> None:
        """Relic damage (Unpowered) to every hittable enemy, read once before the hits."""
        for e in self._hittable():
            self._damage_enemy(e, amount)
        self._check_win()

    def _gain_energy(self, amount: int) -> None:
        if not self.pw.get("NoEnergyGainPower"):  # ModifyEnergyGain -> 0
            self.energy += amount

    def _gain_block(self, amount: int, card: bool = False) -> None:
        """card: a card's own block (Frail, Unmovable apply); other block (powers) is Unpowered."""
        if card:
            num, den = amount + self.dexterity, 1  # DexterityPower.ModifyBlockAdditive, before Frail
            if self.frail:
                num, den = num * 3, den * 4
            if self.pw.get("UnmovablePower") and \
                    len([p for p in self.block_plays if p != self._play_id]) < self.pw["UnmovablePower"]:
                num *= 2
            if "VAMBRACE" in self.relics and num > 0 and self.rt.setdefault("vambrace", self._play_id) == self._play_id:
                num *= 2  # the first card to gain block doubles all of its block
            amount = num // den
            if self._play_id not in self.block_plays:
                self.block_plays.append(self._play_id)
        self.player_block += amount
        if amount > 0 and self.pw.get("JuggernautPower") and self._hittable():
            self._damage_enemy(self.rng.choice(self._hittable()), self.pw["JuggernautPower"])

    # --- piles -----------------------------------------------------------------------------------

    def _take_top(self) -> str | None:
        if not self.draw_pile and self.discard_pile:  # ShuffleIfNecessary
            self.draw_pile, self.discard_pile = self.discard_pile, []
            self.rng.shuffle(self.draw_pile)
            self.shuffles += 1
            if "THE_ABACUS" in self.relics:
                self._gain_block(6)
            if self.shuffles > MAX_SHUFFLES:
                raise SimLoopError(f"{self.shuffles} reshuffles in one fight")
        return self.draw_pile.pop() if self.draw_pile else None

    def _draw_one(self, hand_draw: bool = False) -> str | None:
        if (self.pw.get("NoDrawPower") and not hand_draw) or len(self.hand) >= MAX_HAND_SIZE:
            return None
        card = self._take_top()
        if card is None:
            return None
        self.hand.append(card)
        if self.pw.get("HellraiserPower") and CARDS[card].strike:  # AfterCardDrawnEarly: autoplay it
            self.hand.pop()
            self._autoplay(card)
        return card

    def _draw(self, count: int, hand_draw: bool = False) -> None:
        for _ in range(count):
            if self._draw_one(hand_draw) is None or not self.in_combat:
                return

    def _add_to_hand(self, card_id: str) -> None:
        """A generated card: to hand, or the discard pile if the hand is full (CardPileCmd)."""
        (self.hand if len(self.hand) < MAX_HAND_SIZE else self.discard_pile).append(card_id)

    def _ending(self) -> bool:
        """CombatManager.IsOverOrEnding: no primary enemy left (the sim ends the fight at the next _check_win)."""
        return not self.in_combat or not any(e.is_alive and not (e.defn.illusion or e.defn.minion) for e in self.enemies)

    def _exhaust(self, card_id: str, ethereal: bool = False) -> None:
        if self._ending():  # CardCmd.Exhaust no-ops once the fight is ending
            return
        self.exhaust_pile.append(card_id)
        self.exhausted_this_turn = True
        if self.pw.get("FeelNoPainPower"):
            self._gain_block(self.pw["FeelNoPainPower"])
        if self.pw.get("DarkEmbracePower"):
            if ethereal:  # drawn after the hand flush
                self._ethereal_exhausts += 1
            else:
                self._draw(self.pw["DarkEmbracePower"])
        if base_id(card_id) == "DRUM_OF_BATTLE":  # its AfterCardExhausted. Energy 2, +1
            self._gain_energy(2 + is_upgraded(card_id))
        # ponytail: relic order assumed Charon's Ashes, Joss Paper, Burning Sticks.
        R = self.relics
        if "CHARONS_ASHES" in R:  # a lethal hit only makes the fight "ending": the rest of the card still runs
            for e in self._hittable():
                self._damage_enemy(e, 3)
        if "JOSS_PAPER" in R:
            if ethereal:
                self.rt["joss_eth"] = self.rt.get("joss_eth", 0) + 1  # counted at turn end
            else:
                self.relic_state["joss_paper"] = self.relic_state.get("joss_paper", 0) + 1
                self._joss_draw()
        if "BURNING_STICKS" in R and not self.rt.get("sticks") and CARDS[card_id].type == "Skill" and not self._ending():
            self.rt["sticks"] = 1
            self._add_to_hand(str(card_id))  # a clone: no deck card

    def _joss_draw(self) -> None:
        n = self.relic_state.get("joss_paper", 0)
        if n >= 5:
            if not self._ending():
                self._draw(n // 5)
            self.relic_state["joss_paper"] = n % 5

    # --- damage ----------------------------------------------------------------------------------

    def _damage_enemy(self, e: _Enemy, dmg: int, attack: bool = False) -> None:
        """attack: a card's powered attack, which Flutter, Curl Up and Personal Hive answer."""
        if e.pw.get("HardToKillPower"):  # ModifyDamageCap
            dmg = min(dmg, e.pw["HardToKillPower"])
        had_block = e.block > 0
        absorbed = min(e.block, dmg)
        e.block -= absorbed
        hp_loss = dmg - absorbed
        if e.slippery and hp_loss >= 1:  # SlipperyPower: cap at 1, spend a stack
            hp_loss = 1
            e.slippery -= 1
        was_alive = e.hp > 0
        e.hp = max(0, e.hp - hp_loss)
        if was_alive and e.hp == 0 and "GREMLIN_HORN" in self.relics:  # AfterDeath: minions and illusions too
            self._gain_energy(1)
            self._draw(1)
        if e.is_alive:
            self._hive_damage(e, hp_loss, attack, had_block)
            # PlowPower.AfterDamageReceived: at or below its Plow amount, lose all Strength (and its
            # temporary Strength powers) and get stunned (STUNNED, then BEAST_CRY_MOVE: phase 2).
            if e.plow and hp_loss > 0 and e.hp <= e.plow:
                e.plow, e.strength, e.mangle, e.move, e.next_override = 0, 0, 0, "STUNNED", "BEAST_CRY_MOVE"
            return
        self._hive_death(e, attack)
        # InfestedPower.AfterDeath: spawns that start stunned, in slots after the dead one.
        for i, mid in enumerate(e.defn.on_death_spawn):
            spawn = _Enemy.spawn(MONSTERS[mid], self.rng)
            spawn.next_override = WRIGGLER_SLOT_OPENERS[i]
            self.enemies.append(spawn)
        # ShrinkPower / ConstrictPower.AfterDeath: removed when their applier dies.
        # ponytail: assumes one source of each per fight (true for all Act 1 rosters).
        moves = e.defn.moves.values()
        if any(m.shrink for m in moves):
            self.shrunk = False
        if any(m.constrict for m in moves):
            self.constrict = 0
        if e.defn.illusion:  # keeps buffs, loses debuffs, revives on its next turn
            e.vulnerable = e.weak = 0
            e.move = "REVIVE_MOVE"

    # --- Hive monsters -----------------------------------------------------------------------------

    def _stun(self, e: _Enemy, next_move: str) -> None:
        """CreatureCmd.Stun: a fresh STUNNED state, then next_move."""
        e.move, e.next_override = "STUNNED", next_move

    def _hive_damage(self, e: _Enemy, hp_loss: int, attack: bool, had_block: bool) -> None:
        """AfterDamageReceived and AfterBlockBroken, for a monster that survived the hit."""
        pw = e.pw
        if pw.get("BurrowedPower") and had_block and e.block == 0:
            del pw["BurrowedPower"]
            self._stun(e, "BITE_MOVE")
        if hp_loss and pw.get("SlumberPower"):
            pw["SlumberPower"] -= 1
            if not pw["SlumberPower"]:
                del pw["SlumberPower"]
                pw.pop("PlatingPower", None)
                self._stun(e, "ROLL_OUT_MOVE")
        if attack and hp_loss and pw.get("FlutterPower"):
            pw["FlutterPower"] -= 1
            if not pw["FlutterPower"]:
                del pw["FlutterPower"]
                self._stun(e, self._next_move(e, e.log[-1]))
        if attack:
            self._hive_attacked(e)

    def _hive_attacked(self, e: _Enemy) -> None:
        if e.pw.get("CurlUpPower"):  # gains its block once the card that hit it has finished (_after_resolve)
            self.rt["curl"] = 1
        for _ in range(e.pw.get("PersonalHivePower", 0)):  # Dazed at a random place in the draw pile
            self.draw_pile.insert(self.rng.randint(0, len(self.draw_pile)), "DAZED")

    def _hive_death(self, e: _Enemy, attack: bool) -> None:
        """AfterDeath. A killing blow still counts for Personal Hive (AfterDamageReceived runs first)."""
        if attack:
            self._hive_attacked(e)
        if e.defn.reattach and any(x.is_alive for x in self.enemies if x is not e):
            e.pw["reviving"] = 1
            e.move, e.next_override = "DEAD_MOVE", None
        if e.pw.get("SwipePower"):  # SwipePower.BeforeDeath: the card comes back after the fight
            self.stolen = []
        for x in self.enemies:
            if x is not e and x.is_alive and x.pw.pop("CrabRagePower", None):  # the other arm enrages
                x.strength += 6
                x.block += 99
        if self.pw.get("SurroundedPower"):
            alive = self._hittable()
            if alive and (all("BackAttackLeftPower" in x.pw for x in alive) or all("BackAttackRightPower" in x.pw for x in alive)):
                self._face(alive[0])

    def _face(self, target: _Enemy | None) -> None:
        """SurroundedPower.UpdateDirection: turn toward what was just targeted."""
        if not target or not self.pw.get("SurroundedPower"):
            return
        if self.facing == "Right" and "BackAttackLeftPower" in target.pw:
            self.facing = "Left"
        elif self.facing == "Left" and "BackAttackRightPower" in target.pw:
            self.facing = "Right"

    def _next_move(self, e: _Enemy, performed: str) -> str:
        """The move after `performed`: its follow-up, resolving the Hive's conditional branches."""
        follow = e.defn.follow[performed]
        if follow == "SUMMON_BRANCH_STATE":  # Ovicopter.CanLay
            return "LAY_EGGS_MOVE" if sum(x.is_alive for x in self.enemies) <= 3 else "NUTRITIONAL_PASTE_MOVE"
        if follow == "CURSE_BRANCH":  # Knowledge Demon: 3 curses, then only the rest of the cycle
            return "CURSE_OF_KNOWLEDGE_MOVE" if e.log.count("CURSE_OF_KNOWLEDGE_MOVE") < 3 else "SLAP_MOVE"
        return pick_move(follow, e.log, self.rng)

    def _move_effect(self, e: _Enemy, effect: str) -> None:
        """What a Hive move does beyond damage, block, Strength and status cards."""
        pw = e.pw
        if effect == "tender":
            self._apply_power("TenderPower", 1)
        elif effect == "spikes":
            pw["ThornsPower"] = pw.get("ThornsPower", 0) + 5
        elif effect == "unspike":
            pw["ThornsPower"] = pw.get("ThornsPower", 0) - 5
            if not pw["ThornsPower"]:
                del pw["ThornsPower"]
        elif effect == "burrow":
            pw["BurrowedPower"] = 1
        elif effect == "flutter":
            pw["FlutterPower"] = 5
        elif effect == "steal":
            self._steal(e)
        elif effect == "escape":
            self.enemies.remove(e)  # CreatureCmd.Escape: the stolen card leaves with it
            self._check_win()
        elif effect == "lay_eggs":
            # ponytail: new eggs always go in front; the game refills the last free slot, so once some have died
            # the order on screen can differ (seen once in 238 validated steps; no rule depends on it).
            for _ in range(3):  # the last free slot first, and the eggs' slots come before Ovicopter's
                egg = _Enemy.spawn(MONSTERS["TOUGH_EGG"], self.rng)
                egg.pw["HatchPower"] = 2  # ToughEgg.AfterAddedToRoom, on the enemy's turn
                self.enemies.insert(0, egg)
        elif effect == "hatch":  # every power but Minion goes
            pw.clear()
            e.strength = e.vulnerable = e.weak = e.mangle = e.artifact = 0
            e.hp = e.max_hp = self.rng.randint(19, 22)
        elif effect == "wail":
            for x in self.enemies:
                if x.is_alive:
                    x.strength += 3
        elif effect == "pheromone":
            if pw.get("PersonalHivePower", 0) < 3:
                pw["PersonalHivePower"] = pw.get("PersonalHivePower", 0) + 1
                e.strength += 1
            else:
                e.strength += 2
        elif effect == "spark":
            pw["VitalSparkPower"] = pw.get("VitalSparkPower", 0) + 2
        elif effect == "reattach":
            pw.pop("reviving", None)
            if any(x.is_alive for x in self.enemies if x is not e):
                e.hp = min(e.max_hp, e.hp + pw.get("ReattachPower", 0))
        elif effect == "curse":
            # ponytail: always Disintegration, the first option; give the combat model this choice when it's worth it.
            self._apply_power("DisintegrationPower", (6, 7, 8)[e.log.count("CURSE_OF_KNOWLEDGE_MOVE") - 1])  # this one's in the log
        elif effect == "ponder":
            e.hp = min(e.max_hp, e.hp + 30)
        elif effect == "liquify":
            pw["SandpitPower"] = 4
            for _ in range(3):
                self.draw_pile.insert(self.rng.randint(0, len(self.draw_pile)), "FRANTIC_ESCAPE")
            self.discard_pile += ["FRANTIC_ESCAPE"] * 3
        else:
            raise ValueError(effect)

    def _steal(self, e: _Enemy) -> None:
        """ThievingHopper._stealPriorities, over the draw and discard pile cards with a DeckVersion. The deck loses
        that copy's deck card: for one upgraded this fight (Armaments), the card before the upgrade."""
        rarity = lambda x: CARDS[x[0][x[1]]].rarity  # noqa: E731
        cards = [(pile, i) for pile in (self.draw_pile, self.discard_pile) for i, c in enumerate(pile) if isinstance(c, DeckCard)]
        for tier in (("Uncommon",), ("Common", "Rare"), ("Basic",)):
            best = [x for x in cards if rarity(x) in tier]
            if best:
                cards = best
                break
        if cards:
            pile, i = self.rng.choice(cards)
            self.stolen.append(pile.pop(i).deck)
            e.pw["SwipePower"] = 1

    def _lose_hp(self, amount: int, from_card: bool = False) -> None:
        """Unblocked HP loss: card self-damage (Unblockable), or the part of a hit block didn't stop."""
        R = self.relics
        if amount <= 0:
            return
        # ModifyHpLostAfterOsty. ponytail: relic order assumed Tungsten Rod, then Beating Remnant.
        if "TUNGSTEN_ROD" in R:
            amount -= 1
        if "BEATING_REMNANT" in R:
            amount = min(amount, 20 - self.rt.get("remnant", 0))
        if amount <= 0:
            return
        self.player_hp -= amount
        self.hp_loss_events += 1
        if self.player_hp <= 0:
            self.player_hp = 0
            # Kill -> ShouldDieLate: Lizard Tail heals instead. AfterDamageReceived (relics, Rupture ...) is
            # skipped for a lethal hit either way.
            if "LIZARD_TAIL" in R and not self.relic_state.get("lizard_used"):
                self.relic_state["lizard_used"] = 1
                self.player_hp = max(1, self.player_max_hp * 50 // 100)
                self.hp_lost_this_turn |= self.side == "Player"
                self._red_skull()
                return
            self._end_combat(won=False)
            return
        self._red_skull()
        # AfterDamageReceived. ponytail: the game runs powers (Rupture, Inferno) before relics; here the relics
        # that don't care about the side go first, Demon Tongue (player's side only) last.
        if "CENTENNIAL_PUZZLE" in R and not self.rt.get("puzzle"):
            self.rt["puzzle"] = 1
            if not self._ending():  # CardPileCmd.Draw no-ops once the fight is ending
                self._draw(3)
        if "SELF_FORMING_CLAY" in R:
            self._apply_power("SelfFormingClayPower", 3)
        if "BEATING_REMNANT" in R:
            self.rt["remnant"] = self.rt.get("remnant", 0) + amount
        if self.side != "Player":
            return
        self.hp_lost_this_turn = True
        if self.pw.get("RupturePower"):  # HP the card being played costs pays out after it resolves
            if from_card and self._rupture is not None:
                self._rupture += self.pw["RupturePower"]
            else:
                self._gain_strength(self.pw["RupturePower"])
        if self.pw.get("InfernoPower"):  # Unpowered damage to every hittable enemy
            for e in self._hittable():
                self._damage_enemy(e, self.pw["InfernoPower"])
        # Kill doesn't win-check, so Demon Tongue still heals after Inferno's kill (and before Meat on the Bone).
        if "DEMON_TONGUE" in R and not self.rt.get("tongue"):
            self.rt["tongue"] = 1
            self.heal(amount)
        if self.pw.get("InfernoPower"):
            self._check_win()

    def _damage_player(self, dmg: int, dealer: _Enemy | None = None) -> None:
        """Blockable damage; dealer = a monster's attack (powered), which Flame Barrier answers."""
        if dealer and self.pw.get("ThornsPower"):  # BeforeDamageReceived: before block; a kill doesn't stop the hit
            self._damage_enemy(dealer, self.pw["ThornsPower"])
        absorbed = min(self.player_block, dmg)
        self.player_block -= absorbed
        hits = self.hp_loss_events
        self._lose_hp(dmg - absorbed)
        self.lamp_hit |= self.hp_loss_events > hits  # Lava Lamp: UnblockedDamage > 0 and not Unblockable (card self-damage is)
        if dealer and self.in_combat:
            self._check_win()  # a Thorns kill ends the fight once the hit has landed
        if dealer and self.in_combat and self.pw.get("FlameBarrierPower") and dealer.is_alive:
            self._damage_enemy(dealer, self.pw["FlameBarrierPower"])
            self._check_win()

    def monster_hit_damage(self, e: _Enemy, base: int) -> int:
        """x1.5 player Vulnerable, x0.75 monster Weak, x0.5 if the player has Colossus and the monster
        is Vulnerable (ColossusPower) — one truncation at the end."""
        base += self.pw.get("TaintedPower", 0)  # ModifyDamageAdditive
        back = self.pw.get("SurroundedPower") and ("BackAttackLeftPower" if self.facing == "Right" else "BackAttackRightPower") in e.pw
        num = base * (3 if self.vulnerable else 2) * (3 if e.weak else 4) * \
            (1 if self.pw.get("ColossusPower") and e.vulnerable else 2) * (3 if back else 2)
        return max(0, num // 32)

    def _end_combat(self, won: bool) -> None:
        self.in_combat = False
        self.is_play_phase = False
        self.won = won
        if won and "MEAT_ON_THE_BONE" in self.relics and self.player_hp <= self.player_max_hp // 2:
            self.heal(12)  # AfterCombatVictoryEarly

    # --- turns -----------------------------------------------------------------------------------

    def _start_player_turn(self) -> None:
        """CombatManager.StartTurn + SetupPlayerTurn for the player side."""
        self.side = "Player"
        self.cards_last, self.cards_done = self.cards_done, 0  # Pocketwatch.BeforeSideTurnStart
        self.rt.pop("remnant", None)  # Beating Remnant, Demon Tongue: BeforeSideTurnStart
        self.rt.pop("tongue", None)
        self.exhausted_this_turn = self.hp_lost_this_turn = False
        self.attack_plays, self.block_plays, self.free_cards = 0, [], []
        self.attacks_done = self.skills_done = self.powers_done = 0
        R, st = self.relics, self.relic_state
        # BeforeSideTurnStart. ponytail: per enemy, Bag of Marbles then Red Mask (Artifact: Marbles spends the charge).
        if self.round <= 1:
            for e in self._hittable():
                e.block += e.pw.get("PlatingPower", 0)  # PlatingPower.BeforeSideTurnStart
                if "BackAttackRightPower" in e.pw:  # Rocket.AfterAddedToRoom
                    self.pw["SurroundedPower"] = 1
                if "BAG_OF_MARBLES" in R:
                    self._debuff(e, "vulnerable", 1, card=False)
                if "RED_MASK" in R:
                    self._debuff(e, "weak", 1, card=False)
        # Creature.AfterTurnStart: block clears, except on turn 1. ponytail: Barricade assumed to be the
        # block-clear preventer before Sturdy Clamp.
        if self.round > 1 and not self.pw.get("BarricadePower"):
            self.player_block = min(self.player_block, 10) if "STURDY_CLAMP" in R else 0
        # AfterBlockCleared (unconditional, so Barricade doesn't skip it); powers before relics
        if self.pw.get("SelfFormingClayPower"):
            self._gain_block(self.pw.pop("SelfFormingClayPower"))
        if "HORN_CLEAT" in R and self.round == 2:
            self._gain_block(14)
        if "CAPTAINS_WHEEL" in R and self.round == 3:
            self._gain_block(18)
        if "SPARKLING_ROUGE" in R and self.round == 3:
            self._gain_strength(1)
            self.dexterity += 1
        self._check_win()  # Juggernaut can kill off the block; hooks stop once combat is over
        if not self.in_combat:
            return
        # BeforeSideTurnStart: Aggression moves random Attacks from discard to hand and upgrades them.
        attacks = [c for c in self.discard_pile if CARDS[c].type == "Attack"]
        for c in self.rng.sample(attacks, min(len(attacks), self.pw.get("AggressionPower", 0))):
            del self.discard_pile[next(i for i, x in enumerate(self.discard_pile) if x is c)]  # this copy
            self._add_to_hand(upgrade(c))
        if "ICE_CREAM" in R and self.round > 1:  # ShouldPlayerResetEnergy false: AddMaxEnergyToCurrent
            self.energy += self.max_energy
        else:
            self.energy = self.max_energy
        # AfterEnergyReset
        if "ART_OF_WAR" in R and self.round > 1 and not self.attacks_last:
            self._gain_energy(1)
        if "VENERABLE_TEA_SET" in R and st.get("tea_set"):
            self._gain_energy(2)
            st["tea_set"] = 0
        draw = HAND_DRAW_COUNT + (2 if "BAG_OF_PREPARATION" in R and self.round == 1 else 0) + \
            (3 if "POCKETWATCH" in R and self.round > 1 and self.cards_last <= 3 else 0)
        if self.round == 1:  # Innate cards go on top of the draw pile, and the hand draw is at least that many
            innate = [c for c in self.draw_pile if c in INNATE]
            self.draw_pile = [c for c in self.draw_pile if c not in INNATE] + innate
            draw = min(max(draw, len(innate)), MAX_HAND_SIZE)
        self._draw(draw, hand_draw=True)
        # AfterPlayerTurnStart. ponytail: hook order assumed Crimson Mantle, then Inferno.
        if self.in_combat and self.pw.get("CrimsonMantlePower"):
            self._lose_hp(self.crimson_self)
            if self.in_combat:
                self._gain_block(self.pw["CrimsonMantlePower"])
        if self.in_combat and self.pw.get("InfernoPower"):
            self._lose_hp(self.inferno_self)
        # ponytail: relic hook order assumed Pendulum, Festive Popper, Mercury Hourglass, Vexing Puzzlebox, Blood Vial.
        if self.in_combat and "PENDULUM" in R:
            st["pendulum"] = (st.get("pendulum", 0) + 1) % 3
            if not st["pendulum"]:
                self._draw(1)
        if self.in_combat and "FESTIVE_POPPER" in R and self.round == 1:
            self._damage_all(9)
        if self.in_combat and "MERCURY_HOURGLASS" in R:
            self._damage_all(3)
        if self.in_combat and "VEXING_PUZZLEBOX" in R and self.round == 1:
            # ponytail: the card comes from every Ironclad card that can be generated, not the unlocked pool.
            card = self.rng.choice(GENERATED)
            self.free_cards.append(card)
            self._add_to_hand(card)
        if self.in_combat and "BLOOD_VIAL" in R and self.round <= 1:
            self.heal(2)
        if self.in_combat and "BELLOWS" in R and self.round <= 1:  # hook order after Blood Vial assumed
            self.hand = [upgrade(c) for c in self.hand]
        self._check_win()
        if not self.in_combat:
            return
        # AfterSideTurnStart. ponytail: relic order assumed Lantern, Candelabra, Chandelier, Akabeko, Happy Flower, Bread, Brimstone.
        if "LANTERN" in R and self.round <= 1:
            self._gain_energy(1)
        if "CANDELABRA" in R and self.round == 2:
            self._gain_energy(2)
        if "CHANDELIER" in R and self.round == 3:
            self._gain_energy(3)
        if "AKABEKO" in R and self.round <= 1:
            self._apply_power("VigorPower", 8)
        if "HAPPY_FLOWER" in R:
            st["happy_flower"] = (st.get("happy_flower", 0) + 1) % 3
            if not st["happy_flower"]:
                self._gain_energy(1)
        if "BREAD" in R and self.round == 1:
            self.energy = max(0, self.energy - 2)
        if "BRIMSTONE" in R:
            self._gain_strength(2)
            for e in self._hittable():
                e.strength += 1
        self._gain_strength(self.pw.get("DemonFormPower", 0))
        if self.round > 1:
            self._decrement("PlatingPower")
        self.is_play_phase = True

    def end_turn(self) -> dict:
        if self.pending_choice:
            return {"error": "choice_pending"}
        if not self.in_combat or not self.is_play_phase:
            return {"error": "not_play_phase"}
        self.is_play_phase = False
        # AutoPostPlay phase: Stampede plays random Attacks from hand; Howl from Beyond plays itself
        # from the exhaust pile. ponytail: hook order assumed Stampede first.
        self._post_play = True
        for _ in range(self.pw.get("StampedePower", 0)):
            attacks = [i for i, c in enumerate(self.hand) if CARDS[c].type == "Attack" and CARDS[c].cost >= 0]
            if attacks and self.in_combat:
                self._autoplay(self.hand.pop(self.rng.choice(attacks)))
        while self.in_combat and (howl := next((c for c in self.exhaust_pile if base_id(c) == "HOWL_FROM_BEYOND"), None)):
            self.exhaust_pile.remove(howl)
            self._autoplay(howl)
        self._post_play = False
        if not self.in_combat:
            return {"ok": True}
        # BeforeTurnEnd: Orichalcum reads block first (BeforeSideTurnEndVeryEarly), then Plating (Early),
        # then the BeforeSideTurnEnd relics.
        R = self.relics
        orichalcum = "ORICHALCUM" in R and self.player_block <= 0
        if self.pw.get("PlatingPower"):
            self._gain_block(self.pw["PlatingPower"])
        # ponytail: relic order assumed Orichalcum, Cloak Clasp, Ripple Basin, Screaming Flagon, Stone Calendar.
        if orichalcum:
            self._gain_block(6)
        if "CLOAK_CLASP" in R:
            self._gain_block(len(self.hand))
        if "RIPPLE_BASIN" in R and not self.attacks_done:
            self._gain_block(4)
        if "SCREAMING_FLAGON" in R and not self.hand:
            self._damage_all(20)
            if not self.in_combat:
                return {"ok": True}
        if "STONE_CALENDAR" in R and self.round == 7:
            self._damage_all(52)
            if not self.in_combat:
                return {"ok": True}
        # DoTurnEnd: Ethereal cards exhaust, then turn-end-in-hand effects (Infection).
        for c in [c for c in self.hand if self._is_ethereal(c)]:
            self.hand.remove(c)
            self._exhaust(c, ethereal=True)
        self._check_win()  # Charon's Ashes
        if not self.in_combat:
            return {"ok": True}
        for c in list(self.hand):  # turnEndCards is fixed before any effect runs (a drawn Infection does nothing)
            if CARDS[c].end_turn_damage:
                self._damage_player(CARDS[c].end_turn_damage)
                if not self.in_combat:
                    return {"ok": True}
        if not ("RINGING_TRIANGLE" in R and self.round == 1):  # ShouldFlush; otherwise the whole hand is kept
            self.discard_pile += self.hand  # hand flush
            self.hand = []
        self.ringing = False
        self.attacks_last = self.attacks_done  # AfterSideTurnEnd (Art of War)
        self.cards_played = 0  # SlowPower resets at the start of the enemy turn
        # AfterSideTurnEnd: Constrict hits (Unpowered, so block applies but Vulnerable doesn't);
        # Tangled, temporary Strength and this-turn powers go; Dark Embrace draws for Ethereals.
        if self.constrict:
            self._damage_player(self.constrict)
            if not self.in_combat:
                return {"ok": True}
        self.tangled = 0
        self.strength += self.tender_plays  # TenderPower.AfterSideTurnEnd
        self.dexterity += self.tender_plays
        self.tender_plays = 0
        self.strength -= self.temp_strength  # TemporaryStrengthPower.AfterSideTurnEnd
        self.temp_strength = 0
        self.dexterity -= self.temp_dexterity  # SpeedPotionPower (TemporaryDexterityPower)
        self.temp_dexterity = 0
        for name in TURN_POWERS:
            self.pw.pop(name, None)
        if self._ethereal_exhausts and self.pw.get("DarkEmbracePower"):
            self._draw(self.pw["DarkEmbracePower"] * self._ethereal_exhausts)
        self._ethereal_exhausts = 0
        # ponytail: relic order assumed Joss Paper, then Parrying Shield (so a lethal Shield can't drop Joss's count).
        if "JOSS_PAPER" in self.relics:  # AfterSideTurnEnd: the Ethereal exhausts count now
            self.relic_state["joss_paper"] = self.relic_state.get("joss_paper", 0) + self.rt.pop("joss_eth", 0)
            self._joss_draw()
        if "PARRYING_SHIELD" in R and self.player_block >= 10 and self._hittable():
            self._damage_enemy(self.rng.choice(self._hittable()), 6)
            self._check_win()
            if not self.in_combat:
                return {"ok": True}
        if self.pw.get("DisintegrationPower"):  # AfterSideTurnEndLate; Unpowered
            self._damage_player(self.pw["DisintegrationPower"])
            if not self.in_combat:
                return {"ok": True}
        self._run_enemy_turn()
        return {"ok": True}

    def _run_enemy_turn(self) -> None:
        self.side = "Enemy"
        # ExecuteEnemyTurn iterates a snapshot: summons act from next turn; dead illusions act (revive).
        alive = [e for e in self.enemies if e.in_combat]
        for e in alive:
            if "BurrowedPower" not in e.pw:  # BurrowedPower.ShouldClearBlock
                e.block = 0  # block clears at the start of the enemy's own turn
            if e.pw.get("PlatingPower") and self.round > 1:  # AfterSideTurnStart, not on the first round
                e.pw["PlatingPower"] -= 1
                if not e.pw["PlatingPower"]:
                    del e.pw["PlatingPower"]
            if e.pw.get("SandpitPower"):  # AfterSideTurnStartLate: at 0 it eats the player
                e.pw["SandpitPower"] -= 1
                if not e.pw["SandpitPower"]:
                    self.player_hp = 0
                    self._end_combat(won=False)
                    return
        # PowerCmd.Apply: a debuff newly applied to the player skips its next tick-down,
        # so it survives the end of the enemy turn that applied it.
        fresh = set()
        for e in alive:
            if not e.in_combat:  # killed earlier this turn (Flame Barrier)
                continue
            mv = e.defn.moves[e.move]
            fully_blocked = False
            for _ in range(mv.hits if mv.damage else 0):
                dmg = self.monster_hit_damage(e, mv.damage + e.strength)
                fully_blocked = self.player_block >= dmg
                self._damage_player(dmg, dealer=e)
                if not self.in_combat:
                    return
                if not e.is_alive:
                    break
            if not e.in_combat:
                continue
            e.block += mv.block
            e.strength += mv.strength
            self.shrunk |= mv.shrink
            self.discard_pile += ["SLIMED"] * mv.slimed + ["DAZED"] * mv.dazed
            self.discard_pile += ["INFECTION"] * mv.infection + ["WOUND"] * mv.wound
            for _ in range(mv.toxic):
                self._add_to_hand("TOXIC")
            self.tangled += mv.tangled
            self.constrict += mv.constrict
            self.ringing |= mv.ringing
            e.plow += mv.plow
            if mv.summon:
                # Creatures are ordered by encounter slot; FogmogNormal.Slots = ["illusion", "fogmog"],
                # so the summoned Eye goes first (and acts before Fogmog from next turn).
                # ponytail: Fogmog is the only Act 1 summoner; per-encounter slots if more appear.
                self.enemies.insert(0, _Enemy.spawn(MONSTERS[mv.summon], self.rng))
            if mv.revive:
                e.hp = e.max_hp
            for name in ("vulnerable", "frail", "weak"):
                if getattr(mv, name):
                    if not getattr(self, name):
                        fresh.add(name)
                    setattr(self, name, getattr(self, name) + getattr(mv, name))
            performed = e.move
            e.log.append(performed)
            if mv.effect:
                self._move_effect(e, mv.effect)
                if not self.in_combat:
                    return
            if e.next_override:
                e.move, e.next_override = e.next_override, None
            elif performed in e.defn.follow:
                e.move = self._next_move(e, performed)
            if performed == "SNORE_MOVE" and "SlumberPower" not in e.pw:
                e.move = "ROLL_OUT_MOVE"
            if fully_blocked and "ImbalancedPower" in e.pw and mv.damage:  # HeadbuttMove: stunned, then the same move
                self._stun(e, performed)

        for e in alive:  # its debuffs tick down after its turn ends; Mangle's Strength comes back
            e.vulnerable = max(0, e.vulnerable - 1)
            e.weak = max(0, e.weak - 1)
            e.strength += e.mangle
            e.mangle = 0
        for e in alive:  # TerritorialPower.AfterSideTurnEnd
            if e.is_alive:
                e.strength += e.defn.territorial
                e.block += e.pw.get("PlatingPower", 0)  # BeforeSideTurnEndEarly. ponytail: order against attacks only
                if e.pw.get("HatchPower"):
                    e.pw["HatchPower"] -= 1
                    if not e.pw["HatchPower"]:
                        del e.pw["HatchPower"]
                if e.pw.get("EscapeArtistPower", 0) > 1:
                    e.pw["EscapeArtistPower"] -= 1
                if e.pw.get("SlumberPower"):  # AfterSideTurnEnd: WakeUpMove, no stun
                    e.pw["SlumberPower"] -= 1
                    if not e.pw["SlumberPower"]:
                        del e.pw["SlumberPower"]
                        e.pw.pop("PlatingPower", None)
                        e.move = "ROLL_OUT_MOVE"
        self.pw.pop("TaintedPower", None)  # TaintedPower.AfterSideTurnEnd, enemy side
        self.pw.pop("FlameBarrierPower", None)  # removed at the end of the other side's turn
        self._decrement("ColossusPower")
        for name in ("vulnerable", "frail", "weak"):  # the player's tick at the same point
            if name not in fresh:
                setattr(self, name, max(0, getattr(self, name) - 1))
        self.round += 1
        self._start_player_turn()

    def _enemy_dict(self, i: int, e: _Enemy) -> dict:
        mv = e.defn.moves[e.move]
        hit = self.monster_hit_damage(e, mv.damage + e.strength)
        intents = (
            [{"type": "Attack", "className": "MultiAttackIntent" if mv.hits > 1 else "SingleAttackIntent",
              "damage": hit, "hits": mv.hits, "totalDamage": hit * mv.hits}]
            if mv.damage else [{"type": mv.intent, "className": f"{mv.intent}Intent"}]
        )
        powers = []
        if e.strength:
            powers.append({"id": "STRENGTH", "name": "StrengthPower", "type": "Buff", "amount": e.strength})
        for name, amount in (("VulnerablePower", e.vulnerable), ("WeakPower", e.weak), ("ManglePower", e.mangle)):
            if amount:
                powers.append({"id": name.upper(), "name": name, "type": "Debuff", "amount": amount})
        for name, amount in (("ArtifactPower", e.artifact), ("SlipperyPower", e.slippery), ("PlowPower", e.plow)):
            if amount:
                powers.append({"id": name.upper(), "name": name, "type": "Buff", "amount": amount})
        for name, amount in e.pw.items():
            if name != "reviving":
                powers.append({"id": name.upper(), "name": name, "type": "Buff", "amount": amount})
        return {
            "combatId": i + 1,
            "name": e.defn.name,
            "modelId": e.defn.model_id,
            "hp": e.hp,
            "maxHp": e.max_hp,
            "block": e.block,
            "isAlive": e.is_alive,
            "isStunned": False,
            "powers": powers,
            "intent": {"moveId": e.move, "intents": intents},
        }

    def combat_dict(self) -> dict:
        if not self.in_combat:
            return {"inCombat": False}
        cards = lambda pile: [card_to_dict(c, self.cost(c), self.can_play(c)) for c in pile]  # noqa: E731
        return {
            "inCombat": True,
            "isPlayPhase": self.is_play_phase,
            "round": self.round,
            "cardsPlayedThisTurn": self.cards_played,
            "choice": self.pending_choice,
            "currentSide": "Player" if self.is_play_phase else "Enemy",
            "simRelics": sorted(self.relics),  # sim only; player.relics is filled by the live game
            "relicCounters": {**self.relic_state, "attacks": self.attacks_done, "skills": self.skills_done},
            "potionSlots": list(self.potions),  # sim only: the live /combat has no slots, so env masks potions off
              "player": {
                "hp": self.player_hp,
                "maxHp": self.player_max_hp,
                "block": self.player_block,
                "gold": 99,
                "energy": self.energy,
                "maxEnergy": self.max_energy,
                "stars": 0,
                "hand": cards(self.hand),
                "drawPile": cards(self.draw_pile),
                "discardPile": cards(self.discard_pile),
                "exhaustPile": cards(self.exhaust_pile),
                "powers": [{"id": n.upper(), "name": n, "type": "Debuff", "amount": a} for n, a in (
                    ("ShrinkPower", -1 if self.shrunk else 0), ("VulnerablePower", self.vulnerable),
                    ("FrailPower", self.frail), ("TangledPower", self.tangled),
                    ("ConstrictPower", self.constrict), ("StrengthPower", self.strength),
                    ("SetupStrikePower", self.temp_strength), ("WeakPower", self.weak),
                    ("DexterityPower", self.dexterity), ("SpeedPotionPower", self.temp_dexterity),
                    ("RingingPower", int(self.ringing))) if a] +
                [{"id": n.upper(), "name": n, "type": "Buff", "amount": a} for n, a in self.pw.items()],
                "relics": [],
                "potions": [],
                "deck": cards(starter_deck()),
            },
            # The live game drops dead enemies from the list (combatIds stay stable) — except
            # illusions, which stay with isAlive=false until they revive.
            "enemies": [self._enemy_dict(i, e) for i, e in enumerate(self.enemies) if e.in_combat],
        }


class SimClient:
    """AutoSpireClient-compatible interface backed by SimCombat, for use as
    STS2CombatEnv(client=SimClient()) — see docs/modding-approach.md Phase A."""

    def __init__(self, seed: int | None = None):
        self._combat = SimCombat(rng=random.Random(seed))
        self._deck: list[str] | None = None  # None = starter deck

    def set_deck(self, deck: list[str]) -> None:
        self._deck = list(deck)

    def set_potions(self, potions: list) -> None:
        n = MAX_POTION_SLOTS if "POTION_BELT" in self._combat.relics else POTION_SLOTS
        self._combat.potions = (list(potions) + [None] * n)[:n]

    def set_relics(self, relics: set[str], state: dict[str, int]) -> None:
        """The held relics, and the carried-over counters dict (shared, so fights mutate the caller's)."""
        self._combat.relics, self._combat.relic_state = set(relics), state

    def ping(self) -> bool:
        return True

    def state(self) -> dict:
        return {"phase": "combat" if self._combat.in_combat else "map", "inRun": True,
                "player": {"hp": self._combat.player_hp}}

    def combat(self) -> dict:
        return self._combat.combat_dict()

    def exec(self, cmd: str, settle: float = 0.0, timeout: float | None = None, retries: int | None = None) -> dict:
        parts = cmd.split()
        verb = parts[0].lower() if parts else ""
        if verb == "heal":
            self._combat.heal(int(parts[1]) if len(parts) > 1 else 999)
            return {"ok": True}
        if verb == "fight":
            self._combat.fight(parts[1] if len(parts) > 1 else "NIBBITS_WEAK", self._deck)
            return {"ok": True}
        if verb == "newrun":
            self._combat = SimCombat(rng=self._combat.rng)
            return {"ok": True}
        if verb == "play":
            return self._combat.play_card(int(parts[1]), int(parts[2]) if len(parts) > 2 else None)
        if verb == "choose":
            return self._combat.choose_card(int(parts[1]))
        if verb == "choose_discard":
            return self._combat.choose_discard(parts[1])
        if verb == "end":
            return self._combat.end_turn()
        if verb == "potion":
            return self._combat.use_potion(int(parts[1]), int(parts[2]) if len(parts) > 2 else None)
        return {"error": "unknown_command", "cmd": cmd}

    def play(self, hand_index: int, target_id: int | None = None) -> dict:
        return self._combat.play_card(hand_index, target_id)

    def end_turn(self) -> dict:
        return self._combat.end_turn()

    def wait_for(self, predicate, poll_interval: float = 0.0, timeout: float = 0.0) -> dict:
        # The sim resolves synchronously — nothing to poll for.
        combat = self.combat()
        if not predicate(combat):
            raise TimeoutError(f"sim state never satisfied predicate: {combat}")
        return combat

    def full_restart(self, character: str = "IRONCLAD", boot_timeout: float = 0.0) -> None:
        self._combat = SimCombat(rng=self._combat.rng)
