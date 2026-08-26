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
SHARED = os.path.join(PACKAGE, "aurade_greeter")
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


#: Whether the thing being compared against is here at all.
#:
#: This test's whole job is to catch two files in one repository drifting
#: apart. Inside a package build there is only one of them, because the
#: installer is not part of this package and never will be, so there is
#: nothing to compare and nothing that could be caught. It says so rather
#: than failing, and rather than passing quietly: a run that proved nothing
#: has to be distinguishable from a run that proved something.
HAVE_ORIGINALS = os.path.isdir(ORIGIN)


def test_every_copy_matches_its_original() -> None:
    if not HAVE_ORIGINALS:
        return
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


#: This package's own files, which have no original to be compared against.
OURS = ("__init__.py", "accounts.py", "app.py", "copy.py", "greeter.css",
        "protocol.py", "sessions.py")


def test_every_file_is_either_ours_or_checked() -> None:
    """A carried file that nothing compares is a carried file that drifts."""
    allowed = set(VENDORED) | set(OURS) | {"__pycache__"}
    for name in sorted(os.listdir(SHARED)):
        check(name in allowed,
              f"{name} is neither this package's own nor compared against an original")


def test_the_originals_are_where_this_test_expects_them() -> None:
    """Named separately so the reason for a quiet run is in the output.

    Without this, a repository whose installer directory had been moved would
    run this file, compare nothing, and report PASS.
    """
    if HAVE_ORIGINALS:
        return
    print(f"  nothing to compare against: {ORIGIN} is not here")


def test_the_copies_still_work_where_they_landed() -> None:
    """Vendoring must not have broken the relative import inside brand."""
    sys.path.insert(0, PACKAGE)
    try:
        from aurade_greeter import brand, status, tokens
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
    if not HAVE_ORIGINALS:
        print("greeter shared design test: NOTHING TO COMPARE "
              "(the installer tree is not here, so no copy was checked)")
        return 0
    print(f"greeter shared design test: PASS ({len(VENDORED)} copies identical)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
