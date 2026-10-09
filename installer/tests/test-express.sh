#!/usr/bin/env bash
# Express: an install with no questions, which only aurade-vm asks for.
#
# Nobody is at the erase gate during an express install, so everything that
# gate is for has to be true before it is skipped: a virtual machine, a disk
# with nothing on it, every answer that matters, no encryption to type a
# passphrase for, and a real password hash. Each check here is one way the
# skip could erase something it should not, and each must fall back to the
# ordinary install with the answers filled in.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
export AURADE_TUI_COLUMNS=78

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fail() { echo "test-express: $*" >&2; exit 1; }

command -v openssl >/dev/null 2>&1 || {
  echo 'installer express test: SKIP (openssl not available)'
  exit 0
}

install -d "$TMP/zoneinfo" "$TMP/locales" "$TMP/keymaps/i386/qwerty" \
  "$TMP/block/sda" "$TMP/block/sdb" "$TMP/dri" "$TMP/stub" \
  "$TMP/bundle" "$TMP/installer-meta"
: >"$TMP/zoneinfo/UTC"; : >"$TMP/locales/en_US"
: >"$TMP/keymaps/i386/qwerty/us.map.gz"; : >"$TMP/dri/renderD128"
cat >"$TMP/stub/loadkeys" <<'STUB'
#!/usr/bin/env bash
exit 0
STUB
chmod +x "$TMP/stub/loadkeys"
# Nothing in this test may restart the machine running it. The done screen and
# the failure menu both offer a restart, and an earlier version of this test
# pressed enter on one as root and rebooted the developer's computer. So the
# restart is a stand in that writes a line, systemctl is a stub that refuses,
# and the live medium marker points somewhere that does not exist.
cat >"$TMP/stub/systemctl" <<'STUB'
#!/usr/bin/env bash
echo "systemctl $*" >>"${AURADE_TEST_SYSTEMCTL_LOG:-/dev/null}"
exit 1
STUB
cat >"$TMP/stub/reboot-stand-in" <<'STUB'
#!/usr/bin/env bash
echo reboot >>"${AURADE_TEST_REBOOT_LOG:?}"
STUB
chmod +x "$TMP/stub/systemctl" "$TMP/stub/reboot-stand-in"
export PATH="$TMP/stub:$PATH"
export AURADE_REBOOT_CMD="$TMP/stub/reboot-stand-in"
export AURADE_TEST_REBOOT_LOG="$TMP/reboots"
export AURADE_TEST_SYSTEMCTL_LOG="$TMP/systemctl"
export AURADE_LIVE_MARKER="$TMP/not-a-live-medium"
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
for stage in preflight package-check; do
  aurade_journal_begin "$stage" "starting $stage"
  if [[ ${AURADE_STUB_FAIL_AT:-} == "$stage" ]]; then
    aurade_journal_fail "$stage" 1 unexpected_exit "a step ended without reporting why" \
      retry export log shell reboot
    exit 1
  fi
  if [[ $stage == package-check ]]; then
    aurade_journal_ok "$stage" workspace
  else
    aurade_journal_ok "$stage" "finished $stage"
  fi
done
for stage in acquire confirm partition format mount pacstrap \
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
# The production probe allows five seconds for an optional eglinfo call. This
# fixture drives many independent installer flows, so bound that optional
# lookup tightly while retaining the dedicated probe test's renderer cases.
export AURADE_PROBE_GL_TIMEOUT=0.2
export AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii
# Pinned so the progress screen picks the same layout everywhere.
export AURADE_TUI_HEIGHT=34
export AURADE_INSTALL_ENGINE="$TMP/stub-engine"
export AURADE_JOURNAL_LIB="$ROOT/installer/lib/aurade-journal.sh"
export TMPDIR="$TMP"
export AURADE_BUNDLE_DIR="$TMP/bundle"
printf '%s\n' development-unsigned >"$TMP/installer-meta/repo-fingerprint"
export AURADE_REPO_FINGERPRINT_FILE="$TMP/installer-meta/repo-fingerprint"


# A virtual machine, and a disk that is blank.
printf '%s\n' '#!/usr/bin/env bash' 'echo "${AURADE_TEST_VIRT:-vmware}"' \
  '[[ ${AURADE_TEST_VIRT:-vmware} != none ]]' >"$TMP/stub/virt"
printf '%s\n' '#!/usr/bin/env bash' '[[ -n ${AURADE_TEST_SIGNATURE:-} ]] || exit 2' \
  'echo "$AURADE_TEST_SIGNATURE"' >"$TMP/stub/blkid"
chmod +x "$TMP/stub/virt" "$TMP/stub/blkid"
export AURADE_DETECT_VIRT="$TMP/stub/virt" AURADE_BLKID="$TMP/stub/blkid"
export AURADE_EXPRESS_RESTART_DELAY=0

