#!/usr/bin/env bash
# Compile only the route helper carried by the series. No running desktop or
# Chromium build is involved, and mutations never edit the real source tree.
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
exec python3 "$ROOT/ci/tests/pipewire_audio_route_test.py" "$@"
