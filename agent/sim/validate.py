"""One-step sim-vs-live check: for every live step, load the live "before"
state into the sim, apply the same action, and diff against the live "after".

Each fight uses a random deck (env.random_deck) and plays random playable cards
at random targets, so every card gets exercised. Hand contents after a shuffle
are random, and some cards pick at random (Sword Boomerang's targets, Cinder /
True Grit's exhausted card, Havoc's target), so those comparisons are skipped
for that step; everything else is compared — player HP/block/energy/powers,
each enemy's HP/block/powers, status cards added, combat end, and the enemy's
next move (exact for fixed follow-ups, must-be-legal for random branches).

Usage (from agent/, game running or launchable):
    python -m sim.validate --fights 3
"""
from __future__ import annotations

import argparse
import copy
import json
import random
import time
from collections import defaultdict

import requests

import env as env_module
from client import AutoSpireClient
from env import PLAYER_POWERS, RELIC_POWERS, STS2CombatEnv, _power, _ready, parse_encounters

from .cards import CARDS, CHOICE_CARDS, COLORLESS, COMMONS, NOT_BUYABLE, RARES, UNCOMMONS, UPGRADABLE, DeckCard, upgrade
from .engine import (frantic_escape, BRANCHES, ENEMY_PW, HISTORY_FIELDS, INSTANCED, MONSTERS, WRIGGLER_SLOT_OPENERS, SimClient, SimCombat,
                     _Enemy, legal_moves)

# Random enemy picks (compared only with one hittable enemy): the cards, and powers that hit or
# autoplay at random.
RANDOM_TARGETS = {"SWORD_BOOMERANG", "HAVOC", "CASCADE", "VOLLEY"}
RANDOM_TARGET_POWERS = {"JuggernautPower", "HellraiserPower", "StampedePower"}
# Random cards exhausted / generated / moved (pile contents compared only otherwise).
RANDOM_EXHAUST = {"CINDER", "TRUE_GRIT", "HAVOC", "THRASH", "INFERNAL_BLADE", "STOKE", "CASCADE",
                  "ANOINTED", "JACKPOT", "JACK_OF_ALL_TRADES"}
# Cards that autoplay random cards: which ones, and at what, is random (nothing compared).
RANDOM_PLAYS = {"BEAT_DOWN", "CATASTROPHE"}
# Calamity adds a random Attack, Entropy transforms at random, Stratagem's pick is random in the sim.
RANDOM_PILE_POWERS = {"AggressionPower", "StampedePower", "CalamityPower", "EntropyPower", "StratagemPower"}
SPECIAL = sorted(c for c in UPGRADABLE if CARDS[c].special and c not in CHOICE_CARDS)  # --upgraded decks


def ids(cards) -> list[str]:
    """Sim card ids ("X+" when upgraded); ones this check doesn't model (the prompt cards, which pause for a
    choice the live game makes and the replay can't mirror) become an inert Wound so pile sizes still line up."""
    return [(frantic_escape(x["cost"] - 1) if x["id"] == "FRANTIC_ESCAPE" else x["id"] + "+" * bool(x["upgraded"]))
            if x["id"] in CARDS and x["id"] not in CHOICE_CARDS else "WOUND" for x in cards]


