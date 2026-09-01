#!/usr/bin/env bash
# Every local source file in every PKGBUILD must match its recorded checksum.
#
# This is not a theoretical gate. chromiumos-ash-session.sh sat with a stale
# sha256 on main, so makepkg would have refused the package at its integrity
# check, and nothing in the tree noticed. Editing a packaged script and
# forgetting its checksum is a one line mistake with no local symptom: the file
# works, the tests pass, and the failure appears only when somebody builds the
# package.
#
# Only local files are checked. Remote sources are fetched, not read from here.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
fail() { echo "pkgbuild checksum test: $*" >&2; exit 1; }

python3 - "$ROOT" <<'PY'
import hashlib
import io
import os
import re
import sys

root = sys.argv[1]
problems = []
checked = 0
packages = 0

for entry in sorted(os.listdir(root)):
    pkgbuild = os.path.join(root, entry, "PKGBUILD")
    if not os.path.isfile(pkgbuild):
        continue
    packages += 1
    text = io.open(pkgbuild, encoding="utf-8", errors="replace").read()

    src = re.search(r"^source=\((.*?)^\)", text, re.S | re.M)
    if not src:
        src = re.search(r"^source=\((.*?)\)", text, re.S | re.M)
    sha = re.search(r"^sha256sums=\((.*?)\)", text, re.S | re.M)
    if not src or not sha:
        continue

    # Both quote styles appear across these PKGBUILDs, and matching only one
    # silently reports zero sources against a full list of checksums.
    sources = re.findall(r"""['"]([^'"]+)['"]""", src.group(1))
    sums = re.findall(r"""['"]([0-9a-f]{64}|SKIP)['"]""", sha.group(1))
    if len(sources) != len(sums):
        problems.append(
            "%s: %d sources against %d checksums" % (entry, len(sources), len(sums)))
        continue

    for name, recorded in zip(sources, sums):
        if recorded == "SKIP":
            continue
        # A remote source is fetched by makepkg, so there is nothing local to
        # compare it against.
        if "://" in name:
            continue
        path = os.path.join(root, entry, name)
        if not os.path.isfile(path):
            continue
        actual = hashlib.sha256(io.open(path, "rb").read()).hexdigest()
        checked += 1
        if actual != recorded:
            problems.append(
                "%s/%s: recorded %s, actual %s" % (entry, name, recorded[:16], actual[:16]))

if problems:
    for line in problems:
        print("  " + line, file=sys.stderr)
    print("pkgbuild checksum test: %d stale checksum(s)" % len(problems), file=sys.stderr)
    sys.exit(1)

print("pkgbuild checksum test: PASS (%d files across %d packages)" % (checked, packages))
PY
