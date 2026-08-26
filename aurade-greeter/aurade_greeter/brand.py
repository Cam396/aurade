"""The parts of the interface that are drawn rather than styled.

Four things, all of them taken from the mark rather than invented next to it:

  the aurora, three soft fields of light in the palette's own primary,
  tertiary and secondary tones, which is the ring behind the `A` opened out
  to fill a window;

  the ribbon rule, a one-pixel hairline running lilac to aqua, which is the
  gradient across the `A` reduced to its smallest useful form and used to
  separate the chrome from the content;

  the mark and the wordmark, painted from the real artwork, with the wordmark
  carried as an ink mask so the logotype takes whichever colour the surface
  behind it needs instead of being pinned to one background;

  signal arcs, because a Wi-Fi list where every row is a number is a list
  nobody reads, and four arcs are read at a glance.

Colours come from `tokens.py`, the same generated role table the stylesheet is
built from, so nothing drawn here can drift away from anything styled there.
"""

from __future__ import annotations

import math
import os

from . import tokens as T

ASSET_DIRS = [
    os.environ.get("AURADE_ASSET_DIR", ""),
    "/usr/local/share/aurade",
    os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "assets"),
]

_surfaces: dict[str, object] = {}


def asset(name: str) -> str | None:
    for directory in ASSET_DIRS:
        if not directory:
            continue
        path = os.path.normpath(os.path.join(directory, name))
        if os.path.exists(path):
            return path
    return None


def _png(name: str):
    """A cairo surface for one asset, loaded once."""
    if name in _surfaces:
        return _surfaces[name]
    import cairo  # noqa: PLC0415  - only needed when something is drawn

    path = asset(name)
    surface = None
    if path:
        try:
            surface = cairo.ImageSurface.create_from_png(path)
        except (OSError, MemoryError):
            surface = None
    _surfaces[name] = surface
    return surface


# --------------------------------------------------------------------------
# Geometry and colour, kept free of cairo so they can be checked headlessly
# --------------------------------------------------------------------------


def aurora_fields(dark: bool) -> list[tuple[str, float, float, float, float]]:
    """The three light fields: role, x, y, radius and peak opacity.

    Positions are fractions of the drawing area, so the composition holds at
    any window size. Opacity is deliberately low: this sits behind text that
    has to stay at its contrast ratio, and a backdrop that forces the
    foreground to shout is a backdrop that failed.
    """
    scheme = T.scheme(dark)
    # Measured rather than chosen. At 0.30 the light aurora blended to 2.35 L*
    # against the surface behind it, which on an ordinary panel is not a
    # backdrop, it is nothing. 0.42 puts it at about 3.3 L*, and body text over
    # it still measures 15.5:1, so there is no contrast cost to pay for it.
    strong = 0.42 if dark else 0.42
    return [
        (scheme["primary_container"], 0.18, 0.12, 0.62, strong),
        (scheme["tertiary_container"], 0.86, 0.30, 0.55, strong * 0.9),
        (scheme["secondary_container"], 0.55, 0.95, 0.70, strong * 0.7),
    ]


def aurora_drift(phase: float, index: int) -> tuple[float, float]:
    """How far a field has wandered at this point in the cycle.

    A slow figure-of-eight per field, each at a different rate so the three
    never line up and the motion never reads as a loop. The amplitude is a
    few percent of the window: enough to notice if you look, not enough to
    pull the eye off the thing the page is actually asking.
    """
    rate = 1.0 + index * 0.37
    return (
        math.sin(phase * rate) * 0.035,
        math.sin(phase * rate * 2.0 + index) * 0.022,
    )


