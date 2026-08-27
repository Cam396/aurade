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

import datetime as dt
import json
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

#: Which pass this is. The weather panel is taller than a laptop screen, so
#: it gets its own pass on a taller compositor rather than every other shot
#: being taken on a screen nobody has.
WANT = os.environ.get("AURADE_SHOT_SET", "screens")


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


def fake_weather(path: str) -> None:
    """A recorded afternoon, so the picture is the same every time.

    The weather panel is the one part of this screen whose content comes from
    outside the machine, which would make every screenshot of it different
    and none of them comparable. So the cache is written here with a stamp of
    now, which is fresh by definition, and the greeter never asks anybody.

    The reading is a real one, taken from the National Weather Service for a
    thundery August afternoon, because a design review wants the case where
    every tile has something in it and the sky mark is not a plain sun.
    """
    start = dt.datetime.now().astimezone().replace(minute=0, second=0,
                                                   microsecond=0)
    shape = [26, 27, 27, 27, 26, 25, 24, 23, 22, 21, 20, 20]
    rain = [45, 45, 81, 81, 81, 60, 35, 20, 14, 8, 5, 5]
    marks = ["thunder", "thunder", "thunder", "heavy-rain", "thunder", "rain",
             "rain", "cloudy", "cloudy", "partly-cloudy", "mostly-clear",
             "clear"]
    days = [(28, 20, "thunder", 81, 6.2), (28, 18, "rain", 43, 6.7),
            (28, 18, "partly-cloudy", 3, 6.7), (29, 21, "mostly-clear", 16, 6.0),
            (29, 20, "thunder", 30, 3.8), (24, 16, "cloudy", 12, 5.1),
            (22, 14, "clear", 0, 5.6)]
    record = {
        "version": 1,
        "place": "Ardsley, NY",
        "provider": "nws",
        "latitude": 41.0126,
        "longitude": -73.8437,
        "zone": start.tzname() and "America/New_York" or "",
        "taken": time.time(),
        "narrative": (
            "A chance of showers and thunderstorms before 2pm, then showers "
            "and thunderstorms. Mostly cloudy. High near 28, with "
            "temperatures falling to around 26 in the afternoon. South wind "
            "around 19 km/h. Chance of precipitation is 80%. New rainfall "
            "amounts between 1.5 and 2 cm possible."),
        "now": {
            "temperature": 25.0, "feels_like": 30.3, "humidity": 77,
            "dew_point": 20.6, "wind": 19.0, "gust": 34.0, "bearing": 163,
            "pressure": 1016.7, "visibility": 14.5, "cloud": 83,
            "condition": "thunder", "daylight": True,
            "summary": "Chance Showers And Thunderstorms",
        },
        "hours": [{
            "at": (start + dt.timedelta(hours=index)).isoformat(),
            "temperature": float(shape[index]),
            "condition": marks[index],
            "precipitation": rain[index],
            "daylight": 6 <= (start.hour + index) % 24 <= 19,
        } for index in range(12)],
        "days": [{
            "date": (start.date() + dt.timedelta(days=index)).isoformat(),
            "name": "", "high": float(high), "low": float(low),
            "condition": mark, "precipitation": chance, "ultraviolet": uv,
        } for index, (high, low, mark, chance, uv) in enumerate(days)],
    }
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(record, handle)


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


def save_only(window, name: str, widget) -> str:
    """One widget on its own, at its full natural size.

    The weather panel is taller than any screen it will ever open on, which
    is what the scroller inside it is for. A review still has to see the part
    under the fold, and compositing it over an 860 pixel window just crops it
    somewhere else, so this renders the widget alone and lets the texture be
    however tall the widget is.
    """
    snapshot = Gtk.Snapshot.new()
    paintable = Gtk.WidgetPaintable.new(widget)
    pump()
    # The paintable's own intrinsic size, not a measured one. `snapshot`
    # scales the widget into whatever box it is handed, and a measured size
    # includes the shadow's extents, so asking for the measured box renders
    # the widget stretched by however much shadow there is. Every circle on
    # the panel came out an egg, which looked like a drawing fault and was
    # a fault in the picture of it.
    width = paintable.get_intrinsic_width()
    height = paintable.get_intrinsic_height()
    paintable.snapshot(snapshot, width, height)
    node = snapshot.to_node()
    if node is None:
        raise SystemExit(f"{name}: the snapshot produced no render node")
    texture = window.get_native().get_renderer().render_texture(node, None)
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
        cache = os.environ.get("AURADE_WEATHER_CACHE")
        if cache:
            fake_weather(cache)
        window = GreeterWindow(app, None)
        window.nm = Radio()
        window.present()
        if not wait_for(lambda: window.get_mapped() and window.get_width() > 0):
            raise SystemExit("the greeter window never appeared")
        pump(60)

        if WANT == "screens":
            written.append(save(window, "greeter-accounts"))

        # The panel, composited where the compositor would put it: anchored to
        # the status button, sitting above it against the bottom right corner.
        button = window.widgets.get("status")
        panel = window.widgets.get("panel")
        if WANT == "screens" and button is not None and panel is not None:
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
                popover.popdown()
                pump(20)

        # The weather, opened from its own pill on the same shelf.
        weather = window.widgets.get("weather")
        if weather is not None:
            bubble = weather.get_popover()
            bubble.popup()
            pump(60)
            if WANT == "screens":
                ok, bounds = weather.compute_bounds(window)
                pw = max(bubble.get_width(), 440)
                ph = max(bubble.get_height(), 520)
                if ok:
                    x = max(12.0, bounds.origin.x + bounds.size.width - pw)
                    y = max(12.0, bounds.origin.y - ph - 12.0)
                else:
                    x, y = 1280 - pw - 24.0, 860 - ph - 72.0
                written.append(save(window, "greeter-weather", (bubble, x, y)))

            # And the whole panel end to end, which no screen shows at once.
            # The cap is what makes this fit a netbook; a design review needs
            # to see what is under the fold, so the harness lifts it for one
            # render rather than the product carrying a debug mode.
            panel = window.widgets.get("weather.panel")
            if WANT == "weather-full" and panel is not None:
                panel.scroller.set_max_content_height(3000)
                # Lifting the cap changes what the popover wants, and a
                # popover that is already up does not go back and ask again.
                # Closing and reopening is what makes it lay out at the new
                # size; without it the texture is the right height and the
                # bottom half of it is empty.
                bubble.popdown()
                pump(20)
                bubble.popup()
                pump(60)
                print(f"  full panel is {bubble.get_width()} by "
                      f"{bubble.get_height()}")
                written.append(save_only(window, "greeter-weather-full",
                                         bubble))
        app.quit()

    app.connect("activate", activate)
    app.run([])
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
