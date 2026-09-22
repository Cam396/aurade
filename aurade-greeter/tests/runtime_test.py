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
import datetime
import os
import socket
import struct
import sys
import time
import urllib.error
import urllib.request

TESTS = os.path.dirname(os.path.realpath(__file__))
PACKAGE = os.path.normpath(os.path.join(TESTS, ".."))
sys.path.insert(0, PACKAGE)

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from aurade_greeter import copy as C  # noqa: E402
from aurade_greeter import protocol as P  # noqa: E402
from aurade_greeter import weatherui as WUI  # noqa: E402
from aurade_greeter import alertui as AU  # noqa: E402
from aurade_greeter import weather as _W  # noqa: E402

#: The words for every condition the shade will draw a line for.
W_WORDS = {_W.WORDS[kind] for kind in _W.SPELLS}
from aurade_greeter import network as NET  # noqa: E402
from aurade_greeter.app import GreeterWindow, Wallpaper  # noqa: E402
from aurade_greeter import weather as WX  # noqa: E402
from aurade_greeter import status as ST  # noqa: E402
from aurade_greeter import settings as SET  # noqa: E402
from aurade_greeter import tokens as T  # noqa: E402
from aurade_greeter import app as _app  # noqa: E402


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

#: What this run could not check, and why. A skip that is not reported is a
#: pass that did not happen.
NOT_COVERED: list[str] = []

#: What the greeter opened on, recorded once, at construction.
#:
#: This file reuses one window across every test and resets it between them,
#: and the reset is now to the shade rather than to the account list. That
#: reset would mask the very thing the shade is for: an assertion made after
#: it is an assertion about the reset. So the real starting state is taken
#: from the window before anything has touched it, and never again.
OPENED = {"page": None, "lifted": None}


def seed_weather() -> None:
    """A reading, written before any window exists.

    The greeter paints what it last knew and only asks again once that has
    gone stale, so a cache written a moment ago is what makes the rest of this
    file able to look at a filled in weather panel without a network.
    """
    where = os.environ.get("AURADE_WEATHER_CACHE")
    if not where:
        return
    start = datetime.datetime.now().astimezone().replace(
        minute=0, second=0, microsecond=0)
    report = WX.Report(
        place="Ardsley, NY", provider="nws", latitude=41.0126,
        longitude=-73.8437, zone="America/New_York", taken=time.time(),
        narrative="A chance of showers and thunderstorms before 2pm.",
        now=WX.Now(temperature=25.0, feels_like=30.3, humidity=77,
                   dew_point=20.6, wind=19.0, gust=34.0, bearing=163,
                   pressure=1016.7, visibility=14.5, condition=WX.THUNDER,
                   daylight=True, summary="Chance Showers And Thunderstorms"),
        hours=[WX.Hour(at=start + datetime.timedelta(hours=n),
                       temperature=26.0 - n, condition=WX.RAIN,
                       precipitation=40 + n, daylight=True)
               for n in range(12)],
        days=[WX.Day(date=start.date() + datetime.timedelta(days=n),
                     high=28.0 - n, low=20.0 - n, condition=WX.THUNDER,
                     precipitation=50, ultraviolet=6.2)
              for n in range(7)])
    WX.save(report, where)


seed_weather()


def no_network(*_args, **_kwargs):
    """What every request this file could make gets, which is no answer.

    The fresh cache keeps the forecast from asking. It does not keep the
    warnings from asking, and it is not meant to: they refresh on a clock of
    their own, a minute apart, because a tornado warning cannot wait for the
    forecast to go stale. The suite builds one window and keeps it for every
    test, so that clock runs for the whole run. On a machine with a route out,
    a real answer from the weather service landed partway through the alerts
    test and repainted the panel it was counting rows on, and the test failed
    or passed depending on which half of it the answer arrived in. A refused
    request is the case the greeter already handles by keeping what is on
    screen, so refusing all of them costs no test anything.
    """
    raise urllib.error.URLError("the runtime test has no network")


urllib.request.urlopen = no_network


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
# greetd 0.10's answer when the refused attempt is cancelled, which it has to
# be before the next one can begin. An error, and the attempt is cleared anyway.
CANCELLED = {"type": "error", "error_type": "error",
             "description": "unable to send message: Connection refused "
                            "(os error 111)"}


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


def lower_shade(window) -> None:
    """Put the window back the way it starts, before a test that lifts it.

    One window is reused by every test in this file, and it used to be handed
    back with the stack forced to the account list. That is what the greeter
    opened on at the time, so it was harmless, and it stopped being harmless
    the moment the shade existed: the assertion that the greeter opens on the
    account list went on passing, against a page this helper had just set.

    So the reset is to the real initial state, and a test that wants the
    accounts asks for them the way a person does.
    """
    window.shade_up = False
    window._stop_rotating()  # noqa: SLF001
    window.stack.set_visible_child_name("shade")
    for child in _rows(window):
        child.remove_css_class("aurade-arrived")
    card = window.widgets.get("card")
    if card is not None:
        card.remove_css_class("aurade-gone")
        window._show_card()  # noqa: SLF001


def _rows(window) -> list:
    listbox = window.widgets.get("accounts.list")
    if listbox is None:
        return []
    found, child = [], listbox.get_first_child()
    while child is not None:
        found.append(child)
        child = child.get_next_sibling()
    return found


def build(app, replies: list[dict],
          lifted: bool = True) -> tuple[GreeterWindow, Greetd]:
    global WINDOW, SERVICE
    if SERVICE is not None:
        SERVICE.close()
    SERVICE = Greetd(replies)
    if WINDOW is None:
        WINDOW = GreeterWindow(app, SERVICE.transport)
        WINDOW.nm = NoRadio()
        WINDOW.present()
        pump()
        OPENED["page"] = WINDOW.stack.get_visible_child_name()
        OPENED["lifted"] = WINDOW.shade_up
    else:
        WINDOW.session = None
        WINDOW.transport = SERVICE.transport
        WINDOW.chosen = None
        WINDOW.typed_name = ""
        WINDOW.entry.set_text("")
        WINDOW._clear_error()  # noqa: SLF001
        WINDOW._working(False)  # noqa: SLF001
        # The refusal count belongs to one conversation with one person, and
        # every test here is a new one. Without this, a test that refuses a
        # password leaves the count standing for the next test that refuses
        # one for the same name, which then reads as the second wrong answer
        # and says so. That only shows up where a lockout policy is actually
        # configured, so it stayed hidden on a build host whose PAM stack had
        # no pam_faillock in it at all.
        WINDOW._refusals = 0  # noqa: SLF001
        WINDOW._refused_for = ""  # noqa: SLF001
        pump()
    lower_shade(WINDOW)
    if lifted:
        WINDOW.lift()
        # Long enough for the staggered arrival to have finished, so a test
        # that looks at a row is looking at a row that has arrived.
        pump(60)
    return WINDOW, SERVICE


# --- the screen exists and is reachable -----------------------------------

def test_the_window_has_both_screens(app) -> None:
    window, service = build(app, [])
    try:
        check(window.stack.get_child_by_name("accounts") is not None,
              "there is no account screen")
        check(window.stack.get_child_by_name("password") is not None,
              "there is no password screen")
        check(window.stack.get_child_by_name("shade") is not None,
              "there is no shade")
        equal(window.stack.get_visible_child_name(), "accounts",
              "the account list is not what a lifted shade leads to")
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


