#!/usr/bin/env bash
# The graphical installer's page order, navigation labels and reachability.
#
# Runs without a display, without root and without GTK, because the properties
# it checks are the ones that decide whether a destructive step is reachable
# and whether a button's label matches what it does. A test for those that
# needs a compositor is a test that does not run where the image is built.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)

command -v python3 >/dev/null 2>&1 || {
  echo 'installer GUI flow test: SKIP (python3 not available)'
  exit 0
}

exec python3 "$ROOT/installer/tests/gui_flow_test.py"
