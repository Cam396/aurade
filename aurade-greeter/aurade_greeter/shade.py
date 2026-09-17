"""Render the greeter's clock, wallpaper card, and seasonal details."""

from __future__ import annotations

import datetime as _dt
import math

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gtk, Pango  # noqa: E402

from . import a11y as A  # noqa: E402
from . import brand  # noqa: E402
from . import copy as C  # noqa: E402
from . import weather as W  # noqa: E402

#: Display periods used for the greeting.
BANDS = ((5, 12, "morning"), (12, 18, "afternoon"), (18, 24, "evening"),
         (0, 5, "evening"))

#: Allow a small margin around a full moon.
FULL = 0.985

#: J2000.0, which is the epoch every short solar series counts from.
J2000 = _dt.datetime(2000, 1, 1, 12, tzinfo=_dt.timezone.utc)

#: The four turns of the year, as the sun's ecliptic longitude in degrees.
QUARTERS = (0.0, 90.0, 180.0, 270.0)


def greeting(when: _dt.datetime, style: str = "hour",
             returning: bool = True) -> str:
    """What the screen says above the accounts.

    `plain` is the setting for somebody who does not want their computer
    remarking on the time, and it is the wording this screen used before any of
    this existed, so turning the hour off is a return rather than a downgrade.
    """
    if style != "hour":
        return C.TITLE if returning else C.TITLE_FIRST
    hour = when.hour
    for start, end, part in BANDS:
        if start <= hour < end:
            return C.GREETING.format(part=part)
    return C.TITLE


def solar_longitude(when: _dt.datetime) -> float:
    """Where the sun is around the ecliptic, in degrees from the equinox.

    The Astronomical Almanac's short series, good to about a hundredth of a
    degree, which is a quarter of an hour of time.

    The declination the weather panel's sun arc runs on is the wrong
    instrument for this, and it was tried first. Declination is flat at a
    solstice, by definition, so asking which of three days it peaks on means
    differencing a nearly level function using a series whose own error is
    larger than the difference. It put three of the four turns of 2026 on the
    wrong day. Longitude moves a degree a day all year round, so the crossing
    is never ambiguous.
    """
    days = (when.astimezone(_dt.timezone.utc) - J2000).total_seconds() / 86400.0
    mean = 280.460 + 0.9856474 * days
    anomaly = math.radians((357.528 + 0.9856003 * days) % 360.0)
    return (mean + 1.915 * math.sin(anomaly)
            + 0.020 * math.sin(2.0 * anomaly)) % 360.0


def quarter_crossed(start: _dt.datetime, end: _dt.datetime) -> float | None:
    """Which of the four turns falls between two moments, if any.

    The sun covers about a degree a day, so at most one multiple of ninety can
    lie inside a single day and the first one found is the only one.
    """
    first = solar_longitude(start)
    span = (solar_longitude(end) - first) % 360.0
    for target in QUARTERS:
        if (target - first) % 360.0 < span:
            return target
    return None


def occasion(when: _dt.datetime, latitude: float | None = None) -> str:
    """The one line that is only there on the days it is true.

    Worked out rather than looked up. Eleven or twelve days a year say
    something and every other day says nothing, which is the entire reason it
    is worth having: a line that appears every morning is furniture.

    The day is the reader's own day, midnight to midnight where they are,
    rather than a UTC one. An equinox at six minutes past midnight UTC
    happened during the previous evening in New York, and telling somebody in
    New York that it is tomorrow would be wrong in the one way that matters.

    Without a latitude a solstice is named without saying which one it is for
    the reader. The longest day in Oslo is the shortest in Wellington, and a
    screen that does not know where it is has no business picking.
    """
    zone = when.tzinfo or _dt.timezone.utc
    start = _dt.datetime(when.year, when.month, when.day, tzinfo=zone)
    target = quarter_crossed(start, start + _dt.timedelta(days=1))
    if target is not None:
        if target in (0.0, 180.0):
            return C.OCCASION_EQUINOX
        if latitude is None:
            return C.OCCASION_SOLSTICE
        northern = latitude >= 0.0
        longest = (target == 90.0) == northern
        return C.OCCASION_LONGEST if longest else C.OCCASION_SHORTEST

    _name, lit, phase = W.moon(when)
    # Against the key, not the words. The words are translated.
    if lit >= FULL and phase == "full":
        return C.OCCASION_FULL_MOON
    return ""


#: The four kinds of light a picture can be in, and the bands of the clock
#: they answer to on a machine that does not know where it is.
CLOCK_BANDS = ((5, 8, "dawn"), (8, 17, "day"), (17, 20, "dusk"))

#: Above this and it is day; below the other and it is night; between them the
#: sun is low and the light is the low warm light these photographs were made
#: in. The obvious pair is plus and minus six degrees, civil twilight, and it
#: was tried first and is wrong for this: at forty one degrees north in August
#: it leaves about seventy minutes a day when a dusk picture can be shown, so
#: the seven dusk pictures would almost never appear. Twelve degrees either
#: side is the golden hour and the coloured part of twilight together, which
#: is what "a dusk photograph" actually looks like.
DAY_ABOVE = 12.0
NIGHT_BELOW = -12.0

#: A picture brighter than this is a white out on a dark screen in a dark
#: room. Between eleven at night and five in the morning it is not offered,
#: whatever it is a picture of, because the login screen is often the only
#: thing lighting the room somebody is standing in.
NIGHT_CAP = 0.30
SMALL_HOURS = (23, 5)


