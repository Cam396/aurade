#!/usr/bin/env python3
"""Draw every image the disk unlock screen shows.

The unlock screen runs inside the initramfs, before the root filesystem is
there, through plymouth's script plugin. That plugin can place an image, fade
it and move it, and very little else: it cannot lay out type in more than one
weight, cannot blur, and scales an image by sampling single points, which
turns small type into a jagged mess. So everything with a shape is drawn
here, ahead of time, once for each of a set of screen sizes, and the script
only picks the set nearest the screen and places it. Nothing it shows is ever
resampled except the photograph and the shade over it, which are soft to begin
with.

The photographs themselves are not copied: they are the wallpaper package's,
and the initramfs hook adds the ones photos.list names.

Usage: build-assets.py [--mock OUT.png] [--photo N] [--state STATE]
                       [--size WxH] [--no-build]

With no arguments it draws everything into build/drawn, packs that into
aurade-boot-drawn.tar for the package, and rewrites theme/photos.list and the
generated block of the script. --mock also composes the screen the way the
script does, from the same numbers, so a change can be judged without
booting anything.
"""

from __future__ import annotations

import argparse
import math
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.realpath(__file__))
PACKAGE = os.path.normpath(os.path.join(HERE, ".."))
REPO = os.path.normpath(os.path.join(PACKAGE, ".."))
THEME = os.path.join(PACKAGE, "theme")
SCRIPT = os.path.join(THEME, "aurade-boot.script")
#: Where the drawn files are written, and the archive the package installs
#: them from. Only the archive is kept in the repository.
DRAWN = os.path.join(PACKAGE, "build", "drawn")
ARCHIVE = os.path.join(PACKAGE, "aurade-boot-drawn.tar")
#: The photographs, where the repository keeps them. aurade-wallpapers is
#: built from these; its own directory only holds them once staged.
WALLPAPERS = os.path.join(REPO, "installer", "wallpapers")
TITLES = os.path.join(REPO, "installer", "wallpapers", "titles.tsv")
MARK = os.path.join(REPO, "installer", "assets", "aurade-mark.png")

FONT = "Adwaita Sans"

#: The sizes everything is drawn at, as multiples of a 1080 line screen. The
#: script lays the screen out at whichever of these is nearest the screen's
#: own, so no element is ever scaled at boot. Each value times every
#: reference length below is a whole number of pixels.
SCALES = (0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0)

#: The greeter's dark palette, so the screen before it is plainly the same
#: product: its ground, its accent and the colour it warns in.
GROUND = (18, 19, 24)
ACCENT = (209, 188, 255)
ERROR = (254, 180, 171)
ON_ACCENT = (18, 19, 24)

#: The photographs, in slot order, each with how strongly the shade lies over
#: it and how much extra dark pools behind the column. Picked for light that
#: reads as a beginning (two dusks, a dawn, three nights, two storms breaking)
#: and set by eye, one photograph at a time, against the mock; the printed
#: score is only there to say when a new one needs looking at.
PHOTOS = [
    ("place-vestrahorn", 1.0, 0.0),
    ("place-lofoten", 1.0, 0.75),
    ("place-fuji", 1.0, 0.0),
    ("wild-bioluminescence", 1.0, 0.45),
    ("place-torres", 0.8, 0.0),
    ("place-skye", 0.7, 0.25),
    ("quiet-beach", 0.85, 0.0),
    ("wild-storm", 1.0, 0.3),
]

#: Every fixed sentence: the file it becomes, its words, weight, size in
#: pixels of a 1080 line screen, opacity, and whether it stands on the
#: photograph (and so wears a shadow) or inside the field (and does not).
TEXT = {
    "title": ("Unlock this computer", "SemiBold", 28, 1.0, True),
    "subtitle": ("Type the disk passphrase to start AuraDE.", "Regular", 15, 0.80, True),
    "placeholder": ("Disk passphrase", "Regular", 15, 0.46, False),
    "error": ("That passphrase did not unlock the disk. Try it again.", "Medium", 13, 1.0, True),
    "capslock": ("Caps Lock is on", "Medium", 13, 1.0, True),
    "unlocking": ("Unlocking", "Medium", 14, 0.86, True),
    "starting": ("Starting AuraDE", "Medium", 14, 0.86, True),
    "shutdown": ("Shutting down", "Medium", 14, 0.86, True),
    "reboot": ("Restarting", "Medium", 14, 0.86, True),
}
WARNINGS = ("error", "capslock")

