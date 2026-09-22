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
import re
import subprocess
import sys
import tempfile

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
        'for name in source sha256sums _module _test depends; do\n'
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
depends = recipe["depends"]

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
    needed = [line.split(" = ", 1)[1] for line in lines
              if line.startswith("depends = ")]
    check(needed == depends,
          "the dependencies in .SRCINFO are not the dependencies in the "
          "PKGBUILD")
else:
    FAILURES.append(".SRCINFO is missing, so the AUR has no recipe to read")

# -- what the modules import, the package has to pull in --------------------
#
# The failure at the top of this file, one level further out. `cairo` is
# pycairo, a package of its own, and the greeter paints the photograph and
# everything else it draws by hand with it. The live image lists it, so the
# installer drew its wallpapers and every screenshot looked right. An installed
# system never had it: the import failed inside a handler written to swallow
# exactly that, and the login screen came up on a flat colour with no
# photograph, on every machine, with nothing said anywhere. Read from the
# imports rather than kept as a list, so a new one fails here until the recipe
# names what provides it.
PROVIDERS = {"cairo": "python-cairo", "gi": "python-gobject"}
_imported: dict[str, str] = {}
for _file in sorted(os.listdir(MODULES)):
    if not _file.endswith(".py"):
        continue
    with open(os.path.join(MODULES, _file), encoding="utf-8") as handle:
        for _line in handle:
            _match = re.match(r"\s*(?:import|from)\s+([A-Za-z_]\w*)", _line)
            if _match and _match.group(1) in PROVIDERS:
                _imported.setdefault(_match.group(1), _file)
for _top, _file in sorted(_imported.items()):
    check(PROVIDERS[_top] in depends,
          f"{_file} imports {_top} and the recipe does not depend on "
          f"{PROVIDERS[_top]}, so on an installed system that import fails")
check("cairo" in _imported,
      "no module imports cairo, and brand.py paints the photograph with it. "
      "The scan has stopped seeing something.")

# -- the greeter cannot draw on a bare terminal -----------------------------
#
# greetd runs its command on a virtual terminal. A GTK4 program has no way to
# draw on one, so an `aurade.toml` pointing at `/usr/bin/aurade-greeter` gives
# a login screen that starts, finds no display, exits, and is restarted, on a
# machine whose only way in is the screen that is not appearing.
#
# That is exactly what the shipped example said to do until it was tried on
# real hardware. It is a one line mistake that reads as correct, so it gets an
# assertion rather than a comment.
_example = os.path.join(PACKAGE, "aurade.toml.example")
_wrapper = os.path.join(PACKAGE, "aurade-greeter-session")
if os.path.isfile(_example):
    with open(_example, encoding="utf-8") as handle:
        _config = handle.read()
    _command = ""
    for line in _config.splitlines():
        if line.strip().startswith("command"):
            _command = line.split("=", 1)[1].strip().strip('"')
    check(_command.endswith("aurade-greeter-session"),
          f"the example greetd config runs {_command!r}, which cannot draw "
          f"on a bare terminal and will loop forever")
else:
    FAILURES.append("aurade.toml.example is missing, so nobody is told how "
                    "to switch the greeter on")

if os.path.isfile(_wrapper):
    with open(_wrapper, encoding="utf-8") as handle:
        _lines = handle.read().splitlines()
    # Comments stripped, and that is the whole point of this being here. The
    # first version read the file whole, and the file explains in prose why it
    # starts weston and what it hands to the greeter. Deleting every line that
    # does the work left both words sitting in the commentary and both
    # assertions green.
    _script = "\n".join(line for line in _lines
                        if line.strip() and not line.lstrip().startswith("#"))
    check("weston" in _script,
          "the session wrapper starts no compositor, so the greeter it runs "
          "has nothing to draw on")
    check("/usr/bin/aurade-greeter" in _script,
          "the session wrapper starts a compositor and never runs the greeter")
    check("exec " in _script,
          "the wrapper does not exec, so greetd waits on a shell rather than "
          "on the compositor and cannot tell when the screen has gone")
else:
    FAILURES.append("aurade-greeter-session is missing, so the example config "
                    "names a file that is not there")

# -- a machine with no GPU still gets a login screen ------------------------
#
# The wrapper decides how weston draws before starting it. A render node this
# user can open means the usual renderer; none means pixman underneath and
# cairo in GTK, so a virtual machine with no 3D reaches a login screen instead
# of a compositor that fails and is restarted forever. Driven for real, with a
# stand-in weston that records what it was asked for, because a check on the
# text of the script passed for as long as the words were in its comments.
_WESTON_STUB = """#!/usr/bin/env bash
printf 'gsk=%s\\n' "${GSK_RENDERER:-unset}" >"${AURADE_TEST_WESTON_LOG:?}"
printf 'arg=%s\\n' "$@" >>"${AURADE_TEST_WESTON_LOG:?}"
"""


