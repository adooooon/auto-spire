"""One Act 1 run between fights: map position, HP, gold, deck, encounters, "?" rooms, shops,
rewards. Fights aren't here; run_env.py plays them with the combat policy and copies HP in and
out. Numbers are from the decompiled source; see docs/game-architecture.md, "Act 1 runs".
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .cards import CARDS, COMMONS, RARES, UNCOMMONS, UPGRADABLE, base_id, starter_deck, upgrade
from .engine import ENCOUNTERS, HIVE_BOSSES, HIVE_ELITES, HIVE_NORMALS, HIVE_WEAK, PLAYER_MAX_HP
from .events import EVENT_ALLOWED, HIVE_EVENT_ALLOWED, MODELED_EVENTS
from .map import ActMap, Node, generate_map
from .potions import POTION_POOL, POTION_SLOTS, POTIONS
from .relics import IRONCLAD_RELICS, NOT_IN_SHOPS, RELIC_POOL, RELICS, relic_rarity

STARTING_GOLD = 99  # Ironclad.StartingGold
GOLD = {"Monster": (10, 20), "Elite": (35, 45), "Boss": (100, 100)}  # EncounterModel.Min/MaxGoldReward
BURNING_BLOOD_HEAL = 6
REST_HEAL = 0.3  # HealRestSiteOption: 30% of max HP
UPGRADE_ODDS_PER_ACT = 0.25  # CardFactory.UpgradedCardOddScaling at A0: act index x this, non-Rares only
MAX_LIFTS = 3  # Girya.maxLifts
EGGS = {"MOLTEN_EGG": "Attack", "TOXIC_EGG": "Skill", "FROZEN_EGG": "Power"}  # TryModifyCardBeingAddedToDeck
CARD_PRICE = {"COMMON": 50, "UNCOMMON": 75, "RARE": 150}  # MerchantCardEntry.GetCost
SHOP_SLOTS = ("Attack", "Attack", "Skill", "Skill", "Power")  # MerchantInventory._coloredCardTypes
REMOVAL_PRICE, REMOVAL_STEP = 75, 25  # MerchantCardRemovalEntry: +25 per removal used
NEXT_RARITY = {"COMMON": "UNCOMMON", "UNCOMMON": "RARE", "RARE": "COMMON"}  # GetNextHighestRarityWithWrapping
POTION_PRICE = {"COMMON": 50, "UNCOMMON": 75, "RARE": 100}  # MerchantPotionEntry.GetCost
SHOP_POTIONS = 3  # MerchantInventory.PopulatePotionEntries
BLOOD_POTION_HEAL = 0.2
RELIC_PRICE = {"COMMON": 175, "UNCOMMON": 225, "RARE": 275, "SHOP": 200}  # RelicModel.MerchantCost
SHOP_RELICS = 3  # MerchantInventory.PopulateRelicEntries: two rolled, then one SHOP
FALL_THROUGH = ("SHOP", "COMMON", "UNCOMMON", "RARE")  # RelicGrabBag.GetAvailableDeque

# The Ironclad pool by rarity. Armaments goes last in COMMON (it isn't in COMMONS) so seeded offers keep their order.
REWARD_POOLS = {"COMMON": COMMONS + ("ARMAMENTS",), "UNCOMMON": UNCOMMONS, "RARE": RARES}

WEAK = tuple(e for e in ENCOUNTERS if e.endswith("_WEAK"))
ELITES = tuple(e for e in ENCOUNTERS if e.endswith("_ELITE"))
BOSSES = tuple(e for e in ENCOUNTERS if e.endswith("_BOSS"))
ALL_BOSSES = BOSSES + HIVE_BOSSES
NORMALS = tuple(e for e in ENCOUNTERS if e not in WEAK + ELITES + BOSSES)
TAGS = {"NIBBITS_WEAK": {"Nibbit"}, "SLIMES_WEAK": {"Slimes"}, "SHRINKER_BEETLE_WEAK": {"Shrinker"},  # EncounterModel.Tags
        "FUZZY_WURM_CRAWLER_WEAK": {"Crawler"}, "SLIMES_NORMAL": {"Slimes"}, "OVERGROWTH_CRAWLERS": {"Crawler", "Shrinker"},
        "FLYCONID_NORMAL": {"Mushroom", "Slimes"}, "SNAPPING_JAXFRUIT_NORMAL": {"Mushroom"},
        "BOWLBUGS_WEAK": {"Workers"}, "BOWLBUGS_NORMAL": {"Workers"}, "SLUMBERING_BEETLE_NORMAL": {"Workers"},
        "CHOMPERS_NORMAL": {"Chomper"}, "EXOSKELETONS_WEAK": {"Exoskeletons"}, "EXOSKELETONS_NORMAL": {"Exoskeletons"}}


# Byrdonis Egg and Spoils Map are Unplayable cards that pay off outside what Act 1 models. A Wound does the same
# in a fight. ponytail: shares Wound's observation slot; give them their own ids if the egg's hatch or Act 2 is modeled.
QUEST_CARD = "WOUND"


def card_type(card_id: str) -> str:
    return CARDS[card_id].type


class RarityOdds:
    """CardRarityOdds.cs at ascension 0. Regular fights: Rare 3% + an offset that starts at -5%,
    grows 1% per non-Rare roll (cap 40%) and resets on a Rare; Uncommon 37%. Elites: Rare 10%
    + offset, Uncommon 40%. One instance per run (the offset carries)."""

    def __init__(self):
        self.offset = -0.05

    def roll(self, rng: random.Random, elite: bool = False, boss: bool = False) -> str:
        """boss: CardRarityOddsType.BossEncounter, always Rare (r < 1), so the offset resets."""
        r, rare = rng.random(), 1.0 if boss else (0.10 if elite else 0.03) + self.offset
        if r < rare:
            self.offset = -0.05
            return "RARE"
        self.offset = min(self.offset + 0.01, 0.4)
        return "UNCOMMON" if r < rare + (0.40 if elite else 0.37) else "COMMON"

    def roll_base(self, rng: random.Random) -> str:
        """RollWithBaseOdds(RegularEncounter), used for CardCreationSource.Other (Orrery): no offset, none changed."""
        r = rng.random()
        return "RARE" if r < 0.03 else "UNCOMMON" if r < 0.37 else "COMMON"

    def roll_shop(self, rng: random.Random) -> str:
        """CardRarityOddsType.Shop, RollWithoutChangingFutureOdds: Rare 9% + offset, Uncommon 37%."""
        r, rare = rng.random(), 0.09 + self.offset
        return "RARE" if r < rare else "UNCOMMON" if r < rare + 0.37 else "COMMON"


def offer(rng: random.Random, odds: RarityOdds, elite: bool = False, boss: bool = False,
          base: bool = False, act: int = 0) -> list[str]:
    """CardFactory.CreateForReward: 3 cards, no repeats, each upgraded with RollForUpgrade's chance (act x 0.25 for
    non-Rares; no roll is drawn at 0, so Act 1 seeds are unchanged). base: not an encounter reward, offset untouched."""
    out: list[str] = []
    for _ in range(3):
        rarity = odds.roll_base(rng) if base else odds.roll(rng, elite, boss)
        seen = {base_id(c) for c in out}  # the game blacklists by base card
        card = rng.choice([c for c in REWARD_POOLS[rarity] if c not in seen])
        out.append(card)
        if rarity != "RARE" and act and card in UPGRADABLE and rng.random() <= act * UPGRADE_ODDS_PER_ACT:
            out[-1] = upgrade(card)
    return out



def potion_rarity(pid: str) -> str:
    return next(r for r, ids in POTION_POOL.items() if pid in ids)


def roll_potions(rng: random.Random, n: int = 1) -> list[str]:
    """PotionFactory.CreateRandomPotion: per potion Rare <= 0.10, Uncommon <= 0.35, else Common,
    uniform within the rarity; no repeats within one call."""
    left = {r: list(ids) for r, ids in POTION_POOL.items()}
    out: list[str] = []
    for _ in range(n):
        x = rng.random()
        pool = left["RARE" if x <= 0.10 else "UNCOMMON" if x <= 0.35 else "COMMON"]
        out.append(pool.pop(rng.randrange(len(pool))))
    return out


class PotionOdds:
    """PotionRewardOdds: a drop when random < chance (+0.25 x 0.5 in elite rooms); the chance starts at
    0.4 and falls 0.1 after a drop, rises 0.1 after none, so drops converge on half of fights."""

    def __init__(self):
        self.value = 0.4

    def roll(self, rng, elite: bool = False, force: bool = False) -> bool:
        """force: White Beast Statue (ShouldForcePotionReward); the random is still drawn."""
        if rng.random() < self.value + (0.125 if elite else 0.0) or force:
            self.value -= 0.1
            return True
        self.value += 0.1
        return False

def _grab(rng: random.Random, bag: list[str], pool: tuple[str, ...], last: str | None) -> str:
    """GrabBag.GrabAndRemove via AddWithoutRepeatingTags: avoid the last encounter and its tags."""
    if not bag:
        bag.extend(pool)
    ok = [e for e in bag if e != last and not (TAGS.get(e, set()) & TAGS.get(last, set()))]
    e = rng.choice(ok or bag)
    bag.remove(e)
    return e


def encounter_queue(rng: random.Random, rooms: int = 15, weak: int = 3, weak_pool: tuple = WEAK, normal_pool: tuple = NORMALS,
                    elite_pool: tuple = ELITES, boss_pool: tuple = BOSSES) -> tuple[list[str], list[str], str]:
    """ActModel.GenerateRooms: monster rooms draw 3 weak then regular encounters, elites from
    their own bag; the boss is fixed at run start."""
    normals: list[str] = []
    bag: list[str] = []
    for _ in range(weak):
        normals.append(_grab(rng, bag, weak_pool, normals[-1] if normals else None))
    bag = []
    for _ in range(weak, rooms):
        normals.append(_grab(rng, bag, normal_pool, normals[-1]))
    elites: list[str] = []
    bag = []
    for _ in range(15):
        elites.append(_grab(rng, bag, elite_pool, elites[-1] if elites else None))
    return normals, elites, rng.choice(boss_pool)


class UnknownOdds:
    """UnknownMapPointOdds.Roll: a rolled type resets to its base odds and each unrolled allowed
    type grows by its base, so "?" rooms rarely stay events forever. Elite odds are -1: never.
    ponytail: the first-run tutorial override (events for the first two "?") is left out."""
    BASE = {"Monster": 0.10, "Treasure": 0.02, "Shop": 0.03}

    def __init__(self):
        self.odds = dict(self.BASE)

    def roll(self, rng: random.Random, blacklist: set[str]) -> str:
        r, acc, room = rng.random(), 0.0, "Event"
        for t, p in self.odds.items():
            if t in blacklist:
                continue
            acc += p
            if r <= acc:
                room = t
                break
        for t, base in self.BASE.items():
            if t == room:
                self.odds[t] = base
            elif t not in blacklist:
                self.odds[t] += base
        return room


def roll_relic_rarity(rng: random.Random) -> str:
    """RelicFactory.RollRarity."""
    x = rng.random()
    return "COMMON" if x < 0.5 else "UNCOMMON" if x < 0.83 else "RARE"


class RelicBags:
    """RelicGrabBag: a player bag and a shared (treasure) bag, each a shuffled list per rarity. A pulled
    relic leaves both. A rarity with nothing that passes `allowed` falls through SHOP -> COMMON ->
    UNCOMMON -> RARE. Unmodeled relics are in the bags too, so the odds stay honest."""

    def __init__(self, rng: random.Random):
        self.bags = {}
        for bag in ("player", "shared"):
            # RunManager.InitializeNewRun: the shared bag is SharedRelicPool only; the player bag adds the character pool
            self.bags[bag] = {r: [x for x in ids if bag == "player" or x not in IRONCLAD_RELICS] for r, ids in RELIC_POOL.items()}
            for ids in self.bags[bag].values():
                rng.shuffle(ids)

    def pull(self, bag: str, rarity: str, from_back: bool = False, allowed=None) -> str:
        allowed = allowed or (lambda r: True)
        for rar in FALL_THROUGH[FALL_THROUGH.index(rarity):]:
            ids = [r for r in self.bags[bag][rar] if allowed(r)]
            if ids:
                break
        else:
            raise AssertionError("relic bag drained")  # Act 1 can't use up 122
        relic = ids[-1 if from_back else 0]
        for b in self.bags.values():
            for l in b.values():
                if relic in l:
                    l.remove(relic)
        return relic


@dataclass
class Shop:
    cards: list[str | None]  # one per SHOP_SLOTS entry; None once bought
    prices: list[int]
    removal_price: int
    removal_used: bool = False
    relics: list[str | None] = field(default_factory=lambda: [None] * SHOP_RELICS)  # None once bought
    relic_prices: list[int] = field(default_factory=lambda: [0] * SHOP_RELICS)
    potions: list[str | None] = field(default_factory=lambda: [None] * SHOP_POTIONS)  # None once bought
    potion_prices: list[int] = field(default_factory=lambda: [0] * SHOP_POTIONS)


def egg_upgrade(card: str, relics) -> str:
    """EggRelicHelper.UpgradeValidCards: the Egg of a card's type upgrades it in offers and shops, any rarity."""
    return upgrade(card) if any(r in relics and CARDS[card].type == t for r, t in EGGS.items()) else card


