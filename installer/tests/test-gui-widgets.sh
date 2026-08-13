#!/usr/bin/env bash
# Every GTK 4 and libadwaita name the graphical installer uses, checked against
# the toolkit's own introspection data.
#
# The widget layer is the one file here that cannot be driven without a
# compositor, so the mistake it is most exposed to is a name that does not
# exist. GIR files answer that without a display, and they ship with the
# packages the image installs.
#
# Skips when the introspection data is absent, which is the ordinary case on a
# build host that does not carry the toolkit. Point AURADE_GIR_DIR at a
# directory of .gir files to run it anywhere.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)

command -v python3 >/dev/null 2>&1 || {
  echo 'installer GUI widget test: SKIP (python3 not available)'
  exit 0
}

exec python3 "$ROOT/installer/tests/gui_widgets_test.py"
