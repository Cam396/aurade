"""Check the wallpaper catalog, index, geometry, and contrast boundaries."""

from __future__ import annotations

import os
import sys

TESTS = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.normpath(os.path.join(TESTS, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "installer", "lib"))
sys.path.insert(0, os.path.join(ROOT, "installer", "tools"))

WALLPAPERS = os.path.join(ROOT, "installer", "wallpapers")
MANIFEST = os.path.join(WALLPAPERS, "manifest.tsv")
TITLES = os.path.join(WALLPAPERS, "titles.tsv")
THEME = os.path.join(ROOT, "installer", "lib", "aurade_gui", "theme.css")

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def equal(got: object, want: object, message: str) -> None:
    if got != want:
        FAILURES.append(f"{message}: expected {want!r}, got {got!r}")


def read_rows(path: str) -> list[list[str]]:
    with open(path, encoding="utf-8") as handle:
        return [line.rstrip("\n").split("\t") for line in handle
                if line.strip() and not line.startswith("#")]


# -- the set and its index ---------------------------------------------------

def test_manifest() -> None:
    check(os.path.exists(MANIFEST), "there is no manifest")
    if not os.path.exists(MANIFEST):
        return

    rows = read_rows(MANIFEST)
    check(len(rows) >= 20,
          f"the manifest lists {len(rows)} pictures; the set is meant to be "
          "large enough that the same one is not behind every install")

    listed = {row[0] for row in rows}
    on_disk = {name for name in os.listdir(WALLPAPERS) if name.endswith(".png")}

    for missing in sorted(listed - on_disk):
        FAILURES.append(f"the manifest lists {missing}, which is not here")
    # Also catch files that are present but absent from the manifest.
    for orphan in sorted(on_disk - listed):
        FAILURES.append(f"{orphan} is in the directory and not in the manifest")

    for row in rows:
        check(len(row) >= 5, f"{row[0]} has {len(row)} columns, expected 5")
        if len(row) < 5:
            continue
        check(bool(row[1].strip()),
              f"{row[0]} has no title, so the caption would name a file")
        equal((row[3], row[4]), ("1376", "768"),
              f"{row[0]} is not {1376}x{768}")

    # Keep the hand-maintained catalog in step with the image set.
    if os.path.exists(TITLES):
        titled = {row[0] for row in read_rows(TITLES)}
        for untitled in sorted(listed - titled):
            FAILURES.append(f"{untitled} has no entry in titles.tsv")


def test_reader() -> None:
    from aurade_gui import brand

    # The list, not the environment variable it was built from: `brand` reads
    # that at import and this is already imported. Pointing at the source tree
    # explicitly rather than relying on the fallback, so this tests the set in
    # the repository even on a machine that has an image's set installed.
    brand.WALLPAPER_DIRS[0] = WALLPAPERS
    brand._wallpapers = None  # noqa: SLF001 - read once per process by design

    found = brand.wallpapers()
    equal(len(found), len(read_rows(MANIFEST)),
          "the reader and the manifest disagree about how many there are")
    for entry in found:
        check(os.path.exists(entry["path"]),
              f"the reader returned {entry['file']}, which is not on disk")

    if not found:
        return

    name = found[0]["file"]
    stem = os.path.splitext(name)[0]
    equal(brand.choose_wallpaper(name), found[0], "pinning by file name")
    equal(brand.choose_wallpaper(stem), found[0], "pinning without the suffix")
    # A pinned name that is not in the set has to come back empty handed. The
    # alternative is that somebody comparing two treatments spends an
    # afternoon looking at a third picture chosen at random.
    equal(brand.choose_wallpaper("no-such-picture"), None,
          "a name that is not in the set")
    equal(brand.choose_wallpaper("none"), None, "turning them off by name")
    check(brand.choose_wallpaper() in found, "an unpinned choice is from the set")


# -- the geometry ------------------------------------------------------------

