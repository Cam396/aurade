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

# The frame grows with the terminal, so the width is pinned here the way the
# height already is. Without it a screen rendered on a build machine with a
# wide terminal and the same screen rendered in CI are different screens, and
# every column measurement below is measuring the margin.
export AURADE_TUI_COLUMNS=68

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fail() { echo "test-tui-flow: $*" >&2; exit 1; }
check() { [[ $2 == "$3" ]] || fail "$1: expected '$3', got '$2'"; }

install -d "$TMP/zoneinfo/America" "$TMP/locales" "$TMP/keymaps/i386/qwerty" \
  "$TMP/block/nvme0n1" "$TMP/block/sda" "$TMP/block/sdb" "$TMP/dri" "$TMP/bundle"
: >"$TMP/zoneinfo/UTC"; : >"$TMP/zoneinfo/America/Chicago"
: >"$TMP/locales/en_US"; : >"$TMP/locales/fr_FR"
for _keymap in us fr de; do : >"$TMP/keymaps/i386/qwerty/$_keymap.map.gz"; done
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
export AURADE_BUNDLE_DIR="$TMP/bundle"
export AURADE_REPO_FINGERPRINT_FILE="$TMP/repo-fingerprint"
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

# The keymap answer is applied the instant it is chosen, which on a console
# runs loadkeys (see apply_answer). This suite has no console and may run
# unprivileged, where a real loadkeys cannot load a layout and would turn the
# keyboard question into a dead end that never advances. A stub stands in for
# it, the same one the keymap cases below drive with AURADE_TEST_LOADKEYS_REJECT,
# put on the path once here so every route through the flow is answered the same
# on any host, with or without kbd and root.
install -d "$TMP/stub"
cat >"$TMP/stub/loadkeys" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$1" >>"${AURADE_TEST_LOADKEYS_LOG:-/dev/null}"
[[ $1 != "${AURADE_TEST_LOADKEYS_REJECT:-}" ]]
STUB
chmod +x "$TMP/stub/loadkeys"
PATH="$TMP/stub:$PATH"

# --- the whole default path, answered ---------------------------------------
# shellcheck disable=SC2034  # SHOW_ADVANCED is read by the sourced front end
reset_state() { ANSWERS=(); SHOW_ADVANCED=0; }

