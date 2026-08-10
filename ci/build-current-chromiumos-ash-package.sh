#!/bin/bash
# Build chromiumos-ash from the pinned bootstrap checkout and current series.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CHROME_SRC="${CHROME_SRC:-/mnt/build/aurade-work/chromium-bootstrap/src}"
WORKDIR="${AURADE_WORKDIR:-/mnt/build/aurade-work/current-package}"
PACKAGE_SRC="${WORKDIR}/chromiumos-ash"

for command in rsync makepkg; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Missing required command: ${command}" >&2
    exit 2
  }
done

if [[ "$(id -u)" != "$(stat -c '%u' "${CHROME_SRC}")" ]]; then
  echo "Run as the owner of ${CHROME_SRC}." >&2
  exit 2
fi

CHROME_SRC="${CHROME_SRC}" AURADE_WORKDIR="${WORKDIR}" \
  "${SCRIPT_DIR}/refresh-bootstrap-series.sh"

mkdir -p "${WORKDIR}" "${WORKDIR}/build" "${WORKDIR}/pkgdest" \
  "${WORKDIR}/srcdest" "${WORKDIR}/logdest"
rm -rf "${PACKAGE_SRC}"
rsync -a --exclude pkg --exclude src \
  "${REPO_ROOT}/chromiumos-ash/" "${PACKAGE_SRC}/"

export CHROME_SRC
export BUILDDIR="${WORKDIR}/build"
export PKGDEST="${WORKDIR}/pkgdest"
export SRCDEST="${WORKDIR}/srcdest"
export LOGDEST="${WORKDIR}/logdest"
export PATH="${CHROME_SRC}/buildtools/linux64:${CHROME_SRC}/third_party/ninja:${PATH}"

cd "${PACKAGE_SRC}"
makepkg --force --noconfirm --clean --nodeps

package_file="$(find "${PKGDEST}" -maxdepth 1 -type f \
  -name 'chromiumos-ash-*.pkg.tar.*' ! -name '*.sig' -printf '%T@ %p\n' |
  sort -nr | head -1 | cut -d' ' -f2-)"
if [[ -z "${package_file}" ]]; then
  echo "Package build completed without an artifact in ${PKGDEST}." >&2
  exit 1
fi

if command -v pacman >/dev/null 2>&1; then
  pacman -Qip "${package_file}" >/dev/null
  pacman -Qlp "${package_file}" >/dev/null
fi

package_list="${WORKDIR}/package-files.txt"
bsdtar -tf "${package_file}" > "${package_list}"
for required_entry in \
    usr/bin/chromiumos-ash \
    usr/bin/chromiumos-ash-session \
    usr/bin/chromiumos-ash-session-child \
    usr/lib/chromiumos-ash/chrome \
    usr/lib/chromiumos-ash/chrome-sandbox \
    usr/lib/chromiumos-ash/aurade-session-manager-shim.py \
    opt/google/chrome/chrome; do
  if ! grep -Fxq "${required_entry}" "${package_list}"; then
    echo "Package is missing required entry: ${required_entry}" >&2
    exit 1
  fi
done

sha256sum "${package_file}"
printf 'Packaged Chrome SHA-256: '
bsdtar -xOf "${package_file}" usr/lib/chromiumos-ash/chrome | sha256sum
echo "Current chromiumos-ash package: ${package_file}"
