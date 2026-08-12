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
[[ -r $staged/aurade.db.tar.gz ]]
(cd "$staged" && sha256sum -c \
  <(awk '!/^#/ {print $1 "  " $2}' packages.lock)) >/dev/null
grep -Fxq reflector "$ROOT/installer/archiso/packages.x86_64"
grep -Fxq archlinux-keyring "$ROOT/installer/archiso/packages.x86_64"
grep -Fxq DisableDownloadTimeout "$ROOT/installer/archiso/pacman.conf"
grep -Fq 'cow_spacesize=4G' \
  "$ROOT/installer/archiso/efiboot/loader/entries/01-aurade-linux.conf"
grep -Fxq 'editor no' "$ROOT/installer/archiso/efiboot/loader/loader.conf"
[[ -x $TMP/work/profile/airootfs/usr/local/sbin/aurade-refresh-mirrors ]]
[[ -L $TMP/work/profile/airootfs/etc/systemd/system/multi-user.target.wants/aurade-refresh-mirrors.service ]]
[[ ! -e $TMP/work/profile/airootfs/etc/systemd/system/multi-user.target.wants/sshd.service ]]

echo 'installer ISO staging test: PASS'
