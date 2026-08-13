#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'find "$TMP" -depth -delete' EXIT

for option in --output-dir --since; do
  if "$ROOT/installer/bin/aurade-hardware-qualify" "$option" \
      >"$TMP/${option#--}.out" 2>&1; then
    echo "missing argument unexpectedly passed: $option" >&2
    exit 1
  fi
  grep -Fq -- "$option requires an argument" "$TMP/${option#--}.out"
  grep -Fq -- 'Usage: aurade-hardware-qualify' "$TMP/${option#--}.out"
done

if "$ROOT/installer/bin/aurade-hardware-qualify" --not-an-option \
    >"$TMP/unknown.out" 2>&1; then
  echo 'unknown option unexpectedly passed' >&2
  exit 1
fi
grep -Fq -- 'unknown option: --not-an-option' "$TMP/unknown.out"

echo 'hardware qualification argument test: PASS'
