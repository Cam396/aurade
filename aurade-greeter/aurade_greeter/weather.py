"""Fetch and parse weather data for the greeter.

The service adapters and calculations are kept separate from the UI so cached
responses and recorded forecasts can be tested without a display.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request

# Keep weather labels in the greeter's shared translation table.
from .copy import _  # noqa: E402
from dataclasses import dataclass, field

# The NWS requires a descriptive user agent.
AGENT = os.environ.get(
    "AURADE_WEATHER_AGENT",
    "AuraDE-greeter/1.0 (https://github.com/aurade/aurade)")

# Cache the last good response so the panel can start without a network.
CACHE = os.environ.get(
    "AURADE_WEATHER_CACHE", "/var/cache/aurade-greeter/weather.json")

#: How long an answer is current, and how long a stale one is still worth
#: showing. Past FRESH the panel refetches; past STALE it stops claiming to
#: know. Between the two it shows what it has and says how old it is, because
#: an hour old temperature with its age on it is more use than a blank tile.
FRESH = 900
STALE = 6 * 3600

#: No request may hang. The greeter runs before anybody has signed in, on a
#: machine whose network may be the reason they are stuck at this screen.
TIMEOUT = 8.0

#: The vocabulary this product uses for the sky. Both services are translated
#: into it, so one drawn mark and one sentence serve either source and a
#: machine that falls back mid session does not change its language.
CLEAR = "clear"
MOSTLY_CLEAR = "mostly-clear"
PARTLY = "partly-cloudy"
CLOUDY = "cloudy"
OVERCAST = "overcast"
FOG = "fog"
DRIZZLE = "drizzle"
RAIN = "rain"
HEAVY_RAIN = "heavy-rain"
FREEZING = "freezing-rain"
SLEET = "sleet"
SNOW = "snow"
HEAVY_SNOW = "heavy-snow"
THUNDER = "thunder"
HAIL = "hail"
WIND = "wind"
HAZE = "haze"

CONDITIONS = (
    CLEAR, MOSTLY_CLEAR, PARTLY, CLOUDY, OVERCAST, FOG, DRIZZLE, RAIN,
    HEAVY_RAIN, FREEZING, SLEET, SNOW, HEAVY_SNOW, THUNDER, HAIL, WIND, HAZE)

#: Plain words for each, in the installer's key: what it is, not how it feels.
WORDS = {
    CLEAR: _("Clear"),
    MOSTLY_CLEAR: _("Mostly clear"),
    PARTLY: _("Partly cloudy"),
    CLOUDY: _("Cloudy"),
    OVERCAST: _("Overcast"),
    FOG: _("Fog"),
    DRIZZLE: _("Drizzle"),
    RAIN: _("Rain"),
    HEAVY_RAIN: _("Heavy rain"),
    FREEZING: _("Freezing rain"),
    SLEET: _("Sleet"),
    SNOW: _("Snow"),
    HEAVY_SNOW: _("Heavy snow"),
    THUNDER: _("Thunderstorms"),
    HAIL: _("Hail"),
    WIND: _("Windy"),
    HAZE: _("Haze"),
}

#: The conditions worth a line on a locked screen.
#:
#: A clear sky is not an event and neither is a cloud. What belongs here is
#: everything somebody would put a coat on for, or wait out, or drive slower
#: in, which is also exactly the set that ends: the line says when it stops
#: and there is no answer to that for "partly cloudy".
SPELLS = (FOG, DRIZZLE, RAIN, HEAVY_RAIN, FREEZING, SLEET, SNOW, HEAVY_SNOW,
          THUNDER, HAIL)


#: World Meteorological Organization present weather codes, which is what
#: Open-Meteo speaks. Anything unlisted falls through to cloudy, because an
#: unknown sky is more likely to be dull than to be clear.
WMO = {
    0: CLEAR, 1: MOSTLY_CLEAR, 2: PARTLY, 3: OVERCAST,
    45: FOG, 48: FOG,
    51: DRIZZLE, 53: DRIZZLE, 55: DRIZZLE,
    56: FREEZING, 57: FREEZING,
    61: RAIN, 63: RAIN, 65: HEAVY_RAIN,
    66: FREEZING, 67: FREEZING,
    71: SNOW, 73: SNOW, 75: HEAVY_SNOW, 77: SNOW,
    80: RAIN, 81: RAIN, 82: HEAVY_RAIN,
    85: SNOW, 86: HEAVY_SNOW,
    95: THUNDER, 96: HAIL, 99: HAIL,
}

#: The token the NWS puts in its icon URL, which is the only machine readable
#: statement of condition in a forecast period. `wind_` prefixes are stripped
#: before the lookup: they qualify the sky rather than replace it.
NWS_SKY = {
    "skc": CLEAR, "few": MOSTLY_CLEAR, "sct": PARTLY, "bkn": CLOUDY,
    "ovc": OVERCAST, "fog": FOG, "haze": HAZE, "smoke": HAZE, "dust": HAZE,
    "rain": RAIN, "rain_showers": RAIN, "rain_showers_hi": RAIN,
    "drizzle": DRIZZLE,
    "fzra": FREEZING, "rain_fzra": FREEZING, "snow_fzra": FREEZING,
    "sleet": SLEET, "rain_sleet": SLEET, "snow_sleet": SLEET,
    "rain_snow": SLEET,
    "snow": SNOW, "blizzard": HEAVY_SNOW,
    "tsra": THUNDER, "tsra_sct": THUNDER, "tsra_hi": THUNDER,
    "tornado": THUNDER, "hurricane": THUNDER, "tropical_storm": THUNDER,
    "hot": CLEAR, "cold": CLEAR, "wind": WIND,
}

#: Ultraviolet, in the World Health Organization's bands. The words are theirs
#: and are not improved on here, because somebody who has heard "very high"
#: from a forecast on the radio should meet the same phrase on their screen.
UV_BANDS = ((3, _("Low")), (6, _("Moderate")), (8, _("High")),
            (11, _("Very high")))

COMPASS = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")

#: The same sixteen points as words. A tile that says "From the SSW" has made
#: somebody decode an abbreviation to learn something a word would have told
#: them, and the abbreviation exists for instrument dials, not for sentences.
COMPASS_WORDS = (
    _("north"), _("north-northeast"), _("northeast"), _("east-northeast"),
    _("east"), _("east-southeast"), _("southeast"), _("south-southeast"),
    _("south"), _("south-southwest"), _("southwest"), _("west-southwest"),
    _("west"), _("west-northwest"), _("northwest"), _("north-northwest"))

#: The moon, in the eight phases anybody names. Fractions are of the synodic
#: month measured from new.
#: Each phase carries a key as well as its words. The key is what code
#: compares against and never moves; the words are what a person reads and
#: are translated.
#:
#: `shade.py` used to test `name == "Full moon"` against the display string,
#: which worked exactly as long as nobody translated it. On a French machine
#: the full moon occasion would simply have stopped appearing, silently, with
#: nothing in any log and no test that could see it.
MOON_PHASES = (
    (0.02, "new", _("New moon")),
    (0.24, "waxing-crescent", _("Waxing crescent")),
    (0.28, "first-quarter", _("First quarter")),
    (0.48, "waxing-gibbous", _("Waxing gibbous")),
    (0.52, "full", _("Full moon")),
    (0.73, "waning-gibbous", _("Waning gibbous")),
    (0.77, "last-quarter", _("Last quarter")),
    (0.98, "waning-crescent", _("Waning crescent")),
    (1.01, "new", _("New moon")))

#: A known new moon, to count synodic months from: 2000-01-06 18:14 UTC.
MOON_EPOCH = 947182440.0
SYNODIC = 29.530588853 * 86400.0


# -- the shape of an answer -------------------------------------------------


@dataclass
class Now:
    """What it is like outside at this moment."""

    temperature: float | None = None
    feels_like: float | None = None
    humidity: int | None = None
    dew_point: float | None = None
    wind: float | None = None
    gust: float | None = None
    bearing: int | None = None
    pressure: float | None = None
    visibility: float | None = None
    cloud: int | None = None
    condition: str = CLOUDY
    daylight: bool = True
    #: The service's own phrase for the sky, where it has one worth keeping.
    summary: str = ""


@dataclass
class Hour:
    at: _dt.datetime | None = None
    temperature: float | None = None
    condition: str = CLOUDY
    #: The chance of rain, as a percentage.
    precipitation: int | None = None
    daylight: bool = True
    #: And how much, in millimetres, which is a different question. A ninety
    #: percent chance of a tenth of a millimetre and a thirty percent chance
    #: of twenty are both worth saying and neither is what the other says.
    amount: float | None = None
    #: What kind, so "rain" and "snow" are not both called precipitation.
    rain: float | None = None
    snow: float | None = None
    #: Pressure at sea level, in hectopascals. The barometer's meaning is its
    #: direction and a single reading has none, so it is kept per hour.
    pressure: float | None = None
    #: Wind, for the veer that gives a front away.
    wind: float | None = None
    bearing: int | None = None
    #: Convective available potential energy, which is thunderstorm fuel and
    #: the reason a storm can appear on an afternoon forecast to be clear.
    cape: float | None = None


@dataclass
class Day:
    date: _dt.date | None = None
    name: str = ""
    high: float | None = None
    low: float | None = None
    condition: str = CLOUDY
    precipitation: int | None = None
    ultraviolet: float | None = None


@dataclass
class Report:
    """One complete answer, from whichever service gave it."""

    place: str = ""
    provider: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    zone: str = ""
    taken: float = 0.0
    now: Now = field(default_factory=Now)
    hours: list[Hour] = field(default_factory=list)
    days: list[Day] = field(default_factory=list)
    #: The forecaster's paragraph, where the service employs forecasters.
    narrative: str = ""
    quality: int | None = None
    #: The average high for today's date here, over the last ten years.
    #: Filled by the caller, like the alerts, and for the same reason: it
    #: comes from a different service to the forecast.
    normal: float | None = None

    #: The air, from Open-Meteo's air quality service. Filled by the caller
    #: like the normals and the alerts, and for the same reason: it is a
    #: different request to a different endpoint and losing it must never lose
    #: the temperature.
    air_index: int | None = None
    air_pm: float | None = None
    #: Warnings and advisories in force here, already gated and ordered.
    #:
    #: Filled by the caller rather than by `fetch`, because alerts come from
    #: one service and the rest of this can come from either, and folding the
    #: two together would make a module that is careful about provenance stop
    #: being careful about it.
    alerts: list = field(default_factory=list)

    @property
    def age(self) -> float:
        return max(0.0, time.time() - self.taken)

    @property
    def fresh(self) -> bool:
        return self.age < FRESH

    @property
    def usable(self) -> bool:
        return self.taken > 0 and self.age < STALE and self.now.temperature is not None


# -- talking to a service ---------------------------------------------------


def _get(url: str, timeout: float = TIMEOUT) -> dict:
    """One request, one answer, no redirect to anywhere unexpected."""
    request = urllib.request.Request(url, headers={
        "User-Agent": AGENT,
        "Accept": "application/geo+json, application/json",
    })
    with urllib.request.urlopen(request, timeout=timeout) as answer:  # noqa: S310
        if answer.status != 200:
            raise OSError(f"{url} answered {answer.status}")
        payload = answer.read(2 * 1024 * 1024)
    return json.loads(payload.decode("utf-8", errors="replace"))


def _number(value) -> float | None:
    """A measurement, or nothing, without ever raising over a null."""
    if isinstance(value, dict):
        value = value.get("value")
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _percent(value) -> int | None:
    number = _number(value)
    if number is None:
        return None
    return max(0, min(100, int(round(number))))


def _moment(text: str) -> _dt.datetime | None:
    if not text:
        return None
    stamp = text.strip().replace("Z", "+00:00")
    try:
        return _dt.datetime.fromisoformat(stamp)
    except ValueError:
        return None


def sky_from_icon(icon: str) -> tuple[str, bool]:
    """The condition and whether it is daylight, out of an NWS icon URL.

    The URL looks like `.../icons/land/day/tsra,80?size=medium`, and the two
    facts in it are the only structured statement of condition the forecast
    endpoint makes. Everything else in a period is prose.
    """
    if not icon:
        return CLOUDY, True
    path = urllib.parse.urlsplit(icon).path
    parts = [p for p in path.split("/") if p]
    daylight = "night" not in parts
    token = parts[-1] if parts else ""
    token = token.split(",")[0].strip().lower()
    windy = token.startswith("wind_")
    if windy:
        token = token[len("wind_"):]
    condition = NWS_SKY.get(token)
    if condition is None:
        condition = WIND if windy else CLOUDY
    return condition, daylight


def sky_from_code(code) -> str:
    number = _number(code)
    if number is None:
        return CLOUDY
    return WMO.get(int(number), CLOUDY)


# -- the National Weather Service -------------------------------------------


def from_nws(latitude: float, longitude: float, get=_get,
             units: str = "c") -> Report:
    """The United States forecast, as the office that issued it wrote it."""
    point = get(f"https://api.weather.gov/points/{latitude:.4f},{longitude:.4f}")
    props = point.get("properties", {})
    near = props.get("relativeLocation", {}).get("properties", {})
    city = str(near.get("city") or "").strip()
    state = str(near.get("state") or "").strip()
    report = Report(
        place=", ".join(p for p in (city, state) if p),
        provider="nws",
        latitude=latitude,
        longitude=longitude,
        zone=str(props.get("timeZone") or ""),
        taken=time.time(),
    )

    hourly = get(str(props["forecastHourly"]) + "?units=si")
    periods = hourly.get("properties", {}).get("periods", [])
    for period in periods[:24]:
        condition, daylight = sky_from_icon(str(period.get("icon") or ""))
        report.hours.append(Hour(
            at=_moment(str(period.get("startTime") or "")),
            temperature=_number(period.get("temperature")),
            condition=condition,
            precipitation=_percent(period.get("probabilityOfPrecipitation")),
            daylight=bool(period.get("isDaytime", daylight)),
        ))
    if periods:
        first = periods[0]
        condition, daylight = sky_from_icon(str(first.get("icon") or ""))
        report.now = Now(
            temperature=_number(first.get("temperature")),
            humidity=_percent(first.get("relativeHumidity")),
            dew_point=_number(first.get("dewpoint")),
            wind=_speed(str(first.get("windSpeed") or "")),
            bearing=_bearing_of(str(first.get("windDirection") or "")),
            condition=condition,
            daylight=bool(first.get("isDaytime", daylight)),
            summary=str(first.get("shortForecast") or "").strip(),
        )

    # The daily response carries the meteorologist's prose as well as the
    # numbers, and it renders that prose in whichever system was asked for.
    # So this one request follows the reader, and `_celsius` puts the numbers
    # back on the module's own scale. The hourly request above stays SI
    # because nothing in it is a sentence.
    daily = get(str(props["forecast"])
                + ("?units=us" if units == "f" else "?units=si"))
    report.days = _nws_days(daily.get("properties", {}).get("periods", []))
    if daily.get("properties", {}).get("periods"):
        report.narrative = str(
            daily["properties"]["periods"][0].get("detailedForecast") or "").strip()

    # An observation is a reading from an instrument; a forecast period is a
    # prediction about six hours. Where a station nearby has reported, its
    # numbers replace the predicted ones, because the panel says "now".
    try:
        _observe(report, str(props["observationStations"]), get)
    except (OSError, KeyError, ValueError, json.JSONDecodeError):
        pass
    return report


def _celsius(value: float | None, unit: str) -> float | None:
    """A National Weather Service temperature, in Celsius whatever it arrived in.

    Each period states its own `temperatureUnit`, which matters because the
    daily forecast is now requested in whichever system the person is
    reading. The prose in that response is rendered to match, and the prose
    is the whole reason: asked in SI it says "a low around 26" in the middle
    of a panel that is otherwise Fahrenheit.
    """
    if value is None:
        return None
    return (value - 32.0) * 5.0 / 9.0 if unit.upper() == "F" else value


def _nws_days(periods: list) -> list[Day]:
    """Twelve hour periods folded into days.

    The NWS forecasts in halves of a day and names them, so a run reads
    "This Afternoon, Tonight, Thursday, Thursday Night". A day's high comes
    from its daytime half and its low from the night that follows, which is
    how the forecast itself is constructed rather than a guess made here.
    """
    days: dict[_dt.date, Day] = {}
    order: list[_dt.date] = []
    for period in periods:
        start = _moment(str(period.get("startTime") or ""))
        if start is None:
            continue
        daytime = bool(period.get("isDaytime"))
        # A night period belongs to the day it started on, so "Wednesday
        # Night" is Wednesday's low rather than Thursday's.
        key = start.date()
        if key not in days:
            days[key] = Day(date=key, name=str(period.get("name") or ""))
            order.append(key)
        day = days[key]
        temperature = _celsius(_number(period.get("temperature")),
                               str(period.get("temperatureUnit") or ""))
        chance = _percent(period.get("probabilityOfPrecipitation"))
        if daytime:
            day.high = temperature
            day.name = str(period.get("name") or day.name)
            condition, _ = sky_from_icon(str(period.get("icon") or ""))
            day.condition = condition
        else:
            day.low = temperature
            if day.high is None:
                condition, _ = sky_from_icon(str(period.get("icon") or ""))
                day.condition = condition
        if chance is not None:
            day.precipitation = max(day.precipitation or 0, chance)
    return [days[key] for key in order]


def _observe(report: Report, stations_url: str, get) -> None:
    listing = get(stations_url)
    features = listing.get("features", [])
    if not features:
        return
    station = features[0].get("properties", {}).get("stationIdentifier")
    if not station:
        return
    latest = get(
        f"https://api.weather.gov/stations/{urllib.parse.quote(str(station))}"
        "/observations/latest")
    seen = latest.get("properties", {})
    now = report.now
    for attribute, key in (
            ("temperature", "temperature"),
            ("dew_point", "dewpoint"),
            ("humidity", "relativeHumidity"),
            ("wind", "windSpeed"),
            ("gust", "windGust"),
            ("pressure", "barometricPressure"),
            ("visibility", "visibility"),
    ):
        value = _number(seen.get(key))
        if value is None:
            continue
        if key == "barometricPressure":
            value = value / 100.0          # pascals as the rest of the world reads them
        elif key == "visibility":
            value = value / 1000.0         # metres to kilometres
        elif key == "relativeHumidity":
            value = max(0, min(100, int(round(value))))
        setattr(now, attribute, value)
    bearing = _number(seen.get("windDirection"))
    if bearing is not None:
        now.bearing = int(round(bearing)) % 360

    # And the hourly chart's first column, which is also labelled now.
    #
    # It came from the gridpoint forecast and the headline came from this
    # station, and on a San Antonio evening they were eight degrees apart
    # on the same panel: 80 at the top and 88 in the first column of the
    # chart underneath it. Both were right about their own source and the
    # panel was wrong as a whole.
    #
    # The measurement wins, because the forecast for the current hour is a
    # prediction of a thing an instrument has already reported.
    if report.hours and now.temperature is not None:
        report.hours[0].temperature = now.temperature
    for key in ("heatIndex", "windChill"):
        felt = _number(seen.get(key))
        if felt is not None:
            now.feels_like = felt
            break
    text = str(seen.get("textDescription") or "").strip()
    if text:
        now.summary = text


def _speed(text: str) -> float | None:
    """`"19 km/h"` and `"10 to 15 mph"` both become kilometres per hour."""
    if not text:
        return None
    digits = ""
    numbers = []
    for character in text:
        if character.isdigit() or character == ".":
            digits += character
        elif digits:
            numbers.append(digits)
            digits = ""
    if digits:
        numbers.append(digits)
    if not numbers:
        return None
    try:
        # A range forecasts the stronger end, which is the one worth dressing
        # for and the one every forecast headline quotes.
        value = max(float(n) for n in numbers)
    except ValueError:
        return None
    if "mph" in text.lower():
        value *= 1.609344
    return value


def _bearing_of(letters: str) -> int | None:
    letters = letters.strip().upper()
    if letters in COMPASS:
        return int(round(COMPASS.index(letters) * 22.5)) % 360
    return None


# -- Open-Meteo -------------------------------------------------------------

OPEN_METEO_CURRENT = (
    "temperature_2m,relative_humidity_2m,apparent_temperature,is_day,"
    "precipitation,weather_code,cloud_cover,pressure_msl,wind_speed_10m,"
    "wind_direction_10m,wind_gusts_10m,visibility")
OPEN_METEO_HOURLY = (
    "temperature_2m,weather_code,precipitation_probability,is_day,"
    "precipitation,rain,showers,snowfall,pressure_msl,"
    "wind_speed_10m,wind_direction_10m,cape")
OPEN_METEO_DAILY = (
    "weather_code,temperature_2m_max,temperature_2m_min,uv_index_max,"
    "precipitation_probability_max")


#: How many past years the normal is averaged over, and how many days either
#: side of the date. Ten years is not the thirty a climatologist means by a
#: normal, and this does not call it one anywhere a user can see: the sentence
#: says "usual for the date", which is what ten years of the same fortnight
#: honestly supports.
#:
#: One request covers all of it. Ten years of daily maxima for one point is
#: sixty four kilobytes and under a second, which is the whole reason this is
#: affordable on a login screen at all.
NORMAL_YEARS = 10
NORMAL_WINDOW = 15


def _apart(one: _dt.date, two: _dt.date) -> int:
    """Days between two dates ignoring their years, the short way round.

    By day of the year rather than by rewriting one date into the other's
    year, because the twenty ninth of February cannot be rewritten into most
    years and a normal should not fail every fourth winter.
    """
    gap = abs(one.timetuple().tm_yday - two.timetuple().tm_yday)
    return min(gap, 365 - gap)


#: Answers already given, because a normal for a date and a place does not
#: change and the request behind it is the slowest thing this module makes.
#: In memory only: a login screen runs for weeks and this misses once a day,
#: and a value on disk would have to be invalidated by something.
_NORMALS: dict = {}


def normal_high(latitude: float, longitude: float, when: _dt.date,
                get=_get) -> float | None:
    """The average high for this date and place, from the last ten years.

    A temperature is a fact. A temperature next to its normal is a judgement,
    and it is the judgement everybody makes for themselves badly: nobody
    remembers what late August is supposed to be like, and the difference
    between a warm day and an unusually warm one is the only part of a
    forecast that is ever surprising.

    A fortnight either side of the date, so a single freak year cannot carry
    it and the answer is still about this time of year.
    """
    key = (round(latitude, 2), round(longitude, 2), when.month, when.day)
    if key in _NORMALS:
        return _NORMALS[key]
    last = when.year - 1
    query = urllib.parse.urlencode({
        "latitude": f"{latitude:.4f}",
        "longitude": f"{longitude:.4f}",
        "start_date": f"{last - NORMAL_YEARS + 1}-01-01",
        "end_date": f"{last}-12-31",
        "daily": "temperature_2m_max",
        "timezone": "auto",
    })
    answer = get("https://archive-api.open-meteo.com/v1/archive?" + query)
    daily = answer.get("daily") or {}
    stamps = daily.get("time") or []
    highs = daily.get("temperature_2m_max") or []
    seen = []
    for stamp, value in zip(stamps, highs):
        number = _number(value)
        if number is None:
            continue
        moment = _moment(str(stamp))
        if moment is None:
            continue
        if _apart(moment.date(), when) <= NORMAL_WINDOW:
            seen.append(number)
    if len(seen) < NORMAL_YEARS:
        # Fewer readings than years means the archive is thin here, and an
        # average of three days is not a normal. Remembered as nothing, so a
        # thin place is not asked about again every hour.
        _NORMALS[key] = None
        return None
    _NORMALS[key] = sum(seen) / len(seen)
    return _NORMALS[key]


def from_open_meteo(latitude: float, longitude: float, get=_get,
                    place: str = "") -> Report:
    """Everywhere else, and the ultraviolet index everywhere."""
    query = urllib.parse.urlencode({
        "latitude": f"{latitude:.4f}",
        "longitude": f"{longitude:.4f}",
        "current": OPEN_METEO_CURRENT,
        "hourly": OPEN_METEO_HOURLY,
        "daily": OPEN_METEO_DAILY,
        "timezone": "auto",
        "forecast_days": "10",
    })
    answer = get("https://api.open-meteo.com/v1/forecast?" + query)
    # Open-Meteo answers in the place's own wall clock with no offset written
    # on it, so every moment it returns is naive. The offset is in the reply,
    # and pinning it here is the difference between a timestamp that can be
    # compared with an NWS one and a TypeError at the first comparison.
    offset = _number(answer.get("utc_offset_seconds"))
    where = (_dt.timezone(_dt.timedelta(seconds=offset))
             if offset is not None else None)
    report = Report(
        place=place,
        provider="open-meteo",
        latitude=latitude,
        longitude=longitude,
        zone=str(answer.get("timezone") or ""),
        taken=time.time(),
    )

    current = answer.get("current", {})
    condition = sky_from_code(current.get("weather_code"))
    visibility = _number(current.get("visibility"))
    report.now = Now(
        temperature=_number(current.get("temperature_2m")),
        feels_like=_number(current.get("apparent_temperature")),
        humidity=_percent(current.get("relative_humidity_2m")),
        wind=_number(current.get("wind_speed_10m")),
        gust=_number(current.get("wind_gusts_10m")),
        bearing=None if _number(current.get("wind_direction_10m")) is None
        else int(round(_number(current.get("wind_direction_10m")))) % 360,
        pressure=_number(current.get("pressure_msl")),
        visibility=None if visibility is None else visibility / 1000.0,
        cloud=_percent(current.get("cloud_cover")),
        condition=condition,
        daylight=bool(_number(current.get("is_day")) or 0),
        summary=WORDS.get(condition, ""),
    )
    if report.now.humidity is not None and report.now.temperature is not None:
        report.now.dew_point = dew_point(report.now.temperature,
                                         report.now.humidity)

    hourly = answer.get("hourly", {})
    stamps = hourly.get("time", []) or []
    for index, stamp in enumerate(stamps[:48]):
        rain = _number(_at(hourly, "rain", index))
        showers = _number(_at(hourly, "showers", index))
        bearing = _number(_at(hourly, "wind_direction_10m", index))
        report.hours.append(Hour(
            at=_anchor(_moment(str(stamp)), where),
            temperature=_number(_at(hourly, "temperature_2m", index)),
            condition=sky_from_code(_at(hourly, "weather_code", index)),
            precipitation=_percent(
                _at(hourly, "precipitation_probability", index)),
            daylight=bool(_number(_at(hourly, "is_day", index)) or 0),
            amount=_number(_at(hourly, "precipitation", index)),
            # Showers and steady rain are both rain to somebody deciding
            # whether to take a coat.
            rain=None if rain is None and showers is None
            else (rain or 0.0) + (showers or 0.0),
            snow=_number(_at(hourly, "snowfall", index)),
            pressure=_number(_at(hourly, "pressure_msl", index)),
            wind=_number(_at(hourly, "wind_speed_10m", index)),
            bearing=None if bearing is None else int(round(bearing)) % 360,
            cape=_number(_at(hourly, "cape", index)),
        ))

    daily = answer.get("daily", {})
    for index, stamp in enumerate((daily.get("time", []) or [])[:10]):
        moment = _moment(str(stamp))
        report.days.append(Day(
            date=moment.date() if moment else None,
            name="",
            high=_number(_at(daily, "temperature_2m_max", index)),
            low=_number(_at(daily, "temperature_2m_min", index)),
            condition=sky_from_code(_at(daily, "weather_code", index)),
            precipitation=_percent(
                _at(daily, "precipitation_probability_max", index)),
            ultraviolet=_number(_at(daily, "uv_index_max", index)),
        ))
    return report


def _anchor(moment: _dt.datetime | None, zone) -> _dt.datetime | None:
    """A naive moment given the offset the service forgot to write on it."""
    if moment is None or zone is None or moment.tzinfo is not None:
        return moment
    return moment.replace(tzinfo=zone)


def _at(table: dict, key: str, index: int):
    column = table.get(key)
    if not isinstance(column, list) or index >= len(column):
        return None
    return column[index]


def resolve(place: str, get=_get) -> tuple[float, float, str, str] | None:
    """A typed place name into a coordinate, so nobody has to find their own.

    Asking somebody for a latitude to see the weather is asking them to do a
    computer's job. They type where they live.
    """
    name = place.strip()
    if not name:
        return None
    # A name with a region after it geocodes on the name alone; the region is
    # then used to pick among the answers, which is how "Ardsley, NY" finds
    # the one in New York rather than the one in Yorkshire.
    head, _, tail = name.partition(",")
    query = urllib.parse.urlencode({
        "name": head.strip() or name,
        "count": "10",
        "language": "en",
        "format": "json",
    })
    answer = get("https://geocoding-api.open-meteo.com/v1/search?" + query)
    results = answer.get("results") or []
    if not results:
        return None
    wanted = tail.strip().lower()
    chosen = results[0]
    if wanted:
        for candidate in results:
            if _in_region(candidate, wanted):
                chosen = candidate
                break
    latitude = _number(chosen.get("latitude"))
    longitude = _number(chosen.get("longitude"))
    if latitude is None or longitude is None:
        return None
    label = ", ".join(str(chosen.get(k)) for k in ("name", "admin1")
                      if chosen.get(k))
    return latitude, longitude, label or name, str(chosen.get("timezone") or "")


# -- choosing a service, and remembering the answer --------------------------


def _in_region(candidate: dict, wanted: str) -> bool:
    """Whether a geocoded answer is in the region somebody named.

    People type the short form. "Ardsley, NY" has to find the one in New York
    and not the one in Yorkshire, and no geocoding service returns "NY" as a
    field: it returns "New York". So an abbreviation is matched against the
    initials of the region's words, which handles NY, BC and NSW alike without
    this file carrying a table of every state in every country.
    """
    for key in ("admin1", "admin2", "country", "country_code"):
        field = str(candidate.get(key) or "").lower()
        if not field:
            continue
        if wanted == field or wanted in field.split():
            return True
        words = [word for word in field.replace("-", " ").split() if word]
        initials = "".join(word[0] for word in words)
        # Two letters at least. One letter would make "Texas" answer to "t"
        # and turn a typo into a confident wrong city.
        if len(initials) >= 2 and wanted == initials:
            return True
    return False


def in_united_states(latitude: float, longitude: float) -> bool:
    """Roughly, and only to decide who to ask first.

    Deliberately generous: a coordinate that is not actually covered gets a
    404 from the NWS and falls through to Open-Meteo in the same call, so the
    cost of guessing wide is one wasted request and never a blank panel.
    """
    boxes = (
        (24.0, 50.0, -125.5, -66.5),    # the contiguous states
        (51.0, 72.0, -172.0, -129.0),   # Alaska
        (18.5, 22.6, -161.0, -154.5),   # Hawaii
        (17.5, 18.6, -67.5, -65.0),     # Puerto Rico
    )
    return any(south <= latitude <= north and west <= longitude <= east
               for south, north, west, east in boxes)


def fetch(latitude: float, longitude: float, provider: str = "auto",
          place: str = "", get=_get, units: str = "c") -> Report:
    """One report, from whichever service can answer for this coordinate.

    `units` is what the reader will see, not what this returns. Everything in
    a `Report` is Celsius and millimetres whatever is passed here. It is
    needed because one of the services writes prose, and prose has the units
    baked into the sentence rather than applied at the end.
    """
    wanted = (provider or "auto").strip().lower()
    if wanted == "nws" or (wanted == "auto"
                           and in_united_states(latitude, longitude)):
        try:
            report = from_nws(latitude, longitude, get=get, units=units)
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            if wanted == "nws":
                raise
            report = None
        if report is not None and report.now.temperature is not None:
            _borrow_ultraviolet(report, get)
            # The typed name is a fallback, not an override. The NWS names the
            # town a coordinate actually falls in, which beats whatever the
            # person typed, and losing that to a literal "on" in a config file
            # would be a downgrade nobody asked for.
            report.place = report.place or place
            return report
    report = from_open_meteo(latitude, longitude, get=get, place=place)
    if not report.place:
        report.place = place
    return report


def _borrow_ultraviolet(report: Report, get) -> None:
    """The one number the NWS forecast does not carry.

    Open-Meteo is asked for the ultraviolet index alone, in a second small
    request, rather than the panel dropping a tile that people look for in
    summer. A failure here loses the tile and nothing else.
    """
    try:
        query = urllib.parse.urlencode({
            "latitude": f"{report.latitude:.4f}",
            "longitude": f"{report.longitude:.4f}",
            "daily": "uv_index_max",
            "timezone": "auto",
            "forecast_days": str(max(1, min(10, len(report.days) or 1))),
        })
        answer = get("https://api.open-meteo.com/v1/forecast?" + query)
    except (OSError, ValueError, json.JSONDecodeError):
        return
    daily = answer.get("daily", {})
    for index, day in enumerate(report.days):
        value = _number(_at(daily, "uv_index_max", index))
        if value is not None:
            day.ultraviolet = value


# -- keeping it between openings --------------------------------------------


def to_record(report: Report) -> dict:
    return {
        "version": 1,
        "place": report.place,
        "provider": report.provider,
        "latitude": report.latitude,
        "longitude": report.longitude,
        "zone": report.zone,
        "taken": report.taken,
        "narrative": report.narrative,
        "now": {k: getattr(report.now, k) for k in vars(report.now)},
        # Every field, not the five the chart happens to draw.
        #
        # It was those five, and the effect was invisible: a report read back
        # from the cache had no pressure series, so the barometer tile had no
        # direction on it and the front sentence could never fire, on any
        # machine painting what it last knew. Both of those fail by saying
        # nothing, which is exactly what they say on a quiet day.
        "hours": [{
            "at": h.at.isoformat() if h.at else "",
            "temperature": h.temperature,
            "condition": h.condition,
            "precipitation": h.precipitation,
            "daylight": h.daylight,
            "amount": h.amount,
            "rain": h.rain,
            "snow": h.snow,
            "pressure": h.pressure,
            "wind": h.wind,
            "bearing": h.bearing,
            "cape": h.cape,
        } for h in report.hours],
        "air_index": report.air_index,
        "air_pm": report.air_pm,
        "days": [{
            "date": d.date.isoformat() if d.date else "",
            "name": d.name,
            "high": d.high,
            "low": d.low,
            "condition": d.condition,
            "precipitation": d.precipitation,
            "ultraviolet": d.ultraviolet,
        } for d in report.days],
    }


def from_record(record: dict) -> Report | None:
    if not isinstance(record, dict) or record.get("version") != 1:
        return None
    report = Report(
        place=str(record.get("place") or ""),
        provider=str(record.get("provider") or ""),
        latitude=_number(record.get("latitude")) or 0.0,
        longitude=_number(record.get("longitude")) or 0.0,
        zone=str(record.get("zone") or ""),
        taken=_number(record.get("taken")) or 0.0,
        narrative=str(record.get("narrative") or ""),
    )
    index = _number(record.get("air_index"))
    report.air_index = int(index) if index is not None else None
    report.air_pm = _number(record.get("air_pm"))
    saved = record.get("now")
    if isinstance(saved, dict):
        known = vars(Now())
        report.now = Now(**{k: v for k, v in saved.items() if k in known})
    for entry in record.get("hours") or []:
        if not isinstance(entry, dict):
            continue
        report.hours.append(Hour(
            at=_moment(str(entry.get("at") or "")),
            temperature=_number(entry.get("temperature")),
            condition=str(entry.get("condition") or CLOUDY),
            precipitation=_percent(entry.get("precipitation")),
            daylight=bool(entry.get("daylight", True)),
            amount=_number(entry.get("amount")),
            rain=_number(entry.get("rain")),
            snow=_number(entry.get("snow")),
            pressure=_number(entry.get("pressure")),
            wind=_number(entry.get("wind")),
            bearing=_number(entry.get("bearing")),
            cape=_number(entry.get("cape")),
        ))
    for entry in record.get("days") or []:
        if not isinstance(entry, dict):
            continue
        moment = _moment(str(entry.get("date") or ""))
        report.days.append(Day(
            date=moment.date() if moment else None,
            name=str(entry.get("name") or ""),
            high=_number(entry.get("high")),
            low=_number(entry.get("low")),
            condition=str(entry.get("condition") or CLOUDY),
            precipitation=_percent(entry.get("precipitation")),
            ultraviolet=_number(entry.get("ultraviolet")),
        ))
    return report


def load(path: str = "") -> Report | None:
    where = path or CACHE
    try:
        with open(where, encoding="utf-8") as handle:
            record = json.load(handle)
    except (OSError, ValueError):
        return None
    return from_record(record)


def save(report: Report, path: str = "") -> bool:
    where = path or CACHE
    try:
        os.makedirs(os.path.dirname(where) or ".", exist_ok=True)
        # Written beside and renamed, so a greeter reading this file while
        # another writes it never sees half a record.
        temporary = f"{where}.new"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(to_record(report), handle)
        os.replace(temporary, where)
    except OSError:
        return False
    return True


# -- the sun and the moon, worked out rather than asked for ------------------


def _solar_terms(when: _dt.datetime) -> tuple[float, float]:
    """Equation of time in minutes, and declination in radians (NOAA)."""
    moment = when.astimezone(_dt.timezone.utc)
    day = moment.timetuple().tm_yday
    hour = moment.hour + moment.minute / 60.0
    gamma = (2.0 * math.pi / 365.0) * (day - 1 + (hour - 12.0) / 24.0)
    equation = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma))
    declination = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.001480 * math.sin(3 * gamma))
    return equation, declination


def sun_times(latitude: float, longitude: float,
              when: _dt.datetime) -> tuple[_dt.datetime | None, _dt.datetime | None]:
    """Sunrise and sunset for the day `when` falls on, in `when`'s own zone.

    Both are None above the arctic circles on the days the sun does not set
    or does not rise, which is a real answer rather than a failure.
    """
    equation, declination = _solar_terms(when)
    lat = math.radians(latitude)
    zenith = math.radians(90.833)     # the sun's edge, plus refraction
    try:
        cos_hour = (math.cos(zenith) / (math.cos(lat) * math.cos(declination))
                    - math.tan(lat) * math.tan(declination))
    except ZeroDivisionError:
        return None, None
    if not -1.0 <= cos_hour <= 1.0:
        return None, None
    hour_angle = math.degrees(math.acos(cos_hour))
    # The formula counts minutes from UTC midnight of the date the event
    # falls on, and the date that matters is the one on the wall where the
    # sun is rising. Taking it from the UTC instant instead gives tomorrow's
    # sunrise to anybody looking at this screen late in the evening, which is
    # exactly who is looking at it.
    local = when.date()
    midnight = _dt.datetime(local.year, local.month, local.day,
                            tzinfo=_dt.timezone.utc)
    rise = 720.0 - 4.0 * (longitude + hour_angle) - equation
    set_ = 720.0 - 4.0 * (longitude - hour_angle) - equation
    zone = when.tzinfo or _dt.timezone.utc
    return (
        (midnight + _dt.timedelta(minutes=rise)).astimezone(zone),
        (midnight + _dt.timedelta(minutes=set_)).astimezone(zone),
    )


def sun_altitude(latitude: float, longitude: float,
                 when: _dt.datetime) -> float:
    """How high the sun is right now, in degrees. Negative is below."""
    equation, declination = _solar_terms(when)
    moment = when.astimezone(_dt.timezone.utc)
    minutes = moment.hour * 60.0 + moment.minute + moment.second / 60.0
    true_solar = minutes + equation + 4.0 * longitude
    hour_angle = math.radians(true_solar / 4.0 - 180.0)
    lat = math.radians(latitude)
    cos_zenith = (math.sin(lat) * math.sin(declination)
                  + math.cos(lat) * math.cos(declination) * math.cos(hour_angle))
    cos_zenith = max(-1.0, min(1.0, cos_zenith))
    return 90.0 - math.degrees(math.acos(cos_zenith))


def daylight_fraction(rise: _dt.datetime | None, set_: _dt.datetime | None,
                      when: _dt.datetime) -> float | None:
    """Where in the day this moment sits, from 0 at sunrise to 1 at sunset."""
    if rise is None or set_ is None:
        return None
    span = (set_ - rise).total_seconds()
    if span <= 0:
        return None
    return max(0.0, min(1.0, (when - rise).total_seconds() / span))


def moon(when: _dt.datetime) -> tuple[str, float, str]:
    """The phase's name and how much of the disc is lit, from 0 to 1."""
    elapsed = (when.timestamp() - MOON_EPOCH) % SYNODIC
    age = elapsed / SYNODIC
    lit = (1.0 - math.cos(2.0 * math.pi * age)) / 2.0
    key, name = MOON_PHASES[-1][1], MOON_PHASES[-1][2]
    for edge, phase, words in MOON_PHASES:
        if age < edge:
            key, name = phase, words
            break
    return name, lit, key


