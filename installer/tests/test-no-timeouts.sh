#!/usr/bin/env bash
# Nothing on any screen expires.
#
# An accessibility rule before it is a courtesy one. A confirmation that runs
# out while somebody navigates it with a switch, reads it a character at a time
# off a braille line, or listens to it at the speed speech runs is a locked
# door, and from their side it is indistinguishable from a crash. It is also a
# safety rule at the erase gate, which exists to make somebody certain before
# something irreversible: a gate that gets bored has stopped asking.
set -Eeuo pipefail
trap 'case $- in *e*) printf "%s: line %s gave up: %s\n" "${0##*/}" "$LINENO" "$BASH_COMMAND" >&2 ;; esac' ERR

# shellcheck source=assert.sh
. "$(dirname -- "$0")/assert.sh"

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TUI_LIB="$ROOT/installer/lib/aurade-tui.sh"
TUI="$ROOT/installer/bin/aurade-installer-tui"

TMP=$(mktemp -d)
READER=
cleanup() {
  [[ -z $READER ]] || kill "$READER" 2>/dev/null || true
  exec 9>&- 2>/dev/null || true
  rm -rf "$TMP"
}
trap cleanup EXIT

# --- the behaviour ----------------------------------------------------------
#
# A screen waiting for a key is still waiting a long time later, and the key
# that eventually arrives is the key it returns. Driven through a fifo held
# open at the other end, so the reader sees neither input nor end of file: an
# unheld pipe closes and `read` returns straight away, which looks exactly like
# a timeout and would make this pass against code that had one.
mkfifo "$TMP/keys"
bash -c '
  set -Eeuo pipefail
  . "$1"
  key=$(tui_read_key) || key="(gave up)"
  printf "%s" "$key" >"$2"
' _ "$TUI_LIB" "$TMP/got" <"$TMP/keys" &
READER=$!
exec 9>"$TMP/keys"

# Long enough to rule out a short one, and this is the half of the check that
# costs wall clock, so it is the shorter half. The structural check below is
# what catches a timeout somebody sets to thirty seconds.
sleep 3
kill -0 "$READER" 2>/dev/null ||
  { echo 'a screen waiting for a key gave up on its own' >&2
    [[ ! -s $TMP/got ]] || printf 'it returned: %s\n' "$(cat "$TMP/got")" >&2
    exit 1; }
[[ ! -s $TMP/got ]] ||
  { echo "a screen returned '$(cat "$TMP/got")' before any key was pressed" >&2; exit 1; }

printf 'x' >&9
wait "$READER" 2>/dev/null || true
READER=
[[ $(cat "$TMP/got") == x ]] ||
  { echo "the key that arrived came back as '$(cat "$TMP/got")'" >&2; exit 1; }

# --- the mechanism ----------------------------------------------------------
#
# The behaviour above cannot catch a timeout set to thirty seconds without a
# test that takes thirty seconds, so the two functions every screen waits in
# are read directly and asserted to contain no timed read. This is a rule about
# what may be added later, which is the only kind of rule worth writing down
# when the thing it forbids is not there yet.
body() {
  local file=$1 name=$2
  awk -v fn="$name" '
    $0 ~ "^" fn "\\(\\) \\{" { inside = 1; next }
    inside && /^\}/ { exit }
    inside { print }
  ' "$file"
}

for pair in "$TUI_LIB:tui_read_key" "$TUI:read_key"; do
  file=${pair%%:*}
  name=${pair##*:}
  text=$(body "$file" "$name")
  [[ -n $text ]] ||
    { echo "$name was not found in $(basename "$file"), so nothing was checked" >&2
      exit 1; }
  # `read -t`, `read -rsn1 -t`, `-t 0.05` in any arrangement.
  if grep -Eq 'read[^|;&]*[[:space:]]-[a-zA-Z]*t[[:space:]]|read[^|;&]*[[:space:]]-t[0-9]' <<<"$text"; then
    echo "$name waits with a timeout, so a screen using it can expire:" >&2
    grep -En 'read' <<<"$text" >&2
    exit 1
  fi
done

# The two timed reads that do exist are both accounted for, and neither expires
# a decision. Named here so that a third one appearing is a failing test rather
# than a thing somebody has to notice.
timed=$(grep -rn 'read[^|;&]*-[a-zA-Z]*t[[:space:]]' "$TUI_LIB" "$TUI" | grep -v '^\s*#' || true)
allowed=0
while IFS= read -r line; do
  [[ -n $line ]] || continue
  case $line in
    # The escape sequence decoder. Fifty milliseconds to tell a bare Escape
    # from an arrow key, disambiguating bytes that have already arrived.
    *_tui_read_escape*|*'-t 0.05'*) allowed=$(( allowed + 1 )) ;;
    # The bracketed paste reader, consuming text the terminal has already
    # committed to sending. Bounded because the other end is a terminal: one
    # that sends the start marker and then dies would otherwise hang the
    # installer forever, which is worse than a truncated paste.
    *'-t 5 byte'*) allowed=$(( allowed + 1 )) ;;
    # The progress screen's redraw poll, which is the one screen with no
    # decision on it to expire. That it stays that way is asserted below.
    *'-t "$timeout"'*) allowed=$(( allowed + 1 )) ;;
    *)
      echo "an unaccounted timed read: $line" >&2
      exit 1 ;;
  esac
