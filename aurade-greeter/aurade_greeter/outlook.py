"""Build short forecast summaries from the parsed weather data.

The functions here are pure: they take a report and return strings. Missing
values produce no sentence.
"""
from __future__ import annotations

import datetime as _dt

from . import copy as C
from . import weather as W

#: Below this a chance of rain is not worth a sentence. Twenty percent is the
#: threshold the National Weather Service itself uses before it mentions rain
#: in a forecast, which is as good a place to draw it as any.
LIKELY = 30

#: Millimetres below which "it rained" overstates it. A tenth of a millimetre
#: is a wet windscreen, not weather.
TRACE = 0.2

#: How far the pressure has to fall across the window before it is a front
#: rather than a wobble. Three hectopascals in six hours is the classic
#: threshold for a rapid fall and this is deliberately gentler, because the
#: sentence it produces is descriptive rather than a warning.
FALLING = W.PRESSURE_MOVE

#: And how far the wind has to swing. A front is a change of air mass, and the
#: wind turning through more than this is the clearest sign of one that a
#: forecast series contains.
VEER = 60

#: How much colder the morning has to be before the drop is worth saying.
COLDER = 5.0

#: Dew point above which air is muggy rather than merely humid. Twenty
#: degrees is where most people start describing it that way.
MUGGY = 20.0

#: Convective available potential energy, in joules per kilogram, above which
#: the air is unstable enough for storms whatever the forecast says.
UNSTABLE = 1500.0

#: How far from today's date to look for a normal, in days either side.
#: Fifteen gives a month long window, which is wide enough to smooth a single
#: freak year and narrow enough to still be about this time of year.
AROUND = 15

#: And how far a day has to be from its normal before that is worth saying.
UNUSUAL = 4.0


def _ahead(report: W.Report, here: _dt.datetime, hours: int = 24) -> list:
    """The hours still to come, up to a horizon."""
    edge = here + _dt.timedelta(hours=hours)
    out = []
    for hour in report.hours or []:
        if hour.at is None:
            continue
        try:
            if here <= hour.at <= edge:
                out.append(hour)
        except TypeError:
            # A naive timestamp against an aware one. Skipped rather than
            # crashed, because one badly stamped hour is not worth a panel.
            continue
    return out


def rain(report: W.Report, here: _dt.datetime, units: str = "c") -> str:
    """When it starts, how much, and when it stops.

    The chart underneath shows the chance as a band and says nothing about
    quantity, which is the half people actually decide on: a ninety percent
    chance of a tenth of a millimetre and a thirty percent chance of twenty
    look identical there.

    Only the next run is described. A day with rain at nine and again at six
    is two sentences and this is not the place for the second.
    """
    hours = _ahead(report, here)
    wet = [h for h in hours
           if (h.precipitation or 0) >= LIKELY
           or (h.amount is not None and h.amount >= TRACE)]
    if not wet:
        return ""
    start = wet[0]
    # The run, which ends at the first dry hour after it starts.
    run = []
    for hour in hours[hours.index(start):]:
        if hour not in wet and run:
            break
        if hour in wet:
            run.append(hour)
    total = sum(h.amount for h in run if h.amount is not None)
    frozen = sum(h.snow for h in run if h.snow is not None)
    ends = run[-1].at + _dt.timedelta(hours=1) if run[-1].at else None

    soon = start.at <= here + _dt.timedelta(minutes=45)
    kind = C.OUTLOOK_SNOW if frozen > 0 and frozen >= total * 0.5 \
        else C.OUTLOOK_RAIN
    if total >= TRACE:
        shape = C.OUTLOOK_RAIN_SOON_AMOUNT if soon else C.OUTLOOK_RAIN_AMOUNT
    else:
        shape = C.OUTLOOK_RAIN_SOON if soon else C.OUTLOOK_RAIN_ONLY
    body = shape.format(kind=kind, when=_oclock(start.at),
                        amount=W.precipitation_words(total, units))
    if ends is not None and len(run) > 1:
        body += " " + C.OUTLOOK_RAIN_ENDS.format(when=_oclock(ends))
    return body


