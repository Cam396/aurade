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

from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from aurade_gui import flow as F  # noqa: E402
from aurade_gui.app import InstallerWindow  # noqa: E402
from aurade_gui.bridge import Bridge, find_bridge  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def equal(got: object, want: object, message: str) -> None:
    if got != want:
        FAILURES.append(f"{message}: expected {want!r}, got {got!r}")


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

    # -- a Secure Boot warning remains actionable -------------------------
    #
    # Secure Boot without an AuraDE key is not a reason to make the user fill
    # the form twice. The engine continues and completion guidance covers
    # disabling firmware or enrolling a key before first boot. Legacy BIOS is
    # still a genuine block and remains covered by the readiness contract.
    window.flow.state = "pages"
    window.flow.jump_to_page("readiness")
    real_call = window.model.call
    window.model.call = lambda command, argument="": {
        "ok": True, "verdict": "attention",
        "checks": [{"id": "secure_boot", "title": "Secure Boot", "state": "warn",
                    "finding": "Secure Boot is on, but no AuraDE signing key is available.",
                    "action": "Disable it before the first boot, or enroll an AuraDE key after installation."}],
    } if command == "readiness" else real_call(command, argument)
    window.refresh()
    pump()
    check(window.forward_button.get_sensitive(),
          "a Secure Boot warning incorrectly blocks the installer")
    promoted = [w for w in walk(window.widgets["ready.checks"])
                if isinstance(w, Adw.ActionRow)]
    check(len(promoted) == 1,
          f"the Secure Boot warning was not the only promoted check ({len(promoted)} rows)")
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
        # `overall` is what the bar is set from, and `pct` is what the
        # detail line is built from. They are different numbers on purpose:
        # sixty percent through downloading is not sixty percent through
        # installing, and the bridge sends both for exactly that reason.
        window._draw_progress({
            "running": True, "can_stop": True, "position": "2 of 7",
            "overall": 60,
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
        "overall": 40,
        "stages": [{"stage": "pacstrap", "label": "Installing packages",
                    "status": "running", "pct": 40, "detail": ""}],
    })
    check(abs(window.widgets["progress.bar"].get_fraction() - 0.4) < 1e-6,
          "with motion off the progress bar did not go straight to its value")
    settings.set_property("gtk-enable-animations", motion_was)

    # -- the ten minutes in the middle -------------------------------------
    #
    # The waiting card is the reason this page was rebuilt, and it is made of
    # exactly the things a source-level test cannot see: two stacks that have
    # to swap, a drawing area that has to draw, and a key controller that must
    # steer a snake and nothing else.
    window._draw_progress({
        "running": True, "can_stop": False, "position": "7 of 11",
        "elapsed_ms": 194000, "active": "pacstrap",
        "stages": (
            [{"stage": f"done{n}", "label": f"Step {n}", "status": "ok",
              "pct": 100, "detail": "", "elapsed": "0:04"} for n in range(6)]
            + [{"stage": "pacstrap", "label": "Installing the base system",
                "status": "running", "pct": 58,
                "pacing": "five to ten minutes",
                "detail": "612/1041 packages"}]
            + [{"stage": f"todo{n}", "label": f"Later {n}", "status": "pending",
                "pct": 0, "detail": "", "elapsed": ""} for n in range(4)]
        ),
    })
    # The running step is the heading of its own card, and the pacing line
    # underneath must not repeat it. A card that says "Installing the base
    # system" twice reads as a card that was assembled rather than written.
    check(window.widgets["progress.step"].get_label() == "Installing the base system",
          "the live card does not name the running step")
    pacing = window.widgets["progress.pacing"].get_label()
    check("Installing the base system" not in pacing,
          f"the pacing line repeats the heading above it: {pacing!r}")
    check("Usually five to ten minutes." in pacing,
          f"the pacing line does not say roughly how long: {pacing!r}")
    check("3 minutes so far." in pacing,
          f"the pacing line does not say how long it has been: {pacing!r}")
    # The count, which is also the disclosure the full list lives behind.
    check(window.widgets["progress.steps"].get_title() == "6 done, 4 to go",
          "the step count is wrong: "
          f"{window.widgets['progress.steps'].get_title()!r}")
    # A range, never a countdown. An estimate that turns out wrong is
    # remembered longer than the install it was wrong about.
    for promise in ("remaining", "time left", "estimated"):
        check(promise not in pacing.lower(),
              f"the pacing line promises a countdown it cannot keep: {promise}")

    # A stage with no pacing in the table must not leave the word "Usually"
    # hanging on its own.
    window._draw_progress({
        "running": True, "can_stop": False, "position": "1 of 11",
        "elapsed_ms": 0, "active": "mystery",
        "stages": [{"stage": "mystery", "label": "Doing something new",
                    "status": "running", "pct": 5, "pacing": "", "detail": ""}],
    })
    bare = window.widgets["progress.pacing"].get_label()
    check("Usually" not in bare, f"a stage with no pacing said 'Usually': {bare!r}")
    check(bare.strip() == "",
          f"a stage with no pacing and no elapsed time drew {bare!r}")
    check(window.widgets["progress.step"].get_label() == "Doing something new",
          "a stage with no pacing lost its name as well")

    # The tips come from the same file the text installer reads.
    check(bool(window.tips), "the graphical front end found no tips to show")
    window.tip_index = 0
    window._rotate_tip()
    first_face = window.widgets["progress.tips"].get_visible_child_name()
    first_text = window.widgets[f"progress.tip.{first_face}"].get_label()
    check(len(first_text) > 20, f"the first tip is not a tip: {first_text!r}")
    window._rotate_tip()
    second_face = window.widgets["progress.tips"].get_visible_child_name()
    check(second_face != first_face,
          "rotating a tip did not swap the crossfade stack, so nothing fades")
    second_text = window.widgets[f"progress.tip.{second_face}"].get_label()
    check(second_text != first_text, "the tip rotation repeated itself")

    # The game. It has to actually start, actually move, and actually be
    # steerable, and none of that is visible from the source.
    faces = window.widgets["progress.faces"]
    check(faces.get_visible_child_name() == "tips",
          "the waiting card started on the game rather than the tips")
    window._on_waiting_toggled(window.widgets["progress.play"])
    pump(2)
    check(faces.get_visible_child_name() == "game",
          "asking to play did not show the game")
    check(window.snake is not None, "asking to play did not start a game")
    check(window.widgets["progress.play"].get_label() != F.WAIT_PLAY,
          "the play button still offers to play while the game is up")
    before = list(window.snake.body)
    window._snake_tick()
    check(list(window.snake.body) != before, "a tick did not move the snake")
    check("Score" in window.widgets["progress.score"].get_label(),
          "the game is up and the score is not")

    # Arrow keys steer. Everything else is refused, which is what keeps the
    # least recoverable screen in the product free of bound keys.
    window.snake.direction = (1, 0)
    handled = window._on_snake_key(None, Gdk.KEY_Up, 0, 0)
    check(handled, "the up arrow was not accepted by the game")
    check(window.snake.pending == (0, -1), "the up arrow did not turn the snake")
    check(not window._on_snake_key(None, Gdk.KEY_Return, 0, 0),
          "the game swallowed Return, which belongs to the page")

    # The drawing area draws, including once the snake has earned its gradient.
    arena = window.widgets["progress.arena"]
    for score in (0, 12):
        window.snake.score = score
        try:
            snapshot = Gtk.Snapshot()
            arena.do_snapshot(arena, snapshot)
        except Exception as exc:  # noqa: BLE001
            FAILURES.append(f"drawing the arena at score {score} raised: {exc!r}")

    window._on_waiting_toggled(window.widgets["progress.play"])
    pump(2)
    check(faces.get_visible_child_name() == "tips",
          "leaving the game did not go back to the tips")
    check(window._snake_source == 0,
          "the game kept ticking after it was put away")

    # -- the word ----------------------------------------------------------
    #
    # Typed on the welcome page, it replays the swoop. Typed anywhere else it
    # is six ordinary keystrokes that do nothing.
    window.flow.state = F.WELCOME
    window._swooped = True
    window._secret = ""
    for letter in "aurora":
        window._on_secret_key(None, ord(letter), 0, 0)
    check(not window._swooped or getattr(window, "_swoop_animation", None) is not None,
          "the word on the welcome page did not replay the swoop")
    window.flow.state = F.PROGRESS
    window._secret = ""
    for letter in "aurora":
        check(not window._on_secret_key(None, ord(letter), 0, 0),
              "the word did something on a page that is not the welcome page")
    window.flow.state = F.PROGRESS

    # -- the scheme toggle -------------------------------------------------
    toggles = [w for w in walk(window)
               if isinstance(w, Gtk.ToggleButton)
               and w.has_css_class("aurade-scheme-button")]
    # Four: match the system, light, dark, and dark with the ground switched
    # off. The fourth is not a taste setting. On an OLED panel a pixel at
    # #000000 draws no power and has infinite contrast, and the dark scheme's
    # ground is a pixel that is on and pretending.
    check(len(toggles) == 4,
          f"expected four colour scheme buttons, found {len(toggles)}")
    if len(toggles) == 4:
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
        # The black button asks for the dark scheme and a different sheet
        # underneath it, so the scheme alone cannot tell them apart.
        toggles[3].set_active(True)
        pump()
        check(manager.get_color_scheme() == Adw.ColorScheme.FORCE_DARK,
              "the black button did not force the dark scheme")
        check(window.oled, "the black button did not select the unlit ground")
        toggles[2].set_active(True)
        pump()
        check(not window.oled,
              "going back to dark left the ground switched off")

    # -- nothing drawn is silent -------------------------------------------
    #
    # Every identity in this front end is drawn rather than written: the mark,
    # the wordmark, the aurora, the swoop, the hairline, the progress ribbon,
    # the signal arcs, the icon tile on every row. To a screen reader a
    # `GtkDrawingArea` with no role and no label is an unlabelled box, so a
    # page of them is a page of nothing.
    #
    # This does not check that the *right* choice was made, because that is a
    # judgement: the aurora should be silent and the signal arcs must not be.
    # It checks that a choice was made at all, which is the failure that
    # actually happens, and it will catch the next drawn thing somebody adds
    # without thinking about it.
    drawn = [w for w in walk(window) if isinstance(w, Gtk.DrawingArea)]
    check(len(drawn) >= 5,
          f"expected the drawn layer to still be there, found {len(drawn)}")
    for area in drawn:
        role = area.get_accessible_role()
        if role == Gtk.AccessibleRole.PRESENTATION:
            continue  # deliberately skipped, which is a decision
        labelled = False
        try:
            # There is no getter for an accessible property, so the state is
            # read back off the widget the only way GTK exposes it.
            labelled = bool(area.get_accessible_role() in (
                Gtk.AccessibleRole.PROGRESS_BAR,
                Gtk.AccessibleRole.IMG,
                Gtk.AccessibleRole.APPLICATION,
            ))
        except Exception:
            pass
        check(labelled,
              f"a drawing area is neither decorative nor described: "
              f"role {role}, {type(area).__name__}")

    # The ribbon specifically, because it is the one a blind user needs during
    # the ten minutes when nothing else on the page changes.
    ribbon = window.widgets.get("progress.bar")
    check(ribbon is not None and
          ribbon.get_accessible_role() == Gtk.AccessibleRole.PROGRESS_BAR,
          "the progress ribbon does not report itself as a progress bar")

    run_bible(window)
    run_done_screen(window)
    run_disk_bars(window)
    run_disk_wear(window)
    run_wallpaper(window)


