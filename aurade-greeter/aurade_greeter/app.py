"""The graphical greeter.

This is the first thing somebody sees every morning and the last thing they
see before their own desktop, so it is held to the installer's standard rather
than to a login screen's. The aurora behind it, the type, the colours, the
status cluster and the accessibility announcements are the installer's, carried
over unchanged rather than approximated.

Everything that decides something lives next door with no toolkit in it:
`protocol` holds the greetd conversation, `accounts` holds who counts as a
person, `sessions` holds the picker. This file is the part that draws, and it
is deliberately the part with the fewest rules in it.

Two things here are not decoration.

The conversation runs on a worker thread. PAM can take a noticeable moment,
and longer with a module that talks to something, so doing it on the main loop
would freeze the window between pressing sign in and finding out. A greeter
that stops repainting while it thinks looks exactly like a greeter that has
crashed, and the person in front of it starts holding the power button.

The window never leaves somebody with nothing to press. Every failure has a
sentence and a way onward, including the failure where greetd itself has gone,
because a login screen with a dead back end and no restart button is a machine
that needs a power cycle to recover from a service restarting badly.
"""

from __future__ import annotations

import math
import datetime
import os
import subprocess
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import (Adw, Gdk, Gio, GLib, Graphene, Gtk,  # noqa: E402
                          Pango)

from . import accounts as ACC  # noqa: E402
from . import copy as C  # noqa: E402
from . import network as NET  # noqa: E402
from . import glyphs as G  # noqa: E402
from . import glass as GL  # noqa: E402
from . import settings as SET  # noqa: E402
from . import nmlive  # noqa: E402
from . import preferences as PREF  # noqa: E402
from . import protocol as P  # noqa: E402
from . import sessions as SES  # noqa: E402
from . import a11y as A  # noqa: E402
from . import brand  # noqa: E402
from . import status as ST  # noqa: E402
from . import alerts as ALERTS  # noqa: E402
from . import locate as LOC  # noqa: E402
from . import alertui as AU  # noqa: E402
from . import tokens as T  # noqa: E402
from . import shade as SH  # noqa: E402
from . import weather as WX  # noqa: E402
from . import weatherui as WUI  # noqa: E402
from . import outlook as OUT  # noqa: E402
from . import backlight as BL  # noqa: E402

APP_ID = "org.aurade.Greeter"

_LIB = os.path.dirname(os.path.realpath(__file__))
THEMES = {
    "light": os.path.join(_LIB, "theme.css"),
    "dark": os.path.join(_LIB, "theme-dark.css"),
    "light-hc": os.path.join(_LIB, "theme-hc.css"),
    "dark-hc": os.path.join(_LIB, "theme-dark-hc.css"),
    "oled": os.path.join(_LIB, "theme-oled.css"),
}
GREETER_CSS = os.path.join(_LIB, "greeter.css")

#: How often the aurora advances, and how often the status cluster is reread.
FRAME_MS = 33
STATUS_INTERVAL_MS = 15000
#: How long the photographs take to cross fade into one another, and how
#: long the accounts take to arrive once the shade is lifted. The fade is
#: slow because nothing is waiting on it; the arrival is quick because
#: somebody is.
WALLPAPER_FADE_MS = 1600

#: How far the photograph drifts, as a fraction of the window.
#:
#: One and a half percent, which is nineteen pixels on a 1280 wide screen and
#: takes eleven minutes to cross. Slow enough that nobody catches it moving
#: and only notices, coming back from the kitchen, that the picture is not
#: quite where it was. A window rather than a wallpaper.
#:
#: Deliberately smaller than the blur the frosted cards are built from. The
#: glass samples the picture at its rest position and is not recomputed as it
#: drifts, which is only honest because a thirty two fold reduction of the
#: image cannot see a nineteen pixel shift: the ground under a card genuinely
#: does not change, so the contrast the glass gate proves stays proved.
DRIFT = 0.015

#: One crossing, there and back. Long enough that the motion is never a
#: motion, which is the entire design goal.
DRIFT_MS = 660_000

#: How often warnings are asked about, in seconds.
#:
#: Its own number, and much shorter than the forecast's, because the two are
#: not the same kind of fact. A temperature fifteen minutes old is a
#: temperature. A tornado warning fifteen minutes old is most of the lead time
#: the National Weather Service managed to give anybody.
#:
#: One small request a minute, and only on a machine where somebody has turned
#: both the weather and emergency alerts on. A point query usually comes back
#: as an empty collection of a few hundred bytes.
WARNINGS_EVERY = 60

#: How far the sign in card moves when a password is refused, and for how
#: long. Small and short: this is feedback, not a tantrum.
SHAKE_PIXELS = 9
SHAKE_MS = 420


def shake_offset(value: float) -> int:
    """How far the card is from centre, at one point through the shake.

    Four passes, dying away, and it is a module function so that the property
    that matters can be asserted: it starts at nothing and ends at nothing. A
    card left one pixel off centre is a card somebody notices for the rest of
    the session, and it would be left there by any easing curve that does not
    happen to land on zero.

    Never wider than the margin it is spent against either, because the two
    margins move in opposite directions and the card must never ask the page
    for room it did not already have.
    """
    return int(round(math.sin(value * math.pi * 4.0)
                     * SHAKE_PIXELS * (1.0 - value)))
ARRIVE_MS = 44

#: How wide the sign in panel is allowed to get. Narrower than the installer's
#: prose measure, because there is one field on it and a wide box around one
#: field reads as an empty page rather than a focused one.
PANEL_WIDTH = 420


def column(spacing: int = 16) -> Gtk.Box:
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)


def row(spacing: int = 12) -> Gtk.Box:
    return Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)


def label(text: str, style: str = "m3-body-medium", *, center: bool = False,
          wrap: bool = True, css: str = "") -> Gtk.Label:
    widget = Gtk.Label(label=text)
    widget.add_css_class(style)
    if css:
        widget.add_css_class(css)
    widget.set_wrap(wrap)
    widget.set_xalign(0.5 if center else 0.0)
    if center:
        widget.set_justify(Gtk.Justification.CENTER)
    return widget


class Wallpaper(Gtk.DrawingArea):
    """The photograph, if this machine has the set on it.

    The same forty pictures the installer draws behind its pages, from
    the same manifest, chosen once per boot. They shipped on the installation
    media and nowhere else until `aurade-wallpapers` existed, so a machine
    that finished an installation had seen them and could never see them
    again.

    Draws nothing and says so when there is no set, and the aurora above is
    then the whole background, which is what every machine looked like before.
    """

    def __init__(self, dark: bool, plain: bool = False,
                 where: tuple[float, float] | None = None) -> None:
        super().__init__()
        self.dark = dark
        self.where = where
        #: High contrast draws no photograph at all.
        #:
        #: Everything else on this screen answers high contrast by stating its
        #: ground rather than suggesting it, and a photograph cannot do that:
        #: the clock and the date on the shade sit directly on the picture,
        #: with only a veil between them, and a veil is exactly the soft edge
        #: high contrast exists to remove. So the picture goes, the ground is
        #: the theme's own surface, and the card goes with it rather than
        #: describing something nobody can see.
        self.plain = plain
        pinned = os.environ.get("AURADE_GREETER_WALLPAPER", "")
        self.picture = (brand.choose_wallpaper(pinned) if pinned
                        else self.pick())
        #: The picture being left behind, and how far through leaving it is.
        #: `1.0` means there is nothing to leave and the still path runs.
        self.leaving: dict | None = None
        self.mix = 1.0
        #: Where in the drift the picture is, from 0 to 1, centred at rest.
        self.drift = 0.5
        self._drifting = None
        self._surfaces: dict = {}
        self._fade = None
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_draw_func(self._draw)
        A.decorative(self)

    def pick(self, avoid: dict | None = None) -> dict | None:
        """A picture whose light matches the light outside, near enough.

        Near enough, because the set has three night pictures in it. A screen
        that insisted would show the same three every winter evening, so the
        match gives way to the whole set rather than to nothing, and only the
        brightness cap is absolute.
        """
        import random  # noqa: PLC0415 - one call, on one code path

        available = brand.wallpapers()
        if not available:
            return None
        when = datetime.datetime.now().astimezone()
        where = self.where or (None, None)
        light = SH.light_now(when, where[0], where[1])
        pool = SH.suited(available, light, when)
        if avoid is not None:
            pool = [e for e in pool
                    if e.get("path") != avoid.get("path")] or pool
        return random.choice(pool)

    @property
    def present(self) -> bool:
        return self.picture is not None and not self.plain

    def _surface(self, path: str, width: int, height: int):
        """This widget's own copy, because a cross fade needs two at once.

        `brand` caches exactly one, which is right for the installer and wrong
        here: asking it for two alternately would decode both photographs on
        every frame of the fade, on the machines least able to afford it. Two
        entries, keyed the same way, and everything else thrown away when the
        window changes size.
        """
        key = (path, width, height)
        found = self._surfaces.get(key)
        if found is not None:
            return found
        surface = None
        try:
            import cairo  # noqa: PLC0415

            gi.require_version("GdkPixbuf", "2.0")
            from gi.repository import GdkPixbuf  # noqa: PLC0415

            _, native_w, native_h = GdkPixbuf.Pixbuf.get_file_info(path)
            scaled_w, scaled_h, dx, dy = brand.cover_box(
                native_w, native_h, width, height)
            if scaled_w:
                picture = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    path, scaled_w, scaled_h, False)
                surface = cairo.ImageSurface(cairo.FORMAT_RGB24, width, height)
                context = cairo.Context(surface)
                Gdk.cairo_set_source_pixbuf(context, picture, dx, dy)
                context.paint()
        except Exception:  # noqa: BLE001 - decoration, never a traceback
            surface = None
        # Two, and only the two in the fade. A dictionary that grew would hold
        # every photograph the screen had shown all night at window size.
        self._surfaces = {k: v for k, v in self._surfaces.items()
                          if k[1:] == key[1:]}
        while len(self._surfaces) >= 2:
            self._surfaces.pop(next(iter(self._surfaces)))
        self._surfaces[key] = surface
        return surface

    def backdrop(self):
        """The surface a card should frost, or nothing.

        The widget's own cache rather than `brand`'s, because `brand` holds
        exactly one entry and asking it for a second picture mid crossfade
        would evict the one being drawn and decode both again on every frame.
        This asks for a picture that is already in hand.
        """
        if self.plain or self.picture is None:
            return None
        width, height = self.get_width(), self.get_height()
        if width <= 0 or height <= 0:
            return None
        return self._surface(self.picture["path"], width, height)

    def fade_to(self, entry: dict | None, animate: bool = True) -> bool:
        """Change the photograph, over a second and a half, or at once."""
        if entry is None or self.picture is None:
            return False
        if entry.get("path") == self.picture.get("path"):
            return False
        if not animate:
            self.picture = entry
            self.leaving = None
            self.mix = 1.0
            self.queue_draw()
            return True
        self.leaving = self.picture
        self.picture = entry
        self.mix = 0.0

        def step(value, _user=None):
            self.mix = value
            if value >= 1.0:
                self.leaving = None
            self.queue_draw()

        target = Adw.CallbackAnimationTarget.new(step)
        self._fade = Adw.TimedAnimation.new(
            self, 0.0, 1.0, WALLPAPER_FADE_MS, target)
        self._fade.set_easing(Adw.Easing.EASE_IN_OUT_CUBIC)
        self._fade.play()
        return True

    def _still(self, cr, width: int, height: int) -> None:
        """One photograph, offset by however far it has drifted.

        The surface is asked for slightly larger than the window and drawn
        from inside it, so the drift pans within an overscan rather than
        exposing an edge. Without the margin a sixteen by nine picture in a
        sixteen by nine window has nowhere to go, and the first pixel of
        movement shows the window's own background along one side.
        """
        margin = max(2, int(width * DRIFT))
        surface = self._surface(self.picture["path"],
                                width + margin * 2, height + margin * 2)
        if surface is None:
            brand.draw_wallpaper(cr, width, height, self.picture["path"],
                                 self.dark)
            return
        shift = (self.drift - 0.5) * 2.0
        cr.set_source_surface(surface,
                              -margin + shift * margin,
                              -margin - shift * margin * 0.4)
        cr.paint()
        red, green, blue = T.rgb(T.scheme(self.dark)["surface"])
        cr.set_source_rgba(red, green, blue,
                           brand.WALLPAPER_VEIL_DARK if self.dark
                           else brand.WALLPAPER_VEIL_LIGHT)
        cr.paint()

    def start_drifting(self) -> None:
        """Begin the slow pan, or sit still where motion is not wanted.

        Reduced motion is answered by never starting rather than by starting
        and stopping, so a still screen and a moving one are the same picture
        at the same offset and nobody gets a second layout.
        """
        if self._drifting is not None or not self.present:
            return
        animation = Adw.TimedAnimation.new(
            self, 0.0, 1.0, DRIFT_MS,
            Adw.CallbackAnimationTarget.new(self._drifted))
        animation.set_easing(Adw.Easing.EASE_IN_OUT_SINE)
        animation.set_repeat_count(0)
        animation.set_alternate(True)
        animation.play()
        self._drifting = animation

    def _drifted(self, value, _user=None) -> None:
        self.drift = value
        self.queue_draw()

    def _draw(self, _area, cr, width: int, height: int) -> None:
        if self.plain:
            red, green, blue = T.rgb(T.scheme(self.dark)["surface"])
            cr.set_source_rgb(red, green, blue)
            cr.paint()
            return
        if self.picture is None:
            return
        # No bands. The installer reserves opaque strips where its top bar and
        # footer sit; this screen has a panel in the middle and two small
        # clusters in the corners, so the veil alone carries legibility and
        # the corners get their own ground.
        if self.leaving is None or self.mix >= 1.0:
            self._still(cr, width, height)
            return

        # Mid fade: the outgoing picture stays opaque underneath and the
        # incoming one comes up over it, so at no point is the window's own
        # background showing between two photographs. One veil, not two, and
        # its constants are read from `brand` rather than copied, so the two
        # code paths cannot drift into two different amounts of dark.
        under = self._surface(self.leaving["path"], width, height)
        over = self._surface(self.picture["path"], width, height)
        if under is None or over is None:
            brand.draw_wallpaper(cr, width, height, self.picture["path"],
                                 self.dark)
            return
        cr.set_source_surface(under, 0, 0)
        cr.paint()
        cr.set_source_surface(over, 0, 0)
        cr.paint_with_alpha(max(0.0, min(1.0, self.mix)))
        red, green, blue = T.rgb(T.scheme(self.dark)["surface"])
        cr.set_source_rgba(red, green, blue,
                           brand.WALLPAPER_VEIL_DARK if self.dark
                           else brand.WALLPAPER_VEIL_LIGHT)
        cr.paint()