# --------------------------------------------------------------------------
# The wallpaper
# --------------------------------------------------------------------------
#
# Twenty eight photographs, and the reason they are the installer's background
# rather than the installed desktop's is resolution: 1376x768 is what the model
# emits, which is soft on a monitor and perfectly good behind a window that is
# mostly covered by the interface in front of it.
#
# The rules that make a photograph safe to put behind an interface:
#
#   nothing readable ever sits on it. The page content is on an opaque sheet
#   and the chrome at the top and the bottom is on an opaque band, so every
#   contrast ratio in the theme test is still the ratio that is on the screen.
#   The photograph is visible around all of it and under none of it.
#
#   the aurora stays, at about half strength. Twenty eight pictures with
#   nothing in common is the whole point of the set, and it is also a way to
#   make an installer look like twenty eight different products. A wash of the
#   brand's own light over all of them is what makes them one.
#
#   it is off wherever the ground is a decision rather than a taste. High
#   contrast exists so somebody can read, and a photograph is the opposite of
#   that. The black scheme exists so an OLED panel can leave its pixels unlit,
#   and a photograph lights every one of them.


WALLPAPER_DIRS = [
    os.environ.get("AURADE_WALLPAPER_DIR", ""),
    "/usr/local/share/aurade/wallpapers",
    os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..",
                 "wallpapers"),
]

#: The index, written by `tools/wallpaper-manifest.py` and committed. Reading
#: the directory instead would work until the day a half-written file is in it.
WALLPAPER_MANIFEST = "manifest.tsv"

#: How much of the surface colour goes over the photograph.
#:
#: Different per scheme because the problem is different per scheme. This set
#: is dark: mean luminance runs 0.037 to 0.204, and there is not one bright
#: picture in it. Behind the dark scheme that is nearly free. Behind the light
#: scheme a dark picture at the edges of a pale interface is a hole in the
#: window, so the light veil is the heavier of the two.
#:
#: Neither number is a legibility control - the sheet and the bands are - so
#: both are taste, and both were set by rendering the result and looking at
#: it. The light one started at 0.62 and Vestrahorn came out as a rumour: a
#: veil strong enough that the photograph might as well not be there is a
#: photograph that might as well not be there.
WALLPAPER_VEIL_LIGHT = 0.40
WALLPAPER_VEIL_DARK = 0.34

#: The aurora, over a photograph. Full strength on top of a picture is three
#: coloured clouds in front of a landscape; half of it is a cast over one.
WALLPAPER_AURORA = 0.5

#: How far the opaque band behind the chrome takes to fade into the picture.
#:
#: The band itself is measured from the chrome rather than set here, because
#: the chrome is as tall as its text and its text is as tall as the person
#: reading it asked for: at 200% scale a fixed band would end half way up the
#: wordmark. This is only the distance over which it stops.
#:
#: 130 rather than something tidier because the fade has to be longer than the
#: band is tall or it reads as an edge, and the band is around sixty pixels.
WALLPAPER_FADE = 130

_wallpapers: list[dict[str, str]] | None = None
#: One scaled surface, keyed by the file and the size it was scaled for. The
#: window is repainted many times a second and the picture is rescaled when
#: the window changes shape, which is roughly never.
_wall_cache: dict[str, object] = {"key": None, "surface": None}


def wallpaper_dir() -> str | None:
    """The first directory that has a manifest in it."""
    for directory in WALLPAPER_DIRS:
        if not directory:
            continue
        path = os.path.normpath(os.path.join(directory, WALLPAPER_MANIFEST))
        if os.path.exists(path):
            return os.path.dirname(path)
    return None


