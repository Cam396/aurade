#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/aurade-update-test.XXXXXX")"
trap 'rm -rf "${tmp}"' EXIT

git_init() {
  git init -q "$1"
  git -C "$1" config user.name "AuraDE CI Test"
  git -C "$1" config user.email ci-test@aurade.invalid
}

assert_eq() {
  [[ "$1" == "$2" ]] || {
    echo "assertion failed: expected '$2', got '$1'" >&2
    exit 1
  }
}

upstream="${tmp}/upstream"
remote="${tmp}/remote.git"
patches="${tmp}/patches"
state="${tmp}/state"
developer="${tmp}/developer"
mkdir -p "${patches}"
git_init "${upstream}"
printf 'base\n' > "${upstream}/feature.txt"
printf 'stable\n' > "${upstream}/unrelated.txt"
git -C "${upstream}" add .
git -C "${upstream}" commit -qm base
git -C "${upstream}" branch -M main
git clone -q --bare "${upstream}" "${remote}"
git clone -q --depth=1 "file://${remote}" "${developer}"
assert_eq "$(git -C "${developer}" rev-parse --is-shallow-repository)" true
printf 'developer dirt\n' >> "${developer}/unrelated.txt"
developer_before="$(git -C "${developer}" status --porcelain=v1)"
developer_head="$(git -C "${developer}" rev-parse HEAD)"

printf 'aurade\n' > "${upstream}/feature.txt"
git -C "${upstream}" diff --binary --full-index > "${patches}/0001-feature.patch"
git -C "${upstream}" checkout -q -- feature.txt
printf '0001-feature.patch\n' > "${patches}/SERIES"

base_env=(
  AURADE_UPDATE_STATE_ROOT="${state}"
  AURADE_CHROMIUM_REMOTE="${remote}"
  AURADE_CHROMIUM_BRANCH=refs/heads/main
  AURADE_CHROMIUM_REFERENCE="${developer}"
  PATCH_DIR="${patches}"
  SERIES_FILE="${patches}/SERIES"
)

env "${base_env[@]}" "${SCRIPT_DIR}/update-chromium-candidate.sh" --probe \
  > "${tmp}/probe.log"
[[ ! -e "${state}" ]] || { echo "probe mutated state" >&2; exit 1; }
env "${base_env[@]}" "${SCRIPT_DIR}/update-chromium-candidate.sh" --dry-run \
  > "${tmp}/dry-run.log"
[[ ! -e "${state}" ]] || { echo "dry run mutated state" >&2; exit 1; }

env "${base_env[@]}" "${SCRIPT_DIR}/update-chromium-candidate.sh" --run \
  > "${tmp}/first.log"
first_id="$(<"${state}/pins/last-known-good-id")"
first_sha="$(<"${state}/pins/last-known-good-sha")"
assert_eq "${first_sha}" "${developer_head}"
assert_eq "$(<"${state}/candidates/${first_id}/result")" green
assert_eq "$(git -C "${developer}" status --porcelain=v1)" "${developer_before}"
assert_eq "$(git -C "${developer}" rev-parse HEAD)" "${developer_head}"
[[ -s "${state}/candidates/${first_id}/target-plan.txt" ]]
[[ -s "${state}/candidates/${first_id}/source-manifest.md" ]]

env "${base_env[@]}" "${SCRIPT_DIR}/update-chromium-candidate.sh" --run \
  > "${tmp}/idempotent.log"
assert_eq "$(<"${state}/pins/last-known-good-id")" "${first_id}"

# A conflicting upstream commit must leave LKG untouched and preserve evidence.
printf 'upstream conflict\n' > "${upstream}/feature.txt"
git -C "${upstream}" add feature.txt
git -C "${upstream}" commit -qm conflict
git -C "${upstream}" push -q "${remote}" main
if env "${base_env[@]}" "${SCRIPT_DIR}/update-chromium-candidate.sh" --run \
    > "${tmp}/conflict.log" 2>&1; then
  echo "conflicting candidate unexpectedly passed" >&2
  exit 1
fi
assert_eq "$(<"${state}/pins/last-known-good-id")" "${first_id}"
conflict_id="$(find "${state}/candidates" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | grep -vFx "${first_id}")"
[[ -s "${state}/candidates/${conflict_id}/conflict-report.txt" ]]
assert_eq "$(<"${state}/candidates/${conflict_id}/result")" failed

