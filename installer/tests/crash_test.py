"""The installer writes down how it died.

The graphical installer runs inside a compositor the launcher started, and when
it stops the launcher hands over to the text installer, which clears the
screen. So the evidence for a crash existed for about a second and then did
not, and what the person in front of the machine remembers is that the
installer vanished. That happened, and it cost two boots to work around.

Three deaths are checked, because they are genuinely different and the first
two leave nothing at all by default:

  an exception inside a GTK signal handler, which PyGObject prints and
  swallows, so the program carries on with half a screen from before it;

  a crash in the graphics stack, which is a signal and not an exception, and
  which Python answers by being gone;

  an ordinary uncaught exception.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
GUI = os.path.join(HERE, "..", "bin", "aurade-installer-gui")

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


# The entry point has no `.py` on it, so it has to be loaded by naming the
# loader rather than by letting importlib guess from the extension.
PRELUDE = f"""
import importlib.util, os, sys
from importlib.machinery import SourceFileLoader
os.environ["AURADE_GUI_CRASH_LOG"] = {{log!r}}
loader = SourceFileLoader("gui_entry", {GUI!r})
spec = importlib.util.spec_from_loader("gui_entry", loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)
module.record_crashes()
"""


def run(body: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as tmp:
        log = os.path.join(tmp, "crash.log")
        script = PRELUDE.format(log=log) + body
        proc = subprocess.run([sys.executable, "-c", script],
                              capture_output=True, text=True)
        written = ""
        if os.path.exists(log):
            with open(log) as handle:
                written = handle.read()
        return proc.returncode, written


# An uncaught exception. The traceback goes to the log and to stderr, because
# the log is for whoever is diagnosing and stderr is for the attempt log the
# launcher already keeps.
status, written = run("raise RuntimeError('the readiness page fell over')\n")
check(status != 0, "an uncaught exception did not fail the process")
check("the readiness page fell over" in written,
      f"an uncaught exception was not written down: {written!r}")
check("RuntimeError" in written,
      f"the crash log does not name the kind of failure: {written!r}")

# A segmentation fault, which is what a graphics driver taking the process
# down actually looks like. Not an exception, so only faulthandler catches it.
status, written = run(
    "import ctypes\n"
    "ctypes.string_at(0)\n")
check(status != 0, "a segmentation fault did not fail the process")
check("Fatal Python error" in written or "Segmentation fault" in written,
      f"a segmentation fault left nothing in the crash log: {written!r}")
check("ctypes" in written or "string_at" in written,
      f"the crash log does not say where the fault happened: {written!r}")

# An exception raised where PyGObject swallows it. `sys.unraisablehook` is the
# route Python gives those, and without it the installer carries on in a state
# that is half from before the exception, on a console about to be cleared.
status, written = run(
    "class Boom:\n"
    "    def __del__(self):\n"
    "        raise ValueError('the swoop never finished')\n"
    "b = Boom()\n"
    "del b\n")
check("the swoop never finished" in written,
      f"an exception Python could not raise was not written down: {written!r}")
check("unraisable" in written,
      f"the crash log does not distinguish a swallowed exception: {written!r}")

# A log that cannot be opened is not a reason to fail to start. An installer
# that refuses to run because it has nowhere to record a crash it has not had
# is worse than one that has the crash.
status, written = run("print('still running')\n")
check(status == 0, "a clean run was reported as a failure")

with tempfile.TemporaryDirectory() as _tmp:
    _unwritable = os.path.join(_tmp, "nowhere", "crash.log")
    _script = PRELUDE.format(log=_unwritable) + "print('started anyway')\n"
    _proc = subprocess.run([sys.executable, "-c", _script],
                           capture_output=True, text=True)
    check(_proc.returncode == 0,
          f"an unwritable crash log stopped the installer: {_proc.stderr!r}")
    check("started anyway" in _proc.stdout,
          "an unwritable crash log stopped the installer from starting")

if FAILURES:
    for line in FAILURES:
        print(f"crash test: {line}", file=sys.stderr)
    sys.exit(1)
print("installer crash recording test: PASS")
