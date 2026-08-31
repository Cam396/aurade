"""What this computer can sign you in to.

Almost every AuraDE machine has exactly one answer, and on those machines the
picker never appears. It exists for the machine that has two, and for the
machine whose AuraDE session is broken and whose owner needs the fallback that
is sitting right there in the same directory.

Desktop entry parsing only, no toolkit, so the rules can be tested against a
fixture directory.
"""

from __future__ import annotations

import os
import shlex
import shutil
from typing import Iterable

#: Where Wayland session entries live, and the AuraDE session's own file name.
SESSION_DIR = "/usr/share/wayland-sessions"
PREFERRED = "chromiumos-ash-wayland.desktop"

#: Field codes a desktop entry Exec line may carry. None of them mean anything
#: to a session, and passing a literal "%U" to a compositor starts nothing.
FIELD_CODES = frozenset({"%f", "%F", "%u", "%U", "%d", "%D", "%n", "%N",
                         "%i", "%c", "%k", "%v", "%m"})


class Session:
    """One thing greetd can be asked to start."""

    __slots__ = ("ident", "name", "comment", "command")

    def __init__(self, ident: str, name: str, comment: str,
                 command: list[str]) -> None:
        self.ident = ident
        self.name = name
        self.comment = comment
        self.command = command

    def __repr__(self) -> str:  # pragma: no cover - debugging only
        return f"Session({self.ident!r}, {self.command!r})"

    def __eq__(self, other: object) -> bool:
        return (isinstance(other, Session) and other.ident == self.ident
                and other.command == self.command)


def _entries(directory: str) -> Iterable[tuple[str, dict[str, str]]]:
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return
    for name in names:
        if not name.endswith(".desktop"):
            continue
        try:
            with open(os.path.join(directory, name), "r",
                      encoding="utf-8", errors="replace") as handle:
                yield name, _parse(handle)
        except OSError:
            continue


def _parse(lines: Iterable[str]) -> dict[str, str]:
    """The Desktop Entry group only.

    Anything after a second group header is somebody else's business, and a
    key from an action group is not the session's Exec line.
    """
    values: dict[str, str] = {}
    inside = False
    for line in lines:
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            inside = line == "[Desktop Entry]"
            continue
        if not inside or not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator:
            continue
        key = key.strip()
        if key in values:
            continue
        values[key] = value.strip()
    return values


def _command(exec_line: str) -> list[str]:
    """The Exec line as an argument list, with field codes dropped."""
    try:
        parts = shlex.split(exec_line)
    except ValueError:
        return []
    return [part for part in parts if part not in FIELD_CODES]


def _usable(values: dict[str, str]) -> bool:
    if values.get("Hidden", "").lower() == "true":
        return False
    if values.get("NoDisplay", "").lower() == "true":
        return False
    try_exec = values.get("TryExec", "")
    if try_exec and shutil.which(try_exec) is None and not os.access(try_exec, os.X_OK):
        return False
    return bool(values.get("Exec"))


def sessions(directory: str | None = None) -> list[Session]:
    """Everything startable, AuraDE first.

    The preferred entry leads because on a machine with a fallback installed
    the AuraDE session is still the one somebody means when they press sign in
    without looking at the picker.
    """
    directory = directory or os.environ.get(
        "AURADE_GREETER_SESSION_DIR") or SESSION_DIR
    found: list[Session] = []
    for name, values in _entries(directory):
        if not _usable(values):
            continue
        command = _command(values.get("Exec", ""))
        if not command:
            continue
        found.append(Session(name, values.get("Name") or name.removesuffix(".desktop"),
                             values.get("Comment", ""), command))
    found.sort(key=lambda session: (session.ident != PREFERRED,
                                    session.name.lower()))
    return found


def wrapped(command: list[str], wrapper: str | None = None) -> list[str]:
    """The session command as greetd should be given it.

    The supervisor is what lets a session restart as a unit instead of leaving
    a half dead compositor behind, so it belongs in front of every session the
    greeter starts, not only the AuraDE one.
    """
    wrapper = wrapper if wrapper is not None else os.environ.get(
        "AURADE_GREETER_WRAPPER", "/usr/bin/aurade-session-supervisor")
    if not wrapper:
        return list(command)
    return [wrapper, *command]
