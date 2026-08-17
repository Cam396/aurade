#!/usr/bin/env python3
"""Turn the USFM King James Version into the markdown the installer ships.

The source is eBible.org's `eng-kjv`, which is the 1769 standardised text with
the Apocrypha: eighty books, thirty six thousand eight hundred and twenty two
verses. It is public domain. The zip it comes in is committed beside this
file, because a build that reaches for the network is a build that stops
working the day the network does, and because `--check` can then re-derive the
whole thing and compare rather than merely inspecting it.

Watch out for the near identical `engKJV`, which is a different edition on the
same site and carries the protocanon only. The one with the Apocrypha is the
hyphenated `eng-kjv`. That trap cost an hour once already.

What is dropped, and why:

  Footnotes. Seven thousand translator notes, each an aside about a Hebrew
  idiom or a variant reading. Inline they would break every other sentence in
  half, and this is a thing to read while an operating system installs, not an
  apparatus to study.

  The red letter. USFM marks the words of Jesus and markdown has no colour, so
  the marking is dropped rather than approximated with something louder.

  Word level Strong's numbers. Three hundred thousand of them, wrapped around
  very nearly every word in the book. They are the reason the source is three
  megabytes larger than the text.

What is kept:

  The italics. The KJV has always printed the words its translators supplied
  rather than found, and that distinction is the single most useful piece of
  typography in the book: it is the difference between what the text says and
  what the translation needed to make it read as English. They come out as
  markdown emphasis, which is exactly what emphasis means here.

  The paragraphing, the poetry, and the Psalm superscriptions, because Hebrew
  poetry set as prose is not the same poem.

Run it to regenerate. `installer/tests/test-bible.sh` re-derives and fails on
any difference, so what is in the tree is always what this file makes.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import re
import sys
import zipfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), ".."))
SOURCE_ZIP = os.path.join(ROOT, "bible", "eng-kjv_usfm.zip")
OUT_DIR = os.path.join(ROOT, "bible")
MANIFEST = os.path.join(OUT_DIR, "manifest.tsv")

#: The published checksum of the source, so a swapped zip is loud rather than
#: quiet. A different Bible that parses cleanly is the failure worth catching.
SOURCE_SHA256 = "0079b6db44fff5ffe124015f81fc67a023388d22aba50c012fcf48670e683a25"
SOURCE_URL = "https://ebible.org/Scriptures/eng-kjv_usfm.zip"

#: The three sections, in the order a printed King James with the Apocrypha
#: puts them. Held here rather than derived from the file names because the
#: numbering in those names is a USFM convention with gaps in it, and a gap is
#: not a section boundary.
APOCRYPHA = ("TOB", "JDT", "ESG", "WIS", "SIR", "BAR", "S3Y", "SUS", "BEL",
             "1MA", "2MA", "1ES", "MAN", "2ES")
NEW_TESTAMENT = ("MAT", "MRK", "LUK", "JHN", "ACT", "ROM", "1CO", "2CO", "GAL",
                 "EPH", "PHP", "COL", "1TH", "2TH", "1TI", "2TI", "TIT", "PHM",
                 "HEB", "JAS", "1PE", "2PE", "1JN", "2JN", "3JN", "JUD", "REV")

#: Everything in the zip that is not a book of the Bible.
NOT_A_BOOK = ("FRT", "GLO", "BAK", "OTH", "INT", "CNC", "TDX", "NDX")

# -- inline markup -----------------------------------------------------------

#: `\w word|strong="H0430"\w*` and `\w word\w*`. Three hundred thousand of
#: these, so it is worth one expression rather than a loop.
#:
#: The optional `+` is not decoration. USFM writes a character marker nested
#: inside another one with a leading plus, so a Strong's number inside a name
#: of God is `\+w LORD|strong="H3068"\+w*`. Without the plus here, thirty five
#: thousand of them survived into the text, and neither guard caught it: the
#: converter's own check and the test's both matched `\\[a-z0-9]` , which a
#: backslash followed by a plus does not match. Every expression below takes
#: the plus for that reason, and so does the check.
WORD = re.compile(r"\\\+?w ([^\\|]*?)(?:\|[^\\]*?)?\\\+?w\*")
#: `\f + \fr 1.4 \ft the note \f*`, non greedy so two notes in one verse do
#: not swallow the text between them.
FOOTNOTE = re.compile(r"\\f\s.*?\\f\*")
#: Character styles that survive as emphasis, and those that simply unwrap.
EMPHASIS = re.compile(r"\\\+?(add|tl) (.*?)\\\+?\1\*")
UNWRAP = re.compile(r"\\\+?(nd|wj|qt|bk|pn|sig|sls|no|it|bd) (.*?)\\\+?\1\*")
#: Anything left over. If this ever matches, the converter has met a marker it
#: was not written for, and silently dropping it would put a stray backslash
#: in the middle of somebody's reading.
LEFTOVER = re.compile(r"\\\+?[a-z0-9]+\*?")


def inline(text: str) -> str:
    """One verse's worth of USFM character markup, as markdown."""
    text = FOOTNOTE.sub("", text)
    text = WORD.sub(r"\1", text)
    for _ in range(4):  # nested styles, innermost first
        new = EMPHASIS.sub(r"*\2*", UNWRAP.sub(r"\2", text))
        if new == text:
            break
        text = new
    # Emphasis around nothing, which the source produces where a supplied word
    # sat alone inside a footnote that has just been removed.
    text = text.replace("**", "")
    return re.sub(r"\s+", " ", text).strip()


class Book:
    def __init__(self, code: str) -> None:
        self.code = code
        self.title = ""
        self.short = ""
        self.lines: list[str] = []
        self.chapters = 0
        self.verses = 0


