#!/usr/bin/env python3
# Put ROM shortcuts into their own per-console Steam collections and pull them OUT of
# Steam's built-in Favorites.
#
# Why not just let SRM do it: SRM needs Steam fully stopped to write categories, but in
# Gaming Mode stopping Steam tears down gamescope and its Xwayland servers, so SRM
# (Electron) can't even start. Collections are only JSON, and JSON needs no X server —
# so we write them ourselves while Steam is stopped.
#
# Console is derived from each shortcut's own launch path (.steam-shortcuts/<console>/).
import json, os, re, sys, base64, shutil, time

UID = "98492642"
VDF = os.path.expanduser("~/.local/share/Steam/userdata/%s/config/shortcuts.vdf" % UID)
CLOUD = os.path.expanduser(
    "~/.steam/steam/userdata/%s/config/cloudstorage/cloud-storage-namespace-1.json" % UID)
APPLY = "--apply" in sys.argv

CONSOLE_NAME = {"n64": "Nintendo 64", "gc": "GameCube", "snes": "Super Nintendo",
                "switch": "Nintendo Switch", "wii": "Wii", "gba": "Game Boy Advance",
                "nds": "Nintendo DS", "ps2": "PlayStation 2", "psp": "PSP",
                "psx": "PlayStation", "nes": "NES", "gbc": "Game Boy Color",
                # added with the 2026-07 console expansion; names match the
                # steamCategories set on each SRM parser so the two do not diverge
                "gb": "Game Boy", "genesis": "Sega Genesis",
                "mastersystem": "Master System", "gamegear": "Game Gear",
                "saturn": "Sega Saturn", "dreamcast": "Dreamcast",
                "xbox": "Xbox", "wiiu": "Wii U",
                "pc": "PC", "tools": "Tools"}


def parse_shortcuts(data):
    """minimal binary-VDF reader: yields (appid, appname, blob-of-paths)"""
    out, pos = [], 0
    def cstr():
        nonlocal pos
        e = data.index(b"\x00", pos); s = data[pos:e]; pos = e + 1; return s
    pos += 1; cstr()                                  # 0x00 + "shortcuts"
    while pos < len(data) and data[pos] != 0x08:
        pos += 1; cstr()                              # entry index
        appid, name, paths = None, None, []
        while pos < len(data) and data[pos] != 0x08:
            t = data[pos]; pos += 1; key = cstr().lower()
            if t == 0x01:
                v = cstr()
                if key == b"appname": name = v.decode("utf-8", "replace")
                else: paths.append(v.decode("utf-8", "replace"))
            elif t == 0x02:
                v = int.from_bytes(data[pos:pos+4], "little", signed=True); pos += 4
                if key == b"appid": appid = v
            elif t == 0x00:
                while pos < len(data) and data[pos] != 0x08:
                    nt = data[pos]; pos += 1; cstr()
                    if nt == 0x01: cstr()
                    elif nt == 0x02: pos += 4
                pos += 1
        pos += 1
        if appid is not None:
            out.append((appid & 0xFFFFFFFF, name, " ".join(paths)))
    return out


shortcuts = parse_shortcuts(open(VDF, "rb").read())
by_console = {}
for appid, name, blob in shortcuts:
    console = None
    m = re.search(r"\.steam-shortcuts/([a-z0-9]+)/", blob)
    if m:
        console = m.group(1)
    elif "/Games-local/" in blob:
        console = "pc"          # PC game launchers written by the Offline Manager
    elif "/Emulation/tools/manager/" in blob:
        console = "tools"       # the Offline Manager itself
    if not console:
        continue
    by_console.setdefault(console, []).append(appid)

print("ROM shortcuts found by console:")
for c, ids in sorted(by_console.items()):
    print("   %-8s %3d -> collection %r" % (c, len(ids), CONSOLE_NAME.get(c, c)))
rom_ids = {i for ids in by_console.values() for i in ids}
print("total ROM appids: %d\n" % len(rom_ids))

raw = json.load(open(CLOUD))
now = int(time.time())

# 1) strip ROM appids out of Steam's built-in Favorites
removed = 0
for entry in raw:
    if not (isinstance(entry, list) and len(entry) >= 2):
        continue
    if entry[0] != "user-collections.favorite":
        continue
    val = json.loads(entry[1].get("value") or "{}")
    before = list(val.get("added") or [])
    keep = [a for a in before if a not in rom_ids]
    removed = len(before) - len(keep)
    val["added"] = keep
    if APPLY:
        entry[1]["value"] = json.dumps(val, separators=(",", ":"))
        entry[1]["timestamp"] = now
        entry[1]["version"] = str(int(entry[1].get("version") or 0) + 1)
print("Favorites: %d ROM entries removed (%d remain)" % (removed, len(before) - removed))

# 2) create/replace one collection per console
existing = {e[0] for e in raw if isinstance(e, list) and e}
for c, ids in sorted(by_console.items()):
    cname = CONSOLE_NAME.get(c, c)
    cid = "srm-" + base64.b64encode(cname.encode()).decode().rstrip("=")
    key = "user-collections." + cid
    body = {"id": cid, "name": cname, "added": sorted(ids), "removed": []}
    payload = {"key": key, "timestamp": now, "value": json.dumps(body, separators=(",", ":")),
               "conflictResolutionMethod": "custom", "strMethodId": "union-collections",
               "version": "1"}
    print("  collection %-18s <- %3d games" % (cname, len(ids)))
    if APPLY:
        hit = False
        for entry in raw:
            if isinstance(entry, list) and entry and entry[0] == key:
                entry[1] = payload; hit = True; break
        if not hit:
            raw.append([key, payload])

# 3) franchise collections -- cut across consoles, built from the curated set only
FRANCHISE = {"Zelda": r"zelda"}
for fname, pat in sorted(FRANCHISE.items()):
    p = re.compile(pat, re.I)
    ids = sorted({appid for appid, name, blob in shortcuts
                  if re.search(r"\.steam-shortcuts/", blob) and (p.search(blob) or p.search(name))})
    if not ids:
        print("  collection %-18s <- no matches, skipped" % fname)
        continue
    cid = "srm-" + base64.b64encode(fname.encode()).decode().rstrip("=")
    key = "user-collections." + cid
    body = {"id": cid, "name": fname, "added": ids, "removed": []}
    payload = {"key": key, "timestamp": now, "value": json.dumps(body, separators=(",", ":")),
               "conflictResolutionMethod": "custom", "strMethodId": "union-collections",
               "version": "1"}
    print("  collection %-18s <- %3d games" % (fname, len(ids)))
    if APPLY:
        hit = False
        for entry in raw:
            if isinstance(entry, list) and entry and entry[0] == key:
                entry[1] = payload; hit = True; break
        if not hit:
            raw.append([key, payload])

if APPLY:
    shutil.copy(CLOUD, CLOUD + ".bak")
    json.dump(raw, open(CLOUD, "w"))
    print("\nWROTE collections (backup: cloud-storage-namespace-1.json.bak)")
else:
    print("\n(dry-run — pass --apply to write)")
