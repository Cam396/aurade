#!/usr/bin/env bash
# The King James Version that ships on the image, against the archive it was
# made from.
#
# The interesting failure is not a missing file. It is a Bible that is sixty
# six books long, because three of the four sources checked when this was
# chosen were exactly that, and a sixty six book Bible passes every check
# about file shape, verse numbering and markup. So the canon is pinned by
# name and by count, and the source archive is committed so the whole thing
# can be re-derived rather than merely inspected.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)

command -v python3 >/dev/null 2>&1 || {
  echo 'installer Bible test: SKIP (python3 not available)'
  exit 0
}

python3 "$ROOT/installer/tests/bible_test.py"

# --- and the two screens the text installer draws it on ----------------------
#
# The file level checks above are about the text. These are about what a
# person actually sees, and they exist because the file checks passed for a
# corpus that had thirty five thousand pieces of markup left in it. Rendering
# a psalm and looking at it is what found that, so rendering a psalm and
# looking at it is now something that happens every run.
TUI=$ROOT/installer/bin/aurade-installer-tui

books=$(env AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii AURADE_TUI_HEIGHT=24 \
  AURADE_RENDER_BIBLE_BOOK=40 "$TUI" --render books 2>/dev/null)
[[ $books == *Apocrypha* ]] ||
  { echo 'test-bible: the book list does not say where the Apocrypha starts' >&2; exit 1; }
[[ $books == *Tobit* ]] ||
  { echo 'test-bible: the book list does not offer Tobit, so it is a sixty six book Bible' >&2; exit 1; }

# Psalm 117, which is two verses, so the whole chapter fits on one screen and
# what is asserted is the whole of what was drawn rather than the top of it.
page=$(env AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii AURADE_TUI_HEIGHT=24 \
  AURADE_RENDER_BIBLE_BOOK=18 AURADE_RENDER_BIBLE_CHAPTER=117 \
  "$TUI" --render bible 2>/dev/null)
[[ $page == *Psalms* ]] ||
  { echo 'test-bible: the reading screen does not name its book' >&2; exit 1; }
[[ $page == *'Chapter 117'* ]] ||
  { echo 'test-bible: the reading screen does not name its chapter' >&2; exit 1; }
# Both verse numbers, so a chapter that drew its first line and stopped fails.
# Verse numbers start at column one on the reading page, so assert the line
# boundary rather than requiring a space before the number.
[[ $page == *$'\n1 '* && $page == *$'\n2 '* ]] ||
  { echo 'test-bible: the reading screen did not draw both verses' >&2; exit 1; }
# And nothing that came out of a markup language. A backslash on this screen
# is a converter that missed something, which is exactly what happened once.
if [[ $page == *'\\'* ]]; then
  echo 'test-bible: the reading screen shows markup, so the conversion missed something' >&2
  exit 1
fi
# The asterisks come off in the terminal. They are the King James italics and
# the graphical front end draws them as italics; here they would be noise, and
# on a braille display they would be worse than noise.
if [[ $page == *'*'* ]]; then
  echo 'test-bible: the reading screen shows asterisks rather than plain text' >&2
  exit 1
fi

echo 'installer Bible screens: PASS (book list sectioned, chapter drawn, no markup)'