def test_a_key_press_leaves_focus_on_a_row_and_not_on_the_status_bar(app) -> None:
    """The bug somebody hit by pressing Return at their own login screen.

    lift() switches the stack and grabs focus in the same breath. A row that
    has not been mapped yet refuses focus without saying so, focus stays where
    the window put it, and the next Return goes to whatever the window
    considers first, which is the weather tile. The person pressed Return to
    sign in and got a weather panel.

    So this exercises the real entry point rather than calling the focus
    helper directly, which is what the older test does and why it went on
    passing through the bug.
    """
    window, service = build(app, [], lifted=False)
    try:
        handled = window._on_key(None, Gdk.KEY_Return, 0, 0)  # noqa: SLF001
        check(handled, "the first key press was not swallowed by the shade")
        check(pump_until(lambda: isinstance(window.get_focus(), Gtk.ListBoxRow)),
              f"after a key press focus is on {type(window.get_focus()).__name__}, "
              "not on somebody's row")
        equal(window.stack.get_visible_child_name(), "accounts",
              "a key press did not bring the accounts up")
    finally:
        pump()


# --- signing in -----------------------------------------------------------

def test_no_password_box_appears_for_an_account_that_is_never_asked(app) -> None:
    """An account with no password is never prompted for one.

    The field used to be shown the moment a row was pressed, before greetd had
    said anything, so somebody with a blank password saw a password box, then
    the screen went out underneath them without the box ever being used. That
    reads as a screen that ignored what they were about to type.
    """
    window, service = build(app, [OK, OK])
    try:
        window.choose(window.accounts[0])
        check(pump_until(lambda: window.stack.get_visible_child_name() == "handoff"),
              "a sign in that needed no password never reached the handoff")
        check(not window.entry.get_visible(),
              "a password box was shown to somebody who was never asked for one")
    finally:
        pump()


def test_the_password_box_appears_when_the_service_asks_for_it(app) -> None:
    """And the other half: an account that does have a password must still get
    a field, or the fix above locks everybody out."""
    window, service = build(app, [SECRET, OK, OK])
    try:
        window.choose(window.accounts[0])
        check(pump_until(lambda: window.entry.get_visible()),
              "an account that was asked for a secret never got a field")
        equal(window.stack.get_visible_child_name(), "password",
              "the password screen is not the one on show")
        # GtkPasswordEntry delegates focus to an inner GtkText, so the
        # question is whether focus is inside the field, not whether it is the
        # field. Somebody has to be able to type without clicking first.
        focus = window.get_focus()
        inside = focus is window.entry or (
            focus is not None and focus.is_ancestor(window.entry))
        check(inside,
              "the password field is visible but focus is on "
              f"{type(focus).__name__ if focus is not None else 'nothing'}")
    finally:
        pump()


def test_the_handoff_says_whose_desktop_is_starting(app) -> None:
    """Between the greeter letting go and the desktop drawing, this hardware
    is dark for eight to twenty two seconds. The greeter owns the first part
    of that, and what it leaves on screen is a name, not black."""
    window, service = build(app, [SECRET, OK, OK])
    try:
        window.choose(window.accounts[0])
        check(pump_until(lambda: window.entry.get_visible()),
              "never got as far as a password field")
        window.entry.set_text("secret")
        window.submit()
        check(pump_until(lambda: window.stack.get_visible_child_name() == "handoff"),
              "signing in did not put the handoff screen up")
        said = window.widgets["handoff.title"].get_label()
        check("Ada" in said, f"the handoff says {said!r}, which is not who signed in")
        check(window.widgets["handoff.note"].get_label().strip() != "",
              "the handoff shows a name and no word about what is happening")
    finally:
        window._stop_handoff_pulse()  # noqa: SLF001
        pump()



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


def test_the_photograph_drifts_and_stops_for_reduced_motion(app) -> None:
    """Slow enough that nobody catches it, and absent where it is not wanted.

    The drift has to be smaller than the blur the frosted cards are built
    from, because the glass samples the picture at rest and is not recomputed
    as it moves. That is the assertion worth keeping: if the drift ever grows
    past the blur, the ground under a card starts changing underneath a
    contrast figure that was solved for a different picture.
    """
    window, service = build(app, [SECRET, OK])
    try:
        paper = window.wallpaper
        if not paper.present:
            check(False, "no photograph, so this proved nothing")
            return
        check(paper._drifting is not None,
              "the picture is not drifting on a screen that wants motion")
        check(0.0 <= paper.drift <= 1.0,
              f"the drift left its range at {paper.drift}")

        # It moves, and moving redraws.
        paper._drifted(1.0)
        pump()
        equal(paper.drift, 1.0, "the drift did not take")

        # Reduced motion is answered by never starting, so the picture sits
        # where it started rather than being animated and then stopped.
        # Asserted against the source, because the guard is at the call site
        # and a window built without motion is a second harness.
        import inspect
        source = inspect.getsource(type(window)._build)
        check("if self.animate:" in source
              and "start_drifting" in source.split("if self.animate:")[-1][:200],
              "the drift is started without asking whether motion is wanted")

        # And it stays inside the overscan, so no edge is ever exposed.
        margin = max(2, int(paper.get_width() * _app.DRIFT))
        for value in (0.0, 0.5, 1.0):
            shift = abs((value - 0.5) * 2.0) * margin
            check(shift <= margin,
                  f"a drift of {value} moves {shift} past a {margin} margin")

        # Smaller than the blur it is invisible to. The glass reduces the
        # image by two to the fifth before sampling it, so anything under
        # that is genuinely not there as far as the ground is concerned.
        blur = 2 ** _app.GL.ROUNDS
        check(margin < blur,
              f"the drift is {margin}px and the blur reduces by {blur}, so "
              f"the ground under a card now moves while the tint solved for "
              f"it does not")
    finally:
        pump()


def test_the_panel_says_when_it_continues_below(app) -> None:
    """The fold is around the week and everything under it went unread.

    The scroller caps at 620 so the panel fits a 768 tall screen, GTK's
    overlay scrollbar fades out when it is not in use, and the result looked
    like a panel that simply ended. Somebody reading it concluded the readings
    were missing, and a person who assumes it ends will not scroll.
    """
    window, service = build(app, [SECRET, OK])
    try:
        panel = window.widgets["weather.panel"]
        adjustment = panel.scroller.get_vadjustment()

        # More below than fits: the fade is up.
        adjustment.set_upper(2000.0)
        adjustment.set_page_size(600.0)
        adjustment.set_value(0.0)
        pump()
        check(panel.fade.get_visible(),
              "the panel does not say it continues below the fold")

        # Scrolled to the end: nothing more to promise.
        adjustment.set_value(1400.0)
        pump()
        check(not panel.fade.get_visible(),
              "the fade stayed up at the bottom of the panel")

        # Short enough to need no scrolling at all.
        adjustment.set_upper(400.0)
        adjustment.set_page_size(600.0)
        adjustment.set_value(0.0)
        pump()
        check(not panel.fade.get_visible(),
              "a panel that fits was told it continues below")

        # And it must never eat a click meant for the row under it.
        check(not panel.fade.get_can_target(),
              "the fade takes pointer events, so it would swallow a tap on "
              "the last visible row")
    finally:
        pump()


