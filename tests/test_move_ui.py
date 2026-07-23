"""The UI side of a disk move: staging, the Where column, and what gets queued."""
import json, os, shutil, sys, tempfile
root = tempfile.mkdtemp(prefix="moveui-")
home = root + "/home"; card = root + "/card"
G, E = home + "/Games", home + "/Emulation"
os.makedirs(home); os.makedirs(card)
cfg = root + "/c.json"
json.dump({"rom_local": E + "/.roms-local", "rom_sd": card + "/Emulation/ROMs",
           "rom_nas": E + "/.roms-nas", "rom_union": E + "/roms", "rom_rclone_remote": "off",
           "pc_local": G + "/.pc-local", "pc_sd": card + "/Games/PC", "pc_nas": G + "/.pc-nas",
           "pc_union": G + "/PC", "pc_rclone_remote": "off",
           "pc_manifest": G + "/PC/.manifest.json", "default_target": "sd"}, open(cfg, "w"))
for d in (E + "/.roms-local", E + "/.roms-nas", E + "/roms", card + "/Emulation/ROMs",
          G + "/.pc-local", G + "/.pc-nas", G + "/PC", card + "/Games/PC"):
    os.makedirs(d, exist_ok=True)
# a PC game sitting on INTERNAL while the card exists
os.makedirs(G + "/.pc-local/Celeste"); open(G + "/.pc-local/Celeste/g.bin", "wb").write(b"x" * 1024)
os.environ["LOADOUT_CONFIG"] = cfg; os.environ["HOME"] = home
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gi; gi.require_version("Gtk", "3.0")
import loadout as L

fails = []
r = L.Row("pc", "Celeste")
print("  Celeste is on %r, chosen disk %r" % (r.disk, L.dest_label(r)))
if r.disk != "Internal": fails.append("expected it on Internal, got %r" % r.disk)

# default_target=sd, so the chosen disk already differs -> a move is staged
print("  move staged: %s" % L.move_staged(r))
if not L.move_staged(r): fails.append("no move staged when the chosen disk differs")

# flipping the choice back to where it already is cancels the move
r.dest = "internal"
print("  after choosing Internal (where it already is): staged=%s" % L.move_staged(r))
if L.move_staged(r): fails.append("still staged after choosing its current disk")

# a game with only one disk available can never stage a move
r.dest = "sd"
r2 = L.Row("pc", "Celeste"); r2.disk = ""      # not local
print("  not-local row staged: %s" % L.move_staged(r2))
if L.move_staged(r2): fails.append("staged a move for a game that is not on the Deck")

# destination path is on the card
print("  would move to: %s" % L.pull_dest_dir(r).replace(root, ""))
if L.pull_dest_dir(r) != card + "/Games/PC": fails.append("move destination is not the card")

# and the Where column says so
app = L.App()
pg = app.pc_page
pg.load([r])
where = pg._where(0) if pg.store[0][0] else "(unchecked)"
pg.store[0][0] = True
where = pg._where(0)
print("  Where column: %r" % where)
if where != "Internal → SD": fails.append("Where column shows %r" % where)
print("  moves_pending: %d row(s)" % len(pg.moves_pending()))
if len(pg.moves_pending()) != 1: fails.append("moves_pending did not report the row")

shutil.rmtree(root, ignore_errors=True)
print("FAIL: " + "; ".join(fails) if fails else "PASS")
sys.exit(1 if fails else 0)
