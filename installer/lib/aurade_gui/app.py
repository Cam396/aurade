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

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import brand, flow as F, locales, stage as S, tokens as T  # noqa: E402
from .bridge import Bridge, BridgeError  # noqa: E402

APP_ID = "org.aurade.Installer"

#: How often the progress page re-reads the journal. The journal is the only
#: account of what happened; this is a view of it and keeps no tally.
PROGRESS_INTERVAL_MS = 400

#: Aurora frame interval. Slow on purpose: this is atmosphere behind text
#: someone is reading, not an animation anyone should watch.
AURORA_INTERVAL_MS = 90

_LIB = os.path.dirname(os.path.realpath(__file__))
THEME_CSS = os.path.join(_LIB, "theme.css")
THEME_DARK_CSS = os.path.join(_LIB, "theme-dark.css")


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
    box.set_margin_top(26)
    box.set_margin_bottom(26)
    box.set_margin_start(24)
    box.set_margin_end(24)
    box.append(child)
    clamp = Adw.Clamp(maximum_size=width, tightening_threshold=int(width * 0.85))
    clamp.set_child(box)
    scroller = Gtk.ScrolledWindow()
    scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroller.set_vexpand(True)
    scroller.set_child(clamp)
    return scroller


# --------------------------------------------------------------------------
# Brand chrome
# --------------------------------------------------------------------------


class Aurora(Gtk.DrawingArea):
    """The backdrop. The mark's ring, opened out to fill the window."""

    def __init__(self, window: "InstallerWindow") -> None:
        super().__init__()
        self.window = window
        self.phase = 0.0
        self.set_draw_func(self._draw)
        self.set_can_target(False)

    def _draw(self, _area, cr, width: int, height: int) -> None:
        brand.draw_aurora(cr, width, height, self.window.dark, self.phase)

    def advance(self) -> bool:
        self.phase += 0.012
        self.queue_draw()
        return GLib.SOURCE_CONTINUE


