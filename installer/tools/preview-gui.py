#!/usr/bin/env python3
"""Render the installer's pages to PNG files without anyone watching.

The graphical installer is the one part of this tree that could not be looked
at while it was written: it needs a compositor, and the machine that builds the
image has none. `render-design-proof.py` covers the drawn layer, but the drawn
layer is the backdrop; it says nothing about whether a page is balanced, whether
a column of rows has collapsed, or whether a heading is sitting on top of a
card.

So this drives the real window. It builds the same `InstallerWindow` the
installer builds, walks it to each requested page, and snapshots the widget
tree straight out of GTK rather than screenshotting a screen, which means the
result is exact, has no cursor in it, and does not depend on a compositor
being able to hand out a screenshot protocol.

It needs a display, and a headless one is enough:

    weston --backend=headless --width=1440 --height=900 \\
           --shell=kiosk-shell.so --socket=wl-preview &
    WAYLAND_DISPLAY=wl-preview installer/tools/preview-gui.py --out /tmp/shots

Every page name from the flow works, plus the state names (`welcome`,
`review`, `gate`, `progress`, `done`, `failure`, `stopped`, `planned`), plus
`all`. Nothing here is imported by the installer; it is a tool that uses it.

The installer picks a wallpaper at random, which is right in front of a person
and wrong in a render somebody is comparing against another render. Pin one
with `AURADE_WALLPAPER=place-vestrahorn`, or take them out of the picture with
`AURADE_WALLPAPER=none`.

Two more environment notes, both learned by watching this crash rather than by
reading anything. `GTK_IM_MODULE=gtk-im-context-simple`, because the ibus
module recurses until the stack runs out on a host with no input method
daemon, and the segfault looks exactly like the installer crashing.
`GTK_USE_PORTAL=0`, because every portal lookup otherwise waits out its own
timeout before the first page is drawn. `tests/test-gui-runtime.sh` sets the
full list; it is worth copying.
"""

from __future__ import annotations

import argparse
import os
import sys

SELF_DIR = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.normpath(os.path.join(SELF_DIR, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "installer", "lib"))

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from aurade_gui import arcade as ARC, flow as F  # noqa: E402
from aurade_gui.app import InstallerWindow  # noqa: E402
from aurade_gui.bridge import Bridge, find_bridge  # noqa: E402

#: Long enough for the stack transition, the aurora tick and any idle work the
#: page queued to have run. Frames are cheap; a half-drawn screenshot is not.
SETTLE_FRAMES = 40


def pump(count: int = SETTLE_FRAMES) -> None:
    context = GLib.MainContext.default()
    for _ in range(count):
        while context.pending():
            context.iteration(False)
        GLib.usleep(6000)


def snapshot(window: Gtk.Window, path: str) -> bool:
    """Save the window's own rendering, at its own size."""
    width = window.get_allocated_width()
    height = window.get_allocated_height()
    if width < 2 or height < 2:
        print(f"preview-gui: the window is {width}x{height}; is a compositor "
              "running?", file=sys.stderr)
        return False
    paintable = Gtk.WidgetPaintable.new(window)
    # A frame before it is asked anything.
    #
    # A GtkWidgetPaintable does not hold the widget's contents at the moment it
    # is created. It observes the widget and fills in on the next frame.
    # Snapshot it immediately and `to_node` returns nothing at all, which is
    # indistinguishable from a window that drew nothing. It has been getting
    # away with it here because the pump before this call happened to leave a
    # frame in flight; that is timing, not a guarantee.
    pump(8)
    snap = Gtk.Snapshot()
    paintable.snapshot(snap, width, height)
    node = snap.to_node()
    if node is None:
        print("preview-gui: the window drew nothing", file=sys.stderr)
        return False
    renderer = window.get_native().get_renderer()
    texture = renderer.render_texture(node, None)
    texture.save_to_png(path)
    return True


def expand_all(widget: Gtk.Widget) -> None:
    if isinstance(widget, (Gtk.Expander, Adw.ExpanderRow)):
        widget.set_expanded(True)
    child = widget.get_first_child()
    while child is not None:
        expand_all(child)
        child = child.get_next_sibling()


