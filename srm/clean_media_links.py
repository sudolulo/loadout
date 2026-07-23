#!/usr/bin/env python3
# Remove redundant links/copies on the MEDIA side only. qBittorrent data is never
# touched — those torrents must keep seeding to reach minimum seed requirements.
#
# Three classes handled:
#   1. old-tree files hardlinked into the live library  -> drop the dup link (frees 0 B)
#   2. old-tree files that are separate copies of library files -> real reclaim
#   3. GameCube discs duplicated into Games/ROMs/wii/    -> drop the wii/ copy
# Files UNIQUE to the old tree are never deleted (they exist nowhere else).
import os, re, sys

OLD = "/mnt/Tank/media/ROMs"
NEW = "/mnt/Tank/media/Games/ROMs"
QBIT = "/mnt/Tank/downloads/qbit"
APPLY = "--apply" in sys.argv


def walk(root):
    for r, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(r, f)
            try:
                yield p, os.stat(p)
            except Exception:
                pass


def is_gamecube(path):
    try:
        with open(path, "rb") as f:
            h = f.read(2 * 1024 * 1024)
    except Exception:
        return False
    return len(h) > 0x20 and h[0x1C:0x20] == b"\xc2\x33\x9f\x3d"


new_by_ino, new_by_sig = {}, {}
for p, st in walk(NEW):
    new_by_ino[st.st_ino] = p
    new_by_sig.setdefault((st.st_size, os.path.basename(p).lower()), p)
qbit_ino = {st.st_ino for _, st in walk(QBIT)}

drop_links, drop_copies = [], []
for p, st in walk(OLD):
    if st.st_ino in qbit_ino:          # seeding data — never touch
        continue
    if st.st_ino in new_by_ino:
        drop_links.append((p, st.st_size))
    elif (st.st_size, os.path.basename(p).lower()) in new_by_sig:
        drop_copies.append((p, st.st_size))

# GameCube discs sitting in wii/ that already exist in gc/
gc_names = set(os.listdir(os.path.join(NEW, "gc"))) if os.path.isdir(os.path.join(NEW, "gc")) else set()
dup_wii = []
wii_dir = os.path.join(NEW, "wii")
for fn in sorted(os.listdir(wii_dir)):
    p = os.path.join(wii_dir, fn)
    if not os.path.isfile(p) or fn not in gc_names:
        continue
    if fn.lower().endswith((".iso", ".nkit.iso", ".gcm", ".rvz")) and is_gamecube(p):
        dup_wii.append((p, os.stat(p).st_size))

# 4. mis-grabbed games that got into the library (demos, guides, wrong region/sequel).
# Restricted to the consoles where individual grabs landed — NEVER the set-populated
# ones (snes/nes/gba/gbc/n64/tg16), where a loose pattern could wipe thousands of ROMs.
BADGRAB = re.compile(
    r"Trade Demo|\(Demo\)|\bKiosk\b|Prima Official|Prima Guide|BradyGames|Walkthrough|"
    r"Signature Series|\beGuide\b|Album by Various Artists|\bRockman\b|\bCHT\b|Chinese|"
    r"Biohazard|patched English Maniac|THEATRHYTHM|Final Fantasy VIII English Release|"
    r"^SoulCalibur III|LocoRoco - Midnight Carnival|Etrian Odyssey III|Super Scribblenauts|"
    r"Mega Man ZX Advent", re.I)
GRAB_CONSOLES = ("switch", "ps2", "psp", "nds", "gc", "wii", "saturn", "psx", "dreamcast",
                 "switch-updates")
badgrab = []
for c in GRAB_CONSOLES:
    d = os.path.join(NEW, c)
    if not os.path.isdir(d):
        continue
    for fn in sorted(os.listdir(d)):
        fp = os.path.join(d, fn)
        if os.path.isfile(fp) and BADGRAB.search(fn):
            badgrab.append((fp, os.path.getsize(fp)))

print("1. old-tree links into live library : %5d files, %6.1f GB  (frees 0 B, removes dup)"
      % (len(drop_links), sum(s for _, s in drop_links) / 1e9))
print("2. old-tree separate copies         : %5d files, %6.1f GB  (real reclaim)"
      % (len(drop_copies), sum(s for _, s in drop_copies) / 1e9))
for p, s in drop_copies:
    print("     %6.2fGB  %s" % (s / 1e9, p[len(OLD) + 1:][:70]))
print("3. GameCube dupes in Games/ROMs/wii : %5d files, %6.1f GB"
      % (len(dup_wii), sum(s for _, s in dup_wii) / 1e9))
print("4. mis-grabbed games in the library  : %5d files, %6.1f GB  (torrents keep seeding)"
      % (len(badgrab), sum(s for _, s in badgrab) / 1e9))
for fp, s2 in badgrab:
    print("     %6.2fGB  %s" % (s2 / 1e9, fp[len(NEW) + 1:][:70]))

if APPLY:
    n = 0
    for p, _ in drop_links + drop_copies + dup_wii + badgrab:
        try:
            os.remove(p); n += 1
        except Exception as e:
            print("   failed:", p[:60], e)
    # prune empty dirs left behind in the old tree
    for r, ds, fs in os.walk(OLD, topdown=False):
        if not os.listdir(r) and r != OLD:
            try: os.rmdir(r)
            except Exception: pass
    print("\nDELETED %d file(s). qbit untouched — torrents keep seeding." % n)
else:
    print("\n(dry-run — pass --apply)")
