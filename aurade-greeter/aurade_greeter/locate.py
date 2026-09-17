"""Look up an approximate city for the greeter's weather panel."""
from __future__ import annotations

import json
import os
import time
import urllib.request

# Keyless HTTPS endpoint used for the approximate lookup.
SERVICE = "https://ipapi.co/json/"

CACHE = os.environ.get(
    "AURADE_LOCATION_CACHE", "/var/cache/aurade-greeter/location.json")

# Avoid repeating the lookup on every greeter start.
FRESH = 24 * 3600

# Network lookups must not hold up the login screen.
TIMEOUT = 8.0

AGENT = ("AuraDE-greeter (https://github.com/aurade/aurade, "
         "weather@aurade.invalid)")


class Place:
    """A coordinate, a name, and when it was asked for."""

    __slots__ = ("latitude", "longitude", "name", "taken")

    def __init__(self, latitude: float, longitude: float, name: str,
                 taken: float = 0.0) -> None:
        self.latitude = latitude
        self.longitude = longitude
        self.name = name
        self.taken = taken or time.time()

    @property
    def age(self) -> float:
        return max(0.0, time.time() - self.taken)

    @property
    def fresh(self) -> bool:
        return self.age < FRESH

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"<Place {self.name!r} {self.latitude},{self.longitude}>"


def _get(url: str, timeout: float = TIMEOUT) -> dict:
    request = urllib.request.Request(url, headers={
        "User-Agent": AGENT,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(request, timeout=timeout) as answer:  # noqa: S310
        if answer.status != 200:
            raise OSError(f"{url} answered {answer.status}")
        payload = answer.read(64 * 1024)
    return json.loads(payload.decode("utf-8", errors="replace"))


def _number(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse(answer: dict) -> Place | None:
    """One reply, or nothing at all.

    The service answers 200 with an `error` key when it is rate limiting or
    cannot place an address, so a status code is not the check. Neither is the
    presence of the fields: a reply with a latitude and no longitude is a
    reply to throw away, and a zero for both is the middle of the Atlantic,
    which is what a service says when it means it does not know.
    """
    if not isinstance(answer, dict) or answer.get("error"):
        return None
    latitude = _number(answer.get("latitude"))
    longitude = _number(answer.get("longitude"))
    if latitude is None or longitude is None:
        return None
    if not (-90.0 <= latitude <= 90.0) or not (-180.0 <= longitude <= 180.0):
        return None
    if latitude == 0.0 and longitude == 0.0:
        return None
    city = str(answer.get("city") or "").strip()
    region = str(answer.get("region_code") or answer.get("region") or "").strip()
    name = f"{city}, {region}" if city and region else city
    return Place(latitude, longitude, name)


def load(path: str = "") -> Place | None:
    where = path or CACHE
    try:
        with open(where, encoding="utf-8") as handle:
            record = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or record.get("version") != 1:
        return None
    latitude = _number(record.get("latitude"))
    longitude = _number(record.get("longitude"))
    if latitude is None or longitude is None:
        return None
    return Place(latitude, longitude, str(record.get("name") or ""),
                 _number(record.get("taken")) or 0.0)


def save(place: Place, path: str = "") -> bool:
    where = path or CACHE
    try:
        os.makedirs(os.path.dirname(where) or ".", exist_ok=True)
        temporary = f"{where}.new"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "latitude": place.latitude,
                       "longitude": place.longitude, "name": place.name,
                       "taken": place.taken}, handle)
        os.replace(temporary, where)
    except OSError:
        return False
    return True


def locate(get=_get, path: str = "", now: float | None = None) -> Place | None:
    """Where this machine is, asked at most once a day.

    The cache is consulted first and returned without a request when it is
    still current, so this costs one request per boot on a machine that is
    rebooted and one a day on a machine that is not.

    A stale answer is kept and returned when the request fails, because a
    coordinate from yesterday is a better guess about where this machine is
    than a coordinate from a timezone, and a machine that moved far enough for
    that to be wrong has somebody with it who can say so.
    """
    kept = load(path)
    if kept is not None and (kept.fresh if now is None
                             else (now - kept.taken) < FRESH):
        return kept
    try:
        found = parse(get(SERVICE))
    except Exception:  # noqa: BLE001 - a login screen, not a build tool
        return kept
    if found is None:
        return kept
    save(found, path)
    return found