def run_bible(window: InstallerWindow) -> None:
    """The reader, and the reason it exists rather than a shorter one.

    The failure this is really watching for is a Bible with sixty six books
    in it. Three of the four sources checked when this was chosen were exactly
    that, and a sixty six book edition opens correctly, pages correctly and
    looks completely right. The only place it shows is the picker, which is
    why the count and one apocryphal book by name are asserted here and not
    only in the file level test.

    The other half is that the markup survives being turned into Pango. A
    verse carrying an ampersand takes the whole label down to a parse error
    and draws nothing, and an empty page in a reader looks like a book that
    happens to be blank.
    """
    from aurade_gui import bible  # noqa: PLC0415 - only needed here

    window.flow.state = F.WELCOME
    window.refresh()
    pump()

    button = window.widgets.get("bible.button")
    check(button is not None,
          "the welcome page offers no way to read the Bible, and there is one "
          "on the image")
    if button is None:
        return
    check(button.get_visible(), "the Bible button is built and not shown")

    button.emit("clicked")
    pump()

    picker = window.widgets.get("bible.picker")
    page = window.widgets.get("bible.page")
    heading = window.widgets.get("bible.heading")
    chapters = window.widgets.get("bible.chapters")
    check(picker is not None and page is not None,
          "clicking the Bible button opened nothing")
    if picker is None or page is None or heading is None or chapters is None:
        return

    names = [picker.get_model().get_string(i)
             for i in range(picker.get_model().get_n_items())]
    equal(len(names), 80,
          "the books offered, and eighty rather than sixty six is the whole "
          "reason this edition was chosen")
    for wanted in ("Genesis", "Tobit", "Revelation"):
        check(wanted in names, f"{wanted} is not in the book picker")

    # Something is actually on the page, and it is the book that was asked for.
    check(len(page.get_label()) > 200,
          f"the first chapter drew {len(page.get_label())} characters")
    check(heading.get_label() != "", "the reader shows no book title")

    # Every chapter of a book with a hard one in it. Psalm 119 is the longest
    # chapter in the Bible and Psalms is where the poetry markup lives, so if
    # anything is going to fail to escape or fail to close a tag it is here.
    picker.set_selected(names.index("Psalms"))
    pump()
    equal(chapters.get_model().get_n_items(), 150, "chapters offered in Psalms")
    for number in (1, 119, 150):
        markup = window._bible_markup(bible.chapter("PSA", number))
        parsed = True
        try:
            Gtk.Label(label="").set_markup(f"<span>{markup}</span>")
        except Exception:  # noqa: BLE001
            parsed = False
        check(parsed, f"Psalm {number} does not survive being marked up")
        check(markup.count("<i>") == markup.count("</i>"),
              f"Psalm {number} has unbalanced emphasis")

    # And the Apocrypha opens, which is the part that is not in most Bibles.
    picker.set_selected(names.index("Tobit"))
    pump()
    equal(chapters.get_model().get_n_items(), 14, "chapters offered in Tobit")
    check(len(page.get_label()) > 200, "Tobit chapter one drew almost nothing")

    dialog = window.widgets.get("bible.dialog")
    if dialog is not None:
        dialog.force_close()
        pump()