#: A believable mid install, for the one page that draws nothing until the
#: engine has said something. Without this the progress page previews as a
#: title, an empty list and a bar at zero, which is not the page anybody sees.
PROGRESS_REPORT = {
    "running": True, "can_stop": False, "position": "7 of 11",
    "active": "pacstrap", "elapsed_ms": 194000, "reversible": False,
    "stages": [
        {"stage": "preflight", "label": "Checking this computer",
         "status": "ok", "pct": 100, "detail": "", "elapsed": "0:03"},
        {"stage": "acquire", "label": "Downloading packages",
         "status": "ok", "pct": 100, "detail": "", "elapsed": "2:41"},
        {"stage": "confirm", "label": "Confirming the disk",
         "status": "ok", "pct": 100, "detail": "", "elapsed": "0:00"},
        {"stage": "partition", "label": "Partitioning the disk",
         "status": "ok", "pct": 100, "detail": "", "elapsed": "0:02"},
        {"stage": "format", "label": "Formatting",
         "status": "ok", "pct": 100, "detail": "", "elapsed": "0:18"},
        {"stage": "mount", "label": "Mounting",
         "status": "ok", "pct": 100, "detail": "", "elapsed": "0:00"},
        {"stage": "pacstrap", "label": "Installing the base system",
         "status": "running", "pct": 58, "detail": "612 of 1041 packages",
         "pacing": "five to ten minutes", "elapsed": ""},
        {"stage": "configure", "label": "Setting things up",
         "status": "pending", "pct": 0, "detail": "", "elapsed": ""},
        {"stage": "bootloader", "label": "Making it bootable",
         "status": "pending", "pct": 0, "detail": "", "elapsed": ""},
        {"stage": "snapshot", "label": "Saving a snapshot to roll back to",
         "status": "pending", "pct": 0, "detail": "", "elapsed": ""},
        {"stage": "verify-install", "label": "Checking everything landed",
         "status": "pending", "pct": 0, "detail": "", "elapsed": ""},
    ],
}


#: A few keys per game, so a render shows a board somebody has been playing
#: rather than an opening position. Nothing here is a rule of any game; it is
#: the shortest sequence that makes each board look inhabited.
DEMO_KEYS = {
    "2048": ("left", "up", "left", "up", "right", "down", "left", "up"),
    "mines": ("space", "right", "right", "down", "space", "f", "left", "up"),
    "lights": ("space", "right", "space", "down", "down"),
    "fifteen": ("left", "up", "left", "down", "right"),
    "nono": ("space", "right", "space", "right", "space", "down", "space"),
    "soko": ("right", "right", "down", "left"),
    "c4": ("space", "right", "space", "left", "space"),
    "maze": ("right", "right", "down", "right"),
    "word": tuple("crane") + ("enter",) + tuple("solid") + ("enter",) + tuple("st"),
    "type": tuple("The quick brown fx"),
    "snake": ("down", "right", "right", "up"),
}


def play_a_little(window: InstallerWindow, ident: str) -> None:
    """Press the keys in `DEMO_KEYS`, through the window's own handler."""
    from gi.repository import Gdk  # noqa: PLC0415

    named = {"up": Gdk.KEY_Up, "down": Gdk.KEY_Down, "left": Gdk.KEY_Left,
             "right": Gdk.KEY_Right, "space": Gdk.KEY_space,
             "enter": Gdk.KEY_Return, "backspace": Gdk.KEY_BackSpace}
    game = getattr(window, "game", None)
    for key in DEMO_KEYS.get(ident, ()):
        keyval = named.get(key) or Gdk.unicode_to_keyval(ord(key))
        window._on_arena_key(None, keyval, 0, 0)
        # A game that moves on its own is stepped between keys, or the snake
        # renders as three squares that never left the corner.
        if game is not None and game.tick_ms:
            for _ in range(3):
                window._arcade_tick()
    if game is not None and game.tick_ms and ident not in DEMO_KEYS:
        for _ in range(24):
            window._arcade_tick()
    # Motion is run to its end rather than caught half way. A still of a tile
    # at forty percent of its size is a render of a bug, not of a board, and
    # these files are looked at side by side against the last set.
    if game is not None:
        for _ in range(120):
            if not game.animating():
                break
            game.frame(0.016)
    window.widgets["progress.arena"].queue_draw()