#: Lengths in pixels of a 1080 line screen. The script receives these through
#: its generated block, so the two cannot drift apart.
LAYOUT = {
    "field_y": 0.64,        # the field's centre, as a share of the height
    "mark_dy": -172,        # each element's centre, from the field's centre
    "title_dy": -98,
    "subtitle_dy": -64,
    "status_dy": 54,
    "field_w": 420,
    "field_h": 52,
    "inset": 22,            # where the dots and the placeholder start
    "dot": 8,
    "dot_step": 15,
    "caret_w": 2,
    "caret_h": 20,
    "go": 36,               # the round button at the field's right end
    "caption_margin": 28,
    "rise": 10,             # how far the column rises as it fades in
    "shadow_pad": 16,       # transparent margin round text that has a shadow
    "plain_pad": 4,         # and round text that does not
    "field_pad": 28,        # and round the field, for its shadow and glow
    "mark": 56,
    "mark_pad": 16,
}

#: The brightness the ground right behind a line of type may reach, at its
#: 95th percentile, once the shade is over it. White type with a soft shadow
#: reads cleanly below it on any of the photographs.
BEHIND_TYPE_P95 = 80


def px(reference: float, s: float) -> int:
    value = reference * s
    if abs(value - round(value)) > 1e-9:
        raise ValueError(f"{reference} at {s} is not a whole number of pixels")
    return int(round(value))


def rgba(colour, alpha: float):
    return (*colour, int(round(255 * alpha)))


# -- type -------------------------------------------------------------------

def glyphs(text: str, weight: str, size: float) -> Image.Image:
    """One line of type as coverage, through pango, unhinted, grey antialiased:
    the way GTK 4 draws the greeter on a high density screen."""
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "t.png")
        subprocess.run(
            ["pango-view", "--no-display", f"--font={FONT} {weight} {size:g}",
             f"--text={text}", "--foreground=#ffffff",
             "--background=transparent", "--margin=0", "--dpi=72",
             "--antialias=gray", "--hinting=none", "-o", out],
            check=True, capture_output=True)
        return Image.open(out).convert("RGBA").getchannel("A")


def shadow_layer(coverage: Image.Image, size, at, dy: float, sigma: float,
                 alpha: float) -> Image.Image:
    mask = Image.new("L", size, 0)
    mask.paste(coverage, (at[0], at[1] + int(round(dy))))
    if sigma > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(sigma))
    mask = mask.point(lambda v: int(round(v * alpha)))
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    layer.putalpha(mask)
    return layer


def text_image(key: str, s: float) -> Image.Image:
    text, weight, size, alpha, on_photo = TEXT[key]
    colour = ERROR if key in WARNINGS else (255, 255, 255)
    coverage = glyphs(text, weight, size * s)
    pad = px(LAYOUT["shadow_pad" if on_photo else "plain_pad"], s)
    canvas_size = (coverage.width + pad * 2, coverage.height + pad * 2)
    canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    if on_photo:
        # Two shadows, as the greeter's type on a photograph has: a tight one
        # that gives the edge, and a wide one that quiets busy ground behind.
        canvas = Image.alpha_composite(canvas, shadow_layer(
            coverage, canvas_size, (pad, pad), 1 * s, 1.0 * s, 0.50))
        canvas = Image.alpha_composite(canvas, shadow_layer(
            coverage, canvas_size, (pad, pad), 2 * s, 5.0 * s, 0.32))
    face = Image.new("RGBA", canvas_size, (*colour, 0))
    lit = Image.new("L", canvas_size, 0)
    lit.paste(coverage.point(lambda v: int(round(v * alpha))), (pad, pad))
    face.putalpha(lit)
    return Image.alpha_composite(canvas, face)


# -- shapes -----------------------------------------------------------------

SUPER = 4


