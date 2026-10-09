# auto-spire

Automating Slay the Spire 2. Read game state, send commands, play intelligently.

[![Demo: Claude playing STS2 via AutoSpire](https://img.youtube.com/vi/SXD6wWn3IX4/maxresdefault.jpg)](https://www.youtube.com/watch?v=SXD6wWn3IX4)

STS2 is a C#/.NET 9 game on a custom Godot 4.5.1 Mono engine ("MegaDot"). It ships with HarmonyLib and a built-in mod loader, which we use to inject a bridge mod that exposes game state over HTTP.

## Architecture

```
STS2 Game Process
  └── AutoSpire.dll (mod, loaded by game's mod system)
        └── HTTP server on localhost:31452
              ├── GET /state    → full game state as JSON
              ├── GET /combat   → combat-specific state
              ├── POST /act     → send commands (play card, end turn, use potion)
              └── GET /ping     → health check

Python AI Client (planned)
  └── connects to HTTP API, reads state, sends commands
```

## API

### `GET /state` — Full game state

Returns run progress, player stats, deck, and combat info (if in combat).

```jsonc
{
  "phase": "combat",       // "menu" | "combat" | "map"
  "inRun": true,
  "floor": 1,
  "actIndex": 0,
  "roomType": "Monster",
  "player": {
    "hp": 80, "maxHp": 80, "block": 0, "gold": 99,
    "character": "IRONCLAD",
    "deck": [/* full card list with cost, type, keywords, upgrades */],
    "relics": [{"id": "BURNING_BLOOD", "name": "BurningBlood", "counter": 0}],
    "potions": [{"id": "FIRE_POTION", "targetType": "AnyEnemy", "rarity": "Common"}]
  },
  "combat": {
    "isPlayPhase": true,
    "round": 1,
    "player": {
      "energy": 3, "maxEnergy": 3, "stars": 0,
      "hand": [/* cards with canPlay, cost, targetType, keywords */],
      "drawPile": [/* full card details */],
      "discardPile": [],
      "exhaustPile": [],
      "powers": [{"id": "STRENGTH", "name": "Strength", "type": "Buff", "amount": 2}]
    },
    "enemies": [{
      "combatId": 1, "name": "Nibbit", "hp": 46, "maxHp": 46, "block": 0,
      "powers": [],
      "intent": {
        "moveId": "BUTT_MOVE",
        "intents": [{"type": "Attack", "damage": 8, "hits": 1, "totalDamage": 8}]
      }
    }]
  }
}
```

### `POST /act` — Send commands

```bash
# Play card at hand index 2, targeting enemy with combatId 1
curl -X POST http://localhost:31452/act -d '{"type":"play_card","cardIndex":2,"targetId":1}'

# End turn
curl -X POST http://localhost:31452/act -d '{"type":"end_turn"}'

# Use potion at index 0, targeting enemy with combatId 1
curl -X POST http://localhost:31452/act -d '{"type":"use_potion","potionIndex":0,"targetId":1}'
```

## Setup

`mise` turned out to be impractical here: this Mac is on macOS 14, which Homebrew no longer bottles ("Tier 3"), so `brew install mise` tries to compile LLVM + Rust from source (1hr+). We install runtimes directly instead — same versions, no from-source builds, nothing global.

### Install .NET 9 SDK + .NET 8 runtime (user-local, no sudo)

`ilspycmd` (the decompiler) targets net8.0, so we need both:

```bash
curl -sSL https://dot.net/v1/dotnet-install.sh -o /tmp/dotnet-install.sh && chmod +x /tmp/dotnet-install.sh
/tmp/dotnet-install.sh --channel 9.0 --install-dir "$HOME/.dotnet"
/tmp/dotnet-install.sh --channel 8.0 --runtime dotnet --install-dir "$HOME/.dotnet"
export PATH="$HOME/.dotnet:$PATH"
export DOTNET_ROOT="$HOME/.dotnet"
```

(The Homebrew cask `dotnet-sdk@9` also exists but its `.pkg` installer requires an interactive `sudo` prompt — the script above avoids that.)

### Install project tools

```bash
cd auto-spire
dotnet tool install ilspycmd --version 9.1.0.7988 --tool-path .dotnet-tools
```

If this errors with "Settings file 'DotnetToolSettings.xml' was not found", clear the NuGet cache first: `dotnet nuget locals all --clear`.

Python venv, as needed for the AI client:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt   # once it exists
```

**Godot is not needed.** The mod no longer ships a PCK (see below), so there's nothing to export.

### Day-to-day usage

```bash
cd auto-spire
export PATH="$HOME/.dotnet:$PATH"
export DOTNET_ROOT="$HOME/.dotnet"
source .venv/bin/activate   # if using the python venv
```

## Building the mod

```bash
./mod/build.sh    # builds DLL, writes a manifest.json, deploys to game
```

This:
1. Compiles `mod/AutoSpire/` → `AutoSpire.dll`
2. Writes `manifest.json` with `has_pck: false` (mods are now discovered by manifest, not by scanning for `.pck` files — see `docs/modding-approach.md`)
3. Copies both to `SlayTheSpire2.app/Contents/MacOS/mods/AutoSpire/`

After deploying, restart STS2. **First time only:** a "Player chose to load mods" confirmation appears in-game — clicking through it requires one more restart before mods actually activate (check the bottom-right corner of the main menu for "Running Modded. Loaded 1 mod."). Verify:

```bash
grep AutoSpire ~/Library/Application\ Support/SlayTheSpire2/logs/godot.log
curl http://localhost:31452/ping
```

Launch the game by running the binary directly with `SteamAppId=2868840` set (Steam must be running) — see `GAME_BIN` in `agent/client.py`. Plain `open -a` on the `.app` skips Steam and Steamworks fails to init; `open "steam://rungameid/2868840"` works but silently does nothing if Steam is showing a dialog.

### `/exec` — text command interface (in addition to `/act`)

```bash
curl -X POST http://localhost:31452/exec -d "play 0 1"    # play hand[0] targeting combatId 1
curl -X POST http://localhost:31452/exec -d "end"          # end turn
curl -X POST http://localhost:31452/exec -d "instant"      # toggle FastModeType.Instant (animation skip — use this for training)
curl -X POST http://localhost:31452/exec -d "room Monster" # dev-console passthrough: jump straight into a fight
curl -X POST http://localhost:31452/exec -d "newrun IRONCLAD"  # start a fresh run from the main menu, no UI clicking (see docs/modding-approach.md)
```

## Python RL agent (`agent/`)

A Gymnasium environment (`agent/env.py`, `STS2CombatEnv`) for Ironclad combat against a fixed encounter, plus a thin HTTP client (`agent/client.py`) and a random-action smoke test (`agent/random_agent.py`). Setup:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install gymnasium requests numpy stable-baselines3 sb3-contrib torch
cd agent && python random_agent.py
```

The env periodically calls `AutoSpireClient.full_restart()` (kill + relaunch + `newrun`, no clicking) instead of the lighter in-combat `fight` reset, since the live game's CPU/animation backlog only clears on a full process restart — see the "Open problem" / "Resolved" entries in `docs/modding-approach.md`.
```

## Key paths

| What | Path |
|------|------|
| Game install | `~/Library/Application Support/Steam/steamapps/common/Slay the Spire 2/` |
| Game DLL (C#) | `.../Resources/data_sts2_macos_arm64/sts2.dll` |
| Game logs | `~/Library/Application Support/SlayTheSpire2/logs/godot.log` |
| Mods directory | `.../SlayTheSpire2.app/Contents/MacOS/mods/` |
| Mod source | `./mod/AutoSpire/` |
| PCK project | `./mod/pack/` |
| Decompiled source | `./decompiled/` (gitignored) |

## Decompiling sts2.dll

```bash
.dotnet-tools/ilspycmd ~/Library/Application\ Support/Steam/steamapps/common/"Slay the Spire 2"/SlayTheSpire2.app/Contents/Resources/data_sts2_macos_arm64/sts2.dll -p -o ./decompiled/
```

Produces 3,298 C# files. Key namespaces: `MegaCrit.Sts2.Core.Combat`, `.Commands`, `.Entities.*`, `.AutoSlay`, `.Modding`.

## Cleanup

Everything is project-scoped or mise-managed:

```bash
rm -rf .venv              # python venv + frida-tools
rm -rf .dotnet-tools      # ilspycmd
rm -rf decompiled         # decompiled game source
mise uninstall dotnet     # remove dotnet runtimes
mise uninstall python     # remove python
mise uninstall godot      # remove godot
brew uninstall mise       # remove mise itself
```