def wallpapers() -> list[dict[str, str]]:
    """Every picture in the manifest that is actually on this machine.

    A row whose file is missing is dropped rather than reported: the image
    build stages the set and the manifest together, so the only way to be
    holding one without the other is to be running from a source tree that is
    part way through something.
    """
    global _wallpapers  # noqa: PLW0603 - read once per process, like _surfaces
    if _wallpapers is not None:
        return _wallpapers

    _wallpapers = []
    directory = wallpaper_dir()
    if directory is None:
        return _wallpapers
    try:
        with open(os.path.join(directory, WALLPAPER_MANIFEST),
                  encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return _wallpapers

    for line in lines:
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.rstrip("\n").split("\t")
        path = os.path.join(directory, parts[0])
        if not os.path.exists(path):
            continue
        def field(index: int) -> str:
            return parts[index] if len(parts) > index else ""

        _wallpapers.append({
            "file": parts[0],
            "title": field(1),
            "place": field(2),
            # 3 and 4 are the pixel dimensions, which nothing reads: they are
            # in the manifest so the set can be checked without opening every
            # file.
            "zone": field(5),
            "note": field(6),
            # A dash means the picture is not of anywhere, so there is nothing
            # true to say about where it is. Read as absence rather than as
            # text, because a card showing a literal dash is worse than a card
            # with one fewer line on it.
            "fact": "" if field(7) == "-" else field(7),
            "path": path,
        })
    return _wallpapers


def choose_wallpaper(name: str = "") -> dict[str, str] | None:
    """One picture, once, for this run of the installer.

    `name` pins it, by file name with or without the extension, which is what
    the preview tool and the tests need and what anybody comparing two
    treatments wants. A name that is not in the set returns nothing rather
    than quietly picking something else, because a pinned wallpaper that
    silently became a different one would waste the afternoon of whoever was
    comparing them.
    """
    import random  # noqa: PLC0415 - one call, on one code path

    available = wallpapers()
    if not available or name == "none":
        return None
    if name:
        stem = os.path.splitext(name)[0]
        for entry in available:
            if stem == os.path.splitext(entry["file"])[0]:
                return entry
        return None
    return random.choice(available)


def cover_box(image_w: int, image_h: int, width: int,
              height: int) -> tuple[int, int, int, int]:
    """Scale and offset to fill `width` by `height` without distorting.

    Cover rather than contain, and centred on both axes. Contain would letter
    box a 16:9 picture in a 4:3 window, which is a photograph with black bars
    around it, which is a photograph that looks like a mistake.
    """
    if image_w <= 0 or image_h <= 0 or width <= 0 or height <= 0:
        return 0, 0, 0, 0
    scale = max(width / image_w, height / image_h)
    scaled_w = max(1, round(image_w * scale))
    scaled_h = max(1, round(image_h * scale))
    return scaled_w, scaled_h, (width - scaled_w) // 2, (height - scaled_h) // 2


def _wallpaper_surface(path: str, width: int, height: int):
    """The picture, scaled and cropped to exactly this window, cached.

    Cached because of the machines this runs on rather than the ones it is
    written on. Under the cairo renderer a page transition damages the whole
    window and the whole window is then redrawn on the CPU, at whatever frame
    rate the transition asks for. Decoding and rescaling a photograph inside
    that loop is the difference between a backdrop and a stutter, and the
    machines that get the cairo renderer are exactly the ones with no GPU to
    absorb it.

    One entry. The size only changes when the window does, and the path only
    changes when somebody asks for a different picture.
    """
    key = (path, width, height)
    if _wall_cache["key"] == key:
        return _wall_cache["surface"]

    surface = None
    try:
        import cairo  # noqa: PLC0415
        import gi  # noqa: PLC0415

        # Both, named. `brand` is used without the widget layer by the design
        # proof and by the tests, and in those the toolkit has not already
        # said which Gdk it means.
        gi.require_version("Gdk", "4.0")
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import Gdk, GdkPixbuf  # noqa: PLC0415

        # The header, not the picture. `get_file_info` reads far enough to
        # answer how big it is and stops, which is what is wanted here: the
        # size decides the scale, and decoding a 1376x768 PNG to learn its
        # width and then decoding it again at the right size is two decodes
        # for one picture.
        _, native_w, native_h = GdkPixbuf.Pixbuf.get_file_info(path)
        scaled_w, scaled_h, dx, dy = cover_box(native_w, native_h, width, height)
        if scaled_w:
            picture = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                path, scaled_w, scaled_h, False)
            surface = cairo.ImageSurface(cairo.FORMAT_RGB24, width, height)
            context = cairo.Context(surface)
            Gdk.cairo_set_source_pixbuf(context, picture, dx, dy)
            context.paint()
    except Exception:  # noqa: BLE001 - see below
        # Deliberately everything. This is decoration on a program whose job
        # is to install an operating system, and the list of ways an image
        # loader can fail on unknown hardware is longer than the list anybody
        # would write down. A missing backdrop is a plain window; a raised
        # exception here is a traceback in front of somebody who was trying to
        # install something.
        surface = None

    _wall_cache["key"] = key
    _wall_cache["surface"] = surface
    return surface


