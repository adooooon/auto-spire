"""Potions: the 12 the sim models, and every id the shared and Ironclad pools can drop.

Ids are the game's ModelId entries (UPPER_SNAKE of the class name). Effects live in
SimCombat.use_potion; drop and shop rules in sim/act.py. Unmodeled potions still drop and
stock shops (so the odds stay right) but can't be taken.
"""
POTION_SLOTS = 3  # Player.initialMaxPotionSlotCount

# Modeled potions -> target kind (PotionModel.TargetType: AnyPlayer/Self -> "self", AnyEnemy -> "enemy").
POTIONS = {
    "BLOCK_POTION": "self", "DEXTERITY_POTION": "self", "SPEED_POTION": "self", "ENERGY_POTION": "self",
    "STRENGTH_POTION": "self", "FLEX_POTION": "self", "SWIFT_POTION": "self", "BLOOD_POTION": "self",
    "FIRE_POTION": "enemy", "VULNERABLE_POTION": "enemy", "WEAK_POTION": "enemy", "EXPLOSIVE_AMPOULE": "all",
}
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
