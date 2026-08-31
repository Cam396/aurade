"""The two loud tiers, drawn: a strip that waits, and a screen that does not.

The panel already carries every admitted warning as a row somebody has to open
a popover to read. That is right for a heat advisory and wrong for a tornado,
so the two tiers above it come out of the panel and onto the screen.

`Banner` is a strip. It does not move, does not take focus, and does not cover
the password field. It is also the takeover's dismiss state, which is why it
exists first: building it second would mean building it twice.

`Takeover` is the screen. Extreme and Immediate, which across the whole United
States was thirteen alerts out of three hundred when this was measured. It
tints everything red, dims it, and puts the warning in the middle, and the
first key anybody presses clears it down to the banner and does not bring it
back for that same storm. Somebody standing at a locked screen during a
tornado warning may be trying to sign in to call somebody, and a warning that
cannot be got past is a warning that stopped them.

The distance and the time are shown, never used to decide. `eventMotionDescription`
is optional in the feed and plenty of offices omit it, so gating the takeover
on it would mean the screen staying quiet exactly when a warning arrived
without a tracked cell attached to it.
"""
from __future__ import annotations

import datetime as _dt

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Pango", "1.0")

from gi.repository import Adw, Gtk, Pango  # noqa: E402

#: How long the strip takes to arrive, and the screen to.
#:
#: The takeover is slower on purpose. A red screen that appears between two
#: frames reads as a fault in the machine, and somebody who thinks the screen
#: has broken does not read what it says. Arriving over a fifth of a second is
#: the difference between a crash and a decision.
BANNER_MS = 260
TAKEOVER_MS = 240

#: How far the strip falls from, in pixels above where it settles.
BANNER_DROP = 46

from . import a11y as A  # noqa: E402
from . import alerts as AL  # noqa: E402
from . import copy as C  # noqa: E402
from . import weather as W  # noqa: E402


class Mark(Gtk.DrawingArea):
    """A warning triangle, drawn rather than fetched.

    An icon name would be an icon theme dependency on a screen that runs
    before anybody has signed in, on a machine whose theme is whatever the
    installer left. Twenty lines of cairo has no such opinion.

    White on both surfaces, because both of them paint their own dark ground
    and their own white ink. This mark is never on a photograph.
    """

    def __init__(self, size: int = 18) -> None:
        super().__init__()
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_valign(Gtk.Align.CENTER)
        self.set_draw_func(self._draw)

    def _draw(self, _area, cr, width: int, height: int) -> None:
        side = min(width, height)
        cr.save()
        cr.translate((width - side) / 2.0, (height - side) / 2.0)
        cr.scale(side, side)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.96)

        # The triangle, with its corners taken off. A hard point at this size
        # renders as one dark pixel and reads as a defect.
        radius = 0.10
        points = ((0.5, 0.055), (0.955, 0.90), (0.045, 0.90))
        cr.new_path()
        for index, (x, y) in enumerate(points):
            before = points[index - 1]
            after = points[(index + 1) % 3]
            for other, first in ((before, True), (after, False)):
                dx, dy = other[0] - x, other[1] - y
                length = (dx * dx + dy * dy) ** 0.5 or 1.0
                px, py = x + dx / length * radius, y + dy / length * radius
                if first:
                    cr.line_to(px, py)
                else:
                    cr.curve_to(x, y, x, y, px, py)
        cr.close_path()
        cr.set_line_width(0.105)
        cr.set_line_join(1)  # round
        cr.stroke()

        # The bar and the dot, as one stroke each, so they scale together.
        cr.set_line_cap(1)  # round
        cr.set_line_width(0.10)
        cr.move_to(0.5, 0.40)
        cr.line_to(0.5, 0.615)
        cr.stroke()
        cr.arc(0.5, 0.755, 0.001, 0.0, 6.2832)
        cr.stroke()
        cr.restore()


def _label(words: str, style: str, *, wrap: bool = False,
           dim: bool = False, centre: bool = True) -> Gtk.Label:
    widget = Gtk.Label(label=words)
    widget.add_css_class(style)
    if dim:
        widget.add_css_class("dim-label")
    widget.set_wrap(wrap)
    if wrap:
        widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        widget.set_justify(Gtk.Justification.CENTER if centre
                           else Gtk.Justification.LEFT)
    widget.set_xalign(0.5 if centre else 0.0)
    return widget