def test_warnings_reach_the_panel_and_nothing_else_does(app) -> None:
    """The quiet end of the alerts feature, on screen.

    One row per warning, loudest first, coloured by tier. The row an Amber
    Alert would have occupied is the point of the assertion: it is not
    quieter, it is absent, and the panel has no idea it existed.
    """
    window, service = build(app, [SECRET, OK])
    try:
        panel = window.widgets["weather.panel"]
        check(not panel.alerts.get_visible(),
              "the alert strip is showing with no alerts in the report")

        class Fake:
            def __init__(self, event, category, severity, urgency):
                self.event, self.category = event, category
                self.severity, self.urgency = severity, urgency
                self.status = "Actual"
                self.headline = f"{event} issued"
                self.instruction = "Move to an interior room."
                self.expires = datetime.datetime(
                    2026, 8, 28, 21, 15, tzinfo=datetime.timezone.utc)

        report = WX.Report(place="Ardsley, NY", provider="nws",
                           taken=__import__("time").time())
        report.now.temperature = 21.0
        report.alerts = [
            Fake("Tornado Warning", "Met", "Extreme", "Immediate"),
            Fake("Heat Advisory", "Met", "Moderate", "Expected"),
        ]
        panel.show_report(report, "f")
        pump()
        check(panel.alerts.get_visible(), "two warnings did not show")
        rows = []
        child = panel.alerts.get_first_child()
        while child is not None:
            rows.append(child)
            child = child.get_next_sibling()
        equal(len(rows), 2, "the panel drew the wrong number of warnings")
        check(rows[0].has_css_class("aurade-alert-takeover"),
              "the tornado warning is not marked as the loudest tier")
        check(rows[1].has_css_class("aurade-alert-line"),
              "the heat advisory is not marked as the quietest tier")

        # Shown twice must not stack. Counting children rather than reading
        # visibility, because stale rows left behind are merely hidden and a
        # visibility check passes over them happily.
        panel.show_report(report, "f")
        pump()
        again = 0
        child = panel.alerts.get_first_child()
        while child is not None:
            again += 1
            child = child.get_next_sibling()
        equal(again, 2, "showing the same two warnings twice stacked them")

        # And it clears, because an alert expiring is a row leaving.
        report.alerts = []
        panel.show_report(report, "f")
        pump()
        check(not panel.alerts.get_visible(),
              "the strip stayed up after the warnings ended")
        left = 0
        child = panel.alerts.get_first_child()
        while child is not None:
            left += 1
            child = child.get_next_sibling()
        equal(left, 0, "the rows were hidden rather than removed")

        # And they survive the forecast failing, which is the case that
        # matters most: the warning comes from a different service to the
        # readings, so a dead forecast must not swallow a tornado.
        dead = WX.Report(place="", provider="",
                         taken=__import__("time").time())
        dead.alerts = [Fake("Tornado Warning", "Met", "Extreme", "Immediate")]
        panel.show_report(dead, "f")
        pump()
        check(panel.alerts.get_visible(),
              "a warning was dropped because the forecast did not answer")
        equal(panel.condition.get_label(), C.WEATHER_NO_ANSWER,
              "the panel stopped saying the forecast is missing")
    finally:
        pump()


def test_every_person_gets_their_own_face(app) -> None:
    """Three identical purple discs is the default avatar of every greeter.

    It is also the exact moment a screen stops looking like it was made for
    anybody in particular. The hue comes from the name, so it is stable across
    reboots and the same on every machine that person signs in to, and it
    stays inside ninety degrees of the brand so the set still belongs together.
    """
    window, service = build(app, [SECRET, OK])
    try:
        if len(window.accounts) < 2:
            check(False, "fewer than two accounts, so this proved nothing")
            return
        tint = T.DARK
        tones = [_app._person_tones(a, tint)[0] for a in window.accounts]
        check(len(set(tones)) == len(tones),
              f"two accounts share a face colour: {tones}")
        # Stable, not random.
        again = [_app._person_tones(a, tint)[0] for a in window.accounts]
        equal(tones, again, "the same account got a different colour twice")
        # And the ink is left alone, so contrast is whatever the theme decided.
        inks = {_app._person_tones(a, tint)[1] for a in window.accounts}
        equal(len(inks), 1, "the letter colour moved with the ground")
    finally:
        pump()


def test_a_refused_password_names_the_keyboard(app) -> None:
    """The other reason a password that is definitely right is refused.

    Hidden until a password has actually been refused: stated up front it is a
    fact nobody needs, and stated after a refusal it is the answer.
    """
    window, service = build(app, [SECRET, REFUSED, CANCELLED, SECRET])
    try:
        line = window.widgets.get("password.layout")
        check(line is not None, "the password page has no layout line")
        check(not line.get_visible(),
              "the keyboard layout is announced before anything went wrong")
        if not window.accounts:
            check(False, "no accounts, so this proved nothing")
            return
        window.choose(window.accounts[0])
        pump()
        window.entry.set_text("wrong")
        window.submit()
        for _ in range(40):
            pump()
            if line.get_visible():
                break
        # Only where the machine can say what its layout is. On a host with
        # none of the three files this stays quiet, and a line reading "This
        # keyboard is set to" and then nothing would be worse than no line.
        if SET.keyboard_layout():
            check(line.get_visible(),
                  "a refused password did not name the keyboard")
            check(SET.layout_words(SET.keyboard_layout()) in line.get_label(),
                  f"the layout line does not name the layout: "
                  f"{line.get_label()!r}")
    finally:
        pump()


def test_the_field_asks_the_person_by_name(app) -> None:
    """"Password" is a label on a form. A name is the screen answering you.

    It is also the quickest way to notice the wrong account is selected on a
    machine with three of them, which is the practical argument rather than
    the warm one.
    """
    window, service = build(app, [SECRET, OK])
    try:
        if not window.accounts:
            check(False, "no accounts, so this proved nothing")
            return
        first = window.accounts[0]
        window.choose(first)
        pump()
        placeholder = window.entry.get_property("placeholder-text") or ""
        given = first.title.split()[0]
        check(given and given in placeholder,
              f"the field does not say who it is for: {placeholder!r}")
        check(placeholder != C.PASSWORD,
              "the field still says the generic label")
    finally:
        pump()


def test_only_one_clock_is_on_screen_at_a_time(app) -> None:
    """The shade and the account list both carry the hour at ninety points.

    So the shelf clock is a second reading of the same thing on two pages out
    of three, and the corner is the one to lose. It comes back on the password
    page, which has no clock of its own.

    Keyed off the visible page rather than off whether the shade has lifted:
    that was the first version and it looked right while still leaving two
    clocks on the account list.
    """
    window, service = build(app, [SECRET, OK])
    try:
        clock = window.widgets.get("status.clock")
        rule = window.widgets.get("status.rule")
        check(clock is not None and rule is not None,
              "the shelf has no clock to hide")
        for page, wanted in (("shade", False), ("accounts", False),
                             ("password", True)):
            window.stack.set_visible_child_name(page)
            pump()
            equal(clock.get_visible(), wanted,
                  f"on the {page} page the shelf clock visibility is wrong")
            equal(rule.get_visible(), wanted,
                  f"on the {page} page the shelf hairline visibility is wrong")
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
    window, service = build(app, [SECRET, REFUSED, CANCELLED, SECRET])
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
        # And the next try has to be able to start. greetd refuses a new
        # attempt until the refused one is cancelled; without the cancel the
        # retry failed, the message turned into restart the computer, and it
        # meant it.
        check(pump_until(lambda: not window.busy and window.session is not None
                         and window.session.state == P.Session.ASKING),
              "after a refused password the next try never got its prompt")
        equal(window.widgets["password.error"].get_label(), C.WRONG,
              "the refusal turned into a different message after the retry")
        kinds = [request["type"] for request in service.requests()]
        equal(kinds, ["create_session", "post_auth_message_response",
                      "cancel_session", "create_session"],
              "the refused attempt was not cancelled before the next began")
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

    # Every module that draws, not just `app.py`. It read one file until the
    # warning strip and the takeover arrived in a module of their own wearing
    # two class names the stylesheet had never heard of, and this test was
    # green the whole time.
    used: set[str] = set()
    where = os.path.join(PACKAGE, "aurade_greeter")
    for name in sorted(os.listdir(where)):
        if not name.endswith(".py"):
            continue
        source = open(os.path.join(where, name), encoding="utf-8").read()
        used |= set(re.findall(r'add_css_class\("([a-z0-9-]+)"\)', source))
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