def front(report: W.Report, here: _dt.datetime, units: str = "c") -> str:
    """A change of air mass, from the three signs a forecast series carries.

    Pressure falling, the wind turning, and the temperature dropping after it.
    One of those on its own is weather; all three together is a front, and it
    is the one piece of meteorology a person can feel coming and cannot read
    off a chart of temperatures.

    Deliberately conservative. Saying a front is coming when it is not is
    worse than saying nothing, because the sentence is the only part of this
    panel that claims to explain rather than report.
    """
    hours = _ahead(report, here, 18)
    pressures = [h.pressure for h in hours if h.pressure is not None]
    bearings = [h.bearing for h in hours if h.bearing is not None]
    temperatures = [h.temperature for h in hours if h.temperature is not None]
    if len(pressures) < 6 or len(bearings) < 6 or len(temperatures) < 6:
        return ""

    fall = pressures[0] - min(pressures)
    swing = max(abs((b - bearings[0] + 180) % 360 - 180) for b in bearings)
    drop = temperatures[0] - min(temperatures)
    if fall < FALLING or swing < VEER or drop < COLDER:
        return ""

    coldest = min(temperatures)
    at = hours[temperatures.index(coldest)]
    turned = bearings[-1]
    return C.OUTLOOK_FRONT.format(
        degrees=W.difference(drop, units),
        when=_oclock(at.at),
        direction=W.bearing_name(turned).lower())


def close(report: W.Report, here: _dt.datetime, units: str = "c") -> str:
    """The air itself: muggy, or unstable, or neither.

    Both are things a person notices and neither is on the chart. Instability
    is the more useful of the two, because it is the answer to "the forecast
    says clear, so why did it just thunder".
    """
    now = report.now
    hours = _ahead(report, here, 12)
    energy = [h.cape for h in hours if h.cape is not None]
    if energy and max(energy) >= UNSTABLE:
        return C.OUTLOOK_UNSTABLE
    if now.dew_point is not None and now.dew_point >= MUGGY:
        return C.OUTLOOK_MUGGY
    return ""


def against_normal(high: float | None, normal: float | None,
                   units: str = "c") -> str:
    """How today sits against the last thirty years of the same date.

    The single most human sentence available from any of this. A temperature
    is a fact; a temperature next to its normal is a judgement, and it is the
    judgement everybody makes for themselves badly.
    """
    if high is None or normal is None:
        return ""
    gap = high - normal
    if abs(gap) < UNUSUAL:
        return ""
    words = C.OUTLOOK_WARMER if gap > 0 else C.OUTLOOK_COLDER
    return words.format(degrees=W.difference(abs(gap), units))


def _oclock(moment) -> str:
    """An hour as somebody would say it, not as a clock shows it."""
    if moment is None:
        return ""
    hour = moment.hour
    if hour == 0:
        return C.OUTLOOK_MIDNIGHT
    if hour == 12:
        return C.OUTLOOK_MIDDAY
    said = hour % 12
    if hour < 12:
        return C.OUTLOOK_MORNING.format(hour=said)
    if hour < 18:
        return C.OUTLOOK_AFTERNOON.format(hour=said)
    return C.OUTLOOK_EVENING.format(hour=said)


def sentence(report: W.Report, here: _dt.datetime, units: str = "c",
             normal: float | None = None) -> str:
    """Everything that has something to say, joined.

    Order is by how soon it matters: rain first because it changes what
    somebody does in the next hour, then the front, then the air, then the
    comparison with normal, which is interesting rather than useful.
    """
    today = (report.days or [None])[0]
    parts = [
        rain(report, here, units),
        front(report, here, units),
        close(report, here, units),
        against_normal(getattr(today, "high", None), normal, units),
    ]
    return " ".join(part for part in parts if part)


#: The conditions this screen calls weather, from the same table the panel
#: draws from, so the line under the clock and the mark beside the temperature
#: can never disagree about whether it is raining.
SPELLS = W.SPELLS


def spell(report: W.Report, here: _dt.datetime):
    """What the sky is doing now, and when it stops.

    Returns the condition, the words for it, and the hour it ends, or nothing
    at all where the sky is doing nothing worth saying. Nothing is the common
    answer and the right one: a lock screen that announces "partly cloudy" has
    spent a line of somebody's attention on a fact they can get by looking out
    of a window.

    The words already carry the intensity, because the table they come from
    distinguishes drizzle from rain from heavy rain. There is no second field
    to compose, and composing one would produce "Heavy heavy rain".

    The end is the first hour that is not weather. Where the forecast runs out
    while it is still raining there is no honest end, and the caller is given
    nothing rather than the edge of the data dressed up as a forecast.
    """
    hours = _ahead(report, here)
    if not hours or hours[0].condition not in SPELLS:
        return None
    kind = hours[0].condition
    ends = None
    for hour in hours[1:]:
        if hour.condition not in SPELLS:
            ends = hour.at
            break
    return kind, W.WORDS.get(kind, ""), ends
