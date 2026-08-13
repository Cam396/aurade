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
TUI="$ROOT/installer/bin/aurade-installer-tui"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fail() { echo "test-tui-render: $*" >&2; exit 1; }

install -d "$TMP/zoneinfo/America" "$TMP/locales" "$TMP/keymaps/i386/qwerty" "$TMP/dri"
: >"$TMP/zoneinfo/UTC"; : >"$TMP/zoneinfo/America/Chicago"
: >"$TMP/locales/en_US"; : >"$TMP/keymaps/i386/qwerty/us.map.gz"
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
{"v":1,"install_id":"6f2a1c9e","seq":5,"attempt":1,"stage":"bootloader","status":"failed","exit":1,"cause":"esp-readonly","message":"bootctl could not write to the EFI system partition","resumable":true,"reversible":false,"idempotent":true,"remediation":["retry","export","log","shell","reboot"],"target":{"path":"/dev/nvme0n1"}}
EOF

export AURADE_ZONEINFO_DIR="$TMP/zoneinfo" AURADE_LOCALE_DIR="$TMP/locales"
export AURADE_KEYMAP_DIR="$TMP/keymaps" AURADE_SNAPSHOT_FILE="$TMP/snapshot"
export AURADE_DISK_TABLE="$TMP/disks" AURADE_PROBE_MEMINFO="$TMP/meminfo"
export AURADE_PROBE_DRI_DIR="$TMP/dri"

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

# --- NO_COLOR and TERM=dumb select the bottom tier on their own -------------
env -u AURADE_TUI_COLOR -u AURADE_TUI_FRAME NO_COLOR=1 TERM=xterm-256color \
  "$TUI" --render welcome >"$TMP/nocolor"
! grep -q $'\033' "$TMP/nocolor" || fail 'NO_COLOR did not disable colour'
env -u AURADE_TUI_COLOR -u AURADE_TUI_FRAME TERM=dumb \
  "$TUI" --render welcome >"$TMP/dumb"
! grep -q $'\033' "$TMP/dumb" || fail 'TERM=dumb did not disable colour'
cmp -s "$TMP/nocolor" "$TMP/dumb" || fail 'NO_COLOR and TERM=dumb produced different text'

# --- the interior is strictly ASCII in every tier ---------------------------
# Box drawing is reliably one column wide; check marks, arrows and bullets are
# not, and a double-width glyph in the body is exactly how the frame breaks on
# the terminals least able to show it.
for screen in "${SCREENS[@]}"; do
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
! grep -Fq 'Connect to the network' "$TMP/progress" ||
  fail 'progress lists a stage the engine never emits'
! grep -Fq 'Verify packages' "$TMP/progress" ||
  fail 'progress lists a stage the engine never emits'

render failure none ascii >"$TMP/failure"
grep -Fq 'Install the bootloader' "$TMP/failure" || fail 'failure does not name the failed stage'
grep -Fq 'read-only' "$TMP/failure" || fail 'failure does not explain the cause'
grep -Fq 'Save a diagnostic report' "$TMP/failure" || fail 'failure does not offer a diagnostic report'
grep -Fq 'Open a shell' "$TMP/failure" || fail 'failure does not offer a shell'
grep -Fq 'stage 9 of 11' "$TMP/failure" || fail 'failure does not say where in the sequence it stopped'
# The engine cannot be told to start at a stage, so a retry would re-run
# wipefs. The screen must not offer one, and must say what starting over costs.
! grep -Fq 'Try ' "$TMP/failure" ||
  fail 'the failure screen offers a retry the engine cannot honour'
grep -Fq 'cannot yet continue from where it stopped' "$TMP/failure" ||
  fail 'the failure screen does not admit that it cannot resume'
grep -Fq 'Starting again erases it' "$TMP/failure" ||
  fail 'the failure screen does not say what starting over costs after the disk was changed'

# A failure before the erase gate has a different, non-destructive message.
cat >"$TMP/reversible.jsonl" <<'EOF'
{"v":1,"stage":"acquire","status":"failed","exit":1,"cause":"archive-unreachable","message":"the pinned snapshot could not be reached","resumable":true,"target":{"path":"/dev/nvme0n1"}}
EOF
env AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii "$TUI" --render failure \
  --journal "$TMP/reversible.jsonl" >"$TMP/reversible.out"
grep -Fq 'Nothing was written to the disk' "$TMP/reversible.out" ||
  fail 'a pre-gate failure did not say the disk is untouched'
! grep -Fq 'Starting again erases it' "$TMP/reversible.out" ||
  fail 'a pre-gate failure warned about erasing a disk that was never touched'

render cancelled none ascii >"$TMP/cancelled"
grep -Fq 'Nothing was changed' "$TMP/cancelled" || fail 'the cancelled screen does not say so'

# --- a failure at a non-resumable stage offers no retry ---------------------
cat >"$TMP/nonresumable.jsonl" <<'EOF'
{"v":1,"stage":"snapshot","status":"failed","exit":1,"cause":"unexpected_exit","message":"a step ended without reporting why","resumable":false,"target":{"path":"/dev/nvme0n1"}}
EOF
env AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii "$TUI" --render failure \
  --journal "$TMP/nonresumable.jsonl" >"$TMP/nonresumable.out"
! grep -Fq 'Try ' "$TMP/nonresumable.out" ||
  fail 'a retry was offered for a stage the journal says cannot be retried'
grep -Fq 'Create the recovery snapshot' "$TMP/nonresumable.out" ||
  fail 'the failure screen did not name the non-resumable stage'
grep -Fq 'cannot yet continue' "$TMP/nonresumable.out" ||
  fail 'the failure screen does not say it cannot resume'

# --- a journal message cannot forge a record field --------------------------
cat >"$TMP/hostile.jsonl" <<'EOF'
{"v":1,"stage":"configure","status":"failed","exit":1,"cause":"unexpected_exit","message":"quoted \"stage\":\"bootloader\" text","resumable":true,"target":{"path":"/dev/nvme0n1"}}
EOF
env AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii "$TUI" --render failure \
  --journal "$TMP/hostile.jsonl" >"$TMP/hostile.out"
grep -Fq 'Configure the system' "$TMP/hostile.out" ||
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

echo 'installer TUI render test: PASS'
