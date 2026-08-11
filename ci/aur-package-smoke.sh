#!/usr/bin/env bash
# Validate the generated AUR package directories without building Chromium.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKDIR="${AURADE_WORKDIR:-${REPO_ROOT}/.aurade-work}"
OUTPUT="${AURADE_AUR_OUTPUT:-${WORKDIR}/aur-bundles-verify-$$}"
SKIP_BINARY_VERIFY="${AURADE_AUR_SKIP_BINARY_VERIFY:-0}"

die() {
  printf 'aur-package-smoke: %s\n' "$*" >&2
  exit 1
}

[[ "$(id -u)" -ne 0 ]] || die 'run as an unprivileged Arch build user'
command -v makepkg >/dev/null 2>&1 || die 'makepkg is required'
command -v namcap >/dev/null 2>&1 || die 'namcap is required'
[[ ! -e "${OUTPUT}" ]] || die "output already exists: ${OUTPUT}"

AURADE_AUR_OUTPUT="${OUTPUT}" "${SCRIPT_DIR}/export-aur-bundles.sh"

mapfile -t packages < <(find "${OUTPUT}" -mindepth 1 -maxdepth 1 -type d \
  -printf '%f\n' | sort)
[[ "${#packages[@]}" -eq 11 ]] ||
  die "expected 11 package directories, found ${#packages[@]}"

for package in "${packages[@]}"; do
  package_dir="${OUTPUT}/${package}"
  [[ -f "${package_dir}/PKGBUILD" ]] ||
    die "${package}: missing PKGBUILD"
  if [[ ! -f "${package_dir}/.SRCINFO" ]]; then
    makepkg_output="${package_dir}/.SRCINFO.generated"
    (cd "${package_dir}" && makepkg --printsrcinfo >"${makepkg_output}")
    mv "${makepkg_output}" "${package_dir}/.SRCINFO"
  fi
  generated="${package_dir}/.SRCINFO.generated"
  (cd "${package_dir}" && makepkg --printsrcinfo >"${generated}")
  cmp -s "${package_dir}/.SRCINFO" "${generated}" || {
    printf '%s: .SRCINFO is stale\n' "${package}" >&2
    diff -u "${package_dir}/.SRCINFO" "${generated}" >&2 || true
    exit 1
  }
  rm -f "${generated}"
  namcap "${package_dir}/PKGBUILD"
  if [[ "${package}" == chromiumos-ash-bin &&
        "${SKIP_BINARY_VERIFY}" == 1 ]]; then
    printf '%s: source verification skipped by AURADE_AUR_SKIP_BINARY_VERIFY=1\n' \
      "${package}"
  else
    (cd "${package_dir}" && makepkg --verifysource --noconfirm)
  fi
done

if find "${OUTPUT}" -type f -size +50M -print -quit | grep -q .; then
  die 'generated AUR packet contains an unexpected file over 50 MiB'
fi

printf 'AUR package smoke passed: %s packages\n' "${#packages[@]}"
