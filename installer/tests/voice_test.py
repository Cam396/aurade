"""The voice, checked where it can be.

Most of what makes copy good cannot be tested. Three things can, and each is
a rule this product has already drifted away from once.

The first is punctuation. No em dashes, no en dashes, anywhere a user can see
them. A dash is the joint a sentence uses when it has two ideas and has not
decided which one it is about, and a page full of them reads as written by a
machine, because lately it usually was. Every dash here wants to be a full
stop, a comma, or two sentences.

The second is a short list of words that only appear in writing nobody speaks:
the register of a release note. They are not banned because they are wrong.
They are banned because reaching for one is the moment the copy stops sounding
like a person and starts sounding like a department.

The third is the semicolon, which in this codebase was almost never a
semicolon. It was a way to bolt a reassurance onto the back of a diagnosis:
"could not acquire the package set; the target disk was not modified". The
half the reader needs is on the wrong side of it. Every one of these wanted to
be two sentences with the disk first, and a mark that only ever appeared as a
symptom is worth failing the build over.

The strings this reads are the ones the user sees, across every program that
speaks: the two front ends, the shared copy library and question manifest, the
engine, the launcher, the boot menu, and the screens that only appear when
something has gone wrong. Code comments are exempt, and so is anything inside
a path, a URL or a command.
"""

from __future__ import annotations

import os
import re
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                     "..", ".."))

#: Files whose user-facing strings are checked, and how to find them.
SOURCES = [
    # The screens people see when it works.
    ("installer/lib/aurade_gui/flow.py", "python"),
    ("installer/lib/aurade_gui/locales.py", "python"),
    ("installer/lib/aurade_gui/app.py", "python"),
    ("installer/lib/aurade-questions.sh", "shell"),
    ("installer/bin/aurade-installer-tui", "shell"),
    ("installer/bin/aurade-installer-gui-bridge", "shell"),
    # The words every program shares.
    ("installer/lib/aurade-copy.sh", "shell"),
    ("installer/lib/aurade-tips", "tips"),
    # The screens people see when it does not work, which went unchecked for
    # a pass and turned out to be where the worst of it had settled.
    ("installer/bin/aurade-install-failure", "shell"),
    # Every sentence this prints is read by somebody whose install has just
    # gone wrong, which makes it the most user-facing thing in the tree that
    # looks like a diagnostic tool.
    ("installer/bin/aurade-explain", "shell"),
    ("installer/bin/aurade-installer-start", "shell"),
    ("installer/lib/aurade-probe.sh", "shell"),
    # The engine. Its `die` messages become the failure screen's cause code and
    # its `log` lines are what a text install prints while it runs, so it is as
    # user-facing as anything above. It went unread for the whole of the last
    # pass, and that is where five memo headers arrived.
    ("installer/bin/aurade-install", "shell"),
    ("installer/archiso/airootfs/usr/local/sbin/aurade-installer-autostart", "shell"),
    # Every line this prints is read by the graphical bridge and put on the
    # readiness page verbatim, so it is product copy however much it looks
    # like a sysadmin's checklist.
    ("installer/archiso/airootfs/usr/local/sbin/aurade-network-diagnostics", "shell"),
    # The login screen, which was reading zero of its strings through this
    # while fourteen installer files read all of theirs.
    #
    # It is the same product and the same rules, and it is arguably the more
    # exposed half: an installer is read once by somebody who chose to run it,
    # and a login screen is read every morning by somebody who did not. The
    # only reason it was not here is that it arrived later.
    ("aurade-greeter/aurade_greeter/copy.py", "python"),
    # Not only `copy.py`. These three build sentences of their own, and a
    # module that formats a phrase is as user facing as one that stores it.
    ("aurade-greeter/aurade_greeter/weather.py", "python"),
    ("aurade-greeter/aurade_greeter/shade.py", "python"),
    ("aurade-greeter/aurade_greeter/settings.py", "python"),
    # The first words the product says, and the last place anyone reads.
    ("installer/archiso/airootfs/etc/motd", "plain"),
]

#: Every boot entry, found rather than listed. The four were listed by name
#: until a fifth was added second and the other three shifted down a number,
#: at which point this test failed on a missing file rather than on anything
#: anybody had written. A directory that is entirely boot entries is a
#: directory that can be read.
_ENTRIES = os.path.join(ROOT, "installer/archiso/efiboot/loader/entries")
SOURCES += [
    (os.path.join("installer/archiso/efiboot/loader/entries", name), "boot")
    for name in sorted(os.listdir(_ENTRIES)) if name.endswith(".conf")
]

