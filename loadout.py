#!/usr/bin/env python3
"""Loadout -- choose what stays on this Deck.

The library is a mergerfs union: local storage first, then a READ-ONLY rclone mount of
the NAS. Anything not held locally is streamed, which needs the network and cannot be
written to -- PC games in particular will not run from the NAS branch.

Ticking a row copies it local (playable offline, writable). Unticking removes only the
LOCAL copy; the NAS copy is never touched, so nothing is ever lost.

Built for the Deck: 1280x800, large text, fully drivable from the pad.
"""
import gi, json, os, shutil, subprocess, threading, time

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib, Pango, GdkPixbuf

import steamgriddb                       # optional SteamGridDB cover art (no-op without a key)
import steam_shortcuts                    # native Steam shortcuts.vdf management (drop-SRM)
import steam_recent                       # stamp LastPlayed so new games hit the Recent shelf
import nas_setup                          # in-app SMB share setup (obscured rclone remote)

HOME = os.path.expanduser("~")
# Where this AppImage's bundled scripts live. Loadout is a container: helper scripts
# (deck-saves.sh, mount-setup.sh, fix_collections.py, …) run from INSIDE the AppImage
# payload, never from a copy in ~. AppRun exports $LOADOUT_APP; fall back to this file's
# own directory for a plain `python3 loadout.py` checkout run.
APP_DIR = os.environ.get("LOADOUT_APP") or os.path.dirname(os.path.abspath(__file__))


def _padlog(msg):
    """Debug trace for input handling; no-op unless $LOADOUT_PAD_DEBUG is set."""
    if not os.environ.get("LOADOUT_PAD_DEBUG"):
        return
    try:
        with open(os.path.expanduser("~/loadout-pad.log"), "a") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def _mount_responsive(path, timeout=4):
    """True if `path` can be listed within `timeout` seconds. A wedged rclone/FUSE mount makes
    os.listdir() HANG (blocked in the FUSE wait), and — crucially — a process stuck in that wait
    is UNINTERRUPTIBLE, so it can't even be killed (a subprocess with a timeout blocks too). The
    only safe move is to ABANDON the probe: run it in a daemon thread and, if it hasn't answered
    within `timeout`, give up and call the mount dead. The stuck thread leaks (harmless — it holds
    only a released-GIL syscall and dies with the process), but the GUI thread is never blocked."""
    import threading
    ok = []

    def probe():
        try:
            os.listdir(path)
            ok.append(True)
        except Exception:
            ok.append(False)

    t = threading.Thread(target=probe, daemon=True)
    t.start()
    t.join(timeout)
    return bool(ok) and ok[0]      # timed-out (thread still stuck) -> ok is empty -> False

# --- configuration -------------------------------------------------------------
# Everything the manager touches is a path, and every path is overridable. Defaults
# match a standard EmuDeck + rclone-union layout; drop a JSON at the config path (or set
# $LOADOUT_CONFIG) to point it at a different setup. Nothing else is hardcoded.
_DEFAULTS = {
    "rom_local":   "~/Emulation/roms-local",   # writable INTERNAL ROM branch of the union
    "rom_sd":      "",                          # SD-card ROM branch: "" = auto-detect the
                                                #   Deck SD, an explicit path forces it,
                                                #   "off" disables (internal + NAS only)
    "rom_nas":     "~/.cache/nas-roms",         # read-only NAS branch (rclone mount)
    "rom_rclone_remote": "",                    # rclone "remote:path" for the NAS tier, set by
                                                #   the in-app SMB setup; "" = no NAS (local-only),
                                                #   "off" also disables. Secrets live in
                                                #   rclone.conf, never here.
    "rom_union":   "~/Emulation/roms",          # the mergerfs union ES-DE/SRM read
    "default_target": "sd",                     # initial per-game disk when an SD exists
                                                #   ("sd" or "internal"); overridable per game
    "recent_on_add": True,                      # stamp newly-added games as just-played so they
                                                #   appear on the Deck's home "Recent games" shelf
    "pc_local":    "~/Games-local",
    "pc_nas":      "~/.cache/nas-pc",
    "pc_union":    "~/Games",
    "pc_manifest": "~/Games/.manifest.json",
    "srm_appimage": "~/Emulation/tools/Steam-ROM-Manager.AppImage",
    "saves_script": "~/deck-saves.sh",
}
# Values expanduser'd on load; these two are plain strings (a mode / a path-or-sentinel),
# so leave them raw and let the resolvers below interpret them.
_RAW_KEYS = ("default_target", "rom_sd", "rom_rclone_remote", "recent_on_add")
CONFIG_PATH = os.path.expanduser(
    os.environ.get("LOADOUT_CONFIG", "~/.config/loadout/config.json"))


def _load_config():
    cfg = dict(_DEFAULTS)
    try:
        with open(CONFIG_PATH) as f:
            cfg.update({k: v for k, v in json.load(f).items() if k in _DEFAULTS})
    except Exception:
        pass
    return {k: (v if k in _RAW_KEYS else os.path.expanduser(v)) for k, v in cfg.items()}


def save_config_value(key, value):
    """Persist a single config key to config.json, preserving every other key already there
    (atomic replace). Only non-secret values are ever written here — credentials go to
    rclone.conf, never to config.json."""
    data = {}
    try:
        with open(CONFIG_PATH) as f:
            data = json.load(f)
    except Exception:
        pass
    data[key] = value
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, CONFIG_PATH)


def _detect_sd():
    """Best-effort Deck SD-card ROM dir: the first removable mount that already holds an
    Emulation/roms(-local) tree. Returns "" when nothing looks like one -- the SD is
    optional, so no match just means a two-tier (internal + NAS) library."""
    import glob
    for pat in ("/run/media/deck/*", "/run/media/*/*", "/run/media/*"):
        for m in sorted(glob.glob(pat)):
            if not os.path.isdir(m):
                continue
            for sub in ("Emulation/roms-local", "Emulation/roms"):
                cand = os.path.join(m, sub)
                if os.path.isdir(cand):
                    return cand
    return ""


def _resolve_sd(raw):
    """Config value -> the SD ROM branch to use, or "" for none.

    ""/unset -> auto-detect; off/none/disabled -> disabled; else the given path. In every
    case the branch is only used when it is a real directory, so a configured-but-unmounted
    SD (card pulled out) degrades cleanly to internal-only."""
    v = (raw or "").strip()
    if v.lower() in ("off", "none", "disabled"):
        return ""
    path = os.path.expanduser(v) if v else _detect_sd()
    return path if path and os.path.isdir(path) else ""


_C = _load_config()
ROM_LOCAL = _C["rom_local"]                             # internal branch (always present)
ROM_SD = _resolve_sd(_C["rom_sd"])                      # "" when there is no usable SD
ROM_NAS = _C["rom_nas"]
# Every writable local branch, SD first: SD is the natural home for bulky copies and the
# branch a shared file is reported from. With no SD this is just [internal] and every path
# below reduces to the original two-tier behaviour.
ROM_LOCALS = [b for b in (ROM_SD, ROM_LOCAL) if b]
HAVE_SD = bool(ROM_SD)                                  # is there a per-game disk choice at all?
DISK_LABEL = {ROM_LOCAL: "Internal"}
if ROM_SD:
    DISK_LABEL[ROM_SD] = "SD"
# Sticky initial per-game destination; collapses to internal when there is no SD.
DEFAULT_DEST = "sd" if (ROM_SD and str(_C["default_target"]).strip().lower() != "internal") \
    else "internal"
PC_LOCAL = _C["pc_local"]
PC_NAS = _C["pc_nas"]
PC_MANIFEST = _C["pc_manifest"]
SF_DIR = os.path.join(ROM_LOCAL, ".steam-shortcuts")   # deck-writable Steam pick set
ROM_UNION = _C["rom_union"]
ROM_TARGET = ROM_SD if DEFAULT_DEST == "sd" else ROM_LOCAL   # filesystem the disk gauge tracks
COVERS_ON = steamgriddb.enabled()                           # show game cover art (needs a key)
COVER_W, COVER_H = 46, 69                                    # in-list thumbnail size (2:3)
RECENT_ON = bool(_C["recent_on_add"])                       # surface new games on the Recent shelf
# Probe the NAS mount ONCE. A wedged rclone/FUSE mount hangs EVERY access (listdir/stat/walk) in an
# uninterruptible wait, so if it's unresponsive we treat the NAS as absent for the whole session and
# never touch it again — Loadout still runs on local games (rebuild the union or relaunch once the
# NAS is back). One probe => at most one leaked probe thread; every NAS access below checks NAS_OK.
NAS_OK = _mount_responsive(ROM_NAS)


def dest_dir(dest):
    """The branch dir a per-game destination choice ("sd"/"internal") maps to."""
    return ROM_SD if (dest == "sd" and ROM_SD) else ROM_LOCAL


def rom_local_path(system, fn=""):
    """The branch path actually holding system[/fn] (SD first), or None if not local."""
    for b in ROM_LOCALS:
        p = os.path.join(b, system, fn) if fn else os.path.join(b, system)
        if os.path.exists(p):
            return p
    return None


def pull_dest_dir(r):
    """The branch dir a pull of row `r` copies into: its chosen disk (PC is internal-only)."""
    if getattr(r, "kind", None) == "pc":
        return PC_LOCAL
    return dest_dir(getattr(r, "dest", DEFAULT_DEST))
_STEAM_EXT = (".m3u", ".cue", ".gdi", ".chd", ".iso", ".nkit.iso", ".rvz", ".gcm",
              ".wbfs", ".nsp", ".xci", ".cso", ".pbp", ".gb", ".gbc", ".gba", ".nds",
              ".z64", ".sfc", ".smc", ".nes", ".md", ".sms", ".gg", ".pce")


def steam_file(files):
    """The ONE file SRM should make a shortcut from: a playlist/cue if present (so a
    multi-disc game is one shortcut, not one per disc), else the single playable file."""
    low = {x: x.lower() for x in files}
    for ext in (".m3u", ".cue"):
        for x in files:
            if low[x].endswith(ext):
                return x
    play = [x for x in files if any(low[x].endswith(e) for e in _STEAM_EXT)]
    return sorted(play or files)[0]


def set_steam(system, sfile, on):
    """Add/remove a Steam pick by symlinking (or unlinking) its launch file."""
    d = os.path.join(SF_DIR, system)
    link = os.path.join(d, sfile)
    if on:
        os.makedirs(d, exist_ok=True)
        if not os.path.lexists(link):
            os.symlink(os.path.join(ROM_UNION, system, sfile), link)
    elif os.path.lexists(link):
        os.remove(link)


_ROM_EXT = (".iso", ".chd", ".zip", ".7z", ".nkit", ".wbfs", ".rvz", ".gcm", ".nsp", ".xci",
            ".cso", ".pbp", ".gb", ".gbc", ".gba", ".nds", ".z64", ".n64", ".v64", ".sfc",
            ".smc", ".nes", ".md", ".gen", ".sms", ".gg", ".pce", ".cue", ".m3u", ".gdi",
            ".wux", ".wud", ".rpx", ".dol", ".bin", ".img", ".wad", ".3ds", ".cia")


def _rom_appname(fn):
    """Display name for a rom launch file: strip up to two known extensions (handles .nkit.iso)."""
    n = fn
    for _ in range(2):
        base, ext = os.path.splitext(n)
        if ext.lower() in _ROM_EXT:
            n = base
        else:
            break
    return n.strip()


