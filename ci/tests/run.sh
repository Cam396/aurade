#!/usr/bin/env bash
# Run every fixture in ci/tests.
#
# The workflow used to name each test by hand, and eight of the eighteen tests
# in this directory were not on that list. A test that exists but never runs is
# worse than no test: it reads as coverage and provides none. Discovery removes
# the step where somebody has to remember.
set -Eeuo pipefail

HERE=$(cd -- "$(dirname -- "$0")" && pwd -P)
ROOT=$(cd -- "$HERE/.." && pwd -P)
REPO=$(cd -- "$ROOT/.." && pwd -P)
WORKFLOW="$REPO/.github/workflows/ci.yml"
RUNNER="$ROOT/run.sh"

# Preflight: the workflow calls ci/run.sh, and ci/run.sh has to call this
# runner rather than list the fixtures, or the drift this file exists to
# prevent starts over.
if [[ -r $WORKFLOW ]]; then
  if ! grep -Fq 'ci/run.sh fixtures' "$WORKFLOW" || ! grep -Fq 'ci/tests/run.sh' "$RUNNER"; then
    echo "run: the CI workflow does not reach ci/tests/run.sh through ci/run.sh fixtures" >&2
    exit 1
  fi
  stray=$(grep -ohE 'ci/tests/[a-z0-9-]+-test\.sh' "$WORKFLOW" "$RUNNER" | sort -u || true)
  if [[ -n $stray ]]; then
    echo 'run: the workflow or ci/run.sh still names individual fixtures, so new ones can be forgotten:' >&2
    printf '  %s\n' $stray >&2
    exit 1
  fi
fi

shopt -s nullglob
tests=("$HERE"/*-test.sh)
shopt -u nullglob
if [[ ${#tests[@]} -eq 0 ]]; then
  echo 'run: no fixtures found, which is itself a failure' >&2
  exit 1
fi

failed=()
started=$(date +%s)
for test in "${tests[@]}"; do
  name=$(basename "$test")
  if [[ ! -x $test ]]; then
    echo "run: ${name} is not executable" >&2
    failed+=("$name")
    continue
  fi
  begin=$(date +%s)
  if output=$("$test" 2>&1); then
    printf '  ok    %-46s %3ds\n' "$name" "$(($(date +%s) - begin))"
  else
    printf '  FAIL  %-46s %3ds\n' "$name" "$(($(date +%s) - begin))"
    printf '%s\n' "$output" | sed 's/^/        /' >&2
    failed+=("$name")
  fi
done

elapsed=$(($(date +%s) - started))
if [[ ${#failed[@]} -gt 0 ]]; then
  echo "run: ${#failed[@]} of ${#tests[@]} fixtures failed in ${elapsed}s: ${failed[*]}" >&2
  exit 1
fi
echo "run: ${#tests[@]} fixtures passed in ${elapsed}s"