def draw_wallpaper(cr, width: int, height: int, path: str, dark: bool,
                   top_band: int = 0, bottom_band: int = 0) -> bool:
    """Paint the photograph, the veil, and the bands the chrome stands on.

    `top_band` and `bottom_band` are how tall the opaque part of each band is,
    in pixels, measured from the chrome that is going to sit on it. Inside
    those the surface colour is at full opacity, so a glyph drawn there is on
    exactly the background the theme test measured it against and the
    photograph cannot get between the two. Outside them it fades away over
    `WALLPAPER_FADE` and the picture comes back.

    False when the picture could not be decoded, in which case nothing at all
    has been painted and the caller still owes the window a ground.
    """
    import cairo  # noqa: PLC0415

    surface = _wallpaper_surface(path, width, height)
    if surface is None:
        return False
    cr.set_source_surface(surface, 0, 0)
    cr.paint()

    scheme = T.scheme(dark)
    red, green, blue = T.rgb(scheme["surface"])
    cr.set_source_rgba(red, green, blue,
                       WALLPAPER_VEIL_DARK if dark else WALLPAPER_VEIL_LIGHT)
    cr.paint()

    for band, from_top in ((top_band, True), (bottom_band, False)):
        if band <= 0:
            continue
        depth = band + WALLPAPER_FADE
        start = 0 if from_top else height
        gradient = cairo.LinearGradient(
            0, start, 0, start + depth if from_top else start - depth)
        gradient.add_color_stop_rgba(0.0, red, green, blue, 1.0)
        gradient.add_color_stop_rgba(band / depth, red, green, blue, 1.0)
        gradient.add_color_stop_rgba(1.0, red, green, blue, 0.0)
        cr.set_source(gradient)
        cr.rectangle(0, 0 if from_top else height - depth, width, depth)
        cr.fill()
    return True


# --------------------------------------------------------------------------
# Disk sizes, as a bar
# --------------------------------------------------------------------------
#
# What the bar says is "how big is this one next to the others", and it says
# nothing else. That is deliberate and it is the whole of the design.
#
# The obvious reading of "capacity bar" is used against free, and on this page
# it would be dangerous. Every disk in this list is a disk the installer is
# offering to erase completely, and a bar showing forty percent free invites
# exactly one misreading: that the install will go in the space that is left.
# There is no page in this product where a wrong idea is more expensive.
#
# Relative size cannot be misread that way, and it answers the question the
# page actually poses. Two 512G NVMe drives from the same maker are one row
# apart and identical; a 2T next to a 32G stick is obvious at a glance and is
# obvious without reading a single character, which is the same argument the
# icon tiles are here for.

#: What `lsblk` prints, in the powers it means by them.
SIZE_UNITS = {"": 1.0, "K": 1024.0, "M": 1024.0 ** 2, "G": 1024.0 ** 3,
              "T": 1024.0 ** 4, "P": 1024.0 ** 5}

#: The shortest bar that still reads as a bar. A 32G stick beside a 4T disk is
#: eight thousandths of the width, which draws as nothing at all and looks
#: like a row where the drawing failed rather than like a very small disk.
CAPACITY_FLOOR = 0.05


def parse_size(text: str) -> float:
    """Bytes from a size as `lsblk` writes it. Zero when it is not one.

    Zero rather than a guess. The caller draws no bar for it, which is the
    right outcome for a size this cannot read: a bar of the wrong length is a
    statement about which disk is bigger, and getting that wrong on this page
    is worse than saying nothing.
    """
    cleaned = str(text or "").strip()
    if cleaned[-1:] in ("B", "b"):
        cleaned = cleaned[:-1]
    unit = ""
    if cleaned[-1:].isalpha():
        unit = cleaned[-1].upper()
        cleaned = cleaned[:-1]
    try:
        value = float(cleaned.strip())
    except ValueError:
        return 0.0
    if value < 0:
        return 0.0
    return value * SIZE_UNITS.get(unit, 0.0)


def capacity_fraction(size: str, largest: float) -> float:
    """How much of the bar this disk fills, against the biggest in the list."""
    bytes_ = parse_size(size)
    if bytes_ <= 0 or largest <= 0:
        return 0.0
    return max(CAPACITY_FLOOR, min(1.0, bytes_ / largest))


