# Act 2 boss, part 2a: colorless cards — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the 53 single-player colorless cards (`ColorlessCardPool` without `CardMultiplayerConstraint.MultiplayerOnly`) and their upgrades to the sim, the shops, the agent and live play.

**Architecture:** Colorless cards are ordinary `CardDef`s in `sim/cards.py` with `rarity` Uncommon/Rare and a new `colorless=True` field. They join `CARD_IDS`, so every per-card observation and action grows by name, as Armaments did in part 1. Shops gain the game's two colorless slots. New mechanics go where their kind already lives: keywords and generic fields on `CardDef`, card logic in `SimCombat._special`, powers in the turn hooks, prompts in `_ask`.

**Tech Stack:** Python 3 (agent/, gymnasium, sb3-contrib MaskablePPO), C# Harmony mod (mod/AutoSpire/), decompiled game source in `decompiled/`.

**Spec:** `docs/superpowers/specs/2026-11-09-act2-boss-design.md`, stage 3, colorless item. Part 2 is three plans (user's call, 2026-11-10): 2a colorless cards (this one), 2b potions, 2c relics plus Neow and the Act 2 Ancient. Each is merged before the next starts. The modded profile is fully unlocked (`unlock all`, 2026-11-10), so the sim models every card, with no epoch filter.

## Global Constraints

- Gains must come from the sim matching the game more closely, never from the sim being easier (spec, anti-goals).
- Write every rule from `decompiled/` (each card in `MegaCrit.Sts2.Core.Models.Cards/`, its powers in `MegaCrit.Sts2.Core.Models.Powers/`, `MerchantInventory`, `MerchantCardEntry`, `CardFactory`), not from Slay the Spire 1.
- Every new mechanic is checked against the live game (`sim.validate`, `live_check.py`).
- Act 1 clear no more than 4 points below the grown reference (79.4%, part 1 results).
- Push only to `mine`, never `origin`. Leave `mod/AutoSpire/obj/*` uncommitted. Don't change sim code in a checkout while a queue runs from it.
- Work in a new worktree `auto-spire-colorless` on branch `colorless`, from `rl-agent-sim` at 326edb2 or later. Symlink `.venv`, `decompiled` and `agent/models` from the main checkout, as part 1 did.
- Commands run from `agent/` with `PY=~/projects/sts2-rl-bot/auto-spire/.venv/bin/python`. Self-checks: `$PY -m sim.test_engine`, `$PY -m sim.test_act`, `$PY -m test_run_env`, `$PY -m test_grow`, `$PY -m test_choice_test`. Each prints its `... ok` lines and exits 0.
- Commit messages follow the repo's style (`Sim: ...`, `Run env: ...`, `Live: ...`, `Docs: ...`) and end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Docs follow `CLAUDE.md`'s scopes. Rules go in `docs/game-architecture.md` (new section "Colorless cards"), live progress in `docs/modding-approach.md`, and results in the spec.
- **Left out (spec fallback, my call):** Splash, which offers Attacks from the other four characters' pools, which the sim doesn't have. Alchemize is left for plan 2b, because it procures a random potion and 2b models the potions. Both stay in the pool and the shop stock, so the odds stay right, but neither can be bought, and Jack of All Trades doesn't create Splash. That's the existing rule for unmodeled relics (`relics.NOT_MODELED`). Each gets a `ponytail:` comment.

## Review Focus

1. **A prompt card autoplayed** (Mayhem, Catastrophe, Beat Down, Havoc or Cascade playing Discovery, Purity, Secret Technique, Seeker Strike or Thinking Ahead): `_pausable` is false there, so the prompt resolves at random without pausing. It must not hang or leave `pending_choice` set. Test in Task 4.
2. **Retain at end of turn:** Retain cards and a hand under `RetainHandPower` stay in hand. Ethereal cards follow `RetainHandPower.ShouldFlush` and the game's end-of-turn order. Frantic Escape and Infection's end-of-turn damage still apply to retained cards. Test in Task 1.
3. **Hand of Greed** adds gold to the run only on a fatal kill (not minions or illusions, as for Feed), and the gold reaches `Run.gold` after the fight. Test in Task 2.
4. **Full hand:** Bolas, Thrumming Hatchet, Anointed, Secret Weapon, Discovery and Jack of All Trades follow `CardPileCmd.Add` at 10 cards. A generated card goes to the discard pile, and a moved card stays where it is if the source says so. Test in Task 2.
5. **Shop seeds:** the colorless slots draw from `PlayerRng.Shops` between the character cards and the relics, so shop relics and potions change for a given seed. Map, encounter queue and card offers must not change. Test in Task 5.

---

### Task 1: Colorless card data, keywords and generic cards

**Files:**
- Modify: `agent/sim/cards.py`, `agent/sim/engine.py` (Innate, Retain, end of turn)
- Test: `agent/sim/test_engine.py`

**Interfaces:**
- Produces, in `sim/cards.py`:
  - `CardDef` gains `colorless: bool = False`, `innate: bool = False`, `retain: bool = False` and `defend: bool = False` (`CardTag.Defend`, used by Fasten).
  - A `CardDef` for each of the 53 cards, with the game's id (UPPER_SNAKE of the class name, `ULTIMATE_STRIKE`), and its `UPGRADES` entry. Keyword changes on upgrade (`AddKeyword(Retain)`, `RemoveKeyword(Exhaust)`, `AddKeyword(Innate)`) are `UPGRADES` field changes too.
  - `COLORLESS_UNCOMMONS`, `COLORLESS_RARES`: tuples of ids in `ColorlessCardPool` order. `COLORLESS = COLORLESS_UNCOMMONS + COLORLESS_RARES`.
  - `NOT_BUYABLE = frozenset({"SPLASH", "ALCHEMIZE"})`.
  - `GENERATED` keeps meaning the Ironclad cards Stoke and Infernal Blade create. Colorless creation uses `COLORLESS_GENERATED`: colorless cards with `generated` true, minus Splash.
- In `sim/engine.py`, `INNATE` goes away. Innate is `CARDS[c].innate`, and the existing `JUGGLING+` and `AGGRESSION+` entries move into `UPGRADES`. Retain and `RetainHandPower` keep cards in hand at end of turn (`ShouldFlush`).

- [ ] **Step 1: Write the failing tests** in `sim/test_engine.py`:
  - Every one of the 53 ids is in `CARDS` with `colorless=True` and the source's cost, type, rarity and target. `"SPLASH"` and `"ALCHEMIZE"` are in `NOT_BUYABLE`.
  - Dramatic Entrance and Mind Blast start in the opening hand, and so does `ENTROPY+`.
  - A Retain card is still in hand on turn 2. After Equilibrium, the whole hand is still in hand on turn 2, and an Ethereal card follows the source.
  - Generic cards play their source numbers: Ultimate Strike 14 (+6) damage counts for Perfected Strike, Finesse 4 block and draws 1, Flash of Steel, Master of Strategy, Production, Ultimate Defend, Shockwave (3 Weak and 3 Vulnerable to every hittable enemy), Prowess, Salvo, and Volley (X hits of 10 at random enemies).
  - `JUGGLING+` and `AGGRESSION+` are still Innate.
- [ ] **Step 2:** Run `$PY -m sim.test_engine`. Expected: FAIL.
- [ ] **Step 3:** Implement. Cards whose logic comes in Tasks 2–4 get `special=True` now. Until then, playing one raises `KeyError` in `_special`, and no deck holds them yet.
- [ ] **Step 4:** Run `$PY -m sim.test_engine` and `$PY -m sim.test_act`. Expected: both ok.
- [ ] **Step 5:** Commit (`Sim: colorless card data, Innate and Retain`).

### Task 2: Colorless cards with their own logic

**Files:**
- Modify: `agent/sim/engine.py` (`_special`, `_start_player_turn`, `_end_combat`), `agent/run_env.py` (gold from a fight)
- Test: `agent/sim/test_engine.py`

**Interfaces:**
- Consumes: Task 1's `CardDef` fields and `COLORLESS_GENERATED`.
- Produces: `_special` handles Anointed, Beat Down, Bolas, Catastrophe, Dark Shackles, Fisticuffs, Gold Axe, Hand of Greed, Hidden Gem, Impatience, Jack of All Trades, Jackpot, Mind Blast, Omnislice, Panic Button, Prolong, Rend, Restlessness, Scrawl and Thrumming Hatchet.
  - `SimCombat.gold_gained: int` is the gold this fight gives the run (Hand of Greed). `RunPolicyEnv` adds it to `run.gold` after the fight, the way it takes back HP.
  - Hidden Gem's Replay: `SimCombat.replays: dict[int, int]`, keyed by the `id()` of the pile copy, as `CardCopy`'s per-copy state is. A card with Replay plays again that many extra times (`BaseReplayCount`).
  - Bolas and Thrumming Hatchet return to hand at the next `BeforeHandDraw` if they were played last turn.

- [ ] **Step 1: Write the failing tests**, one or more per card, with the source's numbers and its upgraded numbers. Also:
  - Review Focus 3: Hand of Greed killing a normal enemy sets `gold_gained` to 20 (25 upgraded). Killing a minion gives 0. A sim run gets the gold after that fight.
  - Review Focus 4: Jack of All Trades with 10 cards in hand sends its card to the discard pile. Bolas with a full hand at the next turn follows the source.
  - Omnislice's overflow damage is Unpowered (no Vulnerable, Strength or Weak on it).
  - Rend counts only non-temporary debuffs on its target.
- [ ] **Step 2:** Run `$PY -m sim.test_engine`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `$PY -m sim.test_engine`, `$PY -m sim.test_act` and `$PY -m test_run_env`. Expected: all ok.
- [ ] **Step 5:** Commit (`Sim: colorless cards with their own logic`).

### Task 3: Colorless powers

**Files:**
- Modify: `agent/sim/engine.py` (power hooks: card drawn, card played, turn start and end, block gain, damage taken, shuffle), `agent/env.py` (`PLAYER_POWERS`)
- Test: `agent/sim/test_engine.py`

**Interfaces:**
- Consumes: Task 1's cards.
- Produces: the powers of Automation, Calamity, Entropy, Eternal Armor (the player's `PlatingPower`), Fasten, Mayhem, Nostalgia, Panache, Prep Time, Rolling Boulder, Stratagem, The Bomb, The Gambit, plus `NoBlockPower` (Panic Button), `BlockNextTurnPower` (Prolong) and `DarkShacklesPower` (enemy), each from its `*Power.cs` hooks. Entropy's and Stratagem's prompts use Task 4's prompt kinds. Until Task 4 lands, they pick at random through `_ask`'s non-pausable path.
  - The new player powers join `env.PLAYER_POWERS`, which is built from `CardDef.powers` plus a hand-kept set. Task 7's grow map places them by name.

- [ ] **Step 1: Write the failing tests**, one per power, with the source's trigger and numbers, and their upgraded numbers. Also:
  - Mayhem with Discovery on top of the draw pile autoplays it without leaving `pending_choice` set (Review Focus 1, first half).
  - The Bomb with 3 turns deals 40 (50 upgraded) to every enemy at the end of the third turn, and two Bombs count down separately if the source says so.
  - Fasten adds its block only to `defend` cards.
- [ ] **Step 2:** Run `$PY -m sim.test_engine`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `$PY -m sim.test_engine` and `$PY -m test_run_env`. Expected: both ok.
- [ ] **Step 5:** Commit (`Sim: colorless powers`).

### Task 4: New card prompts

**Files:**
- Modify: `agent/sim/engine.py` (`_ask`, `_take`, `_finish_choice`, `choose_card`, `combat_dict`), `agent/env.py`
- Test: `agent/sim/test_engine.py`, `agent/test_run_env.py`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces:
  - New `_ask` kinds, shown in `combat_dict()["choice"]`:
    - `"generated"`: choose 1 of up to 3 new cards, or skip (Discovery, from the Ironclad pool via `GetDistinctForCombat`). `choice["options"]` lists the ids.
    - `"draw"`: choose 1 card from the draw pile, by id, with a filter (Secret Technique: Skills, Secret Weapon: Attacks, Seeker Strike: 3 random cards, Stratagem: any).
    - `"hand_multi"`: choose 0 to N hand cards, one at a time, then done (Purity: N = 3, 5 upgraded).
    - Thinking Ahead and Entropy use `"hand"`.
  - Env actions appended after `CHOOSE_DISCARD`'s block: `CHOOSE_GENERATED` (3 slots), `CHOOSE_SKIP`, `CHOOSE_DRAW` (`len(CARD_IDS)` slots by `CARD_IDS` index) and `CHOOSE_DONE`. The mask allows only the open prompt's answers.
  - Observation block appended last: one flag per new kind, the identity of each generated option (3 × `len(CARD_IDS)`), and the prompt source among `COLORLESS_PROMPT_CARDS = ("DISCOVERY", "PURITY", "SECRET_TECHNIQUE", "SECRET_WEAPON", "SEEKER_STRIKE", "THINKING_AHEAD", "ENTROPY", "STRATAGEM")`. `_asks()` returns true for these cards.

- [ ] **Step 1: Write the failing tests:**
  - Each prompt card pauses with the right kind and options, and each answer does what the source does: Discovery's pick is free this turn, Purity exhausts each pick and stops at N or done, and Thinking Ahead puts its pick on top of the draw pile.
  - Discovery's skip adds nothing. A non-upgraded Discovery exhausts, and `DISCOVERY+` doesn't.
  - Secret Technique with no Skill in the draw pile does nothing and doesn't pause.
  - Review Focus 1: Havoc and Mayhem autoplaying each prompt card finish without `pending_choice`, in 200 seeded fights.
  - `test_run_env`: `OBS_DIM` matches `_obs().shape`, and for each new kind the mask allows exactly the legal answers.
- [ ] **Step 2:** Run `$PY -m sim.test_engine` and `$PY -m test_run_env`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run all five self-checks. Expected: all ok.
- [ ] **Step 5:** Commit (`Sim: colorless prompts (choose a card, draw pile, multi-select)`).

### Task 5: Colorless cards in the run

**Files:**
- Modify: `agent/sim/act.py` (`make_shop`, `Shop`, `buy`, The Courier), `agent/run_env.py`, `agent/run.py` (`baseline_action`)
- Test: `agent/sim/test_act.py`, `agent/test_run_env.py`

**Interfaces:**
- Consumes: Task 1's `COLORLESS_UNCOMMONS`, `COLORLESS_RARES` and `NOT_BUYABLE`.
- Produces:
  - `SHOP_COLORLESS = ("Uncommon", "Rare")` (`MerchantInventory._colorlessCardRarities`). `Shop.cards` and `Shop.prices` grow to `len(SHOP_SLOTS) + 2`, with the colorless slots last. They're stocked after the character cards and before the relics, as `CreateForNormalMerchant` does. Base price is `round(75 * 1.15)` = 86 or `round(150 * 1.15)` = 172 (`MerchantCardEntry.GetCost`), times `NextFloat(0.95, 1.05)`, rounded. Colorless slots are never on sale.
  - The Courier restocks a colorless slot from the same rarity. Egg relics apply by card type, as for character cards.
  - Run env: shop slot observations and `SHOP` buy actions cover the 2 new slots. The new slots are appended, with old indices unchanged. The mask never allows buying `NOT_BUYABLE`.
  - `baseline_action` leaves colorless slots alone (my call: the baseline stays the same).

- [ ] **Step 1: Write the failing tests:**
  - Over 2,000 shops, the colorless slots hold only colorless cards of their rarity, never repeat within a shop, and are priced within the source's range.
  - Review Focus 5: for seeds 0–9, the Act 1 map, encounter queue and first 3 card offers match the values before this task (capture them first).
  - Buying a colorless card adds it to the deck. Buying `"SPLASH"` is masked out.
  - `test_run_env`: 300 runs with a random legal policy, each deck seeded with 4 random colorless cards, finish without an exception.
- [ ] **Step 2:** Run `$PY -m sim.test_act` and `$PY -m test_run_env`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run all five self-checks. Expected: all ok.
- [ ] **Step 5:** Document "Colorless cards" in `docs/game-architecture.md`: the pool, shop slots and prices, the new keywords and powers, the prompts, and what's left out. Commit (`Sim: colorless cards in shops`).

### Task 6: Live play with colorless cards

**Files:**
- Modify: `mod/AutoSpire/AutoSpireRun.cs` (`ShopState`, buy), `mod/AutoSpire/AutoSpireMod.cs` (prompt state, multi-select, skip), `agent/live.py`, `agent/client.py`, `agent/live_check.py`, `agent/sim/validate.py`
- Docs: `docs/modding-approach.md`

**Interfaces:**
- Consumes: Tasks 4–5's prompt kinds and shop slots.
- Produces:
  - `/state` shop `cards` lists `CharacterCardEntries` then `ColorlessCardEntries`, so the slot indices match the sim's. `/exec buy <slot>` buys from either.
  - `AgentSelector`'s pending prompt reports its kind and options (choose-a-card screen, draw pile, hand with `maxSelect`). `/exec choose` answers multi-select one card at a time, `choose_done` finishes, and `choose_skip` skips a skippable screen.
  - `live.py` and `env.py` map these live prompts to the Task 4 actions.

- [ ] **Step 1:** Add staged checks to `live_check.py`:
  - One per prompt kind: Discovery (pick and skip), Purity (2 picks then done), Secret Weapon and Thinking Ahead. Each matches the sim's hand and piles after.
  - A shop with colorless slots: ids, prices and a purchase.
  - Hand of Greed's gold after a fatal hit.
- [ ] **Step 2:** Run `$PY live_check.py` with the game running. Expected: the new checks fail.
- [ ] **Step 3:** Implement. Build with `mod/build.sh`.
- [ ] **Step 4:** Run `sim.validate` on random decks with 4–8 colorless cards (half upgraded), over the Act 1 and Hive encounters. Expected: no mismatches beyond those already known. Record the step count in `docs/modding-approach.md`.
- [ ] **Step 5:** Run `$PY live_check.py`. Expected: every check passes (23 old plus the new ones), with no `[ERROR]` lines from the mod in `godot.log`.
- [ ] **Step 6:** Commit (`Live: colorless cards, prompts and shop slots`). Leave `mod/AutoSpire/obj/*` out.

### Task 7: Grow the models and check nothing regressed

**Files:**
- Modify: `agent/env.py` (`combat_maps`), `agent/run_env.py` (`run_maps`), `agent/grow.py` (docstring), `agent/test_grow.py`, `agent/test_data/record_grow_fixture.py`, `agent/test_data/grow_fixture.pkl.gz`
- Modify: `docs/superpowers/specs/2026-11-09-act2-boss-design.md` (add "Part 2a results")

**Interfaces:**
- Consumes: every new block from Tasks 1–5.
- Produces: `combat_maps()` and `run_maps()` map the part 1 layout (the `boss_g1` / `boss_run_g1` models) to the new one: old `CARD_IDS`, `PLAYER_POWERS` and shop slots placed by name, with new blocks unmapped. The pre-upgrade map they replace goes away (ponytail: one layout back, as before).

- [ ] **Step 1:** Re-record the grow fixture at 326edb2 with `record_grow_fixture.py`, and point `test_grow` at `ppo_sts2_sim_boss_g1.zip` and `ppo_sts2_sim_boss_run_g1.zip`. Expected: `$PY -m test_grow` passes (same action on 200 recorded observations).
- [ ] **Step 2:** Grow both: `$PY grow.py models/ppo_sts2_sim_boss_g1.zip models/ppo_sts2_sim_boss_g2.zip --env combat --insert-cards` and `$PY grow.py models/ppo_sts2_sim_boss_run_g1.zip models/ppo_sts2_sim_boss_run_g2.zip --env run --insert-cards`. Expected: both print `grow self-check ok`.
- [ ] **Step 3:** Evaluate: `$PY run.py --model models/ppo_sts2_sim_boss_g2.zip --maps generated --run-model models/ppo_sts2_sim_boss_run_g2.zip --runs 500 --n 16`. Expected: no crashes, `stuck=0`, and Act 1 within 4 points of 79.4%. Shops now stock colorless cards, and the untrained model sees them for the first time.
- [ ] **Step 4:** Run `boss_report.py` on the grown pair (1,500 runs) and add the per-boss table to "Part 2a results", next to part 1's.
- [ ] **Step 5:** Commit (`Docs: Act 2 boss part 2a results`). Report to the user. Plan 2b starts after the merge.