# Advance to a compatible commit and exercise every configured command gate.
git -C "${upstream}" revert --no-edit HEAD >/dev/null
printf 'next\n' >> "${upstream}/unrelated.txt"
git -C "${upstream}" add unrelated.txt
git -C "${upstream}" commit -qm next
git -C "${upstream}" push -q "${remote}" main
gate_log="${tmp}/gate-order"
warm_root="${tmp}/warm-candidate"
materialize_command="mkdir -p '${warm_root}/src/out/Ash' '${warm_root}/.aurade-state'; printf 'CHROME_SRC\\t%s\\nAURADE_GN_OUT_DIR\\t%s\\nAURADE_MATERIALIZED_SHA\\t%s\\n' '${warm_root}/src' '${warm_root}/src/out/Ash' \"\$AURADE_CANDIDATE_SHA\" > \"\$AURADE_MATERIALIZED_ENV\"; printf '%s\\n' materialize >> '${gate_log}'"
env "${base_env[@]}" \
  AURADE_UPDATE_GATES=replay,gn,targeted,full-build,package,repo,vm \
  AURADE_CANDIDATE_CHECKOUT_ROOT="${warm_root}" \
  AURADE_MATERIALIZE_COMMAND="${materialize_command}" \
  AURADE_GN_COMMAND="printf '%s\\n' gn >> '${gate_log}'" \
  AURADE_TARGETED_COMMAND="printf '%s\\n' targeted >> '${gate_log}'" \
  AURADE_FULL_BUILD_COMMAND="printf '%s\\n' full-build >> '${gate_log}'" \
  AURADE_PACKAGE_COMMAND="printf '%s\\n' package >> '${gate_log}'" \
  AURADE_REPO_COMMAND="printf '%s\\n' repo >> '${gate_log}'" \
  AURADE_VM_COMMAND="printf '%s\\n' vm >> '${gate_log}'" \
  "${SCRIPT_DIR}/update-chromium-candidate.sh" --run > "${tmp}/gates.log"
second_id="$(<"${state}/pins/last-known-good-id")"
assert_eq "$(tr '\n' ',' < "${gate_log}")" "materialize,gn,targeted,full-build,package,repo,vm,"
[[ "${second_id}" != "${first_id}" ]]
assert_eq "$(awk -F '\t' '$1 == "AURADE_MATERIALIZED_SHA" {print $2}' \
  "${state}/candidates/${second_id}/materialized.env")" \
  "$(<"${state}/candidates/${second_id}/revision")"

# A failed late gate cannot promote, and the green predecessor remains rollbackable.
printf 'later\n' >> "${upstream}/unrelated.txt"
git -C "${upstream}" add unrelated.txt
git -C "${upstream}" commit -qm later
git -C "${upstream}" push -q "${remote}" main
if env "${base_env[@]}" AURADE_UPDATE_GATES=replay,vm AURADE_VM_COMMAND=false \
    "${SCRIPT_DIR}/update-chromium-candidate.sh" --run > "${tmp}/late-fail.log" 2>&1; then
  echo "failed VM gate unexpectedly promoted" >&2
  exit 1
fi
assert_eq "$(<"${state}/pins/last-known-good-id")" "${second_id}"
late_id="$(find "${state}/candidates" -mindepth 2 -maxdepth 2 -type f \
  -name failure-stage -exec grep -lFx vm {} + | sed 's#/failure-stage$##; s#.*/##')"
env "${base_env[@]}" AURADE_UPDATE_GATES=replay,vm AURADE_VM_COMMAND=true \
  "${SCRIPT_DIR}/update-chromium-candidate.sh" --resume "${late_id}" \
  > "${tmp}/resume.log"
assert_eq "$(<"${state}/pins/last-known-good-id")" "${late_id}"
env "${base_env[@]}" "${SCRIPT_DIR}/update-chromium-candidate.sh" \
  --rollback "${first_id}" > "${tmp}/rollback.log"
assert_eq "$(<"${state}/pins/last-known-good-id")" "${first_id}"
assert_eq "$(readlink "${state}/current")" "candidates/${first_id}"
[[ "$(wc -l < "${state}/pins/promotions.tsv")" -ge 4 ]]

# Lock contention is a distinct temporary-failure result.
exec 8>"${state}/update.lock"
flock -n 8
set +e
env "${base_env[@]}" "${SCRIPT_DIR}/update-chromium-candidate.sh" --rollback "${first_id}" \
  > "${tmp}/locked.log" 2>&1
locked_rc=$?
set -e
assert_eq "${locked_rc}" 75

echo "update-chromium-candidate tests: PASS"
