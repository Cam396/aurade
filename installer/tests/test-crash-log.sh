#!/usr/bin/env bash
# The installer writes down how it died.
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
command -v python3 >/dev/null 2>&1 || {
  echo 'installer crash recording test: SKIP (python3 not available)'
  exit 0
}
exec python3 "$ROOT/installer/tests/crash_test.py"
