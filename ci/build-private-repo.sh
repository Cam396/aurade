#!/bin/bash
# Build AuraDE packages and publish them into a local pacman repository.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_DIR="${REPO_DIR:-${REPO_ROOT}/private-repo}"
REPO_NAME="${REPO_NAME:-aurade}"
DEFAULT_PACKAGES=(
  "aurade-account-helper"
  "aurade-system-helper"
  "shill-nm-adapter"
  "aurade-power"
  "aurade-host-bridge"
  "chromiumos-ash"
  "aurade-login"
  "aurade-ai"
  "aurade-webapp-shortcuts"
  "aurade"
  "aurade-full"
)
DEFAULT_NODEPS_PACKAGES=(
  "aurade-account-helper"
  "aurade-system-helper"
  "shill-nm-adapter"
  "aurade-power"
  "aurade-host-bridge"
  "aurade-login"
  "aurade-ai"
  "aurade-webapp-shortcuts"
  "aurade"
  "aurade-full"
)

if [[ -n "${AURADE_PACKAGES:-}" ]]; then
  read -r -a PACKAGES <<<"${AURADE_PACKAGES}"
else
  PACKAGES=("${DEFAULT_PACKAGES[@]}")
fi
if [[ -n "${AURADE_NODEPS_PACKAGES:-}" ]]; then
  read -r -a NODEPS_PACKAGES <<<"${AURADE_NODEPS_PACKAGES}"
else
  NODEPS_PACKAGES=("${DEFAULT_NODEPS_PACKAGES[@]}")
fi

read -r -a makepkg_flags <<<"${MAKEPKG_FLAGS:---force --syncdeps --noconfirm --clean}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

build_package() {
  local pkgdir="$1"
  local flags=("${makepkg_flags[@]}")

  if is_nodeps_package "${pkgdir}"; then
    flags=()
    for flag in "${makepkg_flags[@]}"; do
      if [[ "${flag}" != "--syncdeps" && "${flag}" != "-s" ]]; then
        flags+=("${flag}")
      fi
    done
    if ! has_flag "--nodeps" "${flags[@]}"; then
      flags+=("--nodeps")
    fi
  fi

  echo "==> Building ${pkgdir}"
  (
    cd "${REPO_ROOT}/${pkgdir}"
    PKGDEST="${REPO_DIR}" PKGEXT="${PKGEXT:-.pkg.tar.zst}" makepkg "${flags[@]}"
  )
}

has_flag() {
  local needle="$1"
  shift
  local flag
  for flag in "$@"; do
    [[ "${flag}" == "${needle}" ]] && return 0
  done
  return 1
}

is_nodeps_package() {
  local pkgdir="$1"
  local nodeps_pkg
  for nodeps_pkg in "${NODEPS_PACKAGES[@]}"; do
    [[ "${pkgdir}" == "${nodeps_pkg}" ]] && return 0
  done
  return 1
}

need makepkg
need pacman
need repo-add
need vercmp
if [[ -n "${GPGKEY:-}" ]]; then
  need gpg
fi

mkdir -p "${REPO_DIR}"

for pkgdir in "${PACKAGES[@]}"; do
  build_package "${pkgdir}"
done

mapfile -t all_package_files < <(find "${REPO_DIR}" -maxdepth 1 \
  -name '*.pkg.tar.*' ! -name '*.sig' -type f | sort)
declare -A latest_package_files=()
declare -A latest_package_versions=()
for package_file in "${all_package_files[@]}"; do
  read -r package_name package_version < <(pacman -Qp "${package_file}")
  if [[ -z "${latest_package_files[${package_name}]:-}" ]] ||
      [[ "$(vercmp "${package_version}" \
        "${latest_package_versions[${package_name}]}")" -gt 0 ]]; then
    latest_package_files["${package_name}"]="${package_file}"
    latest_package_versions["${package_name}"]="${package_version}"
  fi
done
mapfile -t package_files < <(
  for package_name in "${!latest_package_files[@]}"; do
    printf '%s\n' "${latest_package_files[${package_name}]}"
  done | sort
)
if [[ "${#package_files[@]}" -eq 0 ]]; then
  echo "No package files found in ${REPO_DIR}" >&2
  exit 1
fi

if [[ -n "${GPGKEY:-}" ]]; then
  if [[ "${AURADE_SIGN_PACKAGES:-1}" = "1" ]]; then
    for package_file in "${package_files[@]}"; do
      gpg --batch --yes --detach-sign --local-user "${GPGKEY}" \
        "${package_file}"
    done
  fi
  repo-add --sign --key "${GPGKEY}" "${REPO_DIR}/${REPO_NAME}.db.tar.gz" "${package_files[@]}"
else
  repo-add "${REPO_DIR}/${REPO_NAME}.db.tar.gz" "${package_files[@]}"
fi

echo "Repository ready: ${REPO_DIR}/${REPO_NAME}.db.tar.gz"