def pill(w: int, h: int, fill, border=None, border_w: float = 0.0,
         top_light=None) -> Image.Image:
    """A rounded rectangle drawn four times over size and reduced, so its edge
    and its one pixel hairline are antialiased the way a browser draws them."""
    k = SUPER
    big = Image.new("RGBA", (w * k, h * k), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)
    radius = h * k / 2
    draw.rounded_rectangle((0, 0, w * k - 1, h * k - 1), radius=radius, fill=fill)
    if border is not None:
        ring = Image.new("RGBA", big.size, (0, 0, 0, 0))
        ImageDraw.Draw(ring).rounded_rectangle(
            (0, 0, w * k - 1, h * k - 1), radius=radius, outline=border,
            width=max(1, int(round(border_w * k))))
        big = Image.alpha_composite(big, ring)
    if top_light is not None:
        # A brighter hairline along the top only, as light catching an edge.
        edge = Image.new("RGBA", big.size, (0, 0, 0, 0))
        ImageDraw.Draw(edge).rounded_rectangle(
            (0, 0, w * k - 1, h * k - 1), radius=radius, outline=top_light,
            width=max(1, int(round(border_w * k))))
        fade = Image.linear_gradient("L").rotate(180).resize(big.size)
        fade = fade.point(lambda v: min(255, max(0, (v - 128) * 2)))
        edge.putalpha(ImageChops.multiply(edge.getchannel("A"), fade))
        big = Image.alpha_composite(big, edge)
    return big.resize((w, h), Image.LANCZOS)


def disc(d: int, fill) -> Image.Image:
    k = 8
    big = Image.new("RGBA", (d * k, d * k), (0, 0, 0, 0))
    ImageDraw.Draw(big).ellipse((0, 0, d * k - 1, d * k - 1), fill=fill)
    return big.resize((d, d), Image.LANCZOS)


def arrow(d: int, s: float, colour) -> Image.Image:
    """A right arrow, stroked with round ends, centred in a d by d square."""
    k = 8
    big = Image.new("RGBA", (d * k, d * k), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)
    c = d * k / 2
    stroke = 2.0 * s * k
    half = 6.5 * s * k
    wing = 5.0 * s * k
    tip = (c + half, c)
    lines = [((c - half, c), tip),
             ((tip[0] - wing, c - wing), tip),
             ((tip[0] - wing, c + wing), tip)]
    for a, b in lines:
        draw.line((a, b), fill=colour, width=int(round(stroke)))
        for x, y in (a, b):
            r = stroke / 2
            draw.ellipse((x - r, y - r, x + r, y + r), fill=colour)
    return big.resize((d, d), Image.LANCZOS)


def glow(image: Image.Image, colour, sigma: float, alpha: float) -> Image.Image:
    mask = image.getchannel("A").filter(ImageFilter.GaussianBlur(sigma))
    mask = mask.point(lambda v: int(round(v * alpha)))
    layer = Image.new("RGBA", image.size, (*colour, 0))
    layer.putalpha(mask)
    return layer


def field(state: str, s: float) -> Image.Image:
    """The passphrase field: dark glass, a hairline, and the round button.

    idle: waiting for nothing (unlocking).  focus: asking, nothing typed.
    ready: asking, something typed.  error: the last passphrase failed.
    """
    w, h = px(LAYOUT["field_w"], s), px(LAYOUT["field_h"], s)
    pad = px(LAYOUT["field_pad"], s)
    size = (w + pad * 2, h + pad * 2)
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    # Asking, the glass edge catches more light rather than taking a coloured
    # outline: a flat accent stroke laid over a photograph read as a form
    # field, not as glass. The accent stays for the caret and the button.
    asking = state in ("focus", "ready")
    body = pill(w, h, rgba((14, 15, 20), 0.60),
                border=rgba((255, 255, 255), 0.30 if asking else 0.10),
                border_w=1 * s, top_light=rgba((255, 255, 255), 0.62 if asking else 0.16))
    # box-shadow: 0 4px 18px rgba(0, 0, 0, 0.34)
    solid = Image.new("RGBA", size, (0, 0, 0, 0))
    solid.alpha_composite(body, (pad, pad))
    canvas = Image.alpha_composite(canvas, shadow_layer(
        solid.getchannel("A").point(lambda v: 255 if v > 8 else 0), size, (0, 0),
        4 * s, 9 * s, 0.34))
    if asking:
        halo = Image.new("RGBA", size, (0, 0, 0, 0))
        halo.alpha_composite(pill(w, h, (0, 0, 0, 0), border=rgba((255, 255, 255), 1.0),
                                  border_w=2 * s), (pad, pad))
        canvas = Image.alpha_composite(canvas, glow(halo, (255, 255, 255), 9 * s, 0.16))
        canvas.alpha_composite(body, (pad, pad))
    elif state == "error":
        ring_colour = ERROR
        ring = Image.new("RGBA", size, (0, 0, 0, 0))
        ring.alpha_composite(pill(w, h, (0, 0, 0, 0), border=rgba(ring_colour, 0.92),
                                  border_w=2 * s), (pad, pad))
        canvas = Image.alpha_composite(canvas, glow(ring, ring_colour, 5 * s, 0.55))
        canvas.alpha_composite(body, (pad, pad))
        canvas = Image.alpha_composite(canvas, ring)
    else:
        canvas.alpha_composite(body, (pad, pad))
    d = px(LAYOUT["go"], s)
    gx = pad + w - (h - d) // 2 - d
    gy = pad + (h - d) // 2
    if state == "ready":
        canvas.alpha_composite(disc(d, rgba(ACCENT, 1.0)), (gx, gy))
        canvas.alpha_composite(arrow(d, s, rgba(ON_ACCENT, 1.0)), (gx, gy))
    else:
        canvas.alpha_composite(disc(d, rgba((255, 255, 255), 0.08)), (gx, gy))
        canvas.alpha_composite(arrow(d, s, rgba((255, 255, 255), 0.42)), (gx, gy))
    return canvas


