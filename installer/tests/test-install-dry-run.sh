#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
install -d -m 0755 "$TMP/repo" "$TMP/package"

make_package() {
  local name=$1 filename digest
  printf 'pkgname = %s\npkgver = 1.0-1\narch = any\n' "$name" \
    >"$TMP/package/.PKGINFO"
  filename=${name}-1.0-1-any.pkg.tar.zst
  bsdtar -cf "$TMP/repo/$filename" -C "$TMP/package" .PKGINFO
  digest=$(sha256sum "$TMP/repo/$filename" | awk '{print $1}')
  printf '%s %s %s 1.0-1 any\n' "$digest" "$filename" "$name" \
    >>"$TMP/packages.lock.unsorted"
}

make_package aurade
make_package chromiumos-ash
{
  printf '%s\n' '# sha256 filename pkgname pkgver arch'
  LC_ALL=C sort -k3,3 "$TMP/packages.lock.unsorted"
} >"$TMP/packages.lock"
printf '%s\n' "\$6\$audit\$not-a-plaintext-password" >"$TMP/password.hash"
printf '%s\n' 'audit-passphrase' >"$TMP/luks.passphrase"
chmod 0600 "$TMP/password.hash" "$TMP/luks.passphrase"

common=(
  --target /dev/aurade-test-disk
  --username audit
  --password-hash-file "$TMP/password.hash"
  --arch-snapshot 2026/07/12
  --bundle-dir "$TMP/repo"
  --package-lock "$TMP/packages.lock"
  --allow-unsigned
  --dry-run
)

if ! "$ROOT/installer/bin/aurade-install" "${common[@]}" \
    >"$TMP/plain.out" 2>&1; then
  cat "$TMP/plain.out" >&2
  exit 1
fi
grep -Fq -- '--typecode=2:8300' "$TMP/plain.out"
grep -Fq -- 'aurade-powerd.service aurade-host-bridge.service aurade-greetd.service' \
  "$TMP/plain.out"
grep -Fq -- 'seatd.service aurade-powerd.service' "$TMP/plain.out"
grep -Fq -- 'useradd -m -G wheel\,audio\,video\,input\,storage\,seat' "$TMP/plain.out"
grep -Fq -- 'chpasswd --encrypted' "$ROOT/installer/bin/aurade-install"
! grep -Fq -- 'usermod --password "$(<"$PASSWORD_HASH_FILE")"' \
  "$ROOT/installer/bin/aurade-install"
grep -Fq -- '/boot/aurade-rollback/factory/vmlinuz-linux' "$TMP/plain.out"
grep -Fq -- 'intel-ucode' "$TMP/plain.out"
grep -Fq -- 'amd-ucode' "$TMP/plain.out"
grep -Fq -- 'sof-firmware' "$TMP/plain.out"
grep -Fq -- 'file:///var/cache/aurade/repo' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'pacstrap -M -G -C' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'GPGDir = ${ARCH_GPG_DIR}' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'LocalFileSigLevel = Required' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'pacman-key --gpgdir "$ARCH_GPG_DIR" --populate archlinux' "$ROOT/installer/bin/aurade-install"
grep -Fq -- '/usr/share/pacman/keyrings/archlinux.gpg' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'gpgv --keyring "$ARCH_GPG_DIR/pubring.gpg"' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'invalid Arch package signature' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'cause=keyring_error' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'cause=capacity_error' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'cause=network_error' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'aurade_journal_fail "$_J_ACTIVE_STAGE" "$status" cancelled' \
  "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'trap '\''handle_cancel 130'\'' INT' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'journal_message=${message:0:256}' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'without touching the target disk' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'private keys excluded' "$TMP/plain.out"
