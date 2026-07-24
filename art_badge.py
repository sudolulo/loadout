"""Stamp a small console badge into the corner of a Steam capsule.

Every ROM Loadout puts in Steam is a non-Steam shortcut with box art fetched from SteamGridDB,
so in the library a NES game and a PS2 game look exactly alike — the system is nowhere on the
tile. This burns a compact corner badge into the artwork, the way a store capsule carries a
platform mark: rounded, inset from the corner, tinted to the console's own family colour, and
legible over both dark and blown-out box art.

Drawn with **cairo**, which GTK already requires, so it runs ON the Deck. (The older netplay
badge needed Pillow, which SteamOS does not have, so its whole workflow was: copy the art off
the Deck, stamp it on a machine with Pillow, copy it back.)

Rendering is always done from the ORIGINAL cached cover, never from a file already on disk in
the grid folder — badging a badged image would stack badges every time a sync ran.
"""
import math
import os

import cairo
import gi

gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gdk", "3.0")
from gi.repository import GdkPixbuf, Gdk  # noqa: E402

# Console families, by their own colours -- the badge reads as part of the art rather than as an
# error message pasted on top. Value is (label, r, g, b).
_FAMILY = {
    "nintendo":    (0xE6, 0x00, 0x12),
    "playstation": (0x00, 0x70, 0xD1),
    "xbox":        (0x10, 0x7C, 0x10),
    "sega":        (0x00, 0x89, 0xCF),
    "atari":       (0xE4, 0x00, 0x2B),
    "neogeo":      (0xC8, 0x10, 0x2E),
    "pc":          (0x6E, 0x7B, 0x8B),
    "other":       (0x3B, 0x82, 0xF6),
}
_SYSTEM_FAMILY = {
    "snes": "nintendo", "nes": "nintendo", "n64": "nintendo", "gb": "nintendo",
    "gbc": "nintendo", "gba": "nintendo", "nds": "nintendo", "n3ds": "nintendo",
    "gc": "nintendo", "wii": "nintendo", "wiiu": "nintendo", "switch": "nintendo",
    "famicom": "nintendo", "sfc": "nintendo", "virtualboy": "nintendo", "pokemini": "nintendo",
    "psx": "playstation", "ps2": "playstation", "ps3": "playstation", "ps4": "playstation",
    "psp": "playstation", "psvita": "playstation",
    "xbox": "xbox", "xbox360": "xbox",
    "genesis": "sega", "megadrive": "sega", "mastersystem": "sega", "gamegear": "sega",
    "sega32x": "sega", "segacd": "sega", "saturn": "sega", "dreamcast": "sega",
    "atari2600": "atari", "atari7800": "atari", "lynx": "atari", "jaguar": "atari",
    "neogeo": "neogeo", "ngp": "neogeo", "ngpc": "neogeo",
    "pc": "pc",
}
# What the badge says. Short enough to stay a badge and not become a banner.
LABELS = {
    "snes": "SNES", "nes": "NES", "n64": "N64", "gb": "GAME BOY", "gbc": "GBC", "gba": "GBA",
    "nds": "DS", "n3ds": "3DS", "gc": "GAMECUBE", "wii": "WII", "wiiu": "WII U",
    "switch": "SWITCH", "famicom": "FAMICOM", "sfc": "SUPER FAMICOM", "virtualboy": "VIRTUAL BOY",
    "psx": "PS1", "ps2": "PS2", "ps3": "PS3", "ps4": "PS4", "psp": "PSP", "psvita": "VITA",
    "xbox": "XBOX", "xbox360": "XBOX 360",
    "genesis": "GENESIS", "megadrive": "MEGA DRIVE", "mastersystem": "MASTER SYSTEM",
    "gamegear": "GAME GEAR", "sega32x": "32X", "segacd": "SEGA CD", "saturn": "SATURN",
    "dreamcast": "DREAMCAST", "atari2600": "ATARI 2600", "neogeo": "NEO GEO",
    "tg16": "TURBOGRAFX-16", "pcengine": "PC ENGINE", "arcade": "ARCADE", "pc": "PC",
}