def run_done_screen(window: InstallerWindow) -> None:
    """The two facts somebody needs thirty seconds after this page appears.

    The text installer has named the username and the hostname on its done
    screen since it had one. The graphical one said "the username you chose",
    which is a sentence about a fact rather than the fact, and the sign-in
    prompt it is sending somebody to asks for the fact.
    """
    def facts(where: str) -> None:
        grid = window.widgets.get("done.facts")
        check(grid is not None, "the done screen has no facts block")
        if grid is None:
            return
        shown = False
        for key in ("username", "hostname"):
            wanted = str(window.model.get(key) or "")
            value = window.widgets.get(f"done.{key}")
            name = window.widgets.get(f"done.{key}.name")
            check(value is not None and name is not None,
                  f"the done screen has no {key} row")
            if value is None or name is None:
                continue
            equal(value.get_label(), wanted, f"the done screen's {key} {where}")
            # The label goes with its value. "This computer" followed by
            # nothing reads as the installer having mislaid the hostname.
            equal(value.get_visible(), bool(wanted),
                  f"the {key} value's visibility {where}")
            equal(name.get_visible(), bool(wanted),
                  f"the {key} label's visibility {where}")
            shown = shown or bool(wanted)
        equal(grid.get_visible(), shown,
              f"the facts block {where} is showing with nothing in it, or "
              "hiding with something in it")

    # Both halves of the rule, because the fixture answers no questions and a
    # test that only ever sees empty values proves the block can hide and
    # proves nothing at all about it filling in. The empty pass first, while
    # nothing has been answered, then the same page again with two answers on
    # it.
    window.flow.state = F.DONE
    window.refresh()
    pump()
    facts("with nothing answered")

    for key, answer in (("username", "ada"), ("hostname", "aurora")):
        ok, error = window.model.set(key, answer)
        check(ok, f"the fixture would not take {key}={answer}: {error}")
    window.refresh()
    pump()
    facts("with both answered")

    # The settle, and which half of it this machine can actually see.
    #
    # `window.animate` reads GTK's own motion preference, and on this headless
    # software rendered setup it comes back false. That is the same answer the
    # safe graphics boot entry gets, so it is a real configuration rather than
    # an artefact of the test. It is also not a limitation to work around: it
    # is the more important of the two branches, because reduce motion is an
    # accessibility setting, and "nothing decorative runs when it is off" is a
    # promise the whole drawn layer makes. So this asserts that the settle did
    # not run, rather than that it ran and finished.
    #
    # The other branch is written out too and does not execute here. There is
    # no compositor on this side that reports animations as wanted, so a
    # settle that fades the tick out and never brings it back is a bug this
    # suite cannot see. It is seen by looking at a real install.
    icon = window.widgets.get(f"{F.DONE}.icon")
    check(icon is not None, "the done screen has no icon")
    if icon is not None and not window.animate:
        check(not window._settled,
              "motion is off and the settle ran anyway, so the done screen is "
              "animating for somebody who asked it not to")
        equal(icon.get_opacity(), 1.0,
              "motion is off and the done screen's tick is not at full "
              "opacity, so something faded it and nothing is coming to bring "
              "it back")
    elif icon is not None:
        settle_pump(window)
        check(window._settled,
              "motion is on and the settle never ran, so the check below it "
              "is vacuous")
        equal(icon.get_opacity(), 1.0,
              "the done screen's tick is not at full opacity after the settle "
              "has had its delay and its whole duration, so the settle has "
              "faded it out with nothing coming to bring it back")