def stock_card(rng: random.Random, odds: RarityOdds, ctype: str, taken: list, relics=()) -> tuple[str, int]:
    """One card slot (MerchantCardEntry.Populate): a card of `ctype` not in `taken`, and its full price
    (by rarity, so an Egg's upgrade doesn't change it). Shops roll no upgrades; only Eggs upgrade."""
    taken = [base_id(c) for c in taken]
    rarity = odds.roll_shop(rng)
    for _ in range(3):  # CardFactory.GetNextAllowedRarity
        pool = [c for c in REWARD_POOLS[rarity] if card_type(c) == ctype and c not in taken]
        if pool:
            break
        rarity = NEXT_RARITY[rarity]
    card = rng.choice(pool)
    return egg_upgrade(card, relics), round(CARD_PRICE[rarity] * rng.uniform(0.95, 1.05))  # Mathf.RoundToInt: banker's, like round()


def stock_relic(rng: random.Random, bags: RelicBags, rarity: str) -> tuple[str, int]:
    relic = bags.pull("player", rarity, True, lambda x: x not in NOT_IN_SHOPS)
    return relic, round(RELIC_PRICE[relic_rarity(relic)] * rng.uniform(0.85, 1.15))


def potion_price(rng: random.Random, pid: str) -> int:
    return round(POTION_PRICE[potion_rarity(pid)] * rng.uniform(0.95, 1.05))


