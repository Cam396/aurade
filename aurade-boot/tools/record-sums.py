#!/usr/bin/env python3
"""Re-record this package's checksums, in the PKGBUILD and in `.SRCINFO`.

The greeter's tool does exactly this for the greeter, so this runs that one
against this directory rather than keeping a second copy of it.

    aurade-boot/tools/record-sums.py            # rewrite both files
    aurade-boot/tools/record-sums.py --check    # say what is stale, write nothing
"""
from __future__ import annotations

import importlib.util
import os

HERE = os.path.dirname(os.path.realpath(__file__))
PACKAGE = os.path.normpath(os.path.join(HERE, ".."))
GREETER_TOOL = os.path.join(PACKAGE, "..", "aurade-greeter", "tools", "record-sums.py")

spec = importlib.util.spec_from_file_location("record_sums", GREETER_TOOL)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
tool.PACKAGE = PACKAGE
tool.PKGBUILD = os.path.join(PACKAGE, "PKGBUILD")
tool.SRCINFO = os.path.join(PACKAGE, ".SRCINFO")

if __name__ == "__main__":
    raise SystemExit(tool.main())
