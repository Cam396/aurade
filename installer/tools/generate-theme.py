#!/usr/bin/env python3
"""Generate the AuraDE installer's design tokens from the brand artwork.

This is a Material 3 tonal system, built the way Material 3 builds one: key
colours become tonal palettes, tonal palettes become roles, roles become the
only colours any widget is allowed to name. What it is not is Google's code.
Material 3's reference implementation derives tones in HCT, a CAM16-based
space with no public GTK binding; this derives them in OKLCh against a real
CIELAB lightness solve, which is a documented approximation and not the same
algorithm. Everything downstream - the role mapping, the shape scale, the
state-layer opacities, the type scale - follows the published Material 3
specification.

The key colours are measured from `assets/aurade-logo.png` rather than typed
in from memory. The mark is a periwinkle plate carrying a ribbon `A` that runs
lilac on the left to aqua on the right, and those two ends are the two accent
hues the whole interface is built from. A palette invented alongside the logo
instead of out of it is how a product ends up with brand artwork that does not
match its own interface.

Run it to regenerate; `installer/tests/test-gui-theme.sh` fails if the
committed output and a fresh generation disagree, so the tokens in the tree
are always the tokens this file produces.
"""

from __future__ import annotations

import argparse
import math
import os
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", ".."))
LOGO = os.path.join(ROOT, "assets", "aurade-logo.png")

# --------------------------------------------------------------------------
# Colour science
# --------------------------------------------------------------------------


def srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def linear_to_srgb(c: float) -> float:
    return c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def rgb_to_oklab(r: float, g: float, b: float) -> tuple[float, float, float]:
    lr, lg, lb = srgb_to_linear(r), srgb_to_linear(g), srgb_to_linear(b)
    l = 0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb
    m = 0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb
    s = 0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb
    l_, m_, s_ = l ** (1 / 3), m ** (1 / 3), s ** (1 / 3)
    return (
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    )


