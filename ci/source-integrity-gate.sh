#!/usr/bin/env bash
# Cheap, public-tree integrity checks that do not require an Arch root.
set -Eeuo pipefail

REPO_ROOT=${AURADE_SOURCE_ROOT:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)}
EXPECTED=${AURADE_EXPECTED_PACKAGES:-${REPO_ROOT}/installer/expected-packages.txt}

fail() {
  printf 'source-integrity-gate: %s\n' "$*" >&2
  exit 1
}

[[ -d ${REPO_ROOT}/.git ]] || fail "not a Git worktree: ${REPO_ROOT}"
[[ -r ${EXPECTED} ]] || fail "expected package list is missing: ${EXPECTED}"

declare -A seen=()
mapfile -t packages < <(sed -E '/^[[:space:]]*(#|$)/d; s/[[:space:]]+$//' "${EXPECTED}")
(( ${#packages[@]} > 0 )) || fail 'expected package list is empty'

for package in "${packages[@]}"; do
  [[ ${package} =~ ^[a-z0-9][a-z0-9@._+-]*$ ]] ||
    fail "unsafe package name in expected list: ${package}"
  [[ -z ${seen[${package}]:-} ]] || fail "duplicate package in expected list: ${package}"
  seen[${package}]=1
  package_dir=${REPO_ROOT}/${package}
  [[ -d ${package_dir} ]] || fail "package directory is missing: ${package}"
  [[ -r ${package_dir}/PKGBUILD ]] || fail "PKGBUILD is missing: ${package}"
  [[ -r ${package_dir}/.SRCINFO ]] || fail ".SRCINFO is missing: ${package}"

  # This is deliberately a static comparison. Sourcing an untrusted PKGBUILD
  # would execute arbitrary packaging code in a source-check job.
  pkgbuild_name=$(awk -F= '/^[[:space:]]*pkgname[[:space:]]*=/ {
    value=$2; sub(/^[[:space:]]*/, "", value); sub(/[[:space:]]*#.*/, "", value);
    gsub(/[[:space:]]+/, "", value); print value; exit
  }' "${package_dir}/PKGBUILD")
  pkgbuild_ver=$(awk -F= '/^[[:space:]]*pkgver[[:space:]]*=/ {
    value=$2; sub(/^[[:space:]]*/, "", value); sub(/[[:space:]]*#.*/, "", value);
    gsub(/[[:space:]]+/, "", value); print value; exit
  }' "${package_dir}/PKGBUILD")
  pkgbuild_rel=$(awk -F= '/^[[:space:]]*pkgrel[[:space:]]*=/ {
    value=$2; sub(/^[[:space:]]*/, "", value); sub(/[[:space:]]*#.*/, "", value);
    gsub(/[[:space:]]+/, "", value); print value; exit
  }' "${package_dir}/PKGBUILD")
  [[ ${pkgbuild_name} == "${package}" ]] ||
    fail "PKGBUILD pkgname does not match directory: ${package}"
  [[ -n ${pkgbuild_ver} && -n ${pkgbuild_rel} ]] ||
    fail "PKGBUILD is missing static pkgver/pkgrel: ${package}"

  srcinfo_name=$(awk -F' = ' '$1 ~ /^[[:space:]]*pkgname[[:space:]]*$/ {print $2; exit}' "${package_dir}/.SRCINFO")
  srcinfo_ver=$(awk -F' = ' '$1 ~ /^[[:space:]]*pkgver[[:space:]]*$/ {print $2; exit}' "${package_dir}/.SRCINFO")
  srcinfo_rel=$(awk -F' = ' '$1 ~ /^[[:space:]]*pkgrel[[:space:]]*$/ {print $2; exit}' "${package_dir}/.SRCINFO")
  [[ ${srcinfo_name} == "${package}" && ${srcinfo_ver} == "${pkgbuild_ver}" &&
     ${srcinfo_rel} == "${pkgbuild_rel}" ]] ||
    fail "PKGBUILD/.SRCINFO identity mismatch: ${package}"
done

series=${REPO_ROOT}/patches/SERIES
[[ -r ${series} ]] || fail 'patches/SERIES is missing'
mapfile -t patch_names < <(sed -E 's/[[:space:]]+#.*$//; /^[[:space:]]*($|#)/d; s/^[[:space:]]+//; s/[[:space:]]+$//' "${series}")
(( ${#patch_names[@]} > 0 )) || fail 'patch series is empty'
declare -A patch_seen=()
for patch in "${patch_names[@]}"; do
  [[ ${patch} != /* && ${patch} != *..* && ${patch} != *//* ]] ||
    fail "unsafe patch path in SERIES: ${patch}"
  [[ -r ${REPO_ROOT}/patches/${patch} ]] || fail "patch listed in SERIES is missing: ${patch}"
  [[ -z ${patch_seen[${patch}]:-} ]] || fail "duplicate patch in SERIES: ${patch}"
  patch_seen[${patch}]=1
done

bad_tracked=$(git -C "${REPO_ROOT}" ls-files | grep -E -n -- '(^|/)(__pycache__/|.*\\.py[co]$|.*\\.(iso|pkg\\.tar\\.|log|core|dump)$)' || true)
[[ -z ${bad_tracked} ]] || fail "generated/build output is tracked:\n${bad_tracked}"

git -C "${REPO_ROOT}" diff --check || fail 'whitespace errors are present'
[[ -x ${REPO_ROOT}/installer/build-iso.sh ]] || fail 'installer/build-iso.sh is not executable'
[[ -x ${REPO_ROOT}/ci/public-release-leak-gate.sh ]] || fail 'public leak gate is not executable'
[[ -r ${REPO_ROOT}/installer/archiso/efiboot/loader/loader.conf ]] || fail 'ISO loader configuration is missing'
grep -Fxq 'editor no' "${REPO_ROOT}/installer/archiso/efiboot/loader/loader.conf" ||
  fail 'ISO loader editor policy is not locked down'
grep -Fxq reflector "${REPO_ROOT}/installer/archiso/packages.x86_64" ||
  fail 'ISO profile does not include reflector'
grep -Fxq archlinux-keyring "${REPO_ROOT}/installer/archiso/packages.x86_64" ||
  fail 'ISO profile does not include archlinux-keyring'

if [[ ${AURADE_VERIFY_MAKEPKG_METADATA:-0} == 1 ]]; then
  command -v makepkg >/dev/null 2>&1 || fail 'AURADE_VERIFY_MAKEPKG_METADATA=1 requires makepkg'
  for package in "${packages[@]}"; do
    generated=$(mktemp)
    trap 'rm -f -- "${generated:-}"' EXIT
    (cd "${REPO_ROOT}/${package}" && makepkg --printsrcinfo >"${generated}") ||
      fail "makepkg could not regenerate .SRCINFO: ${package}"
    cmp -s "${REPO_ROOT}/${package}/.SRCINFO" "${generated}" ||
      fail ".SRCINFO is stale according to makepkg: ${package}"
    rm -f -- "${generated}"
    trap - EXIT
  done
fi

printf 'Source integrity gate passed: %s packages, %s patches\n' \
  "${#packages[@]}" "${#patch_names[@]}"
