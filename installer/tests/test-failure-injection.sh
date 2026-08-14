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
printf '%s\n' 'audit-passphrase' >"$TMP/luks.passphrase"
chmod 0600 "$TMP/luks.passphrase"
export AURADE_JOURNAL_PATH="$TMP/journal.jsonl" AURADE_JOURNAL_RAW="$TMP/install.log"

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

# A digest can be correct while the archive metadata is for another package.
# The engine must inspect .PKGINFO and reject the mismatch before any target
# operation, rather than trusting the lock's name fields.
printf 'pkgname = forged-package\npkgver = 1.0-1\narch = any\n' >"$TMP/package/.PKGINFO"
bsdtar -cf "$TMP/repo/aurade-1.0-1-any.pkg.tar.zst" -C "$TMP/package" .PKGINFO
bad_digest=$(sha256sum "$TMP/repo/aurade-1.0-1-any.pkg.tar.zst" | awk '{print $1}')
awk -v digest="$bad_digest" '$2 == "aurade-1.0-1-any.pkg.tar.zst" {$1=digest} {print}' \
  OFS=' ' "$TMP/packages.lock" >"$TMP/bad-metadata.lock"
if "$ROOT/installer/bin/aurade-install" "${common[@]}" \
    --package-lock "$TMP/bad-metadata.lock" >"$TMP/metadata.out" 2>&1; then
  echo 'mismatched package metadata unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'package metadata does not match lock' "$TMP/metadata.out"
! grep -Fq 'wipefs --all --force' "$TMP/metadata.out"

# A package archive without .PKGINFO must fail closed as well.
printf 'not package metadata\n' >"$TMP/package/README"
rm -f -- "$TMP/package/.PKGINFO"
bsdtar -cf "$TMP/repo/aurade-1.0-1-any.pkg.tar.zst" -C "$TMP/package" README
missing_digest=$(sha256sum "$TMP/repo/aurade-1.0-1-any.pkg.tar.zst" | awk '{print $1}')
awk -v digest="$missing_digest" '$2 == "aurade-1.0-1-any.pkg.tar.zst" {$1=digest} {print}' \
  OFS=' ' "$TMP/packages.lock" >"$TMP/missing-metadata.lock"
if "$ROOT/installer/bin/aurade-install" "${common[@]}" \
    --package-lock "$TMP/missing-metadata.lock" >"$TMP/missing-metadata.out" 2>&1; then
  echo 'missing package metadata unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'cannot read .PKGINFO' "$TMP/missing-metadata.out"
! grep -Fq 'wipefs --all --force' "$TMP/missing-metadata.out"

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

# Plaintext and multi-line credential files are rejected without reading a
# secret into a shell variable or reaching the destructive plan.
chmod 0600 "$TMP/password.hash"
printf '%s\n%s\n' 'plaintext-password' 'second-line' >"$TMP/password.hash"
if "$ROOT/installer/bin/aurade-install" "${common[@]}" >"$TMP/plaintext.out" 2>&1; then
  echo 'plaintext password unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'password hash must be a single crypt(3) hash' "$TMP/plaintext.out"
! grep -Fq 'wipefs --all --force' "$TMP/plaintext.out"

# A single malformed crypt-looking line is rejected too; the old prefix-only
# check would have let this reach chpasswd during a real install.
printf '%s\n' '$bogus' >"$TMP/password.hash"
if "$ROOT/installer/bin/aurade-install" "${common[@]}" >"$TMP/malformed-hash.out" 2>&1; then
  echo 'malformed password hash unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'password hash must be a single crypt(3) hash' "$TMP/malformed-hash.out"
! grep -Fq 'wipefs --all --force' "$TMP/malformed-hash.out"

printf '%s\n' '$6$audit$not-a-plaintext-password' >"$TMP/password.hash"

# Encryption secrets use the same refusal boundary as account credentials.
chmod 0644 "$TMP/luks.passphrase"
if "$ROOT/installer/bin/aurade-install" "${common[@]}" --encrypt \
    --luks-passphrase-file "$TMP/luks.passphrase" >"$TMP/luks-perms.out" 2>&1; then
  echo 'insecure LUKS passphrase file unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'LUKS passphrase file must not be group/world accessible' "$TMP/luks-perms.out"
! grep -Fq 'wipefs --all --force' "$TMP/luks-perms.out"

