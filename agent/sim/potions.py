"""Potions: every id the shared and Ironclad pools can drop (USABLE: the ones with an effect so far).

Ids are the game's ModelId entries (UPPER_SNAKE of the class name). Effects live in
SimCombat.use_potion; drop and shop rules in sim/act.py. Pending potions still drop and
stock shops (so the odds stay right) but can't be taken.
"""
POTION_SLOTS = 3  # Player.initialMaxPotionSlotCount

# Every potion -> target kind (PotionModel.TargetType: Self/AnyPlayer -> "self", AnyEnemy -> "enemy",
# AllEnemies -> "all"). Fairy in a Bottle is Automatic (never used by hand): "auto".
POTIONS = {
    "ASHWATER": "self", "ATTACK_POTION": "self", "BEETLE_JUICE": "enemy", "BLESSING_OF_THE_FORGE": "self",
    "BLOCK_POTION": "self", "BLOOD_POTION": "self", "BOTTLED_POTENTIAL": "self", "CLARITY": "self",
    "COLORLESS_POTION": "self", "CURE_ALL": "self", "DEXTERITY_POTION": "self", "DISTILLED_CHAOS": "self",
    "DROPLET_OF_PRECOGNITION": "self", "DUPLICATOR": "self", "ENERGY_POTION": "self", "ENTROPIC_BREW": "self",
    "EXPLOSIVE_AMPOULE": "all", "FAIRY_IN_A_BOTTLE": "auto", "FIRE_POTION": "enemy", "FLEX_POTION": "self",
    "FORTIFIER": "self", "FRUIT_JUICE": "self", "FYSH_OIL": "self", "GAMBLERS_BREW": "self",
    "GIGANTIFICATION_POTION": "self", "HEART_OF_IRON": "self", "LIQUID_BRONZE": "self", "LIQUID_MEMORIES": "self",
    "LUCKY_TONIC": "self", "MAZALETHS_GIFT": "self", "OROBIC_ACID": "self", "POTION_OF_BINDING": "all",
    "POWDERED_DEMISE": "enemy", "POWER_POTION": "self", "RADIANT_TINCTURE": "self", "REGEN_POTION": "self",
    "SHACKLING_POTION": "all", "SHIP_IN_A_BOTTLE": "self", "SKILL_POTION": "self", "SNECKO_OIL": "self",
    "SOLDIERS_STEW": "self", "SPEED_POTION": "self", "STABLE_SERUM": "self", "STRENGTH_POTION": "self",
    "SWIFT_POTION": "self", "TOUCH_OF_INSANITY": "self", "VULNERABLE_POTION": "enemy", "WEAK_POTION": "enemy",
}
# Potions whose effect isn't written yet (plan 2b, tasks 2-4 remove their ids). They still drop and stock shops, but
# the run, env and live bridge skip them (use USABLE, not POTIONS, to ask "can it be held and used?").
PENDING = frozenset({
    "ASHWATER", "ATTACK_POTION", "COLORLESS_POTION", "DROPLET_OF_PRECOGNITION", "GAMBLERS_BREW", "LIQUID_MEMORIES",
    "POWER_POTION", "SKILL_POTION", "TOUCH_OF_INSANITY"})
USABLE = {p: k for p, k in POTIONS.items() if p not in PENDING}
# PotionUsage.AnyTime (the rest are CombatOnly; Fairy in a Bottle is Automatic).
ANY_TIME = frozenset({"BLOOD_POTION", "FRUIT_JUICE", "ENTROPIC_BREW"})
# CanBeGeneratedInCombat is false.
NOT_IN_COMBAT_GEN = frozenset({"REGEN_POTION", "FAIRY_IN_A_BOTTLE", "FRUIT_JUICE"})
POTION_IDS = sorted(POTIONS)

# SharedPotionPool + IroncladPotionPool (Ironclad4Epoch: Blood Potion, Ashwater, Soldier's Stew), by rarity.
POTION_POOL = {
    "COMMON": ("ATTACK_POTION", "BLOCK_POTION", "COLORLESS_POTION", "DEXTERITY_POTION", "ENERGY_POTION",
               "EXPLOSIVE_AMPOULE", "FIRE_POTION", "FLEX_POTION", "POWER_POTION", "SKILL_POTION", "SPEED_POTION",
               "STRENGTH_POTION", "SWIFT_POTION", "VULNERABLE_POTION", "WEAK_POTION", "BLOOD_POTION"),
    "UNCOMMON": ("BLESSING_OF_THE_FORGE", "CLARITY", "CURE_ALL", "DUPLICATOR", "FORTIFIER", "FYSH_OIL",
                 "GAMBLERS_BREW", "HEART_OF_IRON", "LIQUID_BRONZE", "POTION_OF_BINDING", "POWDERED_DEMISE",
                 "RADIANT_TINCTURE", "REGEN_POTION", "STABLE_SERUM", "TOUCH_OF_INSANITY", "ASHWATER"),
    "RARE": ("BEETLE_JUICE", "BOTTLED_POTENTIAL", "DISTILLED_CHAOS", "DROPLET_OF_PRECOGNITION", "ENTROPIC_BREW",
             "FAIRY_IN_A_BOTTLE", "FRUIT_JUICE", "GIGANTIFICATION_POTION", "LIQUID_MEMORIES", "LUCKY_TONIC",
             "MAZALETHS_GIFT", "OROBIC_ACID", "SHACKLING_POTION", "SHIP_IN_A_BOTTLE", "SNECKO_OIL", "SOLDIERS_STEW"),
}
MAX_POTION_SLOTS = 5  # with Potion Belt


def random_potion(rng, in_combat: bool) -> str:
    """PotionFactory.CreateRandomPotion(InCombat): one NextFloat picks the rarity (<= 0.1 Rare, <= 0.35 Uncommon, else
    Common), then a uniform potion of it. In combat, potions that can't be generated there are left out."""
    x = rng.random()
    pool = POTION_POOL["RARE" if x <= 0.1 else "UNCOMMON" if x <= 0.35 else "COMMON"]
    if in_combat:
        pool = [p for p in pool if p not in NOT_IN_COMBAT_GEN]
    return rng.choice(pool)
