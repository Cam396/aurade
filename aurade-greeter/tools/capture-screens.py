"""Render the greeter to PNGs for design review.

Not a test. The runtime test asks whether the widget tree is correct; this
asks what it looks like, which is a question only a person can answer and
only from a picture.

Two things here are worth knowing. The status panel is a popover, and a
popover is its own surface, so rendering the window alone leaves it out and
rendering the popover alone produces a rectangle floating on nothing. Both
are appended to one snapshot, the popover translated to where the compositor
would put it, so the result is two real widget renders in their real
positions rather than a picture assembled by hand.

And the panel has nothing to show on a build host: no radio, no battery. A
screenshot of an empty list is a screenshot of the test environment. So the
battery is a directory this script writes and points the reader at, and the
radio is a stand in assigned to the same attribute the runtime test uses.
"""
from __future__ import annotations

import os
import sys
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Adw, Gdk, Gtk, GLib, Graphene  # noqa: E402

PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PACKAGE)

from aurade_greeter import network as NET  # noqa: E402
from aurade_greeter.app import GreeterWindow  # noqa: E402

OUT = os.environ.get("AURADE_SHOT_DIR", "/tmp/greeter-shots")


def pump(count: int = 30) -> None:
    """Let the main loop run, with real time between turns.

    The sleep is not padding. A widget paintable has nothing to hand back
    until the widget has drawn a frame, and a frame needs the frame clock to
    tick, which needs wall clock time to pass. Draining pending sources in a
    tight loop returns an empty render node every time.
    """
    context = GLib.MainContext.default()
    for _ in range(count):
        while context.pending():
            context.iteration(False)
        time.sleep(0.01)


class Radio:
    """A wireless card with something in range.

    The strengths and the mix of secured, open and saved are chosen to show
    every row state the list can draw, because a screenshot exists to show
    the states, not to report the weather in this room.
    """

    def wifi_device(self):
        # The same keys nmlive.devices() builds. A stand in that is missing one
        # of them does not fail here, it fails inside the window, which is a
        # confusing place to read a KeyError from.
        return {"path": "/fake/wifi", "kind": "wifi",
                "iface": "wlp1s0", "state": 100}

    def scan(self, _path):
        return None

    def networks(self, _path):
        return [
            NET.Network("Ardsley House", 82, "wpa-psk", saved=True, active=True),
            NET.Network("Ardsley House 5G", 74, "sae", saved=True),
            NET.Network("BT-WIFI-X", 61, "wpa-psk"),
            NET.Network("Hotel Guest", 47, "", saved=False),
            NET.Network("VM8842219", 28, "wpa-psk"),
        ]

    def saved_names(self):
        return {"Ardsley House", "Ardsley House 5G"}


def fake_battery(root: str) -> str:
    """A battery on a machine that has none, as sysfs would report it."""
    bat = os.path.join(root, "BAT0")
    ac = os.path.join(root, "AC")
    os.makedirs(bat, exist_ok=True)
    os.makedirs(ac, exist_ok=True)
    for name, value in (("type", "Battery"), ("capacity", "68"),
                        ("status", "Discharging")):
        with open(os.path.join(bat, name), "w", encoding="utf-8") as handle:
            handle.write(value + "\n")
    for name, value in (("type", "Mains"), ("online", "0")):
        with open(os.path.join(ac, name), "w", encoding="utf-8") as handle:
            handle.write(value + "\n")
    return root


def wait_for(predicate, seconds: float = 15.0) -> bool:
    context = GLib.MainContext.default()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        if predicate():
            return True
        time.sleep(0.02)
    return False


def save(window, name: str, extra=None) -> str:
    """Render the window, and anything else, into one texture."""
    width = window.get_width() or 1280
    height = window.get_height() or 860
    snapshot = Gtk.Snapshot.new()

    paintable = Gtk.WidgetPaintable.new(window)
    pump()
    paintable.snapshot(snapshot, width, height)

    if extra is not None:
        widget, x, y = extra
        widget_paintable = Gtk.WidgetPaintable.new(widget)
        pump()
        snapshot.save()
        snapshot.translate(Graphene.Point().init(x, y))
        widget_paintable.snapshot(
            snapshot,
            widget.get_width() or widget.get_allocated_width(),
            widget.get_height() or widget.get_allocated_height())
        snapshot.restore()

    node = snapshot.to_node()
    if node is None:
        raise SystemExit(f"{name}: the snapshot produced no render node")
    renderer = window.get_native().get_renderer()
    texture = renderer.render_texture(node, None)
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"{name}.png")
    texture.save_to_png(path)
    return path


def main() -> int:
    Adw.init()
    app = Adw.Application(application_id="dev.aurade.greeter.capture")
    written: list[str] = []

    def activate(_app):
        # Before the window: the status cluster reads the battery once during
        # construction, so a battery written afterwards is a battery that is
        # not in the picture.
        power = os.environ.get("AURADE_POWER_DIR")
        if power:
            fake_battery(power)
        window = GreeterWindow(app, None)
        window.nm = Radio()
        window.present()
        if not wait_for(lambda: window.get_mapped() and window.get_width() > 0):
            raise SystemExit("the greeter window never appeared")
        pump(60)

        written.append(save(window, "greeter-accounts"))

        # The panel, composited where the compositor would put it: anchored to
        # the status button, sitting above it against the bottom right corner.
        button = window.widgets.get("status")
        panel = window.widgets.get("panel")
        if button is not None and panel is not None:
            window.refresh_networks()
            pump(40)
            popover = button.get_popover()
            if popover is not None:
                popover.popup()
                pump(40)
                ok, bounds = button.compute_bounds(window)
                # The popover itself, not its child. The bubble's ground,
                # border and shadow live on the popover's own contents node,
                # so rendering the child alone produces tiles floating on the
                # wallpaper and hides exactly the thing being reviewed.
                child = popover
                # Natural size, not allocated. A popover that has just been
                # popped up on a headless compositor may not have been given
                # its full height yet, and rendering it at the smaller number
                # cuts the last row of the list in half.
                _, natural_w, _, _ = child.measure(Gtk.Orientation.HORIZONTAL, -1)
                _, natural_h, _, _ = child.measure(
                    Gtk.Orientation.VERTICAL, natural_w)
                pw = max(natural_w, child.get_width(), 360)
                ph = max(natural_h, child.get_height(), 420)
                if ok:
                    x = max(12.0, bounds.origin.x + bounds.size.width - pw)
                    y = max(12.0, bounds.origin.y - ph - 12.0)
                else:
                    x, y = 1280 - pw - 24.0, 860 - ph - 72.0
                written.append(save(window, "greeter-panel", (child, x, y)))
        app.quit()

    app.connect("activate", activate)
    app.run([])
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
