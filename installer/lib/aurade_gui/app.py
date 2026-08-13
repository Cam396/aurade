"""The GTK4/libadwaita widget layer.

The only module here that imports ``gi``. Everything it draws is either a
string from :mod:`aurade_gui.flow` or an answer from the model process, so
this file can be read as a layout and nothing in it decides what the
installer does.

Keyboard first, throughout. Every page has a default action bound to Return
and a back action bound to Escape, both labelled with what they actually do;
focus is placed on the first control of each page as it appears; the disk
list, the stage list and every option row are reachable with Tab and operable
with the arrow keys and Space. A user who never touches a pointing device
must be able to complete an install, because a graphical installer that
requires a mouse is a graphical installer that excludes people.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from . import flow as F  # noqa: E402
from .bridge import Bridge, BridgeError  # noqa: E402

APP_ID = "org.aurade.Installer"

#: How often the progress page re-reads the journal. The journal is the only
#: account of what happened; this is a view of it and keeps no tally.
PROGRESS_INTERVAL_MS = 400


def _wrapped(text: str, css: str | None = None, center: bool = False) -> Gtk.Label:
    label = Gtk.Label(label=text)
    label.set_wrap(True)
    label.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
    label.set_xalign(0.5 if center else 0.0)
    label.set_justify(Gtk.Justification.CENTER if center else Gtk.Justification.LEFT)
    label.set_max_width_chars(64)
    if css:
        label.add_css_class(css)
    return label


def _page_box() -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
    box.set_margin_top(24)
    box.set_margin_bottom(24)
    box.set_margin_start(24)
    box.set_margin_end(24)
    return box


def _clamp(child: Gtk.Widget) -> Adw.Clamp:
    clamp = Adw.Clamp(maximum_size=680, tightening_threshold=560)
    clamp.set_child(child)
    clamp.set_vexpand(True)
    return clamp


class InstallerWindow(Adw.ApplicationWindow):
    """The whole installer, as one window with a stack of pages."""

    def __init__(self, application: Adw.Application, model: Bridge, plan_only: bool):
        super().__init__(application=application)
        self.model = model
        self.flow = F.Flow(plan_only=plan_only)
        self.manifest: dict = {}
        self.widgets: dict[str, Gtk.Widget] = {}
        self.group_rows: dict[str, list[Gtk.Widget]] = {}
        self.stage_rows: dict[str, Adw.ActionRow] = {}
        self.secrets_set: set[str] = set()
        self.enum_values: dict[str, list[str]] = {}
        self.probe: dict = {}
        self.install_status = 0
        self._progress_source = 0
        self._gate_token = ""
        self._export_notice: tuple[str, bool] | None = None

        self.set_title("AuraDE Installer")
        self.set_default_size(940, 680)

        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        toolbar = Adw.ToolbarView()
        self.toast_overlay.set_child(toolbar)

        self.header = Adw.HeaderBar()
        self.header.set_show_end_title_buttons(False)
        self.header.set_show_start_title_buttons(False)
        self.back_button = Gtk.Button(label="Quit")
        self.back_button.connect("clicked", lambda *_: self.on_back())
        self.header.pack_start(self.back_button)

        self.forward_button = Gtk.Button(label="Get started")
        self.forward_button.add_css_class("suggested-action")
        self.forward_button.connect("clicked", lambda *_: self.on_forward())
        self.header.pack_end(self.forward_button)

        self.title_widget = Adw.WindowTitle(title="AuraDE Installer", subtitle="")
        self.header.set_title_widget(self.title_widget)
        toolbar.add_top_bar(self.header)

        self.banner = Adw.Banner()
        self.banner.set_revealed(False)
        toolbar.add_top_bar(self.banner)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_vexpand(True)
        toolbar.set_content(self.stack)

        self._build_pages()
        self._install_shortcuts()
        self.refresh()

    # -- construction ------------------------------------------------------

    def _build_pages(self) -> None:
        self.manifest = self.model.manifest()
        self.stack.add_named(self._build_welcome(), F.WELCOME)
        for page in F.PAGES:
            self.stack.add_named(self._build_page(page), f"page:{page.name}")
        self.stack.add_named(self._build_review(), F.REVIEW)
        self.stack.add_named(self._build_gate(), F.GATE)
        self.stack.add_named(self._build_progress(), F.PROGRESS)
        self.stack.add_named(self._build_done(), F.DONE)
        self.stack.add_named(self._build_failure(), F.FAILURE)
        self.stack.add_named(self._build_cancelled(), F.CANCELLED)
        self.stack.add_named(self._build_planned(), F.PLANNED)

    def _build_welcome(self) -> Gtk.Widget:
        status = Adw.StatusPage(title=F.WELCOME_TITLE, description=F.WELCOME_BODY)
        status.set_icon_name("drive-harddisk-symbolic")
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        body.set_halign(Gtk.Align.CENTER)
        assurance = _wrapped(F.WELCOME_ASSURANCE, css="dim-label", center=True)
        body.append(assurance)
        status.set_child(body)
        return status

    def _build_page(self, page: F.Page) -> Gtk.Widget:
        box = _page_box()
        box.append(_wrapped(page.subtitle, css="dim-label"))
        if page.name == "graphics":
            self.widgets["graphics.group"] = self._build_graphics(box)
        elif page.name == "network":
            self.widgets["network.group"] = self._build_network(box)
        else:
            # One group per question, with the question's own help as the
            # group description. libadwaita draws that as a caption above the
            # row, which is where a person looks for it - and it keeps the
            # help out of the boxed list, where a plain label would break the
            # rounded-list styling every other row relies on.
            for question in page.questions:
                spec = self.manifest["questions"].get(question)
                if spec is None:
                    continue
                group = Adw.PreferencesGroup(description=spec["help"])
                for row in self._build_question_rows(question, spec):
                    group.add(row)
                self.widgets[f"group.{question}"] = group
                box.append(group)
            if page.name == "disk":
                box.append(self._build_disk_list())
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(_clamp(box))
        return scroller

    def _build_graphics(self, box: Gtk.Box) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Graphics")
        self.widgets["graphics.summary"] = Adw.ActionRow(title="Renderer")
        self.widgets["graphics.detail"] = Adw.ActionRow(title="Detected")
        self.widgets["graphics.memory"] = Adw.ActionRow(title="Memory")
        for key in ("graphics.summary", "graphics.detail", "graphics.memory"):
            row = self.widgets[key]
            row.set_subtitle("")
            row.set_subtitle_lines(0)
            group.add(row)
        box.append(group)
        advice = _wrapped("")
        advice.set_visible(False)
        self.widgets["graphics.advice"] = advice
        box.append(advice)
        return group

    def _build_network(self, box: Gtk.Box) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Network and clock")
        self.widgets["network.list"] = group
        box.append(group)
        note = _wrapped(
            "The installer downloads and verifies every package before it "
            "touches the disk. If this check fails, nothing has been lost - "
            "fix the connection and start again.",
            css="dim-label",
        )
        box.append(note)
        return group

    def _build_question_rows(self, question: str, spec: dict) -> list[Gtk.Widget]:
        """The row or rows one manifest question is asked with."""
        kind = spec["type"]
        if kind == "secret":
            # Typed twice, because a masked field that was mistyped once is
            # discovered at the sign-in screen of a machine already installed.
            entry = Adw.PasswordEntryRow(title=spec["label"])
            repeat = Adw.PasswordEntryRow(title="Type it again")
            self.widgets[f"q.{question}"] = entry
            self.widgets[f"q.{question}.repeat"] = repeat
            return [entry, repeat]
        if kind == "bool":
            row = Adw.SwitchRow(title=spec["label"])
            row.set_active(spec["default"] == "yes")
            row.connect("notify::active", self._on_bool_changed, question)
            self.widgets[f"q.{question}"] = row
            return [row]
        if kind == "enum":
            # The candidate list comes from the same directories the validator
            # reads, so a value that appears here always validates.
            values = self.model.enum(question)
            self.enum_values[question] = values
            row = Adw.ComboRow(
                title=spec["label"],
                model=Gtk.StringList.new(values or [spec["default"]]),
            )
            row.set_enable_search(True)
            if spec["default"] in values:
                row.set_selected(values.index(spec["default"]))
            self.widgets[f"q.{question}"] = row
            return [row]
        if kind == "disk":
            row = Adw.ActionRow(title=spec["label"])
            self.widgets[f"q.{question}"] = row
            return [row]
        row = Adw.EntryRow(title=spec["label"])
        row.set_text(spec["default"])
        row.set_show_apply_button(False)
        self.widgets[f"q.{question}"] = row
        return [row]

    def _build_disk_list(self) -> Gtk.Widget:
        group = Adw.PreferencesGroup(title="Disks in this computer")
        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        listbox.add_css_class("boxed-list")
        listbox.connect("row-selected", self._on_disk_selected)
        self.widgets["disk.list"] = listbox
        group.add(listbox)
        self.widgets["disk.warning"] = _wrapped("", css="warning")
        self.widgets["disk.warning"].set_visible(False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.append(group)
        box.append(self.widgets["disk.warning"])
        return box

    def _build_review(self) -> Gtk.Widget:
        box = _page_box()
        box.append(_wrapped("Check these before continuing.", css="dim-label"))
        group = Adw.PreferencesGroup()
        self.widgets["review.group"] = group
        box.append(group)
        assurance = _wrapped(F.REVIEW_ASSURANCE, css="success")
        box.append(assurance)
        advanced = Gtk.Button(label="Advanced options")
        advanced.set_halign(Gtk.Align.START)
        advanced.connect("clicked", lambda *_: self.on_advanced())
        self.widgets["review.advanced"] = advanced
        box.append(advanced)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(_clamp(box))
        return scroller

    def _build_gate(self) -> Gtk.Widget:
        box = _page_box()
        headline = _wrapped("", css="error")
        headline.add_css_class("title-2")
        self.widgets["gate.headline"] = headline
        box.append(headline)
        group = Adw.PreferencesGroup(title="The disk that will be erased")
        for key, title in (
            ("model", "Model"),
            ("serial", "Serial"),
            ("size", "Size"),
            ("transport", "Connection"),
        ):
            row = Adw.ActionRow(title=title)
            row.set_subtitle("")
            self.widgets[f"gate.{key}"] = row
            group.add(row)
        box.append(group)
        box.append(_wrapped(F.GATE_BODY))
        prompt = Adw.PreferencesGroup()
        entry = Adw.EntryRow(title="Type the confirmation exactly")
        entry.connect("changed", lambda *_: self.refresh_gate_button())
        self.widgets["gate.entry"] = entry
        prompt.add(entry)
        box.append(prompt)
        hint = _wrapped("", css="dim-label")
        self.widgets["gate.hint"] = hint
        box.append(hint)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(_clamp(box))
        return scroller

    def _build_progress(self) -> Gtk.Widget:
        box = _page_box()
        box.append(_wrapped(F.PROGRESS_FOOTER, css="dim-label"))
        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        listbox.add_css_class("boxed-list")
        self.widgets["progress.list"] = listbox
        box.append(listbox)
        bar = Gtk.ProgressBar()
        bar.set_show_text(True)
        self.widgets["progress.bar"] = bar
        box.append(bar)
        note = _wrapped("", css="dim-label")
        self.widgets["progress.note"] = note
        box.append(note)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(_clamp(box))
        return scroller

    def _build_done(self) -> Gtk.Widget:
        status = Adw.StatusPage(title=F.DONE_TITLE, description=F.DONE_BODY)
        status.set_icon_name("emblem-ok-symbolic")
        extra = _wrapped("", css="dim-label", center=True)
        extra.set_visible(False)
        self.widgets["done.extra"] = extra
        status.set_child(extra)
        return status

    def _build_failure(self) -> Gtk.Widget:
        box = _page_box()
        headline = _wrapped("", css="error")
        headline.add_css_class("title-2")
        self.widgets["failure.headline"] = headline
        box.append(headline)
        for key in ("cause", "explanation", "detail", "advice"):
            label = _wrapped("")
            label.set_visible(False)
            if key == "advice":
                label.add_css_class("warning")
            if key == "detail":
                label.add_css_class("monospace")
                label.add_css_class("dim-label")
            self.widgets[f"failure.{key}"] = label
            box.append(label)
        notice = _wrapped("")
        notice.set_visible(False)
        self.widgets["failure.notice"] = notice
        box.append(notice)
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        for key, label in F.FAILURE_ACTIONS:
            button = Gtk.Button(label=label)
            button.connect("clicked", self._on_failure_action, key)
            self.widgets[f"failure.action.{key}"] = button
            actions.append(button)
        box.append(actions)
        log_hint = _wrapped("", css="dim-label")
        self.widgets["failure.loghint"] = log_hint
        box.append(log_hint)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(_clamp(box))
        return scroller

    def _build_cancelled(self) -> Gtk.Widget:
        status = Adw.StatusPage(title=F.CANCELLED_TITLE, description=F.CANCELLED_BODY)
        status.set_icon_name("process-stop-symbolic")
        return status

    def _build_planned(self) -> Gtk.Widget:
        status = Adw.StatusPage(title=F.PLANNED_TITLE, description=F.PLANNED_BODY)
        status.set_icon_name("document-properties-symbolic")
        return status

    # -- keyboard ----------------------------------------------------------

    def _install_shortcuts(self) -> None:
        controller = Gtk.ShortcutController()
        controller.set_scope(Gtk.ShortcutScope.GLOBAL)
        controller.add_shortcut(
            Gtk.Shortcut(
                trigger=Gtk.ShortcutTrigger.parse_string("Escape"),
                action=Gtk.CallbackAction.new(lambda *_: self.on_back() or True),
            )
        )
        controller.add_shortcut(
            Gtk.Shortcut(
                trigger=Gtk.ShortcutTrigger.parse_string("<alt>Right"),
                action=Gtk.CallbackAction.new(lambda *_: self.on_forward() or True),
            )
        )
        controller.add_shortcut(
            Gtk.Shortcut(
                trigger=Gtk.ShortcutTrigger.parse_string("<alt>Left"),
                action=Gtk.CallbackAction.new(lambda *_: self.on_back() or True),
            )
        )
        self.add_controller(controller)
        self.set_default_widget(self.forward_button)

    # -- rendering ---------------------------------------------------------

    def refresh(self) -> None:
        state = self.flow.state
        name = f"page:{self.flow.current_page}" if state == "pages" else state
        self.stack.set_visible_child_name(name)

        if state == "pages":
            page = F.PAGES_BY_NAME[self.flow.current_page]
            self.title_widget.set_title(page.title)
            self.title_widget.set_subtitle(self.flow.step_position())
            self._refresh_page(page)
        else:
            self.title_widget.set_title(self._title_for(state))
            self.title_widget.set_subtitle("")
            self._refresh_state(state)

        back = self.flow.back_label()
        self.back_button.set_visible(bool(back))
        self.back_button.set_label(back or "")
        forward = self.flow.forward_label()
        self.forward_button.set_visible(bool(forward))
        self.forward_button.set_label(forward or "")
        if state == F.GATE:
            self.forward_button.add_css_class("destructive-action")
            self.forward_button.remove_css_class("suggested-action")
            self.refresh_gate_button()
        else:
            self.forward_button.remove_css_class("destructive-action")
            self.forward_button.add_css_class("suggested-action")
            self.forward_button.set_sensitive(True)
        GLib.idle_add(self._focus_first)

    def _title_for(self, state: str) -> str:
        return {
            F.WELCOME: F.WELCOME_TITLE,
            F.REVIEW: F.REVIEW_TITLE,
            F.GATE: F.GATE_TITLE,
            F.PROGRESS: F.PROGRESS_TITLE,
            F.DONE: F.DONE_TITLE,
            F.FAILURE: F.FAILURE_TITLE,
            F.CANCELLED: F.CANCELLED_TITLE,
            F.PLANNED: F.PLANNED_TITLE,
        }.get(state, "AuraDE Installer")

    def _focus_first(self) -> bool:
        state = self.flow.state
        candidate: Gtk.Widget | None = None
        if state == "pages":
            page = F.PAGES_BY_NAME[self.flow.current_page]
            if page.name == "disk":
                candidate = self.widgets.get("disk.list")
            else:
                for question in page.questions:
                    candidate = self.widgets.get(f"q.{question}")
                    # is_visible, not get_visible: a row inside a hidden group
                    # still reports its own visibility as true, and focusing
                    # one puts the cursor somewhere nothing is drawn.
                    if candidate is not None and candidate.is_visible():
                        break
                    candidate = None
        elif state == F.GATE:
            candidate = self.widgets.get("gate.entry")
        if candidate is None:
            candidate = self.forward_button
        candidate.grab_focus()
        return GLib.SOURCE_REMOVE

    def _refresh_page(self, page: F.Page) -> None:
        if page.name == "graphics":
            self._refresh_graphics()
        elif page.name == "network":
            self._refresh_network()
        elif page.name == "disk":
            self._refresh_disks()
        elif page.name == "encryption":
            self._refresh_encryption()

    def _refresh_graphics(self) -> None:
        self.probe = self.model.probe()
        renderer = self.probe.get("renderer", "")
        summary = (
            "Graphical installer"
            if renderer == "gui"
            else "Text installer recommended"
        )
        self.widgets["graphics.summary"].set_subtitle(summary)
        self.widgets["graphics.detail"].set_subtitle(self.probe.get("graphics", ""))
        self.widgets["graphics.memory"].set_subtitle(self.probe.get("memory", ""))
        advice = self.widgets["graphics.advice"]
        advice.set_text(self.probe.get("advice", ""))
        advice.set_visible(bool(self.probe.get("advice")))
        # The black-screen warning is the reason this page exists, and it is
        # shown before the erase gate rather than after it.
        if self.probe.get("predicts_black_screen"):
            self.banner.set_title(
                "This computer has no working graphics driver. Installing now "
                "produces a system that starts but shows no desktop."
            )
            self.banner.set_revealed(True)
        else:
            self.banner.set_revealed(False)

    def _refresh_network(self) -> None:
        group = self.widgets["network.list"]
        self._clear_group("network", group)
        report = self.model.network()
        if not report.get("available", True):
            row = Adw.ActionRow(title="The network check is not available")
            row.set_subtitle(
                "The installer will still verify every package before writing."
            )
            row.set_title_lines(0)
            self._add_row("network", group, row)
            return
        for issue in report.get("issues", []):
            row = Adw.ActionRow(title=issue)
            row.set_title_lines(0)
            row.add_prefix(Gtk.Image.new_from_icon_name("dialog-warning-symbolic"))
            self._add_row("network", group, row)
        for note in report.get("notes", []):
            row = Adw.ActionRow(title=note)
            row.set_title_lines(0)
            row.add_prefix(Gtk.Image.new_from_icon_name("emblem-ok-symbolic"))
            self._add_row("network", group, row)
        if not report.get("ok", True):
            self.banner.set_title(
                "The network check found a problem. Fixing it now is much "
                "cheaper than a download failing later."
            )
            self.banner.set_revealed(True)
        else:
            self.banner.set_revealed(False)

    def _clear_group(self, key: str, group: Adw.PreferencesGroup) -> None:
        """Empty a group this window filled, using its own record of what it put
        there rather than by walking widgets it does not own."""
        for row in self.group_rows.get(key, []):
            group.remove(row)
        self.group_rows[key] = []

    def _add_row(self, key: str, group: Adw.PreferencesGroup, row: Gtk.Widget) -> None:
        group.add(row)
        self.group_rows.setdefault(key, []).append(row)

    def _refresh_disks(self) -> None:
        listbox = self.widgets["disk.list"]
        while (row := listbox.get_first_child()) is not None:
            listbox.remove(row)
        removable = False
        for disk in self.model.disks():
            row = Adw.ActionRow(title=disk["path"])
            subtitle = " - ".join(
                part
                for part in (
                    disk.get("model") or "unknown model",
                    disk.get("size") or "",
                    disk.get("transport") or "",
                )
                if part
            )
            serial = disk.get("serial") or ""
            if serial:
                subtitle += f"\nSerial {serial}"
            row.set_subtitle(subtitle)
            row.set_subtitle_lines(0)
            row.disk_path = disk["path"]
            if (disk.get("transport") or "").lower() == "usb":
                removable = True
                row.add_suffix(Gtk.Image.new_from_icon_name("media-removable-symbolic"))
            listbox.append(row)
        warning = self.widgets["disk.warning"]
        warning.set_visible(removable)
        if removable:
            warning.set_text(
                "A removable disk is listed. That is probably the drive you "
                "started this installer from."
            )
        chosen = self.model.get("target")
        if chosen:
            for row in self._listbox_rows(listbox):
                if getattr(row, "disk_path", None) == chosen:
                    listbox.select_row(row)
                    break

    @staticmethod
    def _listbox_rows(listbox: Gtk.ListBox):
        row = listbox.get_first_child()
        while row is not None:
            yield row
            row = row.get_next_sibling()

    def _refresh_encryption(self) -> None:
        # The passphrase question exists only when encryption was chosen, and
        # that rule comes from the model, not from a copy of it kept here.
        group = self.widgets.get("group.luks_passphrase")
        if group is not None:
            group.set_visible("luks_passphrase" in set(self.model.visible()))

    def _refresh_review(self) -> None:
        group = self.widgets["review.group"]
        self._clear_group("review", group)
        # Secrets arrive here as the word `set`. There is no command that
        # returns one, so this screen cannot show a password even by mistake.
        for entry in self.model.answers().values():
            row = Adw.ActionRow(title=entry["short"], subtitle=entry["value"])
            row.set_subtitle_lines(0)
            if entry.get("advanced"):
                row.add_css_class("dim-label")
            self._add_row("review", group, row)

    def _refresh_gate(self) -> None:
        info = self.model.target()
        if not info.get("ok"):
            self._toast(info.get("error", "No disk has been chosen."))
            self.flow.back()
            self.refresh()
            return
        self._gate_token = info["token"]
        self.widgets["gate.headline"].set_text(
            f"This erases {info['path']} completely."
        )
        for key in ("model", "serial", "size", "transport"):
            self.widgets[f"gate.{key}"].set_subtitle(info.get(key) or "unknown")
        self.widgets["gate.hint"].set_text(f"Type {self._gate_token} to continue.")
        self.widgets["gate.entry"].set_text("")

    def refresh_gate_button(self) -> None:
        if self.flow.state != F.GATE:
            return
        typed = self.widgets["gate.entry"].get_text()
        self.forward_button.set_sensitive(typed == self._gate_token)

    def _refresh_state(self, state: str) -> None:
        if state == F.REVIEW:
            self._refresh_review()
        elif state == F.GATE:
            self._refresh_gate()
        elif state == F.DONE:
            encrypted = self.model.get("encrypt") == "yes"
            extra = self.widgets["done.extra"]
            extra.set_text(F.DONE_ENCRYPTED if encrypted else "")
            extra.set_visible(encrypted)
        elif state == F.FAILURE:
            self._refresh_failure()

    def _refresh_failure(self) -> None:
        report = self.model.failure()
        label = report.get("label") or ""
        self.widgets["failure.headline"].set_text(
            f"{label} did not finish." if label else "The installation stopped."
        )
        for key, text in (
            ("cause", report.get("cause_text", "")),
            ("explanation", report.get("explanation", "")),
            ("detail", report.get("detail", "")),
            ("advice", report.get("restart_advice", "")),
        ):
            widget = self.widgets[f"failure.{key}"]
            widget.set_text(text)
            widget.set_visible(bool(text))
        self.widgets["failure.loghint"].set_text(
            f"The full log is at {report.get('raw_log', '')}."
        )
        notice = self.widgets["failure.notice"]
        if self._export_notice is None:
            notice.set_visible(False)
        else:
            text, ok = self._export_notice
            notice.set_text(text)
            notice.remove_css_class("error")
            notice.remove_css_class("success")
            notice.add_css_class("success" if ok else "error")
            notice.set_visible(True)
        self.banner.set_revealed(False)

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
            if question in self.manifest.get("advanced", []) and not self.flow.show_advanced:
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
        # The renderer's copy goes now. The model holds it in its own memory
        # until it hashes it, then in a mode-0600 file, and there is no
        # command that reads either back.
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
            group.set_description(
                f"{spec['help']} Leave both fields blank to keep what you "
                "already entered."
            )
        return True

    def _value_of(self, question: str, spec: dict) -> str:
        widget = self.widgets.get(f"q.{question}")
        if widget is None:
            return spec["default"]
        if spec["type"] == "bool":
            return "yes" if widget.get_active() else "no"
        if spec["type"] == "enum":
            values = self.enum_values.get(question, [])
            index = widget.get_selected()
            if 0 <= index < len(values):
                return values[index]
            return spec["default"]
        if spec["type"] == "disk":
            return self.model.get("target")
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

    def _toast(self, message: str) -> None:
        if not message:
            return
        toast = Adw.Toast(title=message)
        toast.set_timeout(6)
        self.toast_overlay.add_toast(toast)

    # -- actions -----------------------------------------------------------

    def _on_bool_changed(self, row: Adw.SwitchRow, _param, question: str) -> None:
        self.model.set(question, "yes" if row.get_active() else "no")
        if question == "encrypt":
            self._refresh_encryption()

    def _on_disk_selected(self, _listbox: Gtk.ListBox, row) -> None:
        if row is None:
            return
        path = getattr(row, "disk_path", "")
        ok, error = self.model.set("target", path)
        if not ok:
            self._toast(error or "That disk cannot be installed to.")

    def on_forward(self) -> None:
        state = self.flow.state
        try:
            if state == "pages":
                page = F.PAGES_BY_NAME[self.flow.current_page]
                if not self._collect_page(page):
                    return
                if self.flow.forward() == F.REVIEW:
                    self.refresh()
                    return
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

    def on_back(self) -> None:
        action = self.flow.back_action()
        if action == "quit":
            self._confirm_quit()
            return
        if not action:
            return
        self.flow.back()
        self.refresh()

    def on_advanced(self) -> None:
        self.flow.set_show_advanced(True)
        self.flow.state = "pages"
        self.flow.page_index = self.flow.pages.index("advanced")
        self.refresh()

    def _confirm_quit(self) -> None:
        dialog = Adw.AlertDialog(
            heading="Quit the installer?",
            body=(
                "Nothing has been written to any disk. This computer will be "
                "left exactly as it is now."
            ),
        )
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
        self.title_widget.set_subtitle("Checking the plan")
        try:
            result = self.model.plan()
        except BridgeError as exc:
            self._fatal(str(exc))
            return
        finally:
            self.forward_button.set_sensitive(True)
        if not result.get("ok"):
            self.install_status = int(result.get("status", 1))
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
            PROGRESS_INTERVAL_MS, self._poll_progress
        )

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
        except BridgeError as exc:
            self._fatal(str(exc))
            return GLib.SOURCE_REMOVE
        self.install_status = int(result.get("status", 1))
        self.flow.finished(self.install_status)
        self.refresh()
        return GLib.SOURCE_REMOVE

    def _draw_progress(self, report: dict) -> None:
        listbox = self.widgets["progress.list"]
        rows = self.stage_rows
        active_pct = 0
        active_detail = ""
        for stage in report.get("stages", []):
            name = stage["stage"]
            row = rows.get(name)
            if row is None:
                row = Adw.ActionRow(title=stage["label"])
                icon = Gtk.Image.new_from_icon_name("content-loading-symbolic")
                row.add_prefix(icon)
                row.stage_icon = icon
                listbox.append(row)
                rows[name] = row
            status = stage.get("status", "pending")
            row.set_subtitle(stage.get("elapsed") or "")
            row.stage_icon.set_from_icon_name(
                {
                    "ok": "emblem-ok-symbolic",
                    "running": "media-playback-start-symbolic",
                    "failed": "dialog-error-symbolic",
                }.get(status, "content-loading-symbolic")
            )
            for css in ("success", "error", "dim-label"):
                row.remove_css_class(css)
            row.add_css_class(
                {"ok": "success", "failed": "error"}.get(status, "dim-label")
            )
            if status == "running":
                active_pct = int(stage.get("pct", 0))
                active_detail = stage.get("detail", "")
        bar = self.widgets["progress.bar"]
        bar.set_fraction(max(0.0, min(1.0, active_pct / 100.0)))
        bar.set_text(active_detail or report.get("position", ""))
        note = self.widgets["progress.note"]
        if not report.get("interruptible", True):
            note.set_text(F.PROGRESS_UNINTERRUPTIBLE)
            note.set_visible(True)
        else:
            note.set_visible(False)
        # No cancel control is drawn on this page at all. Offering one after
        # the erase gate would advertise an exit that does not exist.

    def _on_failure_action(self, _button: Gtk.Button, key: str) -> None:
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
            return
        if key == "log":
            self._show_log()
            return
        if key == "reboot":
            Gio.Subprocess.new(
                ["systemctl", "reboot"], Gio.SubprocessFlags.NONE
            )

    def _show_log(self) -> None:
        report = self.model.failure()
        path = report.get("raw_log", "")
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
        scroller.set_size_request(760, 480)
        dialog = Adw.Dialog()
        dialog.set_title("Installer log")
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        toolbar.set_content(scroller)
        dialog.set_child(toolbar)
        dialog.present(self)

    def _fatal(self, message: str) -> None:
        dialog = Adw.AlertDialog(
            heading="The installer stopped responding",
            body=(
                f"{message}\n\nNothing further will be written. Restart this "
                "computer and start the installer again, or use the text "
                "installer."
            ),
        )
        dialog.add_response("close", "Close")
        dialog.set_default_response("close")
        dialog.connect("response", lambda *_: self.close())
        dialog.present(self)


class InstallerApplication(Adw.Application):
    def __init__(self, model: Bridge, plan_only: bool):
        super().__init__(
            application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE
        )
        self.model = model
        self.plan_only = plan_only
        self.window: InstallerWindow | None = None

    def do_activate(self) -> None:  # noqa: N802  (GObject naming)
        if self.window is None:
            self.window = InstallerWindow(self, self.model, self.plan_only)
        self.window.present()


def run(model: Bridge, plan_only: bool = False) -> int:
    Adw.init()
    return InstallerApplication(model, plan_only).run([])
