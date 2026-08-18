"""The GTK4/libadwaita widget layer.

The only module here that imports ``gi``. Everything it draws is either a
string from :mod:`aurade_gui.flow`, a colour from :mod:`aurade_gui.tokens` or
an answer from the model process, so this file can be read as a layout and
nothing in it decides what the installer does.

The visual language is Material 3 applied to the AuraDE mark. The palette is a
tonal system generated from the ribbon in the logo, surfaces are M3 containers,
interaction is an M3 state layer rather than a colour swap, and the shape and
type scales are the published ones. What stops it reading as stock is that the
accents are the brand's own two hues, the chrome carries the real mark and
wordmark, and the aurora behind the page is the ring from the logo opened out
to fill a window.

Two registers of type, throughout. Prose is set in the system sans. Anything
the user has to match against hardware or type back exactly - a device path, a
disk serial, the erase token, a stage timing - is set in mono, because a face
that separates 0 from O is the difference between confirming the right disk
and confirming a different one.

Keyboard first. Every page has a default action on Return and a back action on
Escape, both labelled with what they actually do; focus lands on the first
control of each page as it appears; lists are operable with the arrow keys and
Space. A graphical installer that requires a pointing device is a graphical
installer that excludes people.
"""

from __future__ import annotations

import os
import re

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk  # noqa: E402

from . import (a11y as A, bible, brand, flow as F, locales, stage as S,  # noqa: E402
               tokens as T, wait as W)
from .bridge import Bridge, BridgeError  # noqa: E402

APP_ID = "org.aurade.Installer"

#: What the window is called when nothing is installing.
WINDOW_TITLE = "AuraDE Installer"

#: How often the progress page re-reads the journal. The journal is the only
#: account of what happened; this is a view of it and keeps no tally.
PROGRESS_INTERVAL_MS = 400

#: Aurora frame interval. Slow on purpose: this is atmosphere behind text
#: someone is reading, not an animation anyone should watch.
AURORA_INTERVAL_MS = 90

#: The arena on the progress page, in cells and pixels. Sized so the card is
#: the same height whichever face it is showing, which is why the tip lane is
#: two lines and this is nine rows.
SNAKE_COLUMNS = 28
SNAKE_ROWS = 9
SNAKE_CELL = 16

#: How often the snake moves. Slower than a redraw, so the game is playable
#: rather than frantic.
SNAKE_INTERVAL_MS = 150

#: The score at which the snake stops being two colours and starts being the
#: brand gradient. Nobody gets here by accident.
SNAKE_GRADIENT_AT = 10

#: The drawn progress ribbon. Thicker than a stock bar, because it carries a
#: gradient and a leading cap and both need room to be visible at a glance.
PROGRESS_RIBBON_HEIGHT = 12

#: The size bar on a disk row. Narrow, because it is repeating a number that
#: is already written out two lines below it in mono, and the number is the
#: authority. Six pixels tall so it has a shape rather than being a rule.
CAPACITY_WIDTH = 84
CAPACITY_HEIGHT = 6

#: The done screen's settle. The pause is what makes it read as the page
#: arriving rather than as a slow icon: the words are already there and being
#: read, and then the tick catches up.
SETTLE_DELAY_MS = 160
SETTLE_MS = 520

#: How far the highlight travels per second, in ribbon lengths. Slow: this is
#: a sign of life on a five minute step, not something to watch.
PROGRESS_SHEEN_PER_SECOND = 0.22

#: Environment that means "this machine is drawing without a GPU". The
#: launcher sets these when it walks down to a software path, and they are the
#: only honest signal available: asking GTK which renderer it ended up with
#: says nothing about the compositor underneath it.
SOFTWARE_MARKERS = (
    ("AURADE_SAFE_GRAPHICS", "1"),
    ("GSK_RENDERER", "cairo"),
    ("LIBGL_ALWAYS_SOFTWARE", "1"),
    ("WLR_RENDERER", "pixman"),
)


def software_drawing() -> bool:
    return any(os.environ.get(name) == value for name, value in SOFTWARE_MARKERS)


_LIB = os.path.dirname(os.path.realpath(__file__))
THEME_CSS = os.path.join(_LIB, "theme.css")
THEME_DARK_CSS = os.path.join(_LIB, "theme-dark.css")
#: The same two schemes with every pair held to 7:1 and an outline on every
#: container. Four sheets rather than two because GTK's `@define-color` is
#: global: there is no selector or media query that can give a named colour a
#: second value, which is the same reason light and dark are separate files.
THEME_HC_CSS = os.path.join(_LIB, "theme-hc.css")
THEME_DARK_HC_CSS = os.path.join(_LIB, "theme-dark-hc.css")
#: The dark scheme with the ground switched off rather than dimmed. An OLED
#: pixel at #000000 draws no power and has infinite contrast; `#121318` is a
#: pixel that is on and pretending, and it is most of the screen for ten
#: minutes.
THEME_OLED_CSS = os.path.join(_LIB, "theme-oled.css")


# --------------------------------------------------------------------------
# Small builders
# --------------------------------------------------------------------------


def label(text: str, style: str = "m3-body-medium", *, wrap: bool = True,
          center: bool = False, css: str | None = None) -> Gtk.Label:
    widget = Gtk.Label(label=text)
    widget.set_wrap(wrap)
    if wrap:
        widget.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
    widget.set_xalign(0.5 if center else 0.0)
    widget.set_justify(Gtk.Justification.CENTER if center else Gtk.Justification.LEFT)
    widget.set_max_width_chars(58)
    widget.add_css_class(style)
    if css:
        widget.add_css_class(css)
    return widget


def column(spacing: int = 16) -> Gtk.Box:
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)


def row(spacing: int = 12) -> Gtk.Box:
    return Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)


def pane(child: Gtk.Widget, style: str = "aurade-pane") -> Gtk.Box:
    holder = column(0)
    holder.add_css_class(style)
    child.set_margin_top(16)
    child.set_margin_bottom(16)
    child.set_margin_start(16)
    child.set_margin_end(16)
    holder.append(child)
    return holder


#: How wide a page's content is allowed to get.
#:
#: Prose has a comfortable measure and 660px is about right for it. Cards,
#: disk rows and network lists are not prose: clamping a five-card grid to a
#: reading measure in a 1440px window produces one column down the middle and
#: two thirds of the screen left empty, which is what this installer looked
#: like before. Pages say which they are.
PROSE_WIDTH = 660
BOARD_WIDTH = 940


def page_shell(child: Gtk.Widget, width: int = PROSE_WIDTH) -> Gtk.Widget:
    box = column(20)
    # Top aligned, deliberately. Centring the content of every page makes a
    # short page look balanced and makes the title jump vertically on every
    # step, because the pages are not the same height. A heading that moves
    # when you press Continue is worse than a page with room underneath it.
    box.set_margin_top(44)
    box.set_margin_bottom(26)
    box.set_margin_start(24)
    box.set_margin_end(24)
    box.append(child)
    # The sheet the page stands on.
    #
    # Transparent, marginless and invisible until the window says there is a
    # photograph behind it, at which point this becomes the opaque ground
    # under every word on the page. One extra box either way, and with no
    # wallpaper the CSS gives it nothing at all, so the layout is exactly the
    # layout there was before there were any pictures.
    #
    # It is here rather than on `box` because the 44 and 24 pixel margins are
    # the page's own breathing room and have to end up inside the ground, not
    # between the ground and the window.
    sheet = column(0)
    sheet.add_css_class("aurade-sheet")
    sheet.append(box)
    # As tall as the page, not as tall as the window.
    #
    # The clamp gives its child the whole height, which nobody could see for
    # as long as the child had no ground of its own. With one, a four line
    # review page was a seven hundred pixel slab of empty white over a
    # photograph. Pages that asked to be centred in the window still are: it
    # is the sheet that centres now rather than the content inside it, which
    # is the same result and one fewer empty container.
    sheet.set_valign(Gtk.Align.CENTER if child.get_vexpand() else Gtk.Align.START)
    clamp = Adw.Clamp(maximum_size=width, tightening_threshold=int(width * 0.85))
    clamp.set_child(sheet)
    scroller = Gtk.ScrolledWindow()
    scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroller.set_vexpand(True)
    # A scrollbar that takes up space rather than one that fades in when
    # touched. This installer runs on screens as short as 768 pixels, where a
    # disk list and an open disclosure do not fit, and an overlay scrollbar on
    # a page nobody is scrolling yet is a page that looks complete and is not.
    scroller.set_overlay_scrolling(False)
    scroller.set_child(clamp)
    return scroller


def icon_tile(name: str, state: str = "", size: int = 18) -> Gtk.Widget:
    """One icon, in a disc of its own colour.

    Material 3's leading icon in a shape, and the reason it is worth the two
    extra widgets is that it makes a list of rows scannable without reading
    it: a column of identical ticks says five things passed, a column of
    subjects says which five.
    """
    tile = Gtk.Box()
    # Every one of these repeats its row's title. Scannability for the eye,
    # noise for a reader.
    A.decorative(tile)
    tile.add_css_class("aurade-icon-tile")
    if state:
        tile.add_css_class(f"aurade-tile-{state}")
    tile.set_valign(Gtk.Align.CENTER)
    image = Gtk.Image.new_from_icon_name(name)
    image.set_pixel_size(size)
    tile.append(image)
    return tile


def reveal(widget: Gtk.Widget) -> None:
    """Scroll whatever page `widget` is on until all of it is visible.

    Opening a disclosure adds rows below the fold on a short screen, which
    looks exactly like a disclosure with nothing in it. GTK will not scroll to
    content that appeared as a result of the click that revealed it, so this
    does, once the new rows have been given a size.
    """
    scroller = widget.get_ancestor(Gtk.ScrolledWindow)
    if scroller is None:
        return

    def settle() -> bool:
        child = scroller.get_child()
        found, bounds = widget.compute_bounds(child)
        if not found:
            return GLib.SOURCE_REMOVE
        adjustment = scroller.get_vadjustment()
        bottom = bounds.origin.y + bounds.size.height
        if bottom > adjustment.get_value() + adjustment.get_page_size():
            adjustment.set_value(min(bottom - adjustment.get_page_size(),
                                     adjustment.get_upper() - adjustment.get_page_size()))
        return GLib.SOURCE_REMOVE

    GLib.idle_add(settle, priority=GLib.PRIORITY_LOW)


# --------------------------------------------------------------------------
# Brand chrome
# --------------------------------------------------------------------------


class Wallpaper(Gtk.DrawingArea):
    """One photograph, under everything, for as long as the installer runs.

    Under the aurora rather than instead of it. The set is twenty eight
    pictures with deliberately nothing in common, which is what stops them
    reading as a theme and would also make the installer look like twenty
    eight different products; the aurora over the top of them, at half
    strength, is the thing that makes them one.

    Whichever of this and the aurora is actually showing paints the ground.
    Exactly one of them does, always, which is why this paints a plain surface
    when the picture will not load rather than leaving the window undefined
    for the frame it takes to notice.
    """

    #: What the bands are before anything has been laid out. The first frame
    #: is drawn before the chrome has a position, and a first frame with the
    #: wordmark sitting on a mountain is the one frame everybody sees.
    FIRST_FRAME_TOP = 58
    FIRST_FRAME_BOTTOM = 74

    #: Added above the action bar's own top edge. Its margin is outside its
    #: allocation, so the measured edge is where the buttons start and not
    #: where the eye reads the band as starting.
    BAND_SLACK = 10

    def __init__(self, window: "InstallerWindow") -> None:
        super().__init__()
        self.window = window
        self.set_draw_func(self._draw)
        self.set_can_target(False)
        A.decorative(self)

    def _bands(self, height: int) -> tuple[int, int]:
        """How tall the opaque part of each band has to be, right now.

        Measured from the chrome rather than assumed, because the chrome grows
        with the text scale and somebody who set text to 200% is the last
        person who should end up reading a heading over a photograph.
        """
        top, bottom = self.FIRST_FRAME_TOP, self.FIRST_FRAME_BOTTOM
        rule = self.window.widgets.get("rule")
        if rule is not None:
            found, bounds = rule.compute_bounds(self.window)
            if found:
                top = int(bounds.origin.y + bounds.size.height)

        # Both, because the action bar is not always the lowest thing. The
        # progress page hides its buttons, which leaves the row a few pixels
        # tall at the very bottom and the credit line below it, on the
        # photograph, which is exactly the case this band exists to prevent.
        edge = None
        for name in ("actions", "caption"):
            widget = self.window.widgets.get(name)
            if widget is None or not widget.get_visible():
                continue
            found, bounds = widget.compute_bounds(self.window)
            if found:
                edge = bounds.origin.y if edge is None else min(edge, bounds.origin.y)
        if edge is not None:
            bottom = int(height - edge) + self.BAND_SLACK
        return max(0, top), max(0, bottom)

    def _draw(self, _area, cr, width: int, height: int) -> None:
        entry = self.window.wallpaper_shown
        if entry is None:
            return
        top, bottom = self._bands(height)
        if brand.draw_wallpaper(cr, width, height, entry["path"], self.window.dark,
                                top, bottom):
            return
        cr.set_source_rgb(*T.rgb(T.scheme(self.window.dark)["surface"]))
        cr.paint()
        # Said once. A picture that will not decode is not going to decode on
        # the next frame either, and a caption naming a photograph nobody can
        # see is worse than no caption.
        self.window.drop_wallpaper()


class Aurora(Gtk.DrawingArea):
    """The backdrop. The mark's ring, opened out to fill the window."""

    def __init__(self, window: "InstallerWindow") -> None:
        super().__init__()
        self.window = window
        self.phase = 0.0
        self.set_draw_func(self._draw)
        self.set_can_target(False)
        # Decoration. It says nothing the words do not, and a reader working
        # through a page does not want a canvas announced to it.
        A.decorative(self)

    def _draw(self, _area, cr, width: int, height: int) -> None:
        # Over a photograph the aurora stops being the ground and becomes a
        # cast of the brand's own light across somebody else's picture, which
        # is a different job and a quieter one.
        grounded = self.window.wallpaper_shown is not None
        brand.draw_aurora(
            cr, width, height, self.window.dark, self.phase,
            ground=not grounded,
            strength=brand.WALLPAPER_AURORA if grounded else 1.0)

    def advance(self) -> bool:
        self.phase += 0.012
        self.queue_draw()
        return GLib.SOURCE_CONTINUE


class Swoop(Gtk.DrawingArea):
    """The mark being made, over the whole window, once per session.

    It plays on the way out of the welcome screen, which is the only moment in
    an installer where a second of ceremony costs nothing: the question after
    it is already built and waiting underneath.
    """

    def __init__(self, window: "InstallerWindow") -> None:
        super().__init__()
        self.window = window
        self.phase = 0.0
        self.set_draw_func(self._draw)
        # Never in the way. It covers the page it is revealing, and a pointer
        # that lands on it instead of on the button underneath would be a
        # second of decoration eating a click.
        self.set_can_target(False)
        self.set_visible(False)
        A.decorative(self)

    def _draw(self, _area, cr, width: int, height: int) -> None:
        brand.draw_swoop(cr, width, height, self.window.dark, self.phase)


class RibbonRule(Gtk.DrawingArea):
    """The gradient across the `A`, reduced to a hairline."""

    def __init__(self, window: "InstallerWindow") -> None:
        super().__init__()
        self.window = window
        self.set_content_height(2)
        self.set_draw_func(
            lambda _a, cr, w, h: brand.draw_ribbon_rule(cr, w, h, self.window.dark))
        self.set_can_target(False)
        A.decorative(self)


class ProgressRibbon(Gtk.DrawingArea):
    """The install, drawn as the mark's stroke instead of as a stock bar.

    ``fraction`` is a real GObject property, which is the whole reason this is
    a class rather than a draw function: it lets the same
    ``Adw.PropertyAnimationTarget`` that used to ease a ``Gtk.ProgressBar``
    ease this instead, so the easing behaviour and its test survive the change
    of what is on the screen.

    ``get_fraction`` and ``set_fraction`` are kept because that is the shape
    the rest of the page already speaks.
    """

    fraction = GObject.Property(type=float, default=0.0,
                                minimum=0.0, maximum=1.0)

    def __init__(self, window: "InstallerWindow") -> None:
        super().__init__()
        self.window = window
        self.phase = 0.0
        self.set_content_height(PROGRESS_RIBBON_HEIGHT)
        self.set_can_target(False)
        self.set_draw_func(self._draw)
        self.connect("notify::fraction", lambda *_a: self.queue_draw())
        # Not decoration. It is a progress bar that happens to be drawn as the
        # mark's stroke, and dropping it would cost a reader the one thing on
        # the screen that says how far along an install is. `describe` keeps
        # the percentage current; see `_refresh_progress`.
        A.meter(self, "Installation progress", 0.0, 0.0, 1.0)

    def _draw(self, _area, cr, width, height) -> None:
        brand.draw_progress_ribbon(cr, width, height, self.window.dark,
                                   self.fraction, self.phase)

    def get_fraction(self) -> float:
        return self.fraction

    def set_fraction(self, value: float) -> None:
        self.fraction = max(0.0, min(1.0, value))


