#!/usr/bin/env python3
"""The greeter window, built for real and asked about itself.

Reading the source proves the calls are in the right order. It does not prove
the widget tree that results behaves, and the installer already paid for that
lesson once: a set of pickers assembled from correct calls, referenced
correctly and styled correctly, that were dead when clicked, because
containment is a runtime rule.

So this builds the real window on a headless compositor, against a scripted
greetd on a socket pair, and drives it the way a person would: pick a row,
type the wrong thing, read what it says, press escape, try again.

The properties checked here are the ones a person notices in the first ten
seconds of a bad morning. Focus that lands somewhere announceable. A refused
password that says so and gives the field back. An escape that actually tells
greetd the attempt is over rather than leaving a half open conversation for
the next try to collide with.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import sys
import time

TESTS = os.path.dirname(os.path.realpath(__file__))
PACKAGE = os.path.normpath(os.path.join(TESTS, ".."))
sys.path.insert(0, PACKAGE)

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from aurade_greeter import copy as C  # noqa: E402
from aurade_greeter import protocol as P  # noqa: E402
from aurade_greeter import network as NET  # noqa: E402
from aurade_greeter.app import GreeterWindow  # noqa: E402


class NoRadio:
    """A NetworkManager that is not there.

    The window must build and sign somebody in on a machine with no system
    bus at all, which is every build host. A greeter that needs a radio to
    draw is a greeter that fails closed on exactly the machine somebody is
    trying to rescue.
    """

    def wifi_device(self):
        raise NET.NetworkError("no system bus on this machine")

    def networks(self, _path):
        return []

    def scan(self, _path):
        return None

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def equal(got: object, want: object, message: str) -> None:
    if got != want:
        FAILURES.append(f"{message}: expected {want!r}, got {got!r}")


def pump(count: int = 20) -> None:
    context = GLib.MainContext.default()
    for _ in range(count):
        while context.pending():
            context.iteration(False)
        time.sleep(0.01)


def pump_until(predicate, seconds: float = 4.0) -> bool:
    """Wait for a worker thread's answer to land on the main loop."""
    deadline = time.monotonic() + seconds
    context = GLib.MainContext.default()
    while time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        if predicate():
            return True
        time.sleep(0.02)
    return False


def pack(payload: dict) -> bytes:
    body = json.dumps(payload).encode("utf-8")
    return struct.pack("=I", len(body)) + body


class Greetd:
    """A scripted login service on the other end of a real socket."""

    def __init__(self, replies: list[dict]) -> None:
        self.theirs, self.ours = socket.socketpair()
        for reply in replies:
            self.theirs.sendall(pack(reply))
        self.transport = P.Transport(self.ours)

    def requests(self) -> list[dict]:
        self.theirs.setblocking(False)
        chunks = []
        while True:
            try:
                chunk = self.theirs.recv(65536)
            except (BlockingIOError, OSError):
                break
            if not chunk:
                break
            chunks.append(chunk)
        data = b"".join(chunks)
        out = []
        while len(data) >= 4:
            (size,) = struct.unpack("=I", data[:4])
            out.append(json.loads(data[4:4 + size].decode("utf-8")))
            data = data[4 + size:]
        return out

    def close(self) -> None:
        self.theirs.close()
        self.ours.close()


SECRET = {"type": "auth_message", "auth_message_type": "secret",
          "auth_message": "Password:"}
OK = {"type": "success"}
REFUSED = {"type": "error", "error_type": "auth_error",
           "description": "Login incorrect"}


def rows(window) -> list:
    listbox = window.widgets["accounts.list"]
    found = []
    index = 0
    while True:
        line = listbox.get_row_at_index(index)
        if line is None:
            return found
        found.append(line)
        index += 1


#: One window, built once. weston's kiosk shell segfaults when a toplevel is
#: created and destroyed repeatedly, and a compositor that dies mid test takes
#: the client with it and reports nothing about why. Every test therefore
#: reuses the window and re-points it at a fresh scripted greetd, which is also
#: closer to what actually happens: a greeter is one window for a whole boot,
#: and the sign in attempt inside it is the thing that comes and goes.
WINDOW: GreeterWindow | None = None
SERVICE: Greetd | None = None


def build(app, replies: list[dict]) -> tuple[GreeterWindow, Greetd]:
    global WINDOW, SERVICE
    if SERVICE is not None:
        SERVICE.close()
    SERVICE = Greetd(replies)
    if WINDOW is None:
        WINDOW = GreeterWindow(app, SERVICE.transport)
        WINDOW.nm = NoRadio()
        WINDOW.present()
        pump()
    else:
        WINDOW.session = None
        WINDOW.transport = SERVICE.transport
        WINDOW.chosen = None
        WINDOW.typed_name = ""
        WINDOW.entry.set_text("")
        WINDOW._clear_error()  # noqa: SLF001
        WINDOW._working(False)  # noqa: SLF001
        WINDOW.stack.set_visible_child_name("accounts")
        pump()
    return WINDOW, SERVICE


