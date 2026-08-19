#!/usr/bin/env bash
# The clock, the battery and the network in the top bar, and the download
# rate's agreement between the two front ends.
set -Eeuo pipefail
trap 'case $- in *e*) printf "%s: line %s gave up: %s\n" "${0##*/}" "$LINENO" "$BASH_COMMAND" >&2 ;; esac' ERR

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
command -v python3 >/dev/null 2>&1 || {
  echo 'status test: SKIP (python3 not available)'; exit 0; }
python3 "$ROOT/installer/tests/status_test.py"
