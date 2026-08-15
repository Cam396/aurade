"""The window, built for real, and asked about itself.

Every other test of the graphical installer reads its source. That is enough
for the flow, the model protocol and the palette, and it was not enough for
the widget tree: the enum pickers were assembled correctly, referenced
correctly, styled correctly, and did not open when clicked.

The cause was a containment rule that no amount of reading the file makes
visible. `AdwPreferencesGroup.add` puts an `AdwPreferencesRow` into its
internal `GtkListBox`, and puts anything else into a plain box beside it. An
`AdwComboRow` is a `GtkListBoxRow`; a `GtkListBoxRow` with no `GtkListBox`
above it is never activated, because activation is something the list box
does to its rows. Wrapping a combo row in a box to hang a caption under it
therefore produced a picker that looked right and was dead.

So this builds the real window against fixtures and interrogates the widget
tree. It needs a compositor, and a headless one is enough - the shell script
beside this file starts weston and skips if it cannot.
"""

from __future__ import annotations

import os
import sys

TESTS = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.normpath(os.path.join(TESTS, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "installer", "lib"))

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from aurade_gui import flow as F  # noqa: E402
from aurade_gui.app import InstallerWindow  # noqa: E402
from aurade_gui.bridge import Bridge, find_bridge  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def pump(count: int = 12) -> None:
    context = GLib.MainContext.default()
    for _ in range(count):
        while context.pending():
            context.iteration(False)


def walk(widget: Gtk.Widget):
    yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from walk(child)
        child = child.get_next_sibling()


