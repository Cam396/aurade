#!/usr/bin/env python3
"""Render the drawn parts of the installer to a PNG, in both schemes.

The widget layer needs a compositor to appear. The drawn layer does not: the
aurora, the ribbon rule, the mark, the wordmark and the signal arcs are all
cairo, and cairo will paint into an image surface as happily as into a window.
So this calls the same functions the installer calls and writes the result to
a file, which is how the brand layer gets reviewed on a build host and how a
broken asset path or a bad colour is seen before a VM boot rather than after.

This is not a screenshot of the installer. It is the installer's drawing code,
run against an image surface, with the palette printed beside it.
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "installer", "lib"))

import cairo  # noqa: E402

from aurade_gui import brand, tokens as T  # noqa: E402

PANEL_W, PANEL_H = 860, 420
SWATCHES = [
    ("primary", "on_primary"),
    ("primary_container", "on_primary_container"),
    ("tertiary", "on_tertiary"),
    ("tertiary_container", "on_tertiary_container"),
    ("secondary_container", "on_secondary_container"),
    ("error_container", "on_error_container"),
    ("surface_container_high", "on_surface"),
    ("surface", "on_surface_variant"),
]


def text(cr, x: float, y: float, body: str, size: float, colour: str,
         mono: bool = False) -> None:
    cr.select_font_face(
        "monospace" if mono else "sans",
        cairo.FONT_SLANT_NORMAL,
        cairo.FONT_WEIGHT_NORMAL,
    )
    cr.set_font_size(size)
    cr.set_source_rgb(*T.rgb(colour))
    cr.move_to(x, y)
    cr.show_text(body)


def panel(cr, dark: bool, phase: float) -> None:
    scheme = T.scheme(dark)
    # The real backdrop, from the real function.
    brand.draw_aurora(cr, PANEL_W, PANEL_H, dark, phase)

    cr.save()
    cr.translate(0, 74)
    brand.draw_ribbon_rule(cr, PANEL_W, 2, dark)
    cr.restore()

    cr.save()
    cr.translate(28, 20)
    brand.draw_mark(cr, 38, 38, 38)
    cr.restore()
    cr.save()
    cr.translate(76, 28)
    brand.draw_wordmark(cr, 0, 0, 22, scheme["on_surface"])
    cr.restore()

    text(cr, PANEL_W - 190, 44, "Step 3 of 7", 12, scheme["on_surface_variant"], True)

    text(cr, 28, 122, "Choose a disk", 26, scheme["on_surface"])
    text(cr, 28, 150, "Everything on the disk you choose will be erased.",
         13, scheme["on_surface_variant"])

    # A row in the machine voice, which is where the mono face earns its place.
    cr.set_source_rgb(*T.rgb(scheme["surface_container_low"]))
    cr.rectangle(28, 168, PANEL_W - 56, 52)
    cr.fill()
    text(cr, 44, 190, "/dev/nvme0n1", 14, scheme["on_surface"], True)
    text(cr, 44, 208, "Samsung SSD 980 PRO   476.9G   NVME   S6B2NS0T900123X",
         11, scheme["on_surface_variant"], True)

    # Signal arcs at each step of the scale.
    for index, strength in enumerate((90, 65, 45, 20)):
        cr.save()
        cr.translate(30 + index * 46, 244)
        brand.draw_signal(cr, 26, 24, strength, scheme["primary"],
                          scheme["outline_variant"])
        cr.restore()
        text(cr, 30 + index * 46, 288, brand.signal_words(strength), 9,
             scheme["on_surface_variant"])

    # The role swatches this panel is built from.
    x = 28
    for role, on_role in SWATCHES:
        cr.set_source_rgb(*T.rgb(scheme[role]))
        cr.rectangle(x, 306, 96, 62)
        cr.fill()
        text(cr, x + 8, 328, role.replace("_", " ")[:14], 8, scheme[on_role])
        text(cr, x + 8, 344, scheme[role], 9, scheme[on_role], True)
        x += 100

    text(cr, 28, 394, "light scheme" if not dark else "dark scheme", 11,
         scheme["on_surface_variant"])


def render(path: str) -> None:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, PANEL_W, PANEL_H * 2 + 12)
    cr = cairo.Context(surface)
    cr.set_source_rgb(0.5, 0.5, 0.5)
    cr.paint()
    for index, dark in enumerate((False, True)):
        cr.save()
        cr.translate(0, index * (PANEL_H + 12))
        cr.rectangle(0, 0, PANEL_W, PANEL_H)
        cr.clip()
        panel(cr, dark, phase=1.4 if dark else 0.0)
        cr.restore()
    surface.write_to_png(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output", nargs="?",
        default=os.path.join(os.environ.get("TMPDIR", "/tmp"), "aurade-design-proof.png"),
        help="where to write the proof; defaults outside the tree so a review "
             "render never becomes a committed binary")
    args = parser.parse_args()
    render(args.output)
    print(f"render-design-proof: wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
