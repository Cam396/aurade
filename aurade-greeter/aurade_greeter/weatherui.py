"""The weather panel: a pill that opens into everything the sky is doing.

Two rules shaped this, and they pull against each other.

The first is that a login screen is not a weather app. Nobody came here for
the dew point. So the pill on the shelf says one thing, a mark and a
temperature, and everything else stays behind a press.

The second is that once somebody has pressed it, holding anything back is
just making them go and find it somewhere else. So what opens is not a
summary card. It is the hour by hour line, the week on one scale, the sun's
own day, and every reading either service publishes, laid out so the ones
people actually look for are the ones nearest the top.

What is deliberately not here is a forecast this program wrote. Where the
National Weather Service is the source, the paragraph on this panel is the
one a meteorologist at the local forecast office typed, unedited. A sentence
assembled from a condition code reads like a machine talking, and there is a
real human sentence available for free.
"""

from __future__ import annotations

import datetime as _dt

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from . import a11y as A  # noqa: E402
from . import copy as C  # noqa: E402
from . import tokens as T  # noqa: E402
from . import weather as W  # noqa: E402
from . import weatherdraw as D  # noqa: E402
from . import alerts as AL  # noqa: E402

try:  # pragma: no cover - present on every supported system
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]


def _column(spacing: int = 0) -> Gtk.Box:
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)


def _row(spacing: int = 0) -> Gtk.Box:
    return Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)


def _label(words: str, style: str = "m3-body-medium", *, wrap: bool = False,
           dim: bool = False) -> Gtk.Label:
    widget = Gtk.Label(label=words)
    widget.add_css_class(style)
    if dim:
        widget.add_css_class("dim-label")
    widget.set_wrap(wrap)
    if wrap:
        widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    widget.set_xalign(0.0)
    return widget


class Drawn(Gtk.DrawingArea):
    """A widget whose whole job is to hand `weatherdraw` a context.

    The font comes from the widget's own Pango context rather than from a
    constant, so a chart's internal labels follow the same typeface and the
    same text scale as every label beside it, including for somebody who
    asked the installer for two hundred percent text.
    """

    def __init__(self, height: int, width: int = -1) -> None:
        super().__init__()
        self.set_content_height(height)
        if width > 0:
            # A mark with a fixed size is drawn inside a square measured from
            # the smaller side, so a widget stretched taller than it is wide
            # draws its square at the top and the mark sits above where it
            # belongs. Centred in both directions, that cannot happen.
            self.set_content_width(width)
            self.set_hexpand(False)
            self.set_halign(Gtk.Align.CENTER)
            self.set_valign(Gtk.Align.CENTER)
        else:
            self.set_hexpand(True)
        self.set_can_focus(False)
        # Decorative by default, which is right for a mark sitting beside a
        # label that already says the number. It is wrong for a chart, and
        # `speak` is how the three charts opt out of it.
        self.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        self._dark = True
        self.colours = T.scheme(True)
        self.set_draw_func(self._on_draw)

    def set_dark(self, dark: bool) -> None:
        if dark != self._dark:
            self._dark = dark
            self.colours = T.scheme(dark)
            self.queue_draw()

    @property
    def font(self) -> Pango.FontDescription:
        context = self.get_pango_context()
        description = context.get_font_description()
        if description is None:
            description = Pango.FontDescription.from_string("Sans 11")
        return description

    def _on_draw(self, _area, cr, width: int, height: int) -> None:
        self.render(cr, float(width), float(height))

    def render(self, cr, width: float, height: float) -> None:  # pragma: no cover
        raise NotImplementedError


    def speak(self, label: str, description: str) -> None:
        """Stop being decorative and start saying what is drawn.

        The role changes as well as the text: a widget left as PRESENTATION
        is skipped whatever properties it carries, so setting a description
        on its own would have been a change that reads correct and does
        nothing at all.
        """
        try:
            self.set_accessible_role(Gtk.AccessibleRole.IMG)
        except Exception:  # noqa: BLE001 - decoration, never a traceback
            pass
        A.described(self, label, description)