def run(window: InstallerWindow) -> None:
    # -- every page can be reached and drawn -------------------------------
    #
    # A page that raises on refresh takes the whole installer down, and the
    # only renderer left is the text one. Visiting all of them here is cheap.
    for name in F.PAGE_ORDER:
        window.flow.state = "pages"
        window.flow.jump_to_page(name)
        try:
            window.refresh()
            pump()
        except Exception as exc:  # noqa: BLE001 - the point is to catch any
            FAILURES.append(f"page {name} raised on refresh: {exc!r}")

    for state in (F.WELCOME, F.REVIEW, F.GATE, F.PROGRESS, F.DONE, F.FAILURE,
                  F.STOPPED, F.CANCELLED, F.PLANNED):
        window.flow.state = state
        try:
            window.refresh()
            pump()
        except Exception as exc:  # noqa: BLE001
            FAILURES.append(f"state {state} raised on refresh: {exc!r}")

    rows = [w for w in walk(window) if isinstance(w, Adw.PreferencesRow)]
    check(len(rows) > 6, f"only {len(rows)} preference rows were built")

    # -- the containment rule ----------------------------------------------
    #
    # This is the assertion the original bug needed. Every row that libadwaita
    # expects a list box to drive has to actually be in one.
    for item in rows:
        parent = item.get_parent()
        check(
            isinstance(parent, Gtk.ListBox),
            f"{type(item).__name__} titled {item.get_title()!r} has a "
            f"{type(parent).__name__} for a parent, not a GtkListBox; "
            "libadwaita will never activate it",
        )

    combos = [w for w in walk(window) if isinstance(w, Adw.ComboRow)]
    check(len(combos) >= 7,
          f"expected the locale, keymap, timezone and four storage pickers, "
          f"found {len(combos)}")
    for combo in combos:
        model = combo.get_model()
        check(model is not None and model.get_n_items() > 0,
              f"the {combo.get_title()!r} picker has an empty model")
        # Search without an expression is search with nothing to compare
        # against, which libadwaita reports as a warning and a dead entry.
        if combo.get_enable_search():
            check(combo.get_expression() is not None,
                  f"the {combo.get_title()!r} picker enables search with no "
                  "expression to search on")

    # -- the readiness page ------------------------------------------------
    window.flow.state = "pages"
    window.flow.jump_to_page("readiness")
    window.refresh()
    pump()
    flow_box = window.widgets.get("ready.checks")
    check(flow_box is not None, "the readiness page has no findings container")
    if flow_box is not None:
        cards = list(walk(flow_box))
        titles = [w.get_label() for w in cards
                  if isinstance(w, Gtk.Label) and w.get_label()]
        for expected in ("Firmware", "Secure Boot", "Memory", "Storage", "Graphics"):
            check(expected in titles,
                  f"the readiness page does not report {expected}")
    headline = window.widgets.get("ready.headline")
    check(headline is not None and bool(headline.get_label()),
          "the readiness page drew no verdict")
    # The old page's job was to print a renderer decision. Nothing on the new
    # one may quietly grow back into that.
    if headline is not None:
        text = " ".join(
            w.get_label() for w in walk(window.widgets["ready.verdict"])
            if isinstance(w, Gtk.Label) and w.get_label()
        )
        for jargon in ("renderD", "vmwgfx", "3D acceleration", "render node"):
            check(jargon not in text,
                  f"the readiness verdict says {jargon!r}, which is the "
                  "diagnostic tangent this page was rebuilt to remove")

    # -- the storage disclosure --------------------------------------------
    window.flow.jump_to_page("disk")
    window.refresh()
    pump()
    expander = window.widgets.get("storage.expander")
    check(isinstance(expander, Adw.ExpanderRow),
          "the disk page has no advanced storage disclosure")
    if isinstance(expander, Adw.ExpanderRow):
        check(not expander.get_expanded(),
              "the advanced storage options start open; the defaults are "
              "supposed to be the quiet path")
    for question in ("layout", "filesystem", "swap", "swap_size"):
        widget = window.widgets.get(f"q.{question}")
        check(isinstance(widget, Adw.ComboRow),
              f"the {question} question has no picker on the disk page")

    # Choosing a filesystem with no snapshots has to say so, and has to say it
    # where it can be seen rather than inside a collapsed disclosure.
    values = window.enum_values.get("filesystem", [])
    if "ext4" in values and isinstance(expander, Adw.ExpanderRow):
        window.widgets["q.filesystem"].set_selected(values.index("ext4"))
        pump()
        warning = window.widgets.get("storage.warning")
        check(warning is not None and "rollback" in (warning.get_subtitle() or ""),
              "choosing ext4 does not warn that there will be no rollback entry")
        check(expander.get_expanded(),
              "the rollback consequence was left folded out of sight")
        window.widgets["q.filesystem"].set_selected(values.index("btrfs"))
        pump()

    # -- the scheme toggle -------------------------------------------------
    toggles = [w for w in walk(window)
               if isinstance(w, Gtk.ToggleButton)
               and w.has_css_class("aurade-scheme-button")]
    check(len(toggles) == 3,
          f"expected three colour scheme buttons, found {len(toggles)}")
    if len(toggles) == 3:
        manager = Adw.StyleManager.get_default()
        toggles[2].set_active(True)
        pump()
        check(manager.get_color_scheme() == Adw.ColorScheme.FORCE_DARK,
              "the dark button did not force the dark scheme")
        check(window.dark, "the window did not notice it had gone dark")
        toggles[1].set_active(True)
        pump()
        check(manager.get_color_scheme() == Adw.ColorScheme.FORCE_LIGHT,
              "the light button did not force the light scheme")


def main() -> int:
    if not os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
        print("installer GUI runtime test: SKIP (no display)")
        return 0
    bridge_path = find_bridge(os.path.join(ROOT, "installer", "bin"))
    if bridge_path is None:
        print("installer GUI runtime test: SKIP (no model)")
        return 0

    model = Bridge(
        program=bridge_path,
        journal=os.environ["AURADE_JOURNAL_PATH"],
        raw_log=os.environ["AURADE_JOURNAL_RAW"],
        plan_only=True,
    )
    model.start()
    model.ping()

    Adw.init()
    app = Adw.Application(application_id="org.aurade.InstallerRuntimeTest")

    def activate(application: Adw.Application) -> None:
        window = InstallerWindow(application, model, plan_only=True)
        window.set_default_size(1280, 860)
        window.present()
        pump(30)
        if window.get_allocated_width() < 2:
            FAILURES.append("the compositor never gave the window a size")
        run(window)
        window.close()
        application.quit()

    app.connect("activate", activate)
    app.run([])
    model.close()

    if FAILURES:
        for failure in FAILURES:
            print(f"test-gui-runtime: {failure}", file=sys.stderr)
        return 1
    print("installer GUI runtime test: PASS "
          "(pages drawn, rows contained, storage and scheme controls live)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