def load(c: dict, logs: dict[int, list[str]], prev: SimCombat | None = None) -> SimCombat:
    """prev: the sim from the previous step, for history /combat doesn't show (HISTORY_FIELDS)."""
    p = c["player"]
    sim = SimCombat(
        player_hp=p["hp"], player_max_hp=p["maxHp"], player_block=p["block"], energy=p["energy"],
        shrunk=_power(p, "ShrinkPower") != 0, vulnerable=_power(p, "VulnerablePower"), frail=_power(p, "FrailPower"),
        tangled=_power(p, "TangledPower"), constrict=_power(p, "ConstrictPower"),
        strength=_power(p, "StrengthPower"), temp_strength=_power(p, "SetupStrikePower"), dexterity=_power(p, "DexterityPower"),
        weak=_power(p, "WeakPower"), ringing=_power(p, "RingingPower") != 0, cards_played=c.get("cardsPlayedThisTurn", 0),
        round=c["round"], in_combat=True, is_play_phase=True,
        # /combat lists the draw pile top-first; the sim draws from the end.
        hand=ids(p["hand"]), draw_pile=ids(reversed(p["drawPile"])),
        discard_pile=ids(p["discardPile"]), exhaust_pile=ids(p["exhaustPile"]),
        rng=random.Random(0),
        # INSTANCED powers come from prev (sim.inst, in HISTORY_FIELDS): /combat lacks their counters.
        # RELIC_POWERS too: Prep Time's Vigor, Thorns.
        pw={x["name"]: x["amount"] for x in p["powers"]
            if (x["name"] in PLAYER_POWERS or x["name"] in dict(RELIC_POWERS)) and x["name"] not in INSTANCED},
    )
    for name in HISTORY_FIELDS if prev else ():
        setattr(sim, name, copy.deepcopy(getattr(prev, name)))
    # An INSTANCED power prev lacks or holds different amounts of (a random autoplay played the card): /combat's
    # amounts, with default counters. ponytail: those counters (Automation's, Panache's, The Bomb's damage) may be off.
    for name, state in INSTANCED.items():
        amounts = [x["amount"] for x in p["powers"] if x["name"] == name]
        if amounts != [i[0] for i in sim.inst.get(name, [])]:
            sim.inst[name] = [[a, *state] for a in amounts]
    # A random step (e.g. Hellraiser autoplays after a reshuffle) can leave the carried count high.
    sim.attack_plays = min(sim.attack_plays, sim.cards_played)
    # The game's own counts, when /combat has them (CardPlaysStarted this turn by type): a random step (Catastrophe's
    # autoplays) leaves the carried ones wrong for the rest of the turn, and Stomp's cost reads them.
    ctr = c.get("relicCounters") or {}
    if "attacks" in ctr:
        sim.attack_plays, sim.skill_plays = ctr["attacks"], ctr["skills"]
    # Thieving Hopper steals deck cards. ponytail: /combat doesn't mark generated cards, so every card but a status
    # or token counts as the deck's.
    for pile in (sim.hand, sim.draw_pile, sim.discard_pile, sim.exhaust_pile):
        pile[:] = [DeckCard(c) if CARDS[c].rarity not in ("Status", "Token") else c for c in pile]
    # Bolas / Thrumming Hatchet played this turn come back next turn, and the sim knows them by identity: find them again
    # in the rebuilt piles by id, the discard pile first. ponytail: with two copies, either may be the one marked.
    for cid in prev.played_now if prev else ():
        card = next((x for x in sim.discard_pile + sim.exhaust_pile + sim.draw_pile + sim.hand
                     if x == cid and not any(x is y for y in sim.played_now)), None)
        if card is not None:
            sim.played_now.append(card)
    # Hidden Gem's Replay (on a random card) is keyed by the card object: /combat sends each card's count.
    for pile, live in ((sim.hand, p["hand"]), (sim.draw_pile, reversed(p["drawPile"])), (sim.discard_pile, p["discardPile"]),
                       (sim.exhaust_pile, p["exhaustPile"])):
        for card, x in zip(pile, live):
            if x.get("replay"):
                sim.replays[id(card)] = x["replay"]
                sim._pinned.append(card)
    # Free-this-turn cards (Infernal Blade's) are visible live: cost 0 where the sim would charge.
    sim.free_cards = []
    sim.free_cards = [c for x, c in zip(p["hand"], ids(p["hand"])) if x["cost"] == 0 and sim.cost(c) > 0]
    # /combat lists exactly the enemies still in combat (dead illusions included), in order,
    # so sim index + 1 lines up with list position.
    for e in c["enemies"]:
        sim.enemies.append(_Enemy(MONSTERS[e["modelId"]], e["hp"], e["maxHp"], e["intent"]["moveId"],
                                  block=e["block"], strength=_power(e, "StrengthPower"),
                                  vulnerable=_power(e, "VulnerablePower"), artifact=_power(e, "ArtifactPower"),
                                  slippery=_power(e, "SlipperyPower"), plow=_power(e, "PlowPower"),
                                  weak=_power(e, "WeakPower"), mangle=_power(e, "ManglePower"),
                                  pw={x["name"]: x["amount"] for x in e["powers"] if x["name"] in ENEMY_PW or x["name"] == "DarkShacklesPower"}
                                  | ({"reviving": 1} if e["hp"] <= 0 and MONSTERS[e["modelId"]].reattach else {}),
                                  log=list(logs[e["combatId"]])))
    # Stun follow-ups aren't in the move graph: the Beast's STUNNED leads into phase 2, and a
    # still-stunned Wriggler resumes with its slot's opener (Wriggler.cs INIT_MOVE).
    for x in sim.enemies:
        if x.move == "STUNNED" and x.defn.model_id == "CEREMONIAL_BEAST":
            x.next_override = "BEAST_CRY_MOVE"
    wrigglers = [x for x in sim.enemies if x.defn.model_id == "WRIGGLER"]
    for i, w in enumerate(wrigglers):
        if w.move == "SPAWNED_MOVE":
            w.next_override = WRIGGLER_SLOT_OPENERS[i]
    return sim


