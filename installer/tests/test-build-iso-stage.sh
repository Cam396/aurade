#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
install -d -m 0755 "$TMP/repo" "$TMP/package"

while IFS= read -r name; do
  [[ -n $name ]] || continue
  printf 'pkgname = %s\npkgver = 1.0-1\narch = any\n' "$name" \
    >"$TMP/package/.PKGINFO"
  bsdtar -cf "$TMP/repo/${name}-1.0-1-any.pkg.tar.zst" \
    -C "$TMP/package" .PKGINFO
done <"$ROOT/installer/expected-packages.txt"
printf '%s\n' 'local repository database' >"$TMP/repo/aurade.db.tar.gz"
printf '%s\n' 'must not enter the image' >"$TMP/repo/private-signing-key.txt"
(cd "$TMP/repo" && sha256sum aurade.db.tar.gz >SHA256SUMS)

if env \
  AURADE_ARCH_SNAPSHOT=2026/02/30 \
  AURADE_REPO_DIR="$TMP/repo" \
  AURADE_ALLOW_UNSIGNED=1 \
  AURADE_INSTALLER_WORK_ROOT="$TMP/work_invalid_date" \
  "$ROOT/installer/build-iso.sh" --stage-only >"$TMP/invalid_date.out" 2>&1; then
  echo 'impossible snapshot date unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'build-iso: AURADE_ARCH_SNAPSHOT is not a real calendar date' \
  "$TMP/invalid_date.out"
[[ ! -e $TMP/work_invalid_date ]]

if env \
  AURADE_ARCH_SNAPSHOT=2026/07/12 \
  AURADE_REPO_DIR="$TMP/repo" \
  AURADE_ALLOW_UNSIGNED=1 \
  AURADE_MAX_ISO_BYTES=invalid \
  AURADE_INSTALLER_WORK_ROOT="$TMP/work_invalid" \
  "$ROOT/installer/build-iso.sh" --stage-only >"$TMP/invalid_max_bytes.out" 2>&1; then
  echo 'non-numeric AURADE_MAX_ISO_BYTES unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'build-iso: AURADE_MAX_ISO_BYTES must be a positive integer' "$TMP/invalid_max_bytes.out"
[[ ! -e $TMP/work_invalid ]]

env \
  AURADE_ARCH_SNAPSHOT=2026/07/12 \
  AURADE_REPO_DIR="$TMP/repo" \
  AURADE_ALLOW_UNSIGNED=1 \
  AURADE_INSTALLER_WORK_ROOT="$TMP/work" \
  "$ROOT/installer/build-iso.sh" --stage-only >"$TMP/stage.out"

staged=$TMP/work/profile/airootfs/opt/aurade/repo
expected=$(grep -Evc '^[[:space:]]*(#|$)' "$ROOT/installer/expected-packages.txt")
actual=$(find "$staged" -maxdepth 1 -type f -name '*.pkg.tar.*' \
  ! -name '*.sig' | wc -l)
[[ $actual -eq $expected ]]
[[ ! -e $staged/private-signing-key.txt ]]
[[ -r $staged/packages.lock ]]
[[ -r $staged/SHA256SUMS ]]
[[ -r $staged/aurade.db.tar.gz ]]
(cd "$staged" && sha256sum -c \
  <(awk '!/^#/ {print $1 "  " $2}' packages.lock)) >/dev/null
grep -Fxq reflector "$ROOT/installer/archiso/packages.x86_64"
grep -Fxq archlinux-keyring "$ROOT/installer/archiso/packages.x86_64"
grep -Fxq DisableDownloadTimeout "$ROOT/installer/archiso/pacman.conf"
grep -Fq 'MAX_ISO_BYTES=${AURADE_MAX_ISO_BYTES:-4294967296}' "$ROOT/installer/build-iso.sh"
grep -Fq 'iso_bytes=' "$ROOT/installer/build-iso.sh"
grep -Fq 'package_count=' "$ROOT/installer/build-iso.sh"
grep -Fq 'package_bytes=' "$ROOT/installer/build-iso.sh"
grep -Fxq 'LocalFileSigLevel = Required' "$ROOT/installer/archiso/pacman.conf"
grep -Fxq 'LocalFileSigLevel = Required' \
  "$ROOT/installer/archiso/airootfs/etc/pacman.conf"
grep -Fxq 'LocalFileSigLevel = Optional' \
  "$TMP/work/profile/pacman.conf"
grep -Fxq 'LocalFileSigLevel = Optional' \
  "$TMP/work/profile/airootfs/etc/pacman.conf"
grep -Fq 'cow_spacesize=4G' \
  "$ROOT/installer/archiso/efiboot/loader/entries/01-aurade-linux.conf"
grep -Fxq 'editor no' "$ROOT/installer/archiso/efiboot/loader/loader.conf"
[[ -x $TMP/work/profile/airootfs/usr/local/sbin/aurade-refresh-mirrors ]]
[[ -x $TMP/work/profile/airootfs/usr/local/sbin/aurade-install-failure ]]
[[ -r $TMP/work/profile/airootfs/usr/local/lib/aurade/aurade-validate.sh ]]
[[ -r $TMP/work/profile/airootfs/usr/local/lib/aurade/aurade-journal.sh ]]
[[ -x $TMP/work/profile/airootfs/usr/local/sbin/aurade-network-diagnostics ]]
grep -Fq -- 'empty root password' "$ROOT/installer/archiso/airootfs/etc/motd"
grep -Fq -- 'untrusted network or physical access' "$ROOT/installer/archiso/airootfs/etc/motd"
grep -Fq '/usr/local/lib/aurade/aurade-validate.sh' "$ROOT/installer/archiso/profiledef.sh"
grep -Fq '/usr/local/lib/aurade/aurade-journal.sh' "$ROOT/installer/archiso/profiledef.sh"
grep -Fq '/usr/local/sbin/aurade-network-diagnostics' "$ROOT/installer/archiso/profiledef.sh"
[[ -L $TMP/work/profile/airootfs/etc/systemd/system/multi-user.target.wants/aurade-refresh-mirrors.service ]]
[[ ! -e $TMP/work/profile/airootfs/etc/systemd/system/multi-user.target.wants/sshd.service ]]

# Repository metadata is authenticated separately from the package lock when a
# verified release repository supplies SHA256SUMS. A tampered database must
# stop staging before mkarchiso can consume it.
printf '%s\n' 'tampered repository database' >>"$TMP/repo/aurade.db.tar.gz"
if env \
  AURADE_ARCH_SNAPSHOT=2026/07/12 \
  AURADE_REPO_DIR="$TMP/repo" \
  AURADE_ALLOW_UNSIGNED=1 \
  AURADE_INSTALLER_WORK_ROOT="$TMP/work-tampered" \
  "$ROOT/installer/build-iso.sh" --stage-only >"$TMP/tampered.out" 2>&1; then
  echo 'tampered repository metadata unexpectedly staged' >&2
  exit 1
fi
grep -Fq 'source repository SHA256SUMS verification failed' "$TMP/tampered.out"

echo 'installer ISO staging test: PASS'
