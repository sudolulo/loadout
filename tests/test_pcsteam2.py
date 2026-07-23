"""PC games now become NORMAL non-Steam shortcuts: Steam runs the game's own executable, and
for Windows binaries a compat tool makes Steam own the Proton prefix (so saves land in
steamapps/compatdata like everything else). Shapes taken from deck1's real manifest."""
import json, os, shutil, sys, tempfile

root = tempfile.mkdtemp(prefix="pcsteam2-")
home = root + "/home"; os.makedirs(home)
G = home + "/Games"; E = home + "/Emulation"
cfg = root + "/c.json"
json.dump({"rom_local": E + "/.roms-local", "rom_sd": "off", "rom_nas": E + "/.roms-nas",
           "rom_union": E + "/roms", "rom_rclone_remote": "off", "pc_local": G + "/.pc-local",
           "pc_sd": "off", "pc_nas": G + "/.pc-nas", "pc_union": G + "/PC",
           "pc_rclone_remote": "off", "pc_manifest": G + "/PC/.manifest.json"}, open(cfg, "w"))
for d in (E + "/.roms-local", E + "/.roms-nas", E + "/roms", G + "/.pc-local", G + "/.pc-nas", G + "/PC"):
    os.makedirs(d, exist_ok=True)
MAN = {  # real shapes: a Linux AppImage, a "portable" that is actually a Windows exe, an installer
    "Celeste":            {"kind": "linux",    "entry": "Celeste.AppImage"},
    "Untitled Goose Game":{"kind": "portable", "entry": "Unleashed.exe"},
    "Spider-Man 2":       {"kind": "windows",  "entry": "Spider-Man2.exe"},
    "Some Repack":        {"kind": "wizard",   "entry": "setup.exe"},
}
json.dump(MAN, open(G + "/PC/.manifest.json", "w"))
for n, g in MAN.items():
    for base in (G + "/.pc-local", G + "/PC"):
        os.makedirs(os.path.join(base, n, os.path.dirname(g["entry"])) or os.path.join(base, n), exist_ok=True)
        open(os.path.join(base, n, g["entry"]), "w").write("bin")
ud = home + "/.local/share/Steam/userdata/1/config"; os.makedirs(ud)
sc = home + "/.local/share/Steam/config"; os.makedirs(sc)
open(sc + "/config.vdf", "w").write('"InstallConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n\t\t\t"Steam"\n\t\t\t{\n\t\t\t}\n\t\t}\n\t}\n}\n')
os.makedirs(home + "/.local/share/Steam/steamapps/common/Proton 10.0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import steam_shortcuts as S
open(ud + "/shortcuts.vdf", "wb").write(S.dumps([("shortcuts", [])]))
os.environ["LOADOUT_CONFIG"] = cfg; os.environ["HOME"] = home
import gi; gi.require_version("Gtk", "3.0")
import loadout as L, steam_compat as C

fails = []
# an installer must never become a pick
kept, _ = L.write_pc_picks({"Celeste", "Untitled Goose Game", "Spider-Man 2", "Some Repack"})
picks = sorted(os.listdir(L.PC_SF_DIR))
print("  picks: %s" % picks)
if "Some Repack" in picks: fails.append("an uninstalled repack became a pick")

added, removed = L.sync_steam()
ents = S._entries(S.loads(open(ud + "/shortcuts.vdf", "rb").read()))
print("  sync: +%d -%d  -> %d shortcuts" % (added, removed, len(ents)))
by = {str(S._ci(e, "AppName")): e for _i, e in ents}
for name in ("Celeste", "Untitled Goose Game", "Spider-Man 2"):
    e = by.get(name)
    if not e:
        fails.append("%s got no shortcut" % name); continue
    exe = str(S._ci(e, "Exe")).strip('"'); sd = str(S._ci(e, "StartDir")).strip('"')
    aid = S._ci(e, "appid") & 0xFFFFFFFF
    tool = C.get_tool(aid, home=home)
    print("    %-20s exe=%-46s tool=%s" % (name, exe.replace(home, "~"), tool or "-"))
    if not exe.startswith(L.PC_UNION): fails.append("%s does not run through the union" % name)
    if ".steam-shortcuts" in exe: fails.append("%s still points at a wrapper script" % name)
    if not os.path.exists(exe): fails.append("%s points at a missing file" % name)
    if sd != os.path.dirname(exe): fails.append("%s StartDir is wrong" % name)
    want_proton = exe.lower().endswith(".exe")
    if want_proton and not tool: fails.append("%s is a Windows exe with NO compat tool" % name)
    if not want_proton and tool: fails.append("%s is native but got a compat tool" % name)

# the prefix Steam will use is keyed on the recorded appid
rec = L.pc_record()
print("  recorded appids: %s" % {k: v for k, v in rec.items()})
if set(rec) != {"Celeste", "Untitled Goose Game", "Spider-Man 2"}:
    fails.append("ownership record wrong: %s" % sorted(rec))

# idempotent
a2, r2 = L.sync_steam()
print("  re-sync: +%d -%d (expect 0 0)" % (a2, r2))
if (a2, r2) != (0, 0): fails.append("not idempotent")

# a hand-made shortcut for a game in the same union folder must SURVIVE unpicking
hand_exe = os.path.join(L.PC_UNION, "Celeste", "Celeste.AppImage")
aid_h, pairs = S.game_shortcut("Celeste (my own)", hand_exe)
root_v = S.loads(open(ud + "/shortcuts.vdf", "rb").read())
ents2 = S._entries(root_v) + [("", pairs)]
for k in range(len(root_v)):
    if root_v[k][0].lower() == "shortcuts":
        root_v[k] = (root_v[k][0], [(str(i), e) for i, (_x, e) in enumerate(ents2)])
open(ud + "/shortcuts.vdf", "wb").write(S.dumps(root_v))
L.write_pc_picks(set())                       # unpick everything Loadout owns
a3, r3 = L.sync_steam()
names = [str(S._ci(e, "AppName")) for _i, e in S._entries(S.loads(open(ud + "/shortcuts.vdf", "rb").read()))]
print("  after unpicking all: +%d -%d  remaining: %s" % (a3, r3, names))
if "Celeste (my own)" not in names:
    fails.append("DELETED a hand-made shortcut Loadout did not create")
if any(n in names for n in ("Celeste", "Spider-Man 2")): fails.append("Loadout's own shortcuts survived unpicking")

shutil.rmtree(root, ignore_errors=True)
print("FAIL: " + "; ".join(fails) if fails else "PASS")
sys.exit(1 if fails else 0)
