#!/usr/bin/env python3
"""The frosted ground, measured rather than admired.

Frosted glass is the kind of change that looks finished the moment you see it
and is not, because the failure is not a crash and it is not even ugly: it is
a card that happens to land on the one bright part of one photograph out of
forty, where the words on it stop being readable. The first attempt at this
did exactly that, and it looked better than what it replaced everywhere else.

So the gate is not "does it look like glass". It is: put a card at every
plausible position over every picture in the set, in both schemes, and hold
the composited ground to the same contrast ratio the theme test holds
seventeen pairs to. Nothing here opens a window.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..")))

#: Where the pictures are, pointed at before `brand` is imported.
#:
#: `brand` builds its list of candidate directories once, at import time, from
#: the environment, so setting the variable afterwards does nothing at all.
#: Run through `run-tests.sh` with no variable set this file found an empty
#: set and every assertion below passed over nothing, which is exactly what
#: the guard in the last test is for. It fired.
PICTURES = os.path.normpath(os.path.join(HERE, "..", "..", "installer",
                                         "wallpapers"))
if os.path.isdir(PICTURES):
    os.environ.setdefault("AURADE_WALLPAPER_DIR", PICTURES)

from aurade_greeter import brand, glass, tokens as T  # noqa: E402

FAILURES: list[str] = []
CHECKS = 0

#: The window the shot script uses, and close enough to the 3180's panel.
WIDE, TALL = 1280, 860

#: Where a card actually lands. The photo card sits in the lower left, the
#: account list and the password column in the middle, and the pills in the
#: lower right, so those are the four that matter. The two extra corners are
#: there because a card is allowed to move and the gate should not have to.
PLACES = (
    ("photo card", 20, 600, 296, 240),
    ("account list", 460, 455, 360, 230),
    ("password column", 430, 330, 420, 300),
    ("status pill", 1000, 800, 260, 44),
    ("upper left", 40, 40, 360, 200),
    ("upper right", 880, 40, 360, 200),
)


#: Where this file looks, which is deliberately not where `glass` looks. The
#: module solves against its own percentile; the gate asks a harder question
#: of the answer, so that moving the module's percentile is a change the gate
#: can see rather than one it follows.
GATE_PERCENTILE = 0.99


def _worst(blurred, ink):
    """The ground where the text has least to stand on, off the full surface.

    Sorted by contrast rather than by brightness, for the same reason the
    module is: the dangerous end of a light scheme is the dark end.
    """
    found = glass._pixels(blurred)  # noqa: SLF001
    found.sort(key=lambda triple: glass.contrast(triple, ink))
    return found[min(len(found) - 1, int(len(found) * (1.0 - GATE_PERCENTILE)))]


def check(condition: bool, message: str) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(message)


def test_the_contrast_maths_is_the_published_maths():
    """Known values, so a subtly wrong luminance cannot pass everything else."""
    check(round(glass.contrast((1.0, 1.0, 1.0), (0.0, 0.0, 0.0)), 2) == 21.0,
          "white on black is not 21:1, so the luminance is not WCAG's")
    check(round(glass.contrast((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)), 2) == 21.0,
          "contrast is not symmetric")
    check(abs(glass.contrast((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)) - 1.0) < 1e-9,
          "a colour against itself is not 1:1")
    # Gamma, specifically: mid grey is not half the luminance of white.
    check(glass.luminance(0.5, 0.5, 0.5) < 0.25,
          "mid grey linearises to more than a quarter, so it was not "
          "linearised at all")


def test_the_tint_is_bounded_and_answers_the_ground():
    """The solve, on grounds chosen so the answer is known in advance."""
    tint = T.rgb(T.scheme(True)["surface"])
    ink = T.rgb(T.scheme(True)["on_surface"])
    black = glass.tint_alpha((0.0, 0.0, 0.0), tint, ink)
    white = glass.tint_alpha((1.0, 1.0, 1.0), tint, ink)
    check(black == glass.FLOOR,
          "a card over black asks for more than the least tint")
    check(white > black,
          "a card over white asks for no more tint than one over black")
    check(glass.FLOOR <= white <= glass.CEILING,
          f"the tint left its bounds at {white}")
    # And it is the *least* that works, not simply a lot.
    lower = glass.tint_alpha((1.0, 1.0, 1.0), tint, ink) - 0.01
    check(glass.contrast(glass._over((1.0, 1.0, 1.0), tint, lower), ink)
          < glass.RATIO,
          "a smaller tint would also have held the ratio, so the solve is "
          "not finding the least one")


def test_the_blur_actually_blurs():
    """A frost that returned the region unchanged would pass everything else."""
    import cairo

    source = cairo.ImageSurface(cairo.FORMAT_RGB24, 256, 256)
    context = cairo.Context(source)
    # Hard black and white stripes: nothing survives a real blur, and a copy
    # keeps every edge.
    for index in range(0, 256, 8):
        context.set_source_rgb(*(1.0, 1.0, 1.0) if index % 16 else (0, 0, 0))
        context.rectangle(index, 0, 8, 256)
        context.fill()
    blurred, small = glass.frost(source, 0, 0, 256, 256)
    check(blurred is not None, "the frost returned nothing on a valid region")
    values = [glass.luminance(*pixel) for pixel in glass._pixels(small)]
    spread = max(values) - min(values)
    check(spread < 0.10,
          f"the stripes survived the blur, spread {spread:.3f}")


def test_the_frost_does_not_darken_its_own_edges():
    """A flat colour has to come back flat, corner to corner.

    Cairo samples just outside the source at every border of every scale, and
    its default is to call everything out there transparent, which lays a dark
    rim around the region on each step of the pyramid. The contrast gate
    cannot see it: the tint is solved against the surface that is painted, so
    a rim simply pushes the tint up and the words stay readable. What is lost
    is the glass, and a card with a dark edge on a dark scheme looks like a
    smudge rather than a mistake, so nothing complains.

    A uniform grey is the whole test. Anything that is not the grey it went in
    as came from outside the region.
    """
    import cairo

    grey = 0.5
    source = cairo.ImageSurface(cairo.FORMAT_RGB24, 300, 200)
    context = cairo.Context(source)
    context.set_source_rgb(grey, grey, grey)
    context.paint()
    blurred, _small = glass.frost(source, 0, 0, 300, 200)
    check(blurred is not None, "a flat region would not frost")
    values = [glass.luminance(*pixel) for pixel in glass._pixels(blurred)]
    want = glass.luminance(grey, grey, grey)
    drift = max(abs(value - want) for value in values)
    # Eight bits of rounding, four times up and four times down, is worth a
    # little. A rim is worth a lot: the mutation that removes the clamp moves
    # this to about a third.
    check(drift < 0.01,
          f"a flat grey came back uneven by {drift:.4f}, so the frost is "
          f"sampling outside the region it was given")


def test_a_region_with_no_area_is_not_an_exception():
    """A card measured before it has been allocated asks for a zero box."""
    import cairo

    source = cairo.ImageSurface(cairo.FORMAT_RGB24, 64, 64)
    for width, height in ((0, 10), (10, 0), (0, 0), (-4, 10)):
        blurred, small = glass.frost(source, 0, 0, width, height)
        check(blurred is None and small is None,
              f"a {width} by {height} region did not come back empty")


def _pictures() -> list[str]:
    return [entry["path"] for entry in brand.wallpapers()]


def test_every_card_over_every_picture_stays_readable():
    """The gate. Six positions, forty pictures, two schemes.

    The number that has to hold is the composited ground at the same
    percentile the tint was solved against, because that is the promise: not
    that the card is dark, but that the words on it clear the ratio.
    """
    paths = _pictures()
    check(bool(paths), "there are no wallpapers, so this test proved nothing")
    worst = (99.0, "")
    for path in paths:
        surface = brand._wallpaper_surface(path, WIDE, TALL)  # noqa: SLF001
        if surface is None:
            FAILURES.append(f"{os.path.basename(path)} would not decode")
            continue
        for dark in (True, False):
            scheme = T.scheme(dark)
            tint = T.rgb(scheme["surface"])
            ink = T.rgb(scheme["on_surface"])
            for where, left, top, width, height in PLACES:
                blurred, alpha, peak = glass.ground(
                    surface, left, top, width, height, tint, ink)
                if blurred is None:
                    FAILURES.append(f"no ground for {where} on {path}")
                    continue
                # Measured at this file's own percentile, not the module's.
                # Reading `peak` back would ask the module to mark its own
                # work: lowering `glass.PERCENTILE` would move the solve and
                # the measurement together and the gate would never notice.
                got = glass.contrast(
                    glass._over(_worst(blurred, ink), tint, alpha), ink)
                if got < worst[0]:
                    worst = (got, f"{where} on {os.path.basename(path)} "
                                  f"{'dark' if dark else 'light'}")
                check(alpha <= glass.CEILING and alpha >= glass.FLOOR,
                      f"tint {alpha} out of bounds for {where} on {path}")
    check(worst[0] >= glass.RATIO - 0.01,
          f"the worst ground is {worst[0]:.2f}:1 at {worst[1]}, under "
          f"{glass.RATIO}:1")
    return worst


def main() -> int:
    worst = (0.0, "")
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            answer = function()
            if isinstance(answer, tuple):
                worst = answer
    ran = sorted(n for n in globals() if n.startswith("test_"))
    if FAILURES:
        for failure in FAILURES:
            print(f"greeter-glass: {failure}", file=sys.stderr)
        return 1
    print(f"greeter glass test: PASS ({CHECKS} checks, {len(ran)} tests, "
          f"worst ground {worst[0]:.2f}:1)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
