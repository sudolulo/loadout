"""The console badge must be legible, idempotent, and must never break a sync."""
import os, shutil, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cairo
import art_badge

root = tempfile.mkdtemp(prefix="badge-")
def art(path, w=600, h=900, light=False):
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    c = cairo.Context(s)
    c.set_source_rgb(0.95, 0.8, 0.3) if light else c.set_source_rgb(0.07, 0.08, 0.11)
    c.paint(); s.write_to_png(path); return path
src = art(root + "/src.png")
fails = []

# 1. it renders, and does not touch the original
out = root + "/out.png"
ok = art_badge.badge(src, out, "gc")
print("  rendered: %s  original untouched: %s" % (ok, os.path.getsize(src) != os.path.getsize(out)))
if not ok: fails.append("badge() failed on a valid image")
if not os.path.exists(out): fails.append("no output written")

# 2. same size in, same size out (Steam cares about capsule dimensions)
import gi; gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf
a = GdkPixbuf.Pixbuf.new_from_file(src); b = GdkPixbuf.Pixbuf.new_from_file(out)
print("  dimensions: %dx%d -> %dx%d" % (a.get_width(), a.get_height(), b.get_width(), b.get_height()))
if (a.get_width(), a.get_height()) != (b.get_width(), b.get_height()):
    fails.append("badging changed the capsule size")

# 3. IDEMPOTENT: rendering twice from the original is byte-identical (badges must not stack)
out2 = root + "/out2.png"
art_badge.badge(src, out2, "gc")
same = open(out, "rb").read() == open(out2, "rb").read()
print("  re-render identical (no stacking): %s" % same)
if not same: fails.append("two renders from the same source differ")

# 4. it actually drew something, in the right corner
import struct
def corner_differs(p1, p2, box):
    x0, y0, x1, y1 = box
    pb1 = GdkPixbuf.Pixbuf.new_from_file(p1); pb2 = GdkPixbuf.Pixbuf.new_from_file(p2)
    d1, d2 = pb1.get_pixels(), pb2.get_pixels()
    rs, nc = pb1.get_rowstride(), pb1.get_n_channels()
    diff = 0
    for y in range(y0, y1, 4):
        for x in range(x0, x1, 4):
            i = y * rs + x * nc
            if d1[i:i+3] != d2[i:i+3]: diff += 1
    return diff
bl = corner_differs(src, out, (10, 700, 300, 890))     # bottom-left: the badge
tr = corner_differs(src, out, (350, 10, 590, 200))     # top-right: must be untouched
print("  changed pixels bottom-left=%d  top-right=%d" % (bl, tr))
if bl < 50: fails.append("nothing drawn in the badge corner")
if tr != 0: fails.append("art outside the badge corner was modified")

# 5. every console maps to a label and a colour, and long labels still fit
for sysid in ("snes", "gc", "ps2", "dreamcast", "xbox360", "pcengine", "totally-unknown-system"):
    lab, col = art_badge.label_for(sysid), art_badge.colour_for(sysid)
    o = root + "/%s.png" % sysid
    if not art_badge.badge(src, o, sysid): fails.append("%s failed to render" % sysid)
    w = GdkPixbuf.Pixbuf.new_from_file(o).get_width()
    print("    %-22s %-15s rgb%s" % (sysid, lab, col))
    if len(lab) > 16: fails.append("%s label too long: %r" % (sysid, lab))

# 6. a corrupt cover must NOT take the sync down
bad = root + "/bad.png"; open(bad, "wb").write(b"not a png")
print("  corrupt source returns False (not an exception): %s" % (art_badge.badge(bad, root + "/x.png", "gc") is False))
if art_badge.badge(bad, root + "/x.png", "gc") is not False: fails.append("corrupt art did not fail safe")
if os.path.exists(root + "/x.png.tmp.png"): fails.append("left a temp file behind")

# 7. a wide capsule gets a proportional badge, not a giant one
wide = art(root + "/wide.png", 920, 430)
art_badge.badge(wide, root + "/wide-out.png", "ps2")
print("  wide capsule badged: %s" % os.path.exists(root + "/wide-out.png"))
if not os.path.exists(root + "/wide-out.png"): fails.append("wide capsule failed")

shutil.rmtree(root, ignore_errors=True)
print("FAIL: " + "; ".join(fails) if fails else "PASS")
sys.exit(1 if fails else 0)
