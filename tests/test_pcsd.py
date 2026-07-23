"""A PC game must be able to live on the SD card: detected there, pulled there, freed from
wherever it actually is."""
import json, os, shutil, sys, tempfile

root = tempfile.mkdtemp(prefix="pcsd-")
home = os.path.join(root, "home"); os.makedirs(home)
card = os.path.join(root, "card"); os.makedirs(card)
G, E = home + "/Games", home + "/Emulation"
cfg = os.path.join(root, "config.json")
json.dump({
    "rom_local": E + "/.roms-local", "rom_sd": "off", "rom_nas": E + "/.roms-nas",
    "rom_union": E + "/roms", "rom_rclone_remote": "off",
    "pc_local": G + "/.pc-local", "pc_sd": card + "/Games/PC", "pc_nas": G + "/.pc-nas",
    "pc_union": G + "/PC", "pc_rclone_remote": "off", "pc_manifest": G + "/PC/.manifest.json",
    "default_target": "sd",
}, open(cfg, "w"))
for d in (E + "/.roms-local", E + "/.roms-nas", E + "/roms", G + "/.pc-local",
          G + "/.pc-nas", G + "/PC", card + "/Games/PC"):
    os.makedirs(d, exist_ok=True)
# one game already ON THE CARD, one only on the NAS
os.makedirs(card + "/Games/PC/OnCard/x", exist_ok=True)
os.makedirs(G + "/.pc-nas/Streamed", exist_ok=True)
json.dump({"OnCard": {"kind": "linux", "entry": "run.sh"},
           "Streamed": {"kind": "linux", "entry": "run.sh"}},
          open(G + "/PC/.manifest.json", "w"))
os.environ["LOADOUT_CONFIG"] = cfg; os.environ["HOME"] = home
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gi; gi.require_version("Gtk", "3.0")
import loadout as L

fails = []
print("  PC tiers (SD first): %s" % [p.replace(root, "") for p in L.PC_LOCALS])
if L.PC_LOCALS[0] != card + "/Games/PC": fails.append("SD is not searched first")
if not L.HAVE_PC_SD: fails.append("HAVE_PC_SD false with a card present")

# 1. a game on the card reads as local, labelled SD
r = L.Row("pc", "OnCard")
print("  OnCard:   is_local=%s disk=%r dirs=%s" % (r.is_local, r.disk, [d.replace(root,'') for d in r.local_dirs]))
if not r.is_local: fails.append("a game on the card is not seen as local")
if r.disk != "SD": fails.append("card game labelled %r, expected 'SD'" % r.disk)

# 2. a NAS-only game defaults to the card and can be flipped to internal
r2 = L.Row("pc", "Streamed")
print("  Streamed: is_local=%s dest=%r -> %s" % (r2.is_local, r2.dest,
      L.pull_dest_dir(r2).replace(root, "")))
if r2.is_local: fails.append("a NAS-only game reported local")
if L.pull_dest_dir(r2) != card + "/Games/PC": fails.append("pull did not target the card")
r2.dest = "internal"
print("  Streamed: dest='internal' -> %s" % L.pull_dest_dir(r2).replace(root, ""))
if L.pull_dest_dir(r2) != G + "/.pc-local": fails.append("flip to internal ignored")
if not L.row_has_sd(r2): fails.append("row_has_sd false for a PC row with a card")

# 3. a game on BOTH disks lists both, so a free clears both
os.makedirs(G + "/.pc-local/OnCard", exist_ok=True)
r3 = L.Row("pc", "OnCard")
print("  OnCard on both disks: %d dirs" % len(r3.local_dirs))
if len(r3.local_dirs) != 2: fails.append("a free would leave a copy behind (%d dirs)" % len(r3.local_dirs))

# 4. no card => everything collapses to internal, exactly as before
json.dump({**json.load(open(cfg)), "pc_sd": "off"}, open(cfg, "w"))
for m in [m for m in list(sys.modules) if m == "loadout"]:
    del sys.modules[m]
import loadout as L2
r4 = L2.Row("pc", "Streamed")
print("  no card: tiers=%s dest=%r -> %s" % ([p.replace(root,'') for p in L2.PC_LOCALS],
      r4.dest, L2.pull_dest_dir(r4).replace(root, "")))
if L2.HAVE_PC_SD: fails.append("HAVE_PC_SD true with pc_sd off")
if L2.pull_dest_dir(r4) != G + "/.pc-local": fails.append("no-card pull did not go internal")
if L2.row_has_sd(r4): fails.append("row_has_sd true with no card")

shutil.rmtree(root, ignore_errors=True)
print("FAIL: " + "; ".join(fails) if fails else "PASS")
sys.exit(1 if fails else 0)
