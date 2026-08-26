#!/usr/bin/env python3
"""The accessibility choices, carried from the installer to the login screen.

Somebody who turns on high contrast and larger text to get through an
installation and then meets a login screen with neither has not been helped,
they have been moved one wall further along. And it is the worst wall: the
settings that would let them read the screen are behind the screen they cannot
read.

So the record the installer writes is read here, and every one of these checks
is about a person who needs something and either gets it or does not. A
machine with no record at all, which is every machine installed before this
existed, has to look exactly as it did.
"""

from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), ".."))
sys.path.insert(0, ROOT)

from aurade_greeter import preferences as P  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


class Record:
    """One installer's answers, on disk, for the length of one test."""

    def __init__(self, text: str | None) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "accessibility")
        if text is not None:
            with open(self.path, "w", encoding="utf-8") as handle:
                handle.write(text)
        self.saved = os.environ.get("AURADE_GREETER_ACCESSIBILITY")
        os.environ["AURADE_GREETER_ACCESSIBILITY"] = self.path

    def close(self) -> None:
        if self.saved is None:
            os.environ.pop("AURADE_GREETER_ACCESSIBILITY", None)
        else:
            os.environ["AURADE_GREETER_ACCESSIBILITY"] = self.saved
        self.dir.cleanup()


FULL = """screen_reader=yes
braille=no
contrast=high
text_scale=200
spacing=wide
typeface=atkinson
reduce_motion=yes
cursor_size=48
"""


def test_a_machine_with_no_record_looks_as_it_always_did() -> None:
    """Every machine installed before this existed has no record."""
    record = Record(None)
    try:
        found = P.read()
        check(found == P.DEFAULTS,
              f"a missing record changed the appearance: {found}")
        check(not P.wants_contrast(found), "a missing record turned on high contrast")
        check(not P.wants_stillness(found), "a missing record stopped the animation")
        check(P.text_scale(found) == 100, "a missing record resized the text")
        check(P.font_name(found) == "", "a missing record changed the typeface")
    finally:
        record.close()


def test_what_somebody_asked_for_reaches_the_login_screen() -> None:
    record = Record(FULL)
    try:
        found = P.read()
        check(P.wants_contrast(found),
              "somebody who asked for high contrast did not get it at the greeter")
        check(P.wants_stillness(found),
              "somebody who asked for less movement still gets a moving background")
        check(P.text_scale(found) == 200,
              f"the text scale did not carry: {P.text_scale(found)}")
        check(P.cursor_size(found) == 48,
              f"the pointer size did not carry: {P.cursor_size(found)}")
        check(P.font_name(found) == "Atkinson Hyperlegible 11",
              f"the typeface did not carry: {P.font_name(found)!r}")
        check(P.theme_for(found, dark=True) == "dark-hc",
              "a high contrast answer did not choose the high contrast stylesheet")
        check(P.theme_for(found, dark=False) == "light-hc",
              "a high contrast answer in light did not choose the high contrast stylesheet")
    finally:
        record.close()


def test_the_ordinary_answers_change_nothing() -> None:
    record = Record("contrast=normal\ntext_scale=100\nreduce_motion=no\n"
                    "typeface=system\ncursor_size=24\n")
    try:
        found = P.read()
        check(P.theme_for(found, dark=True) == "dark",
              "an ordinary answer chose the high contrast stylesheet")
        check(P.text_scale(found) == 100, "an ordinary answer resized the text")
        check(P.font_name(found) == "", "an ordinary answer changed the typeface")
    finally:
        record.close()


def test_a_record_that_has_been_edited_by_hand_cannot_break_the_screen() -> None:
    """Numbers outside what can be drawn, and lines that are not settings."""
    record = Record("text_scale=99999\ncursor_size=0\ncontrast=HIGH\n"
                    "reduce_motion=TRUE\ntypeface=comic\n"
                    "this line has no equals sign\n"
                    "rm -rf /\n= \nscreen_reader=\n")
    try:
        found = P.read()
        check(P.text_scale(found) <= P.MAX_SCALE,
              f"a text scale of {P.text_scale(found)} would not fit on a screen")
        check(P.cursor_size(found) >= 16,
              "a pointer size of zero would leave nothing to point with")
        check(P.wants_contrast(found), "HIGH in capitals was not read as high")
        check(P.wants_stillness(found), "TRUE in capitals was not read as yes")
        check(P.font_name(found) == "",
              "a typeface nobody ships was asked for anyway")
        # And nothing the greeter does not understand comes back out of it.
        # This file is written by one program and read by another that stands
        # in front of the login prompt, so it carries exactly the settings
        # this greeter knows how to honour and no others.
        check(set(found) == set(P.DEFAULTS),
              f"the record smuggled keys through: {sorted(set(found) - set(P.DEFAULTS))}")
    finally:
        record.close()


def test_a_key_this_greeter_does_not_know_is_left_where_it_was() -> None:
    record = Record("contrast=high\nmagnifier=yes\nsomething_new=42\n")
    try:
        found = P.read()
        check(set(found) == set(P.DEFAULTS),
              f"an unknown setting was taken from the record: "
              f"{sorted(set(found) - set(P.DEFAULTS))}")
        check(P.wants_contrast(found),
              "an unknown setting alongside a known one lost the known one")
    finally:
        record.close()


def test_a_record_that_is_not_readable_falls_back_rather_than_failing() -> None:
    record = Record(None)
    try:
        os.environ["AURADE_GREETER_ACCESSIBILITY"] = "/proc/aurade/nothing"
        found = P.read()
        check(found == P.DEFAULTS,
              "an unreadable record did not fall back to the ordinary appearance")
    finally:
        record.close()


def test_text_that_is_not_a_number_does_not_shrink_the_screen() -> None:
    record = Record("text_scale=large\ncursor_size=huge\n")
    try:
        found = P.read()
        check(P.text_scale(found) == 100,
              "a text scale that is not a number was not treated as ordinary")
        check(P.cursor_size(found) == 24,
              "a pointer size that is not a number was not treated as ordinary")
    finally:
        record.close()


def test_the_oled_sheet_wins_because_it_is_asked_for_deliberately() -> None:
    record = Record(FULL)
    try:
        found = P.read()
        check(P.theme_for(found, dark=True, oled=True) == "oled",
              "an explicit OLED request was overridden by the record")
    finally:
        record.close()


def main() -> int:
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            function()
    if FAILURES:
        print("greeter preferences test: FAIL")
        for failure in FAILURES:
            print(f"  {failure}")
        return 1
    print("greeter preferences test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
