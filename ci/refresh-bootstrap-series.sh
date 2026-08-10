#!/bin/bash
# Refresh a warm pinned Chromium checkout to the current AuraDE patch series.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CHROME_SRC="${CHROME_SRC:-/mnt/build/aurade-work/chromium-bootstrap/src}"
REVISION="${AURADE_CHROMIUM_REVISION:-}"
WORKDIR="${AURADE_WORKDIR:-/mnt/build/aurade-work}"
VERIFY_DIR="${WORKDIR}/bootstrap-series-refresh.$$"
PATHS_FILE="${VERIFY_DIR}.paths"
check_only=0

case "${1:-}" in
  --check)
    check_only=1
    shift
    ;;
  "")
    ;;
  *)
    echo "Usage: $0 [--check]" >&2
    exit 2
    ;;
esac
[[ "$#" -eq 0 ]] || {
  echo "Usage: $0 [--check]" >&2
  exit 2
}

cleanup() {
  git -C "${CHROME_SRC}" worktree remove --force "${VERIFY_DIR}" \
    >/dev/null 2>&1 || true
  rm -f "${PATHS_FILE}"
}
trap cleanup EXIT

if [[ ! -d "${CHROME_SRC}/.git" ]]; then
  echo "Pinned Chromium checkout not found: ${CHROME_SRC}" >&2
  exit 2
fi

if [[ -z "${REVISION}" ]]; then
  REVISION="$(git -C "${CHROME_SRC}" rev-parse HEAD)"
fi

owner_uid="$(stat -c '%u' "${CHROME_SRC}")"
if [[ "$(id -u)" != "${owner_uid}" ]]; then
  echo "Run as the checkout owner (uid ${owner_uid}); current uid is $(id -u)." >&2
  exit 2
fi

mkdir -p "${WORKDIR}" || {
  echo "Work directory is not writable: ${WORKDIR}" >&2
  exit 2
}
if [[ ! -w "${WORKDIR}" ]]; then
  echo "Work directory is not writable: ${WORKDIR}" >&2
  exit 2
fi

actual_revision="$(git -C "${CHROME_SRC}" rev-parse HEAD)"
if [[ "${actual_revision}" != "${REVISION}" ]]; then
  echo "Pinned checkout is at ${actual_revision}, expected ${REVISION}." >&2
  exit 1
fi

echo "==> Creating clean series reference at ${REVISION}"
while IFS= read -r patch_name; do
  [[ -z "${patch_name}" || "${patch_name}" == \#* ]] && continue
  awk '/^\+\+\+ b\// {sub(/^\+\+\+ b\//, ""); print}' \
    "${REPO_ROOT}/patches/${patch_name}"
done < "${REPO_ROOT}/patches/SERIES" | sort -u > "${PATHS_FILE}"

if [[ ! -s "${PATHS_FILE}" ]]; then
  echo "Patch series owns no files." >&2
  exit 1
fi

git -C "${CHROME_SRC}" worktree add --detach --no-checkout \
  "${VERIFY_DIR}" "${REVISION}" >/dev/null
git -C "${VERIFY_DIR}" sparse-checkout init --no-cone
git -C "${VERIFY_DIR}" sparse-checkout set --no-cone --stdin \
  < "${PATHS_FILE}"
git -C "${VERIFY_DIR}" checkout --detach "${REVISION}" >/dev/null

while IFS= read -r patch_name; do
  [[ -z "${patch_name}" || "${patch_name}" == \#* ]] && continue
  echo "  applying ${patch_name}"
  git -C "${VERIFY_DIR}" apply --whitespace=error-all \
    "${REPO_ROOT}/patches/${patch_name}"
done < "${REPO_ROOT}/patches/SERIES"

if [[ "${check_only}" == 1 ]]; then
  echo "==> Checking $(wc -l < "${PATHS_FILE}") patch-owned files"
else
  echo "==> Refreshing $(wc -l < "${PATHS_FILE}") patch-owned files"
fi
refreshed=0
mismatches=0
while IFS= read -r path; do
  if [[ ! -e "${CHROME_SRC}/${path}" ]] ||
      ! cmp -s "${VERIFY_DIR}/${path}" "${CHROME_SRC}/${path}"; then
    if [[ "${check_only}" == 1 ]]; then
      echo "Bootstrap source mismatch: ${path}" >&2
      mismatches=$((mismatches + 1))
      continue
    fi
    mkdir -p "${CHROME_SRC}/$(dirname "${path}")"
    cp -a "${VERIFY_DIR}/${path}" "${CHROME_SRC}/${path}"
    refreshed=$((refreshed + 1))
  fi
done < "${PATHS_FILE}"
if [[ "${check_only}" == 1 ]]; then
  if (( mismatches > 0 )); then
    echo "Bootstrap source mismatch count: ${mismatches}" >&2
    exit 1
  fi
  echo "Bootstrap source matches the current series: ${CHROME_SRC}"
  exit 0
fi
echo "==> Updated ${refreshed} byte-different files"

mismatches=0
while IFS= read -r path; do
  if ! cmp -s "${VERIFY_DIR}/${path}" "${CHROME_SRC}/${path}"; then
    echo "Mismatch after refresh: ${path}" >&2
    mismatches=$((mismatches + 1))
  fi
done < "${PATHS_FILE}"

if (( mismatches > 0 )); then
  echo "Bootstrap refresh mismatch count: ${mismatches}" >&2
  exit 1
fi

echo "Bootstrap source matches the current series: ${CHROME_SRC}"