def settle_pump(window: InstallerWindow) -> None:
    """Run the loop for as long as the settle takes, in real time.

    `pump` iterates whatever is pending, which is the right tool for widgets
    and the wrong one for a timeout: nothing is pending until the clock says
    so. Half a second of slack on top of the delay and the duration, because
    the software renderer this runs under is not quick and a test that fails
    when the machine is busy is a test people learn to rerun.
    """
    from aurade_gui.app import SETTLE_DELAY_MS, SETTLE_MS  # noqa: PLC0415

    import time  # noqa: PLC0415

    context = GLib.MainContext.default()
    deadline = time.monotonic() + (SETTLE_DELAY_MS + SETTLE_MS + 500) / 1000.0
    while time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        time.sleep(0.01)


def run_disk_bars(window: InstallerWindow) -> None:
    """One size bar per disk, and the biggest disk holds the longest one.

    The bar is the only thing on that page that says which of two identically
    named drives is larger without being read, so a bar that is the wrong
    length is worse than no bar. A size the parser cannot read draws nothing.
    """
    from aurade_gui import brand  # noqa: PLC0415 - only needed here

    window.flow.state = "pages"
    window.flow.jump_to_page("disk")
    window.refresh()
    pump()

    listbox = window.widgets.get("disk.list")
    check(listbox is not None, "there is no disk list")
    if listbox is None:
        return

    disks = list(window.model.disks())
    readable = [d for d in disks if brand.parse_size(d.get("size") or "") > 0]
    bars = [w for w in walk(listbox) if type(w).__name__ == "CapacityBar"]
    equal(len(bars), len(readable),
          f"{len(disks)} disks, {len(readable)} with a size this can read, "
          f"{len(bars)} bars")
    if not bars:
        return

    for bar in bars:
        check(0.0 < bar.fraction <= 1.0,
              f"a size bar is {bar.fraction} of its track")
    largest = max(brand.parse_size(d.get("size") or "") for d in readable)
    biggest_bar = max(bar.fraction for bar in bars)
    equal(biggest_bar, 1.0,
          f"the largest disk ({largest / 1024 ** 3:.0f}G) does not fill its bar")


