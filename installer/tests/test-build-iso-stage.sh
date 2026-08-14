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

if env \
  AURADE_ARCH_SNAPSHOT=2026/07/12 \
  AURADE_REPO_DIR="$TMP/repo" \
  AURADE_ALLOW_UNSIGNED=1 \
  AURADE_GUI_RELEASE=maybe \
  AURADE_INSTALLER_WORK_ROOT="$TMP/work_invalid_gui" \
  "$ROOT/installer/build-iso.sh" --stage-only >"$TMP/invalid_gui.out" 2>&1; then
  echo 'invalid AURADE_GUI_RELEASE unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'build-iso: AURADE_GUI_RELEASE must be 0 or 1' "$TMP/invalid_gui.out"
[[ ! -e $TMP/work_invalid_gui ]]

# A release build must not silently claim provenance when signatures are
# required.  Stage-only mode still validates this policy before touching the
# work directory, so this is safe to exercise without mkarchiso or a keyring.
if env \
  AURADE_ARCH_SNAPSHOT=2026/07/12 \
  AURADE_REPO_DIR="$TMP/repo" \
  AURADE_ALLOW_UNSIGNED=1 \
  AURADE_REQUIRE_ISO_SIGNATURE=1 \
  AURADE_INSTALLER_WORK_ROOT="$TMP/work_unsigned_required" \
  "$ROOT/installer/build-iso.sh" --stage-only >"$TMP/unsigned_required.out" 2>&1; then
  echo 'signature-required stage unexpectedly passed without a signing key' >&2
  exit 1
fi
grep -Fq 'AURADE_ISO_SIGNING_KEY is required when ISO signatures are required' \
  "$TMP/unsigned_required.out"
[[ ! -e $TMP/work_unsigned_required ]]

# The default profile is the public text-only 0.1.0 shape. It must not carry
# the GUI payload, marker, or runtime closure.
env \
  AURADE_ARCH_SNAPSHOT=2026/07/12 \
  AURADE_REPO_DIR="$TMP/repo" \
  AURADE_ALLOW_UNSIGNED=1 \
  AURADE_INSTALLER_WORK_ROOT="$TMP/work_text" \
  "$ROOT/installer/build-iso.sh" --stage-only >"$TMP/text_stage.out"
text_profile=$TMP/work_text/profile
[[ ! -e $text_profile/airootfs/usr/local/sbin/aurade-installer-gui ]]
[[ ! -e $text_profile/airootfs/etc/aurade-installer/gui-enabled ]]
for package in gtk4 libadwaita python-gobject cage; do
  ! grep -Fxq "$package" "$text_profile/packages.x86_64"
done

# A 0.2.0 GUI candidate opts in explicitly and carries the manifest/marker.
env \
  AURADE_ARCH_SNAPSHOT=2026/07/12 \
  AURADE_REPO_DIR="$TMP/repo" \
  AURADE_ALLOW_UNSIGNED=1 \
  AURADE_GUI_RELEASE=1 \
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
# The graphical installer's whole toolkit, including the compositor. GTK 4 on
# a bare virtual console has nothing to draw on, so a package list with the
# toolkit and no compositor ships a front end that can never be displayed.
for package in gtk4 libadwaita python-gobject cage; do
  grep -Fxq "$package" "$ROOT/installer/archiso/packages.x86_64"
done
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
grep -Fq 'ConditionPathExists=/run/aurade-live-firstboot-enabled' \
  "$ROOT/installer/archiso/airootfs/etc/systemd/system/systemd-firstboot.service.d/aurade-live.conf"
[[ -x $TMP/work/profile/airootfs/usr/local/sbin/aurade-refresh-mirrors ]]
[[ -x $TMP/work/profile/airootfs/usr/local/sbin/aurade-install-failure ]]
[[ -x $TMP/work/profile/airootfs/usr/local/sbin/aurade-installer-tui ]]
[[ -x $TMP/work/profile/airootfs/usr/local/sbin/aurade-installer-gui ]]
[[ -x $TMP/work/profile/airootfs/usr/local/sbin/aurade-installer-gui-bridge ]]
[[ -x $TMP/work/profile/airootfs/usr/local/sbin/aurade-installer-start ]]
for module in __init__ bridge flow app; do
  [[ -r $TMP/work/profile/airootfs/usr/local/lib/aurade/aurade_gui/$module.py ]]
