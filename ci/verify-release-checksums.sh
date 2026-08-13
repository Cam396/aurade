#!/usr/bin/env bash
# Refuse a staged package repository whose committed checksum manifest differs.
set -Eeuo pipefail

REPO_DIR=${REPO_DIR:?Set REPO_DIR to the staged package repository}

command -v sha256sum >/dev/null 2>&1 || {
  echo 'Missing required command: sha256sum' >&2
  exit 2
}
command -v cmp >/dev/null 2>&1 || {
  echo 'Missing required command: cmp' >&2
  exit 2
}
[[ -d "$REPO_DIR" ]] || {
  echo "Missing repository directory: $REPO_DIR" >&2
  exit 1
}
[[ -f "$REPO_DIR/SHA256SUMS" ]] || {
  echo "Missing release checksum manifest: $REPO_DIR/SHA256SUMS" >&2
  exit 1
}

mapfile -d '' checksum_files < <(find "$REPO_DIR" -maxdepth 1 -type f \
  ! -name SHA256SUMS -printf '%f\0' | LC_ALL=C sort -z)
[[ "${#checksum_files[@]}" -gt 0 ]] || {
  echo "No published files to verify in $REPO_DIR" >&2
  exit 1
}

expected=$(mktemp)
trap 'rm -f "$expected"' EXIT
(
  cd "$REPO_DIR"
  sha256sum -- "${checksum_files[@]}"
) >"$expected"

cmp -s "$expected" "$REPO_DIR/SHA256SUMS" || {
  echo 'Release checksum manifest does not exactly match published files' >&2
  exit 1
}

echo "Release checksum manifest verified: $REPO_DIR/SHA256SUMS"
