#!/bin/bash
# Refresh ROM shortcuts + per-console Steam collections WITHOUT leaving Gaming Mode.
#
# The catch-22 this works around:
#   - SRM is Electron and needs an X server. In Gaming Mode the only X servers are the
#     two Xwayland instances gamescope owns, so stopping Steam kills them and SRM dies
#     with "Missing X server or $DISPLAY".
#   - But SRM silently SKIPS Steam categories whenever Steam is running.
# Resolution: let SRM do apps+art with Steam UP (X available), then write the collections
# ourselves with Steam DOWN — collections are just JSON and need no X server.
#
# Steam rewrites shortcuts.vdf from memory on exit, so we snapshot SRM's output and
# restore it if Steam clobbers it.
set -u
SRM="$HOME/Emulation/tools/Steam-ROM-Manager.AppImage"
UID_DIR="$HOME/.local/share/Steam/userdata/98492642/config"
VDF="$UID_DIR/shortcuts.vdf"
LOG="$HOME/srm-refresh.log"
export DISPLAY=:0

# Refuse to run while a game is live -- this script stops Steam and restarts the
# gamescope session, which would kill whatever is being played.
for p in retroarch dolphin-emu PPSSPP pcsx2 melonDS xemu Cemu rpcs3 azahar primehack \
         citra ryujinx shadps4 duckstation flycast; do
  if pgrep -fi "$p" >/dev/null 2>&1; then
    echo "ABORT: GAME IS RUNNING ($p) -- refusing to restart Steam"
    exit 3
  fi
done
# a running app launched through Steam also counts
# Match a real game launch (AppId=) and ignore our own process tree -- an earlier
# version matched the watcher script that invoked this one.
if pgrep -f "reaper SteamLaunch AppId=" 2>/dev/null | grep -qv "^$$\$"; then
  echo "ABORT: GAME IS RUNNING (steam launch) -- refusing to restart Steam"
  exit 3
fi

{
  echo "=== $(date '+%F %T') refresh ==="
  [ -x "$SRM" ] || { echo "SRM missing"; exit 1; }

  # 1) apps + artwork, with Steam running so the X server exists
  timeout 900 "$SRM" --no-sandbox add 2>&1 \
    | grep -viE 'portal|object_proxy|select_file_dialog|INFO:CONSOLE' | tail -3
  cp -f "$VDF" "$VDF.srm" 2>/dev/null
  echo "snapshot: $(stat -c %s "$VDF" 2>/dev/null) bytes"

  # 2) stop Steam so it cannot overwrite the collections file
  steam -shutdown >/dev/null 2>&1
  for i in $(seq 1 30); do pgrep -x steam >/dev/null || break; sleep 3; done
  pkill -x steam 2>/dev/null; pkill -f steamwebhelper 2>/dev/null
  for i in $(seq 1 10); do pgrep -x steam >/dev/null || break; sleep 2; done

  # Steam may have rewritten shortcuts.vdf from memory on the way out
  if [ -f "$VDF.srm" ] && ! cmp -s "$VDF" "$VDF.srm"; then
    cp -f "$VDF.srm" "$VDF"; echo "restored SRM shortcuts (steam had rewritten them)"
  fi

  # 3) per-console collections (pure JSON, no X needed)
  python3 "$HOME/fix_collections.py" --apply 2>&1 | tail -8

  echo "re-entering gaming mode"
  steamos-session-select gamescope
  echo "done"
} >> "$LOG" 2>&1
