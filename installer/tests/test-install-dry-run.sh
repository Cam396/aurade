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
grep -Fq -- 'without touching the target disk' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'private keys excluded' "$TMP/plain.out"
grep -Fq -- 'package downloads were stopped instead of being retried' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'installer staging filesystem has ' "$TMP/plain.out"
grep -Fq -- 'choose a disk-backed AURADE_INSTALL_WORK_DIR' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'Secure Boot is enabled' "$ROOT/installer/bin/aurade-installer"
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
grep -Fq -- 'Timezone must name an installed zone' "$ROOT/installer/bin/aurade-installer"
grep -Fq -- 'Locale must name an installed locale' "$ROOT/installer/bin/aurade-installer"
grep -Fq -- 'Keyboard layout must name an installed keymap' "$ROOT/installer/bin/aurade-installer"
grep -Fq -- 'USB/removable disk' "$ROOT/installer/bin/aurade-installer"
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

echo 'installer dry-run test: PASS'
