#!/usr/bin/env python3
"""What the sky is doing, proved against recorded answers rather than the sky.

Every request in `weather.py` goes through an injected `get`, which is what
makes this possible: the fixtures below are the real shapes both services
return, trimmed, so the parsing can be driven to its ends without a network
and without waiting for it to snow.

Three groups of rules here carry the most.

The first is that a service is allowed to answer badly. A null where a number
was promised, a field that has been renamed, a station that has not reported
for six hours. None of those may raise on a login screen, and none of them may
turn into a plausible wrong number either, so the tests below feed nulls and
absences deliberately and check for `None` rather than for zero.

The second is the fold from the National Weather Service's twelve hour periods
into days. The service forecasts in halves and names them, and a day's high
comes from its daytime half and its low from the night that follows it. Get
the fold wrong and every row of the week is off by twelve hours, which looks
entirely reasonable and is wrong.

The third is the sun, which is arithmetic rather than a request, and is
therefore the one part of this panel that can be checked against a published
answer. It is: sunrise and sunset are pinned against Open-Meteo's own values
for a real place on a real date, within three minutes.
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..")))

from aurade_greeter import weather as W  # noqa: E402

FAILURES: list[str] = []

UTC = _dt.timezone.utc
EAST = _dt.timezone(_dt.timedelta(hours=-4))


def check(ok: bool, message: str) -> None:
    if not ok:
        FAILURES.append(message)


def near(one, two, slack: float, message: str) -> None:
    if one is None or two is None:
        FAILURES.append(f"{message} (got {one!r}, wanted {two!r})")
        return
    if abs(one - two) > slack:
        FAILURES.append(f"{message} (got {one!r}, wanted {two!r})")


# -- recorded answers -------------------------------------------------------

POINT = {
    "properties": {
        "forecast": "https://api.weather.gov/gridpoints/OKX/37,56/forecast",
        "forecastHourly":
            "https://api.weather.gov/gridpoints/OKX/37,56/forecast/hourly",
        "observationStations":
            "https://api.weather.gov/gridpoints/OKX/37,56/stations",
        "timeZone": "America/New_York",
        "relativeLocation": {"properties": {"city": "Ardsley", "state": "NY"}},
    },
}

HOURLY = {"properties": {"periods": [
    {"number": 1, "startTime": "2026-08-27T12:00:00-04:00", "isDaytime": True,
     "temperature": 26, "temperatureUnit": "C",
     "probabilityOfPrecipitation": {"value": 45},
     "dewpoint": {"value": 20.55}, "relativeHumidity": {"value": 72},
     "windSpeed": "17 km/h", "windDirection": "S",
     "icon": "https://api.weather.gov/icons/land/day/tsra,50?size=small",
     "shortForecast": "Chance Showers And Thunderstorms"},
    {"number": 2, "startTime": "2026-08-27T13:00:00-04:00", "isDaytime": True,
     "temperature": 27, "probabilityOfPrecipitation": {"value": None},
     "windSpeed": "10 to 15 mph", "windDirection": "SSW",
     "icon": "https://api.weather.gov/icons/land/day/rain_showers,60",
     "shortForecast": "Showers"},
    {"number": 3, "startTime": "2026-08-27T22:00:00-04:00", "isDaytime": False,
     "temperature": 21, "probabilityOfPrecipitation": {"value": 20},
     "windSpeed": "", "windDirection": "",
     "icon": "https://api.weather.gov/icons/land/night/few?size=small",
     "shortForecast": "Mostly Clear"},
]}}

FORECAST = {"properties": {"periods": [
    {"name": "This Afternoon", "startTime": "2026-08-27T12:00:00-04:00",
     "isDaytime": True, "temperature": 28,
     "probabilityOfPrecipitation": {"value": 81},
     "icon": "https://api.weather.gov/icons/land/day/tsra,80?size=medium",
     "shortForecast": "Chance Showers And Thunderstorms",
     "detailedForecast": "A chance of showers and thunderstorms before 2pm."},
    {"name": "Tonight", "startTime": "2026-08-27T18:00:00-04:00",
     "isDaytime": False, "temperature": 20,
     "probabilityOfPrecipitation": {"value": 40},
     "icon": "https://api.weather.gov/icons/land/night/tsra,40",
     "shortForecast": "Showers Likely", "detailedForecast": "Showers."},
    {"name": "Friday", "startTime": "2026-08-28T06:00:00-04:00",
     "isDaytime": True, "temperature": 29,
     "probabilityOfPrecipitation": {"value": 20},
     "icon": "https://api.weather.gov/icons/land/day/wind_bkn?size=medium",
     "shortForecast": "Breezy", "detailedForecast": "Breezy."},
    {"name": "Friday Night", "startTime": "2026-08-28T18:00:00-04:00",
     "isDaytime": False, "temperature": 18,
     "probabilityOfPrecipitation": {"value": 5},
     "icon": "https://api.weather.gov/icons/land/night/skc",
     "shortForecast": "Clear", "detailedForecast": "Clear."},
]}}

STATIONS = {"features": [
    {"properties": {"stationIdentifier": "KHPN", "name": "White Plains"}},
    {"properties": {"stationIdentifier": "KTEB", "name": "Teterboro"}},
]}

OBSERVED = {"properties": {
    "temperature": {"unitCode": "wmoUnit:degC", "value": 22.0},
    "dewpoint": {"unitCode": "wmoUnit:degC", "value": 21.0},
    "relativeHumidity": {"unitCode": "wmoUnit:percent", "value": 94.4},
    "windSpeed": {"unitCode": "wmoUnit:km_h-1", "value": 7.4},
    "windGust": {"unitCode": "wmoUnit:km_h-1", "value": None},
    "windDirection": {"unitCode": "wmoUnit:degree_(angle)", "value": 190},
    "barometricPressure": {"unitCode": "wmoUnit:Pa", "value": 101760},
    "visibility": {"unitCode": "wmoUnit:m", "value": 1600},
    "heatIndex": {"unitCode": "wmoUnit:degC", "value": 24.5},
    "textDescription": "Heavy Rain and Fog/Mist",
}}

UV_ONLY = {"daily": {"time": ["2026-08-27", "2026-08-28"],
                     "uv_index_max": [6.15, 6.7]}}

OPEN_METEO = {
    "timezone": "Europe/London",
    "utc_offset_seconds": 3600,
    "current": {
        "time": "2026-08-27T12:00", "temperature_2m": 24.6,
        "relative_humidity_2m": 55, "apparent_temperature": 25.9,
        "is_day": 1, "weather_code": 2, "cloud_cover": 41,
        "pressure_msl": 1014.2, "wind_speed_10m": 12.0,
        "wind_direction_10m": 225, "wind_gusts_10m": 28.4,
        "visibility": 24000.0,
    },
    "hourly": {
        "time": ["2026-08-27T11:00", "2026-08-27T12:00", "2026-08-27T13:00"],
        "temperature_2m": [23.9, 24.6, None],
        "weather_code": [1, 2, 61],
        "precipitation_probability": [0, 10, 55],
        "is_day": [1, 1, 1],
    },
    "daily": {
        "time": ["2026-08-27", "2026-08-28"],
        "weather_code": [55, 3],
        "temperature_2m_max": [24.6, 27.9],
        "temperature_2m_min": [19.1, 19.3],
        "uv_index_max": [3.2, 6.7],
        "precipitation_probability_max": [39, 15],
    },
}

GEOCODED = {"results": [
    {"name": "Ardsley", "admin1": "England", "country_code": "GB",
     "latitude": 53.546, "longitude": -1.424, "timezone": "Europe/London"},
    {"name": "Ardsley", "admin1": "New York", "country_code": "US",
     "latitude": 41.010, "longitude": -73.843, "timezone": "America/New_York"},
    {"name": "Ardsley", "admin1": "Yorkshire", "country_code": "GB",
     "latitude": 53.900, "longitude": -1.500, "timezone": "Europe/London"},
]}


class Service:
    """Every URL this package asks for, answered from the fixtures above."""

    def __init__(self, break_nws: bool = False) -> None:
        self.asked: list[str] = []
        self.break_nws = break_nws

    def __call__(self, url: str, timeout: float = 0.0) -> dict:
        self.asked.append(url)
        if "api.weather.gov" in url:
            if self.break_nws:
                raise OSError("the forecast office is not answering")
            if "/points/" in url:
                return POINT
            if "/forecast/hourly" in url:
                return HOURLY
            if url.endswith("/stations"):
                return STATIONS
            if "/observations/latest" in url:
                return OBSERVED
            if "/forecast" in url:
                return FORECAST
        if "geocoding-api" in url:
            return GEOCODED
        if "open-meteo" in url:
            return UV_ONLY if "uv_index_max" in url and "current" not in url \
                else OPEN_METEO
        raise AssertionError(f"nothing recorded for {url}")


# -- the National Weather Service -------------------------------------------

service = Service()
nws = W.from_nws(41.0126, -73.8437, get=service)

check(nws.provider == "nws", "the report did not name its service")
check(nws.place == "Ardsley, NY",
      f"the town the coordinate falls in was lost (got {nws.place!r})")
check(nws.zone == "America/New_York", "the place's own timezone was lost")
check(nws.narrative.startswith("A chance of showers"),
      "the forecaster's own paragraph was dropped")

# An observation is a reading; a forecast period is a prediction. Where a
# station has reported, its numbers are the ones the panel says "now" about.
near(nws.now.temperature, 22.0, 0.01,
     "the observed temperature did not replace the forecast one")
check(nws.now.humidity == 94, "the observed humidity was not rounded to a whole")
near(nws.now.pressure, 1017.6, 0.1, "pascals were not read as hectopascals")
near(nws.now.visibility, 1.6, 0.01, "metres were not read as kilometres")
near(nws.now.feels_like, 24.5, 0.01, "the heat index was not taken as feels like")
check(nws.now.bearing == 190, "the observed wind bearing was lost")
check(nws.now.gust is None,
      "a null gust became a number instead of staying unknown")
check(nws.now.summary == "Heavy Rain and Fog/Mist",
      "the station's own description was not preferred over the forecast's")
check(nws.now.condition == W.THUNDER,
      f"the forecast icon was not read (got {nws.now.condition})")

check(len(nws.hours) == 3, f"the hourly periods were lost (got {len(nws.hours)})")
check(nws.hours[0].precipitation == 45, "an hourly rain chance was lost")
check(nws.hours[1].precipitation is None,
      "a null rain chance became zero rather than unknown")
check(nws.hours[2].daylight is False, "a night hour was reported as daylight")
check(nws.hours[2].condition == W.MOSTLY_CLEAR,
      "a night icon did not map to its condition")

# The fold. Two halves of one day become one row, the high from the daytime
# half and the low from the night that follows it on the same date.
check(len(nws.days) == 2, f"the days did not fold (got {len(nws.days)})")
today, tomorrow = nws.days
check(today.name == "This Afternoon", "the day took its name from the night")
near(today.high, 28.0, 0.01, "the day's high did not come from its daytime half")
near(today.low, 20.0, 0.01, "the day's low did not come from the night after it")
check(today.precipitation == 81,
      "the day's rain chance was not the higher of its two halves")
check(today.condition == W.THUNDER, "the day took the night's condition")
check(tomorrow.name == "Friday", "the second day lost its name")
near(tomorrow.high, 29.0, 0.01, "the second day's high was lost")
near(tomorrow.low, 18.0, 0.01, "the second day's low was lost")
check(tomorrow.condition == W.CLOUDY,
      f"a wind_ prefixed icon lost its sky (got {tomorrow.condition})")

# -- what a service says, in this product's words ---------------------------

check(W.sky_from_icon("https://api.weather.gov/icons/land/night/skc") ==
      (W.CLEAR, False), "a night icon was read as daylight")
check(W.sky_from_icon("https://api.weather.gov/icons/land/day/bkn,40?size=m") ==
      (W.CLOUDY, True), "an icon's chance suffix confused the condition")
check(W.sky_from_icon("https://api.weather.gov/icons/land/day/wind_skc")[0] ==
      W.CLEAR, "a wind_ prefix hid the sky behind it")
check(W.sky_from_icon("https://api.weather.gov/icons/land/day/wind_nonsense")[0]
      == W.WIND, "an unknown windy icon lost the one thing it did say")
check(W.sky_from_icon("https://api.weather.gov/icons/land/day/nonsense")[0]
      == W.CLOUDY, "an unknown icon did not fall back to cloudy")
check(W.sky_from_icon("") == (W.CLOUDY, True),
      "an absent icon raised instead of falling back")

for code, wanted in ((0, W.CLEAR), (3, W.OVERCAST), (48, W.FOG),
                     (65, W.HEAVY_RAIN), (66, W.FREEZING), (75, W.HEAVY_SNOW),
                     (82, W.HEAVY_RAIN), (95, W.THUNDER), (99, W.HAIL)):
    check(W.sky_from_code(code) == wanted,
          f"WMO code {code} did not map to {wanted}")
check(W.sky_from_code(7777) == W.CLOUDY, "an unknown WMO code did not fall back")
check(W.sky_from_code(None) == W.CLOUDY, "a null WMO code raised")
for code, condition in W.WMO.items():
    check(condition in W.CONDITIONS,
          f"WMO code {code} maps to {condition}, which is not a condition")
for condition in W.CONDITIONS:
    check(condition in W.WORDS, f"{condition} has no words to say it with")

# Wind speeds arrive as prose and leave as kilometres per hour.
near(W._speed("19 km/h"), 19.0, 0.01, "a plain speed was misread")
near(W._speed("10 to 15 mph"), 15 * 1.609344, 0.01,
     "a range in miles did not forecast its stronger end in kilometres")
near(W._speed("5 mph"), 5 * 1.609344, 0.01, "miles were not converted")
check(W._speed("") is None, "an empty speed became a number")
check(W._speed("calm") is None, "a speed with no digits in it became a number")
check(W._bearing_of("SSW") == 202, "a compass letter did not become degrees")
check(W._bearing_of("") is None, "an absent wind direction became north")
check(W._bearing_of("upwards") is None, "nonsense became a bearing")

# -- Open-Meteo -------------------------------------------------------------

meteo = W.from_open_meteo(51.5, -0.12, get=Service(), place="London")
check(meteo.provider == "open-meteo", "the report did not name its service")
check(meteo.place == "London", "the given place name was dropped")
near(meteo.now.temperature, 24.6, 0.01, "the current temperature was lost")
near(meteo.now.visibility, 24.0, 0.01, "metres were not read as kilometres")
check(meteo.now.bearing == 225, "the wind bearing was lost")
check(meteo.now.condition == W.PARTLY, "the current WMO code was not read")
check(meteo.now.daylight is True, "is_day was not read")
near(meteo.now.dew_point, 15.1, 0.4,
     "the dew point was not worked out from humidity and temperature")

# The offset the service does not write on its own timestamps.
check(all(hour.at is not None and hour.at.tzinfo is not None
          for hour in meteo.hours),
      "Open-Meteo's naive timestamps were left naive and cannot be compared")
check(meteo.hours[0].at.utcoffset() == _dt.timedelta(hours=1),
      "the offset in the reply was not put on the timestamps")
check(meteo.hours[2].temperature is None,
      "a null hourly temperature became zero rather than unknown")
check(len(meteo.days) == 2, "the daily rows were lost")
near(meteo.days[1].ultraviolet, 6.7, 0.01, "the ultraviolet index was lost")
near(meteo.days[0].low, 19.1, 0.01, "the daily low was lost")

# -- choosing a service -----------------------------------------------------

check(W.in_united_states(41.0, -73.8), "a New York coordinate was sent abroad")
check(W.in_united_states(61.2, -149.9), "an Alaskan coordinate was sent abroad")
check(W.in_united_states(21.3, -157.8), "a Hawaiian coordinate was sent abroad")
check(not W.in_united_states(51.5, -0.12), "a London coordinate was sent to the NWS")
check(not W.in_united_states(-33.9, 151.2), "a Sydney coordinate was sent to the NWS")

picked = Service()
here = W.fetch(41.0126, -73.8437, "auto", get=picked)
check(here.provider == "nws",
      "a United States coordinate did not reach the National Weather Service")
check(any("uv_index_max" in url for url in picked.asked),
      "the ultraviolet index the NWS does not carry was never asked for")
near(here.days[0].ultraviolet, 6.15, 0.01,
     "the borrowed ultraviolet index did not reach the day it belongs to")
check(here.place == "Ardsley, NY",
      "the town the service named was lost")
# The typed name is a fallback, not an override. The service names the town a
# coordinate actually falls in, and that beats whatever somebody typed.
overridden = W.fetch(41.0126, -73.8437, "auto", place="Wherever", get=Service())
check(overridden.place == "Ardsley, NY",
      "a typed place name overrode the town the service named")

abroad = W.fetch(51.5, -0.12, "auto", place="London", get=Service())
check(abroad.provider == "open-meteo",
      "a coordinate outside the United States was sent to the NWS")

fallen = W.fetch(41.0126, -73.8437, "auto", place="Ardsley", get=Service(True))
check(fallen.provider == "open-meteo",
      "a failing forecast office did not fall through to the other service")
check(fallen.place == "Ardsley", "the fallback lost the place name")

pinned = None
try:
    W.fetch(41.0126, -73.8437, "nws", get=Service(True))
except OSError:
    pinned = "raised"
check(pinned == "raised",
      "a service asked for by name failed quietly into a different one")

# -- a typed place ----------------------------------------------------------

found = W.resolve("Ardsley, NY", get=Service())
check(found is not None and abs(found[0] - 41.010) < 0.001,
      "a region after the comma did not pick the right Ardsley")
check(found is not None and found[2] == "Ardsley, New York",
      "the resolved name did not include the region")
check(W.resolve("Ardsley, New York", get=Service()) is not None
      and abs(W.resolve("Ardsley, New York", get=Service())[0] - 41.010) < 0.001,
      "a region spelled out in full did not pick the right Ardsley")
check(W.resolve("Ardsley, US", get=Service()) is not None
      and abs(W.resolve("Ardsley, US", get=Service())[0] - 41.010) < 0.001,
      "a country code after the comma did not narrow the answer")
check(W.resolve("Ardsley, ZZ", get=Service()) is not None
      and abs(W.resolve("Ardsley, ZZ", get=Service())[0] - 53.546) < 0.001,
      "a region that matches nothing did not fall back to the first answer")
# One letter is not an abbreviation, it is a typo. Treating it as one would
# send somebody who mistyped to a confidently wrong town: here, Yorkshire.
single = W.resolve("Ardsley, Y", get=Service())
check(single is not None and abs(single[0] - 53.546) < 0.001,
      "a single letter was treated as a region abbreviation")
plain = W.resolve("Ardsley", get=Service())
check(plain is not None and abs(plain[0] - 53.546) < 0.001,
      "a bare name did not take the service's first answer")
check(W.resolve("", get=Service()) is None, "an empty place name was looked up")
check(W.resolve("nowhere", get=lambda url, timeout=0.0: {"results": []}) is None,
      "a place with no answers became a coordinate anyway")

# -- guards against a service answering badly -------------------------------

check(W._number(None) is None, "a null became a number")
check(W._number(True) is None, "a boolean became a number")
check(W._number("nope") is None, "a word became a number")
check(W._number(float("nan")) is None, "a NaN became a number")
check(W._number(float("inf")) is None, "an infinity became a number")
near(W._number({"value": 3.5}), 3.5, 0.001, "a wrapped measurement was not unwrapped")
check(W._number({"value": None}) is None, "a wrapped null became a number")
check(W._percent(140) == 100, "a percentage over a hundred was not clamped")
check(W._percent(-8) == 0, "a negative percentage was not clamped")
check(W._moment("") is None, "an empty timestamp became a moment")
check(W._moment("not a time") is None, "nonsense became a moment")
check(W._moment("2026-08-27T12:00:00Z").tzinfo is not None,
      "a Z suffix was not read as UTC")

# -- remembering the answer between openings --------------------------------

with tempfile.TemporaryDirectory() as folder:
    path = os.path.join(folder, "deeper", "weather.json")
    check(W.save(nws, path), "the report could not be written")
    again = W.load(path)
    check(again is not None, "a written report could not be read back")
    check(again.place == nws.place and again.provider == nws.provider,
          "the place or the service was lost in the cache")
    check(again.narrative == nws.narrative, "the paragraph was lost in the cache")
    near(again.now.temperature, nws.now.temperature, 0.001,
         "the temperature was lost in the cache")
    near(again.now.visibility, nws.now.visibility, 0.001,
         "the visibility was lost in the cache")
    check(again.now.gust is None, "an unknown gust came back as a number")
    check(len(again.hours) == len(nws.hours) and len(again.days) == len(nws.days),
          "rows were lost in the cache")
    check(again.hours[0].at == nws.hours[0].at,
          "an hour's moment did not survive the cache")
    check(again.days[0].date == nws.days[0].date,
          "a day's date did not survive the cache")
    near(again.days[0].low, nws.days[0].low, 0.001,
         "a day's low did not survive the cache")

    broken = os.path.join(folder, "broken.json")
    with open(broken, "w", encoding="utf-8") as handle:
        handle.write("{ this is not json")
    check(W.load(broken) is None, "a corrupt cache was read as a report")
    wrong = os.path.join(folder, "wrong.json")
    with open(wrong, "w", encoding="utf-8") as handle:
        json.dump({"version": 99, "place": "Mars"}, handle)
    check(W.load(wrong) is None, "a cache from another version was trusted")
    check(W.load(os.path.join(folder, "absent.json")) is None,
          "a missing cache raised instead of saying nothing")

# Fresh, stale, and past caring.
report = W.Report(taken=time.time(), now=W.Now(temperature=12.0))
check(report.fresh and report.usable, "a report taken now is not fresh")
report.taken = time.time() - (W.FRESH + 30)
check(not report.fresh, "a report older than the freshness window is still fresh")
check(report.usable, "a report worth showing with its age on it was thrown away")
report.taken = time.time() - (W.STALE + 30)
check(not report.usable, "a report too old to show was still offered")
check(not W.Report().usable, "a report nobody has filled in was called usable")
check(not W.Report(taken=time.time()).usable,
      "a report with no temperature in it was called usable")

# -- the sun, which is arithmetic ------------------------------------------

# Pinned against Open-Meteo's published sunrise and sunset for Ardsley on this
# date, which is an answer from somebody else's implementation.
noon = _dt.datetime(2026, 8, 27, 12, 0, tzinfo=EAST)
rise, set_ = W.sun_times(41.0126, -73.8437, noon)
check(rise is not None and set_ is not None, "the sun neither rose nor set")
if rise and set_:
    near((rise - _dt.datetime(2026, 8, 27, 6, 17, tzinfo=EAST)).total_seconds(),
         0.0, 180.0, "sunrise is more than three minutes from the published time")
    near((set_ - _dt.datetime(2026, 8, 27, 19, 36, tzinfo=EAST)).total_seconds(),
         0.0, 180.0, "sunset is more than three minutes from the published time")

# The day is the one on the wall where the sun is, not the one in UTC. At ten
# at night in New York it is already tomorrow in UTC, and the answer must
# still be tonight's sunset rather than tomorrow's.
late = _dt.datetime(2026, 8, 27, 22, 0, tzinfo=EAST)
late_rise, late_set = W.sun_times(41.0126, -73.8437, late)
check(late_rise is not None and late_rise.date() == _dt.date(2026, 8, 27),
      "late in the evening the sun rose on the wrong day")
check(late_set is not None and late_set.date() == _dt.date(2026, 8, 27),
      "late in the evening the sun set on the wrong day")

check(W.sun_times(78.2, 15.6, _dt.datetime(2026, 6, 21, 12, tzinfo=UTC))
      == (None, None), "the midnight sun was given a sunset")
check(W.sun_times(78.2, 15.6, _dt.datetime(2026, 12, 21, 12, tzinfo=UTC))
      == (None, None), "the polar night was given a sunrise")

high = W.sun_altitude(41.0126, -73.8437, noon)
low = W.sun_altitude(41.0126, -73.8437,
                     _dt.datetime(2026, 8, 27, 0, 30, tzinfo=EAST))
check(high > 50.0, f"the sun was not high at midday (got {high:.1f})")
check(low < 0.0, f"the sun was not below the horizon at midnight (got {low:.1f})")
near(W.sun_altitude(0.0, 0.0, _dt.datetime(2026, 3, 20, 12, 7, tzinfo=UTC)),
     90.0, 1.5, "the sun was not overhead at the equator at the equinox")

check(W.daylight_fraction(rise, set_, rise) == 0.0, "sunrise was not the start")
check(W.daylight_fraction(rise, set_, set_) == 1.0, "sunset was not the end")
near(W.daylight_fraction(rise, set_, rise + (set_ - rise) / 2), 0.5, 0.001,
     "the middle of the day was not the middle of the arc")
check(W.daylight_fraction(rise, set_, rise - _dt.timedelta(hours=3)) == 0.0,
      "a moment before sunrise ran off the start of the arc")
check(W.daylight_fraction(rise, set_, set_ + _dt.timedelta(hours=3)) == 1.0,
      "a moment after sunset ran off the end of the arc")
check(W.daylight_fraction(None, set_, noon) is None,
      "a day with no sunrise still produced a position on the arc")

# -- the moon ---------------------------------------------------------------

new = _dt.datetime.fromtimestamp(W.MOON_EPOCH, UTC)
name, lit, _k = W.moon(new)
check(name == "New moon", f"the known new moon was called {name!r}")
check(lit < 0.01, f"the known new moon was {lit:.2f} lit")
name, lit, _k = W.moon(new + _dt.timedelta(seconds=W.SYNODIC / 2))
check(name == "Full moon", f"half a month after new was called {name!r}")
check(lit > 0.99, f"half a month after new was only {lit:.2f} lit")

# Pinned against four dates from an almanac, which is an answer nothing in
# this file could have produced. Without these, every moon assertion is
# relative to the epoch and moving the epoch moves them all together.
for when, wanted in (
        (_dt.datetime(2024, 1, 11, 11, 57, tzinfo=UTC), "new"),
        (_dt.datetime(2026, 3, 19, 1, 23, tzinfo=UTC), "new"),
        (_dt.datetime(2024, 1, 25, 17, 54, tzinfo=UTC), "full"),
        (_dt.datetime(2025, 7, 10, 20, 37, tzinfo=UTC), "full")):
    words, amount, _k = W.moon(when)
    if wanted == "new":
        check(amount < 0.02,
              f"the new moon of {when:%Y-%m-%d} came out {amount:.2f} lit")
        check(words == "New moon",
              f"the new moon of {when:%Y-%m-%d} was called {words!r}")
    else:
        check(amount > 0.98,
              f"the full moon of {when:%Y-%m-%d} came out {amount:.2f} lit")
        check(words == "Full moon",
              f"the full moon of {when:%Y-%m-%d} was called {words!r}")

previous = 0.0
for step in range(1, 8):
    _, amount, _k = W.moon(new + _dt.timedelta(seconds=W.SYNODIC * step / 16))
    check(amount > previous, "the moon did not brighten through its first half")
    previous = amount
for step in range(0, 400, 7):
    words, amount, _k = W.moon(new + _dt.timedelta(days=step))
    check(0.0 <= amount <= 1.0, f"the moon was {amount} lit after {step} days")
    check(words in [w for _, _key, w in W.MOON_PHASES],
          f"the moon was in no named phase after {step} days")

# -- dew point --------------------------------------------------------------

near(W.dew_point(24.6, 55), 15.1, 0.4, "a known dew point was wrong")
near(W.dew_point(20.0, 100), 20.0, 0.05,
     "saturated air did not have its own temperature as its dew point")
check(W.dew_point(20.0, 0) is None, "zero humidity produced a dew point")
check(W.dew_point(20.0, 50) < 20.0, "the dew point was above the temperature")

# -- numbers into words -----------------------------------------------------

check(W.temperature(22.4) == "22\N{DEGREE SIGN}", "Celsius was not rounded")
check(W.temperature(22.0, "f") == "72\N{DEGREE SIGN}", "Fahrenheit was wrong")
check(W.temperature(-0.4, "c") == "0\N{DEGREE SIGN}", "just below zero was not rounded to zero")
check(W.temperature(None) == "--", "an unknown temperature was invented")
check(W.temperature(22.0, degree=False) == "22", "the degree sign could not be dropped")
check(W.wind_words(19.0) == "19 km/h", "wind in kilometres was wrong")
check(W.wind_words(16.09344, "f") == "10 mph", "wind in miles was wrong")
check(W.wind_words(None) == "--", "an unknown wind speed was invented")
check(W.pressure_words(1016.7) == "1017 hPa", "pressure in hectopascals was wrong")
check(W.pressure_words(1016.7, "f").endswith(" inHg"), "pressure in inches was not named")
check(W.distance_words(1.6) == "1.6 km", "a short visibility lost its decimal")
check(W.distance_words(24.0) == "24 km", "a long visibility kept a pointless decimal")
check(W.distance_words(16.09344, "f") == "10 mi", "visibility in miles was wrong")
check(W.bearing_words(0) == "N" and W.bearing_words(180) == "S",
      "the cardinal points were wrong")
check(W.bearing_words(203) == "SSW", "an intercardinal point was wrong")
check(W.bearing_words(359) == "N", "a bearing just short of north wrapped wrong")
check(W.bearing_words(None) == "", "an unknown bearing was given a letter")
check(W.bearing_name(180) == "south", "a bearing was not said as a word")
check(W.bearing_name(203) == "south-southwest", "a sixteenth point lost its words")
check(len(W.COMPASS) == len(W.COMPASS_WORDS) == 16,
      "the compass letters and the compass words are different lengths")
for degrees in range(0, 360, 5):
    check(W.bearing_words(degrees) in W.COMPASS,
          f"{degrees} degrees fell outside the compass")

check(W.ultraviolet_words(2.9) == "Low", "the low ultraviolet band was wrong")
check(W.ultraviolet_words(3.0) == "Moderate", "the ultraviolet bands are off by one")
check(W.ultraviolet_words(7.9) == "High", "the high ultraviolet band was wrong")
check(W.ultraviolet_words(10.9) == "Very high", "the very high band was wrong")
check(W.ultraviolet_words(11.0) == "Extreme", "the top of the scale was wrong")
check(W.ultraviolet_words(None) == "", "an unknown index was given a band")

check(W.since_words(5) == "Updated just now", "a new reading was called old")
check(W.since_words(61) == "Updated a minute ago", "one minute was pluralised")
check(W.since_words(7 * 60) == "Updated 7 minutes ago", "minutes were miscounted")
check(W.since_words(59 * 60 + 59) == "Updated 59 minutes ago",
      "the last minute of the hour became an hour")
check(W.since_words(3600) == "Updated an hour ago", "one hour was pluralised")
check(W.since_words(5 * 3600) == "Updated 5 hours ago", "hours were miscounted")
check(W.since_words(24 * 3600) == "Updated more than a day ago",
      "a day old reading claimed to be hours old")
check(W.source_words("nws") == "National Weather Service",
      "the National Weather Service was not credited")
check(W.source_words("open-meteo") == "Open-Meteo", "Open-Meteo was not credited")
check(W.source_words("") == "", "an unknown service was credited anyway")

# The terms of service want the caller named, and a request without a name is
# answered with 403 rather than with weather.
check("AuraDE" in W.AGENT and "http" in W.AGENT,
      "the user agent does not identify this product and a way to reach it")

# Two readings of now, which have to be one reading.
#
# The headline came from the station observation and the first column of the
# hourly chart came from the gridpoint forecast, and on a San Antonio evening
# they were eight degrees apart on the same panel. Both were right about their
# own source. The panel was wrong as a whole, and the measurement wins over a
# prediction of the hour an instrument has already reported.
observed = W.from_nws(41.0126, -73.8437, get=Service())
check(observed.hours, "the fixture has no hourly readings to reconcile")
check(observed.now.temperature is not None,
      "the fixture has no observation, so this proved nothing")
check(observed.hours[0].temperature == observed.now.temperature,
      f"the panel reads {observed.now.temperature} at the top and "
      f"{observed.hours[0].temperature} in the first column of the chart")


# Units, which have to agree across a whole panel or none of it is trusted.
#
# The bug this covers was visible on the screen: the panel said 80 degrees
# and 29.96 inHg and 10.0 miles, and then the forecast sentence in the middle
# of it said "a low around 26" and "0.5 cm". The numbers were converted at
# the point of display and the sentence was not, because a sentence has its
# units baked in rather than applied at the end.
check(W.precipitation_words(0.4) == "0.4 mm",
      "a trace of rain lost its decimal in millimetres")
check(W.precipitation_words(5.0) == "5 mm",
      "millimetres kept a decimal it does not need")
check(W.precipitation_words(0.4, "f") == "0.02 in",
      "a trace of rain rounded away to nothing in inches")
check(W.precipitation_words(12.7, "f") == "0.5 in",
      "half an inch is not half an inch")
check(W.precipitation_words(25.4, "f") == "1.0 in",
      "an inch of rain is not an inch")
check(W.precipitation_words(None) == "--" and
      W.precipitation_words(None, "f") == "--",
      "no reading became a number")
check("mm" not in W.precipitation_words(5.0, "f"),
      "millimetres reached a reader asking for Fahrenheit")
check("in" not in W.precipitation_words(5.0, "c"),
      "inches reached a reader asking for Celsius")

# A period arrives in whichever system was asked for and has to end up on the
# module's own scale either way.
check(W._celsius(212.0, "F") == 100.0, "boiling did not come back as 100C")
check(W._celsius(100.0, "C") == 100.0, "a Celsius reading was converted anyway")
check(W._celsius(None, "F") is None, "a missing reading became a number")

# And the sentence follows the reader. Same fixture, two requests.
seen: list[str] = []


class Recorder(Service):
    def __call__(self, url: str):
        seen.append(url)
        return super().__call__(url)


for asked, expect in (("c", "units=si"), ("f", "units=us")):
    seen.clear()
    W.from_nws(41.0126, -73.8437, get=Recorder(), units=asked)
    daily = [u for u in seen if "/forecast" in u and "hourly" not in u]
    check(daily and expect in daily[0],
          f"asked for {asked!r} and the forecast request was {daily[:1]}")
    hourly = [u for u in seen if "/forecast/hourly" in u]
    check(hourly and "units=si" in hourly[0],
          "the hourly request stopped being SI, and nothing in it is a sentence")

# The ultraviolet note leads with what to do and keeps the official name.
for index, band in ((1, "Low"), (4, "Moderate"), (7, "High"),
                    (9, "Very high"), (12, "Extreme")):
    note = W.ultraviolet_note(index)
    check(note.endswith(f"({band})"),
          f"UV {index} did not carry its official name, said {note!r}")
    check(len(note.split(" (")[0]) > len(band),
          f"UV {index} said nothing before its band name")
check(W.ultraviolet_note(None) == "", "no reading produced a sentence anyway")
check("15 minutes" in W.ultraviolet_note(9),
      "very high did not say how long before skin reddens")


# A three digit temperature has to fit inside the chart that draws it.
#
# The number column was sized by measuring the literal "-88 degrees". That is
# four glyphs and so is "100 degrees", but digits are wider than a minus sign,
# so every temperature fitted except a three digit one and the degree sign was
# sliced in half at the right edge. San Antonio is three digits for most of
# the summer.
#
# Measured as pixels rather than as arithmetic, because the arithmetic is the
# thing that was wrong: ink in the final column of the surface is a glyph that
# ran out of chart.
try:
    import cairo
    from aurade_greeter import weatherdraw as _D
    from aurade_greeter import tokens as T
    import gi as _gi
    _gi.require_version("Pango", "1.0")
    from gi.repository import Pango as _Pango
except Exception as exc:  # noqa: BLE001 - reported, never silently skipped
    FAILURES.append(f"the drawing layer would not import, so the chart is "
                    f"unchecked: {exc}")
else:
    class _Hot:
        def __init__(self, high, low):
            self.high, self.low = high, low
            self.date = _dt.date(2026, 8, 28)
            self.name = "Today"
            self.condition = "clear"
            self.precipitation = 0
            self.ultraviolet = None

    for label, units, week in (
            ("Fahrenheit, three digits",
             "f", [_Hot(37.8, 26.0), _Hot(37.2, 25.0)]),
            ("Celsius, two digits",
             "c", [_Hot(37.8, 26.0), _Hot(37.2, 25.0)]),
            ("below zero, with a minus",
             "c", [_Hot(-8.0, -21.0), _Hot(-5.0, -18.0)])):
        wide, tall = 420, 70
        surface = cairo.ImageSurface(cairo.FORMAT_RGB24, wide, tall)
        context = cairo.Context(surface)
        context.set_source_rgb(0.0, 0.0, 0.0)
        context.paint()
        _D.days_chart(context, wide, tall, week, units,
                      T.scheme(True), _Pango.FontDescription("Sans 11"),
                      None, ["Today", "Tomorrow"])
        surface.flush()
        data = surface.get_data()
        stride = surface.get_stride()
        # Ink in the final column is a glyph that ran out of surface. One
        # pixel of margin is the whole assertion: the point is not that the
        # number sits comfortably, it is that none of it was thrown away.
        rightmost = -1
        for row in range(tall):
            base = row * stride
            for column in range(wide):
                index = base + column * 4
                if data[index] or data[index + 1] or data[index + 2]:
                    rightmost = max(rightmost, column)
        check(0 <= rightmost <= wide - 2,
              f"{label}: ink reaches x={rightmost} of {wide}, so a glyph is "
              f"being cut off at the edge of the chart")


# Which discomfort the apparent temperature is describing.
#
# Heat index and wind chill are different formulas meaning different things,
# and the panel called both of them "feels like", which leaves the number
# unexplained in exactly the weather where somebody wants to know why it is
# not the number beside it.
check(W.felt_because(31.0, 36.0) == "humidity",
      "a hot day five degrees warmer than it reads was not blamed on humidity")
check(W.felt_because(2.0, -4.0) == "wind",
      "a cold day six degrees colder than it reads was not blamed on wind")
check(W.felt_because(18.0, 18.4) == "",
      "a mild day was given an explanation it does not need")
check(W.felt_because(18.0, 22.0) == "",
      "a mild day was blamed on humidity, which does not apply at eighteen")
# Inside a band and yet not worth saying, which is the case the band check
# alone cannot cover: thirty degrees that feels like thirty and a half is
# thirty degrees, and explaining half a degree is noise.
check(W.felt_because(30.0, 30.4) == "",
      "half a degree of difference on a hot day was explained")
check(W.felt_because(4.0, 3.7) == "",
      "a third of a degree of difference on a cold day was explained")
check(W.felt_because(None, 5.0) == "" and W.felt_because(31.0, None) == "",
      "a missing reading produced an explanation anyway")
# The band edges, because a rule stated as two numbers is a rule with two
# places to be off by one.
check(W.felt_because(W.CHILL_BELOW, W.CHILL_BELOW - 5) == "wind",
      "the wind chill band excludes its own edge")
check(W.felt_because(W.INDEX_ABOVE, W.INDEX_ABOVE + 5) == "humidity",
      "the heat index band excludes its own edge")


# The rows of the week, named against what is actually drawn.
#
# This is the bug that was on the screen when somebody asked for a picture of
# it. The National Weather Service returns a leading `Tonight` period every
# evening, with a low and no high, because the high has already happened. The
# drawing dropped that row and the panel named the list before dropping it, so
# every remaining row wore the name of the row above it: Friday's forecast
# under `Today`, Saturday's under `Tomorrow`, all the way down. Confidently
# wrong, every evening, for six hours at a time.
#
# `weatherui` is imported here rather than at the top because it pulls in the
# toolkit, and a dead DISPLAY makes that import hang for two minutes.
os.environ.pop("DISPLAY", None)
try:
    from aurade_greeter import weatherui as WUI  # noqa: E402
except Exception as exc:  # noqa: BLE001 - reported, never silently skipped
    FAILURES.append(f"weatherui would not import, so its rows are unchecked: {exc}")
else:
    class _Day:
        def __init__(self, date, high, low):
            self.date, self.high, self.low = date, high, low
            self.name = ""
            self.condition = "clear"
            self.precipitation = 0
            self.ultraviolet = None

    thursday = _dt.date(2026, 8, 27)
    evening = _dt.datetime(2026, 8, 27, 23, 52)
    week = [
        _Day(thursday, None, 26.0),                              # Tonight
        _Day(thursday + _dt.timedelta(days=1), 38.0, 26.0),      # Friday
        _Day(thursday + _dt.timedelta(days=2), 37.0, 25.0),      # Saturday
        _Day(thursday + _dt.timedelta(days=3), 36.0, 25.0),      # Sunday
    ]

    drawn = WUI.usable_days(week)
    check(len(drawn) == 3, f"the row with no high was kept, {len(drawn)} rows")
    check(drawn[0].date == thursday + _dt.timedelta(days=1),
          "the first drawn row is not the first day that can be drawn")

    # Through the seam the panel actually calls, not the two halves of it.
    drawn, names = WUI.day_rows(week, evening)
    check(len(drawn) == 3, f"day_rows drew {len(drawn)} rows")
    check(len(names) == len(drawn),
          f"{len(names)} names for {len(drawn)} rows, so they cannot align")
    # Friday is tomorrow on Thursday evening, and it is the first row drawn.
    # The bug called it Today, because Today belonged to the row that was
    # dropped.
    check(names[0] == "Tomorrow",
          f"the first drawn row is Friday and it is called {names[0]!r}")
    check(names[1] == "Saturday",
          f"the second drawn row is Saturday and it is called {names[1]!r}")
    check(names[2] == "Sunday",
          f"the third drawn row is Sunday and it is called {names[2]!r}")

    # And the name goes with the number beside it. Friday's high is 38, and
    # 38 must never appear on a row called Today.
    paired = dict(zip(names, drawn))
    check("Today" not in paired,
          "a row is called Today on an evening when today has no high left")
    check(paired["Tomorrow"].high == 38.0,
          "the row called Tomorrow is not carrying Friday's high")

    # Named before noon, when the leading period does have a high, Today is
    # correct and must still be produced.
    morning = _dt.datetime(2026, 8, 27, 9, 0)
    whole = [_Day(thursday, 38.0, 26.0)] + week[1:]
    _, day_first = WUI.day_rows(whole, morning)
    check(day_first[0] == "Today",
          f"a morning row for today is called {day_first[0]!r}")
    check(day_first[1] == "Tomorrow",
          f"the row after today is called {day_first[1]!r}")

    # And the panel has to go through that seam. Two calls to `day_names` in
    # this module means somebody has a second list again, which is the shape
    # the bug had.
    source = open(os.path.join(HERE, "..", "aurade_greeter", "weatherui.py"),
                  encoding="utf-8").read()
    check(source.count("day_names(") == 2,
          f"`day_names` is called {source.count('day_names(') - 1} times "
          f"outside its own definition, and it should be once, inside "
          f"`day_rows`")


# The moon's phase key, which is what code compares against.
#
# `shade.py` used to test the display name against the literal "Full moon",
# which worked exactly as long as nobody translated it. On a French machine
# the full moon occasion would have stopped appearing, silently, with nothing
# in a log and no test able to see it. The key never moves.
_full = W.moon(new + _dt.timedelta(seconds=W.SYNODIC / 2))
check(_full[2] == "full",
      f"the middle of the cycle is keyed {_full[2]!r} rather than 'full'")
check(W.moon(new)[2] == "new",
      f"the start of the cycle is keyed {W.moon(new)[2]!r}")
_keys = {key for _edge, key, _words in W.MOON_PHASES}
check(len(_keys) == 8,
      f"the eight phases carry {len(_keys)} distinct keys")
check(all(key == key.lower() and " " not in key for key in _keys),
      f"a phase key looks like display text: {sorted(_keys)}")

if FAILURES:
    for failure in FAILURES:
        print(f"greeter-weather: {failure}", file=sys.stderr)
    sys.exit(1)
print("greeter weather test: PASS")