def motion_words(alert, latitude: float, longitude: float) -> str:
    """Where the storm is and when it gets here, in one sentence.

    Empty when the warning carries no tracked cell, which is most of them.
    Empty is the right answer there: a sentence invented from a polygon
    centroid would read exactly like a measured one.
    """
    near = AL.approaching(alert, latitude, longitude)
    if near is None:
        return ""
    miles = int(round(near["miles"]))
    if not near["towards"]:
        return C.ALERT_MOTION_AWAY.format(miles=miles)
    if near["minutes"] is None:
        return C.ALERT_MOTION_TOWARDS.format(miles=miles)
    return C.ALERT_MOTION_MINUTES.format(miles=miles,
                                         minutes=near["minutes"])


def heading_words(alert) -> str:
    """The direction and speed, for the line under the distance."""
    motion = alert.motion
    if not motion:
        return ""
    # Said in words rather than in degrees, out of the table the panel
    # already uses, because nobody standing at a lock screen converts two
    # hundred and twenty five degrees into anything.
    return C.ALERT_HEADING.format(
        way=W.bearing_name(int(round(motion["bearing"]))),
        mph=int(round(motion["knots"] * 1.15078)))


class Banner(Gtk.Box):
    """One live warning, said once, across the top of the screen.

    Top rather than beside the clock, because it must not move anything. A
    strip that reflows the page it appears on is a strip that moves the
    password field out from under somebody's cursor.
    """

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.add_css_class("aurade-warning-strip")
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.START)
        self.set_margin_top(14)
        self.set_visible(False)
        self.alert = None
        #: Set by the window from the accessibility record. Off means every
        #: animation here is skipped rather than shortened, because reduced
        #: motion is a request for none of it, not for a faster version.
        self.animate = True
        self._arrival = None

        self.mark = Mark(17)
        self.append(self.mark)
        self.event = _label("", "m3-label-large", centre=False)
        self.append(self.event)
        self.detail = _label("", "m3-body-small", dim=True, centre=False)
        self.append(self.detail)

    def show_alert(self, alert, latitude: float, longitude: float) -> None:
        """Put one warning up, or take the strip away when there is none."""
        self.alert = alert
        if alert is None:
            self.set_visible(False)
            return
        # The strip says which tier it is carrying without being read. The
        # panel row for the same alert already does this; the two use
        # different classes because a row inside a popover and a strip across
        # the top of a login screen want different weights of the same idea.
        self.remove_css_class("aurade-warning-strip-urgent")
        if AL.tier(alert) == AL.TAKEOVER:
            self.add_css_class("aurade-warning-strip-urgent")
        self.event.set_label(alert.event)
        near = motion_words(alert, latitude, longitude)
        self.detail.set_label(near or alert.area or "")
        self.detail.set_visible(bool(near or alert.area))
        A.described(self, alert.event,
                    " ".join(part for part in (near, alert.headline) if part))
        already = self.get_visible()
        self.set_visible(True)
        if not already:
            self._arrive()

    def _arrive(self) -> None:
        """Down from above the edge, once, when the strip first appears.

        Margin rather than a transform, because the strip lives in an overlay
        and a transform would be clipped by it. Nothing else on the screen
        moves: it is drawn over the page, not inserted into it.
        """
        if not self.animate:
            self.set_margin_top(14)
            self.set_opacity(1.0)
            return
        self.set_opacity(0.0)

        def step(value, _user=None):
            self.set_margin_top(int(round(14 - BANNER_DROP * (1.0 - value))))
            self.set_opacity(value)

        target = Adw.CallbackAnimationTarget.new(step)
        self._arrival = Adw.TimedAnimation.new(self, 0.0, 1.0, BANNER_MS,
                                               target)
        self._arrival.set_easing(Adw.Easing.EASE_OUT_CUBIC)
        self._arrival.play()


