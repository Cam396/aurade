#!/usr/bin/env python3
"""Fail-closed source manifest validation for the AuraDE 0.2.0 GUI."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(f"gui-release-metadata: {message}")


if len(sys.argv) != 2:
    fail("usage: verify-gui-release-manifest.py MANIFEST")

root = Path(os.environ.get("ROOT", Path(__file__).resolve().parents[1]))
manifest_path = Path(sys.argv[1])
try:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    fail(f"cannot read manifest: {exc}")

expected_top_level = {
    "schema",
    "release",
    "status",
    "architectures",
    "source",
    "payload",
    "runtime_packages",
    "public_release_policy",
}
if not isinstance(data, dict):
    fail("manifest root is not an object")
unknown = sorted(set(data) - expected_top_level)
missing = sorted(expected_top_level - set(data))
if unknown or missing:
    fail(f"manifest keys do not match schema (unknown={unknown}, missing={missing})")
if data.get("schema") != 1:
    fail("unsupported schema")
if data.get("release") != "0.2.0":
    fail("GUI release must be exactly 0.2.0")
if data.get("status") not in {"candidate", "ready-for-maintainer-review"}:
    fail("GUI release has an unsafe status")
if data.get("architectures") != ["x86_64"]:
    fail("architecture contract must be exactly x86_64")
source = data.get("source")
if not isinstance(source, dict) or set(source) != {"tree", "provenance"} or source.get("tree") != "installer":
    fail("source tree is missing or incorrect")
if not source.get("provenance"):
    fail("source provenance is missing")

payload = data.get("payload")
if not isinstance(payload, list) or not payload:
    fail("payload list is empty")
seen = set()
for item in payload:
    if not isinstance(item, dict):
        fail("payload entry is not an object")
    if set(item) != {"path", "sha256"}:
        fail("payload entry has unknown or missing keys")
    path_text = item.get("path")
    digest = item.get("sha256")
    if not isinstance(path_text, str) or path_text in seen:
        fail("payload paths must be unique and textual")
    path_obj = Path(path_text)
    if path_obj.is_absolute() or ".." in path_obj.parts:
        fail(f"unsafe payload path: {path_text}")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        fail(f"invalid payload digest: {path_text}")
    path = root / path_obj
    if not path.is_file():
        fail(f"payload file is missing: {path_text}")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != digest:
        fail(f"payload digest mismatch: {path_text}")
    seen.add(path_text)

required = {
    "installer/bin/aurade-installer-gui",
    "installer/bin/aurade-installer-gui-bridge",
    "installer/bin/aurade-installer-start",
    "installer/lib/aurade-probe.sh",
    "installer/lib/aurade-questions.sh",
    "installer/lib/aurade-validate.sh",
    "installer/lib/aurade-journal.sh",
    "installer/lib/aurade-tui.sh",
    "installer/lib/aurade_gui/app.py",
    "installer/lib/aurade_gui/bridge.py",
    "installer/lib/aurade_gui/flow.py",
}
if not required.issubset(seen):
    fail(f"required GUI payload is missing: {sorted(required - seen)}")

packages = data.get("runtime_packages")
expected_packages = {"cage", "gtk4", "libadwaita", "python-gobject"}
if not isinstance(packages, list) or sorted(packages) != sorted(expected_packages):
    fail("runtime package closure is incomplete or contains unexpected entries")
package_file = root / "installer/archiso/packages.x86_64"
listed = {
    line.strip()
    for line in package_file.read_text(encoding="utf-8").splitlines()
    if line.strip() and not line.startswith("#")
}
missing = sorted(set(packages) - listed)
if missing:
    fail(f"runtime packages are absent from the ISO profile: {missing}")

policy = data.get("public_release_policy")
expected_policy = {
    "gui_in_0_1_0",
    "artifact_signature_required",
    "full_profile_build_required",
    "physical_accelerated_runtime_required",
}
if not isinstance(policy, dict) or set(policy) != expected_policy or policy.get("gui_in_0_1_0") is not False:
    fail("the GUI must remain excluded from public 0.1.0")
for key in (
    "artifact_signature_required",
    "full_profile_build_required",
    "physical_accelerated_runtime_required",
):
    if policy.get(key) is not True:
        fail(f"0.2.0 gate is not fail-closed for {key}")

print(f"GUI release metadata gate: PASS ({len(payload)} payload files, 0.2.0 candidate)")
