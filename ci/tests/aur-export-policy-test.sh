#!/usr/bin/env bash
# Check AUR export safety without makepkg, network, or a package build.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
chmod 0755 "$TMP"
digest=$(printf '0%.0s' {1..64})

AURADE_AUR_OUTPUT="$TMP/aur" \
  AURADE_AUR_ARCHIVE_SHA256="$digest" \
  "$ROOT/ci/export-aur-bundles.sh" >"$TMP/export.out"

count=$(find "$TMP/aur" -mindepth 1 -maxdepth 1 -type d | wc -l)
[[ $count -eq 11 ]] || {
  echo "expected 11 AUR package directories, found $count" >&2
  exit 1
}
pkgver=$(awk -F= '$1 == "pkgver" {print $2; exit}' "$ROOT/chromiumos-ash/PKGBUILD")
pkgrel=$(awk -F= '$1 == "pkgrel" {print $2; exit}' "$ROOT/chromiumos-ash/PKGBUILD")
grep -Fq "pkgver=${pkgver}" "$TMP/aur/chromiumos-ash-bin/PKGBUILD"
grep -Fq "pkgrel=${pkgrel}" "$TMP/aur/chromiumos-ash-bin/PKGBUILD"
grep -Fq "sha256sums=('$digest')" "$TMP/aur/chromiumos-ash-bin/PKGBUILD"
grep -Fq 'chromiumos-ash-${pkgver}-${pkgrel}-${CARCH}.pkg.tar.*' \
  "$TMP/aur/chromiumos-ash-bin/PKGBUILD"
grep -Fq 'expected exactly one Chromium payload' \
  "$TMP/aur/chromiumos-ash-bin/PKGBUILD"
if find "$TMP/aur" -type f -size +50M -print -quit | grep -q .; then
  echo 'AUR export fixture contains an oversized file' >&2
  exit 1
fi

echo 'AUR export policy test: PASS'
