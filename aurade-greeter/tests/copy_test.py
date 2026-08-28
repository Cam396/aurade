#!/usr/bin/env python3
"""Every word this screen says, and whether anybody could translate it.

Three rules, and the third is the one that found a real bug.

The first is that a string added to `copy.py` without a translation call
around it is invisible to every translator, and nothing else in the tree would
notice. The extractor reports those, so adding one fails here.

The second is that the committed catalogue template matches the strings. A
template that drifts is a translator working from words the product stopped
saying.

The third is that a catalogue, once installed, actually reaches the screen and
does not break it. That sounds like testing the standard library, and it is
not: `gettext.translation` does `import copy` on the path where it finds a
catalogue, and this package contains a module named `copy.py`. So the obvious
implementation works with nothing installed and fails to import the first time
somebody installs a translation, on a login screen, with a black screen as the
symptom. This builds a two line catalogue and proves a word comes back
changed.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
PACKAGE = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, PACKAGE)

FAILURES: list[str] = []
CHECKS = 0


def check(condition: bool, message: str) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(message)


def _tool(*arguments: str):
    return subprocess.run(
        [sys.executable, os.path.join(PACKAGE, "tools", "extract-copy.py"),
         *arguments], capture_output=True, text=True)


def test_every_string_can_be_translated() -> None:
    """A bare literal in `copy.py` is a string no translator will ever see."""
    answer = _tool("--check")
    check(answer.returncode == 0,
          f"the extractor is unhappy: "
          f"{(answer.stderr or answer.stdout).strip()[:200]}")


def test_the_committed_template_is_current() -> None:
    """Committed on purpose, so a translator needs no build step to start."""
    pot = os.path.join(PACKAGE, "po", "aurade-greeter.pot")
    check(os.path.isfile(pot), "the catalogue template is not committed")
    if os.path.isfile(pot):
        with open(pot, encoding="utf-8") as handle:
            body = handle.read()
        check(body.count("msgid ") > 50,
              f"the template has almost nothing in it: {body.count('msgid ')}")
        check('msgid "Password"' in body,
              "a string known to be in the copy is missing from the template")


def test_a_catalogue_reaches_the_screen() -> None:
    """Install one, and see a word come back in another language.

    Run in a subprocess because the strings are module level constants read
    once at import, which is the whole reason the locale has to be set before
    the greeter starts.
    """
    with tempfile.TemporaryDirectory(prefix="aurade-locale-") as where:
        messages = os.path.join(where, "xx", "LC_MESSAGES")
        os.makedirs(messages)
        source = os.path.join(where, "xx.po")
        with open(source, "w", encoding="utf-8") as handle:
            handle.write('msgid ""\n'
                         'msgstr "Content-Type: text/plain; charset=UTF-8\\n"\n'
                         '\n'
                         'msgid "Password"\n'
                         'msgstr "TRANSLATED"\n')
        built = subprocess.run(
            ["msgfmt", source, "-o",
             os.path.join(messages, "aurade-greeter.mo")],
            capture_output=True, text=True)
        if built.returncode != 0:
            check(False, f"msgfmt is unavailable, so this proved nothing: "
                         f"{built.stderr.strip()[:120]}")
            return

        environment = dict(os.environ)
        environment["AURADE_GREETER_LOCALEDIR"] = where
        environment["LANGUAGE"] = "xx"
        environment["LC_ALL"] = "C"
        answer = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, sys.argv[1]);"
             "from aurade_greeter import copy as C;"
             "print(C.PASSWORD); print(C.WRONG)", PACKAGE],
            capture_output=True, text=True, env=environment)
        check(answer.returncode == 0,
              f"importing the copy with a catalogue installed failed: "
              f"{answer.stderr.strip()[-300:]}")
        lines = answer.stdout.splitlines()
        check(lines and lines[0] == "TRANSLATED",
              f"the catalogue did not reach the string: {lines[:1]}")
        check(len(lines) > 1 and lines[1].startswith("That password"),
              f"a string with no translation did not fall back to English: "
              f"{lines[1:2]}")


def test_english_survives_a_broken_catalogue() -> None:
    """A truncated file must give a login screen, not a traceback."""
    with tempfile.TemporaryDirectory(prefix="aurade-broken-") as where:
        messages = os.path.join(where, "xx", "LC_MESSAGES")
        os.makedirs(messages)
        with open(os.path.join(messages, "aurade-greeter.mo"), "wb") as handle:
            handle.write(b"not a catalogue at all")
        environment = dict(os.environ)
        environment["AURADE_GREETER_LOCALEDIR"] = where
        environment["LANGUAGE"] = "xx"
        environment["LC_ALL"] = "C"
        answer = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, sys.argv[1]);"
             "from aurade_greeter import copy as C; print(C.PASSWORD)",
             PACKAGE],
            capture_output=True, text=True, env=environment)
        check(answer.returncode == 0,
              f"a broken catalogue stopped the greeter importing: "
              f"{answer.stderr.strip()[-300:]}")
        check(answer.stdout.strip() == "Password",
              f"a broken catalogue did not fall back to English: "
              f"{answer.stdout.strip()!r}")


def main() -> int:
    tests = sorted(name for name in globals() if name.startswith("test_"))
    for name in tests:
        globals()[name]()
    ran = sorted(name for name in globals() if name.startswith("test_"))
    if ran != tests:
        print(f"greeter-copy: {len(tests)} tests found and {len(ran)} ran",
              file=sys.stderr)
        return 1
    if FAILURES:
        for failure in FAILURES:
            print(f"greeter-copy: {failure}", file=sys.stderr)
        return 1
    print(f"greeter copy test: PASS ({CHECKS} checks, {len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