def dew_point(temperature: float, humidity: int) -> float | None:
    """Magnus-Tetens, for the services that report humidity but not dew.

    Somebody who wants to know whether the night will be muggy is asking
    about the dew point, and a panel that shows humidity without it has given
    them the less useful of the two numbers.
    """
    if humidity <= 0:
        return None
    a, b = 17.625, 243.04
    gamma = (math.log(humidity / 100.0)
             + (a * temperature) / (b + temperature))
    if gamma == a:
        return None
    return (b * gamma) / (a - gamma)


# -- putting numbers into words ---------------------------------------------


def temperature(value: float | None, units: str = "c", degree: bool = True) -> str:
    if value is None:
        return "--"
    number = value * 9.0 / 5.0 + 32.0 if units == "f" else value
    return f"{int(round(number))}\N{DEGREE SIGN}" if degree else str(int(round(number)))


#: Where apparent temperature stops being the actual one. Below the first,
#: moving air takes heat off skin faster than still air does; above the
#: second, humidity stops sweat working. Between them the two numbers are the
#: same number and there is nothing to explain.
CHILL_BELOW = 10.0
INDEX_ABOVE = 26.0

#: And how far apart the two have to be before the difference is the point.
FELT = 1.0


def felt_because(temperature: float | None, feels: float | None) -> str:
    """Which calculation is behind an apparent temperature, if either.

    Heat index and wind chill are different formulas describing different
    discomforts, and the panel called both of them "feels like", which leaves
    the number unexplained in precisely the weather where somebody wants to
    know why it is not the number beside it.

    Decided from the temperature rather than asked of the service, because no
    service says which it used and both of them are defined by the range they
    apply in.

    An empty string where there is nothing to say, which is most days.
    """
    if temperature is None or feels is None:
        return ""
    if abs(feels - temperature) < FELT:
        return ""
    if temperature <= CHILL_BELOW:
        return "wind"
    if temperature >= INDEX_ABOVE:
        return "humidity"
    return ""