class SkyMark(Drawn):
    """One condition, at whatever size it was asked for."""

    def __init__(self, size: int = 20) -> None:
        super().__init__(size, size)
        self.condition = W.CLOUDY
        self.daylight = True

    def show_sky(self, condition: str, daylight: bool) -> None:
        if (condition, daylight) != (self.condition, self.daylight):
            self.condition, self.daylight = condition, daylight
            self.queue_draw()

    def render(self, cr, width: float, height: float) -> None:
        size = min(width, height)
        cr.translate((width - size) / 2.0, (height - size) / 2.0)
        cr.scale(size / D.DESIGN, size / D.DESIGN)
        D.sky(cr, self.condition, self.daylight, self.colours)


class HoursChart(Drawn):
    def __init__(self) -> None:
        super().__init__(190)
        self.hours: list = []
        self.units = "c"
        self.zone = None

    def show_hours(self, hours: list, units: str, zone=None) -> None:
        self.hours, self.units, self.zone = hours, units, zone
        self.speak(C.WEATHER_HOURS_CHART, self._spoken())
        self.queue_draw()

    def _spoken(self) -> str:
        """The same readings the chart prints, in the order it prints them.

        Every third hour, and both ends of the range whatever falls where,
        because the coldest hour of the night is the reading somebody is
        listening for and a fixed stride will skip it about two thirds of the
        time. This is the rule the drawing uses for its own labels, applied
        to speech, so the two versions of the chart say the same thing.
        """
        rows = [h for h in self.hours if h.temperature is not None]
        if not rows:
            return C.WEATHER_SPOKEN_NOTHING
        keep = {0, len(rows) - 1}
        keep.add(min(range(len(rows)), key=lambda i: rows[i].temperature))
        keep.add(max(range(len(rows)), key=lambda i: rows[i].temperature))
        keep.update(range(0, len(rows), 3))
        said = [C.WEATHER_SPOKEN_HOUR.format(
                    time=_clock(rows[index].at, self.zone),
                    degrees=W.temperature(rows[index].temperature, self.units))
                for index in sorted(keep)]
        wet = [h for h in rows if (h.precipitation or 0) >= 40]
        if wet:
            said.append(C.WEATHER_SPOKEN_RAIN.format(
                chance=wet[0].precipitation, time=_clock(wet[0].at, self.zone)))
        return ". ".join(said)

    def render(self, cr, width: float, height: float) -> None:
        D.hours_chart(cr, width, height, self.hours, self.units,
                      self.colours, self.font, self.zone)


class DaysChart(Drawn):
    #: A row has to hold a name, a mark and a bar without either crowding the
    #: other, and this is the height at which it stops crowding.
    ROW = 30

    def __init__(self) -> None:
        super().__init__(self.ROW * 7)
        self.days: list = []
        self.names: list = []
        self.units = "c"
        self.current: float | None = None

    def show_days(self, days: list, names: list, units: str,
                  current: float | None) -> None:
        self.days, self.names = days, names
        self.units, self.current = units, current
        usable = usable_days(days)
        self.set_content_height(self.ROW * max(1, len(usable)))
        self.speak(C.WEATHER_DAYS_CHART, self._spoken(usable))
        self.queue_draw()

    def _spoken(self, usable: list) -> str:
        """Every row, named the way the row is named on the screen.

        Six rows is short enough to read in full, and a summary would leave
        out the one day somebody is actually planning around.
        """
        if not usable:
            return C.WEATHER_SPOKEN_NOTHING
        said = []
        for index, day in enumerate(usable):
            name = self.names[index] if index < len(self.names) else ""
            said.append(C.WEATHER_SPOKEN_DAY.format(
                name=name or "",
                condition=W.WORDS.get(day.condition, ""),
                low=W.temperature(day.low, self.units),
                high=W.temperature(day.high, self.units)))
        return ". ".join(said)

    def render(self, cr, width: float, height: float) -> None:
        D.days_chart(cr, width, height, self.days, self.units, self.colours,
                     self.font, self.current, self.names)