def run_disk_wear(window: InstallerWindow) -> None:
    """A worn drive says so on the row, and a healthy one says nothing.

    The text installer grew this line first, and the two front ends read the
    same disks through the same bridge, so a drive called worn out on one and
    fine on the other would be the two of them disagreeing about the disk
    somebody is choosing on the page where that matters most.

    Both halves matter. A drive at four percent is a drive with nothing wrong
    with it, and a row saying so teaches somebody to read every other row as a
    warning too.
    """
    window.flow.state = "pages"
    window.flow.jump_to_page("disk")
    window.refresh()
    pump()

    listbox = window.widgets.get("disk.list")
    check(listbox is not None, "there is no disk list")
    if listbox is None:
        return

    rows = {}
    for widget in walk(listbox):
        title = getattr(widget, "get_title", None)
        subtitle = getattr(widget, "get_subtitle", None)
        if title is None or subtitle is None:
            continue
        try:
            rows[widget.get_title()] = widget.get_subtitle() or ""
        except TypeError:
            continue

    worn = [text for path, text in rows.items() if "write life" in text]
    check(len(worn) == 1,
          f"{len(worn)} disk rows mention write life, expected exactly one")
    if worn:
        check("93%" in worn[0],
              f"the worn drive does not carry its number: {worn[0]!r}")
    healthy = rows.get("/dev/sda", "")
    check("write life" not in healthy,
          f"a drive at four percent was called out: {healthy!r}")