def test_the_alert_request_sits_behind_the_switch(app) -> None:
    """Off means the machine never asks, not that the answer is drawn quietly.

    What somebody switching emergency alerts off is most likely objecting to
    is the request itself, so a setting that suppresses the drawing while the
    request still goes out has lied about what it did.

    This drives the real `refresh_weather`, and the first version of it did
    not: it read the syntax tree and required every `ALERTS.fetch` to sit
    under an `if` naming the switch. A mutation to `if warnings is not None:`
    went straight through. The switch was named, the condition was always
    true, and the shape was the whole of what the assertion could see.
    """
    window, _ = build(app, [])
    if window.widgets.get("weather") is None:
        NOT_COVERED.append("the emergency alert switch: this build has no "
                           "weather pill to hang the request off")
        return
    report = window.weather
    if report is None:
        NOT_COVERED.append("the emergency alert switch: no seeded reading to "
                           "answer the request with")
        return

    asked: list[tuple] = []

    kept = (_app.Worker, _app.ALERTS.fetch, WX.fetch, WX.normal_high,
            WX.save, window.behaviour, window.weather)
    here = dict(window.behaviour)
    here["weather"] = "on"
    here["weather_latitude"] = "29.4241"
    here["weather_longitude"] = "-98.4936"
    try:
        _app.Worker = Immediate
        _app.ALERTS.fetch = (lambda lat, lon, **_kw:
                             asked.append((lat, lon)) or [])
        WX.fetch = lambda *_a, **_kw: report
        WX.normal_high = lambda *_a, **_kw: None
        WX.save = lambda *_a, **_kw: True

        window.behaviour = dict(here, alerts="off")
        window._weather_busy = False
        window.refresh_weather(force=True)
        check(asked == [],
              f"the alert request went out {len(asked)} times on a machine "
              f"where emergency alerts are switched off")

        window.behaviour = dict(here, alerts="on")
        window._weather_busy = False
        window.refresh_weather(force=True)
        check(asked == [(report.latitude, report.longitude)],
              f"the switch was on and the alert request was {asked!r} rather "
              f"than one question about where the reading came from")
    finally:
        (_app.Worker, _app.ALERTS.fetch, WX.fetch, WX.normal_high,
         WX.save, window.behaviour, window.weather) = kept


class Immediate:
    """A Worker without the thread, so an assertion cannot race it."""

    def __init__(self, work, done) -> None:
        self._work, self._done = work, done

    def start(self) -> "Immediate":
        try:
            result, error = self._work(), None
        except Exception as exc:  # noqa: BLE001 - delivered, not swallowed
            result, error = None, exc
        self._done(result, error)
        return self


def _warning(event: str, severity: str, urgency: str, ident: str,
             motion: str = ""):
    """One alert, through the real parser and the real gate."""
    from aurade_greeter import alerts as ALERTS

    when = datetime.datetime.now().astimezone()
    parameters = {"VTEC": [f"/O.NEW.KEWX.{ident}.0001.260828T1200Z-"
                           f"260828T1400Z/"]}
    if motion:
        parameters["eventMotionDescription"] = [motion]
    return ALERTS.shown([{"properties": {
        "event": event, "category": "Met", "severity": severity,
        "urgency": urgency, "certainty": "Observed", "status": "Actual",
        "headline": f"{event} for Bexar County",
        "description": "Radar indicated.",
        "instruction": "Take shelter in an interior room on the lowest floor.",
        "response": "Shelter", "areaDesc": "Bexar, TX",
        "sent": (when - datetime.timedelta(minutes=4)).isoformat(),
        "onset": None,
        "expires": (when + datetime.timedelta(hours=1)).isoformat(),
        "id": ident, "parameters": parameters}, "geometry": None}], when)


def test_a_tornado_warning_takes_the_screen(app) -> None:
    """The loudest tier, drawn, and the strip under it that outlives it.

    Everything here goes through `alerts.shown`, so what reaches the screen is
    what the gate admitted rather than a record placed on the widget by hand.
    A test that skips the gate proves the widget draws and nothing about
    whether the thing that decides would ever have called it.
    """
    window, _ = build(app, [])
    if window.widgets.get("weather") is None or window.weather is None:
        NOT_COVERED.append("the warning takeover: this build has no weather")
        return
    takeover = window.widgets["warning.takeover"]
    banner = window.widgets["warning.banner"]
    kept = list(window.weather.alerts or [])
    takeover.dismissed.clear()
    try:
        window.weather.alerts = _warning(
            "Tornado Warning", "Extreme", "Immediate", "TO.W",
            "...storm...29.20,-98.70...DEG 45KT 30...")
        window._paint_weather()
        check(takeover.get_visible(),
              "a tornado warning did not take the screen")
        check(banner.get_visible(),
              "the strip is not up behind the takeover, so dismissing it "
              "would leave nothing saying there is a tornado")
        check("Tornado Warning" in takeover.event.get_label(),
              f"the takeover says {takeover.event.get_label()!r}")
        check("Take shelter" in takeover.instruction.get_label(),
              f"the takeover does not carry the instruction: "
              f"{takeover.instruction.get_label()!r}")
        check(takeover.near.get_label(),
              "the takeover says nothing about where the storm is, and this "
              "warning came with a tracked cell on it")

        # The way out, and it must not also reach whatever had focus.
        stopped = window._on_warning_key(None, 0, 0, None)
        check(stopped == Gdk.EVENT_STOP,
              "the keystroke that cleared the warning went on to the password "
              "field as well, so it types a character nobody meant")
        check(not takeover.get_visible(),
              "a key press did not clear the warning off the screen")
        check(banner.get_visible(),
              "clearing the takeover took the strip with it, so the warning "
              "is now invisible while it is still in force")

        # And the same storm does not come back. A warning is reissued as it
        # is extended, and without the identity check the sixth reissue lands
        # on somebody who has been trying to type a password for ten minutes.
        window._paint_weather()
        check(not takeover.get_visible(),
              "the same warning took the screen again after being dismissed")
        window.weather.alerts = _warning(
            "Tornado Warning", "Extreme", "Immediate", "TO.W")
        window._paint_weather()
        check(not takeover.get_visible(),
              "a reissue of the same storm took the screen again, so a "
              "warning that updates every ten minutes cannot be got past")

        # A different storm is a different decision.
        window.weather.alerts = _warning(
            "Flash Flood Warning", "Extreme", "Immediate", "FF.W")
        window._paint_weather()
        check(takeover.get_visible(),
              "a second, different emergency was suppressed by the first "
              "one having been dismissed")
        window._on_warning_key(None, 0, 0, None)

        # Nothing live: both go away, and the key stops being swallowed.
        window.weather.alerts = []
        window._paint_weather()
        check(not banner.get_visible(),
              "the strip stayed up with no warning behind it")
        check(window._on_warning_key(None, 0, 0, None) == Gdk.EVENT_PROPAGATE,
              "keystrokes are still being swallowed with nothing on screen, "
              "so the password field has gone deaf")
    finally:
        window.weather.alerts = kept
        takeover.dismissed.clear()
        window._paint_weather()


def test_a_warning_that_expired_was_never_got_past(app) -> None:
    """Clearing is not dismissing, and conflating them loses a warning.

    A warning that ended while it was on screen was not read by anybody. If
    taking it down counted as having been seen, the next issuance of the same
    storm, which carries the same VTEC identity, would arrive in silence. That
    is the one case where this feature failing is indistinguishable from it
    working.
    """
    window, _ = build(app, [])
    if window.widgets.get("weather") is None or window.weather is None:
        NOT_COVERED.append("the expiry case: this build has no weather")
        return
    takeover = window.widgets["warning.takeover"]
    kept = list(window.weather.alerts or [])
    takeover.dismissed.clear()
    try:
        window.weather.alerts = _warning(
            "Tornado Warning", "Extreme", "Immediate", "TO.W3")
        window._paint_weather()
        check(takeover.get_visible(), "the warning never went up")

        # It ends. Nobody pressed anything.
        window.weather.alerts = []
        window._paint_weather()
        check(not takeover.get_visible(),
              "a warning that is no longer in force stayed on the screen")
        check(not takeover.dismissed,
              f"taking down an expired warning recorded it as dismissed "
              f"({takeover.dismissed}), so the next issuance of the same "
              f"storm would never be shown")

        # And the same storm, reissued, is shown again.
        window.weather.alerts = _warning(
            "Tornado Warning", "Extreme", "Immediate", "TO.W3")
        window._paint_weather()
        check(takeover.get_visible(),
              "a reissued warning that nobody had ever dismissed was "
              "suppressed")
    finally:
        window.weather.alerts = kept
        takeover.dismissed.clear()
        window._paint_weather()