def signal_arcs(strength: int) -> int:
    """How many of the four arcs are lit, from a 0-100 nmcli signal."""
    if strength >= 75:
        return 4
    if strength >= 55:
        return 3
    if strength >= 35:
        return 2
    if strength >= 1:
        return 1
    return 0


def signal_words(strength: int) -> str:
    """The same reading in words, for anyone not looking at the arcs."""
    return {4: "Excellent", 3: "Good", 2: "Fair", 1: "Weak", 0: "None"}[
        signal_arcs(strength)
    ]


# --------------------------------------------------------------------------
# Painting
# --------------------------------------------------------------------------


def draw_aurora(cr, width: int, height: int, dark: bool, phase: float = 0.0,
                ground: bool = True, strength: float = 1.0) -> None:
    """The three fields of light.

    `ground` paints the surface colour underneath them first, which is what
    makes this the backdrop. Turn it off and the same three fields become a
    wash over whatever is already there, which is how the aurora survives a
    photograph being put behind it: the light is still the brand's light, it
    is just no longer standing on its own ground.
    """
    import cairo  # noqa: PLC0415

    scheme = T.scheme(dark)
    if ground:
        cr.set_source_rgb(*T.rgb(scheme["surface"]))
        cr.paint()
    span = max(width, height)
    for index, (colour, fx, fy, fr, alpha) in enumerate(aurora_fields(dark)):
        alpha *= strength
        dx, dy = aurora_drift(phase, index)
        cx, cy = (fx + dx) * width, (fy + dy) * height
        radius = fr * span
        gradient = cairo.RadialGradient(cx, cy, 0, cx, cy, radius)
        r, g, b = T.rgb(colour)
        gradient.add_color_stop_rgba(0.0, r, g, b, alpha)
        gradient.add_color_stop_rgba(0.55, r, g, b, alpha * 0.45)
        gradient.add_color_stop_rgba(1.0, r, g, b, 0.0)
        cr.set_source(gradient)
        cr.rectangle(0, 0, width, height)
        cr.fill()


def draw_ribbon_rule(cr, width: int, height: int, dark: bool) -> None:
    """The hairline. Lilac at the left, aqua at the right, exactly as the
    mark's stroke runs."""
    import cairo  # noqa: PLC0415

    scheme = T.scheme(dark)
    gradient = cairo.LinearGradient(0, 0, width, 0)
    left = T.rgb(scheme["primary"])
    mid = T.rgb(scheme["secondary"])
    right = T.rgb(scheme["tertiary"])
    gradient.add_color_stop_rgba(0.0, *left, 0.0)
    gradient.add_color_stop_rgba(0.18, *left, 0.85)
    gradient.add_color_stop_rgba(0.5, *mid, 0.7)
    gradient.add_color_stop_rgba(0.82, *right, 0.85)
    gradient.add_color_stop_rgba(1.0, *right, 0.0)
    cr.set_source(gradient)
    cr.rectangle(0, 0, width, max(1, height))
    cr.fill()


def _capsule(cr, x: float, width: float, height: float) -> None:
    """A rounded rectangle with semicircular ends, left as a path.

    Two caps and a middle rather than a clipped rectangle, because a filled
    part that grows has to keep the track's left cap and grow its own right
    one. Clipping a rectangle gives it square ends at every value except the
    last, which is the value nobody is looking at.
    """
    radius = height / 2
    cr.new_path()
    if width <= 0:
        return
    if width <= height:
        cr.arc(x + radius, radius, radius, 0, 6.283185)
        return
    cr.arc(x + radius, radius, radius, 1.570796, 4.712389)
    cr.arc(x + width - radius, radius, radius, 4.712389, 1.570796)
    cr.close_path()


