#!/usr/bin/env bash
# The whole front end, end to end, against a recording stub engine.
#
# The flow test checks what the state machine records. This one checks what
# actually reaches the engine, which is the question that matters: the engine
# is the program that erases disks, and every safety property of this front end
# is a statement about the arguments it does or does not pass.
#
# So the stub records its argv and its environment, and the assertions are
# about ordering and refusal:
#
#   the dry run happens before the erase gate, so the plan the user approves is
#   the plan the engine produced;
#   `--execute` is never passed without a confirmation token that matches the
#   selected disk exactly;
#   leaving the gate by any route other than typing that token means the engine
#   is never invoked with `--execute` at all;
#   no secret is ever passed as an argument or written to the raw log.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fail() { echo "test-tui-engine: $*" >&2; exit 1; }

command -v openssl >/dev/null 2>&1 || {
  echo 'installer TUI engine test: SKIP (openssl not available)'
  exit 0
}

install -d "$TMP/zoneinfo" "$TMP/locales" "$TMP/keymaps/i386/qwerty" \
  "$TMP/block/sda" "$TMP/block/sdb" "$TMP/dri"
: >"$TMP/zoneinfo/UTC"; : >"$TMP/locales/en_US"
: >"$TMP/keymaps/i386/qwerty/us.map.gz"; : >"$TMP/dri/renderD128"
printf '%s\n' '2026/07/12' >"$TMP/snapshot"
printf 'MemAvailable:   16000000 kB\n' >"$TMP/meminfo"
printf '%s\n' \
  '/dev/sda|931.5G|WDC WD10EZEX|sata|WD-WCC6Y4KP1234' \
  '/dev/sdb|28.7G|SanDisk Ultra|usb|4C5300011212' >"$TMP/disks"

PASSWORD='correct horse battery staple'
PASSPHRASE='a passphrase with spaces'

# A stub engine that records every invocation and writes journal records for
# the stages it claims to have run. AURADE_STUB_FAIL_AT names a stage to fail.
cat >"$TMP/stub-engine" <<'STUB'
#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' "$*" >>"$AURADE_STUB_CALLS"
mode=dry-run
for arg in "$@"; do [[ $arg != --execute ]] || mode=execute; done
printf 'stub engine invoked in %s mode\n' "$mode"
[[ $mode == execute ]] || exit "${AURADE_STUB_DRYRUN_STATUS:-0}"

. "${AURADE_JOURNAL_LIB}"
target=''
previous=''
for arg in "$@"; do
  [[ $previous != --target ]] || target=$arg
  previous=$arg
done
aurade_journal_init execute "$target"
printf 'stub engine running stages\n'
for stage in preflight acquire confirm partition format mount pacstrap \
  configure bootloader snapshot verify-install; do
  aurade_journal_begin "$stage" "starting $stage"
  if [[ ${AURADE_STUB_FAIL_AT:-} == "$stage" ]]; then
    aurade_journal_fail "$stage" 1 unexpected_exit "a step ended without reporting why" \
      retry export log shell reboot
    exit 1
  fi
  aurade_journal_ok "$stage" "finished $stage"
done
exit 0
STUB
chmod +x "$TMP/stub-engine"

export AURADE_ZONEINFO_DIR="$TMP/zoneinfo" AURADE_LOCALE_DIR="$TMP/locales"
export AURADE_KEYMAP_DIR="$TMP/keymaps" AURADE_BLOCK_DIR="$TMP/block"
export AURADE_SNAPSHOT_FILE="$TMP/snapshot" AURADE_DISK_TABLE="$TMP/disks"
export AURADE_PROBE_MEMINFO="$TMP/meminfo" AURADE_PROBE_DRI_DIR="$TMP/dri"
export AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii
export AURADE_INSTALL_ENGINE="$TMP/stub-engine"
export AURADE_JOURNAL_LIB="$ROOT/installer/lib/aurade-journal.sh"
export TMPDIR="$TMP"

# Answer the default path, then whatever the scenario adds at the gate.
answers() {
  local i
  echo enter                       # welcome
  echo enter                       # locale (default)
  echo enter                       # keymap (default)
  echo enter                       # timezone (default)
  echo enter                       # disk -> /dev/sda
  echo enter                       # hostname (default)
  for (( i = 0; i < 4; i++ )); do echo 'a'; done; echo enter   # username aaaa
  script_secret "$PASSWORD"
  echo enter                       # encrypt: yes
  script_secret "$PASSPHRASE"
  echo enter                       # review: continue
}

