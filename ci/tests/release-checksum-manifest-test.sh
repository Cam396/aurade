#!/usr/bin/env bash
# Fixture coverage for the immutable package-repository checksum manifest.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
REPO_DIR="$TMP/repo"
install -d -m 0755 "$REPO_DIR"
printf 'package payload\n' >"$REPO_DIR/aurade-1.0-1-any.pkg.tar.zst"
printf 'repository database\n' >"$REPO_DIR/aurade.db.tar.gz"

REPO_DIR="$REPO_DIR" "$ROOT/ci/write-release-checksums.sh"
REPO_DIR="$REPO_DIR" "$ROOT/ci/verify-release-checksums.sh"

printf 'tampered\n' >>"$REPO_DIR/aurade.db.tar.gz"
if REPO_DIR="$REPO_DIR" "$ROOT/ci/verify-release-checksums.sh" \
    >"$TMP/tampered.out" 2>&1; then
  echo 'tampered repository unexpectedly passed checksum verification' >&2
  exit 1
fi
grep -Fq 'does not exactly match published files' "$TMP/tampered.out"

REPO_DIR="$REPO_DIR" "$ROOT/ci/write-release-checksums.sh"
printf 'unlisted file\n' >"$REPO_DIR/unlisted-artifact"
if REPO_DIR="$REPO_DIR" "$ROOT/ci/verify-release-checksums.sh" \
    >"$TMP/unlisted.out" 2>&1; then
  echo 'repository with an unlisted artifact unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'does not exactly match published files' "$TMP/unlisted.out"

rm "$REPO_DIR/SHA256SUMS"
if REPO_DIR="$REPO_DIR" "$ROOT/ci/verify-release-checksums.sh" \
    >"$TMP/missing.out" 2>&1; then
  echo 'repository without a checksum manifest unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'Missing release checksum manifest' "$TMP/missing.out"

echo 'release checksum manifest test: PASS'
