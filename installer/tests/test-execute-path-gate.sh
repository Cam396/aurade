#!/usr/bin/env bash
# Opt-in execute-mode fixture. It attaches only a sparse loop-backed file and
# stops the real installer before package acquisition, so this is not a full
# installation test and cannot damage a host disk.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
INSTALLER=$ROOT/installer/bin/aurade-install
TMP_ROOT=${AURADE_EXECUTE_PATH_TMPDIR:-/tmp}
EVIDENCE_FILE=${AURADE_EXECUTE_PATH_EVIDENCE_FILE:-}
RUN_DIR=
IMAGE=
LOOP_DEVICE=

record() {
  local line=$1
  printf '%s\n' "$line"
  if [[ -n $EVIDENCE_FILE ]]; then
    printf '%s\n' "$line" >>"$EVIDENCE_FILE" || true
  fi
}

skip() {
  local reason=$1 safe_reason
  safe_reason=${reason//$'\t'/_}
  safe_reason=${safe_reason//$'\n'/_}
  safe_reason=${safe_reason// /_}
  record "execute_path_gate status=skip executed=false full_install_claim=false reason=$safe_reason"
  exit 0
}

cleanup() {
  local status=$? detach_failed=0
  set +e
  if [[ $LOOP_DEVICE =~ ^/dev/loop[0-9]+$ ]]; then
    if command -v timeout >/dev/null 2>&1; then
      timeout 10s losetup --detach "$LOOP_DEVICE" >/dev/null 2>&1 || detach_failed=1
    else
      losetup --detach "$LOOP_DEVICE" >/dev/null 2>&1 || detach_failed=1
    fi
    if (( detach_failed )); then
      printf 'execute-path gate: ERROR could not detach disposable loop device %s\n' \
        "$LOOP_DEVICE" >&2
      status=1
    fi
  fi
  if [[ -n $RUN_DIR && -d $RUN_DIR ]]; then
    rm -rf -- "$RUN_DIR" || status=1
  fi
  exit "$status"
}

trap cleanup EXIT

[[ ${AURADE_EXECUTE_PATH_TEST:-0} == 1 ]] || \
  skip 'opt_in_required_set_AURADE_EXECUTE_PATH_TEST=1_in_a_disposable_environment'
(( EUID == 0 )) || skip 'requires_root'
[[ -d /sys/firmware/efi ]] || skip 'requires_real_uefi_installer_boot_no_efi_state_fabrication'

[[ $TMP_ROOT == /* && $TMP_ROOT != / && -d $TMP_ROOT && -w $TMP_ROOT && -x $TMP_ROOT ]] || \
  skip 'AURADE_EXECUTE_PATH_TMPDIR_must_be_an_existing_writable_non_root_directory'
TMP_ROOT=$(readlink -f -- "$TMP_ROOT") || skip 'could_not_resolve_disposable_fixture_directory'
[[ $TMP_ROOT != / ]] || skip 'disposable_fixture_directory_may_not_resolve_to_root'

if [[ -n $EVIDENCE_FILE ]]; then
  [[ $EVIDENCE_FILE == /* && $EVIDENCE_FILE != / ]] || skip 'evidence_file_must_be_an_absolute_non_root_path'
  evidence_parent=$(dirname -- "$EVIDENCE_FILE")
  [[ -d $evidence_parent && -w $evidence_parent ]] || \
    skip 'evidence_file_parent_is_not_writable'
  : >>"$EVIDENCE_FILE" || skip 'evidence_file_is_not_writable'
  chmod 0600 "$EVIDENCE_FILE" || skip 'evidence_file_permissions_could_not_be_restricted'
fi

# The installer performs this complete command check before it initializes its
# journal. Missing tooling is therefore a skip, not a partial execute claim.
required_commands=(
  losetup lsblk blockdev timeout truncate bsdtar
  sgdisk wipefs partprobe udevadm mkfs.fat mkfs.btrfs mount umount btrfs
  pacman pacstrap pacman-key repo-add arch-chroot genfstab bootctl blkid tee
  gpg gpgv findmnt
)
missing_commands=()
for command in "${required_commands[@]}"; do
  command -v "$command" >/dev/null 2>&1 || missing_commands+=("$command")
done
((${#missing_commands[@]} == 0)) || \
  skip "required_tooling_unavailable_${missing_commands[*]}"

secure_boot_state=$(timeout --foreground 10s bootctl is-secure-boot 2>/dev/null || true)
[[ $secure_boot_state == disabled ]] || \
  skip 'secure_boot_state_is_not_known_disabled_no_firmware_state_fabrication'

RUN_DIR=$(mktemp -d "$TMP_ROOT/aurade-execute-path.XXXXXX") || \
  skip 'could_not_create_disposable_fixture_directory'
chmod 0700 "$RUN_DIR"
install -d -m 0755 "$RUN_DIR/repo" "$RUN_DIR/package" "$RUN_DIR/work" \
  "$RUN_DIR/failure-evidence" "$RUN_DIR/mnt"

# These are metadata-only package archives used to get through the installer's
# input checks. --allow-unsigned is explicit; this fixture never creates or
# verifies a signing key, detached signature, or repository keyring.
make_package() {
  local name=$1 filename digest
  printf 'pkgname = %s\npkgver = 1.0-1\narch = any\n' "$name" \
    >"$RUN_DIR/package/.PKGINFO"
  filename=${name}-1.0-1-any.pkg.tar.zst
  bsdtar -cf "$RUN_DIR/repo/$filename" -C "$RUN_DIR/package" .PKGINFO
  digest=$(sha256sum "$RUN_DIR/repo/$filename" | awk '{print $1}')
  printf '%s %s %s 1.0-1 any\n' "$digest" "$filename" "$name" \
    >>"$RUN_DIR/packages.lock.unsorted"
}

make_package aurade
make_package chromiumos-ash
{
  printf '%s\n' '# sha256 filename pkgname pkgver arch'
  LC_ALL=C sort -k3,3 "$RUN_DIR/packages.lock.unsorted"
} >"$RUN_DIR/packages.lock"
printf '%s\n' "\$6\$fixture\$not-a-plaintext-password" >"$RUN_DIR/password.hash"
chmod 0600 "$RUN_DIR/password.hash"

# A sparse 16-GiB backing file is the only target this fixture may attach. The
# installer sees a real loop block device, but no partition, filesystem, or
# mount is fabricated by this script.
IMAGE=$RUN_DIR/disposable-target.img
truncate -s 17179869184 "$IMAGE"
loop_output=
if ! loop_output=$(timeout 10s losetup --find --show --partscan "$IMAGE" 2>"$RUN_DIR/losetup.err"); then
  attached_loop=$(losetup -j "$IMAGE" 2>/dev/null | sed -n 's#^\(/dev/loop[0-9]*\):.*#\1#p' | head -1)
  [[ $attached_loop =~ ^/dev/loop[0-9]+$ ]] && LOOP_DEVICE=$attached_loop
  skip 'loop_device_attach_unavailable_permission_or_kernel_support'
fi
if [[ $loop_output =~ ^/dev/loop[0-9]+$ ]]; then
  LOOP_DEVICE=$loop_output
else
  attached_loop=$(losetup -j "$IMAGE" 2>/dev/null | sed -n 's#^\(/dev/loop[0-9]*\):.*#\1#p' | head -1)
  [[ $attached_loop =~ ^/dev/loop[0-9]+$ ]] && LOOP_DEVICE=$attached_loop
  skip 'losetup_did_not_return_a_loop_device'
fi
[[ $(lsblk -dnro TYPE "$LOOP_DEVICE") == loop ]] || skip 'attached_target_is_not_a_loop_device'
[[ $(blockdev --getsize64 "$LOOP_DEVICE") == 17179869184 ]] || \
  skip 'disposable_loop_device_size_did_not_match_16_GiB_boundary'
[[ $(losetup -j "$IMAGE" | cut -d: -f1) == "$LOOP_DEVICE" ]] || \
  skip 'loop_backing_file_identity_could_not_be_verified'

before_tree=$(lsblk -lnpo NAME,TYPE "$LOOP_DEVICE")
if findmnt -rn -S "$LOOP_DEVICE" 2>/dev/null | grep -q .; then
  skip 'new_disposable_loop_device_is_already_mounted'
fi

JOURNAL=$RUN_DIR/journal.jsonl
RAW_LOG=$RUN_DIR/install.log
WORK_PARENT=$RUN_DIR/work
MOUNTPOINT=$RUN_DIR/mnt

# Force the real installer to fail at its disk-backed staging capacity check,
# after execute-mode preflight and journal initialization but before acquire,
# wipefs, partitioning, filesystem creation, mounting, or bootloader work.
set +e
AURADE_EXECUTE_PATH_TEST=1 \
AURADE_FAILURE_JOURNAL_DIR="$RUN_DIR/failure-evidence" \
AURADE_INSTALL_WORK_DIR="$WORK_PARENT" \
AURADE_JOURNAL_PATH="$JOURNAL" \
AURADE_JOURNAL_RAW="$RAW_LOG" \
AURADE_MIN_WORKSPACE_BYTES=999999999999999999 \
  timeout --foreground 30s "$INSTALLER" \
    --target "$LOOP_DEVICE" \
    --allow-loop \
    --execute \
    --confirm "ERASE:$LOOP_DEVICE" \
    --username audit \
    --password-hash-file "$RUN_DIR/password.hash" \
    --arch-snapshot 2026/07/12 \
    --bundle-dir "$RUN_DIR/repo" \
    --package-lock "$RUN_DIR/packages.lock" \
    --allow-unsigned \
    --mountpoint "$MOUNTPOINT" \
    >"$RUN_DIR/installer.out" 2>&1
installer_status=$?
set -e
[[ $installer_status -eq 1 ]] || {
  cat "$RUN_DIR/installer.out" >&2
  printf 'execute-path gate: expected capacity-boundary failure, got exit %s\n' \
    "$installer_status" >&2
  exit 1
}

grep -Fq 'installer staging filesystem has ' "$RUN_DIR/installer.out"
grep -Fq 'choose a disk-backed AURADE_INSTALL_WORK_DIR' "$RUN_DIR/installer.out"
for forbidden in \
  'wipefs --all' 'sgdisk ' 'mkfs.' ' mount ' 'pacman ' 'pacstrap ' \
  'bootctl ' 'cryptsetup '; do
  ! grep -Fq -- "$forbidden" "$RUN_DIR/installer.out" || {
    echo "execute-path fixture reached forbidden operation: $forbidden" >&2
    exit 1
  }
done

[[ -r $JOURNAL && $(stat -c '%a' "$JOURNAL") == 600 ]]
python3 - "$JOURNAL" "$LOOP_DEVICE" <<'PY'
import json
import sys

journal_path, target = sys.argv[1:]
records = [json.loads(line) for line in open(journal_path) if line.strip()]
assert [record["stage"] for record in records] == ["start", "preflight", "preflight"]
assert records[-1]["status"] == "ok"
assert all(record["target"]["path"] == target for record in records)
assert all(record["target"]["size_bytes"] == 17179869184 for record in records)
PY

mapfile -t preserved_journals < <(
  find "$RUN_DIR/failure-evidence" -mindepth 2 -maxdepth 2 -type f \
    -name journal.jsonl -print
)
[[ ${#preserved_journals[@]} -eq 1 ]]
[[ $(stat -c '%a' "${preserved_journals[0]}") == 600 ]]
cmp -s "$JOURNAL" "${preserved_journals[0]}"
mapfile -t leftover_workdirs < <(
  find "$RUN_DIR/work" -mindepth 1 -maxdepth 1 -type d \
    -name 'aurade-install.*' -print
)
[[ ${#leftover_workdirs[@]} -eq 0 ]]
[[ ! -e "$MOUNTPOINT/boot" ]]
[[ -z $(findmnt -rn -S "$LOOP_DEVICE" 2>/dev/null || true) ]]
after_tree=$(lsblk -lnpo NAME,TYPE "$LOOP_DEVICE")
[[ $after_tree == "$before_tree" ]]

record "execute_path_gate status=pass executed=true full_install_claim=false scope=pre_acquisition_capacity_failure_cleanup target=$LOOP_DEVICE"
record 'execute_path_gate note=full_install_partition_filesystem_pacstrap_first_boot_and_rollback_evidence_remain_open'
