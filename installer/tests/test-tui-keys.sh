#!/usr/bin/env bash
# The keyboard, and the frame it draws into, both of which change under you.
#
# Three things live here because they share one failure shape: something the
# terminal does that the installer did not notice. A function key that arrives
# as an escape sequence nobody decoded. A window that changed size while a
# screen was waiting for a key. A question mark typed into a passphrase and
# taken as a request for help.
#
# None of the three announces itself. All three are the kind of defect that is
# found by somebody using the product, months later, and reported as "it went
# back a screen for no reason".
set -Eeuo pipefail
trap 'case $- in *e*) printf "%s: line %s gave up: %s\n" "${0##*/}" "$LINENO" "$BASH_COMMAND" >&2 ;; esac' ERR

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
LIB=$ROOT/installer/lib/aurade-tui.sh
TUI=$ROOT/installer/bin/aurade-installer-tui
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
failures=0
fail() { printf 'test-tui-keys: %s\n' "$*" >&2; failures=$(( failures + 1 )); }

export AURADE_TUI_COLUMNS=68 AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii

# --- function keys, through the path that actually reads a terminal ---------
#
# There were two key mappings in this file: one inside `tui_read_key`, which
# every screen goes through, and one inside `tui_decode_key`, which was the
# tested one. They had drifted, and the tested one was not the one being used.
# F1 opens the accessibility settings, and at a real terminal it went back a
# screen instead, because `\033OP` was read two bytes at a time and folded into
# `esc` by a catch-all.
#
# So this drives the real reader with the real bytes rather than the decoder
# with a string.
reads_as() {
  local bytes=$1 want=$2 got
  got=$(printf '%b' "$bytes" | env AURADE_TUI_COLUMNS=68 bash -c '
    . "$0"
    tui_read_key' "$LIB" 2>/dev/null || true)
  [[ $got == "$want" ]] ||
    fail "the sequence for '$want' was read as '$got'"
}

# xterm and most emulators, the linux virtual console, and the numbered form.
reads_as '\033OP'    f1
reads_as '\033[[A'   f1
reads_as '\033[11~'  f1
reads_as '\033OQ'    f2
reads_as '\033[12~'  f2
reads_as '\033[A'    up
reads_as '\033[B'    down
reads_as '\033[C'    right
reads_as '\033[D'    left
# A bare escape is still a bare escape, which is the key that goes back.
reads_as '\033'      esc
reads_as 'k'         k
reads_as ' '         space

# An escape sequence nothing recognises must not become a keystroke. Folding
# it into `esc` is deliberate: going back is recoverable, and typing an `R`
# into a passphrase because the terminal reported its cursor position is not.
reads_as '\033[6;1R' esc

# --- a paste is text, not a run of keystrokes -------------------------------
#
# Typing ERASE:/dev/nvme0n1 by hand is a real load and somebody should be able
# to paste it. The safety half is the less obvious one and is why bracketed
# paste is turned on rather than left alone: without it a terminal delivers a
# paste as ordinary keystrokes, so a copied line that ends in a newline types
# the token and then presses enter, and the confirmation screen submits
# itself. With it, the newline is part of the text and is dropped.
#
# That makes the gate harder to pass by accident than it was, which is the
# only direction that screen is allowed to move.
pasted=$(printf '%b' '\033[200~ERASE:/dev/sda\n\033[201~' | bash -c '
  . "$0"
  tui_read_key' "$LIB" 2>/dev/null || true)
[[ $pasted == 'paste:ERASE:/dev/sda' ]] ||
  fail "a pasted token came back as '$pasted'"

# A paste carrying a newline in the middle of it does not become two answers
# and does not become an enter either.
pasted=$(printf '%b' '\033[200~one\ntwo\033[201~' | bash -c '
  . "$0"
  tui_read_key' "$LIB" 2>/dev/null || true)
[[ $pasted == 'paste:onetwo' ]] ||
  fail "a paste containing a newline came back as '$pasted'"

# And a tab, which is what a copy out of a table brings with it.
pasted=$(printf '%b' '\033[200~a\tb\033[201~' | bash -c '
  . "$0"
  tui_read_key' "$LIB" 2>/dev/null || true)
[[ $pasted == 'paste:ab' ]] ||
  fail "a paste containing a tab came back as '$pasted'"

# --- the frame, measured again -----------------------------------------------
#
# Resizing a terminal mid install used to leave the frame in pieces until the
# next screen, because the width was measured once when the library was loaded
# and never again. This is the remeasure that the resize triggers.
measured() {
  env -u AURADE_TUI_COLUMNS -u AURADE_TUI_WIDTH COLUMNS="$1" bash -c '
    . "$0"
    # No terminal here, so `tput cols` fails and the measure falls back to
    # COLUMNS, which is exactly the path a resize takes.
    tui_measure
    printf "%s %s %s\n" "$AURADE_TUI_WIDTH" "$AURADE_TUI_MARGIN" "$AURADE_TUI_TWOPANE"
  ' "$LIB" 2>/dev/null
}

got=$(measured 80)
[[ $got == '68 6 0' ]] || fail "80 columns measured as '$got', expected '68 6 0'"
got=$(measured 120)
[[ $got == '100 10 1' ]] || fail "120 columns measured as '$got', expected '100 10 1'"
# Narrower than the floor, the frame gives up the floor rather than the
# terminal. A 68 column frame drawn into 60 columns wraps every single row and
# produces a staircase; a 60 column one merely truncates what does not fit,
# and truncation is legible in a way a staircase is not.
got=$(measured 60)
[[ $got == '60 0 0' ]] || fail "60 columns measured as '$got', expected '60 0 0'"

# A pinned width survives a remeasure. Every test in this suite pins one, and a
# resize that overrode it would make them all measure the terminal they happen
# to be running in.
got=$(env AURADE_TUI_WIDTH=88 COLUMNS=200 bash -c '
  . "$0"
  tui_measure
  printf "%s\n" "$AURADE_TUI_WIDTH"' "$LIB" 2>/dev/null)
[[ $got == 88 ]] || fail "a pinned width of 88 became '$got' after a remeasure"

# --- the help key, and the one place it must not fire ------------------------
#
# `?` explains the screen. A passphrase is allowed to contain a question mark,
# and a help screen that ate one would produce a disk that does not open, which
# is the worst single outcome this program has. So the field turns it off.
help=$(env AURADE_TUI_HEIGHT=30 "$TUI" --render explain 2>/dev/null)
grep -Fq 'F1 opens the accessibility settings' <<<"$help" ||
  fail 'the explanation screen does not mention the accessibility key'
grep -Fq 'time limit' <<<"$help" ||
  fail 'the explanation screen does not say there is no time limit'

# The suppression itself is checked in the flow test, where a passphrase with a
# question mark in it is typed and read back.

(( failures == 0 )) || exit 1
echo 'installer TUI key test: PASS (function keys decoded, frame remeasured, help key scoped)'
