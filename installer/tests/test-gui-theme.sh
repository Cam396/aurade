#!/usr/bin/env bash
# The design tokens, against the artwork they claim to come from.
#
# Three things are checked, and each has bitten a real product:
#
#   the committed tokens are what the generator produces, so nobody can hand
#   edit a colour into the stylesheet and have it survive;
#
#   every foreground role clears WCAG AA on the surface it is used on, in both
#   schemes, because these palettes are generated from brand hues and a
#   generated palette can put a role somewhere the specification never
#   anticipated;
#
#   the accent hues still match the mark, so a redraw of the logo that nobody
#   propagated to the interface fails here instead of shipping as a product
#   whose icon and window do not look related.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)

command -v python3 >/dev/null 2>&1 || {
  echo 'installer GUI theme test: SKIP (python3 not available)'
  exit 0
}

exec python3 "$ROOT/installer/tests/gui_theme_test.py"
