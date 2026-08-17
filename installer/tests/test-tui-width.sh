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

# --- a terminal narrower than the floor gives up the floor ------------------
#
# 40 columns cannot hold the frame, and something has to give. Drawing 68
# columns into 40 wraps every row and produces a staircase, which is
# unreadable; drawing 40 overruns the layout budgets, and those truncate,
# which is merely cramped. So the frame follows the terminal below the floor
# and the text loses its ends rather than its shape.
width=$(render 40 | sed -n '1p' | sed 's/^ *//' | tr -d '\n' | wc -c)
[[ $width == 40 ]] || fail "a 40 column terminal produced a $width column frame"

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

# --- two panes, and one divider ---------------------------------------------
#
# On a wide terminal the review screen puts the list on the left and what the
# selected line means on the right. The failure this guards is not "the panes
# are missing", it is a one column disagreement between the rows and the rules
# that close them: `_tui_split` and `tui_pane_rule` compute the divider
# separately, and a frame with a tee one column off its divider looks like a
# rendering bug in a way a missing feature never does.
#
# So it measures rather than greps. Every row that carries two dividers puts
# them in the same place, and so does every rule.
review() {
  env -u AURADE_TUI_WIDTH AURADE_TUI_COLUMNS="$1" AURADE_TUI_HEIGHT=34 \
    AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii "$TUI" --render review 2>/dev/null
}

divider_columns() {
  awk '
    function nth(s, c, want,   i, n) {
      n = 0
      for (i = 1; i <= length(s); i++) {
        if (substr(s, i, 1) != c) continue
        if (++n == want) return i
      }
      return 0
    }
    function total(s, c,   i, n) {
      n = 0
      for (i = 1; i <= length(s); i++) if (substr(s, i, 1) == c) n++
      return n
    }
    {
      line = $0
      sub(/^ +/, "", line)
      # Three verticals is a split row; three corners is a rule with a tee.
      # Everything else is a full width row and has no opinion about this.
      if (total(line, "|") == 3) print "row " nth(line, "|", 2)
      else if (total(line, "+") == 3) print "rule " nth(line, "+", 2)
    }
  ' "$1"
}

review 120 >"$TMP/two"
divider_columns "$TMP/two" >"$TMP/cols"

rows=$(grep -c '^row ' "$TMP/cols" || true)
rules=$(grep -c '^rule ' "$TMP/cols" || true)
(( rows >= 4 )) || fail "a 120 column terminal drew $rows split rows, so there is no second pane"
(( rules == 2 )) || fail "the split is closed by $rules tee'd rules, expected one above and one below"

distinct=$(awk '{ print $2 }' "$TMP/cols" | sort -u | wc -l)
(( distinct == 1 )) ||
  fail "the divider sits in $distinct different columns down the screen, expected 1"

# The right pane has to actually say something. An empty second column is the
# failure mode where the layout landed and the content did not.
right=$(sed 's/^ *//' "$TMP/two" | awk -F'|' '/^\|/ && NF == 4 { print $3 }' | tr -d ' \n' | wc -c)
(( right > 40 )) || fail "the detail pane drew $right characters, so it is empty"

# --- and one pane everywhere else -------------------------------------------
#
# 88 columns split in two is two cramped columns rather than one comfortable
# one, which is worse than what it replaced. The measure has to earn the
# second pane, not merely be wider than the floor.
for columns in 80 100; do
  split=$(review "$columns" | sed 's/^ *//' | grep -c '^|.*|.*|' || true)
  (( split == 0 )) ||
    fail "a $columns column terminal split the review screen into two panes"
done

# Plain mode never splits. Columns are for an eye that moves sideways, and a
# braille line is read in one direction only.
split=$(env AURADE_TUI_PLAIN=1 AURADE_TUI_COLUMNS=160 AURADE_TUI_HEIGHT=34 \
  "$TUI" --render review 2>/dev/null | grep -c '|' || true)
(( split == 0 )) || fail "plain mode drew $split lines carrying a frame character"

(( failures == 0 )) || exit 1
echo 'installer TUI width test: PASS (frame grows to a measure, centred, two panes when they fit)'
