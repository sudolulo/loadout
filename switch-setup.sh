#!/bin/bash
# Deck-side Switch setup — keys + firmware + DLC/update register, ALL pulled from the share.
# Run once per Deck AFTER deck-mount-setup.sh (needs the rclone 'games' remote + mount).
# Fully automatic: no GUI. Firmware = Ryujinx's registered/ store, pre-built on the share
# (media/Games/ROMs/.switch/firmware-registered.tar) so no "Install Firmware" clicking.
set -u
export PATH=$HOME/bin:$PATH XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus

echo "== keys =="
SYS=$HOME/.config/Ryujinx/system; mkdir -p "$SYS"
rclone cat games:roms/.switch/prod.keys  > "$SYS/prod.keys"  2>/dev/null
rclone cat games:roms/.switch/title.keys > "$SYS/title.keys" 2>/dev/null
echo "  prod.keys: $(wc -l < "$SYS/prod.keys" 2>/dev/null) lines"

echo "== firmware (registered store from share; Ryujinx wants <id>.nca DIRECTORIES, not files) =="
C=$HOME/.config/Ryujinx/bis/system/Contents; mkdir -p "$C"; rm -rf "$C/registered"
( cd "$C" && rclone cat games:roms/.switch/firmware-registered.tar | tar xf - )
echo "  registered: $(ls "$C/registered" 2>/dev/null | wc -l) entries"

echo "== DLC/update register + 30-min timer =="
python3 "$HOME/register-switch.py"
mkdir -p "$HOME/.config/systemd/user"
printf '[Unit]\nDescription=Register Switch DLC/updates\nAfter=rclone-roms.service mergerfs-roms.service\n[Service]\nType=oneshot\nExecStart=/usr/bin/python3 %%h/register-switch.py\n' > "$HOME/.config/systemd/user/register-switch.service"
printf '[Unit]\nDescription=Periodic register\n[Timer]\nOnBootSec=3min\nOnUnitActiveSec=30min\nPersistent=true\n[Install]\nWantedBy=timers.target\n' > "$HOME/.config/systemd/user/register-switch.timer"
systemctl --user daemon-reload
systemctl --user enable --now register-switch.timer >/dev/null 2>&1
echo "  timer: $(systemctl --user is-enabled register-switch.timer)"
echo "DONE — restart Ryujinx to pick up keys + firmware."
