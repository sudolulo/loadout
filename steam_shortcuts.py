#!/usr/bin/env python3
"""Read/write Steam's non-Steam-games file (shortcuts.vdf, Valve binary KeyValues) and its
library artwork. Loadout uses this to register itself (and, later, the ROMs you pick) in
Steam natively -- no Steam ROM Manager required.

SAFETY: this file holds ALL of a user's non-Steam shortcuts. The parser/serializer round-trip
byte-for-byte (verify with `python steam_shortcuts.py <shortcuts.vdf>`); string values are kept
as raw bytes (latin-1) so nothing is lost. Every write goes through `add_shortcut`, which backs
the file up first, refuses to run if the round-trip guard fails, and never drops existing entries.
"""
import binascii
import glob
import os
import shutil
import struct

# Binary VDF tags: 0x00 nested map, 0x01 string, 0x02 int32(LE), 0x08 ends a map.


def _read_str(buf, i):
    j = buf.index(b"\x00", i)
    return buf[i:j].decode("latin-1"), j + 1        # latin-1 == byte-exact round-trip


def _parse_map(buf, i):
    """Parse a map's children starting at i; return (list_of_(key,value), next_index)."""
    out = []
    while True:
        t = buf[i]
        i += 1
        if t == 0x08:
            return out, i
        key, i = _read_str(buf, i)
        if t == 0x00:
            val, i = _parse_map(buf, i)
        elif t == 0x01:
            val, i = _read_str(buf, i)
        elif t == 0x02:
            val = struct.unpack_from("<i", buf, i)[0]
            i += 4
        else:
            raise ValueError("unknown VDF tag 0x%02x at %d" % (t, i - 1))
        out.append((key, val))


def _dump_map(pairs):
    out = bytearray()
    for key, val in pairs:
        kb = key.encode("latin-1")
        if isinstance(val, list):
            out += b"\x00" + kb + b"\x00" + _dump_map(val) + b"\x08"
        elif isinstance(val, bool):
            out += b"\x02" + kb + b"\x00" + struct.pack("<i", int(val))
        elif isinstance(val, int):
            out += b"\x02" + kb + b"\x00" + struct.pack("<i", val)
        else:
            out += b"\x01" + kb + b"\x00" + str(val).encode("latin-1") + b"\x00"
    return bytes(out)


def loads(buf):
    """Parse shortcuts.vdf -> root pairs, i.e. [("shortcuts", [(index, entry_pairs), ...])]."""
    root, _ = _parse_map(buf, 0)
    return root


def dumps(root):
    return _dump_map(root) + b"\x08"                # + the document-terminating 0x08


# --- shortcut app id (what the grid artwork files are named after) ------------------------
def app_id(exe, appname):
    return binascii.crc32((exe + appname).encode("utf-8")) & 0xFFFFFFFF | 0x80000000


def _entries(root):
    for k, v in root:
        if k.lower() == "shortcuts":
            return v
    return []


def get(root, appname):
    for _idx, entry in _entries(root):
        for k, v in entry:
            if k.lower() == "appname" and v == appname:
                return entry
    return None


def add_shortcut(vdf_path, appname, exe, start_dir, icon="", tags=None):
    """Add a non-Steam shortcut IF absent. Backs up shortcuts.vdf, refuses on a round-trip
    mismatch, preserves every existing entry. Returns (app_id, changed). Steam must be stopped
    for the write to stick (it rewrites the file on exit)."""
    if os.path.exists(vdf_path):
        raw = open(vdf_path, "rb").read()
        root = loads(raw)
        if dumps(root) != raw:
            raise RuntimeError("shortcuts.vdf round-trip mismatch — refusing to write")
    else:
        raw, root = None, [("shortcuts", [])]
    if get(root, appname):
        return app_id(exe, appname), False
    aid = app_id(exe, appname)
    lst = _entries(root)
    entry = [
        ("appid", struct.unpack("<i", struct.pack("<I", aid))[0]),
        ("AppName", appname), ("Exe", exe), ("StartDir", start_dir),
        ("icon", icon), ("ShortcutPath", ""), ("LaunchOptions", ""),
        ("IsHidden", 0), ("AllowDesktopConfig", 1), ("AllowOverlay", 1),
        ("OpenVR", 0), ("Devkit", 0), ("DevkitGameID", ""), ("DevkitOverrideAppID", 0),
        ("LastPlayTime", 0),
        ("tags", [(str(i), t) for i, t in enumerate(tags or [])]),
    ]
    lst.append((str(len(lst)), entry))
    if raw is not None:
        shutil.copy2(vdf_path, vdf_path + ".loadout-bak")
    tmp = vdf_path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(dumps(root))
    os.replace(tmp, vdf_path)
    return aid, True


