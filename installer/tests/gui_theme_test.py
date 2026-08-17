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

LIB = os.path.join(ROOT, "installer", "lib", "aurade_gui")
css = open(os.path.join(LIB, "theme.css")).read()
dark_css = open(os.path.join(LIB, "theme-dark.css")).read()
app = open(os.path.join(LIB, "app.py")).read()

for role in ("m3_surface", "m3_on_surface", "m3_primary", "m3_error",
             "m3_outline_variant", "m3_tertiary"):
    check(f"@define-color {role} " in css, f"{role} is not defined in the stylesheet")
    check(f"@define-color {role} " in dark_css,
          f"{role} is not defined in the dark stylesheet")

# libadwaita's own names are redefined, so stock widgets wear this palette
# instead of being fought with per-widget overrides.
for adw in ("window_bg_color", "accent_bg_color", "card_bg_color",
            "destructive_bg_color", "headerbar_bg_color"):
    check(f"@define-color {adw} " in css,
          f"libadwaita's {adw} is not mapped onto a role")

# Two sheets, and they must actually differ.
#
# GTK's `@define-color` is global: a named colour has one value per loaded
# sheet and no selector can give it a second one. So the dark scheme is a
# second file that the widget layer swaps in, and the failure this guards
# against is the one that shipped - a dark window drawing light-scheme cards
# with unreadable text on them, because only libadwaita's own names switched
# and none of the custom ones did.
import re  # noqa: E402


def defined(sheet: str) -> dict[str, str]:
    return dict(re.findall(r"@define-color\s+([A-Za-z0-9_]+)\s+([^;]+);", sheet))


light_roles, dark_roles = defined(css), defined(dark_css)
check(set(light_roles) == set(dark_roles),
      "the two stylesheets define different names: "
      f"{sorted(set(light_roles) ^ set(dark_roles))}")
differing = sum(1 for name in light_roles
                if light_roles[name] != dark_roles.get(name))
check(differing > 20,
      f"only {differing} colours differ between the schemes; the dark sheet is "
      "not a dark sheet")
for role in ("m3_surface", "m3_on_surface", "m3_surface_container_low"):
    check(light_roles.get(role) != dark_roles.get(role),
          f"{role} is the same colour in both schemes ({light_roles.get(role)})")

# Every component rule is in both sheets, or a card styled in one scheme is an
# unstyled box in the other.
for style in ("aurade-verdict", "aurade-verdict-badge", "aurade-icon-tile",
              "aurade-tile-ok", "aurade-disclosure", "aurade-scheme-button",
              "aurade-mono"):
    check(f".{style}" in dark_css,
          f".{style} is missing from the dark stylesheet")

# And the widget layer has to actually load the second one.
check("THEME_DARK_CSS" in app and "_load_stylesheet" in app,
      "the widget layer never loads the dark stylesheet")

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
    "linked",
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
        brand.draw_capacity(cr, 84, 6, dark, 0.4)
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

    # The disk size bar. A bar of the wrong length on the disk page is a claim
    # about which drive is bigger, made to somebody about to erase one of
    # them, so the failure mode that matters is a size this cannot read being
    # drawn as though it could.
    for text, want in (("476.9G", 476.9 * 1024 ** 3), ("1.8T", 1.8 * 1024 ** 4),
                       ("356.9M", 356.9 * 1024 ** 2), ("512GB", 512 * 1024 ** 3),
                       ("1024", 1024.0)):
        got = B.parse_size(text)
        check(abs(got - want) < 1,
              f"parse_size({text!r}) is {got}, expected {want}")
    for unreadable in ("", "nope", "12X", "-5G", None):
        equal(B.parse_size(unreadable), 0.0,
              f"parse_size({unreadable!r}) should refuse rather than guess")
        equal(B.capacity_fraction(unreadable, 1024.0 ** 4), 0.0,
              f"a bar was sized from {unreadable!r}")

    biggest = B.parse_size("1.8T")
    equal(B.capacity_fraction("1.8T", biggest), 1.0,
          "the largest disk does not fill its bar")
    sizes = ["8G", "356.9M", "476.9G", "1T", "1.8T"]
    bars = [B.capacity_fraction(s, biggest) for s in sizes]
    ordered = sorted(zip((B.parse_size(s) for s in sizes), bars))
    equal([bar for _size, bar in ordered], sorted(bar for _size, bar in ordered),
          f"a bigger disk drew a shorter bar: {list(zip(sizes, bars))}")
    check(min(bars) >= B.CAPACITY_FLOOR,
          f"the smallest disk drew {min(bars)} of a bar, which is nothing")
    check(max(bars) <= 1.0, f"a bar ran past its track: {max(bars)}")


if FAILURES:
    for failure in FAILURES:
        print(f"test-gui-theme: {failure}", file=sys.stderr)
    sys.exit(1)
print(
    "installer GUI theme test: PASS "
    f"({len(gen.CONTRAST_PAIRS) * 2} contrast pairs, {len(used - stock)} style "
    f"classes, brand layer {drawn})"
)