def difference(value: float | None, units: str = "c") -> str:
    """A gap between two temperatures, which does not convert like one.

    Six Celsius degrees colder is eleven Fahrenheit degrees colder, not
    forty three. A difference scales by nine fifths and the thirty two point
    offset does not apply to it, because the offset is where the two scales
    start and a gap has no start.

    Written down as its own function because the mistake is invisible: the
    sentence still reads correctly, the number is merely wrong, and it is
    wrong by an amount that looks like weather.
    """
    if value is None:
        return "--"
    number = value * 9.0 / 5.0 if units == "f" else value
    return str(int(round(number)))


def precipitation_words(millimetres: float | None, units: str = "c") -> str:
    """How much rain fell or will, in whatever the person is already reading.

    Inches beside Fahrenheit and millimetres beside Celsius. Splitting these
    is how a panel ends up saying eighty degrees and half a centimetre in the
    same sentence, which is what it did.

    Inches get one decimal below an inch and two below a tenth, because
    "0.0 in" is not a measurement and a trace of rain is worth saying.
    """
    if millimetres is None:
        return "--"
    if units != "f":
        if millimetres < 1.0:
            return f"{millimetres:.1f} mm"
        return f"{int(round(millimetres))} mm"
    inches = millimetres / 25.4
    if inches < 0.1:
        return f"{inches:.2f} in"
    return f"{inches:.1f} in"


