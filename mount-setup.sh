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
D = {"rom_local": "~/Emulation/.roms-local", "rom_sd": "~/Emulation/.roms-sd",
     "rom_nas": "~/Emulation/.roms-nas", "rom_union": "~/Emulation/roms",
     "rom_rclone_remote": "",
     "pc_local": "~/Games/.pc-local", "pc_sd": "~/Games/.pc-sd",
     "pc_nas": "~/Games/.pc-nas",
     "pc_union": "~/Games/PC", "pc_rclone_remote": ""}
c = dict(D)
try:
    c.update({k: v for k, v in json.load(open(CFG)).items() if k in D})
except Exception:
    pass


def sd_root():
    """The Deck's SD card: the first removable mount that already looks like a games card."""
    for pat in ("/run/media/deck/*", "/run/media/*/*", "/run/media/*"):
        for m in sorted(glob.glob(pat)):
            if os.path.isdir(m) and (os.path.isdir(os.path.join(m, "Emulation"))
                                     or os.path.isdir(os.path.join(m, "Games"))):
                return m
    return ""


def off(v):
    return (v or "").strip().lower() in ("off", "none", "disabled")


ROOT = sd_root()


def sd_dir(subs, default):
    """The card's branch for one library. Prefer a dir the card ALREADY uses (so an existing
    EmuDeck card keeps working), else fall back to the standard name, which the shell creates.
    The card's real path goes straight into the union -- no symlink indirection."""
    if not ROOT:
        return ""
    for s in subs:
        p = os.path.join(ROOT, s)
        if os.path.isdir(p):
            return p
    return os.path.join(ROOT, default)


# a card mirrors the share: <card>/ROMs and <card>/PC
sd = "" if off(c["rom_sd"]) else (os.path.expanduser(c["rom_sd"]) if (c["rom_sd"] or "").strip()
     else sd_dir(("ROMs", "roms", "Emulation/roms-local", "Emulation/roms"), "ROMs"))
pcsd = "" if off(c.get("pc_sd", "")) else (
    os.path.expanduser(c["pc_sd"]) if (c.get("pc_sd") or "").strip()
    else sd_dir(("PC", "pc", "Games/PC", "Games/.pc-local"), "PC"))


def q(s):
    return "'" + s.replace("'", "'\\''") + "'"


print("LOCAL=%s" % q(os.path.expanduser(c["rom_local"])))
print("SD=%s" % q(sd))
print("NAS=%s" % q(os.path.expanduser(c["rom_nas"])))
print("UNION=%s" % q(os.path.expanduser(c["rom_union"])))
print("REMOTE_CFG=%s" % q(c.get("rom_rclone_remote", "")))
print("PCLOCAL=%s" % q(os.path.expanduser(c["pc_local"])))
print("PCSD=%s" % q(pcsd))
print("PCNAS=%s" % q(os.path.expanduser(c["pc_nas"])))
print("PCUNION=%s" % q(os.path.expanduser(c["pc_union"])))
print("PCREMOTE_CFG=%s" % q(c.get("pc_rclone_remote", "")))
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

# one-time: the tier dirs used to be VISIBLE (roms-local / nas-roms); they're hidden now so only
# the union shows in ~/Emulation. Rename (never copy/merge) so the library moves intact. This MUST
# run before the roms->LOCAL fallback below, which would otherwise read a missing hidden dir as a
# first-ever run and move the union on top of it, orphaning the real library.
migrate_hidden() {                       # $1 = the new, hidden tier path
  local new="$1" dir base old
  dir="$(dirname "$new")"; base="$(basename "$new")"
  case "$base" in .?*) old="$dir/${base#.}" ;; *) return 0 ;; esac
  [ -d "$old" ] || return 0
  [ -e "$new" ] && return 0              # target exists: nothing to migrate, never merge
  mv "$old" "$new" 2>/dev/null || { mkdir -p "$new"; rmdir "$old" 2>/dev/null; }
  echo "  migrated $old -> $new"
}
migrate_hidden "$LOCAL"
migrate_hidden "$NAS"

# one-time: turn the current roms dir into the INTERNAL branch
if [ ! -d "$LOCAL" ]; then mv "$UNION" "$LOCAL" 2>/dev/null || mkdir -p "$LOCAL"; fi
mkdir -p "$LOCAL" "$UNION"
[ "$NAS_ON" = 1 ] && mkdir -p "$NAS"
# retire the previous NAS tier name (.nas-roms) once it's unmounted and empty
rmdir "$(dirname "$NAS")/.nas-roms" 2>/dev/null && echo "  removed legacy .nas-roms"

# SD branches use the card's REAL path (<card>/ROMs, <card>/PC) -- the tiers are hidden plumbing and
# mergerfs wants the actual path, so a symlink would be indirection with no payoff. Create the dir
# on a card we've identified; if there's no card the branch simply drops out.
[ -n "$SD" ] && mkdir -p "$SD" 2>/dev/null
[ -n "$SD" ] && [ ! -d "$SD" ] && SD=""      # no card => no SD branch

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

# --- PC games union: the SAME shape as ROMs, under ~/Games ----------------------------------
#     ~/Games/PC  (the union you browse)  <-  ~/Games/.pc-local (RW) + ~/Games/.pc-nas (RO)
PCREMOTE="${PCREMOTE_CFG:-}"
systemctl --user stop mergerfs-pc.service rclone-pc.service 2>/dev/null
fusermount -uz "$PCUNION" 2>/dev/null; [ -n "$PCNAS" ] && fusermount -uz "$PCNAS" 2>/dev/null; sleep 1

