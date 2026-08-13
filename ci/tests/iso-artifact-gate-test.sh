#!/usr/bin/env bash
# Fixture coverage for the final checksum/SBOM/build-info publication gate.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
install -d -m 0755 "$TMP/repo" "$TMP/package"
ISO="$TMP/aurade-test.iso"
printf '%s\n' 'disposable ISO fixture' >"$ISO"
cat >"$TMP/package/.PKGINFO" <<'EOF'
pkgname = aurade
pkgver = 1.0-1
arch = any
license = BSD-3-Clause
EOF
bsdtar -cf "$TMP/repo/aurade-1.0-1-any.pkg.tar.zst" -C "$TMP/package" .PKGINFO

SOURCE_DATE_EPOCH=1783814400 python3 "$ROOT/ci/write-iso-sbom.py" \
  --iso "$ISO" --repo-dir "$TMP/repo" --output "$ISO.sbom.spdx.json"
(cd "$TMP" && sha256sum "$(basename "$ISO")") >"$ISO.sha256"
sbom_sha=$(sha256sum "$ISO.sbom.spdx.json" | awk '{print $1}')
cat >"$ISO.build-info" <<EOF
sbom_file=$(basename "$ISO.sbom.spdx.json")
sbom_sha256=$sbom_sha
EOF

"$ROOT/ci/verify-iso-artifacts.sh" "$ISO"
if "$ROOT/ci/verify-iso-artifacts.sh" "$ISO" --require-signature \
    >"$TMP/unsigned.out" 2>&1; then
  echo 'signature-required artifact unexpectedly passed without signatures' >&2
  exit 1
fi
grep -Fq 'both ISO and SBOM signatures are required together' "$TMP/unsigned.out"

printf '%s\n' 'tampered' >>"$ISO"
if "$ROOT/ci/verify-iso-artifacts.sh" "$ISO" >"$TMP/tampered.out" 2>&1; then
  echo 'tampered ISO unexpectedly passed artifact verification' >&2
  exit 1
fi
grep -Fq 'ISO checksum mismatch' "$TMP/tampered.out"

echo 'ISO artifact gate test: PASS'
