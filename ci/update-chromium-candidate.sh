#!/bin/bash
# Resolve, validate, and atomically promote an immutable Chromium candidate.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
STATE_ROOT="${AURADE_UPDATE_STATE_ROOT:-/mnt/build/aurade-work/chromium-update}"
REMOTE="${AURADE_CHROMIUM_REMOTE:-https://chromium.googlesource.com/chromium/src.git}"
BRANCH="${AURADE_CHROMIUM_BRANCH:-refs/heads/main}"
PATCH_DIR="${PATCH_DIR:-${REPO_ROOT}/patches}"
SERIES_FILE="${SERIES_FILE:-${PATCH_DIR}/SERIES}"
REFERENCE_REPO="${AURADE_CHROMIUM_REFERENCE:-${REPO_ROOT}/chromium_dev/src}"
CANDIDATE_CHECKOUT_ROOT="${AURADE_CANDIDATE_CHECKOUT_ROOT:-/mnt/build/aurade-work/chromium-candidate}"
GATES="${AURADE_UPDATE_GATES:-replay}"
KEEP_COUNT="${AURADE_UPDATE_KEEP:-8}"
KEEP_WORKTREE="${AURADE_KEEP_CANDIDATE_WORKTREE:-0}"
mode="probe"
resume_id=""
rollback_id=""

usage() {
  cat <<'EOF'
Usage: ci/update-chromium-candidate.sh [mode] [options]

Modes (default: --probe):
  --probe          Resolve the moving branch without changing local state.
  --dry-run        Resolve and print the candidate/gate plan without mutation.
  --run            Fetch, replay, validate, and promote a green candidate.
  --resume ID      Retry a previously failed candidate generation.
  --rollback ID    Atomically select a previously green candidate as LKG.

Options:
  --remote URL     Chromium remote (default: official src repository).
  --branch REF     Full remote branch ref (default: refs/heads/main).
  --gates LIST     Comma list: replay,materialize,gn,targeted,full-build,
                   package,repo,vm. Build gates imply materialize.
  --keep-worktree  Retain the source-only replay worktree.

Gate commands are supplied through AURADE_*_COMMAND. Commands receive
AURADE_CANDIDATE_ID, AURADE_CANDIDATE_SHA, AURADE_CANDIDATE_DIR,
CHROME_SRC, AURADE_CHANGED_FILES, AURADE_TARGET_PLAN, and
AURADE_GN_OUT_DIR. Materialize defaults to materialize-chromium-candidate.sh,
package defaults to build-release-candidate.sh, and repo defaults to
verify-release-repo.sh. Other selected command gates must be configured.
EOF
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --probe) mode="probe"; shift ;;
    --dry-run) mode="dry-run"; shift ;;
    --run) mode="run"; shift ;;
    --resume) mode="resume"; resume_id="$2"; shift 2 ;;
    --rollback) mode="rollback"; rollback_id="$2"; shift 2 ;;
    --remote) REMOTE="$2"; shift 2 ;;
    --branch) BRANCH="$2"; shift 2 ;;
    --gates) GATES="$2"; shift 2 ;;
    --keep-worktree) KEEP_WORKTREE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 2
  }
}
for command in git sha256sum flock awk sed sort find; do need "${command}"; done

