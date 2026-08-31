#!/usr/bin/env python3
"""Re-record the PKGBUILD checksums, and the copies of them in `.SRCINFO`.

Editing a source file makes its recorded digest wrong, and a wrong digest does
not fail with "you changed this file". It fails during the build with a message
about corruption, which sends whoever reads it looking for a bad download that
never happened. `packaging_test.py` catches it first, which is the point of
that test, but the fix was still twenty five hex strings edited by hand across
two files that have to agree, and that is how the digests went stale the last
time.

    aurade-greeter/tools/record-sums.py            # rewrite both files
    aurade-greeter/tools/record-sums.py --check    # say what is stale, write nothing
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
PACKAGE = os.path.normpath(os.path.join(HERE, ".."))
PKGBUILD = os.path.join(PACKAGE, "PKGBUILD")
SRCINFO = os.path.join(PACKAGE, ".SRCINFO")

ARRAY = re.compile(r"^(?P<name>source|sha256sums)=\((?P<body>.*?)\)$",
                   re.MULTILINE | re.DOTALL)


def read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def sources(text: str) -> list[str]:
    found = [m for m in ARRAY.finditer(text) if m.group("name") == "source"]
    if len(found) != 1:
        raise SystemExit("record-sums: the PKGBUILD has no single source array")
    return re.findall(r"'([^']+)'", found[0].group("body"))


def digest(name: str) -> str:
    """The digest of the file, or `SKIP` for anything not on disk.

    A source that is not a local file is not ours to checksum, and makepkg
    reads `SKIP` as exactly that rather than as a failure.
    """
    path = os.path.join(PACKAGE, name)
    if not os.path.isfile(path):
        return "SKIP"
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def rewrite(text: str, sums: list[str]) -> str:
    """The sums array, indented to sit under its own opening the way it does."""
    pad = " " * len("sha256sums=(")
    body = ("\n" + pad).join(f"'{s}'" for s in sums)

    def swap(match: re.Match) -> str:
        if match.group("name") != "sha256sums":
            return match.group(0)
        return f"sha256sums=({body})"

    return ARRAY.sub(swap, text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="report what is stale and write nothing")
    args = parser.parse_args()

    text = read(PKGBUILD)
    names = sources(text)
    wanted = [digest(name) for name in names]

    have = [m for m in ARRAY.finditer(text) if m.group("name") == "sha256sums"]
    current = re.findall(r"'([^']+)'", have[0].group("body")) if have else []
    stale = [n for n, a, b in zip(names, current + [""] * len(names), wanted)
             if a != b]

    if args.check:
        for name in stale:
            print(f"stale: {name}")
        print(f"{len(stale)} of {len(names)} recorded digests are stale")
        return 1 if stale else 0

    with open(PKGBUILD, "w", encoding="utf-8") as handle:
        handle.write(rewrite(text, wanted))

    # `.SRCINFO` is generated from the PKGBUILD and is what the AUR reads, so
    # its copy of the digests is rewritten in place rather than regenerated:
    # makepkg refuses to run as root, which is how this machine builds.
    if os.path.isfile(SRCINFO):
        lines = read(SRCINFO).splitlines(keepends=True)
        out, seen = [], 0
        for line in lines:
            if line.strip().startswith("sha256sums = ") and seen < len(wanted):
                lead = line[:len(line) - len(line.lstrip())]
                out.append(f"{lead}sha256sums = {wanted[seen]}\n")
                seen += 1
            else:
                out.append(line)
        if seen != len(wanted):
            print(f"record-sums: .SRCINFO lists {seen} digests and the "
                  f"PKGBUILD has {len(wanted)}", file=sys.stderr)
            return 2
        with open(SRCINFO, "w", encoding="utf-8") as handle:
            handle.writelines(out)

    print(f"record-sums: {len(stale)} rewritten, {len(names)} recorded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
