#!/usr/bin/env python3
"""Draw the one dot the boot screen animates.

Plymouth's script plugin has no drawing primitives. Everything on the screen
is an image file, so a spinner is not code, it is artwork, and the artwork has
to be in the tree.

The mark and the wordmark are already in `installer/assets` and are staged
into the theme directory unchanged, so this file exists for exactly one small
thing: a soft round dot in the dark scheme's primary, which three sprites take
turns fading up. Three dots taking turns rather than a rotating arc is a
deliberate choice about risk. A rotation is a new image allocated every frame
by a script that cannot be run anywhere except on a booting machine, and the
boot screen is the one part of this installer that no test on this side of a
VMware boot can execute. Sprite opacity is the oldest and least surprising
thing the script plugin does.

Run it to regenerate. `installer/tests/test-gui-theme.sh` fails if the
committed dot and a fresh drawing disagree.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys

import cairo

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), ".."))
THEME = os.path.join(ROOT, "archiso", "airootfs", "usr", "share", "plymouth", "themes", "aurade")
DOT = os.path.join(THEME, "dot.png")

SIZE = 28
RADIUS = 9.0
# The dark scheme's primary. The boot screen is black and stays black, so the
# dot is picked from the palette that was built to sit on a dark surface
# rather than from the light one, which would be a tone chosen against white.
COLOUR = (0xD1 / 255.0, 0xBC / 255.0, 0xFF / 255.0)
# Not a hard edge. A circle drawn with a hard edge at this size shimmers as it
# fades, because the anti aliased rim is a third of the pixels that are
# changing. The falloff spends the outer fifth of the radius on it instead.
SOFT = 0.80


def draw() -> bytes:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, SIZE, SIZE)
    cr = cairo.Context(surface)
    centre = SIZE / 2.0
    red, green, blue = COLOUR
    gradient = cairo.RadialGradient(centre, centre, 0.0, centre, centre, RADIUS)
    gradient.add_color_stop_rgba(0.0, red, green, blue, 1.0)
    gradient.add_color_stop_rgba(SOFT, red, green, blue, 1.0)
    gradient.add_color_stop_rgba(1.0, red, green, blue, 0.0)
    cr.set_source(gradient)
    cr.arc(centre, centre, RADIUS, 0, 2 * 3.141592653589793)
    cr.fill()

    import io

    buffer = io.BytesIO()
    surface.write_to_png(buffer)
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="compare with the committed dot instead of writing it")
    args = parser.parse_args()

    drawn = draw()
    if args.check:
        if not os.path.exists(DOT):
            print(f"make-plymouth-dot: {DOT} is missing", file=sys.stderr)
            return 1
        with open(DOT, "rb") as handle:
            committed = handle.read()
        if committed != drawn:
            print("make-plymouth-dot: the committed dot is not what this draws\n"
                  f"  committed {hashlib.sha256(committed).hexdigest()[:16]}\n"
                  f"  drawn     {hashlib.sha256(drawn).hexdigest()[:16]}",
                  file=sys.stderr)
            return 1
        return 0

    os.makedirs(THEME, exist_ok=True)
    with open(DOT, "wb") as handle:
        handle.write(drawn)
    print(f"make-plymouth-dot: wrote {DOT} ({len(drawn)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
