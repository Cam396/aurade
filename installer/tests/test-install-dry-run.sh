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
grep -Fq -- '/boot/aurade-rollback/factory/vmlinuz-linux' "$TMP/plain.out"
grep -Fq -- 'intel-ucode' "$TMP/plain.out"
grep -Fq -- 'amd-ucode' "$TMP/plain.out"
grep -Fq -- 'sof-firmware' "$TMP/plain.out"
grep -Fq -- 'file:///var/cache/aurade/repo' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'pacstrap -M -G -C' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'GPGDir = ${ARCH_GPG_DIR}' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'pacman-key --gpgdir "$ARCH_GPG_DIR" --populate archlinux' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'package downloads were stopped instead of being retried' "$ROOT/installer/bin/aurade-install"
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
