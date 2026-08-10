#!/bin/bash
# Verify that patches/SERIES applies cleanly to a fresh Chromium source worktree.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CHROME_SRC="${CHROME_SRC:-${REPO_ROOT}/chromium_dev/src}"
PATCH_DIR="${PATCH_DIR:-${REPO_ROOT}/patches}"
SERIES_FILE="${SERIES_FILE:-${PATCH_DIR}/SERIES}"
WORKDIR="${AURADE_WORKDIR:-/mnt/build/aurade-work}"
BASE_REF="${AURADE_PATCH_BASE_REF:-HEAD}"
VERIFY_DIR="${AURADE_PATCH_VERIFY_DIR:-}"
keep=0
expect_tree_match=0

usage() {
  cat <<'EOF'
Usage: ci/verify-patch-series.sh [options]

Creates a detached scratch git worktree from CHROME_SRC, then applies every
patch listed in patches/SERIES in order. It exits non-zero at the first missing,
duplicate, or non-applying patch.

Options:
  --base-ref REF  Git ref in CHROME_SRC to verify against. Default: HEAD.
  --keep          Keep the scratch worktree for inspection after failure/success.
  --expect-tree-match
                  After applying the series, require every file changed in the
                  CHROME_SRC working tree (tracked modifications and untracked
                  additions) to byte-match the patched scratch worktree. This
                  proves the series fully reproduces the current source state.
  -h, --help      Show this help.

Environment:
  CHROME_SRC=/path/to/chromium/src
  PATCH_DIR=/path/to/patches
  SERIES_FILE=/path/to/patches/SERIES
  AURADE_WORKDIR=/mnt/build/aurade-work
  AURADE_PATCH_VERIFY_DIR=/explicit/scratch/worktree
  AURADE_PATCH_BASE_REF=HEAD
EOF
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --base-ref)
      if [[ "$#" -lt 2 ]]; then
        echo "--base-ref requires a value" >&2
        exit 2
      fi
      BASE_REF="$2"
      shift 2
      ;;
    --keep)
      keep=1
      shift
      ;;
    --expect-tree-match)
      expect_tree_match=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

need git

if ! git -C "${CHROME_SRC}" rev-parse --git-dir >/dev/null 2>&1; then
  echo "Chromium source git repo not found: ${CHROME_SRC}" >&2
  exit 1
fi
if [[ ! -r "${SERIES_FILE}" ]]; then
  echo "Patch series file not found: ${SERIES_FILE}" >&2
  exit 1
fi

mapfile -t series < <(
  sed -E 's/[[:space:]]+#.*$//; /^[[:space:]]*($|#)/d; s/^[[:space:]]+//; s/[[:space:]]+$//' \
    "${SERIES_FILE}"
)
if [[ "${#series[@]}" -eq 0 ]]; then
  echo "Patch series is empty: ${SERIES_FILE}" >&2
  exit 1
fi

declare -A seen=()
for patch_name in "${series[@]}"; do
  if [[ -n "${seen[${patch_name}]:-}" ]]; then
    echo "Duplicate patch in series: ${patch_name}" >&2
    exit 1
  fi
  seen["${patch_name}"]=1

  case "${patch_name}" in
    /*|*..*|*//*)
      echo "Unsafe patch path in series: ${patch_name}" >&2
      exit 1
      ;;
  esac

  if [[ ! -r "${PATCH_DIR}/${patch_name}" ]]; then
    echo "Patch listed in series is missing: ${PATCH_DIR}/${patch_name}" >&2
    exit 1
  fi
done

created_worktree=0
if [[ -z "${VERIFY_DIR}" ]]; then
  install -d -m 755 "${WORKDIR}"
  VERIFY_DIR="$(mktemp -d "${WORKDIR}/aurade-patch-verify.XXXXXX")"
  rmdir "${VERIFY_DIR}"
  created_worktree=1
fi

cleanup() {
  if [[ "${keep}" == "1" ]]; then
    echo "Keeping patch verification worktree: ${VERIFY_DIR}" >&2
    return
  fi
  if [[ "${created_worktree}" == "1" && -d "${VERIFY_DIR}" ]]; then
    git -C "${CHROME_SRC}" worktree remove --force "${VERIFY_DIR}" >/dev/null 2>&1 || \
      rm -rf "${VERIFY_DIR}"
  fi
}
trap cleanup EXIT

if [[ -e "${VERIFY_DIR}" ]]; then
  echo "Verification directory already exists: ${VERIFY_DIR}" >&2
  exit 1
fi

git -C "${CHROME_SRC}" worktree add --detach --quiet "${VERIFY_DIR}" "${BASE_REF}"

applied=0
for patch_name in "${series[@]}"; do
  patch_path="${PATCH_DIR}/${patch_name}"
  echo "==> Checking ${patch_name}"
  if ! git -C "${VERIFY_DIR}" apply --check --whitespace=error-all "${patch_path}"; then
    echo "Patch failed --check: ${patch_name}" >&2
    echo "Scratch worktree: ${VERIFY_DIR}" >&2
    keep=1
    exit 1
  fi
  git -C "${VERIFY_DIR}" apply --whitespace=error-all "${patch_path}"
  applied=$((applied + 1))
done

git -C "${VERIFY_DIR}" diff --check
echo "Patch series applied cleanly: ${applied} patches"

if [[ "${expect_tree_match}" == "1" ]]; then
  echo "==> Checking patched worktree against CHROME_SRC working tree"
  mismatches=0
  while IFS= read -r line; do
    src_file="${line:3}"
    if [[ ! -f "${CHROME_SRC}/${src_file}" ]]; then
      echo "Working tree deletes are not supported by the series: ${src_file}" >&2
      mismatches=$((mismatches + 1))
      continue
    fi
    if ! cmp -s "${CHROME_SRC}/${src_file}" "${VERIFY_DIR}/${src_file}"; then
      echo "Series does not reproduce working tree file: ${src_file}" >&2
      mismatches=$((mismatches + 1))
    fi
  done < <(git -C "${CHROME_SRC}" status --porcelain --untracked-files=all)
  if [[ "${mismatches}" -gt 0 ]]; then
    echo "Series/tree mismatch count: ${mismatches}" >&2
    echo "Scratch worktree: ${VERIFY_DIR}" >&2
    keep=1
    exit 1
  fi
  echo "Series reproduces the working tree: OK"
fi
