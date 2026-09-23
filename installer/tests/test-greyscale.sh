#!/usr/bin/env bash
# Nothing may say something in colour alone.
#
# The rule is easy to agree with and easy to break, because breaking it does
# not look like breaking anything: somebody adds a red row for a failure, it
# reads perfectly on their screen, and it is invisible to the roughly one man
# in twelve with red-green colour blindness and to anybody on a monochrome
# console or a projector.
#
# So this takes the colour away and checks the screens still say what they
# said. Not by looking at pixels: the text installer's states are carried by
# marks and words, so removing the colour and asserting the marks survive is
# both cheaper and stricter than sampling a rendering.
#
# The graphical half is checked in `gui_theme_test.py`, which holds every
# foreground and background pair to a contrast floor. Contrast is what survives
# greyscale, so a palette that passes there passes here by construction. What
# it cannot check is whether a *state* is distinguishable, which is this.
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
fail() { printf 'test-greyscale: %s\n' "$*" >&2; failures=$(( failures + 1 )); }

# Four stages in four different states, so every mark the progress screen can
# draw is on the screen at once.
cat >"$TMP/journal.jsonl" <<'EOF'
{"v":1,"install_id":"6f2a1c9e","seq":1,"attempt":1,"stage":"preflight","status":"ok","elapsed_ms":3200,"reversible":true,"idempotent":true,"target":{"path":"/dev/nvme0n1"}}
{"v":1,"install_id":"6f2a1c9e","seq":2,"attempt":1,"stage":"package-check","status":"ok","message":"workspace","reversible":true,"idempotent":true,"target":{"path":"/dev/nvme0n1"}}
{"v":1,"install_id":"6f2a1c9e","seq":3,"attempt":1,"stage":"acquire","status":"running","pct":41,"message":"312/1041 packages","reversible":true,"idempotent":true,"target":{"path":"/dev/nvme0n1"}}
EOF

grey() {
  # `AURADE_TUI_COLOR=none` is the greyscale: no escapes at all, so whatever
  # is left on the screen is carrying its meaning without them.
  env AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii AURADE_TUI_HEIGHT=40 \
    AURADE_TIP_RARITY=0 "$TUI" --render "$1" --journal "$TMP/journal.jsonl" 2>/dev/null
}

# --- the stage list, which is where states live ----------------------------
grey progress >"$TMP/progress"

# Done, running and waiting are three different states and have to look like
# three different things with the colour gone. The marks are ' + ', ' > ' and
# three spaces, so the check is that the first two are present: without them
# the list is eleven identical lines.
grep -q '^|  *+ ' "$TMP/progress" ||
  fail 'a finished stage has no mark, so with no colour it reads as not started'
grep -q '^|  *> ' "$TMP/progress" ||
  fail 'the running stage has no mark, so with no colour it reads as not started'

# The bar is drawn from two different characters rather than two colours.
grep -q '\[#*-*\]' "$TMP/progress" ||
  fail 'the progress bar does not distinguish filled from empty without colour'

# --- the failure screen ----------------------------------------------------
cat >"$TMP/failed.jsonl" <<'EOF'
{"v":1,"install_id":"6f2a1c9e","seq":1,"attempt":1,"stage":"preflight","status":"ok","elapsed_ms":3200,"reversible":true,"idempotent":true,"target":{"path":"/dev/nvme0n1"}}
{"v":1,"install_id":"6f2a1c9e","seq":2,"attempt":1,"stage":"bootloader","status":"failed","exit":1,"cause":"storage_error","message":"bootctl could not write to the EFI system partition","resumable":true,"reversible":false,"idempotent":true,"remediation":["export","log","shell","reboot"],"target":{"path":"/dev/nvme0n1"}}
EOF
env AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii AURADE_TUI_HEIGHT=40 \
  "$TUI" --render failure --journal "$TMP/failed.jsonl" 2>/dev/null >"$TMP/failure"
# A failure is a failure in words, not in red. This is the sentence, and the
# cause explanation under it, both of which survive having no colour at all.
grep -Fq 'Making it bootable did not finish' "$TMP/failure" ||
  fail 'the failure screen does not name the failed stage in words'
grep -Fq 'A filesystem could not be created or mounted.' "$TMP/failure" ||
  fail 'the failure screen does not explain the cause in words'

# --- notes carry a mark, not just a colour ---------------------------------
#
# `tui_note` takes a marker precisely so a caution is a caution without one.
# The disk screen's removable warning is the one somebody most needs to see.
grey disk 2>/dev/null >"$TMP/disk" || true
if [[ -s $TMP/disk ]] && grep -Fq 'removable' "$TMP/disk"; then
  grep -q '^|  *! ' "$TMP/disk" ||
    fail 'the removable-disk caution has no mark, so with no colour it is prose'
fi

# --- the erase gate ---------------------------------------------------------
#
# The one screen that must not look like the others. Its distinction cannot be
# the red pane alone, because the red pane is the first thing to go.
env AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii AURADE_TUI_HEIGHT=40 \
  "$TUI" --render gate 2>/dev/null >"$TMP/gate"
grep -Fq 'completely.' "$TMP/gate" ||
  fail 'the erase gate does not say what it does in words'
grep -Fq 'Nothing after it can.' "$TMP/gate" ||
  fail 'the erase gate does not state the boundary in words'

(( failures == 0 )) || exit 1
echo 'installer greyscale test: PASS (states survive without colour)'