import re as _re
_ROMPAT = _re.compile(r"\.steam-shortcuts/([^/]+)/")


def _ci(d, key):
    for k, v in d:
        if k.lower() == key.lower():
            return v
    return ""


def learn_templates(root):
    """Learn each system's Steam launch template from the existing (SRM-made) shortcuts, so
    Loadout can add matching shortcuts natively -- games then launch identically and SRM is no
    longer needed. Returns {sysid: {exe, lo, start_dir, tag}} with the rom path -> '{ROM}'.

    Keyed by the system DIR under .steam-shortcuts/<sysid>/ (Loadout's own system ids), which is
    what set_steam() symlinks into."""
    out = {}
    for _idx, entry in _entries(root):
        exe, lo = str(_ci(entry, "Exe")), str(_ci(entry, "LaunchOptions"))
        m = _ROMPAT.search(exe) or _ROMPAT.search(lo)
        if not m or m.group(1) in out:
            continue
        sysid = m.group(1)

        def slot(s):                       # replace the quoted rom path for THIS sysid with {ROM}
            return _re.sub(r'"[^"]*\.steam-shortcuts/%s/[^"]*"' % _re.escape(sysid), '"{ROM}"', s)

        tags = _ci(entry, "tags")
        out[sysid] = {"exe": slot(exe), "lo": slot(lo),
                      "start_dir": str(_ci(entry, "StartDir")),
                      "tag": tags[0][1] if isinstance(tags, list) and tags else ""}
    return out


# Built-in EmuDeck launch templates, so Loadout works on a FRESH device with no existing
# shortcuts to learn from. learn_templates() overrides these where the user already has
# shortcuts (matching their exact emulator/core config). {ROM} is the symlink path.
_RA_CORES = {                              # systems launched via retroarch.sh -L <core> "{ROM}"
    "snes": "snes9x", "sfc": "snes9x", "nes": "mesen", "famicom": "mesen",
    "n64": "mupen64plus_next", "gb": "gambatte", "gbc": "gambatte", "gba": "mgba",
    "nds": "melonds", "pokemini": "gambatte", "gamegear": "genesis_plus_gx",
    "mastersystem": "genesis_plus_gx", "genesis": "genesis_plus_gx", "megadrive": "genesis_plus_gx",
    "segacd": "genesis_plus_gx", "sega32x": "picodrive", "psx": "swanstation", "saturn": "kronos",
    "dreamcast": "flycast", "tg16": "mednafen_pce", "pcengine": "mednafen_pce", "neogeo": "fbneo",
    "arcade": "fbneo", "atari2600": "stella", "wonderswan": "mednafen_wswan",
    "ngp": "mednafen_ngp", "virtualboy": "mednafen_vb",
}
_SPECIAL = {                               # systems with a dedicated emulator launcher
    "gc":     ('"{L}dolphin-emu.sh"', 'vblank_mode=0 %command% -b -e "{ROM}"'),
    "wii":    ('"{L}dolphin-emu.sh"', 'vblank_mode=0 %command% -b -e "{ROM}"'),
    "wiiu":   ('"{L}cemu.sh" vblank_mode=0 %command% -f -g "{ROM}"', ""),
    "switch": ('"{L}ryujinx.sh" --fullscreen "{ROM}"', ""),
    "psp":    ('"{L}ppsspp.sh" "{ROM}"', ""),
    "ps2":    ('"{L}pcsx2-qt.sh" "{ROM}"', ""),
    "ps3":    ('"{L}rpcs3.sh" "{ROM}"', ""),
    "xbox":   ('"{L}xemu-emu.sh"  -full-screen -dvd_path "{ROM}"', ""),
    "n3ds":   ('"{L}azahar.sh" "{ROM}"', ""),
}
_TAGS = {
    "gc": "GameCube", "wii": "Wii", "wiiu": "Wii U", "switch": "Nintendo Switch",
    "snes": "Super Nintendo", "sfc": "Super Nintendo", "nes": "Nintendo Entertainment System",
    "famicom": "Nintendo Entertainment System", "n64": "Nintendo 64", "nds": "Nintendo DS",
    "gb": "Game Boy", "gbc": "Game Boy Color", "gba": "Game Boy Advance", "n3ds": "Nintendo 3DS",
    "gamegear": "Game Gear", "mastersystem": "Master System", "genesis": "Sega Genesis",
    "megadrive": "Sega Mega Drive", "segacd": "Sega CD", "sega32x": "Sega 32X",
    "saturn": "Sega Saturn", "dreamcast": "Dreamcast", "psx": "PlayStation", "ps2": "PlayStation 2",
    "ps3": "PlayStation 3", "psp": "PSP", "xbox": "Xbox", "tg16": "TurboGrafx-16",
    "pcengine": "PC Engine", "neogeo": "Neo Geo", "arcade": "Arcade", "atari2600": "Atari 2600",
    "wonderswan": "WonderSwan", "ngp": "Neo Geo Pocket", "virtualboy": "Virtual Boy",
    "pokemini": "Pokemon Mini",
}


