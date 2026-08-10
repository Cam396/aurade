#!/bin/bash
# Maintain an isolated, warm, fully synced Chromium checkout for candidate gates.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ROOT="${AURADE_CANDIDATE_CHECKOUT_ROOT:-/mnt/build/aurade-work/chromium-candidate}"
SRC="${ROOT}/src"
STATE_DIR="${ROOT}/.aurade-state"
MARKER="${STATE_DIR}/owner"
ENV_FILE="${AURADE_MATERIALIZED_ENV:-${STATE_DIR}/materialized.env}"
SHA="${AURADE_CANDIDATE_SHA:-}"
REMOTE="${AURADE_CHROMIUM_REMOTE:-https://chromium.googlesource.com/chromium/src.git}"
PATCH_DIR="${PATCH_DIR:-${REPO_ROOT}/patches}"
SERIES_FILE="${SERIES_FILE:-${PATCH_DIR}/SERIES}"
DEPOT_TOOLS="${AURADE_DEPOT_TOOLS:-${REPO_ROOT}/depot_tools_fresh}"
JOBS="${AURADE_GCLIENT_JOBS:-8}"
OUT_DIR="${AURADE_CANDIDATE_OUT_DIR:-${SRC}/out/Ash}"
FORCE_HOOKS="${AURADE_FORCE_GCLIENT_HOOKS:-0}"
REFERENCE_REPO="${AURADE_CHROMIUM_REFERENCE:-${REPO_ROOT}/chromium_dev/src}"
INTERNAL_USER_RUN="${AURADE_MATERIALIZE_INTERNAL_USER_RUN:-0}"

usage() {
  cat <<'EOF'
Usage: ci/materialize-chromium-candidate.sh

Requires AURADE_CANDIDATE_SHA. Maintains a CI-owned gclient checkout at
AURADE_CANDIDATE_CHECKOUT_ROOT, restores only recorded patch-owned paths,
refuses unrelated source dirt, syncs the exact revision, runs hooks when their
inputs change, and applies patches/SERIES. out/ is never removed or cleaned.

The resulting tab-delimited descriptor is written to AURADE_MATERIALIZED_ENV:
  CHROME_SRC<TAB>/path/to/src
  AURADE_GN_OUT_DIR<TAB>/path/to/src/out/Ash
  AURADE_MATERIALIZED_SHA<TAB><immutable revision>
EOF
}

case "${1:-}" in
  "") ;;
  -h|--help) usage; exit 0 ;;
  *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
esac

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 2
  }
}
for command in git sha256sum flock awk sed sort find stat; do need "${command}"; done