# --- the screen exists and is reachable -----------------------------------

def test_the_window_has_both_screens(app) -> None:
    window, service = build(app, [])
    try:
        check(window.stack.get_child_by_name("accounts") is not None,
              "there is no account screen")
        check(window.stack.get_child_by_name("password") is not None,
              "there is no password screen")
        equal(window.stack.get_visible_child_name(), "accounts",
              "the greeter does not open on the account list")
    finally:
        pump()


def test_every_account_has_a_row_and_so_does_everyone_else(app) -> None:
    window, service = build(app, [])
    try:
        titles = [line.get_title() for line in rows(window)]
        equal(titles, ["Ada Lovelace", "Grace Hopper", C.OTHER],
              "the account rows are not the fixture's people plus a way in")
    finally:
        pump()


def test_focus_lands_on_a_row_and_not_on_the_list(app) -> None:
    """The container focus bug the installer already paid for once.

    Focusing a GtkListBox draws a ring around the whole list and a screen
    reader announces the word list. On a login screen that is somebody being
    told nothing at all about the thing they are about to press.
    """
    window, service = build(app, [])
    try:
        window._focus_first_row()  # noqa: SLF001
        pump()
        focused = window.get_focus()
        check(focused is not None, "nothing at all has focus on the greeter")
        check(not isinstance(focused, Gtk.ListBox),
              "focus is on the list container rather than on a person's row")
        if focused is not None:
            check(isinstance(focused, Gtk.ListBoxRow),
                  f"focus landed on {type(focused).__name__}, not a row")
    finally:
        pump()


# --- signing in -----------------------------------------------------------

def test_choosing_somebody_asks_greetd_about_them(app) -> None:
    window, service = build(app, [SECRET, OK, OK])
    try:
        window.choose(window.accounts[0])
        check(pump_until(lambda: window.busy is False),
              "the greeter never came back from asking greetd")
        equal(window.stack.get_visible_child_name(), "password",
              "choosing an account did not move to the password screen")
        equal(window.widgets["password.name"].get_label(), "Ada Lovelace",
              "the password screen does not say whose password it wants")
        sent = service.requests()
        equal([request["type"] for request in sent], ["create_session"],
              "choosing an account did not open exactly one session")
        equal(sent[0]["username"], "ada",
              "the username sent to greetd is not the row that was pressed")
    finally:
        pump()


def test_the_password_field_never_shows_the_password(app) -> None:
    window, service = build(app, [SECRET, OK])
    try:
        check(isinstance(window.entry, Gtk.PasswordEntry),
              "the password field is an ordinary entry and echoes what is typed")
    finally:
        pump()


def test_a_refused_password_says_so_and_gives_the_field_back(app) -> None:
    window, service = build(app, [SECRET, REFUSED, SECRET])
    try:
        window.choose(window.accounts[0])
        check(pump_until(lambda: not window.busy), "the first prompt never arrived")
        window.entry.set_text("wrong")
        window.submit()
        # Before the answer comes back, not after. The field has a peek icon.
        equal(window.entry.get_text(), "",
              "the password is still in the field while greetd is thinking")
        check(pump_until(
            lambda: window.widgets["password.error"].get_visible()),
            "a refused password produced no message at all")
        equal(window.widgets["password.error"].get_label(), C.WRONG,
              "the refusal does not read like the rest of AuraDE")
        equal(window.entry.get_text(), "",
              "the refused password is still sitting in the field")
        equal(window.stack.get_visible_child_name(), "password",
              "a refused password threw the person back to the account list")
    finally:
        pump()


def test_backing_out_tells_greetd(app) -> None:
    """A half open conversation is what the next attempt collides with."""
    window, service = build(app, [SECRET, OK])
    try:
        window.choose(window.accounts[0])
        check(pump_until(lambda: not window.busy), "the first prompt never arrived")
        window.to_accounts()
        check(pump_until(
            lambda: any(request["type"] == "cancel_session"
                        for request in service.requests())),
            "backing out left the sign in attempt open on greetd")
        equal(window.stack.get_visible_child_name(), "accounts",
              "backing out did not return to the account list")
    finally:
        pump()


