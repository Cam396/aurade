"""The generated design tokens, checked against the brand and against AA.

A generated palette is only trustworthy if the generator is the only thing
that can produce it and the result is measured rather than assumed. Both are
asserted here: the tree is compared against a fresh generation, and every
role pair the interface actually uses is measured for contrast in both
schemes.

The third assertion is the interesting one. The palette claims to be derived
from the mark, so the hues are compared back to the artwork. A logo redrawn in
different colours without anyone updating the interface is a product whose
icon and window stop looking related, and that is exactly the kind of drift
nobody notices until it ships.
"""

from __future__ import annotations

import os
import subprocess
import sys

TESTS = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.normpath(os.path.join(TESTS, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "installer", "lib"))
sys.path.insert(0, os.path.join(ROOT, "installer", "tools"))

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def equal(got: object, want: object, message: str) -> None:
    if got != want:
        FAILURES.append(f"{message}: expected {want!r}, got {got!r}")


# -- the tree is what the generator produces ---------------------------------

result = subprocess.run(
    [sys.executable, os.path.join(ROOT, "installer", "tools", "generate-theme.py"),
     "--check"],
    capture_output=True, text=True,
)
check(
    result.returncode == 0,
    "the committed theme is not what the generator produces; run "
    f"installer/tools/generate-theme.py ({result.stderr.strip()})",
)

# The artwork is cut from the logo by a tool, not dropped in by hand, so the
# same rule applies to it as to the palette: the tree has to be what the tool
# produces from the logo the tree carries.
assets = subprocess.run(
    [sys.executable,
     os.path.join(ROOT, "installer", "tools", "extract-brand-assets.py"), "--check"],
    capture_output=True, text=True,
)
check(
    assets.returncode == 0,
    "the committed artwork is not what the extractor produces; run "
    f"installer/tools/extract-brand-assets.py ({assets.stderr.strip()})",
)

from aurade_gui import tokens as T  # noqa: E402

import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "generate_theme", os.path.join(ROOT, "installer", "tools", "generate-theme.py"))
gen = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(gen)


# -- contrast, measured, in both schemes -------------------------------------

for scheme_name, scheme in (("light", T.LIGHT), ("dark", T.DARK)):
    for fg, bg, want in gen.CONTRAST_PAIRS:
        got = gen.contrast(scheme[fg], scheme[bg])
        check(
            got >= want,
            f"{scheme_name}: {fg} on {bg} is {got:.2f}:1, needs {want}:1",
        )

# Body text should clear AAA on the surface it is read on, not merely AA. An
# installer is read once, under stress, sometimes on a laptop panel at an
# angle, by someone who is about to erase a disk.
for scheme_name, scheme in (("light", T.LIGHT), ("dark", T.DARK)):
    got = gen.contrast(scheme["on_surface"], scheme["surface"])
    check(got >= 7.0, f"{scheme_name}: body text is {got:.2f}:1, wanted AAA")

# Neither scheme may use pure black or pure white as a ground. Both kill depth,
# and both are the signature of a palette nobody chose.
for scheme_name, scheme in (("light", T.LIGHT), ("dark", T.DARK)):
    for role in ("surface", "surface_container", "surface_container_high"):
        value = scheme[role]
        check(value not in ("#000000", "#ffffff"),
              f"{scheme_name}: {role} is pure {value}")


# -- the palette still comes from the mark -----------------------------------

brand = gen.measure_brand()
check(set(brand) == {"lilac", "aqua", "plate"},
      f"the brand sample set changed: {sorted(brand)}")

for name, hue in T.BRAND_HUES.items():
    measured = brand[name][0]
    delta = abs((measured - hue + 180) % 360 - 180)
    check(
        delta < 1.0,
        f"the {name} hue in the tokens is {hue:.1f} but the artwork measures "
        f"{measured:.1f}; regenerate the theme",
    )

# The accents are the two ends of the ribbon and are genuinely different
# colours, not one hue used twice with a lightness change.
lilac, aqua = T.BRAND_HUES["lilac"], T.BRAND_HUES["aqua"]
separation = abs((lilac - aqua + 180) % 360 - 180)
check(separation > 45,
      f"the two accent hues are only {separation:.0f} degrees apart")

# Neutrals carry a hue rather than being flat grey. A pure grey next to a
# violet accent reads as unconsidered; the tint is what makes it look chosen.
neutral = T.PALETTES["neutral"][50]
r, g, b = (int(neutral[i:i + 2], 16) for i in (1, 3, 5))
check(max(r, g, b) - min(r, g, b) >= 3,
      f"the neutral ramp is flat grey at tone 50 ({neutral})")


# -- the stylesheet actually defines what the widgets ask for ----------------

