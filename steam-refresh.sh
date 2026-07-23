#!/bin/bash
# Native Steam ROM-shortcut refresh, run ENTIRELY from within the Loadout AppImage
# (self-contained -- no ~/ scripts, no Steam ROM Manager, no fallback). Invoked as
# `Loadout.AppImage --refresh`; AppRun passes $APP (the payload dir) as $1.
#
# Fired (via a systemd path unit) after Apply drops ~/.loadout-dirty. It waits for the GUI and
# any game to close, stops Steam, reconciles Steam shortcuts with the enabled set natively,
# writes per-console collections, clears the flag, and restarts Steam / Game Mode exactly ONCE.
set -u
APP="${1:-$(dirname "$(readlink -f "$0")")}"
LOG="$HOME/steam-refresh.log"
SELF=$$
export DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus PATH="$HOME/bin:$PATH"

# pids matching $1, excluding this script and its children (patterns live here, not on any
# command line, so pgrep can't match this script itself)
others() {
  pgrep -f "$1" 2>/dev/null | while read -r pid; do
    [ "$pid" = "$SELF" ] && continue
    ppid=$(awk '{print $4}' "/proc/$pid/stat" 2>/dev/null); [ "$ppid" = "$SELF" ] && continue
    echo "$pid"
  done
}

{
  echo "=== $(date '+%F %T') native refresh (APP=$APP) ==="
  # let the GUI and any launched game close before we touch Steam
  for _ in $(seq 1 60); do [ -z "$(others 'loadout[.]py')" ] && break; sleep 2; done
  for _ in $(seq 1 60); do [ -z "$(others 'reaper SteamLaunch AppId=')" ] && break; sleep 2; done
  sleep 2
  for p in retroarch dolphin-emu PPSSPP pcsx2 melonDS xemu Cemu rpcs3 ryujinx shadps4 \
           duckstation flycast mupen64 primehack citra azahar; do
    pgrep -fi "$p" >/dev/null 2>&1 && { echo "ABORT: game running ($p)"; rm -f "$HOME/.loadout-dirty"; exit 3; }
  done
  GAMEMODE=0; pgrep -x gamescope >/dev/null && GAMEMODE=1

  # stop Steam so shortcuts.vdf is writable and it can't clobber our write on its way out
  steam -shutdown >/dev/null 2>&1
  for _ in $(seq 1 30); do pgrep -x steam >/dev/null || break; sleep 2; done
  pkill -x steam 2>/dev/null; pkill -f steamwebhelper 2>/dev/null
  for _ in $(seq 1 10); do pgrep -x steam >/dev/null || break; sleep 2; done

  python3 "$APP/loadout.py" --sync-steam         # native: add/remove ROM shortcuts + art
  python3 "$APP/fix_collections.py" --apply 2>&1 | tail -8   # per-console collections (JSON)

  # Clear the trigger flag NOW: shortcuts.vdf is already written, and the restart below can kill
  # this process -- clearing it afterward would leave the flag set and re-fire the path unit
  # (that was the "resets multiple times" bug). One restart, then done.
  rm -f "$HOME/.loadout-dirty"
  if [ "$GAMEMODE" = 1 ]; then
    echo "re-entering gaming mode"; steamos-session-select gamescope
  else
    echo "restarting Steam (desktop)"; ( setsid steam >/dev/null 2>&1 & )
  fi
  echo "done"
} >> "$LOG" 2>&1
