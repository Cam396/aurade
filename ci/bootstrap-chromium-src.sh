#!/bin/bash
# Bootstrap a pinned Chromium source checkout for AuraDE Arch CI, so package
# builds do not depend on a pre-synced developer CHROME_SRC.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

DEPOT_TOOLS="${AURADE_DEPOT_TOOLS:-${REPO_ROOT}/depot_tools_fresh}"
TARGET="${AURADE_BOOTSTRAP_TARGET:-/mnt/build/aurade-work/chromium-bootstrap}"
REVISION="${AURADE_CHROMIUM_REVISION:-}"
JOBS="${AURADE_BOOTSTRAP_JOBS:-8}"
mode="plan"

usage() {
  cat <<'EOF'
Usage: ci/bootstrap-chromium-src.sh [options]

Creates a self-contained, pinned Chromium checkout that reproduces the
source state AuraDE builds from, without relying on the developer's
pre-synced chromium_dev/src. The result can be fed to
ci/verify-patch-series.sh and build-chromeos-ash.sh via CHROME_SRC.

Options:
  --revision SHA   Chromium src revision to pin. Default: HEAD of
                   chromium_dev/src when present, otherwise pins/chromium.sha.
  --target DIR     Checkout parent directory (holds .gclient and src/).
                   Default: /mnt/build/aurade-work/chromium-bootstrap
  --run            Actually perform the sync. Without this flag the script
                   prints the plan and exits (safe dry run).
  --verify-series  After sync, run ci/verify-patch-series.sh against the
                   fresh checkout to prove the patch series applies to it
                   (uses a scratch worktree; the checkout stays pristine).
  --apply-series   After sync, apply patches/SERIES directly into the
                   checkout so it is ready for CHROME_SRC=<target>/src
                   makepkg / build-chromeos-ash.sh.
  -h, --help       Show this help.

Environment:
  AURADE_DEPOT_TOOLS=/path/to/depot_tools
  AURADE_BOOTSTRAP_TARGET=/mnt/build/aurade-work/chromium-bootstrap
  AURADE_CHROMIUM_REVISION=<sha>
  AURADE_BOOTSTRAP_JOBS=8
EOF
}

verify_series=0
apply_series=0
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --revision)
      REVISION="$2"; shift 2 ;;
    --target)
      TARGET="$2"; shift 2 ;;
    --run)
      mode="run"; shift ;;
    --verify-series)
      verify_series=1; shift ;;
    --apply-series)
      apply_series=1; shift ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "${REVISION}" ]]; then
  if [[ -d "${REPO_ROOT}/chromium_dev/src/.git" ]]; then
    REVISION="$(git -C "${REPO_ROOT}/chromium_dev/src" rev-parse HEAD)"
  elif [[ -r "${REPO_ROOT}/pins/chromium.sha" ]]; then
    REVISION="$(tr -d '[:space:]' < "${REPO_ROOT}/pins/chromium.sha")"
  else
    echo "No --revision given, no chromium_dev/src, and no pins/chromium.sha." >&2
    exit 2
  fi
fi
[[ "${REVISION}" =~ ^[0-9a-fA-F]{40}$ ]] || {
  echo "Chromium revision must be a 40-character commit SHA: ${REVISION}" >&2
  exit 2
}

if [[ ! -x "${DEPOT_TOOLS}/gclient" ]]; then
  echo "depot_tools not found at ${DEPOT_TOOLS} (set AURADE_DEPOT_TOOLS)." >&2
  exit 2
fi

cat <<EOF
Bootstrap plan:
  depot_tools:   ${DEPOT_TOOLS}
  target dir:    ${TARGET}
  src revision:  ${REVISION}
  jobs:          ${JOBS}
  steps:
    1. mkdir -p ${TARGET}
    2. write ${TARGET}/.gclient (solution "src", target_os ["chromeos"])
    3. gclient sync --revision src@${REVISION} --no-history --shallow \\
         --nohooks -j${JOBS}
    4. gclient runhooks (fetches clang, gn, sysroot, node, etc.)
$( [[ "${verify_series}" == "1" ]] && echo "    5. CHROME_SRC=${TARGET}/src ci/verify-patch-series.sh" )
$( [[ "${apply_series}" == "1" ]] && echo "    6. git apply patches/SERIES into ${TARGET}/src (ready for makepkg)" )
EOF

if [[ "${mode}" != "run" ]]; then
  echo
  echo "Dry run only. Re-run with --run to execute."
  exit 0
fi

export PATH="${DEPOT_TOOLS}:${PATH}"
export DEPOT_TOOLS_UPDATE=0
# Some Googlesource mirrors advertise Git LFS but reject its batch endpoint.
# Chromium's target-specific hooks fetch required prebuilts separately.
export GIT_LFS_SKIP_SMUDGE=1

mkdir -p "${TARGET}"
cat > "${TARGET}/.gclient" <<EOF
solutions = [
  {
    "name": "src",
    "url": "https://chromium.googlesource.com/chromium/src.git",
    "managed": False,
    "custom_deps": {},
    "custom_vars": {},
  },
]
target_os = ["chromeos"]
EOF

cd "${TARGET}"
echo "==> gclient sync (this downloads tens of GB; expect hours)"
gclient sync --revision "src@${REVISION}" --no-history --shallow \
  --nohooks -j"${JOBS}"
echo "==> gclient runhooks"
gclient runhooks -j"${JOBS}"

echo "==> synced $(git -C "${TARGET}/src" rev-parse HEAD)"

if [[ "${verify_series}" == "1" ]]; then
  echo "==> verifying patch series against the fresh checkout"
  CHROME_SRC="${TARGET}/src" "${SCRIPT_DIR}/verify-patch-series.sh" \
    --base-ref "${REVISION}"
fi

if [[ "${apply_series}" == "1" ]]; then
  echo "==> applying patch series into the checkout"
  while IFS= read -r patch_name; do
    [[ -z "${patch_name}" || "${patch_name}" == \#* ]] && continue
    echo "  applying ${patch_name}"
    git -C "${TARGET}/src" apply --whitespace=error-all \
      "${REPO_ROOT}/patches/${patch_name}"
  done < "${REPO_ROOT}/patches/SERIES"
  echo "==> series applied; checkout is ready for CHROME_SRC=${TARGET}/src"
fi

echo "Bootstrap complete: ${TARGET}/src"
