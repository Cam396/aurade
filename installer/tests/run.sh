#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")" && pwd -P)

"$ROOT/test-prompt-validation.sh"
"$ROOT/test-questions.sh"
"$ROOT/test-tui-render.sh"
"$ROOT/test-tui-plain.sh"
"$ROOT/test-tui-width.sh"
"$ROOT/test-tui-keys.sh"
"$ROOT/test-disk-identity.sh"
"$ROOT/test-qr.sh"
"$ROOT/test-accessibility.sh"
"$ROOT/test-greyscale.sh"
"$ROOT/test-tui-flow.sh"
"$ROOT/test-probe.sh"
"$ROOT/test-renderer-chain.sh"
"$ROOT/test-tui-engine.sh"
"$ROOT/test-gui-theme.sh"
"$ROOT/test-gui-flow.sh"
"$ROOT/test-gui-bridge.sh"
"$ROOT/test-gui-launch.sh"
"$ROOT/test-gui-widgets.sh"
"$ROOT/test-gui-icons.sh"
"$ROOT/test-voice.sh"
"$ROOT/test-progress-wait.sh"
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
