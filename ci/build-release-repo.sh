#!/bin/bash
# Build and atomically promote a coherent AuraDE release repository.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
target_repo="${REPO_DIR:-${REPO_ROOT}/private-repo}"
REPO_NAME="${REPO_NAME:-aurade}"
expected_package_file="${AURADE_EXPECTED_PACKAGES_FILE:-${REPO_ROOT}/installer/expected-packages.txt}"
release_channel="${AURADE_RELEASE_CHANNEL:-development}"
case "${release_channel}" in
  development|soak|candidate|public) ;;
  *)
    echo "AURADE_RELEASE_CHANNEL must be development, soak, candidate, or public" >&2
    exit 2
    ;;
esac

# A candidate/public repository is a trust boundary, not merely a newer
# development directory. Refuse to construct one unless the caller supplied
# the production signing identity, isolated public keyring, and detached
# package-signature path that the verifier will require later. Development
# fixtures retain an explicit unsigned channel for local testing.
if [[ "${release_channel}" == candidate || "${release_channel}" == public ]]; then
  [[ -n "${GPGKEY:-}" ]] || {
    echo "AURADE_RELEASE_CHANNEL=${release_channel} requires GPGKEY" >&2
    exit 2
  }
  [[ -r "${AURADE_REPO_KEYRING:-}" ]] || {
    echo "AURADE_RELEASE_CHANNEL=${release_channel} requires a readable AURADE_REPO_KEYRING" >&2
    exit 2
  }
  normalized_fingerprint="${AURADE_REPO_FINGERPRINT:-}"
  normalized_fingerprint="${normalized_fingerprint//[[:space:]]/}"
  normalized_fingerprint="${normalized_fingerprint^^}"
  [[ "${normalized_fingerprint}" =~ ^[0-9A-F]{40,64}$ ]] || {
    echo "AURADE_RELEASE_CHANNEL=${release_channel} requires a full AURADE_REPO_FINGERPRINT" >&2
    exit 2
  }
  [[ "${AURADE_SIGN_PACKAGES:-1}" == 1 ]] || {
    echo "AURADE_RELEASE_CHANNEL=${release_channel} requires detached package signatures" >&2
    exit 2
  }
  export AURADE_REQUIRE_SIGNATURES=1
fi
[[ -r "${expected_package_file}" ]] || {
  echo "Expected package list is unreadable: ${expected_package_file}" >&2
  exit 2
}
mapfile -t release_packages < <(
  sed -E '/^[[:space:]]*(#|$)/d; s/[[:space:]]+$//' "${expected_package_file}" \
    | awk '$0 != "chromiumos-ash"'
)
((${#release_packages[@]} > 0)) || {
  echo "Expected package list has no source packages: ${expected_package_file}" >&2
  exit 2
}
chromium_pkgver="$(awk -F= '$1 == "pkgver" { print $2; exit }' \
  "${REPO_ROOT}/chromiumos-ash/PKGBUILD")"
chromium_pkgrel="$(awk -F= '$1 == "pkgrel" { print $2; exit }' \
  "${REPO_ROOT}/chromiumos-ash/PKGBUILD")"
if [[ -z "${CHROMIUMOS_ASH_PACKAGE:-}" ]]; then
  package_dir="${AURADE_WORKDIR:-/mnt/build/aurade-work}/current-package/pkgdest"
  package_name="chromiumos-ash-${chromium_pkgver}-${chromium_pkgrel}-x86_64.pkg.tar.*"
  mapfile -t package_candidates < <(find "${package_dir}" -maxdepth 1 -type f \
    -name "${package_name}" ! -name '*.sig' -printf '%p\n' | LC_ALL=C sort)
  if [[ "${#package_candidates[@]}" -ne 1 ]]; then
    echo "Expected exactly one Chromium package matching ${package_name}, found ${#package_candidates[@]}" >&2
    printf '  %s\n' "${package_candidates[@]}" >&2
    exit 2
  fi
  CHROMIUMOS_ASH_PACKAGE="${package_candidates[0]}"
fi
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
export AURADE_PACKAGES="${release_packages[*]}"
export AURADE_NODEPS_PACKAGES="${AURADE_PACKAGES}"
export MAKEPKG_FLAGS="${MAKEPKG_FLAGS:---force --noconfirm --clean --config ${makepkg_config}}"
if [[ -n "${GPGKEY:-}" ]]; then
  : "${AURADE_REPO_KEYRING:?Set AURADE_REPO_KEYRING to an exported public repository key}"
  : "${AURADE_REPO_FINGERPRINT:?Set AURADE_REPO_FINGERPRINT to the full repository signing fingerprint}"
fi
"${SCRIPT_DIR}/build-private-repo.sh"
rm -f "${makepkg_config}"
REPO_DIR="${staging}" "${SCRIPT_DIR}/write-release-checksums.sh"
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
