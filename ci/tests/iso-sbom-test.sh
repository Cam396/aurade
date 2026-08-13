#!/usr/bin/env bash
# Verify the ISO SBOM generator with deterministic fixture packages.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
install -d -m 0755 "$TMP/repo" "$TMP/package"

make_package() {
  local name=$1 version=$2
  cat >"$TMP/package/.PKGINFO" <<EOF
pkgname = $name
pkgver = $version
pkgrel = 1
arch = x86_64
license = BSD-3-Clause
EOF
  bsdtar -cf "$TMP/repo/${name}-${version}-1-x86_64.pkg.tar.zst" \
    -C "$TMP/package" .PKGINFO
}

make_package aurade 0.1.0
make_package aurade-login 0.2.0
printf '%s\n' 'fixture ISO bytes' >"$TMP/aurade.iso"

SOURCE_DATE_EPOCH=1783814400 python3 "$ROOT/ci/write-iso-sbom.py" \
  --iso "$TMP/aurade.iso" --repo-dir "$TMP/repo" --output "$TMP/one.json"
SOURCE_DATE_EPOCH=1783814400 python3 "$ROOT/ci/write-iso-sbom.py" \
  --iso "$TMP/aurade.iso" --repo-dir "$TMP/repo" --output "$TMP/two.json"
cmp -s "$TMP/one.json" "$TMP/two.json"

python3 - "$TMP/one.json" "$TMP/aurade.iso" <<'PY'
import hashlib
import json
import pathlib
import sys

document = json.loads(pathlib.Path(sys.argv[1]).read_text())
iso = pathlib.Path(sys.argv[2])
assert document["spdxVersion"] == "SPDX-2.3"
assert document["creationInfo"]["created"] == "2026-07-12T00:00:00Z"
assert document["documentNamespace"].endswith(hashlib.sha256(iso.read_bytes()).hexdigest())
names = {package["name"] for package in document["packages"]}
assert names == {"aurade.iso", "aurade", "aurade-login"}
assert len(document["relationships"]) == 2
assert all(rel["relationshipType"] == "CONTAINS" for rel in document["relationships"])
PY

install -d "$TMP/bad"
printf '%s\n' 'not an archive' >"$TMP/bad/bad-1-any.pkg.tar.zst"
if SOURCE_DATE_EPOCH=1783814400 python3 "$ROOT/ci/write-iso-sbom.py" \
    --iso "$TMP/aurade.iso" --repo-dir "$TMP/bad" --output "$TMP/bad.json" \
    >"$TMP/bad.out" 2>&1; then
  echo 'malformed package unexpectedly produced an SBOM' >&2
  exit 1
fi
grep -Fq 'cannot read .PKGINFO' "$TMP/bad.out"

echo 'ISO SBOM test: PASS'
