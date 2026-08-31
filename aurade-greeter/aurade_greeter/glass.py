"""The frosted ground the cards stand on.

Every card on this screen used to be a flat dark rectangle laid over the
photograph. That reads as a dialog box from another application sitting on
somebody's wallpaper, and the difference between it and frosted glass is most
of the distance between this screen and the ones it is measured against.

Two things had to be true at once, and the obvious implementation gets the
second one wrong.

**It has to look like glass.** A blur, of the photograph that is actually
behind the card, in the place it is actually behind it. Not a texture, not a
gradient: the picture, out of focus.

**It has to stay readable.** The first attempt blurred the picture and painted
a constant tint over it, and on the bright shaft of light in the Antelope
Canyon photograph that produced a card less legible than the flat one it
replaced. A blurred bright thing is still bright. So the tint is not a
constant. It is solved, per card, per picture, per position, for the alpha
that puts the composited ground far enough from the text to hold the same
contrast ratio the theme test enforces everywhere else. Over the Atacama at
night the tint falls away and the Milky Way is visible through the card. Over
the salt flat at dawn it rises until the card is nearly opaque. Neither of
those is a taste; both are the same arithmetic answering a different picture.

Nothing here imports Gtk, so all of it can be measured without a display.
"""
from __future__ import annotations

import math

#: The ratio the ground has to hold against the text on it. 4.5:1 is the same
#: number the theme test holds seventeen pairs to, and this is a body text
#: sized surface, so it does not get the large text exemption.
RATIO = 4.5

#: How far into the bright end to look. The mean is the wrong measure: a card
#: half over a dark cliff and half over a lit shaft has an unremarkable mean
#: and an unreadable half, and it is the half somebody is trying to read.
#:
#: All the way to the brightest, and that is safe here only because the ground
#: has already been blurred past recognition. On a photograph the maximum is a
#: speck of sun on water and following it would push every card to full tint;
#: on the thirty second scale buffer that speck has been averaged into its
#: neighbours and the maximum is a real region. Solving at the ninety fifth
#: instead was tried, and left five percent of a small card above the ratio,
#: which on a pill forty four pixels tall is two rows of the word on it.
PERCENTILE = 1.0

#: Every `STEP` pixels across and down, because a blurred ground has nothing
#: in it that is one pixel wide. The gate reads every pixel, so a step that
#: was ever too coarse to find the worst one is a failing gate rather than a
#: card somebody cannot read.
STEP = 2

#: Solved for a little more than the ratio has to be. It covers the pixels
#: `STEP` skips and the rounding into eight bits, and it is why the gate can
#: ask for the exact number while this asks for slightly more than it.
MARGIN = 0.6

#: The least tint, so a card over a black photograph is still a card and not
#: an outline with words floating in it.
FLOOR = 0.28

#: The most tint. Above this the glass has stopped being glass, and there is
#: no picture bright enough to need more once the blur has flattened it.
CEILING = 0.88

#: How many times the region is halved before it is scaled back up. Five
#: halvings is a thirty second of the width, which is well past the point
#: where any edge in a photograph survives.
ROUNDS = 5

#: Below this the pyramid stops, whatever `ROUNDS` says. A buffer reduced to
#: single pixels upscales into flat colour, and the frost stops answering the
#: picture at all.
SMALLEST = 6


def srgb_to_linear(value: float) -> float:
    """One channel, gamma expanded, the way WCAG defines it."""
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def luminance(red: float, green: float, blue: float) -> float:
    """Relative luminance of an sRGB triple in 0..1."""
    return (0.2126 * srgb_to_linear(red)
            + 0.7152 * srgb_to_linear(green)
            + 0.0722 * srgb_to_linear(blue))


def contrast(first: tuple, second: tuple) -> float:
    """The WCAG ratio between two sRGB triples, brighter over darker."""
    one, two = luminance(*first), luminance(*second)
    low, high = min(one, two), max(one, two)
    return (high + 0.05) / (low + 0.05)


