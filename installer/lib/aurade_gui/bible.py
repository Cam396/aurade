"""Finding and reading the King James Version that ships on the image.

No toolkit in here on purpose. Both front ends need the same three answers -
which books are there, what is a book called, and what does one chapter say -
and the graphical one is the only one that can import GTK. Keeping this a
plain reader over plain files means the text installer can use it too, and
means it can be tested without a compositor.

The files are one book per markdown document, one verse per line prefixed
with its number, `## Chapter N` between chapters. `installer/bible/README.md`
says why that shape and not another.
"""

from __future__ import annotations

import os

#: Where to look, in order. The environment first so a test can point at a
#: fixture, the image's own path second, and the source tree last so the front
#: end runs from a checkout without anything being installed.
BIBLE_DIRS = [
    os.environ.get("AURADE_BIBLE_DIR", ""),
    "/usr/local/share/aurade/bible",
    os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "bible"),
]
MANIFEST = "manifest.tsv"

#: The three sections, in the order a printed King James puts them, with the
#: names this product uses for them. "Apocrypha" rather than "Deuterocanon"
#: because that is the word on the title page of the edition being shipped.
SECTIONS = (("old", "Old Testament"),
            ("apocrypha", "Apocrypha"),
            ("new", "New Testament"))

_books: list[dict[str, str]] | None = None
_loaded: dict[str, object] = {"code": None, "chapters": None}


def bible_dir() -> str:
    """The first directory that has a manifest in it, or an empty string."""
    for candidate in BIBLE_DIRS:
        if not candidate:
            continue
        path = os.path.normpath(candidate)
        if os.path.isfile(os.path.join(path, MANIFEST)):
            return path
    return ""


def books() -> list[dict[str, str]]:
    """Every book the manifest names and whose file is actually there.

    A row whose file is missing is dropped rather than offered, because a
    reader that lists a book and then cannot open it is worse than one that
    never mentions it.
    """
    global _books
    if _books is not None:
        return _books
    _books = []
    directory = bible_dir()
    if not directory:
        return _books
    try:
        with open(os.path.join(directory, MANIFEST), encoding="utf-8") as handle:
            rows = handle.read().splitlines()
    except OSError:
        return _books
    for line in rows:
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 7:
            continue
        code, section, short, name, chapters, verses, filename = fields
        if not os.path.isfile(os.path.join(directory, filename)):
            continue
        _books.append({
            "code": code, "section": section, "short": short, "name": name,
            "chapters": chapters, "verses": verses, "file": filename,
        })
    return _books


def available() -> bool:
    """Is there a Bible to offer at all."""
    return bool(books())


def find(code: str) -> dict[str, str] | None:
    for book in books():
        if book["code"] == code:
            return book
    return None


def chapters(code: str) -> list[list[str]]:
    """One book, split into chapters, each a list of lines to draw.

    The last book read is kept, because a reader moves between chapters of one
    book far more often than between books, and re-reading Psalms from disk to
    turn one page is work nobody asked for.
    """
    if _loaded["code"] == code and _loaded["chapters"] is not None:
        return _loaded["chapters"]  # type: ignore[return-value]
    book = find(code)
    directory = bible_dir()
    if book is None or not directory:
        return []
    try:
        with open(os.path.join(directory, book["file"]), encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return []

    out: list[list[str]] = []
    current: list[str] | None = None
    for line in lines:
        if line.startswith("## Chapter "):
            current = []
            out.append(current)
            continue
        if line.startswith("# "):
            # The book's own title. The reader already shows it above the
            # text, so repeating it at the top of chapter one reads as a
            # mistake rather than as a heading.
            continue
        if current is not None:
            current.append(line)
    for chapter in out:
        while chapter and not chapter[-1]:
            chapter.pop()
    _loaded["code"], _loaded["chapters"] = code, out
    return out


def chapter(code: str, number: int) -> list[str]:
    """One chapter, counting from one. Out of range gives nothing."""
    found = chapters(code)
    if number < 1 or number > len(found):
        return []
    return found[number - 1]


def reset() -> None:
    """Forget what was read. For tests that move the directory underneath."""
    global _books
    _books = None
    _loaded["code"], _loaded["chapters"] = None, None
