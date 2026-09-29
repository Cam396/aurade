#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")" && pwd -P)

# Every script runs, and the run ends with the list of the ones that failed.
# Stopping at the first failure used to hide every failure after it, and a
# script that fails says so on its own output above its FAIL line.
#
# AURADE_TEST_SHARD=I/N runs every Nth script starting at the Ith, so CI can
# split the suite across parallel jobs. Shards are dealt round robin in the
# order below, which is also the order a full run uses.
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

failed=()
timings=()
started=$SECONDS
for (( i = 0; i < ${#TESTS[@]}; i++ )); do
  (( i % shard_count == shard_index - 1 )) || continue
  test=${TESTS[i]}
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