class Frosted(Gtk.Widget):
    """One child, standing on a rounded ground of blurred photograph.

    A container rather than a sibling, because the ground has to be drawn
    immediately under this child and nothing else. `Gtk.Overlay` draws its own
    child first and its overlays after, so a ground added as an overlay lands
    on top of the thing it is meant to be under.

    Where there is no photograph, or where high contrast has taken it away,
    this draws nothing at all and the child keeps whatever the stylesheet gave
    it. That is deliberate: high contrast exists so somebody can read, and a
    surface that is partly a photograph is the thing it exists to remove.
    """

    def __init__(self, child: Gtk.Widget, wallpaper: Wallpaper,
                 radius: float = 18.0) -> None:
        super().__init__()
        self._child = child
        self._child.set_parent(self)
        self.wallpaper = wallpaper
        self.radius = radius
        #: One entry, keyed by everything that would change the answer.
        self._cache: tuple | None = None
        self.set_halign(child.get_halign())
        self.set_valign(child.get_valign())
        self.set_hexpand(child.get_hexpand())
        self.set_vexpand(child.get_vexpand())
        # The margins move out to here. Left on the child they would be inside
        # the ground, which would draw the frost out to the screen edge and
        # leave the card floating in the middle of its own glass.
        for edge in ("start", "end", "top", "bottom"):
            value = getattr(child, f"get_margin_{edge}")()
            getattr(self, f"set_margin_{edge}")(value)
            getattr(child, f"set_margin_{edge}")(0)

    def do_measure(self, orientation, for_size):
        return self._child.measure(orientation, for_size)

    def do_size_allocate(self, width, height, baseline):
        self._child.allocate(width, height, baseline, None)

    def do_snapshot(self, snapshot):
        width, height = self.get_width(), self.get_height()
        if width > 0 and height > 0:
            found = self._ground(width, height)
            if found is not None:
                blurred, alpha, left, top = found
                rect = Graphene.Rect().init(0, 0, width, height)
                context = snapshot.append_cairo(rect)
                self._paint(context, blurred, alpha, width, height)
        self.snapshot_child(self._child, snapshot)

    def _ground(self, width: int, height: int):
        """The blurred region and its tint, computed once and then kept.

        Keyed on the picture, the scheme and where this widget sits, because
        those are exactly the four things that change the answer. A card that
        has not moved over a picture that has not changed does not blur a
        photograph again to draw the same frame twice.
        """
        surface = self.wallpaper.backdrop()
        if surface is None:
            return None
        moved, point = self.compute_point(
            self.wallpaper, Graphene.Point().init(0.0, 0.0))
        if not moved:
            return None
        left, top = int(point.x), int(point.y)
        key = (self.wallpaper.picture["path"], self.wallpaper.dark,
               left, top, width, height,
               surface.get_width(), surface.get_height())
        if self._cache is not None and self._cache[0] == key:
            return self._cache[1]
        scheme = T.scheme(self.wallpaper.dark)
        blurred, alpha, _peak = GL.ground(
            surface, left, top, width, height,
            T.rgb(scheme["surface"]), T.rgb(scheme["on_surface"]))
        if blurred is None:
            return None
        answer = (blurred, alpha, left, top)
        self._cache = (key, answer)
        return answer

    def _paint(self, context, blurred, alpha: float,
               width: int, height: int) -> None:
        scheme = T.scheme(self.wallpaper.dark)
        red, green, blue = T.rgb(scheme["surface"])
        context.save()
        GL.rounded(context, 0, 0, width, height, self.radius)
        context.clip()
        context.set_source_surface(blurred, 0, 0)
        context.paint()
        context.set_source_rgba(red, green, blue, alpha)
        context.paint()
        context.restore()
        # The hairline, which is what stops a frosted card from reading as a
        # smudge on the photograph. Light on a dark scheme, dark on a light
        # one, and at the same weight the flat cards already used.
        GL.rounded(context, 0.5, 0.5, width - 1, height - 1, self.radius)
        if self.wallpaper.dark:
            context.set_source_rgba(1.0, 1.0, 1.0, 0.11)
        else:
            context.set_source_rgba(0.0, 0.0, 0.0, 0.10)
        context.set_line_width(1.0)
        context.stroke()

    def refresh(self) -> None:
        """Forget the ground, because the picture under it changed."""
        self._cache = None
        self.queue_draw()

    def do_dispose(self):
        if self._child is not None:
            self._child.unparent()
            self._child = None
        Gtk.Widget.do_dispose(self)


class Aurora(Gtk.DrawingArea):
    """The installer's background, still moving.

    Reduced motion is honoured by not advancing rather than by drawing
    something else, so a still greeter and a moving one are the same picture
    at different moments and nobody gets a second design.
    """

    def __init__(self, dark: bool) -> None:
        super().__init__()
        self.dark = dark
        self.phase = 0.0
        #: Whether a photograph is underneath. When there is one the aurora is
        #: a light over it rather than the ground itself, so it is drawn
        #: faintly; at full strength it turns a photograph into a colour wash.
        self.over_picture = False
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_draw_func(self._draw)
        A.decorative(self)

    def _draw(self, _area, cr, width: int, height: int) -> None:
        if self.over_picture:
            cr.push_group()
            brand.draw_aurora(cr, width, height, self.dark, self.phase)
            cr.pop_group_to_source()
            cr.paint_with_alpha(0.35)
            return
        brand.draw_aurora(cr, width, height, self.dark, self.phase)

    def advance(self, seconds: float) -> None:
        self.phase += seconds
        self.queue_draw()


class Mark(Gtk.DrawingArea):
    """The AuraDE mark, at the size a login screen wants it."""

    def __init__(self, size: int = 64) -> None:
        super().__init__()
        self.size = size
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_halign(Gtk.Align.CENTER)
        self.set_draw_func(
            lambda _a, cr, w, h: brand.draw_mark(cr, w, h, float(min(w, h))))
        A.decorative(self)


class Avatar(Gtk.DrawingArea):
    """A person, as a circle.

    A picture when the system has one, and the first letter of their name when
    it does not. The letter is not a placeholder for a missing picture: on a
    machine where nobody has ever set one, every row has a letter and the list
    still reads as a list of people rather than a list of empty circles.
    """

    def __init__(self, account: ACC.Account, size: int = 48) -> None:
        super().__init__()
        self.account = account
        self.size = size
        self._surface = None
        self._tried = False
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_valign(Gtk.Align.CENTER)
        self.set_draw_func(self._draw)
        A.decorative(self)

    def _picture(self):
        if self._tried:
            return self._surface
        self._tried = True
        if not self.account.avatar:
            return None
        try:
            self._surface = brand._wallpaper_surface(  # noqa: SLF001
                self.account.avatar, self.size, self.size)
        except Exception:  # noqa: BLE001 - a bad picture is not a failed login
            self._surface = None
        return self._surface

    def _draw(self, _area, cr, width: int, height: int) -> None:
        import math

        radius = min(width, height) / 2.0
        cr.save()
        cr.arc(width / 2.0, height / 2.0, radius, 0, 2 * math.pi)
        cr.clip()
        surface = self._picture()
        if surface is not None:
            cr.set_source_surface(surface, 0, 0)
            cr.paint()
            cr.restore()
            return
        tint = T.DARK if _dark() else T.LIGHT
        ground, ink = _person_tones(self.account, tint)
        _fill(cr, ground)
        cr.paint()
        cr.restore()

        # Through Pango, like every other glyph on this screen.
        #
        # These two lines were the only calls to cairo's toy text API in the
        # tree, and it is not a stylistic point: the toy API ignores the text
        # scale somebody set in the installer, picks whatever "Sans" resolves
        # to rather than the interface font, and does not shape. A person
        # whose name begins with a non Latin character got a box.
        import gi  # noqa: PLC0415

        gi.require_version("PangoCairo", "1.0")
        from gi.repository import PangoCairo  # noqa: PLC0415

        letter = self.account.initial
        if not letter:
            return
        _fill(cr, ink)
        layout = PangoCairo.create_layout(cr)
        description = self.get_pango_context().get_font_description().copy()
        description.set_size(int(radius * 1.05 * Pango.SCALE))
        description.set_weight(Pango.Weight.MEDIUM)
        layout.set_font_description(description)
        layout.set_text(letter, -1)
        run_width, run_height = layout.get_pixel_size()
        cr.move_to(width / 2.0 - run_width / 2.0,
                   height / 2.0 - run_height / 2.0)
        PangoCairo.show_layout(cr, layout)


#: How far around the brand's hue a face is allowed to travel.
#:
#: Not the whole wheel. Every avatar still has to sit on this screen without
#: fighting the accent, and a rainbow of user pictures reads as a toy rather
#: than as a product. Ninety degrees either side of the brand keeps them
#: recognisably related and still tells three people apart at a glance.
PERSON_SWING = 90.0


def _person_tones(account, tint: dict) -> tuple[str, str]:
    """A ground and an ink for one person, the same every time.

    Every account had the same purple disc, which is the default avatar of
    every Linux greeter and the exact moment a screen stops looking made for
    anybody. The hue comes from the name, so it is stable across reboots, the
    same on every machine that person signs in to, and needs nothing stored.

    Derived from the container role rather than chosen, so high contrast and
    the light scheme keep whatever they already do to it.
    """
    import colorsys  # noqa: PLC0415
    import hashlib  # noqa: PLC0415

    ground = tint["primary_container"]
    ink = tint["on_primary_container"]
    name = getattr(account, "name", "") or getattr(account, "title", "")
    if not name:
        return ground, ink
    red, green, blue = (int(ground.lstrip("#")[i:i + 2], 16) / 255.0
                        for i in (0, 2, 4))
    hue, lightness, saturation = colorsys.rgb_to_hls(red, green, blue)
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    # A signed offset from the brand hue rather than an absolute hue, so the
    # whole set moves if the brand does.
    offset = (digest[0] / 255.0 * 2.0 - 1.0) * (PERSON_SWING / 360.0)
    moved = colorsys.hls_to_rgb((hue + offset) % 1.0, lightness, saturation)
    return "#%02x%02x%02x" % tuple(round(v * 255) for v in moved), ink


def _fill(cr, colour: str) -> None:
    value = colour.lstrip("#")
    cr.set_source_rgb(int(value[0:2], 16) / 255.0,
                      int(value[2:4], 16) / 255.0,
                      int(value[4:6], 16) / 255.0)


def _children(container) -> list:
    """Every child of a container, as a list rather than a walk."""
    found, child = [], container.get_first_child()
    while child is not None:
        found.append(child)
        child = child.get_next_sibling()
    return found


def _dark() -> bool:
    manager = Adw.StyleManager.get_default()
    return bool(manager.get_dark())


class Worker:
    """One greetd call, off the main loop, answered back on it.

    Deliberately one shot. A worker that could be reused would be a worker
    that could be running two conversations at once, and two conversations at
    once on one socket is a greeter that signs somebody in as the wrong
    person.
    """

    def __init__(self, work, done) -> None:
        self._work = work
        self._done = done
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> "Worker":
        self._thread.start()
        return self

    def _run(self) -> None:
        try:
            result = self._work()
            error = None
        except Exception as exc:  # noqa: BLE001 - delivered, not swallowed
            result, error = None, exc
        GLib.idle_add(self._done, result, error, priority=GLib.PRIORITY_DEFAULT)