def caret(s: float) -> Image.Image:
    w, h = max(2, round(LAYOUT["caret_w"] * s)), px(LAYOUT["caret_h"], s)
    k = 8
    big = Image.new("RGBA", (w * k, h * k), (0, 0, 0, 0))
    ImageDraw.Draw(big).rounded_rectangle((0, 0, w * k - 1, h * k - 1),
                                          radius=w * k / 2, fill=rgba(ACCENT, 1.0))
    return big.resize((w, h), Image.LANCZOS)


def keyboard_icon(s: float) -> Image.Image:
    """A small keyboard, for the corner that names the layout: an outline, two
    rows of keys and a space bar, drawn eight times over size and reduced."""
    k = 8
    w, h = 18 * s, 12 * s
    pad = px(LAYOUT["plain_pad"], s)
    size = (int(math.ceil(w)) + pad * 2, int(math.ceil(h)) + pad * 2)
    big = Image.new("L", (size[0] * k, size[1] * k), 0)
    draw = ImageDraw.Draw(big)
    x0, y0 = pad * k, pad * k
    stroke = max(1.0, 1.25 * s) * k
    draw.rounded_rectangle((x0, y0, x0 + w * k - 1, y0 + h * k - 1), radius=2.5 * s * k,
                           outline=255, width=int(round(stroke)))
    key = 1.6 * s * k
    for row, count in ((0, 6), (1, 5)):
        span = (count - 1) * 2.6 * s * k
        left = x0 + (w * k - span) / 2
        y = y0 + (3.3 + row * 2.7) * s * k
        for i in range(count):
            x = left + i * 2.6 * s * k
            draw.rectangle((x - key / 2, y - key / 2, x + key / 2, y + key / 2), fill=255)
    bar_y = y0 + 8.9 * s * k
    draw.rounded_rectangle((x0 + 5 * s * k, bar_y - key / 2, x0 + 13 * s * k, bar_y + key / 2),
                           radius=key / 2, fill=255)
    coverage = big.resize(size, Image.LANCZOS)
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    canvas = Image.alpha_composite(canvas, shadow_layer(coverage, size, (0, 0), 1 * s, 1.0 * s, 0.55))
    face = Image.new("RGBA", size, (255, 255, 255, 0))
    face.putalpha(coverage.point(lambda v: int(v * 0.72)))
    return Image.alpha_composite(canvas, face)


def mark(s: float) -> Image.Image:
    size = px(LAYOUT["mark"], s)
    pad = px(LAYOUT["mark_pad"], s)
    source = Image.open(MARK).convert("RGBA").resize((size, size), Image.LANCZOS)
    canvas_size = (size + pad * 2, size + pad * 2)
    canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    canvas = Image.alpha_composite(canvas, shadow_layer(
        source.getchannel("A"), canvas_size, (pad, pad), 2 * s, 6 * s, 0.40))
    canvas.alpha_composite(source, (pad, pad))
    return canvas