class Wordmark(Gtk.DrawingArea):
    """The real logotype, painted in whichever ink the surface needs."""

    def __init__(self, window: "InstallerWindow", height: int = 18) -> None:
        super().__init__()
        self.window = window
        self._height = height
        self.set_content_height(height)
        self.set_content_width(int(height * 4.4))
        self.set_draw_func(self._draw)
        self.set_can_target(False)
        self.set_tooltip_text("AuraDE")
        # The word "AuraDE" is written next to this in the header, so a reader
        # that announced the drawing too would say it twice.
        A.decorative(self)

    def _draw(self, _area, cr, _width, height) -> None:
        colour = T.scheme(self.window.dark)["on_surface"]
        brand.draw_wordmark(cr, 0, 0, min(height, self._height), colour)


class Mark(Gtk.DrawingArea):
    """The application mark, from the artwork."""

    def __init__(self, size: int = 36) -> None:
        super().__init__()
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_draw_func(lambda _a, cr, w, h: brand.draw_mark(cr, w, h, min(w, h)))
        self.set_can_target(False)
        A.decorative(self)


#: What each arc count means, for the reader who cannot count arcs.
SIGNAL_WORDS = {0: "none", 1: "weak", 2: "fair", 3: "good", 4: "excellent"}


class CapacityBar(Gtk.DrawingArea):
    """One disk's size, against the biggest one being offered.

    A list of disks is the one page where two rows can be genuinely
    indistinguishable: same maker, same model number, same transport, one row
    apart. The words already separate them and somebody reading carefully will
    get it right. This is for the glance before the reading, which is the same
    argument the icon tiles are here for.
    """

    def __init__(self, window: "InstallerWindow", fraction: float) -> None:
        super().__init__()
        self.window = window
        self.fraction = fraction
        self.set_content_width(CAPACITY_WIDTH)
        self.set_content_height(CAPACITY_HEIGHT)
        self.set_valign(Gtk.Align.CENTER)
        self.set_draw_func(
            lambda _a, cr, w, h: brand.draw_capacity(
                cr, w, h, self.window.dark, self.fraction))
        self.set_can_target(False)
        # The size is written out exactly, in mono, in this row's own
        # subtitle. Announcing the bar as well would be the same fact twice,
        # and the imprecise one of the two.
        A.decorative(self)


class SignalArcs(Gtk.DrawingArea):
    """Four arcs. A column of percentages is not a thing anyone reads."""

    def __init__(self, window: "InstallerWindow", strength: int) -> None:
        super().__init__()
        self.window = window
        self.strength = strength
        self.set_content_width(22)
        self.set_content_height(20)
        self.set_draw_func(self._draw)
        self.set_can_target(False)
        # Four arcs are how a sighted user reads signal strength here. Without
        # this the network list is a column of names with nothing to choose
        # between them.
        A.described(self, "Signal strength", SIGNAL_WORDS.get(strength, ""),
                    Gtk.AccessibleRole.IMG)

    def _draw(self, _area, cr, width, height) -> None:
        scheme = T.scheme(self.window.dark)
        brand.draw_signal(cr, width, height, self.strength,
                          scheme["primary"], scheme["outline_variant"])


# --------------------------------------------------------------------------
# The window
# --------------------------------------------------------------------------