[[ "${BRANCH}" == refs/heads/* ]] || {
  echo "--branch must be a full refs/heads/... ref: ${BRANCH}" >&2
  exit 2
}
[[ "${KEEP_COUNT}" =~ ^[1-9][0-9]*$ ]] || {
  echo "AURADE_UPDATE_KEEP must be a positive integer" >&2
  exit 2
}
[[ -r "${SERIES_FILE}" ]] || {
  echo "Patch series file not found: ${SERIES_FILE}" >&2
  exit 2
}

declare -A gate_enabled=()
IFS=',' read -r -a gate_list <<< "${GATES}"
for gate in "${gate_list[@]}"; do
  gate="${gate//[[:space:]]/}"
  [[ -n "${gate}" ]] || continue
  case "${gate}" in
    replay|materialize|gn|targeted|full-build|package|repo|vm) gate_enabled["${gate}"]=1 ;;
    *) echo "Unknown gate: ${gate}" >&2; exit 2 ;;
  esac
done
gate_enabled[replay]=1
for build_gate in gn targeted full-build package; do
  if [[ -n "${gate_enabled[${build_gate}]:-}" ]]; then
    gate_enabled[materialize]=1
  fi
done

mapfile -t series < <(
  sed -E 's/[[:space:]]+#.*$//; /^[[:space:]]*($|#)/d; s/^[[:space:]]+//; s/[[:space:]]+$//' \
    "${SERIES_FILE}"
)
[[ "${#series[@]}" -gt 0 ]] || { echo "Patch series is empty" >&2; exit 2; }
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
  [[ -r "${PATCH_DIR}/${patch_name}" ]] || {
    echo "Missing series patch: ${PATCH_DIR}/${patch_name}" >&2
    exit 2
  }
  series_material+="$(sha256sum "${PATCH_DIR}/${patch_name}")"$'\n'
done
series_digest="$(printf '%s' "${series_material}" | sha256sum | awk '{print $1}')"

resolve_remote() {
  local result sha
  result="$(git ls-remote --exit-code "${REMOTE}" "${BRANCH}")" || {
    echo "Unable to resolve ${REMOTE} ${BRANCH}" >&2
    return 1
  }
  sha="$(awk 'NR == 1 {print $1}' <<< "${result}")"
  [[ "${sha}" =~ ^[0-9a-fA-F]{40,64}$ ]] || {
    echo "Remote returned an invalid object ID: ${sha}" >&2
    return 1
  }
  printf '%s\n' "${sha,,}"
}

print_plan() {
  local sha="$1" id="${1}-${series_digest:0:12}"
  cat <<EOF
AuraDE Chromium candidate plan:
  remote:        ${REMOTE}
  branch:        ${BRANCH}
  candidate SHA: ${sha}
  series digest: ${series_digest}
  candidate ID:  ${id}
  state root:    ${STATE_ROOT}
  gates:         ${GATES}
  patch count:   ${#series[@]}
EOF
}

if [[ "${mode}" == "probe" || "${mode}" == "dry-run" ]]; then
  resolved_sha="$(resolve_remote)"
  print_plan "${resolved_sha}"
  [[ "${mode}" == "probe" ]] && echo "Probe only; no local state was changed."
  [[ "${mode}" == "dry-run" ]] && echo "Dry run only; no local state was changed."
  exit 0
fi

install -d -m 755 "${STATE_ROOT}" "${STATE_ROOT}/candidates" "${STATE_ROOT}/pins"
exec 9>"${STATE_ROOT}/update.lock"
if ! flock -n 9; then
  echo "Another AuraDE Chromium update is running: ${STATE_ROOT}/update.lock" >&2
  exit 75
fi

atomic_write() {
  local destination="$1" value="$2" tmp
  tmp="${destination}.tmp.$$"
  printf '%s\n' "${value}" > "${tmp}"
  mv -f "${tmp}" "${destination}"
}

find_candidate() {
  local requested="$1" matches=()
  if [[ -d "${STATE_ROOT}/candidates/${requested}" ]]; then
    printf '%s\n' "${requested}"
    return
  fi
  mapfile -t matches < <(find "${STATE_ROOT}/candidates" -mindepth 1 -maxdepth 1 \
    -type d -printf '%f\n' | awk -v prefix="${requested}" 'index($0, prefix) == 1')
  [[ "${#matches[@]}" -eq 1 ]] || {
    echo "Candidate ID/SHA is missing or ambiguous: ${requested}" >&2
    return 1
  }
  printf '%s\n' "${matches[0]}"
}

promote_pointer() {
  local id="$1" reason="$2" candidate_dir
  local old_id="" pointer_tmp="${STATE_ROOT}/current.tmp.$$"
  candidate_dir="${STATE_ROOT}/candidates/${id}"
  [[ -r "${candidate_dir}/result" && "$(<"${candidate_dir}/result")" == "green" ]] || {
    echo "Candidate is not green and cannot be promoted: ${id}" >&2
    return 1
  }
  [[ -r "${STATE_ROOT}/pins/last-known-good-id" ]] && old_id="$(<"${STATE_ROOT}/pins/last-known-good-id")"
  rm -f "${pointer_tmp}"
  ln -s "candidates/${id}" "${pointer_tmp}"
  mv -Tf "${pointer_tmp}" "${STATE_ROOT}/current"
  atomic_write "${STATE_ROOT}/pins/last-known-good-id" "${id}"
  atomic_write "${STATE_ROOT}/pins/last-known-good-sha" "$(<"${candidate_dir}/revision")"
  {
    echo "timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "reason=${reason}"
    echo "from=${old_id}"
    echo "to=${id}"
  } > "${STATE_ROOT}/pins/promotion.tmp.$$"
  mv -f "${STATE_ROOT}/pins/promotion.tmp.$$" "${STATE_ROOT}/pins/promotion.env"
  printf '%s\t%s\t%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "${reason}" "${old_id}" "${id}" >> "${STATE_ROOT}/pins/promotions.tsv"
}

if [[ "${mode}" == "rollback" ]]; then
  candidate_id="$(find_candidate "${rollback_id}")"
  promote_pointer "${candidate_id}" rollback
  echo "Rolled last-known-good back to ${candidate_id}"
  exit 0
fi

mirror="${STATE_ROOT}/chromium.git"
if [[ ! -d "${mirror}" ]]; then
  mirror_staging="${mirror}.staging.$$"
  rm -rf "${mirror_staging}"
  if git -C "${REFERENCE_REPO}" rev-parse --git-dir >/dev/null 2>&1; then
    git clone --bare --no-local --quiet "${REFERENCE_REPO}" "${mirror_staging}"
    git --git-dir="${mirror_staging}" config --remove-section remote.origin \
      >/dev/null 2>&1 || true
  else
    git init --bare --quiet "${mirror_staging}"
  fi
  mv "${mirror_staging}" "${mirror}"
fi
git --git-dir="${mirror}" config gc.auto 0
git --git-dir="${mirror}" fetch --quiet --no-tags --update-shallow "${REMOTE}" \
  "+${BRANCH}:refs/remotes/aurade/candidate"
if [[ "${mode}" == "resume" ]]; then
  candidate_id="$(find_candidate "${resume_id}")"
  candidate_dir="${STATE_ROOT}/candidates/${candidate_id}"
  [[ -r "${candidate_dir}/revision" && -r "${candidate_dir}/series-digest" ]] || {
    echo "Resume candidate metadata is incomplete: ${candidate_id}" >&2
    exit 2
  }
  resolved_sha="$(<"${candidate_dir}/revision")"
  [[ "$(<"${candidate_dir}/series-digest")" == "${series_digest}" ]] || {
    echo "Patch series changed; start a new candidate instead of resuming ${candidate_id}." >&2
    exit 2
  }
  [[ -r "${candidate_dir}/result" && "$(<"${candidate_dir}/result")" == "failed" ]] || {
    echo "Only a failed candidate can be resumed: ${candidate_id}" >&2
    exit 2
  }
  git --git-dir="${mirror}" cat-file -e "${resolved_sha}^{commit}" || {
    echo "Resume revision is unavailable from the candidate mirror: ${resolved_sha}" >&2
    exit 2
  }
else
  resolved_sha="$(git --git-dir="${mirror}" rev-parse 'refs/remotes/aurade/candidate^{commit}')"
  candidate_id="${resolved_sha}-${series_digest:0:12}"
fi
git --git-dir="${mirror}" update-ref \
  "refs/aurade/candidates/${resolved_sha}" "${resolved_sha}"

candidate_dir="${STATE_ROOT}/candidates/${candidate_id}"
worktree="${candidate_dir}/worktree"
state_file="${candidate_dir}/state"
events_file="${candidate_dir}/events.tsv"
logs_dir="${candidate_dir}/logs"
install -d -m 755 "${candidate_dir}" "${logs_dir}"

transition() {
  local next="$1" detail="${2:-}"
  atomic_write "${state_file}" "${next}"
  printf '%s\t%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${next}" "${detail}" >> "${events_file}"
}

fail() {
  local stage="$1" message="$2"
  atomic_write "${candidate_dir}/failure-stage" "${stage}"
  atomic_write "${candidate_dir}/result" failed
  transition failed "${stage}: ${message}"
  echo "Candidate failed at ${stage}: ${message}" >&2
  echo "Evidence: ${candidate_dir}" >&2
  exit 1
}

if [[ -r "${candidate_dir}/result" && "$(<"${candidate_dir}/result")" == "green" && "${mode}" != "resume" ]]; then
  promote_pointer "${candidate_id}" idempotent
  echo "Candidate already green; last-known-good remains ${candidate_id}"
  exit 0
fi
if [[ -r "${candidate_dir}/result" && "$(<"${candidate_dir}/result")" == "failed" && "${mode}" != "resume" ]]; then
  echo "Candidate previously failed; inspect ${candidate_dir} and use --resume ${candidate_id}" >&2
  exit 1
fi

atomic_write "${candidate_dir}/revision" "${resolved_sha}"
atomic_write "${candidate_dir}/series-digest" "${series_digest}"
atomic_write "${candidate_dir}/remote" "${REMOTE}"
atomic_write "${candidate_dir}/branch" "${BRANCH}"
attempt=1
[[ -r "${candidate_dir}/attempt" ]] && attempt=$(( $(<"${candidate_dir}/attempt") + 1 ))
atomic_write "${candidate_dir}/attempt" "${attempt}"
rm -f "${candidate_dir}/result" "${candidate_dir}/failure-stage"
transition resolved "attempt=${attempt} revision=${resolved_sha}"

if [[ -e "${worktree}" ]]; then
  git --git-dir="${mirror}" worktree remove --force "${worktree}" >/dev/null 2>&1 || rm -rf "${worktree}"
fi
git --git-dir="${mirror}" worktree prune
transition replaying
if ! git --git-dir="${mirror}" worktree add --detach --quiet "${worktree}" "${resolved_sha}"; then
  fail replay "unable to create detached worktree"
fi

applied=0
for patch_name in "${series[@]}"; do
  check_log="${logs_dir}/replay-$(printf '%03d' "$((applied + 1))").log"
  if ! git -C "${worktree}" apply --check --whitespace=error-all \
      "${PATCH_DIR}/${patch_name}" >"${check_log}" 2>&1; then
    {
      echo "candidate_id=${candidate_id}"
      echo "revision=${resolved_sha}"
      echo "series_digest=${series_digest}"
      echo "failed_patch=${patch_name}"
      echo "applied_count=${applied}"
      echo
      echo "[git_apply_check]"
      cat "${check_log}"
      echo
      echo "[git_status]"
      git -C "${worktree}" status --short
      echo
      echo "[git_diff_stat]"
      git -C "${worktree}" diff --stat
    } > "${candidate_dir}/conflict-report.txt"
    fail replay "patch does not apply: ${patch_name}"
  fi
  if ! git -C "${worktree}" apply --whitespace=error-all \
      "${PATCH_DIR}/${patch_name}" >>"${check_log}" 2>&1; then
    fail replay "patch apply failed after successful check: ${patch_name}"
  fi
  applied=$((applied + 1))
done
if ! git -C "${worktree}" diff --check >"${logs_dir}/diff-check.log" 2>&1; then
  fail diff-check "patched tree has whitespace errors"
fi
git -C "${worktree}" diff --name-only --diff-filter=ACDMRTUXB HEAD | sort -u \
  > "${candidate_dir}/changed-files.txt"
git -C "${worktree}" diff --binary --full-index HEAD \
  > "${candidate_dir}/replayed-series.patch"
transition replayed "patches=${applied}"

if ! "${SCRIPT_DIR}/select-chromium-targets.sh" \
    --source "${worktree}" --changed "${candidate_dir}/changed-files.txt" \
    --output "${candidate_dir}/target-plan.txt" >"${logs_dir}/target-plan.log" 2>&1; then
  fail target-plan "unable to derive changed-file validation plan"
fi

export AURADE_CANDIDATE_ID="${candidate_id}"
export AURADE_CANDIDATE_SHA="${resolved_sha}"
export AURADE_CHROMIUM_REVISION="${resolved_sha}"
export AURADE_CHROMIUM_REMOTE="${REMOTE}"
export AURADE_CHROMIUM_REFERENCE="${REFERENCE_REPO}"
export AURADE_CANDIDATE_DIR="${candidate_dir}"
export AURADE_REPLAY_CHROME_SRC="${worktree}"
export CHROME_SRC="${worktree}"
export AURADE_CHANGED_FILES="${candidate_dir}/changed-files.txt"
export AURADE_TARGET_PLAN="${candidate_dir}/target-plan.txt"
export AURADE_GN_OUT_DIR="${AURADE_GN_OUT_DIR:-${worktree}/out/AuraDECandidate}"
export AURADE_CANDIDATE_CHECKOUT_ROOT="${CANDIDATE_CHECKOUT_ROOT}"
export AURADE_MATERIALIZED_ENV="${CANDIDATE_CHECKOUT_ROOT}/.aurade-state/materialized.env"
export PATCH_DIR SERIES_FILE

run_command_gate() {
  local gate="$1" command="$2"
  [[ -n "${command}" ]] || fail "${gate}" "selected gate has no configured command"
  transition "gate-${gate}" "${command}"
  if ! /usr/bin/bash -o pipefail -c "${command}" >"${logs_dir}/${gate}.log" 2>&1; then
    fail "${gate}" "command failed; see logs/${gate}.log"
  fi
  printf '%s\n' passed > "${candidate_dir}/gate-${gate}"
}

if [[ -n "${gate_enabled[materialize]:-}" ]]; then
  printf -v default_materialize_command '%q' \
    "${SCRIPT_DIR}/materialize-chromium-candidate.sh"
  run_command_gate materialize \
    "${AURADE_MATERIALIZE_COMMAND:-${default_materialize_command}}"

  materialized_src=""
  materialized_out=""
  materialized_sha=""
  [[ -r "${AURADE_MATERIALIZED_ENV}" ]] ||
    fail materialize "materializer did not write ${AURADE_MATERIALIZED_ENV}"
  while IFS=$'\t' read -r descriptor_key descriptor_value; do
    case "${descriptor_key}" in
      CHROME_SRC) materialized_src="${descriptor_value}" ;;
      AURADE_GN_OUT_DIR) materialized_out="${descriptor_value}" ;;
      AURADE_MATERIALIZED_SHA) materialized_sha="${descriptor_value}" ;;
    esac
  done < "${AURADE_MATERIALIZED_ENV}"
  [[ -d "${materialized_src}" && "${materialized_sha}" == "${resolved_sha}" ]] ||
    fail materialize "descriptor does not identify the immutable candidate"
  [[ "${materialized_out}" == "${materialized_src}/out/"* ]] ||
    fail materialize "descriptor output is outside the candidate source"
  export CHROME_SRC="${materialized_src}"
  export AURADE_GN_OUT_DIR="${materialized_out}"
  cp "${AURADE_MATERIALIZED_ENV}" "${candidate_dir}/materialized.env"
fi

transition cheap-gates
if [[ -n "${gate_enabled[gn]:-}" ]]; then
  run_command_gate gn "${AURADE_GN_COMMAND:-}"
fi
if [[ -n "${gate_enabled[targeted]:-}" ]]; then
  run_command_gate targeted "${AURADE_TARGETED_COMMAND:-}"
fi
transition cheap-gates-passed

if [[ -n "${gate_enabled[full-build]:-}" ]]; then
  run_command_gate full-build "${AURADE_FULL_BUILD_COMMAND:-}"
fi
if [[ -n "${gate_enabled[package]:-}" ]]; then
  run_command_gate package "${AURADE_PACKAGE_COMMAND:-${SCRIPT_DIR}/build-release-candidate.sh}"
fi
if [[ -n "${gate_enabled[repo]:-}" ]]; then
  printf -v default_repo_command 'REPO_DIR=%q %q' \
    "${REPO_DIR:-/mnt/build/aurade-work/private-repo}" \
    "${SCRIPT_DIR}/verify-release-repo.sh"
  run_command_gate repo "${AURADE_REPO_COMMAND:-${default_repo_command}}"
fi
if [[ -n "${gate_enabled[vm]:-}" ]]; then
  run_command_gate vm "${AURADE_VM_COMMAND:-}"
fi

transition manifest
if ! AURADE_SOURCE_MANIFEST="${candidate_dir}/source-manifest.md" \
    CHROME_SRC="${CHROME_SRC}" "${SCRIPT_DIR}/write-source-manifest.sh" \
    >"${logs_dir}/source-manifest.log" 2>&1; then
  fail manifest "write-source-manifest.sh failed"
fi
{
  echo "candidate_id=${candidate_id}"
  echo "revision=${resolved_sha}"
  echo "series_digest=${series_digest}"
  echo "patch_count=${applied}"
  echo "gates=${GATES}"
  echo "attempt=${attempt}"
  echo "green_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "${candidate_dir}/candidate.env.tmp.$$"
mv -f "${candidate_dir}/candidate.env.tmp.$$" "${candidate_dir}/candidate.env"
atomic_write "${candidate_dir}/result" green
transition green
promote_pointer "${candidate_id}" green
transition promoted

if [[ "${KEEP_WORKTREE}" != "1" ]]; then
  git --git-dir="${mirror}" worktree remove --force "${worktree}" >/dev/null 2>&1 || true
fi
git --git-dir="${mirror}" worktree prune

current_id="$(<"${STATE_ROOT}/pins/last-known-good-id")"
mapfile -t retained < <(find "${STATE_ROOT}/candidates" -mindepth 1 -maxdepth 1 \
  -type d -printf '%T@ %f\n' | sort -nr | awk '{print $2}')
retained_count=0
for old_id in "${retained[@]}"; do
  [[ "${old_id}" == "${current_id}" ]] && continue
  retained_count=$((retained_count + 1))
  if [[ "${retained_count}" -ge "${KEEP_COUNT}" ]]; then
    old_sha="$(<"${STATE_ROOT}/candidates/${old_id}/revision")"
    old_worktree="${STATE_ROOT}/candidates/${old_id}/worktree"
    git --git-dir="${mirror}" worktree remove --force "${old_worktree}" >/dev/null 2>&1 || true
    rm -rf "${STATE_ROOT}/candidates/${old_id}"
    if ! find "${STATE_ROOT}/candidates" -mindepth 1 -maxdepth 1 -type d \
        -name "${old_sha}-*" -print -quit | grep -q .; then
      git --git-dir="${mirror}" update-ref -d \
        "refs/aurade/candidates/${old_sha}" >/dev/null 2>&1 || true
    fi
  fi
done

echo "Promoted AuraDE Chromium candidate: ${candidate_id}"
echo "Last-known-good SHA: ${resolved_sha}"
echo "Manifest: ${candidate_dir}/candidate.env"
