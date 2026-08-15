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

from aurade_gui import flow as F  # noqa: E402
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


def goto(window: InstallerWindow, name: str) -> None:
    """Put the window on one page or state, through the flow's own methods."""
    if name in F.PAGES_BY_NAME:
        window.flow.state = "pages"
        window.flow.jump_to_page(name)
    else:
        window.flow.state = name
    window.refresh()


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
            try:
                goto(window, name)
            except Exception as exc:  # noqa: BLE001 - a tool, not the product
                print(f"preview-gui: {name}: {exc}", file=sys.stderr)
                continue
            if args.expand:
                expand_all(window)
            pump()
            path = os.path.join(args.out, f"{name}{suffix}.png")
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
