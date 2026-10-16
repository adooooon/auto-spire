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
import random
import time
from collections import defaultdict

import env as env_module
from client import AutoSpireClient
from env import STS2CombatEnv, _power, _ready, parse_encounters

from .engine import MONSTERS, SimCombat, _Enemy, legal_moves

RANDOM_TARGETS = {"SWORD_BOOMERANG", "HAVOC"}  # random enemy picks (when >1 enemy is hittable)
RANDOM_EXHAUST = {"CINDER", "TRUE_GRIT", "HAVOC"}  # random hand card exhausted (Havoc may autoplay one)


def load(c: dict, logs: dict[int, list[str]]) -> SimCombat:
    p = c["player"]
    sim = SimCombat(
        player_hp=p["hp"], player_max_hp=p["maxHp"], player_block=p["block"], energy=p["energy"],
        shrunk=_power(p, "ShrinkPower") != 0, vulnerable=_power(p, "VulnerablePower"), frail=_power(p, "FrailPower"),
        tangled=_power(p, "TangledPower"), constrict=_power(p, "ConstrictPower"),
        strength=_power(p, "StrengthPower"), temp_strength=_power(p, "SetupStrikePower"),
        round=c["round"], in_combat=True, is_play_phase=True,
        # /combat lists the draw pile top-first; the sim draws from the end.
        hand=[x["id"] for x in p["hand"]], draw_pile=[x["id"] for x in reversed(p["drawPile"])],
        discard_pile=[x["id"] for x in p["discardPile"]], exhaust_pile=[x["id"] for x in p["exhaustPile"]],
        rng=random.Random(0),
    )
    # /combat lists exactly the enemies still in combat (dead illusions included), in order,
    # so sim index + 1 lines up with list position.
    for e in c["enemies"]:
        sim.enemies.append(_Enemy(MONSTERS[e["modelId"]], e["hp"], e["maxHp"], e["intent"]["moveId"],
                                  block=e["block"], strength=_power(e, "StrengthPower"),
                                  vulnerable=_power(e, "VulnerablePower"), artifact=_power(e, "ArtifactPower"),
                                  slippery=_power(e, "SlipperyPower"), log=list(logs[e["combatId"]])))
    return sim


def diff(before: dict, action: str, after: dict, sim: SimCombat, logs, skip: set[str] = frozenset()) -> list[str]:
    out = []
    if not after.get("inCombat"):
        return [] if not sim.in_combat else ["live combat ended, sim did not"]
    if not sim.in_combat:
        return ["sim combat ended, live did not"]
    s, p = sim.combat_dict(), after["player"]
    for k in ("hp", "block", "energy"):
        if s["player"][k] != p[k]:
            out.append(f"player.{k}: sim={s['player'][k]} live={p[k]}")
    # A random kill also removes its applier's Shrink/Constrict, so those follow the enemies skip.
    if "enemies" not in skip and sim.shrunk != (_power(p, "ShrinkPower") != 0):
        out.append(f"player shrink: sim={sim.shrunk} live={_power(p, 'ShrinkPower')}")
    if sim.strength != _power(p, "StrengthPower"):
        out.append(f"player strength: sim={sim.strength} live={_power(p, 'StrengthPower')}")
    for name in ("vulnerable", "frail", "tangled") + (() if "enemies" in skip else ("constrict",)):
        live = _power(p, f"{name.capitalize()}Power")
        if getattr(sim, name) != live:
            out.append(f"player {name}: sim={getattr(sim, name)} live={live}")
    for status in () if "piles" in skip else ("SLIMED", "DAZED"):
        count = lambda pl: sum(x["id"] == status for k in ("hand", "drawPile", "discardPile") for x in pl[k])  # noqa: E731
        if count(s["player"]) != count(p):
            out.append(f"live {status} in deck: sim={count(s['player'])} live={count(p)}")
    attack_costs = lambda pl: sorted((x["id"], x["cost"]) for x in pl["hand"] if x["type"] == "Attack")  # noqa: E731
    same_hand = sorted(x["id"] for x in s["player"]["hand"]) == sorted(x["id"] for x in p["hand"])  # not after a draw
    if same_hand and "piles" not in skip and attack_costs(s["player"]) != attack_costs(p):
        out.append(f"attack costs in hand: sim={attack_costs(s['player'])} live={attack_costs(p)}")
    if "enemies" in skip:
        return out
    if [e["modelId"] for e in s["enemies"]] != [e["modelId"] for e in after["enemies"]]:
        return out + [f"enemies: sim={[e['modelId'] for e in s['enemies']]} live={[e['modelId'] for e in after['enemies']]}"]
    # Same monsters in the same order, so pair them by position (summons insert in front).
    for se, le in zip([e for e in sim.enemies if e.in_combat], after["enemies"]):
        cid = le["combatId"]
        if se.hp != le["hp"]:
            out.append(f"{se.defn.model_id}#{cid}.hp: sim={se.hp} live={le['hp']}")
        if not le["isAlive"]:
            continue
        for name, sv, lv in (("block", se.block, le["block"]), ("strength", se.strength, _power(le, "StrengthPower")),
                             ("vulnerable", se.vulnerable, _power(le, "VulnerablePower")),
                             ("artifact", se.artifact, _power(le, "ArtifactPower")),
                             ("slippery", se.slippery, _power(le, "SlipperyPower"))):
            if sv != lv:
                out.append(f"{se.defn.model_id}#{cid}.{name}: sim={sv} live={lv}")
        atk = lambda e: next((i["totalDamage"] for i in e["intent"]["intents"] if i["type"] == "Attack"), 0)  # noqa: E731
        if se.move == le["intent"]["moveId"] and atk(sim._enemy_dict(0, se)) != atk(le):  # random picks may differ
            out.append(f"{se.defn.model_id}#{cid} intent damage: sim={atk(sim._enemy_dict(0, se))} live={atk(le)}")
        if action == "end" and logs[cid]:  # (a fresh summon has no move yet)
            prev = logs[cid][-1]  # move just performed
            legal = legal_moves(se.defn.follow[prev], logs[cid])
            if le["intent"]["moveId"] not in legal:
                out.append(f"{se.defn.model_id}#{cid} next move: live={le['intent']['moveId']} legal={legal}")
    return out


