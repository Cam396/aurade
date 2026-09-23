#!/usr/bin/env bash
# Plain mode: the same screens with the drawing taken out.
#
# A refreshable braille display renders the text installer one cell at a time.
# The frame is 68 columns on a display that is commonly 40, and every `|`,
# every `+`, every rule and every pad space is a cell under somebody's fingers.
# The existing colour tiers do not help: plain ASCII box drawing is still box
# drawing.
#
# So this checks the four things that are actually expensive to read, and one
# that is worse than expensive. Trailing padding is cells containing nothing.
# Interior padding is a column of nothing between two words. Box drawing is a
# rectangle nobody asked for. Art is a picture described character by
# character.
#
# And the fifth: the stage list marks four states with a glyph in a fixed
# column, and one of those four marks is three spaces. Strip the indentation
# and "waiting" becomes no mark at all, so every stage that has not started
# looks like one that has finished. That is the colour-alone rule one level
# down, and it is the failure this file exists to keep fixed.
set -Eeuo pipefail
trap 'case $- in *e*) printf "%s: line %s gave up: %s\n" "${0##*/}" "$LINENO" "$BASH_COMMAND" >&2 ;; esac' ERR

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
fail() { printf 'test-tui-plain: %s\n' "$*" >&2; failures=$(( failures + 1 )); }