def draw_capacity(cr, width: int, height: int, dark: bool,
                  fraction: float) -> None:
    """One disk's size, against the largest one offered. See `parse_size`."""
    import cairo  # noqa: PLC0415

    if width <= 0 or height <= 0:
        return
    scheme = T.scheme(dark)
    cr.set_source_rgba(*T.rgb(scheme["surface_container_highest"]), 1.0)
    _capsule(cr, 0, width, height)
    cr.fill()
    filled = width * max(0.0, min(1.0, fraction))
    if filled <= 0:
        return
    # The same lilac to aqua the ribbon runs, and laid across the filled part
    # only for the same reason: a small disk is then a short complete ribbon
    # rather than the first eighth of a long one, which would read as a bar
    # part way through something.
    gradient = cairo.LinearGradient(0, 0, filled, 0)
    gradient.add_color_stop_rgb(0.0, *T.rgb(scheme["primary"]))
    gradient.add_color_stop_rgb(1.0, *T.rgb(scheme["tertiary"]))
    cr.set_source(gradient)
    _capsule(cr, 0, filled, height)
    cr.fill()


def draw_progress_ribbon(cr, width: int, height: int, dark: bool,
                        fraction: float, phase: float = 0.0) -> None:
    """The install, drawn as the mark's own stroke rather than as a bar.

    A stock progress bar is the one place a carefully drawn interface reverts
    to the toolkit, and it is on the screen people look at for ten minutes. So
    this is the ribbon: the same lilac to aqua run as the hairline and the
    mark, laid into a rounded track and stopped where the install has got to.

    Three things make it read as a thing being made rather than a rectangle
    being filled. The fill runs the whole lilac to aqua gradient across the
    part that is filled, so the ribbon is complete at every moment and simply
    gets longer; laid across the whole track instead, an install at half way
    shows only the lilac half and the thing reads as a flat purple bar. The
    leading edge carries a brighter cap, which is the same pen that draws the
    swoop. And a slow highlight travels the filled length, because a bar that
    is completely still during a five minute step is indistinguishable from a
    bar that has hung.
    """
    import cairo  # noqa: PLC0415

    scheme = T.scheme(dark)
    fraction = max(0.0, min(1.0, fraction))
    radius = height / 2
    if width <= height:
        return

    def track(x: float, w: float) -> None:
        _capsule(cr, x, w, height)

    # The track. Low contrast on purpose: it is the space the ribbon has left
    # to cross, not a second bar.
    cr.set_source_rgba(*T.rgb(scheme["surface_container_highest"]), 1.0)
    track(0, width)
    cr.fill()

    filled = width * fraction
    if filled < 1:
        return

    gradient = cairo.LinearGradient(0, 0, filled, 0)
    gradient.add_color_stop_rgb(0.0, *T.rgb(scheme["primary"]))
    gradient.add_color_stop_rgb(0.55, *T.rgb(scheme["secondary"]))
    gradient.add_color_stop_rgb(1.0, *T.rgb(scheme["tertiary"]))
    cr.set_source(gradient)
    track(0, filled)
    cr.fill()

    # The highlight, travelling the filled length on a slow loop. Clipped to
    # the fill so it never appears in the empty part of the track and promise
    # progress that has not happened.
    if filled > height * 2:
        cr.save()
        track(0, filled)
        cr.clip()
        centre = (phase % 1.0) * (filled + height * 4) - height * 2
        sheen = cairo.LinearGradient(centre - height * 2, 0,
                                     centre + height * 2, 0)
        white = T.rgb(scheme["on_primary"])
        sheen.add_color_stop_rgba(0.0, *white, 0.0)
        sheen.add_color_stop_rgba(0.5, *white, 0.22)
        sheen.add_color_stop_rgba(1.0, *white, 0.0)
        cr.set_source(sheen)
        cr.rectangle(0, 0, filled, height)
        cr.fill()
        cr.restore()

    # The pen at the leading edge, the same one that draws the swoop. Only
    # once there is room for it to sit inside the fill rather than on top of
    # the left cap.
    if filled > height * 1.5:
        cr.set_source_rgba(*T.rgb(PEN), 0.95)
        cr.new_path()
        cr.arc(filled - radius, radius, radius * 0.42, 0, 6.283185)
        cr.fill()


def draw_mark(cr, width: int, height: int, size: float) -> None:
    surface = _png("aurade-mark.png")
    if surface is None:
        return
    native = surface.get_width()
    if native <= 0:
        return
    scale = size / native
    cr.save()
    cr.translate((width - size) / 2, (height - size) / 2)
    cr.scale(scale, scale)
    cr.set_source_surface(surface, 0, 0)
    cr.paint()
    cr.restore()


