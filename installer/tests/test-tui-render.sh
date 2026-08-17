#!/usr/bin/env bash
# Alignment, degradation and determinism for every installer screen.
#
# The alignment check is here because this is the defect class that keeps
# recurring in framed terminal UIs and that reading the source will not catch:
# a body line is measured with its escape sequences included, or a glyph turns
# out to be double-width, and the right-hand frame lands one column off. The
# only reliable check is to render the screen and measure the result, which is
# what this does - in every colour and frame tier, for every screen.
#
# The cross-tier check is the sharper one. Strip the escape sequences from a
# coloured render and it must be byte-identical to the uncoloured render of the
# same screen. If colour can change layout at all, that comparison fails.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)

# The frame grows with the terminal, so the width is pinned here the way the
# height already is. Without it a screen rendered on a build machine with a
# wide terminal and the same screen rendered in CI are different screens, and
# every column measurement below is measuring the margin.
export AURADE_TUI_COLUMNS=68

TUI="$ROOT/installer/bin/aurade-installer-tui"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fail() { echo "test-tui-render: $*" >&2; exit 1; }

install -d "$TMP/zoneinfo/America" "$TMP/locales" "$TMP/keymaps/i386/qwerty" "$TMP/dri"
: >"$TMP/zoneinfo/UTC"; : >"$TMP/zoneinfo/America/Chicago"
# Several candidates, deliberately including ones that sort before each
# default: with a single-entry list, "opens on the default" would pass even if
# the cursor never moved off zero.
for _locale in en_US en_GB de_DE fr_FR aa_DJ; do : >"$TMP/locales/$_locale"; done
for _keymap in us uk de fr colemak dvorak; do
  : >"$TMP/keymaps/i386/qwerty/$_keymap.map.gz"
done
printf '%s\n' '2026/07/12' >"$TMP/snapshot"
printf 'MemAvailable:   16000000 kB\n' >"$TMP/meminfo"
printf '%s\n' \
  '/dev/nvme0n1|476.9G|Samsung SSD 980 PRO 512GB|nvme|S6B2NS0T900123X' \
  '/dev/sda|931.5G|WDC WD10EZEX-08WN4A0|sata|WD-WCC6Y4KP1234' \
  '/dev/sdb|28.7G|SanDisk Ultra|usb|4C530001121205117454' >"$TMP/disks"

cat >"$TMP/journal.jsonl" <<'EOF'
{"v":1,"install_id":"6f2a1c9e","seq":1,"attempt":1,"stage":"preflight","status":"ok","elapsed_ms":3200,"reversible":true,"idempotent":true,"target":{"path":"/dev/nvme0n1"}}
{"v":1,"install_id":"6f2a1c9e","seq":2,"attempt":1,"stage":"acquire","status":"ok","elapsed_ms":252000,"reversible":true,"idempotent":true,"target":{"path":"/dev/nvme0n1"}}
{"v":1,"install_id":"6f2a1c9e","seq":3,"attempt":1,"stage":"partition","status":"ok","elapsed_ms":2100,"reversible":false,"idempotent":true,"target":{"path":"/dev/nvme0n1"}}
{"v":1,"install_id":"6f2a1c9e","seq":4,"attempt":1,"stage":"pacstrap","status":"running","pct":59,"message":"612/1041 packages","reversible":false,"idempotent":true,"target":{"path":"/dev/nvme0n1"}}
{"v":1,"install_id":"6f2a1c9e","seq":5,"attempt":1,"stage":"bootloader","status":"failed","exit":1,"cause":"storage_error","message":"bootctl could not write to the EFI system partition","resumable":true,"reversible":false,"idempotent":true,"remediation":["retry","export","log","shell","reboot"],"target":{"path":"/dev/nvme0n1"}}
EOF

export AURADE_ZONEINFO_DIR="$TMP/zoneinfo" AURADE_LOCALE_DIR="$TMP/locales"
export AURADE_KEYMAP_DIR="$TMP/keymaps" AURADE_SNAPSHOT_FILE="$TMP/snapshot"
export AURADE_DISK_TABLE="$TMP/disks" AURADE_PROBE_MEMINFO="$TMP/meminfo"
export AURADE_PROBE_DRI_DIR="$TMP/dri"

# The progress screen spends whatever rows the console has, so the height is
# pinned here. Unpinned, the same screen renders one way on a build machine
# with a tall terminal and another way in CI, and every layout assertion below
# becomes a coin toss.
AURADE_TUI_HEIGHT=34
export AURADE_TUI_HEIGHT

