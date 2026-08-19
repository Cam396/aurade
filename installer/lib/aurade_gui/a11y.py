"""What the installer says to a screen reader, as a small vocabulary.

Before this file there were two accessibility calls in two and a half thousand
lines of front end, and everything drawn rather than written was invisible.
That is most of the identity: the aurora, the swoop, the mark, the wordmark,
the progress ribbon, the signal arcs, the icon tile on every row. A blind user
got a page of unlabelled boxes and, for the ten minutes of an install, silence.

Four verbs, because scattering `update_property` calls through the front end
produces the situation this is fixing: nobody can tell what has been done and
what has been forgotten. Everything drawn goes through one of these, and the
runtime test can then assert that nothing drawn was missed.

The distinction that matters is between decoration and information, and it is
not obvious from the widget. The mark and the aurora are decoration: they
repeat what the words already say, and reading them out is noise. The progress
ribbon and the signal arcs are information that happens to be drawn rather than
written, and dropping them loses something a sighted user has. So `decorative`
and `described` are both one line, and choosing between them is the whole job.

Everything degrades to a no-op rather than raising. An installer that crashes
on an image with an older GTK because of an accessibility call has made things
worse for exactly the person it was meant to help.
"""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk  # noqa: E402


def _can_announce() -> bool:
    """Whether saying something out loud is safe here, not merely possible.

    Two questions, and the second one cost a week.

    The method has to exist, which means GTK 4.14 or newer. An older image
    keeps every label and loses only the running commentary.

    And there has to be something listening. GTK hands an announcement to an
    assistive technology over the session bus, and on this installer's live
    image there is no session bus: the compositor is started by a systemd
    oneshot with no login session behind it. Calling it anyway segfaults, and a
    segfault is not an exception, so the `try` around it caught nothing:

        Fatal Python error: Segmentation fault
          File "aurade_gui/a11y.py", line 113 in announce
          File "aurade_gui/app.py", line 3431 in _announce_page
          File "aurade_gui/app.py", line 3443 in refresh
          File "aurade_gui/app.py", line 3745 in on_forward

    That is every page change in the graphical installer. Pressing Get started
    ended the process, on every machine, and it took a week to find because the
    file this crash is in is the one whose whole purpose is to degrade quietly.
    The docstring above already promised it never raises. It never raised.

    Nothing is lost by the check. An announcement with no assistive technology
    listening is a sentence said to an empty room, so the case being refused is
    the case that was worth nothing and cost everything.

    `AURADE_ANNOUNCE` overrides in both directions, for a machine where the bus
    is reached some other way and for reproducing this.
    """
    if not hasattr(Gtk.Accessible, "announce"):
        return False
    forced = os.environ.get("AURADE_ANNOUNCE", "")
    if forced in ("0", "1"):
        return forced == "1"
    if os.environ.get("GTK_A11Y", "") == "none":
        return False
    return bool(os.environ.get("AT_SPI_BUS_ADDRESS")
                or os.environ.get("DBUS_SESSION_BUS_ADDRESS"))


#: Whether this installer may announce. Read once, because the answer is about
#: the session and the session does not change under it.
CAN_ANNOUNCE = _can_announce()


def decorative(widget: Gtk.Widget) -> Gtk.Widget:
    """Mark something drawn that a screen reader should skip entirely.

    For anything whose meaning is already carried by adjacent text. The icon
    tile beside a row titled "Storage" does not need to announce itself as an
    image; it needs to not interrupt the word "Storage".
    """
    try:
        widget.set_property("accessible-role", Gtk.AccessibleRole.PRESENTATION)
    except Exception:  # pragma: no cover - older GTK, or a widget that refuses
        pass
    return widget


def described(widget: Gtk.Widget, label: str,
              description: str = "",
              role: Gtk.AccessibleRole | None = None) -> Gtk.Widget:
    """Give something drawn the words a sighted user gets from looking at it.

    `label` is what the thing is. `description` is what it currently says, and
    is the part that has to be updated when the thing changes, because a label
    that never changes on a widget that does is worse than no label.
    """
    try:
        if role is not None:
            widget.set_property("accessible-role", role)
        properties = [Gtk.AccessibleProperty.LABEL]
        values = [label]
        if description:
            properties.append(Gtk.AccessibleProperty.DESCRIPTION)
            values.append(description)
        widget.update_property(properties, values)
    except Exception:  # pragma: no cover
        pass
    return widget


def meter(widget: Gtk.Widget, label: str, now: float,
          lo: float = 0.0, hi: float = 100.0, text: str = "") -> Gtk.Widget:
    """Report a drawn progress indicator as a progress indicator.

    `text` is what a reader should hear instead of the raw number, because
    "fifty eight" is a worse answer to "how far along is it" than "installing
    the base system, fifty eight percent".
    """
    try:
        widget.set_property("accessible-role", Gtk.AccessibleRole.PROGRESS_BAR)
        properties = [Gtk.AccessibleProperty.VALUE_NOW,
                      Gtk.AccessibleProperty.VALUE_MIN,
                      Gtk.AccessibleProperty.VALUE_MAX,
                      Gtk.AccessibleProperty.LABEL]
        values = [float(now), float(lo), float(hi), label]
        if text:
            properties.append(Gtk.AccessibleProperty.VALUE_TEXT)
            values.append(text)
        widget.update_property(properties, values)
    except Exception:  # pragma: no cover
        pass
    return widget


def announce(widget: Gtk.Widget, message: str, urgent: bool = False) -> bool:
    """Say something out loud without moving focus.

    Returns whether it went anywhere, so a caller can fall back rather than
    assume. `urgent` is for a failure, which should interrupt; everything else
    waits its turn, because a stage change every ninety seconds that talks over
    what somebody is already reading is worse than one that does not.
    """
    if not CAN_ANNOUNCE or not message:
        return False
    try:
        priority = (Gtk.AccessibleAnnouncementPriority.HIGH if urgent
                    else Gtk.AccessibleAnnouncementPriority.MEDIUM)
        widget.announce(message, priority)
        return True
    except Exception:  # pragma: no cover
        return False