def goto(window: InstallerWindow, name: str, playing: str = "") -> None:
    """Put the window on one page or state, through the flow's own methods."""
    if name in F.PAGES_BY_NAME:
        window.flow.state = "pages"
        window.flow.jump_to_page(name)
    else:
        window.flow.state = name
    window.refresh()
    if name != F.PROGRESS:
        return
    # The progress page is a view of a journal that is not being written here,
    # so it is handed one. This is the only page in the tool that needs it, and
    # it goes through `_draw_progress`, the same call the poll makes.
    window._draw_progress(PROGRESS_REPORT)
    window.tip_index = 0
    window._rotate_tip()
    if playing and playing != "tips":
        window._show_wait(playing)
        pump(2)
        play_a_little(window, playing)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pages", nargs="*", default=["all"],
                        help="page or state names, or 'all'")
    parser.add_argument("--out", default="/tmp/aurade-preview",
                        help="directory for the PNGs")
    parser.add_argument("--dark", action="store_true",
                        help="render in the dark scheme")
    parser.add_argument("--size", default="1440x900",
                        help="window size, when the compositor allows one")
    parser.add_argument("--playing", nargs="?", const="snake", default="",
                        help="on the progress page, show this game rather "
                             "than the tips; 'all' renders one file per game")
    parser.add_argument("--focus", action="store_true",
                        help="place the initial focus and draw its ring, for "
                             "reviewing what a keyboard user sees")
    parser.add_argument("--expand", action="store_true",
                        help="open every disclosure before drawing, so folded "
                             "content can be reviewed too")
    args = parser.parse_args()

    if not os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
        print("preview-gui: no display; start a headless compositor first",
              file=sys.stderr)
        return 2

    bridge_path = find_bridge(os.path.join(ROOT, "installer", "bin"))
    if bridge_path is None:
        print("preview-gui: the installer model is missing", file=sys.stderr)
        return 1
    model = Bridge(
        program=bridge_path,
        journal=os.environ.get("AURADE_JOURNAL_PATH", "/tmp/aurade-preview.jsonl"),
        raw_log=os.environ.get("AURADE_JOURNAL_RAW", "/tmp/aurade-preview.log"),
        plan_only=True,
    )
    model.start()
    model.ping()

    os.makedirs(args.out, exist_ok=True)
    Adw.init()
    manager = Adw.StyleManager.get_default()
    manager.set_color_scheme(
        Adw.ColorScheme.FORCE_DARK if args.dark else Adw.ColorScheme.FORCE_LIGHT)

    names = list(args.pages)
    if not names or names == ["all"]:
        names = [F.WELCOME, *F.PAGE_ORDER, F.REVIEW, F.GATE, F.PROGRESS,
                 F.DONE, F.FAILURE, F.STOPPED, F.PLANNED]

    written: list[str] = []
    app = Adw.Application(application_id="org.aurade.InstallerPreview")

    def activate(application: Adw.Application) -> None:
        window = InstallerWindow(application, model, plan_only=True)
        try:
            width, _, height = args.size.partition("x")
            window.set_default_size(int(width), int(height))
        except ValueError:
            pass
        window.present()
        pump(60)
        suffix = "-dark" if args.dark else ""
        for name in names:
            # `--playing all` turns one progress render into one per game,
            # which is the only way to look at thirteen boards without
            # thirteen runs of a headless compositor.
            plays: list[str] = [args.playing]
            if args.playing == "all" and name == F.PROGRESS:
                plays = [ident for ident, _text in ARC.CHOICES
                         if ident not in ARC.NOT_GAMES]
            elif args.playing == "all":
                plays = [""]
            for playing in plays:
                try:
                    goto(window, name, playing)
                except Exception as exc:  # noqa: BLE001 - a tool, not the product
                    print(f"preview-gui: {name}: {exc}", file=sys.stderr)
                    continue
                if args.expand:
                    expand_all(window)
                if args.focus:
                    window.set_focus_visible(True)
                    window._focus_first()
                pump()
                tail = f"-{playing}" if len(plays) > 1 else ""
                path = os.path.join(args.out, f"{name}{tail}{suffix}.png")
                if snapshot(window, path):
                    written.append(path)
        window.close()
        application.quit()

    app.connect("activate", activate)
    app.run([])
    model.close()

    for path in written:
        print(f"preview-gui: {path}")
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