class RibbonRule(Gtk.DrawingArea):
    """The gradient across the `A`, reduced to a hairline."""

    def __init__(self, window: "InstallerWindow") -> None:
        super().__init__()
        self.window = window
        self.set_content_height(2)
        self.set_draw_func(
            lambda _a, cr, w, h: brand.draw_ribbon_rule(cr, w, h, self.window.dark))
        self.set_can_target(False)


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
        self.group_rows: dict = {}
        self.stage_rows: dict = {}
        self.secrets_set: set = set()
        self.enum_values: dict = {}
        self.probe: dict = {}
        self.install_status = 0
        self.failure_cause = ""
        self.dark = False
        self._progress_source = 0
        self._aurora_source = 0
        self._provider = None
        self._gate_token = ""
        self._export_notice = None
        self._wifi_target = ""

        self.set_title("AuraDE Installer")
        self.set_default_size(980, 720)
        self.add_css_class("aurade")

        self._apply_theme()
        self._build_chrome()
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
        self._provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            display, self._provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._load_stylesheet()

    def _load_stylesheet(self) -> None:
        provider = getattr(self, "_provider", None)
        if provider is None:
            return
        try:
            provider.load_from_path(THEME_DARK_CSS if self.dark else THEME_CSS)
        except GLib.Error:
            # An unstyled installer is still an installer. Refusing to start
            # because a stylesheet is missing would trade a cosmetic failure
            # for the text-mode fallback.
            pass

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
        aurora = Aurora(self)
        self.widgets["aurora"] = aurora
        backdrop.set_child(aurora)

        frame = column(0)
        backdrop.add_overlay(frame)

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
        frame.append(actions)

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
        Adw.StyleManager.get_default().set_color_scheme(scheme)

    def start_aurora(self) -> None:
        if self._aurora_source or not self.animate:
            return
        self._aurora_source = GLib.timeout_add(
            AURORA_INTERVAL_MS, self.widgets["aurora"].advance)

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
            F.DONE, F.DONE_TITLE, F.DONE_BODY, "emblem-ok-symbolic"), F.DONE)
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
        return page_shell(box)

    def _build_page(self, page: F.Page) -> Gtk.Widget:
        box = column(20)
        box.append(label(page.title, "m3-headline-small"))
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
        expander.add_prefix(Gtk.Image.new_from_icon_name("drive-harddisk-symbolic"))
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
            notes.append(f"{chosen['filesystem']} has no factory snapshot, so "
                         "this install will have no rollback entry in the boot "
                         "menu.")
        if chosen.get("layout") == "alongside":
            notes.append("Installing alongside needs free space that is already "
                         "unallocated. The installer stops before writing "
                         "anything if there is not enough.")
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
    # five - the firmware mode and Secure Boot - are hard refusals in the
    # engine that used to surface at the erase gate, after every question had
    # been answered. Both need a restart to fix. Asking them first is the
    # entire reason this page exists.

    READINESS_GLYPHS = {
        "ok": "emblem-ok-symbolic",
        "warn": "dialog-warning-symbolic",
        "blocked": "dialog-error-symbolic",
    }

    def _build_readiness(self, box: Gtk.Box) -> None:
        verdict = row(18)
        verdict.add_css_class("aurade-verdict")
        verdict.add_css_class("aurade-transition")
        glyph = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
        glyph.set_pixel_size(38)
        glyph.set_valign(Gtk.Align.START)
        self.widgets["ready.glyph"] = glyph
        verdict.append(glyph)
        text = column(4)
        text.set_hexpand(True)
        headline = label("", "m3-headline-small")
        self.widgets["ready.headline"] = headline
        text.append(headline)
        body = label("", "m3-body-medium")
        self.widgets["ready.body"] = body
        text.append(body)
        verdict.append(text)
        self.widgets["ready.verdict"] = verdict
        box.append(verdict)

        # A flow box rather than a column: two findings side by side at this
        # width, one when the window is narrow, and no reflow logic here to
        # get wrong.
        checks = Gtk.FlowBox()
        checks.set_selection_mode(Gtk.SelectionMode.NONE)
        checks.set_max_children_per_line(2)
        checks.set_min_children_per_line(2)
        checks.set_homogeneous(True)
        checks.set_row_spacing(12)
        checks.set_column_spacing(12)
        self.widgets["ready.checks"] = checks
        box.append(checks)

        # AdwExpanderRow rather than GtkExpander: it keeps its contents in a
        # real list box, which is the containment every other row in this
        # installer relies on, and it wears the same card as the rest of the
        # page instead of being a bare triangle with a label next to it.
        group = Adw.PreferencesGroup()
        details = Adw.ExpanderRow(title=F.READINESS_DETAILS)
        detail_row = Adw.ActionRow()
        detail_row.set_subtitle_lines(0)
        detail_row.add_css_class("aurade-mono")
        self.widgets["ready.details"] = detail_row
        details.add_row(detail_row)
        group.add(details)
        box.append(group)

    def _check_card(self, check: dict) -> Gtk.Widget:
        state = check.get("state", "ok")
        card = row(12)
        card.add_css_class("aurade-check")
        card.add_css_class(f"aurade-check-{state}")
        card.add_css_class("aurade-transition")
        glyph = Gtk.Image.new_from_icon_name(
            self.READINESS_GLYPHS.get(state, "emblem-ok-symbolic"))
        glyph.set_valign(Gtk.Align.START)
        glyph.add_css_class(f"aurade-glyph-{state}")
        card.append(glyph)
        body = column(4)
        body.set_hexpand(True)
        title = label(check.get("title", ""), "m3-title-small", wrap=False)
        body.append(title)
        finding = label(check.get("finding", ""), "m3-body-small", css="dim-label")
        # A card is half the board wide, so it gets half a measure. Left at the
        # prose default every card asks for the full width and the grid becomes
        # a column.
        finding.set_max_width_chars(34)
        body.append(finding)
        action = check.get("action") or ""
        if action:
            what = label(action, "m3-label-medium", css="aurade-action")
            what.set_max_width_chars(34)
            what.set_margin_top(4)
            body.append(what)
        card.append(body)
        # The card is a finding, not a control. Saying so keeps it out of the
        # tab order, where five unfocusable stops sit between the page and the
        # button that leaves it.
        card.set_can_focus(False)
        return card

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
            {"ok": "ok", "attention": "warn", "blocked": "blocked"}.get(
                verdict, "warn"), "dialog-warning-symbolic"))

        flow = self.widgets["ready.checks"]
        while (existing := flow.get_first_child()) is not None:
            flow.remove(existing)
        for check in checks:
            flow.append(self._check_card(check))

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
        self.forward_button.set_sensitive(verdict != "blocked")
        self.banner.set_revealed(False)

    # -- network -----------------------------------------------------------

    def _build_network(self, box: Gtk.Box) -> None:
        status = Adw.PreferencesGroup()
        item = Adw.ActionRow(title="Checking this computer")
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
            "Packages are downloaded and verified before anything is written, "
            "so a connection that fails here costs nothing. Fix it now and "
            "nothing has been lost.",
            "m3-body-small", css="dim-label"))

    def _refresh_network(self) -> None:
        status = self.model.call("net-status")
        item = self.widgets["net.status"]
        if not status.get("available"):
            item.set_title("Network manager unavailable")
            item.set_subtitle(status.get("reason", ""))
            self.widgets["wifi.list"].set_visible(False)
            self.widgets["wifi.empty"].set_label(
                "Wi-Fi cannot be set up from this image. Connect a cable "
                "instead.")
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
            item.set_subtitle("Turn the radio on to see networks.")
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
            empty.set_label("No networks in range. Move closer to the router, "
                            "or connect a cable instead.")
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
            description=("Type here to check the layout before you set a "
                         "password. Nothing typed in this box is saved."))
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
        for disk in self.model.disks():
            item = Adw.ActionRow(title=disk["path"])
            item.add_css_class("aurade-mono")
            transport = (disk.get("transport") or "").upper()
            facts = [disk.get("model") or "unknown model", disk.get("size") or ""]
            if transport:
                facts.append(transport)
            subtitle = "   ".join(f for f in facts if f)
            serial = disk.get("serial") or ""
            if serial:
                subtitle += f"\nSerial {serial}"
            item.set_subtitle(subtitle)
            item.set_subtitle_lines(0)
            item.disk_path = disk["path"]
            item.add_prefix(Gtk.Image.new_from_icon_name(
                "media-removable-symbolic" if transport == "USB"
                else "drive-harddisk-symbolic"))
            if transport == "USB":
                removable = True
            listbox.append(item)
        warning = self.widgets["disk.warning"]
        warning.set_visible(removable)
        if removable:
            warning.set_label("A removable disk is listed. That is probably the "
                              "drive you started this installer from.")
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
        box.append(label("Check these before continuing. Select any line to "
                         "change it.", "m3-body-medium", css="dim-label"))
        group = Adw.PreferencesGroup()
        self.widgets["review.group"] = group
        box.append(group)
        assurance = row(8)
        assurance.append(Gtk.Image.new_from_icon_name("emblem-ok-symbolic"))
        assurance.append(label(F.REVIEW_ASSURANCE, "m3-label-large", wrap=False))
        assurance.add_css_class("aurade-stage-done")
        box.append(assurance)
        advanced = Gtk.Button(label="Advanced options")
        advanced.add_css_class("flat")
        advanced.set_halign(Gtk.Align.START)
        advanced.connect("clicked", lambda *_: self._on_review_row(None, "advanced"))
        box.append(advanced)
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

        prompt = Adw.PreferencesGroup()
        entry = Adw.EntryRow(title="Type the confirmation")
        entry.add_css_class("aurade-token-field")
        entry.connect("changed", lambda *_: self.refresh_gate_button())
        self.widgets["gate.entry"] = entry
        prompt.add(entry)
        box.append(prompt)
        hint = label("", "m3-body-small", css="aurade-mono")
        self.widgets["gate.hint"] = hint
        box.append(hint)
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
        for key in ("model", "serial", "size", "transport"):
            self.widgets[f"gate.{key}"].set_subtitle(info.get(key) or "unknown")
        self.widgets["gate.hint"].set_label(f"Type  {self._gate_token}")
        self.widgets["gate.entry"].set_text("")

    def refresh_gate_button(self) -> None:
        if self.flow.state != F.GATE:
            return
        typed = self.widgets["gate.entry"].get_text()
        self.forward_button.set_sensitive(typed == self._gate_token)

    # -- progress ----------------------------------------------------------

    def _build_progress(self):
        box = column(18)
        box.append(label(F.PROGRESS_TITLE, "m3-headline-small"))
        box.append(label(F.PROGRESS_FOOTER, "m3-body-medium", css="dim-label"))
        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        listbox.add_css_class("boxed-list")
        self.widgets["progress.list"] = listbox
        box.append(listbox)
        bar = Gtk.ProgressBar()
        bar.set_show_text(True)
        self.widgets["progress.bar"] = bar
        box.append(bar)
        state = label("", "m3-body-small")
        self.widgets["progress.state"] = state
        box.append(state)
        return page_shell(box)

    def _draw_progress(self, report: dict) -> None:
        listbox = self.widgets["progress.list"]
        pct, detail = 0, ""
        for stage in report.get("stages", []):
            name = stage["stage"]
            item = self.stage_rows.get(name)
            if item is None:
                item = Adw.ActionRow(title=stage["label"])
                icon = Gtk.Image.new_from_icon_name("content-loading-symbolic")
                item.add_prefix(icon)
                item.stage_icon = icon
                item.add_css_class("aurade-transition")
                listbox.append(item)
                self.stage_rows[name] = item
            status = stage.get("status", "pending")
            elapsed = stage.get("elapsed") or ""
            item.set_subtitle(elapsed)
            if elapsed:
                item.add_css_class("aurade-mono")
            item.stage_icon.set_from_icon_name({
                "ok": "emblem-ok-symbolic",
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
        bar = self.widgets["progress.bar"]
        bar.set_fraction(max(0.0, min(1.0, pct / 100.0)))
        bar.set_text(detail or report.get("position", ""))

        # The stop control exists only while the shared reversibility boundary
        # says nothing has been written, and it is removed rather than
        # disabled at the boundary: a greyed-out Stop invites the user to keep
        # pressing it at the exact moment the answer has become no.
        state = self.widgets["progress.state"]
        if report.get("can_stop"):
            self.secondary_button.set_label("Stop")
            self.secondary_button.set_visible(True)
            state.set_label("Nothing has been written to the disk yet.")
            state.remove_css_class("warning")
            state.add_css_class("aurade-stage-done")
        else:
            self.secondary_button.set_visible(False)
            state.set_label(F.PROGRESS_UNINTERRUPTIBLE if report.get("running") else "")
            state.remove_css_class("aurade-stage-done")
            state.add_css_class("warning")
        state.set_visible(bool(state.get_label()))

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
            body=("Nothing has been written to the disk yet, so stopping now "
                  "leaves this computer exactly as it was. You can start "
                  "again from the beginning."))
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
        box.append(image)
        heading = label(title, "m3-headline-large", center=True)
        heading.set_margin_bottom(12)
        box.append(heading)
        box.append(label(body, "m3-body-large", center=True))
        extra = label("", "m3-body-medium", center=True, css="dim-label")
        extra.set_margin_top(16)
        extra.set_visible(False)
        self.widgets[f"{name}.extra"] = extra
        box.append(extra)
        return page_shell(box)

    def _build_failure(self):
        box = column(16)
        headline = label("", "m3-headline-small")
        self.widgets["failure.headline"] = headline
        box.append(headline)
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
        stage = report.get("label") or ""
        self.widgets["failure.headline"].set_label(
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

    # -- rendering ---------------------------------------------------------

    def refresh(self) -> None:
        state = self.flow.state
        name = f"page:{self.flow.current_page}" if state == "pages" else state
        self.stack.set_visible_child_name(name)
        self.step_label.set_label(self.flow.step_position())

        if state == "pages":
            self._refresh_page(F.PAGES_BY_NAME[self.flow.current_page])
        else:
            self._refresh_state(state)

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
            self.forward_button.set_sensitive(True)

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
        elif state == F.FAILURE:
            self._refresh_failure()

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
    def _on_first_map(_window: Gtk.Widget) -> None:
        """A window reached the screen: this renderer works."""
        S.report(S.MAPPED)


def run(model: Bridge, plan_only: bool = False) -> int:
    Adw.init()
    return InstallerApplication(model, plan_only).run([])
