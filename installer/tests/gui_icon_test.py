"""Every icon the installer asks for, against the ones the image carries.

An icon name GTK cannot resolve is not an error and not a placeholder: the
widget draws nothing, sizes itself as if nothing were there, and the page looks
like it was designed without an icon. Nothing in the build fails, and nothing
in a headless render fails either, because the build host has an icon theme of
its own and it is not the theme on the image.

That is not hypothetical. The readiness page shipped with `emblem-ok-symbolic`
on all five checks and on the verdict badge. Adwaita retired that name; the
image has no such icon; the build host, an older distribution, does. So every
tick was invisible on real hardware and correct in every screenshot taken here.

This reads the names straight out of the widget layer's source rather than
importing it, because it must run on a machine with no GTK at all.
"""

from __future__ import annotations

import os
import re
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                     "..", ".."))
GUI = os.path.join(ROOT, "installer", "lib", "aurade_gui")
SHIPPED = os.path.join(ROOT, "installer", "tests", "fixtures",
                       "image-symbolic-icons.txt")

#: Any string literal that looks like an icon name. Deliberately wider than the
#: calls that take one: a name held in a dict, a tuple or a constant is still a
#: name that has to resolve, and those are where the retired one was hiding.
NAME = re.compile(r'"([a-z][a-z0-9]*(?:-[a-z0-9+]+)*-symbolic)"')


def shipped_names() -> set[str]:
    names = set()
    with open(SHIPPED) as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#"):
                names.add(line)
    return names


def used_names() -> dict[str, list[str]]:
    used: dict[str, list[str]] = {}
    for entry in sorted(os.listdir(GUI)):
        if not entry.endswith(".py"):
            continue
        path = os.path.join(GUI, entry)
        with open(path) as handle:
            for number, line in enumerate(handle, 1):
                for name in NAME.findall(line):
                    used.setdefault(name, []).append(f"{entry}:{number}")
    return used


def main() -> int:
    shipped = shipped_names()
    if len(shipped) < 100:
        print("installer GUI icon test: SKIP (no icon list to check against)")
        return 0

    used = used_names()
    if not used:
        print("test-gui-icons: the widget layer asks for no icons at all; "
              "either this test stopped finding them or the pages lost them",
              file=sys.stderr)
        return 1

    missing = {name: where for name, where in used.items() if name not in shipped}
    for name, where in sorted(missing.items()):
        print(f"test-gui-icons: {name} is not on the image, so it will draw "
              f"nothing ({', '.join(where)})", file=sys.stderr)
    if missing:
        return 1

    print(f"installer GUI icon test: PASS ({len(used)} icon names, all on the image)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
