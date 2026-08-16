#!/usr/bin/env bash
# The two things about the product's voice that a machine can check.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)

command -v python3 >/dev/null 2>&1 || {
  echo 'installer voice test: SKIP (python3 not available)'
  exit 0
}

exec python3 "$ROOT/installer/tests/voice_test.py"