def diff(before: dict, action: str, after: dict, sim: SimCombat, logs, skip: set[str] = frozenset()) -> list[str]:
    out = []
    if not after.get("inCombat"):  # with random hits (skip "enemies"), who dies is random too
        return [] if not sim.in_combat or "enemies" in skip else ["live combat ended, sim did not"]
    if not sim.in_combat:
        return [] if "enemies" in skip else ["sim combat ended, live did not"]
    s, p = sim.combat_dict(), after["player"]
    if "player" in skip:
        return out
    for k in ("hp", "maxHp", "block", "energy", "maxEnergy"):
        if s["player"][k] != p[k]:
            out.append(f"player.{k}: sim={s['player'][k]} live={p[k]}")
    for name in PLAYER_POWERS:
        if _power(s["player"], name) != _power(p, name):
            out.append(f"player {name}: sim={_power(s['player'], name)} live={_power(p, name)}")
    if "piles" not in skip:
        for k in ("hand", "exhaustPile"):
            if len(s["player"][k]) != len(p[k]):
                out.append(f"len({k}): sim={len(s['player'][k])} live={len(p[k])}")
    # A random kill also removes its applier's Shrink/Constrict, so those follow the enemies skip.
    if "enemies" not in skip and sim.shrunk != (_power(p, "ShrinkPower") != 0):
        out.append(f"player shrink: sim={sim.shrunk} live={_power(p, 'ShrinkPower')}")
    if sim.strength != _power(p, "StrengthPower"):
        out.append(f"player strength: sim={sim.strength} live={_power(p, 'StrengthPower')}")
    if sim.ringing != (_power(p, "RingingPower") != 0):
        out.append(f"player ringing: sim={sim.ringing} live={_power(p, 'RingingPower')}")
    for name in ("vulnerable", "frail", "tangled", "weak") + (() if "enemies" in skip else ("constrict",)):
        live = _power(p, f"{name.capitalize()}Power")
        if getattr(sim, name) != live:
            out.append(f"player {name}: sim={getattr(sim, name)} live={live}")
    for status in () if "piles" in skip else ("SLIMED", "DAZED", "INFECTION", "WOUND", "TOXIC", "FRANTIC_ESCAPE"):
        count = lambda pl: sum(i == status for k in ("hand", "drawPile", "discardPile") for i in ids(pl[k]))  # noqa: E731
        if count(s["player"]) != count(p):
            out.append(f"live {status} in deck: sim={count(s['player'])} live={count(p)}")
    costs = lambda pl: sorted((x["id"], x["upgraded"], x["cost"], x["canPlay"]) for x in pl["hand"])  # noqa: E731
    hand_ids = lambda pl: sorted((x["id"], x["upgraded"]) for x in pl["hand"])  # noqa: E731
    same_hand = hand_ids(s["player"]) == hand_ids(p)  # not after a random draw (which copy, upgraded or not)
    if same_hand and "piles" not in skip and costs(s["player"]) != costs(p):
        out.append(f"hand costs: sim={costs(s['player'])} live={costs(p)}")
    for x in p["hand"]:  # card_to_dict's upgraded title, e.g. "Bash+"
        if x["upgraded"] and x["id"] in UPGRADABLE and x["title"] != CARDS[x["id"] + "+"].title:
            out.append(f"title: sim={CARDS[x['id'] + '+'].title} live={x['title']}")
    if "enemies" in skip:
        return out
    if [e["modelId"] for e in s["enemies"]] != [e["modelId"] for e in after["enemies"]]:
        return out + [f"enemies: sim={[e['modelId'] for e in s['enemies']]} live={[e['modelId'] for e in after['enemies']]}"]
    # Same monsters in the same order, so pair them by position (summons insert in front).
    before_ids = {e["combatId"] for e in before["enemies"]}
    for se, le in zip([e for e in sim.enemies if e.in_combat], after["enemies"]):
        cid = le["combatId"]
        if cid not in before_ids:  # spawned this step: HP is a fresh random roll
            continue
        prev_move = logs[cid][-1] if logs[cid] else None
        for name in ENEMY_PW:
            if se.pw.get(name, 0) != _power(le, name):
                out.append(f"{se.defn.model_id}#{cid} {name}: sim={se.pw.get(name, 0)} live={_power(le, name)}")
        if se.hp != le["hp"] and prev_move != "HATCH_MOVE":  # a hatchling's HP is rolled
            out.append(f"{se.defn.model_id}#{cid}.hp: sim={se.hp} live={le['hp']}")
        if not le["isAlive"]:
            continue
        for name, sv, lv in (("block", se.block, le["block"]), ("strength", se.strength, _power(le, "StrengthPower")),
                             ("vulnerable", se.vulnerable, _power(le, "VulnerablePower")),
                             ("weak", se.weak, _power(le, "WeakPower")),
                             ("mangle", se.mangle, _power(le, "ManglePower")),
                             ("artifact", se.artifact, _power(le, "ArtifactPower")),
                             ("slippery", se.slippery, _power(le, "SlipperyPower")),
                             ("plow", se.plow, _power(le, "PlowPower"))):
            if sv != lv:
                out.append(f"{se.defn.model_id}#{cid}.{name}: sim={sv} live={lv}")
        atk = lambda e: next((i["totalDamage"] for i in e["intent"]["intents"] if i["type"] == "Attack"), 0)  # noqa: E731
        if se.move == le["intent"]["moveId"] and atk(sim._enemy_dict(0, se)) != atk(le):  # random picks may differ
            out.append(f"{se.defn.model_id}#{cid} intent damage: sim={atk(sim._enemy_dict(0, se))} live={atk(le)}")
        if action == "end" and logs[cid] and logs[cid][-1] in se.defn.follow:  # (stun follow-ups are overrides)
            prev = logs[cid][-1]  # move just performed
            follow = se.defn.follow[prev]
            legal = BRANCHES.get(follow) if isinstance(follow, str) and follow in BRANCHES else legal_moves(follow, logs[cid])
            if prev == "SNORE_MOVE":  # asleep until Slumber runs out
                legal = ["SNORE_MOVE", "ROLL_OUT_MOVE"]
            if "ImbalancedPower" in se.pw:  # a fully blocked Headbutt
                legal = [*legal, "STUNNED"]
            # A stun before the enemy's turn (The Bomb breaking the Beast's Plow) means the logged move never ran: the
            # sim's own next move is then the reference.
            if le["intent"]["moveId"] not in legal and le["intent"]["moveId"] != se.move:
                out.append(f"{se.defn.model_id}#{cid} next move: live={le['intent']['moveId']} legal={legal}")
    return out


