#!/usr/bin/env bash
# Check AUR export safety without makepkg, network, or a package build.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
chmod 0755 "$TMP"
digest=$(printf '0%.0s' {1..64})
ash=$(printf 'a%.0s' {1..64})
fail() { echo "aur-export-policy: $*" >&2; exit 1; }

AURADE_AUR_OUTPUT="$TMP/aur" AURADE_AUR_REF=v9.9.9 \
  AURADE_AUR_SOURCE_SHA256="$digest" AURADE_AUR_CHROMIUM_SHA256="$ash" \
  "$ROOT/ci/export-aur-bundles.sh" >"$TMP/export.out"

count=$(find "$TMP/aur" -mindepth 1 -maxdepth 1 -type d | wc -l)
[[ $count -eq 15 ]] || fail "expected 15 AUR package directories, found $count"

# The binary package is the release build, and its dependencies are the real
# package's, read rather than copied.
bin=$TMP/aur/chromiumos-ash-bin/PKGBUILD
pkgver=$(awk -F= '$1 == "pkgver" {print $2; exit}' "$ROOT/chromiumos-ash/PKGBUILD")
pkgrel=$(awk -F= '$1 == "pkgrel" {print $2; exit}' "$ROOT/chromiumos-ash/PKGBUILD")
grep -Fq "pkgver=${pkgver}" "$bin" || fail 'bin pkgver'
grep -Fq "pkgrel=${pkgrel}" "$bin" || fail 'bin pkgrel'
grep -Fq "sha256sums=('$ash'" "$bin" || fail 'bin digest'
grep -Fq 'releases/download/repo-x86_64/chromiumos-ash-${pkgver}-${pkgrel}-${CARCH}.pkg.tar.zst' "$bin" ||
  fail 'bin source URL'
want=$(bash -c 'source "$1"; echo "${#depends[@]}"' _ "$ROOT/chromiumos-ash/PKGBUILD")
got=$(bash -c 'source "$1"; echo "${#depends[@]}"' _ "$bin")
[[ $want == "$got" ]] || fail "bin has $got dependencies, chromiumos-ash has $want"

# Sources come from the tag, and nothing large goes into AUR git.
grep -Fq "archive/v9.9.9.tar.gz" "$TMP/aur/auradefs/PKGBUILD" || fail 'auradefs archive'
grep -Fq 'aurade-9.9.9/auradefs/workspace' "$TMP/aur/auradefs/PKGBUILD" || fail 'auradefs tree'
[[ ! -e $TMP/aur/auradefs/workspace ]] || fail 'auradefs workspace copied into AUR git'
grep -Fq "raw/v9.9.9/installer/wallpapers/" "$TMP/aur/aurade-wallpapers/PKGBUILD" || fail 'wallpaper URLs'
grep -Fq '"chromiumos-ash-bin>=' "$TMP/aur/aurade/PKGBUILD" || fail 'aurade names the -bin package'
if find "$TMP/aur" -type f -size +1M -print -quit | grep -q .; then
  fail 'export contains a file over 1 MiB'
fi
if find "$TMP/aur" -name .SRCINFO -print -quit | grep -q .; then
  fail 'a stale .SRCINFO was copied'
fi

echo 'AUR export policy test: PASS'
