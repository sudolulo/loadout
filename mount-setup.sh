#!/bin/bash
# Deck: rootless mergerfs union across up to three tiers -> the ROM union dir.
#   INTERNAL (always)  +  SD card (optional, auto-detected)  +  NAS (optional, rclone RO)
# All paths come from ~/.config/loadout/config.json -- the SAME file the GUI reads --
# so the union and the manager always agree on where the tiers are. Survives reboots via
# systemd --user units.
#
# Env knobs:
#   LOADOUT_CONFIG   override the config path
#   ROM_RCLONE_REMOTE        rclone remote:path for the NAS branch (default games:roms;
#                            set to "off" for a NAS-less, local-only union)
set -u
export XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus PATH=$HOME/bin:$PATH

# --- resolve tier paths from the shared config (single source of truth) --------------------
# Inline python3 mirrors the GUI's defaults + SD auto-detect and prints shell assignments.
# (python3 ships on SteamOS, so no jq dependency.) Auto-detect only picks a mount that
# already holds an Emulation/roms(-local) tree, so it never provisions a stray USB stick;
# to point the SD tier somewhere fresh, set "rom_sd" in the config to an explicit path.
eval "$(python3 - <<'PY'
import json, os, glob
CFG = os.path.expanduser(os.environ.get("LOADOUT_CONFIG",
                                        "~/.config/loadout/config.json"))
D = {"rom_local": "~/Emulation/roms-local", "rom_sd": "",
     "rom_nas": "~/Emulation/nas-roms", "rom_union": "~/Emulation/roms",
     "rom_rclone_remote": ""}
c = dict(D)
try:
    c.update({k: v for k, v in json.load(open(CFG)).items() if k in D})
except Exception:
    pass


def detect_sd():
    for pat in ("/run/media/deck/*", "/run/media/*/*", "/run/media/*"):
        for m in sorted(glob.glob(pat)):
            if not os.path.isdir(m):
                continue
            for sub in ("Emulation/roms-local", "Emulation/roms"):
                if os.path.isdir(os.path.join(m, sub)):
                    return os.path.join(m, sub)
    return ""


raw = (c["rom_sd"] or "").strip()
if raw.lower() in ("off", "none", "disabled"):
    sd = ""
elif raw:
    sd = os.path.expanduser(raw)     # explicit path: created below if missing (user opted in)
else:
    sd = detect_sd()


def q(s):
    return "'" + s.replace("'", "'\\''") + "'"


print("LOCAL=%s" % q(os.path.expanduser(c["rom_local"])))
print("SD=%s" % q(sd))
print("NAS=%s" % q(os.path.expanduser(c["rom_nas"])))
print("UNION=%s" % q(os.path.expanduser(c["rom_union"])))
print("REMOTE_CFG=%s" % q(c.get("rom_rclone_remote", "")))
PY
)"

# --- NAS tier: on unless disabled or rclone/remote missing ---------------------------------
# precedence: config's rom_rclone_remote (set by the in-app SMB setup) > $ROM_RCLONE_REMOTE env
# > the legacy games:roms default. Empty everywhere => local-only union.
REMOTE="${REMOTE_CFG:-${ROM_RCLONE_REMOTE:-games:roms}}"
RCLONE="$HOME/bin/rclone"; [ -x "$RCLONE" ] || RCLONE="$(command -v rclone || true)"
NAS_ON=1
{ [ -z "$REMOTE" ] || [ "$REMOTE" = "off" ] || [ -z "$RCLONE" ]; } && NAS_ON=0

# tear down any prior mounts
systemctl --user stop mergerfs-roms.service rclone-roms.service 2>/dev/null
fusermount -uz "$UNION" 2>/dev/null; [ -n "$NAS" ] && fusermount -uz "$NAS" 2>/dev/null; sleep 1

# one-time: turn the current roms dir into the INTERNAL branch
if [ ! -d "$LOCAL" ]; then mv "$UNION" "$LOCAL" 2>/dev/null || mkdir -p "$LOCAL"; fi
mkdir -p "$LOCAL" "$UNION"
[ "$NAS_ON" = 1 ] && mkdir -p "$NAS"
[ -n "$SD" ] && mkdir -p "$SD"       # existing auto-detected dir = no-op; explicit path = created

