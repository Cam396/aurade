#!/usr/bin/env bash
# The question flow, driven by scripted keystrokes.
#
# This is the part of the front end where a bug reaches the destructive engine:
# a wrong answer recorded, a validator not consulted, a confirmation token
# accepted when it should not have been. So it is tested by running the real
# state machine over a real key stream and inspecting what came out, not by
# checking that the source contains the right words.
#
# The front end is sourced as a library rather than executed, because executing
# it requires root and a terminal, and a test that only runs under both is a
# test that does not run.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fail() { echo "test-tui-flow: $*" >&2; exit 1; }
check() { [[ $2 == "$3" ]] || fail "$1: expected '$3', got '$2'"; }

install -d "$TMP/zoneinfo/America" "$TMP/locales" "$TMP/keymaps/i386/qwerty" \
  "$TMP/block/nvme0n1" "$TMP/block/sda" "$TMP/block/sdb" "$TMP/dri" "$TMP/stub"
: >"$TMP/zoneinfo/UTC"; : >"$TMP/zoneinfo/America/Chicago"
: >"$TMP/locales/en_US"; : >"$TMP/locales/fr_FR"
for _keymap in us fr de; do : >"$TMP/keymaps/i386/qwerty/$_keymap.map.gz"; done
cat >"$TMP/stub/loadkeys" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$1" >>"${AURADE_TEST_LOADKEYS_LOG:-/dev/null}"
[[ $1 != "${AURADE_TEST_LOADKEYS_REJECT:-}" ]]
STUB
chmod +x "$TMP/stub/loadkeys"
export PATH="$TMP/stub:$PATH"
printf '%s\n' '2026/07/12' >"$TMP/snapshot"
printf 'MemAvailable:   16000000 kB\n' >"$TMP/meminfo"
printf '%s\n' \
  '/dev/nvme0n1|476.9G|Samsung SSD 980 PRO|nvme|S6B2NS0T900123X' \
  '/dev/sda|931.5G|WDC WD10EZEX|sata|WD-WCC6Y4KP1234' \
  '/dev/sdb|28.7G|SanDisk Ultra|usb|4C5300011212' >"$TMP/disks"

export AURADE_ZONEINFO_DIR="$TMP/zoneinfo" AURADE_LOCALE_DIR="$TMP/locales"
export AURADE_KEYMAP_DIR="$TMP/keymaps" AURADE_BLOCK_DIR="$TMP/block"
export AURADE_SNAPSHOT_FILE="$TMP/snapshot" AURADE_DISK_TABLE="$TMP/disks"
export AURADE_PROBE_MEMINFO="$TMP/meminfo" AURADE_PROBE_DRI_DIR="$TMP/dri"
export AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii
export AURADE_INSTALLER_TUI_LIB=1

# shellcheck source=../bin/aurade-installer-tui
. "$ROOT/installer/bin/aurade-installer-tui"

# Drive the state machine from a file of key names, one per line, with all
# drawing discarded. `keys` rewinds the stream for each scenario.
keys() {
  printf '%s\n' "$@" >"$TMP/keys"
  exec {_TUI_KEYFD}<"$TMP/keys"
  export _TUI_KEYFD AURADE_TUI_KEYS="$TMP/keys"
}
release() { exec {_TUI_KEYFD}<&-; unset _TUI_KEYFD; }

