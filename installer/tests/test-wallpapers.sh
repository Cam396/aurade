#!/usr/bin/env bash
# The wallpaper set, its manifest, and the bands that keep text off it.
#
# No display needed. The drawing is cairo into an image surface, which is the
# same thing `render-design-proof.py` relies on and the reason the brand layer
# is reviewable on a machine with no compositor.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)

command -v python3 >/dev/null 2>&1 || {
  echo 'installer wallpaper test: SKIP (python3 not available)'
  exit 0
}

exec python3 "$ROOT/installer/tests/wallpaper_test.py"