reset_state
{
  # locale: default en_US.UTF-8 is preselected, enter accepts it
  echo enter
  # keymap: filter to fr, take it, then clear the check field
  typed 'fr'; echo enter
  echo enter                       # keyboard check
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
  echo enter                       # keyboard check
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
  echo enter                       # keyboard check
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

# --- the keyboard check, and where esc goes from it -------------------------
#
# Straight after the layout is chosen there is a field to type into, because
# the layout is already loaded and the next two questions are typed blind. A
# disk passphrase set through a layout whose punctuation is somewhere else is
# a disk nobody opens again, and it is the only answer in this installer that
# cannot be fixed afterwards.
#
# `esc` from the check reopens the layout list rather than stepping back to
# the question before it. That is the whole reason the check is worth having:
# somebody who has just discovered the keys are in the wrong place wants a
# different layout, and sending them to the locale question instead would make
# them navigate forward again to reach the one screen they were asking for.
reset_state
{
  echo enter                       # locale
  typed 'fr'; echo enter           # keymap fr
  typed '@#|'                      # type into the check field
  echo esc                         # and reject it
  typed 'de'; echo enter           # back on the layout list, not the locale
  echo enter                       # the check again, accepted this time
  echo enter                       # timezone
  echo enter                       # disk
  echo enter                       # hostname
  typed 'alex'; echo enter
  typed 'pw'; echo enter; typed 'pw'; echo enter
  echo n
} >"$TMP/keys"
exec {_TUI_KEYFD}<"$TMP/keys"; export _TUI_KEYFD
run_questions >/dev/null || fail 'the keyboard check broke the flow'
release
check 'keymap after rejecting the check' "${ANSWERS[keymap]}" 'de'
check 'locale untouched by the check'    "${ANSWERS[locale]}" 'en_US.UTF-8'
# Nothing typed into the check is kept. It is a field with no answer, which is
# unusual enough in this flow to be worth stating rather than assuming.
for id in "${!ANSWERS[@]}"; do
  [[ ${ANSWERS[$id]} != *'@#|'* ]] ||
    fail "what was typed into the keyboard check was recorded as '$id'"
done

# --- a mismatched password is refused and re-asked --------------------------
reset_state
{
  # locale, keymap, the keyboard check, timezone, disk, hostname
  echo enter; echo enter; echo enter; echo enter; echo enter; echo enter
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
  # locale, keymap, the keyboard check, timezone, disk, hostname
  echo enter; echo enter; echo enter; echo enter; echo enter; echo enter
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
normal_umask=$(umask)
build_engine_args
[[ $(umask) == "$normal_umask" ]] ||
  fail 'writing installer secrets changed the process umask'
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

# Repository trust is shared by the text and graphical front ends. A signed
# image passes its key and fingerprint; the intentionally unsigned development
# image opts into hash-only verification through its explicit marker. A missing
# key on a signed image must not silently become an unsigned install.
printf '%s\n' development-unsigned >"$AURADE_REPO_FINGERPRINT_FILE"
build_engine_args
argv=" ${ENGINE_ARGS[*]} "
[[ $argv == *' --allow-unsigned '* ]] ||
  fail 'the development image did not opt into its explicit unsigned policy'
[[ $argv != *'--repo-key'* ]] ||
  fail 'the unsigned development image unexpectedly received a repository key'

printf '%s\n' 0123456789abcdef0123456789abcdef01234567 >"$AURADE_REPO_FINGERPRINT_FILE"
printf '%s\n' 'test repository key' >"$AURADE_BUNDLE_DIR/aurade-repository.gpg"
build_engine_args
argv=" ${ENGINE_ARGS[*]} "
[[ $argv == *"--repo-key $AURADE_BUNDLE_DIR/aurade-repository.gpg"* ]] ||
  fail 'the signed image did not pass its repository key'
[[ $argv == *'--repo-fingerprint 0123456789abcdef0123456789abcdef01234567'* ]] ||
  fail 'the signed image did not pass its repository fingerprint'
[[ $argv != *'--allow-unsigned'* ]] ||
  fail 'the signed image unexpectedly allowed unsigned packages'

rm -f -- "$AURADE_BUNDLE_DIR/aurade-repository.gpg"
build_engine_args
argv=" ${ENGINE_ARGS[*]} "
[[ $argv != *'--allow-unsigned'* ]] ||
  fail 'a signed image without its key silently allowed unsigned packages'

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
# here, not discovered at a masked prompt. The stub loadkeys is already on the
# path from the harness setup above; here it also records what it was asked to
# load so the call can be checked, and refuses the layout named by REJECT.
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
  echo enter                       # keyboard check
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

# --- the picker never offers a filesystem this image cannot make -------------
# The engine refuses a root filesystem whose mkfs is missing, so offering one
# is offering a choice with a stopped install at the end of it. Both front ends
# read this list, which is why it is tested here rather than in either of them.
install -d "$TMP/fsbin"
for tool in mkfs.btrfs mkfs.ext4; do
  printf '#!/usr/bin/env bash\nexit 0\n' >"$TMP/fsbin/$tool"
  chmod +x "$TMP/fsbin/$tool"
done
saved_path=$PATH
PATH="$TMP/fsbin:$PATH"
# Shadowing rather than emptying the path: `enum_candidates` only asks whether
# each mkfs can be found, and everything else in this file still needs a shell.
printf '#!/usr/bin/env bash\nexit 1\n' >"$TMP/fsbin/mkfs.xfs"
chmod +x "$TMP/fsbin/mkfs.xfs"
offered=$(enum_candidates filesystem | tr '\n' ' ')
offered=${offered% }
[[ $offered == 'btrfs ext4 xfs' ]] || fail "the filesystem list offered '$offered' on an image that has every mkfs"
rm -f "$TMP/fsbin/mkfs.xfs"
# And with the tool out of reach, wherever the host keeps it.
while xfs_tool=$(command -v mkfs.xfs 2>/dev/null); do
  PATH=$(printf '%s' "$PATH" | tr ':' '\n' | grep -Fxv "${xfs_tool%/*}" | tr '\n' ':')
  PATH=${PATH%:}
  [[ -n $PATH ]] || break
done
offered=$(enum_candidates filesystem | tr '\n' ' ')
offered=${offered% }
[[ $offered == 'btrfs ext4' ]] || fail "the filesystem list offered '$offered' on an image with no mkfs.xfs"
PATH=$saved_path

# --- the review screen is a hub, not a page you pass through -----------------
#
# The wizard still runs first, so a first install walks every question top to
# bottom and nobody is asked to find anything. After that this screen is where
# the work happens: arrow to a line, press enter, change that one answer, come
# back. A returning user who wants a different disk changes the disk instead of
# answering eleven questions to reach it.
#
# `enter` edits and `c` continues. On a screen whose rows are all selectable,
# an enter that sometimes means "change this" and sometimes means "start
# erasing a disk" is the wrong key to overload.
TUI=$ROOT/installer/bin/aurade-installer-tui
# `AURADE_INSTALLER_TUI_LIB=1` is exported near the top of this file so the
# functions can be sourced. A render subprocess inherits it, acts as a library
# and returns without drawing, which is a screen that captures as zero bytes
# and fails every assertion below for a reason that has nothing to do with the
# screen.
review=$(env -u AURADE_INSTALLER_TUI_LIB AURADE_TUI_COLUMNS=68 \
  AURADE_TUI_HEIGHT=34 AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii \
  "$TUI" --render review 2>/dev/null)
grep -Fq 'enter  change' <<<"$review" ||
  fail 'the review screen does not offer to change a line'
grep -Fq 'c  continue' <<<"$review" ||
  fail 'the review screen does not say how to continue'
# The selection marker is the same one the disk list and the failure options
# use, so "the line you are on" looks the same everywhere in the product.
grep -q '^| *> ' <<<"$review" ||
  fail 'the review screen shows no selected line'

# Every row it lists is a question it can actually open, or enter lands on
# nothing. This is the pair that drifts: the screen builds its rows from the
# answers and the editor looks them up in the manifest. The library is already
# sourced above, so this calls the real function rather than a copy of it.
ANSWERS[locale]=en_US.UTF-8
ANSWERS[target]=/dev/sda
screen_review 0 >/dev/null 2>&1 || true
for _row in ${REVIEW_ROWS[@]+"${REVIEW_ROWS[@]}"}; do
  aurade_question_exists "$_row" ||
    fail "the review screen lists '$_row', which is not a question it can open"
done
(( ${#REVIEW_ROWS[@]} > 0 )) || fail 'the review screen listed nothing at all'

# --- the detail pane is about the row the marker is on -----------------------
#
# On a wide terminal the right hand pane explains the selected line. The two
# halves are rendered independently, which is what keeps either from moving
# the other, and is also exactly how they come to disagree: the list walks the
# question order and the detail looks one question up by id, so an off-by-one
# in either shows as a screen that confidently explains the wrong answer.
#
# Nothing about that looks broken, which is why it is worth a test. It walks
# every row rather than checking one, because an off-by-one at the top is the
# one an eye would catch anyway.
for _index in 0 1 2 3; do
  _pane=$(env -u AURADE_INSTALLER_TUI_LIB AURADE_TUI_COLUMNS=120 \
    AURADE_TUI_HEIGHT=40 AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii \
    AURADE_RENDER_REVIEW_ROW="$_index" "$TUI" --render review 2>/dev/null)
  # The row the marker is on, by its short name, and the heading the pane on
  # the right chose. Both read out of the drawn screen rather than out of the
  # arrays, so this measures what somebody would be looking at.
  _short=$(sed 's/^ *//' <<<"$_pane" |
    awk -F'|' '/^\|/ && NF == 4 && $2 ~ /> / { sub(/^ *> */, "", $2); print $2; exit }')
  _short=${_short%%"  "*}
  [[ -n $_short ]] || fail "row $_index has no marked line"
  _want=''
  for _id in "${AURADE_QUESTION_IDS[@]}"; do
    [[ $(aurade_question_field "$_id" short) == "$_short" ]] || continue
    _want=$(aurade_question_field "$_id" label)
    break
  done
  [[ -n $_want ]] || fail "the marked row '$_short' is not a question"
  grep -Fq "$_want" <<<"$_pane" ||
    fail "row $_index is '$_short' and the pane beside it does not explain it"
done

# --- a question mark is a character, not a request for help -----------------
#
# `?` opens an explanation of the current screen, which is worth having and is
# one keystroke away from being a disaster: a passphrase is allowed to contain
# a question mark, and a help screen that swallowed one would set a passphrase
# the user does not think they set, on a disk that then cannot be opened by
# anybody. It is the only mistake in this program with no way back.
#
# So the text fields turn the help key off for as long as they are collecting,
# and this types one through the whole flow to prove it.
reset_state
{
  echo enter                       # locale
  echo enter                       # keymap
  echo enter                       # keyboard check
  echo enter                       # timezone
  echo enter                       # disk
  echo enter                       # hostname
  typed 'alex'; echo enter
  typed 'why?not'; echo enter; typed 'why?not'; echo enter   # password
  echo enter                       # encrypt: yes
  typed 'kn?ck kn?ck'; echo enter; typed 'kn?ck kn?ck'; echo enter
} >"$TMP/keys"
exec {_TUI_KEYFD}<"$TMP/keys"; export _TUI_KEYFD
run_questions >/dev/null || fail 'a question mark in a secret broke the flow'
release
check 'password with a question mark'   "${ANSWERS[password]}"        'why?not'
check 'passphrase with a question mark' "${ANSWERS[luks_passphrase]}" 'kn?ck kn?ck'

# --- answer files ------------------------------------------------------------
#
# The question set is already a manifest, so writing the answers out and
# reading them back is nearly free. What is not free is that the file is
# untrusted input which ends at a destructive command line, so it gets the
# same treatment as a typed answer and then some.
#
# Two rules carry the weight. No secret is ever written, because a file that
# held a passphrase would be pasted into a chat by somebody trying to be
# helpful inside a week. And an answer that does not pass its own validator is
# dropped rather than used, because "it came from a file" is not evidence.
reset_state
ANSWERS[target]=/dev/sda
ANSWERS[hostname]=aurade-laptop
ANSWERS[username]=alex
ANSWERS[encrypt]=yes
ANSWERS[keymap]=us
ANSWERS[timezone]=UTC
ANSWERS[locale]=en_US.UTF-8
ANSWERS[password]='hunter2'
ANSWERS[luks_passphrase]='correct horse battery'
answers_save "$TMP/answers" || fail 'the answers could not be written'

grep -Fq 'target=/dev/sda' "$TMP/answers" ||
  fail 'the answer file does not record the disk'
grep -Fq 'hostname=aurade-laptop' "$TMP/answers" ||
  fail 'the answer file does not record the computer name'
# The rule that matters most, checked against the values rather than the keys,
# because a secret written under a different name is still a secret written.
! grep -Fq 'hunter2' "$TMP/answers" ||
  fail 'the answer file contains the password'
! grep -Fq 'correct horse battery' "$TMP/answers" ||
  fail 'the answer file contains the disk passphrase'
! grep -q '^password=' "$TMP/answers" || fail 'the answer file has a password line'
! grep -q '^luks_passphrase=' "$TMP/answers" ||
  fail 'the answer file has a passphrase line'
[[ $(stat -c '%a' "$TMP/answers") == 600 ]] ||
  fail 'the answer file is readable by anyone, and it names a disk to erase'

# Read it back, with three kinds of rubbish appended: a question that does not
# exist, a secret somebody pasted in by hand, and an answer that does not pass.
printf '%s\n' \
  'nosuchquestion=whatever' \
  'password=leaked' \
  'luks_passphrase=alsoleaked' \
  'hostname=-not-a-hostname-' >>"$TMP/answers"
reset_state
answers_load "$TMP/answers" || fail 'the answer file could not be read back'
check 'target read back'   "${ANSWERS[target]}"   '/dev/sda'
check 'hostname read back' "${ANSWERS[hostname]}" 'aurade-laptop'
check 'locale read back'   "${ANSWERS[locale]}"   'en_US.UTF-8'
[[ -z ${ANSWERS[password]:-} ]] ||
  fail 'a password in an answer file was accepted'
[[ -z ${ANSWERS[luks_passphrase]:-} ]] ||
  fail 'a passphrase in an answer file was accepted'
# The invalid hostname later in the file must not have overwritten the good
# one earlier in it, and must not be reported as missing either, because it
# is not.
[[ " ${ANSWERS_REJECTED[*]} " == *' password '* ]] ||
  fail 'a refused password was not reported'
[[ " ${ANSWERS_REJECTED[*]} " != *' hostname '* ]] ||
  fail 'a question that was answered earlier in the file is reported as missing'

# An answer file may not say something the keyboard could not.
#
# Two rules live in `apply_answer` and nowhere else, and loading a file used to
# skip it: it validated and wrote straight into ANSWERS. So `localhost` was
# refused when typed and accepted when read from a file, from the same tree, on
# the same run. That is the shape of drift that ends with a front end quietly
# holding a different rule from the engine.
reset_state
printf '%s\n' 'hostname=localhost' >"$TMP/localhost-answers"
answers_load "$TMP/localhost-answers" ||
  fail 'a file whose only line was refused reported failure rather than a rejection'
[[ ${ANSWERS[hostname]:-} != localhost ]] ||
  fail 'an answer file named a machine localhost, which typing it is refused for'
[[ " ${ANSWERS_REJECTED[*]} " == *' hostname '* ]] ||
  fail 'localhost was dropped from an answer file without being reported'

# A file that is not there is not an error worth stopping for. Somebody who
# mistypes a path should get the questions, not a refusal.
reset_state
answers_load "$TMP/no-such-file" && fail 'a missing answer file reported success'
(( ${#ANSWERS[@]} == 0 )) || fail 'a missing answer file filled something in'

# --- a pasted token reaches the gate whole ----------------------------------
#
# The scripted key stream can carry a paste, because that is what the reader
# hands the screen: one key name with the text attached. This is the gate, so
# the thing being checked is that the pasted string is compared exactly and
# that nothing about arriving by paste makes it match more easily.
reset_state
ANSWERS[target]=/dev/sda
ANSWERS[layout]=wipe
token=$(aurade_confirmation_token /dev/sda wipe)
{ printf 'paste:%s\n' "$token"; echo enter; } >"$TMP/keys"
exec {_TUI_KEYFD}<"$TMP/keys"; export _TUI_KEYFD
run_gate >/dev/null || fail 'a pasted confirmation token was not accepted'
release

# And a paste that is nearly right is still refused, which is the half worth
# testing: the gate has to compare, not merely receive.
{ printf 'paste:%s\n' "${token}x"; echo enter; echo esc; } >"$TMP/keys"
exec {_TUI_KEYFD}<"$TMP/keys"; export _TUI_KEYFD
run_gate >/dev/null && fail 'a pasted token with a character too many was accepted'
release

# --- the secret field, and the three things it now says ---------------------
#
# A typo you cannot see is a disk you cannot open, and that is the only
# mistake in this installer with no way back.
#
# Showing what has been typed is a thing somebody asks for in the moment, so
# it starts masked every time the field is entered and the choice is never
# carried forward. Carrying it would eventually show a passphrase to a room.
reset_state
SECRET_REVEAL=1
{
  echo enter; echo enter; echo enter; echo enter; echo enter; echo enter
  typed 'alex'; echo enter
  typed 'pw'; echo enter; typed 'pw'; echo enter
  echo n
} >"$TMP/keys"
exec {_TUI_KEYFD}<"$TMP/keys"; export _TUI_KEYFD
run_questions >/dev/null || fail 'the flow broke with reveal left on'
release
(( SECRET_REVEAL == 0 )) ||
  fail 'a revealed secret field stayed revealed for the next one'

# Caps lock is read from the keyboard light, which is the only honest signal
# there is. Guessing from the case of what was typed would tell somebody with
# a deliberately capitalised passphrase that they had made a mistake.
install -d "$TMP/leds/input0::capslock"
printf '1\n' >"$TMP/leds/input0::capslock/brightness"
AURADE_CAPSLOCK_GLOB="$TMP/leds/*capslock/brightness" capslock_on ||
  fail 'a lit caps lock light was not noticed'
printf '0\n' >"$TMP/leds/input0::capslock/brightness"
if AURADE_CAPSLOCK_GLOB="$TMP/leds/*capslock/brightness" capslock_on; then
  fail 'an unlit caps lock light was reported as on'
fi
# And where there is no light to read, which is every terminal that is not a
# local console, it says nothing rather than guessing.
if AURADE_CAPSLOCK_GLOB="$TMP/no-such-place/*/brightness" capslock_on; then
  fail 'caps lock was reported on a machine with no keyboard light to read'
fi

# --- the things that are not features ---------------------------------------
#
# Two words the erase gate answers, and the only thing worth testing about
# either is that the gate is exactly as hard to pass afterwards. They clear
# the field, which makes it harder rather than easier, and the token they are
# compared against does not change.
reset_state
ANSWERS[target]=/dev/sda
ANSWERS[layout]=wipe
token=$(aurade_confirmation_token /dev/sda wipe)
{
  typed 'HELLO'
  typed 'xyzzy'
  printf 'paste:%s\n' "$token"
  echo enter
} >"$TMP/keys"
exec {_TUI_KEYFD}<"$TMP/keys"; export _TUI_KEYFD
run_gate >/dev/null ||
  fail 'the gate stopped accepting its own token after the asides'
release

# And neither of them is a way through. Typing HELLO and pressing enter is
# still an empty field at a screen that erases a disk.
{ typed 'HELLO'; echo enter; echo esc; } >"$TMP/keys"
exec {_TUI_KEYFD}<"$TMP/keys"; export _TUI_KEYFD
run_gate >/dev/null && fail 'HELLO was accepted as a confirmation'
release
{ typed 'xyzzy'; echo enter; echo esc; } >"$TMP/keys"
exec {_TUI_KEYFD}<"$TMP/keys"; export _TUI_KEYFD
run_gate >/dev/null && fail 'xyzzy was accepted as a confirmation'
release

# The cheat code, at the one screen in this product that must not have one.
#
# It clears the field and says no, which is the same thing HELLO does and is
# strictly harder rather than easier: the `b` and the `a` that are part of the
# sequence go with it. The token is untouched and the engine still makes its
# own comparison.
konami() {
  local k
  for k in up up down down left right left right b a; do printf '%s\n' "$k"; done
}
reset_state
ANSWERS[target]=/dev/sda
ANSWERS[layout]=wipe
token=$(aurade_confirmation_token /dev/sda wipe)
{ konami; printf 'paste:%s\n' "$token"; echo enter; } >"$TMP/keys"
exec {_TUI_KEYFD}<"$TMP/keys"; export _TUI_KEYFD
# This also proves the field is left empty. A sequence that ended with `b`
# and `a` still in there would mean the token no longer matched after it.
run_gate >/dev/null ||
  fail 'the gate stopped accepting its own token after the sequence'
release

{ konami; echo enter; echo esc; } >"$TMP/keys"
exec {_TUI_KEYFD}<"$TMP/keys"; export _TUI_KEYFD
run_gate >/dev/null && fail 'the cheat code was accepted as a confirmation'
release

# Naming a machine after the word every machine already answers to is declined
# with a sentence rather than an error code, because it is not a mistake, it
# is somebody being funny.
if apply_answer hostname localhost; then
  fail 'a machine was allowed to call itself localhost'
fi
[[ -n $APPLY_ERROR ]] || fail 'localhost was refused without saying why'
[[ $APPLY_ERROR != *invalid* && $APPLY_ERROR != *error* ]] ||
  fail 'localhost was refused with an error message rather than an answer'
apply_answer hostname localhost-2 ||
  fail 'a hostname that merely starts with localhost was refused'

# --- a sequence of keys that do nothing ------------------------------------
#
# The welcome screen is where this lives precisely because none of the ten
# keys does anything there. A sequence built out of keys that do something is
# a sequence somebody enters by accident.
KONAMI_AT=0
for _key in up up down down left right left right b; do
  konami_watch "$_key" && fail 'the sequence fired early'
done
konami_watch a || fail 'the whole sequence did not fire'

# A wrong key restarts it, and a wrong key that happens to be the first key
# restarts at one rather than at nothing, or the sequence cannot be entered a
# second time.
KONAMI_AT=0
konami_watch up || true
konami_watch x || true
(( KONAMI_AT == 0 )) || fail 'a wrong key did not reset the sequence'
konami_watch up || true
konami_watch up || true
(( KONAMI_AT == 2 )) ||
  fail "after up up the sequence is at $KONAMI_AT, so it cannot be entered twice"

# And it fires a second time, which is what that restart rule is for.
KONAMI_AT=0
for _round in 1 2; do
  fired=0
  for _key in up up down down left right left right b a; do
    konami_watch "$_key" && fired=1
  done
  (( fired )) || fail "the sequence did not fire on round $_round"
done

echo 'installer TUI flow test: PASS'
