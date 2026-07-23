#!/bin/bash
# Install offline-manager for the current user (no root needed).
#   ./install.sh          # scripts + systemd units + default config
#   ./install.sh --no-units   # skip the systemd units
set -e
here="$(cd "$(dirname "$0")" && pwd)"
dest="$HOME"
echo "Installing offline-manager to $dest"

# 1) scripts to ~
for f in offline-manager.py offline-worker.py offline-sync.sh srm-refresh.sh \
         fix_collections.py deck-saves.sh deck-saves-daemon.sh steam-account.py \
         ps3-esde-setup.sh mount-setup.sh; do
  [ -f "$here/$f" ] && install -m 0755 "$here/$f" "$dest/$f"
done

# 2) config (never clobber an existing one)
mkdir -p "$HOME/.config/offline-manager"
if [ ! -f "$HOME/.config/offline-manager/config.json" ]; then
  cp "$here/config.example.json" "$HOME/.config/offline-manager/config.json"
  echo "  wrote default config -> ~/.config/offline-manager/config.json"
fi

# 3) systemd --user units
if [ "${1:-}" != "--no-units" ]; then
  mkdir -p "$HOME/.config/systemd/user"
  cp "$here"/systemd/* "$HOME/.config/systemd/user/" 2>/dev/null || true
  systemctl --user daemon-reload 2>/dev/null || true
  for u in offline-manager-worker.path offline-manager-srm.path deck-saves-daemon.service; do
    systemctl --user enable --now "$u" 2>/dev/null || echo "  (skipped $u)"
  done
fi

echo "Done."
echo "Next: run mount-setup.sh once to provision the mergerfs/rclone union,"
echo "and add offline-manager.py to Steam (or your launcher). Edit the config"
echo "at ~/.config/offline-manager/config.json if your paths differ."