def sync_steam(dry_run=False):
    """Reconcile Steam ROM shortcuts with the enabled set (SF_DIR symlinks), natively — no SRM.

    Launch commands come from templates learned from the EXISTING shortcuts, so new shortcuts
    launch identically. Dedups by ROM PATH (never by name), so it can neither duplicate nor
    clobber an existing entry. Steam MUST be stopped for a real run. Returns (added, removed)
    counts; with dry_run, the (add_list, remove_list) for inspection. Backs up + round-trip-guards."""
    import re
    users = steam_shortcuts.steam_users()
    if not users:
        return ([], []) if dry_run else (0, 0)
    cfg = os.path.join(users[0], "config")
    vdf = os.path.join(cfg, "shortcuts.vdf")
    raw = open(vdf, "rb").read()
    root = steam_shortcuts.loads(raw)
    if steam_shortcuts.dumps(root) != raw:
        raise RuntimeError("shortcuts.vdf round-trip mismatch — refusing to sync")
    # built-in EmuDeck templates (so a fresh device works) overridden by the device's own
    # existing shortcuts (so a custom emulator/core setup is matched exactly)
    tmpls = steam_shortcuts.templates(root, HOME)
    ents = steam_shortcuts._entries(root)
    rompat = re.compile(r'"([^"]*\.steam-shortcuts/([^/]+)/[^"]*)"')
    existing = {}                          # rom_path -> index in ents
    for i, (_idx, e) in enumerate(ents):
        m = (rompat.search(str(steam_shortcuts._ci(e, "Exe")))
             or rompat.search(str(steam_shortcuts._ci(e, "LaunchOptions"))))
        if m:
            existing[m.group(1)] = i
    union_sf = os.path.join(ROM_UNION, ".steam-shortcuts")
    present = set()                        # rom-paths whose symlink EXISTS (still "shown in Steam")
    addable = {}                           # + whose target resolves -> can make a working shortcut
    if os.path.isdir(SF_DIR):
        for sysid in os.listdir(SF_DIR):
            sd = os.path.join(SF_DIR, sysid)
            if not os.path.isdir(sd):
                continue
            for fn in os.listdir(sd):
                if fn.startswith("."):
                    continue
                rom = os.path.join(union_sf, sysid, fn)
                present.add(rom)
                if os.path.exists(os.path.join(sd, fn)):     # symlink target resolves
                    addable[rom] = (sysid, _rom_appname(fn))
    add = [(rom, s, n) for rom, (s, n) in addable.items() if rom not in existing and s in tmpls]
    rem = [rom for rom in existing if rom not in present]     # only symlinks that are truly gone
    # also drop any stale offline-manager shortcut (Loadout's old name) that's lingering
    _stale = ("offline-manager", "offline manager")
    staleidx = {i for i in range(len(ents))
                if str(steam_shortcuts._ci(ents[i][1], "AppName")).strip().lower() in _stale}
    if dry_run:
        return add, rem
    if not add and not rem and not staleidx:
        return 0, 0
    drop = {existing[rom] for rom in rem} | staleidx
    kept = [ents[i] for i in range(len(ents)) if i not in drop]
    grid = os.path.join(cfg, "grid")
    added_aids = []
    for rom, sysid, appname in add:
        aid, pairs = steam_shortcuts.game_entry(appname, tmpls[sysid], rom)
        kept.append(("", pairs))
        added_aids.append(aid)
        cov = steamgriddb.cover(appname)
        if cov:
            steam_shortcuts.place_art(grid, aid, portrait=cov)
    kept = [(str(i), e) for i, (_k, e) in enumerate(kept)]
    for k in range(len(root)):
        if root[k][0].lower() == "shortcuts":
            root[k] = (root[k][0], kept)
            break
    shutil.copy2(vdf, vdf + ".loadout-bak")
    tmp = vdf + ".tmp"
    with open(tmp, "wb") as f:
        f.write(steam_shortcuts.dumps(root))
    os.replace(tmp, vdf)
    # stamp just-added games as recently played so they surface on the Deck's home shelf. Steam is
    # stopped here (this runs inside the refresh), which is exactly when localconfig.vdf is writable.
    if RECENT_ON and added_aids:
        try:
            steam_recent.stamp_recent(added_aids, home=HOME)
        except Exception:
            pass
    return len(add), len(rem) + len(staleidx)


QUEUE = os.path.join(HOME, ".loadout-queue.json")
PROGRESS = os.path.join(HOME, ".loadout-progress.json")
PC_UNION = _C["pc_union"]
SRM = _C["srm_appimage"]
SAVES_SCRIPT = os.path.join(APP_DIR, "deck-saves.sh")   # bundled in the AppImage, not ~
SKIP = ("media", "metadata.txt", "systeminfo.txt")

CSS = b"""
window { background: #1a1d23; }
* { font-size: 16pt; color: #e8eaed; }
treeview { background: #22262e; -GtkTreeView-vertical-separator: 12; }
treeview:selected { background: #3b82f6; color: #ffffff; }
button { padding: 12px 22px; border-radius: 8px; font-weight: bold; }
list.nav { background: #16191f; padding: 6px; }
list.nav row { padding: 9px 6px; border-radius: 8px; }
list.nav row:selected { background: #3b82f6; }
/* dim the selected section while the content pane has focus; brighten it (accent bar)
   while the sidebar itself is the active pane, so it's obvious which the D-pad drives. */
list.nav:not(.focused) row:selected { background: #33507f; }
list.nav.focused { background: #1b2230; }
list.nav.focused row:selected { background: #3b82f6; border-left: 3px solid #fbbf24; }
.navhdr { font-size: 11pt; font-weight: bold; color: #6b7280; padding: 14px 6px 4px 6px; }
.navitem { font-size: 15pt; }
.hint { font-size: 13pt; color: #9aa0a6; }
.big { font-size: 20pt; font-weight: bold; }
.confirm { font-size: 19pt; font-weight: bold; color: #0b0d10; background: #fbbf24;
           padding: 16px; border-radius: 10px; }
.error   { font-size: 18pt; font-weight: bold; color: #ffffff; background: #b91c1c;
           padding: 14px; border-radius: 10px; }
"""


def du(path):
    t = 0
    for r, _, fs in os.walk(path):
        for f in fs:
            try:
                t += os.path.getsize(os.path.join(r, f))
            except OSError:
                pass
    return t