def caption(title: str, note: str, s: float) -> Image.Image:
    """Where the photograph was taken, in the corner, as two quiet lines."""
    head = glyphs(title, "SemiBold", 13 * s)
    body = glyphs(note, "Regular", 12 * s)
    gap = max(1, round(2 * s))
    pad = px(LAYOUT["shadow_pad"], s)
    w = max(head.width, body.width) + pad * 2
    h = head.height + gap + body.height + pad * 2
    coverage = Image.new("L", (w, h), 0)
    coverage.paste(head, (pad, pad))
    coverage.paste(body, (pad, pad + head.height + gap))
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    canvas = Image.alpha_composite(canvas, shadow_layer(coverage, (w, h), (0, 0), 1 * s, 1.0 * s, 0.55))
    canvas = Image.alpha_composite(canvas, shadow_layer(coverage, (w, h), (0, 0), 2 * s, 5.0 * s, 0.30))
    face = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    lit = Image.new("L", (w, h), 0)
    lit.paste(head.point(lambda v: int(v * 0.94)), (pad, pad))
    lit.paste(body.point(lambda v: int(v * 0.66)), (pad, pad + head.height + gap))
    face.putalpha(lit)
    return Image.alpha_composite(canvas, face)


# -- the shade --------------------------------------------------------------

def smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def shade_alpha(x: float, y: float) -> float:
    """How dark the ground lies over the photograph at (x, y), both 0 to 1.

    The top quarter is left nearly as the photograph was taken. Below it the
    ground eases in, deepest at the bottom edge, with a soft pool of extra
    dark behind the column so a bright foreground cannot swallow the type,
    and a little at the left and right edges to frame a wide panel.
    """
    vertical = 0.10 + 0.60 * smoothstep((y - 0.22) / 0.78)
    cx, cy, rx, ry = 0.5, LAYOUT["field_y"] - 0.05, 0.30, 0.27
    d = math.hypot((x - cx) / rx, (y - cy) / ry)
    pool = 0.40 * (math.cos(min(d, 1.0) * math.pi) * 0.5 + 0.5)
    edge = max(0.0, (abs(x - 0.5) * 2 - 0.62) / 0.38)
    frame = 0.26 * edge * edge
    keep = (1 - vertical) * (1 - pool) * (1 - frame)
    return 1 - keep


def pool_alpha(x: float, y: float) -> float:
    """Extra dark behind the column alone, for a photograph whose busiest
    part happens to fall where the type goes."""
    cx, cy, rx, ry = 0.5, LAYOUT["field_y"] - 0.06, 0.24, 0.20
    d = math.hypot((x - cx) / rx, (y - cy) / ry)
    return 0.50 * (math.cos(min(d, 1.0) * math.pi) * 0.5 + 0.5)


def mask_image(alpha) -> Image.Image:
    """An alpha function as a small image the script stretches to the screen.
    It is smooth everywhere, so stretching it costs nothing it had."""
    w, h = 320, 180
    image = Image.new("RGBA", (w, h))
    pixels = image.load()
    for j in range(h):
        for i in range(w):
            a = alpha((i + 0.5) / w, (j + 0.5) / h)
            pixels[i, j] = (*GROUND, int(round(a * 255)))
    return image


def cover(photo: Image.Image, w: int, h: int, resample=Image.BILINEAR) -> Image.Image:
    scale = max(w / photo.width, h / photo.height)
    size = (max(w, math.ceil(photo.width * scale)), max(h, math.ceil(photo.height * scale)))
    resized = photo.resize(size, resample)
    x = (resized.width - w) // 2
    y = (resized.height - h) // 2
    return resized.crop((x, y, x + w, y + h))


def faded(layer: Image.Image, opacity: float) -> Image.Image:
    if opacity >= 1:
        return layer
    layer = layer.copy()
    layer.putalpha(layer.getchannel("A").point(lambda v: int(round(v * opacity))))
    return layer


def shaded(photo: Image.Image, opacity: float, pool: float, w: int, h: int) -> Image.Image:
    """The photograph as the script leaves it: covered, shaded, pooled."""
    screen = cover(photo.convert("RGBA"), w, h)
    screen = Image.alpha_composite(screen, faded(
        Image.open(os.path.join(DRAWN, "shade.png")).convert("RGBA").resize((w, h), Image.BILINEAR), opacity))
    if pool > 0:
        screen = Image.alpha_composite(screen, faded(
            Image.open(os.path.join(DRAWN, "pool.png")).convert("RGBA").resize((w, h), Image.BILINEAR), pool))
    return screen


