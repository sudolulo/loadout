#!/bin/bash
# Cut a Loadout release: build the AppImage -> launch-test it -> tag -> publish to Gitea.
#
# The version comes from loadout_update.py, so bump that (and CHANGELOG.md) first; this script
# only ships what the tree already says it is. Everything happens in a scratch dir that is
# removed on exit, including the API-token header file -- the token itself is read from rbw at
# run time and never written into the repo.
#
#   ./packaging/release.sh                # build, test, tag, publish
#   ./packaging/release.sh --dry-run      # build + test only, publish nothing
#
# Needs: appimagetool ($APPIMAGETOOL, or on PATH), rbw unlocked (entry "gitea token"),
# and xvfb-run + the GTK stack for the launch test (skipped with a warning if absent).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO="${LOADOUT_REPO:-flan/loadout}"
API="${LOADOUT_API:-https://git.onetick.ninja/api/v1}"
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1

VERSION="$(grep -oP 'VERSION = "\K[^"]+' "$ROOT/loadout_update.py" | head -1)"
TAG="v$VERSION"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
OUT="$WORK/Loadout-x86_64.AppImage"

echo "### releasing $TAG ###"

echo "== build =="
APPIMAGETOOL="${APPIMAGETOOL:-appimagetool}" bash "$ROOT/packaging/build-appimage.sh" "$OUT" >/dev/null
( cd "$WORK" && sha256sum Loadout-x86_64.AppImage > Loadout-x86_64.AppImage.sha256 )
echo "   built $(du -h "$OUT" | cut -f1)  sha $(cut -c1-16 < "$WORK/Loadout-x86_64.AppImage.sha256")"

echo "== launch-test the built AppImage =="
# Test what actually ships (the extracted payload), not the working tree -- a packaging
# mistake that drops a module only shows up here.
if command -v xvfb-run >/dev/null 2>&1; then
  ( cd "$WORK" && "$OUT" --appimage-extract >/dev/null 2>&1 )
  if ! LOADOUT_CONFIG="$WORK/launchtest.json" timeout 90 xvfb-run -a python3 - \
        "$WORK/squashfs-root/usr/share/loadout" <<'PY'
import os, sys, threading
sys.path.insert(0, sys.argv[1])
import gi; gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib
import loadout                                  # importing must not explode
GLib.timeout_add(2500, lambda: (Gtk.main_quit(), False)[1])
app = loadout.App(); app.show_all(); Gtk.main()  # must actually reach the main loop
print("   PASS - reached Gtk.main() cleanly")
PY
  then
    echo "   ABORT: the built AppImage failed its launch test"; exit 1
  fi
else
  echo "   WARNING: xvfb-run not found - shipping WITHOUT a launch test"
fi

if [ "$DRY" = 1 ]; then
  echo "== dry run: not tagging, not publishing =="
  cp "$OUT" "$OUT.sha256" "$ROOT/" 2>/dev/null || true
  exit 0
fi

echo "== tag + push =="
cd "$ROOT"
if [ -n "$(git status --porcelain)" ]; then
  echo "   ABORT: working tree is dirty - commit first so the tag matches what ships"; exit 1
fi
git tag -f "$TAG" >/dev/null 2>&1
git push origin "$(git rev-parse --abbrev-ref HEAD)" 2>&1 | grep -viE 'pseudo|permanently added' | tail -1 || true
git push -f origin "$TAG" 2>&1 | grep -viE 'pseudo|permanently added' | tail -1

echo "== publish release =="
umask 077
printf 'Authorization: token %s\n' "$(rbw get 'gitea token')" > "$WORK/auth.hdr"
rel=$(curl -sS -X POST -H @"$WORK/auth.hdr" -H 'Content-Type: application/json' \
  -d "{\"tag_name\":\"$TAG\",\"name\":\"Loadout $VERSION\",\"body\":\"Self-updating AppImage. See CHANGELOG.md.\"}" \
  "$API/repos/$REPO/releases")
id=$(printf '%s' "$rel" | python3 -c "import sys,json;print(json.load(sys.stdin).get('id',''))" 2>/dev/null || true)
[ -n "$id" ] || { echo "   release create failed: $(printf '%s' "$rel" | head -c 200)"; exit 1; }
for f in Loadout-x86_64.AppImage Loadout-x86_64.AppImage.sha256; do
  curl -sS -X POST -H @"$WORK/auth.hdr" -F "attachment=@$WORK/$f" \
    "$API/repos/$REPO/releases/$id/assets?name=$f" -o /dev/null -w "   $f: %{http_code}\n"
done

echo "== verify (anonymous, the way a Deck sees it) =="
sleep 3
curl -sS "$API/repos/$REPO/releases/latest" | python3 -c \
  "import sys,json;d=json.load(sys.stdin);print('   latest:',d['tag_name'],[a['name'] for a in d.get('assets',[])])"
