"""Status marks this product draws, rather than names it asks a theme for.

`status.py` returns icon names like `network-wireless-signal-good-symbolic`,
and an icon name is a request. On the machine this was written on it resolves
to breeze-dark, which is KDE's set, so the login screen was rendering KDE
glyphs inside a ChromeOS desktop. On a machine with a different theme it would
render a third set. Nobody chose any of it, and a glyph carrying state is the
last place to accept whatever happens to be installed.

So the marks that carry state are drawn here, in Cairo, from the same tokens
the rest of the screen is coloured from, the way the installer already draws
its aurora and its progress ribbon. The four arc signal meter is not
reimplemented: `brand.draw_signal` is the installer's and is reused.

Marks that carry no state and would be harmless if wrong, a chevron or a
padlock, are still drawn here only because a set of glyphs that half matches
is worse than either whole.
"""
from __future__ import annotations

import math

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from . import brand as B  # noqa: E402
from . import tokens as T  # noqa: E402

#: Everything is drawn in a 24 by 24 space and scaled to the widget, so a
#: measurement here reads the same as the one beside it no matter what size
#: the mark is asked for.
DESIGN = 24.0


def _rounded(cr, x: float, y: float, width: float, height: float,
             radius: float) -> None:
    radius = min(radius, width / 2.0, height / 2.0)
    cr.new_sub_path()
    cr.arc(x + width - radius, y + radius, radius, math.radians(-90), 0)
    cr.arc(x + width - radius, y + height - radius, radius, 0, math.radians(90))
    cr.arc(x + radius, y + height - radius, radius,
           math.radians(90), math.radians(180))
    cr.arc(x + radius, y + radius, radius, math.radians(180), math.radians(270))
    cr.close_path()


class Glyph(Gtk.DrawingArea):
    """A mark that redraws when what it is reporting changes."""

    def __init__(self, size: int = 18) -> None:
        super().__init__()
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_valign(Gtk.Align.CENTER)
        self.set_halign(Gtk.Align.CENTER)
        self.set_can_focus(False)
        # A drawn mark is decoration to a screen reader. The sentence it
        # illustrates is on the label beside it, and hearing both is hearing
        # the same fact twice.
        self.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        self._dark = True
        self._scheme = T.scheme(True)
        self._state: dict = {}
        self.set_draw_func(self._on_draw)

    def set_dark(self, dark: bool) -> None:
        if dark != self._dark:
            self._dark = dark
            self._scheme = T.scheme(dark)
            self.queue_draw()

    def update(self, **state) -> None:
        if any(self._state.get(k) != v for k, v in state.items()):
            self._state.update(state)
            self.queue_draw()

    def colour(self, role: str) -> tuple[float, float, float]:
        return T.rgb(self._scheme[role])

    def _on_draw(self, _area, cr, width: int, height: int) -> None:
        size = min(width, height)
        cr.save()
        cr.translate((width - size) / 2.0, (height - size) / 2.0)
        cr.scale(size / DESIGN, size / DESIGN)
        self.draw(cr)
        cr.restore()

    def draw(self, cr) -> None:  # pragma: no cover - subclasses draw
        raise NotImplementedError


class Network(Glyph):
    """Wireless as four arcs, wired as a port, absent as a struck through arc.

    Offline is not the same mark in a paler colour. A person glancing at a
    login screen to find out why they cannot sign in needs the difference
    between weak and none to survive being looked at for a tenth of a second,
    and two greys do not.
    """

    def draw(self, cr) -> None:
        import cairo  # noqa: PLC0415

        kind = str(self._state.get("kind", ""))
        online = bool(self._state.get("online"))
        strength = int(self._state.get("strength", 0))
        lit = "on_surface" if online else "on_surface_variant"
        dim = "outline_variant"

        if kind == "wired":
            cr.set_line_width(1.7)
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            cr.set_line_join(cairo.LINE_JOIN_ROUND)
            cr.set_source_rgb(*self.colour(lit))
            _rounded(cr, 4.0, 9.0, 16.0, 9.0, 2.4)
            cr.stroke()
            cr.move_to(9.0, 9.0)
            cr.line_to(9.0, 5.0)
            cr.move_to(15.0, 9.0)
            cr.line_to(15.0, 5.0)
            cr.stroke()
            if not online:
                self._strike(cr)
            return

        # Wireless, including the case where there is no radio at all: the
        # arcs are the installer's, so the login screen and the install it
        # came from report a signal the same way.
        B.draw_signal(cr, int(DESIGN), int(DESIGN),
                      strength if online else 0,
                      self._scheme[lit], self._scheme[dim])
        if not online:
            self._strike(cr)

    def _strike(self, cr) -> None:
        import cairo  # noqa: PLC0415

        # Struck through twice, once in the background colour underneath, so
        # the line reads as a gap cut into the mark rather than as a stroke
        # lying on top of it.
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_source_rgb(*self.colour("surface"))
        cr.set_line_width(4.0)
        cr.move_to(5.0, 4.5)
        cr.line_to(19.0, 19.5)
        cr.stroke()
        cr.set_source_rgb(*self.colour("on_surface_variant"))
        cr.set_line_width(1.9)
        cr.move_to(5.5, 5.0)
        cr.line_to(18.5, 19.0)
        cr.stroke()


