#!/usr/bin/env bash
# Stage and build a dated, package-locked AuraDE ArchISO image.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")" && pwd -P)
STAGE_ONLY=0
if [[ ${1:-} == --stage-only ]]; then
  STAGE_ONLY=1
  shift
fi
[[ $# -eq 0 ]] || { echo "Usage: $0 [--stage-only]" >&2; exit 2; }
: "${AURADE_ARCH_SNAPSHOT:?Set AURADE_ARCH_SNAPSHOT=YYYY/MM/DD}"
: "${AURADE_REPO_DIR:?Set AURADE_REPO_DIR to the verified release repository}"

[[ $AURADE_ARCH_SNAPSHOT =~ ^20[0-9]{2}/(0[1-9]|1[0-2])/(0[1-9]|[12][0-9]|3[01])$ ]] || {
  echo 'build-iso: AURADE_ARCH_SNAPSHOT must be YYYY/MM/DD' >&2
  exit 2
}
normalized_snapshot=$(date -u -d "${AURADE_ARCH_SNAPSHOT//\//-}" +%Y/%m/%d 2>/dev/null || true)
[[ $normalized_snapshot == "$AURADE_ARCH_SNAPSHOT" ]] || {
  echo 'build-iso: AURADE_ARCH_SNAPSHOT is not a real calendar date' >&2
  exit 2
}
if (( ! STAGE_ONLY )); then
  command -v mkarchiso >/dev/null || { echo 'build-iso: install the archiso package first' >&2; exit 1; }
  command -v python3 >/dev/null || { echo 'build-iso: python3 is required to write the ISO SBOM' >&2; exit 1; }
fi

WORK_ROOT=${AURADE_INSTALLER_WORK_ROOT:-/mnt/build/aurade-work/installer}
OUTPUT_DIR=${AURADE_ISO_OUTPUT_DIR:-$WORK_ROOT/output}
STAGE=$WORK_ROOT/profile
BUILD_WORK=$WORK_ROOT/work
REPO_URL=${AURADE_REPO_URL:-file:///var/cache/aurade/repo}
ALLOW_UNSIGNED=${AURADE_ALLOW_UNSIGNED:-0}
SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-$(date -u -d "${AURADE_ARCH_SNAPSHOT//\//-} 00:00:00" +%s)}
MAX_ISO_BYTES=${AURADE_MAX_ISO_BYTES:-4294967296}
ISO_SIGNING_KEY=${AURADE_ISO_SIGNING_KEY:-}
ISO_SIGNING_FINGERPRINT=${AURADE_ISO_SIGNING_FINGERPRINT:-}
REQUIRE_ISO_SIGNATURE=${AURADE_REQUIRE_ISO_SIGNATURE:-0}
export SOURCE_DATE_EPOCH

[[ $WORK_ROOT == /* && $WORK_ROOT != / ]] || { echo 'build-iso: work root must be an absolute non-root path' >&2; exit 2; }
[[ $MAX_ISO_BYTES =~ ^[0-9]+$ && $MAX_ISO_BYTES -gt 0 ]] || {
  echo 'build-iso: AURADE_MAX_ISO_BYTES must be a positive integer' >&2
  exit 2
}
[[ $REQUIRE_ISO_SIGNATURE == 0 || $REQUIRE_ISO_SIGNATURE == 1 ]] || {
  echo 'build-iso: AURADE_REQUIRE_ISO_SIGNATURE must be 0 or 1' >&2
  exit 2
}

if [[ -n $ISO_SIGNING_KEY || $REQUIRE_ISO_SIGNATURE == 1 ]]; then
  command -v gpg >/dev/null || { echo 'build-iso: gpg is required for ISO signatures' >&2; exit 1; }
  [[ -n $ISO_SIGNING_KEY ]] || {
    echo 'build-iso: AURADE_ISO_SIGNING_KEY is required when ISO signatures are required' >&2
    exit 1
  }
  gpg --batch --list-secret-keys "$ISO_SIGNING_KEY" >/dev/null 2>&1 || {
    echo 'build-iso: ISO signing key is not available in the builder keyring' >&2
    exit 1
  }
  expected_iso_fingerprint=${ISO_SIGNING_FINGERPRINT//[[:space:]]/}
  expected_iso_fingerprint=${expected_iso_fingerprint^^}
  [[ $expected_iso_fingerprint =~ ^[0-9A-F]{40,64}$ ]] || {
    echo 'build-iso: AURADE_ISO_SIGNING_FINGERPRINT must be a full fingerprint when ISO signatures are enabled' >&2
    exit 1
  }
  iso_key_fingerprints=$(gpg --batch --with-colons --list-secret-keys "$ISO_SIGNING_KEY" 2>/dev/null | \
    awk -F: '$1 == "fpr" {print toupper($10)}') || {
    echo 'build-iso: could not read ISO signing-key fingerprint' >&2
    exit 1
  }
  grep -Fxq "$expected_iso_fingerprint" <<<"$iso_key_fingerprints" || {
    echo 'build-iso: ISO signing key does not contain the requested fingerprint' >&2
    exit 1
  }
fi

if [[ $ALLOW_UNSIGNED != 1 ]]; then
  : "${AURADE_REPO_KEY:?Signed images require AURADE_REPO_KEY}"
  : "${AURADE_REPO_FINGERPRINT:?Signed images require AURADE_REPO_FINGERPRINT}"
  [[ -r $AURADE_REPO_KEY ]] || { echo "build-iso: key not readable: $AURADE_REPO_KEY" >&2; exit 1; }
fi

rm -rf -- "$STAGE" "$BUILD_WORK"
install -d -m 0755 "$STAGE" "$OUTPUT_DIR" "$BUILD_WORK"
cp -a "$ROOT/archiso/." "$STAGE/"
install -Dm0755 "$ROOT/bin/aurade-install" "$STAGE/airootfs/usr/local/sbin/aurade-install"
install -Dm0755 "$ROOT/bin/aurade-secure-boot-sign" "$STAGE/airootfs/usr/local/sbin/aurade-secure-boot-sign"
install -Dm0644 "$ROOT/secure-boot/90-aurade-secure-boot.hook" \
  "$STAGE/airootfs/usr/local/share/aurade/90-aurade-secure-boot.hook"
install -Dm0755 "$ROOT/bin/aurade-recovery" "$STAGE/airootfs/usr/local/sbin/aurade-recovery"
install -Dm0755 "$ROOT/bin/aurade-hardware-qualify" "$STAGE/airootfs/usr/local/sbin/aurade-hardware-qualify"
install -Dm0755 "$ROOT/bin/aurade-install-failure" "$STAGE/airootfs/usr/local/sbin/aurade-install-failure"
install -Dm0755 "$ROOT/bin/aurade-explain" "$STAGE/airootfs/usr/local/sbin/aurade-explain"
# The catalogue goes beside the libraries and not beside the program, because
# `/usr/local/sbin` is for things that run.
install -Dm0644 "$ROOT/data/hardware-notes.tsv" "$STAGE/airootfs/usr/local/lib/aurade/hardware-notes.tsv"
install -Dm0755 "$ROOT/bin/aurade-rate-sampler" "$STAGE/airootfs/usr/local/bin/aurade-rate-sampler"
install -Dm0755 "$ROOT/bin/aurade-first-boot-accessibility" "$STAGE/airootfs/usr/local/bin/aurade-first-boot-accessibility"
install -Dm0644 "$ROOT/units/aurade-first-boot-accessibility.service" "$STAGE/airootfs/usr/local/share/aurade/aurade-first-boot-accessibility.service"
install -Dm0755 "$ROOT/archiso/airootfs/usr/local/sbin/aurade-network-diagnostics" \
  "$STAGE/airootfs/usr/local/sbin/aurade-network-diagnostics"
install -Dm0755 "$ROOT/bin/aurade-installer-tui" "$STAGE/airootfs/usr/local/sbin/aurade-installer-tui"
install -Dm0755 "$ROOT/bin/aurade-installer-gui" "$STAGE/airootfs/usr/local/sbin/aurade-installer-gui"
install -Dm0755 "$ROOT/bin/aurade-installer-gui-bridge" "$STAGE/airootfs/usr/local/sbin/aurade-installer-gui-bridge"
install -Dm0755 "$ROOT/bin/aurade-installer-start" "$STAGE/airootfs/usr/local/sbin/aurade-installer-start"
for _gui_module in __init__ a11y bible bridge flow app brand locales stage tokens wait; do
  install -Dm0644 "$ROOT/lib/aurade_gui/${_gui_module}.py" \
    "$STAGE/airootfs/usr/local/lib/aurade/aurade_gui/${_gui_module}.py"
done
# Both stylesheets. GTK's @define-color is global, so the dark scheme is a
# second sheet the front end swaps in rather than a section of the first.
for _sheet in theme.css theme-dark.css theme-hc.css theme-dark-hc.css theme-oled.css; do
  install -Dm0644 "$ROOT/lib/aurade_gui/${_sheet}" \
    "$STAGE/airootfs/usr/local/lib/aurade/aurade_gui/${_sheet}"
done
# The mark and the wordmark are drawn from the real artwork rather than
# redrawn in code, so the installer and the product carry the same logo.
for _asset in aurade-mark.png aurade-wordmark.png; do
  install -Dm0644 "$ROOT/assets/${_asset}" \
    "$STAGE/airootfs/usr/local/share/aurade/${_asset}"
  # The boot screen gets the same two files rather than a copy kept beside its
  # script. Plymouth's script plugin reads images out of its own theme
  # directory and nowhere else, so they have to be there; committing a second
  # pair of PNGs to sit there would be committing a logo that drifts from the
  # logo the moment either is touched. Copied at build time instead, from the
  # same place the installer window gets its own.
  install -Dm0644 "$ROOT/assets/${_asset}" \
    "$STAGE/airootfs/usr/share/plymouth/themes/aurade/${_asset}"
done
# The wallpapers, and the manifest that indexes them.
#
# The manifest first and by name, because the front end finds the set by
# looking for it: a directory of images with no manifest is not a set, and an
# image staged without one would be a picture nothing can name.
#
# The whole directory rather than a list, because a list here is a list that
# goes stale the next time somebody adds a photograph, and the gate that
# decides what belongs in the set already ran when the manifest was written.
install -Dm0644 "$ROOT/wallpapers/manifest.tsv" \
  "$STAGE/airootfs/usr/local/share/aurade/wallpapers/manifest.tsv"
while IFS=$'\t' read -r _wallpaper _rest; do
  [[ -n ${_wallpaper:-} && ${_wallpaper:0:1} != '#' ]] || continue
  install -Dm0644 "$ROOT/wallpapers/${_wallpaper}" \
    "$STAGE/airootfs/usr/local/share/aurade/wallpapers/${_wallpaper}"
done < "$ROOT/wallpapers/manifest.tsv"
# The King James Version, with the Apocrypha.
#
# The markdown only. `bible/eng-kjv_usfm.zip` is the archive it was made from
# and stays in the source tree: it is what lets the test re-derive all eighty
# books, and it is another two and a half megabytes of something the image
# would never read.
#
# Derived from the manifest for the same reason the wallpapers are. Eighty
# file names typed out here is eighty chances to be wrong, and the manifest is
# what the front ends open first anyway: a book staged and not indexed is a
# book nothing can reach, and a book indexed and not staged is a menu entry
# that opens nothing.
install -Dm0644 "$ROOT/bible/manifest.tsv" \
  "$STAGE/airootfs/usr/local/share/aurade/bible/manifest.tsv"
while IFS=$'\t' read -r _code _section _short _name _chapters _verses _book; do
  [[ -n ${_code:-} && ${_code:0:1} != '#' && -n ${_book:-} ]] || continue
  install -Dm0644 "$ROOT/bible/${_book}" \
    "$STAGE/airootfs/usr/local/share/aurade/bible/${_book}"
done < "$ROOT/bible/manifest.tsv"
install -Dm0644 "$ROOT/lib/aurade-validate.sh" "$STAGE/airootfs/usr/local/lib/aurade/aurade-validate.sh"
install -Dm0644 "$ROOT/lib/aurade-journal.sh" "$STAGE/airootfs/usr/local/lib/aurade/aurade-journal.sh"
install -Dm0644 "$ROOT/lib/aurade-questions.sh" "$STAGE/airootfs/usr/local/lib/aurade/aurade-questions.sh"
install -Dm0644 "$ROOT/lib/aurade-tui.sh" "$STAGE/airootfs/usr/local/lib/aurade/aurade-tui.sh"
install -Dm0644 "$ROOT/lib/aurade-copy.sh" "$STAGE/airootfs/usr/local/lib/aurade/aurade-copy.sh"
install -Dm0644 "$ROOT/lib/aurade-wait.sh" "$STAGE/airootfs/usr/local/lib/aurade/aurade-wait.sh"
install -Dm0644 "$ROOT/lib/aurade-tips" "$STAGE/airootfs/usr/local/lib/aurade/aurade-tips"
install -Dm0644 "$ROOT/lib/aurade-probe.sh" "$STAGE/airootfs/usr/local/lib/aurade/aurade-probe.sh"
install -Dm0644 "$ROOT/lib/aurade-renderers.sh" "$STAGE/airootfs/usr/local/lib/aurade/aurade-renderers.sh"
install -Dm0644 "$ROOT/lib/aurade-bible.sh" "$STAGE/airootfs/usr/local/lib/aurade/aurade-bible.sh"
install -Dm0644 "$ROOT/lib/aurade-badge.sh" "$STAGE/airootfs/usr/local/lib/aurade/aurade-badge.sh"
install -d -m 0755 "$STAGE/airootfs/opt/aurade/repo" "$STAGE/airootfs/etc/aurade-installer"
"$ROOT/tools/generate-package-lock.sh" "$AURADE_REPO_DIR" "$STAGE/airootfs/opt/aurade/repo/packages.lock" "$ROOT/expected-packages.txt"
while read -r _digest filename _pkgname _pkgver _arch; do
  [[ -n ${filename:-} ]] || continue
  install -m 0644 -- "${AURADE_REPO_DIR%/}/$filename" \
    "$STAGE/airootfs/opt/aurade/repo/$filename"
done < <(awk '!/^#/ {print $1, $2, $3, $4, $5}' \
  "$STAGE/airootfs/opt/aurade/repo/packages.lock")
for metadata in \
  "$AURADE_REPO_DIR"/aurade.db "$AURADE_REPO_DIR"/aurade.db.* \
  "$AURADE_REPO_DIR"/aurade.files "$AURADE_REPO_DIR"/aurade.files.*; do
  [[ -f $metadata ]] || continue
  install -m 0644 -- "$metadata" "$STAGE/airootfs/opt/aurade/repo/$(basename "$metadata")"
done
(
  cd "$STAGE/airootfs/opt/aurade/repo"
  sha256sum -c <(awk '!/^#/ {print $1 "  " $2}' packages.lock)
) >/dev/null
if [[ -r ${AURADE_REPO_DIR%/}/SHA256SUMS ]]; then
  install -m 0644 -- "${AURADE_REPO_DIR%/}/SHA256SUMS" \
    "$STAGE/airootfs/opt/aurade/repo/SHA256SUMS"
  (
    cd "$AURADE_REPO_DIR"
    sha256sum -c --quiet SHA256SUMS
  ) || {
    echo 'build-iso: source repository SHA256SUMS verification failed' >&2
    exit 1
  }
  (
    cd "$STAGE/airootfs/opt/aurade/repo"
    sha256sum -c --quiet SHA256SUMS
  ) || {
    echo 'build-iso: staged repository SHA256SUMS verification failed' >&2
    exit 1
  }
fi
printf '%s\n' "$AURADE_ARCH_SNAPSHOT" >"$STAGE/airootfs/etc/aurade-installer/snapshot"

if [[ $ALLOW_UNSIGNED == 1 ]]; then
  # Keep the exception visible in the image instead of inheriting a silent
  # Optional default. Signed images retain Required local-file verification.
  sed -i -E 's/^LocalFileSigLevel[[:space:]]*=.*/LocalFileSigLevel = Optional/' \
    "$STAGE/pacman.conf" "$STAGE/airootfs/etc/pacman.conf"
  printf '%s\n' development-unsigned >"$STAGE/airootfs/etc/aurade-installer/repo-fingerprint"
else
  for command in gpg gpgv; do
    command -v "$command" >/dev/null || { echo "build-iso: signed images require $command" >&2; exit 1; }
  done
  expected_fingerprint=${AURADE_REPO_FINGERPRINT//[[:space:]]/}
  expected_fingerprint=${expected_fingerprint^^}
  [[ $expected_fingerprint =~ ^[0-9A-F]{40,64}$ ]] || { echo 'build-iso: invalid full repository fingerprint' >&2; exit 1; }
  key_listing=$(gpg --batch --show-keys --with-colons "$AURADE_REPO_KEY" 2>/dev/null) || {
    echo 'build-iso: repository public key could not be parsed' >&2
    exit 1
  }
  if awk -F: '$1 == "sec" {found=1} END {exit !found}' <<<"$key_listing"; then
    echo 'build-iso: refusing to embed a repository secret key' >&2
    exit 1
  fi
  key_fingerprints=$(awk -F: '$1 == "fpr" {print toupper($10)}' <<<"$key_listing")
  if ! grep -Fxq "$expected_fingerprint" <<<"$key_fingerprints"; then
    echo 'build-iso: repository key does not contain the requested fingerprint' >&2
    exit 1
  fi
  while read -r -a lock_fields; do
    filename=${lock_fields[1]:-}
    [[ -n $filename ]] || continue
    source_signature=${AURADE_REPO_DIR%/}/${filename}.sig
    [[ -r $source_signature ]] || { echo "build-iso: missing signature: ${filename}.sig" >&2; exit 1; }
    install -m 0644 -- "$source_signature" \
      "$STAGE/airootfs/opt/aurade/repo/${filename}.sig"
    package=$STAGE/airootfs/opt/aurade/repo/$filename
    gpgv --keyring "$AURADE_REPO_KEY" "${package}.sig" "$package" >/dev/null 2>&1 || {
      echo "build-iso: invalid signature: $filename" >&2
      exit 1
    }
  done < <(awk '!/^#/ {print $1, $2, $3}' "$STAGE/airootfs/opt/aurade/repo/packages.lock")
  install -Dm0644 "$AURADE_REPO_KEY" "$STAGE/airootfs/opt/aurade/repo/aurade-repository.gpg"
  printf '%s\n' "$expected_fingerprint" >"$STAGE/airootfs/etc/aurade-installer/repo-fingerprint"
fi
printf '%s\n' "$REPO_URL" >"$STAGE/airootfs/etc/aurade-installer/repo-url"

sed -i \
  -e "s|__AURADE_ARCH_SNAPSHOT__|$AURADE_ARCH_SNAPSHOT|g" \
  "$STAGE/pacman.conf" "$STAGE/airootfs/etc/pacman.d/mirrorlist"

install -d -m 0755 "$STAGE/airootfs/etc/systemd/system/multi-user.target.wants"
# The Arch system package enables systemd-firstboot from sysinit.target when
# the live root has no first-boot state. That prompt belongs on an installed
# system, not in front of AuraDE's own language and timezone page. Mask it in
# the image so no boot entry can reach the generic Arch setup screen.
ln -s /dev/null "$STAGE/airootfs/etc/systemd/system/systemd-firstboot.service"
ln -s /usr/lib/systemd/system/NetworkManager.service "$STAGE/airootfs/etc/systemd/system/multi-user.target.wants/NetworkManager.service"
ln -s /usr/lib/systemd/system/aurade-refresh-mirrors.service \
  "$STAGE/airootfs/etc/systemd/system/multi-user.target.wants/aurade-refresh-mirrors.service"
ln -s /etc/systemd/system/aurade-installer-autostart.service \
  "$STAGE/airootfs/etc/systemd/system/multi-user.target.wants/aurade-installer-autostart.service"
# Both are enabled and their conditions decide which one runs. The serial unit
# asks for aurade.installer=serial on the kernel command line and the tty1 one
# refuses it, so exactly one of them ever claims a console.
ln -s /etc/systemd/system/aurade-installer-serial.service \
  "$STAGE/airootfs/etc/systemd/system/multi-user.target.wants/aurade-installer-serial.service"
find "$STAGE" -exec touch -h -d "@$SOURCE_DATE_EPOCH" {} +

if (( STAGE_ONLY )); then
  printf 'staged_profile=%s\nsource_date_epoch=%s\n' "$STAGE" "$SOURCE_DATE_EPOCH"
  sha256sum "$STAGE/airootfs/opt/aurade/repo/packages.lock"
  exit 0
fi

mkarchiso -v -w "$BUILD_WORK" -o "$OUTPUT_DIR" "$STAGE"

iso=$(find "$OUTPUT_DIR" -maxdepth 1 -type f -name 'aurade-*.iso' -printf '%T@ %p\n' | sort -n | tail -1 | cut -d' ' -f2-)
[[ -n $iso ]] || { echo 'build-iso: mkarchiso produced no AuraDE ISO' >&2; exit 1; }
iso_bytes=$(stat -c '%s' "$iso")
(( iso_bytes <= MAX_ISO_BYTES )) || {
  echo "build-iso: ISO is ${iso_bytes} bytes, above AURADE_MAX_ISO_BYTES=${MAX_ISO_BYTES}" >&2
  exit 1
}
package_count=$(find "$STAGE/airootfs/opt/aurade/repo" -maxdepth 1 -type f -name '*.pkg.tar.*' ! -name '*.sig' | wc -l)
package_bytes=$(find "$STAGE/airootfs/opt/aurade/repo" -maxdepth 1 -type f -name '*.pkg.tar.*' ! -name '*.sig' -printf '%s\n' | awk '{sum += $1} END {print sum + 0}')
(cd "$(dirname "$iso")" && sha256sum "$(basename "$iso")") | tee "$iso.sha256"
sbom="$iso.sbom.spdx.json"
python3 "$ROOT/../ci/write-iso-sbom.py" \
  --iso "$iso" \
  --repo-dir "$STAGE/airootfs/opt/aurade/repo" \
  --output "$sbom"
if [[ -n $ISO_SIGNING_KEY ]]; then
  gpg --batch --yes --local-user "$ISO_SIGNING_KEY" --detach-sign \
    --output "$iso.sig" "$iso"
  gpg --batch --verify "$iso.sig" "$iso" >/dev/null 2>&1
  gpg --batch --yes --local-user "$ISO_SIGNING_KEY" --detach-sign \
    --output "$sbom.sig" "$sbom"
  gpg --batch --verify "$sbom.sig" "$sbom" >/dev/null 2>&1
elif (( REQUIRE_ISO_SIGNATURE )); then
  echo 'build-iso: refusing an unsigned ISO because AURADE_REQUIRE_ISO_SIGNATURE=1' >&2
  exit 1
fi
sbom_sha256=$(sha256sum "$sbom" | awk '{print $1}')
{
  printf 'arch_snapshot=%s\n' "$AURADE_ARCH_SNAPSHOT"
  printf 'source_date_epoch=%s\n' "$SOURCE_DATE_EPOCH"
  printf 'repo_url=%s\n' "$REPO_URL"
  printf 'repo_fingerprint=%s\n' "${expected_fingerprint:-unsigned}"
  printf 'iso_bytes=%s\n' "$iso_bytes"
  printf 'iso_max_bytes=%s\n' "$MAX_ISO_BYTES"
  printf 'package_count=%s\n' "$package_count"
  printf 'package_bytes=%s\n' "$package_bytes"
  printf 'sbom_file=%s\n' "$(basename "$sbom")"
  printf 'sbom_sha256=%s\n' "$sbom_sha256"
  if [[ -f $iso.sig ]]; then
    printf 'iso_signature=%s\n' "$(basename "$iso.sig")"
    printf 'sbom_signature=%s\n' "$(basename "$sbom.sig")"
    printf 'iso_signing_fingerprint=%s\n' "$expected_iso_fingerprint"
  else
    printf 'iso_signature=not-created\n'
    printf 'sbom_signature=not-created\n'
    printf 'iso_signing_fingerprint=not-set\n'
  fi
  printf 'archiso_version=%s\n' "$(pacman -Q archiso 2>/dev/null || printf unknown)"
  (cd "$(dirname "$STAGE/airootfs/opt/aurade/repo/packages.lock")" && sha256sum packages.lock)
} >"$iso.build-info"
printf '%s\n' "$iso"
