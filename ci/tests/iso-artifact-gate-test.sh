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

# A valid detached signature must also match the signer fingerprint recorded
# by the builder. The fixture uses an ephemeral keyring and never touches the
# host trust database.
GPG_HOME="$TMP/gnupg"
install -d -m 0700 "$GPG_HOME"
cat >"$TMP/keyparams" <<'EOF'
Key-Type: RSA
Key-Length: 2048
Name-Real: AuraDE test signer
Name-Email: test-signer@example.invalid
Expire-Date: 0
%no-protection
%commit
EOF
GNUPGHOME="$GPG_HOME" gpg --batch --generate-key "$TMP/keyparams" >/dev/null 2>&1
signing_fingerprint=$(GNUPGHOME="$GPG_HOME" gpg --batch --with-colons \
  --list-secret-keys | awk -F: '$1 == "fpr" {print $10; exit}')
GNUPGHOME="$GPG_HOME" gpg --batch --yes --local-user "$signing_fingerprint" \
  --detach-sign --output "$ISO.sig" "$ISO"
GNUPGHOME="$GPG_HOME" gpg --batch --yes --local-user "$signing_fingerprint" \
  --detach-sign --output "$ISO.sbom.spdx.json.sig" "$ISO.sbom.spdx.json"
printf 'iso_signing_fingerprint=%s\n' "$signing_fingerprint" >>"$ISO.build-info"
GNUPGHOME="$GPG_HOME" "$ROOT/ci/verify-iso-artifacts.sh" "$ISO" --require-signature

# A different valid key must not satisfy the expected signer policy.
ALT_HOME="$TMP/alt-gnupg"
install -d -m 0700 "$ALT_HOME"
GNUPGHOME="$ALT_HOME" gpg --batch --generate-key "$TMP/keyparams" >/dev/null 2>&1
alt_fingerprint=$(GNUPGHOME="$ALT_HOME" gpg --batch --with-colons \
  --list-secret-keys | awk -F: '$1 == "fpr" {print $10; exit}')
GNUPGHOME="$ALT_HOME" gpg --batch --yes --local-user "$alt_fingerprint" \
  --detach-sign --output "$ISO.sig" "$ISO"
GNUPGHOME="$ALT_HOME" gpg --batch --yes --local-user "$alt_fingerprint" \
  --detach-sign --output "$ISO.sbom.spdx.json.sig" "$ISO.sbom.spdx.json"
if GNUPGHOME="$ALT_HOME" "$ROOT/ci/verify-iso-artifacts.sh" "$ISO" \
    --require-signature >"$TMP/wrong-signer.out" 2>&1; then
  echo 'ISO signed by an unexpected valid key unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'signer fingerprint does not match build-info' "$TMP/wrong-signer.out"

printf '%s\n' 'tampered' >>"$ISO"
if "$ROOT/ci/verify-iso-artifacts.sh" "$ISO" >"$TMP/tampered.out" 2>&1; then
  echo 'tampered ISO unexpectedly passed artifact verification' >&2
  exit 1
fi
grep -Fq 'ISO checksum mismatch' "$TMP/tampered.out"

echo 'ISO artifact gate test: PASS'
