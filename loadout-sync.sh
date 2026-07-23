#!/bin/bash
# Wait for the manager to be gone, then refresh Steam. Patterns live in this file, not
# on any command line, so pgrep cannot match this script itself.
LOG="$HOME/loadout-sync.log"
SELF=$$
echo "=== $(date '+%F %T') sync triggered ===" >> "$LOG"

others() {           # pids matching $1, excluding this script and its children
  pgrep -f "$1" 2>/dev/null | while read -r pid; do
    [ "$pid" = "$SELF" ] && continue
    ppid=$(awk '{print $4}' "/proc/$pid/stat" 2>/dev/null)
    [ "$ppid" = "$SELF" ] && continue
    echo "$pid"
  done
}

for i in $(seq 1 60); do [ -z "$(others 'loadout[.]py')" ] && break; sleep 2; done
for i in $(seq 1 60); do [ -z "$(others 'reaper SteamLaunch AppId=')" ] && break; sleep 2; done
sleep 3

# Block the screen so nothing is started mid-refresh (Steam is about to restart)
WAIT_PID=""
if [ -f "$HOME/steam-wait-screen.py" ]; then
  python3 "$HOME/steam-wait-screen.py" >/dev/null 2>&1 &
  WAIT_PID=$!
fi

bash "$HOME/srm-refresh.sh" >> "$LOG" 2>&1
rc=$?
[ -n "$WAIT_PID" ] && kill "$WAIT_PID" 2>/dev/null
if [ $rc -eq 0 ]; then
  rm -f "$HOME/.loadout-dirty"
  echo "sync completed" >> "$LOG"
else
  echo "sync FAILED (exit $rc) - flag kept, will retry" >> "$LOG"
  sleep 60
fi