def builtin_templates(home=None):
    """Loadout's own per-system launch templates (standard EmuDeck layout), so a fresh device
    with no existing shortcuts still works. Same shape as learn_templates()."""
    home = home or os.path.expanduser("~")
    launch = home + "/Emulation/tools/launchers/"
    corep = home + "/.var/app/org.libretro.RetroArch/config/retroarch/cores/"
    sd = home + "/Emulation/tools/launchers"
    out = {}
    for sysid, core in _RA_CORES.items():
        out[sysid] = {"exe": '"%sretroarch.sh" -L %s%s_libretro.so "{ROM}"' % (launch, corep, core),
                      "lo": "", "start_dir": sd, "tag": _TAGS.get(sysid, sysid)}
    for sysid, (exe, lo) in _SPECIAL.items():
        out[sysid] = {"exe": exe.replace("{L}", launch), "lo": lo, "start_dir": sd,
                      "tag": _TAGS.get(sysid, sysid)}
    return out


def templates(root, home=None):
    """All launch templates: built-in defaults overridden by anything learned from the device's
    own existing shortcuts (so a custom emulator/core setup is respected)."""
    t = builtin_templates(home)
    t.update(learn_templates(root))
    return t


def _entry_pairs(appname, exe, start_dir, lo, icon, tags):
    aid = app_id(exe, appname)
    return aid, [
        ("appid", struct.unpack("<i", struct.pack("<I", aid))[0]),
        ("AppName", appname), ("Exe", exe), ("StartDir", start_dir),
        ("icon", icon), ("ShortcutPath", ""), ("LaunchOptions", lo),
        ("IsHidden", 0), ("AllowDesktopConfig", 1), ("AllowOverlay", 1),
        ("OpenVR", 0), ("Devkit", 0), ("DevkitGameID", ""), ("DevkitOverrideAppID", 0),
        ("LastPlayTime", 0),
        ("tags", [(str(i), t) for i, t in enumerate(tags)]),
    ]


def game_entry(appname, tmpl, rom_path, icon=""):
    """Build a Steam shortcut entry for a game from a learned template + its rom symlink path.
    Returns (app_id, entry_pairs)."""
    exe = tmpl["exe"].replace("{ROM}", rom_path)
    lo = tmpl["lo"].replace("{ROM}", rom_path)
    return _entry_pairs(appname, exe, tmpl["start_dir"], lo, icon,
                        [tmpl["tag"]] if tmpl.get("tag") else [])


def place_art(grid_dir, aid, portrait=None, hero=None, logo=None, landscape=None, icon=None):
    """Drop library art for `aid` into userdata/<id>/config/grid/. Safe (files only)."""
    os.makedirs(grid_dir, exist_ok=True)
    for src, dst in ((portrait, "%dp.png" % aid), (hero, "%d_hero.png" % aid),
                     (logo, "%d_logo.png" % aid), (landscape, "%d.png" % aid),
                     (icon, "%d_icon.png" % aid)):
        if src and os.path.exists(src):
            shutil.copy2(src, os.path.join(grid_dir, dst))


def steam_users(home=None):
    home = home or os.path.expanduser("~")
    base = os.path.join(home, ".local/share/Steam/userdata")
    if not os.path.isdir(base):
        base = os.path.join(home, ".steam/steam/userdata")
    return [d for d in glob.glob(os.path.join(base, "*")) if os.path.isdir(d) and
            os.path.basename(d).isdigit() and os.path.basename(d) != "0"]


if __name__ == "__main__":                # round-trip verifier: proves we won't corrupt it
    import sys
    raw = open(sys.argv[1], "rb").read()
    root = loads(raw)
    ok = dumps(root) == raw
    names = [v.encode("latin-1").decode("utf-8", "replace")
             for _i, e in _entries(root) for k, v in e if k.lower() == "appname"]
    print("round-trip byte-exact:", ok)
    print("shortcuts:", len(_entries(root)))
    print("names:", ", ".join(names[:12]) + (" …" if len(names) > 12 else ""))
    print("loadout present:", any(n == "Loadout" for n in names))
    sys.exit(0 if ok else 1)
