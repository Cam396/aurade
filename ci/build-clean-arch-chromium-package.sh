#!/bin/bash
# Build chromiumos-ash from a fresh output tree inside the Arch validation root.
set -euo pipefail

[[ "$(id -u)" -eq 0 ]] || {
  echo "build-clean-arch-chromium-package.sh must run as root." >&2
  exit 2
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKDIR="${AURADE_WORKDIR:-/mnt/build/aurade-work}"
ARCHROOT="${ARCHROOT:-${WORKDIR}/archroot}"
CHROME_SRC="${CHROME_SRC:-${WORKDIR}/chromium-bootstrap/src}"
arch_source="${ARCHROOT}/build/chromium-src"
clean_output="${ARCHROOT}/build/chromium-clean-out/Ash"
package_source="${ARCHROOT}/build/chromium-clean-package-src"
package_dest="${ARCHROOT}/build/clean-arch-package"
reuse_clean_output="${AURADE_REUSE_CLEAN_OUTPUT:-0}"
skip_gn_gen="${AURADE_SKIP_GN_GEN:-0}"
mounted_source=0
mounted_root=0
mounted_output=0

for command in arch-chroot mount mountpoint rsync runuser; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Missing required command: ${command}" >&2
    exit 2
  }
done
[[ -d "${ARCHROOT}" && -d "${CHROME_SRC}" ]] || {
  echo "Missing Arch root or pinned Chromium checkout." >&2
  exit 2
}
[[ "${reuse_clean_output}" == 0 || "${reuse_clean_output}" == 1 ]] || {
  echo "AURADE_REUSE_CLEAN_OUTPUT must be 0 or 1." >&2
  exit 2
}
[[ "${skip_gn_gen}" == 0 || "${skip_gn_gen}" == 1 ]] || {
  echo "AURADE_SKIP_GN_GEN must be 0 or 1." >&2
  exit 2
}
if [[ "${skip_gn_gen}" == 1 && "${reuse_clean_output}" != 1 ]]; then
  echo "AURADE_SKIP_GN_GEN=1 requires AURADE_REUSE_CLEAN_OUTPUT=1." >&2
  exit 2
fi
if [[ "${skip_gn_gen}" == 1 && ! -f "${clean_output}/build.ninja" ]]; then
  echo "Cannot skip GN generation without ${clean_output}/build.ninja." >&2
  exit 2
fi

arch_build_uid="$(stat -c '%u' "${ARCHROOT}/home/aurabuild")"
arch_build_gid="$(stat -c '%g' "${ARCHROOT}/home/aurabuild")"
chrome_owner="$(stat -c '%U' "${CHROME_SRC}")"
chrome_owner_uid="$(stat -c '%u' "${CHROME_SRC}")"
chrome_owner_gid="$(stat -c '%g' "${CHROME_SRC}")"
series_check_workdir="${WORKDIR}/clean-series-check"
install -d -o "${chrome_owner_uid}" -g "${chrome_owner_gid}" -m 755 \
  "${series_check_workdir}"

runuser -u "${chrome_owner}" -- /usr/bin/env \
  CHROME_SRC="${CHROME_SRC}" AURADE_WORKDIR="${series_check_workdir}" \
  "${SCRIPT_DIR}/refresh-bootstrap-series.sh" --check

cleanup() {
  if [[ "${mounted_output}" == 1 ]]; then
    umount "${arch_source}/out/Ash"
  fi
  if [[ "${mounted_source}" == 1 ]]; then
    umount "${arch_source}"
  fi
  if [[ "${mounted_root}" == 1 ]]; then
    umount "${ARCHROOT}"
  fi
}
trap cleanup EXIT

if ! mountpoint -q "${ARCHROOT}"; then
  mount --bind "${ARCHROOT}" "${ARCHROOT}"
  mounted_root=1
fi
install -d -m 755 "${arch_source}"
if ! mountpoint -q "${arch_source}"; then
  mount --bind "${CHROME_SRC}" "${arch_source}"
  mounted_source=1
fi

if [[ "${reuse_clean_output}" == 0 ]]; then
  rm -rf "${ARCHROOT}/build/chromium-clean-out"
fi
rm -rf "${package_source}" "${package_dest}"
install -d -o "${arch_build_uid}" -g "${arch_build_gid}" -m 755 \
  "${clean_output}" "${package_source}" "${package_dest}"

rsync -a --exclude pkg --exclude src \
  "${REPO_ROOT}/chromiumos-ash/" "${package_source}/"
chown -R "${arch_build_uid}:${arch_build_gid}" \
  "${ARCHROOT}/build/chromium-clean-out" \
  "${package_source}" "${package_dest}"

# The quoted script intentionally expands nproc inside the Arch root.
# shellcheck disable=SC2016
arch-chroot "${ARCHROOT}" /usr/bin/runuser -u aurabuild -- \
  /usr/bin/env \
  AURADE_SKIP_GN_GEN="${skip_gn_gen}" \
  PATH=/build/chromium-src/buildtools/linux64:/build/chromium-src/third_party/ninja:/usr/local/sbin:/usr/local/bin:/usr/bin \
  /usr/bin/nice -n "${AURADE_BUILD_NICE:-15}" \
  /usr/bin/bash -lc '
    cd /build/chromium-src
    if [[ "${AURADE_SKIP_GN_GEN}" != 1 ]]; then
      gn gen /build/chromium-clean-out/Ash --root=/build/chromium-src --args="
        target_os = \"chromeos\"
        is_debug = false
        is_component_build = false
        is_official_build = false
        symbol_level = 0
        use_ozone = true
        ozone_platform_wayland = true
        use_system_minigbm = true
        enable_rust = true
      "
    fi
    ninja -C /build/chromium-clean-out/Ash -j"$(nproc)" chrome chrome_sandbox
  '

mount --bind "${clean_output}" "${arch_source}/out/Ash"
mounted_output=1

arch-chroot "${ARCHROOT}" /usr/bin/runuser -u aurabuild -- \
  /usr/bin/env \
  CHROME_SRC=/build/chromium-src \
  AURADE_SKIP_CHROMIUM_BUILD=1 \
  BUILDDIR=/build/chromium-clean-package-src/build \
  PKGDEST=/build/clean-arch-package \
  SRCDEST=/build/chromium-clean-package-src/srcdest \
  LOGDEST=/build/chromium-clean-package-src/logs \
  PATH=/build/chromium-src/buildtools/linux64:/build/chromium-src/third_party/ninja:/usr/local/sbin:/usr/local/bin:/usr/bin \
  /usr/bin/nice -n "${AURADE_BUILD_NICE:-15}" \
  /usr/bin/bash -lc \
  'cd /build/chromium-clean-package-src && makepkg --force --noconfirm --clean --nodeps'

package_file="$(find "${package_dest}" -maxdepth 1 -type f \
  -name 'chromiumos-ash-*.pkg.tar.*' ! -name '*.sig' -print -quit)"
[[ -n "${package_file}" ]] || {
  echo "Clean Arch build produced no package." >&2
  exit 1
}
pacman -Qip "${package_file}" >/dev/null
pacman -Qlp "${package_file}" >/dev/null
sha256sum "${package_file}"
echo "Clean Arch Chromium package: ${package_file}"
