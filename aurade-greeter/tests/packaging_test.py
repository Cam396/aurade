#!/usr/bin/env python3
"""Everything in the source tree is in the package, and is what the package says.

This test exists because of a real failure, and the failure is worth stating.

A pass added two modules to `aurade_greeter/`, wired them into `app.py`, and
watched every suite go green, because the suites import from the source tree.
Neither module was added to the PKGBUILD. A package built from that commit
would have installed a greeter whose first import fails, and the symptom is a
machine that boots to a black screen with no login prompt on it. Nothing in
the repository could have noticed: the tests ran against the tree, and the
tree was fine.

So this compares the two lists that must never disagree. It is deliberately
mechanical. There is no judgement in it and there is nothing to keep up to
date: a new module in the directory is a failure until it is in the package.

It skips, loudly, when run from inside a build. `check()` stages the flat
sources into the shape the package imports and runs the suite there, and that
staged tree has no PKGBUILD in it, because a package cannot contain the recipe
that built it. A skip that says so is not the same as a pass.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
PACKAGE = os.path.normpath(os.path.join(HERE, ".."))
RECIPE = os.path.join(PACKAGE, "PKGBUILD")
SRCINFO = os.path.join(PACKAGE, ".SRCINFO")
MODULES = os.path.join(PACKAGE, "aurade_greeter")

FAILURES: list[str] = []


def check(ok: bool, message: str) -> None:
    if not ok:
        FAILURES.append(message)


if not os.path.isfile(RECIPE) or not os.path.isdir(MODULES):
    print("greeter packaging test: SKIP (no PKGBUILD here, this is a build tree)")
    raise SystemExit(0)


def arrays() -> dict[str, list[str]]:
    """The recipe's own lists, read by the shell that will read them for real.

    Parsing a PKGBUILD with a regular expression means writing a second, worse
    bash. It is a shell script, so it is sourced by a shell.
    """
    script = (
        "source ./PKGBUILD\n"
        'for name in source sha256sums _module _test; do\n'
        '  declare -n array="$name"\n'
        '  printf "%s\\n" "@@${name}"\n'
        '  printf "%s\\n" "${array[@]}"\n'
        "done\n"
    )
    out = subprocess.run(["bash", "-c", script], cwd=PACKAGE,
                         capture_output=True, text=True, check=True).stdout
    found: dict[str, list[str]] = {}
    key = ""
    for line in out.splitlines():
        if line.startswith("@@"):
            key = line[2:]
            found[key] = []
        elif key:
            found[key].append(line)
    return found


recipe = arrays()
source = recipe["source"]
sums = recipe["sha256sums"]
module = recipe["_module"]
tests = recipe["_test"]

# The two arrays are read in step, so a file added to one and not the other
# silently shifts every checksum after it onto the wrong file.
check(len(source) == len(sums),
      f"the recipe lists {len(source)} sources and {len(sums)} checksums")

# Everything the greeter imports has to be installed. This is the check that
# would have caught the failure this file was written for.
present = sorted(name for name in os.listdir(MODULES)
                 if name.endswith((".py", ".css")))
missing = [name for name in present if name not in module]
check(not missing,
      f"the package does not install these, so importing them will fail: {missing}")
phantom = [name for name in module if not os.path.isfile(os.path.join(MODULES, name))]
check(not phantom, f"the package installs files that do not exist: {phantom}")
check(len(module) == len(set(module)), "a module is listed twice")

# And everything the check step runs.
suite = sorted(name for name in os.listdir(HERE)
               if name.endswith("_test.py") or name == "test-runtime.sh")
absent = [name for name in suite if name not in tests]
check(not absent,
      f"these tests are in the tree and not in the package's check step: {absent}")

# Every name in `source` has to be reachable from the top level, because
# makepkg resolves a local source to its basename and the repository keeps the
# real tree one directory down behind symlinks.
for name in source:
    path = os.path.join(PACKAGE, name)
    check(os.path.exists(path),
          f"{name} is a source and nothing at the top level resolves to it")

for name in module + tests:
    check(name in source, f"{name} is installed and is not a source")

# The checksums have to be of the files that are actually there. A stale one
# stops the build with a message about corruption, which sends whoever reads
# it looking for a download that never happened.
for name, digest in zip(source, sums):
    path = os.path.join(PACKAGE, name)
    if not os.path.isfile(path):
        continue
    with open(path, "rb") as handle:
        actual = hashlib.sha256(handle.read()).hexdigest()
    check(actual == digest,
          f"the recorded checksum for {name} is not the checksum of {name}")

# `.SRCINFO` is generated from the PKGBUILD and is what the AUR reads. The two
# drifting apart means the published recipe is not this one.
if os.path.isfile(SRCINFO):
    with open(SRCINFO, encoding="utf-8") as handle:
        lines = [line.strip() for line in handle]
    listed = [line.split(" = ", 1)[1] for line in lines
              if line.startswith("source = ")]
    recorded = [line.split(" = ", 1)[1] for line in lines
                if line.startswith("sha256sums = ")]
    check(listed == source,
          "the sources in .SRCINFO are not the sources in the PKGBUILD")
    check(recorded == sums,
          "the checksums in .SRCINFO are not the checksums in the PKGBUILD")
else:
    FAILURES.append(".SRCINFO is missing, so the AUR has no recipe to read")

if FAILURES:
    for failure in FAILURES:
        print(f"greeter-packaging: {failure}", file=sys.stderr)
    sys.exit(1)
print(f"greeter packaging test: PASS ({len(module)} modules, {len(tests)} tests, "
      f"{len(source)} sources checksummed)")