def human(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return "%d %s" % (n, u) if u in ("B", "KB") else "%.1f %s" % (n, u)
        n /= 1024.0
    return "%.1f PB" % n


def _statvfs_of(path):
    """statvfs of the filesystem holding `path`, walking up to the nearest existing parent
    (a copy target dir may not exist yet)."""
    p = path
    while p and not os.path.exists(p):
        p = os.path.dirname(p)
    return os.statvfs(p or "/")


def free_on(path):
    st = _statvfs_of(path)
    return st.f_bavail * st.f_frsize


def free_bytes():
    # The disk gauge tracks the default copy-target filesystem (SD when present, else
    # internal). A single Apply spanning both disks makes the gauge an estimate; the hard
    # space check in on_apply is per-destination-filesystem and exact.
    return free_on(ROM_TARGET)


def total_bytes():
    st = _statvfs_of(ROM_TARGET)
    return st.f_blocks * st.f_frsize


class Gamepad(threading.Thread):
    """Read the controller straight from evdev.

    Steam Input sends XInput events to non-Steam apps, not keystrokes, so a GTK window
    receives nothing from the pad. Reading the device ourselves works no matter which
    Steam Input layout happens to be applied.
    """
    NAMES = ("x-box", "xbox", "steam controller", "steam deck", "gamepad", "controller")

    def __init__(self, app):
        super().__init__(daemon=True)
        self.app = app
        self.devs = []
        self.axis_dir = {}          # axis code -> current committed direction (-1/0/1)
        self.axis_at = {}           # axis code -> last time it fired (for auto-repeat)
        self._dbg = bool(os.environ.get("LOADOUT_PAD_DEBUG"))

    def _log(self, msg):
        if not self._dbg:
            return
        try:
            with open(os.path.expanduser("~/loadout-pad.log"), "a") as f:
                f.write(msg + "\n")
        except Exception:
            pass

    def _axis(self, e, code, value, now):
        """Map a D-pad hat OR an analog stick axis to a nav move. On the Deck, Game Mode can feed
        navigation as the *left stick* (ABS_X/ABS_Y), not the hat, so both must drive the same moves.
        Vertical axes scroll the list/sidebar; horizontal axes move focus between the panes. Hats are
        digital (-1/0/1); sticks ramp and rest off-centre, so use hysteresis (commit past HI, release
        below LO) plus auto-repeat while held."""
        VERT = (e.ABS_HAT0Y, e.ABS_Y, e.ABS_RY)
        HORIZ = (e.ABS_HAT0X, e.ABS_X, e.ABS_RX)
        if code not in VERT and code not in HORIZ:
            return
        digital = code in (e.ABS_HAT0X, e.ABS_HAT0Y)
        hi, lo = (1, 1) if digital else (12000, 5000)
        if value >= hi:
            d = 1
        elif value <= -hi:
            d = -1
        elif abs(value) <= lo:
            d = 0
        else:
            d = self.axis_dir.get(code, 0)          # inside the hysteresis band: hold prior state
        if d == 0:
            self.axis_dir[code] = 0
            return
        prev = self.axis_dir.get(code, 0)
        if d != prev or (now - self.axis_at.get(code, 0) > 0.25):   # fresh commit or auto-repeat
            self.axis_at[code] = now
            if code in VERT:
                GLib.idle_add(self.app.pad_move, d)                 # move within the active list
            else:
                pane = "content" if d > 0 else "sidebar"           # right=games, left=console list
                if self._dbg:
                    self._log("FIRE code=%d d=%d -> pane %s" % (code, d, pane))
                GLib.idle_add(self.app.set_pane, pane)
        self.axis_dir[code] = d

    def find(self):
        """Every gamepad-capable evdev device (a south/A face button plus an analog or hat axis).
        Deliberately NOT filtered by name: in Game Mode the controller Loadout must read is Steam's
        *virtual* pad (e.g. 'Microsoft X-Box 360 pad'), which the old name list could miss, and the
        physical 'Steam Deck' device is exclusively grabbed by Steam and never delivers events."""
        try:
            import evdev
        except Exception:
            return []
        e = evdev.ecodes
        found = []
        for path in evdev.list_devices():
            try:
                d = evdev.InputDevice(path)
                keys = d.capabilities(verbose=False).get(e.EV_KEY, [])   # plain int codes
            except Exception:
                continue
            # a gamepad is anything exposing the south/A face button. On the Deck only the pad
            # (Steam's virtual 'Microsoft X-Box 360 pad') has it -- the keyboard and the raw Steam
            # Controller endpoints don't -- so this is a clean, name-independent test. We do NOT
            # require an analog axis: Steam's virtual pad can report its axes a beat after it appears.
            if e.BTN_SOUTH in keys or e.BTN_A in keys:
                found.append(d)
            else:
                try:
                    d.close()
                except Exception:
                    pass
        return found

    def run(self):
        try:
            import evdev, selectors
        except Exception:
            GLib.idle_add(self.app.set_pad_status, "gamepad: evdev unavailable")
            return
        e = evdev.ecodes
        # xpad maps X to BTN_NORTH(307) and Y to BTN_WEST(308). Start toggles the highlighted game's
        # copy disk (SD/Internal) -- safe to bind because it only stages a choice; nothing copies or
        # deletes until Apply (Y) is confirmed. Apply itself stays on Y so it's never one stray press.
        BTN = {e.BTN_SOUTH: "a", e.BTN_EAST: "b", e.BTN_NORTH: "x", e.BTN_WEST: "y",
               e.BTN_TL: "l1", e.BTN_TR: "r1", e.BTN_SELECT: "select", e.BTN_START: "start"}
        # some controllers report the D-pad as buttons rather than the ABS_HAT0 axes; handle both.
        DPAD = {}
        for code, act in (("BTN_DPAD_UP", ("move", -1)), ("BTN_DPAD_DOWN", ("move", 1)),
                          ("BTN_DPAD_LEFT", ("pane", "sidebar")), ("BTN_DPAD_RIGHT", ("pane", "content"))):
            if hasattr(e, code):
                DPAD[getattr(e, code)] = act
        sel = selectors.DefaultSelector()
        fds = {}                       # path -> registered InputDevice
        last_scan, announced = 0.0, None
        self._log("=== gamepad run start ===")
        total, last_hb = 0, 0.0
        while True:
            now = time.time()
            if self._dbg and now - last_hb > 5.0:
                last_hb = now
                self._log("alive fds=%d total_events=%d" % (len(fds), total))
            # (Re)scan for controllers rather than enumerating once: in Game Mode Steam creates its
            # virtual pad AFTER we launch, and controllers hotplug, so keep looking until one arrives.
            if now - last_scan > 2.0:
                last_scan = now
                for d in self.find():
                    if d.path in fds:
                        try:
                            d.close()
                        except Exception:
                            pass
                    else:
                        try:
                            sel.register(d, selectors.EVENT_READ)
                            fds[d.path] = d
                            self._log("registered %s (%s)" % (d.name, d.path))
                        except Exception as ex:
                            self._log("register FAIL %s: %s" % (d.path, ex))
                            try:
                                d.close()
                            except Exception:
                                pass
                status = ("gamepad: " + ", ".join(sorted(x.name for x in fds.values()))
                          if fds else "gamepad: waiting for controller…")
                if status != announced:
                    announced = status
                    GLib.idle_add(self.app.set_pad_status, status)
            # The Deck's virtual pad streams stick/gyro samples continuously (hundreds/sec). Reading
            # that in a tight non-blocking loop pins this thread and starves the GTK main thread of
            # the GIL, so the idle_add nav callbacks NEVER run — the controls look dead. A short
            # sleep each cycle yields the GIL (time.sleep releases it) while staying responsive.
            time.sleep(0.008)
            for key, _ in sel.select(timeout=1):
                d = key.fileobj
                try:
                    events = list(d.read())
                except OSError:            # device went away (unplugged / Steam took it)
                    try:
                        sel.unregister(d)
                    except Exception:
                        pass
                    fds.pop(getattr(d, "path", None), None)
                    continue
                for ev in events:
                    total += 1
                    if ev.type == e.EV_KEY and ev.value == 1:
                        if self._dbg:
                            self._log("KEY code=%d (%s)" % (ev.code, BTN.get(ev.code, DPAD.get(ev.code, "?"))))
                        if ev.code in BTN:
                            GLib.idle_add(self.app.pad_action, BTN[ev.code])
                        elif ev.code in DPAD:
                            kind, arg = DPAD[ev.code]
                            if kind == "move":
                                GLib.idle_add(self.app.pad_move, arg)
                            else:
                                GLib.idle_add(self.app.set_pane, arg)
                    elif ev.type == e.EV_ABS:
                        if self._dbg and (ev.code in (e.ABS_HAT0X, e.ABS_HAT0Y) or abs(ev.value) > 6000):
                            self._log("ABS code=%d val=%d" % (ev.code, ev.value))
                        self._axis(e, ev.code, ev.value, now)


SCAFFOLD = ("media", "gamelist.xml", "metadata.txt", "systeminfo.txt", "desktop.txt")
# ES-DE ships non-ROM system dirs; never list these as manageable systems
NONGAME = ("desktop", "emulators", "tools", "ps4", "custom-collections")


def is_update_dlc(system):
    """Updates and DLC are never managed on their own: a game update / add-on is only
    useful with its base game, so it should live wherever that game lives (offline or on
    the NAS), not be independently toggled. Any '*-updates' / '*-dlc' system is hidden."""
    n = system.lower()
    return "update" in n or "dlc" in n


def system_stats(system):
    """(size, is_local, n_files) for a cartridge system, counting only ROM content.

    Every union branch is scanned; a file counts as local when it is present in any local
    branch (internal or SD). media/gamelist scaffolding is ignored so an ES-DE stub dir
    does not read as a pulled system."""
    info = {}
    bases = [(os.path.join(ROM_NAS, system), False)] if NAS_OK else []
    bases += [(os.path.join(b, system), True) for b in ROM_LOCALS]
    for base, isloc in bases:
        if not os.path.isdir(base):
            continue
        for r, ds, fs in os.walk(base):
            if "media" in os.path.relpath(r, base).split(os.sep):
                continue                       # skip the media subtree
            for fn in fs:
                if fn in SCAFFOLD or fn.startswith("."):
                    continue
                rel = os.path.relpath(os.path.join(r, fn), base)
                try:
                    sz = os.path.getsize(os.path.join(r, fn))
                except OSError:
                    sz = 0
                d = info.setdefault(rel, {"size": 0, "local": False})
                d["size"] = max(d["size"], sz)
                if isloc:
                    d["local"] = True
    if not info:
        return 0, False, 0
    total = sum(d["size"] for d in info.values())
    all_local = all(d["local"] for d in info.values())
    return total, all_local, len(info)


class Row:
    def __init__(self, kind, name):
        self.kind = kind                       # "pc" or "roms"
        self.name = name
        self.dest = DEFAULT_DEST               # chosen destination for a pull
        if kind == "roms":
            self.nas_path = os.path.join(ROM_NAS, name)
            # a cartridge collection can span internal + SD; track every branch dir that
            # holds it so a free clears them all, and label the disk it currently lives on.
            holding = [b for b in ROM_LOCALS if os.path.isdir(os.path.join(b, name))]
            self.local_dirs = [os.path.join(b, name) for b in holding]
            self.local_path = self.local_dirs[0] if self.local_dirs \
                else os.path.join(dest_dir(self.dest), name)
            self.disk = DISK_LABEL.get(holding[0], "") if holding else ""
            self.size, self.is_local, self.n_files = system_stats(name)
            # a whole-console collection: name it properly and say how many games it holds
            self.label = "%s  —  %s games" % (
                CART_NAME.get(name, name.replace("-", " ").title()), format(self.n_files, ","))
        else:
            self.dest = "internal"             # PC games stay on internal storage
            self.local_path = os.path.join(PC_LOCAL, name)
            self.nas_path = os.path.join(PC_NAS, name)
            self.is_local = os.path.exists(self.local_path)
            self.local_dirs = [self.local_path] if self.is_local else []
            self.disk = "Internal" if self.is_local else ""
            src = self.local_path if self.is_local else self.nas_path
            self.size = du(src) if os.path.isdir(src) else (
                os.path.getsize(src) if os.path.exists(src) else 0)
            self.n_files = 1
            self.label = name
            # a PC game "shows in Steam" when its generated launcher exists
            if kind == "pc":
                self.is_steam = os.path.exists(os.path.join(PC_LOCAL, name + ".sh"))


import re as _re

# Consoles with big per-file games -- worth choosing individually. Everything else is a
# cartridge system with thousands of tiny ROMs, kept as a single all-or-nothing row.
LARGE = ("gc", "wii", "wiiu", "switch", "ps2", "psp", "psx", "saturn",
         "dreamcast", "xbox", "segacd", "n3ds", "ps3", "ps4")
# Consoles whose games are a DIRECTORY (a decrypted PS3 disc folder, a PS4 pkg set),
# not one file -- enumerated dir-by-dir instead of file-by-file.
FOLDER_CONSOLES = ("ps3", "ps4", "psvita", "xbox360")
SYS_SHORT = {"gc": "GC", "wii": "Wii", "wiiu": "WiiU", "switch": "Switch",
             "ps2": "PS2", "psp": "PSP", "psx": "PS1",
             "saturn": "Saturn", "dreamcast": "DC", "xbox": "Xbox", "segacd": "SegaCD",
             "n3ds": "3DS"}
TAB_NAME = {"gc": "GameCube", "wii": "Wii", "wiiu": "Wii U", "switch": "Switch",
            "psx": "PS1", "ps2": "PS2", "psp": "PSP",
            "saturn": "Saturn", "dreamcast": "Dreamcast", "xbox": "Xbox", "n3ds": "3DS",
            "segacd": "Sega CD", "ps3": "PS3", "ps4": "PS4"}
# Friendly names for the whole-console ROM collections shown on the Collections tab.
CART_NAME = {"snes": "Super Nintendo", "nes": "NES", "n64": "Nintendo 64",
             "gb": "Game Boy", "gbc": "Game Boy Color", "gba": "Game Boy Advance",
             "nds": "Nintendo DS", "genesis": "Sega Genesis", "megadrive": "Mega Drive",
             "mastersystem": "Master System", "gamegear": "Game Gear", "sega32x": "Sega 32X",
             "tg16": "TurboGrafx-16", "pcengine": "PC Engine", "arcade": "Arcade",
             "neogeo": "Neo Geo", "atari2600": "Atari 2600", "wonderswan": "WonderSwan",
             "famicom": "Famicom", "sfc": "Super Famicom", "virtualboy": "Virtual Boy",
             "pokemini": "Pokémon Mini", "ngp": "Neo Geo Pocket", "vectrex": "Vectrex"}
TAB_ORDER = ["gc", "wii", "wiiu", "switch", "n3ds",
             "psx", "ps2", "psp", "ps3", "ps4", "saturn", "dreamcast", "segacd", "xbox"]
_DISC = _re.compile(r"\s*\((?:Disc|CD|Track)\s*\d+\)", _re.I)


def game_key(fn):
    """Group a game's files: 'FF VII (Disc 1).chd' and '(Disc 2).chd' are one game,
    as are 'Game.cue' + 'Game (Track 1).bin'."""
    return _DISC.sub("", __import__("os").path.splitext(fn)[0]).strip()


class GameRow:
    """one individual title within a large console (may be several files)"""
    def __init__(self, system, game, files, size, locs):
        self.kind = "game"
        self.system = system
        self.game = game
        self.name = game
        # folder-console games carry a .ps3/.ps4 marker in the dir name -- hide it in the UI
        self.label = _re.sub(r"\.(ps3|ps4|psvita)$", "", game, flags=_re.I)
        self.files = files                     # filenames within the system dir
        self.size = size
        # {filename: the local branch dir that actually holds it, or None}. The game is
        # local only when every one of its files is present in some local branch.
        self.local_files = dict(locs)
        self.is_local = bool(files) and all(self.local_files.get(fn) for fn in files)
        # the disk this game lives on (SD/Internal label), or "" when not local
        self.disk = DISK_LABEL.get(self.local_files.get(files[0]) if files else None, "")
        self.dest = DEFAULT_DEST               # chosen destination for a pull (user-overridable)
        # the system dir on some branch (its actual home if local, else the pull target); the
        # live copy/free paths come from local_files / pull_dest_dir, this is a sane fallback.
        self.local_path = rom_local_path(system) or os.path.join(dest_dir(self.dest), system)
        self.sfile = steam_file(files)
        self.is_steam = os.path.lexists(os.path.join(SF_DIR, system, self.sfile))


def _local_bases(system):
    """(base_dir, holding_branch_or_None) for the NAS branch (only when it's alive) then every
    local branch. A dead NAS mount is omitted so nothing walks/stat's a wedged FUSE path."""
    nas = [(os.path.join(ROM_NAS, system), None)] if NAS_OK else []
    return nas + [(os.path.join(b, system), b) for b in ROM_LOCALS]


def enumerate_folder_games(system):
    """PS3/PS4 etc.: each PLAYABLE game is a directory named `<title>.<system>` (a decrypted
    PS3 disc folder / an extracted PS4 game). Raw pkg/rar source dirs left in the console
    folder are NOT playable and are skipped -- you only see the finished game."""
    ext = "." + system                     # .ps3 / .ps4 / .psvita
    info = {}
    for base, loc in _local_bases(system):
        if not os.path.isdir(base):
            continue
        for dn in os.listdir(base):
            if dn.startswith(".") or dn in SKIP:
                continue
            p = os.path.join(base, dn)
            if not os.path.isdir(p) or not dn.lower().endswith(ext):
                continue                   # skip pkg/rar source dirs -- only extracted games
            d = info.setdefault(dn, {"size": 0, "loc": None})
            d["size"] = max(d["size"], du(p))
            if loc and d["loc"] is None:
                d["loc"] = loc             # SD scanned first, so SD wins when on both
    return [GameRow(system, dn, [dn], d["size"], {dn: d["loc"]})
            for dn, d in sorted(info.items())]


def enumerate_games(system):
    if system in FOLDER_CONSOLES:
        return enumerate_folder_games(system)
    info = {}
    for base, loc in _local_bases(system):
        if not os.path.isdir(base):
            continue
        for fn in os.listdir(base):
            if fn.startswith(".") or fn in SKIP:
                continue
            p = os.path.join(base, fn)
            if not os.path.isfile(p):
                continue
            try:
                sz = os.path.getsize(p)
            except OSError:
                sz = 0
            d = info.setdefault(fn, {"size": 0, "loc": None})
            d["size"] = max(d["size"], sz)
            if loc and d["loc"] is None:
                d["loc"] = loc
    groups = {}
    for fn, d in info.items():
        g = groups.setdefault(game_key(fn), {"files": [], "size": 0, "locs": {}})
        g["files"].append(fn)
        g["size"] += d["size"]
        g["locs"][fn] = d["loc"]
    rows = []
    for game, g in sorted(groups.items()):
        rows.append(GameRow(system, game, g["files"], g["size"], g["locs"]))
    return rows


def sweep_partials():
    """Remove *.part left over from a job that is no longer queued.

    While a job IS queued the partials are resume data and must be kept -- the worker
    skips files it has already transferred. Only orphans from an abandoned job are
    swept, and the NAS copy is untouched either way."""
    if os.path.exists(QUEUE):
        return 0          # a job is pending; its .part files are resume data, not junk
    freed = 0
    for base in (PC_LOCAL, *ROM_LOCALS):
        if not os.path.isdir(base):
            continue
        for n in os.listdir(base):
            if not n.endswith(".part"):
                continue
            p = os.path.join(base, n)
            try:
                freed += du(p) if os.path.isdir(p) else os.path.getsize(p)
                shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
            except Exception:
                pass
    return freed


def scan():
    pc, roms = [], []
    manifest = {}
    try:
        manifest = json.load(open(PC_MANIFEST))
    except Exception:
        pass
    # Only PLAYABLE games belong on the PC tab. An installer -- a FitGirl / setup.exe
    # repack that has not been installed yet (kind "wizard") -- is NOT playable, and
    # neither is a raw scene release or anything unrecognised. You can only tick something
    # you can actually run, so those are all hidden until they become a real installed game.
    PLAYABLE = {"linux", "portable", "windows", "installed"}
    playable = {k for k, v in manifest.items()
                if isinstance(v, dict) and v.get("kind") in PLAYABLE}
    seen = set()
    pc_bases = (PC_NAS, PC_LOCAL) if _mount_responsive(PC_NAS) else (PC_LOCAL,)
    for base in pc_bases:
        if not os.path.isdir(base):
            continue
        try:
            pc_names = sorted(os.listdir(base))
        except OSError:
            continue          # a dropped mount must never crash the launch
        for n in pc_names:
            if n.startswith(".") or n in SKIP or n in seen:
                continue
            if not os.path.isdir(os.path.join(base, n)):
                continue
            if n not in playable:            # installers / raw releases / unknown -> hidden
                continue
            seen.add(n)
            pc.append(Row("pc", n))
    sseen, games = set(), []
    # only include the (networked) NAS branch if it responds; a wedged rclone mount would otherwise
    # HANG os.listdir and freeze the whole launch. Local branches are always scanned.
    rom_bases = (ROM_NAS, *ROM_LOCALS) if NAS_OK else tuple(ROM_LOCALS)
    for base in rom_bases:
        if not os.path.isdir(base):
            continue
        try:
            names = sorted(os.listdir(base))
        except OSError:
            continue          # a dropped rclone / stale mount must never crash the launch
        for name in names:
            p = os.path.join(base, name)
            # "_"-prefixed dirs are the ROM sorter's non-console buckets (e.g. _unsorted --
            # a catch-all for ROMs it couldn't file); never manage those as a system.
            if name.startswith((".", "_")) or name in sseen or not os.path.isdir(p):
                continue
            try:
                has_content = any(f for f in os.listdir(p) if not f.startswith(".") and f not in SKIP)
            except OSError:
                continue
            if not has_content:
                continue
            sseen.add(name)
            if is_update_dlc(name):
                continue                               # updates/DLC follow their base game
            if name in LARGE:
                games.extend(enumerate_games(name))    # individual titles
            else:
                if name in NONGAME:
                    continue
                row = Row("roms", name)
                if row.n_files and row.size > 1024:     # skip empty / pure-scaffolding
                    roms.append(row)
    by_system = {}
    for g in games:
        by_system.setdefault(g.system, []).append(g)
    for lst in by_system.values():
        lst.sort(key=lambda r: r.name.lower())
    return pc, roms, by_system


def copy_with_progress(src, dst, report):
    """shutil.copytree is a single blocking call with no callback, so a multi-GB game
    looks frozen. Walk the tree and copy file by file so progress is visible."""
    files, total = [], 0
    for r, _, fs in os.walk(src):
        for f in fs:
            fp = os.path.join(r, f)
            try:
                sz = os.path.getsize(fp)
            except OSError:
                sz = 0
            files.append((fp, sz))
            total += sz
    done, last = 0, 0.0
    os.makedirs(dst, exist_ok=True)
    for fp, sz in files:
        rel = os.path.relpath(fp, src)
        out = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        shutil.copy2(fp, out)
        done += sz
        now = time.time()
        if now - last > 0.25:                 # throttle: do not flood the UI
            last = now
            report(done, total, rel)
    report(done, total, "")
    return total


def write_launchers(desired=None):
    """One launcher per PC game that should be on the Deck.

    SRM globs this directory, so writing/removing a launcher is what adds or removes the
    Steam shortcut. Games needing a manual install are skipped -- no shortcut is created
    for something that cannot start.

    `desired` is the set of games that will be local once the queued copies finish. A
    PC game cannot run from the read-only NAS branch, so only those get a shortcut --
    and they get it immediately, so the Steam restart happens when you press Apply
    rather than unpredictably later when a copy completes.
    """
    try:
        games = json.load(open(PC_MANIFEST))
    except Exception:
        return 0, 0
    os.makedirs(PC_LOCAL, exist_ok=True)
    wanted, made = set(), 0
    for name, g in games.items():
        kind = g.get("kind")
        if kind not in ("linux", "portable", "windows", "installed") or not g.get("entry"):
            continue                       # installers/wizards get no shortcut
        if desired is not None and name not in desired:
            continue                       # not wanted on this Deck
        if desired is None and not os.path.exists(os.path.join(PC_LOCAL, name)):
            continue                       # only games actually present
        target = os.path.join(PC_UNION, name, g["entry"])
        out = os.path.join(PC_LOCAL, name + ".sh")
        wanted.add(os.path.basename(out))
        if kind in ("windows", "installed"):
            # a Windows game needs Proton, not a bare exec: run it through the Deck's
            # newest Proton in a per-game prefix.
            body = ('#!/bin/bash\n# generated by Loadout (Proton)\n'
                    'export STEAM_COMPAT_CLIENT_INSTALL_PATH="$HOME/.steam/steam"\n'
                    'export STEAM_COMPAT_DATA_PATH="$HOME/.proton-prefixes/%s"\n'
                    'mkdir -p "$STEAM_COMPAT_DATA_PATH"\n'
                    'P=$(ls -d "$HOME"/.steam/steam/steamapps/common/Proton*/proton 2>/dev/null | sort -V | tail -1)\n'
                    'cd %s || exit 1\nexec "$P" run %s "$@"\n'
                    % (name, repr(os.path.dirname(target)), repr(target)))
        else:
            body = ('#!/bin/bash\n# generated by Loadout\ncd %s || exit 1\nexec %s "$@"\n'
                    % (repr(os.path.dirname(target)), repr(target)))
        try:
            if not os.path.exists(out) or open(out).read() != body:
                open(out, "w").write(body)
                os.chmod(out, 0o755)
            made += 1
        except Exception:
            pass
    # drop launchers whose game is gone, so SRM removes the stale shortcut
    removed = 0
    for f in os.listdir(PC_LOCAL):
        if f.endswith(".sh") and f not in wanted:
            try:
                os.remove(os.path.join(PC_LOCAL, f)); removed += 1
            except Exception:
                pass
    return made, removed


def srm_add():
    """Add/remove Steam shortcuts. Safe with Steam running: only CATEGORY writes need
    Steam stopped, and those are handled by the full srm-refresh later."""
    if not os.path.exists(SRM):
        return "SRM not found"
    env = dict(os.environ)
    env.setdefault("DISPLAY", ":0")
    try:
        r = subprocess.run([SRM, "--no-sandbox", "add"], capture_output=True, text=True,
                           timeout=900, env=env)
        return "Steam shortcuts synced" if r.returncode == 0 else \
            "SRM failed (%s)" % (r.stderr or r.stdout or "")[-60:]
    except Exception as ex:
        return "SRM error: %s" % ex


class Page(Gtk.Box):
    """one tab: a checklist"""
    def __init__(self, app, empty_text, steam_col=False):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self.steam_col = steam_col
        # cols: offline(bool) steam(bool) name where size obj cover(pixbuf)
        self.store = Gtk.ListStore(bool, bool, str, str, str, object, GdkPixbuf.Pixbuf)
        self.view = Gtk.TreeView(model=self.store)
        self.view.set_activate_on_single_click(True)
        self.view.set_enable_search(False)
        self.view.connect("row-activated", self.on_activate)
        self._covers_done = False

        if COVERS_ON:                        # leftmost cover-art thumbnail
            pr = Gtk.CellRendererPixbuf()
            pr.set_property("xpad", 6)
            cov = Gtk.TreeViewColumn("", pr, pixbuf=6)
            cov.set_min_width(COVER_W + 14)
            self.view.append_column(cov)

        t = Gtk.CellRendererToggle()
        t.set_property("xpad", 14)
        t.connect("toggled", self.on_toggled)
        self.off_col = Gtk.TreeViewColumn("Offline", t, active=0)
        self.off_col.set_min_width(120)
        self.view.append_column(self.off_col)
        self.steam_toggle_col = None
        if steam_col:
            t2 = Gtk.CellRendererToggle()
            t2.set_property("xpad", 14)
            t2.connect("toggled", self.on_steam_toggled)
            self.steam_toggle_col = Gtk.TreeViewColumn("Steam", t2, active=1)
            self.steam_toggle_col.set_min_width(110)
            self.view.append_column(self.steam_toggle_col)
        for i, (title, expand, width) in enumerate(
                (("Name", True, 420), ("Where", False, 140), ("Size", False, 140)), start=2):
            r = Gtk.CellRendererText()
            r.set_property("ypad", 10)
            if i == 1:
                r.set_property("ellipsize", Pango.EllipsizeMode.END)
            c = Gtk.TreeViewColumn(title, r, text=i)
            c.set_expand(expand)
            c.set_min_width(width)
            self.view.append_column(c)

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.add(self.view)
        self.pack_start(sw, True, True, 0)
        self.empty = Gtk.Label(label=empty_text)
        self.empty.get_style_context().add_class("hint")
        self.pack_start(self.empty, False, False, 8)
        self.rows = []

    def _where(self, i):
        """The 'Where' cell: where this game is / is going, given its checkbox + chosen disk.

        With an SD present the destination of a queued pull is shown (→ SD / → Internal) so
        the per-game disk choice is visible; a two-tier library keeps the plain on-Deck/NAS
        wording."""
        r = self.rows[i]
        checked = self.store[i][0]
        pc = getattr(r, "kind", None) == "pc"
        if r.is_local:
            if not checked:
                return "free"                          # will be removed on Apply
            return (r.disk if HAVE_SD else "on Deck") or "on Deck"
        if not checked:
            return "NAS"
        if HAVE_SD and not pc:                          # a queued pull with a disk choice
            return "→ " + ("SD" if r.dest == "sd" else "Internal")
        return "→ Deck"

    def load(self, rows):
        self.rows = rows
        self.store.clear()
        for r in rows:
            self.store.append([r.is_local, getattr(r, "is_steam", False),
                               getattr(r, "label", r.name), "", human(r.size), r, None])
        for i in range(len(rows)):
            self.store[i][3] = self._where(i)
        self.empty.set_visible(not rows)
        self._covers_done = False
        if rows:
            self.view.set_cursor(0)

    def load_covers(self):
        """Lazily fetch SteamGridDB covers for this page's individual games, once. Runs on a
        background thread (network) and drops each cover into its row when it arrives."""
        if not COVERS_ON or self._covers_done or not self.rows:
            return
        self._covers_done = True
        snapshot = list(enumerate(self.rows))

        def work():
            for i, r in snapshot:
                if getattr(r, "kind", None) == "roms":
                    continue                    # cartridge collections have no single cover
                name = getattr(r, "label", None) or getattr(r, "name", "")
                path = steamgriddb.cover(name)
                if not path:
                    continue
                try:
                    pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, COVER_W, COVER_H, True)
                except Exception:
                    continue
                GLib.idle_add(self._set_cover, i, r, pb)
        threading.Thread(target=work, daemon=True).start()

    def _set_cover(self, i, r, pb):
        if i < len(self.rows) and self.rows[i] is r:     # row still where we left it
            self.store[i][6] = pb
        return False

    def on_toggled(self, _c, path):
        i = int(str(path))
        self.store[i][0] = not self.store[i][0]
        self.store[i][3] = self._where(i)
        self.app.update_totals()

    def on_steam_toggled(self, _c, path):
        self.store[path][1] = not self.store[path][1]

    def on_activate(self, _v, path, _c):
        self.toggle_at(path, 0)

    def toggle_at(self, path, col):
        col = col if (col == 0 or self.steam_col) else 0
        i = int(str(path))
        self.store[i][col] = not self.store[i][col]
        if col == 0:
            self.store[i][3] = self._where(i)
            self.app.update_totals()

    def toggle_current(self, col=0):
        sel = self.view.get_selection().get_selected()[1]
        if sel is not None:
            self.toggle_at(self.store.get_path(sel), col)

    def cycle_dest_current(self):
        """Flip the highlighted game's copy destination between SD and Internal.

        Only queued pulls of an SD-capable library can be steered -- PC games are
        internal-only, and a game already on the Deck keeps its disk (moving it between
        disks is a separate operation)."""
        if not HAVE_SD or self.view is None:
            return
        sel = self.view.get_selection().get_selected()[1]
        if sel is None:
            return
        i = int(str(self.store.get_path(sel)))
        r = self.rows[i]
        if getattr(r, "kind", None) == "pc" or r.is_local:
            return
        r.dest = "internal" if r.dest == "sd" else "sd"
        self.store[i][3] = self._where(i)

    def selected_bytes(self):
        return sum(r.size for i, r in enumerate(self.rows) if self.store[i][0])

    def pending(self):
        pulls, drops = [], []
        for i, r in enumerate(self.rows):
            if self.store[i][0] and not r.is_local:
                pulls.append(r)
            elif not self.store[i][0] and r.is_local:
                drops.append(r)
        return pulls, drops

    def steam_pending(self):
        """(add, remove) GameRows whose Steam checkbox differs from disk"""
        add, rem = [], []
        if not self.steam_col:
            return add, rem
        for i, r in enumerate(self.rows):
            want = self.store[i][1]
            if want and not r.is_steam:
                add.append(r)
            elif not want and r.is_steam:
                rem.append(r)
        return add, rem


