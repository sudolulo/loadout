#!/bin/bash
# Deck: rootless SMB(rclone) + mergerfs union -> ~/Emulation/roms. Survives reboots (user units).
set -u
export XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus PATH=$HOME/bin:$PATH
EMU=$HOME/Emulation; LOCAL=$EMU/roms-local; NAS=$HOME/.cache/nas-roms; UNION=$EMU/roms

# tear down any prior mounts
systemctl --user stop mergerfs-roms.service rclone-roms.service 2>/dev/null
fusermount -uz "$UNION" 2>/dev/null; fusermount -uz "$NAS" 2>/dev/null; sleep 1

# one-time: turn the current roms dir into the LOCAL branch
if [ ! -d "$LOCAL" ]; then mv "$EMU/roms" "$LOCAL"; fi
mkdir -p "$NAS" "$UNION"

# leave Switch/Wii OFF the local branch (clear partial early-sync copies; share provides them)
rm -rf "$LOCAL/switch" "$LOCAL/wii"; mkdir -p "$LOCAL/switch" "$LOCAL/wii"

mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/rclone-roms.service <<'UNIT'
[Unit]
Description=rclone mount NAS roms (read-only)
After=network-online.target
[Service]
Type=simple
ExecStart=%h/bin/rclone mount games:roms %h/.cache/nas-roms --read-only --dir-cache-time 1m --vfs-cache-mode minimal --buffer-size 64M --attr-timeout 5s --rc --rc-addr 127.0.0.1:5573 --rc-no-auth
ExecStop=/usr/bin/fusermount -uz %h/.cache/nas-roms
Restart=on-failure
RestartSec=10
[Install]
WantedBy=default.target
UNIT

cat > ~/.config/systemd/user/mergerfs-roms.service <<'UNIT'
[Unit]
Description=mergerfs union roms (local + NAS share)
After=rclone-roms.service
Requires=rclone-roms.service
[Service]
Type=simple
ExecStartPre=/bin/bash -c 'for i in $(seq 1 30); do mountpoint -q %h/.cache/nas-roms && exit 0; sleep 1; done; exit 0'
ExecStart=%h/bin/mergerfs -f -o category.create=ff,cache.files=partial,dropcacheonclose=true,allow_other=false %h/Emulation/roms-local=RW:%h/.cache/nas-roms=RO %h/Emulation/roms
ExecStop=/usr/bin/fusermount -uz %h/Emulation/roms
Restart=on-failure
RestartSec=10
[Install]
WantedBy=default.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now rclone-roms.service; sleep 6
systemctl --user enable --now mergerfs-roms.service; sleep 4

echo "=== services ==="; systemctl --user is-active rclone-roms.service mergerfs-roms.service
echo "=== union mounted? ==="; mountpoint -q "$UNION" && echo "UNION mounted" || echo "UNION NOT mounted"
echo "=== counts (local snes/n64 + remote switch/gc/wii/xbox) ==="
for s in snes n64 switch gc wii xbox; do printf "  %-7s %s\n" "$s" "$(ls "$UNION/$s" 2>/dev/null | wc -l)"; done
echo "=== free ==="; df -h "$HOME" | tail -1 | awk '{print "  "$4" free"}'
