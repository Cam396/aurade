#!/usr/bin/env bash
# The graphical installer's model process, over its real protocol.
#
# The graphical front end reaches the destructive engine through exactly one
# path, and this is it. So the fixtures here are the ones that let the whole
# path run without root, without a disk and without a display: a recording stub
# engine, an injectable disk table, fixture keymap/zone/locale roots, and stub
# helpers for the diagnostics the failure and network pages call.
#
# The assertions live in gui_bridge_test.py, which drives the shipped Python
# client against the shipped shell model, so a quoting or buffering bug between
# the two fails here rather than on a machine with a disk in it.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

command -v python3 >/dev/null 2>&1 || {
  echo 'installer GUI bridge test: SKIP (python3 not available)'
  exit 0
}
command -v openssl >/dev/null 2>&1 || {
  echo 'installer GUI bridge test: SKIP (openssl not available)'
  exit 0
}

install -d "$TMP/zoneinfo/America" "$TMP/locales" "$TMP/keymaps/i386/qwerty" \
  "$TMP/block/sda" "$TMP/block/sda1" "$TMP/block/sdb" "$TMP/dri" \
  "$TMP/empty-dri" "$TMP/run" "$TMP/stub" "$TMP/export" "$TMP/bundle"
: >"$TMP/zoneinfo/UTC"; : >"$TMP/zoneinfo/America/Chicago"
: >"$TMP/locales/en_US"; : >"$TMP/locales/fr_FR"
for _keymap in us fr de; do : >"$TMP/keymaps/i386/qwerty/$_keymap.map.gz"; done
: >"$TMP/dri/renderD128"
# The kernel driver behind the node, read from sysfs. Two fixtures, because the
# graphics page prints different advice for "a named driver is loaded" and
# "something published a node and we cannot tell what".
install -d "$TMP/drm/renderD128/device"
printf 'DRIVER=i915\n' >"$TMP/drm/renderD128/device/uevent"
install -d "$TMP/drm-unknown"
install -d "$TMP/drm-virtual/renderD128/device"
printf 'DRIVER=vgem\n' >"$TMP/drm-virtual/renderD128/device/uevent"
# A partition carries this attribute; a whole disk does not.
: >"$TMP/block/sda1/partition"
printf '%s\n' '2026/07/12' >"$TMP/snapshot"
printf 'MemAvailable:   16000000 kB\n' >"$TMP/meminfo"
printf '%s\n' \
  '/dev/sda|931.5G|WDC WD10EZEX|sata|WD-WCC6Y4KP1234' \
  '/dev/sdb|28.7G|SanDisk Ultra|usb|4C5300011212' >"$TMP/disks"

# A stub engine that records its argv, copies the secret files it was handed so
# the test can prove they arrived unaltered, and writes journal records for the
# stages it claims to have run.
cat >"$TMP/stub-engine" <<'STUB'
#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' "$*" >>"$AURADE_STUB_CALLS"
mode=dry-run
target=''
previous=''
for arg in "$@"; do
  [[ $arg != --execute ]] || mode=execute
  case $previous in
    --target) target=$arg ;;
    --luks-passphrase-file) cp -- "$arg" "$AURADE_STUB_DIR/passphrase.seen" ;;
    --password-hash-file) cp -- "$arg" "$AURADE_STUB_DIR/hash.seen" ;;
  esac
  previous=$arg
done
printf 'stub engine invoked in %s mode\n' "$mode"
[[ $mode == execute ]] || exit "${AURADE_STUB_DRYRUN_STATUS:-0}"

. "$AURADE_JOURNAL_LIB"
aurade_journal_init execute "$target"
for stage in preflight acquire confirm partition format mount pacstrap \
  configure bootloader snapshot verify-install; do
  aurade_journal_begin "$stage" "starting $stage"
  if [[ ${AURADE_STUB_FAIL_AT:-} == "$stage" ]]; then
    aurade_journal_fail "$stage" 1 unexpected_exit \
      'a step ended without reporting why' export log reboot
    exit 1
  fi
  aurade_journal_ok "$stage" "finished $stage"
done
exit 0
STUB

cat >"$TMP/stub/loadkeys" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$1" >>"$AURADE_TEST_LOADKEYS_LOG"
[[ ${AURADE_TEST_LOADKEYS_REJECT:-} != "$1" ]] || exit 1
exit 0
STUB