grep -Fq -- 'package downloads were stopped instead of being retried' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'installer staging filesystem has ' "$TMP/plain.out"
grep -Fq -- 'choose a disk-backed AURADE_INSTALL_WORK_DIR' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'Secure Boot is enabled' "$ROOT/installer/bin/aurade-installer"
grep -Fq -- 'Secure Boot state could not be determined' "$ROOT/installer/bin/aurade-installer"
grep -Fq -- 'could not determine Secure Boot state' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'aurade_valid_arch_snapshot "$snapshot"' "$ROOT/installer/bin/aurade-installer"
grep -Fq -- '"$NETWORK_DIAGNOSTICS" --snapshot "$snapshot"' "$ROOT/installer/bin/aurade-installer"
grep -Fq -- 'select an exact PATH from the table above' "$ROOT/installer/bin/aurade-installer"
grep -Fq -- 'lsblk -dnro TYPE "$target"' "$ROOT/installer/bin/aurade-installer"
# The rules themselves are exercised by test-prompt-validation.sh against
# fixture roots. Assert only that the front end delegates to them instead of
# re-implementing the checks inline, where they cannot be tested.
grep -Fq -- 'aurade_valid_hostname "$hostname"' "$ROOT/installer/bin/aurade-installer"
grep -Fq -- 'aurade_valid_username "$username"' "$ROOT/installer/bin/aurade-installer"
grep -Fq -- 'aurade_valid_timezone "$timezone"' "$ROOT/installer/bin/aurade-installer"
grep -Fq -- 'aurade_valid_locale "$locale"' "$ROOT/installer/bin/aurade-installer"
grep -Fq -- 'aurade_valid_keymap "$keymap"' "$ROOT/installer/bin/aurade-installer"
grep -Fq -- 'loadkeys "$keymap"' "$ROOT/installer/bin/aurade-installer"
grep -Fq -- 'confirmation=$(aurade_normalize_confirmation "$confirmation")' "$ROOT/installer/bin/aurade-installer"
grep -Fq -- 'Timezone must name an installed zone' "$ROOT/installer/bin/aurade-installer"
grep -Fq -- 'Locale must name an installed locale' "$ROOT/installer/bin/aurade-installer"
grep -Fq -- 'Keyboard layout must name an installed keymap' "$ROOT/installer/bin/aurade-installer"
grep -Fq -- 'USB/removable disk' "$ROOT/installer/bin/aurade-installer"
grep -Fq -- 'smartctl -H "$target"' "$ROOT/installer/bin/aurade-installer"
grep -Fq -- 'smartctl is unavailable' "$ROOT/installer/bin/aurade-installer"
grep -Fq -- 'SMART reported a failing health status' "$ROOT/installer/bin/aurade-installer"
grep -Fq -- 'SMART health: passed' "$ROOT/installer/bin/aurade-installer"
grep -Fq -- 'does not replace a backup' "$ROOT/installer/bin/aurade-installer"
grep -Fq -- 'LUKS2 encryption and Btrfs recovery snapshots consume additional space' \
  "$ROOT/installer/bin/aurade-installer"
grep -Fq -- 'no swap or hibernation setup is created by default' "$ROOT/installer/bin/aurade-installer"
grep -Fq -- 'read_secret_file' "$ROOT/installer/bin/aurade-installer"
grep -Fq -- 'openssl passwd -6 -stdin <"$secret_dir/password"' "$ROOT/installer/bin/aurade-installer"
grep -Fq -- 'secure_remove "$secret_dir/password"' "$ROOT/installer/bin/aurade-installer"
! grep -Fq -- 'read -r -s -p '\''Account password: '\'' password' "$ROOT/installer/bin/aurade-installer"
acquire_line=$(grep -n -- '--disable-sandbox -Syy' "$TMP/plain.out" | head -1 | cut -d: -f1)
wipe_line=$(grep -n -- 'wipefs --all --force' "$TMP/plain.out" | head -1 | cut -d: -f1)
(( acquire_line < wipe_line ))
if grep -Fq -- 'cryptsetup luksFormat' "$TMP/plain.out"; then
  echo 'unencrypted plan unexpectedly formats LUKS' >&2
  exit 1
fi

if ! "$ROOT/installer/bin/aurade-install" "${common[@]}" --encrypt \
    --luks-passphrase-file "$TMP/luks.passphrase" >"$TMP/encrypted.out" 2>&1; then
  cat "$TMP/encrypted.out" >&2
  exit 1
fi
grep -Fq -- '--typecode=2:8309' "$TMP/encrypted.out"
grep -Fq -- 'cryptsetup luksFormat --type luks2 --batch-mode' "$TMP/encrypted.out"
grep -Fq -- '/boot/aurade-rollback/factory/initramfs-linux.img' "$TMP/encrypted.out"

# ---------------------------------------------------------------------------
# Storage shape
#
# The default is the only shape this product shipped before these options
# existed, and the first assertion here is that it did not move: no swap file,
# a Btrfs root, subvolumes, a factory snapshot and a rollback entry. Everything
# after it checks that choosing something else actually changes the plan, and -
# more importantly - that the consequences of choosing it are carried through
# rather than left as a half-configured system.
# ---------------------------------------------------------------------------