def light_now(when: _dt.datetime, latitude: float | None = None,
              longitude: float | None = None) -> str:
    """What the light is doing outside, right now.

    From the sun where the machine knows where it is, and from the clock where
    it does not. The sun is worth the arithmetic: in Tromso in June the clock
    says night for hours while the sky is still lit, and a login screen that
    put an aurora on the wall at midnight there would be the only thing in the
    room that had not noticed.
    """
    if latitude is not None and longitude is not None:
        altitude = W.sun_altitude(latitude, longitude, when)
        if altitude > DAY_ABOVE:
            return "day"
        if altitude < NIGHT_BELOW:
            return "night"
        rise, set_ = W.sun_times(latitude, longitude, when)
        if rise is not None and set_ is not None:
            return "dawn" if when < rise + (set_ - rise) / 2 else "dusk"
        return "dawn" if when.hour < 12 else "dusk"
    for start, end, part in CLOCK_BANDS:
        if start <= when.hour < end:
            return part
    return "night"


def suited(entries: list, light: str, when: _dt.datetime) -> list:
    """The pictures that suit this hour, or all of them rather than none.

    Two rules, doing two different jobs. The brightness cap is about the room
    somebody is standing in and applies whatever the picture is of. The light
    match is about the pleasure of the screen agreeing with the window, and it
    gives way rather than emptying the set. It was written when three of the
    twenty eight pictures were night pictures and a machine that insisted
    would have shown the same three all winter. There are nine of forty now,
    so the rule bites less often, and it stays because the reason generalises:
    the brightness cap and the light match are applied one after the other,
    and two filters can always leave a band short however the set is built.
    """
    if not entries:
        return []
    start, end = SMALL_HOURS
    dark = when.hour >= start or when.hour < end
    pool = [e for e in entries
            if not (dark and e.get("luminance", 0.0) > NIGHT_CAP)] or entries
    # A picture whose light cannot be told does not clash with any hour, so it
    # is offered at all of them. Excluding it instead would retire three good
    # photographs for the sake of a field that is empty precisely because
    # there was nothing honest to put in it.
    return [e for e in pool if e.get("light") in (light, "")] or pool


def card_lines(entry: dict | None) -> dict[str, str]:
    """What the card can honestly say about this picture.

    Every value may be empty, and empty means the line is not drawn. A picture
    of nowhere in particular has a title and a sentence and nothing else, which
    is the whole of what is known about it.
    """
    if not entry:
        return {"title": "", "when": "", "note": "", "fact": ""}
    there, here = brand.local_times(entry.get("zone", ""))
    if there and here:
        when = C.CARD_TIMES.format(there=there, here=here)
    elif there:
        when = C.CARD_TIME_THERE.format(there=there)
    else:
        when = ""
    return {
        "title": entry.get("title", ""),
        "when": when,
        "note": entry.get("note", ""),
        "fact": entry.get("fact", ""),
    }


class PhotoCard(Gtk.Box):
    """What the picture is, where, and what time it is there.

    Bottom left, opposite the two pills, so the shade has a weight in each
    lower corner and the middle stays for the clock.

    The time where the picture was taken is the line worth defending. It costs
    two lines of text and it is the only thing on this screen that makes the
    photograph feel like a place rather than a texture: seeing that it is six
    in the morning in Namibia while you sign in at midnight is a small
    pleasure, and small pleasures are the entire difference between a product
    somebody made and a product somebody shipped.
    """

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class("aurade-photo-card")
        self.set_halign(Gtk.Align.START)
        self.set_valign(Gtk.Align.END)
        self.set_margin_start(20)
        self.set_margin_bottom(20)
        self.set_size_request(-1, -1)

        self.title = self._line("m3-title-small", wrap=True)
        self.when = self._line("m3-label-medium", dim=True)
        self.when.set_margin_top(2)
        self.note = self._line("m3-body-small", wrap=True, dim=True)
        self.note.set_margin_top(10)
        self.fact = self._line("m3-label-medium", wrap=True)
        self.fact.set_margin_top(8)
        for child in (self.title, self.when, self.note, self.fact):
            self.append(child)
        A.decorative(self)

    def _line(self, style: str, *, wrap: bool = False,
              dim: bool = False) -> Gtk.Label:
        widget = Gtk.Label(label="")
        widget.add_css_class(style)
        if dim:
            widget.add_css_class("dim-label")
        widget.set_xalign(0.0)
        widget.set_wrap(wrap)
        if wrap:
            widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            # A wrapped label asks for the width of its longest unbroken run,
            # so without a cap the longest fact in the set decides how wide
            # the card is and the card is then a different width per picture.
            widget.set_max_width_chars(38)
        widget.set_visible(False)
        return widget

    def show_picture(self, entry: dict | None) -> bool:
        """Fill the card in, and say whether there was anything to fill it with."""
        lines = card_lines(entry)
        for key, widget in (("title", self.title), ("when", self.when),
                            ("note", self.note), ("fact", self.fact)):
            widget.set_label(lines[key])
            widget.set_visible(bool(lines[key]))
        spoken = " ".join(lines[key] for key in ("title", "when", "note", "fact")
                          if lines[key])
        if spoken:
            A.described(self, C.CARD_LABEL, spoken)
        return bool(lines["title"])
