from choice_test import headbutt_subset, passes_flip, passes_headbutt, passes_hp, passes_junk, score_headbutt, score_junk

hand = lambda picked: {"source": "BRAND", "options": ["WOUND", "BASH", "BASH", "BASH"], "picked": picked}
assert score_junk([hand("WOUND")] * 3 + [hand("BASH")]) == (0.75, 0.25)
assert passes_junk(0.75, 0.25) and not passes_junk(0.25, 0.25)  # a random chooser fails
assert not passes_junk(0.5, 0.1)  # the bar is over 50%
assert not passes_junk(0.6, 0.4)  # and twice chance
assert score_junk([{"source": "BRAND", "options": ["BASH", "BASH"], "picked": "BASH"}]) == (0.0, 0.0)  # no junk: not scored

disc = lambda picked: {"source": "HEADBUTT", "options": ["BASH", "STRIKE_IRONCLAD", "WOUND", "DEFEND_IRONCLAD"], "picked": picked}
assert score_headbutt([disc("BASH")] * 3 + [disc("WOUND")]) == (0.75, 0.25)
assert passes_headbutt(0.75, 0.25) and not passes_headbutt(0.3, 0.25)
assert passes_flip(0.51) and not passes_flip(0.5)
assert passes_hp(0.5, 0.4) and not passes_hp(0.5, 0.45)
# duplicates count in hand but not in a discard pile (each id is one action)
assert score_junk([{"source": "BRAND", "options": ["WOUND", "BASH", "BASH", "BASH"], "picked": "BASH"}])[1] == 0.25
assert score_headbutt([{"source": "HEADBUTT", "options": ["BASH", "WOUND", "WOUND", "WOUND"], "picked": "WOUND"}]) == (0.0, 0.5)

# row 3 subset: scored only where the first legal (lowest CARD_IDS) id is basic or junk and a good card is there too
sub = lambda *o: {"source": "HEADBUTT", "options": list(o), "picked": o[0]}
assert headbutt_subset([sub("BASH", "STRIKE_IRONCLAD", "WOUND")]) == []  # first id is BASH
assert len(headbutt_subset([sub("STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "WOUND", "DEMON_FORM")])) == 1  # DEFEND_IRONCLAD first
assert headbutt_subset([sub("DEFEND_IRONCLAD", "WOUND")]) == []  # no good card

# The combat-reading rows, against stub choosers that do and don't look at the situation.
import numpy as np
from choice_test import headbutt_subset, score_headbutt_subset, collect, hp_rates, swap_rate
from env import CHOOSE_DISCARD, CHOOSE_HAND, CARD_IDS, STS2CombatEnv
from sim.cards import CARDS
from sim.engine import SimClient


class Stub:
    def __init__(self, env, smart):
        self.env, self.smart = env, smart

    def predict(self, obs, action_masks, deterministic=True):
        c = self.env._combat
        legal = np.flatnonzero(action_masks)
        if not self.smart or not c.get("choice"):  # play: first card that can be played, else end the turn
            return np.array(legal[0]), None
        p = c["player"]
        if c["choice"]["kind"] == "hand":
            junk = [i for i, x in enumerate(p["hand"]) if CARDS[x["id"]].rarity == "Status"]
            return np.array(CHOOSE_HAND + (junk or [0])[0]), None
        want_block = p["hp"] < 0.5 * p["maxHp"]
        good = [a for a in legal if (CARDS[CARD_IDS[a - CHOOSE_DISCARD]].block > 0) == want_block]
        return np.array((good or legal)[0]), None


env = STS2CombatEnv(client=SimClient(seed=0))
for smart in (True, False):
    m = Stub(env, smart)
    brand = collect(m, "BURNING_PACT", fights=25, seed=1, env=env)
    head = collect(m, "HEADBUTT", fights=25, seed=1, env=env)
    before = env._combat
    swap, n_swap = swap_rate(m, env, brand, seed=0)
    low, high, n_hp = hp_rates(m, env, head)
    print(f"smart={smart}: prompts {len(brand)}/{len(head)} swap {swap:.2f} (n={n_swap}) hp {low:.2f}/{high:.2f} (n={n_hp})")
    assert env._combat is before  # the read-only rows leave the fight as they found it
    assert n_swap >= 5 and n_hp >= 5, "stub runs found too few prompts to test the rows"
    assert passes_flip(swap) == smart and passes_hp(low, high) == smart  # the rows can fail, not just pass

class Last(Stub):  # answers prompts with the last legal action, plays the first
    def predict(self, obs, action_masks, deterministic=True):
        legal = np.flatnonzero(action_masks)
        return np.array(legal[-1] if self.env._combat.get("choice") else legal[0]), None


for name, m, want in (("first-legal", Stub(env, False), False), ("last-legal", Last(env, False), False)):
    head = collect(m, "HEADBUTT", fights=60, seed=2, env=env)
    r, ch = score_headbutt_subset(head)
    ro, cho = score_headbutt(head)
    n = len(headbutt_subset(head))
    print(f"{name}: row 3 subset n={n} {r:.2f} vs {ch:.2f}; overall {ro:.2f} vs {cho:.2f}")
    assert n >= 10 and passes_headbutt(r, ch) == want
print("choice test checks ok")

# Only the card under test is scored; a row below MIN_N is LOW N, never a pass.
from choice_test import from_card, print_verdict
mixed = collect(Stub(env, False), "BURNING_PACT", fights=60, seed=3, env=env)
assert len(from_card(mixed, "BURNING_PACT")) <= len(mixed) and all(p["source"] == "BURNING_PACT" for p in from_card(mixed, "BURNING_PACT"))
assert from_card([{"source": "BRAND"}, {"source": "HEADBUTT"}], "BRAND") == [{"source": "BRAND"}]
assert print_verdict([("a", 100, "x", True), ("b", 29, "y", True)]) == "NOT ALL PASS"
assert print_verdict([("a", 100, "x", True), ("b", 30, "y", True)]) == "ALL PASS"
print("choice test fix checks ok")
