#!/usr/bin/env python3
"""Render the greeter to a PNG so somebody can look at it.

A login screen is judged by eye before it is judged by anything else, and no
assertion in the test suite says whether the clock is the right size or the
account rows sit where they should. This puts a real window on a headless
compositor, snapshots it, and writes the picture out.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..")))

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gsk", "4.0")

from gi.repository import Adw, Gdk, GLib, Gsk, Gtk  # noqa: E402

from aurade_greeter import protocol as P  # noqa: E402
from aurade_greeter.app import GreeterWindow  # noqa: E402


def pump(frames: int = 60) -> None:
    """Frames, not seconds. A window that has not been allocated yet draws
    nothing, and the allocation arrives on a frame rather than on a clock."""
    context = GLib.MainContext.default()
    for _ in range(frames):
        while context.pending():
            context.iteration(False)
        GLib.usleep(6000)


def scripted(replies: list[dict]) -> P.Transport:
    theirs, ours = socket.socketpair()
    for reply in replies:
        body = json.dumps(reply).encode("utf-8")
        theirs.sendall(struct.pack("=I", len(body)) + body)
    return P.Transport(ours)


def shot(window, path: str) -> None:
    """The widget's own rendering, at its own size.

    The paintable gets a frame before it is asked anything. A
    GtkWidgetPaintable does not hold the widget's contents at the moment it is
    created; it observes the widget and fills in on the next frame. Snapshot
    it immediately and it returns no render node at all, which is
    indistinguishable from a window that drew nothing.
    """
    paintable = Gtk.WidgetPaintable.new(window)
    pump(20)
    width = window.get_width()
    height = window.get_height()
    if width < 2 or height < 2:
        print(f"{path}: the window is {width}x{height}; is a compositor running?")
        return
    snapshot = Gtk.Snapshot()
    paintable.snapshot(snapshot, width, height)
    node = snapshot.to_node()
    if node is None:
        print(f"{path}: the window drew nothing")
        return
    renderer = window.get_native().get_renderer()
    texture = renderer.render_texture(node, None)
    texture.save_to_png(path)
    print(f"{path}: {width}x{height}")


def main() -> int:
    """Run a real application, not a pumped context.

    A window renders on its frame clock, and the frame clock runs inside a
    real main loop. Driving GLib.MainContext by hand allocates the widgets and
    produces no render node at all, which looks exactly like a window that
    drew nothing.
    """
    Adw.init()
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/greeter"
    secret = {"type": "auth_message", "auth_message_type": "secret",
              "auth_message": "Password:"}
    app = Adw.Application(application_id="org.aurade.GreeterPreview")

    def activate(application: Adw.Application) -> None:
        window = GreeterWindow(application, scripted([secret, {"type": "success"}]))
        window.set_default_size(1280, 860)
        window.present()
        pump(60)
        # The shade, which is what the screen is before anybody touches it.
        # This used to be written as `-accounts.png`, which named the one
        # state the tool never captured: `choose` goes straight from here to
        # the password page, so the account list was never in any picture.
        shot(window, f"{out}-shade.png")
        window.lift()
        pump(80)
        shot(window, f"{out}-accounts.png")
        # The status area, open, which is where the network lives.
        try:
            window.widgets["status"].popup()
            pump(60)
            # A popover lives in its own surface, so snapshotting the window
            # captures the screen behind it. The panel's own child is the
            # thing worth looking at.
            shot(window.widgets["panel"].get_child(), f"{out}-panel.png")
            window.widgets["panel"].popdown()
            pump(20)
        except Exception as exc:  # noqa: BLE001 - a tool, not the product
            print(f"panel: {exc}")
        if window.accounts:
            window.choose(window.accounts[0])
            pump(80)
            shot(window, f"{out}-password.png")
            window.widgets["password.error"].set_label(
                "That password did not work. Try it again, or choose another "
                "account.")
            window.widgets["password.error"].set_visible(True)
            window.widgets["password.caps"].set_visible(True)
            pump(50)
            shot(window, f"{out}-refused.png")
        window.close()
        application.quit()

    app.connect("activate", activate)
    return app.run([])


if __name__ == "__main__":
    raise SystemExit(main())