script_secret() {
  local text=$1
  for _ in 1 2; do
    local i
    for (( i = 0; i < ${#text}; i++ )); do
      if [[ ${text:i:1} == ' ' ]]; then echo space; else printf '%s\n' "${text:i:1}"; fi
    done
    echo enter
  done
}

typed_token() {
  local text=$1 i
  for (( i = 0; i < ${#text}; i++ )); do
    if [[ ${text:i:1} == ' ' ]]; then echo space; else printf '%s\n' "${text:i:1}"; fi
  done
}

run_flow() {
  local name=$1
  export AURADE_STUB_CALLS="$TMP/calls.$name"
  : >"$AURADE_STUB_CALLS"
  env AURADE_INSTALLER_TUI_LIB=1 \
      AURADE_STUB_DRYRUN_STATUS="${AURADE_STUB_DRYRUN_STATUS:-0}" \
      AURADE_STUB_FAIL_AT="${AURADE_STUB_FAIL_AT:-}" \
      AURADE_TUI_KEYS="$TMP/keys.$name" \
      AURADE_JOURNAL_PATH="$TMP/journal.$name.jsonl" \
      AURADE_JOURNAL_RAW="$TMP/raw.$name.log" \
      AURADE_FAILURE_EXPORT_DIR="${AURADE_TEST_EXPORT_DIR:-$TMP/export.$name}" \
      AURADE_TEST_PLAN_ONLY="${AURADE_TEST_PLAN_ONLY:-0}" \
      bash -c '
        set -Eeuo pipefail
        . "$1"
        exec {_TUI_KEYFD}<"$AURADE_TUI_KEYS"
        export _TUI_KEYFD
        JOURNAL_FILE=$AURADE_JOURNAL_PATH
        RAW_LOG=$AURADE_JOURNAL_RAW
        EXPORT_DIR=$AURADE_FAILURE_EXPORT_DIR
        PLAN_ONLY=$AURADE_TEST_PLAN_ONLY
        main_flow
      ' _ "$ROOT/installer/bin/aurade-installer-tui" >"$TMP/out.$name" 2>&1
}

# --- a complete install -----------------------------------------------------
{ answers; typed_token 'ERASE:/dev/sda'; echo enter; echo enter; } >"$TMP/keys.happy"
run_flow happy || fail "a complete install returned non-zero: $(tail -3 "$TMP/out.happy")"

calls=$TMP/calls.happy
(( $(wc -l <"$calls") == 2 )) || fail "expected exactly two engine calls, got $(wc -l <"$calls")"
head -1 "$calls" | grep -Fq -- '--dry-run' || fail 'the first engine call was not the dry run'
head -1 "$calls" | grep -Fq -- '--execute' && fail 'the dry run was passed --execute'
tail -1 "$calls" | grep -Fq -- '--execute' || fail 'the second engine call did not execute'
tail -1 "$calls" | grep -Fq -- '--confirm ERASE:/dev/sda' ||
  fail 'the execute call did not carry the exact confirmation token'
tail -1 "$calls" | grep -Fq -- '--target /dev/sda' || fail 'the execute call named the wrong disk'
tail -1 "$calls" | grep -Fq -- '--arch-snapshot 2026/07/12' ||
  fail 'the execute call lost the image snapshot date'
tail -1 "$calls" | grep -Fq -- '--encrypt' || fail 'encryption was requested but not passed'

# The finished screen must actually be reached.
grep -Fq 'AuraDE is installed' "$TMP/out.happy" || fail 'the finished screen was never shown'
# And the journal the engine wrote must have driven a progress render.
grep -Fq 'Install the base system' "$TMP/out.happy" || fail 'no progress screen was rendered'

# --- no secret leaves the process ------------------------------------------
! grep -Fq "$PASSWORD" "$calls" || fail 'the password was passed to the engine as an argument'
! grep -Fq "$PASSPHRASE" "$calls" || fail 'the passphrase was passed to the engine as an argument'
! grep -Fq "$PASSWORD" "$TMP/out.happy" || fail 'the password appeared on screen'
! grep -Fq "$PASSPHRASE" "$TMP/out.happy" || fail 'the passphrase appeared on screen'
! grep -Fq "$PASSWORD" "$TMP/raw.happy.log" || fail 'the password reached the raw log'
! grep -Fq "$PASSPHRASE" "$TMP/raw.happy.log" || fail 'the passphrase reached the raw log'
! grep -Fq "$PASSWORD" "$TMP/journal.happy.jsonl" || fail 'the password reached the journal'
! grep -Fq "$PASSPHRASE" "$TMP/journal.happy.jsonl" || fail 'the passphrase reached the journal'
# The secret directory is removed on exit, so nothing survives the run.
find "$TMP" -maxdepth 1 -name 'aurade-installer.*' -print -quit | grep -q . &&
  fail 'the secret directory outlived the installer'

# --- escaping the erase gate never reaches --execute ------------------------
{ answers; typed_token 'ERASE:/dev/sda'; echo esc; } >"$TMP/keys.escaped"
run_flow escaped || fail 'cancelling at the erase gate returned non-zero'
grep -Fq 'Nothing was changed' "$TMP/out.escaped" ||
  fail 'cancelling at the gate did not show the cancelled screen'
(( $(wc -l <"$TMP/calls.escaped") == 1 )) ||
  fail 'more than the dry run ran after the gate was cancelled'
! grep -Fq -- '--execute' "$TMP/calls.escaped" ||
  fail 'the engine was told to execute after the gate was cancelled'

# --- a token for a different disk never reaches --execute -------------------
{
  answers
  typed_token 'ERASE:/dev/sdb'; echo enter   # wrong disk: must not proceed
  echo esc                                   # leave the gate
} >"$TMP/keys.wrongdisk"
run_flow wrongdisk || fail 'a mistyped token returned non-zero'
! grep -Fq -- '--execute' "$TMP/calls.wrongdisk" ||
  fail 'a confirmation token naming a different disk was accepted'

# --- quitting before any question runs no engine at all ---------------------
{ echo esc; echo q; } >"$TMP/keys.quit"
run_flow quit || fail 'quitting at the welcome screen returned non-zero'
[[ ! -s $TMP/calls.quit ]] || fail 'the engine ran even though the user quit at the welcome screen'
grep -Fq 'Nothing was changed' "$TMP/out.quit" || fail 'quitting did not confirm that nothing changed'

# --- a failing dry run stops before the gate --------------------------------
{ answers; echo esc; } >"$TMP/keys.dryfail"
AURADE_STUB_DRYRUN_STATUS=3 run_flow dryfail && fail 'a failing dry run reported success'
(( $(wc -l <"$TMP/calls.dryfail") == 1 )) || fail 'the engine ran again after the dry run failed'
! grep -Fq -- '--execute' "$TMP/calls.dryfail" ||
  fail 'the erase gate was reached even though the dry run failed'

# --- a mid-install failure lands on the failure screen ----------------------
{ answers; typed_token 'ERASE:/dev/sda'; echo enter; echo esc; } >"$TMP/keys.bootfail"
AURADE_STUB_FAIL_AT=bootloader run_flow bootfail && fail 'a failed install reported success'
grep -Fq 'Install the bootloader did not finish' "$TMP/out.bootfail" ||
  fail 'the failure screen did not name the failed stage'
grep -Fq 'cannot yet continue from where it stopped' "$TMP/out.bootfail" ||
  fail 'the failure screen did not admit that it cannot resume'
! grep -Fq 'Try ' "$TMP/out.bootfail" ||
  fail 'the failure screen offered a retry the engine cannot honour'
grep -Fq '"stage":"bootloader","status":"failed"' "$TMP/journal.bootfail.jsonl" ||
  fail 'the journal did not record the failure'

# --- the diagnostic report can be exported from the failure screen ----------
{
  answers; typed_token 'ERASE:/dev/sda'; echo enter
  echo enter                     # save a diagnostic report (first option)
  echo esc
} >"$TMP/keys.export"
AURADE_STUB_FAIL_AT=bootloader run_flow export && true
# The helper keeps each source file's own basename, so the export is matched
# by prefix rather than by an assumed name.
exported=$(find "$TMP/export.export" -name 'journal.*' 2>/dev/null | head -1 || true)
[[ -n $exported ]] || fail 'the failure screen did not export a diagnostic report'
[[ $(stat -c '%a' "$exported") == 600 ]] || fail 'the exported journal is not mode 0600'
! grep -Fq "$PASSWORD" "$exported" || fail 'the exported journal contains the password'
raw_export=$(find "$TMP/export.export" -name 'raw.*' 2>/dev/null | head -1 || true)
if [[ -n $raw_export ]]; then
  ! grep -Fq "$PASSWORD" "$raw_export" || fail 'the exported raw log contains the password'
  ! grep -Fq "$PASSPHRASE" "$raw_export" || fail 'the exported raw log contains the passphrase'
fi

# --- --plan-only can never reach --execute ---------------------------------
# The flag exists so an operator can see the plan without any risk at all, so
# the guarantee has to be that no key sequence gets past it - including one
# that types a correct erase token.
{
  answers
  typed_token 'ERASE:/dev/sda'; echo enter
  echo enter; echo enter; echo esc
} >"$TMP/keys.planonly"
AURADE_TEST_PLAN_ONLY=1 run_flow planonly ||
  fail '--plan-only returned non-zero on a complete answer set'
(( $(wc -l <"$TMP/calls.planonly") == 1 )) ||
  fail "--plan-only ran the engine $(wc -l <"$TMP/calls.planonly") times instead of once"
grep -Fq -- '--dry-run' "$TMP/calls.planonly" || fail '--plan-only did not run the dry run'
! grep -Fq -- '--execute' "$TMP/calls.planonly" ||
  fail '--plan-only reached a destructive invocation'
! grep -Fq -- '--confirm' "$TMP/calls.planonly" ||
  fail '--plan-only built a confirmation token'
! grep -Fq 'Confirm erase' "$TMP/out.planonly" ||
  fail '--plan-only displayed the erase gate'
[[ ! -e /dev/sda ]] || true

# --- going back from the erase gate returns to review, as the footer says ---
{
  answers
  echo esc                                   # gate -> review
  echo enter                                 # review -> prepare -> gate again
  typed_token 'ERASE:/dev/sda'; echo enter   # now go through
  echo enter
} >"$TMP/keys.gateback"
run_flow gateback || fail 'going back from the erase gate broke the flow'
grep -Fq 'AuraDE is installed' "$TMP/out.gateback" ||
  fail 'the install did not complete after going back and forward again'
# Two dry runs, because returning to review re-validates the plan, then one
# execute. The important part is that exactly one execute happened.
(( $(grep -c -- '--execute' "$TMP/calls.gateback") == 1 )) ||
  fail 'the engine executed more than once across a back-and-forward'
(( $(grep -c -- '--dry-run' "$TMP/calls.gateback") == 2 )) ||
  fail 'the plan was not re-validated after returning to the review screen'

# --- a failed export says so, and the menu stays usable ---------------------
# The helper exits with the install status on success and 2 on failure, so its
# exit code cannot distinguish them. Reporting "Saved" for a report that was
# never written is the failure this guards.
{
  answers; typed_token 'ERASE:/dev/sda'; echo enter
  echo enter                     # save a diagnostic report -> must fail
  echo down                      # menu still responds
  echo esc
} >"$TMP/keys.exportfail"
AURADE_STUB_FAIL_AT=bootloader AURADE_TEST_EXPORT_DIR=/proc/aurade-cannot-write \
  run_flow exportfail && fail 'a failed install reported success'
# Flatten the frame before matching: these sentences wrap, and an assertion
# that depends on where they wrap breaks whenever the wording shifts.
flatten() { tr -d '|' <"$1" | tr -s ' \n' '  ' ; }
flatten "$TMP/out.exportfail" >"$TMP/exportfail.flat"
grep -Fq 'Could not save a report' "$TMP/exportfail.flat" ||
  fail 'a failed export did not report the failure'
! grep -Fq 'Saved to' "$TMP/exportfail.flat" ||
  fail 'a failed export claimed the report was saved'
[[ ! -e /proc/aurade-cannot-write ]] ||
  fail 'the export wrote somewhere it should not have'
# The menu is redrawn after the failed attempt, so the user still has options.
(( $(grep -c 'View the full log' "$TMP/out.exportfail") >= 2 )) ||
  fail 'the failure menu did not survive a failed export'
grep -Fq 'Open a shell' "$TMP/out.exportfail" ||
  fail 'the failure menu lost its options after a failed export'

# --- raw command output stays out of the structured journal -----------------
# The journal is the contract the UI parses; a stray line of subprocess output
# in it is both a parse hazard and a disclosure risk.
python3 - "$TMP/journal.happy.jsonl" <<'PY' || fail 'the journal is not valid JSONL'
import json, sys
for n, line in enumerate(open(sys.argv[1]), 1):
    line = line.strip()
    if not line:
        continue
    try:
        json.loads(line)
    except Exception as exc:
        print(f'line {n} is not valid JSON: {exc}', file=sys.stderr)
        sys.exit(1)
PY
! grep -Fq 'stub engine running stages' "$TMP/journal.happy.jsonl" ||
  fail 'engine stdout leaked into the structured journal'
grep -Fq 'stub engine running stages' "$TMP/raw.happy.log" ||
  fail 'engine stdout did not reach the raw log'

# A dry run that fails never reaches the execute call, so nothing truncates the
# log and its output is exactly what the failure screen has to work with.
grep -Fq 'stub engine invoked in dry-run mode' "$TMP/raw.dryfail.log" ||
  fail 'the failing dry run left no output in the raw log'

echo 'installer TUI engine test: PASS'
