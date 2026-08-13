#!/usr/bin/env bash
# Verify the sidecars emitted by installer/build-iso.sh before publication.
set -Eeuo pipefail

usage() {
  printf '%s\n' 'Usage: ci/verify-iso-artifacts.sh ISO [--require-signature]' >&2
}

ISO=${1:-}
REQUIRE_SIGNATURE=${AURADE_REQUIRE_ISO_SIGNATURE:-0}
[[ $REQUIRE_SIGNATURE == 0 || $REQUIRE_SIGNATURE == 1 ]] || {
  echo 'verify-iso-artifacts: AURADE_REQUIRE_ISO_SIGNATURE must be 0 or 1' >&2
  exit 2
}
if [[ $# -gt 1 ]]; then
  [[ ${2:-} == --require-signature && $# -eq 2 ]] || {
    usage
    exit 2
  }
  REQUIRE_SIGNATURE=1
fi
[[ -n $ISO ]] || { usage; exit 2; }
[[ $ISO == /* ]] || ISO=$(readlink -f -- "$ISO")
[[ -f $ISO ]] || { echo "verify-iso-artifacts: ISO does not exist: $ISO" >&2; exit 1; }

basename_iso=$(basename -- "$ISO")
checksum="$ISO.sha256"
build_info="$ISO.build-info"
sbom="$ISO.sbom.spdx.json"
iso_signature="$ISO.sig"
sbom_signature="$sbom.sig"
for sidecar in "$checksum" "$build_info" "$sbom"; do
  [[ -f $sidecar ]] || {
    echo "verify-iso-artifacts: missing sidecar: $sidecar" >&2
    exit 1
  }
done

expected_line=$(awk 'NF {print; count++} END {exit count != 1}' "$checksum") || {
  echo "verify-iso-artifacts: checksum sidecar must contain exactly one record" >&2
  exit 1
}
expected_digest=$(awk 'NF {print $1; exit}' <<<"$expected_line")
expected_name=$(awk 'NF {sub(/^\*/, "", $2); print $2; exit}' <<<"$expected_line")
[[ $expected_digest =~ ^[0-9a-fA-F]{64}$ && $expected_name == "$basename_iso" ]] || {
  echo 'verify-iso-artifacts: checksum sidecar has the wrong ISO name or digest format' >&2
  exit 1
}
actual_digest=$(sha256sum -- "$ISO" | awk '{print $1}')
[[ $actual_digest == "$expected_digest" ]] || {
  echo "verify-iso-artifacts: ISO checksum mismatch (expected $expected_digest, got $actual_digest)" >&2
  exit 1
}

python3 - "$sbom" "$basename_iso" "$actual_digest" "$build_info" "$ISO" <<'PY'
import hashlib
import json
import pathlib
import re
import sys

sbom_path, iso_name, iso_digest, build_info_path, iso_path = sys.argv[1:]
document = json.loads(pathlib.Path(sbom_path).read_text(encoding="utf-8"))
if document.get("spdxVersion") != "SPDX-2.3":
    raise SystemExit("verify-iso-artifacts: SBOM is not SPDX-2.3")
if not document.get("packages"):
    raise SystemExit("verify-iso-artifacts: SBOM contains no packages")
iso_packages = [p for p in document["packages"] if p.get("packageFileName") == iso_name]
if len(iso_packages) != 1:
    raise SystemExit("verify-iso-artifacts: SBOM does not identify the ISO exactly once")
checksums = iso_packages[0].get("checksums", [])
if {c.get("algorithm"): c.get("checksumValue") for c in checksums}.get("SHA256") != iso_digest:
    raise SystemExit("verify-iso-artifacts: SBOM ISO checksum does not match the image")
if not document.get("documentNamespace", "").endswith(iso_digest):
    raise SystemExit("verify-iso-artifacts: SBOM namespace is not bound to the ISO digest")

info = {}
for line in pathlib.Path(build_info_path).read_text(encoding="utf-8").splitlines():
    if "=" in line:
        key, value = line.split("=", 1)
        info[key] = value
if info.get("sbom_file") != pathlib.Path(sbom_path).name:
    raise SystemExit("verify-iso-artifacts: build-info points at a different SBOM")
sbom_digest = hashlib.sha256(pathlib.Path(sbom_path).read_bytes()).hexdigest()
if info.get("sbom_sha256") != sbom_digest:
    raise SystemExit("verify-iso-artifacts: build-info SBOM digest mismatch")

snapshot = info.get("arch_snapshot", "")
if not re.fullmatch(r"\d{4}/\d{2}/\d{2}", snapshot):
    raise SystemExit("verify-iso-artifacts: build-info has invalid arch_snapshot")
source_epoch = info.get("source_date_epoch", "")
if not source_epoch.isdigit() or int(source_epoch) <= 0:
    raise SystemExit("verify-iso-artifacts: build-info has invalid source_date_epoch")
if not info.get("repo_url", ""):
    raise SystemExit("verify-iso-artifacts: build-info is missing repo_url")
repo_fingerprint = info.get("repo_fingerprint", "")
if repo_fingerprint != "unsigned" and not re.fullmatch(r"[0-9A-Fa-f]{40,64}", repo_fingerprint):
    raise SystemExit("verify-iso-artifacts: build-info has invalid repo_fingerprint")

def positive_int(name):
    value = info.get(name, "")
    if not value.isdigit() or int(value) <= 0:
        raise SystemExit(f"verify-iso-artifacts: build-info has invalid {name}")
    return int(value)

iso_bytes = positive_int("iso_bytes")
iso_max_bytes = positive_int("iso_max_bytes")
package_count = positive_int("package_count")
package_bytes = positive_int("package_bytes")
actual_iso_bytes = pathlib.Path(iso_path).stat().st_size
if iso_bytes != actual_iso_bytes:
    raise SystemExit("verify-iso-artifacts: build-info ISO size mismatch")
if iso_bytes > iso_max_bytes:
    raise SystemExit("verify-iso-artifacts: ISO exceeds build-info size ceiling")
if package_count < 1 or package_bytes < 1:
    raise SystemExit("verify-iso-artifacts: build-info package closure is empty")
PY

if [[ -e $iso_signature || -e $sbom_signature || $REQUIRE_SIGNATURE == 1 ]]; then
  command -v gpg >/dev/null 2>&1 || {
    echo 'verify-iso-artifacts: gpg is required to verify detached signatures' >&2
    exit 1
  }
  [[ -s $iso_signature && -s $sbom_signature ]] || {
    echo 'verify-iso-artifacts: both ISO and SBOM signatures are required together' >&2
    exit 1
  }
  signing_fingerprint=$(awk -F= '$1 == "iso_signing_fingerprint" {print toupper($2); exit}' "$build_info")
  [[ $signing_fingerprint =~ ^[0-9A-F]{40,64}$ ]] || {
    echo 'verify-iso-artifacts: build-info lacks a full ISO signing fingerprint' >&2
    exit 1
  }
  verify_signature() {
    local signature=$1 payload=$2 label=$3 status signer primary
    if ! status=$(gpg --batch --status-fd 1 --verify "$signature" "$payload" 2>/dev/null); then
      echo "verify-iso-artifacts: invalid $label signature" >&2
      return 1
    fi
    signer=$(awk '$1 == "[GNUPG:]" && $2 == "VALIDSIG" {print toupper($3); exit}' <<<"$status")
    primary=$(awk '$1 == "[GNUPG:]" && $2 == "VALIDSIG" {print toupper($NF); exit}' <<<"$status")
    [[ $signer == "$signing_fingerprint" || $primary == "$signing_fingerprint" ]] || {
      echo "verify-iso-artifacts: $label signer fingerprint does not match build-info" >&2
      return 1
    }
  }
  verify_signature "$iso_signature" "$ISO" ISO
  verify_signature "$sbom_signature" "$sbom" SBOM
fi

printf 'ISO artifact verification: PASS (%s)\n' "$basename_iso"