def convert(code: str, usfm: str) -> Book:
    """One USFM book into one markdown document."""
    book = Book(code)
    out: list[str] = []
    pending_break = False
    pending_heading = ""
    verse: list[str] = []

    def flush() -> None:
        nonlocal verse
        if verse:
            out.append("".join(verse).rstrip())
            verse = []

    for raw in usfm.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        marker, _, rest = line.partition(" ")
        marker = marker.lstrip("\\")
        rest = rest.strip()

        if marker in ("id", "ide", "toc2", "toc3", "sts", "rem", "usfm"):
            continue
        if marker == "h":
            book.short = rest
        elif marker == "toc1":
            book.title = book.title or rest
        elif marker in ("mt1", "mt2", "ms1"):
            book.title = rest if marker == "mt1" else book.title
        elif marker == "c":
            flush()
            book.chapters += 1
            out.append("")
            out.append(f"## Chapter {rest}")
            out.append("")
            pending_break = False
        elif marker == "s1":
            flush()
            pending_heading = inline(rest)
        elif marker == "d":
            flush()
            out.append("")
            out.append(f"*{inline(rest)}*")
            out.append("")
        elif marker in ("p", "m", "pi1", "pi2", "nb", "b"):
            flush()
            pending_break = True
        elif marker in ("q1", "q2", "qc", "qr"):
            # A poetry line. It carries no text of its own here; the verse that
            # follows is what breaks. Recorded so the verse knows to start on
            # its own line even mid sentence.
            flush()
            if rest:
                out.append(inline(rest))
        elif marker == "v":
            number, _, text = rest.partition(" ")
            flush()
            if pending_heading:
                out.append("")
                out.append(f"### {pending_heading}")
                out.append("")
                pending_heading = ""
                pending_break = False
            if pending_break:
                out.append("")
                pending_break = False
            book.verses += 1
            verse.append(f"{number} {inline(text)}")
        elif marker in ("imt1", "ip", "is1", "iot", "io1", "ili1"):
            continue
        else:
            flush()
            body = inline(rest)
            if body:
                out.append(body)
    flush()

    title = book.title or book.short or code
    document = [f"# {title}", ""]
    for line in out:
        if line == "" and document and document[-1] == "":
            continue
        document.append(line)
    book.lines = document
    book.title = title
    return book


def render(book: Book) -> str:
    text = "\n".join(book.lines).rstrip() + "\n"
    leftover = LEFTOVER.search(text)
    if leftover:
        raise SystemExit(
            f"make-bible: {book.code} still carries the USFM marker "
            f"{leftover.group(0)!r}, so a reader would see a backslash")
    return text


def build() -> tuple[dict[str, str], list[Book]]:
    with open(SOURCE_ZIP, "rb") as handle:
        blob = handle.read()
    digest = hashlib.sha256(blob).hexdigest()
    if digest != SOURCE_SHA256:
        raise SystemExit(
            f"make-bible: the source zip is {digest[:16]} and this expects "
            f"{SOURCE_SHA256[:16]}. That is a different Bible.")

    files: dict[str, str] = {}
    books: list[Book] = []
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        names = sorted(n for n in archive.namelist() if n.endswith(".usfm"))
        for name in names:
            code = os.path.basename(name)[3:6]
            if code in NOT_A_BOOK:
                continue
            book = convert(code, archive.read(name).decode("utf-8"))
            books.append(book)
            files[f"{book.code}.md"] = render(book)

    rows = ["# code\tsection\tshort\tname\tchapters\tverses\tfile"]
    for order, book in enumerate(books, 1):
        section = ("apocrypha" if book.code in APOCRYPHA else
                   "new" if book.code in NEW_TESTAMENT else "old")
        # The short name as well as the title. A picker listing "The
        # First Book of Moses, called Genesis" is a picker nobody can
        # scan; the title still belongs at the head of the book.
        rows.append(f"{book.code}\t{section}\t{book.short or book.title}\t"
                    f"{book.title}\t{book.chapters}\t{book.verses}\t{book.code}.md")
    files["manifest.tsv"] = "\n".join(rows) + "\n"
    return files, books


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="compare with the committed text instead of writing it")
    args = parser.parse_args()

    files, books = build()
    verses = sum(b.verses for b in books)
    if len(books) != 80:
        raise SystemExit(f"make-bible: {len(books)} books, and this is the "
                         "edition with the Apocrypha, which has eighty")
    if verses != 36822:
        raise SystemExit(f"make-bible: {verses} verses, expected 36822")

    if args.check:
        problems = []
        for name, body in sorted(files.items()):
            path = os.path.join(OUT_DIR, name)
            if not os.path.exists(path):
                problems.append(f"{name} is missing")
                continue
            with open(path, encoding="utf-8") as handle:
                if handle.read() != body:
                    problems.append(f"{name} is not what this produces")
        extra = set(os.listdir(OUT_DIR)) - set(files) - {
            os.path.basename(SOURCE_ZIP), "README.md"}
        for name in sorted(extra):
            problems.append(f"{name} is in the directory and nothing made it")
        for problem in problems:
            print(f"make-bible: {problem}", file=sys.stderr)
        return 1 if problems else 0

    os.makedirs(OUT_DIR, exist_ok=True)
    for name, body in sorted(files.items()):
        with open(os.path.join(OUT_DIR, name), "w", encoding="utf-8") as handle:
            handle.write(body)
    size = sum(len(b.encode("utf-8")) for b in files.values())
    print(f"make-bible: wrote {len(files)} files, {len(books)} books, "
          f"{verses} verses, {size / 1024 / 1024:.1f}MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
