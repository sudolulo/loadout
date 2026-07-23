#!/bin/bash
# Install loadout for the current user (no root needed).
#   ./install.sh          # scripts + systemd units + default config
#   ./install.sh --no-units   # skip the systemd units
set -e
here="$(cd "$(dirname "$0")" && pwd)"
dest="$HOME"
echo "Installing loadout to $dest"

# 0) migrate a previous "offline-manager" install (the project was renamed to loadout)
oldcfg="$HOME/.config/offline-manager"; newcfg="$HOME/.config/loadout"
if [ -d "$oldcfg" ] && [ ! -d "$newcfg" ]; then
  mv "$oldcfg" "$newcfg" && echo "  migrated config: offline-manager -> loadout"
fi
for u in offline-manager-worker.path offline-manager-worker.service \
         offline-manager-srm.path offline-manager-srm.service; do
  systemctl --user disable --now "$u" 2>/dev/null || true
  rm -f "$HOME/.config/systemd/user/$u"
done
rm -f "$HOME"/offline-manager.py "$HOME"/offline-worker.py "$HOME"/offline-sync.sh
systemctl --user daemon-reload 2>/dev/null || true

# 1) scripts to ~
for f in loadout.py loadout-worker.py loadout_update.py steamgriddb.py steam_shortcuts.py \
         loadout-sync.sh steam-refresh.sh srm-refresh.sh fix_collections.py deck-saves.sh deck-saves-daemon.sh \
         steam-account.py ps3-esde-setup.sh mount-setup.sh; do
  [ -f "$here/$f" ] && install -m 0755 "$here/$f" "$dest/$f"
done

# 2) config (never clobber an existing one)
mkdir -p "$HOME/.config/loadout"
if [ ! -f "$HOME/.config/loadout/config.json" ]; then
  cp "$here/config.example.json" "$HOME/.config/loadout/config.json"
  echo "  wrote default config -> ~/.config/loadout/config.json"
fi

# 3) systemd --user units
if [ "${1:-}" != "--no-units" ]; then
  mkdir -p "$HOME/.config/systemd/user"
  cp "$here"/systemd/* "$HOME/.config/systemd/user/" 2>/dev/null || true
  systemctl --user daemon-reload 2>/dev/null || true
  for u in loadout-worker.path loadout-srm.path deck-saves-daemon.service; do
    systemctl --user enable --now "$u" 2>/dev/null || echo "  (skipped $u)"
  done
fi

echo "Done."
echo "Next: run mount-setup.sh once to provision the mergerfs/rclone union,"
echo "and add loadout.py to Steam (or your launcher). Edit the config"
echo "at ~/.config/loadout/config.json if your paths differ."