# Make sure these branch dirs exist. This used to `rm -rf` switch/wii to clear partial early-sync
# copies -- but Loadout now decides what lives locally, so wiping them would DELETE games the user
# deliberately pulled offline (a Rebuild union would eat them). Never destroy branch content here.
mkdir -p "$LOCAL/switch" "$LOCAL/wii"

# assemble the branch string: internal RW, then SD RW, then NAS RO -- whichever exist
BRANCHES="$LOCAL=RW"
[ -n "$SD" ] && BRANCHES="$BRANCHES:$SD=RW"
[ "$NAS_ON" = 1 ] && BRANCHES="$BRANCHES:$NAS=RO"
DESC="internal"; [ -n "$SD" ] && DESC="$DESC + SD"; [ "$NAS_ON" = 1 ] && DESC="$DESC + NAS"

mkdir -p ~/.config/systemd/user

# --- NAS rclone unit (only when NAS is enabled) --------------------------------------------
if [ "$NAS_ON" = 1 ]; then
cat > ~/.config/systemd/user/rclone-roms.service <<UNIT
[Unit]
Description=rclone mount NAS roms (read-only)
After=network-online.target
[Service]
Type=simple
ExecStart=$RCLONE mount $REMOTE "$NAS" --read-only --dir-cache-time 1m --vfs-cache-mode minimal --buffer-size 64M --attr-timeout 5s --rc --rc-addr 127.0.0.1:5573 --rc-no-auth
ExecStop=/usr/bin/fusermount -uz "$NAS"
Restart=on-failure
RestartSec=10
[Install]
WantedBy=default.target
UNIT
else
  systemctl --user disable rclone-roms.service 2>/dev/null
  rm -f ~/.config/systemd/user/rclone-roms.service
fi

# --- mergerfs union unit (dynamic branches; NAS deps only when NAS is enabled) -------------
DEPS=""; PRE=""
if [ "$NAS_ON" = 1 ]; then
  DEPS=$'After=rclone-roms.service\nRequires=rclone-roms.service'
  PRE="ExecStartPre=/bin/bash -c 'for i in \$(seq 1 30); do mountpoint -q \"$NAS\" && exit 0; sleep 1; done; exit 0'"
fi
cat > ~/.config/systemd/user/mergerfs-roms.service <<UNIT
[Unit]
Description=mergerfs union roms ($DESC)
$DEPS
[Service]
Type=simple
$PRE
ExecStart=$HOME/bin/mergerfs -f -o category.create=ff,cache.files=partial,dropcacheonclose=true,allow_other=false "$BRANCHES" "$UNION"
ExecStop=/usr/bin/fusermount -uz "$UNION"
Restart=on-failure
RestartSec=10
[Install]
WantedBy=default.target
UNIT

systemctl --user daemon-reload
if [ "$NAS_ON" = 1 ]; then systemctl --user enable --now rclone-roms.service; sleep 6; fi
systemctl --user enable --now mergerfs-roms.service; sleep 4

# --- report --------------------------------------------------------------------------------
echo "=== tiers ==="
echo "  internal  $LOCAL"
[ -n "$SD" ] && echo "  SD        $SD"
[ "$NAS_ON" = 1 ] && echo "  NAS       $REMOTE  ->  $NAS" || echo "  NAS       (disabled -- local-only union)"
echo "=== services ==="
svc="mergerfs-roms.service"; [ "$NAS_ON" = 1 ] && svc="rclone-roms.service $svc"
systemctl --user is-active $svc
echo "=== union mounted? ==="; mountpoint -q "$UNION" && echo "UNION mounted" || echo "UNION NOT mounted"
echo "=== counts (snes/n64/switch/gc/wii/xbox) ==="
for s in snes n64 switch gc wii xbox; do printf "  %-7s %s\n" "$s" "$(ls "$UNION/$s" 2>/dev/null | wc -l)"; done
echo "=== free per tier ==="
for t in "$LOCAL" "$SD" "$NAS"; do
  [ -n "$t" ] && [ -d "$t" ] && printf "  %-44s %s free\n" "$t" "$(df -h "$t" | tail -1 | awk '{print $4}')"
done
