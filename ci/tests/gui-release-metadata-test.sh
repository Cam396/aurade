#!/usr/bin/env bash
# Validate the source-of-truth manifest for the unreleased 0.2.0 GUI.
# This is intentionally source-only: it binds the files and package closure
# without pretending that an unsigned or repacked ISO is a public release.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
VERIFY="$ROOT/ci/verify-gui-release-manifest.py"
MANIFEST=${AURADE_GUI_RELEASE_MANIFEST:-$ROOT/installer/gui-release-manifest.json}

ROOT="$ROOT" python3 "$VERIFY" "$MANIFEST"

TMP=$(mktemp -d)
trap 'rm -rf -- "$TMP"' EXIT
cp -- "$MANIFEST" "$TMP/release-0.1.json"
ROOT="$ROOT" python3 - "$TMP/release-0.1.json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
data["release"] = "0.1.0"
path.write_text(json.dumps(data), encoding="utf-8")
PY
if ROOT="$ROOT" python3 "$VERIFY" "$TMP/release-0.1.json" >"$TMP/release-0.1.out" 2>&1; then
    echo 'GUI metadata mutation to 0.1.0 unexpectedly passed' >&2
    exit 1
fi
grep -Fq 'GUI release must be exactly 0.2.0' "$TMP/release-0.1.out"

cp -- "$MANIFEST" "$TMP/bad-digest.json"
ROOT="$ROOT" python3 - "$TMP/bad-digest.json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
data["payload"][0]["sha256"] = "0" * 64
path.write_text(json.dumps(data), encoding="utf-8")
PY
if ROOT="$ROOT" python3 "$VERIFY" "$TMP/bad-digest.json" >"$TMP/bad-digest.out" 2>&1; then
    echo 'GUI metadata digest mutation unexpectedly passed' >&2
    exit 1
fi
grep -Fq 'payload digest mismatch' "$TMP/bad-digest.out"

echo 'GUI release metadata test: PASS'
