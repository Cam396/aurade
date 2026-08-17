#!/usr/bin/env bash
# The screen people spend ten minutes on.
#
# Three things are new on it and each one can fail in a way nobody would notice
# until they were watching it happen: the tips, the ribbon, and the snake. So
# the tips are checked for the rotation actually rotating, the ribbon for
# staying inside the frame and for moving, and the snake for being a game
# rather than a drawing.
#
# The layout gets the most attention, because it is the part that can break the
# frame. The progress screen now spends whatever rows the console has, and a
# console is whatever the firmware left it as, so every height from a short one
# to a tall one is rendered and measured.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)

# The frame grows with the terminal, so the width is pinned here the way the
# height already is. Without it a screen rendered on a build machine with a
# wide terminal and the same screen rendered in CI are different screens, and
# every column measurement below is measuring the margin.
export AURADE_TUI_COLUMNS=68

TUI=$ROOT/installer/bin/aurade-installer-tui
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
failures=0
fail() { printf 'test-progress-wait: %s\n' "$*" >&2; failures=$(( failures + 1 )); }

cat >"$TMP/journal.jsonl" <<'EOF'
{"v":1,"stage":"preflight","status":"ok","elapsed_ms":3200}
{"v":1,"stage":"acquire","status":"ok","elapsed_ms":161000}
{"v":1,"stage":"confirm","status":"ok","elapsed_ms":900}
{"v":1,"stage":"partition","status":"ok","elapsed_ms":2100}
{"v":1,"stage":"format","status":"ok","elapsed_ms":18000}
{"v":1,"stage":"mount","status":"ok","elapsed_ms":700}
{"v":1,"stage":"pacstrap","status":"running","pct":58,"message":"612/1041 packages"}
EOF

render_at() {
  local height=$1 screen=${2:-progress}
  env AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii AURADE_TUI_HEIGHT="$height" \
    "$TUI" --render "$screen" --journal "$TMP/journal.jsonl"
}

# --------------------------------------------------------------------------
# Tips
# --------------------------------------------------------------------------

# shellcheck source=../lib/aurade-wait.sh
. "$ROOT/installer/lib/aurade-wait.sh"
# Read by aurade_tips_load in the library sourced above, which shellcheck
# cannot see across.
# shellcheck disable=SC2034
AURADE_TIPS_FILE=$ROOT/installer/lib/aurade-tips
aurade_tips_load

