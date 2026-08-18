#!/usr/bin/env bash
# Stage transitions: the marks that arrive, the time that types itself in, and
# the bar that catches up rather than jumping.
set -Eeuo pipefail
trap 'case $- in *e*) printf "%s: line %s gave up: %s\n" "${0##*/}" "$LINENO" "$BASH_COMMAND" >&2 ;; esac' ERR

# shellcheck source=assert.sh
. "$(dirname -- "$0")/assert.sh"

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TUI="$ROOT/installer/bin/aurade-installer-tui"

export AURADE_TUI_COLUMNS=74
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

export AURADE_INSTALLER_TUI_LIB=1
# shellcheck source=../bin/aurade-installer-tui
. "$TUI"
unset AURADE_INSTALLER_TUI_LIB

AURADE_TUI_HEIGHT=40
JOURNAL_FILE=$TMP/j.jsonl
AURADE_JOURNAL_PATH=$JOURNAL_FILE
# No download meter in these screens; this is about the stage list.
RATE_FILE=$TMP/no-such-file

ok_row()   { printf '{"v":1,"stage":"%s","status":"ok","elapsed_ms":%s}\n' "$1" "$2" >>"$JOURNAL_FILE"; }
run_row()  { printf '{"v":1,"stage":"%s","status":"running","pct":%s}\n' "$1" "$2" >>"$JOURNAL_FILE"; }

# The screen is drawn with a plain redirect and never through a pipe. A
# pipeline is a subshell, every global the transition remembers dies with it,
# and the animation then looks exactly like one that is correctly disabled.
# This is the trap the code itself is written around, so the test that proves
# the code avoids it must avoid it too.
draw() { screen_progress "$1" >"$TMP/screen"; }
row()  { grep -F "$1" "$TMP/screen" | head -1 | tr -d '|' | sed 's/^ *//; s/ *$//; s/  */ /g'; }

reset_motion() {
  PROGRESS_LAST_STATUS=()
  PROGRESS_SETTLE_AT=()
  PROGRESS_SHOWN=-1
  PROGRESS_AGE=-1
}

# A stage running for three frames, then finishing while the next one starts.
# Six frames of settle at the default, so frames 10..15 are the transition and
# 16 onward is at rest.
stage_handover() {
  reset_motion
  : >"$JOURNAL_FILE"
  ok_row preflight 4000
  run_row pacstrap 40
  local f
  for f in 7 8 9; do draw "$f"; done
  ok_row pacstrap 323000
  run_row configure 0
}

# --- the marks arrive rather than appear ------------------------------------
stage_handover
marks_done=''
marks_next=''
times=''
for f in 10 11 12 13 14 15 16 17; do
  draw "$f"
  marks_done+="$(row 'Installing the base system' | cut -c1)"
  marks_next+="$(row 'Setting things up' | cut -c1)"
  times+="$(row 'Installing the base system' | sed 's/^. Installing the base system *//')|"
done
# A dot that swells into the mark it is going to be. Two frames each at the
# default settle, then at rest for good.
[[ $marks_done == '..oo++++' ]] ||
  { echo "the finishing mark went '$marks_done', not '..oo++++'" >&2; exit 1; }
[[ $marks_next == '..-->>>>' ]] ||
  { echo "the starting mark went '$marks_next', not '..-->>>>'" >&2; exit 1; }
# They share their first frames on purpose. What somebody sees is one movement
# travelling down the list, not two rows repainting near each other.
[[ ${marks_done:0:2} == ${marks_next:0:2} ]] ||
  { echo 'the two marks do not start together, so the hand-off reads as two events' >&2; exit 1; }
# And they have stopped being the same by the time they land.
[[ ${marks_done:6:1} != ${marks_next:6:1} ]]

# --- the elapsed time types itself in ---------------------------------------
[[ $times == '5|5:|5:|5:2|5:23|5:23|5:23|5:23|' ]] ||
  { echo "the time revealed as '$times'" >&2; exit 1; }
