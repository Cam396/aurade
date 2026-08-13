#!/usr/bin/env python3
"""Write a deterministic SPDX 2.3 SBOM for an AuraDE ISO and its payload."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_pkginfo(raw: bytes, path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in raw.decode("utf-8", errors="strict").splitlines():
        if " = " not in line:
            continue
        key, value = line.split(" = ", 1)
        fields.setdefault(key, value)
    missing = [key for key in ("pkgname", "pkgver", "arch") if not fields.get(key)]
    if missing:
        raise ValueError(f"{path.name}: .PKGINFO is missing {', '.join(missing)}")
    return fields


def pkginfo(path: Path, bsdtar: str) -> dict[str, str]:
    try:
        result = subprocess.run(
            [bsdtar, "-xOf", str(path), ".PKGINFO"],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"{path.name}: cannot read .PKGINFO") from exc
    return parse_pkginfo(result.stdout, path)


def spdx_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9.-]+", "-", value).strip("-")
    return cleaned or "package"


def created_time() -> str:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch and epoch.isdigit():
        value = dt.datetime.fromtimestamp(int(epoch), dt.timezone.utc)
    else:
        value = dt.datetime.now(dt.timezone.utc)
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_document(iso: Path, repo: Path, bsdtar: str) -> dict:
    iso_digest = sha256(iso)
    package_paths = sorted(
        path
        for path in repo.iterdir()
        if path.is_file()
        and ".pkg.tar." in path.name
        and not path.name.endswith(".sig")
    )
    if not package_paths:
        raise ValueError("repository contains no package archives")

    iso_id = "SPDXRef-AuraDE-ISO"
    packages = [
        {
            "SPDXID": iso_id,
            "name": iso.name,
            "versionInfo": "NOASSERTION",
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": "NOASSERTION",
            "copyrightText": "NOASSERTION",
            "checksums": [{"algorithm": "SHA256", "checksumValue": iso_digest}],
            "packageFileName": iso.name,
        }
    ]
    relationships = []
    seen_ids: set[str] = set()
    for path in package_paths:
        fields = pkginfo(path, bsdtar)
        identity = f"{fields['pkgname']}-{fields['pkgver']}-{fields['arch']}"
        package_id = f"SPDXRef-Package-{spdx_id(identity)}"
        if package_id in seen_ids:
            raise ValueError(f"duplicate package identity: {identity}")
        seen_ids.add(package_id)
        license_value = fields.get("license", "NOASSERTION")
        packages.append(
            {
                "SPDXID": package_id,
                "name": fields["pkgname"],
                "versionInfo": fields["pkgver"],
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": license_value,
                "licenseDeclared": license_value,
                "copyrightText": "NOASSERTION",
                "checksums": [{"algorithm": "SHA256", "checksumValue": sha256(path)}],
                "packageFileName": path.name,
                "architecture": fields["arch"],
            }
        )
        relationships.append(
            {
                "spdxElementId": iso_id,
                "relatedSpdxElement": package_id,
                "relationshipType": "CONTAINS",
            }
        )

    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"AuraDE ISO {iso.name}",
        "documentNamespace": f"https://aurade.dev/spdx/{iso_digest}",
        "creationInfo": {
            "created": created_time(),
            "creators": ["Tool: AuraDE write-iso-sbom.py"],
        },
        "packages": packages,
        "relationships": relationships,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso", required=True, type=Path)
    parser.add_argument("--repo-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not args.iso.is_file():
        parser.error(f"ISO does not exist: {args.iso}")
    if not args.repo_dir.is_dir():
        parser.error(f"repository directory does not exist: {args.repo_dir}")
    bsdtar = shutil.which("bsdtar")
    if not bsdtar:
        parser.error("bsdtar is required to inspect package archives")
    try:
        document = build_document(args.iso, args.repo_dir, bsdtar)
    except (OSError, ValueError) as exc:
        print(f"write-iso-sbom: {exc}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"ISO SBOM written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
