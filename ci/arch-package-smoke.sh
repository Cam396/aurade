#!/bin/bash
# Arch-native package smoke checks for AuraDE package directories.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_DIR="${REPO_DIR:-${REPO_ROOT}/private-repo}"
AURADE_PACKAGES="${AURADE_PACKAGES:-aurade-account-helper aurade-system-helper shill-nm-adapter aurade-power aurade-host-bridge aurade-login aurade-ai aurade-webapp-shortcuts aurade aurade-full}"
MAKEPKG_FLAGS="${MAKEPKG_FLAGS:---force --noconfirm --clean}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

need makepkg
need repo-add
need namcap
need pacman
need python
need bsdtar

"${REPO_ROOT}/installer/tests/run.sh"

export AURADE_PACKAGES
export MAKEPKG_FLAGS
export REPO_DIR

"${SCRIPT_DIR}/build-private-repo.sh"

read -r -a package_dirs <<<"${AURADE_PACKAGES}"
for pkgdir in "${package_dirs[@]}"; do
  namcap "${REPO_ROOT}/${pkgdir}/PKGBUILD"
done

mapfile -t package_files < <(find "${REPO_DIR}" -maxdepth 1 -type f \
  -name '*.pkg.tar.*' ! -name '*.sig' | sort)
if [[ "${#package_files[@]}" -eq 0 ]]; then
  echo "No built package files found in ${REPO_DIR}" >&2
  exit 1
fi

namcap "${package_files[@]}"
pacman -Qip "${package_files[@]}" >/dev/null
pacman -Qlp "${package_files[@]}" >/dev/null
python -B -m py_compile "${REPO_ROOT}/shill-nm-adapter/shill_nm_adapter.py"
python -B -m py_compile \
  "${REPO_ROOT}/aurade-power/aurade-powerd" \
  "${REPO_ROOT}/aurade-host-bridge/aurade_host_bridge_core.py" \
  "${REPO_ROOT}/aurade-host-bridge/aurade_host_bridge.py" \
  "${REPO_ROOT}/aurade-host-bridge/aurade_desktop_bridge.py"

if command -v systemd-analyze >/dev/null 2>&1; then
  systemd-analyze verify \
    "${REPO_ROOT}/shill-nm-adapter/shill-nm-adapter.service" \
    "${REPO_ROOT}/aurade-power/aurade-powerd.service" \
    "${REPO_ROOT}/aurade-host-bridge/aurade-host-bridge.service" \
    "${REPO_ROOT}/aurade-login/aurade-greetd.service"
fi

if [[ "${AURADE_VERIFY_CHROMIUMOS_ASH:-1}" = "1" ]]; then
  (
    cd "${REPO_ROOT}/chromiumos-ash"
    makepkg --verifysource --noconfirm
    namcap PKGBUILD
  )
fi

if [[ "${AURADE_INSTALL_SMOKE:-0}" = "1" ]]; then
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "AURADE_INSTALL_SMOKE=1 requires root." >&2
    exit 1
  fi
  pacman -U --noconfirm "${package_files[@]}"
  pacman -Qk aurade-account-helper aurade-system-helper shill-nm-adapter \
    aurade-power aurade-host-bridge aurade-login
fi
