#!/bin/bash
# Build and deploy the AutoSpire mod
#
# NOTE: as of the game's current version, mods are discovered via a JSON
# manifest (not by scanning for .pck files), and a manifest can declare
# has_pck=false. So we skip PCK/Godot entirely and just ship a DLL + manifest.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR/AutoSpire"
OUT_DIR="$SCRIPT_DIR/out"
GAME_APP="$HOME/Library/Application Support/Steam/steamapps/common/Slay the Spire 2/SlayTheSpire2.app"
GAME_DIR="$GAME_APP/Contents/Resources/data_sts2_macos_arm64"
MODS_DIR="$GAME_APP/Contents/MacOS/mods/AutoSpire"

mkdir -p "$OUT_DIR"

echo "=== Building AutoSpire DLL ==="
cd "$PROJECT_DIR"
dotnet build -p:STS2_GAME_DIR="$GAME_DIR" -c Release -o "$OUT_DIR" 2>&1

echo ""
echo "=== Writing mod manifest ==="
cat > "$OUT_DIR/manifest.json" <<'EOF'
{
  "id": "AutoSpire",
  "name": "AutoSpire",
  "author": "auto-spire",
  "description": "Automation bridge for Slay the Spire 2",
  "version": "0.1.0",
  "has_pck": false,
  "has_dll": true,
  "affects_gameplay": true
}
EOF

echo ""
echo "=== Deploying to $MODS_DIR ==="
mkdir -p "$MODS_DIR"
cp "$OUT_DIR/AutoSpire.dll" "$MODS_DIR/"
cp "$OUT_DIR/manifest.json" "$MODS_DIR/"

echo ""
echo "=== Done! ==="
ls -la "$MODS_DIR/"
echo ""
echo "Restart the game. On first launch with mods present you'll need to confirm"
echo "the in-game 'allow mod loading' popup. Then test with: curl http://localhost:31452/ping"