def make_shop(rng: random.Random, odds: RarityOdds, removals: int, bags: RelicBags, relics=()) -> Shop:
    """MerchantInventory.PopulateCharacterCardEntries: 5 typed slots, no repeats, one half price.
    Then 3 relics (two rolled, one SHOP, pulled from the back of the player bag) and 3 potions.
    Colorless cards aren't stocked yet."""
    sale = rng.randrange(len(SHOP_SLOTS))
    cards: list[str | None] = []
    prices: list[int] = []
    for i, ctype in enumerate(SHOP_SLOTS):
        card, price = stock_card(rng, odds, ctype, cards, relics)
        cards.append(card)
        prices.append(price // 2 if i == sale else price)
    rarities = [roll_relic_rarity(rng), roll_relic_rarity(rng), "SHOP"]
    relics, relic_prices = [], []
    for r in rarities:
        relic, price = stock_relic(rng, bags, r)
        relics.append(relic)
        relic_prices.append(price)
    potions = roll_potions(rng, SHOP_POTIONS)
    potion_prices = [potion_price(rng, p) for p in potions]
    return Shop(cards, prices, REMOVAL_PRICE + REMOVAL_STEP * removals, relics=relics, relic_prices=relic_prices,
                potions=potions, potion_prices=potion_prices)


class Run:
    """An Act 1 run between fights. HP lives here; run_env copies it into each SimCombat and back."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.act = 0
        self.normal_pool, self.elite_pool, self.event_allowed = NORMALS, ELITES, EVENT_ALLOWED
        self.map: ActMap = generate_map(rng)
        self.normals, self.elites, self.boss = encounter_queue(rng)
        self.bags = RelicBags(rng)  # after the map and queue, so a seed keeps its map
        self.relics: set[str] = set()
        self.relic_state: dict[str, int] = {}  # carried into the fight env
        self.relic_log: list[tuple[str, str]] = []  # (id, "elite" | "treasure" | "shop")
        self.node: Node = self.map.start
        self.hp = self.max_hp = PLAYER_MAX_HP
        self.gold, self.deck, self.removals, self.spent = STARTING_GOLD, starter_deck(), 0, 0
        self.card_odds, self.unknown_odds = RarityOdds(), UnknownOdds()
        self.last_room: str | None = None
        self.elites_fought = 0
        self.shop: Shop | None = None
        self.potions: list[str | None] = [None] * POTION_SLOTS
        self.potion_odds = PotionOdds()
        self.potion_drop: str | None = None  # the potion next_reward last surfaced, until taken or skipped
        self.pending: list[tuple[str, object]] = []  # ("cards", offer) | ("potion", pid), in order
        self.events = sorted(EVENT_ALLOWED)
        rng.shuffle(self.events)  # ActModel.GenerateRooms
        self.events_visited = 0  # RoomSet.eventsVisited
        self.events_seen: list[str] = []  # every event entered, modeled or not
        self.event: str | None = None  # the modeled event waiting on a choice
        self.event_opts: list[tuple[int, int, int]] = []  # each option's (HP loss, gold gain, max HP gain)
        self.event_log: list[tuple] = []  # (event, option, hp, max_hp, gold) at each choice
        self.fight_hit = True  # the last fight let a blockable hit through (Lava Lamp); run_env.play sets it
        self.lava_ok = False  # Lava Lamp lights the card offers made inside win()
        self.bridge_card: int | None = None  # Slippery Bridge: deck index of the card at risk
        self.bridge_skipped: set[int] = set()

    def gain_gold(self, amount: int) -> None:
        """PlayerCmd.GainGold: Bowler Hat on the decimal, then truncated; then Dragon Fruit."""
        amount = int(amount * 1.25 if "BOWLER_HAT" in self.relics else amount)
        if amount <= 0:
            return
        self.gold += amount
        if "DRAGON_FRUIT" in self.relics:
            self.gain_max_hp(1)

    def gain_max_hp(self, amount: int) -> None:
        self.max_hp += amount
        self.hp += amount

    def heal(self, amount: int) -> None:
        self.hp = min(self.max_hp, self.hp + amount)

    def lose_hp(self, amount: int) -> None:
        """Event damage (CreatureCmd.Damage). Tungsten Rod works anywhere; Beating Remnant only in combat."""
        self.hp -= max(0, amount - ("TUNGSTEN_ROD" in self.relics))
        if self.hp <= 0:
            self.hp = 0
            if "LIZARD_TAIL" in self.relics and not self.relic_state.get("lizard_used"):  # ShouldDieLate
                self.relic_state["lizard_used"] = 1
                self.hp = max(1, self.max_hp * 50 // 100)

    def offer(self, **kw) -> list[str]:
        """offer() as the player sees it: Eggs (any rarity) and a lit Lava Lamp (after a fight with no hit) upgrade the cards."""
        return [upgrade(c) if self.lava_ok else egg_upgrade(c, self.relics) for c in offer(self.rng, self.card_odds, act=self.act, **kw)]

    def add_card(self, card: str) -> None:
        if any(r in self.relics and CARDS[card].type == t for r, t in EGGS.items()):
            card = upgrade(card)  # Molten / Toxic / Frozen Egg; also covers shop cards (Eggs upgrade shop stock at creation, so this is a no-op there)
        self.deck.append(card)
        if "LUCKY_FYSH" in self.relics:
            self.gain_gold(15)
        if "BOOK_OF_FIVE_RINGS" in self.relics:
            n = self.relic_state["book_of_five_rings"] = self.relic_state.get("book_of_five_rings", 0) + 1
            if n % 5 == 0:
                self.heal(20)

    def price(self, raw: int) -> int:
        """MerchantEntry.Cost: the discounts multiply, then truncate."""
        pct = (50 if "MEMBERSHIP_CARD" in self.relics else 100) * (80 if "THE_COURIER" in self.relics else 100) // 100
        return raw * pct // 100

    def next_reward(self) -> tuple[str, object] | None:
        """Pop pending until something needs a decision. An unmodeled potion is used up and skipped."""
        while self.pending:
            kind, what = self.pending.pop(0)
            if kind == "cards":
                return kind, what
            if what in POTIONS:
                self.potion_drop = what
                return kind, what
            self.potion_drop = None
        return None

    def choices(self) -> list[Node]:
        return sorted(self.node.children, key=lambda n: n.col)

    def enter(self, node: Node) -> str:
        """Move to a child of the current node and resolve its room type (shops stock; a rest site waits for rest())."""
        assert node in self.node.children, (node, self.node)
        room = node.type
        if room == "Unknown":  # RunManager.BuildRoomTypeBlacklist
            no_shop = self.last_room == "Shop" or (node.children and all(c.type == "Shop" for c in node.children))
            block = {"Shop"} if no_shop else set()
            if "JUZU_BRACELET" in self.relics:
                block.add("Monster")
            room = self.unknown_odds.roll(self.rng, block)
        self.node, self.last_room = node, room
        if room == "RestSite":
            if "ETERNAL_FEATHER" in self.relics:  # AfterRoomEntered, before the rest option is chosen
                self.heal(3 * (len(self.deck) // 5))
            if "VENERABLE_TEA_SET" in self.relics:
                self.relic_state["tea_set"] = 1
            if "TINY_MAILBOX" in self.relics:
                self.pending += [("potion", roll_potions(self.rng)[0]) for _ in range(2)]
        elif room == "Shop":
            if "MEAL_TICKET" in self.relics:
                self.heal(15)
            self.shop = make_shop(self.rng, self.card_odds, self.removals, self.bags, self.relics)
        elif room == "Event":
            self.start_event(self.pull_event())
        elif room == "Treasure":
            # OneOffSynchronizer.cs:133: NextInt(42, 53), upper bound exclusive
            relic = self.bags.pull("shared", roll_relic_rarity(self.rng))
            self.gain_gold(self.rng.randint(42, 52))  # the gold is awarded before the relic is picked up
            self.obtain(relic, "treasure")
        if node.type == "Unknown" and "PLANISPHERE" in self.relics:
            self.heal(5)
        return room

    def pull_event(self) -> str:
        """RoomSet.EnsureNextEventIsValid: skip what's not allowed or already seen; if nothing's left, repeat."""
        n = len(self.events)
        for _ in range(n):
            event = self.events[self.events_visited % n]
            if event not in self.events_seen and self.event_allowed[event](self):
                break
            self.events_visited += 1
        event = self.events[self.events_visited % n]
        self.events_visited += 1  # RoomSet.MarkVisited
        self.events_seen.append(event)
        return event

    def start_event(self, event: str) -> None:
        """Roll the event's variables (CalculateVars). An unmodeled event leaves self.event None: an empty room."""
        if event not in MODELED_EVENTS:
            return
        self.event = event
        if event == "BYRDONIS_NEST":
            self.event_opts = [(0, 0, 7), (0, 0, 0)]
        elif event == "JUNGLE_MAZE_ADVENTURE":  # decimal gold: gain_gold truncates it
            self.event_opts = [(18, 150 + self.rng.uniform(-15, 15), 0), (0, 50 + self.rng.uniform(-15, 15), 0)]
        elif event == "SLIPPERY_BRIDGE":
            self.bridge_card, self.bridge_skipped = None, set()
            self._bridge_roll()
            self.event_opts = [(0, 0, 0), (3, 0, 0)]
        elif event == "SUNKEN_STATUE":
            self.event_opts = [(0, 0, 0), (7, 111 + self.rng.randint(-10, 10), 0)]
        else:  # THE_LEGENDS_WERE_TRUE
            self.event_opts = [(0, 0, 0), (8, 0, 0)]

    def _bridge_roll(self) -> None:
        """SlipperyBridge.GetNewRandomCard: skipped copies stay out unless nothing else is left."""
        cur = self.bridge_card
        if cur is None:
            pool = [i for i, c in enumerate(self.deck) if CARDS[c].rarity != "Basic"]
        else:
            self.bridge_skipped.add(cur)
            pool = [i for i, c in enumerate(self.deck) if c != self.deck[cur]]
        self.bridge_card = self.rng.choice([i for i in pool if i not in self.bridge_skipped] or range(len(self.deck)))

    def choose_event(self, option: int) -> None:
        """Apply an option. self.event stays set while the event goes on; check hp for a death."""
        event, (hp, gold, max_hp) = self.event, self.event_opts[option]
        self.event_log.append((event, option, self.hp, self.max_hp, self.gold))
        if event == "SLIPPERY_BRIDGE" and option == 1:  # hold on: pay, and a new card is at risk, for 1 HP more
            self.lose_hp(hp)
            self.event_opts = [(0, 0, 0), (hp + 1, 0, 0)]
            self._bridge_roll()
            return
        self.event = None
        if event == "SLIPPERY_BRIDGE":
            del self.deck[self.bridge_card]
        elif event == "BYRDONIS_NEST":
            if option == 0:
                self.gain_max_hp(max_hp)
            else:
                self.add_card(QUEST_CARD)
        elif event == "JUNGLE_MAZE_ADVENTURE":  # damage first
            self.lose_hp(hp)
            if self.hp > 0:
                self.gain_gold(gold)
        elif event == "SUNKEN_STATUE":  # gold first
            if option == 0:
                self.obtain("SWORD_OF_STONE", "event")  # ponytail: needs 5 elites to do anything; Act 1 never has them
            else:
                self.gain_gold(gold)
                self.lose_hp(hp)
        elif option == 0:  # The Legends Were True
            self.add_card(QUEST_CARD)
        else:
            self.lose_hp(hp)
            # a uniform pick over both pools, unlike rolled drops
            self.pending.append(("potion", self.rng.choice([p for pool in POTION_POOL.values() for p in pool])))

    def encounter(self, room: str) -> str:
        if room == "Boss":
            return self.boss
        queue, pool = (self.elites, self.elite_pool) if room == "Elite" else (self.normals, self.normal_pool)
        return queue.pop(0) if queue else self.rng.choice(pool)

    def win(self, room: str) -> list[str]:
        """_win with Lava Lamp lit for its card offers when the fight (run.fight_hit, set by the env) took no hit."""
        self.lava_ok = "LAVA_LAMP" in self.relics and not self.fight_hit
        try:
            return self._win(room)
        finally:
            self.lava_ok = False

    def _win(self, room: str) -> list[str]:
        """After a won fight: Burning Blood, gold, a potion roll (sets potion_drop) and the card offer.
        After the boss the run ends, so neither the potion nor the card offer is rolled."""
        self.heal(BURNING_BLOOD_HEAL)
        self.gain_gold(self.rng.randint(*GOLD[room]))
        if "AMETHYST_AUBERGINE" in self.relics:
            self.gain_gold(15)
        if room == "Boss" and self.act == 1:  # where the sim's run ends
            return []
        if room == "Boss":  # RewardsSet: gold, a potion roll and an all-Rare card offer, and no relic
            potion = roll_potions(self.rng)[0] if self.potion_odds.roll(self.rng, False, False) else None
            if potion:
                self.pending.append(("potion", potion))
            return self.offer(boss=True)
        # Rewards are generated (and modified by held relics) before the elite's relic is picked up.
        force, wheel, star = (r in self.relics for r in ("WHITE_BEAST_STATUE", "PRAYER_WHEEL", "WHITE_STAR"))
        if room == "Elite":
            self.obtain(self.bags.pull("player", roll_relic_rarity(self.rng)), "elite")
        potion = roll_potions(self.rng)[0] if self.potion_odds.roll(self.rng, room == "Elite", force) else None
        offered = self.offer(elite=room == "Elite")
        if room == "Monster" and wheel:
            self.pending.append(("cards", self.offer()))
        if room == "Elite" and star:
            self.pending.append(("cards", self.offer(boss=True)))
        if potion:
            self.pending.append(("potion", potion))
        return offered

    def next_act(self) -> None:
        """RunManager.EnterAct, then Act 2's Ancient: a new map, rooms and events, healed to full (A0). Its relic
        offer isn't modeled. Deck, relics, potions, gold, rarity and potion odds carry over."""
        self.act = 1
        self.map = generate_map(self.rng, hive=True)
        self.node = self.map.start
        self.normal_pool, self.elite_pool, self.event_allowed = HIVE_NORMALS, HIVE_ELITES, HIVE_EVENT_ALLOWED
        self.normals, self.elites, self.boss = encounter_queue(self.rng, 14, 2, HIVE_WEAK, HIVE_NORMALS, HIVE_ELITES, HIVE_BOSSES)
        self.events = sorted(HIVE_EVENT_ALLOWED)
        self.rng.shuffle(self.events)
        self.events_visited = 0
        self.unknown_odds, self.last_room, self.shop = UnknownOdds(), None, None
        self.hp = self.max_hp

    def buy(self, slot: int) -> None:
        s = self.shop
        card, price = s.cards[slot], self.price(s.prices[slot])
        assert card in CARDS and self.gold >= price, (card, price, self.gold)
        self.gold -= price
        self.spent += price
        self.add_card(card)
        if "THE_COURIER" in self.relics:  # RestockAfterPurchase: same type, not on sale; the bought card still counts as taken
            s.cards[slot], s.prices[slot] = stock_card(self.rng, self.card_odds, SHOP_SLOTS[slot], [c for c in s.cards if c], self.relics)
        else:
            s.cards[slot] = None

    def upgrade_card(self, base: str) -> None:
        """CardCmd.Upgrade on one un-upgraded copy of `base` in the deck."""
        self.deck[self.deck.index(base)] = upgrade(base)

    def rest_options(self) -> list[str]:
        """RestSiteOptions in the game's order: Heal, Smith (enabled iff something is upgradable), Girya's Lift
        (until 3 lifts), Shovel's Dig."""
        return (["HEAL"] + ["SMITH"] * any(c in UPGRADABLE for c in self.deck)
                + ["LIFT"] * ("GIRYA" in self.relics and self.relic_state.get("girya", 0) < MAX_LIFTS)
                + ["DIG"] * ("SHOVEL" in self.relics))

    def rest(self, option: str, card: str | None = None) -> None:
        """Choose a rest site option. card: the base id to Smith."""
        assert option in self.rest_options(), (option, self.rest_options())
        if option == "HEAL":
            self.heal(int(self.max_hp * REST_HEAL) + (15 if "REGAL_PILLOW" in self.relics else 0))
        elif option == "SMITH":
            self.upgrade_card(card)
        elif option == "LIFT":
            self.relic_state["girya"] = self.relic_state.get("girya", 0) + 1
        else:  # DigRestSiteOption: PullNextRelicFromFront with a rolled rarity
            self.obtain(self.bags.pull("player", roll_relic_rarity(self.rng)), "dig")

    def remove(self, card: str) -> None:
        s = self.shop
        price = self.price(s.removal_price)
        card = card if card in self.deck else card + "+"  # the policy names base ids; an upgraded copy goes if no plain one is left
        assert not s.removal_used and self.gold >= price and card in self.deck
        self.gold -= price
        self.spent += price
        self.deck.remove(card)
        self.removals += 1
        s.removal_used = True

    def take_potion(self, slot: int) -> None:
        """Put potion_drop in `slot`, discarding whatever was there."""
        assert self.potion_drop in POTIONS, self.potion_drop
        self.potions[slot], self.potion_drop = self.potion_drop, None

    def buy_potion(self, k: int) -> None:
        s = self.shop
        pid, price = s.potions[k], self.price(s.potion_prices[k])
        assert pid in POTIONS and self.gold >= price and None in self.potions, (pid, price, self.gold, self.potions)
        self.gold -= price
        self.spent += price
        self.potions[self.potions.index(None)] = pid
        s.potions[k] = None
        if "THE_COURIER" in self.relics:
            s.potions[k] = roll_potions(self.rng)[0]
            s.potion_prices[k] = potion_price(self.rng, s.potions[k])

    def obtain(self, relic: str, source: str) -> None:
        self.relics.add(relic)
        self.relic_log.append((relic, source))
        if relic == "STRAWBERRY":
            self.gain_max_hp(7)
        elif relic == "PEAR":
            self.gain_max_hp(10)
        elif relic == "MANGO":
            self.gain_max_hp(14)
        elif relic == "LEES_WAFFLE":
            self.gain_max_hp(7)
            self.heal(self.max_hp)
        elif relic == "OLD_COIN":
            self.gain_gold(300)
        elif relic == "POTION_BELT":
            self.potions += [None] * 2
        elif relic in ("WHETSTONE", "WAR_PAINT"):  # 2 random un-upgraded Attacks / Skills, upgraded now
            kind = "Attack" if relic == "WHETSTONE" else "Skill"
            ups = [i for i, c in enumerate(self.deck) if c in UPGRADABLE and CARDS[c].type == kind]
            for i in self.rng.sample(ups, min(2, len(ups))):
                self.deck[i] = upgrade(self.deck[i])
        elif relic == "ORRERY":
            self.pending += [("cards", self.offer(base=True)) for _ in range(5)]
        elif relic == "CAULDRON":
            self.pending += [("potion", roll_potions(self.rng)[0]) for _ in range(5)]

    def buy_relic(self, k: int) -> None:
        s = self.shop
        relic, price = s.relics[k], self.price(s.relic_prices[k])  # before obtain: Membership Card doesn't discount itself
        assert relic in RELICS and self.gold >= price, (relic, price, self.gold)
        self.gold -= price
        self.spent += price
        s.relics[k] = None
        if "THE_COURIER" in self.relics:
            s.relics[k], s.relic_prices[k] = stock_relic(self.rng, self.bags, roll_relic_rarity(self.rng))
        self.obtain(relic, "shop")

    def drink(self, slot: int) -> None:
        """Blood Potion between fights (PotionUsage.AnyTime): 20% of max HP, truncated."""
        assert self.potions[slot] == "BLOOD_POTION", self.potions
        self.hp = min(self.max_hp, self.hp + int(self.max_hp * BLOOD_POTION_HEAL))
        self.potions[slot] = None