class SunChart(Drawn):
    def __init__(self) -> None:
        super().__init__(104)
        self.fraction: float | None = None
        self.altitude: float | None = None
        self.rise = ""
        self.set_ = ""

    def show_sun(self, fraction, rise: str, set_: str, altitude) -> None:
        self.fraction, self.rise, self.set_ = fraction, rise, set_
        self.altitude = altitude
        ends = [part for part in (rise, set_) if part]
        self.speak(C.WEATHER_SUN_CHART,
                   ". ".join(ends) if ends else C.WEATHER_SPOKEN_NOTHING)
        self.queue_draw()

    def render(self, cr, width: float, height: float) -> None:
        D.sun_arc(cr, width, height, self.fraction, self.colours, self.font,
                  self.rise, self.set_, self.altitude)


class CompassMark(Drawn):
    def __init__(self, size: int = 62) -> None:
        super().__init__(size, size)
        self.bearing: int | None = None

    def show_bearing(self, bearing: int | None) -> None:
        self.bearing = bearing
        self.queue_draw()

    def render(self, cr, width: float, height: float) -> None:
        D.compass(cr, min(width, height), self.bearing, self.colours, self.font)


class BarMark(Drawn):
    """A reading placed in the range it can take."""

    def __init__(self, kind: str = "level") -> None:
        super().__init__(14)
        self.kind = kind
        self.value: float | None = None
        self.low = 0.0
        self.high = 100.0
        self.role = "primary"

    def show_value(self, value, low: float = 0.0, high: float = 100.0,
                   role: str = "primary") -> None:
        self.value, self.low, self.high, self.role = value, low, high, role
        self.queue_draw()

    def render(self, cr, width: float, height: float) -> None:
        if self.kind == "uv":
            D.uv_bar(cr, width, height, self.value, self.colours)
        else:
            D.level_bar(cr, width, height, self.value, self.low, self.high,
                        self.colours, self.role)


class MoonMark(Drawn):
    def __init__(self, size: int = 42) -> None:
        super().__init__(size, size)
        self.lit = 0.0
        self.waxing = True

    def show_moon(self, lit: float, waxing: bool) -> None:
        self.lit, self.waxing = lit, waxing
        self.queue_draw()

    def render(self, cr, width: float, height: float) -> None:
        D.moon_disc(cr, min(width, height), self.lit, self.waxing, self.colours)


class Tile(Gtk.Box):
    """One reading, its name, its picture and the sentence that reads it.

    Every tile has the same three parts in the same order, because a grid of
    readings where each one is laid out to suit itself is a grid nobody can
    scan. The picture is the only part that differs.
    """

    def __init__(self, name: str, art: Gtk.Widget | None = None,
                 beside: bool = False) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class("aurade-weather-tile")
        self.set_hexpand(True)

        self.caption = _label(name.upper(), "m3-label-small", dim=True)
        self.caption.add_css_class("aurade-weather-caption")
        self.append(self.caption)

        body = _row(10) if beside else _column(2)
        body.set_margin_top(6)
        self.value = _label("--", "m3-title-medium")
        self.note = _label("", "m3-label-medium", dim=True)
        self.note.set_ellipsize(Pango.EllipsizeMode.END)

        if beside and art is not None:
            body.append(art)
            words = _column(0)
            words.set_valign(Gtk.Align.CENTER)
            words.append(self.value)
            words.append(self.note)
            body.append(words)
            self.append(body)
        else:
            if art is not None:
                art.set_margin_bottom(6)
                self.append(art)
                art.set_margin_top(4)
            body.append(self.value)
            body.append(self.note)
            self.append(body)
        self.art = art

    def say(self, value: str, note: str = "") -> None:
        self.value.set_label(value)
        self.note.set_label(note)
        self.note.set_visible(bool(note))
        A.described(self, self.caption.get_label().title(),
                    f"{value}. {note}" if note else value)


