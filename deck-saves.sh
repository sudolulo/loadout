#!/bin/bash
# Emulator saves on the NAS, filed under the Steam account that is actually signed in.
#
# Emulators keep one save tree per Deck (~/Emulation/{saves,storage}), not one per Steam
# profile -- so "saves follow the profile" means swapping that tree when the signed-in
# account changes. That is what `autosync` does, and it never does it mid-game.
#
#   backup    push the signed-in profile's saves up
#   restore   pull them down
#   autosync  profile switch -> hand the tree over; otherwise pull only if the NAS is
#             newer AND this Deck has nothing unpushed. Refuses on conflict.
#   status    machine-readable state for the manager GUI
set -u
RC="${RCLONE_BIN:-$HOME/bin/rclone}"
RCLONE_REMOTE="${DECK_SAVES_REMOTE:-games}"       # rclone remote name (rclone config)
SAVES_BASE="${DECK_SAVES_BASE:-games/Saves}"      # path within that remote
STATE="$HOME/.deck-saves"; mkdir -p "$STATE"
CURFILE="$STATE/current-account"     # whose saves are sitting in ~/Emulation right now
FLAGS="--transfers=8 --checkers=8 --fast-list"
LOG="$HOME/deck-saves.log"
declare -A SRC=( [saves]="$HOME/Emulation/saves" [storage]="$HOME/Emulation/storage" )

# The signed-in account, not merely the first directory under userdata/.
ACCT="${DECK_SAVES_ACCT:-$(python3 "$HOME/steam-account.py" 2>/dev/null)}"
[ -n "${ACCT:-}" ] || { echo "ERR cannot determine the signed-in Steam account"; exit 1; }

remote()   { echo "$RCLONE_REMOTE:$SAVES_BASE/$1"; }
mark()     { echo "$STATE/synced-$1"; }
conflict() { echo "$STATE/conflict-$1"; }
nas_ts()   { "$RC" cat "$(remote "$1")/.last-backup" 2>/dev/null | head -1 | cut -f1; }
nas_host() { "$RC" cat "$(remote "$1")/.last-backup" 2>/dev/null | head -1 | cut -f2; }
local_ts() { cat "$(mark "$1")" 2>/dev/null | head -1; }
nas_has()  { "$RC" lsf "$(remote "$1")/saves" >/dev/null 2>&1; }

newest_local() {
  local n=0 t
  for k in "${!SRC[@]}"; do
    [ -d "${SRC[$k]}" ] || continue
    t=$(find "${SRC[$k]}" -type f -printf '%T@\n' 2>/dev/null | cut -d. -f1 | sort -rn | head -1)
    [ -n "${t:-}" ] && [ "$t" -gt "$n" ] && n=$t
  done
  echo "$n"
}
# progress this Deck has that the NAS has not seen
local_dirty() { [ "$(newest_local)" -gt "$(( $(local_ts "$1" || echo 0) + 5 ))" ] 2>/dev/null; }

push() {                       # push $1's saves; refuses to stamp the marker on failure
  local a=$1 now rc=0
  for k in "${!SRC[@]}"; do
    [ -d "${SRC[$k]}" ] || continue
    "$RC" sync "${SRC[$k]}" "$(remote "$a")/$k" $FLAGS >>"$LOG" 2>&1 || rc=$?
  done
  if [ "$rc" != 0 ]; then
    echo "ERR push failed (rclone rc=$rc) -- see $LOG; marker NOT stamped"
    return "$rc"
  fi
  now=$(date +%s)
  printf '%s\t%s\t%s\n' "$now" "$(cat /etc/hostname 2>/dev/null || echo deck)" "$a" > /tmp/.sb.$$
  "$RC" copyto /tmp/.sb.$$ "$(remote "$a")/.last-backup" >>"$LOG" 2>&1 || rc=$?
  rm -f /tmp/.sb.$$
  [ "$rc" != 0 ] && { echo "ERR could not stamp timestamp (rc=$rc)"; return "$rc"; }
  echo "$now" > "$(mark "$a")"; rm -f "$(conflict "$a")"; echo "$a" > "$CURFILE"
}

