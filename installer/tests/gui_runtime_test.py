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
    group = window.widgets.get("ready.checks")
    details = window.widgets.get("ready.detail.group")
    check(group is not None and details is not None,
          "the readiness page has no findings container")
    if group is not None and details is not None:
        # Everything passes against these fixtures, so the page itself has to
        # be empty of findings and all five have to be inside the details.
        # A page that reports five green ticks every time is a page with
        # nothing to read and nothing to do, which is what this one was.
        check(not [w for w in walk(group) if isinstance(w, Adw.ActionRow)],
              "a passing check is still on the page instead of in the details")

        widgets = list(walk(details))
        titles = [w.get_label() for w in widgets
                  if isinstance(w, Gtk.Label) and w.get_label()]
        for expected in ("Firmware", "Secure Boot", "Memory", "Storage", "Graphics"):
            check(expected in titles,
                  f"the readiness details do not report {expected}")

        # Every finding carries its own subject icon. Five identical ticks is
        # what this page used to be, and the tick it used was not in the
        # image's icon theme, so it was five blank spaces and five titles.
        named = [w.get_icon_name() for w in widgets
                 if isinstance(w, Gtk.Image) and w.get_icon_name()]
        for expected in ("application-x-firmware-symbolic", "channel-secure-symbolic",
                         "media-flash-symbolic", "drive-harddisk-symbolic",
                         "video-display-symbolic"):
            check(expected in named,
                  f"no finding on the readiness page draws {expected}")
        tiles = [w for w in widgets if w.has_css_class("aurade-icon-tile")]
        check(len(tiles) >= 5,
              f"only {len(tiles)} findings put their icon in a tile")
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

    # -- a blocked verdict has to actually block ---------------------------
    #
    # The readiness page's whole purpose is to move the engine's two hard
    # refusals - a BIOS boot and an enabled Secure Boot - to before the disk
    # is chosen. If Next still works, the page is a notice board: the user
    # answers nine more questions and meets the same refusal at the erase
    # gate, which is the failure this page was built to prevent. The page did
    # disable the button, and the refresh that drew it turned it back on two
    # dozen lines later.
    window.flow.state = "pages"
    window.flow.jump_to_page("readiness")
    real_call = window.model.call
    window.model.call = lambda command, argument="": {
        "ok": True, "verdict": "blocked",
        "checks": [{"id": "secure_boot", "title": "Secure Boot", "state": "blocked",
                    "finding": "Secure Boot is on.",
                    "action": "Turn it off in the firmware settings."}],
    } if command == "readiness" else real_call(command, argument)
    window.refresh()
    pump()
    check(not window.forward_button.get_sensitive(),
          "a blocked readiness verdict still lets the installer continue")
    promoted = [w for w in walk(window.widgets["ready.checks"])
                if isinstance(w, Adw.ActionRow)]
    check(len(promoted) == 1,
          f"the blocking check was not the only thing on the page ({len(promoted)} rows)")
    window.model.call = real_call
    window.refresh()
    pump()
    check(window.forward_button.get_sensitive(),
          "the readiness page left the installer stuck after the block cleared")

    # -- the way in to the advanced page -----------------------------------
    #
    # The advanced questions have working defaults, so their page is not in the
    # flow until it is asked for, and for one release the only thing that asked
    # for it was a flat button at the end of the review screen. This is the
    # control that makes it reachable from anywhere, and the assertion is that
    # it actually changes the flow rather than looking like it might.
    # Walking every page above reached the advanced one, which is what puts it
    # in the flow; put it back the way a fresh installer starts.
    window.flow.set_show_advanced(False)
    window.flow.state = "pages"
    window.flow.jump_to_page("readiness")
    window.refresh()
    pump()
    advanced = window.widgets.get("chrome.advanced")
    check(isinstance(advanced, Gtk.ToggleButton),
          "there is no way to reach the advanced options from the chrome")
    if isinstance(advanced, Gtk.ToggleButton):
        before = len(window.flow.pages)
        advanced.set_active(True)
        pump()
        check("advanced" in window.flow.pages,
              "the advanced toggle did not put the advanced page in the flow")
        check(len(window.flow.pages) == before + 1,
              "the advanced toggle changed the flow by more than one page")
        check(window.flow.current_page == "advanced",
              f"the advanced toggle left the installer on "
              f"{window.flow.current_page!r}")
        advanced.set_active(False)
        pump()
        check("advanced" not in window.flow.pages,
              "turning the advanced toggle off left the page in the flow")
        window.flow.jump_to_page("readiness")
        window.refresh()
        pump()

    # -- the motion actually runs ------------------------------------------
    #
    # Two animations, both driven by libadwaita rather than by a timer here.
    # An API name that does not exist raises on the machine being installed
    # and nowhere else, so both are played for real against the toolkit.
    #
    # Animations have to be turned on to test them: this harness draws with
    # cairo, which is exactly the condition under which the installer switches
    # motion off, so leaving it alone would take both paths straight to the
    # branch that does nothing and prove neither call exists.
    settings = Gtk.Settings.get_default()
    motion_was = settings.get_property("gtk-enable-animations")
    settings.set_property("gtk-enable-animations", True)
    check(window.animate, "the window will not animate even with motion on")
    try:
        window.fade_in()
    except Exception as exc:  # noqa: BLE001 - any failure is the finding
        FAILURES.append(f"the window's fade-in raised: {exc!r}")

    window.flow.state = F.PROGRESS
    window.refresh()
    try:
        window._draw_progress({
            "running": True, "can_stop": True, "position": "2 of 7",
            "stages": [{"stage": "acquire", "label": "Downloading packages",
                        "status": "running", "pct": 60, "detail": "60%"}],
        })
    except Exception as exc:  # noqa: BLE001
        FAILURES.append(f"drawing progress raised: {exc!r}")
    else:
        bar = window.widgets["progress.bar"]
        animation = getattr(window, "_progress_fade", None)
        check(animation is not None,
              "the progress bar was not animated with motion turned on")
        if animation is not None:
            # Run it to its end rather than waiting for frames. A headless
            # compositor's frame clock is not a thing to build an assertion
            # on, and the question here is whether the animation reaches the
            # value it was given - which is the half that breaks when a
            # property name is wrong.
            animation.skip()
            pump(4)
            check(abs(bar.get_fraction() - 0.6) < 1e-6,
                  f"the progress animation ended at {bar.get_fraction()}, not 0.6")

    # And with motion off - the machines this installer usually runs on - the
    # same call still has to land on the value rather than easing to it in a
    # step nobody scheduled.
    settings.set_property("gtk-enable-animations", False)
    window.widgets["progress.bar"].set_fraction(0.0)
    window._draw_progress({
        "running": True, "can_stop": False, "position": "3 of 7",
        "stages": [{"stage": "pacstrap", "label": "Installing packages",
                    "status": "running", "pct": 40, "detail": ""}],
    })
    check(abs(window.widgets["progress.bar"].get_fraction() - 0.4) < 1e-6,
          "with motion off the progress bar did not go straight to its value")
    settings.set_property("gtk-enable-animations", motion_was)

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