class Panel(Gtk.Box):
    """Everything behind the weather pill."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.report: W.Report | None = None
        self.units = "c"
        self.dark = True
        self._drawn: list[Drawn] = []
        self.on_refresh = None
        self._build()

    # -- construction ------------------------------------------------------

    def _remember(self, widget):
        if isinstance(widget, Drawn):
            self._drawn.append(widget)
        return widget

    def _rule(self) -> Gtk.Widget:
        line = Gtk.Separator()
        line.add_css_class("aurade-panel-rule")
        line.set_margin_top(12)
        line.set_margin_bottom(12)
        return line

    def _build(self) -> None:
        page = _column(0)
        # Wide enough that twelve hours can carry a label on every other
        # column and the week's bars have room to be bars rather than dashes.
        page.set_size_request(452, -1)
        page.set_margin_top(16)
        page.set_margin_bottom(16)
        page.set_margin_start(18)
        page.set_margin_end(18)

        head = _row(8)
        self.place = _label("", "m3-title-small")
        self.place.set_hexpand(True)
        self.place.set_ellipsize(Pango.EllipsizeMode.END)
        head.append(self.place)
        self.source = _label("", "m3-label-small", dim=True)
        self.source.set_valign(Gtk.Align.CENTER)
        head.append(self.source)
        page.append(head)

        hero = _row(14)
        hero.set_margin_top(10)
        self.mark = self._remember(SkyMark(64))
        self.mark.set_valign(Gtk.Align.CENTER)
        hero.append(self.mark)

        numbers = _column(0)
        numbers.set_valign(Gtk.Align.CENTER)
        numbers.set_hexpand(True)
        self.degrees = _label("--", "m3-display-small")
        numbers.append(self.degrees)
        self.condition = _label("", "m3-body-medium")
        numbers.append(self.condition)
        self.range = _label("", "m3-label-medium", dim=True)
        self.range.set_margin_top(2)
        numbers.append(self.range)
        hero.append(numbers)
        page.append(hero)

        # The forecaster's paragraph, where there is one. Hidden rather than
        # left empty, so the panel does not carry a blank block on a machine
        # outside the area the National Weather Service covers.
        # Warnings, above the paragraph, because an advisory in force now
        # outranks a forecast for this evening. One line each, in the colour
        # of its tier, and nothing here ever takes over the screen: the
        # louder tiers are a separate change and this one is deliberately the
        # quiet end of the feature.
        self.alerts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.alerts.set_visible(False)
        A.described(self.alerts, C.WEATHER_ALERTS)
        page.append(self.alerts)

        self.narrative = _label("", "m3-label-medium", wrap=True, dim=True)
        # A wrapped label asks for the width of its longest unbroken run, and
        # a forecaster's paragraph is one long run, so without this the label
        # decides how wide the whole panel is and the answer is six hundred
        # pixels. Capping the character count leaves the page's own size
        # request in charge of the width and the label wrapping into it.
        self.narrative.set_max_width_chars(34)
        self.narrative.set_margin_top(12)
        self.narrative.set_visible(False)
        page.append(self.narrative)

        page.append(self._rule())
        self.hours = self._remember(HoursChart())
        page.append(self.hours)

        page.append(self._rule())
        self.days = self._remember(DaysChart())
        page.append(self.days)

        page.append(self._rule())
        sun_head = _row(8)
        self.daylight = _label("", "m3-label-medium", dim=True)
        self.daylight.set_hexpand(True)
        sun_head.append(self.daylight)
        page.append(sun_head)
        self.sun = self._remember(SunChart())
        page.append(self.sun)

        page.append(self._rule())
        page.append(self._build_tiles())

        page.append(self._rule())
        foot = _row(8)
        self.updated = _label("", "m3-label-small", dim=True)
        self.updated.set_hexpand(True)
        self.updated.set_valign(Gtk.Align.CENTER)
        foot.append(self.updated)
        self.again = Gtk.Button(label=C.WEATHER_AGAIN)
        self.again.add_css_class("flat")
        self.again.connect("clicked", self._on_again)
        A.described(self.again, C.WEATHER_AGAIN, C.DESCRIBE_WEATHER_AGAIN)
        foot.append(self.again)
        page.append(foot)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        # Tall enough to hold the hero, the hours and the week without
        # scrolling on a laptop, short enough to fit a netbook screen with the
        # panel's own margins around it.
        scroller.set_max_content_height(620)
        scroller.set_propagate_natural_height(True)
        scroller.set_child(page)
        self.scroller = scroller
        self.page = page
        self.append(scroller)

    def _build_tiles(self) -> Gtk.Widget:
        grid = Gtk.Grid()
        grid.set_row_spacing(10)
        grid.set_column_spacing(10)
        grid.set_column_homogeneous(True)

        self.humidity_bar = self._remember(BarMark())
        self.humidity = Tile(C.WEATHER_HUMIDITY, self.humidity_bar)
        self.wind_dial = self._remember(CompassMark(58))
        self.wind = Tile(C.WEATHER_WIND, self.wind_dial, beside=True)
        self.uv_bar = self._remember(BarMark("uv"))
        self.ultraviolet = Tile(C.WEATHER_UV, self.uv_bar)
        self.pressure_bar = self._remember(BarMark())
        self.pressure = Tile(C.WEATHER_PRESSURE, self.pressure_bar)
        self.visibility_bar = self._remember(BarMark())
        self.visibility = Tile(C.WEATHER_VISIBILITY, self.visibility_bar)
        self.moon_disc = self._remember(MoonMark(40))
        self.moon = Tile(C.WEATHER_MOON, self.moon_disc, beside=True)

        for index, tile in enumerate((self.humidity, self.wind,
                                      self.ultraviolet, self.pressure,
                                      self.visibility, self.moon)):
            grid.attach(tile, index % 2, index // 2, 1, 1)
        self.tiles = (self.humidity, self.wind, self.ultraviolet,
                      self.pressure, self.visibility, self.moon)
        return grid

    # -- appearance --------------------------------------------------------

    def set_dark(self, dark: bool) -> None:
        self.dark = dark
        for widget in self._drawn:
            widget.set_dark(dark)

    def _on_again(self, _button) -> None:
        if self.on_refresh is not None:
            self.on_refresh()

    # -- filling it in -----------------------------------------------------

    def show_report(self, report: W.Report | None, units: str) -> None:
        self.units = units
        self.report = report
        if report is None or report.now.temperature is None:
            self.place.set_label(C.WEATHER_UNKNOWN)
            self.degrees.set_label("--")
            self.condition.set_label(C.WEATHER_NO_ANSWER)
            self.updated.set_label("")
            # Warnings still show, and this is not a detail. They come from a
            # different service to the readings, so "the forecast is not
            # answering" and "there is a tornado warning in force" are two
            # independent facts, and the first one silently swallowing the
            # second is the worst thing this panel could do.
            if report is not None:
                self._show_alerts(report, _dt.datetime.now(), None)
            else:
                self._show_alerts(W.Report(), _dt.datetime.now(), None)
            return

        zone = _zone_of(report)
        here = _dt.datetime.now(zone)
        now = report.now

        self.place.set_label(report.place or C.WEATHER)
        self.source.set_label(W.source_words(report.provider))
        self.mark.show_sky(now.condition, now.daylight)
        self.degrees.set_label(W.temperature(now.temperature, units))
        self.condition.set_label(now.summary or W.WORDS.get(now.condition, ""))

        parts = []
        if now.feels_like is not None:
            parts.append(C.WEATHER_FEELS.format(
                degrees=W.temperature(now.feels_like, units)))
        today = report.days[0] if report.days else None
        if today is not None and today.high is not None and today.low is not None:
            parts.append(C.WEATHER_RANGE.format(
                high=W.temperature(today.high, units),
                low=W.temperature(today.low, units)))
        self.range.set_label("   ".join(parts))

        self._show_alerts(report, here, zone)

        self.narrative.set_label(report.narrative)
        self.narrative.set_visible(bool(report.narrative))

        self.hours.show_hours(_from_now(report.hours, here), units, zone)
        drawn, named = day_rows(report.days, here)
        self.days.show_days(drawn, named, units, now.temperature)
        self._show_sun(report, here, zone)
        self._show_tiles(report, here)
        self.updated.set_label(W.since_words(report.age))

    def _show_alerts(self, report: W.Report, here: _dt.datetime, zone) -> None:
        """One line per warning, loudest first, in the colour of its tier.

        Rebuilt rather than updated, because the list changes shape rather
        than changing values: an alert expiring is a row leaving, not a row
        with different words in it.
        """
        child = self.alerts.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self.alerts.remove(child)
            child = following

        found = list(getattr(report, "alerts", None) or [])
        self.alerts.set_visible(bool(found))
        for alert in found:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.add_css_class("aurade-alert")
            row.add_css_class(f"aurade-alert-{AL.tier(alert)}")
            words = _label(alert.event, "m3-label-large", wrap=True)
            words.set_hexpand(True)
            words.set_xalign(0.0)
            row.append(words)
            when = ""
            if alert.expires is not None:
                when = C.WEATHER_ALERT_UNTIL.format(
                    time=_clock(alert.expires, zone))
            edge = _label(when or C.WEATHER_ALERT_NOW, "m3-label-medium",
                          dim=True)
            edge.set_valign(Gtk.Align.CENTER)
            row.append(edge)
            # Read out as one sentence rather than as two labels, and the
            # instruction goes with it: what to do is the half that matters
            # and it is the half that is not on the face.
            A.described(row, alert.event,
                        " ".join(part for part in
                                 (alert.headline, alert.instruction) if part))
            self.alerts.append(row)

    def _show_sun(self, report: W.Report, here: _dt.datetime, zone) -> None:
        rise, set_ = W.sun_times(report.latitude, report.longitude, here)
        altitude = W.sun_altitude(report.latitude, report.longitude, here)
        fraction = W.daylight_fraction(rise, set_, here)
        self.sun.show_sun(fraction,
                          _clock(rise, zone), _clock(set_, zone), altitude)
        if rise is None or set_ is None:
            self.daylight.set_label(C.WEATHER_NO_SUNSET)
            return
        minutes = int((set_ - rise).total_seconds() // 60)
        length = C.WEATHER_DAYLIGHT.format(
            hours=minutes // 60, minutes=minutes % 60)
        if here < rise:
            length += "   " + C.WEATHER_SUNRISE.format(time=_clock(rise, zone))
        elif here < set_:
            left = int((set_ - here).total_seconds() // 60)
            length += "   " + C.WEATHER_SUNSET_IN.format(
                hours=left // 60, minutes=left % 60)
        else:
            length += "   " + C.WEATHER_AFTER_DARK
        self.daylight.set_label(length)

    def _show_tiles(self, report: W.Report, here: _dt.datetime) -> None:
        now = report.now
        units = self.units

        self.humidity_bar.show_value(now.humidity, 0, 100)
        self.humidity.say(
            "--" if now.humidity is None else f"{now.humidity}%",
            "" if now.dew_point is None else C.WEATHER_DEW.format(
                degrees=W.temperature(now.dew_point, units)))

        self.wind_dial.show_bearing(now.bearing)
        gust = ("" if now.gust is None
                else C.WEATHER_GUST.format(speed=W.wind_words(now.gust, units)))
        blowing = W.bearing_name(now.bearing)
        self.wind.say(W.wind_words(now.wind, units),
                      gust or (C.WEATHER_FROM.format(direction=blowing)
                               if blowing else ""))

        today = report.days[0] if report.days else None
        index = today.ultraviolet if today else None
        self.uv_bar.show_value(index)
        self.ultraviolet.say("--" if index is None else f"{index:.0f}",
                             W.ultraviolet_note(index))

        self.pressure_bar.show_value(now.pressure, 960.0, 1050.0, "tertiary")
        self.pressure.say(W.pressure_words(now.pressure, units),
                          _pressure_note(now.pressure))

        # Twenty kilometres is where every service stops counting, so that is
        # the top of the scale rather than a number picked to look right.
        self.visibility_bar.show_value(now.visibility, 0.0, 20.0, "tertiary")
        self.visibility.say(W.distance_words(now.visibility, units),
                            _visibility_note(now.visibility, units))

        name, lit = W.moon(here)
        # Waxing is the first half of the cycle, which is also the half where
        # tomorrow is brighter than today.
        _, tomorrow = W.moon(here + _dt.timedelta(days=1))
        self.moon_disc.show_moon(lit, tomorrow >= lit)
        self.moon.say(name, C.WEATHER_MOON_LIT.format(percent=int(round(lit * 100))))


# -- small conversions the panel needs --------------------------------------


def _zone_of(report: W.Report):
    if report.zone and ZoneInfo is not None:
        try:
            return ZoneInfo(report.zone)
        except Exception:  # noqa: BLE001 - a bad zone name is not fatal
            pass
    return _dt.datetime.now().astimezone().tzinfo


def _clock(moment, zone) -> str:
    if moment is None:
        return ""
    return moment.astimezone(zone).strftime("%-I:%M %p")


def _from_now(hours: list, here: _dt.datetime) -> list:
    """The forecast from this hour on.

    A cached answer is still worth drawing an hour later, but not from the
    hour it was fetched in: the first column says "Now", and it has to be.
    """
    edge = here - _dt.timedelta(minutes=59)
    ahead = []
    for hour in hours:
        moment = hour.at
        if moment is None:
            continue
        # A cache written by an older greeter, or a service that changed its
        # mind about offsets, must not take the panel down over a comparison.
        if (moment.tzinfo is None) != (edge.tzinfo is None):
            return hours
        if moment >= edge:
            ahead.append(hour)
    return ahead or hours


def day_rows(days: list, here: _dt.datetime) -> tuple[list, list[str]]:
    """The rows to draw, and the names to write on them. One call, one list.

    These were two calls, and the caller made them against two different
    lists: the names from everything the service sent, the rows from what
    could actually be drawn. Every evening the two lists differed by one and
    the whole week shifted under its own labels.

    They are returned together now so that there is no second list to pass by
    mistake, and `weather_test.py` holds them to being the same length and to
    naming the day each row actually carries.
    """
    drawn = usable_days(days)
    return drawn, day_names(drawn, here)


def usable_days(days: list) -> list:
    """The days that can be drawn as a row, which is not all of them.

    A row is a name, a low, a high and a bar between them, so a period with no
    high cannot be one. The National Weather Service returns exactly that
    every evening: its first period becomes `Tonight`, which has a low and no
    high because the high already happened.

    This existed twice, in the two places that need it, and they disagreed
    about when to apply it. `weatherdraw` dropped the unusable rows before
    drawing and the panel named the list before dropping them, so from about
    six in the evening until midnight every row on the panel carried the name
    of the row above it: Friday's forecast under `Today`, Saturday's under
    `Tomorrow`, and so on to the bottom. Now there is one filter and the names
    are taken from what it returns.
    """
    return [day for day in days
            if day.high is not None and day.low is not None]


def day_names(days: list, here: _dt.datetime) -> list[str]:
    """Today, Tomorrow, then weekdays.

    The National Weather Service names its own periods, and its names are
    good ("This Afternoon", "Thursday Night"), but they are names for halves
    of a day and these rows are days. So the rows are named here, the same
    way for either service, and "Today" and "Tomorrow" are spelled out
    because counting forward from a weekday name is work nobody should do at
    a login screen.
    """
    names = []
    for index, day in enumerate(days):
        if day.date is None:
            names.append(day.name or "")
            continue
        delta = (day.date - here.date()).days
        if delta <= 0:
            names.append(C.WEATHER_TODAY)
        elif delta == 1:
            names.append(C.WEATHER_TOMORROW)
        else:
            names.append(day.date.strftime("%A"))
    return names


def _pressure_note(value: float | None) -> str:
    """What a barometer reading means, for the many people who do not know.

    A number with no scale beside it is trivia. These are the standard
    aviation and marine bands, which is where the numbers come from.
    """
    if value is None:
        return ""
    if value < 1000.0:
        return C.WEATHER_PRESSURE_LOW
    if value > 1022.0:
        return C.WEATHER_PRESSURE_HIGH
    return C.WEATHER_PRESSURE_NORMAL


def _visibility_note(value: float | None, units: str) -> str:
    if value is None:
        return ""
    if value < 1.0:
        return C.WEATHER_VISIBILITY_POOR
    if value < 5.0:
        return C.WEATHER_VISIBILITY_FAIR
    return C.WEATHER_VISIBILITY_GOOD
