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
if (( ! STAGE_ONLY )); then
  command -v mkarchiso >/dev/null || { echo 'build-iso: install the archiso package first' >&2; exit 1; }
fi

WORK_ROOT=${AURADE_INSTALLER_WORK_ROOT:-/mnt/build/aurade-work/installer}
OUTPUT_DIR=${AURADE_ISO_OUTPUT_DIR:-$WORK_ROOT/output}
STAGE=$WORK_ROOT/profile
BUILD_WORK=$WORK_ROOT/work
REPO_URL=${AURADE_REPO_URL:-file:///var/cache/aurade/repo}
ALLOW_UNSIGNED=${AURADE_ALLOW_UNSIGNED:-0}
SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-$(date -u -d "${AURADE_ARCH_SNAPSHOT//\//-} 00:00:00" +%s)}
MAX_ISO_BYTES=${AURADE_MAX_ISO_BYTES:-4294967296}
export SOURCE_DATE_EPOCH

[[ $WORK_ROOT == /* && $WORK_ROOT != / ]] || { echo 'build-iso: work root must be an absolute non-root path' >&2; exit 2; }
[[ $MAX_ISO_BYTES =~ ^[0-9]+$ && $MAX_ISO_BYTES -gt 0 ]] || {
  echo 'build-iso: AURADE_MAX_ISO_BYTES must be a positive integer' >&2
  exit 2
}

if [[ $ALLOW_UNSIGNED != 1 ]]; then
  : "${AURADE_REPO_KEY:?Signed images require AURADE_REPO_KEY}"
  : "${AURADE_REPO_FINGERPRINT:?Signed images require AURADE_REPO_FINGERPRINT}"
  [[ -r $AURADE_REPO_KEY ]] || { echo "build-iso: key not readable: $AURADE_REPO_KEY" >&2; exit 1; }
fi

rm -rf -- "$STAGE" "$BUILD_WORK"
install -d -m 0755 "$STAGE" "$OUTPUT_DIR" "$BUILD_WORK"
cp -a "$ROOT/archiso/." "$STAGE/"
install -Dm0755 "$ROOT/bin/aurade-install" "$STAGE/airootfs/usr/local/sbin/aurade-install"
install -Dm0755 "$ROOT/bin/aurade-installer" "$STAGE/airootfs/usr/local/sbin/aurade-installer"
install -Dm0755 "$ROOT/bin/aurade-recovery" "$STAGE/airootfs/usr/local/sbin/aurade-recovery"
install -Dm0755 "$ROOT/bin/aurade-hardware-qualify" "$STAGE/airootfs/usr/local/sbin/aurade-hardware-qualify"
install -Dm0755 "$ROOT/bin/aurade-install-failure" "$STAGE/airootfs/usr/local/sbin/aurade-install-failure"
install -Dm0755 "$ROOT/archiso/airootfs/usr/local/sbin/aurade-network-diagnostics" \
  "$STAGE/airootfs/usr/local/sbin/aurade-network-diagnostics"
install -Dm0644 "$ROOT/lib/aurade-validate.sh" "$STAGE/airootfs/usr/local/lib/aurade/aurade-validate.sh"
install -Dm0644 "$ROOT/lib/aurade-journal.sh" "$STAGE/airootfs/usr/local/lib/aurade/aurade-journal.sh"
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
ln -s /usr/lib/systemd/system/NetworkManager.service "$STAGE/airootfs/etc/systemd/system/multi-user.target.wants/NetworkManager.service"
ln -s /usr/lib/systemd/system/aurade-refresh-mirrors.service \
  "$STAGE/airootfs/etc/systemd/system/multi-user.target.wants/aurade-refresh-mirrors.service"
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
{
  printf 'arch_snapshot=%s\n' "$AURADE_ARCH_SNAPSHOT"
  printf 'source_date_epoch=%s\n' "$SOURCE_DATE_EPOCH"
  printf 'repo_url=%s\n' "$REPO_URL"
  printf 'repo_fingerprint=%s\n' "${expected_fingerprint:-unsigned}"
  printf 'iso_bytes=%s\n' "$iso_bytes"
  printf 'iso_max_bytes=%s\n' "$MAX_ISO_BYTES"
  printf 'package_count=%s\n' "$package_count"
  printf 'package_bytes=%s\n' "$package_bytes"
  printf 'archiso_version=%s\n' "$(pacman -Q archiso 2>/dev/null || printf unknown)"
  (cd "$(dirname "$STAGE/airootfs/opt/aurade/repo/packages.lock")" && sha256sum packages.lock)
} >"$iso.build-info"
printf '%s\n' "$iso"
