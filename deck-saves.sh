#!/bin/bash
# Game saves on the NAS, filed under the Steam account that is actually signed in.
#
# Covers emulator saves (~/Emulation/{saves,storage}) and Windows-game saves from the Proton
# prefixes Steam keeps at steamapps/compatdata/<appid> -- only for NON-STEAM shortcuts, and
# filtered to the user profile so the Windows install itself is never uploaded.
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
# Where saves live on the NAS comes from the SAME config.json the GUI writes, so the in-app SMB
# setup can point it anywhere. It used to be readable only from these environment variables,
# which meant a share laid out differently could not be configured at all. Precedence:
# config.json > environment > the historical default.
_CFG=$(python3 - <<'PY' 2>/dev/null
import json, os
p = os.environ.get("LOADOUT_CONFIG") or os.path.expanduser("~/.config/loadout/config.json")
try:
    v = (json.load(open(p)).get("saves_rclone_remote") or "").strip()
except Exception:
    v = ""
print(v if ":" in v and v.lower() != "off" else "")
PY
)
if [ -n "${_CFG:-}" ]; then
  RCLONE_REMOTE="${_CFG%%:*}"
  SAVES_BASE="${_CFG#*:}"
else
  RCLONE_REMOTE="${DECK_SAVES_REMOTE:-games}"     # rclone remote name (rclone config)
  SAVES_BASE="${DECK_SAVES_BASE:-games/Saves}"    # path within that remote
fi
STATE="$HOME/.deck-saves"; mkdir -p "$STATE"
CURFILE="$STATE/current-account"     # whose saves are sitting in ~/Emulation right now
FLAGS="--transfers=8 --checkers=8 --fast-list"
LOG="$HOME/deck-saves.log"
declare -A SRC=( [saves]="$HOME/Emulation/saves" [storage]="$HOME/Emulation/storage" )
declare -A FIND=()

# --- Windows-game saves -------------------------------------------------------------------
# Windows games run in a Proton prefix that STEAM owns, at steamapps/compatdata/<appid> -- the
# normal place, the one every guide points at. Only NON-STEAM shortcuts are our business: a
# real Steam game's prefix is Steam Cloud's job and is often many GB.
#
# Steam sets the high bit on a non-Steam shortcut's appid, so >= 2^31 identifies them exactly.
# Include rules are built per-appid because rclone filters cannot do that comparison -- and if
# there are none, the key is left out entirely: an empty include list would mean "no filter",
# which would upload every Steam game's prefix.
CD="$HOME/.local/share/Steam/steamapps/compatdata"
PC_IDS=(); PC_FIND=""
if [ -d "$CD" ]; then
  for _d in "$CD"/*; do
    _id=${_d##*/}
    [[ "$_id" =~ ^[0-9]+$ ]] || continue
    [ "$_id" -ge 2147483648 ] 2>/dev/null || continue
    PC_IDS+=("$_id")
    PC_FIND="$PC_FIND -o -path */$_id/pfx/drive_c/users/steamuser/*"
  done
fi
if [ ${#PC_IDS[@]} -gt 0 ]; then
  SRC[pcsaves]="$CD"
  # the same subtree drives the "has this Deck got unpushed progress?" check -- otherwise the
  # constant churn Windows makes inside a prefix reads as progress and jams autosync in CONFLICT
  FIND[pcsaves]="( ${PC_FIND# -o } ) -not -path */Temp/* -not -path */Cache/*"
fi

# rclone REFUSES to define an order when --include and --exclude are mixed ("the order they are
# parsed in is indeterminate"), so the rules are expressed as --filter, which is explicitly
# first-match-wins. Built as an ARRAY: a filter rule contains a space, which unquoted word
# splitting would tear in half.
rclone_filters() {
  FILTERS=()
  [ "$1" = pcsaves ] || return 0
  local id
  FILTERS+=( --filter "- **/AppData/Local/Temp/**" )
  FILTERS+=( --filter "- **/AppData/LocalLow/Temp/**" )
  FILTERS+=( --filter "- **/Cache/**" )
  for id in "${PC_IDS[@]}"; do
    FILTERS+=( --filter "+ $id/pfx/drive_c/users/steamuser/**" )
  done
  FILTERS+=( --filter "- **" )        # a prefix is ~1GB of Windows; nothing else goes up
}

# The signed-in account, not merely the first directory under userdata/.
# Helpers live INSIDE the AppImage, never in $HOME -- the container deletes any copy there, so
# reaching into ~ silently broke the account lookup (and with it all save sync) after 0.7.2.
APPDIR="${LOADOUT_APP:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
ACCT="${DECK_SAVES_ACCT:-$(python3 "$APPDIR/steam-account.py" 2>/dev/null)}"
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
    t=$(find "${SRC[$k]}" ${FIND[$k]:-} -type f -printf '%T@\n' 2>/dev/null | cut -d. -f1 | sort -rn | head -1)
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
    rclone_filters "$k"
    "$RC" sync "${SRC[$k]}" "$(remote "$a")/$k" $FLAGS "${FILTERS[@]}" >>"$LOG" 2>&1 || rc=$?
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
    rclone_filters "$k"
    "$RC" sync "$(remote "$a")/$k" "${SRC[$k]}" $FLAGS "${FILTERS[@]}" >>"$LOG" 2>&1 || rc=$?
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
    # the containerised unit is loadout-saves.service; the old deck-saves-daemon name reported
    # "inactive" forever. is-active PRINTS its answer and also exits non-zero, so the old
    # `|| echo unknown` emitted a second bogus line on top of it.
    _auto=$(systemctl --user is-active loadout-saves.service 2>/dev/null | head -1)
    echo "auto=${_auto:-unknown}"
    # size only what is actually synced -- du on a whole Proton prefix would report the
    # Windows install as if it were save data
    loc=0
    for k in "${!SRC[@]}"; do
      [ -d "${SRC[$k]}" ] || continue
      loc=$((loc+$(find "${SRC[$k]}" ${FIND[$k]:-} -type f -printf '%s\n' 2>/dev/null | awk '{t+=$1} END{print t+0}')))
    done
    echo "local_bytes=$loc"
    echo "nas_bytes=$("$RC" size "$(remote "$ACCT")" --json 2>/dev/null | python3 -c 'import json,sys;print(json.load(sys.stdin).get("bytes",0))' 2>/dev/null || echo 0)" ;;
esac
