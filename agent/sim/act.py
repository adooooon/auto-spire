"""One Act 1 run between fights: map position, HP, gold, deck, encounters, "?" rooms, shops,
rewards. Fights aren't here; run_env.py plays them with the combat policy and copies HP in and
out. Numbers are from the decompiled source; see docs/game-architecture.md, "Act 1 runs".
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from .cards import CARDS, COMMONS, RARES, UNCOMMONS, starter_deck
from .engine import ENCOUNTERS, PLAYER_MAX_HP
from .map import ActMap, Node, generate_map

STARTING_GOLD = 99  # Ironclad.StartingGold
GOLD = {"Monster": (10, 20), "Elite": (35, 45), "Boss": (100, 100)}  # EncounterModel.Min/MaxGoldReward
BURNING_BLOOD_HEAL = 6
REST_HEAL = 0.3  # HealRestSiteOption: 30% of max HP
CARD_PRICE = {"COMMON": 50, "UNCOMMON": 75, "RARE": 150}  # MerchantCardEntry.GetCost
SHOP_SLOTS = ("Attack", "Attack", "Skill", "Skill", "Power")  # MerchantInventory._coloredCardTypes
REMOVAL_PRICE, REMOVAL_STEP = 75, 25  # MerchantCardRemovalEntry: +25 per removal used
NEXT_RARITY = {"COMMON": "UNCOMMON", "UNCOMMON": "RARE", "RARE": "COMMON"}  # GetNextHighestRarityWithWrapping

# The Ironclad pool by rarity. These open a card-choice prompt the sim can't play yet, so they're
# offered and stocked like any card but can't be picked or bought.
PROMPT_CARDS = {"ARMAMENTS": "Skill", "HEADBUTT": "Attack", "BURNING_PACT": "Skill", "BRAND": "Skill"}
REWARD_POOLS = {"COMMON": COMMONS + ("ARMAMENTS", "HEADBUTT"), "UNCOMMON": UNCOMMONS + ("BURNING_PACT",),
                "RARE": RARES + ("BRAND",)}

WEAK = tuple(e for e in ENCOUNTERS if e.endswith("_WEAK"))
ELITES = tuple(e for e in ENCOUNTERS if e.endswith("_ELITE"))
BOSSES = tuple(e for e in ENCOUNTERS if e.endswith("_BOSS"))
NORMALS = tuple(e for e in ENCOUNTERS if e not in WEAK + ELITES + BOSSES)
TAGS = {"NIBBITS_WEAK": {"Nibbit"}, "SLIMES_WEAK": {"Slimes"}, "SHRINKER_BEETLE_WEAK": {"Shrinker"},  # EncounterModel.Tags
        "FUZZY_WURM_CRAWLER_WEAK": {"Crawler"}, "SLIMES_NORMAL": {"Slimes"}, "OVERGROWTH_CRAWLERS": {"Crawler", "Shrinker"},
        "FLYCONID_NORMAL": {"Mushroom", "Slimes"}, "SNAPPING_JAXFRUIT_NORMAL": {"Mushroom"}}


def card_type(card_id: str) -> str:
    return CARDS[card_id].type if card_id in CARDS else PROMPT_CARDS[card_id]


class RarityOdds:
    """CardRarityOdds.cs at ascension 0. Regular fights: Rare 3% + an offset that starts at -5%,
    grows 1% per non-Rare roll (cap 40%) and resets on a Rare; Uncommon 37%. Elites: Rare 10%
    + offset, Uncommon 40%. One instance per run (the offset carries)."""

    def __init__(self):
        self.offset = -0.05

    def roll(self, rng: random.Random, elite: bool = False) -> str:
        r, rare = rng.random(), (0.10 if elite else 0.03) + self.offset
        if r < rare:
            self.offset = -0.05
            return "RARE"
        self.offset = min(self.offset + 0.01, 0.4)
        return "UNCOMMON" if r < rare + (0.40 if elite else 0.37) else "COMMON"

    def roll_shop(self, rng: random.Random) -> str:
        """CardRarityOddsType.Shop, RollWithoutChangingFutureOdds: Rare 9% + offset, Uncommon 37%."""
        r, rare = rng.random(), 0.09 + self.offset
        return "RARE" if r < rare else "UNCOMMON" if r < rare + 0.37 else "COMMON"


def offer(rng: random.Random, odds: RarityOdds, elite: bool = False) -> list[str]:
    """CardFactory.CreateForReward: 3 cards, no repeats."""
    out: list[str] = []
    for _ in range(3):
        out.append(rng.choice([c for c in REWARD_POOLS[odds.roll(rng, elite)] if c not in out]))
    return out


def _grab(rng: random.Random, bag: list[str], pool: tuple[str, ...], last: str | None) -> str:
    """GrabBag.GrabAndRemove via AddWithoutRepeatingTags: avoid the last encounter and its tags."""
    if not bag:
        bag.extend(pool)
    ok = [e for e in bag if e != last and not (TAGS.get(e, set()) & TAGS.get(last, set()))]
    e = rng.choice(ok or bag)
    bag.remove(e)
    return e


def encounter_queue(rng: random.Random, rooms: int = 15, weak: int = 3) -> tuple[list[str], list[str], str]:
    """ActModel.GenerateRooms: monster rooms draw 3 weak then regular encounters, elites from
    their own bag; the boss is fixed at run start."""
    normals: list[str] = []
    bag: list[str] = []
    for _ in range(weak):
        normals.append(_grab(rng, bag, WEAK, normals[-1] if normals else None))
    bag = []
    for _ in range(weak, rooms):
        normals.append(_grab(rng, bag, NORMALS, normals[-1]))
    elites: list[str] = []
    bag = []
    for _ in range(15):
        elites.append(_grab(rng, bag, ELITES, elites[-1] if elites else None))
    return normals, elites, rng.choice(BOSSES)


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


@dataclass
class Shop:
    cards: list[str | None]  # one per SHOP_SLOTS entry; None once bought
    prices: list[int]
    removal_price: int
    removal_used: bool = False


def make_shop(rng: random.Random, odds: RarityOdds, removals: int) -> Shop:
    """MerchantInventory.PopulateCharacterCardEntries: 5 typed slots, no repeats, one half price.
    Colorless cards, relics and potions aren't stocked yet."""
    sale = rng.randrange(len(SHOP_SLOTS))
    cards: list[str | None] = []
    prices: list[int] = []
    for i, ctype in enumerate(SHOP_SLOTS):
        rarity = odds.roll_shop(rng)
        for _ in range(3):  # CardFactory.GetNextAllowedRarity
            pool = [c for c in REWARD_POOLS[rarity] if card_type(c) == ctype and c not in cards]
            if pool:
                break
            rarity = NEXT_RARITY[rarity]
        cards.append(rng.choice(pool))
        price = round(CARD_PRICE[rarity] * rng.uniform(0.95, 1.05))  # Mathf.RoundToInt: banker's, like round()
        prices.append(price // 2 if i == sale else price)
    return Shop(cards, prices, REMOVAL_PRICE + REMOVAL_STEP * removals)


class Run:
    """An Act 1 run between fights. HP lives here; run_env copies it into each SimCombat and back."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.map: ActMap = generate_map(rng)
        self.normals, self.elites, self.boss = encounter_queue(rng)
        self.node: Node = self.map.start
        self.hp = self.max_hp = PLAYER_MAX_HP
        self.gold, self.deck, self.removals, self.spent = STARTING_GOLD, starter_deck(), 0, 0
        self.card_odds, self.unknown_odds = RarityOdds(), UnknownOdds()
        self.last_room: str | None = None
        self.shop: Shop | None = None

    def choices(self) -> list[Node]:
        return sorted(self.node.children, key=lambda n: n.col)

    def enter(self, node: Node) -> str:
        """Move to a child of the current node and resolve its room type (rest heals, shops stock)."""
        assert node in self.node.children, (node, self.node)
        room = node.type
        if room == "Unknown":  # RunManager.BuildRoomTypeBlacklist
            no_shop = self.last_room == "Shop" or (node.children and all(c.type == "Shop" for c in node.children))
            room = self.unknown_odds.roll(self.rng, {"Shop"} if no_shop else set())
        self.node, self.last_room = node, room
        if room == "RestSite":
            self.hp = min(self.max_hp, self.hp + int(self.max_hp * REST_HEAL))
        elif room == "Shop":
            self.shop = make_shop(self.rng, self.card_odds, self.removals)
        return room

    def encounter(self, room: str) -> str:
        if room == "Boss":
            return self.boss
        queue, pool = (self.elites, ELITES) if room == "Elite" else (self.normals, NORMALS)
        return queue.pop(0) if queue else self.rng.choice(pool)

    def win(self, room: str) -> list[str]:
        """After a won fight: Burning Blood, gold, and the card offer (none after the boss)."""
        self.hp = min(self.max_hp, self.hp + BURNING_BLOOD_HEAL)
        self.gold += self.rng.randint(*GOLD[room])
        return [] if room == "Boss" else offer(self.rng, self.card_odds, room == "Elite")

    def buy(self, slot: int) -> None:
        s = self.shop
        card, price = s.cards[slot], s.prices[slot]
        assert card in CARDS and self.gold >= price, (card, price, self.gold)
        self.gold -= price
        self.spent += price
        self.deck.append(card)
        s.cards[slot] = None

    def remove(self, card: str) -> None:
        s = self.shop
        assert not s.removal_used and self.gold >= s.removal_price and card in self.deck
        self.gold -= s.removal_price
        self.spent += s.removal_price
        self.deck.remove(card)
        self.removals += 1
        s.removal_used = True