class SavesPage(Gtk.Box):
    """Emulator saves on the NAS, filed under this Deck's Steam account.

    A background service (deck-saves-daemon) pushes saves up when a game exits and pulls
    them down when this Deck is idle and the NAS copy is newer, so a profile resumes on
    whichever Deck you pick up. These buttons are for forcing it, or for settling a
    conflict the daemon refused to guess at."""
    is_saves = True
    is_panel = True                     # a button panel (navigated like the Storage page)
    steam_col = False
    view = None

    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.app = app
        self.rows = []
        self.set_border_width(20)
        self.status = Gtk.Label(xalign=0)
        self.status.get_style_context().add_class("big")
        self.pack_start(self.status, False, False, 0)
        self.warn = Gtk.Label(xalign=0)
        self.warn.set_line_wrap(True)
        self.pack_start(self.warn, False, False, 0)
        self.btns, self.actions = [], ["backup", "restore"]
        for label in ("Back up now      this Deck  \u2192  NAS",
                      "Restore          NAS  \u2192  this Deck"):
            b = Gtk.Button(label=label)
            b.set_size_request(460, 62)
            self.btns.append(b)
            self.pack_start(b, False, False, 0)
        self.btns[0].connect("clicked", lambda *_: self.run("backup"))
        self.btns[1].connect("clicked", lambda *_: self.run("restore"))
        self.prog = Gtk.Label(xalign=0)
        self.prog.get_style_context().add_class("hint")
        self.pack_start(self.prog, False, False, 0)
        self.focus = 0
        self.busy = False
        self.refresh()

    # ---- App-compat no-ops: the App treats every tab the same ----
    def selected_bytes(self):
        return 0

    def pending(self):
        return [], []

    def steam_pending(self):
        return [], []

    def load(self, *_):
        pass

    # ---- gamepad ----
    def move_focus(self, delta):
        self.focus = max(0, min(len(self.btns) - 1, self.focus + delta))
        self.highlight()

    def highlight(self):
        self.btns[self.focus].grab_focus()

    def toggle_current(self, *_):
        self.run(self.actions[self.focus])

    # ---- state ----
    def refresh(self):
        """Fetch save status in the background (it hits the NAS over rclone, which is slow
        and network-bound) so it never blocks startup; the labels fill in when it returns."""
        if getattr(self, "_refreshing", False):
            return
        self._refreshing = True
        self.status.set_markup("<small>checking saves…</small>")
        threading.Thread(target=self._refresh_work, daemon=True).start()

    def _refresh_work(self):
        try:
            out = subprocess.run(["bash", SAVES_SCRIPT, "status"],
                                 capture_output=True, text=True, timeout=90).stdout
            kv = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
        except Exception:
            kv = {}
        GLib.idle_add(self._refresh_apply, kv)

    def _refresh_apply(self, kv):
        self._refreshing = False
        lb, when, where = kv.get("last_backup", ""), "never", ""
        if lb and lb != "none":
            try:
                import time as _t
                parts = lb.split("\t")
                when = _t.strftime("%b %d  %H:%M", _t.localtime(int(parts[0])))
                if len(parts) > 1:
                    where = "  (from %s)" % parts[1]
            except Exception:
                when = lb
        auto = kv.get("auto", "unknown")
        auto_txt = ("<span foreground='#7fdc7f'>on</span>" if auto == "active"
                    else "<span foreground='#ff8a8a'>OFF (%s)</span>" % auto)
        self.status.set_markup(
            "Steam account <b>%s</b>        Auto-sync: %s\n"
            "On this Deck: <b>%s</b>        On NAS: <b>%s</b>\n"
            "Last backup: <b>%s</b>%s"
            % (kv.get("account", "?"), auto_txt,
               human(int(kv.get("local_bytes", 0) or 0)),
               human(int(kv.get("nas_bytes", 0) or 0)), when, where))
        conflict = kv.get("conflict", "none")
        if conflict and conflict != "none":
            self.warn.set_markup(
                "<span foreground='#ffc46b'><b>Conflict.</b> This Deck has saves it never "
                "pushed, and the NAS copy is newer. Nothing was overwritten. Pick one: "
                "<b>Back up now</b> keeps this Deck's saves, <b>Restore</b> takes the NAS "
                "copy.</span>")
        elif kv.get("dirty") == "1":
            self.warn.set_markup("<small>Unsaved progress on this Deck \u2014 it will be "
                                 "pushed automatically when you close your next game.</small>")
        else:
            self.warn.set_markup("<small>In sync with the NAS.</small>")
        return False

    def run(self, action):
        if self.busy:
            return
        self.busy = True
        self.prog.set_text("%s running\u2026" % action.title())
        import threading

        def work():
            import subprocess
            try:
                r = subprocess.run(["bash", SAVES_SCRIPT, action],
                                   capture_output=True, text=True, timeout=3600)
                msg = (r.stdout or r.stderr or "").strip().splitlines()
                msg = msg[-1] if msg else "done"
            except Exception as e:
                msg = "failed: %s" % e
            GLib.idle_add(self._done, msg)
        threading.Thread(target=work, daemon=True).start()

    def _done(self, msg):
        self.busy = False
        self.prog.set_text(msg)
        self.refresh()
        return False


