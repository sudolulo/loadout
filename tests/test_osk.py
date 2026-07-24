"""Prove that walking onto the Storage page never focuses a text entry (which is what
pops Steam's on-screen keyboard), and that B unwinds instead of quitting."""
import os, sys
os.environ.setdefault("LOADOUT_CONFIG", "/tmp/claude-1000/-home-dev/3e7a9cf4-2826-4859-9326-f77905ed5f6e/scratchpad/osk-cfg.json")
import json
json.dump({}, open(os.environ["LOADOUT_CONFIG"], "w"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gi; gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
import loadout as L

app = L.App()
app.show_all()
while Gtk.events_pending():
    Gtk.main_iteration()

sp = app.settings_page   # the text fields live on Settings since the split
win = app

def focused_entry():
    f = win.get_focus()
    return f if isinstance(f, Gtk.Entry) else None

fails = []

# 1. landing on the page (what the sidebar preview does) must not focus an entry
sp.focus = 0
sp.highlight()
while Gtk.events_pending(): Gtk.main_iteration()
print("  after highlight() on field 0: focus=%s" % type(win.get_focus()).__name__)
if focused_entry(): fails.append("highlight() focused a text entry -> keyboard would open")

# 2. walking the whole panel must never focus an entry
for i in range(len(sp.focusables)):
    sp.focus = i
    sp.highlight()
    while Gtk.events_pending(): Gtk.main_iteration()
    if focused_entry():
        fails.append("walking to focusable %d focused an entry" % i)
print("  walked all %d focusables, entries focused: %d" % (len(sp.focusables), sum(1 for f in fails if "walking" in f)))

# 3. the painted cue still marks exactly one widget
marked = [i for i, w in enumerate(sp.focusables) if w.get_style_context().has_class("padsel")]
print("  painted cursor on: %s (expect exactly one)" % marked)
if len(marked) != 1: fails.append("padsel cue on %d widgets" % len(marked))

# 4. A on a text field DOES focus it (that's when the keyboard is wanted)
sp.focus = 0
sp.toggle_current()
while Gtk.events_pending(): Gtk.main_iteration()
print("  after A on field 0: focus=%s  entry_focused()=%s" % (type(win.get_focus()).__name__, sp.entry_focused()))
if not sp.entry_focused(): fails.append("A on a text field did NOT focus it")

# 5. B with the keyboard open must close it, NOT quit
quit_calls = []
app.quit_app = lambda: quit_calls.append(1)
app.go_back()
while Gtk.events_pending(): Gtk.main_iteration()
print("  B with keyboard open: entry_focused=%s quit_called=%d" % (sp.entry_focused(), len(quit_calls)))
if sp.entry_focused(): fails.append("B did not release the text entry")
if quit_calls: fails.append("B QUIT THE APP while the keyboard was open")

# 6. B in the content pane backs out to the sidebar, still no quit
app.set_pane("content")
app.go_back()
print("  B in content pane: pane=%s quit_called=%d" % (app.focus_pane, len(quit_calls)))
if app.focus_pane != "sidebar": fails.append("B did not back out to the sidebar")
if quit_calls: fails.append("B quit from the content pane")

# 7. B on the sidebar (outermost) DOES quit
app.go_back()
print("  B on sidebar: quit_called=%d (expect 1)" % len(quit_calls))
if len(quit_calls) != 1: fails.append("B on the sidebar did not quit")

# the Storage page carries no text fields at all, so it cannot raise the keyboard by any route
st = app.storage_page
n_entries = sum(1 for w in st.focusables if isinstance(w, Gtk.Entry))
print("  Storage page text fields: %d (expect 0 - actions only)" % n_entries)
if n_entries: fails.append("the Storage page still has %d text field(s)" % n_entries)

print("FAIL: " + "; ".join(fails) if fails else "PASS")
sys.exit(1 if fails else 0)