def run_wallpaper(window: InstallerWindow) -> None:
    """The photograph, and the two places it is not allowed to be.

    High contrast and the black ground are decisions about what the ground is
    for. A wallpaper is a taste. The rule is that the taste never wins, and it
    is a rule that is easy to write and easy to leave half applied: the class
    comes off the window and the caption stays, or the caption goes and the
    drawing area carries on painting a mountain underneath it.
    """
    from aurade_gui import brand  # noqa: PLC0415 - only needed here

    available = brand.wallpapers()
    if not available:
        print("installer GUI runtime test: no wallpapers staged, skipping those",
              file=sys.stderr)
        return

    window.wallpaper = available[0]
    window._update_ground()
    pump()

    caption = window.widgets.get("caption")
    check(caption is not None, "there is no caption")
    if caption is None:
        return

    check(window.wallpaper_shown is not None, "a wallpaper was set and is not shown")
    check(window.has_css_class("aurade-grounded"),
          "the window is showing a photograph and is not marked as grounded, "
          "so the sheet under every page is transparent")
    check(caption.get_visible(), "the caption is hidden with a photograph behind it")
    equal(caption.get_label(), available[0]["title"],
          "the caption names the wrong picture")

    # Every page stands on exactly one sheet. Not "at least one": two nested
    # sheets is two opaque grounds with a border between them, which looks
    # like a rendering fault rather than a design.
    stack = window.stack
    child = stack.get_first_child()
    pages = 0
    while child is not None:
        sheets = [w for w in walk(child) if w.has_css_class("aurade-sheet")]
        equal(len(sheets), 1,
              f"the {stack.get_page(child).get_name()} page has {len(sheets)} "
              "sheets")
        pages += 1
        child = child.get_next_sibling()
    check(pages >= 8, f"only {pages} pages were checked for a sheet")

    if len(available) > 1:
        first = window.wallpaper["file"]
        window.next_wallpaper()
        pump()
        check(window.wallpaper["file"] != first,
              "asking for a different photograph gave back the same one")
        equal(caption.get_label(), window.wallpaper["title"],
              "the caption did not follow the picture")

    # -- the two places it must not appear ---------------------------------
    #
    # Driven through the real switch rather than by setting the flag, because
    # the flag is not the mechanism: `_obey_access` reloads the stylesheet and
    # the stylesheet reload is what notices.
    window._obey_access("contrast", "high")
    pump()
    check(window.wallpaper_shown is None,
          "high contrast is on and a photograph is still behind the window")
    check(not window.has_css_class("aurade-grounded"),
          "high contrast is on and the pages are still on a sheet")
    check(not caption.get_visible(),
          "high contrast is on and the caption is still offering another photograph")
    window._obey_access("contrast", "normal")
    pump()
    check(window.wallpaper_shown is not None,
          "the photograph did not come back when high contrast went off")

    # The black scheme. The fourth scheme button sets `oled` and then asks
    # libadwaita for the dark scheme, and it is the resulting sheet reload
    # that gets here, so this sets both and reloads.
    was_dark = window.dark
    window.oled = True
    window.dark = True
    window._load_stylesheet()
    pump()
    check(window.wallpaper_shown is None,
          "the black ground is on and a photograph is lighting every pixel of it")
    window.oled = False
    window.dark = was_dark
    window._load_stylesheet()
    pump()


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
        # Whatever happens in here, the loop has to stop.
        #
        # Without the finally, a mistake in an assertion leaves the main loop
        # running with nothing left to drive it, and the test does not fail:
        # it hangs, until whoever is waiting on the suite gives up and kills
        # it. That is a much worse failure than a wrong assertion, and it is
        # the one a typo in this file produces.
        try:
            run(window)
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            FAILURES.append(f"the run raised: {exc!r}")
        finally:
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
