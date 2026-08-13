#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")" && pwd -P)

"$ROOT/test-prompt-validation.sh"
"$ROOT/test-journal.sh"
"$ROOT/test-install-dry-run.sh"
"$ROOT/test-build-iso-stage.sh"
if (( EUID == 0 )); then
  "$ROOT/test-recovery.sh"
else
  echo 'recovery rollback test: SKIP (requires root)'
fi