#: The pen: the bright head that rides the leading edge of anything the ribbon
#: draws, in the swoop and on the progress page both.
#:
#: A fixed tone rather than a role, and that is the point. Picking it by role
#: gave the two drawings different colours in the same scheme, and then picking
#: the same role for both gave the progress ribbon an aqua pen sitting on the
#: aqua end of its own gradient, which is invisible. A pen is a highlight; it
#: has to be lighter than whatever it is riding on, and the aqua ramp's tone 90
#: is lighter than every part of the ribbon in either scheme.
PEN = T.PALETTES["tertiary"][90]

SWOOP_REVEAL = 0.55   #: the ribbon has closed its circle by here
SWOOP_HOLD = 0.72     #: the ring has left the mark by here


def swoop_ease(t: float) -> float:
    """Emphasised deceleration. Fast out of the gate, long settle."""
    t = max(0.0, min(1.0, t))
    return 1.0 - pow(1.0 - t, 3)


def draw_swoop(cr, width: int, height: int, dark: bool, phase: float) -> None:
    """The mark being made, over a veil, once.

    The artwork is a bitmap rather than a path, so the mark cannot literally
    stroke itself, and revealing it through a wipe slices the tile into wedges
    that read as a broken image rather than a drawn one. So the thing that is
    drawn is the ribbon: an arc sweeps a full circle around the centre with a
    bright pen at its leading edge, and the mark fades up inside the circle as
    it closes.

    Then the ribbon leaves the mark and opens outwards, and the veil under it
    fades. What it opens into is the aurora, which is this same ring at window
    scale and is already sitting behind every page. The mark does not appear
    on top of the product. It becomes the room the product is in.
    """
    import cairo  # noqa: PLC0415

    scheme = T.scheme(dark)
    phase = max(0.0, min(1.0, phase))
    cx, cy = width / 2, height / 2
    size = min(width, height) * 0.26
    span = max(width, height)

    # The veil. Opaque while the mark is drawn, gone by the end, so the page
    # underneath arrives already laid out rather than assembling in view.
    veil = 1.0 if phase < SWOOP_HOLD else 1.0 - swoop_ease(
        (phase - SWOOP_HOLD) / (1.0 - SWOOP_HOLD))
    if veil <= 0.0:
        return
    r, g, b = T.rgb(scheme["surface"])
    cr.set_source_rgba(r, g, b, veil)
    cr.paint()

    sweep = swoop_ease(min(1.0, phase / SWOOP_REVEAL))
    ring = size * 0.86
    pr, pg, pb = T.rgb(scheme["primary"])
    tr, tg, tb = T.rgb(scheme["tertiary"])
    start = -math.pi / 2

    # The mark, fading up inside the circle as it closes.
    surface = _png("aurade-mark.png")
    native = surface.get_width() if surface is not None else 0
    if native > 0:
        drawn = size * (0.92 + 0.08 * sweep)
        cr.save()
        cr.translate(cx - drawn / 2, cy - drawn / 2)
        cr.scale(drawn / native, drawn / native)
        cr.set_source_surface(surface, 0, 0)
        cr.paint_with_alpha(veil * min(1.0, sweep * 1.35))
        cr.restore()

    # The ribbon, drawn rather than revealed. One stroke under a lilac to
    # aqua gradient, which is the same gradient as the hairline under the
    # chrome and the same one that runs across the `A`. Drawn as one path
    # rather than as segments with falling alpha: overlapping translucent
    # segments bead at every join, and beads read as a loading spinner.
    cr.new_path()
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    gradient = cairo.LinearGradient(cx - ring, cy - ring, cx + ring, cy + ring)
    gradient.add_color_stop_rgba(0.0, pr, pg, pb, veil)
    gradient.add_color_stop_rgba(0.5, *T.rgb(scheme["secondary"]), veil)
    gradient.add_color_stop_rgba(1.0, tr, tg, tb, veil)
    cr.set_source(gradient)
    cr.set_line_width(size * 0.07)
    if sweep >= 1.0:
        cr.arc(cx, cy, ring, 0, 2 * math.pi)
    else:
        cr.arc(cx, cy, ring, start, start + sweep * 2 * math.pi)
    cr.stroke()

    # The pen: a short bright head on the leading edge, which is what makes it
    # read as being drawn rather than as a bar filling up.
    if 0.0 < sweep < 1.0:
        angle = start + sweep * 2 * math.pi
        cr.new_path()
        cr.set_source_rgba(*T.rgb(PEN), veil)
        cr.set_line_width(size * 0.09)
        cr.arc(cx, cy, ring, max(start, angle - 0.30), angle)
        cr.stroke()

    # And then it opens out, into the backdrop it was always going to become.
    if phase > SWOOP_REVEAL:
        out = swoop_ease((phase - SWOOP_REVEAL) / (1.0 - SWOOP_REVEAL))
        cr.new_path()
        cr.set_source_rgba(pr, pg, pb, 0.5 * (1.0 - out) * veil)
        cr.set_line_width(max(1.0, size * 0.09 * (1.0 - out)))
        cr.arc(cx, cy, ring + out * span * 0.8, 0, 2 * math.pi)
        cr.stroke()