[[ "${SHA}" =~ ^[0-9a-fA-F]{40,64}$ ]] || {
  echo "AURADE_CANDIDATE_SHA must be an immutable Git object ID" >&2
  exit 2
}
SHA="${SHA,,}"
[[ "${ROOT}" == /* && "${ROOT}" != "/" ]] || {
  echo "AURADE_CANDIDATE_CHECKOUT_ROOT must be an absolute non-root path" >&2
  exit 2
}
[[ "${OUT_DIR}" == "${SRC}/out/"* ]] || {
  echo "AURADE_CANDIDATE_OUT_DIR must be below ${SRC}/out" >&2
  exit 2
}
[[ "${JOBS}" =~ ^[1-9][0-9]*$ ]] || {
  echo "AURADE_GCLIENT_JOBS must be a positive integer" >&2
  exit 2
}
[[ -r "${SERIES_FILE}" ]] || { echo "Missing patch series: ${SERIES_FILE}" >&2; exit 2; }
[[ "${REMOTE}" != *'"'* && "${REMOTE}" != *$'\n'* ]] || {
  echo "AURADE_CHROMIUM_REMOTE contains unsupported characters" >&2
  exit 2
}
[[ -x "${DEPOT_TOOLS}/gclient" ]] || {
  echo "gclient not found at ${DEPOT_TOOLS}/gclient" >&2
  exit 2
}

# Chromium tooling should not run as root. When the system pipeline is root,
# default to the local reference checkout owner unless explicitly overridden.
candidate_user="${AURADE_CANDIDATE_USER:-}"
if [[ -z "${candidate_user}" ]] && git -C "${REFERENCE_REPO}" rev-parse --git-dir >/dev/null 2>&1; then
  candidate_user="$(stat -c '%U' "${REFERENCE_REPO}")"
fi
if [[ "$(id -u)" -eq 0 && "${INTERNAL_USER_RUN}" != "1" &&
      -n "${candidate_user}" && "${candidate_user}" != root &&
      "${candidate_user}" != UNKNOWN ]]; then
  need runuser
  candidate_group="$(id -gn "${candidate_user}")"
  if [[ -e "${ROOT}" && "$(stat -c '%U' "${ROOT}")" != "${candidate_user}" ]]; then
    echo "Candidate root owner mismatch: ${ROOT} must be owned by ${candidate_user}" >&2
    exit 2
  fi
  install -d -o "${candidate_user}" -g "${candidate_group}" -m 755 "${ROOT}"
  export AURADE_MATERIALIZE_INTERNAL_USER_RUN=1
  exec runuser -u "${candidate_user}" -- "$0"
fi

install -d -m 755 "${ROOT}"
exec 9>"${ROOT}/.materialize.lock"
if ! flock -n 9; then
  echo "Candidate checkout is already being materialized: ${ROOT}" >&2
  exit 75
fi

if [[ -e "${ROOT}" && ! -r "${MARKER}" ]] &&
    find "${ROOT}" -mindepth 1 -maxdepth 1 ! -name .materialize.lock \
      -print -quit | grep -q .; then
  echo "Refusing unowned non-empty candidate root: ${ROOT}" >&2
  exit 2
fi
install -d -m 755 "${ROOT}" "${STATE_DIR}"
if [[ ! -e "${MARKER}" ]]; then
  printf 'AuraDE isolated Chromium candidate checkout v1\n' > "${MARKER}"
fi
grep -Fxq 'AuraDE isolated Chromium candidate checkout v1' "${MARKER}" || {
  echo "Invalid candidate checkout ownership marker: ${MARKER}" >&2
  exit 2
}

developer_src=""
if git -C "${REFERENCE_REPO}" rev-parse --show-toplevel >/dev/null 2>&1; then
  developer_src="$(cd "${REFERENCE_REPO}" && pwd -P)"
fi
if [[ -d "${SRC}" && "$(cd "${SRC}" && pwd -P)" == "${developer_src}" ]]; then
  echo "Candidate checkout must not be the developer source tree" >&2
  exit 2
fi

mapfile -t series < <(
  sed -E 's/[[:space:]]+#.*$//; /^[[:space:]]*($|#)/d; s/^[[:space:]]+//; s/[[:space:]]+$//' \
    "${SERIES_FILE}"
)
[[ "${#series[@]}" -gt 0 ]] || { echo "Patch series is empty" >&2; exit 2; }

current_paths="${STATE_DIR}/current-patch-paths.tmp.$$"
union_paths="${STATE_DIR}/restore-paths.tmp.$$"
cleanup() { rm -f "${current_paths}" "${union_paths}"; }
trap cleanup EXIT
: > "${current_paths}"
declare -A seen=()
series_material=""
for patch_name in "${series[@]}"; do
  case "${patch_name}" in
    /*|*..*|*//* ) echo "Unsafe patch path: ${patch_name}" >&2; exit 2 ;;
  esac
  [[ -z "${seen[${patch_name}]:-}" ]] || {
    echo "Duplicate patch in series: ${patch_name}" >&2
    exit 2
  }
  seen["${patch_name}"]=1
  patch_path="${PATCH_DIR}/${patch_name}"
  [[ -r "${patch_path}" ]] || { echo "Missing patch: ${patch_path}" >&2; exit 2; }
  series_material+="$(sha256sum "${patch_path}")"$'\n'
  awk '
    ($1 == "---" || $1 == "+++") && $2 != "/dev/null" {
      path = $2
      sub(/^[ab]\//, "", path)
      print path
    }
  ' "${patch_path}" >> "${current_paths}"
done
sort -u -o "${current_paths}" "${current_paths}"
while IFS= read -r path; do
  [[ -n "${path}" ]] || continue
  case "${path}" in
    /*|*..*|*//* ) echo "Unsafe patch-owned path: ${path}" >&2; exit 2 ;;
  esac
done < "${current_paths}"
series_digest="$(printf '%s' "${series_material}" | sha256sum | awk '{print $1}')"

if [[ -d "${SRC}/.git" || -f "${SRC}/.git" ]]; then
  {
    [[ -r "${STATE_DIR}/patch-paths" ]] && cat "${STATE_DIR}/patch-paths"
    [[ -r "${STATE_DIR}/attempted-patch-paths" ]] &&
      cat "${STATE_DIR}/attempted-patch-paths"
    cat "${current_paths}"
  } | sort -u > "${union_paths}"

  echo "==> Restoring recorded patch-owned paths at the prior base"
  while IFS= read -r path; do
    [[ -n "${path}" ]] || continue
    if git -C "${SRC}" cat-file -e "HEAD:${path}" 2>/dev/null; then
      git -C "${SRC}" restore --source=HEAD --staged --worktree -- "${path}"
    elif [[ -e "${SRC}/${path}" || -L "${SRC}/${path}" ]]; then
      rm -f -- "${SRC}/${path}"
    fi
  done < "${union_paths}"

  if [[ -n "$(git -C "${SRC}" status --porcelain=v1 --untracked-files=all)" ]]; then
    echo "Refusing to sync: isolated checkout has non-patch source changes" >&2
    git -C "${SRC}" status --short --untracked-files=all >&2
    exit 1
  fi
fi

cp "${current_paths}" "${STATE_DIR}/attempted-patch-paths.tmp.$$"
mv -f "${STATE_DIR}/attempted-patch-paths.tmp.$$" \
  "${STATE_DIR}/attempted-patch-paths"

cat > "${ROOT}/.gclient.tmp.$$" <<EOF
solutions = [
  {
    "name": "src",
    "url": "${REMOTE}",
    "managed": False,
    "custom_deps": {},
    "custom_vars": {},
  },
]
target_os = ["chromeos"]
EOF
mv -f "${ROOT}/.gclient.tmp.$$" "${ROOT}/.gclient"

export PATH="${DEPOT_TOOLS}:${PATH}"
export DEPOT_TOOLS_UPDATE=0
export GIT_LFS_SKIP_SMUDGE=1
echo "==> Syncing isolated candidate ${SHA}"
(
  cd "${ROOT}"
  gclient sync --revision "src@${SHA}" --no-history --shallow --nohooks \
    --jobs "${JOBS}"
)
actual_sha="$(git -C "${SRC}" rev-parse HEAD)"
[[ "${actual_sha}" == "${SHA}" ]] || {
  echo "gclient synced ${actual_sha}, expected ${SHA}" >&2
  exit 1
}

fingerprint_material=""
fingerprint_inputs=(
  "${ROOT}/.gclient"
  "${SRC}/DEPS"
  "${SRC}/build/config/gclient_args.gni"
  "${SRC}/build/linux/sysroot_scripts/install-sysroot.py"
  "${SRC}/tools/clang/scripts/update.py"
)
for input in "${fingerprint_inputs[@]}"; do
  [[ -f "${input}" ]] && fingerprint_material+="$(sha256sum "${input}")"$'\n'
done
hooks_fingerprint="$(printf '%s' "${fingerprint_material}" | sha256sum | awk '{print $1}')"
hooks_needed=0
[[ "${FORCE_HOOKS}" == "1" ]] && hooks_needed=1
[[ ! -r "${STATE_DIR}/hooks-fingerprint" ]] && hooks_needed=1
[[ -r "${STATE_DIR}/hooks-fingerprint" &&
   "$(<"${STATE_DIR}/hooks-fingerprint")" != "${hooks_fingerprint}" ]] && hooks_needed=1
[[ ! -x "${SRC}/buildtools/linux64/gn" ]] && hooks_needed=1
[[ ! -x "${SRC}/third_party/ninja/ninja" ]] && hooks_needed=1
if [[ "${hooks_needed}" == "1" ]]; then
  echo "==> Running gclient hooks (tool inputs changed or tools are missing)"
  (cd "${ROOT}" && gclient runhooks --jobs "${JOBS}")
  printf '%s\n' "${hooks_fingerprint}" > "${STATE_DIR}/hooks-fingerprint.tmp.$$"
  mv -f "${STATE_DIR}/hooks-fingerprint.tmp.$$" "${STATE_DIR}/hooks-fingerprint"
else
  echo "==> Skipping gclient hooks (fingerprint and tools unchanged)"
fi

if [[ -n "$(git -C "${SRC}" status --porcelain=v1 --untracked-files=all)" ]]; then
  echo "Refusing to apply patches: sync/hooks left source changes" >&2
  git -C "${SRC}" status --short --untracked-files=all >&2
  exit 1
fi

echo "==> Applying AuraDE series (${#series[@]} patches)"
for patch_name in "${series[@]}"; do
  git -C "${SRC}" apply --check --whitespace=error-all "${PATCH_DIR}/${patch_name}"
  git -C "${SRC}" apply --whitespace=error-all "${PATCH_DIR}/${patch_name}"
done
git -C "${SRC}" diff --check

cp "${current_paths}" "${STATE_DIR}/patch-paths.tmp.$$"
mv -f "${STATE_DIR}/patch-paths.tmp.$$" "${STATE_DIR}/patch-paths"
printf '%s\n' "${SHA}" > "${STATE_DIR}/revision.tmp.$$"
mv -f "${STATE_DIR}/revision.tmp.$$" "${STATE_DIR}/revision"
printf '%s\n' "${series_digest}" > "${STATE_DIR}/series-digest.tmp.$$"
mv -f "${STATE_DIR}/series-digest.tmp.$$" "${STATE_DIR}/series-digest"
install -d -m 755 "$(dirname "${ENV_FILE}")" "${OUT_DIR}"
{
  printf 'CHROME_SRC\t%s\n' "${SRC}"
  printf 'AURADE_GN_OUT_DIR\t%s\n' "${OUT_DIR}"
  printf 'AURADE_MATERIALIZED_SHA\t%s\n' "${SHA}"
  printf 'AURADE_SERIES_DIGEST\t%s\n' "${series_digest}"
} > "${ENV_FILE}.tmp.$$"
mv -f "${ENV_FILE}.tmp.$$" "${ENV_FILE}"

echo "Materialized candidate: ${SHA}"
echo "Reusable Chromium source: ${SRC}"
echo "Reusable output directory: ${OUT_DIR}"
echo "Descriptor: ${ENV_FILE}"
