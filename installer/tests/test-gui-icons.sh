#!/usr/bin/env bash
# Every icon name the graphical installer asks for, against the icon theme the
# installation image actually installs.
#
# This is the counterpart of the widget test. That one asks whether a name
# exists in the toolkit; this one asks whether a name exists in the artwork,
# which is a different question with the same failure mode - the front end
# calls a real function with a name nothing resolves, and the page draws a gap
# where an icon should be. No warning, no failed test, and no way to see it in
# a screenshot taken on a machine whose icon theme is a different version.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)

command -v python3 >/dev/null 2>&1 || {
  echo 'installer GUI icon test: SKIP (python3 not available)'
  exit 0
}

exec python3 "$ROOT/installer/tests/gui_icon_test.py"