# Type a literal string as individual key names.
typed() {
  local text=$1 i
  for (( i = 0; i < ${#text}; i++ )); do
    if [[ ${text:i:1} == ' ' ]]; then printf 'space\n'; else printf '%s\n' "${text:i:1}"; fi
  done
}

# --- the whole default path, answered ---------------------------------------
# shellcheck disable=SC2034  # SHOW_ADVANCED is read by the sourced front end
reset_state() { ANSWERS=(); SHOW_ADVANCED=0; }

reset_state
{
  # locale: default en_US.UTF-8 is preselected, enter accepts it
  echo enter
  # keymap: filter to fr, take it
  typed 'fr'; echo enter
  # timezone: default UTC preselected
  echo enter
  # disk: move down once to /dev/sda
  echo down; echo enter
  # hostname: accept the default
  echo enter
  # username: type one
  typed 'alex'; echo enter
  # password: type, confirm
  typed 'correct horse'; echo enter; typed 'correct horse'; echo enter
  # encrypt: default is yes
  echo enter
  # luks passphrase
  typed 'battery staple'; echo enter; typed 'battery staple'; echo enter
} >"$TMP/keys"
exec {_TUI_KEYFD}<"$TMP/keys"; export _TUI_KEYFD AURADE_TUI_KEYS="$TMP/keys"
run_questions >/dev/null || fail 'the default question path did not complete'
release

check 'locale'   "${ANSWERS[locale]}"   'en_US.UTF-8'
check 'keymap'   "${ANSWERS[keymap]}"   'fr'
check 'timezone' "${ANSWERS[timezone]}" 'UTC'
check 'target'   "${ANSWERS[target]}"   '/dev/sda'
check 'hostname' "${ANSWERS[hostname]}" 'aurade'
check 'username' "${ANSWERS[username]}" 'alex'
check 'password' "${ANSWERS[password]}" 'correct horse'
check 'encrypt'  "${ANSWERS[encrypt]}"  'yes'
check 'luks'     "${ANSWERS[luks_passphrase]}" 'battery staple'

# --- a rejected answer re-asks instead of advancing -------------------------
reset_state
{
  echo enter                       # locale
  echo enter                       # keymap
  echo enter                       # timezone
  echo enter                       # disk
  typed '-illegal-'; echo enter    # hostname: rejected
  for i in $(seq 30); do echo backspace; done   # clear the pre-filled default too
  typed 'good-name'; echo enter    # hostname: accepted
  typed 'alex'; echo enter
  typed 'pw'; echo enter; typed 'pw'; echo enter
  echo n                           # no encryption
} >"$TMP/keys"
exec {_TUI_KEYFD}<"$TMP/keys"; export _TUI_KEYFD
run_questions >/dev/null || fail 'the flow did not complete after a rejected answer'
release
check 'hostname after rejection' "${ANSWERS[hostname]}" 'good-name'
check 'encrypt declined' "${ANSWERS[encrypt]}" 'no'
[[ -z ${ANSWERS[luks_passphrase]:-} ]] ||
  fail 'a passphrase was collected even though encryption was declined'

# --- declining encryption removes the passphrase question -------------------
ANSWERS=([encrypt]=no)
mapfile -t visible < <(visible_questions)
for id in "${visible[@]}"; do
  [[ $id != luks_passphrase ]] || fail 'the passphrase question is still asked when encryption is off'
done
ANSWERS=([encrypt]=yes)
mapfile -t visible < <(visible_questions)
found=0
for id in "${visible[@]}"; do [[ $id != luks_passphrase ]] || found=1; done
(( found )) || fail 'the passphrase question is missing when encryption is on'

# --- esc goes back a step rather than forward -------------------------------
reset_state
{
  echo enter                       # locale
  echo enter                       # keymap
  echo enter                       # timezone
  echo enter                       # disk -> /dev/nvme0n1
  echo esc                         # back to disk
  echo down; echo down; echo enter # now /dev/sdb
  echo enter                       # hostname
  typed 'alex'; echo enter
  typed 'pw'; echo enter; typed 'pw'; echo enter
  echo n
} >"$TMP/keys"
exec {_TUI_KEYFD}<"$TMP/keys"; export _TUI_KEYFD
run_questions >/dev/null || fail 'going back broke the flow'
release
check 'target after going back' "${ANSWERS[target]}" '/dev/sdb'

# --- a mismatched password is refused and re-asked --------------------------
reset_state
{
  echo enter; echo enter; echo enter; echo enter; echo enter
  typed 'alex'; echo enter
  typed 'first'; echo enter; typed 'second'; echo enter   # mismatch
  typed 'agreed'; echo enter; typed 'agreed'; echo enter  # match
  echo n
} >"$TMP/keys"
exec {_TUI_KEYFD}<"$TMP/keys"; export _TUI_KEYFD
run_questions >/dev/null || fail 'a mismatched password broke the flow'
release
check 'password after mismatch' "${ANSWERS[password]}" 'agreed'

# --- quitting from the first question cancels, and only when confirmed ------
reset_state
{ echo esc; echo q; } >"$TMP/keys"
exec {_TUI_KEYFD}<"$TMP/keys"; export _TUI_KEYFD
run_questions >/dev/null && fail 'quitting was reported as a completed flow'
release

reset_state
{
  echo esc; echo x                 # decline the quit, stay in the flow
  echo enter; echo enter; echo enter; echo enter; echo enter
  typed 'alex'; echo enter
  typed 'pw'; echo enter; typed 'pw'; echo enter
  echo n
} >"$TMP/keys"
exec {_TUI_KEYFD}<"$TMP/keys"; export _TUI_KEYFD
run_questions >/dev/null || fail 'declining the quit prompt did not resume the flow'
release

# --- the erase gate accepts only the exact token ----------------------------
ANSWERS=([target]=/dev/sda)
{
  typed 'ERASE:/dev/sdb'; echo enter      # wrong disk
  for i in $(seq 20); do echo backspace; done
  typed 'erase:/dev/sda'; echo enter      # wrong case
  for i in $(seq 20); do echo backspace; done
  typed 'ERASE:/dev/sda'; echo enter      # exact
} >"$TMP/keys"
exec {_TUI_KEYFD}<"$TMP/keys"; export _TUI_KEYFD
run_gate >/dev/null || fail 'the exact confirmation token was refused'
release

ANSWERS=([target]=/dev/sda)
{ typed 'ERASE:/dev/sda'; echo esc; } >"$TMP/keys"
exec {_TUI_KEYFD}<"$TMP/keys"; export _TUI_KEYFD
run_gate >/dev/null && fail 'escaping out of the erase gate was treated as confirmation'
release

# --- the argument list matches the answers ----------------------------------
SECRET_DIR=$TMP/secrets
install -d -m 0700 "$SECRET_DIR"
ANSWERS=(
  [target]=/dev/sda [hostname]=aurade [username]=alex [password]=set
  [encrypt]=yes [luks_passphrase]=set [keymap]=fr [timezone]=UTC
  [locale]=en_US.UTF-8
)
build_engine_args
argv=" ${ENGINE_ARGS[*]} "
for expected in '--target /dev/sda' '--hostname aurade' '--username alex' \
  '--keymap fr' '--timezone UTC' '--locale en_US.UTF-8' '--encrypt' \
  "--password-hash-file $SECRET_DIR/password.hash" \
  "--luks-passphrase-file $SECRET_DIR/luks.passphrase"; do
  [[ $argv == *"$expected"* ]] || fail "the engine arguments are missing: $expected"
done
# The advanced section was never opened, so the snapshot must still be present.
[[ $argv == *'--arch-snapshot 2026/07/12'* ]] ||
  fail 'skipping the advanced section dropped --arch-snapshot'
# Neither secret value may appear as an argument; only the file holding it.
[[ $argv != *'correct horse'* && $argv != *'battery staple'* ]] ||
  fail 'a secret was passed to the engine as a command-line argument'

# Declining encryption must drop both the flag and the passphrase file.
ANSWERS[encrypt]=no
ANSWERS[luks_passphrase]=''
build_engine_args
argv=" ${ENGINE_ARGS[*]} "
[[ $argv != *'--encrypt'* ]] || fail '--encrypt survived declining encryption'
[[ $argv != *'--luks-passphrase-file'* ]] ||
  fail 'a passphrase file was passed even though encryption was declined'

# --- password hashing leaves nothing recoverable behind ---------------------
ANSWERS[password]='correct horse battery staple'
hash_password
[[ -r $SECRET_DIR/password.hash ]] || fail 'no password hash was written'
[[ $(stat -c '%a' "$SECRET_DIR/password.hash") == 600 ]] ||
  fail "the password hash is not mode 0600"
grep -q '^\$6\$' "$SECRET_DIR/password.hash" || fail 'the password was not hashed with SHA-512'
[[ ! -e $SECRET_DIR/password ]] || fail 'the plaintext password file survived hashing'
! grep -rFq 'correct horse battery staple' "$SECRET_DIR" ||
  fail 'the plaintext password is still recoverable from the secret directory'
check 'password answer replaced' "${ANSWERS[password]}" 'set'

# --- the review screen shows answers but never secret values ----------------
ANSWERS[luks_passphrase]='battery staple'
screen_review >"$TMP/review.out"
grep -Fq '/dev/sda' "$TMP/review.out" || fail 'the review screen omits the target'
! grep -Fq 'battery staple' "$TMP/review.out" ||
  fail 'the review screen printed a passphrase'
! grep -Fq 'correct horse' "$TMP/review.out" ||
  fail 'the review screen printed a password'

# --- a validated keymap is applied immediately ------------------------------
# The keyboard question is answered before any password, so the layout has to
# take effect at the moment it is chosen rather than at the end of the flow.
# A layout that is installed but will not load on this console must be caught
# here, not discovered at a masked prompt.
install -d "$TMP/stub"
cat >"$TMP/stub/loadkeys" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$1" >>"${AURADE_TEST_LOADKEYS_LOG:-/dev/null}"
[[ $1 != "${AURADE_TEST_LOADKEYS_REJECT:-}" ]]
STUB
chmod +x "$TMP/stub/loadkeys"

: >"$TMP/loadkeys.log"
export AURADE_TEST_LOADKEYS_LOG="$TMP/loadkeys.log"

# Present and succeeding: the answer is accepted and the layout was applied.
APPLY_ERROR=x
PATH="$TMP/stub:$PATH" apply_answer keymap fr || fail 'a loadable keymap was rejected'
[[ -z $APPLY_ERROR ]] || fail 'a successful keymap left an error message behind'
grep -Fxq fr "$TMP/loadkeys.log" || fail 'loadkeys was never called for the chosen keymap'

# Present and failing: rejected, with something the user can act on.
APPLY_ERROR=
if AURADE_TEST_LOADKEYS_REJECT=de PATH="$TMP/stub:$PATH" apply_answer keymap de; then
  fail 'a keymap that could not be loaded was accepted'
fi
[[ -n $APPLY_ERROR ]] || fail 'a rejected keymap produced no error message'
[[ $APPLY_ERROR == *'could not be loaded'* ]] || fail "unhelpful keymap error: $APPLY_ERROR"

# Absent: not an error. The image ships kbd, but a test host or serial console
# may not, and refusing to continue would make the question unanswerable.
APPLY_ERROR=x
PATH='' apply_answer keymap fr || fail 'a missing loadkeys was treated as a failure'
[[ -z $APPLY_ERROR ]] || fail 'a missing loadkeys produced an error message'

# Questions with nothing to apply are unaffected.
PATH='' apply_answer hostname aurade || fail 'a question with no apply step failed'

# End to end through the prompt: a rejected layout re-asks instead of advancing.
reset_state
{
  echo enter                       # locale
  typed 'de'; echo enter           # keymap de -> loadkeys refuses
  echo backspace; echo backspace
  typed 'fr'; echo enter           # keymap fr -> accepted
  echo enter                       # timezone
  echo enter                       # disk
  echo enter                       # hostname
  typed 'alex'; echo enter
  typed 'pw'; echo enter; typed 'pw'; echo enter
  echo n
} >"$TMP/keys"
exec {_TUI_KEYFD}<"$TMP/keys"; export _TUI_KEYFD
AURADE_TEST_LOADKEYS_REJECT=de PATH="$TMP/stub:$PATH" \
  run_questions >"$TMP/keymap-flow.out" || fail 'the flow stalled on a rejected keymap'
release
check 'keymap after rejection' "${ANSWERS[keymap]}" 'fr'
grep -Fq 'could not be loaded' "$TMP/keymap-flow.out" ||
  fail 'the rejected keymap error was never shown'

# --- going back shows the answer you gave, not the default ------------------
# "esc back" is only truthful if the question it returns to still holds the
# previous answer. Otherwise going back silently rewrites it to the default.
reset_state
ANSWERS=([encrypt]=no [target]=/dev/sdb [keymap]=fr)
{ echo enter; } >"$TMP/keys"
exec {_TUI_KEYFD}<"$TMP/keys"; export _TUI_KEYFD
prompt_bool encrypt 8 9 >/dev/null || fail 'the encryption question did not accept'
release
check 'bool remembered' "$PROMPT_RESULT" 'no'

{ echo enter; } >"$TMP/keys"
exec {_TUI_KEYFD}<"$TMP/keys"; export _TUI_KEYFD
prompt_disk target 4 9 >/dev/null || fail 'the disk question did not accept'
release
check 'disk remembered' "$PROMPT_RESULT" '/dev/sdb'

{ echo enter; } >"$TMP/keys"
exec {_TUI_KEYFD}<"$TMP/keys"; export _TUI_KEYFD
prompt_enum keymap 2 9 >/dev/null || fail 'the keymap question did not accept'
release
check 'enum remembered' "$PROMPT_RESULT" 'fr'

# --- the first question offers quit; later ones offer back ------------------
reset_state
screen_question locale 1 9 >"$TMP/first.out"
grep -Fq 'esc  quit' "$TMP/first.out" ||
  fail 'the first question does not offer quit, which is what esc actually does there'
screen_question hostname 5 9 >"$TMP/later.out"
grep -Fq 'esc  back' "$TMP/later.out" ||
  fail 'a later question does not offer back'
! grep -Fq 'esc  quit' "$TMP/later.out" ||
  fail 'a later question claims esc quits'

# --- key decoding ------------------------------------------------------------
check 'up arrow'    "$(tui_decode_key $'\033[A')" 'up'
check 'down arrow'  "$(tui_decode_key $'\033[B')" 'down'
check 'right arrow' "$(tui_decode_key $'\033[C')" 'right'
check 'left arrow'  "$(tui_decode_key $'\033[D')" 'left'
check 'bare escape' "$(tui_decode_key $'\033')"   'esc'
check 'enter'       "$(tui_decode_key '')"        'enter'
check 'tab'         "$(tui_decode_key $'\t')"     'tab'
check 'backspace'   "$(tui_decode_key $'\177')"   'backspace'
check 'space'       "$(tui_decode_key ' ')"       'space'
check 'letter'      "$(tui_decode_key 'k')"       'k'
# An unrecognised escape sequence must not be typed into an answer.
check 'unknown csi' "$(tui_decode_key $'\033[5~')" 'esc'

# --- the reversibility boundary the progress screen renders ------------------
# The UI must not invent its own idea of what can be undone; it asks the
# journal library, which the engine uses too.
for stage in preflight acquire confirm; do
  aurade_stage_reversible "$stage" || fail "$stage should be reversible"
done
for stage in partition format pacstrap bootloader; do
  ! aurade_stage_reversible "$stage" || fail "$stage must not be reversible"
done

echo 'installer TUI flow test: PASS'
