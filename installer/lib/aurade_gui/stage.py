"""Record how far the graphical installer got.

The launcher uses the result to decide whether another graphics candidate can
be tried. This module stays on the standard library path so it also works when
the GUI toolkit failed to load.
"""

from __future__ import annotations

import os

MAPPED = "mapped"
ENGAGED = "engaged"
DECLINED = "declined"
QUIT = "quit"


def report(stage: str) -> None:
    path = os.environ.get("AURADE_GUI_READY_FILE")
    if not path:
        return
    try:
        with open(path, "w") as handle:
            handle.write(f"{stage}\n")
    except OSError:
        # Not being able to say so is not a reason to fail to start. The
        # launcher treats a missing file as "try the next candidate", which at
        # worst costs one extra attempt.
        pass


def launcher_managed() -> bool:
    """Whether a launcher started a compositor for this process.

    When it did, this process is inside `cage` with no terminal behind it, and
    handing over to the text installer here would run it on a console nobody
    can see. The launcher owns that console and starts the text installer on
    it; all this process has to do is say why.
    """
    return bool(os.environ.get("AURADE_GUI_READY_FILE"))