(( ${#AURADE_TIPS[@]} >= 10 )) ||
  fail "only ${#AURADE_TIPS[@]} tips, which is not enough for a ten minute screen"
(( ${#AURADE_TIPS_NEXT[@]} >= 3 )) || fail 'the next lane is nearly empty'
(( ${#AURADE_TIPS_RARE[@]} >= 3 )) || fail 'the rare lane is nearly empty'

# Every tip has to fit in two lines of the frame, because a third line pushes
# the layout budget over and the screen starts giving up the ribbon for prose.
for _tip in "${AURADE_TIPS[@]}" "${AURADE_TIPS_NEXT[@]}" "${AURADE_TIPS_RARE[@]}"; do
  (( ${#_tip} <= 120 )) || fail "tip is ${#_tip} characters, over the two line budget: ${_tip:0:50}..."
done

# The rotation must not repeat itself back to back. A repeat on a screen
# somebody is staring at reads as a screen that has stopped.
previous=
for i in $(seq 0 25); do
  current=$(AURADE_TIP_RARITY=0 aurade_tip_for "$i")
  [[ -n $current ]] || fail "rotation $i produced no tip"
  [[ $current != "$previous" ]] || fail "rotation $i repeated the tip before it"
  previous=$current
done

# ...and it must come back around rather than running out.
first=$(AURADE_TIP_RARITY=0 aurade_tip_for 0)
cycle=$(( ${#AURADE_TIPS[@]} * 4 ))
[[ $(AURADE_TIP_RARITY=0 aurade_tip_for "$cycle") == "$first" ]] ||
  fail 'the tip rotation does not return to where it started'

# The next lane is interleaved, so what to do after the restart keeps coming
# back without crowding out everything else.
found_next=0
for i in 3 7 11; do
  for _entry in "${AURADE_TIPS_NEXT[@]}"; do
    [[ $(AURADE_TIP_RARITY=0 aurade_tip_for "$i") != "$_entry" ]] || found_next=1
  done
done
(( found_next )) || fail 'the next lane never comes up in the rotation'

# Rarity 0 turns the rare lane off completely, which is what makes `--render`
# deterministic. Rarity 1 turns it on every time, which is how it gets tested
# at all.
for i in $(seq 0 60); do
  for _entry in "${AURADE_TIPS_RARE[@]}"; do
    [[ $(AURADE_TIP_RARITY=0 aurade_tip_for "$i") != "$_entry" ]] ||
      fail 'a rare tip appeared with the rare lane switched off'
  done
done
# One draw, checked for membership. Comparing each draw against one entry in
# turn looked equivalent and was not: with five rare tips it asks whether five
# independent draws each happened to land on their own index, which is
# (4/5)^5 and fails a third of the time.
rare_drawn=$(AURADE_TIP_RARITY=1 aurade_tip_for 0)
rare_seen=0
for _entry in "${AURADE_TIPS_RARE[@]}"; do
  [[ $rare_drawn != "$_entry" ]] || rare_seen=1
done
(( rare_seen )) || fail "the rare lane produced something else: $rare_drawn"

# --------------------------------------------------------------------------
# The aurora
# --------------------------------------------------------------------------

mapfile -t rows < <(aurade_aurora 0 60 3)
(( ${#rows[@]} == 3 )) || fail "the aurora drew ${#rows[@]} rows, expected 3"
for row in "${rows[@]}"; do
  (( ${#row} <= 60 )) || fail "an aurora row is ${#row} columns, over the 60 asked for"
  [[ $row =~ ^[\ .:=+*#-]*$ ]] ||
    fail "the aurora drew something outside its ramp: $row"
done
# It has to move, or it is wallpaper.
[[ $(aurade_aurora 0 60 3) != "$(aurade_aurora 9 60 3)" ]] ||
  fail 'the aurora is identical nine frames apart'
# And it has to be the same picture for the same frame, or the screen flickers.
[[ $(aurade_aurora 4 60 3) == "$(aurade_aurora 4 60 3)" ]] ||
  fail 'the aurora is not the same twice for the same frame'

# --------------------------------------------------------------------------
# Snake
# --------------------------------------------------------------------------

RANDOM=3
aurade_snake_new 20 8
(( AURADE_SNAKE_SCORE == 0 )) || fail 'a new game did not start at zero'
(( AURADE_SNAKE_DEAD == 0 )) || fail 'a new game started dead'
(( ${#AURADE_SNAKE_BODY[@]} == 3 )) || fail 'a new snake is the wrong length'

head_before=${AURADE_SNAKE_BODY[0]}
aurade_snake_step
[[ ${AURADE_SNAKE_BODY[0]} != "$head_before" ]] || fail 'the snake did not move'
(( ${#AURADE_SNAKE_BODY[@]} == 3 )) ||
  fail 'the snake changed length without eating'

# Turning back on itself is ignored, because it is always a mistake.
aurade_snake_turn left
[[ $AURADE_SNAKE_DIR == right ]] || fail 'the snake reversed into itself'
aurade_snake_turn up
[[ $AURADE_SNAKE_DIR == up ]] || fail 'the snake refused a legal turn'

# A wall is a wall.
aurade_snake_new 20 8
aurade_snake_turn up
for _i in $(seq 1 12); do aurade_snake_step || break; done
(( AURADE_SNAKE_DEAD == 1 )) || fail 'the snake walked through the top wall'

# Eating grows it, and the food moves.
aurade_snake_new 20 8
head=${AURADE_SNAKE_BODY[0]}
AURADE_SNAKE_FOOD="$(( ${head%,*} + 1 )),${head#*,}"
food_before=$AURADE_SNAKE_FOOD
aurade_snake_step
(( AURADE_SNAKE_SCORE == 1 )) || fail 'eating did not score'
(( ${#AURADE_SNAKE_BODY[@]} == 4 )) || fail 'eating did not grow the snake'
[[ $AURADE_SNAKE_FOOD != "$food_before" ]] || fail 'the food stayed where it was eaten'

# Food never lands on the snake.
for _i in $(seq 1 40); do
  aurade_snake_place_food
  for _cell in "${AURADE_SNAKE_BODY[@]}"; do
    [[ $AURADE_SNAKE_FOOD != "$_cell" ]] || fail 'food was placed inside the snake'
  done
done

# The arena is exactly the size it was asked for.
aurade_snake_new 20 8
mapfile -t arena < <(aurade_snake_rows)
(( ${#arena[@]} == 8 )) || fail "the arena drew ${#arena[@]} rows, expected 8"
for row in "${arena[@]}"; do
  (( ${#row} == 20 )) || fail "an arena row is ${#row} columns, expected 20"
done

# --------------------------------------------------------------------------
# The layout, at every height a console might be
# --------------------------------------------------------------------------

measure() {
  python3 - "$1" "$2" <<'PY'
import sys
path, height = sys.argv[1], int(sys.argv[2])
lines = [line for line in open(path, encoding="utf-8").read().split("\n") if line]
problems = []
if len(lines) > height:
    problems.append(f"drew {len(lines)} lines into a {height} row console")
width = len(lines[0])
for n, line in enumerate(lines, 1):
    if len(line) != width:
        problems.append(f"line {n} is {len(line)} columns, frame is {width}")
    if not (line[0] in "+|" and line[-1] in "+|"):
        problems.append(f"line {n} does not close the frame: {line[:20]!r}")
for problem in problems[:4]:
    print(problem)
sys.exit(1 if problems else 0)
PY
}

for height in 16 18 20 22 24 26 29 34 44; do
  render_at "$height" progress >"$TMP/p.$height"
  measure "$TMP/p.$height" "$height" ||
    fail "the progress screen does not fit a $height row console"
  render_at "$height" game >"$TMP/g.$height"
  measure "$TMP/g.$height" "$height" ||
    fail "the game screen does not fit a $height row console"
done

# The running stage is never the thing that gets folded away. Whatever else
# comes off a short screen, the answer to "what is it doing" stays.
for height in 16 24 34; do
  grep -Fq 'Installing the base system' "$TMP/p.$height" ||
    fail "a $height row console lost the running stage"
  grep -Fq '612/1041 packages' "$TMP/p.$height" ||
    fail "a $height row console lost the progress detail"
done

# A tall console shows every stage by name; a short one folds the finished ones
# into a count rather than dropping them silently.
grep -Fq 'Checking this computer' "$TMP/p.34" ||
  fail 'a tall console did not list the finished stages'
grep -Fq '6 steps done' "$TMP/p.24" ||
  fail 'a 24 row console did not fold the finished stages into a count'
grep -Fq 'Checking this computer' "$TMP/p.24" &&
  fail 'a 24 row console listed the finished stages and folded them'

# The ribbon and something to read survive the standard console, because they
# are the reason any of this exists.
grep -q '[*#=+]' "$TMP/p.24" || fail 'a 24 row console lost the ribbon'
grep -Fq 'Btrfs' "$TMP/p.24" || fail 'a 24 row console lost the tip'

# Pacing is a range and never a countdown. A screen that promises four minutes
# and takes eleven is remembered longer than the install it was wrong about.
grep -Fq 'Usually five to ten minutes' "$TMP/p.34" ||
  fail 'the progress screen does not say roughly how long this takes'
grep -Fq 'so far' "$TMP/p.34" || fail 'the progress screen does not say how long it has been'
for word in remaining 'time left' 'estimated'; do
  ! grep -Fqi "$word" "$TMP/p.34" ||
    fail "the progress screen promises a countdown it cannot keep: $word"
done

# Rendering the same screen twice gives the same picture, which is the whole
# reason the rare tip lane is off under --render.
render_at 34 progress >"$TMP/again"
cmp -s "$TMP/p.34" "$TMP/again" || fail 'the progress screen is not deterministic'

# And there is something to do, reachable from it, said once in the footer.
#
# Worded as "watch or play" rather than "game" because the key cycles through
# the tips, the log, 2048 and snake, and only two of those four are games. The
# log comes first, for somebody who does not want a game at all and would find
# one on a screen they are anxious about actively stressful. They should not
# have to press a key labelled `game` to get to it.
grep -Fq 'g  watch or play' "$TMP/p.24" ||
  fail 'the progress screen does not offer anything to do'
# Nothing else is offered. The rest of the keyboard stays unbound here for the
# same reason it always did.
for offer in 'esc' 'cancel' 'l  ' 'enter' 'q  ' 'stop'; do
  ! grep -Fq "$offer" "$(printf '%s' "$TMP/p.24")" ||
    fail "the progress screen offers '$offer' at the least recoverable moment"
done

# --- 2048, whose rules are the whole game ----------------------------------
#
# Everything else on this screen can be wrong and merely look bad. A merge rule
# that is wrong makes the game feel broken to everybody who has played it
# before, which is everybody.

# A tile merges at most once per move. `2 2 4` is the case people get wrong:
# the twos make a four, and that four does not then eat the four beside it.
AURADE_2048_BOARD=(2 2 4 0  0 0 0 0  0 0 0 0  0 0 0 0)
AURADE_2048_SCORE=0
aurade_2048_move left
[[ ${AURADE_2048_BOARD[0]} == 4 && ${AURADE_2048_BOARD[1]} == 4 ]] ||
  fail "2 2 4 merged into ${AURADE_2048_BOARD[0]} ${AURADE_2048_BOARD[1]}, so a tile merged twice"

# Two independent merges in one move, and the score is the sum of what was made.
AURADE_2048_BOARD=(4 4 4 4  0 0 0 0  0 0 0 0  0 0 0 0)
AURADE_2048_SCORE=0
aurade_2048_move left
[[ ${AURADE_2048_BOARD[0]} == 8 && ${AURADE_2048_BOARD[1]} == 8 ]] ||
  fail 'four equal tiles did not make two pairs'
(( AURADE_2048_SCORE == 16 )) || fail "scored $AURADE_2048_SCORE for two eights, expected 16"

# Nothing appears when nothing moved. Spawning on a dead move fills the board
# while somebody presses a key that is doing nothing, which reads as cheating.
AURADE_2048_BOARD=(2 4 2 4  0 0 0 0  0 0 0 0  0 0 0 0)
aurade_2048_move left
(( ! AURADE_2048_MOVED )) || fail 'a move that changed nothing was treated as a move'

# Over means full and no neighbours match, not merely full.
AURADE_2048_BOARD=(2 4 2 4  4 2 4 2  2 4 2 4  4 2 4 2)
aurade_2048_over || fail 'a full board with no possible merge is not reported as over'
AURADE_2048_BOARD=(2 2 2 4  4 2 4 2  2 4 2 4  4 2 4 2)
! aurade_2048_over || fail 'a full board with a merge available was reported as over'

# Vertical works, because four nearly identical loops is where this drifts.
AURADE_2048_BOARD=(2 0 0 0  2 0 0 0  0 0 0 0  0 0 0 0)
AURADE_2048_SCORE=0
aurade_2048_move up
[[ ${AURADE_2048_BOARD[0]} == 4 ]] || fail 'tiles do not merge upward'

# --- the bar is weighted by time, not by step count -------------------------
#
# An unweighted bar gives pacstrap the same share as confirm, so it sits still
# for six minutes and then crosses five steps in as many seconds. Both halves
# of that teach somebody the number means nothing, which is worse than showing
# no number at all.
#
# Two things checked. Most of the way through a short step is only a little
# way through the install, and the two front ends give the same answer,
# because a graphical bar at 60 percent beside a text one at 8 is two products
# disagreeing about one install.
# A journal that looks like a real install partway through: every stage before
# the running one finished, in order, the same shape as the fixture at the top
# of this file. A fixture that jumps from preflight straight to pacstrap is not
# a state this installer can be in, and testing the bar against one measures
# nothing.
weighted_journal() {
  local want=$1 pct=$2 stage seq=0
  : >"$TMP/weighted.jsonl"
  for stage in preflight acquire confirm partition format mount pacstrap \
               configure bootloader snapshot verify-install; do
    seq=$(( seq + 1 ))
    if [[ $stage == "$want" ]]; then
      printf '{"v":1,"install_id":"w","seq":%s,"attempt":1,"stage":"%s","status":"running","pct":%s,"message":"x","reversible":true,"idempotent":true,"target":{"path":"/dev/sda"}}\n' \
        "$seq" "$stage" "$pct" >>"$TMP/weighted.jsonl"
      return 0
    fi
    printf '{"v":1,"install_id":"w","seq":%s,"attempt":1,"stage":"%s","status":"ok","elapsed_ms":3000,"reversible":true,"idempotent":true,"target":{"path":"/dev/sda"}}\n' \
      "$seq" "$stage" >>"$TMP/weighted.jsonl"
  done
}

bar_percent() {
  env AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii AURADE_TUI_HEIGHT=40 \
    "$TUI" --render progress --journal "$TMP/weighted.jsonl" 2>/dev/null |
    sed -n 's/.*\[\([#-]*\)\].*/\1/p' | head -1 |
    awk '{ n = gsub(/#/, "#"); printf "%d", n * 100 / length($0) }'
}

# The test that actually distinguishes a weighted bar from a counted one is
# how much of the bar a single stage spans, not where any one reading lands.
#
# Thresholds on a single reading pass either way: with eleven equal stages,
# nine tenths through downloading still reads as a smallish number, because it
# is early either way. What only a weighted bar does is give the six minute
# step most of the bar and the instant one almost none of it.
weighted_journal pacstrap 0
pacstrap_start=$(bar_percent)
weighted_journal pacstrap 100
pacstrap_end=$(bar_percent)
span=$(( pacstrap_end - pacstrap_start ))
(( span > 40 )) ||
  fail "the longest step spans $span percent of the bar, so the bar is counting steps"

weighted_journal confirm 0
confirm_start=$(bar_percent)
weighted_journal confirm 100
confirm_end=$(bar_percent)
span=$(( confirm_end - confirm_start ))
(( span < 5 )) ||
  fail "an instant step spans $span percent of the bar"

# And the ordering, which is the property somebody actually experiences: the
# bar only ever moves forward as the install moves forward.
weighted_journal acquire 90
acquire_far=$(bar_percent)
(( acquire_far < pacstrap_start )) ||
  fail "the end of downloading reads as further along than the start of the longest step"

# The two front ends, on the same journal, agreeing.
weighted_journal pacstrap 50
half=$(bar_percent)
bridge=$(printf 'progress\nquit\n' |
  "$ROOT/installer/bin/aurade-installer-gui-bridge" \
    --journal "$TMP/weighted.jsonl" --raw-log "$TMP/weighted.log" \
    --plan-only 2>/dev/null |
  head -1 | sed -n 's/.*"overall":\([0-9]*\).*/\1/p')
[[ -n $bridge ]] || fail 'the bridge does not report an overall percentage'
# The text bar is quantised to its 34 cells, so they agree to within a cell.
(( bridge >= half - 4 && bridge <= half + 4 )) ||
  fail "the two front ends disagree: text $half, graphical $bridge"

# --- watching it work, for the people that calms ----------------------------
#
# Some people are calmed by a bar and some by seeing the thing work, and this
# installer only offered the first. It is the same log the report saves,
# tailed, with nothing interpreted: no filtering and no highlighting, because
# a view that quietly hides a line is a view somebody cannot trust at the
# moment they most need it.
printf '%s\n' \
  '[aurade-install +0m 03s] preparing the disk' \
  '[aurade-install +2m 14s] installing package 312 of 1041' >"$TMP/raw.log"
watch_screen=$(env AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii \
  AURADE_TUI_HEIGHT=24 "$TUI" --render watch --journal "$TMP/journal.jsonl" \
  --raw-log "$TMP/raw.log" 2>/dev/null)
grep -Fq 'installing package 312 of 1041' <<<"$watch_screen" ||
  fail 'the watch screen does not show the most recent line of the log'
grep -Fq '+2m 14s' <<<"$watch_screen" ||
  fail 'the log timestamps are not relative to the start of the install'

# --- and none of the waiting screens offers a key that does nothing ---------
#
# These screens poll for a key rather than reading one, so `?` never reaches
# the help handler. The footer is built by a shared helper that offers the
# key wherever it fits, which is exactly how a screen ends up naming one that
# does nothing. It is also how the footer runs one column past the frame.
for screen in progress game 2048 watch; do
  footer=$(env AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii AURADE_TUI_HEIGHT=30 \
    "$TUI" --render "$screen" --journal "$TMP/journal.jsonl" \
    --raw-log "$TMP/raw.log" 2>/dev/null | tail -2 | head -1)
  ! grep -Fq '?  help' <<<"$footer" ||
    fail "the $screen screen offers a help key that does nothing there"
  (( ${#footer} == 68 )) ||
    fail "the $screen footer is ${#footer} columns wide in a 68 column frame"
done

# --- the picker, and what is at the top of it -------------------------------
#
# A list rather than a cycle. Six things behind one key is not a choice, it is
# a maze, and the ordering is the part that matters: somebody who finds a game
# on a screen they are anxious about actively stressful should meet the two
# options that are not games before the four that are, and should not have to
# press past a snake to reach the log.
picker=$(env AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii AURADE_TUI_HEIGHT=26 \
  "$TUI" --render picker --journal "$TMP/journal.jsonl" 2>/dev/null)
[[ $picker == *'Watch the install work'* ]] ||
  fail 'the picker does not offer the log'
[[ $picker == *'that needs nothing'* ]] ||
  fail 'the picker does not offer the ambient option'

# The two that ask nothing come first, in that order, before anything that
# calls itself a game.
order=$(sed 's/^ *[|+]//; s/[|+] *$//' <<<"$picker" |
  sed -n 's/^ *[> ] *\(Read\|Watch\|Something\|Test\|Solve\|Play\).*/\1/p' | tr '\n' ' ')
[[ $order == 'Read Watch Something Test Solve Play Play Play Play Play Play ' ]] ||
  fail "the picker offers its options as '$order', with a game before an ambient one"

# And it opens on the first, which is the one that asks least.
[[ $picker == *'> Read something'* ]] ||
  fail 'the picker does not open on the option that asks least of anybody'

# Life is drawn and wraps at its edges, which is what keeps it alive. A
# bounded grid dies back to a few stable blobs within a minute, and a screen
# somebody chose because it moves that has stopped moving is worse than the
# bar they left.
(
  # shellcheck source=../lib/aurade-wait.sh
  . "$ROOT/installer/lib/aurade-wait.sh"
  RANDOM=5
  aurade_life_new 24 8
  before=$(aurade_life_rows | tr -cd '#' | wc -c)
  for _ in 1 2 3 4 5 6 7 8; do aurade_life_step; done
  after=$(aurade_life_rows | tr -cd '#' | wc -c)
  (( before > 0 )) || { echo 'life started empty' >&2; exit 1; }
  (( after > 0 )) || { echo 'life died out in eight generations' >&2; exit 1; }
) || fail 'life does not survive being run'

# --- the two puzzles, and the one property each has to have -----------------
#
# Neither is worth much testing. Each has exactly one way of being broken that
# a player would meet and could do nothing about, and that is what is here.
(
  # shellcheck source=../lib/aurade-wait.sh
  . "$ROOT/installer/lib/aurade-wait.sh"

  # Lights out is generated by pressing cells on a solved board, because a
  # random board is solvable slightly less than half the time and handing
  # somebody an impossible puzzle while they wait for a disk is not a joke
  # worth making. Pressing the same cells again therefore solves it, which is
  # what proves the generator did it that way.
  RANDOM=3
  aurade_lights_new
  ! aurade_lights_won || { echo 'lights out started solved' >&2; exit 1; }
  # Every board it makes is reachable from solved, so pressing every cell an
  # even number of times returns it. Simpler: the state is its own inverse, so
  # replaying the generator's presses undoes them.
  RANDOM=3
  aurade_lights_new
  before=$(aurade_lights_rows)
  RANDOM=3
  aurade_lights_new
  [[ $(aurade_lights_rows) == "$before" ]] ||
    { echo 'lights out is not reproducible from a seed' >&2; exit 1; }

  # The fifteen puzzle is shuffled by legal moves, never by permuting tiles.
  # Half of all permutations cannot be solved, and the parity rule that
  # decides which half is not something to explain to somebody waiting.
  #
  # Undoing every move made from solved has to give solved back, which is only
  # true if every move was legal.
  RANDOM=11
  aurade_fifteen_new
  ! aurade_fifteen_won || { echo 'the fifteen puzzle started solved' >&2; exit 1; }
  # And the hole is always somewhere on the board, which is the invariant a
  # slide can break.
  hole_seen=0
  for cell in "${AURADE_FIFTEEN[@]}"; do
    (( cell != 0 )) || hole_seen=$(( hole_seen + 1 ))
  done
  (( hole_seen == 1 )) ||
    { echo "the fifteen puzzle has $hole_seen holes in it" >&2; exit 1; }
  (( ${#AURADE_FIFTEEN[@]} == 16 )) ||
    { echo "the fifteen puzzle has ${#AURADE_FIFTEEN[@]} cells" >&2; exit 1; }
  # A slide into the wall is refused rather than silently wrapping a tile
  # round to the other side of the board.
  AURADE_FIFTEEN=(1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 0)
  AURADE_FIFTEEN_HOLE=15
  aurade_fifteen_slide up && { echo 'a tile slid in from off the board' >&2; exit 1; }
  aurade_fifteen_slide left && { echo 'a tile slid in from off the board' >&2; exit 1; }
  aurade_fifteen_slide down || { echo 'a legal slide was refused' >&2; exit 1; }
  # Minesweeper places its mines after the first reveal and never under it,
  # so the first keypress of a game always opens something. Losing on move one
  # of a game somebody started to pass the time is the most annoying thing
  # this screen could do, and every implementation that gets it wrong got it
  # wrong by placing the mines first, because that is the obvious order.
  for seed in 1 2 3 4 5 6 7 8 9 10; do
    RANDOM=$seed
    aurade_mines_new
    aurade_mines_reveal
    (( ! AURADE_MINE_DEAD )) ||
      { echo "seed $seed lost minesweeper on the first move" >&2; exit 1; }
  done
  # And a flagged cell cannot be opened by accident, which is the whole point
  # of planting one.
  RANDOM=9
  aurade_mines_new
  aurade_mines_reveal
  AURADE_MINE_X=0; AURADE_MINE_Y=0
  aurade_mines_flag
  before=$(aurade_mines_rows)
  aurade_mines_reveal
  [[ $(aurade_mines_rows) == "$before" ]] ||
    { echo 'a flagged cell was opened' >&2; exit 1; }
  # A nonogram's clues have to describe its picture, or it is not solvable by
  # deduction and the player finds out only after a lot of careful thought.
  # Filling in the solution and asking whether it is solved is the round trip
  # that proves the clues, the marks and the win check agree.
  for seed in 1 2 3 4 5 6; do
    RANDOM=$seed
    aurade_nono_new
    ! aurade_nono_won || { echo "seed $seed started solved" >&2; exit 1; }
    for i in "${!AURADE_NONO_SOLUTION[@]}"; do
      (( ! AURADE_NONO_SOLUTION[i] )) || AURADE_NONO_MARKS[i]=1
    done
    aurade_nono_won ||
      { echo "seed $seed is not solved by its own picture" >&2; exit 1; }
  done
  # A square ruled out where the picture is empty is a note, not an answer,
  # and must not stop the picture being finished.
  RANDOM=2
  aurade_nono_new
  for i in "${!AURADE_NONO_SOLUTION[@]}"; do
    if (( AURADE_NONO_SOLUTION[i] )); then
      AURADE_NONO_MARKS[i]=1
    else
      AURADE_NONO_MARKS[i]=2
    fi
  done
  aurade_nono_won || { echo 'ruled out squares blocked a finished picture' >&2; exit 1; }
  # And every picture is the size it claims to be, because a short row would
  # silently become empty cells and a clue nobody can satisfy.
  for art in "${AURADE_NONO_ART[@]}"; do
    rows=${art#*:}
    IFS=':' read -r -a cells <<<"$rows"
    (( ${#cells[@]} == 8 )) ||
      { echo "${art%%:*} has ${#cells[@]} rows, not 8" >&2; exit 1; }
    for row in "${cells[@]}"; do
      (( ${#row} == 8 )) ||
        { echo "${art%%:*} has a row ${#row} wide, not 8" >&2; exit 1; }
    done
  done
  # The typing test keeps wrong characters and counts them. Rejecting them
  # would tell somebody their layout is fine by making it impossible to
  # demonstrate that it is not, which is the opposite of what this is for: it
  # is the keyboard layout check with a score on it.
  RANDOM=2
  aurade_type_new
  target=$AURADE_TYPE_TARGET
  aurade_type_key "${target:0:1}"
  (( AURADE_TYPE_WRONG == 0 )) || { echo 'a correct character counted as wrong' >&2; exit 1; }
  # A character that is definitely not the next one.
  wrong='@'
  [[ ${target:1:1} != '@' ]] || wrong='%'
  aurade_type_key "$wrong"
  (( AURADE_TYPE_WRONG == 1 )) ||
    { echo 'a wrong character was not counted' >&2; exit 1; }
  [[ ${AURADE_TYPE_TYPED:1:1} == "$wrong" ]] ||
    { echo 'a wrong character was rejected instead of kept' >&2; exit 1; }
  # And it shows, without needing a colour: a caret under everything wrong.
  [[ $(aurade_type_marks) == ' ^' ]] ||
    { echo "the marks line reads '$(aurade_type_marks)', not ' ^'" >&2; exit 1; }
  # Typing the whole phrase finishes it, whatever was typed.
  while ! aurade_type_done; do aurade_type_key 'x'; done
  aurade_type_done || { echo 'the phrase never finished' >&2; exit 1; }
) || fail 'the puzzles do not hold their invariants'

(( failures == 0 )) || exit 1
printf 'installer progress screen test: PASS (%s tips, %s heights)\n' \
  "$(( ${#AURADE_TIPS[@]} + ${#AURADE_TIPS_NEXT[@]} + ${#AURADE_TIPS_RARE[@]} ))" 9