def union_status():
    """(union_mounted, [(label, path, mode, mounted, free_bytes), ...]) for the storage tiers."""
    tiers = [("Internal", ROM_LOCAL, "RW", os.path.isdir(ROM_LOCAL), free_on(ROM_LOCAL))]
    if ROM_SD:
        tiers.append(("SD", ROM_SD, "RW", os.path.isdir(ROM_SD), free_on(ROM_SD)))
    # use the one-time NAS probe, NOT os.path.ismount()/statvfs() which HANG on a wedged rclone
    # mount; only statvfs the NAS when it's known alive, so a dead NAS can't freeze the Storage page.
    nas_up = NAS_OK
    tiers.append(("NAS", ROM_NAS, "RO", nas_up, free_on(ROM_NAS) if nas_up else 0))
    return _mount_responsive(ROM_UNION), tiers


class StoragePage(Gtk.Box):
    """The storage tiers behind the ~/Emulation/roms union (Internal + SD + NAS), their mount
    state and free space, plus a rebuild action. A System page, not a game list."""
    is_panel = True                     # a button panel, navigated like the Saves page
    is_saves = False
    steam_col = False
    view = None

    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.app = app
        self.rows = []
        self.set_border_width(20)
        self.status = Gtk.Label(xalign=0)
        self.status.get_style_context().add_class("big")
        self.status.set_line_wrap(True)
        self.pack_start(self.status, False, False, 0)
        self.detail = Gtk.Label(xalign=0)
        self.pack_start(self.detail, False, False, 0)
        self.btns = []
        nb = Gtk.Button(label="Set up NAS share…   (SMB host / share / login)")
        nb.set_size_request(500, 62)
        nb.connect("clicked", lambda *_: self.open_nas_setup())
        self.btns.append(nb)
        self.pack_start(nb, False, False, 0)
        b = Gtk.Button(label="Rebuild union      (re-provision the tiers)")
        b.set_size_request(500, 62)
        b.connect("clicked", lambda *_: self.rebuild())
        self.btns.append(b)
        self.pack_start(b, False, False, 0)
        self.prog = Gtk.Label(xalign=0)
        self.prog.get_style_context().add_class("hint")
        self.pack_start(self.prog, False, False, 0)
        self.focus = 0
        self.busy = False
        self.refresh()

    # ---- App-compat no-ops ----
    def selected_bytes(self):
        return 0

    def pending(self):
        return [], []

    def steam_pending(self):
        return [], []

    def load(self, *_):
        pass

    # ---- gamepad (button panel) ----
    def move_focus(self, delta):
        self.focus = max(0, min(len(self.btns) - 1, self.focus + delta))
        self.highlight()

    def highlight(self):
        if self.btns:
            self.btns[self.focus].grab_focus()

    def toggle_current(self, *_):
        self.rebuild()

    # ---- state ----
    def refresh(self):
        mounted, tiers = union_status()
        self.status.set_markup(
            "Library union   <b>%s</b>\n%s" % (ROM_UNION,
            "<span foreground='#7fdc7f'>● mounted</span>" if mounted else
            "<span foreground='#ff8a8a'>○ not mounted — press Rebuild</span>"))
        rows = []
        for label, path, mode, up, free in tiers:
            dot = "<span foreground='#7fdc7f'>●</span>" if up else \
                  "<span foreground='#6b7280'>○</span>"
            state = ("%s · %s free" % (mode, human(free))) if up else \
                    ("%s · not mounted" % mode)
            rows.append("%s  <b>%s</b>\n<span foreground='#9aa0a6'>      %s   —   %s</span>"
                        % (dot, label, path, state))
        self.detail.set_markup("\n".join(rows))

    def rebuild(self):
        if self.busy:
            return
        self.busy = True
        self.prog.set_text("Rebuilding the union…")

        def work():
            try:
                r = subprocess.run(["bash", os.path.join(APP_DIR, "mount-setup.sh")],
                                   capture_output=True, text=True, timeout=180)
                msg = "Union rebuilt." if r.returncode == 0 else "Rebuild reported an error."
            except Exception as e:
                msg = "Rebuild failed: %s" % e
            GLib.idle_add(self._done, msg)
        threading.Thread(target=work, daemon=True).start()

    def _done(self, msg):
        self.busy = False
        self.prog.set_text(msg)
        self.refresh()
        self.app.reload()
        return False

    def open_nas_setup(self):
        """Modal SMB setup: Host / Share / User / Password -> an obscured rclone remote +
        a non-secret remote:path in config.json. Test before saving; rebuild the union after."""
        cur = _C.get("rom_rclone_remote", "") or ""
        name0, path0 = "roms-nas", ""
        if ":" in cur and cur.lower() != "off":
            name0, path0 = cur.split(":", 1)
        pre = nas_setup.read_remote(name0)

        dlg = Gtk.Dialog(title="NAS share (SMB)", transient_for=self.app, modal=True)
        dlg.set_default_size(580, 0)
        box = dlg.get_content_area()
        box.set_spacing(10)
        box.set_border_width(16)
        intro = Gtk.Label(xalign=0, label=(
            "Point Loadout at your NAS's SMB share. The password is stored obscured in rclone's "
            "config (0600) — never in Loadout's config. Leave the password blank to keep the one "
            "already saved."))
        intro.set_line_wrap(True)
        box.pack_start(intro, False, False, 0)
        grid = Gtk.Grid(column_spacing=10, row_spacing=8)

        def field(row, label, text="", secret=False, ph=""):
            grid.attach(Gtk.Label(label=label, xalign=1), 0, row, 1, 1)
            e = Gtk.Entry()
            e.set_hexpand(True)
            e.set_text(text)
            if ph:
                e.set_placeholder_text(ph)
            if secret:
                e.set_visibility(False)
                e.set_input_purpose(Gtk.InputPurpose.PASSWORD)
            grid.attach(e, 1, row, 1, 1)
            return e

        e_host = field(0, "Host", pre["host"], ph="192.168.10.14  or  truenas.local")
        e_share = field(1, "Share / path", path0, ph="Games/roms")
        e_user = field(2, "Username", pre["user"], ph="(blank = guest)")
        e_pass = field(3, "Password", "", secret=True, ph="(unchanged)")
        e_name = field(4, "Remote name", name0)
        box.pack_start(grid, False, False, 0)
        status = Gtk.Label(xalign=0)
        status.set_line_wrap(True)
        status.get_style_context().add_class("hint")
        box.pack_start(status, False, False, 0)
        dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("Test", 10)
        dlg.add_button("Save", Gtk.ResponseType.OK)
        dlg.show_all()

        def stat(color, msg):
            status.set_markup("<span foreground='%s'>%s</span>"
                              % (color, GLib.markup_escape_text(msg)))

        def apply(persist):
            host, share = e_host.get_text().strip(), e_share.get_text().strip()
            user, pw = e_user.get_text().strip(), e_pass.get_text()
            name = e_name.get_text().strip() or "roms-nas"
            if not host or not share:
                stat("#ff8a8a", "Host and Share are required.")
                return None
            try:
                nas_setup.write_remote(name, host, user, pw, keep_existing_pass=True)
            except Exception as ex:
                stat("#ff8a8a", "rclone error: %s" % ex)
                return None
            remote = nas_setup.remote_path(name, share)
            if persist:
                save_config_value("rom_rclone_remote", remote)
                _C["rom_rclone_remote"] = remote
            return remote

        def do_test():
            remote = apply(persist=False)
            if not remote:
                return
            status.set_text("Testing %s …" % remote)

            def work():
                ok, msg = nas_setup.test_remote(remote)
                GLib.idle_add(stat, "#7fdc7f" if ok else "#ff8a8a", msg)
            threading.Thread(target=work, daemon=True).start()

        while True:
            resp = dlg.run()
            if resp == 10:                         # Test — keep the dialog open
                do_test()
                continue
            if resp == Gtk.ResponseType.OK:
                remote = apply(persist=True)
                if remote is None:                 # validation failed — keep open
                    continue
                dlg.destroy()
                self.prog.set_text("NAS set to %s — rebuilding the union…" % remote)
                self.rebuild()
            else:
                dlg.destroy()
            break


