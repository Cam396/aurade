#!/usr/bin/env python3
"""Draw the three fields of light the boot screen drifts.

The boot screen used to be the mark on black with three dots taking turns
fading up. The dots were the safe choice and they read as every other Linux
distribution, because they are: a row of pulsing dots is what a boot screen
looks like when nobody decided what it should look like.

This product already has a decision. The installer and the login screen are
both lit by the same three soft fields, drawn by `brand.draw_aurora` and
drifted by `brand.aurora_drift`, and the boot screen is the one surface that
was not. So it is now, and the boot, the installer and the login screen are
one continuous piece of light rather than three unrelated screens.

Doing it as a film would have been the obvious way and it does not fit.
`aurora_drift` is a figure of eight per field at three incommensurate rates,
which never repeats, which is the point of it and also means there is no loop
to pre-render. Rendering a long sequence and cutting it into a loop puts a
visible jump at the seam, and rendering full screen frames at all costs about
a hundred and fifty megabytes of resident images once plymouth has scaled them
to a panel.

So the fields are shipped as three sprites and the script does the arithmetic
that `aurora_drift` does. It is the same motion, live, for the cost of three
images, and the script plugin is only ever asked to set a position and an
opacity, which is the oldest thing it does.

Run it to regenerate. `installer/tests/test-gui-theme.sh` fails if the
committed fields and a fresh drawing disagree.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import sys

import cairo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

from aurade_gui import brand as B  # noqa: E402
from aurade_gui import tokens as T  # noqa: E402

THEME = os.path.join(ROOT, "archiso", "airootfs", "usr", "share", "plymouth",
                     "themes", "aurade")

#: How big each field is drawn before plymouth scales it to the panel.
#:
#: A radial gradient is the one thing that upscales without anybody being able
#: to tell, so this is sized for the file rather than for the screen. At 512
#: the three fields together are about sixty kilobytes and they scale to a
#: nineteen hundred pixel radius on a laptop panel with nothing visible lost.
SIZE = 512

#: Which end of the gradient is which, taken from `draw_aurora` so the boot
#: screen and the installer cannot drift apart. The field is opaque at the
#: centre, still nearly half strength at 0.55 of the radius, and gone at the
#: edge.
STOPS = ((0.0, 1.0), (0.55, 0.45), (1.0, 0.0))


def field(colour: str, alpha: float) -> bytes:
    """One field, as a PNG with its own alpha.

    The peak opacity is baked in rather than left to the script. Plymouth's
    opacity is a whole sprite multiplier, so a field that has to be drawn at
    forty two percent and then breathed would need two multiplications and one
    of them would be in a script that cannot be tested here.
    """
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, SIZE, SIZE)
    context = cairo.Context(surface)
    middle = SIZE / 2.0
    gradient = cairo.RadialGradient(middle, middle, 0, middle, middle, middle)
    red, green, blue = T.rgb(colour)
    for stop, scale in STOPS:
        gradient.add_color_stop_rgba(stop, red, green, blue, alpha * scale)
    context.set_source(gradient)
    context.rectangle(0, 0, SIZE, SIZE)
    context.fill()
    surface.flush()

    import io

    buffer = io.BytesIO()
    surface.write_to_png(buffer)
    return buffer.getvalue()


def drawings() -> dict[str, bytes]:
    """Every field the theme needs, keyed by the file it is written to."""
    out: dict[str, bytes] = {}
    for index, (colour, _fx, _fy, _fr, alpha) in enumerate(
            B.aurora_fields(True)):
        out[f"field-{index}.png"] = field(colour, alpha)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="fail when the committed fields are stale")
    parser.add_argument("--into", default=THEME)
    given = parser.parse_args()

    stale = []
    for name, drawn in drawings().items():
        path = os.path.join(given.into, name)
        try:
            with open(path, "rb") as handle:
                have = handle.read()
        except OSError:
            have = b""
        if hashlib.sha256(have).digest() == hashlib.sha256(drawn).digest():
            continue
        stale.append(name)
        if given.check:
            continue
        os.makedirs(given.into, exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(drawn)

    if given.check:
        if stale:
            print("make-plymouth-aurora: stale, rerun without --check: "
                  + ", ".join(sorted(stale)), file=sys.stderr)
            return 1
        print("plymouth aurora: up to date")
        return 0
    print(f"plymouth aurora: {len(stale)} written into {given.into}"
          if stale else "plymouth aurora: already current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
