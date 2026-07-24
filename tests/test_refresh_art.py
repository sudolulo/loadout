"""Refreshing artwork must cover every title Loadout manages - including a Deck whose art came
from somewhere else - and must never touch shortcuts Loadout did not create."""
import json, os, shutil, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
root = tempfile.mkdtemp(prefix="refresh-"); home = root + "/home"; os.makedirs(home)
E, G = home + "/Emulation", home + "/Games"
cfg = root + "/c.json"
json.dump({"rom_local": E+"/.roms-local","rom_sd":"off","rom_nas":E+"/.roms-nas","rom_union":E+"/roms",
  "rom_rclone_remote":"off","pc_local":G+"/.pc-local","pc_sd":"off","pc_nas":G+"/.pc-nas",
  "pc_union":G+"/PC","pc_rclone_remote":"off","pc_manifest":G+"/PC/.manifest.json"}, open(cfg,"w"))
for d in (E+"/.roms-local/snes",E+"/.roms-nas",E+"/roms/snes",G+"/.pc-local",G+"/.pc-nas",G+"/PC"):
    os.makedirs(d, exist_ok=True)
ud = home + "/.local/share/Steam/userdata/1/config"; os.makedirs(ud + "/grid")
os.environ["LOADOUT_CONFIG"]=cfg; os.environ["HOME"]=home
import gi; gi.require_version("Gtk","3.0")
import steam_shortcuts as S, cairo
import loadout as L

# art the way another tool would have left it: capsules present, nothing in Loadout's cache
def png(path, w=600, h=900):
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h); c = cairo.Context(s)
    c.set_source_rgb(0.1, 0.3, 0.6); c.paint(); s.write_to_png(path)

for g in ("Super Metroid", "Chrono Trigger"):
    open(E + "/roms/snes/%s.sfc" % g, "wb").write(b"x"*32)
    open(E + "/.roms-local/snes/%s.sfc" % g, "wb").write(b"x"*32)
    L.set_steam("snes", "%s.sfc" % g, True)
open(ud + "/shortcuts.vdf", "wb").write(S.dumps([("shortcuts", [])]))
L.sync_steam()

# a shortcut the USER made, which must be left completely alone
foreign_aid, pairs = S.game_shortcut("Someone Else's Game", home + "/whatever/game.exe")
r = S.loads(open(ud + "/shortcuts.vdf","rb").read())
ents = S._entries(r) + [("", pairs)]
for k in range(len(r)):
    if r[k][0].lower() == "shortcuts":
        r[k] = (r[k][0], [(str(i), e) for i, (_x, e) in enumerate(ents)])
open(ud + "/shortcuts.vdf","wb").write(S.dumps(r))
png(ud + "/grid/%dp.png" % foreign_aid)
foreign_before = open(ud + "/grid/%dp.png" % foreign_aid, "rb").read()

fails = []
managed = list(L.managed_shortcuts(S.loads(open(ud + "/shortcuts.vdf","rb").read())))
print("  managed shortcuts: %s" % sorted(n for _a, n, _s in managed))
if len(managed) != 2: fails.append("expected 2 managed, got %d" % len(managed))
if any(a == foreign_aid for a, _n, _s in managed):
    fails.append("claimed a shortcut Loadout did not create")

# stub the cover source: this is the network the offline pass refuses to use
cache = root + "/covers"; os.makedirs(cache)
served = []
def fake_cover(name):
    served.append(name)
    p = os.path.join(cache, "%s.png" % name.replace(" ", "_")); png(p); return p
L.steamgriddb.cover = fake_cover
L.steamgriddb.cached_cover = lambda n: None          # nothing cached: the deck2 situation

# 1. the offline pass must do NOTHING here, and must not call out
done, skipped, total = L.refresh_all_art(badge_only=True)
print("  offline pass: badged=%d of %d, network calls=%d (expect 0/0)" % (done, total, len(served)))
if done or served: fails.append("the offline pass fetched or wrote something")

# 2. the explicit refresh fetches and badges everything managed
seen = []
done, skipped, total = L.refresh_all_art(progress=lambda i, n, nm: seen.append(nm))
print("  explicit refresh: badged=%d skipped=%d total=%d  progress reported %d" % (done, skipped, total, len(seen)))
if done != 2: fails.append("badged %d of 2" % done)
if len(seen) != total: fails.append("progress not reported for every title")
for a, n, _s in managed:
    if not os.path.exists(os.path.join(ud, "grid", "%dp.png" % a)):
        fails.append("%s got no capsule" % n)

# 3. the user's own shortcut is untouched, byte for byte
after = open(ud + "/grid/%dp.png" % foreign_aid, "rb").read()
print("  foreign shortcut art untouched: %s" % (after == foreign_before))
if after != foreign_before: fails.append("MODIFIED a shortcut Loadout does not own")

# 4. running it twice is stable (badges must not stack)
first = open(os.path.join(ud, "grid", "%dp.png" % managed[0][0]), "rb").read()
L.refresh_all_art()
second = open(os.path.join(ud, "grid", "%dp.png" % managed[0][0]), "rb").read()
print("  second run identical: %s" % (first == second))
if first != second: fails.append("re-running changed the art (badges stacking?)")

shutil.rmtree(root, ignore_errors=True)
print("FAIL: " + "; ".join(fails) if fails else "PASS")
sys.exit(1 if fails else 0)
