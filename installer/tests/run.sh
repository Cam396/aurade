#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")" && pwd -P)

# Every script runs, and the run ends with the list of the ones that failed.
# Stopping at the first failure used to hide every failure after it, and a
# script that fails says so on its own output above its FAIL line.
#
# AURADE_TEST_SHARD=I/N runs shard I of N, so CI can split the suite across
# parallel jobs. Scripts are dealt longest first, each to the shard with the
# least time so far, using the times in durations.tsv; a script missing from
# that file counts as one second. Within a shard they run in the order below.
TESTS=(
  test-prompt-validation.sh
  test-questions.sh
  test-tui-render.sh
  test-tui-plain.sh
  test-tui-width.sh
  test-tui-keys.sh
  test-disk-identity.sh
  test-qr.sh
  test-accessibility.sh
  test-a11y-announce.sh
  test-first-boot.sh
  test-no-timeouts.sh
  test-greyscale.sh
  test-tui-flow.sh
  test-tui-wifi.sh
  test-answers-fuzz.sh
  test-probe.sh
  test-renderer-chain.sh
  test-tui-engine.sh
  test-express.sh
  test-gui-theme.sh
  test-wallpapers.sh
  test-arcade.sh
  test-status.sh
  test-bible.sh
  test-badge.sh
  test-explain.sh
  test-gui-flow.sh
  test-gui-bridge.sh
  test-gui-launch.sh
  test-crash-log.sh
  test-gui-widgets.sh
  test-gui-icons.sh
  test-voice.sh
  test-progress-wait.sh
  test-progress-motion.sh
  test-download-rate.sh
  test-package-staging.sh
  test-die-cause.sh
  test-gui-runtime.sh
  test-network-diagnostics.sh
  test-failure-injection.sh
  test-installer-failure.sh
  test-hardware-qualify-args.sh
  test-refresh-mirrors.sh
  test-signed-stage.sh
  test-stage-reproducibility.sh
  test-journal.sh
  test-install-dry-run.sh
  test-secure-boot.sh
  test-build-iso-stage.sh
  test-execute-path-contract.sh
  test-execute-path-gate.sh
  test-leak-gate.sh
  test-patch-series-gate.sh
  ../../ci/tests/runtime-risk-source-test.sh
)

shard_index=1
shard_count=1
if [[ -n ${AURADE_TEST_SHARD:-} ]]; then
  if [[ ! $AURADE_TEST_SHARD =~ ^([0-9]+)/([0-9]+)$ ]] ||
     (( BASH_REMATCH[1] < 1 || BASH_REMATCH[1] > BASH_REMATCH[2] )); then
    echo "run.sh: AURADE_TEST_SHARD must look like 2/4, not ${AURADE_TEST_SHARD}" >&2
    exit 2
  fi
  shard_index=${BASH_REMATCH[1]}
  shard_count=${BASH_REMATCH[2]}
fi

declare -A duration=()
if [[ -r $ROOT/durations.tsv ]]; then
  while IFS=$'\t' read -r name seconds; do
    [[ $name == \#* || -z $name ]] || duration[$name]=$seconds
  done <"$ROOT/durations.tsv"
fi
declare -A mine=()
if (( shard_count > 1 )); then
  load=()
  for (( s = 0; s < shard_count; s++ )); do load[s]=0; done
  # Longest first; ties keep the order of the list above.
  while read -r _ i; do
    lightest=0
    for (( s = 1; s < shard_count; s++ )); do
      (( load[s] < load[lightest] )) && lightest=$s
    done
    weight=${duration[${TESTS[i]##*/}]:-1}
    load[lightest]=$(( load[lightest] + weight ))
    (( lightest == shard_index - 1 )) && mine[$i]=1
  done < <(for (( i = 0; i < ${#TESTS[@]}; i++ )); do
             printf '%s %s\n' "${duration[${TESTS[i]##*/}]:-1}" "$i"
           done | sort -s -k1,1nr)
  printf 'run.sh: shard %s of %s holds about %ss of work\n' \
    "$shard_index" "$shard_count" "${load[shard_index - 1]}"
fi

failed=()
timings=()
started=$SECONDS
for (( i = 0; i < ${#TESTS[@]}; i++ )); do
  (( shard_count == 1 )) || [[ -n ${mine[$i]:-} ]] || continue
  test=${TESTS[i]}
  # AURADE_TEST_LIST=1 names what this shard would run, and runs nothing.
  if [[ -n ${AURADE_TEST_LIST:-} ]]; then
    printf '%s\n' "$test"
    continue
  fi
  begin=$SECONDS
  if "$ROOT/$test"; then
    result=ok
  else
    result=FAIL
    failed+=("$test")
  fi
  printf 'run.sh: %-4s %-40s %4ss\n' "$result" "${test##*/}" "$(( SECONDS - begin ))"
  timings+=("| ${test##*/} | ${result} | $(( SECONDS - begin ))s |")
done

[[ -z ${AURADE_TEST_LIST:-} ]] || exit 0

# The rollback test mounts and snapshots, so only root can run it. It goes in
# the last shard so a sharded run still covers it exactly once.
if (( shard_index == shard_count )); then
  if (( EUID == 0 )); then
    "$ROOT/test-recovery.sh" || failed+=(test-recovery.sh)
  else
    echo 'recovery rollback test: SKIP (requires root)'
  fi
fi

if [[ -n ${GITHUB_STEP_SUMMARY:-} ]]; then
  {
    printf '### Installer tests, shard %s of %s\n\n' "$shard_index" "$shard_count"
    printf '| Test | Result | Time |\n|---|---|---|\n'
    printf '%s\n' "${timings[@]}"
  } >>"$GITHUB_STEP_SUMMARY"
fi

if (( ${#failed[@]} > 0 )); then
  printf 'run.sh: %s failed in %ss: %s\n' "${#failed[@]}" "$(( SECONDS - started ))" "${failed[*]}" >&2
  exit 1
fi
printf 'run.sh: shard %s of %s passed in %ss\n' "$shard_index" "$shard_count" "$(( SECONDS - started ))"
