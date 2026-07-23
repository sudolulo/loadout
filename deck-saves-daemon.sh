#!/bin/bash
# Keeps emulator saves in step with the NAS without you thinking about it.
#
#   game exits              -> push the signed-in profile's saves up
#   idle + NAS newer        -> pull them down
#   idle + profile changed  -> hand the save tree to whoever just signed in
#
# Never touches saves while a game is running, and never overwrites local progress that
# was not pushed yet -- that is flagged as a conflict for the manager to settle.
set -u
SAVES="$HOME/deck-saves.sh"
INTERVAL=60
was_running=0

# A game is "running" if Steam launched one OR any emulator is up. Checking only the
# Steam reaper is blind to anything started from ES-DE -- which is how most ROMs launch.
EMUS="Ryujinx dolphin-emu PPSSPP pcsx2 melonDS xemu Cemu rpcs3 azahar citra retroarch \
      duckstation flycast primehack shadps4 Vita3K mgba snes9x ppsspp"
game_running() {
  pgrep -f "[r]eaper SteamLaunch AppId=" >/dev/null 2>&1 && return 0
  local e
  for e in $EMUS; do
    pgrep -x "$e" >/dev/null 2>&1 && return 0          # exact name: no self-match
    pgrep -f "/${e}[^/]*\$" >/dev/null 2>&1 && return 0   # or launched by full path
  done
  return 1
}
log() { echo "$(date '+%F %T') $*"; }

while true; do
  if game_running; then
    was_running=1
  elif [ "$was_running" = 1 ]; then
    log "game exited -> push"
    log "$(bash "$SAVES" backup 2>&1 | tail -1)"
    was_running=0
  else
    out=$(bash "$SAVES" autosync 2>&1 | tail -1)
    case "$out" in
      OK\ pulled*|OK\ profile*|CONFLICT*|ERR*) log "$out" ;;
    esac
  fi
  sleep "$INTERVAL"
done
