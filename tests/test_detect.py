"""Loadout must list a playable game it can SEE in a folder, without waiting for a manifest -
and must still keep un-installed repacks out."""
import os, shutil, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json, tempfile
root = tempfile.mkdtemp(prefix="detect-")
home = root + "/home"; G = home + "/Games"; E = home + "/Emulation"
os.makedirs(home)
cfg = root + "/c.json"
json.dump({"rom_local": E + "/.roms-local", "rom_sd": "off", "rom_nas": E + "/.roms-nas",
           "rom_union": E + "/roms", "rom_rclone_remote": "off", "pc_local": G + "/.pc-local",
           "pc_sd": "off", "pc_nas": G + "/.pc-nas", "pc_union": G + "/PC",
           "pc_rclone_remote": "off", "pc_manifest": G + "/PC/.manifest.json"}, open(cfg, "w"))
for d in (E + "/.roms-local", E + "/.roms-nas", E + "/roms", G + "/.pc-local", G + "/.pc-nas", G + "/PC"):
    os.makedirs(d, exist_ok=True)
os.environ["LOADOUT_CONFIG"] = cfg; os.environ["HOME"] = home
import gi; gi.require_version("Gtk", "3.0")
import loadout as L

def mk(name, files):          # files: {relpath: size}
    for base in (G + "/.pc-local", G + "/PC"):
        for rel, sz in files.items():
            p = os.path.join(base, name, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "wb").write(b"x" * sz)

mk("Celeste",       {"Celeste.AppImage": 900})                       # native
mk("Spider-Man",    {"Spider-Man2.exe": 5000, "UnityCrashHandler.exe": 50,
                     "_CommonRedist/vcredist_x64.exe": 900})          # game + noise
mk("Morrowind",     {"Morrowind.exe": 4000, "Setup.exe": 6000})       # installer is BIGGER
mk("FitGirl Repack",{"setup.exe": 9000, "fg-01.bin": 100})            # repack: nothing runnable
mk("Portal 2",      {"portal2.sh": 20, "bin/linux64/engine.so": 5000})# shell launcher at top
mk("Mystery",       {"data/readme.txt": 10})                          # nothing at all
mk("Repack B",      {"MD5/QuickSFV.EXE": 8000, "fg-02.bin": 100})     # repack: only a checksum tool
mk("Repack C",      {"Game.Updater.exe": 7000, "setup.exe": 9000})    # updater is not the game

fails = []
for name, want_kind, why in (
        ("Celeste", "linux", "native AppImage"),
        ("Spider-Man", "windows", "largest non-installer exe"),
        ("Morrowind", "windows", "must not pick the bigger Setup.exe"),
        ("Portal 2", "linux", "top-level .sh launcher"),
):
    e = L.detect_entry(os.path.join(L.PC_UNION, name))
    print("  %-16s -> %-22s (%s)" % (name, e or "(nothing)", why))
    if not e: fails.append("%s: detected nothing" % name)
    elif L.pc_kind(e) != want_kind: fails.append("%s: kind %s" % (name, L.pc_kind(e)))
if L.detect_entry(os.path.join(L.PC_UNION, "Morrowind")) != "Morrowind.exe":
    fails.append("picked the installer over the game")
for name in ("FitGirl Repack", "Mystery", "Repack B", "Repack C"):
    e = L.detect_entry(os.path.join(L.PC_UNION, name))
    print("  %-16s -> %s (must be nothing)" % (name, e or "(nothing)"))
    if e: fails.append("%s: would launch %r" % (name, e))

# and the list the app actually shows
rows = [r.name for r in L.scan()[0]]
print("  PC page lists: %s" % sorted(rows))
for want in ("Celeste", "Spider-Man", "Morrowind", "Portal 2"):
    if want not in rows: fails.append("%s missing from the PC page" % want)
for no in ("FitGirl Repack", "Mystery", "Repack B", "Repack C"):
    if no in rows: fails.append("%s should not be listed" % no)

# a manifest that says "not runnable yet" still wins over detection
json.dump({"Celeste": {"kind": "wizard", "entry": "setup.exe"}}, open(G + "/PC/.manifest.json", "w"))
import importlib; importlib.reload(L)
rows2 = [r.name for r in L.scan()[0]]
print("  with manifest marking Celeste as a wizard: %s" % sorted(rows2))
if "Celeste" in rows2: fails.append("manifest 'wizard' verdict was ignored")

shutil.rmtree(root, ignore_errors=True)
print("FAIL: " + "; ".join(fails) if fails else "PASS")
sys.exit(1 if fails else 0)
