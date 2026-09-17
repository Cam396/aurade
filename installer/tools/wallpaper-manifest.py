#!/usr/bin/env python3
"""Check the wallpaper files and write the index used by the installer."""

from __future__ import annotations

import argparse
import os
import sys

try:
    from PIL import Image
    import numpy as np
except ImportError:  # pragma: no cover - tooling dependency
    print("wallpaper-manifest: needs Pillow and numpy", file=sys.stderr)
    raise SystemExit(1)

#: Keep the image dimensions and basic photographic range consistent.
MIN_DISTINCT_COLOURS = 5_000
MIN_LUMINANCE_SPREAD = 12.0

#: Allowed values for the hand-maintained light field.
LIGHTS = ("", "dawn", "day", "dusk", "night")

#: The header is part of the file format.
HEADER = [
    "# Every wallpaper in the set.",
    "# Free to use, anywhere, no attribution required.",
    "#",
    "# The first seven fields come from `titles.tsv`; the last three are measured.",
    "#",
    "# Ten tab separated fields:",
    "#",
    "#   file       the image, in this directory",
    "#   title      what the caption button says",
    "#   place      the real place, or empty when there is not one",
    "#   width      pixels",
    "#   height     pixels",
    "#   zone       IANA time zone for the place, or empty",
    "#   note       what is in the picture. One sentence, present tense, no",
    "#              adjectives doing work a noun could do.",
    "#   fact       one true thing about the place, or `-` when there is none",
    "#   light      the light in the picture: dawn, day, dusk, night, or empty",
    "#              when it cannot be told",
    "#   luminance  mean relative luminance, measured",
    "#",
    "# file\ttitle\tplace\twidth\theight\tzone\tnote\tfact\tlight\tluminance",
]

NATIVE_SIZE = (1376, 768)


def relative_luminance(a: np.ndarray) -> np.ndarray:
    """WCAG relative luminance from 8 bit sRGB, linearised properly.

    The eyeballed version weights the *encoded* values, which is wrong by
    enough to matter in shadows, and shadows are where this spends its time.
    """
    c = a.astype(np.float64) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]


def looks_photographic(path: str) -> tuple[bool, str]:
    im = Image.open(path)
    if im.size != NATIVE_SIZE:
        return False, (f"{im.size[0]}x{im.size[1]}, not the "
                       f"{NATIVE_SIZE[0]}x{NATIVE_SIZE[1]} is required")
    a = np.asarray(im.convert("RGB"))
    lum = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
    colours = len(np.unique(a.reshape(-1, 3), axis=0))
    if colours < MIN_DISTINCT_COLOURS:
        return False, f"only {colours} distinct colours, not a photograph"
    if lum.std() < MIN_LUMINANCE_SPREAD:
        return False, f"luminance spread {lum.std():.1f}, essentially flat"
    return True, ""


def measure(path: str) -> dict[str, object]:
    a = np.asarray(Image.open(path).convert("RGB"))
    y = relative_luminance(a)

    return {
        "width": int(a.shape[1]),
        "height": int(a.shape[0]),
        # For the OLED grading pass: how much real shadow is here already, and
        # how much highlight has been thrown away.
        "true_black_pct": round(float((y <= 0.0008).mean()) * 100, 3),
        "clipped_pct": round(float((a.max(2) >= 255).mean()) * 100, 3),
        "mean_luminance": round(float(y.mean()), 4),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory", help="directory of wallpaper PNGs")
    p.add_argument("--titles", help="TSV containing the wallpaper metadata")
    p.add_argument("--out", help="write the manifest here instead of stdout")
    args = p.parse_args()

    written: dict[str, list[str]] = {}
    if args.titles and os.path.exists(args.titles):
        with open(args.titles, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip() or line.startswith("#"):
                    continue
                parts = line.rstrip("\n").split("\t")
                # Treat missing trailing fields as empty values.
                written[parts[0]] = (parts[1:] + [""] * 6)[:6]

    bad = sorted(name for name, row in written.items() if row[5] not in LIGHTS)
    if bad:
        for name in bad:
            print(f"wallpaper-manifest: {name} has light "
                  f"{written[name][5]!r}, which is not one of {sorted(LIGHTS)}",
                  file=sys.stderr)
        return 1

    listing = sorted(f for f in os.listdir(args.directory) if f.endswith(".png"))
    if not listing:
        print(f"wallpaper-manifest: no PNGs in {args.directory}", file=sys.stderr)
        return 1

    rows = HEADER.copy()
    rejected = 0
    for name in listing:
        path = os.path.join(args.directory, name)
        ok, why = looks_photographic(path)
        if not ok:
            print(f"wallpaper-manifest: REJECT {name}: {why}", file=sys.stderr)
            rejected += 1
            continue
        m = measure(path)
        title, place, zone, note, fact, light = written.get(name, [""] * 6)
        if name not in written:
            print(f"wallpaper-manifest: {name} has no row in the titles file, "
                  f"so it will ship with no title and no caption",
                  file=sys.stderr)
        rows.append(f"{name}\t{title}\t{place}"
                    f"\t{m['width']}\t{m['height']}"
                    f"\t{zone}\t{note}\t{fact}"
                    f"\t{light}\t{m['mean_luminance']}")
        print(f"{name:26}"
              f"  black {m['true_black_pct']:6.3f}%"
              f"  clip {m['clipped_pct']:5.2f}%"
              f"  meanY {m['mean_luminance']:.3f}", file=sys.stderr)

    text = "\n".join(rows) + "\n"
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wallpaper-manifest: wrote {args.out}, "
              f"{len(listing) - rejected} kept, {rejected} rejected",
              file=sys.stderr)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