def label_for(system):
    return LABELS.get(system, str(system).upper().replace("-", " ")[:14])


def colour_for(system):
    return _FAMILY[_SYSTEM_FAMILY.get(system, "other")]


def _rounded(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def badge(src, dst, system, corner="bottom-left"):
    """Write `src` to `dst` with a console badge burned into one corner.

    Returns True on success. Never raises: art is a nicety, and a cover that cannot be decoded
    must not take a Steam sync down with it.
    """
    try:
        pb = GdkPixbuf.Pixbuf.new_from_file(src)
        w, h = pb.get_width(), pb.get_height()
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(surface)
        Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
        cr.paint()

        text = label_for(system)
        r, g, b = colour_for(system)
        # scale everything off the capsule's own size so 600x900 grid art and a 460x215 wide
        # capsule both get a badge in proportion
        unit = min(w, h)
        pad_x, pad_y = unit * 0.065, unit * 0.065   # inset, not jammed into the corner
        font_px = max(11.0, unit * 0.055)
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(font_px)
        track = font_px * 0.09                       # letter-spacing, drawn glyph by glyph
        widths = [cr.text_extents(c).x_advance for c in text]
        text_w = sum(widths) + track * (len(text) - 1)
        ext = cr.text_extents("H")
        text_h = ext.height
        bx_w = text_w + font_px * 1.30
        bx_h = text_h + font_px * 1.05
        bx = pad_x if "left" in corner else w - pad_x - bx_w
        by = h - pad_y - bx_h if "bottom" in corner else pad_y

        # shadow, then plate. The edge is a white hairline rather than a thick coloured ring:
        # a store capsule's platform mark is a quiet inlay, not a warning label. The console's
        # colour lives in the chip instead, which is enough to tell families apart at a glance.
        cr.push_group()
        _rounded(cr, bx, by + unit * 0.007, bx_w, bx_h, bx_h * 0.32)
        cr.set_source_rgba(0, 0, 0, 0.5)
        cr.fill()
        cr.pop_group_to_source()
        cr.paint_with_alpha(0.85)

        _rounded(cr, bx, by, bx_w, bx_h, bx_h * 0.32)
        cr.set_source_rgba(0.04, 0.05, 0.07, 0.88)   # near-black plate: readable over anything
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, 0.17)
        cr.set_line_width(max(1.0, unit * 0.0028))
        cr.stroke()

        cr.save()                                    # a soft top highlight, like moulded plastic
        _rounded(cr, bx, by, bx_w, bx_h, bx_h * 0.32)
        cr.clip()
        hl = cairo.LinearGradient(0, by, 0, by + bx_h * 0.55)
        hl.add_color_stop_rgba(0, 1, 1, 1, 0.10)
        hl.add_color_stop_rgba(1, 1, 1, 1, 0.0)
        cr.set_source(hl)
        cr.paint()
        cr.restore()

        # a colour chip on the left edge carries the console family at a glance
        chip = bx_h * 0.36
        cr.set_source_rgb(r / 255, g / 255, b / 255)
        cr.arc(bx + bx_h * 0.46, by + bx_h / 2, chip / 2, 0, 2 * math.pi)
        cr.fill()

        x = bx + bx_h * 0.46 + chip / 2 + font_px * 0.38
        y = by + bx_h / 2 + text_h / 2
        cr.set_source_rgb(1, 1, 1)
        for ch, adv in zip(text, widths):
            cr.move_to(x, y)
            cr.show_text(ch)
            x += adv + track

        surface.flush()
        tmp = dst + ".tmp.png"
        surface.write_to_png(tmp)
        os.replace(tmp, dst)
        return True
    except Exception:
        try:
            os.remove(dst + ".tmp.png")
        except OSError:
            pass
        return False