def test_power_stays_reachable_while_greetd_thinks(app) -> None:
    """A hung authentication must not take the restart button with it.

    Everything else on the panel goes insensitive while a worker is out, which
    is right: pressing sign in twice starts two conversations on one socket.
    Power is the exception, because a login screen that has stopped answering
    needs a way out that is not the power switch on the case.
    """
    window, service = build(app, [SECRET, OK])
    try:
        window._working(True)  # noqa: SLF001
        pump()
        for name in ("power.restart", "power.off"):
            check(window.widgets[name].get_sensitive(),
                  f"{name} went dead while the greeter was waiting on greetd")
        check(not window.widgets["password.submit"].get_sensitive(),
              "sign in stayed pressable while a conversation was already out")
        window._working(False)  # noqa: SLF001
    finally:
        pump()


def test_a_dead_service_says_something_a_person_can_act_on(app) -> None:
    window, service = build(app, [])
    try:
        service.theirs.close()
        window.choose(window.accounts[0])
        check(pump_until(
            lambda: window.widgets["password.error"].get_visible()),
            "a login service that has gone away produced no message")
        equal(window.widgets["password.error"].get_label(), C.SERVICE_GONE,
              "the message for a dead login service is not the written one")
        for name in ("power.restart", "power.off"):
            check(window.widgets[name].get_sensitive(),
                  f"{name} is unusable during a failure, so there is no way out")
    finally:
        pump()


# --- the things that are only true at runtime -----------------------------

def test_the_status_area_opens_and_says_there_is_no_radio(app) -> None:
    """A machine with no NetworkManager still has a working login screen.

    The panel is the only way to fix a network from here, so it has to be
    reachable, and on a machine with no radio it has to say so rather than
    show an empty list somebody presses at.
    """
    window, service = build(app, [])
    try:
        check(window.widgets["status"] is not None, "there is no status area")
        check(window.widgets["panel"] is not None, "the status area opens nothing")
        window.refresh_networks(scan=False)
        check(pump_until(lambda: not window._network_busy),  # noqa: SLF001
              "reading the network never came back")
        note = window.widgets["panel.note"]
        check(note.get_visible(), "a machine with no radio said nothing at all")
        check(bool(note.get_label()), "the note is visible and empty")
        # And the power controls moved into the panel rather than vanishing.
        for name in ("power.restart", "power.off"):
            check(window.widgets[name] is not None,
                  f"{name} was lost when the corner became a panel")
    finally:
        pump()


def test_one_session_shows_no_picker(app) -> None:
    window, service = build(app, [])
    try:
        check(not window.widgets["password.session.holder"].get_visible(),
              "a machine with one session still asks which session to use")
    finally:
        pump()


def test_the_clock_reads_as_a_clock(app) -> None:
    window, service = build(app, [])
    try:
        text = window.widgets["clock"].get_label()
        check(len(text) == 5 and text[2] == ":",
              f"the clock on the login screen reads {text!r}")
        check(bool(window.widgets["date"].get_label()),
              "the login screen shows a time with no day attached to it")
    finally:
        pump()


def test_every_class_the_greeter_uses_is_defined(app) -> None:
    """The stylesheet and the widget layer, checked against each other.

    A class that is applied and never defined is a widget that silently keeps
    the default appearance, which on a screen this small is the difference
    between a login panel and a stack of unstyled labels.
    """
    import re

    source = open(os.path.join(PACKAGE, "aurade_greeter", "app.py"),
                  encoding="utf-8").read()
    used = set(re.findall(r'add_css_class\("([a-z0-9-]+)"\)', source))
    used |= set(re.findall(r'css="([a-z0-9-]+)"', source))
    defined = set()
    for name in ("theme-dark.css", "theme.css", "greeter.css"):
        path = os.path.join(PACKAGE, "aurade_greeter", name)
        defined |= set(re.findall(r'\.([a-z0-9-]+)',
                                  open(path, encoding="utf-8").read()))
    # Classes libadwaita and GTK define for themselves.
    builtin = {"flat", "pill", "suggested-action", "destructive-action",
               "boxed-list", "dim-label", "error", "warning", "success",
               "heading", "title", "body", "caption", "card", "linked",
               "circular", "osd", "toolbar", "numeric", "monospace"}
    missing = sorted(used - defined - builtin)
    check(not missing,
          f"the greeter applies classes the stylesheet does not define: {missing}")


def main() -> int:
    Adw.init()
    app = Adw.Application(application_id="org.aurade.GreeterTest")
    app.register(None)
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            try:
                function(app)
            except Exception as exc:  # noqa: BLE001 - a raise is a failure
                FAILURES.append(f"{name} raised {exc!r}")
    if SERVICE is not None:
        SERVICE.close()
    if FAILURES:
        print("greeter runtime test: FAIL")
        for failure in FAILURES:
            print(f"  {failure}")
        return 1
    print("greeter runtime test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