def _drive_wrapper(scratch: str, render_node: bool) -> str:
    stubs = os.path.join(scratch, "bin")
    os.makedirs(stubs, exist_ok=True)
    weston = os.path.join(stubs, "weston")
    with open(weston, "w", encoding="utf-8") as handle:
        handle.write(_WESTON_STUB)
    os.chmod(weston, 0o755)
    dri = os.path.join(scratch, "dri-gpu" if render_node else "dri-none")
    os.makedirs(dri, exist_ok=True)
    open(os.path.join(dri, "card0"), "w", encoding="utf-8").close()
    if render_node:
        open(os.path.join(dri, "renderD128"), "w", encoding="utf-8").close()
    log = os.path.join(scratch, "weston.log")
    if os.path.exists(log):
        os.unlink(log)
    env = {key: value for key, value in os.environ.items()
           if key not in ("GSK_RENDERER", "AURADE_WESTON_RENDERER",
                          "AURADE_FORCE_SOFTWARE_RENDERING")}
    env.update(PATH=stubs + os.pathsep + env.get("PATH", "/usr/bin:/bin"),
               AURADE_DRI_DIR=dri, AURADE_TEST_WESTON_LOG=log,
               XDG_RUNTIME_DIR=scratch)
    subprocess.run(["bash", _wrapper], env=env, check=False,
                   capture_output=True, timeout=30)
    if not os.path.isfile(log):
        return ""
    with open(log, encoding="utf-8") as handle:
        return handle.read()


if os.path.isfile(_wrapper):
    with tempfile.TemporaryDirectory() as _scratch:
        _plain = _drive_wrapper(_scratch, render_node=False)
        check("arg=--renderer=pixman" in _plain.splitlines(),
              "with no GPU render node the wrapper did not ask weston for "
              "pixman, so a machine with no 3D gets no login screen")
        check("gsk=cairo" in _plain.splitlines(),
              "with no GPU render node the greeter is not told to draw with "
              "cairo, so GTK goes looking for a GL it cannot have")
        _gpu = _drive_wrapper(_scratch, render_node=True)
        check("arg=--renderer=auto" in _gpu.splitlines(),
              "a machine with a usable GPU was given a software renderer")
        check("gsk=unset" in _gpu.splitlines(),
              "a machine with a usable GPU had the greeter forced to cairo")

# -- somewhere to write ----------------------------------------------------
#
# Every default path a module caches into has to sit in a directory this
# recipe creates. The weather and the location both wrote into
# `/var/cache/aurade`, which belongs to no package and is root owned, so on
# the machine every write failed silently: the forecast was refetched from
# nothing on every start and the location service was asked every time the
# greeter came up, which is the one thing its own test says must not happen.
#
# Invisible here, because every test passes its own path in, and invisible on
# the machine, because a cache that never writes just looks like a cold start.
# Every `/var` path any module names, however it names it. The first version
# of this looked for `os.environ.get("AURADE_...", "/var/...")` and found two
# of the three, because `accounts.py` wraps its default in a helper. A scan
# that quietly covers less than it claims is the same defect as the bug it is
# here to catch.
_wanted: dict[str, str] = {}
for _name in sorted(os.listdir(MODULES)):
    if not _name.endswith(".py"):
        continue
    with open(os.path.join(MODULES, _name), encoding="utf-8") as _handle:
        _body = _handle.read()
    for _default in re.findall(r'"(/var/[^"]+)"', _body):
        _wanted[_default] = _name

with open(RECIPE, encoding="utf-8") as _handle:
    _recipe = _handle.read()
_made = set(re.findall(r'install -dm?[0-7]*\s+"\$\{pkgdir\}(/var/[^"]+)"',
                       _recipe))
check(_wanted, "no module names a path under /var any more, so this check is "
               "guarding something that is not there")
#: Paths under /var that belong to somebody else and are only ever read.
#:
#: Named one at a time rather than filtered by a pattern, so that a write path
#: cannot be exempted by accident. Adding to this list should cost somebody an
#: argument about whether the greeter really has no business creating it.
FOREIGN = (
    "/var/lib/AccountsService/icons",   # accountsservice, read for avatars
    "/var/lib/AccountsService/users",   # accountsservice, read for real names
)

_wanted = {path: name for path, name in _wanted.items() if path not in FOREIGN}

check(len(_wanted) >= 3,
      f"only {len(_wanted)} paths under /var were found across the modules, "
      f"and there are at least three: the account list's state file and the "
      f"two caches. The scan has stopped seeing something.")
for _named, _name in sorted(_wanted.items()):
    # Either the path is a directory the recipe makes, or its parent is.
    check(_named in _made or os.path.dirname(_named) in _made,
          f"{_name} writes to {_named} and the recipe creates neither it nor "
          f"{os.path.dirname(_named)}, so on a machine that write fails as "
          f"the greeter user and nothing anywhere says so")

check("aurade-greeter-session" in source,
      "the session wrapper is not in the recipe's sources, so it is not in "
      "the package and the example config names nothing")

if FAILURES:
    for failure in FAILURES:
        print(f"greeter-packaging: {failure}", file=sys.stderr)
    sys.exit(1)
print(f"greeter packaging test: PASS ({len(module)} modules, {len(tests)} tests, "
      f"{len(source)} sources checksummed)")
