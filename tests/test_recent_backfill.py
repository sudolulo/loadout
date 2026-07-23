"""Games added recently but never played must reach the Deck's home shelf, stamped with the time
they were ACTUALLY added - and a real play time must never be overwritten."""
import json, os, shutil, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

root = tempfile.mkdtemp(prefix="recent-")
home = root + "/home"; os.makedirs(home)
E, G = home + "/Emulation", home + "/Games"
cfg = root + "/c.json"
json.dump({"rom_local": E + "/.roms-local", "rom_sd": "off", "rom_nas": E + "/.roms-nas",
           "rom_union": E + "/roms", "rom_rclone_remote": "off", "pc_local": G + "/.pc-local",
           "pc_sd": "off", "pc_nas": G + "/.pc-nas", "pc_union": G + "/PC",
           "pc_rclone_remote": "off", "pc_manifest": G + "/PC/.manifest.json",
           "recent_days": 14}, open(cfg, "w"))
for d in (E + "/.roms-local/snes", E + "/.roms-nas", E + "/roms/snes",
          G + "/.pc-local", G + "/.pc-nas", G + "/PC"):
    os.makedirs(d, exist_ok=True)
ud = home + "/.local/share/Steam/userdata/1/config"; os.makedirs(ud)
os.environ["LOADOUT_CONFIG"] = cfg; os.environ["HOME"] = home
import steam_shortcuts as S
import gi; gi.require_version("Gtk", "3.0")
import loadout as L

NOW = time.time()
GAMES = {"Recent Game": NOW - 2 * 86400,      # added 2 days ago  -> should surface
         "Old Game":    NOW - 60 * 86400,     # added 60 days ago -> too old, leave alone
         "Played Game": NOW - 1 * 86400}      # added recently BUT already has a real play time
for g in GAMES:
    open(E + "/.roms-local/snes/%s.sfc" % g, "w").write("rom")
    open(E + "/roms/snes/%s.sfc" % g, "w").write("rom")
    L.set_steam("snes", "%s.sfc" % g, True)
    os.utime(os.path.join(L.SF_DIR, "snes", "%s.sfc" % g), (GAMES[g], GAMES[g]), follow_symlinks=False)
open(ud + "/shortcuts.vdf", "wb").write(S.dumps([("shortcuts", [])]))
open(ud + "/localconfig.vdf", "w").write(
    '"UserLocalConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n\t\t\t"Steam"\n\t\t\t{\n\t\t\t\t"apps"\n\t\t\t\t{\n\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n}\n')

fails = []
L.sync_steam()                                  # first sync: adds all three
# simulate the pre-fix world: wipe the stamps, then give one a genuine play time
ents = S._entries(S.loads(open(ud + "/shortcuts.vdf", "rb").read()))
PLAYED_AT = int(NOW - 3600)
out = []
for idx, e in ents:
    nm = str(S._ci(e, "AppName"))
    val = PLAYED_AT if nm == "Played Game" else 0
    out.append((idx, [(k, val if k.lower() == "lastplaytime" else v) for k, v in e]))
r = S.loads(open(ud + "/shortcuts.vdf", "rb").read())
for k in range(len(r)):
    if r[k][0].lower() == "shortcuts":
        r[k] = (r[k][0], [(str(i), e) for i, (_x, e) in enumerate(out)])
open(ud + "/shortcuts.vdf", "wb").write(S.dumps(r))
print("  before: %s" % {str(S._ci(e,"AppName")): S._ci(e,"LastPlayTime")
                        for _i, e in S._entries(S.loads(open(ud+"/shortcuts.vdf","rb").read()))})

L.sync_steam()                                  # the backfill pass runs here
after = {str(S._ci(e,"AppName")): S._ci(e,"LastPlayTime")
         for _i, e in S._entries(S.loads(open(ud+"/shortcuts.vdf","rb").read()))}
print("  after : %s" % after)

if after["Recent Game"] != int(GAMES["Recent Game"]):
    fails.append("recent game stamped %s, expected its add time %d"
                 % (after["Recent Game"], GAMES["Recent Game"]))
if after["Old Game"] != 0:
    fails.append("a game added 60 days ago was surfaced as recent")
if after["Played Game"] != PLAYED_AT:
    fails.append("overwrote a REAL play time (%s != %s)" % (after["Played Game"], PLAYED_AT))
print("  recent game -> its add time: %s" % (after["Recent Game"] == int(GAMES["Recent Game"])))
print("  60-day-old game left at 0  : %s" % (after["Old Game"] == 0))
print("  real play time preserved   : %s" % (after["Played Game"] == PLAYED_AT))

# and it must be idempotent: a second run must not keep rewriting
L.sync_steam()
again = {str(S._ci(e,"AppName")): S._ci(e,"LastPlayTime")
         for _i, e in S._entries(S.loads(open(ud+"/shortcuts.vdf","rb").read()))}
if again != after: fails.append("not idempotent: %s -> %s" % (after, again))
print("  idempotent                 : %s" % (again == after))

# localconfig got the same stamp so the desktop client agrees
lc = open(ud + "/localconfig.vdf").read()
print("  localconfig LastPlayed entries: %d" % lc.count('"LastPlayed"'))
if lc.count('"LastPlayed"') < 1: fails.append("no localconfig stamp written")

shutil.rmtree(root, ignore_errors=True)
print("FAIL: " + "; ".join(fails) if fails else "PASS")
sys.exit(1 if fails else 0)
