#!/bin/bash
# Build and atomically promote a coherent AuraDE release repository.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
target_repo="${REPO_DIR:-${REPO_ROOT}/private-repo}"
REPO_NAME="${REPO_NAME:-aurade}"
chromium_pkgver="$(awk -F= '$1 == "pkgver" { print $2; exit }' \
  "${REPO_ROOT}/chromiumos-ash/PKGBUILD")"
chromium_pkgrel="$(awk -F= '$1 == "pkgrel" { print $2; exit }' \
  "${REPO_ROOT}/chromiumos-ash/PKGBUILD")"
default_chromium_package="/mnt/build/aurade-work/current-package/pkgdest/chromiumos-ash-${chromium_pkgver}-${chromium_pkgrel}-x86_64.pkg.tar.gz"
CHROMIUMOS_ASH_PACKAGE="${CHROMIUMOS_ASH_PACKAGE:-${default_chromium_package}}"
staging="${target_repo}.staging.$$"
previous="${target_repo}.previous"

[[ "$(id -u)" -ne 0 ]] || {
  echo "Run build-release-repo.sh as an unprivileged build user." >&2
  exit 2
}
[[ -f "${CHROMIUMOS_ASH_PACKAGE}" ]] || {
  echo "Missing prebuilt Chromium package: ${CHROMIUMOS_ASH_PACKAGE}" >&2
  exit 2
}

cleanup() {
  rm -rf "${staging}"
}
trap cleanup EXIT
mkdir -p "${staging}"
cp -a "${CHROMIUMOS_ASH_PACKAGE}" "${staging}/"

makepkg_config="${staging}/makepkg.conf"
sed -E 's/(^OPTIONS=.*[( ])debug([ )])+/\1!debug\2/' \
  /etc/makepkg.conf >"${makepkg_config}"
if grep -Eq '^OPTIONS=.*[( ]debug([ )])' "${makepkg_config}"; then
  echo "Failed to disable makepkg debug splitting." >&2
  exit 1
fi

export REPO_DIR="${staging}"
export REPO_NAME
export AURADE_PACKAGES="aurade-account-helper aurade-system-helper shill-nm-adapter aurade-power aurade-host-bridge aurade-login aurade-ai aurade-webapp-shortcuts aurade aurade-full"
export AURADE_NODEPS_PACKAGES="${AURADE_PACKAGES}"
export MAKEPKG_FLAGS="${MAKEPKG_FLAGS:---force --noconfirm --clean --config ${makepkg_config}}"
if [[ -n "${GPGKEY:-}" ]]; then
  : "${AURADE_REPO_KEYRING:?Set AURADE_REPO_KEYRING to an exported public repository key}"
  : "${AURADE_REPO_FINGERPRINT:?Set AURADE_REPO_FINGERPRINT to the full repository signing fingerprint}"
fi
"${SCRIPT_DIR}/build-private-repo.sh"
rm -f "${makepkg_config}"
if [[ -n "${GPGKEY:-}" ]]; then
  export AURADE_REQUIRE_SIGNATURES=1
fi
"${SCRIPT_DIR}/verify-release-repo.sh"

rm -rf "${previous}"
if [[ -e "${target_repo}" ]]; then
  mv "${target_repo}" "${previous}"
fi
mv "${staging}" "${target_repo}"
trap - EXIT
echo "Promoted release repository: ${target_repo}"