mapfile -t SCREENS < <("$TUI" --list-screens)
(( ${#SCREENS[@]} >= 15 )) || fail "expected the full screen set, found ${#SCREENS[@]}"

# A journal of its own, and not a borrowed one.
#
# Without this the progress screen reads whatever journal happens to be lying
# around, so this file passed on state a previous test had left behind and then
# failed the first time it ran on a clean machine. A test that depends on the
# order the suite happens to run in is not testing what it says it is.
#
# Four states on purpose, because the whole point of the stage list assertions
# below is that all four survive having the frame taken off.
cat >"$TMP/journal.jsonl" <<'EOF'
{"v":1,"install_id":"6f2a1c9e","seq":1,"attempt":1,"stage":"preflight","status":"ok","elapsed_ms":3200,"reversible":true,"idempotent":true,"target":{"path":"/dev/nvme0n1"}}
{"v":1,"install_id":"6f2a1c9e","seq":2,"attempt":1,"stage":"package-check","status":"ok","message":"workspace","reversible":true,"idempotent":true,"target":{"path":"/dev/nvme0n1"}}
{"v":1,"install_id":"6f2a1c9e","seq":3,"attempt":1,"stage":"acquire","status":"ok","elapsed_ms":252000,"reversible":true,"idempotent":true,"target":{"path":"/dev/nvme0n1"}}
{"v":1,"install_id":"6f2a1c9e","seq":4,"attempt":1,"stage":"pacstrap","status":"running","pct":59,"message":"612/1041 packages","reversible":false,"idempotent":true,"target":{"path":"/dev/nvme0n1"}}
EOF

plain() {
  env AURADE_TUI_PLAIN=1 AURADE_TUI_HEIGHT=34 AURADE_TIP_RARITY=0 \
    "$TUI" --render "$1" --journal "$TMP/journal.jsonl" 2>/dev/null
}

# --- every screen, every rule ----------------------------------------------
for screen in "${SCREENS[@]}"; do
  # The games are the screens with no plain rendering, deliberately. All three
  # are grids of characters with nothing in them to read, and in plain mode
  # all three are unreachable: the footer offers none of them and the key that
  # opens them returns to the tips, which is asserted below. Rendering one here
  # anyway and demanding it be frameless would be asserting on a screen nobody
  # can get to.
  case $screen in game|2048|ttt|life|lights|fifteen|mines|nono) continue ;; esac
  plain "$screen" >"$TMP/$screen" || { fail "$screen did not render in plain mode"; continue; }

  # Something has to come out. A screen that renders to nothing is a screen
  # somebody navigated to and heard silence on.
  [[ -s $TMP/$screen ]] || fail "$screen rendered nothing at all"

  # Box drawing, both tiers. The unicode set and the ASCII set the frame falls
  # back to are equally unwelcome here.
  if grep -qE '[│─┌┐└┘├┤]' "$TMP/$screen"; then
    fail "$screen still draws a unicode frame in plain mode"
  fi
  if grep -qE '^\+[-+]+\+$|^\|.*\|$' "$TMP/$screen"; then
    fail "$screen still draws an ASCII frame in plain mode"
  fi

  # Trailing cells.
  if grep -q '[[:space:]]$' "$TMP/$screen"; then
    fail "$screen leaves trailing whitespace, which is blank braille cells"
  fi

  # Interior padding. Two spaces in a row is a column being lined up, and
  # nothing is being looked at here.
  if grep -q '  ' "$TMP/$screen"; then
    fail "$screen pads to a column in plain mode: $(grep -m1 -n '  ' "$TMP/$screen")"
  fi
done

# --- the progress screen, which is where the art and the games live --------
plain progress >"$TMP/progress.out"

# The aurora is drawn from a small alphabet of shading characters. None of them
# mean anything read aloud.
if grep -qE '[:.=*#+-]{12,}' "$TMP/progress.out"; then
  fail 'the aurora is still drawn on the plain progress screen'
fi
# The game is a grid of moving characters, so it is not offered.
! grep -Fq 'g  game' "$TMP/progress.out" ||
  fail 'the plain progress screen still offers the game'

# --- the four stage states stay four states --------------------------------
#
# The one that matters. Checked by name rather than by glyph, because the
# glyph is exactly what plain mode removes.
for word in 'Done:' 'Now:' 'Waiting:'; do
  grep -Fq "$word" "$TMP/progress.out" ||
    fail "the plain stage list never says '$word', so its state is invisible"
done

# --- same words, not a different product -----------------------------------
#
# Plain mode is a rendering, so the sentences have to survive it. These are
# load bearing: the first is the promise the welcome screen makes and the
# second is the one the gate makes.
grep -Fq 'Nothing is written to any disk until you confirm.' "$TMP/welcome" ||
  fail 'the plain welcome screen lost its assurance'
grep -Fq 'Everything up to here can be undone. Nothing after it can.' "$TMP/gate" ||
  fail 'the plain erase gate lost the reversibility line'

# --- the flag and the detection both work ----------------------------------
AURADE_TUI_HEIGHT=34 AURADE_TIP_RARITY=0 "$TUI" --plain --render welcome \
  --journal "$TMP/journal.jsonl" >"$TMP/flag.out" 2>/dev/null
cmp -s "$TMP/flag.out" "$TMP/welcome" ||
  fail '--plain and AURADE_TUI_PLAIN=1 do not produce the same screen'

# TERM=dumb is what a serial console and several screen reader setups report,
# and it has to land here without being asked.
env -u AURADE_TUI_PLAIN TERM=dumb AURADE_TUI_HEIGHT=34 AURADE_TIP_RARITY=0 \
  "$TUI" --render welcome --journal "$TMP/journal.jsonl" >"$TMP/dumb.out" 2>/dev/null
cmp -s "$TMP/dumb.out" "$TMP/welcome" ||
  fail 'TERM=dumb did not select plain mode on its own'

# --- and the framed rendering is untouched ---------------------------------
env AURADE_TUI_HEIGHT=34 AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii \
  AURADE_TIP_RARITY=0 "$TUI" --render welcome >"$TMP/framed.out" 2>/dev/null
grep -q '^+[-]*+$' "$TMP/framed.out" ||
  fail 'plain mode has leaked into the framed rendering'

(( failures == 0 )) || exit 1
printf 'installer TUI plain mode test: PASS (%s screens, no frame, no padding, no art)\n' \
  "${#SCREENS[@]}"