def oklab_to_rgb(L: float, a: float, b: float) -> tuple[float, float, float]:
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    return (
        linear_to_srgb(+4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
        linear_to_srgb(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
        linear_to_srgb(-0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s),
    )


def rgb_to_lstar(r: float, g: float, b: float) -> float:
    """CIELAB L*, which is what a Material 3 tone number actually means."""
    lr, lg, lb = srgb_to_linear(r), srgb_to_linear(g), srgb_to_linear(b)
    y = 0.2126729 * lr + 0.7151522 * lg + 0.0721750 * lb
    e = 216 / 24389
    return 116 * (y ** (1 / 3)) - 16 if y > e else (24389 / 27) * y


def in_gamut(rgb: tuple[float, float, float], tol: float = 1e-4) -> bool:
    return all(-tol <= c <= 1 + tol for c in rgb)


def oklch_to_rgb(L: float, C: float, h_deg: float) -> tuple[float, float, float]:
    h = math.radians(h_deg)
    return oklab_to_rgb(L, C * math.cos(h), C * math.sin(h))


def solve_oklab_l(target_lstar: float, C: float, h: float) -> float:
    """The OKLab lightness whose rendered colour has the requested L*.

    Bisection rather than a formula: OKLab L and CIELAB L* are both monotonic
    in luminance but are not the same curve, and at high chroma the rendered
    L* also depends on hue. Solving numerically keeps the tone numbers
    meaning what Material 3 says they mean.
    """
    lo, hi = 0.0, 1.0
    for _ in range(48):
        mid = (lo + hi) / 2
        rgb = oklch_to_rgb(mid, C, h)
        clamped = tuple(min(1.0, max(0.0, c)) for c in rgb)
        if rgb_to_lstar(*clamped) < target_lstar:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def tone(hue: float, chroma: float, t: float) -> str:
    """One tone of a tonal palette, gamut-mapped by reducing chroma.

    Material 3 keeps hue and tone and gives up chroma when a colour will not
    fit in the display gamut, because a shifted hue reads as a different
    colour while a duller one reads as the same colour. Same rule here.
    """
    if t <= 0:
        return "#000000"
    if t >= 100:
        return "#ffffff"
    c = chroma
    while c > 0.0005:
        L = solve_oklab_l(t, c, hue)
        rgb = oklch_to_rgb(L, c, hue)
        if in_gamut(rgb):
            return "#%02x%02x%02x" % tuple(
                round(min(1.0, max(0.0, v)) * 255) for v in rgb
            )
        c -= 0.002
    L = solve_oklab_l(t, 0.0, hue)
    rgb = oklch_to_rgb(L, 0.0, hue)
    return "#%02x%02x%02x" % tuple(round(min(1.0, max(0.0, v)) * 255) for v in rgb)


def contrast(fg: str, bg: str) -> float:
    def lum(hexstr: str) -> float:
        r, g, b = (int(hexstr[i : i + 2], 16) / 255 for i in (1, 3, 5))
        lr, lg, lb = srgb_to_linear(r), srgb_to_linear(g), srgb_to_linear(b)
        return 0.2126 * lr + 0.7152 * lg + 0.0722 * lb

    a, b = lum(fg), lum(bg)
    lo, hi = min(a, b), max(a, b)
    return (hi + 0.05) / (lo + 0.05)


# --------------------------------------------------------------------------
# Key colours, measured from the logo
# --------------------------------------------------------------------------


def measure_brand() -> dict[str, tuple[float, float]]:
    """Hue and chroma of the mark's ribbon ends and its plate.

    Falls back to the values this file measured when it was written if Pillow
    or the artwork is unavailable, so the generator still runs on a machine
    that only has the source tree. The fallback is asserted against the live
    measurement by the theme test whenever the artwork is present.
    """
    samples = {
        # ribbon left third, ribbon right third, and the plate behind them
        "lilac": (0xD7, 0xCA, 0xF6),
        "aqua": (0xC7, 0xE4, 0xF1),
        "plate": (0x94, 0x99, 0xB7),
    }
    try:
        from PIL import Image  # noqa: PLC0415
    except ImportError:
        pass
    else:
        if os.path.exists(LOGO):
            samples = sample_logo(Image.open(LOGO).convert("RGB"))
    out = {}
    for name, (r, g, b) in samples.items():
        L, a, bb = rgb_to_oklab(r / 255, g / 255, b / 255)
        out[name] = (math.degrees(math.atan2(bb, a)) % 360, math.hypot(a, bb))
    return out


def sample_logo(im) -> dict[str, tuple[int, int, int]]:
    px = im.load()
    w, h = im.size
    plate_x, plate_y = int(w * 0.12), int(h * 0.34)

    def peak(x0: int, x1: int) -> tuple[int, int, int]:
        band = [
            px[x, y]
            for y in range(int(h * 0.11), int(h * 0.69))
            for x in range(x0, x1)
            if sum(px[x, y]) / 3 > 205
        ]
        band.sort(key=lambda c: -sum(c))
        band = band[: max(1, len(band) // 10)]
        return tuple(sum(c[i] for c in band) // len(band) for i in range(3))

    return {
        "lilac": peak(int(w * 0.15), int(w * 0.37)),
        "aqua": peak(int(w * 0.64), int(w * 0.87)),
        "plate": px[plate_x, plate_y],
    }


# --------------------------------------------------------------------------
# Tonal palettes and roles
# --------------------------------------------------------------------------

#: Tone stops Material 3 reads from a palette, including the extended stops
#: the surface-container roles need.
TONES = [0, 4, 6, 10, 12, 17, 20, 22, 24, 30, 40, 50, 60, 70, 80, 87, 90, 92,
         94, 95, 96, 98, 99, 100]


def build_palettes() -> dict[str, dict[int, str]]:
    brand = measure_brand()
    lilac_h, lilac_c = brand["lilac"]
    aqua_h, _ = brand["aqua"]
    plate_h, _ = brand["plate"]

    # The measured ribbon is a pale tint, so its chroma is not the chroma the
    # accent should carry. Material 3's own key-colour chromas are used
    # instead, anchored on the hues the artwork actually contains.
    return {
        "primary": ramp(lilac_h, max(0.13, lilac_c)),
        "secondary": ramp(plate_h, 0.045),
        "tertiary": ramp(aqua_h, 0.085),
        "neutral": ramp(plate_h, 0.010),
        "neutral_variant": ramp(plate_h, 0.022),
        "error": ramp(27.0, 0.170),
        # Amber, and its own ramp rather than an alias. `warning` used to point
        # at `secondary`, which is the plate hue at chroma 0.045: a slate grey.
        # A caution drawn in the same colour as ordinary chrome is not a
        # caution. Warm enough to read as one, and far enough from `error` at
        # hue 27 that the two are never confused.
        "warning": ramp(78.0, 0.140),
    }


def ramp(hue: float, chroma: float) -> dict[int, str]:
    return {t: tone(hue, chroma, t) for t in TONES}


#: How far a high contrast scheme pushes each role, as tone substitutions.
#:
#: Not a filter over the existing scheme, and not "the dark one but more".
#: The current design separates surfaces by two or three tones and leans on
#: that difference to say what is a card and what is behind it. Two or three
#: tones is exactly what stops being visible at high contrast, so the answer
#: is not to darken the same relationships, it is to stop relying on them: the
#: ground goes to the end of the ramp, the text goes to the other end, and
#: every container gets an outline that is doing the work the tone difference
#: used to do.
HIGH_CONTRAST_LIGHT = {
    "surface": 100, "on_surface": 0,
    "surface_dim": 96, "surface_bright": 100,
    "surface_container_lowest": 100, "surface_container_low": 100,
    "surface_container": 98, "surface_container_high": 96,
    "surface_container_highest": 94,
    "surface_variant": 96, "on_surface_variant": 0,
    "outline": 0, "outline_variant": 20,
}
HIGH_CONTRAST_DARK = {
    "surface": 0, "on_surface": 100,
    "surface_dim": 0, "surface_bright": 12,
    "surface_container_lowest": 0, "surface_container_low": 4,
    "surface_container": 6, "surface_container_high": 10,
    "surface_container_highest": 12,
    "surface_variant": 6, "on_surface_variant": 100,
    "outline": 100, "outline_variant": 80,
}


def oled(scheme: dict[str, str], p: dict[str, dict[int, str]]) -> dict[str, str]:
    """The dark scheme with the ground actually switched off.

    An OLED pixel at #000000 is not dark, it is unlit: no power and infinite
    contrast. The dark scheme's ground is `#121318`, which is a pixel that is
    on and pretending. On a laptop panel that is the difference between a
    backdrop and a hole in the front of the machine, and it is most of the
    screen for the ten minutes of an install.

    Only the grounds move. The containers stay separated from each other so a
    card is still findable, and every accent is untouched, because an OLED
    scheme that also restyles the brand is two changes wearing one name.
    """
    N = p["neutral"]
    out = dict(scheme)
    out["surface"] = "#000000"
    out["surface_dim"] = "#000000"
    out["surface_container_lowest"] = "#000000"
    # The cards lift off the black rather than sinking into it, which is the
    # one thing a true black ground makes harder rather than easier.
    out["surface_container_low"] = N[6]
    out["surface_container"] = N[10]
    out["surface_container_high"] = N[12]
    out["surface_container_highest"] = N[17]
    out["scrim"] = "#000000"
    return out


def high_contrast(scheme: dict[str, str], p: dict[str, dict[int, str]],
                  dark: bool) -> dict[str, str]:
    """The same roles, pushed to the ends of their ramps.

    The accent families move too, but only as far as they have to: an accent
    that is pushed all the way to the end of its ramp stops being that accent
    and the product loses the one thing that made it recognisable. Tone 20 and
    tone 90 are far enough to clear 7:1 against the new grounds while still
    being lilac, plate and aqua.
    """
    out = dict(scheme)
    N, NV = p["neutral"], p["neutral_variant"]
    table = HIGH_CONTRAST_DARK if dark else HIGH_CONTRAST_LIGHT
    for role, tone_value in table.items():
        ramp = NV if role in ("surface_variant", "on_surface_variant",
                              "outline", "outline_variant") else N
        out[role] = ramp[tone_value]
    accent_on = 90 if dark else 20
    container = 20 if dark else 90
    on_container = 90 if dark else 20
    for family, key in (("primary", "primary"), ("secondary", "secondary"),
                        ("tertiary", "tertiary"), ("error", "error"),
                        ("warning", "warning")):
        ramp = p[family]
        out[key] = ramp[accent_on]
        out[f"on_{key}"] = ramp[0 if dark else 100]
        out[f"{key}_container"] = ramp[container]
        out[f"on_{key}_container"] = ramp[on_container]
    out["danger_surface"] = p["error"][10 if dark else 96]
    out["on_danger_surface"] = p["error"][90 if dark else 10]
    return out


def roles(p: dict[str, dict[int, str]], dark: bool) -> dict[str, str]:
    """The Material 3 colour roles, light and dark, as published."""
    P, S, T, N, NV, E, W = (
        p["primary"], p["secondary"], p["tertiary"],
        p["neutral"], p["neutral_variant"], p["error"], p["warning"],
    )
    if not dark:
        return {
            "primary": P[40], "on_primary": P[100],
            "primary_container": P[90], "on_primary_container": P[10],
            "secondary": S[40], "on_secondary": S[100],
            "secondary_container": S[90], "on_secondary_container": S[10],
            "tertiary": T[40], "on_tertiary": T[100],
            "tertiary_container": T[90], "on_tertiary_container": T[10],
            "error": E[40], "on_error": E[100],
            "error_container": E[90], "on_error_container": E[10],
            "danger_surface": E[96], "on_danger_surface": E[10],
            "warning": W[40], "on_warning": W[100],
            "warning_container": W[90], "on_warning_container": W[10],
            "surface": N[98], "on_surface": N[10],
            "surface_dim": N[87], "surface_bright": N[98],
            "surface_container_lowest": N[100], "surface_container_low": N[96],
            "surface_container": N[94], "surface_container_high": N[92],
            "surface_container_highest": N[90],
            "surface_variant": NV[90], "on_surface_variant": NV[30],
            "outline": NV[50], "outline_variant": NV[80],
            "inverse_surface": N[20], "inverse_on_surface": N[95],
            "inverse_primary": P[80],
            "scrim": N[0], "shadow": N[0],
        }
    return {
        "primary": P[80], "on_primary": P[20],
        "primary_container": P[30], "on_primary_container": P[90],
        "secondary": S[80], "on_secondary": S[20],
        "secondary_container": S[30], "on_secondary_container": S[90],
        "tertiary": T[80], "on_tertiary": T[20],
        "tertiary_container": T[30], "on_tertiary_container": T[90],
        "error": E[80], "on_error": E[20],
        "error_container": E[30], "on_error_container": E[90],
        "danger_surface": E[12], "on_danger_surface": E[90],
        "warning": W[80], "on_warning": W[20],
        "warning_container": W[30], "on_warning_container": W[90],
        "surface": N[6], "on_surface": N[90],
        "surface_dim": N[6], "surface_bright": N[24],
        "surface_container_lowest": N[4], "surface_container_low": N[10],
        "surface_container": N[12], "surface_container_high": N[17],
        "surface_container_highest": N[22],
        "surface_variant": NV[30], "on_surface_variant": NV[80],
        "outline": NV[60], "outline_variant": NV[30],
        "inverse_surface": N[90], "inverse_on_surface": N[20],
        "inverse_primary": P[40],
        "scrim": N[0], "shadow": N[0],
    }


#: Foreground/background pairs that must stay legible. Checked by the theme
#: test in both schemes rather than trusted because Material 3 says so: the
#: palettes here are generated from brand hues, and a generated palette can
#: put a role somewhere the specification never anticipated.
CONTRAST_PAIRS = [
    ("on_surface", "surface", 7.0),
    ("on_surface_variant", "surface", 4.5),
    ("on_surface", "surface_container", 7.0),
    ("on_surface", "surface_container_high", 7.0),
    ("on_surface_variant", "surface_container", 4.5),
    ("on_primary", "primary", 4.5),
    ("on_primary_container", "primary_container", 4.5),
    ("on_secondary_container", "secondary_container", 4.5),
    ("on_tertiary_container", "tertiary_container", 4.5),
    ("on_error", "error", 4.5),
    ("on_error_container", "error_container", 4.5),
    # The gate's ground carries the four facts somebody checks against the
    # sticker on their drive, so it is held to the body-text floor, not the
    # container one.
    ("on_danger_surface", "danger_surface", 7.0),
    ("inverse_on_surface", "inverse_surface", 4.5),
    ("outline", "surface", 3.0),
    ("primary", "surface", 3.0),
    ("error", "surface", 3.0),
]

#: Material 3 shape scale, state-layer opacities and elevation, verbatim.
SHAPE = {"none": 0, "xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 28, "full": 999}
STATE = {"hover": 0.08, "focus": 0.10, "pressed": 0.10, "dragged": 0.16,
         "disabled_content": 0.38, "disabled_container": 0.12}

#: Material 3 type scale. The families are the two the image carries: the
#: system sans for prose, and a mono for machine facts. The mono is not a
#: flourish - disk serials, device paths and the erase token are read by a
#: person who has to match them against a label on hardware, and a face that
#: separates 0 from O and 1 from l is the difference between confirming the
#: right disk and confirming a different one.
TYPE = {
    # size, weight, tracking (px), line height (multiple of size)
    #
    # This began as the Material 3 spec table and is no longer it, in three
    # ways that are the whole difference between a page that reads as a
    # settings screen and one that reads as a product.
    #
    # Tracking is zero or negative. M3 sets positive tracking on body and
    # label sizes, which is a convention built around Roboto and is the single
    # loudest tell that a page was laid out from someone else's spec. Large
    # text gets negative tracking here, the way large text has always wanted
    # it: the bigger the type, the more air there already is between letters.
    #
    # Headings carry weight. Everything in the M3 table above title size is
    # regular, and a 24px regular heading over 14px regular body is a
    # hierarchy expressed in size alone. The image ships Adwaita Sans as a
    # variable font, so 600 costs nothing and is the difference between a
    # heading and a big sentence.
    #
    # Body text is a size larger than the spec and set with real leading. This
    # is read from a desk chair, once, by someone deciding whether to erase a
    # disk.
    "display_large": (57, 500, -1.6, 1.08),
    "display_medium": (45, 500, -1.1, 1.12),
    "display_small": (36, 600, -0.7, 1.16),
    "headline_large": (32, 600, -0.6, 1.20),
    "headline_medium": (28, 600, -0.5, 1.22),
    "headline_small": (24, 600, -0.4, 1.26),
    "title_large": (22, 600, -0.2, 1.32),
    "title_medium": (18, 600, -0.1, 1.36),
    "title_small": (15, 500, 0.0, 1.40),
    "body_large": (17, 400, 0.0, 1.55),
    "body_medium": (15, 400, 0.0, 1.55),
    "body_small": (13, 400, 0.0, 1.50),
    "label_large": (14, 500, 0.0, 1.32),
    "label_medium": (12, 500, 0.0, 1.32),
    "label_small": (11, 500, 0.2, 1.32),
}


def rgba(hexstr: str, alpha: float) -> str:
    r, g, b = (int(hexstr[i : i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {alpha:g})"


# --------------------------------------------------------------------------
# Emitters
# --------------------------------------------------------------------------

HEADER = """/* Generated by installer/tools/generate-theme.py. Do not edit by hand.
 *
 * A Material 3 tonal system whose key colours are measured from the AuraDE
 * mark. Tones are solved in OKLCh against a CIELAB lightness target, which
 * approximates Material 3's HCT rather than reproducing it; the role mapping,
 * shape scale, state layers and type scale follow the published spec.
 *
 * libadwaita's own named colours are redefined from the same roles, so every
 * stock widget wears this palette instead of being fought with overrides.
 */
"""


#: What the high contrast sheets add on top of the shared component rules.
#:
#: The tone table alone is not enough, and the measurement says why: a card
#: against its ground is 1.05:1 in the normal schemes. It is not separated by
#: tone at all, it is separated by a one pixel outline, and pushing a 1.05:1
#: relationship further apart leaves it at 1.05:1. So the surfaces that had no
#: outline get one, and the ones that had a hairline get a line somebody can
#: actually see.
#:
#: This is also why high contrast is not a filter over the existing scheme. A
#: filter can change colours. It cannot add an edge that was never drawn.
HIGH_CONTRAST_RULES = """
/* ---- high contrast: every container gets an edge --------------------- */

.aurade-pane,
.aurade-pane-flat,
.aurade-hero,
.card,
.aurade-live-step,
.aurade-waiting,
row.activatable,
list.boxed-list {
  border: 2px solid @m3_outline;
}

/* The gate keeps its own edge and gets it thicker, because it is the one
   surface that must not look like the others. */
.aurade-danger-pane {
  border: 3px solid @m3_error;
}

/* A focus ring somebody can actually see, which is the clearest case of a
   change that helps everybody and is noticed by nobody. */
*:focus-visible {
  outline: 3px solid @m3_primary;
  outline-offset: 2px;
}

/* The icon tile stops being a coloured disc, because a coloured disc at high
   contrast is a grey disc. */
.aurade-icon-tile {
  border: 2px solid @m3_outline;
}
"""


def emit_css(scheme: dict[str, str], name: str) -> str:
    """One complete stylesheet for one scheme.

    Two files rather than one, because GTK's `@define-color` is global: there
    is no selector, no media query and no cascade that can give a named colour
    a second value for the dark scheme. A single sheet therefore pins every
    custom surface to whichever scheme it was generated from - which is what
    this file used to do, and why the dark scheme drew light-coloured cards on
    a dark window with text nobody could read.

    So the widget layer loads whichever of these matches, and swaps the
    provider when the scheme changes. The component rules are identical in
    both; only the role table underneath them differs.
    """
    out = [HEADER, f"\n/* ---- Material 3 roles, {name} ---- */"]
    for role, value in scheme.items():
        out.append(f"@define-color m3_{role} {value};")
    out.append("\n/* ---- libadwaita, mapped onto the roles ---- */")
    out.append(_adw_map(scheme))
    out.append("\n/* ---- state layers ---- */")
    out.append(f"@define-color m3_hover {rgba(scheme['on_surface'], STATE['hover'])};")
    out.append(f"@define-color m3_focus {rgba(scheme['primary'], STATE['focus'])};")
    out.append(f"@define-color m3_pressed {rgba(scheme['on_surface'], STATE['pressed'])};")
    out.append("\n" + _components())
    # rstrip then one newline: the component block already ends with one, and a
    # file that ends in a blank line trips `git diff --check` on every commit.
    if "high contrast" in name:
        out.append(HIGH_CONTRAST_RULES)
    return "\n".join(out).rstrip() + "\n"


def _adw_map(s: dict[str, str]) -> str:
    pairs = [
        ("window_bg_color", "surface"),
        ("window_fg_color", "on_surface"),
        ("view_bg_color", "surface_container_lowest"),
        ("view_fg_color", "on_surface"),
        ("headerbar_bg_color", "surface_container"),
        ("headerbar_fg_color", "on_surface"),
        ("headerbar_border_color", "outline_variant"),
        ("headerbar_backdrop_color", "surface"),
        ("headerbar_shade_color", "outline_variant"),
        ("card_bg_color", "surface_container_low"),
        ("card_fg_color", "on_surface"),
        ("dialog_bg_color", "surface_container_high"),
        ("dialog_fg_color", "on_surface"),
        ("popover_bg_color", "surface_container_high"),
        ("popover_fg_color", "on_surface"),
        ("sidebar_bg_color", "surface_container_low"),
        ("sidebar_fg_color", "on_surface"),
        ("accent_bg_color", "primary"),
        ("accent_fg_color", "on_primary"),
        ("accent_color", "primary"),
        ("destructive_bg_color", "error"),
        ("destructive_fg_color", "on_error"),
        ("destructive_color", "error"),
        ("error_bg_color", "error"),
        ("error_fg_color", "on_error"),
        ("error_color", "error"),
        ("success_bg_color", "tertiary"),
        ("success_fg_color", "on_tertiary"),
        ("success_color", "tertiary"),
        ("warning_bg_color", "warning_container"),
        ("warning_fg_color", "on_warning_container"),
        ("warning_color", "warning"),
    ]
    return "\n".join(f"@define-color {name} {s[role]};" for name, role in pairs)


def _components() -> str:
    return _type_scale() + COMPONENT_CSS


def _type_scale() -> str:
    """Every role in the Material 3 type scale, emitted from the spec table.

    Written out rather than hand-picked, because a class the widget layer asks
    for and the stylesheet does not carry is not an error anywhere: the label
    simply renders at the default size and the hierarchy quietly collapses.
    """
    lines = ['/* ---- type scale ---- */', '',
             'window.aurade {',
             '  font-family: "Adwaita Sans", "Cantarell", sans-serif;',
             '  font-size: 15px;',
             '  line-height: 1.5;',
             '}',
             '']
    for name, (size, weight, tracking, line) in TYPE.items():
        selector = ".m3-" + name.replace("_", "-")
        lines.append(
            f"{selector} {{ font-size: {size}px; font-weight: {weight}; "
            f"letter-spacing: {tracking}px; line-height: {line}; }}"
        )
    return "\n".join(lines)


COMPONENT_CSS = r"""

/* The machine voice. Everything the user has to match against hardware or
   type back exactly is set here, never in the prose face. */
.aurade-mono {
  font-family: "JetBrains Mono", "Adwaita Mono", monospace;
  font-feature-settings: "zero" 1, "ss01" 1;
  letter-spacing: 0.2px;
}

/* ---- surfaces --------------------------------------------------------- */

.aurade-pane {
  background: @m3_surface_container_low;
  border-radius: 16px;
  border: 1px solid @m3_outline_variant;
}

.aurade-pane-flat {
  background: @m3_surface_container_low;
  border-radius: 16px;
}

.aurade-hero {
  background: @m3_surface;
}

/* ---- the erase gate: serious, and legible ------------------------------
   This was `background: @m3_error_container` on a pane whose own padding is
   16px, with a boxed list inside it painting its own surface on top. The fill
   therefore only ever showed as a 16px ring of #93000c, which reads as a
   certificate error rather than as a warning, and it framed the four facts
   somebody is meant to be checking against the sticker on their drive. Alarm
   around the thing you need to read carefully is the wrong way round.

   Still the one surface in the installer with an error edge and an error
   ground, so it is still nothing else on any other page. It just no longer
   shouts over its own contents. The list inside goes transparent so the
   ground is one surface rather than a border. */

.aurade-danger-pane {
  background: @m3_danger_surface;
  color: @m3_on_danger_surface;
  border-radius: 16px;
  border: 1px solid @m3_error;
}

.aurade-danger-pane list,
.aurade-danger-pane listview,
.aurade-danger-pane row {
  background: transparent;
  color: inherit;
}

/* Scoped to the editable text. Applied to the whole row, the 17px and the
   letter spacing landed on the floating title too, which is how "Type the
   confirmation" came out as "Type the confirmatio..." above the field. */
.aurade-token-field text {
  font-family: "JetBrains Mono", "Adwaita Mono", monospace;
  font-size: 17px;
  letter-spacing: 1.2px;
}

/* ---- stage list ------------------------------------------------------- */

.aurade-stage-done { color: @m3_tertiary; }
.aurade-stage-active { color: @m3_primary; font-weight: 600; }
.aurade-stage-failed { color: @m3_error; }
.aurade-stage-waiting { color: @m3_outline; }

/* ---- signal strength and other data readouts -------------------------- */

.aurade-metric {
  font-family: "JetBrains Mono", "Adwaita Mono", monospace;
  font-size: 12px;
  color: @m3_on_surface_variant;
}

/* ---- state layers ----------------------------------------------------- */
/* Material 3 expresses interaction as an opacity layer over the container,
   not as a different colour. Same here, so hover on a primary surface and
   hover on a neutral one stay recognisably the same gesture. */

.aurade-selectable:hover { background-image: image(alpha(@m3_on_surface, 0.08)); }
.aurade-selectable:active { background-image: image(alpha(@m3_on_surface, 0.10)); }
.aurade-selectable:focus-visible {
  outline: 2px solid @m3_primary;
  outline-offset: -2px;
}

/* ---- focus, on everything --------------------------------------------- */
/*
   This used to be on the disk and network rows only, which are the two places
   somebody is obviously choosing between things. Everything else fell back to
   whatever GTK draws by default, and on a dark surface a default focus ring is
   easy to lose track of.

   It is the clearest case of the rule this whole pass keeps arriving at: a
   change that costs nothing, is invisible to anybody using a pointer, and is
   the difference between usable and not for anybody who is not.

   `:focus-visible` rather than `:focus`, so it appears for the keyboard and
   stays out of the way of the mouse.
*/
*:focus-visible {
  outline: 2px solid @m3_primary;
  outline-offset: 2px;
}

/* ---- motion ----------------------------------------------------------- */
/* Material 3 emphasised easing. Applied only where a change of state needs
   acknowledging; nothing here loops. */

.aurade-transition {
  transition: background 220ms cubic-bezier(0.2, 0, 0, 1),
              color 220ms cubic-bezier(0.2, 0, 0, 1),
              opacity 220ms cubic-bezier(0.2, 0, 0, 1);
}

/* ---- readiness -------------------------------------------------------- */
/* The verdict is the loudest surface in the product, and it is the only one
   whose colour is the message rather than decoration: a tonal container in
   the tertiary, secondary or error family, read before any of the findings
   under it. Material 3 calls these container roles, and the reason to use
   them here rather than a plain accent is that each one arrives with an
   `on_` colour that is guaranteed against it. */

.aurade-verdict {
  border-radius: 28px;
  padding: 22px 26px;
}

.aurade-verdict-ok {
  background: @m3_tertiary_container;
  color: @m3_on_tertiary_container;
}

.aurade-verdict-attention {
  background: @m3_secondary_container;
  color: @m3_on_secondary_container;
}

.aurade-verdict-blocked {
  background: @m3_error_container;
  color: @m3_on_error_container;
}

/* The one step that is happening, and the card it happens in.

   Roomier than the other cards on purpose. It holds four things - the step,
   the ribbon, the count under it and the pacing - and it is the only thing on
   this page that anybody is looking at, so it gets the padding of something
   that matters rather than the padding of a list row. */
.card,
.aurade-live-step {
  border-radius: 16px;
}

.aurade-live-step {
  padding: 24px;
  background: @m3_surface_container_low;
}

/* And the card underneath, which is deliberately quieter: it holds the thing
   to read or the thing to play, and it must not compete with the install. */
.aurade-waiting {
  padding: 20px;
  background: @m3_surface_container;
  border-radius: 16px;
}

/* The verdict's own glyph, in a disc of its container's ink. Material 3 puts
   a leading icon in a shape rather than loose beside the text, and at this
   size - the first thing on the first page - the difference is between a
   decoration and a verdict. */
.aurade-verdict-badge {
  border-radius: 999px;
  padding: 13px;
}

.aurade-verdict-ok .aurade-verdict-badge {
  background: alpha(@m3_on_tertiary_container, 0.12);
}

.aurade-verdict-attention .aurade-verdict-badge {
  background: alpha(@m3_on_secondary_container, 0.12);
}

.aurade-verdict-blocked .aurade-verdict-badge {
  background: alpha(@m3_on_error_container, 0.12);
}

/* One finding's subject, in the same shape one size down. Five identical
   ticks in a column tell you five things passed and nothing about what they
   were; the tile is what makes the page scannable without reading it. The
   state is carried by the tile's colour and by the mark at the other end of
   the row, so a finding that needs attention is visible from across a desk. */
.aurade-icon-tile {
  border-radius: 999px;
  padding: 9px;
  background: @m3_surface_container_high;
  color: @m3_on_surface_variant;
}

.aurade-tile-ok {
  background: @m3_tertiary_container;
  color: @m3_on_tertiary_container;
}

.aurade-tile-warn {
  background: @m3_secondary_container;
  color: @m3_on_secondary_container;
}

.aurade-tile-blocked {
  background: @m3_error_container;
  color: @m3_on_error_container;
}

/* What to do about it. Only ever present on a card that needs an answer. */
.aurade-action { color: @m3_on_surface; }

.aurade-glyph-ok { color: @m3_tertiary; }
.aurade-glyph-warn { color: @m3_secondary; }
.aurade-glyph-blocked { color: @m3_error; }

/* ---- disclosure ------------------------------------------------------- */
/* Advanced storage and the technical details both live behind one of these.
   Neither is hidden because it is dangerous; they are folded because the
   default answer is right for almost everyone and an expanded page of
   choices reads as a page of decisions you are required to make. */

.aurade-disclosure {
  background: @m3_surface_container_low;
  border-radius: 16px;
  padding: 8px 14px;
  border: 1px solid @m3_outline_variant;
}

/* GTK builds an expander as box > title > (arrow + label), so the header row
   is reached through `title` rather than by styling the widget itself. */
.aurade-disclosure > box > title {
  color: @m3_primary;
  font-weight: 600;
  padding: 4px 0;
}

.aurade-disclosure > box > title:hover {
  background-image: image(alpha(@m3_primary, 0.08));
  border-radius: 8px;
}

/* ---- scheme toggle ---------------------------------------------------- */

.aurade-scheme-button,
.aurade-chrome-button {
  border-radius: 999px;
  padding: 4px;
  min-width: 30px;
  min-height: 30px;
}

.aurade-scheme-button:checked {
  background: @m3_secondary_container;
  color: @m3_on_secondary_container;
}
"""


def emit_python(palettes, light, dark, brand) -> str:
    lines = [
        '"""Generated by installer/tools/generate-theme.py. Do not edit by hand.',
        "",
        "The same Material 3 roles the stylesheet defines, for the parts of the",
        "interface that are drawn rather than styled. Cairo cannot read GTK CSS,",
        "so the aurora, the signal arcs and the stage timeline read their colours",
        "from here and stay in step with everything else by construction.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        f"BRAND_HUES = {{{', '.join(f'{k!r}: {v[0]:.3f}' for k, v in brand.items())}}}",
        "",
        "PALETTES = {",
    ]
    for name, ramp_ in palettes.items():
        body = ", ".join(f"{t}: {v!r}" for t, v in ramp_.items())
        lines.append(f"    {name!r}: {{{body}}},")
    lines.append("}")
    lines.append("")
    for label, scheme in (("LIGHT", light), ("DARK", dark)):
        lines.append(f"{label} = {{")
        for k, v in scheme.items():
            lines.append(f"    {k!r}: {v!r},")
        lines.append("}")
        lines.append("")
    lines.append(f"SHAPE = {SHAPE!r}")
    lines.append(f"STATE = {STATE!r}")
    lines.append(f"TYPE = {TYPE!r}")
    lines.append("")
    lines.append("")
    lines.append("def scheme(dark: bool) -> dict[str, str]:")
    lines.append('    """The role table for the scheme currently in use."""')
    lines.append("    return DARK if dark else LIGHT")
    lines.append("")
    lines.append("")
    lines.append("def rgb(value: str) -> tuple[float, float, float]:")
    lines.append('    """A role colour as Cairo wants it."""')
    lines.append("    return tuple(int(value[i:i + 2], 16) / 255 for i in (1, 3, 5))")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="exit non-zero if the tree differs from a fresh generation")
    args = parser.parse_args()

    brand = measure_brand()
    palettes = build_palettes()
    light, dark = roles(palettes, False), roles(palettes, True)
    light_hc = high_contrast(light, palettes, False)
    dark_hc = high_contrast(dark, palettes, True)
    dark_oled = oled(dark, palettes)

    failures = []
    for scheme_name, scheme in (("light", light), ("dark", dark),
                                ("dark oled", dark_oled)):
        for fg, bg, want in CONTRAST_PAIRS:
            got = contrast(scheme[fg], scheme[bg])
            if got < want:
                failures.append(
                    f"{scheme_name}: {fg} on {bg} is {got:.2f}:1, needs {want}:1"
                )
    # The high contrast schemes are held to 7:1 on every pair, not to each
    # pair's own floor. That is the whole point of them: a pair that only ever
    # had to clear 4.5:1 is exactly the pair somebody turned this on to read.
    for scheme_name, scheme in (("light high contrast", light_hc),
                                ("dark high contrast", dark_hc)):
        for fg, bg, _want in CONTRAST_PAIRS:
            got = contrast(scheme[fg], scheme[bg])
            if got < 7.0:
                failures.append(
                    f"{scheme_name}: {fg} on {bg} is {got:.2f}:1, needs 7.0:1"
                )
    if failures:
        for line in failures:
            print(f"generate-theme: {line}", file=sys.stderr)
        return 1

    lib = os.path.join(ROOT, "installer", "lib", "aurade_gui")
    targets = {
        os.path.join(lib, "theme.css"): emit_css(light, "light"),
        os.path.join(lib, "theme-dark.css"): emit_css(dark, "dark"),
        os.path.join(lib, "theme-hc.css"): emit_css(light_hc, "light high contrast"),
        os.path.join(lib, "theme-dark-hc.css"): emit_css(dark_hc, "dark high contrast"),
        os.path.join(lib, "theme-oled.css"): emit_css(dark_oled, "dark oled"),
        os.path.join(lib, "tokens.py"): emit_python(palettes, light, dark, brand),
    }
    stale = []
    for path, content in targets.items():
        current = open(path).read() if os.path.exists(path) else None
        if current == content:
            continue
        if args.check:
            stale.append(os.path.relpath(path, ROOT))
        else:
            open(path, "w").write(content)
    if stale:
        print("generate-theme: out of date: " + ", ".join(stale), file=sys.stderr)
        return 1
    if not args.check:
        print(f"generate-theme: wrote {len(targets)} files")
        for name, (h, c) in brand.items():
            print(f"  {name:6} hue {h:6.1f}  chroma {c:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
