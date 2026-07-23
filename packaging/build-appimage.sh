#!/bin/bash
# Build Loadout-x86_64.AppImage from this repo. Needs `appimagetool` on PATH (or pass its
# path as $APPIMAGETOOL). Runs anywhere x86_64 Linux; no FUSE needed if appimagetool is the
# extracted binary. The AppImage relies on the target's system python3+GTK (SteamOS has them).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/Loadout-x86_64.AppImage}"
APPIMAGETOOL="${APPIMAGETOOL:-appimagetool}"
APPDIR="$(mktemp -d)/Loadout.AppDir"
VERSION="$(grep -oP 'VERSION = "\K[^"]+' "$ROOT/loadout_update.py" | head -1)"

mkdir -p "$APPDIR/usr/share/loadout" "$APPDIR/usr/share/icons/hicolor/256x256/apps"

# app payload — every script the container runs, all invoked from inside the mount. The old
# SRM-fallback chain (loadout-sync.sh, srm-refresh.sh) and the script-copying install.sh are
# deliberately NOT bundled: the container never falls back to SRM and never installs scripts to ~.
cp "$ROOT"/loadout.py "$ROOT"/loadout-worker.py "$ROOT"/loadout_update.py \
   "$ROOT"/steamgriddb.py "$ROOT"/steam_shortcuts.py \
   "$ROOT"/steam-refresh.sh "$ROOT"/fix_collections.py \
   "$ROOT"/deck-saves.sh "$ROOT"/deck-saves-daemon.sh "$ROOT"/steam-account.py \
   "$ROOT"/ps3-esde-setup.sh "$ROOT"/mount-setup.sh \
   "$ROOT"/config.example.json "$APPDIR/usr/share/loadout/"

# AppImage metadata
install -m 0755 "$ROOT/packaging/AppRun" "$APPDIR/AppRun"
cp "$ROOT/packaging/loadout.desktop" "$APPDIR/loadout.desktop"
cp "$ROOT/assets/icon-256.png" "$APPDIR/loadout.png"
cp "$ROOT/assets/icon-256.png" "$APPDIR/.DirIcon"
cp "$ROOT/assets/icon-256.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/loadout.png"
cp "$ROOT/assets/icon-256.png" "$APPDIR/usr/share/loadout/loadout.png"   # gen_units → app-menu icon

echo "Building Loadout $VERSION -> $OUT"
ARCH=x86_64 "$APPIMAGETOOL" --no-appstream "$APPDIR" "$OUT"
sha256sum "$OUT" | tee "$OUT.sha256"
rm -rf "$(dirname "$APPDIR")"
echo "done: $OUT"
