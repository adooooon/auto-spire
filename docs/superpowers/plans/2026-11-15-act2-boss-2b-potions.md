# Act 2 boss, part 2b: potions — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the 36 missing potions (every Uncommon and Rare, plus Attack, Skill, Power and Colorless Potion) to the sim, the run, the agent and live play, with 2a's three carry-overs: Alchemize, Entropy's missing statuses, and the prompt observation gaps.

**Architecture:** Potions stay in `sim/potions.py` (data) and `SimCombat.use_potion` (effects). Every potion in `POTION_POOL` becomes modeled, so `POTION_IDS` grows from 12 to 48 and every per-potion observation grows by name. New potion powers live in `SimCombat.pw` beside the card powers and run in the existing turn and damage hooks. Potions that ask the player reuse 2a's prompt kinds (`generated`, `hand`, `hand_multi`, `draw`, `discard`). Mid-fight potion gain gets one helper, `_procure_potion`.

**Tech Stack:** Python 3 (agent/, gymnasium, sb3-contrib MaskablePPO), C# Harmony mod (mod/AutoSpire/), decompiled game source in `decompiled/`.

**Spec:** `docs/superpowers/specs/2026-11-09-act2-boss-design.md`, stage 3, potions item. Part 2 is three plans (user's call, 2026-11-10): 2a colorless cards (done, merged 2026-11-13), 2b potions (this one), 2c relics plus Neow and the Act 2 Ancient. Part 3's retrain is done and merged (`ppo_sts2_sim_boss_b_final` + `ppo_sts2_sim_boss_run_v1_final`, 2026-11-15). The user asked to add the missing content after it (2026-11-15). The Expo poster (due about 2026-11-22) uses part 3's numbers and doesn't wait on this plan.

## Global Constraints

- Gains must come from the sim matching the game more closely, never from the sim being easier (spec, anti-goals).
- Write every rule from `decompiled/` (each potion in `MegaCrit.Sts2.Core.Models.Potions/`, its power in `MegaCrit.Sts2.Core.Models.Powers/`, `PotionFactory`, `PotionCmd`, `CombatManager`, `Hook`), not from Slay the Spire 1.
- Every new mechanic is checked against the live game (`sim.validate`, `live_check.py`).
- Act 1 clear no more than 4 points below the part 3 pair's 88.8% (spec, part 3 results).
- Push only to `mine`, never `origin`. Leave `mod/AutoSpire/obj/*` uncommitted. Don't change sim code in a checkout while a queue runs from it.
- Work in a new worktree `auto-spire-potions` on branch `potions`, from `rl-agent-sim` at 698b7ae or later. Symlink `.venv`, `decompiled` and `agent/models` from the main checkout, as 2a did.
- Commands run from `agent/` with `PY=~/projects/sts2-rl-bot/auto-spire/.venv/bin/python`. Self-checks: `$PY -m sim.test_engine`, `$PY -m sim.test_act`, `$PY -m test_run_env`, `$PY -m test_grow`, `$PY -m test_choice_test`. Each prints its `... ok` lines and exits 0.
- Commit messages follow the repo's style (`Sim: ...`, `Run env: ...`, `Live: ...`, `Docs: ...`) and end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Docs follow `CLAUDE.md`'s scopes. Rules go in `docs/game-architecture.md` (new section "Potions"), live progress in `docs/modding-approach.md`, and results in the spec.
- Source facts this plan relies on (checked 2026-11-15):
  - `CombatManager` draws the player's hand before `Hook.AfterSideTurnStart`, and `AfterEnergyReset` runs before `BeforeHandDraw`.
  - `Hook.ShouldDie` (Fairy in a Bottle) is asked before `ShouldDieLate` (Lizard Tail).
  - `PotionFactory` rolls rarity with one `NextFloat`: ≤ 0.1 Rare, ≤ 0.35 Uncommon, else Common, then a random potion of that rarity. The in-combat version drops potions with `CanBeGeneratedInCombat` false (Regen Potion, Fairy in a Bottle, Fruit Juice).
  - Usage: Fruit Juice, Entropic Brew and Blood Potion are `AnyTime`, Fairy in a Bottle is `Automatic`, and the rest are `CombatOnly`.
- **Left out (my call):** Wither's `FakeUpgrade`, which only the Act 3 monster Aeonglass calls. A `ponytail:` comment says so.

## Review Focus

1. **A potion prompt with nothing to pick:** Gambler's Brew or Ashwater with an empty hand, Touch of Insanity with no card that costs energy, Droplet of Precognition with an empty draw pile, Liquid Memories with an empty discard pile. Each does what the source does without pausing, and `pending_choice` stays unset. Attack Potion with 10 cards in hand sends its card to the discard pile (`AddGeneratedCardToCombat`). Test in Task 3.
2. **Fairy in a Bottle and Lizard Tail together:** Fairy saves the player first and empties its slot, and Lizard Tail stays unused. It also saves the player from self-inflicted HP loss (Beckon, Offering), and the fight goes on. Test in Task 2.
3. **Gaining a potion with full slots:** Alchemize does nothing and Entropic Brew stops at the first failure, with no exception. Five slots count with Potion Belt. A potion gained mid-fight is still there after the fight. Test in Task 1.
4. **Played twice:** Duplicator or Soldier's Stew on a prompt card (Headbutt, Purity, Discovery) or an X-cost card (Whirlwind) plays it twice without hanging. The extra play takes the non-pausable path, as Hidden Gem's Replay does. Test in Task 2.
5. **Seeds:** for seeds 0–9, the Act 1 map, encounter queue and first 3 card offers match the values before this plan. Potion effects use the combat rng, never the run's map or offer streams. Test in Task 5.

---

### Task 1: Potion data, plain effects and gaining potions

**Files:**
- Modify: `agent/sim/potions.py`, `agent/sim/engine.py` (`use_potion`, `_special` for Alchemize), `agent/sim/cards.py` (`NOT_BUYABLE`)
- Test: `agent/sim/test_engine.py`

**Interfaces:**
- Produces, in `sim/potions.py`:
  - `POTIONS` covers all 48 ids in `POTION_POOL`. Its target kinds are `"self"` (Self, AnyPlayer), `"enemy"` (AnyEnemy), `"all"` (AllEnemies) and `"auto"` (Fairy in a Bottle: never used by hand).
  - `ANY_TIME = frozenset({"BLOOD_POTION", "FRUIT_JUICE", "ENTROPIC_BREW"})`.
  - `NOT_IN_COMBAT_GEN = frozenset({"REGEN_POTION", "FAIRY_IN_A_BOTTLE", "FRUIT_JUICE"})`.
  - `random_potion(rng, in_combat: bool) -> str`, from `PotionFactory.CreateRandomPotion` with the thresholds above.
- In `sim/engine.py`: `SimCombat._procure_potion(pid) -> bool` puts `pid` in the first open slot (`len(self.potions)` already counts Potion Belt) and returns False when the slots are full (`PotionCmd.TryToProcure`). It replaces the ponytail "no mid-fight potion gain yet".
- `use_potion` handles, with the source's numbers:
  - Cure All: 1 energy, draw 2.
  - Fortifier: gain the current block again, Unpowered.
  - Fysh Oil: 1 Strength and 1 Dexterity.
  - Heart of Iron: 7 `PlatingPower`.
  - Liquid Bronze: 3 `ThornsPower`.
  - Potion of Binding: 1 Weak and 1 Vulnerable on every hittable enemy.
  - Stable Serum: 2 `RetainHandPower`.
  - Ship in a Bottle: 10 Unpowered block now and 10 `BlockNextTurnPower`.
  - Blessing of the Forge: upgrade every upgradable hand card for this combat, the way Armaments does.
  - Bottled Potential: the hand goes to the draw pile, shuffle, draw 5.
  - Fruit Juice: 5 max HP, as `CreatureCmd.GainMaxHp` does.
  - Snecko Oil: draw 7, then every non-X hand card with cost ≥ 0 costs `rng.randrange(4)` this turn or until played. This needs per-copy cost state on `CardCopy` (a `cost_override` attribute, read by `cost()`). A plain `str` copy is wrapped first.
  - Distilled Chaos: autoplay the top 3 draw-pile cards, through the path Mayhem and Havoc use.
  - Orobic Acid: one random Ironclad Attack, Skill and Power (`GetDistinctForCombat`), each free this turn, to hand.
  - Entropic Brew: `_procure_potion(random_potion(rng, in_combat=False))` until it fails.
- Alchemize: `_procure_potion(random_potion(rng, in_combat=True))`. It leaves `NOT_BUYABLE`, which keeps only `"SPLASH"`, and its `ponytail:` comment goes.

- [ ] **Step 1: Write the failing tests** in `sim/test_engine.py`:
  - All 48 pool ids are in `POTIONS`, and each target kind matches the source's `TargetType`.
  - One test per potion above, using the source's numbers.
  - Snecko Oil never changes an X-cost card or an Unplayable one. A changed card keeps its new cost on later turns until it is played (`SetThisTurnOrUntilPlayed`).
  - Over 10,000 draws, `random_potion(in_combat=True)` never returns an id in `NOT_IN_COMBAT_GEN`. Its rarity shares are within 1 point of 10% Rare, 25% Uncommon and 65% Common.
  - Review Focus 3: Alchemize with full slots changes nothing. Entropic Brew with 1 open slot of 3 fills that slot and stops. With Potion Belt it fills up to 5.
- [ ] **Step 2:** Run `$PY -m sim.test_engine`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `$PY -m sim.test_engine` and `$PY -m sim.test_act`. Expected: both ok.
- [ ] **Step 5:** Commit (`Sim: potion data, plain potion effects, potions gained mid-fight`).

### Task 2: Potion powers and Fairy in a Bottle

**Files:**
- Modify: `agent/sim/engine.py` (power hooks: turn start and end, energy reset, hand draw, damage dealt and taken, HP loss, card play count, `_kill_player`), `agent/env.py` (`PLAYER_POWERS`, `ENEMY_PW` observation)
- Test: `agent/sim/test_engine.py`

**Interfaces:**
- Consumes: Task 1's `POTIONS`.
- Produces the potions and the powers they apply, each from its `*Power.cs` hooks:
  - Clarity: draw 1 now, plus `ClarityPower` 3. Each hand draw is one card bigger, and the power decrements at `AfterSideTurnStart`, after the draw, so 3 bigger hands.
  - Duplicator: `DuplicationPower` 1. The next card is played one extra time, then the power decrements, and it is removed at the end of the turn.
  - Powdered Demise: enemy `DemisePower` 9. The enemy takes 9 Unblockable, Unpowered damage at the end of each of its turns. It never decrements, and it stacks.
  - Radiant Tincture: 1 energy now, plus `RadiancePower` 3. The power gives 1 energy after each energy reset and decrements.
  - Regen Potion: `RegenPower` 5. At the end of the player's turn, heal the power's amount, then decrement it.
  - Gigantification Potion: `GigantificationPower` 1. The next Attack card's powered damage is ×3 for every hit of that card, then the power decrements.
  - Lucky Tonic: `BufferPower` 1. The next HP loss above 0 becomes 0, then the power decrements. It covers every HP loss, self-inflicted included, after other reductions.
  - Mazaleth's Gift: player `RitualPower` 1, which gains the power's amount of Strength at the end of each player turn.
  - Shackling Potion: every hittable enemy loses 7 Strength this turn (`ShacklingPotionPower`, a `TemporaryStrengthPower`), the way Dark Shackles works.
  - Beetle Juice: enemy `ShrinkPower` 4. That enemy's powered attacks deal ×0.7, and the power decrements at the end of the enemy's turn.
  - Fairy in a Bottle: `_kill_player` asks Fairy before Lizard Tail. Fairy heals `max(max_hp * 0.3, 1)`, as `Creature.SetCurrentHpInternal` rounds it, and empties its slot.
  - Soldier's Stew: every Strike-tagged card in hand, draw, discard and exhaust piles gets +1 Replay, through 2a's `replays`.
- `env.PLAYER_POWERS` gains `ClarityPower`, `DuplicationPower`, `RadiancePower`, `RegenPower`, `GigantificationPower`, `BufferPower` and `RitualPower`. `ENEMY_PW` appends `ShrinkPower` and `DemisePower` at its end. Both are grown by name in Task 7.

- [ ] **Step 1: Write the failing tests**, one per potion, using the source's trigger and numbers. Also:
  - Clarity used on turn 1 gives hands of 6 on turns 2, 3 and 4, and 5 on turn 5.
  - Gigantification on Twin Strike triples both hits, and the next Attack is normal.
  - Buffer under a fully blocked hit stays at 1.
  - Review Focus 2: Fairy plus Lizard Tail. An enemy hit for lethal leaves HP at 30% of max, the Fairy slot empty and Lizard Tail unused. Beckon's end-of-turn HP loss at 6 HP triggers Fairy, and the fight goes on.
  - Review Focus 4: Duplicator, then Headbutt, Purity, Discovery and Whirlwind each, over 200 seeded fights. Each finishes, with `pending_choice` unset after the extra play.
- [ ] **Step 2:** Run `$PY -m sim.test_engine`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `$PY -m sim.test_engine` and `$PY -m test_run_env`. Expected: both ok.
- [ ] **Step 5:** Commit (`Sim: potion powers and Fairy in a Bottle`).

### Task 3: Potions that ask the player

**Files:**
- Modify: `agent/sim/engine.py` (`use_potion`, `_ask`, `_take`, `_finish_choice`, `combat_dict`), `agent/env.py` (prompt observation and mask)
- Test: `agent/sim/test_engine.py`, `agent/test_run_env.py`

**Interfaces:**
- Consumes: 2a's prompt kinds and answers (`choose_card`, `choose_generated`, `choose_draw`, `choose_done`, `choose_discard`).
- Produces:
  - Prompts that open from a potion, with `pending_choice["source"]` set to the potion id:
    - Attack, Skill and Power Potion: `"generated"` with 3 distinct Ironclad cards of that type. Colorless Potion uses 3 from `COLORLESS_GENERATED`. Each can be skipped, and the pick is free this turn.
    - Gambler's Brew: `"hand_multi"` with no limit (`most` = hand size). The picks are discarded and that many cards drawn (`DiscardAndDraw`).
    - Ashwater: `"hand_multi"` with no limit. Each pick is exhausted.
    - Touch of Insanity: `"hand"`, offering only cards that cost energy. The pick is free for the rest of combat (a `free_combat` flag on `CardCopy`, read by `cost()`).
    - Droplet of Precognition: `"draw"` with the whole draw pile. The pick goes to hand.
    - Liquid Memories: `"discard"`. The pick goes to hand, free this turn.
  - `AfterPotionUsed` (Reptile Trinket, Belt Buckle) moves into `SimCombat._after_potion(pid)`. It runs when the potion's prompt finishes, or at once if none opened.
  - The observation block is appended last:
    - the prompt's potion source, one-hot over `POTION_PROMPTS = ("ATTACK_POTION", "SKILL_POTION", "POWER_POTION", "COLORLESS_POTION", "GAMBLERS_BREW", "ASHWATER", "TOUCH_OF_INSANITY", "DROPLET_OF_PRECOGNITION", "LIQUID_MEMORIES")`;
    - 2a carry-over, picks left for a `"hand_multi"` (`(most - picked) / 10`, capped at 1);
    - 2a carry-over, the offered draw-pile cards for a `"draw"` prompt, one flag per `CARD_IDS` entry (Seeker Strike's 3, Secret Technique's Skills, Droplet's whole pile).
  - No new actions: the mask allows the open prompt's answers as in 2a.

- [ ] **Step 1: Write the failing tests:**
  - Each prompt potion pauses with the right kind, source and options, and each answer does what the source does.
  - Reptile Trinket's Strength from Attack Potion arrives after the pick, not before.
  - Review Focus 1: each empty case above does nothing and doesn't pause. Attack Potion with 10 cards in hand puts its pick in the discard pile.
  - `test_run_env`: `OBS_DIM` matches `_obs().shape`. Purity's picks-left drops by 0.1 per pick. Seeker Strike's 3 options are flagged and nothing else is.
- [ ] **Step 2:** Run `$PY -m sim.test_engine` and `$PY -m test_run_env`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run all five self-checks. Expected: all ok.
- [ ] **Step 5:** Commit (`Sim: potion prompts; picks-left and draw options observed`).

### Task 4: Entropy's missing statuses

**Files:**
- Modify: `agent/sim/cards.py`, `agent/sim/engine.py` (`STATUS_TRANSFORMS`, end of turn in hand, card drawn)
- Test: `agent/sim/test_engine.py`

**Interfaces:**
- Produces `CardDef`s, with the game's ids:
  - `BECKON`: cost 1, Status, playable and does nothing. At end of turn in hand, the player loses 6 HP (Unblockable, Unpowered).
  - `BURN`: Unplayable. At end of turn in hand, the player takes 2 damage (blockable).
  - `DEBRIS`: cost 1, Exhaust, does nothing.
  - `WITHER`: Unplayable. At end of turn in hand, the player takes 3 damage (blockable).
  - `VOID`: Unplayable, Ethereal. When drawn, the player loses 1 energy.
- `STATUS_TRANSFORMS = ("BECKON", "BURN", "DAZED", "DEBRIS", "INFECTION", "WITHER", "SLIMED", "TOXIC", "VOID", "WOUND")`, in `StatusCardPool` order, and the engine's ponytail note goes. They join `CARD_IDS`, so Task 7 grows them in with `--insert-cards`.

- [ ] **Step 1: Write the failing tests:** each card's effect, plus Entropy's transform reaching all 10 statuses over 2,000 seeded transforms.
- [ ] **Step 2:** Run `$PY -m sim.test_engine`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `$PY -m sim.test_engine` and `$PY -m test_run_env`. Expected: both ok.
- [ ] **Step 5:** Commit (`Sim: Beckon, Burn, Debris, Wither and Void for Entropy`).

### Task 5: Potions in the run

**Files:**
- Modify: `agent/sim/act.py` (drink outside combat), `agent/run_env.py` (`DRINK` mask, carry potions out of a fight), `agent/env.py` (`random_potions`), `agent/run.py` (`baseline_action`), `agent/live.py` (`do_potion`)
- Test: `agent/sim/test_act.py`, `agent/test_run_env.py`

**Interfaces:**
- Consumes: Task 1's `ANY_TIME`, `random_potion` and `_procure_potion`.
- Produces:
  - `Run.drink(slot)` handles every `ANY_TIME` potion outside combat:
    - Blood Potion: as now.
    - Fruit Juice: 5 max HP.
    - Entropic Brew: fill open slots with `random_potion(in_combat=False)` from the run rng.
  - The run env's `DRINK` mask allows exactly these, at the decisions where Blood Potion is allowed now.
  - Every pool potion can now be taken from rewards and bought in shops (the "unmodeled potions can't be taken" rule goes). `live.py` no longer skips them.
  - A potion gained mid-fight (Alchemize, Entropic Brew) reaches `run.potions` after the fight.
  - `random_potions` for random-deck training draws from every id but `FAIRY_IN_A_BOTTLE`, so Fairy appears only through rewards and shops. That's my call: a Fairy can't be used by hand, so a random slot of it only blocks a slot.
  - `baseline_action` drinks nothing new (my call: the baseline stays the same).

- [ ] **Step 1: Write the failing tests:**
  - Drinking Fruit Juice and Entropic Brew outside combat does what the source does.
  - The mask never allows drinking a `CombatOnly` potion outside combat, or Fairy anywhere.
  - Review Focus 5: for seeds 0–9, the Act 1 map, encounter queue and first 3 card offers match values captured before this task.
  - `test_run_env`: 300 runs with a random legal policy, starting with 3 random potions, finish without an exception.
- [ ] **Step 2:** Run `$PY -m sim.test_act` and `$PY -m test_run_env`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run all five self-checks. Expected: all ok.
- [ ] **Step 5:** Document "Potions" in `docs/game-architecture.md`: the pools and rarity roll, target kinds and usage, each potion's power and hook, the prompts, Fairy's place before Lizard Tail, and what's left out. Commit (`Run env: every potion in rewards, shops and outside combat`).

### Task 6: Live play with every potion

**Files:**
- Modify: `mod/AutoSpire/AutoSpireMod.cs` (prompt state: source from a potion), `agent/live.py`, `agent/env.py` (live prompt mapping), `agent/live_check.py`, `agent/sim/validate.py`
- Docs: `docs/modding-approach.md`

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces:
  - `AgentSelector`'s pending prompt reports `source` as the potion id when a potion opened it (`CardSelectorPrefs` source).
  - `env.py` maps it to Task 3's potion-source one-hot. The live `/exec potion <slot> [targetId]` already uses potions in and out of combat.
  - Stage potions with the dev console's `potion <ID>`, through `/exec potion <ID>`.

- [ ] **Step 1:** Add staged checks to `live_check.py`:
  - One per prompt potion: Attack Potion (pick and skip), Gambler's Brew (2 picks then done), Ashwater, Touch of Insanity, Droplet of Precognition and Liquid Memories. Each matches the sim's hand and piles after.
  - Clarity's hand sizes over the next 3 turns.
  - Gigantification on a two-hit Attack.
  - Fairy in a Bottle's heal after a lethal hit, which pins the rounding.
  - Snecko Oil's costs, all between 0 and 3.
  - Entropic Brew filling 2 open slots.
- [ ] **Step 2:** Run `$PY live_check.py` with the game running. Expected: the new checks fail.
- [ ] **Step 3:** Implement. Build with `mod/build.sh`.
- [ ] **Step 4:** Run `sim.validate` with 3 random potions per fight, used by the policy, over the Act 1 and Hive encounters. Expected: no mismatches beyond those already known. Record the step count in `docs/modding-approach.md`.
- [ ] **Step 5:** Run `$PY live_check.py`. Expected: every check passes (31 old plus the new ones), with no `[ERROR]` lines from the mod in `godot.log`.
- [ ] **Step 6:** Commit (`Live: every potion, potion prompts`). Leave `mod/AutoSpire/obj/*` out.

### Task 7: Grow the models and check nothing regressed

**Files:**
- Modify: `agent/env.py` (`combat_maps`), `agent/run_env.py` (`run_maps`), `agent/test_grow.py`, `agent/test_data/record_grow_fixture.py`, `agent/test_data/grow_fixture.pkl.gz`
- Modify: `docs/superpowers/specs/2026-11-09-act2-boss-design.md` (add "Part 2b results")

**Interfaces:**
- Consumes: every new block from Tasks 1–4.
- Produces: `combat_maps()` and `run_maps()` map part 3's layout (the `boss_b_final` and `boss_run_v1_final` models) to the new one:
  - old `CARD_IDS` placed by name (`"cards"` segments);
  - each potion one-hot (slots 0–2, slots 3–4, the offered potion, shop potions) as an `(OLD_POTION_IDS, POTION_IDS)` pair;
  - `PLAYER_POWERS` by name;
  - each enemy slot's `ENEMY_PW` with the new powers at its end;
  - the new prompt block unmapped.
  - The 2a-era map they replace goes away (ponytail: one layout back, as before).

- [ ] **Step 1:** Re-record the grow fixture at 698b7ae with `record_grow_fixture.py`, and point `test_grow` at `ppo_sts2_sim_boss_b_final.zip` and `ppo_sts2_sim_boss_run_v1_final.zip`. Expected: `$PY -m test_grow` passes (same action on 200 recorded observations).
- [ ] **Step 2:** Grow both: `$PY grow.py models/ppo_sts2_sim_boss_b_final.zip models/ppo_sts2_sim_boss_g3.zip --env combat --insert-cards` and `$PY grow.py models/ppo_sts2_sim_boss_run_v1_final.zip models/ppo_sts2_sim_boss_run_g3.zip --env run --insert-cards`. Expected: both print `grow self-check ok`.
- [ ] **Step 3:** Evaluate: `$PY run.py --model models/ppo_sts2_sim_boss_g3.zip --maps generated --run-model models/ppo_sts2_sim_boss_run_g3.zip --runs 500 --n 16`, under `caffeinate -i` on AC power. Expected: no crashes, `stuck=0`, and Act 1 at 84.8% or more. The untrained model sees 36 potions for the first time.
- [ ] **Step 4:** Run `boss_report.py` on the grown pair (1,500 runs) and add the per-boss table to "Part 2b results", next to part 3's.
- [ ] **Step 5:** Commit (`Docs: Act 2 boss part 2b results`). Report to the user. Plan 2c starts after the merge, and the retrain on all new content comes after 2c.