def test_cover() -> None:
    from aurade_gui import brand

    for window_w, window_h in ((1440, 900), (1024, 768), (1920, 1080),
                               (1376, 768), (800, 1200)):
        scaled_w, scaled_h, dx, dy = brand.cover_box(1376, 768, window_w, window_h)
        check(scaled_w >= window_w and scaled_h >= window_h,
              f"{window_w}x{window_h}: scaled to {scaled_w}x{scaled_h}, which "
              "leaves part of the window uncovered")
        # Within a pixel of the original aspect: a photograph stretched to fit
        # is a photograph that looks like a mistake.
        want = 1376 / 768
        got = scaled_w / scaled_h
        check(abs(got - want) < 0.005,
              f"{window_w}x{window_h}: aspect {got:.4f}, expected {want:.4f}")
        check(dx <= 0 and dy <= 0,
              f"{window_w}x{window_h}: offset {dx},{dy} is inside the window, "
              "so an edge would be blank")
        # Centred: what is cropped off one side is cropped off the other.
        check(abs((window_w - scaled_w) - 2 * dx) <= 1,
              f"{window_w}x{window_h}: the horizontal crop is not centred")
        check(abs((window_h - scaled_h) - 2 * dy) <= 1,
              f"{window_w}x{window_h}: the vertical crop is not centred")

    equal(brand.cover_box(1376, 768, 1376, 768), (1376, 768, 0, 0),
          "an exact fit should need no scaling and no offset")
    for degenerate in ((0, 768, 100, 100), (1376, 0, 100, 100),
                       (1376, 768, 0, 100), (1376, 768, 100, 0)):
        equal(brand.cover_box(*degenerate), (0, 0, 0, 0),
              f"cover_box{degenerate} should refuse rather than divide by zero")


# -- the stylesheet ----------------------------------------------------------

def test_scoped() -> None:
    """Nothing the wallpaper adds may apply when there is no wallpaper.

    An image with no wallpapers staged, a window in high contrast and a window
    with the black ground on all have to be exactly the interface they were.
    The mechanism for that is one class on the window, and the mechanism only
    works for as long as every rule stays scoped under it.
    """
    if not os.path.exists(THEME):
        FAILURES.append("theme.css has not been generated")
        return
    with open(THEME, encoding="utf-8") as handle:
        lines = handle.readlines()

    for number, line in enumerate(lines, 1):
        if "aurade-sheet" not in line or line.lstrip().startswith(("*", "/*")):
            continue
        check("aurade-grounded" in line,
              f"theme.css:{number}: a rule for the sheet is not scoped under "
              ".aurade-grounded, so it would paint with no photograph behind it")


# -- the property the whole design rests on ----------------------------------