done
[[ -r $TMP/work/profile/airootfs/etc/aurade-installer/gui-release-manifest.json ]]
[[ -r $TMP/work/profile/airootfs/etc/aurade-installer/gui-enabled ]]
for package in gtk4 libadwaita python-gobject cage; do
  grep -Fxq "$package" "$TMP/work/profile/packages.x86_64"
done
[[ -r $TMP/work/profile/airootfs/usr/local/lib/aurade/aurade-validate.sh ]]
[[ -r $TMP/work/profile/airootfs/usr/local/lib/aurade/aurade-journal.sh ]]
[[ -r $TMP/work/profile/airootfs/usr/local/lib/aurade/aurade-questions.sh ]]
[[ -r $TMP/work/profile/airootfs/usr/local/lib/aurade/aurade-tui.sh ]]
[[ -r $TMP/work/profile/airootfs/usr/local/lib/aurade/aurade-probe.sh ]]
[[ -x $TMP/work/profile/airootfs/usr/local/sbin/aurade-network-diagnostics ]]
grep -Fq -- 'empty root password' "$ROOT/installer/archiso/airootfs/etc/motd"
grep -Fq -- 'untrusted network or physical access' "$ROOT/installer/archiso/airootfs/etc/motd"
grep -Fq '/usr/local/lib/aurade/aurade-validate.sh' "$ROOT/installer/archiso/profiledef.sh"
grep -Fq '/usr/local/lib/aurade/aurade-journal.sh' "$ROOT/installer/archiso/profiledef.sh"
grep -Fq '/usr/local/lib/aurade/aurade-questions.sh' "$ROOT/installer/archiso/profiledef.sh"
grep -Fq '/usr/local/lib/aurade/aurade-tui.sh' "$ROOT/installer/archiso/profiledef.sh"
grep -Fq '/usr/local/lib/aurade/aurade-probe.sh' "$ROOT/installer/archiso/profiledef.sh"
grep -Fq '/usr/local/sbin/aurade-installer-tui' "$ROOT/installer/archiso/profiledef.sh"
for staged in /usr/local/sbin/aurade-installer-gui \
  /usr/local/sbin/aurade-installer-gui-bridge \
  /usr/local/sbin/aurade-installer-start \
  /usr/local/lib/aurade/aurade_gui/bridge.py \
  /usr/local/lib/aurade/aurade_gui/flow.py \
  /usr/local/lib/aurade/aurade_gui/app.py; do
  grep -Fq "$staged" "$ROOT/installer/archiso/profiledef.sh"
done
grep -Fq 'aurade-installer-start' "$ROOT/installer/archiso/airootfs/etc/motd"
# The staged front end must resolve its libraries from the image, not from a
# source tree that will not exist on the installation media.
grep -Fq '/usr/local/lib/aurade/$name' "$ROOT/installer/bin/aurade-installer-tui"
grep -Fq '/usr/local/lib/aurade/$name' "$ROOT/installer/bin/aurade-installer-start"
grep -Fq '/usr/local/lib/aurade' "$ROOT/installer/bin/aurade-installer-gui"
grep -Fq '/usr/local/sbin/aurade-installer-gui-bridge' \
  "$ROOT/installer/lib/aurade_gui/bridge.py"
grep -Fq '/usr/local/sbin/aurade-installer-tui' \
  "$ROOT/installer/bin/aurade-installer-gui-bridge"
grep -Fq '/usr/local/sbin/aurade-network-diagnostics' "$ROOT/installer/archiso/profiledef.sh"
[[ -L $TMP/work/profile/airootfs/etc/systemd/system/multi-user.target.wants/aurade-refresh-mirrors.service ]]
[[ ! -e $TMP/work/profile/airootfs/etc/systemd/system/multi-user.target.wants/sshd.service ]]
[[ -r $TMP/work/profile/airootfs/etc/systemd/system/systemd-firstboot.service.d/aurade-live.conf ]]
grep -Fq 'ConditionPathExists=/run/aurade-live-firstboot-enabled' \
  "$TMP/work/profile/airootfs/etc/systemd/system/systemd-firstboot.service.d/aurade-live.conf"

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