def test_warnings_are_asked_about_on_their_own_clock(app) -> None:
    """A forecast that is still fresh must not mean no request for warnings.

    They rode on the weather worker, which returns early while the reading is
    less than fifteen minutes old, so in that window no request was made at
    all and a warning issued inside it did not reach the screen until the
    temperature went stale. On a greeter that had just started with a warm
    cache it never arrived.

    Found on the hardware, where the takeover appeared only after the weather
    cache was deleted. The first reading of that was that the takeover did not
    work, which is the more alarming way to find out.
    """
    window, _ = build(app, [])
    if window.widgets.get("weather") is None or window.weather is None:
        NOT_COVERED.append("the warning clock: this build has no weather")
        return
    asked: list[tuple] = []
    kept = (_app.Worker, _app.ALERTS.fetch, window.behaviour,
            window.weather.taken)
    try:
        _app.Worker = Immediate
        _app.ALERTS.fetch = (lambda lat, lon, **_kw:
                             asked.append((lat, lon)) or [])
        window.behaviour = dict(window.behaviour, weather="on", alerts="on")

        # Unambiguously fresh, which is exactly the state that used to mean
        # no request was made.
        window.weather.taken = time.time()
        check(window.weather.fresh,
              "the fixture reading is not fresh, so this test is not in the "
              "state the bug needed")
        window._alerts_busy = False
        window.refresh_alerts()
        check(asked == [(window.weather.latitude, window.weather.longitude)],
              f"a warning refresh against a fresh reading asked {asked!r} "
              f"rather than one question about where the reading came from")

        # And the switch still turns it off.
        asked.clear()
        window.behaviour = dict(window.behaviour, alerts="off")
        window._alerts_busy = False
        window.refresh_alerts()
        check(asked == [],
              "the warning clock keeps asking on a machine where emergency "
              "alerts are switched off")
    finally:
        (_app.Worker, _app.ALERTS.fetch, window.behaviour,
         window.weather.taken) = kept


def test_the_warning_clock_does_not_read_the_forecast_clock(app) -> None:
    """The shape that caused it, kept out.

    Written on the tree rather than the text because the words `fresh` and
    `stale` appear in the comments explaining why they are not consulted.
    """
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(
        inspect.getsource(GreeterWindow.refresh_alerts)))
    read = {node.attr for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)}
    for name in ("fresh", "age"):
        check(name not in read,
              f"refresh_alerts reads .{name}, so warnings are back on the "
              f"forecast's clock and a fresh reading means no request")


def test_the_screen_says_what_a_lockout_is(app) -> None:
    """Four wrong passwords, and the fourth message is not the first one.

    The stack below locks an account after a few of these. Saying "that
    password did not work" for the fourth time running describes a broken
    machine rather than one protecting somebody, and the difference is a
    sentence built from the policy the machine is actually running.
    """
    window, _ = build(app, [])
    kept = (SET.lockout_policy, window._refusals, window._refused_for)
    try:
        SET.lockout_policy = lambda *_a, **_k: (3, 600)
        window._refusals = 0
        window._refused_for = ""
        window.chosen = None
        window.typed_name = "ada"

        first = window._refusal_words()
        equal(first, C.WRONG, "the first refusal does not say the plain thing")

        second = window._refusal_words()
        check(second != first and C.LOCKOUT_SOON in second,
              f"the attempt before the lockout says {second!r}, so nobody is "
              f"warned that the next one costs them ten minutes")

        third = window._refusal_words()
        check(third == C.locked_words(600),
              f"the attempt that locks the account says {third!r}")
        check("10" in third,
              f"the lockout message does not say how long it lasts: {third!r}")

        # And it stays said, rather than reverting to the plain refusal.
        check(window._refusal_words() == C.locked_words(600),
              "the message after the lockout went back to saying the "
              "password was wrong, which is the original bug")

        # A different person starts again. Without this the count carries over
        # and the screen tells somebody their account is locked when it is not.
        window.typed_name = "grace"
        equal(window._refusal_words(), C.WRONG,
              "the refusal count carried over to a different account")
    finally:
        SET.lockout_policy, window._refusals, window._refused_for = kept


def test_no_lockout_is_described_where_none_is_configured(app) -> None:
    """A login screen explaining a rule it invented is worse than a silent one."""
    window, _ = build(app, [])
    kept = (SET.lockout_policy, window._refusals, window._refused_for)
    try:
        SET.lockout_policy = lambda *_a, **_k: None
        window._refusals = 0
        window._refused_for = ""
        window.chosen = None
        window.typed_name = "ada"
        for attempt in range(5):
            equal(window._refusal_words(), C.WRONG,
                  f"attempt {attempt + 1} on a machine with no lockout "
                  f"described one anyway")
    finally:
        SET.lockout_policy, window._refusals, window._refused_for = kept


def test_the_card_ends_the_shake_where_it_started(app) -> None:
    """A refusal that moves nothing looks like a screen that did nothing.

    The two margins move against each other so the card never asks the page
    for room it did not already have, and the curve has to land on zero: a
    card left one pixel off centre is a card somebody notices for the rest of
    the session.
    """
    steps = 200
    check(_app.shake_offset(0.0) == 0,
          f"the shake starts {_app.shake_offset(0.0)} pixels off centre")
    check(_app.shake_offset(1.0) == 0,
          f"the shake ends {_app.shake_offset(1.0)} pixels off centre, and "
          f"stays there")
    worst = max(abs(_app.shake_offset(n / steps)) for n in range(steps + 1))
    check(0 < worst <= _app.SHAKE_PIXELS,
          f"the shake reaches {worst} pixels against a margin of "
          f"{_app.SHAKE_PIXELS}, so the card asks the page for room it does "
          f"not have and everything around it moves")
    # It has to actually go both ways, or it is a lurch rather than a shake.
    check(min(_app.shake_offset(n / steps) for n in range(steps + 1)) < 0,
          "the shake only ever moves one way")

    window, _ = build(app, [])
    card = window.widgets.get("password.card")
    check(card is not None, "the sign in card is not named, so nothing shakes")
    if card is not None:
        equal(card.get_margin_start() + card.get_margin_end(),
              _app.SHAKE_PIXELS * 2,
              "the card's margins do not add up to the room the shake needs")


def test_reduced_motion_means_none_of_it(app) -> None:
    """Off is a request for no animation, not for a faster one."""
    banner = AU.Banner()
    banner.animate = False
    banner.set_margin_top(-99)
    banner.set_opacity(0.0)
    banner._arrive()
    equal(banner.get_opacity(), 1.0,
          "the strip was left transparent on a machine with motion off")
    equal(banner.get_margin_top(), 14,
          "the strip was left off its mark on a machine with motion off")
    check(banner._arrival is None,
          "the strip built an animation on a machine that asked for none")

    takeover = AU.Takeover()
    takeover.animate = False
    takeover.set_opacity(0.0)
    takeover._arrive()
    equal(takeover.get_opacity(), 1.0,
          "the warning screen was left transparent on a machine with motion "
          "off, which is a red screen nobody can read")
    # The end state alone proves nothing here. libadwaita skips an animation
    # on a widget with no frame clock, so an unguarded `_arrive` lands on full
    # opacity too and the first version of this passed with the guard deleted.
    # What differs is whether an animation was ever built.
    check(takeover._arrival is None,
          "the warning screen built an animation on a machine that asked for "
          "none, so reduced motion got a fast fade rather than no fade")

    # And with motion on, one is built, or the check above passes by the
    # animation never existing at all.
    moving = AU.Takeover()
    moving.animate = True
    moving._arrive()
    check(moving._arrival is not None,
          "no animation is built even with motion on, so nothing here fades")


