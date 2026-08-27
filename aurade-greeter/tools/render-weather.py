#!/usr/bin/env python3
"""Every weather mark and chart on one sheet, so they can be looked at.

`weatherdraw.py` holds no state and touches no widget, which is what makes
this possible: the whole set can be drawn straight to a file and compared
side by side. A sky mark that is wrong is obvious in a contact sheet and
invisible one at a time inside a running greeter.

    tools/render-weather.py out.png [--light]
"""
from __future__ import annotations

import datetime as _dt
import os
import sys

import cairo
import gi

gi.require_version("Pango", "1.0")
from gi.repository import Pango  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurade_greeter import tokens as T  # noqa: E402
from aurade_greeter import weather as W  # noqa: E402
from aurade_greeter import weatherdraw as D  # noqa: E402

WIDTH = 1180
FONT = Pango.FontDescription.from_string("Adwaita Sans 11")


def sample_hours(start: _dt.datetime) -> list:
    shape = [17, 18, 20, 23, 25, 27, 28, 27, 24, 21, 19, 18]
    rain = [5, 10, 20, 45, 70, 81, 60, 35, 20, 10, 5, 0]
    weather = [W.MOSTLY_CLEAR, W.PARTLY, W.PARTLY, W.RAIN, W.THUNDER,
               W.THUNDER, W.HEAVY_RAIN, W.RAIN, W.CLOUDY, W.PARTLY,
               W.MOSTLY_CLEAR, W.CLEAR]
    return [W.Hour(at=start + _dt.timedelta(hours=index),
                   temperature=float(shape[index]),
                   condition=weather[index],
                   precipitation=rain[index],
                   daylight=6 <= (start.hour + index) % 24 <= 19)
            for index in range(12)]


def sample_days(start: _dt.date) -> list:
    rows = [
        (28, 20, W.THUNDER, 81, 6.2), (28, 18, W.RAIN, 43, 6.7),
        (28, 18, W.PARTLY, 3, 6.7), (29, 21, W.MOSTLY_CLEAR, 16, 6.0),
        (29, 20, W.THUNDER, 30, 3.8), (24, 16, W.CLOUDY, 12, 5.1),
        (22, 14, W.CLEAR, 0, 5.6),
    ]
    return [W.Day(date=start + _dt.timedelta(days=index), high=float(h),
                  low=float(low), condition=c, precipitation=p,
                  ultraviolet=uv)
            for index, (h, low, c, p, uv) in enumerate(rows)]


def sheet(path: str, dark: bool) -> None:
    colours = T.scheme(dark)
    height = 1180
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, WIDTH, height)
    cr = cairo.Context(surface)
    cr.set_source_rgb(*D.rgb(colours["surface"]))
    cr.paint()

    y = 24.0
    D._set(cr, colours, "on_surface")
    D.text(cr, FONT, "Sky, day", 24, y, weight=700)
    y += 26

    size = 44.0
    for row, daylight in ((0, True), (1, False)):
        x = 24.0
        for condition in W.CONDITIONS:
            cr.save()
            cr.translate(x, y + row * (size + 30))
            cr.scale(size / D.DESIGN, size / D.DESIGN)
            D.sky(cr, condition, daylight, colours)
            cr.restore()
            D._set(cr, colours, "on_surface_variant")
            D.text(cr, FONT, W.WORDS[condition].split()[0].lower(),
                   x + size / 2, y + row * (size + 30) + size + 2,
                   align="center", scale=0.68)
            x += size + 22
        if row == 0:
            D._set(cr, colours, "on_surface")
            D.text(cr, FONT, "Sky, night", 24, y + size + 22, weight=700)
    y += (size + 30) * 2 + 16

    D._set(cr, colours, "on_surface")
    D.text(cr, FONT, "Twelve hours", 24, y, weight=700)
    y += 24
    cr.save()
    cr.translate(24, y)
    D.hours_chart(cr, WIDTH - 48, 190, sample_hours(
        _dt.datetime(2026, 8, 27, 12, tzinfo=_dt.timezone.utc)),
        "c", colours, FONT)
    cr.restore()
    y += 206

    D._set(cr, colours, "on_surface")
    D.text(cr, FONT, "Seven days", 24, y, weight=700)
    y += 24
    cr.save()
    cr.translate(24, y)
    D.days_chart(cr, 560, 210, sample_days(_dt.date(2026, 8, 27)), "c",
                 colours, FONT, current=25.0,
                 names=["Today", "Friday", "Saturday", "Sunday", "Monday",
                        "Tuesday", "Wednesday"])
    cr.restore()

    right = 640.0
    cr.save()
    cr.translate(right, y - 4)
    D.sun_arc(cr, 500, 130, 0.62, colours, FONT, "6:16 AM", "7:37 PM", 42.0)
    cr.restore()

    cr.save()
    cr.translate(right, y + 136)
    D.compass(cr, 92, 163, colours, FONT)
    cr.restore()

    cr.save()
    cr.translate(right + 120, y + 152)
    D.uv_bar(cr, 220, 18, 6.2, colours)
    cr.restore()
    cr.save()
    cr.translate(right + 120, y + 186)
    D.level_bar(cr, 220, 18, 94, 0, 100, colours)
    cr.restore()
    cr.save()
    cr.translate(right + 120, y + 216)
    D.level_bar(cr, 220, 18, 1018, 960, 1050, colours, "tertiary")
    cr.restore()

    for index, (lit, waxing) in enumerate(
            ((0.04, True), (0.28, True), (0.5, True), (0.80, True),
             (1.0, True), (0.80, False), (0.28, False))):
        cr.save()
        cr.translate(right + 8 + index * 44, y + 244)
        D.moon_disc(cr, 38, lit, waxing, colours)
        cr.restore()

    y += 226
    D._set(cr, colours, "on_surface")
    D.text(cr, FONT, "Sun, wind, ultraviolet, humidity, pressure, moon",
           24, y + 30, scale=0.9)

    surface.write_to_png(path)
    print(f"wrote {path}")


if __name__ == "__main__":
    where = sys.argv[1] if len(sys.argv) > 1 else "weather-sheet.png"
    sheet(where, "--light" not in sys.argv)
