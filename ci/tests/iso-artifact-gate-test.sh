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
iso_bytes=$(stat -c '%s' "$ISO")
package_bytes=$(stat -c '%s' "$TMP/repo/aurade-1.0-1-any.pkg.tar.zst")
cat >"$ISO.build-info" <<EOF
arch_snapshot=2026/07/12
release_channel=development
gui_release=0
gui_manifest_sha256=not-embedded
source_date_epoch=1783814400
repo_url=https://packages.example.invalid/aurade
repo_fingerprint=unsigned
sbom_file=$(basename "$ISO.sbom.spdx.json")
sbom_sha256=$sbom_sha
iso_bytes=$iso_bytes
iso_max_bytes=4294967296
package_count=1
package_bytes=$package_bytes
packages_lock_sha256=$(printf '%s\n' 'fixture lock' | sha256sum | awk '{print $1}')
EOF

"$ROOT/ci/verify-iso-artifacts.sh" "$ISO"

# Required provenance must not be silently omitted from a release sidecar.
sed -i '/^repo_url=/d' "$ISO.build-info"
if "$ROOT/ci/verify-iso-artifacts.sh" "$ISO" >"$TMP/missing-provenance.out" 2>&1; then
  echo 'artifact with missing repository provenance unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'build-info is missing repo_url' "$TMP/missing-provenance.out"
printf '%s\n' 'repo_url=https://packages.example.invalid/aurade' >>"$ISO.build-info"

# Release-channel provenance is required so a GUI candidate cannot be confused
# with an unsigned development image during publication.
sed -i '/^release_channel=/d' "$ISO.build-info"
if "$ROOT/ci/verify-iso-artifacts.sh" "$ISO" >"$TMP/missing-release-channel.out" 2>&1; then
  echo 'artifact with missing release channel unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'build-info has invalid release_channel' "$TMP/missing-release-channel.out"
printf '%s\n' 'release_channel=development' >>"$ISO.build-info"

# GUI provenance must be internally coherent and fail closed on malformed
# values.
sed -i 's/^gui_release=.*/gui_release=maybe/' "$ISO.build-info"
if "$ROOT/ci/verify-iso-artifacts.sh" "$ISO" >"$TMP/invalid-gui-release.out" 2>&1; then
  echo 'artifact with invalid gui_release unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'build-info has invalid gui_release' "$TMP/invalid-gui-release.out"
sed -i 's/^gui_release=.*/gui_release=0/' "$ISO.build-info"

sed -i 's/^gui_release=.*/gui_release=1/' "$ISO.build-info"
if "$ROOT/ci/verify-iso-artifacts.sh" "$ISO" >"$TMP/missing-gui-digest.out" 2>&1; then
  echo 'GUI artifact without a manifest digest unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'GUI build-info lacks a manifest digest' "$TMP/missing-gui-digest.out"
sed -i 's/^gui_release=.*/gui_release=0/' "$ISO.build-info"

# Duplicate metadata keys must not allow a later value to override provenance.
printf '%s\n' 'repo_fingerprint=unsigned' >>"$ISO.build-info"
if "$ROOT/ci/verify-iso-artifacts.sh" "$ISO" >"$TMP/duplicate-key.out" 2>&1; then
  echo 'artifact with duplicate build-info key unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'duplicate or empty build-info key' "$TMP/duplicate-key.out"
sed -i '$d' "$ISO.build-info"

# The package-lock digest is part of the provenance contract and must be
# machine-readable rather than a raw ``sha256sum`` line.
sed -i '/^packages_lock_sha256=/d' "$ISO.build-info"
if "$ROOT/ci/verify-iso-artifacts.sh" "$ISO" >"$TMP/missing-lock-digest.out" 2>&1; then
  echo 'artifact with missing package-lock digest unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'invalid packages_lock_sha256' "$TMP/missing-lock-digest.out"
printf 'packages_lock_sha256=%s\n' "$(printf '%s\n' 'fixture lock' | sha256sum | awk '{print $1}')" >>"$ISO.build-info"

# A tampered or mismatched SBOM digest recorded in build-info must fail.
sed -i "s/^sbom_sha256=.*/sbom_sha256=0000000000000000000000000000000000000000000000000000000000000000/" "$ISO.build-info"
if "$ROOT/ci/verify-iso-artifacts.sh" "$ISO" >"$TMP/tampered-sbom-digest.out" 2>&1; then
  echo 'artifact with tampered SBOM digest in build-info unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'build-info SBOM digest mismatch' "$TMP/tampered-sbom-digest.out"
sed -i "s/^sbom_sha256=.*/sbom_sha256=$sbom_sha/" "$ISO.build-info"