# legacy: PC games used to live in ~/Games-local with the union at ~/Games. Move that library into
# the hidden internal tier (rename, never merge) so the layout matches Emulation.
if [ -d "$HOME/Games-local" ] && [ ! -e "$PCLOCAL" ]; then
  mkdir -p "$(dirname "$PCLOCAL")"
  mv "$HOME/Games-local" "$PCLOCAL" && echo "  migrated $HOME/Games-local -> $PCLOCAL"
fi
migrate_hidden "$PCLOCAL"
migrate_hidden "$PCNAS"
mkdir -p "$PCLOCAL" "$PCUNION"

PCNAS_ON=0
{ [ -n "$PCREMOTE" ] && [ "$PCREMOTE" != "off" ] && [ -n "$RCLONE" ]; } && PCNAS_ON=1
[ "$PCNAS_ON" = 1 ] && mkdir -p "$PCNAS"
[ -n "$PCSD" ] && mkdir -p "$PCSD" 2>/dev/null
[ -n "$PCSD" ] && [ ! -d "$PCSD" ] && PCSD=""
PCBRANCHES="$PCLOCAL=RW"
[ -n "$PCSD" ] && PCBRANCHES="$PCBRANCHES:$PCSD=RW"
[ "$PCNAS_ON" = 1 ] && PCBRANCHES="$PCBRANCHES:$PCNAS=RO"

if [ "$PCNAS_ON" = 1 ]; then
cat > ~/.config/systemd/user/rclone-pc.service <<UNIT
[Unit]
Description=rclone mount NAS PC games (read-only)
After=network-online.target
[Service]
Type=simple
ExecStart=$RCLONE mount $PCREMOTE "$PCNAS" --read-only --dir-cache-time 1m --vfs-cache-mode minimal --buffer-size 64M --attr-timeout 5s --rc --rc-addr 127.0.0.1:5574 --rc-no-auth
ExecStop=/usr/bin/fusermount -uz "$PCNAS"
Restart=on-failure
RestartSec=10
[Install]
WantedBy=default.target
UNIT
else
  systemctl --user disable rclone-pc.service 2>/dev/null
  rm -f ~/.config/systemd/user/rclone-pc.service
fi

PCDEPS=""; PCPRE=""
if [ "$PCNAS_ON" = 1 ]; then
  PCDEPS=$'After=rclone-pc.service\nRequires=rclone-pc.service'
  PCPRE="ExecStartPre=/bin/bash -c 'for i in \$(seq 1 30); do mountpoint -q \"$PCNAS\" && exit 0; sleep 1; done; exit 0'"
fi
cat > ~/.config/systemd/user/mergerfs-pc.service <<UNIT
[Unit]
Description=mergerfs union PC games (internal$([ "$PCNAS_ON" = 1 ] && echo " + NAS"))
$PCDEPS
[Service]
Type=simple
$PCPRE
ExecStart=$HOME/bin/mergerfs -f -o category.create=ff,cache.files=partial,dropcacheonclose=true,allow_other=false "$PCBRANCHES" "$PCUNION"
ExecStop=/usr/bin/fusermount -uz "$PCUNION"
Restart=on-failure
RestartSec=10
[Install]
WantedBy=default.target
UNIT

systemctl --user daemon-reload
if [ "$PCNAS_ON" = 1 ]; then systemctl --user enable --now rclone-pc.service; sleep 6; fi
systemctl --user enable --now mergerfs-pc.service; sleep 3

# --- report --------------------------------------------------------------------------------
echo "=== tiers ==="
echo "  internal  $LOCAL"
[ -n "$SD" ] && echo "  SD        $SD"
[ "$NAS_ON" = 1 ] && echo "  NAS       $REMOTE  ->  $NAS" || echo "  NAS       (disabled -- local-only union)"
echo "=== services ==="
svc="mergerfs-roms.service"; [ "$NAS_ON" = 1 ] && svc="rclone-roms.service $svc"
systemctl --user is-active $svc
echo "=== PC tiers ==="
echo "  internal  $PCLOCAL"
[ -n "$PCSD" ] && echo "  SD        $PCSD"
[ "$PCNAS_ON" = 1 ] && echo "  NAS       $PCREMOTE  ->  $PCNAS" || echo "  NAS       (disabled -- local-only PC union)"
echo "  union     $PCUNION"
echo "=== union mounted? ==="; mountpoint -q "$UNION" && echo "UNION mounted" || echo "UNION NOT mounted"
mountpoint -q "$PCUNION" && echo "PC UNION mounted" || echo "PC UNION NOT mounted"
echo "=== counts (snes/n64/switch/gc/wii/xbox) ==="
for s in snes n64 switch gc wii xbox; do printf "  %-7s %s\n" "$s" "$(ls "$UNION/$s" 2>/dev/null | wc -l)"; done
echo "=== free per tier ==="
for t in "$LOCAL" "$SD" "$NAS"; do
  [ -n "$t" ] && [ -d "$t" ] && printf "  %-44s %s free\n" "$t" "$(df -h "$t" | tail -1 | awk '{print $4}')"
done