css = open(os.path.join(ROOT, "installer", "lib", "aurade_gui", "theme.css")).read()
app = open(os.path.join(ROOT, "installer", "lib", "aurade_gui", "app.py")).read()

for role in ("m3_surface", "m3_on_surface", "m3_primary", "m3_error",
             "m3_outline_variant", "m3_tertiary"):
    check(f"@define-color {role} " in css, f"{role} is not defined in the stylesheet")

# libadwaita's own names are redefined, so stock widgets wear this palette
# instead of being fought with per-widget overrides.
for adw in ("window_bg_color", "accent_bg_color", "card_bg_color",
            "destructive_bg_color", "headerbar_bg_color"):
    check(f"@define-color {adw} " in css,
          f"libadwaita's {adw} is not mapped onto a role")

# Every style class the widget layer asks for has to exist, or it silently
# does nothing and the page renders unstyled.
import re  # noqa: E402

used = set(re.findall(r'add_css_class\("([a-z0-9-]+)"\)', app))
used |= set(re.findall(r'css="([a-z0-9-]+)"', app))
used |= set(re.findall(r'label\([^,]+,\s*"(m3-[a-z-]+)"', app))
stock = {
    # provided by GTK or libadwaita, not by this stylesheet
    "flat", "suggested-action", "destructive-action", "pill", "boxed-list",
    "dim-label", "error", "warning", "success", "card", "monospace", "aurade",
}
for style in sorted(used - stock):
    check(f".{style}" in css, f"the widget layer uses .{style}, which the "
                              "stylesheet does not define")


# -- the drawn layer actually draws -----------------------------------------
#
# The widget layer needs a compositor. The drawn layer does not, so there is no
# excuse for shipping an aurora that raises, a mark whose asset path is wrong,
# or a wordmark that carries its old background with it.

drawn = "skipped"
try:
    import cairo  # noqa: E402
except ImportError:
    pass
else:
    from aurade_gui import brand  # noqa: E402

    check(brand.asset("aurade-mark.png") is not None,
          "the mark is not findable from the source tree")
    check(brand.asset("aurade-wordmark.png") is not None,
          "the wordmark is not findable from the source tree")

    # The wordmark is an ink mask, not a picture. If it still carries the page
    # it was cut from, it lifts a visible rectangle on any surface that is not
    # the one it came off.
    mark_path = brand.asset("aurade-wordmark.png")
    if mark_path:
        try:
            from PIL import Image
        except ImportError:
            pass
        else:
            image = Image.open(mark_path).convert("RGBA")
            w, h = image.size
            px = image.load()
            edge = [px[x, y][3] for x in range(0, w, 2) for y in (0, h - 1)]
            check(min(edge) == 0,
                  "the wordmark mask has no fully transparent pixels on its edges")
            filled = sum(1 for a in edge if a > 8)
            check(filled < len(edge) * 0.5,
                  f"the wordmark mask still carries its background ({filled} of "
                  f"{len(edge)} edge samples are inked)")

    def panel(dark: bool):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 240, 160)
        cr = cairo.Context(surface)
        brand.draw_aurora(cr, 240, 160, dark, 0.4)
        brand.draw_ribbon_rule(cr, 240, 2, dark)
        brand.draw_mark(cr, 240, 160, 40)
        brand.draw_wordmark(cr, 10, 10, 18, T.scheme(dark)["on_surface"])
        brand.draw_signal(cr, 24, 20, 70, T.scheme(dark)["primary"],
                          T.scheme(dark)["outline_variant"])
        surface.flush()
        return bytes(surface.get_data())

    light_px, dark_px = panel(False), panel(True)
    check(len(set(light_px)) > 8, "the light panel drew a flat colour")
    check(light_px != dark_px, "the two schemes drew identically")
    drawn = "drawn"

# The aurora has to stay behind text rather than compete with it, and the arc
# scale has to be monotonic or the strongest network is not the fullest icon.
try:
    from aurade_gui import brand as B  # noqa: E402
except ImportError:
    pass
else:
    for dark in (False, True):
        for _role, _x, _y, _r, alpha in B.aurora_fields(dark):
            check(alpha <= 0.45, f"an aurora field is {alpha} opaque")
    arcs = [B.signal_arcs(s) for s in (0, 10, 40, 60, 80, 100)]
    equal(arcs, sorted(arcs), f"the signal scale is not monotonic: {arcs}")
    equal(B.signal_arcs(0), 0, "a dead signal lit an arc")
    equal(B.signal_arcs(100), 4, "a full signal did not light every arc")


if FAILURES:
    for failure in FAILURES:
        print(f"test-gui-theme: {failure}", file=sys.stderr)
    sys.exit(1)
print(
    "installer GUI theme test: PASS "
    f"({len(gen.CONTRAST_PAIRS) * 2} contrast pairs, {len(used - stock)} style "
    f"classes, brand layer {drawn})"
)