class InstallerWindow(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application, model: Bridge, plan_only: bool):
        super().__init__(application=application)
        self.model = model
        self.flow = F.Flow(plan_only=plan_only)
        self.names = locales.Names()
        self.manifest: dict = {}
        self.widgets: dict = {}
        #: The readiness rows currently in the list, so a refresh can take out
        #: exactly what it put in. AdwPreferencesGroup has no "empty me".
        self.readiness_rows: list = []
        #: The passing checks, which live inside the details disclosure.
        self.detail_rows: list = []
        self.group_rows: dict = {}
        self.stage_rows: dict = {}
        self.secrets_set: set = set()
        self.enum_values: dict = {}
        self.probe: dict = {}
        self.install_status = 0
        #: The last thing said out loud, so a refresh on a timer does not
        #: repeat itself. Empty means nothing has been announced yet.
        self._spoken_stage = ""
        self._spoken_page = ""
        #: Whether the high contrast sheets are the ones loaded. Read back from
        #: the bridge rather than remembered here, so the two front ends cannot
        #: disagree about what is currently on.
        self.high_contrast = False
        #: Whether the true black ground is wanted. Only meaningful in the dark
        #: scheme, which is the only place a ground can be switched off.
        self.oled = False
        #: The overlay that carries line and letter spacing, or None.
        self._spacing_provider = None
        #: Set by a page that will not let the flow past it. Read once, in
        #: `refresh`, after the page has drawn.
        self.forward_blocked = False
        self.failure_cause = ""
        self.dark = False
        self._progress_source = 0
        # The waiting card. `tips` is read once, from the same file the text
        # installer reads; `snake` is created the first time somebody asks for
        # it and never before, because most installs will not.
        self.tips = W.Tips()
        self.tip_index = 0
        self._tip_source = 0
        self.snake: W.Snake | None = None
        self._snake_source = 0
        self._aurora_source = 0
        #: The photograph behind the window, picked once for this run. None
        #: when the set is not installed, when the picture would not decode,
        #: or when it was never wanted: see `wallpaper_shown`.
        #:
        #: `AURADE_WALLPAPER` pins one by name, or turns them off with `none`.
        #: The preview tool and the tests both need to say which picture they
        #: are looking at, and so does anybody comparing two of them.
        self.wallpaper = brand.choose_wallpaper(os.environ.get("AURADE_WALLPAPER", ""))
        #: The mark animation plays once. Coming back to the welcome screen
        #: and leaving it again is not a new arrival.
        self._swooped = False
        #: The done screen's settle, likewise. There is only one arrival at
        #: the end of an install, and a refresh is not it.
        self._settled = False
        self._settle = None
        self._secret = ""
        self._provider = None
        self._gate_token = ""
        self._export_notice = None
        self._wifi_target = ""

        self.set_title(WINDOW_TITLE)
        self.set_default_size(980, 720)
        self.add_css_class("aurade")

        self._apply_theme()
        self._build_chrome()
        # Again, now that there is a caption to fill in. The first call ran
        # from `_apply_theme`, before this window had any widgets in it, which
        # is the right place for it because every later change to the ground
        # arrives through the stylesheet.
        self._update_ground()
        self._build_pages()
        self._install_shortcuts()
        self.refresh()

    # -- theme -------------------------------------------------------------

    def _apply_theme(self) -> None:
        """Load the stylesheet for the current scheme, and keep it current.

        Two sheets, one provider, reloaded on change. GTK's `@define-color` is
        global: a named colour has exactly one value per loaded sheet, and no
        selector or media query can give it a second one for the dark scheme.
        A single stylesheet therefore pins every custom surface to whichever
        scheme generated it, which is how this installer ended up drawing
        light-coloured cards, on a dark window, in text that could not be read.
        """
        manager = Adw.StyleManager.get_default()
        self.dark = manager.get_dark()
        manager.connect("notify::dark", self._on_scheme_changed)
        display = Gdk.Display.get_default()
        if display is None:
            return

        # Ask for the icon theme this front end was drawn against, rather than
        # whatever the machine happens to prefer. Every icon name here is
        # checked against the set the image installs, and an icon that is not
        # in the theme GTK ends up using does not fall back to a similar one:
        # it draws a "missing image" glyph, or nothing at all, in a page that
        # otherwise looks finished. On the image this is already the default;
        # on a developer's desktop it very often is not.
        settings = Gtk.Settings.get_for_display(display)
        if settings is not None:
            settings.set_property("gtk-icon-theme-name", "Adwaita")
            # The face, named rather than inherited. GTK's built-in default is
            # Cantarell, which the image does not install, so anything drawn
            # outside this stylesheet's reach would be whatever fontconfig
            # substitutes. Adwaita Sans is on the image because the toolkit
            # depends on it, and it is the face the type scale was set in.
            settings.set_property("gtk-font-name", "Adwaita Sans 11")
            # Light hinting, grayscale antialiasing: stems keep the shape the
            # face was drawn with instead of being snapped to the pixel grid.
            # A live image has no font configuration of its own, so leaving
            # these unset means the installer looks different depending on
            # what the distribution happened to default to that month.
            settings.set_property("gtk-xft-antialias", 1)
            settings.set_property("gtk-xft-hinting", 1)
            settings.set_property("gtk-xft-hintstyle", "hintslight")
            settings.set_property("gtk-xft-rgba", "none")
            # Motion is a luxury paid for by the graphics stack, and on the
            # machines this installer most often runs on there is no graphics
            # stack: the launcher walks down to a compositor that composites
            # in software and a GTK that draws with cairo, and every frame of
            # a transition is then a full-window redraw on the CPU. Turning
            # motion off there is not a downgrade - it is the difference
            # between a page that appears and a page that crawls into place.
            if software_drawing():
                settings.set_property("gtk-enable-animations", False)
        self._provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            display, self._provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._load_stylesheet()

    def _load_stylesheet(self) -> None:
        provider = getattr(self, "_provider", None)
        if provider is None:
            return
        try:
            if self.high_contrast:
                # High contrast wins over black. Both push the ground to an
                # extreme and the one somebody turned on to be able to read
                # is the one that should decide.
                provider.load_from_path(
                    THEME_DARK_HC_CSS if self.dark else THEME_HC_CSS)
            elif self.oled and self.dark:
                provider.load_from_path(THEME_OLED_CSS)
            else:
                provider.load_from_path(THEME_DARK_CSS if self.dark else THEME_CSS)
        except GLib.Error:
            # An unstyled installer is still an installer. Refusing to start
            # because a stylesheet is missing would trade a cosmetic failure
            # for the text-mode fallback.
            pass
        # Every route that changes the ground ends here: the scheme toggle,
        # the black button and the high contrast switch all reload the sheet,
        # so this is the one place that has to notice.
        self._update_ground()

    # -- the photograph ----------------------------------------------------

    @property
    def wallpaper_shown(self) -> dict | None:
        """The picture that is actually on the screen, or None.

        Off in high contrast, because high contrast exists so that somebody
        can read and a photograph is the opposite of that. Off in the black
        scheme, because that one exists so an OLED panel can leave its pixels
        unlit and a photograph lights every one of them. Both are decisions
        about what the ground is for; a wallpaper is a taste, and a taste does
        not get to overrule either.
        """
        if self.wallpaper is None or self.high_contrast:
            return None
        if self.oled and self.dark:
            return None
        return self.wallpaper

    def _update_ground(self) -> None:
        """Tell the window whether it is standing on a photograph.

        One class on the window, which every stylesheet rule that cares is
        scoped under, so the sheet under every page turns opaque and back with
        a single change. The caption is a widget and is told separately. The
        bands are neither: they are painted by the backdrop, which reads the
        same state per frame.
        """
        showing = self.wallpaper_shown
        if showing is None:
            self.remove_css_class("aurade-grounded")
        else:
            self.add_css_class("aurade-grounded")
        caption = self.widgets.get("caption")
        if caption is not None:
            caption.set_visible(showing is not None)
            if showing is not None:
                self._set_caption(showing)
        self._redraw_all(self)

    def _set_caption(self, entry: dict) -> None:
        caption = self.widgets.get("caption")
        if caption is None:
            return
        title = entry["title"] or entry["file"]
        caption.set_label(title)
        # No role: a button already reports itself as one, and the role
        # property is construct only on most widgets. The description is the
        # part worth setting, because the label says where the picture is and
        # says nothing about the button being a button.
        A.described(caption, title, F.WALLPAPER_HINT)

    def next_wallpaper(self) -> None:
        """Another one. The answer to not liking the one you were given."""
        available = [entry for entry in brand.wallpapers()
                     if self.wallpaper is None or entry["file"] != self.wallpaper["file"]]
        if not available:
            return
        import random  # noqa: PLC0415 - one call, on one code path

        self.wallpaper = random.choice(available)
        self._update_ground()

    def drop_wallpaper(self) -> None:
        """Give up on photographs for the rest of this run."""
        if self.wallpaper is None:
            return
        self.wallpaper = None
        self._update_ground()

    def _on_scheme_changed(self, manager, _param) -> None:
        self.dark = manager.get_dark()
        self._load_stylesheet()
        # Everything drawn reads its colours per frame, so a redraw is the
        # whole of the update. Everything styled follows the stylesheet.
        #
        # Every drawing area, not a list of three: the signal arcs on the
        # network page are drawn too, and a hand-maintained list is a list that
        # goes stale the next time something is drawn.
        self._redraw_all(self)

    def _redraw_all(self, widget: Gtk.Widget) -> None:
        if isinstance(widget, Gtk.DrawingArea):
            widget.queue_draw()
        child = widget.get_first_child()
        while child is not None:
            self._redraw_all(child)
            child = child.get_next_sibling()

    @property
    def animate(self) -> bool:
        """Whether motion is wanted here.

        GTK carries the accessibility preference. Nothing decorative runs when
        it is off, and nothing that runs is needed to understand a page.
        """
        settings = Gtk.Settings.get_default()
        if settings is None:
            return False
        return bool(settings.get_property("gtk-enable-animations"))

    # -- chrome ------------------------------------------------------------

    def _build_chrome(self) -> None:
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        backdrop = Gtk.Overlay()
        self.toast_overlay.set_child(backdrop)
        # Three layers, bottom first: the photograph, the brand's light over
        # it, then the interface.
        wallpaper = Wallpaper(self)
        self.widgets["wallpaper"] = wallpaper
        backdrop.set_child(wallpaper)
        aurora = Aurora(self)
        self.widgets["aurora"] = aurora
        backdrop.add_overlay(aurora)

        frame = column(0)
        self.widgets["frame"] = frame
        backdrop.add_overlay(frame)

        swoop = Swoop(self)
        self.widgets["swoop"] = swoop
        backdrop.add_overlay(swoop)

        # Top bar: the mark, the wordmark, and where the user is. No window
        # controls, because this is the only thing running and a close button
        # on an installer means something different at every step.
        top = row(12)
        top.set_margin_top(14)
        top.set_margin_bottom(12)
        top.set_margin_start(20)
        top.set_margin_end(20)
        top.append(Mark(32))
        wordmark = Wordmark(self, 18)
        wordmark.set_valign(Gtk.Align.CENTER)
        self.widgets["wordmark"] = wordmark
        top.append(wordmark)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        top.append(spacer)
        top.append(self._build_advanced_toggle())
        top.append(self._build_access_button())
        top.append(self._build_scheme_toggle())
        self.step_label = label("", "m3-label-medium", wrap=False, css="aurade-metric")
        self.step_label.set_valign(Gtk.Align.CENTER)
        top.append(self.step_label)
        frame.append(top)

        rule = RibbonRule(self)
        self.widgets["rule"] = rule
        frame.append(rule)

        self.banner = Adw.Banner()
        self.banner.set_revealed(False)
        frame.append(self.banner)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_transition_duration(240)
        self.stack.set_vexpand(True)
        frame.append(self.stack)

        # Bottom action bar. Material 3 puts the committing action on the
        # right in a filled button and the reversing one on the left with no
        # container, so visual weight matches consequence.
        actions = row(12)
        actions.set_margin_top(10)
        actions.set_margin_bottom(18)
        actions.set_margin_start(24)
        actions.set_margin_end(24)
        self.back_button = Gtk.Button(label="Quit")
        self.back_button.add_css_class("flat")
        self.back_button.add_css_class("m3-label-large")
        self.back_button.connect("clicked", lambda *_: self.on_back())
        actions.append(self.back_button)
        gap = Gtk.Box()
        gap.set_hexpand(True)
        actions.append(gap)
        self.secondary_button = Gtk.Button(label="")
        self.secondary_button.add_css_class("pill")
        self.secondary_button.set_visible(False)
        self.secondary_button.connect("clicked", lambda *_: self.on_secondary())
        actions.append(self.secondary_button)
        self.forward_button = Gtk.Button(label="Get started")
        self.forward_button.add_css_class("suggested-action")
        self.forward_button.add_css_class("pill")
        self.forward_button.add_css_class("m3-label-large")
        self.forward_button.connect("clicked", lambda *_: self.on_forward())
        actions.append(self.forward_button)
        self.widgets["actions"] = actions
        frame.append(actions)
        frame.append(self._build_caption())

    def _build_caption(self) -> Gtk.Widget:
        """Where the photograph is, and a way to get a different one.

        A credit line, in the corner, in the smallest type in the product,
        answering the only question a background ever prompts. It is a button
        rather than a label because the second thing anybody wants after "where
        is that" is "show me another one", and a caption that is already there
        is a better home for that than a preference nobody would find.

        Hidden entirely when there is no photograph, rather than left empty:
        a control that does nothing is worse than a control that is absent.
        """
        button = Gtk.Button(label="")
        button.add_css_class("flat")
        button.add_css_class("aurade-caption")
        button.add_css_class("m3-label-small")
        button.add_css_class("dim-label")
        button.set_halign(Gtk.Align.END)
        button.set_margin_end(24)
        button.set_margin_bottom(10)
        button.set_visible(False)
        button.set_tooltip_text(F.WALLPAPER_HINT)
        button.connect("clicked", lambda *_: self.next_wallpaper())
        self.widgets["caption"] = button
        return button

    def _build_advanced_toggle(self) -> Gtk.Widget:
        """A way in to the advanced page that does not require finding it.

        The advanced questions have working defaults, so the page is not in
        the flow by default and the step count stays honest. But the only way
        to reach it was a flat button on the review screen, at the end, next
        to the answers - which is to say that anyone looking for a package
        snapshot or a mirror while answering questions did not find one, and
        reasonably concluded the graphical installer did not have them.

        A toggle in the chrome is visible from every page, says which state it
        is in, and is reversible: turning it off takes the page back out of
        the flow rather than leaving an extra step behind for the rest of the
        session.
        """
        button = Gtk.ToggleButton()
        button.set_child(Gtk.Image.new_from_icon_name("document-properties-symbolic"))
        button.set_tooltip_text("Advanced options")
        button.update_property([Gtk.AccessibleProperty.LABEL], ["Advanced options"])
        button.add_css_class("flat")
        # Its own class, styled the same. The scheme buttons are a set of three
        # and things that count them - the runtime test among them - should not
        # have to know that a fourth button borrowed their look.
        button.add_css_class("aurade-chrome-button")
        button.set_valign(Gtk.Align.CENTER)
        button.set_margin_end(6)
        self._advanced_handler = button.connect("toggled", self._on_advanced_toggled)
        self.widgets["chrome.advanced"] = button
        return button

    def _on_advanced_toggled(self, button: Gtk.ToggleButton) -> None:
        if button.get_active():
            # Opening it goes there. A toggle that adds a step somewhere else
            # in the flow and leaves you where you were is a toggle that looks
            # like it did nothing.
            if self.flow.state == "pages":
                self.flow.jump_to_page("advanced")
            else:
                self.flow.set_show_advanced(True)
        else:
            self.flow.set_show_advanced(False)
        self.refresh()

    def _build_access_button(self) -> Gtk.Widget:
        """One icon, beside the scheme toggle, on every screen.

        Not a page in the flow. These are not part of deciding what to install,
        they are how somebody is able to use the installer at all, so answering
        them once at step three is the wrong shape: they have to be reachable
        from wherever you already are.

        `preferences-desktop-accessibility-symbolic` is the glyph people who
        need it already scan for, and it is unnoticed by everyone else in
        exactly the way the scheme toggle has been.
        """
        button = Gtk.Button()
        button.set_child(Gtk.Image.new_from_icon_name(
            "preferences-desktop-accessibility-symbolic"))
        button.set_tooltip_text("Accessibility")
        button.add_css_class("flat")
        button.set_valign(Gtk.Align.CENTER)
        button.set_margin_end(6)
        A.described(button, "Accessibility",
                    "Screen reader, contrast, text size and motion. "
                    "These are carried into the installed system.")
        button.connect("clicked", lambda *_: self.open_accessibility())
        self.widgets["access.button"] = button
        return button

    def open_accessibility(self) -> None:
        """The choices, read from the shared state rather than held here.

        The bridge sources the text installer, so there is exactly one set of
        these variables and both front ends read and write it. A copy kept here
        would be a second place for them to live, and the two would drift the
        way the failure remediation tables did.
        """
        try:
            report = self.model.call("access")
        except BridgeError as exc:
            self._toast(str(exc))
            return
        entries = report.get("access", {})
        order = (report.get("order") or "").split()

        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup()
        group.set_title("Accessibility")
        # The one sentence that makes this worth opening. Without it these look
        # like ten minutes of convenience rather than the settings the machine
        # will start with.
        group.set_description(
            "These take effect now, and are carried into the installed system.")
        for key in order:
            entry = entries.get(key)
            if not entry:
                continue
            values = entry.get("values", [])
            row_widget = Adw.ComboRow()
            row_widget.set_title(entry.get("label", key))
            row_widget.set_subtitle(entry.get("help", ""))
            row_widget.set_model(Gtk.StringList.new(
                [self._access_value_label(key, v) for v in values]))
            current = entry.get("value")
            if current in values:
                row_widget.set_selected(values.index(current))
            row_widget.connect("notify::selected",
                               self._on_access_changed, key, values)
            group.add(row_widget)
        page.add(group)

        dialog = Adw.PreferencesDialog()
        dialog.set_title("Accessibility")
        dialog.add(page)
        dialog.present(self)

    @staticmethod
    def _spell(text: str) -> str:
        """Say a device path so it can be heard rather than guessed at.

        `/dev/nvme0n1` read at speaking speed is a run of sounds. Naming the
        punctuation and separating the characters is the difference between
        hearing it and hearing something like it.
        """
        spoken = {"/": "slash", ":": "colon", "-": "dash",
                  "_": "underscore", ".": "dot"}
        return " ".join(spoken.get(c, c) for c in text)

    @staticmethod
    def _access_value_label(key: str, value: str) -> str:
        """`yes`, `no` and `high` are the engine's words, not a chooser's."""
        if key == "text_scale":
            return f"{value}%"
        if key == "cursor_size":
            return f"{value} pixels"
        return {"yes": "On", "no": "Off",
                "normal": "Normal", "high": "High",
                # Named, not explained. The UI says nothing about who a face is
                # for: telling somebody which typeface helps them is its own
                # kind of patronising, and preference is a real reason on its
                # own.
                "system": "Default",
                "atkinson": "Atkinson Hyperlegible",
                "opendyslexic": "OpenDyslexic",
                "roomy": "Roomy", "roomier": "Roomier"}.get(value, value)

    def _on_access_changed(self, row_widget, _param, key: str,
                           values: list) -> None:
        index = row_widget.get_selected()
        if index < 0 or index >= len(values):
            return
        try:
            result = self.model.call("access-set", f"{key}={values[index]}")
        except BridgeError as exc:
            self._toast(str(exc))
            return
        if not result.get("ok"):
            self._toast(result.get("error", "That could not be set."))
            return
        # Obeyed immediately as well as recorded, so the effect is visible
        # rather than promised. A settings screen where nothing appears to
        # happen is one people press twice and then stop trusting.
        self._obey_access(key, values[index])
        self.refresh()

    #: Line and letter spacing, as an overlay rather than a scheme.
    #:
    #: Three spacing levels times four schemes would be twelve stylesheets to
    #: generate, stage and keep in step. A second provider at a higher priority
    #: overrides two properties on top of whichever scheme is loaded, which is
    #: one file's worth of behaviour instead of eight more files.
    #:
    #: The engine writes the same rule into /etc/xdg/gtk-4.0/gtk.css on the
    #: installed system, so the setting is the same setting rather than a
    #: resemblance.
    SPACING_CSS = {
        "normal": "",
        "roomy": "label, entry, textview "
                 "{ line-height: 1.75; letter-spacing: 0.2px; }",
        "roomier": "label, entry, textview "
                   "{ line-height: 2.0; letter-spacing: 0.4px; }",
    }

    #: Family names to try for each choice, best first.
    #:
    #: Two names for OpenDyslexic because the package in the pinned snapshot is
    #: the Nerd Fonts build, and a patched build does not always keep the plain
    #: family name. Guessing wrong here is the failure this whole feature has
    #: to avoid: a font name written for a family that is not installed does
    #: not error, it silently renders in the default face, and somebody who
    #: needed the other one has no way to tell that it did not work.
    TYPEFACES = {
        "system": [],
        "atkinson": ["Atkinson Hyperlegible"],
        "opendyslexic": ["OpenDyslexic Nerd Font", "OpenDyslexic"],
    }

    def _resolve_family(self, names: list) -> str:
        """The first of `names` this machine actually has, or empty."""
        try:
            context = self.get_pango_context()
            have = {f.get_name() for f in context.list_families()}
        except Exception:  # pragma: no cover - no font map yet
            return ""
        for name in names:
            if name in have:
                return name
        return ""

    def _apply_typeface(self, value: str) -> None:
        settings = Gtk.Settings.get_default()
        if settings is None:
            return
        if value == "system":
            settings.reset_property("gtk-font-name")
            return
        family = self._resolve_family(self.TYPEFACES.get(value, []))
        if not family:
            # Said out loud rather than swallowed. The choice still travels to
            # the installed system, where the engine installs the package, so
            # the honest message is that it is not here yet rather than that it
            # did not work.
            self._toast("That face is not on this image. "
                        "It will be on the installed system.")
            return
        settings.set_property("gtk-font-name", f"{family} 11")

    def _apply_spacing(self, value: str) -> None:
        css = self.SPACING_CSS.get(value, "")
        display = self.get_display()
        if display is None:
            return
        if self._spacing_provider is not None:
            Gtk.StyleContext.remove_provider_for_display(
                display, self._spacing_provider)
            self._spacing_provider = None
        if not css:
            return
        provider = Gtk.CssProvider()
        provider.load_from_string(css)
        # Above the scheme sheet, which sets line height per type role.
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self._spacing_provider = provider

    def _obey_access(self, key: str, value: str) -> None:
        """Apply a choice to this installer, now.

        The GTK keys set here are the same ones the engine writes into
        `/etc/xdg/gtk-4.0/settings.ini` on the installed system, which is the
        point: what somebody sets up to get through the install is literally
        the configuration the machine starts with, rather than a separate
        thing that happens to resemble it.
        """
        settings = Gtk.Settings.get_default()
        if key == "contrast":
            self.high_contrast = value == "high"
            self._apply_theme()
        elif key == "reduce_motion" and settings is not None:
            # `self.animate` reads this property, so every animation in the
            # front end stops without any of them being told individually.
            settings.set_property("gtk-enable-animations", value != "yes")
        elif key == "text_scale" and settings is not None:
            # GTK counts dpi in 1024ths of a point, which is why 100 is not 100.
            settings.set_property("gtk-xft-dpi", int(value) * 96 * 1024 // 100)
        elif key == "cursor_size" and settings is not None:
            settings.set_property("gtk-cursor-theme-size", int(value))
        elif key == "spacing":
            self._apply_spacing(value)
        elif key == "typeface":
            self._apply_typeface(value)

    def _build_scheme_toggle(self) -> Gtk.Widget:
        """Light, dark, or whatever the system says.

        An installer runs before the system it is installing has any
        preference, and it runs in every kind of room - a bright office, a
        dark server rack at two in the morning. libadwaita will follow a
        desktop setting, but on the installation image there is no desktop and
        no setting, so the choice has to be here or it does not exist.

        Three states rather than a switch, because "follow the system" is a
        real answer and a two-position switch cannot express it.
        """
        box = row(0)
        box.add_css_class("linked")
        box.set_valign(Gtk.Align.CENTER)
        box.set_margin_end(14)
        first = None
        for scheme, icon, tip in (
            (Adw.ColorScheme.DEFAULT, "display-brightness-symbolic", "Match the system"),
            (Adw.ColorScheme.FORCE_LIGHT, "weather-clear-symbolic", "Light"),
            (Adw.ColorScheme.FORCE_DARK, "weather-clear-night-symbolic", "Dark"),
            # A fourth, because on an OLED panel the difference between a dark
            # ground and an unlit one is not a matter of taste. Only offered
            # here rather than as an accessibility choice: it is about the
            # screen rather than about the person.
            (Adw.ColorScheme.FORCE_DARK, "night-light-symbolic", "Black"),
        ):
            button = Gtk.ToggleButton()
            button.set_child(Gtk.Image.new_from_icon_name(icon))
            button.set_tooltip_text(tip)
            button.add_css_class("flat")
            button.add_css_class("aurade-scheme-button")
            button.get_accessible_role()
            button.update_property([Gtk.AccessibleProperty.LABEL], [tip])
            if first is None:
                first = button
                button.set_active(True)
            else:
                button.set_group(first)
            button.connect("toggled", self._on_scheme_button, scheme)
            box.append(button)
        return box

    def _on_scheme_button(self, button: Gtk.ToggleButton, scheme) -> None:
        if not button.get_active():
            return
        # The fourth button is the dark scheme with the ground off, so it asks
        # for the same colour scheme and a different sheet underneath it.
        self.oled = button.get_tooltip_text() == "Black"
        Adw.StyleManager.get_default().set_color_scheme(scheme)

    def fade_in(self) -> None:
        """The window arriving, rather than appearing.

        An installer that snaps into existence on a machine that has just
        booted from a stick reads as something that failed and restarted. Four
        hundred milliseconds of opacity is the whole effect: no logo screen, no
        progress bar for work that is not happening, nothing that delays the
        first question. It is skipped entirely when motion is off, which is
        also when it would cost the most.
        """
        frame = self.widgets.get("frame")
        if frame is None or not self.animate:
            return
        target = Adw.PropertyAnimationTarget.new(frame, "opacity")
        animation = Adw.TimedAnimation.new(frame, 0.0, 1.0, 420, target)
        animation.set_easing(Adw.Easing.EASE_OUT_CUBIC)
        # Held on the window: an animation that goes out of scope stops.
        self._fade = animation
        animation.play()

    def play_settle(self) -> None:
        """The done screen arriving, rather than having been there all along.

        The page draws, a beat passes, and the tick fades up. Then nothing
        moves again, which is the whole difference between a moment and an
        animation. Half a second, once per install.

        Deliberately not confetti. Somebody who has just watched ten minutes
        of an operating system being written to their disk does not want to be
        congratulated at, and a machine that throws a party for itself is
        pleased with itself rather than with you. What the moment is for is
        marking that the waiting is over, and a beat of stillness followed by
        one thing appearing does that.

        Opacity only. Anything that changes a size relayouts a page whose
        contents are vertically centred, so every other line on the screen
        would shuffle to make room for the tick arriving. On the machines that
        get the software renderer it would shuffle slowly.
        """
        icon = self.widgets.get(f"{F.DONE}.icon")
        if icon is None or self._settled or not self.animate:
            return
        self._settled = True
        icon.set_opacity(0.0)

        def start() -> bool:
            target = Adw.PropertyAnimationTarget.new(icon, "opacity")
            animation = Adw.TimedAnimation.new(icon, 0.0, 1.0, SETTLE_MS, target)
            animation.set_easing(Adw.Easing.EASE_OUT_CUBIC)
            # Held on the window: an animation that goes out of scope stops,
            # and this one would go out of scope at the end of this function.
            self._settle = animation
            animation.play()
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(SETTLE_DELAY_MS, start)

    def play_swoop(self) -> None:
        """Draw the mark over the page, once, and then get out of the way."""
        swoop = self.widgets.get("swoop")
        if swoop is None or self._swooped or not self.animate:
            return
        self._swooped = True

        def frame(value: float) -> None:
            swoop.phase = value
            swoop.queue_draw()
            if value >= 1.0:
                swoop.set_visible(False)

        swoop.phase = 0.0
        swoop.set_visible(True)
        target = Adw.CallbackAnimationTarget.new(frame)
        animation = Adw.TimedAnimation.new(swoop, 0.0, 1.0, 900, target)
        # Linear here on purpose: the easing is inside the drawing, where the
        # sweep and the ring need different curves from each other.
        animation.set_easing(Adw.Easing.LINEAR)
        self._swoop_animation = animation
        animation.play()

    def skip_swoop(self) -> None:
        """Anything the user does outranks the animation."""
        animation = getattr(self, "_swoop_animation", None)
        if animation is not None:
            animation.skip()
        swoop = self.widgets.get("swoop")
        if swoop is not None:
            swoop.set_visible(False)

    def start_aurora(self) -> None:
        if self._aurora_source or not self.animate:
            return
        self._aurora_source = GLib.timeout_add(AURORA_INTERVAL_MS, self._tick)

    def _tick(self) -> bool:
        """One clock for everything that drifts.

        The aurora and the ribbon's highlight both move slowly and forever, and
        giving each its own timer would mean two wakeups a frame on a machine
        that is busy installing an operating system.
        """
        self.widgets["aurora"].advance()
        ribbon = self.widgets.get("progress.bar")
        if ribbon is not None and ribbon.get_mapped():
            ribbon.phase += PROGRESS_SHEEN_PER_SECOND * AURORA_INTERVAL_MS / 1000
            ribbon.queue_draw()
        return GLib.SOURCE_CONTINUE

    def stop_aurora(self) -> None:
        if self._aurora_source:
            GLib.source_remove(self._aurora_source)
            self._aurora_source = 0

    # -- pages -------------------------------------------------------------

    def _build_pages(self) -> None:
        self.manifest = self.model.manifest()
        self.stack.add_named(self._build_welcome(), F.WELCOME)
        for page in F.PAGES:
            self.stack.add_named(self._build_page(page), f"page:{page.name}")
        self.stack.add_named(self._build_review(), F.REVIEW)
        self.stack.add_named(self._build_gate(), F.GATE)
        self.stack.add_named(self._build_progress(), F.PROGRESS)
        self.stack.add_named(self._build_outcome(
            F.DONE, F.DONE_TITLE, F.DONE_BODY, "object-select-symbolic"), F.DONE)
        self.stack.add_named(self._build_failure(), F.FAILURE)
        self.stack.add_named(self._build_outcome(
            F.STOPPED, F.STOPPED_TITLE, F.STOPPED_BODY,
            "process-stop-symbolic"), F.STOPPED)
        self.stack.add_named(self._build_outcome(
            F.CANCELLED, F.CANCELLED_TITLE, F.CANCELLED_BODY,
            "process-stop-symbolic"), F.CANCELLED)
        self.stack.add_named(self._build_outcome(
            F.PLANNED, F.PLANNED_TITLE, F.PLANNED_BODY,
            "document-properties-symbolic"), F.PLANNED)

    def _build_welcome(self) -> Gtk.Widget:
        box = column(0)
        box.set_valign(Gtk.Align.CENTER)
        box.set_vexpand(True)
        mark = Mark(128)
        mark.set_halign(Gtk.Align.CENTER)
        mark.set_margin_bottom(26)
        box.append(mark)
        title = label(F.WELCOME_TITLE, "m3-display-small", center=True)
        title.set_margin_bottom(12)
        box.append(title)
        body = label(F.WELCOME_BODY, "m3-body-large", center=True)
        body.set_margin_bottom(22)
        box.append(body)
        assurance = row(8)
        assurance.set_halign(Gtk.Align.CENTER)
        assurance.append(Gtk.Image.new_from_icon_name("channel-secure-symbolic"))
        assurance.append(label(F.WELCOME_ASSURANCE, "m3-label-large", wrap=False))
        assurance.add_css_class("aurade-stage-done")
        box.append(assurance)
        reader = self._build_bible_button()
        if reader is not None:
            box.append(reader)
        return page_shell(box)

    def _build_bible_button(self) -> Gtk.Widget | None:
        """The Bible, offered once, quietly, and only if it is on the image.

        A flat button under the assurance line, in the small label size, which
        is the same weight as the photograph credit in the other corner. Not a
        card, not an icon tile, and nothing above it explaining what it is for:
        somebody who wants it will find it, and somebody who does not should
        be able to walk past without the installer having made a point of
        itself. An installer with opinions about your evening is worse than an
        installer with none.

        Absent entirely when no Bible is staged, rather than present and
        apologetic. A button that opens an empty window is a bug wearing a
        feature's clothes.
        """
        if not bible.available():
            return None
        button = Gtk.Button(label=F.BIBLE_BUTTON)
        button.add_css_class("flat")
        button.add_css_class("m3-label-small")
        button.add_css_class("dim-label")
        button.set_halign(Gtk.Align.CENTER)
        button.set_margin_top(30)
        button.connect("clicked", lambda _b: self._open_bible())
        A.described(button, F.BIBLE_BUTTON, F.BIBLE_EDITION)
        self.widgets["bible.button"] = button
        return button

    def _bible_markup(self, lines: list[str]) -> str:
        """One chapter as Pango markup.

        Escaped first and marked up second, in that order and never the other
        way round, because a verse carrying an ampersand would otherwise take
        the whole label down to a markup parse error and show nothing at all.

        The asterisks are the converter's, and they are the King James
        italics: the words the translators supplied rather than found. The
        verse number goes dim rather than bold. Bold numbers turn a page of
        prose into a numbered list, which is not how the book reads.
        """
        out = []
        for line in lines:
            if not line:
                out.append("")
                continue
            text = GLib.markup_escape_text(line)
            text = re.sub(r"\*([^*]+)\*", r"<i>\1</i>", text)
            number = re.match(r"^(\d+) ", text)
            if number:
                text = (f'<span alpha="55%">{number.group(1)}</span> '
                        f"{text[number.end():]}")
            out.append(text)
        return "\n".join(out)

    def _open_bible(self) -> None:
        """The reader. Two pickers and a page.

        Book and chapter as dropdowns rather than a sidebar, because eighty
        books and a hundred and fifty Psalms do not fit in a list beside the
        text on the screens this installer supports, and because a dropdown is
        reachable with Tab and Enter alone, which a two pane navigation is not
        without arrow keys nobody was told about.
        """
        books = bible.books()
        if not books:
            return

        page = label("", "m3-body-large")
        page.set_selectable(True)
        page.set_use_markup(True)
        page.set_max_width_chars(72)
        page.set_margin_top(20)
        page.set_margin_bottom(28)
        page.set_margin_start(24)
        page.set_margin_end(24)

        heading = label("", "m3-title-medium")
        heading.set_margin_start(24)
        heading.set_margin_top(18)

        chapter_list = Gtk.StringList()
        chapters = Gtk.DropDown(model=chapter_list)
        book_list = Gtk.StringList()
        for book in books:
            book_list.append(book["short"])
        picker = Gtk.DropDown(model=book_list)
        picker.set_enable_search(True)
        # Searching a dropdown needs to know what to search. Without an
        # expression the eighty entries are a list you can only scroll.
        picker.set_expression(Gtk.PropertyExpression.new(
            Gtk.StringObject, None, "string"))

        def show(*_args) -> None:
            index = picker.get_selected()
            if index >= len(books):
                return
            book = books[index]
            wanted = chapters.get_selected()
            count = len(bible.chapters(book["code"]))
            if chapter_list.get_n_items() != count:
                chapter_list.splice(0, chapter_list.get_n_items(),
                                    [str(n) for n in range(1, count + 1)])
                wanted = 0
            if wanted >= count:
                wanted = 0
            chapters.set_selected(wanted)
            heading.set_label(book["name"])
            page.set_label(self._bible_markup(
                bible.chapter(book["code"], wanted + 1)))
            # Back to the top. A reader who was at verse forty of one chapter
            # and turns the page should be at the start of the next one, not
            # forty verses into it.
            adjustment = scroller.get_vadjustment()
            if adjustment is not None:
                adjustment.set_value(0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_overlay_scrolling(False)
        scroller.set_vexpand(True)
        body = column(0)
        body.append(heading)
        body.append(page)
        scroller.set_child(body)

        picker.connect("notify::selected", show)
        chapters.connect("notify::selected", show)
        A.described(picker, F.BIBLE_BOOK, F.BIBLE_TITLE)
        A.described(chapters, F.BIBLE_CHAPTER, F.BIBLE_TITLE)

        header = Adw.HeaderBar()
        header.pack_start(picker)
        header.pack_start(chapters)
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(scroller)

        dialog = Adw.Dialog()
        dialog.set_title(F.BIBLE_TITLE)
        dialog.set_content_width(720)
        dialog.set_content_height(620)
        dialog.set_child(toolbar)
        self.widgets["bible.dialog"] = dialog
        self.widgets["bible.picker"] = picker
        self.widgets["bible.chapters"] = chapters
        self.widgets["bible.page"] = page
        self.widgets["bible.heading"] = heading
        show()
        dialog.present(self)

    def _build_page(self, page: F.Page) -> Gtk.Widget:
        box = column(20)
        box.append(label(page.title, "m3-headline-small"))
        if page.subtitle:
            # An empty label still takes its line, and a page that has nothing
            # more to say should not leave a gap where the sentence would be.
            box.append(label(page.subtitle, "m3-body-medium", css="dim-label"))
        if page.name == "readiness":
            self._build_readiness(box)
        elif page.name == "network":
            self._build_network(box)
        elif page.name == "disk":
            box.append(self._build_disk_list())
            box.append(self._build_storage_options(page))
        else:
            for question in page.questions:
                spec = self.manifest["questions"].get(question)
                if spec is None:
                    continue
                group = Adw.PreferencesGroup(description=spec["help"])
                for widget in self._build_question_rows(question, spec):
                    group.add(widget)
                self.widgets[f"group.{question}"] = group
                box.append(group)
            if page.name == "language":
                box.append(self._build_keymap_test())
        return page_shell(box, F.PAGE_WIDTHS.get(page.name, PROSE_WIDTH))

    def _build_storage_options(self, page: F.Page) -> Gtk.Widget:
        """Layout, filesystem and swap, folded away until asked for.

        These are on the disk page and not on the advanced page at the end
        because every one of them is a statement about the disk that is
        selected directly above them. They are folded because the defaults are
        the shape this product is designed around, and an installer that opens
        with six storage decisions reads as an installer that needs six
        storage decisions.
        """
        group = Adw.PreferencesGroup()
        expander = Adw.ExpanderRow(title=F.STORAGE_TITLE,
                                   subtitle=F.STORAGE_SUBTITLE)
        expander.add_prefix(icon_tile("drive-harddisk-symbolic"))
        for question in page.questions:
            spec = self.manifest["questions"].get(question)
            if spec is None or spec["type"] == "disk":
                continue
            expander.add_row(self._build_enum_row(question, spec))
            self.widgets[f"group.{question}"] = group

        # The consequence line, last, inside the same disclosure. It is a row
        # rather than a loose label so it sits in the list box with everything
        # it is talking about.
        warning = Adw.ActionRow()
        warning.set_subtitle_lines(0)
        warning.add_prefix(Gtk.Image.new_from_icon_name("emblem-important-symbolic"))
        warning.set_visible(False)
        self.widgets["storage.warning"] = warning
        expander.add_row(warning)
        group.add(expander)
        expander.connect(
            "notify::expanded",
            lambda item, _p: reveal(item) if item.get_expanded() else None)
        self.widgets["storage.expander"] = expander
        return group

    def _refresh_storage(self) -> None:
        """Say what the current storage answers cost, while they can be changed.

        The rollback entry is the thing people lose without noticing: it is
        absent rather than broken, so nothing complains, and the first time it
        matters is the first time they need it.
        """
        chosen = {}
        for question in ("filesystem", "layout", "swap"):
            widget = self.widgets.get(f"q.{question}")
            values = self.enum_values.get(question, [])
            if widget is None or not values:
                continue
            index = widget.get_selected()
            if 0 <= index < len(values):
                chosen[question] = values[index]

        notes = []
        if chosen.get("filesystem", "btrfs") != "btrfs":
            named = locales.describe_storage("filesystem",
                                             chosen["filesystem"])[0]
            notes.append(f"{named} has no snapshot to roll back to, so this "
                         "install will have no rollback entry in the boot "
                         "menu.")
        if chosen.get("layout") == "alongside":
            notes.append("Installing alongside only uses free space that is "
                         "already there. Nothing on this disk is moved, "
                         "resized or erased.")
        widget = self.widgets.get("storage.warning")
        if widget is None:
            return
        widget.set_title("Worth knowing" if notes else "")
        widget.set_subtitle(" ".join(notes))
        widget.set_visible(bool(notes))
        expander = self.widgets.get("storage.expander")
        # A consequence folded out of sight is a consequence nobody read.
        if notes and expander is not None and not expander.get_expanded():
            expander.set_expanded(True)

    # -- readiness ---------------------------------------------------------
    #
    # The first page after the welcome screen. It used to print the renderer
    # decision, a DRM node path and a paragraph about whether 3D acceleration
    # could be proven, which is an answer to a question nobody standing in
    # front of a new computer is asking.
    #
    # What they are asking is whether this will work. So the page answers that
    # in one line, lists the five things that decide it, and puts the driver
    # strings behind a disclosure for the person who wants them. Two of the
    # five - the firmware mode and Secure Boot - are answered before the disk
    # is chosen. Secure Boot is a supported signed-chain path in setup mode;
    # when no key is available it remains a warning, because the user can
    # finish the install and handle firmware before the first boot.

    #: What each check is about, so a page of five findings reads as five
    #: subjects rather than five identical ticks. Every name here is in the
    #: icon set the image installs, which `gui_icon_test.py` is what proves:
    #: a name the theme does not carry draws nothing at all, silently, and
    #: this page shipped that way once already.
    READINESS_ICONS = {
        "firmware": "application-x-firmware-symbolic",
        "secure_boot": "channel-secure-symbolic",
        "memory": "media-flash-symbolic",
        "disk": "drive-harddisk-symbolic",
        "graphics": "video-display-symbolic",
        "power": "battery-good-symbolic",
    }

    #: Two checks have a subject with two faces. Showing the open padlock when
    #: Secure Boot is on says more than any wording can, and a battery drawn
    #: nearly empty is read before the sentence beside it is.
    READINESS_ICONS_BAD = {
        "secure_boot": "channel-insecure-symbolic",
        "power": "battery-caution-symbolic",
    }

    READINESS_GLYPHS = {
        "ok": "object-select-symbolic",
        "warn": "dialog-warning-symbolic",
        "blocked": "dialog-error-symbolic",
    }

    #: Verdict to check-state, for the badge at the top.
    VERDICT_GLYPHS = {"ok": "ok", "attention": "warn", "blocked": "blocked"}

    def _build_readiness(self, box: Gtk.Box) -> None:
        verdict = row(20)
        verdict.add_css_class("aurade-verdict")
        verdict.add_css_class("aurade-transition")
        # The glyph sits in a tonal disc rather than floating beside the text.
        # It is the first thing on the first page after the welcome screen, and
        # a bare 38-pixel icon on a coloured field reads as a decoration; a
        # badge reads as a verdict.
        badge = Gtk.Box()
        badge.add_css_class("aurade-verdict-badge")
        badge.set_valign(Gtk.Align.CENTER)
        glyph = Gtk.Image.new_from_icon_name("object-select-symbolic")
        glyph.set_pixel_size(30)
        badge.append(glyph)
        self.widgets["ready.glyph"] = glyph
        verdict.append(badge)
        text = column(3)
        text.set_hexpand(True)
        text.set_valign(Gtk.Align.CENTER)
        headline = label("", "m3-headline-small")
        self.widgets["ready.headline"] = headline
        text.append(headline)
        body = label("", "m3-body-medium")
        self.widgets["ready.body"] = body
        text.append(body)
        verdict.append(text)
        self.widgets["ready.verdict"] = verdict
        box.append(verdict)

        # Only what needs an answer.
        #
        # This page listed all five checks, every time, each with its finding
        # and a tick. Five green rows is a page reporting its own work: there
        # is nothing on it to read and nothing on it to do, and the sentences
        # that fill it are all justifications, which is most of why this
        # installer read like a status report. So a check that passes says
        # nothing here. It is in the details, where anyone who wants it can
        # find it, and the page above stays one sentence long.
        #
        # A check that does not pass gets the page to itself.
        group = Adw.PreferencesGroup()
        self.widgets["ready.checks"] = group
        self.readiness_rows = []
        box.append(group)

        group = Adw.PreferencesGroup()
        details = Adw.ExpanderRow(title=F.READINESS_DETAILS)
        details.add_prefix(icon_tile("document-properties-symbolic"))
        self.widgets["ready.detail.group"] = details
        self.detail_rows = []
        detail_row = Adw.ActionRow()
        detail_row.set_subtitle_lines(0)
        detail_row.add_css_class("aurade-mono")
        self.widgets["ready.details"] = detail_row
        details.add_row(detail_row)
        details.connect(
            "notify::expanded",
            lambda item, _p: reveal(item) if item.get_expanded() else None)
        group.add(details)
        box.append(group)

    def _check_row(self, check: dict) -> Adw.ActionRow:
        state = check.get("state", "ok")
        check_id = check.get("id", "")
        item = Adw.ActionRow(title=check.get("title", ""))
        item.set_subtitle_lines(0)
        item.set_title_lines(0)
        item.add_css_class("aurade-transition")

        subject = self.READINESS_ICONS.get(check_id, "dialog-information-symbolic")
        if state != "ok":
            subject = self.READINESS_ICONS_BAD.get(check_id, subject)
        item.add_prefix(icon_tile(subject, state))

        # The finding, and what to do about it when there is something to do.
        # Two sentences on one line reads as one thought; the action belongs
        # under the finding it answers.
        finding = check.get("finding", "")
        action = check.get("action") or ""
        item.set_subtitle(f"{finding}\n{action}" if action else finding)

        mark = Gtk.Image.new_from_icon_name(
            self.READINESS_GLYPHS.get(state, "object-select-symbolic"))
        mark.add_css_class(f"aurade-glyph-{state}")
        mark.set_valign(Gtk.Align.CENTER)
        item.add_suffix(mark)

        # A finding is not a control. Rows in a list box take focus by default,
        # which puts five unactionable stops between the page and the button
        # that leaves it.
        item.set_activatable(False)
        item.set_focusable(False)
        return item

    def _refresh_readiness(self) -> None:
        self.probe = self.model.probe()
        try:
            report = self.model.call("readiness")
        except BridgeError:
            report = {}
        verdict = report.get("verdict", "")
        checks = report.get("checks", [])

        headline, body = F.READINESS_VERDICTS.get(
            verdict, ("This computer could not be checked", F.READINESS_UNKNOWN))
        self.widgets["ready.headline"].set_label(headline)
        self.widgets["ready.body"].set_label(body)
        holder = self.widgets["ready.verdict"]
        for name in ("ok", "attention", "blocked"):
            holder.remove_css_class(f"aurade-verdict-{name}")
        holder.add_css_class(f"aurade-verdict-{verdict or 'attention'}")
        self.widgets["ready.glyph"].set_from_icon_name(self.READINESS_GLYPHS.get(
            self.VERDICT_GLYPHS.get(verdict, "warn"), "dialog-warning-symbolic"))

        group = self.widgets["ready.checks"]
        for existing in self.readiness_rows:
            group.remove(existing)
        self.readiness_rows = []
        details = self.widgets["ready.detail.group"]
        for existing in self.detail_rows:
            details.remove(existing)
        self.detail_rows = []
        for check in checks:
            item = self._check_row(check)
            if check.get("state", "ok") == "ok":
                # AdwExpanderRow takes rows, not children: `add` is the
                # AdwPreferencesGroup call and does not exist here.
                details.add_row(item)
                self.detail_rows.append(item)
            else:
                group.add(item)
                self.readiness_rows.append(item)

        # The raw strings go under the findings they belong to, not above
        # them. Rows are appended in the order they are added, and the mono
        # block was built first because it is part of the page rather than
        # part of a check.
        raw = self.widgets["ready.details"]
        details.remove(raw)
        details.add_row(raw)

        detail_lines = [
            f"{check.get('title', '')}: {check.get('detail')}"
            for check in checks if check.get("detail")
        ]
        detail_lines.append(f"Installer: {self.probe.get('renderer', 'unknown')}"
                            f" ({self.probe.get('reason', '')})")
        if self.probe.get("advice"):
            detail_lines.append(self.probe["advice"])
        self.widgets["ready.details"].set_subtitle("\n".join(detail_lines))

        # A blocked verdict is the one case where the page cannot be walked
        # past. The engine would refuse later anyway; refusing here saves the
        # user answering nine questions first.
        self.forward_blocked = verdict == "blocked"
        self.banner.set_revealed(False)

    # -- network -----------------------------------------------------------

    def _build_network(self, box: Gtk.Box) -> None:
        status = Adw.PreferencesGroup()
        item = Adw.ActionRow(title="Checking the connection")
        item.set_subtitle("")
        item.set_subtitle_lines(0)
        item.add_prefix(Gtk.Image.new_from_icon_name(
            "network-wireless-acquiring-symbolic"))
        self.widgets["net.status"] = item
        status.add(item)
        box.append(pane(status, "aurade-pane-flat"))

        header = row(8)
        header.append(label("Wi-Fi networks", "m3-title-medium", wrap=False))
        gap = Gtk.Box()
        gap.set_hexpand(True)
        header.append(gap)
        spinner = Gtk.Spinner()
        spinner.set_valign(Gtk.Align.CENTER)
        self.widgets["wifi.spinner"] = spinner
        header.append(spinner)
        rescan = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        rescan.add_css_class("flat")
        rescan.set_tooltip_text("Scan again")
        rescan.connect("clicked", lambda *_: self.scan_wifi())
        self.widgets["wifi.rescan"] = rescan
        header.append(rescan)
        box.append(header)

        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        listbox.add_css_class("boxed-list")
        listbox.connect("row-activated", self._on_wifi_row)
        self.widgets["wifi.list"] = listbox
        box.append(listbox)

        empty = label("", "m3-body-medium", css="dim-label")
        empty.set_visible(False)
        self.widgets["wifi.empty"] = empty
        box.append(empty)

        # The password field appears under the chosen network rather than in a
        # dialog, so the name of the network being joined stays on screen
        # while the password is typed.
        prompt = Adw.PreferencesGroup()
        prompt.set_visible(False)
        entry = Adw.PasswordEntryRow(title="Wi-Fi password")
        entry.connect("entry-activated", lambda *_: self.join_wifi())
        join = Gtk.Button(label="Join")
        join.add_css_class("suggested-action")
        join.add_css_class("pill")
        join.set_valign(Gtk.Align.CENTER)
        join.connect("clicked", lambda *_: self.join_wifi())
        entry.add_suffix(join)
        prompt.add(entry)
        self.widgets["wifi.prompt"] = prompt
        self.widgets["wifi.password"] = entry
        box.append(prompt)

        box.append(label(
            "Everything is downloaded and checked before any disk is touched, "
            "so a connection that fails here costs you nothing.",
            "m3-body-small", css="dim-label"))

    def _refresh_network(self) -> None:
        status = self.model.call("net-status")
        item = self.widgets["net.status"]
        if not status.get("available"):
            item.set_title("Wi-Fi cannot be set up here")
            item.set_subtitle(status.get("reason", ""))
            self.widgets["wifi.list"].set_visible(False)
            self.widgets["wifi.empty"].set_label(
                "This image has no way to set up Wi-Fi. Connect a cable to "
                "get online.")
            self.widgets["wifi.empty"].set_visible(True)
            return
        if status.get("wired"):
            item.set_title("Connected by cable")
            item.set_subtitle("A wired connection is up. Wi-Fi is optional.")
        elif status.get("ssid"):
            item.set_title(f"Connected to {status['ssid']}")
            item.set_subtitle("")
        elif status.get("radio") == "disabled":
            item.set_title("Wi-Fi is turned off")
            item.set_subtitle("Turn Wi-Fi on to see what is nearby.")
        else:
            item.set_title("Not connected")
            item.set_subtitle("Choose a network below.")
        self.scan_wifi()

    def scan_wifi(self) -> None:
        self.widgets["wifi.spinner"].start()
        self.widgets["wifi.rescan"].set_sensitive(False)
        # A scan blocks for a second or two. Yielding to the main loop first
        # means the spinner is on screen while it happens rather than
        # appearing and vanishing after the fact.
        GLib.idle_add(self._do_scan)

    def _do_scan(self) -> bool:
        try:
            result = self.model.call("wifi-scan")
        except BridgeError as exc:
            self._fatal(str(exc))
            return GLib.SOURCE_REMOVE
        self.widgets["wifi.spinner"].stop()
        self.widgets["wifi.rescan"].set_sensitive(True)
        listbox = self.widgets["wifi.list"]
        while (existing := listbox.get_first_child()) is not None:
            listbox.remove(existing)
        empty = self.widgets["wifi.empty"]
        if not result.get("ok"):
            empty.set_label(result.get("error", "Wi-Fi is not available here."))
            empty.set_visible(True)
            listbox.set_visible(False)
            return GLib.SOURCE_REMOVE
        networks = result.get("networks", [])
        listbox.set_visible(bool(networks))
        if not networks:
            empty.set_label("Nothing in range. Move closer to the router, or "
                            "use a cable.")
            empty.set_visible(True)
            return GLib.SOURCE_REMOVE
        empty.set_visible(False)
        for network in sorted(networks, key=lambda n: -n.get("signal", 0)):
            listbox.append(self._wifi_row(network))
        return GLib.SOURCE_REMOVE

    def _wifi_row(self, network: dict):
        item = Adw.ActionRow(title=network["ssid"])
        item.set_activatable(True)
        strength = int(network.get("signal", 0))
        arcs = SignalArcs(self, strength)
        arcs.set_valign(Gtk.Align.CENTER)
        arcs.set_tooltip_text(f"{brand.signal_words(strength)} signal")
        item.add_prefix(arcs)
        notes = []
        if network.get("active"):
            notes.append("Connected")
        elif network.get("saved"):
            notes.append("Saved")
        notes.append("Open network" if network.get("open")
                     else network.get("security", ""))
        item.set_subtitle("   ".join(n for n in notes if n))
        if not network.get("open"):
            lock = Gtk.Image.new_from_icon_name("channel-secure-symbolic")
            lock.set_tooltip_text("Password required")
            item.add_suffix(lock)
        if network.get("active"):
            item.add_css_class("aurade-stage-done")
        item.wifi = network
        return item

    def _on_wifi_row(self, _listbox, item) -> None:
        network = getattr(item, "wifi", None)
        if network is None:
            return
        if network.get("active"):
            self._toast(f"Already connected to {network['ssid']}.")
            return
        self._wifi_target = network["ssid"]
        prompt = self.widgets["wifi.prompt"]
        entry = self.widgets["wifi.password"]
        if network.get("open") or network.get("saved"):
            prompt.set_visible(False)
            self.join_wifi()
            return
        entry.set_title(f"Password for {network['ssid']}")
        entry.set_text("")
        prompt.set_visible(True)
        entry.grab_focus()

    def join_wifi(self) -> None:
        if not self._wifi_target:
            return
        entry = self.widgets["wifi.password"]
        password = entry.get_text()
        self.widgets["wifi.spinner"].start()
        try:
            result = self.model.call("wifi-connect", self._wifi_target, password)
        except BridgeError as exc:
            self._fatal(str(exc))
            return
        finally:
            # The renderer's copy of the passphrase goes now. The model wrote
            # it into a mode-0600 profile and there is no command that reads
            # one back.
            entry.set_text("")
            self.widgets["wifi.spinner"].stop()
        if not result.get("ok"):
            self._toast(result.get("error", "Could not join that network."))
            entry.grab_focus()
            return
        self.widgets["wifi.prompt"].set_visible(False)
        joined = self._wifi_target
        self._wifi_target = ""
        self._toast(f"Connected to {joined}.")
        self._refresh_network()

    # -- questions ---------------------------------------------------------

    def _build_question_rows(self, question: str, spec: dict) -> list:
        kind = spec["type"]
        if kind == "secret":
            entry = Adw.PasswordEntryRow(title=spec["label"])
            repeat = Adw.PasswordEntryRow(title="Type it again")
            self.widgets[f"q.{question}"] = entry
            self.widgets[f"q.{question}.repeat"] = repeat
            # Checked on leaving the second field rather than on pressing
            # Continue. Finding out at the end of a page that two boxes near
            # the top disagree means going back up and doing both again, and
            # for a disk passphrase it means doing it again with no idea which
            # of the two was the one you meant.
            focus = Gtk.EventControllerFocus()
            focus.connect("leave", self._on_secret_blur, question)
            repeat.add_controller(focus)
            return [entry, repeat]
        if kind == "bool":
            item = Adw.SwitchRow(title=spec["label"])
            item.set_active(spec["default"] == "yes")
            item.connect("notify::active", self._on_bool_changed, question)
            self.widgets[f"q.{question}"] = item
            return [item]
        if kind == "enum":
            return [self._build_enum_row(question, spec)]
        if kind == "disk":
            # The disk list is the control for this question. A row here would
            # be a second, empty one sitting above it.
            return []
        item = Adw.EntryRow(title=spec["label"])
        item.set_text(spec["default"])
        item.set_show_apply_button(False)
        self.widgets[f"q.{question}"] = item
        return [item]

    def _build_enum_row(self, question: str, spec: dict):
        """A picker whose rows say what the value means.

        The model supplies the candidates and validates the answer. What it
        does not do, and should not, is decide that `en_US.UTF-8` is a
        reasonable thing to show someone who is choosing a language.

        The row is returned bare, and that is load-bearing rather than tidy.
        ``AdwPreferencesGroup.add`` puts an ``AdwPreferencesRow`` into its
        internal ``GtkListBox`` and puts anything else into a plain box beside
        it. An ``AdwComboRow`` is a ``GtkListBoxRow``, and a ``GtkListBoxRow``
        with no ``GtkListBox`` above it never receives activation - so wrapping
        this row in a box to carry a caption under it produced a picker that
        drew correctly, took focus badly, and did not open when clicked. The
        caption is the row's own subtitle instead.
        """
        values = self.model.enum(question)
        self.enum_values[question] = values
        titles, details = [], []
        for value in values:
            if question == "locale":
                title, detail = self.names.describe_locale(value)
            elif question == "keymap":
                title, detail = locales.describe_keymap(value)
            elif question == "timezone":
                title, detail = locales.describe_timezone(value)
            else:
                title, detail = locales.describe_storage(question, value)
            titles.append(title)
            details.append(detail)
        self.widgets[f"q.{question}.details"] = details

        item = Adw.ComboRow(title=spec["label"],
                            model=Gtk.StringList.new(titles or [spec["default"]]))
        # Search needs an expression to search *on*; without one libadwaita has
        # nothing to compare a query against. Only offered where the list is
        # long enough to be worth searching - a search field over three
        # filesystems is a search field in the way.
        if len(values) > 12:
            item.set_expression(Gtk.PropertyExpression.new(
                Gtk.StringObject, None, "string"))
            item.set_enable_search(True)
        if spec["default"] in values:
            item.set_selected(values.index(spec["default"]))
        item.connect("notify::selected", self._on_enum_changed, question)
        self.widgets[f"q.{question}"] = item
        self._sync_enum_caption(question)
        return item

    def _sync_enum_caption(self, question: str) -> None:
        item = self.widgets.get(f"q.{question}")
        details = self.widgets.get(f"q.{question}.details") or []
        if item is None:
            return
        index = item.get_selected()
        text = details[index] if 0 <= index < len(details) else ""
        item.set_subtitle(text)

    def _on_enum_changed(self, _row, _param, question: str) -> None:
        self._sync_enum_caption(question)
        if question in ("filesystem", "layout", "swap", "swap_size"):
            self._refresh_storage()
            return
        if question != "keymap":
            return
        # Applying the layout as it is chosen is the whole point of the test
        # field below: what gets typed there has to be what the chosen layout
        # produces, not what the previous one did.
        values = self.enum_values.get("keymap", [])
        index = self.widgets["q.keymap"].get_selected()
        if 0 <= index < len(values):
            ok, error = self.model.set("keymap", values[index])
            if not ok:
                self._toast(error)

    def _build_keymap_test(self):
        """Somewhere to try the layout before it is used for a password.

        The manifest's own help for this question tells the user to test the
        layout in the field below. The text installer has that field. This is
        that field, and without it the instruction was a lie.
        """
        group = Adw.PreferencesGroup(
            title="Try your keyboard",
            description=("Try the layout here before you set a password. "
                         "Nothing typed in this box is saved."))
        entry = Adw.EntryRow(title="Test the keys")
        entry.set_show_apply_button(False)
        self.widgets["keymap.test"] = entry
        group.add(entry)
        return group

    # -- disks -------------------------------------------------------------

    def _build_disk_list(self):
        box = column(12)
        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        listbox.add_css_class("boxed-list")
        listbox.connect("row-selected", self._on_disk_selected)
        self.widgets["disk.list"] = listbox
        box.append(listbox)
        warning = label("", "m3-body-small")
        warning.add_css_class("warning")
        warning.set_visible(False)
        self.widgets["disk.warning"] = warning
        box.append(warning)
        return box

    def _refresh_disks(self) -> None:
        listbox = self.widgets["disk.list"]
        while (existing := listbox.get_first_child()) is not None:
            listbox.remove(existing)
        removable = False
        disks = list(self.model.disks())
        # Against the biggest one on offer, so the bars answer "which of these
        # is the big one" rather than "how does this compare to a disk that is
        # not in the list".
        largest = max((brand.parse_size(item.get("size") or "")
                       for item in disks), default=0.0)
        for disk in disks:
            item = Adw.ActionRow(title=disk["path"])
            item.add_css_class("aurade-mono")
            transport = (disk.get("transport") or "").upper()
            # Never "unknown". A drive that does not report its model has not
            # been misread by the installer, and the other wording says which
            # of the two actually happened.
            facts = [disk.get("model") or "not reported by this drive",
                     disk.get("size") or ""]
            if transport:
                facts.append(transport)
            subtitle = "   ".join(f for f in facts if f)
            # What is already on it, which is the line that stops somebody
            # picking the wrong one of two identical looking drives. The erase
            # gate is the last line of defence against that, not the first.
            holds = disk.get("holds") or ""
            if disk.get("booted"):
                holds = ("You started this installer from this one"
                         + (f", {holds}" if holds else ""))
            if holds:
                subtitle += f"\n{holds}"
            serial = disk.get("serial") or ""
            if serial:
                subtitle += f"\nSerial {serial}"
            item.set_subtitle(subtitle)
            item.set_subtitle_lines(0)
            item.disk_path = disk["path"]
            # A removable disk gets the caution tile as well as the sentence
            # under the list, because the one being warned about is one row in
            # a list of otherwise identical-looking disks.
            item.add_prefix(
                icon_tile("media-removable-symbolic", "warn") if transport == "USB"
                else icon_tile("drive-harddisk-symbolic"))
            # No bar at all when the size could not be read, rather than an
            # empty one. A bar of the wrong length is a claim about which disk
            # is bigger, on the page where that matters most.
            fraction = brand.capacity_fraction(disk.get("size") or "", largest)
            if fraction > 0:
                item.add_suffix(CapacityBar(self, fraction))
            if transport == "USB":
                removable = True
            listbox.append(item)
        warning = self.widgets["disk.warning"]
        warning.set_visible(removable)
        if removable:
            warning.set_label("One of these is removable, and it is listed last.")
        chosen = self.model.get("target")
        if chosen:
            for item in self._rows(listbox):
                if getattr(item, "disk_path", None) == chosen:
                    listbox.select_row(item)
                    break

    @staticmethod
    def _rows(listbox):
        item = listbox.get_first_child()
        while item is not None:
            yield item
            item = item.get_next_sibling()

    # -- review ------------------------------------------------------------

    def _build_review(self):
        box = column(20)
        box.append(label(F.REVIEW_TITLE, "m3-headline-small"))
        box.append(label("Pick any line to change it.",
                         "m3-body-medium", css="dim-label"))
        group = Adw.PreferencesGroup()
        self.widgets["review.group"] = group
        box.append(group)
        assurance = row(8)
        assurance.append(Gtk.Image.new_from_icon_name("object-select-symbolic"))
        assurance.append(label(F.REVIEW_ASSURANCE, "m3-label-large", wrap=False))
        assurance.add_css_class("aurade-stage-done")
        box.append(assurance)
        # The way through to the advanced page from here. It is a row rather
        # than a bare button because a line of bold text under a card reads as
        # a heading for something missing, which is what it looked like.
        more = Adw.PreferencesGroup()
        entry = Adw.ActionRow(title="Advanced options")
        entry.set_subtitle("Package snapshot and where updates come from")
        entry.add_prefix(icon_tile("document-properties-symbolic"))
        entry.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        entry.set_activatable(True)
        entry.connect("activated", lambda *_: self._on_review_row(None, "advanced"))
        more.add(entry)
        box.append(more)
        return page_shell(box)

    def _refresh_review(self) -> None:
        group = self.widgets["review.group"]
        self._clear_group("review", group)
        # Secrets arrive as the word `set`. There is no command that returns
        # one, so this screen cannot show a password even by mistake.
        for question, entry in self.model.answers().items():
            item = Adw.ActionRow(title=entry["short"], subtitle=entry["value"])
            item.set_subtitle_lines(0)
            if question in ("target", "snapshot", "repo_url"):
                item.add_css_class("aurade-mono")
            page = F.page_for_question(question)
            if page is not None:
                item.set_activatable(True)
                item.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
                item.connect("activated", self._on_review_row, page.name)
            self._add_row("review", group, item)

    def _on_review_row(self, _row, page_name: str) -> None:
        self.flow.jump_to_page(page_name)
        self.refresh()

    def _clear_group(self, key: str, group) -> None:
        for item in self.group_rows.get(key, []):
            group.remove(item)
        self.group_rows[key] = []

    def _add_row(self, key: str, group, item) -> None:
        group.add(item)
        self.group_rows.setdefault(key, []).append(item)

    # -- the erase gate ----------------------------------------------------

    def _build_gate(self):
        box = column(20)
        headline = label("", "m3-headline-small")
        self.widgets["gate.headline"] = headline
        box.append(headline)

        facts = Adw.PreferencesGroup()
        for key, title in (("model", "Model"), ("serial", "Serial"),
                           ("size", "Size"), ("transport", "Connection")):
            item = Adw.ActionRow(title=title)
            item.set_subtitle("")
            item.add_css_class("aurade-mono")
            self.widgets[f"gate.{key}"] = item
            facts.add(item)
        box.append(pane(facts, "aurade-danger-pane"))
        box.append(label(F.GATE_BODY, "m3-body-medium"))

        # What to type comes before the place to type it, the way the text
        # installer has always had it. Underneath the field, it is the one
        # thing on the page you cannot see while you are using the page.
        hint = label("", "m3-body-medium", css="aurade-mono")
        # Selectable, so the token can be copied and pasted rather than
        # retyped. Typing it exactly is a real motor and cognitive load and it
        # is the one thing here that must not be made easier to get *wrong*;
        # copying it is not easier to get wrong, it is harder.
        hint.set_selectable(True)
        self.widgets["gate.hint"] = hint
        box.append(hint)

        prompt = Adw.PreferencesGroup()
        entry = Adw.EntryRow(title="Confirmation")
        entry.add_css_class("aurade-token-field")
        entry.connect("changed", lambda *_: self.refresh_gate_button())
        self.widgets["gate.entry"] = entry
        prompt.add(entry)
        box.append(prompt)
        return page_shell(box)

    def _refresh_gate(self) -> None:
        info = self.model.target()
        if not info.get("ok"):
            self._toast(info.get("error", "No disk has been chosen."))
            self.flow.back()
            self.refresh()
            return
        self._gate_token = info["token"]
        self.widgets["gate.headline"].set_label(
            f"This erases {info['path']} completely.")
        # Said out loud on arrival, spelled out, because this is the one screen
        # where hearing "dev nvme zero n one" as a run of characters is not
        # good enough. A sighted user proofreads the token against the disk
        # facts beside it; this is the equivalent.
        A.announce(self,
                   f"Erase gate. This erases {self._spell(info['path'])} "
                   f"completely. Type {self._spell(info['token'])} to continue.",
                   urgent=True)
        for key in ("model", "serial", "size", "transport"):
            self.widgets[f"gate.{key}"].set_subtitle(info.get(key) or "unknown")
        self.widgets["gate.hint"].set_label(
            f"Type  {self._gate_token}  to continue")
        self.widgets["gate.entry"].set_text("")

    def refresh_gate_button(self) -> None:
        if self.flow.state != F.GATE:
            return
        typed = self.widgets["gate.entry"].get_text()
        self.forward_button.set_sensitive(typed == self._gate_token)

    # -- progress ----------------------------------------------------------

    def _build_progress(self):
        """One step is happening. Show that, and put the rest behind a count.

        This page used to be eleven equally weighted rows with a timing under
        each, and it filled the window: the bar, the pacing and everything
        underneath were below the fold on a 1440 by 900 screen. It was the
        readiness page's mistake in a different shape. A list of everything the
        machine has done is a log, and the answer to "what is happening" was
        the seventh row down, styled exactly like the six above it.

        So the running step gets the top of the page to itself, at heading
        size, with the ribbon under it. The finished ones become a count, and
        the count is the disclosure: open it and the full list with its timings
        is still there, which is what somebody diagnosing a slow install wants
        and nobody else ever needs.
        """
        box = column(18)
        box.append(label(F.PROGRESS_TITLE, "m3-headline-small"))
        # Starts as the safe wording and changes when the install crosses the
        # reversibility boundary. Kept as a widget rather than a constant line
        # because which of the two is showing is the answer to the only
        # question somebody hovering over the power button has.
        footer = label(F.PROGRESS_FOOTER_SAFE, "m3-body-medium", css="dim-label")
        self.widgets["progress.footer"] = footer
        box.append(footer)

        live = column(10)
        live.add_css_class("card")
        live.add_css_class("aurade-live-step")
        step = label("", "m3-title-medium")
        self.widgets["progress.step"] = step
        live.append(step)
        bar = ProgressRibbon(self)
        self.widgets["progress.bar"] = bar
        live.append(bar)
        # The detail used to be painted inside the bar by GTK, in whatever the
        # toolkit chose. On its own label it is set in the interface's type
        # and it can wrap, which "612 of 1041 packages" could not.
        detail = label("", "m3-body-small", css="dim-label")
        self.widgets["progress.detail"] = detail
        live.append(detail)
        pacing = label("", "m3-body-medium", css="dim-label")
        self.widgets["progress.pacing"] = pacing
        live.append(pacing)
        # Whether stopping is still possible is a fact about this step, so it
        # lives in this step's card. It used to float between two other cards,
        # belonging to neither.
        state = label("", "m3-body-small")
        self.widgets["progress.state"] = state
        live.append(state)
        box.append(live)

        # The rest, as a count that opens into the log it used to be.
        group = Adw.PreferencesGroup()
        steps = Adw.ExpanderRow(title=F.PROGRESS_STEPS)
        steps.add_prefix(icon_tile("view-list-symbolic"))
        self.widgets["progress.steps"] = steps
        group.add(steps)
        box.append(group)

        box.append(self._build_waiting())
        return page_shell(box)

    # -- the ten minutes in the middle -------------------------------------
    #
    # Every other page in this installer is measured in seconds. This one is
    # measured in ten minutes, and it held a title, a list and a bar: the
    # longest page in the product was the least designed one.
    #
    # What goes in the space is one card with two faces. By default it says
    # roughly how long the current step takes and then rotates something worth
    # knowing about the system being written. Ask, and the same card becomes a
    # game instead. One card rather than a panel of widgets, because the
    # install is still the subject of the page and this is what is underneath
    # it.
    #
    # Nothing on this card can reach the engine. It reads two strings the
    # bridge already sends and a text file, and its keys go to a snake.

    def _build_waiting(self):
        card = column(12)
        card.add_css_class("card")
        card.add_css_class("aurade-waiting")

        # The pacing line moved up to the live step, where it belongs: it is
        # about the install, and this card is about everything that is not.

        # A stack of two labels rather than one label and an opacity
        # animation: the crossfade is then GTK's, it is correct at any frame
        # rate, and it costs one widget.
        tips = Gtk.Stack()
        tips.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        tips.set_transition_duration(W.TIP_FADE_MS)
        tips.set_vhomogeneous(False)
        for name in ("a", "b"):
            face = label("", "m3-body-medium", css="dim-label")
            face.set_valign(Gtk.Align.CENTER)
            tips.add_named(face, name)
            self.widgets[f"progress.tip.{name}"] = face
        self.widgets["progress.tips"] = tips

        arena = Gtk.DrawingArea()
        arena.set_content_height(SNAKE_CELL * SNAKE_ROWS)
        arena.set_draw_func(self._draw_snake)
        arena.set_can_focus(True)
        arena.set_focusable(True)
        # Focusable, so it is reachable, so it has to say what it is. A game
        # nobody can be told about is a trap for anyone tabbing through.
        A.described(arena, "Snake",
                    "A game to pass the time. Arrow keys to steer.",
                    Gtk.AccessibleRole.APPLICATION)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_snake_key)
        arena.add_controller(keys)
        self.widgets["progress.arena"] = arena

        # Tips and game are two faces of one card, so the page does not change
        # height when somebody switches between them.
        faces = Gtk.Stack()
        faces.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        faces.set_transition_duration(W.TIP_FADE_MS)
        # Exactly the arena's height, whichever face is showing, so pressing
        # Play does not move everything above it. `vexpand` was wrong here: it
        # propagates out through the card and takes the rest of the page with
        # it, which is how a two line tip ended up centred in 380 pixels.
        faces.set_size_request(-1, SNAKE_ROWS * SNAKE_CELL)
        faces.add_named(tips, "tips")
        faces.add_named(arena, "game")
        self.widgets["progress.faces"] = faces
        card.append(faces)

        footer = row(12)
        score = label("", "m3-body-small", css="dim-label")
        score.set_hexpand(True)
        self.widgets["progress.score"] = score
        footer.append(score)
        toggle = Gtk.Button(label=F.WAIT_PLAY)
        toggle.add_css_class("flat")
        toggle.connect("clicked", self._on_waiting_toggled)
        self.widgets["progress.play"] = toggle
        footer.append(toggle)
        card.append(footer)
        return card

    def _on_waiting_toggled(self, _button) -> None:
        faces = self.widgets["progress.faces"]
        playing = faces.get_visible_child_name() != "game"
        faces.set_visible_child_name("game" if playing else "tips")
        self.widgets["progress.play"].set_label(
            F.WAIT_STOP if playing else F.WAIT_PLAY)
        if playing:
            if self.snake is None:
                self.snake = W.Snake(SNAKE_COLUMNS, SNAKE_ROWS)
            self.widgets["progress.arena"].grab_focus()
            if not self._snake_source:
                self._snake_source = GLib.timeout_add(
                    SNAKE_INTERVAL_MS, self._snake_tick)
        else:
            self._stop_snake()
        self._refresh_score()

    def _stop_snake(self) -> None:
        if self._snake_source:
            GLib.source_remove(self._snake_source)
            self._snake_source = 0

    def _snake_tick(self) -> bool:
        if self.snake is None:
            self._snake_source = 0
            return GLib.SOURCE_REMOVE
        self.snake.step()
        self.widgets["progress.arena"].queue_draw()
        self._refresh_score()
        return GLib.SOURCE_CONTINUE

    def _refresh_score(self) -> None:
        if self.snake is None or \
                self.widgets["progress.faces"].get_visible_child_name() != "game":
            self.widgets["progress.score"].set_label("")
            return
        if self.snake.dead:
            self.widgets["progress.score"].set_label(
                F.WAIT_SCORE_OVER % self.snake.score)
        else:
            self.widgets["progress.score"].set_label(
                F.WAIT_SCORE % self.snake.score)

    #: Which keys steer. Arrows and the usual four letters, and nothing else,
    #: so that no key on this page can do anything to the install.
    SNAKE_KEYS = {
        Gdk.KEY_Up: (0, -1), Gdk.KEY_w: (0, -1), Gdk.KEY_W: (0, -1),
        Gdk.KEY_Down: (0, 1), Gdk.KEY_s: (0, 1), Gdk.KEY_S: (0, 1),
        Gdk.KEY_Left: (-1, 0), Gdk.KEY_a: (-1, 0), Gdk.KEY_A: (-1, 0),
        Gdk.KEY_Right: (1, 0), Gdk.KEY_d: (1, 0), Gdk.KEY_D: (1, 0),
    }

    def _on_snake_key(self, _controller, keyval, _code, _state) -> bool:
        if self.snake is None:
            return False
        if keyval in self.SNAKE_KEYS:
            self.snake.turn(self.SNAKE_KEYS[keyval])
            return True
        if self.snake.dead:
            self.snake.reset()
            self.widgets["progress.arena"].queue_draw()
            self._refresh_score()
            return True
        return False

    def _draw_snake(self, area, cr, width, height) -> None:
        """The arena, sized to the card it is in.

        The cell is fixed and the column count comes from the width, rather
        than the other way round. Fixing the columns left a 448 pixel board
        floating in a 570 pixel card with no edge drawn round it, so the only
        thing visible was a few loose squares and it did not read as a game at
        all.
        """
        dark = self.dark
        scheme = T.scheme(dark)
        cell = SNAKE_CELL
        columns = max(10, int(width // cell))
        board_w = cell * columns
        board_h = cell * SNAKE_ROWS
        left = (width - board_w) / 2
        top = (height - board_h) / 2

        # The playfield, as an object with an edge. Without it the pieces are
        # loose on the card and there is nothing to tell you where the walls
        # are, which matters in a game whose only rule is that walls are walls.
        radius = 10
        cr.new_path()
        cr.arc(left + radius, top + radius, radius, 3.141593, 4.712389)
        cr.arc(left + board_w - radius, top + radius, radius, 4.712389, 0)
        cr.arc(left + board_w - radius, top + board_h - radius, radius,
               0, 1.570796)
        cr.arc(left + radius, top + board_h - radius, radius,
               1.570796, 3.141593)
        cr.close_path()
        cr.set_source_rgb(*T.rgb(scheme["surface_container_lowest" if not dark
                                        else "surface_container_high"]))
        cr.fill_preserve()
        # A hairline, so the playfield has an edge rather than being a lighter
        # patch. The walls are the only rule in this game.
        cr.set_source_rgba(*T.rgb(scheme["outline_variant"]), 0.9)
        cr.set_line_width(1)
        cr.stroke()

        if self.snake is None:
            return
        # The arena follows the card. A window that is resized mid game starts
        # a new one rather than leaving the snake outside its own walls.
        if self.snake.width != columns:
            self.snake = W.Snake(columns, SNAKE_ROWS)
        if self.snake.food is not None:
            cr.set_source_rgb(*T.rgb(scheme["tertiary"]))
            fx, fy = self.snake.food
            cr.arc(left + (fx + 0.5) * cell, top + (fy + 0.5) * cell,
                   cell * 0.32, 0, 6.2832)
            cr.fill()
        # The head in the primary accent and the body a step back from it, so
        # the direction of travel is readable without watching it move.
        #
        # Past ten, the body runs the brand gradient from head to tail instead.
        # Ten is far enough in that nobody arrives there by accident and near
        # enough that somebody who decides to try will get there before the
        # install finishes.
        earned = self.snake.score >= SNAKE_GRADIENT_AT
        head_rgb = T.rgb(scheme["primary"])
        tail_rgb = T.rgb(scheme["tertiary"])
        length = max(1, len(self.snake.body) - 1)
        for index, (x, y) in enumerate(self.snake.body):
            if index == 0:
                cr.set_source_rgba(*head_rgb, 1.0)
            elif earned:
                blend = (index - 1) / length
                cr.set_source_rgba(*(
                    head + (tail - head) * blend
                    for head, tail in zip(head_rgb, tail_rgb)), 1.0)
            else:
                # The accent, fading along the length. The container tone was
                # nearly white on a white playfield, so the snake was a head
                # with nothing behind it.
                cr.set_source_rgba(*head_rgb,
                                   0.85 - 0.45 * ((index - 1) / length))
            cr.rectangle(left + x * cell + 1, top + y * cell + 1,
                         cell - 2, cell - 2)
            cr.fill()

    def _draw_progress(self, report: dict) -> None:
        steps = self.widgets["progress.steps"]
        pct, detail, running_label = 0, "", ""
        # Safe until a stage says otherwise. An install that has not reached a
        # running stage yet has not written anything either, and defaulting the
        # other way would put the strong warning on screen before it is true.
        reversible = True
        done = pending = 0
        for stage in report.get("stages", []):
            name = stage["stage"]
            item = self.stage_rows.get(name)
            if item is None:
                item = Adw.ActionRow(title=stage["label"])
                icon = Gtk.Image.new_from_icon_name("content-loading-symbolic")
                item.add_prefix(icon)
                item.stage_icon = icon
                item.add_css_class("aurade-transition")
                # `add_row`, not `add`. An AdwExpanderRow's `add` is the
                # PreferencesGroup method it does not have, and getting this
                # wrong once already cost a release of enum pickers that
                # assembled from correct calls and showed nothing.
                steps.add_row(item)
                self.stage_rows[name] = item
            status = stage.get("status", "pending")
            elapsed = stage.get("elapsed") or ""
            item.set_subtitle(elapsed)
            if elapsed:
                item.add_css_class("aurade-mono")
            item.stage_icon.set_from_icon_name({
                "ok": "object-select-symbolic",
                "running": "media-playback-start-symbolic",
                "failed": "dialog-error-symbolic",
            }.get(status, "content-loading-symbolic"))
            for css in ("aurade-stage-done", "aurade-stage-active",
                        "aurade-stage-failed", "aurade-stage-waiting"):
                item.remove_css_class(css)
            item.add_css_class({
                "ok": "aurade-stage-done",
                "running": "aurade-stage-active",
                "failed": "aurade-stage-failed",
            }.get(status, "aurade-stage-waiting"))
            if status == "running":
                pct = int(stage.get("pct", 0))
                detail = stage.get("detail", "")
                running_label = stage.get("label", "")
                reversible = stage.get("reversible", True)
            elif status == "ok":
                done += 1
            elif status != "failed":
                pending += 1

        # The one line that answers "what is happening", at heading size,
        # because it is the only question this page exists to answer.
        self.widgets["progress.step"].set_label(
            running_label or F.PROGRESS_STEP_IDLE)
        self.widgets["progress.footer"].set_label(
            F.PROGRESS_FOOTER_SAFE if reversible else F.PROGRESS_FOOTER)
        steps.set_title(F.progress_steps(done, pending))
        bar = self.widgets["progress.bar"]
        # The whole install, weighted by how long each stage takes, not how
        # far through one stage the engine happens to be. `pct` is still what
        # the detail line under the bar is built from, because "612 of 1041
        # packages" is about the stage and the bar is about the wait.
        overall = int(report.get("overall", 0))
        wanted = max(0.0, min(1.0, overall / 100.0))
        # Stages complete in uneven jumps - a package set arrives all at once -
        # and a bar that teleports forward reads as a bar that is guessing.
        # Easing to the new value takes the same time either way and makes the
        # jump legible as progress. Never backwards: the only thing that moves
        # a bar left is a mistake, and it should look like one.
        current = bar.get_fraction()
        if self.animate and wanted > current:
            target = Adw.PropertyAnimationTarget.new(bar, "fraction")
            animation = Adw.TimedAnimation.new(bar, current, wanted, 260, target)
            animation.set_easing(Adw.Easing.EASE_OUT_CUBIC)
            self._progress_fade = animation
            animation.play()
        else:
            bar.set_fraction(wanted)
        self.widgets["progress.detail"].set_label(
            detail or report.get("position", ""))

        # The ribbon is drawn, so without this it is a rectangle with no value
        # in it. Kept current on every refresh rather than set once, because a
        # progress bar whose reported value never moves is worse than one that
        # reports nothing: it says the install has stalled.
        spoken = f"{running_label}, {overall} percent" if running_label else ""
        A.meter(bar, "Installation progress", wanted, 0.0, 1.0, spoken)

        # The title bar, which is the actual answer to a ten minute wait.
        #
        # Somebody who can see "58% AuraDE" in a taskbar can go and do
        # something else and glance back, and somebody who cannot has to sit
        # in front of the window. The text installer has put this in the
        # terminal title since it had one; this is the same string, so the two
        # front ends read identically in a tab and in a task switcher.
        self.set_title(f"{overall}% AuraDE  {running_label}".rstrip())

        # And the part that matters most on this page. Ten minutes with no
        # sound is indistinguishable from a hung machine if you cannot see the
        # screen, so each stage says itself once as it starts. Once, not on
        # every refresh: this runs on a timer, and a reader that repeats the
        # same sentence every second is a reader you turn off.
        if running_label and running_label != self._spoken_stage:
            self._spoken_stage = running_label
            A.announce(self, f"{running_label}. {pct} percent.")

        # The stop control exists only while the shared reversibility boundary
        # says nothing has been written, and it is removed rather than
        # disabled at the boundary: a greyed-out Stop invites the user to keep
        # pressing it at the exact moment the answer has become no.
        # What is happening and roughly how long it takes. The pacing half is
        # a range from the shared copy library and the elapsed half is measured
        # from the journal, which is the right way round: the number that is
        # real is the one about the past. There is deliberately no countdown.
        # An estimate that turns out wrong is remembered longer than the
        # install it was wrong about, and there is no honest per-machine number
        # until the engine reports package by package.
        self.widgets["progress.pacing"].set_label(self._pacing_text(report))

        state = self.widgets["progress.state"]
        if report.get("can_stop"):
            self.secondary_button.set_label("Stop")
            self.secondary_button.set_visible(True)
            state.set_label("Nothing has been written to any disk yet.")
            state.remove_css_class("warning")
            state.add_css_class("aurade-stage-done")
        else:
            self.secondary_button.set_visible(False)
            state.set_label(F.PROGRESS_UNINTERRUPTIBLE if report.get("running") else "")
            state.remove_css_class("aurade-stage-done")
            state.add_css_class("warning")
        state.set_visible(bool(state.get_label()))

    def _pacing_text(self, report: dict) -> str:
        active = report.get("active", "")
        running = None
        for stage in report.get("stages", []):
            if stage.get("stage") == active:
                running = stage
                break
        if running is None:
            return ""
        # Not the label. It is the heading directly above this line now, and
        # a card that says "Installing the base system" twice reads as a card
        # that was assembled rather than written.
        parts: list[str] = []
        pacing = running.get("pacing", "")
        if pacing:
            parts.append(F.PROGRESS_PACING % pacing)
        elapsed = self._elapsed_text(report.get("elapsed_ms", 0))
        if elapsed:
            parts.append(elapsed)
        return " ".join(part for part in parts if part.strip(". "))

    @staticmethod
    def _elapsed_text(elapsed_ms) -> str:
        try:
            minutes = int(elapsed_ms) // 60000
        except (TypeError, ValueError):
            return ""
        if minutes < 1:
            return ""
        if minutes == 1:
            return F.PROGRESS_ELAPSED_ONE
        return F.PROGRESS_ELAPSED % minutes

    def _rotate_tip(self) -> bool:
        """Fade the next tip in, if anyone is looking at the tips."""
        if not self.tips:
            self._tip_source = 0
            return GLib.SOURCE_REMOVE
        stack = self.widgets["progress.tips"]
        showing = stack.get_visible_child_name()
        other = "b" if showing == "a" else "a"
        self.widgets[f"progress.tip.{other}"].set_label(
            self.tips.at(self.tip_index))
        self.tip_index += 1
        stack.set_visible_child_name(other)
        return GLib.SOURCE_CONTINUE

    def _poll_progress(self) -> bool:
        try:
            report = self.model.progress()
        except BridgeError as exc:
            self._fatal(str(exc))
            return GLib.SOURCE_REMOVE
        self._draw_progress(report)
        if report.get("running"):
            return GLib.SOURCE_CONTINUE
        self._progress_source = 0
        try:
            result = self.model.wait()
            failure = self.model.failure()
        except BridgeError as exc:
            self._fatal(str(exc))
            return GLib.SOURCE_REMOVE
        self.install_status = int(result.get("status", 1))
        self.failure_cause = failure.get("cause", "")
        self.flow.finished(self.install_status, self.failure_cause)
        self.refresh()
        return GLib.SOURCE_REMOVE

    def stop_install(self) -> None:
        dialog = Adw.AlertDialog(
            heading="Stop the installation?",
            body=("Nothing has been written to any disk, so stopping leaves "
                  "this computer exactly as it was. You can start again from "
                  "the beginning."))
        dialog.add_response("keep", "Keep installing")
        dialog.add_response("stop", "Stop")
        dialog.set_response_appearance("stop", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("keep")
        dialog.set_close_response("keep")
        dialog.connect("response", self._on_stop_response)
        dialog.present(self)

    def _on_stop_response(self, _dialog, response: str) -> None:
        if response != "stop":
            return
        try:
            result = self.model.call("stop")
        except BridgeError as exc:
            self._fatal(str(exc))
            return
        if not result.get("ok"):
            # The only way here is for the boundary to have been crossed
            # between the button being drawn and being pressed.
            self._toast(result.get("error",
                                   "The installation cannot be stopped now."))
            self.secondary_button.set_visible(False)

    # -- outcomes ----------------------------------------------------------

    def _build_outcome(self, name: str, title: str, body: str, icon: str):
        box = column(0)
        box.set_valign(Gtk.Align.CENTER)
        box.set_vexpand(True)
        image = Gtk.Image.new_from_icon_name(icon)
        image.set_pixel_size(56)
        image.set_margin_bottom(20)
        if name == F.DONE:
            image.add_css_class("aurade-stage-done")
        self.widgets[f"{name}.icon"] = image
        box.append(image)
        heading = label(title, "m3-headline-large", center=True)
        heading.set_margin_bottom(12)
        box.append(heading)
        box.append(label(body, "m3-body-large", center=True))
        if name == F.DONE:
            box.append(self._build_done_facts())
        extra = label("", "m3-body-medium", center=True, css="dim-label")
        extra.set_margin_top(16)
        extra.set_visible(False)
        self.widgets[f"{name}.extra"] = extra
        box.append(extra)
        return page_shell(box)

    def _build_done_facts(self) -> Gtk.Widget:
        """The username and the hostname, on the screen that just finished.

        People forget both within the minute, and the sign-in prompt they are
        about to meet asks for one of them. The text installer has said this
        since it had a done screen; the graphical one said "the username you
        chose", which is a sentence about a fact rather than the fact.

        Set in mono, like every other thing in this installer somebody has to
        type back exactly. A username in the prose face with an l and a 1 in
        it is a username somebody gets wrong at the sign-in prompt, which is
        the first thing that happens after this screen.
        """
        grid = Gtk.Grid()
        grid.set_column_spacing(14)
        grid.set_row_spacing(4)
        grid.set_halign(Gtk.Align.CENTER)
        grid.set_margin_top(20)
        grid.set_visible(False)
        for row_index, (key, title) in enumerate(
                (("username", F.DONE_SIGN_IN), ("hostname", F.DONE_COMPUTER))):
            name = label(title, "m3-label-medium", wrap=False, css="dim-label")
            name.set_xalign(1.0)
            self.widgets[f"done.{key}.name"] = name
            grid.attach(name, 0, row_index, 1, 1)
            value = label("", "m3-body-medium", wrap=False, css="aurade-mono")
            self.widgets[f"done.{key}"] = value
            grid.attach(value, 1, row_index, 1, 1)
        self.widgets["done.facts"] = grid
        return grid

    def _build_failure(self):
        box = column(16)
        headline = label("", "m3-headline-small")
        self.widgets["failure.headline"] = headline
        box.append(headline)
        stage_line = label("", "m3-body-large")
        self.widgets["failure.stage"] = stage_line
        box.append(stage_line)
        for key in ("cause", "explanation", "advice"):
            item = label("", "m3-body-medium")
            item.set_visible(False)
            if key == "advice":
                item.add_css_class("warning")
            self.widgets[f"failure.{key}"] = item
            box.append(item)
        detail = label("", "m3-body-small", css="aurade-mono")
        detail.set_visible(False)
        self.widgets["failure.detail"] = detail
        box.append(detail)
        notice = label("", "m3-body-medium")
        notice.set_visible(False)
        self.widgets["failure.notice"] = notice
        box.append(notice)
        actions = row(12)
        for key, text in F.FAILURE_ACTIONS:
            button = Gtk.Button(label=text)
            button.add_css_class("pill")
            if key == "export":
                button.add_css_class("suggested-action")
            button.connect("clicked", self._on_failure_action, key)
            self.widgets[f"failure.action.{key}"] = button
            actions.append(button)
        box.append(actions)
        hint = label("", "m3-body-small", css="aurade-mono")
        self.widgets["failure.loghint"] = hint
        box.append(hint)
        return page_shell(box)

    def _refresh_failure(self) -> None:
        report = self.model.failure()
        # The disk first. After a failed install the only question anyone
        # has is whether their machine still has its old system on it, and
        # the answer is the shared reversibility boundary, not a guess made
        # here. The stage that stopped is the second line, because it is the
        # answer to a question they have not asked yet.
        stage = report.get("label") or ""
        self.widgets["failure.headline"].set_label(
            "Nothing was written to any disk" if report.get("reversible")
            else "This disk has been changed")
        self.widgets["failure.stage"].set_label(
            f"{stage} did not finish." if stage else "The installation stopped.")
        for key, text in (("cause", report.get("cause_text", "")),
                          ("explanation", report.get("explanation", "")),
                          ("advice", report.get("restart_advice", ""))):
            widget = self.widgets[f"failure.{key}"]
            widget.set_label(text)
            widget.set_visible(bool(text))
        detail = self.widgets["failure.detail"]
        detail.set_label(report.get("detail", ""))
        detail.set_visible(bool(report.get("detail")))
        self.widgets["failure.loghint"].set_label(
            f"Full log: {report.get('raw_log', '')}")
        notice = self.widgets["failure.notice"]
        if self._export_notice is None:
            notice.set_visible(False)
        else:
            text, ok = self._export_notice
            notice.set_label(text)
            notice.remove_css_class("error")
            notice.remove_css_class("aurade-stage-done")
            notice.add_css_class("aurade-stage-done" if ok else "error")
            notice.set_visible(True)
        self.banner.set_revealed(False)

    def _on_failure_action(self, _button, key: str) -> None:
        if key == "export":
            try:
                result = self.model.export(self.install_status)
            except BridgeError as exc:
                self._fatal(str(exc))
                return
            notice = result.get("notice") or "The report could not be saved."
            self._export_notice = (notice, bool(result.get("ok")))
            self._refresh_failure()
            self._toast(notice)
        elif key == "log":
            self._show_log()
        elif key == "reboot":
            Gio.Subprocess.new(["systemctl", "reboot"], Gio.SubprocessFlags.NONE)

    def _show_log(self) -> None:
        path = self.model.failure().get("raw_log", "")
        try:
            with open(path, "r", errors="replace") as handle:
                text = handle.read()
        except OSError as exc:
            self._toast(f"The log could not be opened: {exc}")
            return
        view = Gtk.TextView()
        view.set_editable(False)
        view.set_monospace(True)
        view.get_buffer().set_text(text)
        scroller = Gtk.ScrolledWindow()
        scroller.set_child(view)
        scroller.set_size_request(780, 480)
        dialog = Adw.Dialog()
        dialog.set_title("Installer log")
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        toolbar.set_content(scroller)
        dialog.set_child(toolbar)
        dialog.present(self)

    # -- keyboard ----------------------------------------------------------

    def _install_shortcuts(self) -> None:
        controller = Gtk.ShortcutController()
        controller.set_scope(Gtk.ShortcutScope.GLOBAL)
        for trigger, handler in (("Escape", self.on_back),
                                 ("<alt>Left", self.on_back),
                                 ("<alt>Right", self.on_forward)):
            controller.add_shortcut(Gtk.Shortcut(
                trigger=Gtk.ShortcutTrigger.parse_string(trigger),
                action=Gtk.CallbackAction.new(lambda *_a, h=handler: h() or True)))
        self.add_controller(controller)
        self.set_default_widget(self.forward_button)

        # And one more listener, which does nothing at all to the installer.
        #
        # The swoop plays once, on the first press of Continue, and then never
        # again in that session. It is the best thing this front end draws and
        # almost nobody will see it twice. So: type the word on the welcome
        # page and it plays again.
        #
        # Deliberately not written down anywhere a user would look. The rare
        # tips on the progress page mention that there is a game and say
        # nothing about this, which is the point of the difference between the
        # two: one is quiet, this one is hidden.
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_secret_key)
        self.add_controller(keys)

    #: Six letters, typed in order, on the one page where no control wants
    #: them. Any other page, any other key, and the buffer empties.
    SECRET_WORD = "aurora"

    def _on_secret_key(self, _controller, keyval, _code, _state) -> bool:
        if self.flow.state != F.WELCOME:
            self._secret = ""
            return False
        letter = chr(keyval) if 32 <= keyval < 127 else ""
        if not letter:
            self._secret = ""
            return False
        self._secret = (self._secret + letter.lower())[-len(self.SECRET_WORD):]
        if self._secret != self.SECRET_WORD:
            return False
        self._secret = ""
        self._swooped = False
        self.play_swoop()
        return True

    # -- rendering ---------------------------------------------------------

    def _sound(self, times: int) -> None:
        """A pattern, not a pitch.

        `Gdk.Display.beep` is whatever the session has: a real sound if there
        is one, the terminal bell if not, nothing at all if neither. That is
        the right failure mode for something whose absence costs nothing and
        whose presence is the only thing telling somebody across the room that
        ten minutes of waiting is over.

        One for finished, three for stopped, matching the text installer, so
        the two front ends do not disagree about what a machine sounds like.
        """
        display = self.get_display()
        if display is None:
            return
        for index in range(times):
            GLib.timeout_add(index * 150, lambda: (display.beep(), False)[1])

    def _announce_page(self, state: str, name: str) -> None:
        """Say where we now are, once per arrival.

        A sighted user gets this from the page redrawing. Without it, moving
        between pages is silent except for whatever the newly focused widget
        happens to say, which is a field label with no context around it.

        The position comes first because "step 3 of 7" is the question people
        actually have during a wizard, and the failure states are urgent
        because they are the one case where interrupting is the right thing.
        """
        if name == self._spoken_page:
            return
        self._spoken_page = name
        if state == "pages":
            page = F.PAGES_BY_NAME[self.flow.current_page]
            position = self.flow.step_position()
            title = page.title
        else:
            position = ""
            title = {
                F.WELCOME: F.WELCOME_TITLE, F.REVIEW: F.REVIEW_TITLE,
                F.GATE: F.GATE_TITLE, F.PROGRESS: F.PROGRESS_TITLE,
                F.DONE: F.DONE_TITLE, F.FAILURE: F.FAILURE_TITLE,
                F.CANCELLED: F.CANCELLED_TITLE, F.STOPPED: F.STOPPED_TITLE,
                F.PLANNED: F.PLANNED_TITLE,
            }.get(state, "")
        if not title:
            return
        urgent = state in (F.FAILURE, F.STOPPED)
        A.announce(self, f"{position}. {title}." if position else f"{title}.",
                   urgent=urgent)
        if state == F.DONE:
            self._sound(1)
        elif state in (F.FAILURE, F.STOPPED):
            self._sound(3)

    def refresh(self) -> None:
        state = self.flow.state
        name = f"page:{self.flow.current_page}" if state == "pages" else state
        self.stack.set_visible_child_name(name)
        self.step_label.set_label(self.flow.step_position())
        self._announce_page(state, name)

        # A page may refuse to be left. Cleared before the page is drawn and
        # set by the page itself, because the alternative - the page disabling
        # the button directly - is a decision that the button block below then
        # quietly reverses, which is exactly what a blocked readiness verdict
        # used to do: the refusal was computed, applied, and undone two dozen
        # lines later, on every refresh.
        self.forward_blocked = False

        if state == "pages":
            self._refresh_page(F.PAGES_BY_NAME[self.flow.current_page])
        else:
            self._refresh_state(state)

        # The chrome's advanced toggle reflects the flow rather than owning
        # it: the review screen can open the same page, and a toggle that says
        # off while the page is in the flow is worse than no toggle.
        advanced = self.widgets.get("chrome.advanced")
        if advanced is not None:
            if advanced.get_active() != self.flow.show_advanced:
                advanced.handler_block(self._advanced_handler)
                advanced.set_active(self.flow.show_advanced)
                advanced.handler_unblock(self._advanced_handler)
            # Nothing about the flow is negotiable once it is running.
            advanced.set_sensitive(state in ("pages", F.WELCOME, F.REVIEW))

        back = self.flow.back_label()
        self.back_button.set_visible(bool(back))
        self.back_button.set_label(back or "")
        forward = self.flow.forward_label()
        self.forward_button.set_visible(bool(forward))
        self.forward_button.set_label(forward or "")
        if state != F.PROGRESS:
            self.secondary_button.set_visible(False)
        if state == F.GATE:
            self.forward_button.add_css_class("destructive-action")
            self.forward_button.remove_css_class("suggested-action")
            self.refresh_gate_button()
        else:
            self.forward_button.remove_css_class("destructive-action")
            self.forward_button.add_css_class("suggested-action")
            self.forward_button.set_sensitive(not self.forward_blocked)

        # The aurora runs on the pages that are about the product and stops on
        # the ones that are about a decision. Atmosphere behind a disk list is
        # atmosphere in the way.
        if state in (F.WELCOME, F.DONE, F.STOPPED, F.CANCELLED, F.PLANNED) or (
                state == "pages"
                and self.flow.current_page in ("readiness", "network")):
            self.start_aurora()
        else:
            self.stop_aurora()
        GLib.idle_add(self._focus_first)

    def _refresh_page(self, page: F.Page) -> None:
        if page.name == "readiness":
            self._refresh_readiness()
        elif page.name == "network":
            self._refresh_network()
        elif page.name == "disk":
            self._refresh_disks()
            self._refresh_storage()
        elif page.name == "encryption":
            self._refresh_encryption()
        else:
            self.banner.set_revealed(False)

    def _refresh_state(self, state: str) -> None:
        self.banner.set_revealed(False)
        if state == F.REVIEW:
            self._refresh_review()
        elif state == F.GATE:
            self._refresh_gate()
        elif state == F.DONE:
            encrypted = self.model.get("encrypt") == "yes"
            extra = self.widgets["done.extra"]
            extra.set_label(F.DONE_ENCRYPTED if encrypted else "")
            extra.set_visible(encrypted)
            self._refresh_done_facts()
            self.play_settle()
        elif state == F.FAILURE:
            self._refresh_failure()

    def _refresh_done_facts(self) -> None:
        """Fill the two facts in, and show nothing rather than a blank row.

        The model is the only place either of these lives, and an install that
        somehow reached the done screen without a username is an install with
        a bigger problem than a missing line. Hiding the whole block is still
        the right answer for it: a label with nothing after it reads as the
        installer having lost something.
        """
        grid = self.widgets.get("done.facts")
        if grid is None:
            return
        shown = False
        for key in ("username", "hostname"):
            value = str(self.model.get(key) or "")
            self.widgets[f"done.{key}"].set_label(value)
            # The label goes with its value. "This computer" followed by
            # nothing is worse than no row: it reads as the installer having
            # mislaid the hostname rather than as a row that does not apply.
            self.widgets[f"done.{key}"].set_visible(bool(value))
            self.widgets[f"done.{key}.name"].set_visible(bool(value))
            shown = shown or bool(value)
        grid.set_visible(shown)

    def _refresh_encryption(self) -> None:
        group = self.widgets.get("group.luks_passphrase")
        if group is not None:
            group.set_visible("luks_passphrase" in set(self.model.visible()))

    def _focus_first(self) -> bool:
        state = self.flow.state
        candidate = None
        if state == "pages":
            page = F.PAGES_BY_NAME[self.flow.current_page]
            if page.name == "disk":
                candidate = self.widgets.get("disk.list")
            elif page.name == "network":
                candidate = self.widgets.get("wifi.list")
            else:
                for question in page.questions:
                    candidate = self.widgets.get(f"q.{question}")
                    # is_visible, not get_visible: a row inside a hidden group
                    # still reports its own visibility as true, and focusing
                    # one puts the cursor where nothing is drawn.
                    if candidate is not None and candidate.is_visible():
                        break
                    candidate = None
        elif state == F.GATE:
            candidate = self.widgets.get("gate.entry")
        if candidate is None:
            candidate = self.forward_button
        candidate.grab_focus()
        return GLib.SOURCE_REMOVE

    def _warn(self, text: str) -> None:
        self.banner.set_title(text)
        self.banner.set_revealed(True)

    def _toast(self, message: str) -> None:
        if not message:
            return
        toast = Adw.Toast(title=message)
        toast.set_timeout(6)
        self.toast_overlay.add_toast(toast)

    # -- collecting answers ------------------------------------------------

    def _collect_page(self, page: F.Page) -> bool:
        """Send this page's answers to the model. False stops the flow.

        Validation is the model's, always. A rule re-stated here would be a
        second copy of it, and the copy that drifts is the one the user meets.
        """
        visible = set(self.model.visible())
        for question in page.questions:
            spec = self.manifest["questions"].get(question)
            if spec is None:
                continue
            if spec["secret"]:
                if question not in visible:
                    continue
                if not self._collect_secret(question, spec):
                    return False
                continue
            value = self._value_of(question, spec)
            ok, error = self.model.set(question, value)
            if not ok:
                self._flag(question, error or spec["error"])
                return False
            self._flag(question, "")
        return True

    def _collect_secret(self, question: str, spec: dict) -> bool:
        entry = self.widgets.get(f"q.{question}")
        repeat = self.widgets.get(f"q.{question}.repeat")
        if entry is None or repeat is None:
            return True
        first = entry.get_text()
        second = repeat.get_text()
        # Both blank on a question already answered means "leave it alone".
        # The fields are cleared as soon as the model has the value, so
        # without this, going back a page and forward again would demand the
        # password be typed twice more to get past a screen it already passed.
        if question in self.secrets_set and not first and not second:
            return True
        if not first or first != second:
            self._flag(question, spec["error"])
            entry.grab_focus()
            return False
        ok, error = self.model.secret(question, first)
        entry.set_text("")
        repeat.set_text("")
        del first, second
        if not ok:
            self._flag(question, error or spec["error"])
            return False
        self._flag(question, "")
        self.secrets_set.add(question)
        group = self.widgets.get(f"group.{question}")
        if group is not None:
            group.set_description(f"{spec['help']} Leave both fields blank to "
                                  "keep what you already entered.")
        return True

    def _value_of(self, question: str, spec: dict) -> str:
        if spec["type"] == "disk":
            return self.model.get("target")
        widget = self.widgets.get(f"q.{question}")
        if widget is None:
            return spec["default"]
        if spec["type"] == "bool":
            return "yes" if widget.get_active() else "no"
        if spec["type"] == "enum":
            values = self.enum_values.get(question, [])
            index = widget.get_selected()
            return values[index] if 0 <= index < len(values) else spec["default"]
        return widget.get_text()

    def _on_secret_blur(self, _controller, question: str) -> None:
        """The two secret fields, compared when the second one is left.

        Silent while either is empty, because a field somebody has not
        finished typing has not disagreed with anything yet, and a warning
        that appears on the way past is a warning that means nothing.
        """
        entry = self.widgets.get(f"q.{question}")
        repeat = self.widgets.get(f"q.{question}.repeat")
        if entry is None or repeat is None:
            return
        first, second = entry.get_text(), repeat.get_text()
        if not first or not second:
            repeat.remove_css_class("error")
            return
        if first == second:
            repeat.remove_css_class("error")
            return
        repeat.add_css_class("error")
        self._toast(F.SECRET_MISMATCH)

    def _flag(self, question: str, message: str) -> None:
        widget = self.widgets.get(f"q.{question}")
        if widget is None:
            return
        if message:
            widget.add_css_class("error")
            self._toast(message)
            widget.grab_focus()
        else:
            widget.remove_css_class("error")

    # -- actions -----------------------------------------------------------

    def _on_bool_changed(self, item, _param, question: str) -> None:
        self.model.set(question, "yes" if item.get_active() else "no")
        if question == "encrypt":
            self._refresh_encryption()

    def _on_disk_selected(self, _listbox, item) -> None:
        if item is None:
            return
        ok, error = self.model.set("target", getattr(item, "disk_path", ""))
        if not ok:
            self._toast(error or "That disk cannot be installed to.")

    def on_forward(self) -> None:
        # The first Continue is the point of no return for the renderer chain:
        # after it there are answers on screen that a restart under a different
        # renderer would silently discard.
        S.report(S.ENGAGED)
        state = self.flow.state
        if state == F.WELCOME:
            self.play_swoop()
        try:
            if state == "pages":
                if not self._collect_page(F.PAGES_BY_NAME[self.flow.current_page]):
                    return
                self.flow.forward()
                self.refresh()
                return
            if state == F.REVIEW:
                self._start_plan()
                return
            if state == F.GATE:
                self._start_execute()
                return
            self.flow.forward()
            self.refresh()
        except BridgeError as exc:
            self._fatal(str(exc))

    def on_secondary(self) -> None:
        if self.flow.state == F.PROGRESS:
            self.stop_install()

    def on_back(self) -> None:
        self.skip_swoop()
        action = self.flow.back_action()
        if action == "quit":
            self._confirm_quit()
            return
        if not action:
            return
        self.flow.back()
        self.refresh()

    def _confirm_quit(self) -> None:
        dialog = Adw.AlertDialog(
            heading="Quit the installer?",
            body=("Nothing has been written to any disk. This computer will "
                  "be left exactly as it is now."))
        dialog.add_response("stay", "Keep going")
        dialog.add_response("quit", "Quit")
        dialog.set_response_appearance("quit", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("stay")
        dialog.set_close_response("stay")
        dialog.connect("response", self._on_quit_response)
        dialog.present(self)

    def _on_quit_response(self, _dialog, response: str) -> None:
        if response != "quit":
            return
        self.flow.cancel()
        self.refresh()

    def _start_plan(self) -> None:
        self.forward_button.set_sensitive(False)
        self.forward_button.set_label("Checking")
        try:
            result = self.model.plan()
        except BridgeError as exc:
            self._fatal(str(exc))
            return
        finally:
            self.forward_button.set_sensitive(True)
        if not result.get("ok"):
            self.install_status = int(result.get("status", 1))
            self.failure_cause = ""
            self.flow.plan_failed()
            self.refresh()
            return
        self.flow.forward()
        self.refresh()

    def _start_execute(self) -> None:
        typed = self.widgets["gate.entry"].get_text()
        if typed != self._gate_token:
            self._toast("The confirmation did not match the disk.")
            return
        try:
            result = self.model.execute(typed)
        except BridgeError as exc:
            self._fatal(str(exc))
            return
        if not result.get("ok"):
            self._toast(result.get("error", "The installation could not start."))
            return
        self.flow.confirmed()
        self.refresh()
        self._progress_source = GLib.timeout_add(
            PROGRESS_INTERVAL_MS, self._poll_progress)
        if self.tips and not self._tip_source:
            # The first tip goes up immediately rather than after the first
            # interval, so the card is never blank on the page somebody has
            # just arrived at.
            self._rotate_tip()
            if self.animate:
                self._tip_source = GLib.timeout_add(
                    W.TIP_INTERVAL_MS, self._rotate_tip)

    def _fatal(self, message: str) -> None:
        dialog = Adw.AlertDialog(
            heading="The installer stopped responding",
            body=(f"{message}\n\nNothing further will be written. Restart this "
                  "computer and start the installer again, or use the text "
                  "installer."))
        dialog.add_response("close", "Close")
        dialog.set_default_response("close")
        dialog.connect("response", lambda *_: self.close())
        dialog.present(self)


class InstallerApplication(Adw.Application):
    def __init__(self, model: Bridge, plan_only: bool):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.model = model
        self.plan_only = plan_only
        self.window = None

    def do_activate(self) -> None:  # noqa: N802  (GObject naming)
        if self.window is None:
            self.window = InstallerWindow(self, self.model, self.plan_only)
            self.window.connect("map", self._on_first_map)
        self.window.present()

    @staticmethod
    def _on_first_map(window: Gtk.Widget) -> None:
        """A window reached the screen: this renderer works."""
        S.report(S.MAPPED)
        window.fade_in()


def run(model: Bridge, plan_only: bool = False) -> int:
    Adw.init()
    return InstallerApplication(model, plan_only).run([])
