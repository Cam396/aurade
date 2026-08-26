#!/usr/bin/env python3
"""The design system is one design system.

The greeter carries copies of the installer's tokens, brand drawing,
accessibility helpers, status readings and generated stylesheets, because the
installer only ever exists on the installation media and the greeter only ever
exists on the installed system, so neither can import the other.

Copies drift. This file is the reason they cannot drift quietly: every vendored
file is compared byte for byte against its original, and a difference fails
rather than being noticed six months later when a purple in one place stopped
matching a purple in the other.

If this test fails, the fix is to copy the file again. It is not to edit the
copy until the numbers agree, and it is certainly not to relax the comparison.
"""

from __future__ import annotations

import hashlib
import os
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
PACKAGE = os.path.normpath(os.path.join(HERE, ".."))
ROOT = os.path.normpath(os.path.join(PACKAGE, ".."))
SHARED = os.path.join(PACKAGE, "aurade_greeter", "shared")
ORIGIN = os.path.join(ROOT, "installer", "lib", "aurade_gui")

#: Everything carried across, and nothing else.
VENDORED = (
    "tokens.py",
    "brand.py",
    "a11y.py",
    "status.py",
    "theme.css",
    "theme-dark.css",
    "theme-hc.css",
    "theme-dark-hc.css",
    "theme-oled.css",
)

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def digest(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def test_every_copy_matches_its_original() -> None:
    for name in VENDORED:
        copy = os.path.join(SHARED, name)
        original = os.path.join(ORIGIN, name)
        if not os.path.isfile(original):
            FAILURES.append(f"{name} has no original at {ORIGIN}")
            continue
        if not os.path.isfile(copy):
            FAILURES.append(f"{name} was never carried into the greeter")
            continue
        check(digest(copy) == digest(original),
              f"{name} in the greeter is no longer the installer's {name}")


def test_nothing_extra_was_added_to_the_shared_directory() -> None:
    """A file that lives here and nowhere else is a file nothing checks."""
    allowed = set(VENDORED) | {"__init__.py", "__pycache__"}
    for name in sorted(os.listdir(SHARED)):
        check(name in allowed,
              f"{name} sits in the shared directory with nothing to compare it to")


def test_the_copies_still_work_where_they_landed() -> None:
    """Vendoring must not have broken the relative import inside brand."""
    sys.path.insert(0, PACKAGE)
    try:
        from aurade_greeter.shared import brand, status, tokens
    except Exception as exc:  # noqa: BLE001 - any failure here is the failure
        FAILURES.append(f"the carried modules do not import: {exc!r}")
        return
    check(bool(tokens.LIGHT) and bool(tokens.DARK),
          "the carried tokens have no palettes in them")
    check(brand.aurora_fields(True) and brand.aurora_fields(False),
          "the carried aurora has no fields to draw")
    check(isinstance(status.clock(0.0), str) and len(status.clock(0.0)) == 5,
          "the carried clock does not read as a clock")


def main() -> int:
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            function()
    if FAILURES:
        print("greeter shared design test: FAIL")
        for failure in FAILURES:
            print(f"  {failure}")
        return 1
    print("greeter shared design test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
