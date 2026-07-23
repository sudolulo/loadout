"""Everything a user needs must be settable from the Storage page - no config.json editing."""
import json, os, shutil, stat, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
root = tempfile.mkdtemp(prefix="settings-")
home = root + "/home"; os.makedirs(home)
E, G = home + "/Emulation", home + "/Games"
cfg = root + "/c.json"
json.dump({"rom_local": E + "/.roms-local", "rom_sd": "off", "rom_nas": E + "/.roms-nas",
           "rom_union": E + "/roms", "rom_rclone_remote": "off", "pc_local": G + "/.pc-local",
           "pc_sd": "off", "pc_nas": G + "/.pc-nas", "pc_union": G + "/PC",
           "pc_rclone_remote": "off", "pc_manifest": G + "/PC/.manifest.json"}, open(cfg, "w"))
for d in (E + "/.roms-local", E + "/.roms-nas", E + "/roms", G + "/.pc-local", G + "/.pc-nas", G + "/PC"):
    os.makedirs(d, exist_ok=True)
os.environ["LOADOUT_CONFIG"] = cfg; os.environ["HOME"] = home
import gi; gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
import loadout as L

app = L.App(); app.show_all()
def pump():
    for _ in range(60):
        if not Gtk.events_pending(): break
        Gtk.main_iteration()
pump()
sp = app.storage_page
fails = []

labels = [type(w).__name__ for w in sp.focusables]
print("  Storage page focusables: %d entries + %d buttons"
      % (sum(1 for w in sp.focusables if isinstance(w, Gtk.Entry)),
         sum(1 for w in sp.focusables if isinstance(w, Gtk.Button))))
for name in ("e_host", "e_share", "e_pcshare", "e_saves", "e_user", "e_pass", "e_sgdb"):
    if not hasattr(sp, name): fails.append("missing field %s" % name)

# 1. the SteamGridDB key: written 0600, never into config.json
sp.e_sgdb.set_text("SECRETKEY123")
sp._save_sgdb_key()
kp = home + "/.config/loadout/steamgriddb.key"
mode = oct(stat.S_IMODE(os.stat(kp).st_mode)) if os.path.exists(kp) else "-"
print("  SGDB key file: %s  mode=%s  content=%r" % (os.path.exists(kp), mode, open(kp).read().strip() if os.path.exists(kp) else ""))
if not os.path.exists(kp): fails.append("SGDB key not written")
elif stat.S_IMODE(os.stat(kp).st_mode) != 0o600: fails.append("SGDB key mode %s" % mode)
if "SECRETKEY123" in open(cfg).read(): fails.append("SECRET LEAKED into config.json")
if sp.e_sgdb.get_text(): fails.append("key left in the field after saving")

# 2. disk policy is settable without editing a file
before = L.DEFAULT_DEST
sp.cycle_default_disk(); pump()
after = json.load(open(cfg)).get("default_target")
print("  default disk: %s -> config now %r, button says %r" % (before, after, sp.b_disk.get_label()))
if after not in ("sd", "internal"): fails.append("default_target not persisted")
sp.toggle_sd(); pump()
c = json.load(open(cfg))
print("  SD toggle -> rom_sd=%r pc_sd=%r, button says %r" % (c.get("rom_sd"), c.get("pc_sd"), sp.b_sd.get_label()))
if c.get("rom_sd") != "" or c.get("pc_sd") != "": fails.append("SD toggle did not persist both keys")

# 3. saves path round-trips through the config
sp.e_host.set_text("nas.local"); sp.e_share.set_text("games/roms")
sp.e_saves.set_text("games/Saves")
sp._remote_name = "games"
try:
    import nas_setup
    nas_setup.write_remote = lambda *a, **k: {}
    nas_setup.remote_path = lambda n, p: "%s:%s" % (n, p)
    sp._apply_smb(persist=True)
except Exception as e:
    fails.append("apply failed: %s" % e)
saved = json.load(open(cfg)).get("saves_rclone_remote")
print("  saves path saved as: %r" % saved)
if saved != "games:games/Saves": fails.append("saves remote not saved (%r)" % saved)

# 4. an empty PC list explains itself
print("  empty PC text: %r" % L._pc_empty_text()[:70])
if not L._pc_empty_text().strip(): fails.append("empty PC page says nothing")

shutil.rmtree(root, ignore_errors=True)
print("FAIL: " + "; ".join(fails) if fails else "PASS")
sys.exit(1 if fails else 0)
