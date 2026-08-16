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


def draw_aurora(cr, width: int, height: int, dark: bool, phase: float = 0.0) -> None:
    import cairo  # noqa: PLC0415

    scheme = T.scheme(dark)
    cr.set_source_rgb(*T.rgb(scheme["surface"]))
    cr.paint()
    span = max(width, height)
    for index, (colour, fx, fy, fr, alpha) in enumerate(aurora_fields(dark)):
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
        # A rounded rectangle, drawn as two caps and a middle, because the
        # filled part has to keep the track's left cap and grow its own right
        # one rather than being a clipped rectangle with square ends.
        cr.new_path()
        if w <= 0:
            return
        if w <= height:
            cr.arc(x + radius, radius, radius, 0, 6.283185)
            return
        cr.arc(x + radius, radius, radius, 1.570796, 4.712389)
        cr.arc(x + w - radius, radius, radius, 4.712389, 1.570796)
        cr.close_path()

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