def _answer(kind: str, hand: int, options: list[str]) -> str:
    """A random answer to a prompt of this kind: the command, as env.step sends it. hand: the hand's size;
    options: the offered ids ("X+" upgraded) for "generated", "draw" and "discard"."""
    if kind == "hand_multi":
        return "choose_done" if not hand or random.random() < 0.3 else f"choose {random.randrange(hand)}"
    if kind == "generated":
        i = random.randrange(len(options) + 1)
        return "choose_skip" if i == len(options) else f"choose_generated {i}"
    if kind in ("draw", "discard"):
        return f"choose_{kind} {random.choice(options).removesuffix('+')}"
    return f"choose {random.randrange(max(hand, 1))}"


def answer_prompts(sim: SimCombat, client, after: dict, played: str, powers: set[str]) -> tuple[dict, str, list[str], bool]:
    """Answer every open prompt in both, the same random way. (live after, the answers, mismatches, whether only one
    side asked: then the sim picked at random, so its piles can't be compared). The sim can't pause an autoplay or
    Stratagem's mid-draw pick, so a live prompt from those is expected; any other one-sided prompt is a mismatch."""
    said, problems, one_sided = "", [], False
    sc = SimClient()
    sc._combat = sim
    while sim.pending_choice or after.get("choice"):
        mine, live = sim.pending_choice or {}, after.get("choice") or {}
        live_ids = ids({"id": i, "upgraded": u, "cost": 1} for i, u in zip(live.get("options") or [], live.get("upgraded") or []))
        if mine and live and mine["kind"] == live["kind"]:
            if live["kind"] == "generated":  # new random cards: the sim offers what the game offered
                sim._options, mine["options"] = list(live_ids), list(live_ids)
            elif live["kind"] == "draw" and sorted(map(str, sim._options)) != sorted(live_ids):  # Seeker Strike's random 3
                pool, opts = list(sim.draw_pile), []
                for cid in live_ids:
                    j = next((j for j, d in enumerate(pool) if d == cid), None)
                    if j is None:
                        break
                    opts.append(pool.pop(j))
                else:
                    sim._options, mine["options"] = opts, [str(c) for c in opts]
            options = mine.get("options") or live_ids or list(dict.fromkeys(sim.discard_pile))
            if mine["kind"] == "upgrade":
                cmd = f"choose {random.choice([i for i, x in enumerate(sim.hand) if x in UPGRADABLE] or [0])}"
            else:
                cmd = _answer(mine["kind"], len(sim.hand), options)
            sc.exec(cmd)
            client.exec(cmd)
            said += f" {cmd}"
        else:
            one_sided = True
            if mine or not ("StratagemPower" in powers or live.get("source") != played):
                problems.append(f"prompt: sim={mine or None} live={live or None}")
            if mine:
                cmd = _answer(mine["kind"], len(sim.hand), mine.get("options") or list(dict.fromkeys(sim.discard_pile)))
                sc.exec(cmd)
                said += f" sim:{cmd}"
            if live:
                cmd = "choose_option 0" if live["kind"] == "deck" else _answer(live["kind"], len(after["player"]["hand"]), live_ids)
                client.exec(cmd)
                said += f" live:{cmd}"
        after = wait_ready(client)
    return after, said, list(dict.fromkeys(problems)), one_sided