DASHES = {"—": "em dash", "–": "en dash", "―": "horizontal bar"}

#: Read one aloud. If it sounds like a memo, it is on this list.
STUFFY = (
    "utilise", "utilize", "in order to", "prior to", "subsequent to",
    "please note", "kindly", "at this time", "is able to", "has the ability",
    "facilitate", "leverage", "commence", "terminate the",
)

#: Memo headers. A line that has to announce its own severity is a line that
#: did not manage to convey it. Matched at the front only, because that is what
#: a header is: `${APPLY_ERROR:-...}` is a variable with a default, not a memo.
HEADERS = ("warning:", "notice:", "note:", "error:", "attention:", "important:")

#: The semicolon, which was never used here as a semicolon. Allowed inside a
#: command or a code fragment, where it is punctuation for a shell rather than
#: for a reader; the exemptions below carry those.
SEMICOLON = ";"

#: Strings that are quotes from somewhere else, or a name, and are not this
#: product's voice to fix.
EXEMPT = re.compile(r"^(https?://|/|-|\.|[A-Z_]+=)")

#: Fragments that are shell, awk, sed or C rather than English. A semicolon in
#: any of these is a statement separator and nothing to do with the voice.
CODE = re.compile(
    r"(&&|\|\||>&2|<<|=~|\bawk\b|\bsed\b|\bprintf\b|\bgrep\b"
    r"|\bfor \w+ in\b|\bdone\b|\bfi\b|\besac\b|::|;;|\bIFS=|\belse\b"
    r"|\{[^}]*\bprint\b|\w\+?=\s*$"
    # A braced block whose contents are `property: value` pairs. That is CSS,
    # where the semicolon is a statement separator and nothing to do with the
    # voice. Narrow on purpose: it wants both braces and a colon inside them,
    # so a sentence that happens to contain a brace is still checked.
    r"|\{[^}]*[a-z-]+:[^}]*\})"
)


def strings(path: str, kind: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    with open(os.path.join(ROOT, path)) as handle:
        for number, line in enumerate(handle, 1):
            if kind == "plain":
                found.append((number, line.rstrip("\n")))
                continue
            if kind == "tips":
                # lane, tab, text.
                if "\t" in line:
                    found.append((number, line.split("\t", 1)[1].rstrip("\n")))
                continue
            if kind == "boot":
                # Only the title. The rest of a loader entry is kernel
                # arguments and paths, which no one reads as prose.
                if line.startswith("title"):
                    found.append((number, line.split(None, 1)[1].strip()))
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
                # Both quotes. Reading only the single-quoted ones let a
                # semicolon splice sit in a `printf "..."` through three
                # green runs, because interpolation needs double quotes and
                # interpolation is exactly what a message with a value in it
                # has.
                for pattern in (r"'([^'\\]{4,})'", r'"([^"\\]{4,})"'):
                    for match in re.findall(pattern, line):
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
            for header in HEADERS:
                if lowered.startswith(header):
                    problems.append(
                        f"{path}:{number}: {header!r} in {text.strip()!r}")
            if SEMICOLON in text and not CODE.search(text):
                problems.append(
                    f"{path}:{number}: semicolon in {text.strip()!r}")

    # The dash rule again, over the documents, and only the dash rule.
    #
    # The checks above are about how the product sounds and they would be
    # wrong applied to prose: a design document is allowed a semicolon and is
    # allowed to say "note". The dash is different. It is banned everywhere
    # rather than in product copy, it takes no judgement to spot, and the
    # documents are where it comes back, because a paragraph explaining a
    # decision is exactly the kind of writing that reaches for one.
    for name in sorted(os.listdir(os.path.join(ROOT, "installer"))):
        if not name.endswith(".md"):
            continue
        path = os.path.join("installer", name)
        with open(os.path.join(ROOT, path), encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                checked += 1
                for glyph, label in DASHES.items():
                    if glyph in line:
                        problems.append(
                            f"{path}:{number}: {label} in {line.strip()!r}")

    for problem in problems:
        print(f"test-voice: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"installer voice test: PASS ({checked} strings, no dashes, "
          "no semicolons, nothing from the memo)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