def behind_type(image: Image.Image) -> int:
    """The worst 95th percentile brightness behind the title, the subtitle
    and the field, on a 1080 line screen, with the layout the script uses."""
    w, h = image.size
    grey = image.convert("L")
    fy = int(h * LAYOUT["field_y"])
    rows = ((LAYOUT["title_dy"], 22, 0.39), (LAYOUT["subtitle_dy"], 12, 0.36),
            (0, LAYOUT["field_h"] // 2, 0.39))
    worst = 0
    for dy, half, x0 in rows:
        area = grey.crop((int(w * x0), fy + dy - half, int(w * (1 - x0)), fy + dy + half))
        hist = area.histogram()
        total = sum(hist)
        seen = 0
        for value, count in enumerate(hist):
            seen += count
            if seen >= 0.95 * total:
                worst = max(worst, value)
                break
    return worst


# -- the catalogue ----------------------------------------------------------

def titles() -> dict[str, tuple[str, str]]:
    found = {}
    with open(TITLES, encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.rstrip("\n").split("\t")
            found[parts[0].removesuffix(".png")] = (parts[1], parts[4])
    return found


def photo_path(name: str) -> str:
    return os.path.join(WALLPAPERS, f"{name}.png")


# -- writing ----------------------------------------------------------------

def scale_dir(s: float) -> str:
    return f"s{int(round(s * 100)):03d}"


def save(image: Image.Image, *parts: str) -> None:
    path = os.path.join(DRAWN, *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    image.save(path, optimize=True)


def generated_block() -> str:
    lines = ["# BEGIN GENERATED by tools/build-assets.py; edit that, not this."]
    for i, s in enumerate(SCALES):
        lines.append(f'scales[{i}] = {s:g}; scale_dirs[{i}] = "{scale_dir(s)}";')
    lines.append(f"scale_count = {len(SCALES)};")
    for i, (_, opacity, pool) in enumerate(PHOTOS):
        lines.append(f"photo_shade[{i}] = {opacity:g}; photo_pool[{i}] = {pool:g};")
    lines.append(f"photo_count = {len(PHOTOS)};")
    for key, value in LAYOUT.items():
        lines.append(f"L.{key} = {value:g};")
    lines.append("# END GENERATED")
    return "\n".join(lines)


def rewrite_script() -> None:
    with open(SCRIPT, encoding="utf-8") as handle:
        source = handle.read()
    pattern = re.compile(r"# BEGIN GENERATED.*?# END GENERATED", re.S)
    if not pattern.search(source):
        raise SystemExit(f"{SCRIPT} has no generated block")
    updated = pattern.sub(lambda _: generated_block(), source)
    if updated != source:
        with open(SCRIPT, "w", encoding="utf-8") as handle:
            handle.write(updated)


def pack() -> None:
    """The drawn files as one archive, the same bytes for the same pictures:
    sorted, owned by root, dated 1970, so a rebuild that changed nothing
    changes nothing in the repository."""
    def plain(info: tarfile.TarInfo) -> tarfile.TarInfo:
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        info.mtime = 0
        info.mode = 0o755 if info.isdir() else 0o644
        return info

    paths = []
    for root, dirs, files in os.walk(DRAWN):
        dirs.sort()
        for name in sorted(files):
            paths.append(os.path.relpath(os.path.join(root, name), DRAWN))
    with tarfile.open(ARCHIVE, "w", format=tarfile.GNU_FORMAT) as archive:
        for relative in sorted(paths):
            archive.add(os.path.join(DRAWN, relative), arcname=relative,
                        recursive=False, filter=plain)


def build() -> None:
    if os.path.isdir(DRAWN):
        shutil.rmtree(DRAWN)
    os.makedirs(DRAWN)
    places = titles()
    save(mask_image(shade_alpha), "shade.png")
    save(mask_image(pool_alpha), "pool.png")
    with open(os.path.join(THEME, "photos.list"), "w", encoding="utf-8") as handle:
        handle.write("# The wallpapers the initramfs hook adds, in slot order.\n")
        for name, _, _ in PHOTOS:
            handle.write(f"{name}\n")
    for name, opacity, pool in PHOTOS:
        score = behind_type(shaded(Image.open(photo_path(name)), opacity, pool, 1920, 1080))
        flag = "" if score <= BEHIND_TYPE_P95 else "  look at this one"
        print(f"{name:24s} shade {opacity:<4g} pool {pool:<4g} behind the type {score}{flag}")
    for s in SCALES:
        d = scale_dir(s)
        for key in TEXT:
            save(text_image(key, s), d, f"{key}.png")
        for state in ("idle", "focus", "ready", "error"):
            save(field(state, s), d, f"field-{state}.png")
        save(disc(px(LAYOUT["dot"], s), (255, 255, 255, 242)), d, "dot.png")
        save(caret(s), d, "caret.png")
        save(mark(s), d, "mark.png")
        save(keyboard_icon(s), d, "keyboard.png")
        for i, (name, _, _) in enumerate(PHOTOS):
            title, note = places[name]
            save(caption(title, note, s), d, f"caption-{i}.png")
    if os.path.exists(SCRIPT):
        rewrite_script()
    pack()


# -- the mock ---------------------------------------------------------------

def pick_scale(w: int, h: int) -> float:
    u = min(h / 1080, w / 1600)
    best = SCALES[0]
    for s in SCALES:
        if abs(s - u) < abs(best - u) - 1e-9:
            best = s
    return best


def load(s: float, name: str) -> Image.Image:
    return Image.open(os.path.join(DRAWN, scale_dir(s), name)).convert("RGBA")


def put_centred(screen: Image.Image, image: Image.Image, cx: float, cy: float) -> None:
    screen.alpha_composite(image, (int(cx - image.width / 2), int(cy - image.height / 2)))


def mock(out: str, slot: int, state: str, w: int, h: int) -> None:
    s = pick_scale(w, h)
    L = {k: (v if k == "field_y" else v * s) for k, v in LAYOUT.items()}
    name, opacity, pool = PHOTOS[slot]
    screen = shaded(Image.open(photo_path(name)), opacity, pool, w, h)
    cx = w / 2
    fy = int(h * LAYOUT["field_y"])
    put_centred(screen, load(s, "mark.png"), cx, fy + L["mark_dy"])
    if state in ("focus", "ready", "error", "idle"):
        put_centred(screen, load(s, "title.png"), cx, fy + L["title_dy"])
        put_centred(screen, load(s, "subtitle.png"), cx, fy + L["subtitle_dy"])
        put_centred(screen, load(s, f"field-{state}.png"), cx, fy)
        left = cx - L["field_w"] / 2 + L["inset"]
        if state == "focus":
            hint = load(s, "placeholder.png")
            screen.alpha_composite(hint, (int(left - L["plain_pad"]), int(fy - hint.height / 2)))
            car = load(s, "caret.png")
            screen.alpha_composite(car, (int(left - L["caret_w"] - 2 * s), int(fy - car.height / 2)))
        elif state in ("ready", "idle"):
            dot = load(s, "dot.png")
            for i in range(11):
                screen.alpha_composite(dot, (int(left + i * L["dot_step"]), int(fy - dot.height / 2)))
            if state == "ready":
                car = load(s, "caret.png")
                screen.alpha_composite(car, (int(left + 11 * L["dot_step"] - 1 * s), int(fy - car.height / 2)))
        status = {"error": "error.png", "idle": "unlocking.png"}.get(state)
        if status:
            put_centred(screen, load(s, status), cx, fy + L["status_dy"])
    elif state == "starting":
        put_centred(screen, load(s, "starting.png"), cx, fy + L["title_dy"])
    cap = load(s, f"caption-{slot}.png")
    m = L["caption_margin"]
    pad = L["shadow_pad"]
    screen.alpha_composite(cap, (int(m - pad), int(h - m - cap.height + pad)))
    screen.convert("RGB").save(out)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock")
    parser.add_argument("--photo", type=int, default=0)
    parser.add_argument("--state", default="ready",
                        choices=("boot", "focus", "ready", "error", "idle", "starting"))
    parser.add_argument("--size", default="1920x1080")
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args()
    if not args.no_build:
        build()
    if args.mock:
        w, h = (int(v) for v in args.size.split("x"))
        mock(args.mock, args.photo, args.state, w, h)
    return 0


if __name__ == "__main__":
    sys.exit(main())