def wind_words(value: float | None, units: str = "c") -> str:
    if value is None:
        return "--"
    if units == "f":
        return f"{int(round(value / 1.609344))} mph"
    return f"{int(round(value))} km/h"


def pressure_words(value: float | None, units: str = "c") -> str:
    if value is None:
        return "--"
    if units == "f":
        return f"{value / 33.8639:.2f} inHg"
    return f"{int(round(value))} hPa"


def distance_words(value: float | None, units: str = "c") -> str:
    if value is None:
        return "--"
    if units == "f":
        miles = value / 1.609344
        return f"{miles:.0f} mi" if miles >= 10 else f"{miles:.1f} mi"
    return f"{value:.0f} km" if value >= 10 else f"{value:.1f} km"


def bearing_words(degrees: int | None) -> str:
    if degrees is None:
        return ""
    return COMPASS[int(round((degrees % 360) / 22.5)) % 16]


def bearing_name(degrees: int | None) -> str:
    if degrees is None:
        return ""
    return COMPASS_WORDS[int(round((degrees % 360) / 22.5)) % 16]


#: How far the pressure has to move before it is worth calling a direction.
#:
#: One number, and `outlook.FALLING` is this number rather than a copy of it,
#: because a tile that says the barometer is steady while the sentence under
#: it says a front is coming is two parts of one panel disagreeing in front of
#: somebody.
PRESSURE_MOVE = 2.0


