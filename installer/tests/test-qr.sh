#!/usr/bin/env bash
# The square on the help screen has to be a QR code, not a picture of one.
#
# This is the one drawn thing in the product where looking right and being
# right are completely unrelated. A matrix with the placement order wrong, or
# the wrong mask applied, or a quiet zone made of dark modules, renders as a
# tidy square with finder patterns in the corners that no phone will ever
# read. Nobody reviewing a screenshot would catch it, and the person who finds
# out is somebody whose install just failed.
#
# So the check is not "is there a square". The generator decodes its own
# output, and this runs that decode against the matrix that is actually
# committed, which is what would rot if somebody edited it by hand or
# regenerated it with a different URL.
set -Eeuo pipefail
trap 'case $- in *e*) printf "%s: line %s gave up: %s\n" "${0##*/}" "$LINENO" "$BASH_COMMAND" >&2 ;; esac' ERR

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TUI=$ROOT/installer/bin/aurade-installer-tui
MATRIX=$ROOT/installer/lib/aurade-qr-help
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
failures=0
fail() { printf 'test-qr: %s\n' "$*" >&2; failures=$(( failures + 1 )); }

export AURADE_TUI_COLUMNS=68 AURADE_TUI_COLOR=none

command -v python3 >/dev/null 2>&1 || {
  echo 'installer QR test: SKIP (python3 not available)'
  exit 0
}

[[ -r $MATRIX ]] || { fail 'the QR matrix is missing from the tree'; exit 1; }

# --- the committed matrix decodes back to the committed URL -----------------
#
# The generator's own verifier, pointed at the file in the tree rather than at
# something it just built in memory.
url=$(sed -n '2s/^# //p' "$MATRIX")
[[ -n $url ]] || fail 'the matrix does not record which URL it encodes'

python3 - "$ROOT" "$MATRIX" "$url" <<'PY' || fail 'the committed matrix does not decode to its own URL'
import sys, importlib.util

root, path, url = sys.argv[1], sys.argv[2], sys.argv[3]
spec = importlib.util.spec_from_file_location(
    "makeqr", f"{root}/installer/tools/make-qr.py")
qr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qr)

rows = [line.strip() for line in open(path)
        if line.strip() and not line.startswith('#')]
matrix = [[int(c) for c in row] for row in rows]

# Rebuild from the same URL and compare, which checks the file against the
# generator, and then decode the file itself, which checks the generator
# against the specification.
built, mask, version, reserved, codewords = qr.encode(url)
if built != matrix:
    print("the committed matrix is not what the generator produces", file=sys.stderr)
    sys.exit(1)
qr.verify(matrix, mask, version, reserved, codewords, url, "L")

n = len(matrix)
if n != len(matrix[0]):
    print("the matrix is not square", file=sys.stderr)
    sys.exit(1)
# The three finder patterns, which are what a reader looks for first.
for top, left in ((0, 0), (0, n - 7), (n - 7, 0)):
    for dy in range(7):
        for dx in range(7):
            edge = max(abs(dy - 3), abs(dx - 3))
            want = 1 if edge in (0, 1, 3) else 0
            if matrix[top + dy][left + dx] != want:
                print(f"the finder pattern at {top},{left} is wrong",
                      file=sys.stderr)
                sys.exit(1)
PY

# --- the URL it encodes is the one the screen shows -------------------------
#
# Two places name the project and they must not drift, because the code is the
# half nobody can proofread.
screen=$(env AURADE_TUI_FRAME=unicode AURADE_TUI_HEIGHT=36 \
  "$TUI" --render help 2>/dev/null)
grep -Fq "$url" <<<"$screen" ||
  fail "the help screen does not show $url, which is what the code carries"
grep -Fq 'discord.gg' <<<"$screen" ||
  fail 'the help screen does not offer anywhere to talk to a person'

# --- the quiet zone is light, and it is there -------------------------------
#
# A code with no margin is a code a reader will not look at, and the mistake
# is invisible: the matrix is correct, the border is simply painted in the
# wrong one of two characters. The first and last drawn rows are solid.
solid=$(grep -c '████████████' <<<"$screen" || true)
(( solid >= 2 )) || fail "the code has $solid solid rows, so its quiet zone is dark"

# --- and it is only drawn where those characters are safe -------------------
#
# Half blocks are ambiguous width, unlike the braille the progress bar uses,
# so a terminal in a CJK locale can draw them double and tear the frame. The
# addresses say the same thing without them.
ascii_screen=$(env AURADE_TUI_FRAME=ascii AURADE_TUI_HEIGHT=36 \
  "$TUI" --render help 2>/dev/null)
! grep -q '█' <<<"$ascii_screen" ||
  fail 'the ascii tier drew half blocks'
grep -Fq "$url" <<<"$ascii_screen" ||
  fail 'the ascii tier dropped the code and did not offer the address instead'

plain=$(env AURADE_TUI_PLAIN=1 AURADE_TUI_HEIGHT=36 "$TUI" --render help 2>/dev/null)
! grep -q '█' <<<"$plain" ||
  fail 'plain mode drew a picture at a braille display'
grep -Fq "$url" <<<"$plain" ||
  fail 'plain mode dropped the address as well as the picture'

(( failures == 0 )) || exit 1
echo 'installer QR test: PASS (matrix decodes to its own URL, quiet zone light)'
