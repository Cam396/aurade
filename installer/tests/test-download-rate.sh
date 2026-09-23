#!/usr/bin/env bash
# The download meter: the sampler that watches the cache, and the sparkline
# the progress screen draws from what it wrote.
set -Eeuo pipefail
trap 'case $- in *e*) printf "%s: line %s gave up: %s\n" "${0##*/}" "$LINENO" "$BASH_COMMAND" >&2 ;; esac' ERR

# shellcheck source=assert.sh
. "$(dirname -- "$0")/assert.sh"

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
SAMPLER="$ROOT/installer/bin/aurade-rate-sampler"
TUI="$ROOT/installer/bin/aurade-installer-tui"

export AURADE_TUI_COLUMNS=78

TMP=$(mktemp -d)
cleanup() {
  [[ -z ${SAMPLER_PID:-} ]] || { kill "$SAMPLER_PID" 2>/dev/null || true; }
  rm -rf "$TMP"
}
trap cleanup EXIT
SAMPLER_PID=

# --- the sparkline, which is pure and can be measured exactly ---------------
export AURADE_INSTALLER_TUI_LIB=1
# shellcheck source=../bin/aurade-installer-tui
. "$TUI"
unset AURADE_INSTALLER_TUI_LIB

AURADE_TUI_PLAIN=0
AURADE_TUI_FRAME=rounded
TERM=xterm-256color

# Scaled to its own maximum, so the tallest sample is the tallest glyph and
# the shortest is the shortest. A meter drawn against an absolute ceiling is
# flat at the floor on every connection that is not a leased line.
[[ $(tui_spark 0 1 2 3 4 5 6 7) == '▁▂▃▄▅▆▇█' ]]
[[ $(tui_spark 0 70000000) == '▁█' ]]
# The same series scaled up is the same picture. This is the property that
# makes the line worth looking at, and the one an absolute scale would lose.
[[ $(tui_spark 1 2 3 4) == "$(tui_spark 1000 2000 3000 4000)" ]]
# A flat line is flat, wherever it sits.
[[ $(tui_spark 5 5 5 5) == '████' ]]
# Nothing has arrived yet. All zeroes is a divide by zero waiting to be a
# stack trace on somebody's install screen; it has to be a floor instead.
[[ $(tui_spark 0 0 0) == '▁▁▁' ]]
# Junk in the file is skipped rather than drawn or crashed on.
[[ $(tui_spark 4 'nonsense' 8 -3) == '▄█' ]]
[[ -z $(tui_spark) ]]
[[ -z $(tui_spark 'nonsense') ]]
# One glyph per sample, always. A line that quietly drops or doubles a sample
# is a line that lies about the shape.
[[ $(tui_spark 1 2 3 4 5 6 7 8 9 10 11 12) == '▁▂▂▃▃▄▅▅▆▆▇█' ]]

# A terminal with no block elements gets the shape, not an apology.
AURADE_TUI_FRAME=ascii
[[ $(tui_spark 0 1 2 3 4) == '_.-=#' ]]
[[ $(tui_spark 9 9 9) == '###' ]]
# The linux console draws box characters and does not have these, which is the
# same reason tui_bar checks for it.
AURADE_TUI_FRAME=rounded
TERM=linux
[[ $(tui_spark 0 4) == '_#' ]]
TERM=xterm-256color

# --- the rate, in the units somebody reading a meter thinks in --------------
[[ $(tui_rate 0) == '0 B/s' ]]
[[ $(tui_rate 512) == '512 B/s' ]]
[[ $(tui_rate 1024) == '1.0 kB/s' ]]
[[ $(tui_rate 1536) == '1.5 kB/s' ]]
[[ $(tui_rate 1048576) == '1.0 MB/s' ]]
[[ $(tui_rate 3355443) == '3.1 MB/s' ]]
[[ -z $(tui_rate '') ]]
[[ -z $(tui_rate 'nonsense') ]]

# --- the sampler ------------------------------------------------------------
#
# Wall clock, because what is being tested is a thing that samples on a timer.
# One second per sample and a handful of samples, so this costs a few seconds
# and measures the behaviour rather than a mock of it.
mkdir -p "$TMP/cache"
"$SAMPLER" "$TMP/cache" "$TMP/rate" 1 4 >/dev/null 2>&1 &
SAMPLER_PID=$!

