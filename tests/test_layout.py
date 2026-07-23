"""The app must FIT a Steam Deck's 1280x800 screen. Everything below or right of the edge is
silently clipped, which is how seven settings buttons became unreachable."""
import json, os, shutil, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
root = tempfile.mkdtemp(prefix="layout-"); home = root + "/home"; os.makedirs(home)
E, G = home + "/Emulation", home + "/Games"
cfg = root + "/c.json"
json.dump({"rom_local": E+"/.roms-local","rom_sd":"off","rom_nas":E+"/.roms-nas","rom_union":E+"/roms",
  "rom_rclone_remote":"off","pc_local":G+"/.pc-local","pc_sd":"off","pc_nas":G+"/.pc-nas",
  "pc_union":G+"/PC","pc_rclone_remote":"off","pc_manifest":G+"/PC/.manifest.json"}, open(cfg,"w"))
for d in (E+"/.roms-local/snes",E+"/.roms-nas",E+"/roms/snes",G+"/.pc-local",G+"/.pc-nas",G+"/PC"):
    os.makedirs(d, exist_ok=True)
# names long enough to blow out the Name column if it is not ellipsized
for n in ("The_Elder_Scrolls_III_Morrowind_Game_Of_The_Year_Edition_PAL_MULTI_REPACK_XBOX-WAR3X",
          "Short Game"):
    for base in (G+"/PC", G+"/.pc-local"):
        p2 = os.path.join(base, n); os.makedirs(p2, exist_ok=True)
        open(os.path.join(p2, "game.AppImage"), "wb").write(b"x"*64)
os.environ["LOADOUT_CONFIG"]=cfg; os.environ["HOME"]=home
import gi; gi.require_version("Gtk","3.0")
from gi.repository import Gtk
import loadout as L

app = L.App(); app.set_default_size(1280, 800); app.resize(1280, 800); app.show_all()
for _ in range(150):
    if not Gtk.events_pending(): break
    Gtk.main_iteration()
fails = []
W, H = 1280, 800
nw, nh = app.get_preferred_width()[1], app.get_preferred_height()[1]
print("  natural window: %dx%d  (screen %dx%d)" % (nw, nh, W, H))
if nh > H: fails.append("window wants %dpx of height - the bottom is clipped" % nh)
if nw > W: fails.append("window wants %dpx of width - the right edge is clipped" % nw)

for key, page in [(e["key"], e["page"]) for e in app.nav]:
    app.select_nav([e["key"] for e in app.nav].index(key))
    for _ in range(80):
        if not Gtk.events_pending(): break
        Gtk.main_iteration()
    ph = page.get_preferred_height()[1]
    if ph > H: fails.append("page %r needs %dpx height" % (key, ph))
    # every action must be inside the window
    for b in getattr(page, "btns", []):
        al = b.get_allocation()
        if al.y + al.height > H or al.x + al.width > W:
            fails.append("%s: button %r at y=%d x=%d is off-screen"
                         % (key, b.get_label(), al.y + al.height, al.x + al.width))
print("  every page fits, every button on screen: %s" % (not fails))

# measure a list page that is actually on screen: an unrealised page reports width 0
keys = [e["key"] for e in app.nav]
pg = None
for i, e in enumerate(app.nav):
    if getattr(e["page"], "view", None) is not None and len(getattr(e["page"], "store", []) or []):
        app.select_nav(i); pg = e["page"]
        for _ in range(120):
            if not Gtk.events_pending(): break
            Gtk.main_iteration()
        break
if pg is None:
    fails.append("no list page had rows to measure")
if pg is not None and getattr(pg, "view", None):
    cols = [(c.get_title(), c.get_width()) for c in pg.view.get_columns()]
    total = sum(w for _t, w in cols)
    print("  columns: %s  total=%d" % (", ".join("%s=%d" % c for c in cols), total))
    if total > W - 240:
        fails.append("columns total %dpx - Where/Size are pushed off" % total)
    if not any(t == "Where" and w > 0 for t, w in cols):
        fails.append("the Where column is not rendered")
shutil.rmtree(root, ignore_errors=True)
print("FAIL: " + "; ".join(fails) if fails else "PASS")
sys.exit(1 if fails else 0)