def draw_wordmark(cr, x: float, y: float, height: float, colour: str) -> float:
    """Paint the logotype in one colour. Returns the width it occupied.

    The asset is an ink mask rather than a picture, so the wordmark can sit on
    the light surface and the dark one without shipping two of it, and it
    always matches the text it sits beside.
    """
    surface = _png("aurade-wordmark.png")
    if surface is None:
        return 0.0
    native_h = surface.get_height()
    native_w = surface.get_width()
    if native_h <= 0:
        return 0.0
    scale = height / native_h
    cr.save()
    cr.translate(x, y)
    cr.scale(scale, scale)
    cr.set_source_rgb(*T.rgb(colour))
    cr.mask_surface(surface, 0, 0)
    cr.restore()
    return native_w * scale


def draw_signal(cr, width: int, height: int, strength: int, colour: str,
                dim: str) -> None:
    """Four arcs around a common origin, lit from the inside out."""
    import cairo  # noqa: PLC0415

    lit = signal_arcs(strength)
    cx, cy = width / 2.0, height * 0.86
    cr.set_line_width(max(1.6, height * 0.075))
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    for index in range(4):
        radius = height * (0.18 + index * 0.21)
        cr.set_source_rgb(*T.rgb(colour if index < lit else dim))
        cr.new_path()
        cr.arc(cx, cy, radius, math.radians(218), math.radians(322))
        cr.stroke()


def local_times(zone: str) -> tuple[str, str]:
    """What time it is where the picture was taken, and what time it is here.

    Two strings, either of which may be empty. Empty means there is nothing
    honest to say: no zone on the picture, no zone database on this machine, or
    a name the database does not have.

    The second one is deliberately withheld while this computer still thinks it
    is on UTC, which is what a live image thinks until somebody answers the
    timezone question. "11:12 pm here" is a fact about the reader's evening and
    it would be a guess, and a guess next to a real answer reads as two real
    answers.
    """
    if not zone:
        return "", ""
    try:
        from zoneinfo import ZoneInfo  # noqa: PLC0415
    except ImportError:  # pragma: no cover - stdlib since 3.9
        return "", ""
    import datetime  # noqa: PLC0415

    try:
        there = datetime.datetime.now(ZoneInfo(zone))
    except Exception:  # pragma: no cover - no tzdata on this machine
        return "", ""

    def spoken(when: datetime.datetime) -> str:
        # Lower case am and pm, and no leading zero on the hour, because this
        # is a sentence rather than a timetable.
        hour = when.hour % 12 or 12
        return f"{hour}:{when.minute:02d} {'am' if when.hour < 12 else 'pm'}"

    here = datetime.datetime.now().astimezone()
    offset = here.utcoffset()
    if offset is None or not offset.total_seconds():
        return spoken(there), ""
    if here.utcoffset() == there.utcoffset():
        return spoken(there), ""
    return spoken(there), spoken(here)
