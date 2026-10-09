"""Compare sim vs. live game turn-by-turn under the same scripted policy.

Nibbit's starting HP is randomized in both backends and there's no shared
seed control via the mod, so this doesn't diff exact HP numbers — instead it
diffs the *mechanics*: per-card damage dealt, enemy move order, block/energy
arithmetic, turn count shape. See docs/modding-approach.md Phase A.
"""
from __future__ import annotations

from client import AutoSpireClient
from sim.engine import SimClient


def scripted_trajectory(client, label: str) -> list[dict]:
    client.exec("heal 999")
    client.exec("fight NIBBITS_WEAK", settle=0.5 if isinstance(client, AutoSpireClient) else 0.0)
    client.exec("heal 999")
    log = []
    combat = client.wait_for(lambda c: c.get("inCombat") and c.get("isPlayPhase"), timeout=15.0)
    turn = 0
    while combat.get("inCombat"):
        turn += 1
        player = combat["player"]
        enemy = combat["enemies"][0]
        log.append({
            "turn": turn,
            "player_hp": player["hp"], "player_block": player["block"], "energy": player["energy"],
            "enemy_hp": enemy["hp"], "enemy_block": enemy["block"],
            "intent": enemy["intent"]["moveId"],
            "hand_titles": [c["title"] for c in player["hand"]],
        })
        # scripted policy: play Bash if playable, else Strike, else Defend, else end turn
        hand = player["hand"]
        action = None
        for want in ("Bash", "Strike", "Defend"):
            for i, c in enumerate(hand):
                if c["title"] == want and c["canPlay"]:
                    action = i
                    break
            if action is not None:
                break
        if action is not None:
            result = client.play(action)
        else:
            result = client.end_turn()
        log.append({"turn": turn, "action_result": result})

        if isinstance(client, AutoSpireClient):
            import time
            deadline = time.monotonic() + 8.0
            while time.monotonic() < deadline:
                combat = client.combat()
                if not combat.get("inCombat") or combat.get("isPlayPhase"):
                    break
                time.sleep(0.05)
        else:
            combat = client.combat()
    print(f"[{label}] combat ended after {turn} turns")
    return log


if __name__ == "__main__":
    live = AutoSpireClient()
    if not live.ping():
        raise SystemExit("live game not reachable — launch it first")

    print("=== LIVE ===")
    live_log = scripted_trajectory(live, "live")
    for entry in live_log:
        print(entry)

    print("\n=== SIM ===")
    sim_log = scripted_trajectory(SimClient(seed=123), "sim")
    for entry in sim_log:
        print(entry)
