"""When the installer is allowed to say something out loud.

This is the file that ended the process on every machine for a week, and the
shape of the mistake is worth keeping in front of whoever reads it next.

`gtk_accessible_announce` hands a sentence to an assistive technology over the
session bus. On this installer's live image there is no session bus: the
compositor is started by a systemd oneshot with no login session behind it.
Calling it anyway segfaults, and a segfault is not an exception, so the `try`
that wraps it caught nothing at all:

    Fatal Python error: Segmentation fault
      File "aurade_gui/a11y.py", line 113 in announce
      File "aurade_gui/app.py", line 3431 in _announce_page
      File "aurade_gui/app.py", line 3443 in refresh
      File "aurade_gui/app.py", line 3745 in on_forward

`_announce_page` runs on every page change, so pressing Get started ended the
installer. The module's own docstring promised it degrades to a no-op rather
than raising, and it was telling the truth: it never raised.

The decision is tested without importing GTK, because the machine the image is
built on does not have the toolkit and a check that does not run is not a
check. The rule is small enough to be worth stating in one place and reading in
another.
"""

from __future__ import annotations

import os
import re
import sys

TESTS = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.normpath(os.path.join(TESTS, "..", ".."))
SOURCE = os.path.join(ROOT, "installer", "lib", "aurade_gui", "a11y.py")

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


source = open(SOURCE, encoding="utf-8").read()

# The rule, lifted out of the module and run on its own. Rewriting it here
# would let the two drift, so it is executed from the file itself.
namespace: dict = {"os": os}
match = re.search(r"def _can_announce\(\) -> bool:.*?(?=\n\n\n|\nCAN_ANNOUNCE)",
                  source, re.S)
check(match is not None, "a11y.py no longer has a _can_announce to check")
if match:
    body = match.group(0)
    # The one line that needs the toolkit, replaced by the answer it gives on
    # an image new enough to have the method at all. Everything else about the
    # decision is environment and is what this is testing.
    body = body.replace('if not hasattr(Gtk.Accessible, "announce"):\n        return False',
                        "pass")
    exec(body, namespace)  # noqa: S102 - the file under test, by design
    can = namespace["_can_announce"]

    original = dict(os.environ)
    try:
        for name in ("AURADE_ANNOUNCE", "GTK_A11Y",
                     "AT_SPI_BUS_ADDRESS", "DBUS_SESSION_BUS_ADDRESS"):
            os.environ.pop(name, None)

        # The live image: a compositor with no session behind it. This is the
        # case that was crashing and it is the default case, not a corner.
        check(not can(), "with nothing listening the installer would still announce, "
                         "which is the segfault this file exists for")

        # A desktop with an accessibility bus. The whole point of announcing.
        os.environ["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/run/user/1000/bus"
        check(can(), "with a session bus present the installer stays silent, "
                     "which loses the running commentary for the person it is for")

        os.environ.pop("DBUS_SESSION_BUS_ADDRESS")
        os.environ["AT_SPI_BUS_ADDRESS"] = "unix:path=/run/at-spi"
        check(can(), "an accessibility bus named directly was not believed")

        # Turned off explicitly beats any amount of bus.
        os.environ["GTK_A11Y"] = "none"
        check(not can(), "GTK_A11Y=none was ignored")
        os.environ.pop("GTK_A11Y")

        # And the override works in both directions, which is what makes this
        # reproducible on a machine where it does not happen.
        os.environ["AURADE_ANNOUNCE"] = "0"
        check(not can(), "AURADE_ANNOUNCE=0 did not silence it")
        os.environ.pop("AT_SPI_BUS_ADDRESS")
        os.environ["AURADE_ANNOUNCE"] = "1"
        check(can(), "AURADE_ANNOUNCE=1 did not force it on with no bus present")
    finally:
        os.environ.clear()
        os.environ.update(original)

# The call itself stays wrapped, because a version of GTK that raises rather
# than crashing is still a version this has to survive.
check("def announce(" in source, "announce is gone")
announce_body = source[source.index("def announce("):]
check("except Exception" in announce_body,
      "the announcement is no longer wrapped, and an older GTK raises here")
check("if not CAN_ANNOUNCE" in announce_body,
      "announce no longer consults CAN_ANNOUNCE, so the gate above does nothing")

if FAILURES:
    for failure in FAILURES:
        print(f"a11y announce test: {failure}", file=sys.stderr)
    sys.exit(1)
print("accessibility announcement test: PASS")