openssl passwd -6 -salt testsalt 'a password' >"$TMP/hash"
chmod 600 "$TMP/hash"
printf '%s\n' locale=en_US.UTF-8 keymap=us timezone=UTC target=/dev/sda \
  hostname=express-box username=alex encrypt=no \
  profile=plus display_scale=125 apps=firefox,flatpak auto_snapshots=yes >"$TMP/answers"

run_express() {
  local name=$1 answers=${2:-$TMP/answers} hash=${3:-$TMP/hash}
  export AURADE_STUB_CALLS="$TMP/calls.$name"
  : >"$AURADE_STUB_CALLS"; : >"$TMP/keys.$name"; rm -f "$TMP/reboots"
  env AURADE_INSTALLER_TUI_LIB=1 \
      AURADE_TUI_KEYS="$TMP/keys.$name" \
      AURADE_JOURNAL_PATH="$TMP/journal.$name.jsonl" \
      AURADE_JOURNAL_RAW="$TMP/raw.$name.log" \
      bash -c '
        set -Eeuo pipefail
        . "$1"
        exec {_TUI_KEYFD}<"$AURADE_TUI_KEYS"
        export _TUI_KEYFD
        JOURNAL_FILE=$AURADE_JOURNAL_PATH
        RAW_LOG=$AURADE_JOURNAL_RAW
        ANSWERS_IN=$2 EXPRESS=1 EXPRESS_HASH=$3
        main_flow
      ' _ "$ROOT/installer/bin/aurade-installer-tui" "$answers" "$hash" >"$TMP/out.$name" 2>&1
}

# --- everything in place: it installs and restarts ---------------------------
run_express happy || fail "the express install returned non-zero: $(tail -3 "$TMP/out.happy")"
calls=$TMP/calls.happy
(( $(wc -l <"$calls") == 2 )) || fail "expected a dry run and an install, got $(wc -l <"$calls") engine calls"
tail -1 "$calls" | grep -Fq -- '--execute' || fail 'the express install never executed'
tail -1 "$calls" | grep -Fq -- '--confirm ERASE:/dev/sda' || fail 'the express install did not confirm the disk it was given'
tail -1 "$calls" | grep -Fq -- '--username alex' || fail 'the express install lost the username'
tail -1 "$calls" | grep -Fq -- '--hostname express-box' || fail 'the express install lost the computer name'
! tail -1 "$calls" | grep -Fq -- '--encrypt' || fail 'the express install encrypted the disk'
tail -1 "$calls" | grep -Fq -- '--password-hash-file ' || fail 'the express install passed no password hash'
# The desktop answers ride along like any other.
for arg in '--feature-profile plus' '--display-scale 125' '--apps firefox,flatpak' '--auto-snapshots yes'; do
  tail -1 "$calls" | grep -Fq -- "$arg" || fail "the express install lost $arg"
done
! grep -Fq "$(cat "$TMP/hash")" "$TMP/out.happy" || fail 'the password hash was drawn on screen'
grep -Fq 'AuraDE is installed' "$TMP/out.happy" || fail 'the finished screen was never shown'
[[ $(cat "$TMP/reboots" 2>/dev/null) == reboot ]] || fail 'an express install did not restart by itself'
! grep -Fq 'Where should AuraDE be installed' "$TMP/out.happy" || fail 'an express install asked a question'

# --- every reason to stop, and each one stops before the engine runs --------
stopped() {
  local name=$1 why=$2
  ! grep -Fq -- '--execute' "$TMP/calls.$name" || fail "$name: the engine executed"
  grep -Fq 'The express install stopped before doing anything' "$TMP/out.$name" ||
    fail "$name: the stop was not explained"
  grep -Fq "$why" "$TMP/out.$name" || fail "$name: the reason was not '$why'"
  [[ ! -s $TMP/reboots ]] || fail "$name: restarted"
}

AURADE_TEST_VIRT=none run_express physical || true
stopped physical 'not a virtual machine'

AURADE_TEST_SIGNATURE=gpt run_express used-disk || true
stopped used-disk 'is not blank (it holds gpt)'

install -d "$TMP/block/sda/sda1"; : >"$TMP/block/sda/sda1/partition"
run_express partitioned || true
stopped partitioned 'already has partitions'
rm -rf "${TMP:?}/block/sda/sda1"

sed 's/^encrypt=no/encrypt=yes/' "$TMP/answers" >"$TMP/answers.enc"
run_express encrypted "$TMP/answers.enc" || true
stopped encrypted 'Encryption needs a passphrase'

grep -v '^username=' "$TMP/answers" >"$TMP/answers.nouser"
run_express no-user "$TMP/answers.nouser" || true
stopped no-user 'have no usable username'

run_express no-hash "$TMP/answers" "$TMP/missing" || true
stopped no-hash 'No password came with the answers'

printf 'hunter2\n' >"$TMP/plain"
run_express plain-password "$TMP/answers" "$TMP/plain" || true
stopped plain-password 'is not a password'

echo 'installer express test: PASS'