done <<<"$timed"
# Both of the accounted ones are still there. Without this the list above
# would keep passing after the reads it exempts had been deleted, which is a
# check that has quietly stopped looking at anything.
# All of the accounted ones are still there. Without this the list above would
# keep passing after the reads it exempts had been deleted, which is a check
# that has quietly stopped looking at anything.
(( allowed >= 4 )) ||
  { echo "only $allowed of the four known timed reads are still there, so this" \
         'check is no longer looking at what it thinks it is' >&2; exit 1; }

# The escape decoder is the mirror image of the rule above: every read in it
# must be bounded, because it runs after Escape has already arrived and is
# deciding whether a second byte is coming. An unbounded read there hangs the
# installer on the one key that means "go back", and counting timed reads in
# total does not catch it, because there are three and losing one still leaves
# two. This is why the count above is not enough on its own.
text=$(body "$TUI_LIB" _tui_read_escape)
[[ -n $text ]] ||
  { echo 'the escape decoder was not found, so nothing was checked' >&2; exit 1; }
while IFS= read -r line; do
  case $line in
    *read*) ;;
    *) continue ;;
  esac
  case $line in
    *'#'*) continue ;;
  esac
  grep -Eq -- '-[a-zA-Z]*t[[:space:]]|-t[0-9]' <<<"$line" ||
    { echo "the escape decoder reads without a bound, so Escape hangs: $line" >&2
      exit 1; }
done <<<"$text"

# And the polling read is used by exactly one caller: the loop that draws the
# progress screen while the engine runs. That is the property that keeps it
# from being a timeout. A second caller would be a screen that gives up, and
# the exemption above would quietly cover it.
callers=$(grep -n 'tui_poll_key' "$TUI" | grep -v '^[0-9]*:[[:space:]]*#' | grep -cv '#:' || true)
[[ $callers -eq 1 ]] ||
  { echo "the polling read has $callers callers in the text installer, not 1" >&2
    grep -n 'tui_poll_key' "$TUI" >&2
    exit 1; }
grep -n 'tui_poll_key' "$TUI" | grep -Fq 'AURADE_PROGRESS_TICK' ||
  { echo 'the polling read is no longer called from the progress loop' >&2; exit 1; }

# --- the graphical installer ------------------------------------------------
#
# Its timers drive animation, the snake, the tip rotation and the progress
# poll. None of them may dismiss a dialog or advance a page, which is the same
# rule stated in the one way it could be broken there.
APP="$ROOT/installer/lib/aurade_gui/app.py"
while IFS= read -r line; do
  [[ -n $line ]] || continue
  case $line in
    # The done screen's settle, the aurora, the snake and the tip rotation:
    # drawing, all four.
    *SETTLE_DELAY_MS*|*_aurora_source*|*_snake_source*|*_tip_source*) ;;
    # The gap between the rings of a sound.
    *'index * 150'*) ;;
    # Asking the engine how far along it is, on the one screen with no
    # decision on it to expire.
    *_progress_source*) ;;
    *)
      echo "an unaccounted graphical timer, which may be a screen that expires: $line" >&2
      exit 1 ;;
  esac
done < <(grep -n 'GLib.timeout_add' "$APP" || true)
# All six are still there, so the list above cannot be passing because the
# timers it accounts for have gone.
timers=$(grep -c 'GLib.timeout_add' "$APP")
[[ $timers -eq 6 ]] ||
  { echo "the graphical installer has $timers timers, not the 6 accounted for" >&2
    grep -n 'GLib.timeout_add' "$APP" >&2; exit 1; }

# And nothing anywhere closes a dialog or moves a page on a clock, which is the
# one way this rule could be broken there.
refute grep -Eq 'timeout_add[^)]*\.(close|dismiss|response)\b' "$APP"
refute grep -Eq 'timeout_add[^)]*(jump_to_page|advance|set_visible_child)' "$APP"

echo 'no timeouts test: PASS'