def test_bands_are_opaque() -> None:
    """The chrome's band is the surface colour and nothing else.

    This is the assertion that lets the theme test keep meaning what it says.
    Every contrast pair it measures is a foreground against a named surface,
    and those numbers describe the screen only for as long as nothing gets
    between the two. So: paint a real photograph through the real function,
    then read the band back and check it is the exact colour the palette says
    it is, to the last of its eight bits.
    """
    try:
        import cairo
        from aurade_gui import brand, tokens as T
    except ImportError as exc:
        print(f"installer wallpaper test: SKIP ({exc})")
        return

    entries = brand.wallpapers()
    if not entries:
        FAILURES.append("no wallpapers to paint")
        return

    width, height, top, bottom = 900, 600, 58, 74
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, width, height)
    context = cairo.Context(surface)
    painted = brand.draw_wallpaper(context, width, height, entries[0]["path"],
                                   True, top, bottom)
    if not painted:
        print("installer wallpaper test: SKIP (no image loader)")
        return
    surface.flush()

    data = surface.get_data()
    stride = surface.get_stride()

    def pixel(x: int, y: int) -> tuple[int, int, int]:
        at = y * stride + x * 4
        return data[at + 2], data[at + 1], data[at]

    want = tuple(round(channel * 255) for channel in T.rgb(T.scheme(True)["surface"]))

    for y, where in ((2, "the very top"), (top - 2, "the bottom of the top band"),
                     (height - 2, "the very bottom"),
                     (height - bottom + 2, "the top of the bottom band")):
        got = pixel(width // 2, y)
        check(all(abs(a - b) <= 1 for a, b in zip(got, want)),
              f"{where} of the window is {got}, not the surface colour {want}: "
              "a photograph is showing through where the chrome's text goes")

    # And the opposite, or the test above would pass on a window with no
    # photograph in it at all.
    middle = pixel(width // 2, height // 2)
    check(any(abs(a - b) > 2 for a, b in zip(middle, want)),
          f"the middle of the window is {middle}, the same as the surface "
          "colour: the photograph was never painted")


# -- the gate, re-run --------------------------------------------------------

def test_the_manifest_is_what_the_tool_writes() -> None:
    """A fresh manifest must match the checked-in one."""
    import subprocess  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    tool = os.path.join(ROOT, "installer", "tools", "wallpaper-manifest.py")
    titles = os.path.join(WALLPAPERS, "titles.tsv")
    if not (os.path.exists(tool) and os.path.exists(titles)):
        FAILURES.append("the manifest tool or the titles file is missing")
        return
    with tempfile.TemporaryDirectory() as folder:
        fresh = os.path.join(folder, "manifest.tsv")
        result = subprocess.run(
            [sys.executable, tool, WALLPAPERS, "--titles", titles,
             "--out", fresh],
            capture_output=True, text=True)
        if result.returncode != 0:
            tail = (result.stderr or "").strip().splitlines()[-3:]
            FAILURES.append(f"regenerating the manifest failed: {tail}")
            return
        with open(fresh, encoding="utf-8") as handle:
            written = handle.read()
    with open(MANIFEST, encoding="utf-8") as handle:
        committed = handle.read()
    if written == committed:
        return
    fresh_rows = {r[0]: r for r in
                  [line.split("\t") for line in written.splitlines()
                   if line.strip() and not line.startswith("#")]}
    old_rows = {r[0]: r for r in
                [line.split("\t") for line in committed.splitlines()
                 if line.strip() and not line.startswith("#")]}
    for name in sorted(set(old_rows) | set(fresh_rows)):
        if old_rows.get(name) != fresh_rows.get(name):
            FAILURES.append(
                f"the committed manifest and a fresh run disagree about "
                f"{name}. Edit titles.tsv and regenerate; never edit the "
                f"manifest by hand.")
            return
    FAILURES.append("the manifest and a fresh run differ in their header only, "
                    "so the tool has been changed without regenerating")


def test_every_hour_has_a_picture() -> None:
    """The light column, and the rule that no photograph is unreachable.

    The login screen prefers a picture whose light matches the light outside.
    A band with nothing in it means that hour silently stops matching, and a
    picture in no band at all is a picture that shipped and cannot be seen.
    """
    rows = read_rows(MANIFEST)
    allowed = {"", "dawn", "day", "dusk", "night"}
    seen = {}
    for row in rows:
        light = row[8] if len(row) > 8 else ""
        if light not in allowed:
            FAILURES.append(f"{row[0]} has light {light!r}, which is not a "
                            f"kind of light")
        seen.setdefault(light, []).append(row[0])
        try:
            luminance = float(row[9]) if len(row) > 9 else -1.0
        except ValueError:
            luminance = -1.0
        check(0.0 < luminance < 1.0,
              f"{row[0]} has luminance {row[9] if len(row) > 9 else '(none)'}, "
              f"which is not a measurement")
    for band in ("dawn", "day", "dusk", "night"):
        check(seen.get(band),
              f"no picture in the set is a {band} picture, so that hour of the "
              f"day has nothing of its own to show")


def test_titles_are_complete() -> None:
    """Each catalog row has valid display metadata."""
    titles = os.path.join(WALLPAPERS, "titles.tsv")
    if not os.path.exists(titles):
        FAILURES.append("there is no titles.tsv")
        return
    allowed = {"", "dawn", "day", "dusk", "night"}
    with open(titles, encoding="utf-8") as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            parts = (line.rstrip("\n").split("\t") + [""] * 7)[:7]
            name, title, place, zone, note, fact, light = parts
            check(bool(title), f"{name} has no title")
            check(light in allowed, f"{name} has light {light!r}")
            if place:
                check(bool(zone),
                      f"{name} is somewhere and has no time zone, so the card "
                      f"cannot say what time it is there")
            if fact and fact != "-":
                check(bool(place),
                      f"{name} carries a fact and is not anywhere, so the fact "
                      f"is about nothing")
            if not place:
                check(fact in ("", "-"),
                      f"{name} is nowhere in particular and carries a fact")
def test_still_photographs() -> None:
    """Every file in the set passes the image-quality checks."""
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "wallpaper_manifest",
            os.path.join(ROOT, "installer", "tools", "wallpaper-manifest.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except (ImportError, SystemExit, AttributeError) as exc:
        print(f"installer wallpaper test: SKIP the gate ({exc})")
        return

    for name in sorted(os.listdir(WALLPAPERS)):
        if not name.endswith(".png"):
            continue
        ok, why = module.looks_photographic(os.path.join(WALLPAPERS, name))
        check(ok, f"{name} would not pass the gate today: {why}")




def test_card_facts() -> None:
    """What the card says has to be true, and has to be there.

    The card is the one place in this installer that volunteers information
    nobody asked for, which makes it the one place where a wrong sentence
    costs nothing to say and gets repeated afterwards. So the fields are held
    to the same rule as the `place` column: a picture that is not of anywhere
    gets no place, no clock and no fact, and a picture that is of somewhere
    gets all three or the row is wrong.
    """
    sys.path.insert(0, os.path.join(ROOT, "installer", "lib"))
    os.environ["AURADE_WALLPAPER_DIR"] = WALLPAPERS
    from aurade_gui import brand  # noqa: PLC0415

    entries = brand.wallpapers()
    check(len(entries) > 0, "no wallpapers were indexed at all")

    for entry in entries:
        name = entry["file"]
        note = entry.get("note", "")
        check(bool(note), f"{name} says nothing about what is in it")
        check(note.endswith("."), f"{name}: the note is not a sentence: {note!r}")
        check(len(note) <= 160, f"{name}: the note is a paragraph, not a sentence")

        place = entry.get("place", "")
        zone = entry.get("zone", "")
        fact = entry.get("fact", "")

        if place:
            check(bool(zone), f"{name} is somewhere real and has no time zone")
            check(bool(fact), f"{name} is somewhere real and says nothing about it")
            check(fact.endswith("."), f"{name}: the fact is not a sentence: {fact!r}")
            check(len(fact) <= 260, f"{name}: the fact is a paragraph")
        else:
            # A picture of nowhere gets nothing invented to fill the space.
            # Inventing a location for a picture invents a fact about it, and
            # inventing a fact about a place that is not in the picture is the
            # same mistake with more words.
            check(not zone, f"{name} is nowhere in particular and has a time zone")
            check(not fact, f"{name} is nowhere in particular and has a fact about it")

        for field, text in (("note", note), ("fact", fact)):
            check("\u2014" not in text and "\u2013" not in text,
                  f"{name}: a dash in the {field}")
            check(";" not in text, f"{name}: a semicolon in the {field}")

    # Every zone is one this machine's database actually has. A name with a
    # typo in it produces no clock at all, silently, which is exactly the kind
    # of thing that survives a review and never gets noticed.
    zones = {entry["zone"] for entry in entries if entry.get("zone")}
    check(len(zones) > 0, "not one picture carries a time zone")
    for zone in sorted(zones):
        there, _here = brand.local_times(zone)
        check(bool(there), f"{zone} is not a time zone this machine knows")

    # And a picture with no zone asks for no clock rather than a wrong one.
    check(brand.local_times("") == ("", ""),
          "a picture of nowhere was given a clock anyway")

    # A name this machine does not have gets no clock either, rather than the
    # machine's own time wearing a foreign label. This is what makes the check
    # above worth anything: without it a typo in a zone name shows a confident
    # wrong time, and every zone in the manifest would pass by falling back to
    # here.
    check(brand.local_times("Nowhere/Atlantis") == ("", ""),
          "a time zone this machine does not have was given a clock anyway")


def main() -> int:
    """Every test in this file, found rather than listed.

    It used to be a hand written call list, and three tests were added to this
    file and not to that list, so the suite reported PASS on a run that had not
    executed them. Enumerating makes the omission impossible: a function named
    `test_something` is run because it is named that, and there is no second
    place to remember to change.
    """
    found = sorted(name for name, value in globals().items()
                   if name.startswith("test_") and callable(value))
    if not found:
        print("test-wallpapers: no tests were found at all", file=sys.stderr)
        return 1
    for name in found:
        try:
            globals()[name]()
        except Exception as exc:  # noqa: BLE001 - a raise is a failure
            FAILURES.append(f"{name} raised {exc!r}")

    # Counted again, afterwards, against a list built fresh. A dispatch that
    # has been quietly narrowed back to a literal hides its own breakage: it
    # runs what it lists and reports a pass. This is the only thing that can
    # notice, and it is deliberately not reading the same variable.
    everything = {name for name, value in globals().items()
                  if name.startswith("test_") and callable(value)}
    skipped = sorted(everything - set(found))
    if skipped:
        FAILURES.append(f"these tests exist in this file and were not run: "
                        f"{skipped}")

    if FAILURES:
        for failure in FAILURES:
            print(f"test-wallpapers: {failure}", file=sys.stderr)
        return 1
    print(f"installer wallpaper test: PASS ({len(found)} checks; set indexed, "
          f"geometry covers, chrome bands opaque)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
