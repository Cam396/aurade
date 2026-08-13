#!/usr/bin/env bash
# Exercise the signed repository staging path with a disposable fixture key.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
install -d -m 0700 "$TMP/gnupg" "$TMP/repo" "$TMP/package"

gpg --batch --quiet --homedir "$TMP/gnupg" --passphrase '' \
  --quick-gen-key 'AuraDE test fixture <fixture@example.invalid>' rsa2048 sign 1d \
  >/dev/null 2>&1
fingerprint=$(gpg --batch --homedir "$TMP/gnupg" --with-colons --list-secret-keys |
  awk -F: '$1 == "fpr" {print $10; exit}')
[[ $fingerprint =~ ^[0-9A-Fa-f]{40}$ ]]
gpg --batch --quiet --homedir "$TMP/gnupg" --export "$fingerprint" >"$TMP/test-key.gpg"

while IFS= read -r name; do
  [[ -n $name ]] || continue
  printf 'pkgname = %s\npkgver = 1.0-1\narch = any\n' "$name" >"$TMP/package/.PKGINFO"
  package="$TMP/repo/${name}-1.0-1-any.pkg.tar.zst"
  bsdtar -cf "$package" -C "$TMP/package" .PKGINFO
  gpg --batch --quiet --homedir "$TMP/gnupg" --passphrase '' \
    --local-user "$fingerprint" --detach-sign --output "$package.sig" "$package"
done <"$ROOT/installer/expected-packages.txt"

env \
  AURADE_ARCH_SNAPSHOT=2026/07/12 \
  AURADE_REPO_DIR="$TMP/repo" \
  AURADE_REPO_KEY="$TMP/test-key.gpg" \
  AURADE_REPO_FINGERPRINT="$fingerprint" \
  AURADE_INSTALLER_WORK_ROOT="$TMP/work" \
  "$ROOT/installer/build-iso.sh" --stage-only >"$TMP/stage.out"

staged=$TMP/work/profile/airootfs/opt/aurade/repo
expected=$(grep -Evc '^[[:space:]]*(#|$)' "$ROOT/installer/expected-packages.txt")
actual=$(find "$staged" -maxdepth 1 -type f -name '*.pkg.tar.*.sig' | wc -l)
[[ $actual -eq $expected ]]
[[ -r $staged/aurade-repository.gpg ]]
grep -Fxq "$fingerprint" "$TMP/work/profile/airootfs/etc/aurade-installer/repo-fingerprint"
! grep -Fq 'development-unsigned' "$TMP/work/profile/airootfs/etc/aurade-installer/repo-fingerprint"

# A detached signature that is present but corrupted must fail closed before
# the profile is accepted. This exercises the real gpgv path with only the
# disposable fixture key.
first_package=$(find "$TMP/repo" -maxdepth 1 -type f -name '*.pkg.tar.zst.sig' -print -quit)
printf '%s\n' 'corrupted signature' >>"$first_package"
if env \
  AURADE_ARCH_SNAPSHOT=2026/07/12 \
  AURADE_REPO_DIR="$TMP/repo" \
  AURADE_REPO_KEY="$TMP/test-key.gpg" \
  AURADE_REPO_FINGERPRINT="$fingerprint" \
  AURADE_INSTALLER_WORK_ROOT="$TMP/work-invalid-signature" \
  "$ROOT/installer/build-iso.sh" --stage-only >"$TMP/invalid-signature.out" 2>&1; then
  echo 'corrupted package signature unexpectedly staged' >&2
  exit 1
fi
grep -Fq 'invalid signature' "$TMP/invalid-signature.out"

echo 'signed ISO staging test: PASS'
