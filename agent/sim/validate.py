"""One-step sim-vs-live check: for every live step, load the live "before"
state into the sim, apply the same action, and diff against the live "after".

Hand contents after a draw (end turn, Slimed) are random, so those aren't
compared; everything else is — player HP/block/energy/Shrink, each enemy's
HP/block/Strength/Vulnerable, Slimed cards added, combat end, and the enemy's
next move (exact for fixed follow-ups, must-be-legal for random branches).

Usage (from agent/, game running or launchable):
    python -m sim.validate --fights 3
"""
from __future__ import annotations

import argparse
import random
import time

from client import AutoSpireClient
from env import WEAK_ENCOUNTERS, STS2CombatEnv, _ready

from .engine import MONSTERS, SimCombat, _Enemy

PRIORITY = ("BASH", "STRIKE_IRONCLAD", "SLIMED", "DEFEND_IRONCLAD")


def _power(entity: dict, name: str) -> int:
    return next((p["amount"] for p in entity.get("powers") or [] if p["name"] == name), 0)


def load(c: dict, logs: dict[int, list[str]]) -> SimCombat:
    p = c["player"]
    sim = SimCombat(
        player_hp=p["hp"], player_max_hp=p["maxHp"], player_block=p["block"], energy=p["energy"],
        shrunk=_power(p, "ShrinkPower") != 0, round=c["round"], in_combat=True, is_play_phase=True,
        hand=[x["id"] for x in p["hand"]], draw_pile=[x["id"] for x in p["drawPile"]],
        discard_pile=[x["id"] for x in p["discardPile"]], exhaust_pile=[x["id"] for x in p["exhaustPile"]],
        rng=random.Random(0),
    )
    for e in c["enemies"]:
        if e["isAlive"]:
            sim.enemies.append(_Enemy(MONSTERS[e["modelId"]], e["hp"], e["maxHp"], e["intent"]["moveId"],
                                      block=e["block"], strength=_power(e, "StrengthPower"),
                                      vulnerable=_power(e, "VulnerablePower"), log=list(logs[e["combatId"]])))
    return sim


def diff(before: dict, action: str, after: dict, sim: SimCombat, logs) -> list[str]:
    out = []
    if not after.get("inCombat"):
        return [] if not sim.in_combat else ["live combat ended, sim did not"]
    if not sim.in_combat:
        return ["sim combat ended, live did not"]
    s, p = sim.combat_dict(), after["player"]
    for k in ("hp", "block", "energy"):
        if s["player"][k] != p[k]:
            out.append(f"player.{k}: sim={s['player'][k]} live={p[k]}")
    if sim.shrunk != (_power(p, "ShrinkPower") != 0):
        out.append(f"player shrink: sim={sim.shrunk} live={_power(p, 'ShrinkPower')}")
    slimed = lambda pl: sum(x["id"] == "SLIMED" for k in ("hand", "drawPile", "discardPile") for x in pl[k])  # noqa: E731
    if slimed(s["player"]) != slimed(p):
        out.append(f"live Slimed in deck: sim={slimed(s['player'])} live={slimed(p)}")
    live_by_id = {e["combatId"]: e for e in after["enemies"]}
    alive_ids = [e["combatId"] for e in before["enemies"] if e["isAlive"]]
    for cid, se in zip(alive_ids, sim.enemies):
        le = live_by_id.get(cid)
        live_hp = le["hp"] if le and le["isAlive"] else 0
        if se.hp != live_hp:
            out.append(f"{se.defn.model_id}#{cid}.hp: sim={se.hp} live={live_hp}")
        if not le or not le["isAlive"]:
            continue
        for name, sv, lv in (("block", se.block, le["block"]), ("strength", se.strength, _power(le, "StrengthPower")),
                             ("vulnerable", se.vulnerable, _power(le, "VulnerablePower"))):
            if sv != lv:
                out.append(f"{se.defn.model_id}#{cid}.{name}: sim={sv} live={lv}")
        if action == "end":
            prev = logs[cid][-1]  # move just performed
            spec = se.defn.follow[prev]
            legal = {spec} if isinstance(spec, str) else {
                m for m, n in spec if not (len(logs[cid]) >= n and all(x == m for x in logs[cid][-n:]))}
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
    args = ap.parse_args()
    encounters = WEAK_ENCOUNTERS if args.encounters == "weak" else args.encounters.split(",")

    env = STS2CombatEnv(client=AutoSpireClient())
    client = env.client
    steps = mismatched = 0
    for enc in encounters:
        env.encounters = [enc]
        for fight in range(args.fights):
            env.reset()
            c = client.combat()
            logs = {e["combatId"]: [] for e in c["enemies"]}
            print(f"[{enc} #{fight}] " + ", ".join(f"{e['modelId']}({e['hp']})" for e in c["enemies"]))
            while c.get("inCombat"):
                hand = c["player"]["hand"]
                idx = next((i for want in PRIORITY for i, x in enumerate(hand) if x["id"] == want and x["canPlay"]), None)
                living = [e for e in c["enemies"] if e["isAlive"]]
                # Random target exercises targeting; sim enemies are the living ones in order.
                pos = random.randrange(len(living)) if idx is not None and hand[idx]["targetType"] == "AnyEnemy" else None
                action = "end" if idx is None else f"play {idx}" + ("" if pos is None else f" @{living[pos]['modelId']}")
                sim = load(c, logs)
                if idx is None:
                    sim.end_turn()
                    client.end_turn()
                    for e in c["enemies"]:
                        if e["isAlive"]:
                            logs[e["combatId"]].append(e["intent"]["moveId"])
                else:
                    sim.play_card(idx, None if pos is None else pos + 1)
                    client.play(idx, None if pos is None else living[pos]["combatId"])
                after = wait_ready(client)
                problems = diff(c, action, after, sim, logs)
                steps += 1
                if problems:
                    mismatched += 1
                    print(f"  round {c['round']} {action} ({hand[idx]['id'] if idx is not None else ''}): " + "; ".join(problems))
                c = after
    print(f"\n{steps} steps compared, {mismatched} with mismatches")


if __name__ == "__main__":
    main()
