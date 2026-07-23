#!/bin/bash
# The saves location must be configurable from config.json (it used to be env-only), while the
# old environment variables still work for anyone relying on them.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
set -u
T=$(mktemp -d); H="$T/home"; mkdir -p "$H/Emulation/saves" "$H/Emulation/storage" "$H/bin" "$H/.deck-saves" "$H/.config/loadout"
cat > "$H/bin/rclone" <<'RC'
#!/bin/bash
echo "$@" >> "$HOME/calls.log"
case "$1" in lsf|cat) exit 1;; *) exit 0;; esac
RC
chmod +x "$H/bin/rclone"
fails=()
run() { HOME="$H" DECK_SAVES_ACCT=A RCLONE_BIN="$H/bin/rclone" bash "$ROOT/deck-saves.sh" backup >/dev/null 2>&1; }

echo '{"saves_rclone_remote": "mynas:backups/DeckSaves"}' > "$H/.config/loadout/config.json"
: > "$H/calls.log"; run
line=$(grep -m1 'sync' "$H/calls.log")
echo "  config says mynas:backups/DeckSaves -> $(grep -o 'mynas:[^ ]*' <<<"$line" | head -1)"
grep -q 'mynas:backups/DeckSaves/A/' <<<"$line" || fails+=("config value ignored")

echo '{}' > "$H/.config/loadout/config.json"
: > "$H/calls.log"; HOME="$H" DECK_SAVES_ACCT=A RCLONE_BIN="$H/bin/rclone" \
  DECK_SAVES_REMOTE=envnas DECK_SAVES_BASE=env/Saves bash "$ROOT/deck-saves.sh" backup >/dev/null 2>&1
line=$(grep -m1 'sync' "$H/calls.log")
echo "  no config, env set          -> $(grep -o 'envnas:[^ ]*' <<<"$line" | head -1)"
grep -q 'envnas:env/Saves/A/' <<<"$line" || fails+=("env fallback broken")

echo '{"saves_rclone_remote": "off"}' > "$H/.config/loadout/config.json"
: > "$H/calls.log"; run
line=$(grep -m1 'sync' "$H/calls.log")
echo "  config 'off'                -> falls back to default: $(grep -o 'games:[^ ]*' <<<"$line" | head -1)"
grep -q 'games:games/Saves/A/' <<<"$line" || fails+=("'off' did not fall back safely")

rm -rf "$T"
if [ ${#fails[@]} -eq 0 ]; then echo "PASS"; else printf 'FAIL: %s\n' "${fails[@]}"; exit 1; fi
