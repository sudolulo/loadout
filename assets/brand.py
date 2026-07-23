#!/usr/bin/env python3
"""Loadout brand art generator (procedural, Pillow).

Emits the app icon (several sizes) and the Steam library card art — grid (portrait
capsule), hero (page banner) and logo (transparent wordmark). Regenerate with:
    python brand.py
Kept in-repo so the branding is reproducible, not a binary blob nobody can edit.
"""
import glob
import os

from PIL import Image, ImageDraw, ImageFont

OUT = os.path.dirname(os.path.abspath(__file__))
SS = 4  # supersample, then downscale with LANCZOS for crisp edges

# --- palette (matches the app CSS: dark slate + blue accent) ------------------------
BG_TOP, BG_BOT = (36, 44, 60), (16, 19, 26)
ACC_TOP, ACC_BOT = (96, 165, 250), (37, 99, 235)
SLATE_TOP, SLATE_BOT = (60, 71, 90), (39, 47, 62)
LIGHT, MUTE = (233, 235, 238), (150, 158, 170)


def font(px, bold=True):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    m = glob.glob("/usr/share/fonts/**/" + name, recursive=True)
    return ImageFont.truetype(m[0], px) if m else ImageFont.load_default()


def vgrad(w, h, top, bot):
    col = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(h - 1, 1)
        col.putpixel((0, y), tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
    return col.resize((w, h))


def grad_masked(w, h, top, bot, draw_white):
    """A vertical-gradient fill clipped to whatever `draw_white(mask_draw)` paints."""
    mask = Image.new("L", (w, h), 0)
    draw_white(ImageDraw.Draw(mask))
    out = vgrad(w, h, top, bot).convert("RGBA")
    out.putalpha(mask)
    return out


def tracked(draw, xy, text, fnt, fill, spacing, anchor_mid=True):
    """Draw letter-spaced text; returns total width. Centered on xy[0] if anchor_mid."""
    widths = [draw.textlength(c, font=fnt) for c in text]
    total = sum(widths) + spacing * (len(text) - 1)
    x = xy[0] - total / 2 if anchor_mid else xy[0]
    for c, wch in zip(text, widths):
        draw.text((x, xy[1]), c, font=fnt, fill=fill)
        x += wch + spacing
    return total


def glyph(size):
    """The mark: a bold 'load' arrow descending into the Deck's tray. RGBA, size x size."""
    W = H = size
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    cx = W // 2
    # tray / deck
    tw, th = int(W * 0.62), int(H * 0.185)
    tx, ty = (W - tw) // 2, int(H * 0.605)
    img.alpha_composite(grad_masked(
        W, H, SLATE_TOP, SLATE_BOT,
        lambda d: d.rounded_rectangle([tx, ty, tx + tw, ty + th], radius=int(th * 0.36), fill=255)))
    # tray opening (inset dark slot)
    sx, sw = tx + int(tw * 0.13), tw - 2 * int(tw * 0.13)
    ImageDraw.Draw(img).rounded_rectangle(
        [sx, ty + int(th * 0.13), sx + sw, ty + int(th * 0.30)],
        radius=int(th * 0.09), fill=(12, 14, 19, 165))
    # load arrow (rounded shaft + head), accent gradient, tip meeting the tray opening
    shaft_w = int(W * 0.11)
    s_top, s_bot = int(H * 0.165), int(H * 0.47)
    head_w, head_h = int(W * 0.30), int(H * 0.155)
    tip = ty + int(th * 0.16)

    def arrow(d):
        d.rounded_rectangle([cx - shaft_w // 2, s_top, cx + shaft_w // 2, s_bot],
                            radius=shaft_w // 2, fill=255)
        d.polygon([(cx - head_w // 2, tip - head_h), (cx + head_w // 2, tip - head_h),
                   (cx, tip)], fill=255)
    img.alpha_composite(grad_masked(W, H, ACC_TOP, ACC_BOT, arrow))
    # spark highlight at the top of the shaft
    ImageDraw.Draw(img).ellipse(
        [cx - int(W * 0.018), s_top - int(H * 0.005),
         cx + int(W * 0.018), s_top + int(H * 0.03)], fill=(191, 219, 254, 235))
    return img


def rounded_bg(w, h, radius, top, bot, border=True):
    base = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    base.alpha_composite(grad_masked(
        w, h, top, bot,
        lambda d: d.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)))
    if border:
        ImageDraw.Draw(base).rounded_rectangle(
            [1, 1, w - 2, h - 2], radius=radius, outline=(255, 255, 255, 18), width=max(2, w // 200))
    return base


def make_icon(size):
    w = size * SS
    img = rounded_bg(w, w, int(w * 0.225), BG_TOP, BG_BOT)
    img.alpha_composite(glyph(w))
    return img.resize((size, size), Image.LANCZOS)


def make_grid():
    w, h = 600 * SS, 900 * SS
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    img.alpha_composite(vgrad(w, h, BG_TOP, BG_BOT).convert("RGBA"))
    # accent glow behind the mark
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([w * 0.18, h * 0.10, w * 0.82, h * 0.52], fill=(37, 99, 235, 60))
    from PIL import ImageFilter
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(w * 0.06)))
    # mark
    g = glyph(int(w * 0.62))
    img.alpha_composite(g, ((w - g.width) // 2, int(h * 0.10)))
    d = ImageDraw.Draw(img)
    tracked(d, (w // 2, int(h * 0.66)), "LOADOUT", font(int(78 * SS)), LIGHT, int(10 * SS))
    tracked(d, (w // 2, int(h * 0.75)), "STEAM DECK LIBRARY MANAGER",
            font(int(23 * SS), bold=False), MUTE, int(6 * SS))
    return img.resize((600, 900), Image.LANCZOS).convert("RGB")


def make_hero():
    w, h = 1920 * SS, 620 * SS
    img = vgrad(w, h, BG_TOP, BG_BOT).convert("RGBA")
    g = glyph(int(h * 0.72))
    gx = int(w * 0.30) - g.width // 2
    img.alpha_composite(g, (gx, (h - g.height) // 2))
    d = ImageDraw.Draw(img)
    tracked(d, (int(w * 0.62), int(h * 0.34)), "LOADOUT", font(int(120 * SS)), LIGHT, int(14 * SS))
    tracked(d, (int(w * 0.62), int(h * 0.56)), "SET YOUR DECK'S LOADOUT",
            font(int(34 * SS), bold=False), MUTE, int(8 * SS))
    return img.resize((1920, 620), Image.LANCZOS).convert("RGB")


def make_logo():
    w, h = 1000 * SS, 300 * SS
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    g = glyph(int(h * 0.98))
    img.alpha_composite(g, (0, (h - g.height) // 2))
    d = ImageDraw.Draw(img)
    tracked(d, (int(w * 0.62), int(h * 0.30)), "LOADOUT", font(int(150 * SS)), LIGHT, int(16 * SS))
    return img.resize((1000, 300), Image.LANCZOS)


def main():
    for s in (1024, 512, 256, 128, 64):
        make_icon(s).save(os.path.join(OUT, "icon-%d.png" % s))
    make_grid().save(os.path.join(OUT, "grid-600x900.png"))
    make_hero().save(os.path.join(OUT, "hero-1920x620.png"))
    make_logo().save(os.path.join(OUT, "logo.png"))
    print("wrote:", ", ".join(sorted(os.listdir(OUT))))


if __name__ == "__main__":
    main()
