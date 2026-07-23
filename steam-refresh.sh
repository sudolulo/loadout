#!/bin/bash
# Native Steam ROM-shortcut refresh -- no Steam ROM Manager. Reconciles Steam shortcuts with
# the enabled set (Loadout's --sync-steam), writes per-console collections, and returns you to
# where you were. Steam must be stopped to write shortcuts.vdf (it rewrites the file on exit),
# so this runs AFTER Loadout closes, guarded against a live game.
set -u
LOG="$HOME/steam-refresh.log"
APPIMAGE="$HOME/Applications/Loadout.AppImage"
export DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus

# Refuse while a game is live -- this stops Steam / restarts the session.
for p in retroarch dolphin-emu PPSSPP pcsx2 melonDS xemu Cemu rpcs3 azahar primehack citra \
         ryujinx shadps4 duckstation flycast mupen64 ppsspp; do
  pgrep -fi "$p" >/dev/null 2>&1 && { echo "ABORT: game running ($p)"; exit 3; }
done
if pgrep -f "reaper SteamLaunch AppId=" 2>/dev/null | grep -qv "^$$\$"; then
  echo "ABORT: a Steam-launched game is running"; exit 3
fi

GAMEMODE=0; pgrep -x gamescope >/dev/null && GAMEMODE=1

sync_cmd() {
  if [ -x "$APPIMAGE" ]; then "$APPIMAGE" --sync-steam
  elif [ -f "$HOME/loadout.py" ]; then python3 "$HOME/loadout.py" --sync-steam
  else echo "no loadout to sync with"; return 1; fi
}

{
  echo "=== $(date '+%F %T') native refresh (gamemode=$GAMEMODE) ==="
  # stop Steam so shortcuts.vdf is writable and won't be clobbered on its exit
  steam -shutdown >/dev/null 2>&1
  for i in $(seq 1 30); do pgrep -x steam >/dev/null || break; sleep 2; done
  pkill -x steam 2>/dev/null; pkill -f steamwebhelper 2>/dev/null
  for i in $(seq 1 10); do pgrep -x steam >/dev/null || break; sleep 2; done

  sync_cmd                                   # native: add/remove ROM shortcuts + art
  python3 "$HOME/fix_collections.py" --apply 2>&1 | tail -8   # per-console collections (JSON)

  if [ "$GAMEMODE" = 1 ]; then
    echo "re-entering gaming mode"; steamos-session-select gamescope
  else
    echo "restarting Steam (desktop)"; ( setsid steam >/dev/null 2>&1 & )
  fi
  echo "done"
} >> "$LOG" 2>&1