# Exits non-zero and writes nothing. Its exit status is deliberately 2, which
# is also a status a real install can exit with, which is exactly why the
# export check looks at the artifact instead.
cat >"$TMP/stub/broken-helper" <<'STUB'
#!/usr/bin/env bash
printf 'aurade-install-failure: the export directory is not writable\n' >&2
exit 2
STUB

cat >"$TMP/stub/net-ok" <<'STUB'
#!/usr/bin/env bash
printf '  an active network interface is present\n'
printf '  the package archive answered\n'
exit 0
STUB

cat >"$TMP/stub/net-bad" <<'STUB'
#!/usr/bin/env bash
printf '  an active network interface is present\n'
printf '  ERROR: the clock is wrong; package signatures will not verify\n' >&2
exit 1
STUB

chmod +x "$TMP/stub-engine" "$TMP/stub/loadkeys" "$TMP/stub/broken-helper" \
  "$TMP/stub/net-ok" "$TMP/stub/net-bad"
: >"$TMP/loadkeys.log"

# A search path with everything the bridge needs and no loadkeys, so the
# "a console tool this image does not carry is not a failure" case can be
# exercised through the real protocol. An empty PATH cannot be used for this:
# the bridge would not find its own interpreter, and the test would prove that
# instead.
install -d "$TMP/nokeys"
for _tool in bash sh env awk sed grep sort find cat head tr wc printf mktemp \
  chmod chown install dirname basename date rm cp mv ln readlink id uname \
  openssl lsblk blockdev shred timeout systemd-detect-virt stat mkdir rmdir \
  touch tee cut; do
  _path=$(command -v "$_tool" 2>/dev/null) || continue
  ln -sfn "$_path" "$TMP/nokeys/$_tool"
done
[[ ! -e $TMP/nokeys/loadkeys ]] || {
  echo 'test-gui-bridge: the restricted search path still carries loadkeys' >&2
  exit 1
}

# A second copy laid out the way the installation image lays it out, with the
# diagnostic helpers deliberately absent. The front ends resolve their helpers
# next to themselves, so "this image does not carry that helper" is only
# reachable from a tree that genuinely does not carry it - and running the
# bridge from here also proves the image's own library resolution works.
install -d "$TMP/image/sbin" "$TMP/image/lib"
install -m 0755 "$ROOT/installer/bin/aurade-installer-tui" \
  "$ROOT/installer/bin/aurade-installer-gui-bridge" "$TMP/image/sbin/"
install -m 0644 "$ROOT/installer/lib/aurade-validate.sh" \
  "$ROOT/installer/lib/aurade-questions.sh" "$ROOT/installer/lib/aurade-tui.sh" \
  "$ROOT/installer/lib/aurade-probe.sh" "$ROOT/installer/lib/aurade-journal.sh" \
  "$TMP/image/lib/"
[[ ! -e $TMP/image/sbin/aurade-install-failure ]] || {
  echo 'test-gui-bridge: the bare image copy carries a diagnostic helper' >&2
  exit 1
}

export AURADE_ZONEINFO_DIR="$TMP/zoneinfo" AURADE_LOCALE_DIR="$TMP/locales"
export AURADE_KEYMAP_DIR="$TMP/keymaps" AURADE_BLOCK_DIR="$TMP/block"
export AURADE_SNAPSHOT_FILE="$TMP/snapshot" AURADE_DISK_TABLE="$TMP/disks"
export AURADE_PROBE_MEMINFO="$TMP/meminfo" AURADE_PROBE_DRI_DIR="$TMP/dri"
export AURADE_INSTALL_ENGINE="$TMP/stub-engine"
export AURADE_JOURNAL_LIB="$ROOT/installer/lib/aurade-journal.sh"
export AURADE_JOURNAL_PATH="$TMP/run/journal.jsonl"
export AURADE_JOURNAL_RAW="$TMP/run/install.log"
export AURADE_FAILURE_HELPER="$ROOT/installer/bin/aurade-install-failure"
export AURADE_FAILURE_EXPORT_DIR="$TMP/export"
export AURADE_NETWORK_HELPER="$TMP/stub/net-ok"
export AURADE_BUNDLE_DIR="$TMP/bundle"
export AURADE_STUB_CALLS="$TMP/calls"
export AURADE_STUB_DIR="$TMP"
export AURADE_TEST_LOADKEYS_LOG="$TMP/loadkeys.log"
export TMPDIR="$TMP"

exec python3 "$ROOT/installer/tests/gui_bridge_test.py" "$TMP"