class Takeover(Gtk.Overlay):
    """The screen, given over to one warning, until a key is pressed.

    A widget over everything rather than a dialog. A dialog is a thing the
    window manager owns, and this screen has no window manager: it is the only
    surface on a kiosk compositor and there is nothing to put a dialog above.

    An overlay rather than a box, and that is not a detail. In a box the
    warning sits wherever the slack happens to be distributed once labels have
    been hidden and shown, which put it two hundred pixels below centre the
    first time this was drawn. Here the middle asks to be centred in the whole
    screen and the footer asks to be at the bottom of it, and neither answer
    depends on the other or on how many lines the instruction ran to.
    """

    def __init__(self) -> None:
        super().__init__()
        self.add_css_class("aurade-warning-screen")
        self.set_halign(Gtk.Align.FILL)
        self.set_valign(Gtk.Align.FILL)
        self.set_visible(False)
        self.alert = None

        #: Same contract as the strip's.
        self.animate = True
        self._arrival = None

        ground = Gtk.Box()
        ground.set_hexpand(True)
        ground.set_vexpand(True)
        self.set_child(ground)

        #: Storms already got past, by the identity that survives an update.
        #:
        #: A warning is reissued as it is extended and each reissue is a new
        #: record with the same VTEC. Without this, a tornado warning updated
        #: six times covers the screen six times, and the sixth one lands on
        #: somebody who has been trying to type a password for ten minutes.
        self.dismissed: set = set()

        middle = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        middle.set_halign(Gtk.Align.CENTER)
        middle.set_valign(Gtk.Align.CENTER)
        middle.add_css_class("aurade-warning-screen-middle")

        self.mark = Mark(58)
        self.mark.set_halign(Gtk.Align.CENTER)
        middle.append(self.mark)

        self.event = _label("", "m3-display-small", wrap=True)
        self.event.add_css_class("aurade-warning-screen-event")
        middle.append(self.event)

        self.near = _label("", "m3-title-medium", wrap=True)
        middle.append(self.near)

        self.heading = _label("", "m3-body-medium", wrap=True, dim=True)
        middle.append(self.heading)

        self.instruction = _label("", "m3-body-large", wrap=True)
        self.instruction.set_max_width_chars(52)
        middle.append(self.instruction)

        self.add_overlay(middle)

        self.footer = _label(C.ALERT_DISMISS, "m3-label-medium")
        self.footer.add_css_class("aurade-warning-screen-footer")
        self.footer.set_halign(Gtk.Align.CENTER)
        self.footer.set_valign(Gtk.Align.END)
        self.footer.set_margin_bottom(40)
        self.add_overlay(self.footer)

    def wanted(self, alert) -> bool:
        """Whether this alert should take the screen at all.

        Top tier, and not one somebody has already pressed a key at. Distance
        is not consulted, deliberately: the service was asked about this exact
        point, so a warning that came back is a warning whose area contains
        the machine, and how far away the storm inside it happens to be is
        something to say rather than something to decide on.
        """
        if alert is None or AL.tier(alert) != AL.TAKEOVER:
            return False
        return self._identity(alert) not in self.dismissed

    @staticmethod
    def _identity(alert) -> str:
        return alert.identifier or f"{alert.event}/{alert.area}"

    def show_alert(self, alert, latitude: float, longitude: float) -> None:
        self.alert = alert
        self.event.set_label(alert.event)
        near = motion_words(alert, latitude, longitude)
        self.near.set_label(near or alert.area or "")
        self.near.set_visible(bool(near or alert.area))
        heading = heading_words(alert)
        self.heading.set_label(heading)
        self.heading.set_visible(bool(heading))
        words = alert.instruction or alert.headline or ""
        self.instruction.set_label(words)
        self.instruction.set_visible(bool(words))
        A.described(self, alert.event,
                    " ".join(part for part in (near, heading, words) if part))
        already = self.get_visible()
        self.set_visible(True)
        if not already:
            self._arrive()

    def _arrive(self) -> None:
        """The screen going red, over a fifth of a second rather than at once.

        Fast enough that nobody waits for it and slow enough to read as a
        decision. A warning that appears between two frames looks like the
        machine has broken, and somebody who thinks the screen is broken does
        not read what it says.
        """
        if not self.animate:
            self.set_opacity(1.0)
            return
        target = Adw.PropertyAnimationTarget.new(self, "opacity")
        self._arrival = Adw.TimedAnimation.new(self, 0.0, 1.0, TAKEOVER_MS,
                                               target)
        self._arrival.set_easing(Adw.Easing.EASE_OUT_QUAD)
        self._arrival.play()

    def clear(self) -> None:
        """Take it away without recording it as seen.

        Not the same as `dismiss`. An alert that expired while the screen was
        showing it was never got past by anybody, and marking it dismissed
        would mean a reissue of the same storm arriving in silence.
        """
        self.alert = None
        self.set_visible(False)

    def dismiss(self) -> bool:
        """Put it away, and remember that this storm has been seen.

        Returns whether anything was actually dismissed, so the caller can
        tell a keystroke that closed a warning from one that should go on to
        the password field.
        """
        if not self.get_visible():
            return False
        if self.alert is not None:
            self.dismissed.add(self._identity(self.alert))
        self.set_visible(False)
        self.alert = None
        return True