def wait_ready(client) -> dict:
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        c = client.combat()
        choice = c.get("choice") or {}
        if choice.get("kind") == "deck":  # Knowledge Demon's curse: the sim takes the first option too
            client.exec("choose_option 0")
            continue
        if not c.get("inCombat") or _ready(c):
            return c
        time.sleep(0.05)
    raise TimeoutError("turn never returned to the player")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fights", type=int, default=3, help="live fights per encounter")
    ap.add_argument("--encounters", default="weak")
    ap.add_argument("--deck", help="comma-separated card ids to use instead of random decks")
    ap.add_argument("--new-cards", action="store_true", help="decks of 4 starter cards + 10 Uncommons/Rares")
    ap.add_argument("--colorless", action="store_true",
                    help="decks of 4 starter cards + 3 others + 4-8 colorless cards, each upgraded with p=0.5")
    ap.add_argument("--upgraded", action="store_true",
                    help="decks of 4 starter cards + 6 special cards + 4 others, each upgraded with p=0.5")
    args = ap.parse_args()
    if args.deck:
        env_module.random_deck = lambda rng, *_: args.deck.split(",")
    elif args.new_cards:
        pool = UNCOMMONS + RARES
        env_module.random_deck = lambda rng, *_: ["STRIKE_IRONCLAD", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "BASH"] + \
            [str(c) for c in rng.choice(pool, size=10)]
    elif args.colorless:  # not Splash or Alchemize: no shop sells them
        pool = [c for c in COLORLESS if c not in NOT_BUYABLE]
        env_module.random_deck = lambda rng, *_: [upgrade(c) if rng.random() < 0.5 else c for c in
                                                  ["STRIKE_IRONCLAD", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "BASH"]
                                                  + [str(c) for c in rng.choice(COMMONS + UNCOMMONS + RARES, size=3)]
                                                  + [str(c) for c in rng.choice(pool, size=rng.integers(4, 9))]]
    elif args.upgraded:
        env_module.random_deck = lambda rng, *_: [upgrade(c) if rng.random() < 0.5 else c for c in
                                                  ["STRIKE_IRONCLAD", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "BASH"]
                                                  + [str(c) for c in rng.choice(SPECIAL, size=6)]
                                                  + [str(c) for c in rng.choice(COMMONS + UNCOMMONS + RARES, size=4)]]
    encounters = parse_encounters(args.encounters)

    env = STS2CombatEnv(client=AutoSpireClient(), random_decks=True)
    client = env.client
    steps = mismatched = 0
    played_ids: set[str] = set()
    for enc in encounters:
        env.encounters = [enc]
        for fight in range(args.fights):
            env.reset()
            action = played = ""
            hand = []
            try:
                c = client.combat()
                logs = defaultdict(list)  # combatId -> performed moves (summons join mid-fight)
                sim = prev = None
                print(f"[{enc} #{fight}] " + ", ".join(f"{e['modelId']}({e['hp']})" for e in c["enemies"]))
                while c.get("inCombat"):
                    hand = c["player"]["hand"]
                    playable = [i for i, x in enumerate(hand) if x["canPlay"] and x["id"] in CARDS and x["id"] not in CHOICE_CARDS]  # (no prompts)
                    idx = random.choice(playable) if playable and random.random() < 0.85 else None
                    living = [e for e in c["enemies"] if e["isAlive"]]
                    played = hand[idx]["id"] if idx is not None else ""
                    played_ids |= {played} | ({played + "+"} if idx is not None and hand[idx]["upgraded"] else set())
                    powers = {x["name"] for x in c["player"]["powers"]}
                    skip = {"enemies"} if (played in RANDOM_TARGETS or powers & RANDOM_TARGET_POWERS) and \
                        len(living) > 1 else set()
                    skip |= {"piles"} if played in RANDOM_EXHAUST or powers & RANDOM_PILE_POWERS else set()
                    if idx is None and "MayhemPower" in powers and len(living) > 1:  # its turn-start autoplay hits at random
                        skip |= {"enemies"}
                    if idx is None and "StampedePower" in powers:  # autoplays a random Attack from hand
                        skip |= {"enemies", "piles"}
                        if len({c for x, c in zip(hand, ids(hand)) if x["type"] == "Attack"}) > 1:  # which one: random
                            skip |= {"player"}
                    # Random target exercises targeting.
                    tgt = random.choice(living) if idx is not None and hand[idx]["targetType"] == "AnyEnemy" else None
                    action = "end" if idx is None else f"play {idx}" + ("" if tgt is None else f" @{tgt['modelId']}")
                    prev = sim
                    sim = load(c, logs, prev)
                    if idx is None:
                        sim.end_turn()
                        client.end_turn()
                        for e in c["enemies"]:  # everything in combat acts, dead illusions included
                            logs[e["combatId"]].append(e["intent"]["moveId"])
                    else:
                        sim.play_card(idx, None if tgt is None else c["enemies"].index(tgt) + 1)
                        client.play(idx, None if tgt is None else tgt["combatId"])
                    after = wait_ready(client)
                    after, said, prompt, one_sided = answer_prompts(sim, client, after, played, powers)
                    action += said
                    if one_sided:
                        skip |= {"piles"}
                    if sim.shuffles and "HellraiserPower" in powers:  # drew random cards, and Strikes autoplay
                        skip |= {"enemies", "piles"}
                    if sim.shuffles and played == "CASCADE":  # autoplayed cards from a fresh shuffle: random
                        skip |= {"enemies", "piles", "player"}
                    if sim.shuffles and "MayhemPower" in powers:  # autoplays the top card after the turn's draw: random
                        skip |= {"enemies", "piles", "player"}
                    if played in RANDOM_PLAYS:
                        skip |= {"enemies", "piles", "player"}
                    if sim.shuffles and played == "PILLAGE":  # draws until a non-Attack from a fresh shuffle: random
                        skip |= {"piles"}
                    problems = prompt + diff(c, action, after, sim, logs, skip)
                    steps += 1
                    if problems:
                        mismatched += 1
                        print(f"  round {c['round']} {action} ({hand[idx]['id'] if idx is not None else ''}): " + "; ".join(problems))
                        with open("validate_mismatches.jsonl", "a") as f:  # replay offline with load()
                            f.write(json.dumps({"before": c, "action": action, "idx": idx, "after": after,
                                                "target": None if tgt is None else c["enemies"].index(tgt) + 1,
                                                "history": {k: getattr(prev, k) for k in HISTORY_FIELDS} if prev else None,
                                                "logs": logs, "problems": problems}) + "\n")
                        pw = lambda x: {q["name"]: q["amount"] for q in x["player"]["powers"]}  # noqa: E731
                        print(f"    powers {pw(c)}; hand {[x['id'] for x in hand]} -> live "
                              f"{[x['id'] for x in (after.get('player') or {}).get('hand', [])]} / sim {sim.hand}")
                    c = after
            except (requests.RequestException, TimeoutError) as exc:  # a hung live game: restart it, next fight
                print(f"  live game stopped responding after {action} ({played}), hand {[x['title'] for x in hand]}: {exc!r}")
                env._needs_restart = True
    print(f"\n{steps} steps compared, {mismatched} with mismatches")
    print(f"cards played: {len(played_ids - {''})}; new cards never played: "
          f"{sorted(set(UNCOMMONS + RARES) - played_ids)}")
    if args.upgraded:
        print(f"upgraded special cards never played: {sorted({c + '+' for c in SPECIAL} - played_ids)}")
    if args.colorless:
        print(f"colorless cards never played: {sorted(set(COLORLESS) - NOT_BUYABLE - played_ids)}")


if __name__ == "__main__":
    main()