def pressure_trend(hours: list, when=None) -> str:
    """Falling, rising or steady, over the hours the forecast covers.

    The number on its own is trivia. Nobody carries the standard sea level
    pressure around in their head, and the direction is the entire reason a
    barometer is a thing people own.

    Read forward rather than back, from the same series `outlook.front` reads,
    because this panel already has the forecast and does not have yesterday.
    """
    found = [h.pressure for h in hours[:18] if h.pressure is not None]
    if len(found) < 6:
        return ""
    first = found[0]
    if first - min(found) >= PRESSURE_MOVE:
        return "falling"
    if max(found) - first >= PRESSURE_MOVE:
        return "rising"
    return "steady"


#: The bands the United States AQI is published in, and where each one ends.
#:
#: Their own names, kept exactly, for the same reason the ultraviolet tile
#: keeps its band name: somebody who has heard a number on the radio should
#: find the same words here.
AIR_BANDS = (
    (51, _("Good")),
    (101, _("Moderate")),
    (151, _("Unhealthy for sensitive groups")),
    (201, _("Unhealthy")),
    (301, _("Very unhealthy")),
)

#: What the band means for somebody deciding whether to go outside. The band
#: name alone is a category, and a category is not advice.
AIR_ADVICE = (
    (51, _("Fine to be out")),
    (101, _("Fine for most people")),
    (151, _("Take it easy outside if your chest is sensitive")),
    (201, _("Everybody should go easy outside")),
    (301, _("Stay indoors if you can")),
)