# Restricted from the moment it exists, not from the first sample. The window
# between the two is short and is exactly when a file that is going to be
# world readable is world readable.
sleep 0.3
[[ $(stat -c '%a' "$TMP/rate") == 600 ]]

every_line_a_number() {
  local line
  while IFS= read -r line; do
    [[ $line =~ ^[0-9]+$ ]] ||
      { echo "sampler wrote a non-number: $line" >&2; exit 1; }
  done <"$TMP/rate"
}

head -c 2000000 /dev/urandom >"$TMP/cache/a"; sleep 1.2
head -c 4000000 /dev/urandom >"$TMP/cache/b"; sleep 1.2
# A cache being cleared for a retry is not a negative download rate. Read
# immediately, because the window is four samples wide and a negative one
# scrolls out of it before the end of this test.
rm -f "$TMP/cache"/*; sleep 1.4
every_line_a_number
head -c 3000000 /dev/urandom >"$TMP/cache/c"; sleep 1.2
head -c 1000000 /dev/urandom >"$TMP/cache/d"; sleep 1.2
head -c 1000000 /dev/urandom >"$TMP/cache/e"; sleep 1.4

# Every line is a non-negative integer. The front end skips anything else, so
# without this assertion the sampler could emit prose and nothing would say so.
every_line_a_number
# Bounded. This file is rewritten once a second for however long a package
# download takes, and an unbounded one on tmpfs is a memory leak with a graph.
[[ $(wc -l <"$TMP/rate") -le 4 ]]
[[ $(wc -l <"$TMP/rate") -ge 2 ]]
[[ $(stat -c '%a' "$TMP/rate") == 600 ]]
# Something was actually measured. Six seconds of writing megabytes cannot
# honestly come out as a flat zero.
grep -qE '^[1-9][0-9]{4,}$' "$TMP/rate"
# The temporary the rewrite goes through is never left behind, and is never
# what a reader finds instead of the file.
[[ ! -e "$TMP/rate.new" ]]

kill "$SAMPLER_PID" 2>/dev/null || true
wait "$SAMPLER_PID" 2>/dev/null || true
SAMPLER_PID=
[[ ! -e "$TMP/rate.new" ]]

# Bad arguments are refused rather than half-obeyed.
#
# Refusing is only half of it. This runs in the background of an install, in
# whatever directory the engine happens to be in, so the property that matters
# is that a rejected invocation leaves nothing behind: a sampler that creates
# a directory and then dies has still created a directory somewhere nobody
# asked for one. Both halves are checked, from a scratch directory, because a
# non-zero exit on its own is satisfied by falling over after the damage.
mkdir -p "$TMP/cwd"
for bad in \
  '' \
  "$TMP/cache" \
  "$TMP/cache relative-path" \
  "$TMP/cache sub/relative-path" \
  "$TMP/cache $TMP/out 0" \
  "$TMP/cache $TMP/out 1 1" \
  "$TMP/cache $TMP/out x 4" \
  "$TMP/not-a-directory $TMP/out"; do
  # shellcheck disable=SC2086
  if (cd "$TMP/cwd" && timeout 5 "$SAMPLER" $bad) >/dev/null 2>&1; then
    echo "sampler accepted bad arguments: [$bad]" >&2
    exit 1
  fi
  [[ -z $(ls -A "$TMP/cwd") ]] ||
    { echo "sampler left something behind after: [$bad]" >&2
      ls -A "$TMP/cwd" >&2; exit 1; }
  [[ ! -e "$TMP/out" ]] ||
    { echo "sampler wrote an output file after: [$bad]" >&2; exit 1; }
done

# --- the row on the progress screen ----------------------------------------
cat >"$TMP/journal.jsonl" <<'EOF'
{"v":1,"install_id":"x","seq":1,"stage":"preflight","status":"ok","elapsed_ms":4000}
{"v":1,"install_id":"x","seq":2,"stage":"package-check","status":"ok","message":"workspace"}
{"v":1,"install_id":"x","seq":3,"stage":"acquire","status":"running","pct":41,"message":"downloading"}
EOF
printf '%s\n' 120000 4800000 6100000 5900000 2400000 900000 6291456 >"$TMP/acquire-rate"

render() {
  AURADE_TUI_HEIGHT=40 AURADE_TUI_FRAME=${2:-rounded} \
    bash "$TUI" --render progress --journal "$TMP/journal.jsonl" ${1:+$1} 2>&1
}

render >"$TMP/screen.out"
grep -Fq '6.0 MB/s' "$TMP/screen.out"
grep -q '▁▆▇▇▃▂█' "$TMP/screen.out"
render '' ascii >"$TMP/ascii.out"
grep -Fq '6.0 MB/s' "$TMP/ascii.out"

# Plain mode says the number instead. A row of block characters read out loud
# is a row of block characters read out loud, and a braille display renders it
# as gibberish for the whole of the download.
render --plain >"$TMP/plain.out"
grep -Fq 'Downloading at 6.0 MB/s.' "$TMP/plain.out"
refute grep -q '▁' "$TMP/plain.out"

# Not during any other stage. The meter measures the package cache, so drawing
# it while the disk is being partitioned would be showing a number that stopped
# changing several minutes ago.
cat >"$TMP/later.jsonl" <<'EOF'
{"v":1,"install_id":"x","seq":1,"stage":"package-check","status":"ok","message":"workspace"}
{"v":1,"install_id":"x","seq":2,"stage":"acquire","status":"ok","elapsed_ms":40000}
{"v":1,"install_id":"x","seq":3,"stage":"pacstrap","status":"running","pct":12,"message":"60 of 500 packages"}
EOF
cp "$TMP/acquire-rate" "$TMP/acquire-rate.keep"
AURADE_TUI_HEIGHT=40 bash "$TUI" --render progress --journal "$TMP/later.jsonl" \
  >"$TMP/later.out" 2>&1
refute grep -Fq 'MB/s' "$TMP/later.out"

# The target-disk route uses the same meter after formatting, with its own
# stage selected from the package-check record.
cat >"$TMP/target.jsonl" <<'EOF'
{"v":1,"install_id":"x","seq":1,"stage":"package-check","status":"ok","message":"target"}
{"v":1,"install_id":"x","seq":2,"stage":"acquire-target","status":"running","pct":41,"message":"downloading"}
EOF
render_target() {
  AURADE_TUI_HEIGHT=40 AURADE_TUI_FRAME=${2:-rounded} \
    bash "$TUI" --render progress --journal "$TMP/target.jsonl" ${1:+$1} 2>&1
}
render_target >"$TMP/target.out"
grep -Fq 'Downloading packages to disk' "$TMP/target.out"
grep -Fq '6.0 MB/s' "$TMP/target.out"

# No samples, no row, no gap where a row would be. A resumed install and a
# machine that got its packages off the medium both look like this.
rm -f "$TMP/acquire-rate"
render >"$TMP/norate.out"
refute grep -Fq 'MB/s' "$TMP/norate.out"
grep -Fq 'Downloading packages' "$TMP/norate.out"
# One sample is a dot, not a line.
printf '%s\n' 4800000 >"$TMP/acquire-rate"
render >"$TMP/one.out"
refute grep -Fq 'MB/s' "$TMP/one.out"

# The row is in the height budget.
#
# It appears for exactly one stage of fourteen, so a row left out of the
# layout arithmetic costs a row of something else on a short console during
# `acquire` and nowhere else, which is the shape of bug that ships.
#
# Asserted against the layout rather than against the rendered height, because
# the rendered height cannot see it: the fixed cost is a conservative estimate
# and the screen has slack at every terminal size, so an uncounted row is
# absorbed rather than shown. What is actually wrong is that the layout was
# told the wrong number, so that is what is measured.
#
# Eleven stages, one done, nine pending, twenty one rows: the exact size at
# which the aurora is the last thing that fits, so one more row is one row too
# many and the difference is visible in the chosen layout.
cp "$TMP/acquire-rate.keep" "$TMP/acquire-rate"
AURADE_TUI_HEIGHT=21
progress_layout 11 1 9 0
[[ $PROGRESS_AURORA -eq 1 ]]
progress_layout 11 1 9 1
[[ $PROGRESS_AURORA -eq 0 ]] ||
  { echo 'the download row is not counted in the progress layout' >&2; exit 1; }

# And the whole screen still fits the terminal it was drawn for, at the sizes
# a console actually comes in.
for height in 24 26 30 40; do
  AURADE_TUI_HEIGHT=$height bash "$TUI" --render progress \
    --journal "$TMP/journal.jsonl" >"$TMP/h$height.out" 2>&1
  [[ $(wc -l <"$TMP/h$height.out") -le $height ]] ||
    { echo "progress screen overflowed a $height row console" >&2; exit 1; }
done

echo 'download rate test: PASS'
