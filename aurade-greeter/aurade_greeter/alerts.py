"""Filter weather alerts and choose their display level.

Only current weather alerts and the two shelter warnings listed below reach
the greeter. Keeping admission separate from display level prevents unrelated
emergency messages from taking over the login screen.
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import urllib.parse
import urllib.request

#: The category this screen carries without further argument.
WEATHER = "Met"

#: Shelter warnings admitted by name. Keep this list closed.
SHELTER = (
    "Shelter In Place Warning",
    "Nuclear Power Plant Warning",
)

#: Ignore exercises, tests, drafts, and other non-live messages.
ACTUAL = "Actual"

#: How loud, in the order they are checked.
TAKEOVER = "takeover"
BANNER = "banner"
LINE = "line"
SILENT = ""

#: Alerts that already went through the Emergency Alert System need no banner.
EAS = "EAS"

#: VTEC actions that end an event rather than continue it.
FINISHED = ("CAN", "EXP", "UPG")

AGENT = ("AuraDE-greeter (https://github.com/aurade/aurade, "
         "weather@aurade.invalid)")


class Alert:
    """One alert, with the fields this screen actually acts on."""

    __slots__ = ("event", "category", "severity", "urgency", "certainty",
                 "status", "headline", "description", "instruction",
                 "response", "area", "sent", "onset", "expires",
                 "identifier", "action", "broadcast", "motion", "polygon")

    def __init__(self, **fields) -> None:
        for name in self.__slots__:
            setattr(self, name, fields.get(name))

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"<Alert {self.event!r} {self.category}/{self.severity}>"


def _moment(text: str):
    if not text:
        return None
    try:
        return _dt.datetime.fromisoformat(text)
    except ValueError:
        return None


def _first(parameters: dict, key: str) -> str:
    found = (parameters or {}).get(key) or []
    return str(found[0]) if found else ""


def _vtec_parts(vtec: str) -> tuple[str, str]:
    """The action and a stable identity for the event, out of a VTEC string.

    A VTEC looks like `/O.NEW.KCTP.TO.W.0030.260828T0045Z-260828T0130Z/`.
    The second field is the action and the office, phenomenon, significance
    and event number together name one storm across every update it gets.

    Without this a warning that is updated six times is six alerts, and the
    top tier becomes unusable inside an hour.
    """
    parts = [p for p in (vtec or "").strip("/").split(".") if p]
    if len(parts) < 6:
        return "", ""
    return parts[1], ".".join(parts[2:6])


def _motion(text: str):
    """Bearing, speed and position out of `eventMotionDescription`.

    The field looks like:

        2026-08-28T00:45:00-00:00...storm...288DEG...11KT...40.08,-76.1

    Which is where "it is coming towards you" stops being a guess: a bearing,
    a speed in knots and the storm's own position, against coordinates this
    machine already has.
    """
    if not text:
        return None
    bearing = knots = None
    where = None
    for piece in str(text).split("..."):
        piece = piece.strip()
        if piece.endswith("DEG"):
            try:
                bearing = int(piece[:-3])
            except ValueError:
                bearing = None
        elif piece.endswith("KT"):
            try:
                knots = float(piece[:-2])
            except ValueError:
                knots = None
        elif "," in piece and piece.replace(",", "").replace(".", "").replace(
                "-", "").isdigit():
            try:
                latitude, longitude = (float(v) for v in piece.split(",")[:2])
                where = (latitude, longitude)
            except ValueError:
                where = None
    if bearing is None or knots is None or where is None:
        return None
    return {"bearing": bearing % 360, "knots": knots,
            "latitude": where[0], "longitude": where[1]}


def parse(feature: dict) -> Alert:
    """One GeoJSON feature, as the fields this screen acts on."""
    properties = feature.get("properties") or {}
    parameters = properties.get("parameters") or {}
    blocked = [str(v) for v in (parameters.get("BLOCKCHANNEL") or [])]
    action, identity = _vtec_parts(_first(parameters, "VTEC"))
    geometry = feature.get("geometry") or {}
    ring = None
    if str(geometry.get("type") or "") == "Polygon":
        rings = geometry.get("coordinates") or []
        ring = [tuple(point[:2]) for point in rings[0]] if rings else None
    return Alert(
        event=str(properties.get("event") or ""),
        category=str(properties.get("category") or ""),
        severity=str(properties.get("severity") or ""),
        urgency=str(properties.get("urgency") or ""),
        certainty=str(properties.get("certainty") or ""),
        status=str(properties.get("status") or ""),
        headline=str(properties.get("headline") or ""),
        description=str(properties.get("description") or ""),
        instruction=str(properties.get("instruction") or ""),
        response=str(properties.get("response") or ""),
        area=str(properties.get("areaDesc") or ""),
        sent=_moment(str(properties.get("sent") or "")),
        onset=_moment(str(properties.get("onset") or "")),
        expires=_moment(str(properties.get("expires") or "")),
        identifier=identity or str(properties.get("id") or ""),
        action=action,
        broadcast=EAS not in blocked,
        motion=_motion(_first(parameters, "eventMotionDescription")),
        polygon=ring,
    )


def admitted(alerts: list) -> list:
    """The gate. What this screen carries at all.

    Weather, or one of the two events named in `SHELTER`, and in either case
    actually happening rather than a drill.

    Unconditional and first, and deliberately not folded into `tier`. Two
    questions, two functions: this one is whether an alert exists as far as
    this screen is concerned, and `tier` is only ever asked about alerts that
    got through here.
    """
    return [a for a in alerts
            if (a.category == WEATHER or a.event in SHELTER)
            and a.status == ACTUAL]


def tier(alert: Alert) -> str:
    """How loudly, for an alert that has already passed `admitted`.

    Of 301 alerts active across the whole United States when this was
    written, thirteen were `Immediate`. The top tier being rare is the only
    thing that makes it worth having.
    """
    if alert.severity == "Extreme" and alert.urgency == "Immediate":
        return TAKEOVER
    if alert.severity in ("Extreme", "Severe"):
        return BANNER
    return LINE


#: Loudest first, for sorting.
ORDER = {TAKEOVER: 0, BANNER: 1, LINE: 2, SILENT: 3}


def live(alerts: list, when: _dt.datetime | None = None) -> list:
    """The ones that have not ended, by clock and by VTEC alike.

    Both, because they disagree: an alert can be cancelled before it expires,
    and one whose office never sent a cancellation still stops mattering when
    its expiry passes.
    """
    when = when or _dt.datetime.now(_dt.timezone.utc)
    kept = []
    for alert in alerts:
        if alert.action in FINISHED:
            continue
        if alert.expires is not None and alert.expires <= when:
            continue
        kept.append(alert)
    return kept


def newest(alerts: list) -> list:
    """One entry per event, the most recently sent of each.

    A warning updated six times arrives as six messages naming one storm. Six
    banners for one storm is the feature failing.
    """
    best: dict = {}
    for alert in alerts:
        key = alert.identifier or f"{alert.event}/{alert.area}"
        seen = best.get(key)
        if seen is None or (alert.sent or _dt.datetime.min.replace(
                tzinfo=_dt.timezone.utc)) >= (seen.sent or
                                              _dt.datetime.min.replace(
                                                  tzinfo=_dt.timezone.utc)):
            best[key] = alert
    return list(best.values())


def rank(alerts: list) -> list:
    """Loudest first, then whichever is about to matter soonest.

    An expiring tornado warning outranks a fresh heat advisory, and two of
    equal weight are ordered by which one runs out first, because that is the
    one somebody has least time to act on.
    """
    far = _dt.datetime.max.replace(tzinfo=_dt.timezone.utc)

    def key(alert: Alert):
        return (ORDER.get(tier(alert), 9), alert.expires or far, alert.event)

    return sorted(alerts, key=key)


def shown(features: list, when: _dt.datetime | None = None) -> list:
    """Everything, in one call: parsed, gated, deduplicated and ordered."""
    return rank(newest(live(admitted([parse(f) for f in features]), when)))


def _bearing_to(from_lat: float, from_lon: float,
                to_lat: float, to_lon: float) -> float:
    """Initial great circle bearing, in degrees from north."""
    lat1, lat2 = math.radians(from_lat), math.radians(to_lat)
    delta = math.radians(to_lon - from_lon)
    y = math.sin(delta) * math.cos(lat2)
    x = (math.cos(lat1) * math.sin(lat2)
         - math.sin(lat1) * math.cos(lat2) * math.cos(delta))
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _miles_between(from_lat: float, from_lon: float,
                   to_lat: float, to_lon: float) -> float:
    radius = 3958.8
    lat1, lat2 = math.radians(from_lat), math.radians(to_lat)
    dlat = lat2 - lat1
    dlon = math.radians(to_lon - from_lon)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


#: How far off a storm's heading a place can be and still be in its way.
#: Thirty degrees either side, which is wide enough to cover the width of a
#: storm and narrow enough that a cell moving away is not called approaching.
TOWARDS = 30.0


def approaching(alert: Alert, latitude: float, longitude: float) -> dict | None:
    """Whether the storm is coming this way, and roughly how long it has.

    Returns nothing where the alert carries no motion, which is most of them:
    only a warning issued against a tracked cell has `eventMotionDescription`,
    and inventing a direction for the rest would be worse than saying nothing.

    The arithmetic is deliberately coarse. A storm is not a point and it does
    not travel in a straight line, so this rounds to five minutes and is
    described in the copy as "about".
    """
    motion = alert.motion
    if not motion:
        return None
    miles = _miles_between(motion["latitude"], motion["longitude"],
                           latitude, longitude)
    toward = _bearing_to(motion["latitude"], motion["longitude"],
                         latitude, longitude)
    off = abs((toward - motion["bearing"] + 180.0) % 360.0 - 180.0)
    speed = motion["knots"] * 1.15078
    minutes = None
    if off <= TOWARDS and speed > 1.0:
        minutes = int(round(miles / speed * 60.0 / 5.0)) * 5
    return {"miles": miles, "off": off, "mph": speed,
            "towards": off <= TOWARDS, "minutes": minutes}


def _get(url: str):
    request = urllib.request.Request(
        url, headers={"User-Agent": AGENT, "Accept": "application/geo+json"})
    with urllib.request.urlopen(request, timeout=15) as answer:
        return json.load(answer)


def fetch(latitude: float, longitude: float, get=_get) -> list:
    """Every active alert for one point, already gated and ordered.

    Asked for a point rather than a zone, so a warning covering half a county
    is not shown to the other half.
    """
    url = ("https://api.weather.gov/alerts/active?point="
           + urllib.parse.quote(f"{latitude:.4f},{longitude:.4f}"))
    answer = get(url)
    return shown(answer.get("features") or [])
