#!/usr/bin/env bash
# When the installer is allowed to say something out loud.
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
command -v python3 >/dev/null 2>&1 || {
  echo 'accessibility announcement test: SKIP (python3 not available)'
  exit 0
}
exec python3 "$ROOT/installer/tests/a11y_announce_test.py"
