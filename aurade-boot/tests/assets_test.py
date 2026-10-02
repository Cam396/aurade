#!/usr/bin/env python3
"""The theme's three sources of truth agree: the generator, the script, and
the drawn archive.

The generator holds the layout and the photograph list and writes them into
the script; the archive holds what the generator drew. A change to one that
is not carried to the others is a screen that loads an image that is not
there, or lays out a field at a size it was not drawn at, and plymouth says
nothing about either. It just shows less.

Standard library only: PIL is stubbed for the import, because nothing here
draws, and the sizes are read straight from each PNG's header.
"""

from __future__ import annotations

import importlib.util
import os
import re
import struct
import sys
import tarfile
import types

HERE = os.path.dirname(os.path.realpath(__file__))
PACKAGE = os.path.normpath(os.path.join(HERE, ".."))
REPO = os.path.normpath(os.path.join(PACKAGE, ".."))
SCRIPT = os.path.join(PACKAGE, "theme", "aurade-boot.script")
ARCHIVE = os.path.join(PACKAGE, "aurade-boot-drawn.tar")
PHOTOS_LIST = os.path.join(PACKAGE, "theme", "photos.list")

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


class _Nothing(types.SimpleNamespace):
    """Stands in for a PIL module: any attribute, all of them unused here."""

    def __getattr__(self, name: str) -> None:
        return None


def generator():
    pil = types.ModuleType("PIL")
    for name in ("Image", "ImageChops", "ImageDraw", "ImageFilter"):
        setattr(pil, name, _Nothing())
    sys.modules.setdefault("PIL", pil)
    spec = importlib.util.spec_from_file_location(
        "build_assets", os.path.join(PACKAGE, "tools", "build-assets.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def png_size(data: bytes) -> tuple[int, int]:
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError("not a PNG")
    return struct.unpack(">II", data[16:24])


def main() -> int:
    gen = generator()
    with open(SCRIPT, encoding="utf-8") as handle:
        script = handle.read()

    # The generated block is what the generator writes today.
    block = re.search(r"# BEGIN GENERATED.*?# END GENERATED", script, re.S)
    check(block is not None, "the script has no generated block")
    if block:
        check(block.group(0) == gen.generated_block(),
              "the script's generated block is stale: run tools/build-assets.py")

    # photos.list is the generator's list, and every photograph exists and has
    # a caption to draw from.
    with open(PHOTOS_LIST, encoding="utf-8") as handle:
        listed = [line.strip() for line in handle
                  if line.strip() and not line.startswith("#")]
    check(listed == [name for name, _, _ in gen.PHOTOS],
          "photos.list is not the generator's photograph list")
    # What the theme's links point at is what the wallpaper package installs,
    # and its manifest is the list of that.
    with open(os.path.join(REPO, "aurade-wallpapers", "manifest.tsv"), encoding="utf-8") as handle:
        installed = {line.split("\t", 1)[0] for line in handle
                     if line.strip() and not line.startswith("#")}
    titles = gen.titles()
    for name in listed:
        check(f"{name}.png" in installed,
              f"{name}.png is not in the wallpaper package, so its slot links to nothing")
        check(name in titles, f"no caption for {name} in titles.tsv")

    # Every image the script asks for, at every size, is in the archive.
    with tarfile.open(ARCHIVE) as archive:
        members = {m.name: m for m in archive.getmembers() if m.isfile()}
        for root in ("shade.png", "pool.png"):
            check(root in members, f"the archive has no {root}")
        names = set(re.findall(r'asset\("([a-z0-9-]+\.png)"\)', script))
        names |= {f"caption-{i}.png" for i in range(len(gen.PHOTOS))}
        check(len(names) > 15, "the script asks for suspiciously few images")
        for s in gen.SCALES:
            folder = gen.scale_dir(s)
            for name in sorted(names):
                check(f"{folder}/{name}" in members, f"{folder}/{name} is not in the archive")

            def size(name: str) -> tuple[int, int]:
                return png_size(archive.extractfile(members[f"{folder}/{name}"]).read(24))

            L = gen.LAYOUT
            if f"{folder}/dot.png" in members:
                check(size("dot.png") == (gen.px(L["dot"], s),) * 2,
                      f"{folder}/dot.png is not {L['dot']} at {s}")
            for state in ("idle", "focus", "ready", "error"):
                name = f"field-{state}.png"
                if f"{folder}/{name}" in members:
                    want = (gen.px(L["field_w"] + 2 * L["field_pad"], s),
                            gen.px(L["field_h"] + 2 * L["field_pad"], s))
                    check(size(name) == want, f"{folder}/{name} is {size(name)}, not {want}")
            if f"{folder}/mark.png" in members:
                want = (gen.px(L["mark"] + 2 * L["mark_pad"], s),) * 2
                check(size("mark.png") == want, f"{folder}/mark.png is not {want}")
        # Nothing in the archive that nothing asks for.
        expected = {"shade.png", "pool.png"} | {
            f"{gen.scale_dir(s)}/{name}" for s in gen.SCALES for name in names}
        for extra in sorted(set(members) - expected):
            check(False, f"the archive carries {extra}, which the script never loads")

    # The script and the hook agree on the drawn sizes' names.
    hook = open(os.path.join(PACKAGE, "initcpio", "install", "aurade-boot"), encoding="utf-8").read()
    check("s100" in hook, "the hook no longer keeps 1x for a firmware framebuffer")

    if FAILURES:
        for failure in FAILURES:
            print(f"assets test: {failure}", file=sys.stderr)
        return 1
    print(f"aurade-boot assets test: PASS ({len(gen.SCALES)} sizes, {len(gen.PHOTOS)} photographs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
