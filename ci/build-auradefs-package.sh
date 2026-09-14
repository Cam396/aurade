#!/bin/bash
# Build the auradefs package from the workspace in this tree.
#
# The PKGBUILD reads the Cargo workspace from ${srcdir}/auradefs-src rather
# than from a tarball, so this script is the one supported way to drive it:
# it copies auradefs/workspace there, fetches what Cargo.lock pins, and runs
# makepkg. Everything lands under AURADE_WORKDIR, by default a folder beside
# the other package builds under /mnt/build.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKDIR="${AURADE_WORKDIR:-/mnt/build/aurade-work/auradefs-package}"
PACKAGE_SRC="${WORKDIR}/auradefs"

for command in rsync makepkg cargo; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Missing required command: ${command}" >&2
    exit 2
  }
done

mkdir -p "${WORKDIR}" "${WORKDIR}/build" "${WORKDIR}/pkgdest" \
  "${WORKDIR}/srcdest" "${WORKDIR}/logdest"
rm -rf "${PACKAGE_SRC}"
rsync -a --exclude pkg --exclude src --exclude workspace \
  "${REPO_ROOT}/auradefs/" "${PACKAGE_SRC}/"
# The workspace goes where the PKGBUILD's prepare() looks for it. A target
# directory that came along from a developer's tree would be a stale build
# with the right name, so it stays behind.
mkdir -p "${PACKAGE_SRC}/src"
rsync -a --exclude target --exclude target-dev --exclude '*.before-*' \
  "${REPO_ROOT}/auradefs/workspace/" "${PACKAGE_SRC}/src/auradefs-src/"

export BUILDDIR="${WORKDIR}/build"
export PKGDEST="${WORKDIR}/pkgdest"
export SRCDEST="${WORKDIR}/srcdest"
export LOGDEST="${WORKDIR}/logdest"

cd "${PACKAGE_SRC}"
makepkg --force --noconfirm --nodeps

package_file="$(find "${PKGDEST}" -maxdepth 1 -type f \
  -name 'auradefs-*.pkg.tar.*' ! -name '*.sig' -printf '%T@ %p\n' |
  sort -nr | head -1 | cut -d' ' -f2-)"
if [[ -z "${package_file}" ]]; then
  echo "makepkg finished but no auradefs package is in ${PKGDEST}" >&2
  exit 1
fi
echo "built ${package_file}"
