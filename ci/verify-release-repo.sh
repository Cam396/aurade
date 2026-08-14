#!/bin/bash
# Verify that an AuraDE repository contains exactly the current package set.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_DIR="${REPO_DIR:-${REPO_ROOT}/private-repo}"
REPO_NAME="${REPO_NAME:-aurade}"
REQUIRE_SIGNATURES="${AURADE_REQUIRE_SIGNATURES:-0}"
REPO_KEYRING="${AURADE_REPO_KEYRING:-}"
REPO_FINGERPRINT="${AURADE_REPO_FINGERPRINT:-}"
mapfile -t PACKAGE_DIRS < <(
  sed -E '/^[[:space:]]*(#|$)/d; s/[[:space:]]+$//' \
    "${REPO_ROOT}/installer/expected-packages.txt"
)
(( ${#PACKAGE_DIRS[@]} > 0 )) || {
  echo "Expected package list is empty: ${REPO_ROOT}/installer/expected-packages.txt" >&2
  exit 1
}

for command in makepkg pacman bsdtar sha256sum; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Missing required command: ${command}" >&2
    exit 2
  }
done
if [[ "${REQUIRE_SIGNATURES}" == 1 ]]; then
  for command in gpg gpgv; do
    command -v "${command}" >/dev/null 2>&1 || {
      echo "Missing required command: ${command}" >&2
      exit 2
    }
  done
  [[ -r "${REPO_KEYRING}" ]] || {
    echo "AURADE_REPO_KEYRING must name a readable public keyring when signatures are required" >&2
    exit 2
  }
  normalized_fingerprint="${REPO_FINGERPRINT//[[:space:]]/}"
  normalized_fingerprint="${normalized_fingerprint^^}"
  [[ "${normalized_fingerprint}" =~ ^[0-9A-F]{40,64}$ ]] || {
    echo "AURADE_REPO_FINGERPRINT must be a full fingerprint when signatures are required" >&2
    exit 2
  }
  key_listing=$(gpg --batch --show-keys --with-colons "${REPO_KEYRING}" 2>/dev/null) || {
    echo "AURADE_REPO_KEYRING could not be parsed" >&2
    exit 2
  }
  if awk -F: '$1 == "sec" || $1 == "ssb" {found=1} END {exit !found}' <<<"${key_listing}"; then
    echo "AURADE_REPO_KEYRING must contain public keys only" >&2
    exit 2
  fi
  key_fingerprints=$(awk -F: '$1 == "fpr" {print toupper($10)}' <<<"${key_listing}")
  grep -Fxq "${normalized_fingerprint}" <<<"${key_fingerprints}" || {
    echo "AURADE_REPO_KEYRING does not contain AURADE_REPO_FINGERPRINT" >&2
    exit 2
  }
fi

verify_detached_signature() {
  local signature=$1 payload=$2 label=$3 status signer primary
  if ! status=$(gpgv --status-fd 1 --keyring "${REPO_KEYRING}" \
      "${signature}" "${payload}" 2>/dev/null); then
    echo "Invalid ${label} signature" >&2
    return 1
  fi
  signer=$(awk '$1 == "[GNUPG:]" && $2 == "VALIDSIG" {print toupper($3); exit}' <<<"${status}")
  primary=$(awk '$1 == "[GNUPG:]" && $2 == "VALIDSIG" {print toupper($NF); exit}' <<<"${status}")
  [[ "${signer}" == "${normalized_fingerprint}" ||
     "${primary}" == "${normalized_fingerprint}" ]] || {
    echo "${label} signature signer does not match AURADE_REPO_FINGERPRINT" >&2
    return 1
  }
}

database="${REPO_DIR}/${REPO_NAME}.db.tar.gz"
[[ -f "${database}" ]] || {
  echo "Missing repository database: ${database}" >&2
  exit 1
}
REPO_DIR="${REPO_DIR}" "${SCRIPT_DIR}/verify-release-checksums.sh"

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
declare -a version_mismatches=()

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
    verify_detached_signature "${package_file}.sig" "${package_file}" "${package_file##*/}"
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
  verify_detached_signature "${database}.sig" "${database}" "repository database"
fi

for package_name in "${!expected_versions[@]}"; do
  expected="${expected_versions[${package_name}]}"
  artifact_version="${artifact_versions[${package_name}]:-missing}"
  database_version="${database_versions[${package_name}]:-missing}"
  if [[ "${artifact_version}" != "${expected}" ]]; then
    version_mismatches+=("Artifact mismatch for ${package_name}: expected ${expected}, found ${artifact_version}")
  fi
  if [[ "${database_version}" != "${expected}" ]]; then
    version_mismatches+=("Database mismatch for ${package_name}: expected ${expected}, found ${database_version}")
  fi
done

for package_name in "${!artifact_versions[@]}"; do
  [[ -n "${expected_versions[${package_name}]:-}" ]] || {
    version_mismatches+=("Unexpected package artifact: ${package_name} (not present in the expected package set)")
  }
done
for package_name in "${!database_versions[@]}"; do
  [[ -n "${expected_versions[${package_name}]:-}" ]] || {
    version_mismatches+=("Unexpected package in repository database: ${package_name} (not present in the expected package set)")
  }
done

if ((${#version_mismatches[@]} > 0)); then
  echo "Release repository package-set verification failed; review all findings before rebuilding or publishing:" >&2
  printf '  - %s\n' "${version_mismatches[@]}" >&2
  exit 1
fi

echo "Release repository verified: ${#package_files[@]} current packages"