def test_the_air_tile_appears_only_with_a_reading(app) -> None:
    """The least important tile on the panel, and an empty one is worse than none."""
    window, _ = build(app, [])
    panel = window.widgets.get("weather.panel")
    if panel is None or window.weather is None:
        NOT_COVERED.append("the air tile: this build has no weather panel")
        return
    kept = (window.weather.air_index, window.weather.air_pm)
    try:
        window.weather.air_index = None
        window._paint_weather()
        check(not panel.air.get_visible(),
              "an air quality tile with nothing in it was left on the panel")

        window.weather.air_index = 128
        window._paint_weather()
        check(panel.air.get_visible(), "a real air reading drew no tile")
        equal(panel.air.value.get_label(), "128",
              "the air tile does not show the index")
        note = panel.air.note.get_label()
        check("(" in note and ")" in note,
              f"the air note does not carry the band's own name: {note!r}")
        check(note != C.WEATHER_AIR_NOTE,
              "the air note was never filled in")
    finally:
        window.weather.air_index, window.weather.air_pm = kept
        window._paint_weather()


def test_the_shade_says_what_the_sky_is_doing(app) -> None:
    """The faint line under the clock, and only while there is weather.

    Worth a runtime assertion rather than a unit one because the failure it
    caught was silent in exactly the way a unit test would have missed:
    `outlook._ahead` skips any hour it cannot compare against the clock it is
    given, so a naive clock against an aware forecast skips every hour and the
    line simply never appears. No traceback, no empty row, nothing.
    """
    window, _ = build(app, [])
    line = window.widgets.get("shade.weather")
    if line is None or window.weather is None:
        NOT_COVERED.append("the shade weather line: this build has no weather")
        return
    words = window.widgets["shade.weather.words"]
    kept = [hour.condition for hour in window.weather.hours]
    try:
        # The seeded reading is rain, which is weather.
        window._paint_weather()
        check(line.get_visible(),
              "the sky is raining and the shade says nothing about it")
        said = words.get_label()
        check(said, "the weather line is drawn with nothing written on it")
        check("until" in said or said in W_WORDS,
              f"the line reads {said!r}, which is neither a spell with an end "
              f"on it nor one without")

        # A clear sky is not an event.
        for hour in window.weather.hours:
            hour.condition = WX.CLEAR
        window._paint_weather()
        check(not line.get_visible(),
              "a clear sky put a line under the clock, which spends somebody's "
              "attention on a fact they can get by turning their head")
    finally:
        for hour, condition in zip(window.weather.hours, kept):
            hour.condition = condition
        window._paint_weather()


def test_an_advisory_stays_in_the_panel(app) -> None:
    """The quiet tier is not promoted.

    A heat advisory is worth a row somebody can open a panel and read. It is
    not worth a strip across a login screen, and it is certainly not worth the
    screen. If this ever fails, San Antonio in August is a permanent banner.
    """
    window, _ = build(app, [])
    if window.widgets.get("weather") is None or window.weather is None:
        NOT_COVERED.append("the advisory tier: this build has no weather")
        return
    takeover = window.widgets["warning.takeover"]
    banner = window.widgets["warning.banner"]
    kept = list(window.weather.alerts or [])
    try:
        window.weather.alerts = _warning(
            "Heat Advisory", "Moderate", "Expected", "HT.Y")
        window._paint_weather()
        check(not takeover.get_visible(),
              "a heat advisory took over the login screen")
        check(not banner.get_visible(),
              "a heat advisory put a strip across the login screen")

        # And the middle tier, which is the one that decides whether this
        # feature is usable in a place with weather. A severe thunderstorm
        # warning gets the strip and must never get the screen: San Antonio
        # has several a week, and a login screen that goes full red for each
        # of them is a login screen people learn to hit a key at without
        # reading, which is the whole failure this design exists to avoid.
        window.weather.alerts = _warning(
            "Severe Thunderstorm Warning", "Severe", "Expected", "SV.W")
        window._paint_weather()
        check(banner.get_visible(),
              "a severe thunderstorm warning said nothing at all on the "
              "screen, so the middle tier has no surface")
        check(not takeover.get_visible(),
              "a severe thunderstorm warning took over the whole screen, "
              "which in a thundery week is a screen nobody reads any more")
        check("Severe Thunderstorm" in banner.event.get_label(),
              f"the strip says {banner.event.get_label()!r}")
    finally:
        window.weather.alerts = kept
        window._paint_weather()


def test_a_warning_outlives_a_forecast_that_did_not_answer(app) -> None:
    """Two services, two facts, and one must not swallow the other.

    The panel already had this bug once: `show_report` returns early when
    there is no temperature, and everything below that return stopped running,
    including the warnings, which come from a different service entirely. The
    same early return exists in `_paint_weather`, so the same mistake is
    available here and this is what stops it being made twice.
    """
    window, _ = build(app, [])
    if window.widgets.get("weather") is None or window.weather is None:
        NOT_COVERED.append("the dead forecast case: this build has no weather")
        return
    takeover = window.widgets["warning.takeover"]
    kept_alerts = list(window.weather.alerts or [])
    kept_now = window.weather.now.temperature
    takeover.dismissed.clear()
    try:
        window.weather.now.temperature = None
        window.weather.alerts = _warning(
            "Tornado Warning", "Extreme", "Immediate", "TO.W2")
        window._paint_weather()
        check(takeover.get_visible(),
              "the forecast service not answering also swallowed the tornado "
              "warning, which came from somewhere else entirely")
    finally:
        window.weather.now.temperature = kept_now
        window.weather.alerts = kept_alerts
        takeover.dismissed.clear()
        window._paint_weather()


def test_the_warning_key_is_read_before_anything_else(app) -> None:
    """On CAPTURE, so a focused password field does not eat it first.

    Bubbling would mean the first letter somebody types goes into the entry
    and clears the warning at the same time, and they never find out what it
    said.
    """
    window, _ = build(app, [])
    # By name, not by looking for any controller in the capture phase. GTK
    # installs one of its own on the window, so the first version of this
    # found that one and passed with the phase deleted from ours.
    guard = None
    for controller in window.observe_controllers():
        if controller.get_name() == "aurade-warning-guard":
            guard = controller
    check(guard is not None,
          "the warning's own key controller is not on the window at all")
    if guard is not None:
        check(guard.get_propagation_phase() == Gtk.PropagationPhase.CAPTURE,
              f"the warning key controller runs in "
              f"{guard.get_propagation_phase().value_nick}, so a focused "
              f"password field reads the keystroke first and the takeover is "
              f"cleared by a character nobody meant to spend on it")


def test_return_on_the_shade_lifts_it_rather_than_opening_the_weather(app) -> None:
    """The bug somebody hit by pressing Return at their own login screen.

    The shade carries live pills and the weather one is interactive on purpose.
    A key controller in the default bubble phase is asked after the focused
    widget, so Return went to the weather and the shade never lifted. Somebody
    pressing Return to sign in got a forecast instead.

    This asserts the phase rather than the outcome, because the outcome cannot
    tell the two versions apart: the test compositor maps the account rows
    before lift() runs, so focus lands on a row either way and Return works in
    the harness while failing on the machine. Five mutations against an
    outcome-shaped version of this went uncaught, which is how the first
    attempt at this fix shipped without fixing anything.
    """
    window, service = build(app, [], lifted=False)
    try:
        shade_key = None
        for controller in window.observe_controllers():
            if controller.get_name() == "aurade-shade-key":
                shade_key = controller
        check(shade_key is not None,
              "the shade's own key controller is not on the window at all")
        if shade_key is not None:
            phase = shade_key.get_propagation_phase()
            check(phase == Gtk.PropagationPhase.CAPTURE,
                  f"the shade key controller runs in {phase.value_nick}, so a "
                  f"focused pill answers Return first and the lock screen opens "
                  f"the weather instead of letting somebody sign in")
        # And the handler still only claims the keystroke while the shade is
        # down, or capture would eat every character of a password.
        window.shade_up = True
        check(window._on_key(None, Gdk.KEY_a, 0, 0) is False,  # noqa: SLF001
              "the shade key controller swallows keys after the shade is up, "
              "which on capture means nobody can type a password")
    finally:
        pump()