pull() {                       # pull $1's saves down; same no-lying-on-failure rule
  local a=$1 rc=0 t
  for k in "${!SRC[@]}"; do
    "$RC" lsf "$(remote "$a")/$k" >/dev/null 2>&1 || continue
    mkdir -p "${SRC[$k]}"
    "$RC" sync "$(remote "$a")/$k" "${SRC[$k]}" $FLAGS >>"$LOG" 2>&1 || rc=$?
  done
  [ "$rc" != 0 ] && { echo "ERR pull failed (rclone rc=$rc) -- see $LOG"; return "$rc"; }
  t=$(nas_ts "$a")
  # the tree now matches the NAS, so record its stamp -- not "now"
  echo "${t:-$(date +%s)}" > "$(mark "$a")"
  rm -f "$(conflict "$a")"; echo "$a" > "$CURFILE"
}

case "${1:-status}" in
  backup)  push "$ACCT"  && echo "OK backed up profile $ACCT" ;;
  restore) pull "$ACCT"  && echo "OK restored profile $ACCT" ;;

  autosync)
    prev=$(cat "$CURFILE" 2>/dev/null | head -1)
    if [ -z "${prev:-}" ]; then echo "$ACCT" > "$CURFILE"; prev="$ACCT"; fi

    # --- a different profile signed in: hand the save tree over ---
    if [ "$prev" != "$ACCT" ]; then
      # keep the outgoing profile's progress -- if that push fails, change nothing
      push "$prev" || { echo "ERR could not save profile $prev; not switching"; exit 1; }
      if nas_has "$ACCT"; then
        pull "$ACCT" && echo "OK profile $prev -> $ACCT (restored their saves)"
      else
        push "$ACCT" && \
          echo "OK profile $prev -> $ACCT (new profile, seeded from this Deck)"
      fi
      exit 0
    fi

    n=$(nas_ts "$ACCT"); l=$(local_ts "$ACCT")
    [ -z "${n:-}" ] && { echo "OK nothing on NAS yet"; exit 0; }
    [ "${n:-0}" -le "${l:-0}" ] 2>/dev/null && { echo "OK already current"; exit 0; }
    if local_dirty "$ACCT"; then
      printf 'nas=%s\thost=%s\n' "$n" "$(nas_host "$ACCT")" > "$(conflict "$ACCT")"
      echo "CONFLICT unsynced saves here and a newer copy on the NAS"; exit 2
    fi
    pull "$ACCT" && echo "OK pulled newer saves from $(nas_host "$ACCT")" ;;

  status)
    echo "account=$ACCT"
    echo "account_name=$(grep -aoE '\"AutoLoginUser\"[[:space:]]+\"[^\"]*\"' "$HOME/.steam/registry.vdf" 2>/dev/null | sed 's/.*\"\([^\"]*\)\"$/\1/')"
    echo "profiles_on_deck=$(ls -1 "$HOME/.local/share/Steam/userdata" 2>/dev/null | grep -cE '^[0-9]+$')"
    echo "last_backup=$("$RC" cat "$(remote "$ACCT")/.last-backup" 2>/dev/null | head -1 || echo none)"
    echo "local_synced=$(local_ts "$ACCT" || echo 0)"
    echo "dirty=$(local_dirty "$ACCT" && echo 1 || echo 0)"
    echo "conflict=$( [ -f "$(conflict "$ACCT")" ] && cat "$(conflict "$ACCT")" || echo none)"
    echo "auto=$(systemctl --user is-active deck-saves-daemon 2>/dev/null || echo unknown)"
    loc=0; for k in "${!SRC[@]}"; do [ -d "${SRC[$k]}" ] && loc=$((loc+$(du -sb "${SRC[$k]}" 2>/dev/null|cut -f1))); done
    echo "local_bytes=$loc"
    echo "nas_bytes=$("$RC" size "$(remote "$ACCT")" --json 2>/dev/null | python3 -c 'import json,sys;print(json.load(sys.stdin).get("bytes",0))' 2>/dev/null || echo 0)" ;;
esac
