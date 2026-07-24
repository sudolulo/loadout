"""Walk the sidebar to the very bottom the way the D-pad does, and see whether anything
ends up with keyboard focus on a text entry (which is what raises Steam's keyboard)."""
import json, os, sys, tempfile
cfg = tempfile.mktemp(suffix=".json"); json.dump({}, open(cfg, "w"))
os.environ["LOADOUT_CONFIG"] = cfg
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gi; gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
import loadout as L

app = L.App(); app.show_all()
def pump():
    for _ in range(50):
        if not Gtk.events_pending(): break
        Gtk.main_iteration()
pump()

print("  sections: %s" % [n["key"] for n in app.nav])
fails = []
app.set_pane("sidebar"); pump()
for step in range(len(app.nav) + 2):          # walk PAST the end, like holding down
    app.pad_move(1); pump()
    f = app.get_focus()
    key = app.nav[app.nav_index]["key"]
    if isinstance(f, Gtk.Entry):
        print("  at section %-10s FOCUS IS AN ENTRY -> keyboard opens" % key)
        fails.append("sidebar walk onto %r focused a text entry" % key)
        break
print("  ended on section %r, focus=%s" % (app.nav[app.nav_index]["key"], type(app.get_focus()).__name__))

# now enter the page the way A does
app.set_pane("content"); pump()
print("  after entering content: focus=%s" % type(app.get_focus()).__name__)
if isinstance(app.get_focus(), Gtk.Entry):
    fails.append("entering the Storage page focused a text entry")

# and moving within the panel
for i in range(6):
    app.pad_move(1); pump()
    if isinstance(app.get_focus(), Gtk.Entry):
        fails.append("moving inside the panel focused a text entry (step %d)" % i)
        break
print("  after walking the panel: focus=%s" % type(app.get_focus()).__name__)

# --- structural guarantee: the fields are not focusable unless A was pressed on them
sp = app.settings_page   # the text fields live on Settings since the split
ents = [w for w in sp.focusables if isinstance(w, Gtk.Entry)]
print("  text fields: %d, focusable right now: %d (expect 0)"
      % (len(ents), sum(1 for e in ents if e.get_can_focus())))
assert all(not e.get_can_focus() for e in ents), "a text field is focusable while idle"
# even a direct grab_focus (what a stray GTK path would do) cannot take it
ents[0].grab_focus(); pump()
print("  after a stray grab_focus on a field: focus=%s" % type(app.get_focus()).__name__)
assert not isinstance(app.get_focus(), Gtk.Entry), "a stray grab_focus still focused the field"
# pressing A on it works, and B releases it again
sp.focus = 0; sp.toggle_current(); pump()
print("  A on the field: focused=%s" % sp.entry_focused())
assert sp.entry_focused(), "A did not open the field for typing"
app.go_back(); pump()
print("  B afterwards: focused=%s, focusable again=%s"
      % (sp.entry_focused(), any(e.get_can_focus() for e in ents)))
assert not sp.entry_focused() and not any(e.get_can_focus() for e in ents)
print("STRUCTURAL PASS")

os.unlink(cfg)
print("FAIL: " + "; ".join(fails) if fails else "PASS")
sys.exit(1 if fails else 0)
