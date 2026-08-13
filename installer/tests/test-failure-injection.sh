#!/usr/bin/env bash
# Safe refusal-path fixtures. None of these cases reaches an execute path or
# opens a block device; they prove bad inputs fail before a destructive plan.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
install -d -m 0755 "$TMP/repo" "$TMP/package"
install -d -m 0755 "$TMP/original"

make_package() {
  local name=$1 filename digest
  printf 'pkgname = %s\npkgver = 1.0-1\narch = any\n' "$name" >"$TMP/package/.PKGINFO"
  filename=${name}-1.0-1-any.pkg.tar.zst
  bsdtar -cf "$TMP/repo/$filename" -C "$TMP/package" .PKGINFO
  digest=$(sha256sum "$TMP/repo/$filename" | awk '{print $1}')
  printf '%s %s %s 1.0-1 any\n' "$digest" "$filename" "$name"
}

{
  printf '%s\n' '# sha256 filename pkgname pkgver arch'
  make_package aurade
  make_package chromiumos-ash
} >"$TMP/packages.lock"
cp "$TMP/repo/aurade-1.0-1-any.pkg.tar.zst" "$TMP/original/"
printf '%s\n' '$6$audit$not-a-plaintext-password' >"$TMP/password.hash"
chmod 0600 "$TMP/password.hash"

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

# Corrupt a locked package after the digest was recorded.
printf 'corruption' >>"$TMP/repo/aurade-1.0-1-any.pkg.tar.zst"
if "$ROOT/installer/bin/aurade-install" "${common[@]}" >"$TMP/hash.out" 2>&1; then
  echo 'tampered package unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'SHA-256 mismatch: aurade-1.0-1-any.pkg.tar.zst' "$TMP/hash.out"
! grep -Fq 'wipefs --all --force' "$TMP/hash.out"

# Restore the exact package whose digest is recorded in the lock, then reject
# a password file with unsafe permissions.
cp "$TMP/original/aurade-1.0-1-any.pkg.tar.zst" "$TMP/repo/"
chmod 0644 "$TMP/password.hash"
if "$ROOT/installer/bin/aurade-install" "${common[@]}" >"$TMP/perms.out" 2>&1; then
  echo 'insecure password file unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'password hash file must not be group/world accessible' "$TMP/perms.out"
! grep -Fq 'wipefs --all --force' "$TMP/perms.out"

# An invalid target is rejected before any package or disk operation.
chmod 0600 "$TMP/password.hash"
if "$ROOT/installer/bin/aurade-install" "${common[@]}" --target relative-disk >"$TMP/target.out" 2>&1; then
  echo 'invalid target unexpectedly passed' >&2
  exit 1
fi
grep -Fq -- '--target must be an absolute /dev path' "$TMP/target.out"
! grep -Fq 'wipefs --all --force' "$TMP/target.out"

echo 'installer failure-injection test: PASS'