def air_words(index: int | None) -> str:
    if index is None:
        return ""
    for edge, words in AIR_BANDS:
        if index < edge:
            return words
    return _("Hazardous")


def air_advice(index: int | None) -> str:
    if index is None:
        return ""
    for edge, words in AIR_ADVICE:
        if index < edge:
            return words
    return _("Stay indoors")


def air_quality(latitude: float, longitude: float, get=_get):
    """The air, right now, from a service that needs no key.

    Returns nothing rather than raising, on every path, because this is the
    least important tile on the panel and it has no business being the reason
    the temperature is missing.
    """
    query = urllib.parse.urlencode({
        "latitude": f"{latitude:.4f}", "longitude": f"{longitude:.4f}",
        "current": "us_aqi,pm2_5",
    })
    try:
        answer = get("https://air-quality-api.open-meteo.com/v1/air-quality?"
                     + query)
    except Exception:  # noqa: BLE001 - a tile, not a build tool
        return None
    current = (answer or {}).get("current") or {}
    index = _number(current.get("us_aqi"))
    if index is None:
        return None
    return int(round(index)), _number(current.get("pm2_5"))


def ultraviolet_words(index: float | None) -> str:
    """The official band name. Boring on purpose, and kept for that reason."""
    if index is None:
        return ""
    for edge, words in UV_BANDS:
        if index < edge:
            return words
    return _("Extreme")


