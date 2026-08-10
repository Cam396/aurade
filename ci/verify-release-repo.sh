#!/bin/bash
# Verify that an AuraDE repository contains exactly the current package set.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_DIR="${REPO_DIR:-${REPO_ROOT}/private-repo}"
REPO_NAME="${REPO_NAME:-aurade}"
REQUIRE_SIGNATURES="${AURADE_REQUIRE_SIGNATURES:-0}"
PACKAGE_DIRS=(
  aurade-account-helper
  aurade-system-helper
  shill-nm-adapter
  aurade-power
  aurade-host-bridge
  chromiumos-ash
  aurade-login
  aurade-ai
  aurade-webapp-shortcuts
  aurade
  aurade-full
)

for command in makepkg pacman bsdtar sha256sum; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Missing required command: ${command}" >&2
    exit 2
  }
done
if [[ "${REQUIRE_SIGNATURES}" == 1 ]]; then
  command -v gpg >/dev/null 2>&1 || {
    echo "Missing required command: gpg" >&2
    exit 2
  }
fi

database="${REPO_DIR}/${REPO_NAME}.db.tar.gz"
[[ -f "${database}" ]] || {
  echo "Missing repository database: ${database}" >&2
  exit 1
}

while IFS= read -r -d '' repository_file; do
  repository_name="${repository_file##*/}"
  case "${repository_name}" in
    SHA256SUMS|"${REPO_NAME}.db.tar.gz"|"${REPO_NAME}.files.tar.gz"|\
      "${REPO_NAME}.db.tar.gz.sig"|"${REPO_NAME}.files.tar.gz.sig"|\
      *.pkg.tar.*)
      ;;
    *)
      echo "Unexpected published file: ${repository_name}" >&2
      exit 1
      ;;
  esac
done < <(find "${REPO_DIR}" -maxdepth 1 -type f -print0)

while IFS= read -r -d '' repository_link; do
  repository_name="${repository_link##*/}"
  case "${repository_name}" in
    "${REPO_NAME}.db"|"${REPO_NAME}.files"|\
      "${REPO_NAME}.db.sig"|"${REPO_NAME}.files.sig")
      [[ -e "${repository_link}" ]] || {
        echo "Broken repository link: ${repository_name}" >&2
        exit 1
      }
      ;;
    *)
      echo "Unexpected published link: ${repository_name}" >&2
      exit 1
      ;;
  esac
done < <(find "${REPO_DIR}" -maxdepth 1 -type l -print0)

while IFS= read -r -d '' repository_entry; do
  echo "Unexpected published entry: ${repository_entry##*/}" >&2
  exit 1
done < <(find "${REPO_DIR}" -mindepth 1 -maxdepth 1 \
  ! -type f ! -type l -print0)

declare -A expected_versions=()
declare -A artifact_versions=()
declare -A database_versions=()

for package_dir in "${PACKAGE_DIRS[@]}"; do
  srcinfo="$(cd "${REPO_ROOT}/${package_dir}" && makepkg --printsrcinfo)"
  if [[ ! -f "${REPO_ROOT}/${package_dir}/.SRCINFO" ]] ||
      ! cmp -s "${REPO_ROOT}/${package_dir}/.SRCINFO" \
        <(printf '%s\n' "${srcinfo}"); then
    echo "Stale or missing metadata: ${package_dir}/.SRCINFO" >&2
    exit 1
  fi
  package_name="$(awk -F' = ' '/^[[:space:]]*pkgname = / { print $2; exit }' <<<"${srcinfo}")"
  package_version="$(awk -F' = ' '/^[[:space:]]*pkgver = / { print $2; exit }' <<<"${srcinfo}")"
  package_release="$(awk -F' = ' '/^[[:space:]]*pkgrel = / { print $2; exit }' <<<"${srcinfo}")"
  epoch="$(awk -F' = ' '/^[[:space:]]*epoch = / { print $2; exit }' <<<"${srcinfo}")"
  [[ -n "${package_name}" && -n "${package_version}" && -n "${package_release}" ]] || {
    echo "Cannot derive package identity from ${package_dir}/PKGBUILD" >&2
    exit 1
  }
  if [[ -n "${epoch}" ]]; then
    package_version="${epoch}:${package_version}"
  fi
  expected_versions["${package_name}"]="${package_version}-${package_release}"
done

mapfile -t package_files < <(find "${REPO_DIR}" -maxdepth 1 -type f \
  -name '*.pkg.tar.*' ! -name '*.sig' | sort)
for package_file in "${package_files[@]}"; do
  read -r package_name package_version < <(pacman -Qp "${package_file}")
  if [[ -n "${artifact_versions[${package_name}]:-}" ]]; then
    echo "Duplicate package artifact: ${package_name}" >&2
    exit 1
  fi
  artifact_versions["${package_name}"]="${package_version}"
  pacman -Qip "${package_file}" >/dev/null
  pacman -Qlp "${package_file}" >/dev/null
  if [[ "${REQUIRE_SIGNATURES}" == 1 && ! -s "${package_file}.sig" ]]; then
    echo "Missing package signature: ${package_file}.sig" >&2
    exit 1
  fi
  if [[ "${REQUIRE_SIGNATURES}" == 1 ]]; then
    gpg --batch --verify "${package_file}.sig" "${package_file}" >/dev/null
  fi
done

database_listing="$(mktemp)"
trap 'rm -f "${database_listing}"' EXIT
bsdtar -xOf "${database}" --include '*/desc' >"${database_listing}"
while IFS=$'\t' read -r package_name package_version; do
  [[ -n "${package_name}" ]] || continue
  database_versions["${package_name}"]="${package_version}"
done < <(awk '
  $0 == "%NAME%" { getline; name=$0 }
  $0 == "%VERSION%" { getline; print name "\t" $0 }
' "${database_listing}")

if [[ "${REQUIRE_SIGNATURES}" == 1 && ! -s "${database}.sig" ]]; then
  echo "Missing repository database signature: ${database}.sig" >&2
  exit 1
fi
if [[ "${REQUIRE_SIGNATURES}" == 1 ]]; then
  gpg --batch --verify "${database}.sig" "${database}" >/dev/null
fi

for package_name in "${!expected_versions[@]}"; do
  expected="${expected_versions[${package_name}]}"
  [[ "${artifact_versions[${package_name}]:-}" == "${expected}" ]] || {
    echo "Artifact mismatch for ${package_name}: expected ${expected}, got ${artifact_versions[${package_name}]:-missing}" >&2
    exit 1
  }
  [[ "${database_versions[${package_name}]:-}" == "${expected}" ]] || {
    echo "Database mismatch for ${package_name}: expected ${expected}, got ${database_versions[${package_name}]:-missing}" >&2
    exit 1
  }
done

for package_name in "${!artifact_versions[@]}"; do
  [[ -n "${expected_versions[${package_name}]:-}" ]] || {
    echo "Unexpected package artifact: ${package_name}" >&2
    exit 1
  }
done
for package_name in "${!database_versions[@]}"; do
  [[ -n "${expected_versions[${package_name}]:-}" ]] || {
    echo "Unexpected package in repository database: ${package_name}" >&2
    exit 1
  }
done

mapfile -d '' checksum_files < <(find "${REPO_DIR}" -maxdepth 1 -type f \
  ! -name SHA256SUMS -printf '%f\0' | sort -z)
(
  cd "${REPO_DIR}"
  sha256sum -- "${checksum_files[@]}"
) >"${REPO_DIR}/SHA256SUMS"
echo "Release repository verified: ${#package_files[@]} current packages"
