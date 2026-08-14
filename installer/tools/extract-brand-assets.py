#!/usr/bin/env python3
"""Cut the installer's artwork out of the AuraDE logo.

`assets/aurade-logo.png` is the product's logo: a periwinkle plate carrying a
ribbon `A`, with the wordmark below it, both sitting on a near-white page with
a soft drop shadow. None of that composites onto an installer window, so two
derived assets are cut from it here rather than redrawn by hand, because a
redrawn logo is a second logo and the two diverge the first time either is
touched.

  `aurade-mark.png` is the plate alone, found by its own violet cast rather
  than by a luminance threshold that would take the neutral shadow with it,
  with the rounded corners re-cut as alpha so it sits on any surface.

  `aurade-wordmark.png` is the logotype as an ink mask: white, with alpha
  carrying the stroke coverage. The installer paints it in whichever theme
  colour the surface behind it calls for, which a flat-coloured copy could not
  do. The page it was cut from is a vertical gradient, so the ground is
  estimated per row; a single threshold leaves a faint rectangle behind the
  word, and two percent of white across a 600-pixel box is invisible as a
  pixel and plainly visible as a block.

Run it to regenerate. `installer/tests/test-gui-theme.sh` fails if the
committed assets and a fresh extraction disagree, so the artwork in the tree
is always the artwork this file produces from the logo in the tree.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", ".."))
LOGO = os.path.join(ROOT, "assets", "aurade-logo.png")
OUT_DIR = os.path.join(ROOT, "installer", "assets")

MARK_SIZE = 512
#: Fraction of the plate's side taken by its corner radius, measured off the
#: source artwork.
CORNER = 0.225
#: Everything below this share of the ramp is the page, not the logotype.
INK_FLOOR = 0.16
#: The least contrast a row must hold before it is treated as containing ink.
MIN_ROW_SPAN = 0.06


def luminance(colour) -> float:
    r, g, b = colour[0], colour[1], colour[2]
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def extract_mark(source):
    """The plate, cut at its own edge rather than at its shadow.

    The plate fill is violet-leaning and the drop shadow around it is neutral
    grey, so the two are told apart by hue. A luminance threshold cannot do
    it: the darkest part of the shadow and the plate itself overlap.
    """
    from PIL import Image, ImageDraw

    px = source.load()
    width, height = source.size

    def is_plate(colour) -> bool:
        return colour[2] - colour[0] > 20 and sum(colour[:3]) / 3 < 215

    # Rows are classified by how much of them the plate covers, not by walking
    # a contiguous run and not by taking the outermost match. A run stops at
    # the ribbon `A`, which is too bright to be plate; the outermost match
    # reaches the wordmark, which is the same lilac family as the plate. Only
    # the plate covers most of a row.
    plate_rows = [
        y for y in range(height)
        if sum(1 for x in range(0, width, 2) if is_plate(px[x, y])) > (width // 2) * 0.6
    ]
    if not plate_rows:
        raise SystemExit("extract-brand-assets: no plate found in the logo")
    top, bottom = plate_rows[0], plate_rows[-1]
    edges = [
        [x for x in range(width) if is_plate(px[x, y])]
        for y in range(top, bottom + 1, 4)
    ]
    left = min(row[0] for row in edges if row)
    right = max(row[-1] for row in edges if row)

    # Squared by resampling, not by extending the crop. The plate is 808x827
    # in the source and sits flush against the left edge, so growing the box
    # to a square runs off the artwork and fills the difference with black.
    plate = source.crop((left, top, right + 1, bottom + 1)).convert("RGBA")
    edge = max(plate.size)
    plate = plate.resize((edge, edge), Image.LANCZOS)

    # Drawn at four times the size and scaled down, because Pillow's rounded
    # rectangle is not antialiased and a hard corner on a 512px mark is
    # visible against any surface.
    mask = Image.new("L", (edge * 4, edge * 4), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, edge * 4 - 1, edge * 4 - 1], radius=int(edge * 4 * CORNER), fill=255)
    plate.putalpha(mask.resize((edge, edge), Image.LANCZOS))
    return plate.resize((MARK_SIZE, MARK_SIZE), Image.LANCZOS)


def extract_wordmark(source):
    """The logotype, as coverage rather than as colour."""
    from PIL import Image

    px = source.load()
    width, height = source.size

    # The wordmark sits below the plate, separated by a band of bare page.
    #
    # The plate spans essentially the whole width; the logotype's widest row
    # covers about half. So the plate is found by requiring most of the row to
    # be covered, not merely some of it - a lower bar picks the bottom of the
    # wordmark instead and the crop lands below everything.
    samples = len(range(0, width, 2))
    coverage = [
        sum(1 for x in range(0, width, 2) if luminance(px[x, y]) < 0.89)
        for y in range(height)
    ]
    plate_end = max(y for y in range(height) if coverage[y] > samples * 0.6)
    gap = next((y for y in range(plate_end, height) if coverage[y] == 0), plate_end)
    band = source.crop((0, gap, width, height))
    bw, bh = band.size
    bp = band.load()

    rows = []
    for y in range(bh):
        values = sorted(luminance(bp[x, y]) for x in range(bw))
        rows.append((values[int(len(values) * 0.92)], values[int(len(values) * 0.02)]))
    # One ink level across the whole logotype, so stroke weight stays even.
    inked = [row[1] for row in rows if row[0] - row[1] >= MIN_ROW_SPAN]
    if not inked:
        raise SystemExit("extract-brand-assets: found no logotype below the plate")
    ink = sorted(inked)[len(inked) // 2]

    out = Image.new("RGBA", (bw, bh), (255, 255, 255, 0))
    op = out.load()
    for y in range(bh):
        ground = rows[y][0]
        # A row of bare page has almost no spread between its darkest and
        # lightest pixel. Scaling that spread up to full range turns paper
        # grain into solid ink, so a row with nothing in it stays empty.
        if ground - rows[y][1] < MIN_ROW_SPAN:
            continue
        span = ground - ink
        for x in range(bw):
            alpha = (ground - luminance(bp[x, y])) / span
            if alpha < INK_FLOOR:
                alpha = 0.0
            else:
                alpha = min(1.0, (alpha - INK_FLOOR) / (1.0 - INK_FLOOR))
            op[x, y] = (255, 255, 255, int(round(alpha * 255)))
    box = out.getbbox()
    if box is None:
        raise SystemExit("extract-brand-assets: the wordmark keyed out to nothing")
    return out.crop(box)


def encode(image) -> bytes:
    buffer = io.BytesIO()
    # No timestamp chunk, so two runs of this file are byte-identical and the
    # check mode compares content rather than when it ran.
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="exit non-zero if the tree differs from a fresh extraction")
    args = parser.parse_args()

    try:
        from PIL import Image
    except ImportError:
        print("extract-brand-assets: Pillow is required to cut the artwork",
              file=sys.stderr)
        return 0 if args.check else 1
    if not os.path.exists(LOGO):
        print(f"extract-brand-assets: {LOGO} is missing", file=sys.stderr)
        return 1

    source = Image.open(LOGO).convert("RGB")
    targets = {
        "aurade-mark.png": encode(extract_mark(source)),
        "aurade-wordmark.png": encode(extract_wordmark(source)),
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    stale = []
    for name, content in targets.items():
        path = os.path.join(OUT_DIR, name)
        current = open(path, "rb").read() if os.path.exists(path) else None
        if current == content:
            continue
        if args.check:
            stale.append(name)
        else:
            with open(path, "wb") as handle:
                handle.write(content)
    if stale:
        print("extract-brand-assets: out of date: " + ", ".join(stale), file=sys.stderr)
        return 1
    if not args.check:
        for name, content in targets.items():
            digest = hashlib.sha256(content).hexdigest()[:12]
            print(f"extract-brand-assets: {name}  {len(content):>7} bytes  {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
