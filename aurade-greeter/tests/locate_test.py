#!/usr/bin/env python3
"""Where this machine is, from the network, and every way that can go wrong.

The failure this file exists for is not a crash. It is a service that answers
200 with an apology in the body, or with a latitude and no longitude, or with
zero and zero, which is what a geolocation service says when it means it does
not know. Every one of those is a coordinate this screen would then fetch a
forecast for and print on a lock screen as fact.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..")))

from aurade_greeter import locate as L  # noqa: E402

FAILURES: list[str] = []
CHECKS = 0


def check(ok: bool, message: str) -> None:
    global CHECKS
    CHECKS += 1
    if not ok:
        FAILURES.append(message)


DIR = tempfile.mkdtemp(prefix="aurade-locate-")


def where(name: str) -> str:
    return os.path.join(DIR, name)


#: A representative reply with a deliberately different timezone and city.
REPLY = json.loads(r"""
{
 "ip": "203.0.113.7",
 "city": "San Antonio",
 "region": "Texas",
 "region_code": "TX",
 "country_code": "US",
 "latitude": 29.42412,
 "longitude": -98.49373,
 "timezone": "America/Chicago"
}
""")


# -- reading one reply ------------------------------------------------------

_good = L.parse(REPLY)
check(_good is not None, "a good reply was thrown away")
if _good:
    check(abs(_good.latitude - 29.42412) < 1e-6,
          f"the latitude came out {_good.latitude}")
    check(abs(_good.longitude + 98.49373) < 1e-6,
          f"the longitude came out {_good.longitude}")
    check(_good.name == "San Antonio, TX",
          f"the place is named {_good.name!r}")

# 200 with an apology in it. This is how the service rate limits, so it is the
# most likely bad reply rather than the least, and nothing about the status
# code says so.
check(L.parse({"error": True, "reason": "RateLimited",
               "latitude": 29.4, "longitude": -98.4}) is None,
      "a reply that says error carried a coordinate through anyway")

check(L.parse({"latitude": 29.4}) is None,
      "half a coordinate was accepted")
check(L.parse({"latitude": 29.4, "longitude": None}) is None,
      "a null longitude was accepted")
check(L.parse({"latitude": "not a number", "longitude": -98.4}) is None,
      "a latitude that is not a number was accepted")
check(L.parse({"latitude": 91.0, "longitude": 0.0}) is None,
      "a latitude off the globe was accepted")
check(L.parse({"latitude": 0.0, "longitude": 200.0}) is None,
      "a longitude off the globe was accepted")

# Zero and zero is a real place, in the Atlantic off Ghana, and no machine
# running this is there. It is what a service returns when it has nothing.
check(L.parse({"latitude": 0.0, "longitude": 0.0}) is None,
      "null island was accepted as somewhere this machine might be")

check(L.parse([]) is None, "a list instead of an object did not say nothing")

# A city with no region still names somewhere. A reply with neither does not,
# and the coordinate is still good, so the place goes unnamed rather than the
# whole answer being thrown away.
_partial = L.parse({"latitude": 51.5, "longitude": -0.12, "city": "London"})
check(_partial is not None and _partial.name == "London",
      f"a reply with no region code lost its city: {_partial}")
_unnamed = L.parse({"latitude": 51.5, "longitude": -0.12})
check(_unnamed is not None and _unnamed.name == "",
      "a reply with no city at all was thrown away, coordinate and all")


# -- the cache --------------------------------------------------------------

_path = where("one.json")
check(L.load(_path) is None, "an absent cache did not read as nothing")
check(L.save(L.Place(29.4, -98.5, "San Antonio, TX"), _path) is True,
      "the cache would not write")
_back = L.load(_path)
check(_back is not None and _back.name == "San Antonio, TX",
      f"the cache did not read back: {_back}")
check(_back is not None and abs(_back.latitude - 29.4) < 1e-9,
      "the cached latitude changed on the way through the file")

with open(where("junk.json"), "w", encoding="utf-8") as handle:
    handle.write("{not json")
check(L.load(where("junk.json")) is None,
      "a corrupt cache raised instead of saying nothing")

with open(where("old.json"), "w", encoding="utf-8") as handle:
    json.dump({"version": 99, "latitude": 1.0, "longitude": 2.0}, handle)
check(L.load(where("old.json")) is None,
      "a cache from a version this code does not know was read anyway")


# -- how often anybody is asked ---------------------------------------------

class Counted:
    def __init__(self, answer) -> None:
        self.answer = answer
        self.asked = 0

    def __call__(self, _url, timeout=0.0):
        self.asked += 1
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


_path = where("count.json")
_get = Counted(REPLY)
_first = L.locate(get=_get, path=_path)
check(_first is not None and _first.name == "San Antonio, TX",
      f"the first lookup came back {_first}")
check(_get.asked == 1, f"the first lookup made {_get.asked} requests")

L.locate(get=_get, path=_path)
L.locate(get=_get, path=_path)
check(_get.asked == 1,
      f"a fresh cache was ignored and the service was asked {_get.asked} "
      f"times, which is a request from a login screen every refresh")

# Past a day, it asks again.
_stale = time.time() - L.FRESH - 60
L.save(L.Place(1.0, 2.0, "Somewhere", taken=_stale), _path)
_get = Counted(REPLY)
_again = L.locate(get=_get, path=_path)
check(_get.asked == 1, "a day old cache was served rather than refreshed")
check(_again is not None and _again.name == "San Antonio, TX",
      f"the refreshed answer was not used: {_again}")

# And when the service is down, yesterday's answer is better than the
# timezone's guess, so it is kept rather than thrown away.
L.save(L.Place(29.4, -98.5, "San Antonio, TX", taken=_stale), _path)
_kept = L.locate(get=Counted(OSError("no route to host")), path=_path)
check(_kept is not None and _kept.name == "San Antonio, TX",
      f"a failed refresh threw away a usable stale answer: {_kept}")

# Same when the service answers with an apology rather than an error.
L.save(L.Place(29.4, -98.5, "San Antonio, TX", taken=_stale), _path)
_kept = L.locate(get=Counted({"error": True, "reason": "RateLimited"}),
                 path=_path)
check(_kept is not None and _kept.name == "San Antonio, TX",
      f"a rate limited reply threw away a usable stale answer: {_kept}")

# With nothing cached and nobody answering, it says nothing, and the caller
# falls back to the timezone.
check(L.locate(get=Counted(OSError("down")), path=where("none.json")) is None,
      "a failed lookup with no cache invented a location")


# -- what is actually sent, and to whom --------------------------------------
#
# This module exists to make one request to one company. That it is HTTPS is
# not a detail: the reply carries where this machine is and the request is
# made from a screen nobody has authenticated at, on whatever network happens
# to be in range.
check(L.SERVICE.startswith("https://"),
      f"the location service is asked over {L.SERVICE.split(':')[0]}, so the "
      f"answer and the question are readable by the network")

# Read off the import list rather than out of the text. The first version
# searched the source for "Gtk" and failed on this module's own docstring,
# which is a sentence saying it does not import Gtk.
import ast  # noqa: E402
import inspect  # noqa: E402

_tree = ast.parse(inspect.getsource(L))
_imported: set[str] = set()
for _node in ast.walk(_tree):
    if isinstance(_node, ast.Import):
        _imported |= {alias.name.split(".")[0] for alias in _node.names}
    elif isinstance(_node, ast.ImportFrom) and _node.module:
        _imported.add(_node.module.split(".")[0])
check("gi" not in _imported,
      f"the location module imports a toolkit ({sorted(_imported)}), so it "
      f"can no longer be driven on a machine with no display")
check("urllib" in _imported,
      "the location module no longer makes a request at all, so these checks "
      "are describing something that is not there")

if FAILURES:
    for failure in FAILURES:
        print(f"greeter-locate: {failure}", file=sys.stderr)
    sys.exit(1)
print(f"greeter locate test: PASS ({CHECKS} checks)")