def _halve(stage):
    """Exactly half, bilinear, which averages four pixels into one.

    Any coarser step skips pixels rather than averaging them, and the skipped
    ones come back as a visible grid when the buffer is scaled up again. That
    grid is what the first attempt at this looked like.
    """
    import cairo  # noqa: PLC0415

    width = max(1, stage.get_width() // 2)
    height = max(1, stage.get_height() // 2)
    out = cairo.ImageSurface(cairo.FORMAT_RGB24, width, height)
    context = cairo.Context(out)
    context.scale(width / stage.get_width(), height / stage.get_height())
    pattern = cairo.SurfacePattern(stage)
    pattern.set_filter(cairo.FILTER_BILINEAR)
    # Clamp to the edge pixel. The default is to treat everything outside the
    # source as transparent, and a scale samples just outside it at every
    # border, so the default lays a dark fringe around the whole region on
    # every step of the pyramid. On a dark scheme that fringe is invisible.
    # On a light one it is the riskiest pixel in the card, and it is what the
    # gate was failing on.
    pattern.set_extend(cairo.EXTEND_PAD)
    context.set_source(pattern)
    context.paint()
    return out


def _double(stage, width: int, height: int):
    """Back up, one doubling at a time, for the same reason as `_halve`."""
    import cairo  # noqa: PLC0415

    out = cairo.ImageSurface(cairo.FORMAT_RGB24, width, height)
    context = cairo.Context(out)
    context.scale(width / stage.get_width(), height / stage.get_height())
    pattern = cairo.SurfacePattern(stage)
    pattern.set_filter(cairo.FILTER_BILINEAR)
    # Clamp to the edge pixel. The default is to treat everything outside the
    # source as transparent, and a scale samples just outside it at every
    # border, so the default lays a dark fringe around the whole region on
    # every step of the pyramid. On a dark scheme that fringe is invisible.
    # On a light one it is the riskiest pixel in the card, and it is what the
    # gate was failing on.
    pattern.set_extend(cairo.EXTEND_PAD)
    context.set_source(pattern)
    context.paint()
    return out


def frost(source, left: int, top: int, width: int, height: int):
    """The region of `source` at that offset, blurred past recognition.

    A pyramid rather than a convolution. Every step of it is inside cairo's
    own C, because the machines this screen runs on have no GPU to absorb a
    Gaussian written in Python, and the one it was written for has a Radeon R3
    and 3.7 GB of memory.

    Returns the full size blurred surface and the smallest buffer in the
    pyramid, because the caller needs to measure the second one.
    """
    import cairo  # noqa: PLC0415

    if width <= 0 or height <= 0:
        return None, None
    stage = cairo.ImageSurface(cairo.FORMAT_RGB24, width, height)
    context = cairo.Context(stage)
    context.set_source_surface(source, -left, -top)
    context.paint()

    sizes = []
    for _ in range(ROUNDS):
        if min(stage.get_width(), stage.get_height()) <= SMALLEST * 2:
            break
        sizes.append((stage.get_width(), stage.get_height()))
        stage = _halve(stage)
    small = stage

    for was_width, was_height in reversed(sizes):
        stage = _double(stage, was_width, was_height)
    return stage, small


def _pixels(small, step: int = 1):
    """Pixels of a surface, as sRGB triples in 0..1, every `step` across."""
    data = small.get_data()
    stride = small.get_stride()
    out = []
    for row in range(0, small.get_height(), step):
        base = row * stride
        for column in range(0, small.get_width(), step):
            index = base + column * 4
            # cairo's FORMAT_RGB24 is native endian, and this runs on little
            # endian machines, so the bytes arrive as blue, green, red.
            out.append((data[index + 2] / 255.0,
                        data[index + 1] / 255.0,
                        data[index] / 255.0))
    return out


def riskiest(small, ink: tuple, percentile: float = PERCENTILE) -> tuple:
    """The pixel of the blurred ground that the text is closest to.

    Not the brightest one. Brightest is only the dangerous end in a dark
    scheme, where the words are pale; in a light scheme the words are nearly
    black and it is the dark part of the ground that swallows them. Sorting by
    brightness got the light scheme backwards and solved the tint against the
    safest pixel in the card, which the gate caught over an ice cave.

    Sorting by contrast instead asks the question that actually matters and
    asks it the same way in both schemes.
    """
    found = _pixels(small, STEP)
    if not found:
        return (0.0, 0.0, 0.0)
    found.sort(key=lambda triple: contrast(triple, ink))
    return found[min(len(found) - 1, int(len(found) * (1.0 - percentile)))]


def _over(under: tuple, over: tuple, alpha: float) -> tuple:
    """`over` painted on `under` at `alpha`, the way cairo composites it.

    In sRGB, per channel, because that is what the toolkit actually does. The
    luminance of the answer is then a separate question and not a linear one,
    which is why the solve below is a search rather than a formula.
    """
    return tuple(u * (1.0 - alpha) + o * alpha for u, o in zip(under, over))


def tint_alpha(ground: tuple, tint: tuple, ink: tuple,
               ratio: float = RATIO, floor: float = FLOOR,
               ceiling: float = CEILING, steps: int = 12) -> float:
    """The least tint that keeps `ink` readable on `ground`.

    Bisection rather than algebra: compositing is linear in sRGB and contrast
    is not linear in sRGB, so there is no closed form to write down. Twelve
    halvings resolves alpha to about a thousandth, which is far finer than the
    eye or the eight bits it ends up in.

    Monotone in alpha, because the tint is the theme's own surface and the
    theme's own surface already holds the ratio against its own text. So if
    any alpha works, `ceiling` works, and bisection is safe.
    """
    if contrast(_over(ground, tint, floor), ink) >= ratio:
        return floor
    if contrast(_over(ground, tint, ceiling), ink) < ratio:
        # The picture is too close to the text for even a nearly opaque card
        # to separate them. Take the most that is on offer and let the gate
        # say so rather than quietly shipping something unreadable.
        return ceiling
    low, high = floor, ceiling
    for _ in range(steps):
        middle = (low + high) / 2.0
        if contrast(_over(ground, tint, middle), ink) >= ratio:
            high = middle
        else:
            low = middle
    return high


def rounded(context, left: float, top: float, width: float, height: float,
            radius: float) -> None:
    """A rounded rectangle path, corners in the order cairo prefers them."""
    radius = max(0.0, min(radius, width / 2.0, height / 2.0))
    context.new_sub_path()
    context.arc(left + width - radius, top + radius, radius,
                -math.pi / 2.0, 0.0)
    context.arc(left + width - radius, top + height - radius, radius,
                0.0, math.pi / 2.0)
    context.arc(left + radius, top + height - radius, radius,
                math.pi / 2.0, math.pi)
    context.arc(left + radius, top + radius, radius,
                math.pi, 3.0 * math.pi / 2.0)
    context.close_path()


def ground(source, left: int, top: int, width: int, height: int,
           tint: tuple, ink: tuple) -> tuple:
    """Everything that does not depend on where it is being drawn.

    Split out from `paint` so it can be cached, and so the gate can ask what
    the ground under a card would be without opening a window.
    """
    blurred, small = frost(source, left, top, width, height)
    if blurred is None or small is None:
        return None, 1.0, (0.0, 0.0, 0.0)
    # Measured on the surface that is actually painted, not on the buffer it
    # was built from. The small buffer is more averaged than the upscale of
    # it, so its extremes are milder, and solving against those left the real
    # ground short of the ratio by about two tenths.
    peak = riskiest(blurred, ink)
    return blurred, tint_alpha(peak, tint, ink, ratio=RATIO + MARGIN), peak
