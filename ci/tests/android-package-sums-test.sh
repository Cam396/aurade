#!/usr/bin/env bash
# The Android service package must build from what is in the tree: every source
# listed in its PKGBUILD has the checksum the PKGBUILD says, and the Python
# files compile.
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
cd "$ROOT/aurade-android"
python3 -I - <<'PY'
import hashlib, py_compile, re, sys, tempfile, os
s = open("PKGBUILD").read()
files = re.findall(r"'([^']+)'", re.search(r"source=\((.*?)\n\)", s, re.S).group(1))
sums = re.findall(r"'([0-9a-f]{64})'", re.search(r"sha256sums=\((.*?)\)", s, re.S).group(1))
bad = [f for f, h in zip(files, sums) if hashlib.sha256(open(f, "rb").read()).hexdigest() != h]
if len(files) != len(sums) or bad:
    print("android package sums: stale for", bad or "count mismatch"); sys.exit(1)
tmp = tempfile.mkdtemp()
for f in ("aurade-android", "aurade-android-patch-waydroid", "aurade-apk-check", "aurade-android-install"):
    py_compile.compile(f, cfile=os.path.join(tmp, f + ".pyc"), doraise=True)
print("android package sums test: PASS")
PY
