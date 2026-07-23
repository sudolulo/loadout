#!/bin/bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# PC saves now come from Steam's compatdata. The rule must cover NON-STEAM shortcuts only,
# and must never degenerate into "sync every Steam game's prefix".
set -u
mk() {   # $1 = list of appids to create prefixes for
  T=$(mktemp -d); H="$T/home"
  mkdir -p "$H/Emulation/saves" "$H/Emulation/storage" "$H/bin" "$H/.deck-saves"
  CD="$H/.local/share/Steam/steamapps/compatdata"
  for id in $1; do
    mkdir -p "$CD/$id/pfx/drive_c/users/steamuser/Documents/My Games"
    echo "save-$id" > "$CD/$id/pfx/drive_c/users/steamuser/Documents/My Games/s.sav"
    mkdir -p "$CD/$id/pfx/drive_c/windows/system32"
    echo bulk > "$CD/$id/pfx/drive_c/windows/system32/big.dll"
  done
  cat > "$H/bin/rclone" <<'RC'
#!/bin/bash
echo "$@" >> "$HOME/rclone-calls.log"
case "$1" in lsf|cat) exit 1 ;; *) exit 0 ;; esac
RC
  chmod +x "$H/bin/rclone"
}
fails=()

# 1. a mix of real Steam appids and non-Steam shortcut appids
mk "413150 362890 3359702471 4006258169"
out=$(HOME="$H" DECK_SAVES_ACCT=A RCLONE_BIN="$H/bin/rclone" bash "$ROOT"/deck-saves.sh backup 2>&1)
line=$(grep 'compatdata' "$H/rclone-calls.log" | head -1)
echo "  pushed compatdata: $([ -n "$line" ] && echo yes || echo no)"
for id in 3359702471 4006258169; do
  grep -q -- "--include=$id/pfx" <<<"$line" || fails+=("non-Steam prefix $id was not included")
done
for id in 413150 362890; do
  grep -q -- "--include=$id/pfx" <<<"$line" && fails+=("REAL Steam game $id would be uploaded")
done
echo "  includes only non-Steam appids: $(grep -o -- '--include=[0-9]*' <<<"$line" | tr '\n' ' ')"
[[ "${line%%--include*}" == *"--exclude"* ]] || fails+=("an exclude lands after the include")

# 2. THE DANGEROUS CASE: no non-Steam prefixes at all must mean no pcsaves sync,
#    never an unfiltered sync of every Steam game
mk "413150 362890"
out=$(HOME="$H" DECK_SAVES_ACCT=A RCLONE_BIN="$H/bin/rclone" bash "$ROOT"/deck-saves.sh backup 2>&1)
n=$(grep -c "compatdata" "$H/rclone-calls.log" 2>/dev/null; true)
echo "  with only real Steam prefixes, compatdata syncs attempted: $n (expect 0)"
[ "$n" = "0" ] || fails+=("would sync Steam-owned prefixes with no filter")

# 3. dirty detection sees a non-Steam save edit but ignores Windows churn
mk "3359702471"
NOW=$(date +%s); CD="$H/.local/share/Steam/steamapps/compatdata"
touch -d "@$((NOW-100))" "$CD/3359702471/pfx/drive_c/users/steamuser/Documents/My Games/s.sav"
touch -d "@$((NOW+300))" "$CD/3359702471/pfx/drive_c/windows/system32/big.dll"
echo "$NOW" > "$H/.deck-saves/synced-A"
d=$(HOME="$H" DECK_SAVES_ACCT=A RCLONE_BIN="$H/bin/rclone" bash "$ROOT"/deck-saves.sh status 2>&1 | grep '^dirty=' | cut -d= -f2)
b=$(HOME="$H" DECK_SAVES_ACCT=A RCLONE_BIN="$H/bin/rclone" bash "$ROOT"/deck-saves.sh status 2>&1 | grep '^local_bytes=' | cut -d= -f2)
echo "  windows churn only -> dirty=$d (expect 0), local_bytes=$b (expect just the save)"
[ "$d" = "0" ] || fails+=("Windows churn read as unsynced progress")
[ "${b:-999}" -lt 100 ] || fails+=("local_bytes counts the Windows install ($b)")
touch -d "@$((NOW+400))" "$CD/3359702471/pfx/drive_c/users/steamuser/Documents/My Games/s.sav"
d2=$(HOME="$H" DECK_SAVES_ACCT=A RCLONE_BIN="$H/bin/rclone" bash "$ROOT"/deck-saves.sh status 2>&1 | grep '^dirty=' | cut -d= -f2)
echo "  after a real save edit -> dirty=$d2 (expect 1)"
[ "$d2" = "1" ] || fails+=("a real PC save edit was not detected")

if [ ${#fails[@]} -eq 0 ]; then echo "PASS"; else printf 'FAIL: %s\n' "${fails[@]}"; exit 1; fi
