#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")" && pwd -P)

# Name the test that gave up.
#
# Almost every test here is a bash script under errexit, and a bare assertion
# in one of those - `grep -Fq expected file`, with no `|| fail` after it - ends
# the whole run with an exit code and not one word about where. The test's own
# summary line never prints either, so what the operator sees is a suite that
# stopped mid list, which reads far more like the run having been killed than
# like an assertion having failed. `test-journal.sh` hid a stale expectation
# that way for a hundred and twenty commits.
#
# This does not fix those assertions. It makes the run say which script to go
# and look at, which is the whole distance between five minutes and an hour.
#
# The status is read first because the assignment after it would replace it,
# and the quotes come out of `BASH_COMMAND` because it carries the line as
# written rather than as expanded, which would otherwise leave one hanging off
# the end of the name.
trap '_rc=$?; _cmd=${BASH_COMMAND//\"/};
      printf "run.sh: %s gave up (exit %s)\n" "${_cmd##*/}" "$_rc" >&2' ERR

"$ROOT/test-prompt-validation.sh"
"$ROOT/test-questions.sh"
"$ROOT/test-tui-render.sh"
"$ROOT/test-tui-plain.sh"
"$ROOT/test-tui-width.sh"
"$ROOT/test-tui-keys.sh"
"$ROOT/test-disk-identity.sh"
"$ROOT/test-qr.sh"
"$ROOT/test-accessibility.sh"
"$ROOT/test-a11y-announce.sh"
"$ROOT/test-first-boot.sh"
"$ROOT/test-no-timeouts.sh"
"$ROOT/test-greyscale.sh"
"$ROOT/test-tui-flow.sh"
"$ROOT/test-answers-fuzz.sh"
"$ROOT/test-probe.sh"
"$ROOT/test-renderer-chain.sh"
"$ROOT/test-tui-engine.sh"
"$ROOT/test-gui-theme.sh"
"$ROOT/test-wallpapers.sh"
"$ROOT/test-bible.sh"
"$ROOT/test-badge.sh"
"$ROOT/test-explain.sh"
"$ROOT/test-gui-flow.sh"
"$ROOT/test-gui-bridge.sh"
"$ROOT/test-gui-launch.sh"
"$ROOT/test-crash-log.sh"
"$ROOT/test-gui-widgets.sh"
"$ROOT/test-gui-icons.sh"
"$ROOT/test-voice.sh"
"$ROOT/test-progress-wait.sh"
"$ROOT/test-progress-motion.sh"
"$ROOT/test-download-rate.sh"
"$ROOT/test-die-cause.sh"
"$ROOT/test-gui-runtime.sh"
"$ROOT/test-network-diagnostics.sh"
"$ROOT/test-failure-injection.sh"
"$ROOT/test-installer-failure.sh"
"$ROOT/test-hardware-qualify-args.sh"
"$ROOT/test-refresh-mirrors.sh"
"$ROOT/test-signed-stage.sh"
"$ROOT/test-stage-reproducibility.sh"
"$ROOT/test-journal.sh"
"$ROOT/test-install-dry-run.sh"
"$ROOT/test-secure-boot.sh"
"$ROOT/test-build-iso-stage.sh"
"$ROOT/test-execute-path-contract.sh"
"$ROOT/test-execute-path-gate.sh"
"$ROOT/../../ci/tests/runtime-risk-source-test.sh"
if (( EUID == 0 )); then
  "$ROOT/test-recovery.sh"
else
  echo 'recovery rollback test: SKIP (requires root)'
fi