! grep -Fq -- 'mkswap' "$TMP/plain.out"
! grep -Fq -- 'mkswapfile' "$TMP/plain.out"
! grep -Fq -- 'zram' "$TMP/plain.out"
grep -Fq -- 'mkfs.btrfs' "$TMP/plain.out"
grep -Fq -- 'btrfs subvolume create' "$TMP/plain.out"
grep -Fq -- 'boot options: root=UUID=<root-filesystem-uuid> rw rootflags=subvol=@ quiet' "$TMP/plain.out"

plan() {
  local name=$1
  shift
  if ! "$ROOT/installer/bin/aurade-install" "${common[@]}" "$@" \
      >"$TMP/$name.out" 2>&1; then
    echo "dry run failed: $name" >&2
    cat "$TMP/$name.out" >&2
    exit 1
  fi
}

refuses() {
  local expected=$1
  shift
  if "$ROOT/installer/bin/aurade-install" "${common[@]}" "$@" \
      >"$TMP/refusal.out" 2>&1; then
    echo "expected a refusal for: $*" >&2
    exit 1
  fi
  grep -Fq -- "$expected" "$TMP/refusal.out" || {
    echo "wrong refusal for: $*" >&2
    cat "$TMP/refusal.out" >&2
    exit 1
  }
}

# A swap file on Btrfs must be made by mkswapfile, which is the call that turns
# copy-on-write and compression off. fallocate plus mkswap produces a file the
# kernel refuses to swap to, so the tool used here is the assertion.
plan swapfile --swap file --swap-size 4G
grep -Fq -- 'btrfs filesystem mkswapfile --size 4096m' "$TMP/swapfile.out"
grep -Fq -- '/swap/swapfile none swap defaults 0 0' "$TMP/swapfile.out"
! grep -Fq -- 'resume_offset' "$TMP/swapfile.out"

plan hibernate --swap file --swap-size hibernate
grep -Fq -- 'resume=UUID=<root-filesystem-uuid> resume_offset=<swapfile-offset>' "$TMP/hibernate.out"
grep -Fq -- 'add the mkinitcpio resume hook' "$TMP/hibernate.out"

plan zram --swap zram
grep -Fq -- 'zram-generator.conf' "$TMP/zram.out"
! grep -Fq -- 'mkswapfile' "$TMP/zram.out"

# ext4 has no subvolumes, so it has no factory snapshot; the rollback entry
# must be absent rather than present and broken.
plan ext4 --filesystem ext4
grep -Fq -- 'mkfs.ext4' "$TMP/ext4.out"
! grep -Fq -- 'btrfs subvolume create' "$TMP/ext4.out"
! grep -Fq -- 'aurade-rollback.conf' "$TMP/ext4.out"
! grep -Fq -- 'rootflags=subvol=@' "$TMP/ext4.out"
grep -Fq -- 'boot options: root=UUID=<root-filesystem-uuid> rw quiet' "$TMP/ext4.out"
grep -Fq -- 'no factory snapshot and no rollback boot entry' "$TMP/ext4.out"

plan xfs --filesystem xfs
grep -Fq -- 'mkfs.xfs' "$TMP/xfs.out"

# Installing alongside must not wipe, must not zap, and must not reformat the
# EFI system partition it was asked to share.
plan alongside --layout alongside
! grep -Fq -- 'wipefs --all --force' "$TMP/alongside.out"
! grep -Fq -- 'sgdisk --zap-all' "$TMP/alongside.out"
! grep -Fq -- 'mkfs.fat' "$TMP/alongside.out"
grep -Fq -- 'sgdisk --largest-new=0' "$TMP/alongside.out"
grep -Fq -- 'keeping the existing EFI system partition' "$TMP/alongside.out"
grep -Fq -- 'INSTALL:/dev/aurade-test-disk' "$TMP/alongside.out"
grep -Fq -- 'ERASE:/dev/aurade-test-disk' "$TMP/plain.out"

refuses '--filesystem must be btrfs, ext4 or xfs' --filesystem zfs
refuses '--swap must be none, file or zram' --swap partition
refuses '--swap-size must be auto, hibernate, or a size like 8G' --swap-size huge
refuses '--layout must be wipe or alongside' --layout resize
refuses 'zram swap cannot support hibernation' --swap zram --swap-size hibernate
refuses 'which xfs does not provide' --filesystem xfs --swap file --swap-size hibernate

echo 'installer dry-run test: PASS'
