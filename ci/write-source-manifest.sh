#!/bin/bash
# Write a source/patch manifest for the current AuraDE build inputs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CHROME_SRC="${CHROME_SRC:-${REPO_ROOT}/chromium_dev/src}"
WORKDIR="${AURADE_WORKDIR:-/mnt/build/aurade-work}"
OUTPUT="${AURADE_SOURCE_MANIFEST:-${WORKDIR}/source-manifest.md}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

need git
need sha256sum

install -d -m 755 "$(dirname "${OUTPUT}")"

{
  echo "# AuraDE Source Manifest"
  echo
  echo "- Generated UTC: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "- Repo root: ${REPO_ROOT}"
  echo "- Chromium source: ${CHROME_SRC}"
  if [[ -d "${CHROME_SRC}/.git" ]]; then
    echo "- Chromium revision: $(git -C "${CHROME_SRC}" rev-parse HEAD)"
    echo "- Chromium branch: $(git -C "${CHROME_SRC}" rev-parse --abbrev-ref HEAD)"
    echo
    echo "## Chromium Worktree Status"
    echo
    git -C "${CHROME_SRC}" status --short || true
  else
    echo "- Chromium revision: unavailable"
  fi

  echo
  echo "## Patch Series"
  echo
  while IFS= read -r patch_entry; do
    [[ -z "${patch_entry}" || "${patch_entry}" == \#* ]] && continue
    patch_path="${REPO_ROOT}/patches/${patch_entry}"
    if [[ ! -f "${patch_path}" ]]; then
      echo "- MISSING ${patch_entry}"
      continue
    fi
    patch_hash="$(sha256sum "${patch_path}" | awk '{print $1}')"
    echo "- ${patch_hash}  ${patch_entry}"
  done < "${REPO_ROOT}/patches/SERIES"

  echo
  echo "## Package Sources"
  echo
  package_dirs=(
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
  for package_dir in "${package_dirs[@]}"; do
    echo
    echo "### ${package_dir}"
    find "${REPO_ROOT}/${package_dir}" -maxdepth 3 -type f | sort | while read -r source_file; do
      source_hash="$(sha256sum "${source_file}" | awk '{print $1}')"
      echo "- ${source_hash}  ${source_file#"${REPO_ROOT}/"}"
    done
  done

  echo
  echo "## CI Scripts"
  echo
  find "${REPO_ROOT}/ci" -maxdepth 1 -type f | sort | while read -r ci_file; do
    ci_hash="$(sha256sum "${ci_file}" | awk '{print $1}')"
    echo "- ${ci_hash}  ci/$(basename "${ci_file}")"
  done
} >"${OUTPUT}"

echo "Source manifest written: ${OUTPUT}"
