#!/usr/bin/env bash
# No em dashes and no en dashes anywhere AuraDE writes.
#
# This is a standing house rule and until now it was enforced in three places:
# the installer voice test, and two of the Files patches. Everything outside
# those three windows drifted, which is how seven of them ended up in the build
# script and eighteen more in the terminal patch.
#
# Two exemptions, both narrow and both listed with a reason:
#   installer/bible/       public domain scripture, not AuraDE's prose
#   installer/tests/voice_test.py and this file, which have to contain the
#   characters they search for
#
# Patch files are checked on their added lines only. A context line is
# upstream Chromium's text and has to match the source byte for byte, so
# rewriting one would break the patch rather than fix the style.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
cd "$ROOT"

python3 - <<'PY'
import io
import re
import subprocess
import sys

EXEMPT_PREFIX = ("installer/bible/",)
EXEMPT_EXACT = ("installer/tests/voice_test.py", "ci/tests/house-style-test.sh")

# em dash, en dash, horizontal bar. The horizontal bar is here because it is
# what a text editor produces when somebody tries to avoid the other two.
BANNED = {"—": "em dash", "–": "en dash", "―": "horizontal bar"}

# Code that looks for these characters has to contain them, which is the same
# reason this file exempts itself above. Only a regex character class made of
# nothing but the banned characters is taken out of the line before it is
# read, so prose beside such a class is still caught.
DETECTOR = re.compile(r"\[[—–―]+\]")

listing = subprocess.run(
    ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
    check=True, stdout=subprocess.PIPE).stdout
paths = [p for p in listing.decode("utf-8").split("\0") if p]

problems = []
scanned = 0

for path in paths:
    if path.startswith(EXEMPT_PREFIX) or path in EXEMPT_EXACT:
        continue
    try:
        raw = io.open(path, "rb").read()
    except (IOError, OSError):
        continue
    # A NUL byte means binary. PNG and zip payloads carry these code points as
    # ordinary data and rewriting them would corrupt the file.
    if b"\0" in raw:
        continue
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        continue
    scanned += 1

    lines = text.split("\n")
    is_patch = path.startswith("patches/") and path.endswith(".patch")
    for number, line in enumerate(lines, 1):
        if is_patch:
            # Only what AuraDE adds. Context and removed lines belong to
            # upstream and must stay byte identical.
            if not line.startswith("+") or line.startswith("+++"):
                continue
        probe = DETECTOR.sub("", line)
        for char, name in BANNED.items():
            if char in probe:
                problems.append("%s:%d: %s in %s" % (path, number, name, line.strip()[:70]))
                break

if problems:
    for line in problems[:40]:
        print("  " + line, file=sys.stderr)
    if len(problems) > 40:
        print("  ... and %d more" % (len(problems) - 40), file=sys.stderr)
    print("house style test: %d dash(es) to replace" % len(problems), file=sys.stderr)
    sys.exit(1)

print("house style test: PASS (%d text files)" % scanned)
PY
