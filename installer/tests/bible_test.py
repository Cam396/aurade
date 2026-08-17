"""The Bible in the tree, against the archive it was made from.

Two kinds of check, and both matter for different reasons.

The re-derivation is the strong one: `make-bible.py --check` rebuilds all
eighty books from the committed archive and fails on any difference, so a
hand edit to a verse cannot survive, and neither can a change to the converter
that nobody regenerated after.

The structural checks are the ones that would catch a converter that is
confidently wrong. Re-derivation only proves the tree matches the tool; if the
tool started dropping every other verse, the tree would match a broken tool
perfectly. So the counts are pinned against the edition's published figures,
and the shape of every file is checked against what the front ends walk.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

TESTS = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.normpath(os.path.join(TESTS, "..", ".."))
BIBLE = os.path.join(ROOT, "installer", "bible")

#: The edition's own figures. Eighty books rather than sixty six is the whole
#: point of this source: three of the four candidates checked first carried
#: the protocanon only, and a sixty six book Bible would satisfy every other
#: assertion in this file.
BOOKS = 80
CHAPTERS = 1362
VERSES = 36822
SECTIONS = {"old": 39, "apocrypha": 14, "new": 27}

#: A few of the fourteen, named rather than counted. A count can be reached by
#: any fourteen files; these are the ones a reader would look for.
APOCRYPHA_MUST_HAVE = ("TOB", "JDT", "WIS", "SIR", "BAR", "1MA", "2MA", "1ES")

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def equal(got: object, want: object, message: str) -> None:
    if got != want:
        FAILURES.append(f"{message}: expected {want!r}, got {got!r}")


def main() -> int:
    # -- the tree is what the converter produces -----------------------------
    made = subprocess.run(
        [sys.executable, os.path.join(ROOT, "installer", "tools", "make-bible.py"),
         "--check"],
        capture_output=True, text=True,
    )
    check(made.returncode == 0,
          "the committed Bible is not what the converter produces from the "
          f"committed archive; run installer/tools/make-bible.py ({made.stderr.strip()})")

    manifest = os.path.join(BIBLE, "manifest.tsv")
    if not os.path.exists(manifest):
        print("test-bible: there is no manifest, so nothing can find the books",
              file=sys.stderr)
        return 1

    rows = [line.split("\t") for line in
            open(manifest, encoding="utf-8").read().splitlines()
            if line and not line.startswith("#")]

    # -- the canon -----------------------------------------------------------
    equal(len(rows), BOOKS, "the number of books")
    counted = {"old": 0, "apocrypha": 0, "new": 0}
    for row in rows:
        if len(row) != 7:
            FAILURES.append(f"a manifest row has {len(row)} fields, not 7: {row!r}")
            continue
        counted[row[1]] = counted.get(row[1], 0) + 1
    for section, wanted in SECTIONS.items():
        equal(counted.get(section), wanted, f"books in the {section} testament")

    codes = {row[0] for row in rows if len(row) == 7}
    for code in APOCRYPHA_MUST_HAVE:
        check(code in codes,
              f"{code} is missing, so this is not the edition with the Apocrypha")

    # -- every book is there, and is shaped the way the readers walk it ------
    total_chapters = total_verses = 0
    for row in rows:
        if len(row) != 7:
            continue
        code, _section, short, name, chapters, verses, filename = row
        path = os.path.join(BIBLE, filename)
        if not os.path.exists(path):
            FAILURES.append(f"{filename} is indexed and not in the directory")
            continue
        text = open(path, encoding="utf-8").read()
        lines = text.splitlines()

        check(bool(name.strip()), f"{code} has no name in the manifest")
        check(bool(short.strip()), f"{code} has no short name, so a picker cannot list it")
        check(len(short) <= len(name),
              f"{code} short name {short!r} is longer than its title {name!r}")
        check(lines and lines[0].startswith("# "),
              f"{filename} does not open with its title")

        # The two things a front end counts on. Chapter headings it can jump
        # to, and verse lines it can number. A file whose verses do not start
        # with their number renders as unbroken prose in the terminal.
        heads = sum(1 for line in lines if line.startswith("## Chapter "))
        numbered = sum(1 for line in lines if re.match(r"^\d+ ", line))
        equal(heads, int(chapters), f"{filename} chapter headings")
        equal(numbered, int(verses), f"{filename} verse lines")
        total_chapters += int(chapters)
        total_verses += int(verses)

        # No USFM survived. A stray backslash marker is not a crash and not a
        # blank page; it is one wrong-looking word in the middle of a verse,
        # which is exactly the kind of thing nobody reports.
        #
        # The `\+?` matters and is why this once passed over thirty five
        # thousand of them. USFM nests a character marker inside another one
        # by prefixing it with a plus, and `\\[a-z0-9]` does not match a
        # backslash followed by a plus. The converter's own guard had the
        # identical blind spot, so the two agreed with each other and both
        # were wrong. It was found by rendering a psalm and looking at it.
        stray = re.search(r"\\\+?[a-z0-9]+\*?", text)
        check(stray is None,
              f"{filename} still carries USFM markup: "
              f"{stray.group(0) if stray else ''!r}")

    equal(total_chapters, CHAPTERS, "chapters in the whole Bible")
    equal(total_verses, VERSES, "verses in the whole Bible")

    # -- the archive it all comes from ---------------------------------------
    check(os.path.exists(os.path.join(BIBLE, "eng-kjv_usfm.zip")),
          "the source archive is not committed, so nothing here can be "
          "re-derived and the check above proves only that the files exist")

    for problem in FAILURES:
        print(f"test-bible: {problem}", file=sys.stderr)
    if FAILURES:
        return 1
    print(f"installer Bible test: PASS ({len(rows)} books, {total_chapters} "
          f"chapters, {total_verses} verses, Apocrypha present)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
