"""The voice, checked where it can be.

Most of what makes copy good cannot be tested. Two things can, and both are
rules this product has already drifted away from once.

The first is punctuation. No em dashes, no en dashes, anywhere a user can see
them. A dash is the joint a sentence uses when it has two ideas and has not
decided which one it is about, and a page full of them reads as written by a
machine, because lately it usually was. Every dash here wants to be a full
stop, a comma, or two sentences.

The second is a short list of words that only appear in writing nobody speaks:
the register of a release note. They are not banned because they are wrong.
They are banned because reaching for one is the moment the copy stops sounding
like a person and starts sounding like a department.

The strings this reads are the ones the user sees: the page and state copy, the
shared question manifest, the stage vocabulary and the readiness findings. Code
comments are exempt, and so is anything inside a path, a URL or a command.
"""

from __future__ import annotations

import os
import re
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                     "..", ".."))

#: Files whose user-facing strings are checked, and how to find them.
SOURCES = [
    ("installer/lib/aurade_gui/flow.py", "python"),
    ("installer/lib/aurade_gui/locales.py", "python"),
    ("installer/lib/aurade_gui/app.py", "python"),
    ("installer/lib/aurade-questions.sh", "shell"),
    ("installer/bin/aurade-installer-tui", "shell"),
    ("installer/bin/aurade-installer-gui-bridge", "shell"),
    ("installer/archiso/airootfs/etc/motd", "plain"),
]

DASHES = {"—": "em dash", "–": "en dash", "―": "horizontal bar"}

#: Read one aloud. If it sounds like a memo, it is on this list.
STUFFY = (
    "utilise", "utilize", "in order to", "prior to", "subsequent to",
    "please note", "kindly", "at this time", "is able to", "has the ability",
    "facilitate", "leverage", "commence", "terminate the",
)

#: Strings that are quotes from somewhere else, or a name, and are not this
#: product's voice to fix.
EXEMPT = re.compile(r"^(https?://|/|-|\.|[A-Z_]+=)")


def strings(path: str, kind: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    with open(os.path.join(ROOT, path)) as handle:
        for number, line in enumerate(handle, 1):
            if kind == "plain":
                found.append((number, line.rstrip("\n")))
                continue
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if kind == "python":
                # Docstrings are comments with quotes around them.
                if stripped.startswith(('"""', "'''")):
                    continue
                for match in re.findall(r'"([^"\\]{4,})"', line):
                    found.append((number, match))
            else:
                for match in re.findall(r"'([^'\\]{4,})'", line):
                    found.append((number, match))
    return [(number, text) for number, text in found if not EXEMPT.match(text)]


def main() -> int:
    problems: list[str] = []
    checked = 0
    for path, kind in SOURCES:
        for number, text in strings(path, kind):
            checked += 1
            for glyph, name in DASHES.items():
                if glyph in text:
                    problems.append(
                        f"{path}:{number}: {name} in {text.strip()!r}")
            lowered = text.lower()
            for word in STUFFY:
                if word in lowered:
                    problems.append(
                        f"{path}:{number}: {word!r} in {text.strip()!r}")

    for problem in problems:
        print(f"test-voice: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"installer voice test: PASS ({checked} strings, no dashes, "
          "nothing from the memo)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