# Long copy is wrapped to the frame, so grepping a whole sentence in the raw
# render is really a test of where the wrap landed. Flatten first.
flatten() {
  sed 's/^ *[|+]//; s/[|+] *$//' "$1" | tr '\n' ' ' | tr -s ' '
}

render() {
  local screen=$1 color=$2 frame=$3
  env AURADE_TUI_COLOR="$color" AURADE_TUI_FRAME="$frame" \
    "$TUI" --render "$screen" --journal "$TMP/journal.jsonl"
}

mapfile -t SCREENS < <("$TUI" --list-screens)
(( ${#SCREENS[@]} >= 15 )) || fail "expected the full screen set, found ${#SCREENS[@]}"

measure() {
  python3 - "$1" <<'PY'
import sys, unicodedata
path = sys.argv[1]
bad = []
for n, line in enumerate(open(path, encoding='utf-8').read().split('\n'), 1):
    if line == '':
        continue
    width = sum(2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in line)
    if width != 68:
        bad.append(f'  line {n}: {width} columns: {line[:52]!r}')
if bad:
    print('\n'.join(bad))
    sys.exit(1)
PY
}

strip_ansi() { sed -e 's/\x1b\[[0-9;]*m//g' "$1"; }

# --- every screen, every tier, exactly 68 columns ---------------------------
for screen in "${SCREENS[@]}"; do
  for color in none 16 256; do
    for frame in ascii unicode; do
      render "$screen" "$color" "$frame" >"$TMP/raw" 2>"$TMP/err" ||
        fail "$screen did not render in ${color}/${frame}: $(cat "$TMP/err")"
      [[ -s $TMP/raw ]] || fail "$screen rendered nothing in ${color}/${frame}"
      strip_ansi "$TMP/raw" >"$TMP/plain"
      measure "$TMP/plain" ||
        fail "$screen is misaligned in ${color}/${frame}"
    done
  done
done

# --- colour never changes layout -------------------------------------------
for screen in "${SCREENS[@]}"; do
  for frame in ascii unicode; do
    render "$screen" none "$frame" >"$TMP/none"
    for color in 16 256; do
      render "$screen" "$color" "$frame" >"$TMP/colored"
      strip_ansi "$TMP/colored" >"$TMP/stripped"
      cmp -s "$TMP/none" "$TMP/stripped" ||
        fail "$screen differs between none and $color once colour is stripped ($frame frame)"
    done
  done
done

# --- the bottom tier emits no escape sequences at all ------------------------
# This is the serial console and screen reader path, so it has to be plain text
# rather than merely uncoloured.
for screen in "${SCREENS[@]}"; do
  render "$screen" none ascii >"$TMP/raw"
  ! grep -q $'\033' "$TMP/raw" || fail "$screen emitted an escape sequence in the no-colour tier"
done

# --- NO_COLOR and TERM=dumb are not the same request ------------------------
#
# They used to be, and this asserted they produced identical text. They do not
# mean the same thing and now do not behave the same way.
#
# NO_COLOR is somebody saying "not in colour". They are looking at the screen,
# so the frame is still doing its job and only the escapes go.
#
# TERM=dumb is a terminal saying it has no capabilities, which is what a serial
# console and several screen reader setups report. Nobody sets it because they
# dislike colour. It now selects plain mode, where the frame goes too, because
# a console reader speaks the frame out loud and a braille display renders it
# one cell at a time.
env -u AURADE_TUI_COLOR -u AURADE_TUI_FRAME -u AURADE_TUI_PLAIN \
  NO_COLOR=1 TERM=xterm-256color \
  "$TUI" --render welcome >"$TMP/nocolor"
! grep -q $'\033' "$TMP/nocolor" || fail 'NO_COLOR did not disable colour'
grep -q '^+[-]*+$' "$TMP/nocolor" ||
  fail 'NO_COLOR dropped the frame, which is not what it asks for'

env -u AURADE_TUI_COLOR -u AURADE_TUI_FRAME -u AURADE_TUI_PLAIN TERM=dumb \
  "$TUI" --render welcome >"$TMP/dumb"
! grep -q $'\033' "$TMP/dumb" || fail 'TERM=dumb did not disable colour'
! grep -q '^+[-]*+$' "$TMP/dumb" ||
  fail 'TERM=dumb kept the frame instead of selecting plain mode'
! cmp -s "$TMP/nocolor" "$TMP/dumb" ||
  fail 'NO_COLOR and TERM=dumb produced identical text, so one of them is wrong'

# --- the interior is one column per character in every tier -----------------
# The rule people remember is "the body is ASCII", and the rule that actually
# matters is that every character in it occupies exactly one column. Check
# marks, arrows and bullets are ambiguous width, and a double-width glyph in
# the body is exactly how the frame breaks on the terminals least able to show
# it.
#
# Two blocks are as reliable as ASCII on that measure and both are used here:
# box drawing for the frame, and the braille patterns the progress bar fills
# itself with. Both are Neutral width, which every terminal renders narrow.
# Whether the font has the glyph at all is a different question, and it is why
# the braille bar is off on the Linux console, which is checked below.
for screen in "${SCREENS[@]}"; do
  # The help screen is the one deliberate exception, and it is deliberate
  # rather than overlooked. It draws a QR code out of half blocks, which are
  # ambiguous width where the braille above is neutral, so this rule is
  # genuinely broken there and the screen accepts the consequence: a terminal
  # in a CJK locale may draw the code double and tear that one frame, and the
  # addresses printed under it say the same thing regardless. Everything about
  # that square is checked by test-qr.sh instead, including that it is absent
  # from the tiers where it would not be safe.
  [[ $screen != help ]] || continue
  for frame in ascii unicode; do
    render "$screen" 256 "$frame" >"$TMP/raw"
    strip_ansi "$TMP/raw" >"$TMP/plain"
    python3 - "$TMP/plain" "$screen" <<'PY' || exit 1
import sys
path, screen = sys.argv[1], sys.argv[2]
# Content rows only. The horizontal rules are frame all the way across, and
# the frame is allowed to be Unicode; the body is not.
for n, line in enumerate(open(path, encoding='utf-8').read().split('\n'), 1):
    if line == '' or line[0] not in '|│':
        continue
    for c in line[1:-1]:
        if 0x2800 <= ord(c) <= 0x28ff:
            continue
        if not (0x20 <= ord(c) <= 0x7e):
            print(f'test-tui-render: {screen} line {n} has a non-ASCII interior '
                  f'character {c!r} (U+{ord(c):04X})', file=sys.stderr)
            sys.exit(1)
PY
  done
done

# --- the ascii frame really is ascii, and the unicode frame really is not ---
render welcome none ascii >"$TMP/ascii"
! grep -qP '[^\x00-\x7f]' "$TMP/ascii" || fail 'the ascii frame contains non-ASCII bytes'
render welcome none unicode >"$TMP/unicode"
grep -q '┌' "$TMP/unicode" || fail 'the unicode frame is missing its box drawing'

# --- rendering is deterministic --------------------------------------------
for screen in "${SCREENS[@]}"; do
  render "$screen" 256 unicode >"$TMP/first"
  render "$screen" 256 unicode >"$TMP/second"
  cmp -s "$TMP/first" "$TMP/second" || fail "$screen does not render deterministically"
done

# --- screens say the things they exist to say -------------------------------
render gate none ascii >"$TMP/gate"
grep -Fq 'ERASE:/dev/nvme0n1' "$TMP/gate" || fail 'the erase gate does not show the confirmation token'
grep -Fq 'S6B2NS0T900123X' "$TMP/gate" || fail 'the erase gate does not show the disk serial'
grep -Fq 'Nothing after it' "$TMP/gate" || fail 'the erase gate does not state the boundary'

render question-target none ascii >"$TMP/disk"
grep -Fq '/dev/sdb' "$TMP/disk" || fail 'the disk screen omits a disk'
grep -Fq 'removable' "$TMP/disk" || fail 'the disk screen does not warn about removable media'

render progress none ascii >"$TMP/progress"
grep -Fq '612/1041 packages' "$TMP/progress" || fail 'progress does not render journal detail'
grep -Fq 'cannot be interrupted safely' "$TMP/progress" ||
  fail 'progress does not state that the irreversible region cannot be cancelled'
# Stages the engine never emits must not sit on screen as permanently pending.
! grep -Fq 'Connecting' "$TMP/progress" ||
  fail 'progress lists a stage the engine never emits'
! grep -Fq 'Checking the downloads' "$TMP/progress" ||
  fail 'progress lists a stage the engine never emits'

render failure none ascii >"$TMP/failure"
grep -Fq 'Making it bootable' "$TMP/failure" || fail 'failure does not name the failed stage'
# The cause codes in these fixtures are the ones `aurade-install` actually
# writes. They used to be invented ones, which is how seven of the engine's
# nine real codes reached the screen as raw tokens with the suite green.
grep -Fq 'A filesystem could not be created or mounted.' "$TMP/failure" ||
  fail 'failure does not explain the cause'
! grep -Fq 'storage_error' "$TMP/failure" ||
  fail 'failure printed the raw cause code'
flatten "$TMP/failure" | grep -Fq 'Check the disk for faults, then start again.' ||
  fail 'failure does not name one next step'
grep -Fq 'Save a report' "$TMP/failure" || fail 'failure does not offer a report'
grep -Fq 'Open a terminal' "$TMP/failure" || fail 'failure does not offer a terminal'
grep -Fq 'stage 9 of 11' "$TMP/failure" || fail 'failure does not say where in the sequence it stopped'
# The engine cannot be told to start at a stage, so a retry would re-run
# wipefs. The screen must not offer one, and must say what starting over costs.
! grep -Fq 'Try ' "$TMP/failure" ||
  fail 'the failure screen offers a retry the engine cannot honour'
flatten "$TMP/failure" | grep -Fq 'no way to carry on from where this stopped' ||
  fail 'the failure screen does not admit that it cannot resume'
flatten "$TMP/failure" | grep -Fq 'Starting again erases the disk' ||
  fail 'the failure screen does not say what starting over costs after the disk was changed'

# A failure before the erase gate has a different, non-destructive message.
cat >"$TMP/reversible.jsonl" <<'EOF'
{"v":1,"stage":"acquire","status":"failed","exit":1,"cause":"network_error","message":"the pinned snapshot could not be reached","resumable":true,"target":{"path":"/dev/nvme0n1"}}
EOF
env AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii "$TUI" --render failure \
  --journal "$TMP/reversible.jsonl" >"$TMP/reversible.out"
flatten "$TMP/reversible.out" | grep -Fq 'Nothing has been changed. A package could not be downloaded.' ||
  fail 'a pre-gate failure did not say the disk is untouched'
flatten "$TMP/reversible.out" | grep -Fq 'Check the network connection, then start again.' ||
  fail 'a pre-gate failure did not name one next step'
# Before the boundary there is no cost to starting again, so the warning about
# what starting again destroys must not appear. It says the opposite of the
# line above it and turns an untouched disk into a scare.
! flatten "$TMP/reversible.out" | grep -Fq 'Starting again erases the disk' ||
  fail 'a pre-gate failure warned about a destructive restart'
# ...and after the boundary it must.
flatten "$TMP/failure" | grep -Fq 'Starting again erases the disk' ||
  fail 'a post-gate failure did not say what starting again costs'
! flatten "$TMP/reversible.out" | grep -Fq 'Starting again erases the disk' ||
  fail 'a pre-gate failure warned about erasing a disk that was never touched'

render cancelled none ascii >"$TMP/cancelled"
grep -Fq 'Nothing was changed' "$TMP/cancelled" || fail 'the cancelled screen does not say so'

# --- defaults are visible, not applied invisibly on enter -------------------
# Every question type accepts its default when the user presses enter, so the
# screen has to show what that default is. An empty-looking field that quietly
# means "aurade" is a default nobody can review before confirming it.
render question-hostname none ascii >"$TMP/hostname.out"
grep -Eq '^\|  > aurade_' "$TMP/hostname.out" ||
  fail 'the hostname field does not show its default'
render question-snapshot none ascii >"$TMP/snapshot.out"
grep -Fq '2026/07/12' "$TMP/snapshot.out" ||
  fail 'the snapshot field does not show the image default'
render question-keymap none ascii >"$TMP/keymap.out"
grep -Eq '^\|  > us +\|' "$TMP/keymap.out" ||
  fail 'the keyboard list does not open on the default layout'
render question-encrypt none ascii >"$TMP/encrypt.out"
grep -Eq '^\|  > Yes,' "$TMP/encrypt.out" ||
  fail 'the encryption question does not open on its default answer'
# A question the user must answer has no default to show.
render question-username none ascii >"$TMP/username.out"
grep -Eq '^\|  > _ +\|' "$TMP/username.out" ||
  fail 'the username field was pre-filled with something'

# --- rendered text is never glob-expanded ----------------------------------
# Journal messages, device paths and failure details can all contain * or ?,
# and an unquoted `for word in $text` replaces them with matching filenames.
# The first time this happened, an export error rendered as a listing of the
# repository root.
cat >"$TMP/glob.jsonl" <<'EOF'
{"v":1,"stage":"configure","status":"failed","exit":1,"cause":"unexpected_exit","message":"no match for /dev/sd* or ?? in the table","resumable":true,"target":{"path":"/dev/nvme0n1"}}
EOF
env AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii "$TUI" --render failure \
  --journal "$TMP/glob.jsonl" >"$TMP/glob.out"
grep -Fq '/dev/sd*' "$TMP/glob.out" ||
  fail 'a message containing a glob was not rendered literally'
grep -Fq '??' "$TMP/glob.out" ||
  fail 'a message containing ?? was not rendered literally'
# Rendered again from a directory holding one uniquely named file: if any glob
# is expanded, that name is what it expands to. Matching on ordinary words
# would not distinguish expansion from prose that happens to say "installer".
install -d "$TMP/globdir"
: >"$TMP/globdir/GLOBCANARY-must-not-appear"
( cd "$TMP/globdir" && env AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii \
    "$TUI" --render failure --journal "$TMP/glob.jsonl" ) >"$TMP/glob-cwd.out"
! grep -Fq GLOBCANARY "$TMP/glob-cwd.out" ||
  fail 'rendering expanded a glob against the working directory'
cmp -s "$TMP/glob.out" "$TMP/glob-cwd.out" ||
  fail 'the same journal rendered differently from a different directory'
# And the frame still holds.
measure "$TMP/glob.out" || fail 'a glob-bearing message broke the frame'

# --- long labels and values are laid out, not clipped -----------------------
# Both of these carry the sentence a user needs in order to act, so losing the
# end of one at the frame is a functional defect rather than a cosmetic one.
render review none ascii >"$TMP/review.layout"
# The indent is not the point and is no longer fixed: the review screen now
# carries a selection marker, so the label column starts further in. What has
# to hold is the gap, because "Disk passphrase" is longer than the column and
# the failure being guarded against is it touching its value.
grep -Eq '^\| +Disk passphrase  +set' "$TMP/review.layout" ||
  fail 'a label longer than its column ran into its value'
grep -Fq 'the EFI system partition' "$TMP/failure" ||
  fail 'the failure detail was truncated instead of wrapped'
# A field value too long for one line continues in the value column.
#
# The value is injected rather than provoked out of the graphics probe. It used
# to arrive by giving the probe a very long directory path to fail on, which
# worked only for as long as the probe echoed that path back at the user, and
# it no longer does: that field holds a value now and the sentence lives in the
# advice. Injecting keeps this test about `tui_field` wrapping, which is what
# it was always for.
long_value='a-graphics-adapter-with-a-very-long-name-that-will-not-fit-on-one-line-at-all'
env AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii \
  AURADE_PROBE_FORCE_GRAPHICS="$long_value" \
  "$TUI" --render fallback >"$TMP/longfield.out"
grep -Fq 'a-graphics-adapter-with-a-very-long-name' "$TMP/longfield.out" ||
  fail 'a long field value did not appear at all'
# The same value with spaces in it wraps at the spaces rather than mid word.
env AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii \
  AURADE_PROBE_FORCE_GRAPHICS='a graphics adapter with a very long name that will not fit on one line at all' \
  "$TUI" --render fallback >"$TMP/longwords.out"
grep -Fq 'a graphics adapter with a very long name' "$TMP/longwords.out" ||
  fail 'a long spaced field value did not appear'
measure "$TMP/longwords.out" || fail 'a long spaced field value broke the frame'
grep -q 'name-$' "$TMP/longwords.out" && fail 'a spaced value was cut mid word'

python3 - "$TMP/longfield.out" <<'PY' || fail 'a long field value did not wrap into its own column'
import sys
lines = open(sys.argv[1], encoding='utf-8').read().split('\n')
for n, line in enumerate(lines):
    if line.startswith('|    Graphics'):
        follow = lines[n + 1]
        # The continuation carries text and starts in the value column, not at
        # the body indent, which is what distinguishes wrapping from a new row.
        if follow[1:21].strip() == '' and follow[21:].strip():
            sys.exit(0)
        print(f'continuation line was {follow!r}', file=sys.stderr)
        sys.exit(1)
print('no Graphics field was rendered', file=sys.stderr)
sys.exit(1)
PY

# --- a failure at a non-resumable stage offers no retry ---------------------
cat >"$TMP/nonresumable.jsonl" <<'EOF'
{"v":1,"stage":"snapshot","status":"failed","exit":1,"cause":"unexpected_exit","message":"a step ended without reporting why","resumable":false,"target":{"path":"/dev/nvme0n1"}}
EOF
env AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii "$TUI" --render failure \
  --journal "$TMP/nonresumable.jsonl" >"$TMP/nonresumable.out"
! grep -Fq 'Try ' "$TMP/nonresumable.out" ||
  fail 'a retry was offered for a stage the journal says cannot be retried'
grep -Fq 'Saving a snapshot to roll back to' "$TMP/nonresumable.out" ||
  fail 'the failure screen did not name the non-resumable stage'
flatten "$TMP/nonresumable.out" | grep -Fq 'no way to carry on' ||
  fail 'the failure screen does not say it cannot resume'

# --- a journal message cannot forge a record field --------------------------
cat >"$TMP/hostile.jsonl" <<'EOF'
{"v":1,"stage":"configure","status":"failed","exit":1,"cause":"unexpected_exit","message":"quoted \"stage\":\"bootloader\" text","resumable":true,"target":{"path":"/dev/nvme0n1"}}
EOF
env AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii "$TUI" --render failure \
  --journal "$TMP/hostile.jsonl" >"$TMP/hostile.out"
grep -Fq 'Setting things up' "$TMP/hostile.out" ||
  fail 'the real stage was lost when a message contained a quoted field'
! grep -Fq 'Install the bootloader did not finish' "$TMP/hostile.out" ||
  fail 'a message impersonated the stage field'

# --- no secret ever reaches a rendered screen -------------------------------
render review none ascii >"$TMP/review"
grep -Fq 'Password' "$TMP/review" || fail 'the review screen omits the password row'
! grep -Fq 'hunter2' "$TMP/review" || fail 'a password value reached the review screen'
env AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii AURADE_RENDER_BUFFER='hunter2' \
  "$TUI" --render question-password >"$TMP/secret.out"
! grep -Fq 'hunter2' "$TMP/secret.out" || fail 'a secret question echoed its input'
grep -Fq '*******' "$TMP/secret.out" || fail 'a secret question did not mask its input'

# --- the unknown-screen path refuses rather than rendering something --------
if "$TUI" --render no-such-screen >"$TMP/unknown.out" 2>&1; then
  fail 'an unknown screen name was accepted'
fi
grep -Fq 'unknown screen' "$TMP/unknown.out" || fail 'the unknown screen error is unclear'


# --- truecolor draws the same colours the graphical front end does ----------
#
# The 256 colour tier approximates the brand from a fixed palette, which is the
# best a terminal could do for years and is visibly not lilac. Most terminals
# have done 24 bit for a decade, so the exact colours are available, and a
# second approximation of the brand is exactly what this tier exists to remove.
#
# The literals live in the shell because the text installer cannot import
# Python. That is a copy, and a copy drifts, so this is the thing that catches
# it: regenerate the theme and the two must still agree.
python3 - "$ROOT" <<'CHECK' || exit 1
import re, sys, os
root = sys.argv[1]
sys.path.insert(0, os.path.join(root, "installer", "lib"))
from aurade_gui import tokens as T

scheme = T.scheme(True)
want = {
    "border": scheme["outline_variant"], "ink": scheme["on_surface"],
    "dim": scheme["on_surface_variant"], "accent": scheme["primary"],
    "cyan": scheme["tertiary"], "ok": scheme["secondary"],
    "warn": scheme["warning"], "danger": scheme["error"],
}
source = open(os.path.join(root, "installer", "lib", "aurade-tui.sh")).read()
block = source.split("    true)", 1)[1].split("    256)", 1)[0]
found = dict(re.findall(r"(\w+)\)\s+printf '\\033\[38;2;(\d+;\d+;\d+)m'", block))
bad = 0
for token, hexcolour in want.items():
    r, g, b = (int(hexcolour[i:i+2], 16) for i in (1, 3, 5))
    expected = f"{r};{g};{b}"
    if found.get(token) != expected:
        print(f"test-tui-render: truecolor {token} is {found.get(token)}, "
              f"the graphical front end draws {expected} ({hexcolour})",
              file=sys.stderr)
        bad += 1
sys.exit(1 if bad else 0)
CHECK

# And it is only chosen when the terminal says so, because terminfo does not
# carry the capability and `tput colors` reports 256 on terminals that have
# been doing 24 bit for years.
env -u AURADE_TUI_COLOR -u AURADE_TUI_FRAME -u AURADE_TUI_PLAIN \
  COLORTERM=truecolor TERM=xterm-256color \
  "$TUI" --render welcome >"$TMP/tc" 2>/dev/null
env -u AURADE_TUI_COLOR -u AURADE_TUI_FRAME -u AURADE_TUI_PLAIN \
  -u COLORTERM TERM=xterm-256color \
  "$TUI" --render welcome >"$TMP/no-tc" 2>/dev/null
# Rendered to a pipe, so both land on the no-colour tier and are identical.
# What matters is that neither crashes and the detector has both paths.
grep -Fq '38;2;' "$ROOT/installer/lib/aurade-tui.sh" ||
  fail 'the truecolor tier emits no 24 bit sequences'
grep -Fq 'COLORTERM' "$ROOT/installer/lib/aurade-tui.sh" ||
  fail 'truecolor is never detected from the only signal terminals agree on'


# --- the console palette, which is where the brand actually lands -----------
#
# The Linux virtual console reports eight colours and means it. It is also the
# terminal this installer actually runs on, so the truecolor tier above never
# fires there: it is for somebody running the text installer from an emulator.
#
# The console's sixteen colours are registers rather than constants, so the
# brand arrives by rewriting them and then using the ordinary 16 colour tier.
python3 - "$ROOT" <<'PALETTE' || exit 1
import re, sys, os
root = sys.argv[1]
sys.path.insert(0, os.path.join(root, "installer", "lib"))
from aurade_gui import tokens as T
scheme = T.scheme(True)
source = open(os.path.join(root, "installer", "lib", "aurade-tui.sh")).read()
# Split on a closing brace at the start of a line: the first `}` in this
# function is inside `${TERM:-}`, which truncated the block to one line
# and reported three slots missing that were there all along.
block = source.split("tui_palette_apply() {", 1)[1].split("\n}", 1)[0]
slots = dict(re.findall(r"\\033\]P([0-9A-F])([0-9a-f]{6})", block))
want = {"8": "outline_variant", "F": "on_surface", "C": "primary",
        "E": "tertiary", "A": "secondary", "D": "warning", "9": "error"}
bad = 0
for slot, role in want.items():
    expected = scheme[role].lstrip("#")
    if slots.get(slot) != expected:
        print(f"test-tui-render: console slot {slot} is {slots.get(slot)}, "
              f"{role} is {expected}", file=sys.stderr)
        bad += 1
sys.exit(1 if bad else 0)
PALETTE

# Only on that console: the sequence is its own extension, and an emulator that
# does not know it prints the payload as text across the first screen.
grep -Fq '[[ ${TERM:-} == linux ]] || return 0' "$ROOT/installer/lib/aurade-tui.sh" ||
  fail 'the console palette is not gated on the console that understands it'
# And restored, because the palette outlives the process.
grep -Fq 'tui_palette_reset' "$TUI" ||
  fail 'the installer never puts the console palette back'

# --- the frame runs lilac to aqua where a terminal can draw it --------------
#
# The same two colours the mark's stroke runs between and the same two the
# graphical front end draws its hairline with, so the two installers are one
# product rather than two that share a name.
#
# Only at the truecolor tier. In 256 colours the ramp between these tones is
# four or five steps, which reads as banding, and banding looks like a fault.
top_rule() {
  # `sed -n 1p` rather than `head -1`, which closes the pipe after one line
  # and takes the renderer down with a broken pipe under `pipefail`.
  env AURADE_TUI_COLOR="$1" AURADE_TUI_FRAME=unicode AURADE_TUI_HEIGHT=24 \
    "$TUI" --render welcome 2>/dev/null | sed -n '1p'
}

colours=$(top_rule true | grep -o '38;2;[0-9;]*' || true)
[[ $(head -1 <<<"$colours") == '38;2;209;188;255' ]] ||
  fail "the frame does not start at the mark's lilac"
[[ $(tail -1 <<<"$colours") == '38;2;135;208;239' ]] ||
  fail "the frame does not end at the mark's aqua"
# A gradient, not two ends and a flat middle.
steps=$(sort -u <<<"$colours" | wc -l)
(( steps > 20 )) || fail "the frame changes colour $steps times, which is banding not a gradient"

# The other tiers keep the flat border they had. A flat hairline is what the
# design was before this and it looked deliberate.
for tier in 256 16; do
  steps=$(top_rule "$tier" | grep -o '38;5;[0-9]*\|\[9[0-9]m' | sort -u | wc -l)
  (( steps <= 1 )) ||
    fail "the $tier colour tier drew $steps colours along one rule"
done

# And the frame is the same width in every tier, because the colour is not
# part of the measurement and a per-character escape sequence is the easiest
# way to accidentally make it part of the measurement.
for tier in true 256 16 none; do
  width=$(top_rule "$tier" | sed 's/\x1b\[[0-9;]*m//g' | awk '{ print length($0) }')
  (( width == 68 )) || fail "at the $tier tier the frame measured $width columns"
done

# --- the braille bar, and the console it must not appear on -----------------
#
# A braille cell is two columns of four dots, so filling one left to right
# gives eight steps inside a single character and the bar moves continuously
# instead of jumping a whole cell at a time.
#
# The Linux virtual console is the one place it must not be drawn, and it is
# also where this installer mostly runs. Its fonts carry a few hundred glyphs;
# box drawing is among them, which is why the frame is safe there, and the
# braille block is not. A bar made of missing glyphs is a row of blanks, which
# looks exactly like an install that is not progressing.
bar_on() {
  env AURADE_TUI_COLOR=none AURADE_TUI_FRAME="$1" TERM="$2" AURADE_TUI_HEIGHT=40 \
    "$TUI" --render progress --journal "$TMP/journal.jsonl" 2>/dev/null |
    grep -F '[' | head -1
}

grep -q '⣿' <<<"$(bar_on unicode xterm-256color)" ||
  fail 'a terminal that can draw braille got the plain bar'
! grep -q '⣿' <<<"$(bar_on unicode linux)" ||
  fail 'the braille bar was drawn on the console whose font has no braille in it'
grep -q '#' <<<"$(bar_on unicode linux)" ||
  fail 'the console fell back to no bar at all instead of the ASCII one'
! grep -q '⣿' <<<"$(bar_on ascii xterm-256color)" ||
  fail 'the ascii tier drew braille'
# And never under plain mode, where the cells are eight dot patterns under a
# finger rather than a picture of anything.
! env AURADE_TUI_PLAIN=1 AURADE_TUI_HEIGHT=40 "$TUI" --render progress \
    --journal "$TMP/journal.jsonl" 2>/dev/null | grep -q '⣿' ||
  fail 'plain mode drew a braille progress bar at a braille display'

# --- the battery warning, and the three times it stays quiet ----------------
#
# Losing power part way through writing a filesystem leaves a disk that is
# neither the old system nor the new one, so the last screen before the point
# of no return says something when the machine is running on a low battery.
#
# The silence is the harder half and gets three cases. A warning that also
# fires on a desktop, or while plugged in, or at 90 percent, is a warning
# people learn to read past, and then it is not there on the laptop at 12
# percent that this exists for.
power_fixture() {
  local dir=$TMP/power
  rm -rf "$dir"
  install -d "$dir/BAT0" "$dir/AC"
  printf 'Battery\n' >"$dir/BAT0/type"
  printf '%s\n' "$1" >"$dir/BAT0/capacity"
  printf '%s\n' "$2" >"$dir/BAT0/status"
  printf 'Mains\n' >"$dir/AC/type"
  printf '%s\n' "$3" >"$dir/AC/online"
  printf '%s' "$dir"
}

battery_says() {
  env AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii AURADE_TUI_HEIGHT=40 \
    AURADE_POWER_DIR="$1" "$TUI" --render review 2>/dev/null |
    grep -c 'on battery at' || true
}

said=$(battery_says "$(power_fixture 17 Discharging 0)")
(( said >= 1 )) || fail 'a laptop on battery at 17 percent was told nothing before the gate'

said=$(battery_says "$(power_fixture 17 Discharging 1)")
(( said == 0 )) || fail 'a machine that is plugged in was warned about its battery'

said=$(battery_says "$(power_fixture 90 Discharging 0)")
(( said == 0 )) || fail 'a battery at 90 percent was treated as low'

rm -rf "$TMP/power"
install -d "$TMP/power"
said=$(battery_says "$TMP/power")
(( said == 0 )) || fail 'a machine with no battery at all was warned about one'

echo 'installer TUI render test: PASS'