#: Roughly how long untanned, unprotected skin takes to redden, by band.
#:
#: Banded rather than computed, because the honest calculation needs a skin
#: type nobody has told us and would put a precise looking number on a guess.
#: These are the ranges published alongside the index itself, rounded to the
#: nearest thing a person would actually say.
UV_BURN = (
    (3, _("Safe outside for most of the day")),
    (6, _("Unprotected skin burns in about 45 minutes")),
    (8, _("Unprotected skin burns in about 30 minutes")),
    (11, _("Unprotected skin burns in about 15 minutes")),
)



def ultraviolet_note(index: float | None) -> str:
    """What the number means for somebody standing outside, then its name.

    The band on its own is a word with no scale attached: "Very high" is only
    meaningful to somebody who already knows the index. The time is the part
    that changes what a person does, so it leads, and the official name
    follows in brackets for anybody who wants the number's proper label.
    """
    if index is None:
        return ""
    words = ultraviolet_words(index)
    for edge, note in UV_BURN:
        if index < edge:
            return f"{note} ({words})"
    return _("Unprotected skin burns in under 10 minutes") + f" ({words})"


def since_words(seconds: float) -> str:
    """How old the reading is, said the way a person would say it."""
    minutes = int(seconds // 60)
    if minutes < 1:
        return "Updated just now"
    if minutes == 1:
        return "Updated a minute ago"
    if minutes < 60:
        return f"Updated {minutes} minutes ago"
    hours = minutes // 60
    if hours == 1:
        return "Updated an hour ago"
    if hours < 24:
        return f"Updated {hours} hours ago"
    return "Updated more than a day ago"


def source_words(provider: str) -> str:
    if provider == "nws":
        return "National Weather Service"
    if provider == "open-meteo":
        return "Open-Meteo"
    return ""
