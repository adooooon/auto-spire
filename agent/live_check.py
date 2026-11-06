"""Stage the paths a real run rarely reaches, in the live game, and compare them with the sim's rules.

Unlike a real run this uses debug commands (fight, event, room, gold). It prints one PASS or FAIL per check.
    python live_check.py --run-model models/ppo_sts2_sim_run_policy_v6pc.zip --model models/ppo_sts2_sim_act1_pc_v13c.zip
"""
from __future__ import annotations

import argparse
import time
import traceback
from collections import Counter

from env import CARD_IDS, CHOOSE_DISCARD, CHOOSE_HAND, MAX_ENEMIES, _ready
from live import LiveGame, _event_opts


def pile(p: dict, name: str) -> list[str]:
    return [c["id"] for c in p.get(name) or []]


def power(p: dict, name: str) -> int:
    return next((x["amount"] for x in p.get("powers") or [] if x["name"] == name), 0)


class Check:
    def __init__(self, game: LiveGame):
        self.game, self.client = game, game.client
        self.results: list[tuple[str, bool, str]] = []

    def do(self, cmd: str, settle: float = 0.3) -> dict:
        r = self.client.exec(cmd, settle=settle)
        assert "error" not in r and r.get("ok", True), f"{cmd}: {r}"
        return r

    def wait(self, test, what: str, timeout: float = 20.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            s = self.client.state()
            if test(s):
                return s
            time.sleep(0.2)
        raise AssertionError(f"timed out waiting for {what}; screen {s.get('screen')}")

    def run(self, name: str, fn) -> None:
        try:
            fn()
            self.results.append((name, True, ""))
            print(f"PASS {name}", flush=True)
        except Exception as exc:  # noqa: BLE001 - one failed check must not hide the rest
            self.results.append((name, False, repr(exc)))
            print(f"FAIL {name}: {exc!r}", flush=True)
            traceback.print_exc()

    # --- prompt cards, through the same env.step the combat model uses ----------------------------------

    def fight_with(self, card: str, discard: tuple[str, ...] = ()) -> tuple:
        self.do("fight NIBBITS_WEAK", settle=0.5)
        self.client.wait_for(_ready, timeout=30.0)
        for c in discard:
            self.do(f"card {c} Discard")
        self.do(f"card {card} Hand")
        self.do("energy 5")
        combat = self.client.wait_for(_ready, timeout=15.0)
        env = self.game.fight
        env._combat, env._steps = combat, 0
        hand = pile(combat["player"], "hand")
        assert card in hand, (card, hand)
        return env, combat, hand.index(card) * MAX_ENEMIES

    def finish_fight(self) -> None:
        self.do("win")
        self.wait(lambda s: s["screen"] != "combat", "the fight to end")

    def play_to_prompt(self, env, action: int, kind: str) -> dict:
        env.step(action)
        combat = env._combat
        assert (combat.get("choice") or {}).get("kind") == kind, combat.get("choice")
        return combat

    def burning_pact(self) -> None:
        env, _, a = self.fight_with("BURNING_PACT")
        combat = self.play_to_prompt(env, a, "hand")
        assert combat["choice"]["source"] == "BURNING_PACT", combat["choice"]
        assert env.action_masks()[CHOOSE_HAND]
        p = combat["player"]
        picked, size = pile(p, "hand")[0], len(pile(p, "hand"))
        env.step(CHOOSE_HAND)
        p = env._combat["player"]
        assert picked in pile(p, "exhaustPile"), pile(p, "exhaustPile")
        assert len(pile(p, "hand")) == size + 1, "exhausted 1, drew 2"
        self.finish_fight()

    def brand(self) -> None:
        env, combat, a = self.fight_with("BRAND")
        hp = combat["player"]["hp"]
        p = self.play_to_prompt(env, a, "hand")["player"]
        assert p["hp"] == hp - 1, "HP is lost before the prompt"
        picked = pile(p, "hand")[0]
        env.step(CHOOSE_HAND)
        p = env._combat["player"]
        assert picked in pile(p, "exhaustPile") and power(p, "StrengthPower") == 1, p.get("powers")
        self.finish_fight()

    def headbutt(self) -> None:
        env, combat, a = self.fight_with("HEADBUTT", ("STRIKE_IRONCLAD", "DEFEND_IRONCLAD"))
        hp = sum(e["hp"] for e in combat["enemies"])
        combat = self.play_to_prompt(env, a, "discard")
        assert sum(e["hp"] for e in combat["enemies"]) == hp - 9, "damage comes before the prompt"
        assert combat["choice"]["source"] == "HEADBUTT", combat["choice"]
        mask = env.action_masks()
        assert mask[CHOOSE_DISCARD + CARD_IDS.index("DEFEND_IRONCLAD")] and mask[CHOOSE_DISCARD + CARD_IDS.index("STRIKE_IRONCLAD")]
        env.step(CHOOSE_DISCARD + CARD_IDS.index("DEFEND_IRONCLAD"))
        before = Counter(pile(env._combat["player"], "hand"))
        self.do("draw 1", settle=0.5)
        after = Counter(pile(self.client.wait_for(_ready, timeout=15.0)["player"], "hand"))
        assert after - before == Counter(["DEFEND_IRONCLAD"]), "the chosen card is on top of the draw pile"
        self.finish_fight()

    # --- the five modeled events: each option's numbers must match Run.start_event ------------------------

    def open_event(self, event: str) -> dict:
        self.do("close_map")
        self.do(f"event {event}", settle=0.5)
        s = self.wait(lambda s: s["screen"] == "event" and s.get("details") and s["details"]["id"] == event
                      and s["details"].get("options") and not s["details"]["finished"], f"event {event}")
        return s

    def leave_event(self) -> None:
        """Answer whatever the event left behind, as a run would, until the map opens."""
        g = self.game
        g.seen = set()
        deadline = time.monotonic() + 45.0
        while time.monotonic() < deadline:
            s = self.client.state()
            g.run.sync(s)
            if s["screen"] == "map":
                return
            if s["screen"] == "event" and s.get("details"):
                g.do_event(s["details"])
            elif s["screen"] == "rewards":
                g.do_rewards(s["rewards"])
            elif s["screen"] == "choice":
                g.do_choice(s["choice"])
            else:
                time.sleep(0.2)
        raise AssertionError(f"never got back to the map from {s['screen']}")

    def event_option(self, event: str, option: int, expect) -> None:
        def check():
            self.do("heal 999")
            if event == "SLIPPERY_BRIDGE":
                self.do("card INFLAME Deck")
            s = self.open_event(event)
            d, before = s["details"], s["player"]
            hp_loss, gold, max_hp = _event_opts(event, d["vars"])[option]
            self.do(f"option {option}", settle=0.5)
            s = self.wait(lambda s: (s["player"]["hp"], s["player"]["gold"], len(s["player"]["deck"]), len(s["player"]["relics"]))
                          != (before["hp"], before["gold"], len(before["deck"]), len(before["relics"])), "the option to take effect")
            time.sleep(1.0)
            s = self.client.state()
            p = s["player"]
            assert p["hp"] - before["hp"] == max_hp - hp_loss, ("hp", before["hp"], p["hp"], hp_loss, max_hp)
            assert p["maxHp"] - before["maxHp"] == max_hp, ("maxHp", before["maxHp"], p["maxHp"])
            assert p["gold"] - before["gold"] == int(gold), ("gold", before["gold"], p["gold"], gold)
            if expect:
                expect(before, p, d, s)
            if event == "SLIPPERY_BRIDGE" and option == 1:  # hold on again costs 1 more, then let the card go
                assert s["details"]["vars"]["HpLoss"] == hp_loss + 1, s["details"]["vars"]
                self.do("option 0", settle=0.5)
            self.leave_event()
        self.run(f"event {event} option {option}", check)

    @staticmethod
    def gained(card: str):
        def test(before, p, d, s):
            assert (Counter(pile(p, "deck")) - Counter(pile(before, "deck"))) == Counter([card]), pile(p, "deck")
        return test

    @staticmethod
    def lost_at_risk(before, p, d, s):
        assert (Counter(pile(before, "deck")) - Counter(pile(p, "deck"))) == Counter([d["atRisk"]]), d.get("atRisk")

    @staticmethod
    def sword(before, p, d, s):
        assert "SWORD_OF_STONE" in {r["id"] for r in p["relics"]}, p["relics"]

    # --- shop and potions ---------------------------------------------------------------------------------

    def open_shop(self) -> dict:
        self.do("gold 999")
        self.do("close_map")
        self.do("room Shop", settle=0.5)
        return self.wait(lambda s: s["screen"] == "shop" and s.get("details"), "the shop")

    def shop_relic(self) -> None:
        s = self.open_shop()
        i, entry = next((i, e) for i, e in enumerate(s["details"]["relics"]) if e.get("id"))
        gold = s["player"]["gold"]
        self.do(f"buy relic {i}")
        s = self.wait(lambda s: s["player"]["gold"] != gold, "the purchase")
        assert s["player"]["gold"] == gold - entry["cost"], (gold, entry)
        assert entry["id"] in {r["id"] for r in s["player"]["relics"]}, entry

    def shop_removal(self) -> None:
        s = self.open_shop()
        cost, gold, deck = s["details"]["removal"]["cost"], s["player"]["gold"], Counter(pile(s["player"], "deck"))
        self.game.pending_remove = "STRIKE_IRONCLAD"
        self.do("buy removal", settle=0.5)
        s = self.wait(lambda s: s["screen"] == "choice", "the removal prompt")
        self.game.do_choice(s["choice"])
        s = self.wait(lambda s: s["player"]["gold"] != gold, "the removal")
        assert s["player"]["gold"] == gold - cost, (gold, cost)
        assert deck - Counter(pile(s["player"], "deck")) == Counter(["STRIKE_IRONCLAD"]), pile(s["player"], "deck")
        s = self.wait(lambda s: s["screen"] == "shop" and s.get("details"), "the shop again")
        assert s["details"]["removal"]["used"], s["details"]["removal"]
        self.do("proceed")
        self.wait(lambda s: s["screen"] == "map", "the map")

    def potions(self) -> None:
        self.clear_potions()
        for p in ("BLOOD_POTION", "SPEED_POTION", "ENERGY_POTION"):
            self.do(f"potion {p}", settle=0.5)
        slots = self.client.state()["potionSlots"]
        assert slots == ["BLOOD_POTION", "SPEED_POTION", "ENERGY_POTION"], slots
        self.do("drop_potion 1", settle=0.5)
        s = self.wait(lambda s: s["potionSlots"][1] is None, "the drop")
        assert s["potionSlots"] == ["BLOOD_POTION", None, "ENERGY_POTION"], s["potionSlots"]
        # Blood Potion between fights: 20% of max HP, truncated (Run.drink), and the slots keep their places.
        self.open_event("JUNGLE_MAZE_ADVENTURE")
        self.do("option 0", settle=0.5)
        self.wait(lambda s: s["player"]["hp"] < s["player"]["maxHp"], "the HP loss")
        time.sleep(1.0)
        self.leave_event()
        before = self.client.state()["player"]
        self.do("potion 0", settle=0.5)
        s = self.wait(lambda s: s["potionSlots"][0] is None, "the potion to be drunk")
        time.sleep(1.0)
        s = self.client.state()
        assert s["player"]["hp"] == min(before["maxHp"], before["hp"] + before["maxHp"] * 20 // 100), (before["hp"], s["player"]["hp"])
        assert s["potionSlots"] == [None, None, "ENERGY_POTION"], s["potionSlots"]

    def clear_potions(self) -> None:
        for i, p in enumerate(self.client.state()["potionSlots"]):
            if p:
                self.do(f"drop_potion {i}", settle=0.5)

    # ------------------------------------------------------------------------------------------------------

    def all(self) -> int:
        self.client.full_restart()
        self.run("Burning Pact prompt", self.burning_pact)
        self.run("Brand prompt", self.brand)
        self.run("Headbutt prompt", self.headbutt)
        self.event_option("BYRDONIS_NEST", 0, None)
        self.event_option("BYRDONIS_NEST", 1, self.gained("BYRDONIS_EGG"))
        self.event_option("JUNGLE_MAZE_ADVENTURE", 0, None)
        self.event_option("JUNGLE_MAZE_ADVENTURE", 1, None)
        self.event_option("SLIPPERY_BRIDGE", 0, self.lost_at_risk)
        self.event_option("SLIPPERY_BRIDGE", 1, None)
        self.event_option("SUNKEN_STATUE", 0, self.sword)
        self.event_option("SUNKEN_STATUE", 1, None)
        self.event_option("THE_LEGENDS_WERE_TRUE", 0, self.gained("SPOILS_MAP"))
        self.event_option("THE_LEGENDS_WERE_TRUE", 1, None)
        self.run("shop relic", self.shop_relic)
        self.run("shop removal", self.shop_removal)
        self.run("potion drop and Blood Potion", self.potions)
        failed = [r for r in self.results if not r[1]]
        print(f"{len(self.results) - len(failed)}/{len(self.results)} passed")
        for name, _, why in failed:
            print(f"  FAILED {name}: {why[:200]}")
        return len(failed)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--run-model", required=True)
    args = ap.parse_args()
    raise SystemExit(min(Check(LiveGame(args.model, args.run_model)).all(), 1))
