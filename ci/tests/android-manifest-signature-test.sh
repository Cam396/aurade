#!/usr/bin/env bash
# The Android service only trusts a fetched image manifest that carries a good
# detached signature from a trusted key, and never one older than the manifest
# in use. The keyring the package ships must be the pinned release key.
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export GNUPGHOME="$TMP/gnupg"
mkdir -m 700 "$GNUPGHOME"

cmp -s "$ROOT/aurade-android/release.gpg" "$ROOT/pins/aurade-release.gpg" || {
  echo "android manifest signature: shipped keyring is not the pinned release key"; exit 1; }

gpg --batch --quiet --passphrase '' --quick-gen-key 'Test Signer <test@example.invalid>' ed25519 sign 1d
gpg --batch --quiet --export > "$TMP/trusted.gpg"
gpg --batch --quiet --passphrase '' --quick-gen-key 'Other Signer <other@example.invalid>' ed25519 sign 1d

cat > "$TMP/images.json" <<'JSON'
{"version": "2026-10-20", "base_url": "https://example.invalid/", "files": [
 {"name": "system.img", "sha256": "0000000000000000000000000000000000000000000000000000000000000000", "size": 1}]}
JSON
gpg --batch --quiet --detach-sign --local-user test@example.invalid -o "$TMP/images.json.sig" "$TMP/images.json"
gpg --batch --quiet --detach-sign --local-user other@example.invalid -o "$TMP/other.sig" "$TMP/images.json"

python3 -I - "$ROOT/aurade-android/aurade-android" "$TMP" <<'PY'
import importlib.machinery, importlib.util, sys
path, tmp = sys.argv[1:3]
loader = importlib.machinery.SourceFileLoader("aurade_android", path)
spec = importlib.util.spec_from_loader("aurade_android", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)
A = mod.Android
raw = open(f"{tmp}/images.json", "rb").read()
good = open(f"{tmp}/images.json.sig", "rb").read()
other = open(f"{tmp}/other.sig", "rb").read()
rings = [f"{tmp}/trusted.gpg"]

def check(name, cond):
    if not cond:
        print("android manifest signature: FAIL", name); sys.exit(1)

check("good signature accepted", A.accept_manifest(raw, good, rings, "2026-10-16b") is not None)
check("same version accepted", A.accept_manifest(raw, good, rings, "2026-10-20") is not None)
check("older than current refused", A.accept_manifest(raw, good, rings, "2026-10-21") is None)
check("untrusted signer refused", A.accept_manifest(raw, other, rings) is None)
check("missing signature refused", A.accept_manifest(raw, b"", rings) is None)
check("no keyrings refused", A.accept_manifest(raw, good, []) is None)
check("garbage signature refused", A.accept_manifest(raw, b"not a signature", rings) is None)
check("tampered manifest refused", A.accept_manifest(raw.replace(b"system.img", b"evil.img"), good, rings) is None)
bad_http = raw.replace(b"https://", b"http://")
check("signed but not https refused", A.accept_manifest(bad_http, good, rings) is None)
print("android manifest signature test: PASS")
PY
