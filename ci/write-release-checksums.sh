#!/usr/bin/env bash
# Write the canonical checksum manifest for a staged AuraDE package repository.
set -Eeuo pipefail

REPO_DIR=${REPO_DIR:?Set REPO_DIR to the staged package repository}

command -v sha256sum >/dev/null 2>&1 || {
  echo 'Missing required command: sha256sum' >&2
  exit 2
}
[[ -d "$REPO_DIR" ]] || {
  echo "Missing repository directory: $REPO_DIR" >&2
  exit 1
}

mapfile -d '' checksum_files < <(find "$REPO_DIR" -maxdepth 1 -type f \
  ! -name SHA256SUMS -printf '%f\0' | LC_ALL=C sort -z)
[[ "${#checksum_files[@]}" -gt 0 ]] || {
  echo "No published files to checksum in $REPO_DIR" >&2
  exit 1
}

(
  cd "$REPO_DIR"
  sha256sum -- "${checksum_files[@]}"
) >"$REPO_DIR/SHA256SUMS"

echo "Release checksum manifest written: $REPO_DIR/SHA256SUMS"