# Monotone: a reveal that ever showed fewer characters than the frame before
# would read as a glitch rather than as typing.
previous=0
for part in ${times//|/ }; do
  (( ${#part} >= previous )) ||
    { echo "the time went backwards at '$part'" >&2; exit 1; }
  previous=${#part}
done

# Every character of the time stays where it was first drawn.
#
# The field is right aligned and eight wide, so a reveal that returned `5` and
# then `5:` and then `5:2` would keep the row exactly as wide and slide every
# character it had already drawn one place left on every frame. The row width
# cannot see that at all, which is why this measures the column the first digit
# lands in instead.
stage_handover
columns=''
for f in 10 11 12 13 14 15 16; do
  draw "$f"
  line=$(grep -F 'Installing the base system' "$TMP/screen" | head -1)
  rest=${line#*Installing the base system}
  head=${rest%%[0-9]*}
  columns+="${#head} "
done
[[ $(tr ' ' '\n' <<<"$columns" | sort -u | grep -c .) -eq 1 ]] ||
  { echo "the time moved across the row as it arrived, at columns: $columns" >&2; exit 1; }

# --- nothing moves on the first frame a screen is drawn ---------------------
#
# This is what keeps `--render` honest and every render test valid: one call
# sees one status, has nothing to compare it against, and draws the screen at
# rest. It is also true of somebody arriving at the progress screen partway
# through an install, which should not replay transitions that already happened.
reset_motion
: >"$JOURNAL_FILE"
ok_row preflight 4000
ok_row pacstrap 323000
run_row configure 0
draw 40
[[ $(row 'Installing the base system') == '+ Installing the base system 5:23' ]] ||
  { echo "a first draw was mid transition: '$(row 'Installing the base system')'" >&2; exit 1; }
[[ $(row 'Setting things up' | cut -c1) == '>' ]]

# The rendered screen agrees, which is the assertion that actually pins the
# render tests rather than pinning the function they call.
out=$(AURADE_TUI_HEIGHT=40 "$TUI" --render progress --journal "$JOURNAL_FILE" 2>&1)
grep -Fq ' +  Installing the base system' <<<"$out"
refute grep -Fq ' .  Installing the base system' <<<"$out"
refute grep -Fq ' o  Installing the base system' <<<"$out"

# --- reduce motion means no transition, not a quicker one -------------------
ACCESS[reduce_motion]=yes
stage_handover
draw 10
[[ $(row 'Installing the base system') == '+ Installing the base system 5:23' ]] ||
  { echo 'reduce motion still animated the mark or the time' >&2; exit 1; }
[[ $(row 'Setting things up' | cut -c1) == '>' ]]
refute progress_motion
ACCESS[reduce_motion]=no
expect progress_motion

# --- plain mode says the state instead --------------------------------------
AURADE_TUI_PLAIN=1
stage_handover
draw 10
grep -Fq 'Done: Installing the base system' "$TMP/screen"
grep -Fq 'Now: Setting things up' "$TMP/screen"
refute grep -Fq ' o  Installing' "$TMP/screen"
refute progress_motion
AURADE_TUI_PLAIN=0

# --- the marks at rest, all four --------------------------------------------
[[ $(progress_mark ok)      == ' + ' ]]
[[ $(progress_mark running) == ' > ' ]]
[[ $(progress_mark failed)  == ' ! ' ]]
[[ $(progress_mark pending) == '   ' ]]
# A failure is not eased into. It happened, and the screen says so on the frame
# it happened rather than a little later and more gently.
[[ $(progress_mark failed 0) == ' ! ' ]]
[[ $(progress_mark failed 2) == ' ! ' ]]
# Waiting is three spaces to the eye and the word read linearly, because plain
# mode strips indentation and an unmarked row would look finished.
AURADE_TUI_PLAIN=1
[[ $(progress_mark pending) == 'Waiting:' ]]
[[ $(progress_mark ok 0) == 'Done:' ]]
AURADE_TUI_PLAIN=0

# --- the bar catches up rather than jumping ---------------------------------
#
# Every step has to land exactly on the target. A bar that approaches a number
# and stops a percent short of it forever is worse than one that jumps.
for target in 1 8 37 100; do
  PROGRESS_SHOWN=-1
  progress_ease 0
  [[ $PROGRESS_SHOWN -eq 0 ]] ||
    { echo 'the first frame did not start where it was told' >&2; exit 1; }
  previous=0
  frames=0
  while (( PROGRESS_SHOWN != target )); do
    progress_ease "$target"
    (( PROGRESS_SHOWN > previous )) ||
      { echo "easing to $target stalled at $PROGRESS_SHOWN" >&2; exit 1; }
    (( PROGRESS_SHOWN <= target )) ||
      { echo "easing to $target overshot to $PROGRESS_SHOWN" >&2; exit 1; }
    previous=$PROGRESS_SHOWN
    frames=$(( frames + 1 ))
    (( frames <= 40 )) ||
      { echo "easing to $target never arrived" >&2; exit 1; }
  done
  # Long enough to be movement, short enough that the number on screen is
  # never meaningfully behind the truth. At 0.12s a frame this is under two
  # seconds even for the whole bar at once.
  (( frames <= 12 )) ||
    { echo "easing to $target took $frames frames" >&2; exit 1; }
done

# The first frame ever drawn snaps, because there is nothing to move from.
PROGRESS_SHOWN=-1
progress_ease 64
[[ $PROGRESS_SHOWN -eq 64 ]]
# Progress does not go backwards. If the weighting ever says it did, the engine
# is believed rather than the animation.
progress_ease 20
[[ $PROGRESS_SHOWN -eq 20 ]]
# Reduce motion snaps too.
ACCESS[reduce_motion]=yes
PROGRESS_SHOWN=0
progress_ease 90
[[ $PROGRESS_SHOWN -eq 90 ]]
ACCESS[reduce_motion]=no

# The bar and the window title are the same number. Two opinions about how far
# along an install is, one on screen and one in a tab, is worse than either.
stage_handover
draw 12
bar=$(grep -oE '\[[#-]+\]' "$TMP/screen" | head -1)
filled=$(tr -cd '#' <<<"$bar" | wc -c)
width=$(( ${#bar} - 2 ))
expected=$(( PROGRESS_SHOWN * width / 100 ))
[[ $filled -eq $expected ]] ||
  { echo "the bar drew $filled of $width cells for $PROGRESS_SHOWN percent, not $expected" >&2; exit 1; }

echo 'progress motion test: PASS'
