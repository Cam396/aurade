#!/bin/bash
# Build the pinned Chromium package and a coherent Arch-native AuraDE repo.
set -euo pipefail

[[ "$(id -u)" -eq 0 ]] || {
  echo "build-release-candidate.sh must run as root." >&2
  exit 2
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKDIR="${AURADE_WORKDIR:-/mnt/build/aurade-work}"
ARCHROOT="${ARCHROOT:-${WORKDIR}/archroot}"
CHROME_SRC="${CHROME_SRC:-${WORKDIR}/chromium-bootstrap/src}"
OUTPUT_REPO="${REPO_DIR:-${WORKDIR}/private-repo}"
REUSE_CHROMIUM=0

if [[ "${1:-}" == "--reuse-chromium" ]]; then
  REUSE_CHROMIUM=1
  shift
fi
[[ "$#" -eq 0 ]] || {
  echo "Usage: $0 [--reuse-chromium]" >&2
  exit 2
}

for command in rsync runuser stat; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Missing required command: ${command}" >&2
    exit 2
  }
done
[[ -d "${ARCHROOT}" && -d "${CHROME_SRC}" ]] || {
  echo "Missing Arch root or pinned Chromium checkout." >&2
  exit 2
}

chrome_owner="$(stat -c '%U' "${CHROME_SRC}")"
package_workdir="${WORKDIR}/current-package"
pkgver="$(awk -F= '$1 == "pkgver" { print $2; exit }' "${REPO_ROOT}/chromiumos-ash/PKGBUILD")"
pkgrel="$(awk -F= '$1 == "pkgrel" { print $2; exit }' "${REPO_ROOT}/chromiumos-ash/PKGBUILD")"
chrome_package="${package_workdir}/pkgdest/chromiumos-ash-${pkgver}-${pkgrel}-x86_64.pkg.tar.gz"

if [[ "${REUSE_CHROMIUM}" == 0 ]]; then
  runuser -u "${chrome_owner}" -- env \
    CHROME_SRC="${CHROME_SRC}" AURADE_WORKDIR="${package_workdir}" \
    nice -n "${AURADE_BUILD_NICE:-10}" \
    "${SCRIPT_DIR}/build-current-chromiumos-ash-package.sh"
fi
[[ -f "${chrome_package}" ]] || {
  echo "Missing current Chromium package: ${chrome_package}" >&2
  exit 1
}

arch_source="${ARCHROOT}/build/aurade"
arch_input="${ARCHROOT}/build/aurade-input"
arch_output="${ARCHROOT}/build/aurade-output"
arch_build_uid="$(stat -c '%u' "${ARCHROOT}/home/aurabuild")"
arch_build_gid="$(stat -c '%g' "${ARCHROOT}/home/aurabuild")"
install -d -m 755 "${arch_source}" "${arch_input}"
install -d -o "${arch_build_uid}" -g "${arch_build_gid}" -m 755 \
  "${arch_output}"
rsync -a --delete --exclude pkg --exclude src --exclude __pycache__ \
  "${REPO_ROOT}/aurade-account-helper" \
  "${REPO_ROOT}/aurade-system-helper" \
  "${REPO_ROOT}/aurade-power" \
  "${REPO_ROOT}/aurade-host-bridge" \
  "${REPO_ROOT}/aurade-login" \
  "${REPO_ROOT}/shill-nm-adapter" \
  "${REPO_ROOT}/aurade-ai" \
  "${REPO_ROOT}/aurade-webapp-shortcuts" \
  "${REPO_ROOT}/aurade" \
  "${REPO_ROOT}/aurade-full" \
  "${REPO_ROOT}/chromiumos-ash" \
  "${REPO_ROOT}/ci" \
  "${arch_source}/"
install -m 644 "${chrome_package}" "${arch_input}/"
chown -R "${arch_build_uid}:${arch_build_gid}" \
  "${arch_source}" "${arch_input}" "${arch_output}"
rm -rf "${arch_output}/aurade" "${arch_output}/aurade.previous"

"${SCRIPT_DIR}/run-in-arch-root.sh" /usr/bin/runuser -u aurabuild -- \
  /usr/bin/bash -lc \
  "cd /build/aurade && REPO_DIR=/build/aurade-output/aurade CHROMIUMOS_ASH_PACKAGE=/build/aurade-input/$(basename "${chrome_package}") ci/build-release-repo.sh"

host_staging="${OUTPUT_REPO}.staging.$$"
host_previous="${OUTPUT_REPO}.previous"
trap 'rm -rf "${host_staging}"' EXIT
rsync -a "${arch_output}/aurade/" "${host_staging}/"
rm -rf "${host_previous}"
if [[ -e "${OUTPUT_REPO}" ]]; then
  mv "${OUTPUT_REPO}" "${host_previous}"
fi
mv "${host_staging}" "${OUTPUT_REPO}"
trap - EXIT

AURADE_SOURCE_MANIFEST="${WORKDIR}/source-manifest.md" \
  CHROME_SRC="${CHROME_SRC}" "${SCRIPT_DIR}/write-source-manifest.sh"
echo "Release candidate ready: ${OUTPUT_REPO}"