class GreeterWindow(Adw.ApplicationWindow):
    """The whole screen."""

    def __init__(self, application: Adw.Application,
                 transport: P.Transport | None) -> None:
        super().__init__(application=application)
        self.transport = transport
        self.session: P.Session | None = None
        self.accounts: list[ACC.Account] = []
        self.chosen: ACC.Account | None = None
        self.typed_name = ""
        self.widgets: dict = {}
        self.busy = False
        self._frame_source = 0
        self._frame_last = 0.0
        self._status_source = 0
        self._clock_source = 0
        self._handoff_source = None
        #: The network panel's own state. `wifi` is the radio the panel acts
        #: on, read once per refresh rather than looked up per press.
        #: How this screen was asked to behave. Read once, before anything
        #: draws, because the weather decides whether there are one or two
        #: pills on the shelf and a shelf that grows a pill after the fact
        #: moves the clock somebody was looking at.
        self.behaviour = SET.read()
        self.weather: WX.Report | None = None
        self._weather_source = 0
        self._weather_busy = False
        self._alerts_source = 0
        self._alerts_busy = False
        #: Consecutive refusals, and who they were for.
        #:
        #: Kept against the name rather than reset from the three places that
        #: change who is being asked about. A list of call sites is a list
        #: that stops matching the code, and this one would fail quietly: the
        #: count would carry over to the next person and lock a screen that is
        #: not locked.
        self._refusals = 0
        self._refused_for = ""
        #: Whether the shade is still down. It starts down, which is the whole
        #: point: the first thing anybody sees is a photograph and a clock,
        #: and the accounts are not on screen until somebody asks for them.
        self.shade_up = False
        self._rotate_source = 0
        self._arrivals: list[int] = []
        self.nm = nmlive.Client()
        # The strength the arcs draw, once NetworkManager has said.
        # None means nobody has asked yet, which is not zero.
        self._wifi_strength: int | None = None
        self.wifi = None
        self._network_busy = False

        self.set_title("AuraDE")
        self._load_styles()
        self._build()
        self.reload_accounts()
        self._load_sessions()
        self._start_clock()
        self._start_status()
        self._start_weather()
        self._start_rotating()
        self._start_frames()

    # -- appearance --------------------------------------------------------

    @property
    def animate(self) -> bool:
        settings = Gtk.Settings.get_default()
        if settings is None:
            return True
        return bool(settings.get_property("gtk-enable-animations"))

    def _load_styles(self) -> None:
        """The appearance, taken from what this person already asked for.

        The installer writes their answers to `/etc/aurade-install/accessibility`
        and a first boot unit checks the desktop honoured them. Nothing checked
        the login screen did, and it did not, which is the worst place for it
        to fail: the settings that would let somebody read the screen sit
        behind the screen they cannot read.
        """
        display = Gdk.Display.get_default()
        if display is None:
            return
        self.wanted = PREF.read()
        oled = os.environ.get("AURADE_GREETER_OLED", "").lower() in ("1", "true")
        dark = os.environ.get("AURADE_GREETER_DARK", "1").lower() not in ("0", "false")
        # The environment still wins, so a machine can be looked at either way
        # without editing the record somebody depends on.
        override = os.environ.get("AURADE_GREETER_CONTRAST", "").lower()
        if override in ("1", "true", "high"):
            self.wanted["contrast"] = "high"
        elif override in ("0", "false", "normal"):
            self.wanted["contrast"] = "normal"
        Adw.StyleManager.get_default().set_color_scheme(
            Adw.ColorScheme.FORCE_DARK if dark else Adw.ColorScheme.FORCE_LIGHT)
        self._apply_settings(self.wanted)
        name = PREF.theme_for(self.wanted, dark, oled)
        for path in (THEMES.get(name), GREETER_CSS):
            if not path or not os.path.isfile(path):
                continue
            provider = Gtk.CssProvider()
            try:
                provider.load_from_path(path)
            except GLib.Error:
                continue
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.dark = dark
        # High contrast is a theme file, and greeter.css is loaded after it
        # and knows nothing about which one won. Translucency is the whole
        # point of the pill and the bubble and it is exactly wrong here, so
        # the window says which mode it is in and the overrides below key off
        # it. Without this, turning on high contrast would make the two
        # surfaces this pass added the least readable things on the screen.
        self.high_contrast = name.endswith("-hc")
        if self.high_contrast:
            self.add_css_class("aurade-high-contrast")
        else:
            self.remove_css_class("aurade-high-contrast")
        # And which scheme, for the same reason. The pill and the panel state
        # their grounds in white at a low alpha, which is right over a dark
        # base and backwards over a light one: the text turns dark and the
        # ground stays dark with it. The light overrides key off this.
        if dark:
            self.remove_css_class("aurade-light")
        else:
            self.add_css_class("aurade-light")

    def _apply_settings(self, record: dict) -> None:
        """Text size, cursor size, typeface and stillness, before anything draws.

        Set on GtkSettings rather than through CSS, because these are the same
        knobs the desktop uses and somebody who asked for 200 percent text
        means it everywhere, not only where a stylesheet remembered to ask.
        """
        settings = Gtk.Settings.get_default()
        if settings is None:
            return
        scale = PREF.text_scale(record)
        if scale != PREF.MIN_SCALE:
            settings.set_property("gtk-xft-dpi", int(scale * 96 * 1024 / 100))
        settings.set_property("gtk-cursor-theme-size", PREF.cursor_size(record))
        typeface = PREF.font_name(record)
        if typeface:
            settings.set_property("gtk-font-name", typeface)
        if PREF.wants_stillness(record):
            # Honoured by not moving, rather than by drawing something else,
            # so a still greeter and a moving one are the same picture at
            # different moments and nobody gets a second design.
            settings.set_property("gtk-enable-animations", False)

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        # Toast overlay outermost, the way the installer has it. The greeter
        # has one thing to toast about, which is a power action the system
        # refused, and it is worth a line at the bottom rather than a dialog
        # over a login screen.
        self.toasts = Adw.ToastOverlay()
        self.set_content(self.toasts)

        overlay = Gtk.Overlay()
        self.toasts.set_child(overlay)
        # Photograph, then the brand's light over it, then the interface. The
        # same three layers the installer stacks, in the same order.
        self.wallpaper = Wallpaper(self.dark, plain=self.high_contrast,
                                   where=SET.coordinates(self.behaviour))
        overlay.set_child(self.wallpaper)
        self.aurora = Aurora(self.dark)
        self.aurora.over_picture = self.wallpaper.present
        overlay.add_overlay(self.aurora)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(220 if self.animate else 0)
        self.stack.add_named(self._build_shade(), "shade")
        self.stack.add_named(self._build_accounts(), "accounts")
        self.stack.add_named(self._build_password(), "password")
        self.stack.add_named(self._build_handoff(), "handoff")
        self.stack.set_visible_child_name("shade")
        overlay.add_overlay(self.stack)

        # The card sits in the overlay rather than in the shade page, opposite
        # the two pills, so the shade has a weight in each lower corner and
        # the middle is left for the clock.
        self.card = SH.PhotoCard()
        self.widgets["card"] = self.card
        overlay.add_overlay(self._on_glass(self.card, "card.glass"))
        self._show_card()

        overlay.add_overlay(self._build_shelf())

        # Warnings last, so they are over the shelf and the cards as well as
        # over the pages. The strip first and the screen after it, because the
        # screen is what the strip is the dismiss state of and a takeover with
        # the banner drawn on top of it would look like a rendering fault.
        self.banner = AU.Banner()
        self.banner.animate = self.animate
        self.widgets["warning.banner"] = self.banner
        overlay.add_overlay(self.banner)
        self.takeover = AU.Takeover()
        self.takeover.animate = self.animate
        self.widgets["warning.takeover"] = self.takeover
        overlay.add_overlay(self.takeover)
        # Connected to the stack rather than called from the four places
        # that change the page. A list of call sites is a list that stops
        # matching the code; the signal cannot.
        self.stack.connect("notify::visible-child-name",
                           lambda *_a: self._sync_status_clock())
        self._sync_status_clock()
        # Only where motion is wanted. Reduced motion leaves the picture at
        # rest, which is where the drift starts anyway, so the two screens
        # are the same screen rather than two designs.
        if self.animate:
            self.wallpaper.start_drifting()

        # CAPTURE, not the default bubble.
        #
        # The shade carries live pills, and the weather one is deliberately
        # interactive. On bubble the focused widget answers first, so Return on
        # the lock screen opened the weather instead of lifting the shade, and
        # the person pressing it to sign in got a forecast. On capture the
        # window is asked first, and because _on_key only claims the keystroke
        # while the shade is still down, everything after the lift behaves
        # exactly as it did.
        #
        # Named for the same reason the warning guard is: a test that searches
        # for whichever controller happens to be in the capture phase will find
        # the other one and stay green with this phase removed.
        keys = Gtk.EventControllerKey()
        keys.set_name("aurade-shade-key")
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

        # Ahead of everything, including the password entry.
        #
        # A takeover that a focused text field can type through is a takeover
        # somebody dismisses by accident with the first letter of their
        # password, and then wonders what the screen said. On CAPTURE the
        # keystroke is spent clearing the warning and reaches nothing else,
        # and every keystroke after it behaves exactly as before.
        guard = Gtk.EventControllerKey()
        # Named, so a test can find this one rather than whichever key
        # controller GTK happens to have installed on the window itself. The
        # first version of that assertion searched every controller for one in
        # the capture phase, found one that was not this one, and stayed green
        # with the phase removed from here entirely.
        guard.set_name("aurade-warning-guard")
        guard.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        guard.connect("key-pressed", self._on_warning_key)
        self.add_controller(guard)

        # Every way somebody might tell this screen they are here. A lock
        # screen that only answers the keyboard is a lock screen that a laptop
        # trackpad cannot get past, and one that only answers a click is one
        # that somebody typing their password has to reach for the mouse to
        # use. The presses land on the window, behind the pills, so pressing
        # the clock lifts the shade and pressing the weather does not.
        press = Gtk.GestureClick()
        press.set_button(0)
        press.set_propagation_phase(Gtk.PropagationPhase.BUBBLE)
        press.connect("pressed", self._on_press)
        self.add_controller(press)

        swipe = Gtk.EventControllerScroll(
            flags=Gtk.EventControllerScrollFlags.VERTICAL)
        swipe.connect("scroll", lambda *_a: self.lift())
        self.add_controller(swipe)

    def _build_status(self) -> Gtk.Widget:
        """One pill, bottom right, that opens.

        Where a ChromeOS machine keeps it, so somebody who signs in and finds
        the same three facts in the same corner has not learned two places.
        It was a read only strip in the opposite corner, which told you the
        network was down and offered nothing to do about it.

        A pill, and not a row of text on a photograph. It had the radius
        already and no ground to apply it to, so the radius did nothing and
        the cluster read as a caption. It is a control, and the ground is what
        says so.

        What it does not carry is the interface name. `eth0` is a fact about
        this computer's kernel, not a word anybody signing in has a use for,
        and the panel says which network by name to whoever goes looking. The
        battery percentage stays, because on a login screen whether the laptop
        survives the next ten minutes is worth two characters.
        """
        button = Gtk.MenuButton()
        # Not `flat`. Flat exists to remove a button's ground, which is the
        # one thing this button needs, and it wins, so the pill had a radius
        # and nothing to apply it to. The ground is given below instead.
        button.add_css_class("aurade-status-area")

        face = row(8)
        network = G.Network(18)
        self.widgets["status.network.icon"] = network
        face.append(network)

        battery_pair = row(6)
        battery = G.Battery(18)
        self.widgets["status.battery.icon"] = battery
        battery_pair.append(battery)
        battery_label = label("", "m3-label-medium", wrap=False)
        battery_label.set_valign(Gtk.Align.CENTER)
        self.widgets["status.battery"] = battery_label
        battery_pair.append(battery_label)
        self.widgets["status.battery.pair"] = battery_pair
        face.append(battery_pair)

        # A hairline, not a gap. Three readings separated by whitespace read
        # as one run-on fact; the rule says where the machine stops talking
        # about itself and starts telling you the time.
        rule = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        rule.add_css_class("aurade-status-rule")
        self.widgets["status.rule"] = rule
        face.append(rule)

        clock = label("", "m3-label-large", wrap=False)
        clock.set_valign(Gtk.Align.CENTER)
        self.widgets["status.clock"] = clock
        face.append(clock)

        # The network name still exists for anyone listening rather than
        # looking. It is on the button's description, which is read out, and
        # off the face, which is not the place for it.
        self.widgets["status.network"] = Gtk.Label(visible=False)
        face.append(self.widgets["status.network"])

        button.set_child(face)
        button.set_popover(self._build_panel())
        A.described(button, C.STATUS_AREA, C.STATUS_AREA_HELP)
        self.widgets["status"] = button
        return button

    def _build_shelf(self) -> Gtk.Widget:
        """The bottom right corner, which now holds two pills rather than one.

        One is about this computer and one is about the sky, and they are
        separate presses because they answer separate questions. Putting the
        temperature inside the system panel would mean somebody checking the
        weather has to open the thing that also offers to shut their machine
        down.

        The weather pill sits to the left of the system pill and never moves,
        including on a machine that has the weather switched off, where it is
        simply not built: a pill that appears once an answer arrives shifts
        the clock somebody was reading.
        """
        shelf = row(8)
        shelf.set_halign(Gtk.Align.END)
        shelf.set_valign(Gtk.Align.END)
        shelf.set_margin_bottom(16)
        shelf.set_margin_end(16)
        weather = self._build_weather()
        if weather is not None:
            shelf.append(weather)
        shelf.append(self._build_status())
        self.widgets["shelf"] = shelf
        return shelf

    def _build_weather(self) -> Gtk.Widget | None:
        """A mark and a number, and everything else behind a press.

        Nobody signs in to read a dew point, so the shelf says the one thing
        somebody glances down for. What opens is the other extreme, because
        once they have pressed it, holding anything back only sends them to
        find it somewhere else.
        """
        if not SET.weather_on(self.behaviour):
            return None

        button = Gtk.MenuButton()
        button.add_css_class("aurade-status-area")
        face = row(7)
        mark = WUI.SkyMark(19)
        mark.set_dark(self.dark)
        self.widgets["weather.mark"] = mark
        face.append(mark)
        degrees = label("", "m3-label-large", wrap=False)
        degrees.set_valign(Gtk.Align.CENTER)
        self.widgets["weather.degrees"] = degrees
        face.append(degrees)
        button.set_child(face)

        bubble = Gtk.Popover()
        bubble.add_css_class("aurade-panel")
        bubble.add_css_class("aurade-weather-panel")
        bubble.set_position(Gtk.PositionType.TOP)
        bubble.set_has_arrow(False)
        panel = WUI.Panel()
        panel.set_dark(self.dark)
        panel.on_refresh = lambda: self.refresh_weather(force=True)
        bubble.set_child(panel)
        bubble.connect("show", lambda _b: self.refresh_weather())
        button.set_popover(bubble)

        A.described(button, C.WEATHER, C.WEATHER_PILL_HELP)
        self.widgets["weather"] = button
        self.widgets["weather.panel"] = panel
        self.widgets["weather.bubble"] = bubble
        return button

    # -- the weather -------------------------------------------------------

    def _start_weather(self) -> None:
        """What was known last time, then what is true now.

        The cache is painted before anything is asked, so a machine that has
        been off overnight opens with yesterday evening's reading and its age
        on it rather than with a blank pill for however long the network takes
        to answer.
        """
        if "weather" not in self.widgets:
            return
        self.weather = WX.load()
        self._paint_weather()
        self.refresh_weather()
        self._weather_source = GLib.timeout_add_seconds(300, self._tick_weather)
        self._alerts_source = GLib.timeout_add_seconds(WARNINGS_EVERY,
                                                       self._tick_alerts)

    def _tick_alerts(self) -> bool:
        self.refresh_alerts()
        return True

    def refresh_alerts(self) -> None:
        """Refresh alerts independently of the weather cache."""
        if self._alerts_busy or "weather" not in self.widgets:
            return
        if not SET.alerts_on(self.behaviour):
            return
        report = self.weather
        if report is None or not report.usable:
            return
        latitude, longitude = report.latitude, report.longitude
        self._alerts_busy = True

        def work():
            return ALERTS.fetch(latitude, longitude)

        Worker(work, self._on_alerts).start()

    def _on_alerts(self, result, error) -> bool:
        self._alerts_busy = False
        # A failed request keeps what is on screen. A warning that disappears
        # because a network blipped is worse than one shown a minute longer
        # than it was in force, and `live()` drops it on the next good answer
        # anyway once it has actually expired.
        if error is None and result is not None and self.weather is not None:
            self.weather.alerts = result
            self._paint_weather()
        return False

    def _tick_weather(self) -> bool:
        self.refresh_weather()
        panel = self.widgets.get("weather.panel")
        # The age line moves every tick whether or not a fetch happened, so a
        # panel left open does not go on claiming the reading is new.
        if panel is not None and self.weather is not None and self.weather.usable:
            panel.updated.set_label(WX.since_words(self.weather.age))
        return True

    def refresh_weather(self, force: bool = False) -> None:
        """Ask, off the main loop, at most one conversation at a time."""
        if self._weather_busy or "weather" not in self.widgets:
            return
        record = self.behaviour
        if not SET.weather_on(record):
            return
        if not force and self.weather is not None and self.weather.fresh:
            return
        self._weather_busy = True
        where = SET.coordinates(record)
        wanted = SET.place(record)
        service = SET.provider(record)
        # Read here rather than inside `work`, because `work` runs on a
        # worker thread and the record is the main thread's.
        units = SET.units(record)
        # Asked before the request rather than after it. Somebody who turned
        # emergency alerts off did not ask for them to be fetched quietly and
        # then not drawn.
        warnings = SET.alerts_on(record)
        # Same reason, and the same thread. Whether to ask a stranger where
        # this machine is, decided where the record lives.
        locating = SET.location_on(record)

        def finish(report):
            """The two things asked about a reading once there is one.

            A function rather than a tail, because the location lookup gave
            this worker a second way out and a second way out is how one of
            two exits quietly stops fetching warnings.
            """
            # Never allowed to lose the weather. A service that cannot say
            # whether there is a tornado is a service that must still be able
            # to say it is twenty six degrees.
            if warnings:
                try:
                    report.alerts = ALERTS.fetch(report.latitude,
                                                 report.longitude)
                except Exception:  # noqa: BLE001 - a panel, not a build tool
                    report.alerts = []
            # Cached after the first answer, so this is one request a day at
            # most and none at all on a machine up since yesterday.
            try:
                report.normal = WX.normal_high(
                    report.latitude, report.longitude,
                    datetime.datetime.now().date())
            except Exception:  # noqa: BLE001
                report.normal = None
            # The least important tile on the panel, and it says so by being
            # last and by never raising.
            found = WX.air_quality(report.latitude, report.longitude)
            if found is not None:
                report.air_index, report.air_pm = found
            return report

        def work():
            if locating:
                # Before the forecast, because it decides what to ask about.
                # Cached for a day, so this is one request per boot, and a
                # failure leaves the timezone's guess exactly where it was.
                found = LOC.locate()
                if found is not None:
                    report = WX.fetch(found.latitude, found.longitude, service,
                                      place=found.name or wanted, units=units)
                    return finish(report)
            if where is not None:
                report = WX.fetch(where[0], where[1], service, place=wanted,
                                  units=units)
            else:
                found = WX.resolve(wanted)
                if found is None:
                    raise LookupError(wanted)
                latitude, longitude, name, _zone = found
                report = WX.fetch(latitude, longitude, service, place=name,
                                  units=units)
            return finish(report)

        Worker(work, self._on_weather).start()

    def _on_weather(self, result, error) -> bool:
        self._weather_busy = False
        # A failed fetch keeps whatever was on screen. The alternative is a
        # pill that empties itself every time a network drops, which is both
        # less useful and more alarming than a reading with its age on it.
        if error is None and result is not None and result.now.temperature is not None:
            self.weather = result
            WX.save(result)
        self._paint_weather()
        return False

    def _paint_weather(self) -> None:
        button = self.widgets.get("weather")
        if button is None:
            return
        units = SET.units(self.behaviour)
        report = self.weather
        panel = self.widgets["weather.panel"]
        known = report is not None and report.usable
        panel.show_report(report if known else None, units)
        # Above the early return below, and deliberately. A reading with no
        # temperature in it is a forecast service that did not answer, and
        # whether there is a tornado came from a different service entirely.
        # That exact ordering mistake ate warnings on the panel once already.
        self._show_warnings(report)
        if not known:
            self.widgets["weather.degrees"].set_label("--")
            A.described(button, C.WEATHER, C.WEATHER_LOOKING)
            return
        now = report.now
        self.widgets["weather.mark"].show_sky(now.condition, now.daylight)
        self.widgets["weather.degrees"].set_label(
            WX.temperature(now.temperature, units))
        A.described(button, C.WEATHER, self._weather_sentence(report, units))
        self._paint_shade_weather(report)

    def _paint_shade_weather(self, report) -> None:
        """The faint line under the clock, or nothing at all.

        Read from the same table the panel draws its mark from, so the two
        cannot disagree about whether it is raining, and drawn only while
        there is something to say.
        """
        line = self.widgets.get("shade.weather")
        if line is None:
            return
        # In the report's own zone, and that is not a detail. `_ahead` skips
        # any hour it cannot compare, which is every hour when a naive clock
        # meets an aware forecast, so the first version of this returned
        # nothing at all and did it in silence: no traceback, no empty line,
        # just a screen that never mentioned the weather.
        zone = WUI.zone_of(report) if report else None
        found = (OUT.spell(report, datetime.datetime.now(zone))
                 if report else None)
        if found is None:
            # Measured again on the way out as well as on the way in. This
            # line changes how tall the shade is, and the two pages are kept
            # the same height so the clock does not jump when the shade
            # lifts. The suite caught this within a minute of the line
            # existing, which is the whole reason that assertion is there.
            if line.get_visible():
                line.set_visible(False)
                self._sync_shade()
            return
        kind, words, ends = found
        self.widgets["shade.weather.mark"].show_sky(
            kind, report.now.daylight if report.now else True)
        said = (C.SHADE_WEATHER.format(words=words,
                                       time=WUI.clock_words(ends, zone))
                if ends is not None else C.SHADE_WEATHER_ON.format(words=words))
        self.widgets["shade.weather.words"].set_label(said)
        A.described(line, C.WEATHER, said)
        showing = line.get_visible()
        line.set_visible(True)
        if not showing:
            self._sync_shade()

    def _on_warning_key(self, _controller, _keyval, _code, _state) -> bool:
        return Gdk.EVENT_STOP if self.takeover.dismiss() else Gdk.EVENT_PROPAGATE

    def _show_warnings(self, report) -> None:
        """Which of the two loud tiers this reading has earned, if either.

        `rank` already put the loudest first, so the head of the list is the
        decision and there is nothing to search. A `LINE` alert is not
        promoted out of the panel: a heat advisory is worth a row somebody can
        go and read and is not worth a strip across a login screen.
        """
        found = list(getattr(report, "alerts", None) or []) if report else []
        top = found[0] if found else None
        if top is not None and ALERTS.tier(top) == ALERTS.LINE:
            top = None
        latitude = report.latitude if report is not None else 0.0
        longitude = report.longitude if report is not None else 0.0
        if top is not None and self.takeover.wanted(top):
            self.takeover.show_alert(top, latitude, longitude)
        else:
            self.takeover.clear()
        self.banner.show_alert(top, latitude, longitude)

    def _weather_sentence(self, report, units: str) -> str:
        """The pill's face, said out loud.

        The pill shows a mark and a number, which is all a pill on a
        photograph has room for. Anybody listening rather than looking gets
        the same fact as a sentence with the place in it, because a
        temperature with nowhere attached to it is not an answer.

        Kept as its own method for the same reason `_status_sentence` is: what
        the screen says out loud is a thing worth being able to check without
        opening a screen reader.
        """
        now = report.now
        words = now.summary or WX.WORDS.get(now.condition, "")
        degrees = WX.temperature(now.temperature, units)
        if report.place:
            return C.WEATHER_SAID.format(degrees=degrees, condition=words,
                                         place=report.place)
        return C.WEATHER_SAID_HERE.format(degrees=degrees, condition=words)

    def _pod(self, key: str, name: str, glyph: Gtk.Widget,
             opens: str = "") -> Gtk.Button:
        """One tile in the panel.

        ChromeOS calls these feature pods and they are the reason its quick
        settings reads as a place rather than as a menu: each one says what it
        is, what it is currently doing, and whether there is more behind it.
        A menu item says only its own name.
        """
        # A tile that leads somewhere is a button. A tile that only reports is
        # not, because a button that does nothing when pressed is worse than a
        # label, and a greyed out one reads as broken rather than as reading
        # only.
        button = Gtk.Button() if opens else Gtk.Box()
        button.add_css_class("aurade-pod")
        if not opens:
            button.add_css_class("aurade-pod-readout")
        button.set_hexpand(True)

        body = row(10)
        body.set_margin_top(10)
        body.set_margin_bottom(10)
        body.set_margin_start(12)
        body.set_margin_end(10)
        glyph.set_valign(Gtk.Align.CENTER)
        self.widgets[f"pod.{key}.icon"] = glyph
        body.append(glyph)

        text = column(0)
        text.set_valign(Gtk.Align.CENTER)
        text.set_hexpand(True)
        title = label(name, "m3-label-large", wrap=False)
        title.set_xalign(0.0)
        text.append(title)
        state = label("", "m3-label-medium", wrap=False, css="dim-label")
        state.set_xalign(0.0)
        state.set_ellipsize(Pango.EllipsizeMode.END)
        self.widgets[f"pod.{key}.state"] = state
        text.append(state)
        body.append(text)

        if opens:
            chevron = G.Chevron(16)
            chevron.set_valign(Gtk.Align.CENTER)
            body.append(chevron)
            button.connect("clicked", lambda _b, page=opens: self._panel_show(page))

        if opens:
            button.set_child(body)
        else:
            button.append(body)
        self.widgets[f"pod.{key}"] = button
        return button

    def _on_panel_shown(self, _panel) -> None:
        stack = self.widgets.get("panel.stack")
        if stack is not None:
            stack.set_transition_type(Gtk.StackTransitionType.NONE)
            stack.set_visible_child_name("pods")
        self.widgets["pod.access.state"].set_label(self._access_words())
        # Read the radio, but do not make it scan. A scan takes seconds and
        # opening the panel to read the time should not start one.
        self.refresh_networks(scan=False)

    def _access_words(self) -> str:
        """The accessibility choices that survived the install, in words.

        `preferences.read` returns a record of strings, not an object, and
        every value in it is text: `text_scale` is "125", not 1.25. Reading it
        as anything else is how this returned nothing on a machine where all
        three were on.
        """
        record = getattr(self, "wanted", None) or {}
        on = []
        if str(record.get("contrast", "normal")) not in ("", "normal"):
            on.append(C.ACCESS_CONTRAST)
        try:
            scale = float(record.get("text_scale", "100") or "100")
        except ValueError:
            scale = 100.0
        if scale > 105.0:
            on.append(C.ACCESS_TEXT)
        if SET.truthy(str(record.get("reduce_motion", "no")), False):
            on.append(C.ACCESS_MOTION)
        if not on:
            return C.PANEL_ACCESS_STATE_OFF
        return ", ".join(on)

    def _pod_lit(self, key: str, on: bool) -> None:
        """Light the tile for the thing that is currently on."""
        pod = self.widgets.get(f"pod.{key}")
        if pod is None:
            return
        if on:
            pod.add_css_class("aurade-pod-on")
        else:
            pod.remove_css_class("aurade-pod-on")
        glyph = self.widgets.get(f"pod.{key}.icon")
        if glyph is not None and hasattr(glyph, "update"):
            glyph.update(role="primary" if on else "on_surface_variant")

    def _panel_show(self, page: str) -> None:
        """Move between the pods and a pod's detail, inside the same bubble.

        The bubble does not resize and does not close. A panel that shuts in
        order to open something else makes somebody find it again, and on a
        login screen the thing they were reaching for is the network, which is
        the one thing they may need before they can get in at all.
        """
        stack = self.widgets.get("panel.stack")
        if stack is None:
            return
        stack.set_transition_type(
            Gtk.StackTransitionType.NONE if not self.animate
            else (Gtk.StackTransitionType.SLIDE_LEFT if page != "pods"
                  else Gtk.StackTransitionType.SLIDE_RIGHT))
        stack.set_visible_child_name(page)
        if page == "network":
            self.refresh_networks(scan=True)
            self.widgets["panel.back"].grab_focus()
        else:
            self.widgets["pod.network"].grab_focus()

    def _build_panel(self) -> Gtk.Widget:
        """What opens when the pill is pressed.

        A bubble of tiles that expands into one of them, which is what
        ChromeOS does and what a menu of flat rows cannot do. The network is
        first because it is the only thing on this screen somebody may have to
        change before they can get in at all: an account that needs the
        network, on a machine whose network is down, is a machine with no way
        into it.
        """
        panel = Gtk.Popover()
        panel.add_css_class("aurade-panel")
        panel.set_position(Gtk.PositionType.TOP)
        panel.set_has_arrow(False)

        stack = Gtk.Stack()
        stack.set_transition_duration(180)
        stack.set_hhomogeneous(True)
        stack.set_vhomogeneous(False)
        self.widgets["panel.stack"] = stack
        stack.add_named(self._build_pods(), "pods")
        stack.add_named(self._build_network_page(), "network")
        stack.set_visible_child_name("pods")
        panel.set_child(stack)

        # Opening returns to the tiles. A panel that reopens wherever it was
        # last left makes somebody undo a navigation they did not make.
        panel.connect("show", self._on_panel_shown)
        self.widgets["panel"] = panel
        return panel

    def _build_pods(self) -> Gtk.Widget:
        box = column(8)
        box.set_size_request(360, -1)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(16)
        box.set_margin_end(16)

        # Brightness first, the way ChromeOS puts its sliders above its pods.
        # It is the control somebody reaches for in the dark, and a control
        # somebody reaches for in the dark should not be under two others.
        #
        # Absent on a machine with no backlight rather than present and dead:
        # a slider that moves and changes nothing is worse than no slider.
        if BL.device():
            box.append(self._build_brightness())

        # What the battery is doing, in a sentence. The pill in the corner
        # says the percentage, which answers "how much" and never answers
        # "for how long" or "which way".
        box.append(self._build_battery())

        network = self._pod("network", C.PANEL_NETWORK_POD, G.Network(20),
                            opens="network")
        A.described(network, C.PANEL_NETWORK_POD, C.DESCRIBE_NETWORK_POD)
        box.append(network)

        # What the person chose during the install, still in force. Reading
        # only for now, and honest about it: the choices reached this screen,
        # which is the promise the installer made, and changing them from here
        # is a later pass rather than a button that does nothing.
        access = self._pod("access", C.PANEL_ACCESS_POD, G.Access(20))
        self.widgets["pod.access.state"].set_label(self._access_words())
        A.described(access, C.PANEL_ACCESS_POD, C.DESCRIBE_ACCESS_POD)
        box.append(access)

        # A rule, not a gap. The two below act on the whole machine and the
        # two above act on one setting, and whitespace does not say that.
        rule = Gtk.Separator()
        rule.add_css_class("aurade-panel-rule")
        box.append(rule)

        buttons = row(8)
        for name, text, confirm, body in (
                ("restart", C.RESTART, C.RESTART_CONFIRM, C.POWER_BODY),
                ("off", C.SHUT_DOWN, C.SHUT_DOWN_CONFIRM, C.POWER_BODY)):
            action = Gtk.Button(label=text)
            action.add_css_class("flat")
            action.set_hexpand(True)
            action.connect(
                "clicked",
                lambda _b, n=name, h=confirm, y=body: self._confirm_power(n, h, y))
            A.described(action, text, C.DESCRIBE_POWER)
            self.widgets[f"power.{name}"] = action
            buttons.append(action)
        box.append(buttons)
        return box

    def _build_brightness(self) -> Gtk.Widget:
        holder = row(10)
        holder.add_css_class("aurade-pod")
        holder.add_css_class("aurade-pod-readout")
        holder.set_margin_top(2)
        mark = G.Brightness(20)
        mark.set_valign(Gtk.Align.CENTER)
        mark.set_margin_start(12)
        holder.append(mark)

        slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,
                                          0.0, 1.0, 0.01)
        slider.set_draw_value(False)
        slider.set_hexpand(True)
        slider.set_margin_end(12)
        slider.set_margin_top(8)
        slider.set_margin_bottom(8)
        slider.set_value(BL.level() or 1.0)
        slider.connect("value-changed", self._on_brightness)
        A.described(slider, C.PANEL_BRIGHTNESS, C.PANEL_BRIGHTNESS)
        self.widgets["panel.brightness"] = slider
        holder.append(slider)
        return holder

    def _on_brightness(self, slider) -> None:
        BL.set_level(slider.get_value())

    def _build_battery(self) -> Gtk.Widget:
        holder = row(10)
        holder.add_css_class("aurade-pod")
        holder.add_css_class("aurade-pod-readout")
        mark = G.Battery(20)
        mark.set_valign(Gtk.Align.CENTER)
        mark.set_margin_start(12)
        mark.set_margin_top(10)
        mark.set_margin_bottom(10)
        self.widgets["panel.battery.icon"] = mark
        holder.append(mark)

        text = column(0)
        text.set_valign(Gtk.Align.CENTER)
        text.set_hexpand(True)
        name = label(C.PANEL_BATTERY, "m3-label-large", center=False)
        text.append(name)
        state = label("", "m3-label-medium", center=False, css="dim-label")
        self.widgets["panel.battery.state"] = state
        text.append(state)
        holder.append(text)

        percent = label("", "m3-title-medium", center=False)
        percent.set_margin_end(14)
        percent.set_valign(Gtk.Align.CENTER)
        self.widgets["panel.battery.percent"] = percent
        holder.append(percent)
        self.widgets["panel.battery"] = holder
        return holder

    def _paint_battery_row(self) -> None:
        """The sentence and the number, from one reading of the kernel."""
        holder = self.widgets.get("panel.battery")
        if holder is None:
            return
        found = ST.battery()
        if found.get("percent") is None:
            holder.set_visible(False)
            return
        holder.set_visible(True)
        self.widgets["panel.battery.percent"].set_label(
            C.BATTERY_PERCENT.format(percent=found["percent"]))
        said = C.battery_words(found)
        self.widgets["panel.battery.state"].set_label(said)
        self.widgets["panel.battery.icon"].update(
            percent=int(found["percent"]), charging=bool(found["charging"]))
        A.described(holder, C.PANEL_BATTERY,
                    f"{found['percent']} percent. {said}")

    def _build_network_page(self) -> Gtk.Widget:
        box = column(8)
        box.set_size_request(360, -1)
        box.set_margin_top(12)
        box.set_margin_bottom(16)
        box.set_margin_start(16)
        box.set_margin_end(16)

        head = row(6)
        back = Gtk.Button()
        back.add_css_class("flat")
        back.add_css_class("circular")
        arrow = G.Chevron(16)
        arrow.update(back=True)
        back.set_child(arrow)
        back.connect("clicked", lambda _b: self._panel_show("pods"))
        A.described(back, C.PANEL_BACK, C.PANEL_BACK)
        self.widgets["panel.back"] = back
        head.append(back)
        title = label(C.NETWORK, "m3-title-small", wrap=False)
        title.set_hexpand(True)
        title.set_valign(Gtk.Align.CENTER)
        head.append(title)
        state = label("", "m3-label-medium", wrap=False, css="dim-label")
        state.set_valign(Gtk.Align.CENTER)
        self.widgets["panel.state"] = state
        head.append(state)
        box.append(head)

        listbox = Gtk.ListBox()
        listbox.add_css_class("boxed-list")
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        listbox.connect("row-activated", self._on_network_row)
        self.widgets["panel.list"] = listbox
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_max_content_height(260)
        scroller.set_propagate_natural_height(True)
        scroller.set_child(listbox)
        box.append(scroller)

        note = label(C.NETWORK_LOOKING, "m3-label-medium", css="dim-label")
        self.widgets["panel.note"] = note
        box.append(note)

        rescan = Gtk.Button(label=C.NETWORK_AGAIN)
        rescan.add_css_class("flat")
        rescan.set_halign(Gtk.Align.START)
        rescan.connect("clicked", lambda _b: self.refresh_networks(scan=True))
        self.widgets["panel.rescan"] = rescan
        box.append(rescan)
        return box

    def _build_shade(self) -> Gtk.Widget:
        """What the screen is before anybody has touched it.

        The clock, the date, whatever is true about today, and a greeting.
        Nothing that belongs to a person, because no person has arrived.

        The spacer at the bottom is the whole trick of this screen and it is
        worth explaining. The accounts page and this one are two pages of one
        stack, centred in the same space, and a shorter page centres higher.
        Without the spacer the clock sits lower here than it does over the
        accounts, and lifting the shade jerks it upward by about a hundred
        pixels. With it, the two pages are the same height, the clock is at
        the same pixel in both, and the only thing that happens on lifting is
        that the accounts arrive underneath a clock that has not moved.
        """
        # Three groups, not five lines.
        #
        # Every line used to be twenty four pixels from the next, which
        # makes five different sentences read as one list of five things.
        # The time and the date are one thought. The occasion and the
        # greeting are another. The hint is a third and belongs further
        # away than either, because it is an instruction rather than a
        # statement. Grouping is done with the spacing alone: nothing here
        # changed size, and the page stopped reading as a list.
        box = column(34)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)

        when = column(2)
        when.set_halign(Gtk.Align.CENTER)
        clock = label("", "m3-display-large", center=True, wrap=False)
        clock.add_css_class("aurade-greeter-clock")
        self.widgets["shade.clock"] = clock
        when.append(clock)

        date = label("", "m3-title-medium", center=True, wrap=False,
                     css="dim-label")
        self.widgets["shade.date"] = date
        when.append(date)

        # Under the date, because that is what it is about. Shown only where
        # the clock is wrong beyond argument, which is a dead coin cell and
        # not a machine that merely has no time server.
        wrong = label(C.CLOCK_WRONG, "m3-label-medium", center=True,
                      wrap=True, css="aurade-status")
        wrong.set_visible(SET.clock_is_wrong())
        self.widgets["shade.clock.wrong"] = wrong
        when.append(wrong)
        box.append(when)

        said = column(8)
        said.set_halign(Gtk.Align.CENTER)
        greeting = label("", "m3-headline-small", center=True)
        self.widgets["shade.greeting"] = greeting
        said.append(greeting)

        # Under the greeting rather than above it, and in the brand
        # colour at a readable size.
        #
        # This is the one line on the screen that is not simply the time,
        # and it was the smallest and dimmest thing on the page, sitting
        # above the greeting where it read as a caption for it. A full
        # moon is not a caption for good evening.
        #
        # Eleven or twelve days a year it says something. Every other day
        # it is not drawn at all, rather than drawn empty, so nothing
        # below it sits a line lower for the sake of a blank.
        occasion = label("", "m3-title-small", center=True, wrap=True)
        occasion.add_css_class("aurade-occasion")
        occasion.set_visible(False)
        self.widgets["shade.occasion"] = occasion
        said.append(occasion)
        box.append(said)

        # What the sky is doing, faintly, under the greeting.
        #
        # Only when it is doing something. A line reading "partly cloudy" has
        # spent somebody's attention on a fact they can get by turning their
        # head, and this screen is already asking for a password. Absent
        # rather than empty, so nothing below moves on a clear day.
        weather_line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                               spacing=8)
        weather_line.set_halign(Gtk.Align.CENTER)
        weather_line.set_visible(False)
        weather_mark = WUI.SkyMark(19)
        weather_mark.set_valign(Gtk.Align.CENTER)
        weather_line.append(weather_mark)
        weather_words = label("", "m3-label-large", center=True, wrap=False,
                              css="dim-label")
        weather_line.append(weather_words)
        self.widgets["shade.weather"] = weather_line
        self.widgets["shade.weather.mark"] = weather_mark
        self.widgets["shade.weather.words"] = weather_words
        said.append(weather_line)

        hint = label(C.SHADE_HINT, "m3-label-medium", center=True, wrap=False,
                     css="dim-label")
        self.widgets["shade.hint"] = hint
        box.append(hint)

        # Under everything that says something, so the height this page has to
        # make up sits below the writing rather than through the middle of it.
        spacer = Gtk.Box()
        spacer.set_hexpand(False)
        self.widgets["shade.spacer"] = spacer
        box.append(spacer)

        A.described(box, C.SHADE_LABEL, C.SHADE_HELP)
        self.widgets["shade.box"] = box
        return self._shell(box)

    # -- lifting it ----------------------------------------------------------

    def lift(self) -> bool:
        """Somebody is here. Bring the accounts up under the clock.

        Once only: every later press is a press on whatever is now on screen,
        and a lock screen that re-runs its entrance because somebody clicked
        twice is a lock screen that fights the person using it.
        """
        if self.shade_up:
            return False
        self.shade_up = True
        self.stack.set_visible_child_name("accounts")
        self._stop_rotating()
        self._stagger_accounts()
        # After the stack switch, not during it. A row that is not mapped yet
        # refuses focus silently, and the next Return then goes to whatever the
        # window considers first, which is the weather tile in the status bar.
        GLib.idle_add(self._focus_first_row)
        # The card goes with the shade, because it is about the photograph and
        # the photograph is no longer the subject. Faded rather than dropped:
        # a caption that vanishes between two frames is the one moment on this
        # screen where somebody would notice a seam.
        card = self.widgets.get("card")
        if card is not None and card.get_visible():
            if not self.animate:
                card.set_visible(False)
            else:
                card.add_css_class("aurade-gone")
                GLib.timeout_add(240, lambda: (card.set_visible(False), False)[1])
        return True

    def _on_press(self, _gesture, _presses: int, x: float, y: float) -> None:
        """A press anywhere lifts the shade, except on the pills.

        The weather and the system pill are on screen while the shade is down
        and they are pressable there deliberately: checking whether it is
        raining should not require signing in first. So a press that landed
        inside the shelf is a press on the shelf, and lifting as well would
        answer a question nobody asked.
        """
        # A warning covering the screen is got past by a press as well as by
        # a key, for the same reason the shade is: a trackpad is the only
        # input some of these machines have that works one handed.
        if self.takeover.dismiss():
            return
        node = self.pick(x, y, Gtk.PickFlags.DEFAULT)
        shelf = self.widgets.get("shelf")
        while node is not None:
            if node is shelf:
                return
            node = node.get_parent()
        self.lift()

    def _stagger_accounts(self) -> None:
        """The rows arrive one after another rather than all at once.

        Forty four milliseconds apart, from the top. It is the difference
        between a list appearing and a list arriving, it costs one CSS class
        and one timer per row, and it is the single cheapest thing on this
        screen that makes it feel like somebody built it.

        Somebody who asked for stillness gets the list, immediately, with no
        motion at all. Honoured by not moving rather than by moving less.
        """
        while self._arrivals:
            source = self._arrivals.pop()
            try:
                GLib.source_remove(source)
            except (ValueError, TypeError):  # already fired
                pass
        listbox = self.widgets.get("accounts.list")
        if listbox is None:
            return
        rows = _children(listbox)
        for index, row_widget in enumerate(rows):
            if not self.animate:
                row_widget.add_css_class("aurade-arrived")
                continue

            def arrive(widget=row_widget, source=[0]):
                widget.add_css_class("aurade-arrived")
                if source[0] in self._arrivals:
                    self._arrivals.remove(source[0])
                return False

            handle = GLib.timeout_add(ARRIVE_MS * index + 20, arrive)
            arrive.__defaults__[1][0] = handle
            self._arrivals.append(handle)

    #: The pages that already show the hour in ninety point type.
    #:
    #: Both of them, which is the part that made the first version of this
    #: wrong: keying it off whether the shade had lifted looked right and
    #: still left two clocks on the account list, because the account list
    #: carries the big clock too. Only the password page does not.
    CLOCKED = ("shade", "accounts")

    def _sync_status_clock(self) -> None:
        """The shelf keeps the time except where the screen already has it.

        Two pages show the hour at ninety points in the middle of the
        window. Repeating it at eleven points in the corner is not a
        second reading, it is the same reading twice, and the corner is
        the one to lose. The hairline goes with it, because a rule with
        nothing on the far side of it separates a thing from nothing.
        """
        page = self.stack.get_visible_child_name() or ""
        wanted = page not in self.CLOCKED
        for name in ("status.clock", "status.rule"):
            found = self.widgets.get(name)
            if found is not None:
                found.set_visible(wanted)

    def _sync_shade(self) -> None:
        """Make the two pages the same height, so the clock does not move.

        Measured rather than guessed, because the accounts page is as tall as
        this machine has accounts and no number written here would be right on
        the next machine.
        """
        shade = self.widgets.get("shade.box")
        accounts = self.widgets.get("accounts.box")
        spacer = self.widgets.get("shade.spacer")
        if shade is None or accounts is None or spacer is None:
            return
        spacer.set_size_request(-1, 0)
        _, wanted, _, _ = accounts.measure(Gtk.Orientation.VERTICAL, -1)
        _, have, _, _ = shade.measure(Gtk.Orientation.VERTICAL, -1)
        spacer.set_size_request(-1, max(0, wanted - have))

    def _show_card(self) -> None:
        """What the photograph is, if this person wants to be told."""
        card = self.widgets.get("card")
        if card is None:
            return
        wanted = (SET.truthy(self.behaviour.get("photo_card", "on"), True)
                  and self.wallpaper.present)
        known = card.show_picture(self.wallpaper.picture if wanted else None)
        card.set_visible(bool(wanted and known and not self.shade_up))

    # -- the photographs, changing --------------------------------------------

    def _start_rotating(self) -> None:
        """Move to the next photograph now and then, while the shade is down.

        Only while it is down. A picture that changed underneath somebody
        typing their password would be a moving background behind a field, and
        the whole reason the fade is a second and a half is that nothing is
        waiting on it.
        """
        if self._rotate_source or not SET.rotates(self.behaviour):
            return
        if self.wallpaper.plain:
            return
        if not self.wallpaper.present or len(brand.wallpapers()) < 2:
            return
        seconds = SET.interval(self.behaviour.get("photo_interval", "120"))
        self._rotate_source = GLib.timeout_add_seconds(seconds, self._rotate)

    def _stop_rotating(self) -> None:
        if self._rotate_source:
            GLib.source_remove(self._rotate_source)
            self._rotate_source = 0

    def _rotate(self) -> bool:
        if self.shade_up:
            self._rotate_source = 0
            return False
        following = self.wallpaper.pick(avoid=self.wallpaper.picture)
        if following is not None:
            self.wallpaper.fade_to(following, self.animate)
            # The card follows the picture into the fade rather than snapping
            # to the new one on the first frame, so the two arrive together.
            GLib.timeout_add(WALLPAPER_FADE_MS // 2 if self.animate else 0,
                             lambda: (self._show_card(),
                                      self._refresh_glass(), False)[2])
        return True

    def _on_glass(self, child: Gtk.Widget, name: str) -> Gtk.Widget:
        """`child`, standing on frosted photograph, where there is one.

        Where there is not, the child is returned untouched and keeps the flat
        ground the stylesheet gives it. That is the whole fallback: a machine
        with no wallpaper set, or somebody who turned high contrast on, gets
        exactly the screen they got before this existed.
        """
        if not self.wallpaper.present:
            return child
        child.add_css_class("aurade-on-glass")
        frosted = Frosted(child, self.wallpaper)
        self.widgets[name] = frosted
        return frosted

    def _refresh_glass(self) -> None:
        """Every ground forgets its picture, because the picture changed."""
        for name in ("card.glass", "accounts.glass", "password.glass"):
            found = self.widgets.get(name)
            if found is not None:
                found.refresh()

    def _build_accounts(self) -> Gtk.Widget:
        box = column(28)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)

        clock = label("", "m3-display-large", center=True, wrap=False)
        clock.add_css_class("aurade-greeter-clock")
        self.widgets["clock"] = clock
        box.append(clock)
        date = label("", "m3-title-medium", center=True, wrap=False,
                     css="dim-label")
        self.widgets["date"] = date
        box.append(date)

        heading = label(C.TITLE, "m3-headline-small", center=True)
        self.widgets["accounts.heading"] = heading
        box.append(heading)

        listbox = Gtk.ListBox()
        listbox.add_css_class("boxed-list")
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        listbox.connect("row-activated", self._on_account_row)
        self.widgets["accounts.list"] = listbox
        holder = Adw.Clamp(maximum_size=PANEL_WIDTH)
        holder.set_child(self._on_glass(listbox, "accounts.glass"))
        box.append(holder)

        empty = label(C.NO_ACCOUNTS, "m3-body-medium", center=True)
        empty.set_visible(False)
        self.widgets["accounts.empty"] = empty
        box.append(empty)
        self.widgets["accounts.box"] = box
        return self._shell(box)

    def _build_handoff(self) -> Gtk.Widget:
        """What the screen shows while the desktop is starting.

        greetd takes the greeter away the moment the session is handed over,
        so this page cannot cover the whole gap on its own. It covers the part
        the greeter still owns, and it exists so that the last thing somebody
        sees is their own name rather than the screen going out.
        """
        box = column(16)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)

        avatar_holder = column(0)
        avatar_holder.set_halign(Gtk.Align.CENTER)
        self.widgets["handoff.avatar"] = avatar_holder
        box.append(avatar_holder)

        title = label("", "m3-headline-small", center=True)
        self.widgets["handoff.title"] = title
        box.append(title)

        note = label(C.HANDOFF_NOTE, "m3-label-medium", center=True,
                     css="dim-label")
        self.widgets["handoff.note"] = note
        box.append(note)

        progress = Gtk.ProgressBar()
        progress.set_show_text(False)
        progress.set_size_request(220, -1)
        progress.set_halign(Gtk.Align.CENTER)
        self.widgets["handoff.progress"] = progress
        box.append(progress)
        return box

    def to_handoff(self) -> None:
        """Put the person's own name up while the desktop starts."""
        account = self.chosen
        title = account.title if account is not None else self.typed_name
        first = title.split()[0] if title.strip() else ""
        holder = self.widgets["handoff.avatar"]
        child = holder.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            holder.remove(child)
            child = following
        holder.append(Avatar(account, 72) if account is not None else Mark(64))
        self.widgets["handoff.title"].set_label(
            C.HANDOFF_TITLE.format(first=first) if first else C.HANDOFF_TITLE_PLAIN)
        self.stack.set_visible_child_name("handoff")
        A.announce(self.widgets["handoff.note"], C.HANDOFF_NOTE)
        self._start_handoff_pulse()

    def _start_handoff_pulse(self) -> None:
        """A bar that moves, because a bar that does not is a bar that hung.

        Nothing here knows how far along the desktop is, so this deliberately
        pulses rather than claiming a fraction it cannot measure.
        """
        bar = self.widgets.get("handoff.progress")
        if bar is None or not self.animate:
            return
        if self._handoff_source is not None:
            return

        def step() -> bool:
            bar.pulse()
            return True

        bar.set_pulse_step(0.08)
        self._handoff_source = GLib.timeout_add(90, step)

    def _stop_handoff_pulse(self) -> None:
        if self._handoff_source is not None:
            GLib.source_remove(self._handoff_source)
            self._handoff_source = None

    def _build_password(self) -> Gtk.Widget:
        box = column(18)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)
        # Both margins set to the shake's own amplitude, so the animation has
        # room to move the card in either direction without ever asking for
        # more width than it already has.
        box.set_margin_start(SHAKE_PIXELS)
        box.set_margin_end(SHAKE_PIXELS)
        self.widgets["password.card"] = box

        avatar_holder = column(0)
        avatar_holder.set_halign(Gtk.Align.CENTER)
        self.widgets["password.avatar"] = avatar_holder
        box.append(avatar_holder)

        name = label("", "m3-headline-small", center=True)
        self.widgets["password.name"] = name
        box.append(name)

        self.entry = Gtk.PasswordEntry()
        self.entry.set_show_peek_icon(True)
        self.entry.set_property("placeholder-text", C.PASSWORD)
        self.entry.connect("activate", lambda _e: self.submit())
        self.entry.connect("changed", lambda _e: self._clear_error())
        self.widgets["password.entry"] = self.entry

        self.name_entry = Gtk.Entry()
        self.name_entry.set_property("placeholder-text", C.USERNAME)
        self.name_entry.connect("activate", lambda _e: self._named_account())
        self.name_entry.set_visible(False)
        self.widgets["password.username"] = self.name_entry

        field_holder = column(10)
        field_holder.append(self.name_entry)
        field_holder.append(self.entry)
        clamp = Adw.Clamp(maximum_size=PANEL_WIDTH)
        clamp.set_child(field_holder)
        box.append(clamp)

        caps = label(C.CAPS_LOCK, "m3-label-medium", center=True,
                     css="aurade-status")
        caps.set_visible(False)
        self.widgets["password.caps"] = caps
        box.append(caps)

        # Beside Caps Lock, because it answers the same question and it
        # is the answer people do not think of. Hidden until a password
        # has actually been refused: stated up front it is a fact nobody
        # needs, and stated after a refusal it is the reason.
        layout = label("", "m3-label-medium", center=True,
                       css="aurade-status")
        layout.set_visible(False)
        self.widgets["password.layout"] = layout
        box.append(layout)

        note = label(C.PASSWORD_HELP, "m3-label-medium", center=True,
                     css="dim-label")
        self.widgets["password.note"] = note
        box.append(note)

        error = label("", "m3-body-medium", center=True)
        error.add_css_class("error")
        error.set_visible(False)
        self.widgets["password.error"] = error
        box.append(error)

        buttons = row(10)
        buttons.set_halign(Gtk.Align.CENTER)
        back = Gtk.Button(label=C.BACK)
        back.add_css_class("flat")
        back.connect("clicked", lambda _b: self.to_accounts())
        self.widgets["password.back"] = back
        buttons.append(back)
        sign_in = Gtk.Button(label=C.SIGN_IN)
        sign_in.add_css_class("suggested-action")
        sign_in.add_css_class("pill")
        sign_in.connect("clicked", lambda _b: self.submit())
        self.widgets["password.submit"] = sign_in
        buttons.append(sign_in)
        box.append(buttons)

        picker_holder = column(6)
        picker_holder.set_halign(Gtk.Align.CENTER)
        picker_holder.set_visible(False)
        self.widgets["password.session.holder"] = picker_holder
        box.append(picker_holder)
        self.widgets["password.box"] = box
        # The last page still standing on bare photograph.
        #
        # The account list has had a ground since the glass landed and
        # this one has not, so the name, the field, the hint and both
        # buttons sit on the picture with only the veil between them.
        # On Antelope Canyon the field lands squarely in the shaft of
        # light and the placeholder is close to unreadable, which is
        # the case the veil was never going to carry: the set now
        # reaches luminance 0.53 and it reached 0.20 when that
        # decision was made.
        #
        # Padding rather than margin, and that distinction matters
        # here: `Frosted` moves a child's margins onto itself, so a
        # margin would push the glass away from the screen edge and
        # leave it exactly the size of the words. Padding sits inside
        # the allocation, which is what the glass is measured from.
        box.add_css_class("aurade-password-card")
        return self._shell(self._on_glass(box, "password.glass"))

    def _shell(self, child: Gtk.Widget) -> Gtk.Widget:
        holder = column(0)
        holder.set_valign(Gtk.Align.CENTER)
        holder.set_halign(Gtk.Align.CENTER)
        holder.set_hexpand(True)
        holder.set_vexpand(True)
        holder.append(child)
        return holder

    # -- the network, which is the way in ----------------------------------

    def refresh_networks(self, scan: bool = False) -> None:
        """Read the radio on a worker, draw the answer on the main loop.

        A scan takes seconds and NetworkManager is entitled to take its time.
        A login screen that stops repainting while it waits looks exactly like
        one that has crashed, and the person in front of it starts holding the
        power button.
        """
        if self._network_busy:
            return
        self._network_busy = True
        self.widgets["panel.note"].set_label(C.NETWORK_LOOKING)

        def read():
            device = self.nm.wifi_device()
            if device is None:
                return None, [], ""
            if scan:
                try:
                    self.nm.scan(device["path"])
                except NET.NetworkError:
                    # A refused scan still leaves the last results worth
                    # showing, and saying so is better than an empty list.
                    pass
            return device, self.nm.networks(device["path"]), ""

        Worker(read, self._on_networks).start()

    def _on_networks(self, result, error) -> bool:
        self._network_busy = False
        note = self.widgets["panel.note"]
        listbox = self.widgets["panel.list"]
        child = listbox.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            listbox.remove(child)
            child = following
        if error is not None:
            # Reading the radio failed, which is not the same as a network
            # refusing to be joined, so the fallback here says so.
            note.set_label(str(error) if isinstance(error, NET.NetworkError)
                           else C.NETWORK_UNREACHABLE)
            note.set_visible(True)
            self.widgets["panel.state"].set_label("")
            return False
        device, found, _ = result
        self.wifi = device
        if device is None:
            note.set_label(C.NETWORK_NO_RADIO)
            note.set_visible(True)
            self.widgets["panel.state"].set_label("")
            return False
        self.widgets["panel.state"].set_label(
            NET.state_words(int(device.get("state", 0)), device["kind"]))
        active = next((n for n in found if n.active), None)
        # The pill draws arcs and sysfs cannot tell it how many. This is the
        # only place a real number is known, so it is kept here and the next
        # tick uses it.
        self._wifi_strength = int(active.strength) if active is not None else None
        self.widgets["pod.network.state"].set_label(
            active.ssid if active is not None else C.PANEL_NETWORK_OFF)
        self.widgets["pod.network.icon"].update(
            kind="wifi", online=active is not None,
            strength=int(active.strength) if active is not None else 0)
        self._pod_lit("network", active is not None)
        for chosen in found:
            listbox.append(self._network_row(chosen))
        note.set_visible(not found)
        if not found:
            note.set_label(C.NETWORK_NONE)
        return False

    def _network_row(self, chosen) -> Gtk.Widget:
        line = Adw.ActionRow(title=chosen.ssid)
        if chosen.active:
            line.set_subtitle(C.NETWORK_ON)
        elif chosen.saved:
            line.set_subtitle(C.NETWORK_SAVED)
        elif chosen.secured:
            line.set_subtitle(C.NETWORK_LOCKED)
        icon = G.Network(18)
        icon.update(kind="wifi", online=True, strength=int(chosen.strength))
        line.add_prefix(icon)
        if chosen.secured:
            lock = G.Lock(14)
            line.add_suffix(lock)
        line.set_activatable(True)
        line.network = chosen
        A.described(line, chosen.ssid,
                    C.DESCRIBE_NETWORK.format(name=chosen.ssid,
                                              bars=chosen.bars))
        return line

    def _on_network_row(self, _listbox, line) -> None:
        chosen = getattr(line, "network", None)
        if chosen is None or self.wifi is None:
            return
        if chosen.active:
            self._join(chosen, None, leave=True)
            return
        if chosen.needs_passphrase:
            self._ask_passphrase(chosen)
            return
        self._join(chosen, None)

    def _ask_passphrase(self, chosen) -> None:
        """One field, in a dialog, and the secret is never held here.

        The entry is read once when the dialog answers and the text goes
        straight to NetworkManager. Nothing on this screen keeps it, which is
        the same rule the sign in field follows.
        """
        dialog = Adw.AlertDialog(
            heading=C.NETWORK_JOIN.format(name=chosen.ssid),
            body=C.NETWORK_JOIN_BODY)
        entry = Gtk.PasswordEntry()
        entry.set_show_peek_icon(True)
        entry.set_property("placeholder-text", C.PASSWORD)
        entry.set_margin_top(8)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", C.NETWORK_CANCEL)
        dialog.add_response("join", C.NETWORK_JOIN_ACTION)
        dialog.set_response_appearance("join", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("join")
        dialog.set_close_response("cancel")
        entry.connect("activate", lambda _e: dialog.close())

        def answered(_dialog, response):
            if response != "join":
                return
            self._join(chosen, entry.get_text())

        dialog.connect("response", answered)
        self.widgets["panel"].popdown()
        dialog.present(self)

    def _join(self, chosen, passphrase, leave: bool = False) -> None:
        device = self.wifi
        if device is None:
            return
        self.widgets["panel.note"].set_visible(True)
        self.widgets["panel.note"].set_label(
            C.NETWORK_LEAVING if leave
            else C.NETWORK_JOINING.format(name=chosen.ssid))

        def work():
            if leave:
                self.nm.leave(device)
            else:
                self.nm.join(device, chosen, passphrase)
            return True

        def done(_result, error):
            if error is not None:
                self.widgets["panel.note"].set_label(
                    str(error) if isinstance(error, NET.NetworkError)
                    else C.NETWORK_REFUSED)
                self.widgets["panel.note"].set_visible(True)
                A.announce(self.widgets["panel.note"],
                           self.widgets["panel.note"].get_label(), urgent=True)
            else:
                # NetworkManager answers before the association finishes, so
                # the list is read again rather than assumed.
                GLib.timeout_add(1500, lambda: self.refresh_networks() or False)
            return False

        Worker(work, done).start()

    # -- accounts ----------------------------------------------------------

    def reload_accounts(self) -> None:
        self.accounts = ACC.accounts()
        listbox = self.widgets["accounts.list"]
        child = listbox.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            listbox.remove(child)
            child = following
        for account in self.accounts:
            listbox.append(self._account_row(account))
        listbox.append(self._other_row())
        self.widgets["accounts.empty"].set_visible(not self.accounts)
        if "shade.greeting" in self.widgets:
            self._say_today()
        else:
            self.widgets["accounts.heading"].set_label(
                C.TITLE if ACC.last_user() else C.TITLE_FIRST)
        # A reload after the shade has already gone up is not an entrance.
        # Somebody who signed out and came back should find the list there,
        # not watch it introduce itself a second time.
        if self.shade_up:
            for child in list(_children(self.widgets["accounts.list"])):
                child.add_css_class("aurade-arrived")
        self._sync_shade()

    def _account_row(self, account: ACC.Account) -> Gtk.Widget:
        line = Adw.ActionRow(title=account.title)
        if account.subtitle != account.title:
            line.set_subtitle(account.subtitle)
        line.add_prefix(Avatar(account))
        line.set_activatable(True)
        line.add_css_class("aurade-arrive")
        line.account = account
        A.described(line, account.title,
                    C.DESCRIBE_ACCOUNT.format(name=account.title))
        return line

    def _other_row(self) -> Gtk.Widget:
        line = Adw.ActionRow(title=C.OTHER, subtitle=C.OTHER_HELP)
        icon = Gtk.Image.new_from_icon_name("system-users-symbolic")
        icon.set_pixel_size(24)
        icon.set_size_request(48, 48)
        icon.set_valign(Gtk.Align.CENTER)
        line.add_prefix(icon)
        line.set_activatable(True)
        line.add_css_class("aurade-arrive")
        line.account = None
        A.described(line, C.OTHER, C.OTHER_HELP)
        return line

    # -- sessions ----------------------------------------------------------

    def _load_sessions(self) -> None:
        """Fill the picker, and hide it on the machines that have one answer.

        A dropdown with a single item is a control that cannot be used, and it
        makes a login screen look like it is asking a question it is not.
        """
        available = SES.sessions()
        self.widgets["password.session.list"] = available
        holder = self.widgets["password.session.holder"]
        if len(available) < 2:
            holder.set_visible(False)
            return
        holder.set_visible(True)
        caption = label(C.SESSION, "m3-label-medium", center=True, css="dim-label")
        holder.append(caption)
        picker = Gtk.DropDown.new_from_strings(
            [session.name for session in available])
        picker.set_selected(0)
        A.described(picker, C.SESSION, C.SESSION_HELP)
        self.widgets["password.session.picker"] = picker
        holder.append(picker)

    def _on_account_row(self, _listbox, line) -> None:
        account = getattr(line, "account", None)
        if account is None:
            self.to_named()
            return
        self.choose(account)

    # -- moving between the two screens ------------------------------------

    def to_accounts(self) -> None:
        """Back out, and tell greetd so it does not keep the attempt open."""
        self._stop_handoff_pulse()
        self._end_session()
        self.chosen = None
        self.typed_name = ""
        self.entry.set_text("")
        self._clear_error()
        self.stack.set_visible_child_name("accounts")
        self._focus_first_row()

    def to_named(self) -> None:
        """Somebody whose account is not on the list."""
        self.chosen = None
        self.typed_name = ""
        self._show_person(C.OTHER, None)
        self.name_entry.set_visible(True)
        self.name_entry.set_text("")
        self.entry.set_visible(False)
        self.widgets["password.note"].set_label(C.OTHER_HELP)
        self.stack.set_visible_child_name("password")
        self.name_entry.grab_focus()

    def _named_account(self) -> None:
        name = self.name_entry.get_text().strip()
        if not name:
            return
        self.typed_name = name
        self.name_entry.set_visible(False)
        self.entry.set_visible(True)
        self.widgets["password.note"].set_label(C.PASSWORD_HELP)
        self._show_person(name, None)
        self._begin(name)

    def choose(self, account: ACC.Account) -> None:
        self.chosen = account
        self.typed_name = ""
        self.name_entry.set_visible(False)
        # The field stays hidden until the login service asks for a secret.
        # An account with no password is never asked for one, and putting an
        # empty box in front of somebody who is already being signed in reads
        # as a screen that ignored what they were about to type.
        self.entry.set_visible(False)
        self.entry.set_text("")
        self.widgets["password.note"].set_label(C.CHECKING)
        self._show_person(account.title, account)
        self.stack.set_visible_child_name("password")
        self._working(True)
        self._begin(account.name)

    def _show_person(self, title: str, account: ACC.Account | None) -> None:
        holder = self.widgets["password.avatar"]
        child = holder.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            holder.remove(child)
            child = following
        holder.append(Avatar(account, 72) if account is not None else Mark(64))
        self.widgets["password.name"].set_label(title)
        # The field says whose password it wants. "Password" is a label for
        # a form; a name is the screen answering the person standing at it,
        # and on a machine with three accounts it is also the quickest way
        # to notice that the wrong one is selected.
        #
        # First name only. The full name is already above the field in
        # headline type and repeating it inside the box reads as a form.
        first = title.split()[0] if title.strip() else ""
        self.entry.set_property(
            "placeholder-text",
            C.PASSWORD_FOR.format(name=first) if first else C.PASSWORD)
        A.described(self.entry, C.PASSWORD,
                    C.DESCRIBE_PASSWORD.format(name=title))

    def _focus_field(self, widget: Gtk.Widget) -> bool:
        if widget.get_visible():
            widget.grab_focus()
        return False

    def _focus_first_row(self) -> None:
        """A row, never the list.

        Focusing a GtkListBox outlines the whole container and a screen reader
        announces the word list, which tells somebody standing in front of
        their own login screen nothing at all.
        """
        listbox = self.widgets["accounts.list"]
        line = listbox.get_row_at_index(0)
        if line is not None:
            line.grab_focus()
        return False

    # -- the conversation --------------------------------------------------

    def _begin(self, username: str) -> None:
        if self.transport is None:
            self._fail(C.OUTSIDE_GREETD)
            return
        self._end_session()
        session = P.Session(self.transport)
        self.session = session
        self._working(True)
        Worker(lambda: session.begin(username), self._on_prompt).start()

    def submit(self) -> None:
        if self.busy:
            return
        if self.name_entry.get_visible():
            self._named_account()
            return
        session = self.session
        if session is None:
            self._fail(C.SERVICE_GONE)
            return
        secret = self.entry.get_text()
        # Emptied before the worker starts, not after it answers. The field
        # has a peek icon, and a password sitting in it while a slow PAM
        # module thinks is a password on a screen in a room with other people
        # in it for as long as that takes.
        self.entry.set_text("")
        self._working(True)
        Worker(lambda: session.answer(secret), self._on_prompt).start()

    def _on_prompt(self, prompt, error) -> bool:
        self._working(False)
        if isinstance(error, P.AuthFailed):
            self.session = None
            words = self._refusal_words()
            self._shake()
            self._show_error(words)
            self._say_layout()
            self.entry.grab_focus()
            A.announce(self.entry, words, urgent=True)
            self._restart_attempt()
            return False
        if error is not None:
            self._fail(C.SERVICE_GONE)
            return False
        if prompt is not None:
            # Focus after the field has been mapped, not in the same breath as
            # making it visible. A widget that is not on screen yet refuses
            # focus without saying so, and the field then sits there waiting
            # for a click nobody should have to make.
            if prompt.secret:
                self.entry.set_visible(True)
                GLib.idle_add(self._focus_field, self.entry)
            else:
                self.name_entry.set_visible(True)
                self.name_entry.set_text("")
                GLib.idle_add(self._focus_field, self.name_entry)
            self.widgets["password.note"].set_label(
                prompt.text or C.PASSWORD_HELP)
            return False
        self._start_session()
        return False

    def _shake(self) -> None:
        """The card refuses, visibly, without moving anything else.

        The two margins move together and in opposite directions, so the space
        the card asks for never changes and nothing around it reflows. Animate
        one margin alone and the whole page breathes in and out, which is the
        obvious implementation and looks like a bug.

        A password refused in silence, on a screen where the field also
        empties itself, is a screen that looks like it did nothing at all.
        """
        card = self.widgets.get("password.card")
        if card is None or not self.animate:
            return

        def step(value, _user=None):
            offset = shake_offset(value)
            card.set_margin_start(SHAKE_PIXELS + offset)
            card.set_margin_end(SHAKE_PIXELS - offset)

        target = Adw.CallbackAnimationTarget.new(step)
        self._shaking = Adw.TimedAnimation.new(card, 0.0, 1.0, SHAKE_MS,
                                               target)
        self._shaking.play()

    def _refusal_words(self) -> str:
        """What to say about a password that did not work, this time.

        The stack below locks an account after a few of these, and saying
        "that password did not work" for the fourth time running describes a
        broken machine rather than one protecting somebody. The numbers are
        `pam_faillock`'s own, read at the moment they are needed, so this
        describes the policy the machine is running.

        Nothing extra is ever said where no lockout is configured, because the
        alternative is a login screen explaining a rule it invented.
        """
        name = self.chosen.name if self.chosen else self.typed_name
        if name != self._refused_for:
            self._refused_for = name
            self._refusals = 0
        self._refusals += 1

        policy = SET.lockout_policy()
        if policy is None:
            return C.WRONG
        deny, unlock = policy
        if self._refusals >= deny:
            return C.locked_words(unlock)
        if self._refusals == deny - 1:
            return f"{C.WRONG} {C.LOCKOUT_SOON}"
        return C.WRONG

    def _restart_attempt(self) -> None:
        """greetd ends the attempt on a refusal, so the next try needs a new one."""
        name = self.chosen.name if self.chosen else self.typed_name
        if name and self.transport is not None:
            session = P.Session(self.transport)
            self.session = session
            Worker(lambda: session.begin(name), self._on_retry_prompt).start()

    def _on_retry_prompt(self, prompt, error) -> bool:
        if error is not None:
            self._fail(C.SERVICE_GONE)
        return False

    def _start_session(self) -> None:
        session = self.session
        if session is None:
            self._fail(C.SERVICE_GONE)
            return
        chosen = self._chosen_session()
        if chosen is None:
            self._fail(C.SESSION_GONE)
            return
        command = SES.wrapped(chosen.command)
        environment = [
            "XDG_SESSION_TYPE=wayland",
            "XDG_CURRENT_DESKTOP=AuraDE",
            f"XDG_SESSION_DESKTOP={chosen.ident.removesuffix('.desktop')}",
        ]
        name = self.chosen.name if self.chosen else self.typed_name
        self._working(True)
        self.widgets["password.submit"].set_label(C.SIGNING_IN)
        self.to_handoff()

        def start():
            session.start(command, environment)
            ACC.remember(name)
            return True

        Worker(start, self._on_started).start()

    def _on_started(self, _result, error) -> bool:
        self._working(False)
        self.widgets["password.submit"].set_label(C.SIGN_IN)
        if error is not None:
            self._show_error(C.SESSION_GONE)
            A.announce(self.entry, C.SESSION_GONE, urgent=True)
        return False

    def _chosen_session(self):
        holder = self.widgets.get("password.session.picker")
        available = self.widgets.get("password.session.list") or []
        if holder is not None and available:
            index = holder.get_selected()
            if 0 <= index < len(available):
                return available[index]
        return available[0] if available else None

    def _end_session(self) -> None:
        session = self.session
        self.session = None
        if session is None:
            return
        Worker(session.cancel, lambda *_: False).start()

    # -- state a person can see --------------------------------------------

    def _working(self, busy: bool) -> None:
        """What goes dead while greetd is thinking, and what never does.

        The power buttons are deliberately not in this list. A PAM module that
        hangs would otherwise take the restart button with it, and the way out
        of a login screen that has stopped answering has to be something other
        than holding the power switch.
        """
        self.busy = busy
        for name in ("password.submit", "password.back"):
            widget = self.widgets.get(name)
            if widget is not None:
                widget.set_sensitive(not busy)
        self.entry.set_sensitive(not busy)

    def _show_error(self, text: str) -> None:
        widget = self.widgets["password.error"]
        widget.set_label(text)
        widget.set_visible(True)

    def _clear_error(self) -> None:
        self.widgets["password.error"].set_visible(False)
        found = self.widgets.get("password.layout")
        if found is not None:
            found.set_visible(False)

    def _say_layout(self) -> None:
        """Name the keyboard, now that a password has been refused.

        Silent where the machine cannot say what its layout is, because a
        line reading "This keyboard is set to" and then nothing is worse
        than no line at all.
        """
        found = self.widgets.get("password.layout")
        if found is None:
            return
        words = SET.layout_words(SET.keyboard_layout())
        if not words:
            return
        found.set_label(C.KEYBOARD_LAYOUT.format(layout=words))
        found.set_visible(True)

    def _fail(self, text: str) -> None:
        """Something the person cannot fix by typing again.

        The message stays on screen and the power buttons stay reachable,
        because the way out of a dead login service is a restart and a greeter
        that hides the restart button during a failure is a greeter that needs
        the power switch.
        """
        self._working(False)
        self._show_error(text)
        A.announce(self.entry, text, urgent=True)

    # -- keys, clock, status, frames ---------------------------------------

    def _on_key(self, _controller, keyval: int, _code: int, _state) -> bool:
        # Any key at all, which is what the hint on the shade promises. The
        # press is swallowed so that the key somebody happened to hit does not
        # also arrive at whatever the lift just put under their cursor.
        if not self.shade_up:
            self.lift()
            return True
        if keyval == Gdk.KEY_Escape:
            if self.stack.get_visible_child_name() == "password":
                self.to_accounts()
                return True
        self._refresh_caps()
        return False

    def _refresh_caps(self) -> None:
        widget = self.widgets.get("password.caps")
        if widget is None:
            return
        display = Gdk.Display.get_default()
        seat = display.get_default_seat() if display is not None else None
        keyboard = seat.get_keyboard() if seat is not None else None
        on = bool(keyboard.get_caps_lock_state()) if keyboard is not None else False
        if on != widget.get_visible():
            widget.set_visible(on)
            if on:
                A.announce(widget, C.CAPS_LOCK)

    def _start_clock(self) -> None:
        self._tick_clock()

    def _tick_clock(self) -> bool:
        now = time.time()
        reading = ST.clock(now)
        written = time.strftime("%A, %e %B",
                                time.localtime(now)).replace("  ", " ")
        self.widgets["clock"].set_label(reading)
        self._tick_status_clock()
        self.widgets["date"].set_label(written)
        # The shade carries its own copies at the same size in the same place,
        # so the two pages can be crossfaded without anything appearing to
        # move. Both are set from one reading rather than two calls, because
        # two calls a millisecond apart across a minute boundary would put a
        # different time on each page for as long as the shade stayed down.
        if "shade.clock" in self.widgets:
            self.widgets["shade.clock"].set_label(reading)
            self.widgets["shade.date"].set_label(written)
            self._say_today()
        # Land on the next minute rather than every sixty seconds from now, so
        # the displayed minute changes when the minute changes.
        delay = int(60 - (now % 60)) or 60
        self._clock_source = GLib.timeout_add_seconds(delay, self._tick_clock)
        return False

    def _say_today(self) -> None:
        """The greeting, and the line that is only there when it is true.

        The same greeting goes on both pages, in the same slot, at the same
        size. It was two different words, "Good afternoon" on the shade and
        "Welcome" behind it, and since the two pages cross fade in place that
        read as the sentence rewriting itself. With one word, lifting the
        shade changes exactly one thing on the screen, which is the accounts
        arriving, and that is the whole idea.
        """
        when = datetime.datetime.now().astimezone()
        words = SH.greeting(when, self.behaviour.get("greeting", "hour"),
                            bool(ACC.last_user()))
        self.widgets["shade.greeting"].set_label(words)
        heading = self.widgets.get("accounts.heading")
        if heading is not None:
            heading.set_label(words)

        where = SET.coordinates(self.behaviour)
        today = SH.occasion(when, where[0] if where else None)
        occasion = self.widgets["shade.occasion"]
        was = occasion.get_visible()
        occasion.set_label(today)
        occasion.set_visible(bool(today))
        # The occasion is a whole line, and a line appearing changes how tall
        # this page is, which is what the spacer exists to cancel out. Without
        # this the clock sat twenty five pixels higher on the shade than on
        # the accounts, and lifting jerked it down.
        if was != bool(today):
            self._sync_shade()

    def _start_status(self) -> None:
        self._tick_status()
        self._status_source = GLib.timeout_add(
            STATUS_INTERVAL_MS, self._tick_status)

    def _tick_status(self) -> bool:
        power = ST.battery()
        percent = power.get("percent")
        charging = bool(power.get("charging"))
        # A machine with no battery says nothing about batteries. An empty
        # percentage or a hyphen where a number belongs is a reading, and a
        # desktop reporting nothing about a battery it does not have is not.
        self.widgets["status.battery.pair"].set_visible(percent is not None)
        if percent is not None:
            self.widgets["status.battery.icon"].update(
                percent=int(percent), charging=charging)
            self.widgets["status.battery"].set_label(f"{percent}%")
        # The panel row reads the kernel again rather than being handed this
        # one, because it wants the rate and the state as well and reading
        # twice costs four small files. Fed from here so the two cannot drift
        # apart on screen at the same moment.
        self._paint_battery_row()
        link = ST.network()
        kind = str(link.get("kind", ""))
        online = bool(link.get("online"))
        name = str(link.get("name") or "")
        # `status.network()` reports which interface is carrying the machine,
        # not how strong it is, because it reads sysfs and sysfs does not say.
        # The real number comes from NetworkManager when the panel reads it,
        # so the arcs use that once it is known. Until then a connected radio
        # draws full rather than empty: an unknown strength shown as no signal
        # is a lie, and it is the specific lie that sends somebody looking for
        # a fault that is not there.
        strength = self._wifi_strength if self._wifi_strength is not None else 100
        self.widgets["status.network.icon"].update(
            kind=kind, online=online, strength=strength)
        self.widgets["status.network"].set_label(name)
        # The name left the face, so it has to stay somewhere it is still
        # announced, or a screen reader user loses a fact a sighted user can
        # still get by opening the panel.
        A.described(self.widgets["status"], C.STATUS_AREA,
                    self._status_sentence(kind, online, name, percent, charging))
        return True

    def _status_sentence(self, kind: str, online: bool, name: str,
                         percent, charging: bool) -> str:
        """What the pill would say if it were read out loud.

        Three drawn marks and a number are four facts to a sighted person and
        nothing at all to a screen reader. This is the same four, in the order
        somebody would say them.
        """
        parts: list[str] = []
        if not kind:
            parts.append(C.STATUS_NO_NETWORK)
        elif not online:
            parts.append(C.STATUS_NETWORK_DOWN)
        elif name:
            parts.append(C.STATUS_NETWORK_ON.format(name=name))
        else:
            parts.append(C.STATUS_NETWORK_UP)
        if percent is not None:
            parts.append((C.STATUS_BATTERY_CHARGING if charging
                          else C.STATUS_BATTERY).format(percent=percent))
        parts.append(C.STATUS_AREA_HELP)
        return " ".join(parts)

    def _tick_status_clock(self) -> None:
        """The small clock in the cluster, beside the large one on the page."""
        widget = self.widgets.get("status.clock")
        if widget is not None:
            widget.set_label(ST.clock(time.time()))

    def _start_frames(self) -> None:
        if not self.animate:
            return
        self._frame_last = time.monotonic()
        self._frame_source = GLib.timeout_add(FRAME_MS, self._tick_frame)

    def _tick_frame(self) -> bool:
        now = time.monotonic()
        self.aurora.advance(now - self._frame_last)
        self._frame_last = now
        return True

    # -- power -------------------------------------------------------------

    def _confirm_power(self, action: str, heading: str, body: str) -> None:
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("stay", C.POWER_STAY)
        dialog.add_response("go", C.RESTART if action == "restart" else C.SHUT_DOWN)
        dialog.set_response_appearance("go", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("stay")
        dialog.set_close_response("stay")
        dialog.connect("response",
                       lambda _d, response: self.power(action)
                       if response == "go" else None)
        dialog.present(self)

    def power(self, action: str) -> bool:
        """Ask logind, and say so plainly when it says no."""
        override = os.environ.get("AURADE_GREETER_POWER_COMMAND")
        argv = ([override, action] if override
                else ["systemctl", "reboot" if action == "restart" else "poweroff"])
        try:
            finished = subprocess.run(argv, check=False, timeout=20)
        except (OSError, subprocess.SubprocessError):
            self._fail(C.SERVICE_GONE)
            return False
        if finished.returncode != 0:
            self._fail(C.SERVICE_GONE)
            return False
        return True


class GreeterApplication(Adw.Application):
    def __init__(self, transport: P.Transport | None) -> None:
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.transport = transport
        self.window = None

    def do_activate(self) -> None:  # noqa: N802  (GObject naming)
        if self.window is None:
            self.window = GreeterWindow(self, self.transport)
        self.window.fullscreen()
        self.window.present()


def run(argv: list[str] | None = None) -> int:
    Adw.init()
    try:
        transport = P.Transport.connect()
    except P.GreeterError:
        transport = None
    return GreeterApplication(transport).run(argv or [])
