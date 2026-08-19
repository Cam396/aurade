#!/usr/bin/env bash
# The thirteen games, their rules, and their agreement with the text installer.
set -Eeuo pipefail
trap 'case $- in *e*) printf "%s: line %s gave up: %s\n" "${0##*/}" "$LINENO" "$BASH_COMMAND" >&2 ;; esac' ERR

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
command -v python3 >/dev/null 2>&1 || {
  echo 'arcade test: SKIP (python3 not available)'; exit 0; }
python3 "$ROOT/installer/tests/arcade_test.py"