class Battery(Glyph):
    """A capsule that fills, with the level drawn rather than written.

    The fill is the reading. The percentage beside it is the same reading for
    anybody who cannot judge a bar, and low is carried by colour and by the
    bar being short, never by colour alone.
    """

    LOW = 15

    def draw(self, cr) -> None:
        import cairo  # noqa: PLC0415

        percent = self._state.get("percent")
        charging = bool(self._state.get("charging"))
        body_x, body_y, body_w, body_h = 2.0, 7.0, 17.0, 10.0
        inset = 1.9

        cr.set_line_width(1.5)
        cr.set_source_rgb(*self.colour("on_surface_variant"))
        _rounded(cr, body_x + 0.75, body_y + 0.75,
                 body_w - 1.5, body_h - 1.5, 2.6)
        cr.stroke()
        # The tip, which is what makes a rounded rectangle read as a battery.
        _rounded(cr, body_x + body_w + 0.6, 10.4, 2.2, 3.2, 1.0)
        cr.fill()

        if percent is None:
            return
        level = max(0, min(100, int(percent)))
        track_w = body_w - inset * 2.0
        fill_w = track_w * (level / 100.0)
        if charging:
            role = "primary"
        elif level <= self.LOW:
            role = "error"
        else:
            role = "on_surface"
        if fill_w > 0.6:
            cr.set_source_rgb(*self.colour(role))
            _rounded(cr, body_x + inset, body_y + inset,
                     max(fill_w, 1.4), body_h - inset * 2.0, 1.4)
            cr.fill()

        if charging:
            # A bolt, punched through the fill in the surface colour so it
            # stays visible whether the battery behind it is full or empty.
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_rgba(0, 0, 0, 0)
            cr.move_to(11.6, 6.2)
            cr.line_to(7.4, 12.6)
            cr.line_to(10.3, 12.6)
            cr.line_to(9.4, 17.8)
            cr.line_to(13.8, 11.2)
            cr.line_to(10.9, 11.2)
            cr.close_path()
            cr.fill()
            cr.set_operator(cairo.OPERATOR_OVER)


class Brightness(Glyph):
    """A sun, for the slider. Not a weather sun: this one is a control.

    Drawn here rather than taken from `weatherdraw`, deliberately. That sun
    has a warm cast and a soft halo because it is describing a sky, and a sky
    beside a slider reads as a forecast rather than as a brightness. This one
    is the interface's own ink and nothing else.
    """

    def draw(self, cr) -> None:
        import cairo  # noqa: PLC0415

        cr.set_source_rgb(*self.colour("on_surface_variant"))
        cr.set_line_cap(cairo.LINE_CAP_ROUND)

        cr.new_path()
        cr.arc(12.0, 12.0, 4.1, 0.0, math.tau)
        cr.fill()

        cr.set_line_width(1.8)
        for index in range(8):
            angle = index * math.tau / 8.0
            cr.move_to(12.0 + math.cos(angle) * 6.6,
                       12.0 + math.sin(angle) * 6.6)
            cr.line_to(12.0 + math.cos(angle) * 9.2,
                       12.0 + math.sin(angle) * 9.2)
        cr.stroke()


class Chevron(Glyph):
    """Points at the page this opens."""

    def draw(self, cr) -> None:
        import cairo  # noqa: PLC0415

        cr.set_line_width(1.9)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.set_source_rgb(*self.colour(
            str(self._state.get("role", "on_surface_variant"))))
        back = bool(self._state.get("back"))
        if back:
            cr.move_to(14.5, 5.5)
            cr.line_to(8.5, 12.0)
            cr.line_to(14.5, 18.5)
        else:
            cr.move_to(9.5, 5.5)
            cr.line_to(15.5, 12.0)
            cr.line_to(9.5, 18.5)
        cr.stroke()


class Lock(Glyph):
    """This network wants a password."""

    def draw(self, cr) -> None:
        cr.set_source_rgb(*self.colour(
            str(self._state.get("role", "on_surface_variant"))))
        _rounded(cr, 5.5, 10.5, 13.0, 9.5, 2.4)
        cr.fill()
        cr.set_line_width(1.7)
        cr.new_path()
        cr.arc(12.0, 10.0, 3.6, math.radians(180), math.radians(360))
        cr.stroke()


class Access(Glyph):
    """The accessibility figure, which is one of the few marks that is a
    standard rather than a style. Drawn rather than requested for the same
    reason as the rest, but not redesigned: this one is recognised, and a
    clever version of it would be a worse version."""

    def draw(self, cr) -> None:
        import cairo  # noqa: PLC0415

        cr.set_source_rgb(*self.colour(
            str(self._state.get("role", "on_surface_variant"))))
        cr.new_path()
        cr.arc(12.0, 4.9, 2.1, 0, math.radians(360))
        cr.fill()
        cr.set_line_width(1.9)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.move_to(4.6, 9.4)
        cr.line_to(19.4, 9.4)
        cr.stroke()
        cr.move_to(12.0, 9.0)
        cr.line_to(12.0, 14.0)
        cr.stroke()
        cr.move_to(8.0, 20.2)
        cr.line_to(12.0, 14.0)
        cr.line_to(16.0, 20.2)
        cr.stroke()