# Tampering the SBOM file payload itself must also trigger a digest mismatch.
printf ' ' >>"$ISO.sbom.spdx.json"
if "$ROOT/ci/verify-iso-artifacts.sh" "$ISO" >"$TMP/tampered-sbom-file.out" 2>&1; then
  echo 'artifact with tampered SBOM file unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'build-info SBOM digest mismatch' "$TMP/tampered-sbom-file.out"
SOURCE_DATE_EPOCH=1783814400 python3 "$ROOT/ci/write-iso-sbom.py" \
  --iso "$ISO" --repo-dir "$TMP/repo" --output "$ISO.sbom.spdx.json"

# Numeric provenance fields must be strictly positive integers.
sed -i 's/^source_date_epoch=.*/source_date_epoch=invalid/' "$ISO.build-info"
if "$ROOT/ci/verify-iso-artifacts.sh" "$ISO" >"$TMP/invalid-epoch.out" 2>&1; then
  echo 'artifact with non-numeric source_date_epoch unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'build-info has invalid source_date_epoch' "$TMP/invalid-epoch.out"
sed -i 's/^source_date_epoch=.*/source_date_epoch=0/' "$ISO.build-info"
if "$ROOT/ci/verify-iso-artifacts.sh" "$ISO" >"$TMP/zero-epoch.out" 2>&1; then
  echo 'artifact with zero source_date_epoch unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'build-info has invalid source_date_epoch' "$TMP/zero-epoch.out"
sed -i 's/^source_date_epoch=.*/source_date_epoch=1783814400/' "$ISO.build-info"

# Invalid or mismatched ISO byte size provenance must fail.
sed -i 's/^iso_bytes=.*/iso_bytes=not_a_number/' "$ISO.build-info"
if "$ROOT/ci/verify-iso-artifacts.sh" "$ISO" >"$TMP/invalid-iso-bytes.out" 2>&1; then
  echo 'artifact with non-numeric iso_bytes unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'build-info has invalid iso_bytes' "$TMP/invalid-iso-bytes.out"

sed -i "s/^iso_bytes=.*/iso_bytes=$((iso_bytes + 1024))/" "$ISO.build-info"
if "$ROOT/ci/verify-iso-artifacts.sh" "$ISO" >"$TMP/mismatched-iso-bytes.out" 2>&1; then
  echo 'artifact with mismatched iso_bytes unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'build-info ISO size mismatch' "$TMP/mismatched-iso-bytes.out"
sed -i "s/^iso_bytes=.*/iso_bytes=$iso_bytes/" "$ISO.build-info"

# Invalid or violated ISO size ceiling provenance must fail.
sed -i 's/^iso_max_bytes=.*/iso_max_bytes=0/' "$ISO.build-info"
if "$ROOT/ci/verify-iso-artifacts.sh" "$ISO" >"$TMP/zero-iso-max-bytes.out" 2>&1; then
  echo 'artifact with zero iso_max_bytes unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'build-info has invalid iso_max_bytes' "$TMP/zero-iso-max-bytes.out"

sed -i "s/^iso_max_bytes=.*/iso_max_bytes=$((iso_bytes - 1))/" "$ISO.build-info"
if "$ROOT/ci/verify-iso-artifacts.sh" "$ISO" >"$TMP/exceeded-max-bytes.out" 2>&1; then
  echo 'artifact exceeding iso_max_bytes ceiling unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'ISO exceeds build-info size ceiling' "$TMP/exceeded-max-bytes.out"
sed -i 's/^iso_max_bytes=.*/iso_max_bytes=4294967296/' "$ISO.build-info"

# Invalid or zero package count provenance must fail.
sed -i 's/^package_count=.*/package_count=0/' "$ISO.build-info"
if "$ROOT/ci/verify-iso-artifacts.sh" "$ISO" >"$TMP/zero-package-count.out" 2>&1; then
  echo 'artifact with zero package_count unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'build-info has invalid package_count' "$TMP/zero-package-count.out"
sed -i 's/^package_count=.*/package_count=1/' "$ISO.build-info"

# Invalid or zero package bytes provenance must fail.
sed -i 's/^package_bytes=.*/package_bytes=0/' "$ISO.build-info"
if "$ROOT/ci/verify-iso-artifacts.sh" "$ISO" >"$TMP/zero-package-bytes.out" 2>&1; then
  echo 'artifact with zero package_bytes unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'build-info has invalid package_bytes' "$TMP/zero-package-bytes.out"
sed -i "s/^package_bytes=.*/package_bytes=$package_bytes/" "$ISO.build-info"

if AURADE_REQUIRE_ISO_SIGNATURE=1 "$ROOT/ci/verify-iso-artifacts.sh" "$ISO" \
    >"$TMP/env-unsigned.out" 2>&1; then
  echo 'environment signature policy unexpectedly passed without signatures' >&2
  exit 1
fi
grep -Fq 'both ISO and SBOM signatures are required together' "$TMP/env-unsigned.out"
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