class App(Gtk.Window):
    def __init__(self):
        super().__init__(title="Loadout")
        self.set_default_size(1280, 800)
        self.fullscreen()
        css = Gtk.CssProvider()
        css.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        outer.set_border_width(16)
        self.add(outer)

        self.title = Gtk.Label(xalign=0)
        self.title.get_style_context().add_class("big")
        outer.pack_start(self.title, False, False, 0)

        self.bar = Gtk.LevelBar()
        self.bar.set_size_request(-1, 18)
        outer.pack_start(self.bar, False, False, 0)

        # --- nav: a grouped left sidebar + a content stack (replaces the tab strip) ---
        self.stack = Gtk.Stack()
        self.sidebar = Gtk.ListBox()
        self.sidebar.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.sidebar.get_style_context().add_class("nav")
        self.sidebar.connect("row-selected", self._on_nav_row)
        self.nav = []                          # ordered SELECTABLE entries (headers excluded)
        self.nav_index = 0
        self.focus_pane = "content"            # "sidebar" | "content": which pane the D-pad drives
        self.console_pages = {}

        self.pc_page = Page(self, "No playable PC games installed yet.", steam_col=True)
        self.rom_page = Page(self, "No console collections found.")
        self.saves_page = SavesPage(self)
        self.storage_page = StoragePage(self)

        # reuse this one scan for the initial load below (startup scans the mounts once)
        _pc0, _roms0, _by = scan()
        self._nav_header("LIBRARY")
        self._nav_add("pc", self.pc_page, "PC Games")
        self._nav_add("collections", self.rom_page, "Collections")
        for sysid in TAB_ORDER:
            if sysid in _by:
                pg = Page(self, "No games.", steam_col=True)
                self.console_pages[sysid] = pg
                self._nav_add(sysid, pg, TAB_NAME.get(sysid, sysid))
        self._nav_header("SYSTEM")
        self._nav_add("saves", self.saves_page, "Saves")
        self._nav_add("storage", self.storage_page, "Storage")

        _side = Gtk.ScrolledWindow()
        _side.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        _side.set_size_request(232, -1)
        _side.add(self.sidebar)
        _split = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        _split.pack_start(_side, False, False, 0)
        _split.pack_start(self.stack, True, True, 0)
        outer.pack_start(_split, True, True, 0)
        self.pages = [e["page"] for e in self.nav]
        self.focus_label = Gtk.Label(xalign=0)
        self.focus_label.get_style_context().add_class("hint")
        outer.pack_start(self.focus_label, False, False, 0)

        # Inline confirmation: a modal Gtk dialog runs its own event loop, so the
        # gamepad thread's actions never reach it and A/B would do nothing.
        self.banner = Gtk.Label(xalign=0)
        self.banner.set_line_wrap(True)
        self.banner.set_no_show_all(True)
        outer.pack_start(self.banner, False, False, 0)

        self.progress = Gtk.ProgressBar(show_text=True)
        outer.pack_start(self.progress, False, False, 0)

        bar = Gtk.Box(spacing=10)
        self.apply_btn = Gtk.Button(label="Apply  (Y)")
        self.apply_btn.connect("clicked", self.on_apply)
        rescan = Gtk.Button(label="Rescan  (⧉ View)")
        rescan.connect("clicked", lambda *_: self.reload())
        close = Gtk.Button(label="Close  (B)")
        close.connect("clicked", lambda *_: self.quit_app())
        bar.pack_start(self.apply_btn, False, False, 0)
        bar.pack_start(rescan, False, False, 0)
        bar.pack_end(close, False, False, 0)
        outer.pack_start(bar, False, False, 0)

        hint = Gtk.Label(xalign=0)
        _disk = "    •    Start = disk (SD/Internal)" if HAVE_SD else ""
        hint.set_text("D-pad = move    •    L1/R1 = switch section    •    A = keep Offline    •    "
                      "X = show in Steam" + _disk + "    •    Y = apply    •    B = close")
        hint.get_style_context().add_class("hint")
        outer.pack_start(hint, False, False, 0)

        self.sync_label = Gtk.Label(xalign=0)
        self.sync_label.get_style_context().add_class("hint")
        outer.pack_start(self.sync_label, False, False, 0)

        self.pad_label = Gtk.Label(xalign=0)
        self.pad_label.get_style_context().add_class("hint")
        outer.pack_start(self.pad_label, False, False, 0)

        self.dirty = False
        self.confirm = None
        self.update_info = None
        self.busy = False
        self.connect("delete-event", lambda *_: (self.quit_app(), True)[1])
        self.connect("key-press-event", self.on_key)
        # open on the first section that actually has games (PC is often empty on a Deck)
        _dkey = "pc"
        if not _pc0:
            _dkey = "collections" if _roms0 else (next(iter(self.console_pages), "pc")
                                                  if self.console_pages else "pc")
        self.select_nav(next((i for i, e in enumerate(self.nav) if e["key"] == _dkey), 0))
        self.reload(prescanned=(_pc0, _roms0, _by))
        self.pad = Gamepad(self)
        self.pad.start()
        # Non-blocking self-update check: if a newer AppImage release exists, offer it (U).
        self.update_info = None
        threading.Thread(target=self._check_update, daemon=True).start()

    def _check_update(self):
        try:
            import loadout_update
            info = loadout_update.check()
        except Exception:
            info = None
        if info and os.environ.get("APPIMAGE"):
            GLib.idle_add(self._offer_update, info)

    def _offer_update(self, info):
        self.update_info = info
        self.show_banner("Loadout %s is available.     U = install     B = dismiss"
                         % info["version"], "confirm")
        return False

    def _do_update(self):
        info, self.update_info = self.update_info, None
        self.show_banner("Downloading Loadout %s…" % info["version"], "confirm")

        def work():
            import loadout_update
            ok, msg = loadout_update.apply(info)
            GLib.idle_add(self.show_banner, msg, "confirm" if ok else "error")
        threading.Thread(target=work, daemon=True).start()

    def quit_app(self):
        # Copying happens in a systemd service now, so closing here never cancels it.
        """Exit. If anything changed, leave the dirty flag; a systemd path unit then
        fires the native Steam refresh (`Loadout.AppImage --refresh`) once this app is gone.

        It cannot run here: the refresh stops Steam, which would kill this process
        mid-way, and the refresh's own guard refuses to run while a Steam-launched app
        (this one) is still alive."""
        if self.dirty:
            try:
                write_launchers()          # flag was already written in finish()
            except Exception:
                pass
        Gtk.main_quit()

    def set_pad_status(self, text):
        self.pad_label.set_text(text)
        return False

    def _grab(self):
        pg = self.page()
        if getattr(pg, "is_panel", False):
            pg.highlight()
        elif getattr(pg, "view", None) is not None:
            pg.view.grab_focus()
        self.update_focus_hint()

    def pad_move(self, delta):
        """D-pad / stick moves the highlighted row. When focus is on the sidebar it walks the
        sections (live-previewing each); otherwise it moves the row/button in the content pane."""
        if self.focus_pane == "sidebar":
            self.select_nav(self.nav_index + delta)
            self.nav[self.nav_index]["row"].grab_focus()
            return False
        pg = self.page()
        _padlog("  pad_move(%d) EXEC page=%s rows=%d" % (delta, type(pg).__name__, len(getattr(pg, "rows", []) or [])))
        if getattr(pg, "is_panel", False):
            pg.move_focus(delta); return False
        if not pg.rows:
            return False
        path, _ = pg.view.get_cursor()
        i = (path.get_indices()[0] if path else 0) + delta
        i = max(0, min(i, len(pg.rows) - 1))
        try:
            pg.view.set_cursor(Gtk.TreePath.new_from_indices([i]))
            pg.view.scroll_to_cell(i)
            _padlog("    cursor -> %d OK" % i)
        except Exception as ex:
            _padlog("    set_cursor RAISED: %r" % ex)
        return False

    def pad_action(self, name):
        if self.confirm is not None:            # confirmation is showing
            if name == "a":
                self.do_apply()
            elif name == "b":
                self.hide_banner()
            return False
        if name == "a":
            if self.focus_pane == "sidebar":    # A on the sidebar = enter the content list
                self.set_pane("content")
            else:
                self.page().toggle_current(0)
        elif name == "b":
            if self.banner.get_visible():
                self.hide_banner()
            else:
                self.quit_app()
        elif name == "x":
            self.toggle_steam_current()
        elif name == "y":
            self.on_apply(None)
        elif name == "l1":
            self.prev_nav()
        elif name == "r1":
            self.next_nav()
        elif name == "select":
            self.reload()
        elif name == "start":
            self.cycle_dest()
        return False

    def cycle_dest(self):
        """Start / D: flip the highlighted game's copy destination (SD <-> Internal).

        No-op without an SD, on the Saves tab, or on an already-local game."""
        pg = self.page()
        if getattr(pg, "is_saves", False) or not hasattr(pg, "cycle_dest_current"):
            return False
        pg.cycle_dest_current()
        self.update_totals()
        return False

    def toggle_steam_current(self):
        """X marks the highlighted game as a Steam shortcut (or unmarks it)."""
        pg = self.page()
        if getattr(pg, "is_saves", False) or not getattr(pg, "steam_col", False):
            return False
        pg.toggle_current(1)
        return False

    def update_focus_hint(self):
        if self.focus_pane == "sidebar":
            self.focus_label.set_text(
                "↑/↓ = choose console    •    → or A = go to its games    •    L1/R1 = jump")
            return
        pg = self.page()
        disk = "    •    Start = copy to SD / Internal" if HAVE_SD else ""
        nav = "    •    ← = console list"
        if getattr(pg, "steam_col", False):
            self.focus_label.set_text(
                "A = keep this game Offline    •    X = show it in Steam" + disk + nav)
        elif getattr(pg, "is_saves", False):
            self.focus_label.set_text("A = run the highlighted backup / restore" + nav)
        elif getattr(pg, "is_panel", False):
            self.focus_label.set_text("A = rebuild the union" + nav)
        else:
            self.focus_label.set_text("A = keep this collection Offline" + disk + nav)

    def _nav_header(self, text):
        r = Gtk.ListBoxRow()
        r.set_selectable(False)
        r.set_activatable(False)
        lbl = Gtk.Label(label=text, xalign=0)
        lbl.get_style_context().add_class("navhdr")
        r.add(lbl)
        self.sidebar.add(r)

    def _nav_add(self, key, page, label):
        self.stack.add_named(page, key)
        r = Gtk.ListBoxRow()
        lbl = Gtk.Label(label="   " + label, xalign=0)
        lbl.get_style_context().add_class("navitem")
        r.add(lbl)
        r._navkey = key
        self.sidebar.add(r)
        self.nav.append({"key": key, "page": page, "label": label, "row": r})

    def _on_nav_row(self, _list, row):
        if row is None:
            return
        key = getattr(row, "_navkey", None)
        if key is None:
            return
        for i, e in enumerate(self.nav):
            if e["key"] == key:
                self.nav_index = i
                _padlog("  _on_nav_row EXEC -> idx=%d key=%s" % (i, key))
                self.stack.set_visible_child(e["page"])
                if hasattr(e["page"], "load_covers"):
                    e["page"].load_covers()        # lazily fetch covers for the shown section
                self.update_focus_hint()
                GLib.idle_add(self._grab)
                break

    def select_nav(self, i):
        i = max(0, min(i, len(self.nav) - 1))
        _padlog("  select_nav(%d) EXEC" % i)
        self.sidebar.select_row(self.nav[i]["row"])    # fires _on_nav_row

    def prev_nav(self):
        self.select_nav(self.nav_index - 1)

    def next_nav(self):
        self.select_nav(self.nav_index + 1)

    def set_pane(self, pane):
        """Move the D-pad focus to the sidebar or the content list, with a visible cue."""
        self.focus_pane = pane
        sc = self.sidebar.get_style_context()
        if pane == "sidebar":
            sc.add_class("focused")
            row = self.nav[self.nav_index]["row"]
            self.sidebar.select_row(row)
            row.grab_focus()
        else:
            sc.remove_class("focused")
            self._grab()
        self.update_focus_hint()
        return False

    def page(self):
        return self.nav[self.nav_index]["page"]

    def poll_progress(self):
        """Show the background worker's state; keep polling while it is running."""
        try:
            p = json.load(open(PROGRESS))
        except Exception:
            return os.path.exists(QUEUE)          # queued but not started yet
        st = p.get("state")
        if st in ("copying", "freeing"):
            tot, done = max(p.get("total", 1), 1), p.get("done", 0)
            it, itt = p.get("item_done", 0), max(p.get("item_total", 1), 1)
            rate = p.get("rate", 0)
            eta = (itt - it) / rate if rate > 1000 else 0
            self.progress.set_fraction(min(done / tot, 1.0))
            self.progress.set_text("%s %s   %s / %s   %s/s%s"
                                   % (st, p.get("name", "")[:26], human(it), human(itt),
                                      human(rate),
                                      "   ~%dm%02ds" % (eta // 60, eta % 60) if eta else ""))
            return True
        self.progress.set_fraction(1.0)
        self.progress.set_text("Background copy finished — Steam updates shortly")
        self.reload()
        return False

    def last_sync_note(self):
        """A previous exit may have failed to reach Steam (guard aborted, Deck slept).
        Say so plainly instead of leaving it invisible."""
        pending = os.path.exists(os.path.join(HOME, ".loadout-dirty"))
        log = os.path.join(HOME, "steam-refresh.log")
        last = ""
        try:
            lines = [l.strip() for l in open(log) if l.strip()]
            last = lines[-1][:70] if lines else ""
        except Exception:
            pass
        if pending:
            self.sync_label.set_text("Steam sync PENDING from a previous session — "
                                     "it will run when you exit.  " + last)
        elif last:
            self.sync_label.set_text("last Steam sync: " + last)
        else:
            self.sync_label.set_text("")

    def reload(self, prescanned=None):
        if os.path.exists(QUEUE):
            GLib.timeout_add(1000, self.poll_progress)
        freed = sweep_partials()
        if freed:
            self.show_banner("Cleaned up %s of interrupted copy data." % human(freed), "error")
        pc, roms, by_system = prescanned if prescanned else scan()
        self.pc_page.load(pc)
        self.rom_page.load(roms)
        for sysid, pg in self.console_pages.items():
            pg.load(by_system.get(sysid, []))
        self.update_totals()
        self.last_sync_note()
        if hasattr(self, "saves_page"):
            self.saves_page.refresh()
        cur = self.page()
        if hasattr(cur, "load_covers"):
            cur.load_covers()                  # covers for whatever section is showing
        self._grab()

    def update_totals(self):
        want = sum(pg.selected_bytes() for pg in self.pages)
        have_local = sum(r.size for pg in self.pages for r in pg.rows if r.is_local)
        projected = free_bytes() + have_local - want
        used = total_bytes() - projected
        self.bar.set_max_value(max(total_bytes(), 1))
        self.bar.set_value(max(0, min(used, total_bytes())))
        self.title.set_markup(
            "Keep offline: <b>%s</b>     Free now: <b>%s</b>     After apply: <b>%s</b>"
            % (human(want), human(free_bytes()), human(max(projected, 0))))

    def on_key(self, _w, ev):
        k = Gdk.keyval_name(ev.keyval) or ""
        _padlog("KEY-GTK %s" % k)
        if self.confirm is not None:
            if k in ("space", "Return", "KP_Enter", "a", "A"):
                self.do_apply()
            elif k in ("Escape", "b", "B"):
                self.hide_banner()
            return True
        if k in ("Left",):
            self.set_pane("sidebar"); return True
        if k in ("Right",):
            self.set_pane("content"); return True
        if k in ("space", "Return", "KP_Enter"):
            self.page().toggle_current(0); return True
        if k in ("y", "Y"):
            self.on_apply(None); return True
        if k in ("x", "X"):
            self.toggle_steam_current(); return True
        if k in ("d", "D"):
            self.cycle_dest(); return True
        if k in ("u", "U") and self.update_info:
            self._do_update(); return True
        if k in ("F5",):
            self.reload(); return True
        if k in ("Escape", "b", "B"):
            if self.banner.get_visible():
                self.hide_banner()
            else:
                self.quit_app()
            return True
        # L1/R1 commonly arrive as these
        if k in ("Page_Up", "bracketleft", "l", "L"):
            self.prev_nav(); return True
        if k in ("Page_Down", "bracketright", "r", "R", "Tab"):
            self.next_nav(); return True
        return False

    def on_apply(self, _b):
        pulls, drops, sadd, srem = [], [], [], []
        for pg in self.pages:
            p, d = pg.pending()
            pulls += p; drops += d
            a, r = pg.steam_pending()
            sadd += a; srem += r
        if not pulls and not drops and not sadd and not srem:
            self.title.set_markup("<b>Nothing to change.</b>")
            return
        need = sum(r.size for r in pulls)
        # Space check is per destination filesystem: SD-bound and internal-bound copies can
        # land on different disks, so a single total would mis-judge either one.
        by_fs = {}
        for r in pulls:
            p = pull_dest_dir(r)
            while p and not os.path.exists(p):
                p = os.path.dirname(p)
            try:
                dev = os.stat(p or "/").st_dev
            except OSError:
                dev = 0
            slot = by_fs.setdefault(dev, [0, p or "/"])
            slot[0] += r.size
        short = [(n, p) for n, p in by_fs.values() if n > free_on(p)]
        if short:
            self.show_banner("Not enough space — need %s, only %s free.    B = dismiss"
                             % (human(sum(n for n, _ in short)),
                                human(sum(free_on(p) for _, p in short))), "error")
            self.confirm = None
            return
        self.confirm = (pulls, drops, sadd, srem)
        steam_note = ""
        if sadd or srem:
            steam_note = "     Steam: +%d / -%d shortcut(s)" % (len(sadd), len(srem))
        self.show_banner(
            "Apply?   Copy to Deck: %d (%s)     Free from Deck: %d%s\n"
            "The NAS copies are not touched.        A = confirm      B = cancel"
            % (len(pulls), human(need), len(drops), steam_note), "confirm")

    def show_banner(self, text, style):
        ctx = self.banner.get_style_context()
        for c in ("confirm", "error"):
            ctx.remove_class(c)
        ctx.add_class(style)
        self.banner.set_text(text)
        self.banner.show()

    def hide_banner(self):
        self.banner.hide()
        self.confirm = None
        self.update_info = None

    def do_apply(self):
        """Hand the work to the background worker and return at once.

        Copying inside this process meant closing the app killed the transfer. The
        worker is a systemd user service, so you can queue a 15GB game, close this, and
        go play while it copies."""
        pulls, drops, sadd, srem = self.confirm
        self.hide_banner()
        # Console Steam picks are instant symlinks. PC picks are launchers, handled below.
        for r in sadd:
            if getattr(r, "kind", None) == "game":
                try:
                    set_steam(r.system, r.sfile, True)
                except Exception:
                    pass
        for r in srem:
            if getattr(r, "kind", None) == "game":
                try:
                    set_steam(r.system, r.sfile, False)
                except Exception:
                    pass

        def pull_job(r):
            dst = pull_dest_dir(r)             # the chosen disk (SD/Internal), or PC internal
            if getattr(r, "kind", None) == "game":
                return {"name": r.name, "kind": "game", "system": r.system, "size": r.size,
                        "files": [{"nas": os.path.join(ROM_NAS, r.system, fn),
                                   "local": os.path.join(dst, r.system, fn)}
                                  for fn in r.files]}
            return {"name": r.name, "nas": r.nas_path,
                    "local": os.path.join(dst, r.name), "size": r.size}

        def drop_job(r):
            if getattr(r, "kind", None) == "game":
                # free each file from the branch that actually holds it (SD or internal)
                files = [rom_local_path(r.system, fn) for fn in r.files]
                return {"name": r.name, "kind": "game", "system": r.system,
                        "files": [p for p in files if p]}
            # cartridge collection / PC game: free every local branch that holds it
            return {"name": r.name, "local": getattr(r, "local_dirs", None) or [r.local_path]}

        job = {"pulls": [pull_job(r) for r in pulls],
               "drops": [drop_job(r) for r in drops]}
        try:
            tmp = QUEUE + ".tmp"
            json.dump(job, open(tmp, "w"))
            os.replace(tmp, QUEUE)          # appearing triggers the worker path unit
        except Exception as e:
            self.show_banner("Could not queue the job: %s" % e, "error")
            return
        # PC Steam shortcuts are launchers, driven by the PC "Steam" checkbox (NOT the
        # Offline one) -- so a title only lands in Steam if you actually enabled Steam for
        # it. The Steam stop/restart + SRM re-run happens ONLY when a Steam-showing toggle
        # changed (console or PC); an offline-only change copies quietly with no restart.
        pc_steam_want = {r.name for i, r in enumerate(self.pc_page.rows)
                         if self.pc_page.store[i][1]}
        steam_changed = bool(sadd or srem)
        try:
            write_launchers(pc_steam_want)
            if steam_changed:
                open(os.path.join(HOME, ".loadout-dirty"), "w").write("apply\n")
        except Exception:
            pass
        self.dirty = steam_changed
        self.confirm = None
        # Nothing left for this app to do: the worker copies and the sync service
        # refreshes Steam. Close immediately rather than lingering.
        self.show_banner("Applying — closing. Steam will refresh; copying continues "
                         "in the background.", "confirm")
        GLib.timeout_add(1200, lambda: (Gtk.main_quit(), False)[1])

    def worker(self, pulls, drops):
        # weight by bytes so the bar reflects real work; drops are near-instant
        total = max(sum(r.size for r in pulls), 1)
        done = 0
        for r in drops:
            GLib.idle_add(self.status, "Freeing: %s" % r.name, done / total)
            try:
                shutil.rmtree(r.local_path) if os.path.isdir(r.local_path) else os.remove(r.local_path)
            except Exception as e:
                GLib.idle_add(self.status, "Failed to free %s: %s" % (r.name, e), done / total)
        for idx, r in enumerate(pulls):
            base = done / total
            span = 1.0 / total
            GLib.idle_add(self.status, "Copying %s (%s)…" % (r.name, human(r.size)), base)
            tmp = r.local_path + ".part"
            t0 = time.time()

            def report(b, tot, rel, _r=r, _base=base, _span=span, _t0=t0):
                pct = (b / tot) if tot else 1.0
                el = max(time.time() - _t0, 0.001)
                rate = b / el
                eta = (tot - b) / rate if rate > 1000 else 0
                GLib.idle_add(self.status,
                              "%s   %s / %s  (%d%%)   %s/s%s"
                              % (_r.name, human(b), human(tot), pct * 100, human(rate),
                                 "   ~%dm%02ds left" % (eta // 60, eta % 60) if eta else ""),
                              _base + _span * pct)

            try:
                os.makedirs(os.path.dirname(r.local_path), exist_ok=True)
                shutil.rmtree(tmp, ignore_errors=True)
                if os.path.isdir(r.nas_path):
                    copy_with_progress(r.nas_path, tmp, report)
                    os.rename(tmp, r.local_path)
                else:
                    shutil.copy2(r.nas_path, tmp)
                    os.replace(tmp, r.local_path)
                # the read-only NAS mount strips the execute bit; restore it
                subprocess.run(["bash", "-c",
                                'find %s -type d -exec chmod u+rwx {} + 2>/dev/null; '
                                'find %s \\( -iname "*.exe" -o -iname "*.sh" -o -iname "*.AppImage" '
                                '-o -iname "*.x86_64" \\) -exec chmod +x {} + 2>/dev/null'
                                % (repr(r.local_path), repr(r.local_path))], check=False)
            except Exception as e:
                shutil.rmtree(tmp, ignore_errors=True)
                GLib.idle_add(self.status, "Failed copying %s: %s" % (r.name, e), done / total)
            done += r.size
        GLib.idle_add(self.finish)

    def status(self, text, frac):
        self.progress.set_fraction(max(0.0, min(1.0, frac)))
        self.progress.set_text(text[:80])
        return False

    def finish(self):
        self.busy = False
        self.dirty = True
        # Persist immediately: if this process dies before quit_app() runs, the flag is
        # still on disk so the sync is not lost.
        try:
            write_launchers()
            open(os.path.join(HOME, ".loadout-dirty"), "w").write("changes applied\n")
        except Exception:
            pass          # changes saved; Steam gets synced when we exit
        self.progress.set_fraction(1.0)
        self.progress.set_text("Done — Steam will be updated on exit")
        self.apply_btn.set_sensitive(True)
        self.reload()
        return False


if __name__ == "__main__":
    import sys
    if "--sync-steam-dry" in sys.argv:             # report what a native Steam sync would do
        _add, _rem = sync_steam(dry_run=True)
        print("would ADD %d shortcut(s), REMOVE %d" % (len(_add), len(_rem)))
        for _rom, _sys, _name in _add[:25]:
            print("  + [%s] %s" % (_sys, _name))
        for _rom in _rem[:25]:
            print("  - %s" % _rom)
        raise SystemExit(0)
    if "--sync-steam" in sys.argv:                 # native Steam sync (Steam must be stopped)
        _a, _r = sync_steam()
        print("synced Steam shortcuts: +%d, -%d" % (_a, _r))
        raise SystemExit(0)
    if "--update" in sys.argv:                     # headless self-update (timer / manual)
        import loadout_update
        _info = loadout_update.check()
        if not _info:
            print("Loadout %s is up to date." % loadout_update.VERSION)
            raise SystemExit(0)
        _ok, _msg = loadout_update.apply(_info)
        print(_msg)
        raise SystemExit(0 if _ok else 1)
    w = App()
    w.connect("destroy", Gtk.main_quit)
    w.show_all()
    Gtk.main()