def test_the_shelf_holds_the_weather_beside_the_system(app) -> None:
    """Two pills, not one, and the weather to the left of the system.

    They answer separate questions and so they are separate presses. Folding
    the temperature into the system panel would mean somebody checking whether
    to take a coat has to open the menu that also offers to shut the machine
    down.
    """
    window, _ = build(app, [])
    shelf = window.widgets.get("shelf")
    check(shelf is not None, "the bottom right corner has no shelf")
    if shelf is None:
        return
    pills = []
    child = shelf.get_first_child()
    while child is not None:
        pills.append(child)
        child = child.get_next_sibling()
    equal(len(pills), 2, "the shelf does not hold two pills")
    check(window.widgets.get("weather") is pills[0],
          "the weather pill is not the first thing on the shelf")
    check(window.widgets.get("status") is pills[1],
          "the system pill is not the last thing on the shelf")
    for pill in pills:
        check(pill.has_css_class("aurade-status-area"),
              "a pill on the shelf has no ground to be a pill with")


def test_the_weather_pill_says_what_it_knows(app) -> None:
    window, _ = build(app, [])
    if window.widgets.get("weather") is None:
        FAILURES.append("the weather was switched on and no pill was built")
        return
    pump()
    equal(window.widgets["weather.degrees"].get_label(), "25\N{DEGREE SIGN}",
          "the pill does not show the temperature it was given")
    mark = window.widgets["weather.mark"]
    equal(mark.condition, WX.THUNDER, "the pill draws the wrong sky")
    # The place is on the description rather than the face, because a pill on
    # a photograph has room for a mark and a number and nothing else.
    said = window._weather_sentence(window.weather, "c")
    check("Ardsley" in said,
          f"the pill never says where the weather is (said {said!r})")
    check("25" in said, f"the pill never says the temperature (said {said!r})")
    check("Thunderstorm" in said or "thunder" in said.lower(),
          f"the pill never says what the sky is doing (said {said!r})")
    nowhere = WX.Report(taken=time.time(),
                        now=WX.Now(temperature=4.0, condition=WX.SNOW))
    check("in " not in window._weather_sentence(nowhere, "c"),
          "a reading with no place named claimed to be somewhere")


def test_the_weather_panel_fills_itself_in(app) -> None:
    window, _ = build(app, [])
    panel = window.widgets.get("weather.panel")
    if panel is None:
        FAILURES.append("the weather was switched on and no panel was built")
        return
    pump()
    equal(panel.place.get_label(), "Ardsley, NY", "the panel lost the place")
    equal(panel.degrees.get_label(), "25\N{DEGREE SIGN}",
          "the panel lost the temperature")
    equal(panel.source.get_label(), "National Weather Service",
          "the panel does not credit the service it got the reading from")
    check(panel.narrative.get_visible(),
          "the forecaster's own paragraph was hidden")
    equal(panel.humidity.value.get_label(), "77%", "the humidity tile is empty")
    check("21" in panel.humidity.note.get_label(),
          "the dew point never reached its tile")
    # The contract rather than the literal. The note leads with what the
    # number means for somebody standing outside and ends with the official
    # band name in brackets, and pinning the whole sentence here means the
    # copy cannot be improved without a test failure that says nothing.
    # The drawn charts are the only place the forecast exists, so they
    # have to say it out loud as well as draw it.
    #
    # `Drawn` marks everything PRESENTATION, which is right for a glyph
    # sitting beside a label that already carries the number and wrong for
    # a chart. Left that way the barometric pressure was announced and the
    # entire week was not. The role matters as much as the words: a widget
    # left as PRESENTATION is skipped whatever properties it carries, so a
    # description alone would read correct and do nothing.
    for name, chart in (("hourly", panel.hours), ("week", panel.days),
                        ("daylight", panel.sun)):
        check(chart.get_accessible_role() != Gtk.AccessibleRole.PRESENTATION,
              f"the {name} chart is still marked decorative, so nothing "
              f"it says will be read out")
    spoken_hours = panel.hours._spoken()
    check("\N{DEGREE SIGN}" in spoken_hours,
          f"the hourly chart says no temperatures: {spoken_hours!r}")
    check(spoken_hours.count(".") >= 4,
          f"the hourly chart says almost nothing: {spoken_hours!r}")
    spoken_days = panel.days._spoken(WUI.usable_days(panel.days.days))
    for word in ("Today", "\N{DEGREE SIGN}"):
        check(word in spoken_days,
              f"the week chart never says {word!r}: {spoken_days!r}")

    uv_note = panel.ultraviolet.note.get_label()
    check(uv_note.endswith("(High)"),
          f"the ultraviolet tile lost its official band name, said {uv_note!r}")
    check(len(uv_note) > len("(High)") + 8,
          f"the ultraviolet tile says only its band name, {uv_note!r}")
    check(panel.days.days, "the week never reached the panel")
    check(panel.hours.hours, "the hours never reached the panel")
    check("Today" in panel.days.names,
          "the first row of the week is not called Today")
    check("Tomorrow" in panel.days.names,
          "the second row of the week is not called Tomorrow")
    check(panel.updated.get_label().startswith("Updated"),
          "the panel does not say how old its reading is")


def test_the_weather_panel_survives_knowing_nothing(app) -> None:
    """The case that happens on a machine with no route out.

    A panel that raises here is a login screen that will not draw, which is
    the worst outcome available: the weather is the least important thing on
    this screen and it must never be able to take the rest of it down.
    """
    window, _ = build(app, [])
    panel = window.widgets.get("weather.panel")
    if panel is None:
        return
    panel.show_report(None, "c")
    pump()
    equal(panel.degrees.get_label(), "--",
          "a panel with no reading claimed to have one")
    check(panel.condition.get_label(),
          "a panel with no reading said nothing at all about why")
    empty = WX.Report(taken=time.time())
    panel.show_report(empty, "c")
    pump()
    equal(panel.degrees.get_label(), "--",
          "a report with no temperature in it was drawn as though it had one")


def test_the_weather_panel_opens(app) -> None:
    window, _ = build(app, [])
    button = window.widgets.get("weather")
    if button is None:
        return
    popover = button.get_popover()
    check(popover is not None, "the weather pill opens nothing")
    if popover is None:
        return
    popover.popup()
    pump_until(popover.get_visible)
    check(popover.get_visible(), "the weather panel did not open")
    check(popover.has_css_class("aurade-weather-panel"),
          "the weather panel is not styled as one")
    popover.popdown()


# --- the shade -------------------------------------------------------------

def test_high_contrast_draws_no_photograph(app) -> None:
    """The one surface high contrast cannot make safe by stating its ground.

    Every other translucent thing on this screen goes opaque. A photograph
    cannot: the clock and the date sit directly on it with a veil between,
    and a veil is the soft edge high contrast exists to remove. So the picture
    goes, and the card that describes it goes with it rather than captioning
    something nobody can see.
    """
    window, _ = build(app, [], lifted=False)
    plain = Wallpaper(True, plain=True)
    check(not plain.present,
          "a plain wallpaper still reports a photograph to draw over")
    ordinary = Wallpaper(True, plain=False)
    equal(ordinary.present, ordinary.picture is not None,
          "an ordinary wallpaper disagrees with itself about having a picture")

    # And the card follows the picture. Captioning a photograph that is not
    # being drawn is a card describing a blank screen.
    was, card = window.wallpaper, window.widgets["card"]
    try:
        window.wallpaper = plain
        window._show_card()  # noqa: SLF001
        pump()
        check(not card.get_visible(),
              "the card described a photograph that high contrast had removed")
    finally:
        window.wallpaper = was
        window._show_card()  # noqa: SLF001


