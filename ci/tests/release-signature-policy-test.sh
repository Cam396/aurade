#!/usr/bin/env bash
# Verify that signed repository mode requires an isolated public keyring and
# an explicit fingerprint before it can inspect or promote a repository.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# The release orchestrator must not silently construct an unsigned candidate
# repository. Its development channel remains available for local fixtures.
if AURADE_RELEASE_CHANNEL=candidate REPO_DIR="$TMP/missing" \
  "$ROOT/ci/build-release-repo.sh" >"$TMP/candidate-builder.out" 2>&1; then
  echo 'unsigned candidate repository build unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'AURADE_RELEASE_CHANNEL=candidate requires GPGKEY' \
  "$TMP/candidate-builder.out"

if AURADE_RELEASE_CHANNEL=public GPGKEY=fixture REPO_DIR="$TMP/missing" \
  "$ROOT/ci/build-release-repo.sh" >"$TMP/public-builder.out" 2>&1; then
  echo 'public repository build without keyring unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'AURADE_RELEASE_CHANNEL=public requires a readable AURADE_REPO_KEYRING' \
  "$TMP/public-builder.out"

if AURADE_RELEASE_CHANNEL=not-a-channel REPO_DIR="$TMP/missing" \
  "$ROOT/ci/build-release-repo.sh" >"$TMP/channel.out" 2>&1; then
  echo 'invalid release channel unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'AURADE_RELEASE_CHANNEL must be development, soak, candidate, or public' \
  "$TMP/channel.out"

if AURADE_REQUIRE_SIGNATURES=1 REPO_DIR="$TMP/missing" \
  "$ROOT/ci/verify-release-repo.sh" >"$TMP/missing-key.out" 2>&1; then
  echo 'signed repository verification unexpectedly accepted missing keyring' >&2
  exit 1
fi
grep -Fq 'AURADE_REPO_KEYRING must name a readable public keyring' "$TMP/missing-key.out"

GNUPGHOME="$TMP/gnupg"
install -d -m 0700 "$GNUPGHOME"
cat >"$TMP/keyparams" <<'EOF'
Key-Type: RSA
Key-Length: 2048
Name-Real: AuraDE repository fixture
Name-Email: repo-fixture@example.invalid
Expire-Date: 0
%no-protection
%commit
EOF
GNUPGHOME="$GNUPGHOME" gpg --batch --generate-key "$TMP/keyparams" >/dev/null 2>&1
fingerprint=$(GNUPGHOME="$GNUPGHOME" gpg --batch --with-colons \
  --list-secret-keys | awk -F: '$1 == "fpr" {print $10; exit}')
GNUPGHOME="$GNUPGHOME" gpg --batch --export "$fingerprint" >"$TMP/public.gpg"
GNUPGHOME="$GNUPGHOME" gpg --batch --export-secret-keys "$fingerprint" >"$TMP/secret.gpg"

if AURADE_RELEASE_CHANNEL=candidate GPGKEY=fixture \
  AURADE_REPO_KEYRING="$TMP/public.gpg" \
  AURADE_REPO_FINGERPRINT="$fingerprint" AURADE_SIGN_PACKAGES=0 \
  REPO_DIR="$TMP/missing" "$ROOT/ci/build-release-repo.sh" \
  >"$TMP/unsigned-packages.out" 2>&1; then
  echo 'candidate repository with package signing disabled unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'requires detached package signatures' "$TMP/unsigned-packages.out"

if AURADE_REQUIRE_SIGNATURES=1 AURADE_REPO_KEYRING="$TMP/public.gpg" \
  AURADE_REPO_FINGERPRINT=not-a-fingerprint REPO_DIR="$TMP/missing" \
  "$ROOT/ci/verify-release-repo.sh" >"$TMP/bad-fingerprint.out" 2>&1; then
  echo 'invalid repository fingerprint unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'AURADE_REPO_FINGERPRINT must be a full fingerprint' "$TMP/bad-fingerprint.out"

if AURADE_REQUIRE_SIGNATURES=1 AURADE_REPO_KEYRING="$TMP/secret.gpg" \
  AURADE_REPO_FINGERPRINT="$fingerprint" REPO_DIR="$TMP/missing" \
  "$ROOT/ci/verify-release-repo.sh" >"$TMP/secret-keyring.out" 2>&1; then
  echo 'secret repository keyring unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'must contain public keys only' "$TMP/secret-keyring.out"

if AURADE_REQUIRE_SIGNATURES=1 AURADE_REPO_KEYRING="$TMP/public.gpg" \
  AURADE_REPO_FINGERPRINT="$fingerprint" REPO_DIR="$TMP/missing" \
  "$ROOT/ci/verify-release-repo.sh" >"$TMP/accepted-policy.out" 2>&1; then
  echo 'missing repository unexpectedly passed after valid key policy' >&2
  exit 1
fi
grep -Fq 'Missing repository database' "$TMP/accepted-policy.out"

echo 'release signature policy test: PASS'
