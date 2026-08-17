#!/usr/bin/env bash
# The frame grows with the terminal, and then stops.
#
# 68 columns was a constant. A 68 column box in the corner of a 140 column
# terminal is the loudest signal a text interface can send that it was written
# for a screen nobody has any more, and it is the first thing anybody notices.
#
# Filling the terminal is not the answer either, and this is the part worth
# stating: 66 characters of text is a comfortable measure and 120 is not. A
# line that runs the full width of a wide terminal is harder to read than one
# that stops, because the eye loses its place on the way back. So the frame
# grows to a measure and the margins take whatever is left, which is what a
# printed page does with the same problem.
#
# Everything else in the suite pins AURADE_TUI_COLUMNS so its column
# measurements mean something. This file is the one that does not, because it
# is the one testing what happens when the terminal changes.
set -Eeuo pipefail
trap 'case $- in *e*) printf "%s: line %s gave up: %s\n" "${0##*/}" "$LINENO" "$BASH_COMMAND" >&2 ;; esac' ERR

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TUI=$ROOT/installer/bin/aurade-installer-tui
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
failures=0
fail() { printf 'test-tui-width: %s\n' "$*" >&2; failures=$(( failures + 1 )); }

render() {
  env -u AURADE_TUI_WIDTH AURADE_TUI_COLUMNS="$1" AURADE_TUI_HEIGHT=30 \
    AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii AURADE_TIP_RARITY=0 \
    "$TUI" --render welcome 2>/dev/null
}

# --- the measure, at four terminal widths ----------------------------------
#
# 68 is the floor rather than a preference: the layout budgets on the progress
# screen were written against it, and a narrower frame breaks them rather than
# merely looking cramped.
for pair in '80 68' '100 88' '120 100' '200 100'; do
  set -- $pair
  width=$(render "$1" | sed -n '1p' | sed 's/^ *//' | tr -d '\n' | wc -c)
  [[ $width == "$2" ]] ||
    fail "a $1 column terminal drew a $width column frame, expected $2"
done

# --- and it is centred, not left aligned -----------------------------------
#
# A frame that grows but stays in the corner has solved half the problem and
# looks like it solved none of it.
for columns in 100 140; do
  render "$columns" >"$TMP/out"
  margin=$(sed -n '1p' "$TMP/out" | sed 's/[^ ].*//' | wc -c)
  margin=$(( margin - 1 ))
  frame=$(sed -n '1p' "$TMP/out" | sed 's/^ *//' | tr -d '\n' | wc -c)
  want=$(( (columns - frame) / 2 ))
  [[ $margin == "$want" ]] ||
    fail "at $columns columns the frame sits $margin from the left, centred is $want"
  # Every row has to carry the same margin, or the frame is a staircase.
  ragged=$(grep -cv "^ \{$margin\}[|+]" "$TMP/out" || true)
  (( ragged == 0 )) || fail "at $columns columns, $ragged rows do not start at the margin"
done

# --- a terminal narrower than the floor is not made narrower ---------------
#
# 40 columns cannot hold the frame. Drawing a 68 column frame into it wraps
# every row and produces a staircase; drawing a 40 column one breaks the
# budgets. It draws the floor and lets the terminal scroll, which is the same
# answer the height already gives on a short console.
width=$(render 40 | sed -n '1p' | sed 's/^ *//' | tr -d '\n' | wc -c)
(( width >= 40 )) || fail "a 40 column terminal produced a $width column frame"

# --- an explicit width is still obeyed -------------------------------------
#
# The tests rely on this, and so does anybody who has a reason.
explicit=$(env AURADE_TUI_WIDTH=88 AURADE_TUI_COLUMNS=200 AURADE_TUI_HEIGHT=30 \
  AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii "$TUI" --render welcome 2>/dev/null |
  sed -n '1p' | sed 's/^ *//' | tr -d '\n' | wc -c)
[[ $explicit == 88 ]] ||
  fail "an explicit width of 88 drew $explicit columns"

# --- plain mode has no frame and therefore no margin -----------------------
#
# Leading spaces are braille cells. A centred frame in plain mode would be
# paying for a margin that is not there.
lead=$(env AURADE_TUI_PLAIN=1 AURADE_TUI_COLUMNS=160 AURADE_TUI_HEIGHT=30 \
  "$TUI" --render welcome 2>/dev/null | grep -c '^ ' || true)
(( lead == 0 )) || fail "plain mode indented $lead lines on a wide terminal"

(( failures == 0 )) || exit 1
echo 'installer TUI width test: PASS (frame grows to a measure, centred, floor held)'