def wait_ready(client) -> dict:
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        c = client.combat()
        if not c.get("inCombat") or _ready(c):
            return c
        time.sleep(0.05)
    raise TimeoutError("turn never returned to the player")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fights", type=int, default=3, help="live fights per encounter")
    ap.add_argument("--encounters", default="weak")
    ap.add_argument("--deck", help="comma-separated card ids to use instead of random decks")
    args = ap.parse_args()
    if args.deck:
        env_module.random_deck = lambda rng: args.deck.split(",")
    encounters = parse_encounters(args.encounters)

    env = STS2CombatEnv(client=AutoSpireClient(), random_decks=True)
    client = env.client
    steps = mismatched = 0
    for enc in encounters:
        env.encounters = [enc]
        for fight in range(args.fights):
            env.reset()
            c = client.combat()
            logs = defaultdict(list)  # combatId -> performed moves (summons join mid-fight)
            print(f"[{enc} #{fight}] " + ", ".join(f"{e['modelId']}({e['hp']})" for e in c["enemies"]))
            while c.get("inCombat"):
                hand = c["player"]["hand"]
                playable = [i for i, x in enumerate(hand) if x["canPlay"]]
                idx = random.choice(playable) if playable and random.random() < 0.85 else None
                living = [e for e in c["enemies"] if e["isAlive"]]
                played = hand[idx]["id"] if idx is not None else ""
                skip = {"enemies"} if played in RANDOM_TARGETS and len(living) > 1 else set()
                skip |= {"piles"} if played in RANDOM_EXHAUST else set()
                # Random target exercises targeting.
                tgt = random.choice(living) if idx is not None and hand[idx]["targetType"] == "AnyEnemy" else None
                action = "end" if idx is None else f"play {idx}" + ("" if tgt is None else f" @{tgt['modelId']}")
                sim = load(c, logs)
                if idx is None:
                    sim.end_turn()
                    client.end_turn()
                    for e in c["enemies"]:  # everything in combat acts, dead illusions included
                        logs[e["combatId"]].append(e["intent"]["moveId"])
                else:
                    sim.play_card(idx, None if tgt is None else c["enemies"].index(tgt) + 1)
                    client.play(idx, None if tgt is None else tgt["combatId"])
                after = wait_ready(client)
                problems = diff(c, action, after, sim, logs, skip)
                steps += 1
                if problems:
                    mismatched += 1
                    print(f"  round {c['round']} {action} ({hand[idx]['id'] if idx is not None else ''}): " + "; ".join(problems))
                c = after
    print(f"\n{steps} steps compared, {mismatched} with mismatches")


if __name__ == "__main__":
    main()