def test_the_greeter_opens_on_the_shade(app) -> None:
    """Not on the account list. The first thing anybody sees is a photograph.

    Asserted against a window that has been reset to its starting state rather
    than one the helper has just pointed at a page, which is the whole reason
    `lower_shade` exists.
    """
    window, _ = build(app, [], lifted=False)
    equal(OPENED["page"], "shade",
          "the greeter does not open on the shade")
    equal(OPENED["lifted"], False,
          "the greeter starts up thinking it has already been lifted")
    card = window.widgets.get("card")
    if window.wallpaper.present:
        check(card is not None and card.get_visible(),
              "the shade does not say what the photograph is")
    else:
        # Said rather than skipped silently. A machine with no picture set has
        # nothing for the card to identify, and that is the correct behaviour,
        # but a run that proved it is not a run that proved the card works.
        check(card is not None and not card.get_visible(),
              "there is no photograph and the card claimed to identify one")
        NOT_COVERED.append("the photo card, because this tree has no pictures")
    check(window.widgets["shade.clock"].get_label(),
          "the shade has no time on it")
    check(window.widgets["shade.greeting"].get_label(),
          "the shade does not greet anybody")


def test_lifting_the_shade_brings_the_accounts(app) -> None:
    window, _ = build(app, [], lifted=False)
    check(window.lift(), "the shade would not lift")
    pump(60)
    equal(window.stack.get_visible_child_name(), "accounts",
          "lifting the shade did not reach the account list")
    check(window.shade_up, "the shade lifted and did not say so")
    check(not window.lift(),
          "the shade lifted a second time, which would replay the entrance")
    # Hidden, not merely faded. A widget at zero opacity is still in the
    # accessibility tree, so a card left behind is a screen reader describing
    # a photograph to somebody who is being asked to choose an account.
    card = window.widgets.get("card")
    check(card is not None and not card.get_visible(),
          "the card faded out and was left on the accounts page")


def test_the_clock_does_not_move_when_the_shade_lifts(app) -> None:
    """The one measurement that stands for the whole seam.

    Both pages are centred in the same space, so two pages of the same height
    put their first child, the clock, on the same pixel. When they differed the
    clock jumped about twenty five pixels on lifting, which is small enough to
    look like a rendering fault and large enough to see.
    """
    window, _ = build(app, [], lifted=False)
    pump(20)
    _, shade_high, _, _ = window.widgets["shade.box"].measure(
        Gtk.Orientation.VERTICAL, -1)
    _, accounts_high, _, _ = window.widgets["accounts.box"].measure(
        Gtk.Orientation.VERTICAL, -1)
    equal(shade_high, accounts_high,
          "the shade and the account list are different heights, so the clock "
          "moves when the shade lifts")


def test_the_greeting_is_the_same_on_both_pages(app) -> None:
    window, _ = build(app, [], lifted=False)
    pump(10)
    equal(window.widgets["accounts.heading"].get_label(),
          window.widgets["shade.greeting"].get_label(),
          "the greeting rewrites itself when the shade lifts")


def test_the_clocks_agree(app) -> None:
    """One reading on both faces, not two calls a millisecond apart."""
    window, _ = build(app, [], lifted=False)
    pump(10)
    equal(window.widgets["shade.clock"].get_label(),
          window.widgets["clock"].get_label(),
          "the two clock faces disagree")
    equal(window.widgets["shade.date"].get_label(),
          window.widgets["date"].get_label(),
          "the two date lines disagree")


def test_the_accounts_arrive_rather_than_appear(app) -> None:
    window, _ = build(app, [], lifted=False)
    rows = _rows(window)
    check(rows, "there are no rows to arrive")
    check(all(row.has_css_class("aurade-arrive") for row in rows),
          "a row is not set up to arrive, so it will simply appear")
    check(not any(row.has_css_class("aurade-arrived") for row in rows),
          "a row had already arrived before the shade was lifted")
    window.lift()
    # One at a time, in order. Immediately after lifting, the last row cannot
    # have arrived yet, which is what makes this a stagger rather than a fade.
    check(not rows[-1].has_css_class("aurade-arrived"),
          "every row arrived at once, so the list appears rather than arrives")
    pump(80)
    check(all(row.has_css_class("aurade-arrived") for row in rows),
          "a row never arrived, so it is invisible on the account list")


def test_stillness_means_the_accounts_are_simply_there(app) -> None:
    """Honoured by not moving, never by moving less."""
    settings = Gtk.Settings.get_default()
    was = settings.get_property("gtk-enable-animations")
    settings.set_property("gtk-enable-animations", False)
    try:
        window, _ = build(app, [], lifted=False)
        window.lift()
        # No pump. The whole assertion is that nothing was scheduled: with
        # animations off the rows are already there on the frame the shade
        # lifts, and letting a fifth of a second pass would let a stagger
        # finish and look exactly the same.
        rows = _rows(window)
        check(rows and all(row.has_css_class("aurade-arrived") for row in rows),
              "with animations off the rows still waited their turn to arrive")
        check(not window._arrivals,  # noqa: SLF001
              "with animations off the arrival was still put on a timer")
        card = window.widgets.get("card")
        check(card is not None and not card.get_visible(),
              "with animations off the card was still fading rather than gone")
    finally:
        settings.set_property("gtk-enable-animations", was)


def test_a_press_on_the_pills_does_not_lift_the_shade(app) -> None:
    """Checking the weather should not require signing in first."""
    window, _ = build(app, [], lifted=False)
    shelf = window.widgets.get("shelf")
    check(shelf is not None, "there is no shelf")
    if shelf is None:
        return
    ok, bounds = shelf.compute_bounds(window)
    check(ok, "the shelf has no bounds to press inside")
    if not ok:
        return
    window._on_press(  # noqa: SLF001
        None, 1,
        bounds.origin.x + bounds.size.width / 2.0,
        bounds.origin.y + bounds.size.height / 2.0)
    pump()
    check(not window.shade_up,
          "pressing the weather pill signed the machine's shade away")
    window._on_press(None, 1, 40.0, 40.0)  # noqa: SLF001
    pump()
    check(window.shade_up, "pressing the photograph did not lift the shade")


def test_the_card_says_only_what_the_manifest_carries(app) -> None:
    window, _ = build(app, [], lifted=False)
    card = window.widgets["card"]
    card.show_picture({"title": "Bagan, Myanmar", "zone": "Asia/Yangon",
                       "note": "Brick temples in the haze.",
                       "fact": "Myanmar keeps its clocks half an hour off."})
    pump()
    check(card.title.get_visible() and card.note.get_visible()
          and card.fact.get_visible(),
          "a picture that is somewhere did not fill the card in")
    card.show_picture({"title": "A river between hills", "zone": "",
                       "note": "A river running out of frame.", "fact": ""})
    pump()
    check(card.title.get_visible(), "a picture of nowhere lost its title")
    check(not card.when.get_visible(),
          "a picture with no time zone was given a time")
    check(not card.fact.get_visible(),
          "a picture of nowhere was given a fact about somewhere")
    check(not card.show_picture(None),
          "a card with no picture claimed to have something to show")


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
    if NOT_COVERED:
        for missing in sorted(set(NOT_COVERED)):
            print(f"  not covered: {missing}")
    print("greeter runtime test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
