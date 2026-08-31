#!/usr/bin/env python3
"""What this computer offers to sign you in to.

Most AuraDE machines have one answer and never show the picker. The picker
exists for the machine whose AuraDE session will not start, whose owner needs
the fallback that is sitting in the same directory and has no terminal to
reach it from. So the rules that decide what appears in that list are the
rules that decide whether a broken machine is recoverable without a keyboard
shortcut nobody remembers.
"""

from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), ".."))
sys.path.insert(0, ROOT)

from aurade_greeter import sessions as S  # noqa: E402

FAILURES: list[str] = []

AURADE = """\
[Desktop Entry]
Name=AuraDE
Comment=The AuraDE desktop
Exec=/usr/bin/chromiumos-ash-session %U
Type=Application
"""

WESTON = """\
[Desktop Entry]
Name=Alternative desktop
Exec=/usr/bin/weston
Type=Application
"""

HIDDEN = """\
[Desktop Entry]
Name=Old session
Exec=/usr/bin/old-session
Hidden=true
Type=Application
"""

NO_DISPLAY = """\
[Desktop Entry]
Name=Internal
Exec=/usr/bin/internal
NoDisplay=true
Type=Application
"""

ACTIONS = """\
[Desktop Entry]
Name=With actions
Exec=/usr/bin/real-session
Type=Application
Actions=safe;

[Desktop Action safe]
Name=Safe mode
Exec=/usr/bin/wrong-session --safe
TryExec=/usr/bin/definitely-not-installed-anywhere
"""

DUPLICATE = """\
[Desktop Entry]
Name=Duplicated
Exec=/usr/bin/real-session
Exec=/usr/bin/wrong-session
Type=Application
"""

NO_EXEC = """\
[Desktop Entry]
Name=Broken
Type=Application
"""

MISSING_BINARY = """\
[Desktop Entry]
Name=Not installed
Exec=/usr/bin/absent-session
TryExec=/usr/bin/absent-session-binary-that-is-not-here
Type=Application
"""


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


class Fixture:
    def __init__(self, entries: dict[str, str]) -> None:
        self.dir = tempfile.TemporaryDirectory()
        for name, body in entries.items():
            with open(os.path.join(self.dir.name, name), "w",
                      encoding="utf-8") as handle:
                handle.write(body)
        self.saved = os.environ.get("AURADE_GREETER_SESSION_DIR")
        os.environ["AURADE_GREETER_SESSION_DIR"] = self.dir.name

    def close(self) -> None:
        if self.saved is None:
            os.environ.pop("AURADE_GREETER_SESSION_DIR", None)
        else:
            os.environ["AURADE_GREETER_SESSION_DIR"] = self.saved
        self.dir.cleanup()


def test_aurade_leads_whatever_it_is_called() -> None:
    """Alphabetical order would put AuraDE behind anything starting with A."""
    fixture = Fixture({"chromiumos-ash-wayland.desktop": AURADE,
                       "aaa-weston.desktop": WESTON})
    try:
        found = S.sessions()
        check([session.ident for session in found] ==
              ["chromiumos-ash-wayland.desktop", "aaa-weston.desktop"],
              "the AuraDE session is not the first thing offered")
        check(found[0].name == "AuraDE",
              "the session picker shows a file name rather than a name")
    finally:
        fixture.close()


def test_field_codes_never_reach_the_compositor() -> None:
    """A literal %U passed to a session starts nothing and explains nothing."""
    fixture = Fixture({"chromiumos-ash-wayland.desktop": AURADE})
    try:
        command = S.sessions()[0].command
        check(command == ["/usr/bin/chromiumos-ash-session"],
              f"the session command still carries a field code: {command}")
    finally:
        fixture.close()


def test_a_hidden_session_stays_hidden() -> None:
    fixture = Fixture({"a.desktop": HIDDEN, "b.desktop": NO_DISPLAY,
                       "c.desktop": WESTON})
    try:
        found = [session.name for session in S.sessions()]
        check(found == ["Alternative desktop"],
              f"a session the system asked to hide was offered anyway: {found}")
    finally:
        fixture.close()


def test_an_action_is_not_the_session() -> None:
    """The Exec inside an action group belongs to a menu item, not a session."""
    fixture = Fixture({"a.desktop": ACTIONS})
    try:
        command = S.sessions()[0].command
        check(command == ["/usr/bin/real-session"],
              f"a desktop action's command became the session command: {command}")
    finally:
        fixture.close()


def test_the_first_value_of_a_repeated_key_wins() -> None:
    """A key written twice is a malformed entry, and the spec says the first
    value stands. Taking the last one instead would let anything appended to
    a session file replace the command that runs."""
    fixture = Fixture({"a.desktop": DUPLICATE})
    try:
        command = S.sessions()[0].command
        check(command == ["/usr/bin/real-session"],
              f"a repeated key replaced the session command: {command}")
    finally:
        fixture.close()


def test_a_key_from_an_action_never_reaches_the_session() -> None:
    """Scoping proved by a key the session group does not have at all.

    The action group carries a TryExec pointing at nothing. If group scoping
    breaks, that TryExec is read as the session's own and a working session
    disappears from the picker with no error anywhere.
    """
    fixture = Fixture({"a.desktop": ACTIONS})
    try:
        found = [session.name for session in S.sessions()]
        check(found == ["With actions"],
              f"a key from a desktop action removed a working session: {found}")
    finally:
        fixture.close()


def test_an_entry_with_nothing_to_run_is_not_offered() -> None:
    fixture = Fixture({"a.desktop": NO_EXEC, "b.desktop": WESTON})
    try:
        found = [session.name for session in S.sessions()]
        check(found == ["Alternative desktop"],
              "a session with no command was offered as something to press")
    finally:
        fixture.close()


def test_a_session_whose_binary_is_gone_is_not_offered() -> None:
    """TryExec is how an entry says its own program was uninstalled."""
    fixture = Fixture({"a.desktop": MISSING_BINARY, "b.desktop": WESTON})
    try:
        found = [session.name for session in S.sessions()]
        check(found == ["Alternative desktop"],
              "a session whose program is not installed was still offered")
    finally:
        fixture.close()


def test_an_empty_directory_is_not_a_crash() -> None:
    fixture = Fixture({})
    try:
        check(S.sessions() == [],
              "an empty session directory did not produce an empty list")
    finally:
        fixture.close()
    check(S.sessions("/nowhere/at/all") == [],
          "a missing session directory did not produce an empty list")


def test_every_session_goes_through_the_supervisor() -> None:
    """Not only the AuraDE one.

    The supervisor is what lets a session restart as a unit rather than
    leaving half a compositor behind, and a fallback session that skips it is
    a fallback that can strand the machine it was there to rescue.
    """
    wrapped = S.wrapped(["/usr/bin/weston"], "/usr/bin/aurade-session-supervisor")
    check(wrapped == ["/usr/bin/aurade-session-supervisor", "/usr/bin/weston"],
          f"the session command does not run under the supervisor: {wrapped}")
    check(S.wrapped(["/usr/bin/weston"], "") == ["/usr/bin/weston"],
          "an empty wrapper still prefixed something to the command")


def main() -> int:
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            function()
    if FAILURES:
        print("greeter sessions test: FAIL")
        for failure in FAILURES:
            print(f"  {failure}")
        return 1
    print("greeter sessions test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