# An invalid target is rejected before any package or disk operation.
if "$ROOT/installer/bin/aurade-install" "${common[@]}" --target relative-disk >"$TMP/target.out" 2>&1; then
  echo 'invalid target unexpectedly passed' >&2
  exit 1
fi
grep -Fq -- '--target must be an absolute /dev path' "$TMP/target.out"
! grep -Fq 'wipefs --all --force' "$TMP/target.out"

# A staged installer missing its recovery helper must fail before it can read
# or modify a target. Use a copied engine so the real source tree is untouched.
install -d -m 0755 "$TMP/engine/lib"
cp "$ROOT/installer/bin/aurade-install" "$TMP/engine/aurade-install"
cp "$ROOT/installer/lib/aurade-journal.sh" "$TMP/engine/lib/aurade-journal.sh"
chmod 0755 "$TMP/engine/aurade-install"
if AURADE_JOURNAL_LIB="$TMP/engine/lib/aurade-journal.sh" \
  "$TMP/engine/aurade-install" "${common[@]}" >"$TMP/helper.out" 2>&1; then
  echo 'missing helper unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'installer helper is missing' "$TMP/helper.out"
! grep -Fq 'wipefs --all --force' "$TMP/helper.out"

# A readable directory must not satisfy the staged-helper contract. This
# catches a malformed image before the engine can reach any destructive stage.
rm -f -- "$TMP/engine/aurade-recovery"
mkdir -m 0755 "$TMP/engine/aurade-recovery"
if AURADE_JOURNAL_LIB="$TMP/engine/lib/aurade-journal.sh" \
  "$TMP/engine/aurade-install" "${common[@]}" >"$TMP/helper-directory.out" 2>&1; then
  echo 'helper directory unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'installer helper must be a regular executable file' "$TMP/helper-directory.out"
! grep -Fq 'wipefs --all --force' "$TMP/helper-directory.out"

# A symlink to an executable outside the staged engine must not satisfy the
# helper contract. The staged image must contain the helper as a regular file.
rm -rf -- "$TMP/engine/aurade-recovery"
ln -s "$ROOT/installer/bin/aurade-recovery" "$TMP/engine/aurade-recovery"
if AURADE_JOURNAL_LIB="$TMP/engine/lib/aurade-journal.sh" \
  "$TMP/engine/aurade-install" "${common[@]}" >"$TMP/helper-symlink.out" 2>&1; then
  echo 'helper symlink unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'installer helper must be a regular executable file' "$TMP/helper-symlink.out"
! grep -Fq 'wipefs --all --force' "$TMP/helper-symlink.out"

# If the requested staging path cannot be used, the engine falls back to /tmp
# and measures capacity on the filesystem that actually holds its workdir.
touch "$TMP/not-a-directory"
if ! AURADE_INSTALL_WORK_DIR="$TMP/not-a-directory" \
  "$ROOT/installer/bin/aurade-install" "${common[@]}" >"$TMP/fallback.out" 2>&1; then
  cat "$TMP/fallback.out" >&2
  exit 1
fi
grep -Fq 'could not use ' "$TMP/fallback.out"
grep -Fq 'installer staging filesystem has ' "$TMP/fallback.out"

# A disk-backed staging requirement that cannot fit must fail before package
# acquisition, making low-memory/tmpfs failures actionable and bounded.
if AURADE_MIN_WORKSPACE_BYTES=999999999999999999 \
  "$ROOT/installer/bin/aurade-install" "${common[@]}" >"$TMP/capacity.out" 2>&1; then
  echo 'impossible staging capacity unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'choose a disk-backed AURADE_INSTALL_WORK_DIR' "$TMP/capacity.out"
! grep -Fq -- '--disable-sandbox -Syy' "$TMP/capacity.out"
! grep -Fq 'wipefs --all --force' "$TMP/capacity.out"

# The encrypted execute path must reject a missing cryptsetup dependency
# before the first erase command. This source-order assertion is intentionally
# synthetic: proving the command itself would require a disposable target and
# is outside the safe refusal suite's no-device boundary.
grep -Fq -- "required command not found: cryptsetup" "$ROOT/installer/bin/aurade-install"
cryptsetup_check_line=$(grep -n -- "required command not found: cryptsetup" \
  "$ROOT/installer/bin/aurade-install" | head -1 | cut -d: -f1)
wipe_line=$(grep -n -- 'wipefs --all --force' "$ROOT/installer/bin/aurade-install" | head -1 | cut -d: -f1)
(( cryptsetup_check_line < wipe_line ))

echo 'installer failure-injection test: PASS'
