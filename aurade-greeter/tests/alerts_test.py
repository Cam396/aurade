#!/usr/bin/env python3
"""Weather emergencies, and the one field that keeps everything else out.

The fixtures below are real records read from `api.weather.gov`, trimmed to
the fields this module acts on. Two of them are the whole argument for how
this is built, and the first test asserts the thing that makes it necessary
rather than taking it on trust: a tornado and an Amber Alert are identical on
severity, urgency and certainty, so the textbook escalation on those three
fields would put a full screen takeover on a lock screen twice a day in San
Antonio, and no amount of tuning would help because the numbers are the same
numbers.

If that assertion ever fails because the service changed, the design needs
revisiting, and this file is where somebody would find out.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..")))

from aurade_greeter import alerts as A  # noqa: E402

FAILURES: list[str] = []
CHECKS = 0


def check(condition: bool, message: str) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(message)


#: Real records, trimmed. Not invented, because the fields that matter here
#: are exactly the ones a hand written fixture would get subtly wrong.
RECORDS = json.loads(r"""
{
 "tornado": {
  "properties": {
   "event": "Tornado Warning",
   "category": "Met",
   "severity": "Extreme",
   "urgency": "Immediate",
   "certainty": "Observed",
   "status": "Actual",
   "headline": "Tornado Warning issued August 27 at 8:46PM EDT until August 27 at 8:45PM EDT by NWS State College PA",
   "description": "The storm which prompted the warning has weakened, and no longer\nappears capable of producing a tornado. Therefore, the warning has\nbeen allowed to expire.\n\nA Severe Thunderstorm Watch remains in effe",
   "instruction": null,
   "response": "Shelter",
   "areaDesc": "Lancaster, PA",
   "sent": "2026-08-27T20:46:00-04:00",
   "onset": "2026-08-27T20:46:00-04:00",
   "expires": "2026-08-27T20:55:00-04:00",
   "id": "urn:oid:2.49.0.1.840.0.ca7c3678daa7d6079e8d0da38e4bd28c1a1c4e10.001.1",
   "parameters": {
    "VTEC": [
     "/O.EXP.KCTP.TO.W.0030.000000T0000Z-260828T0045Z/"
    ],
    "BLOCKCHANNEL": [
     "EAS",
     "NWEM",
     "CMAS"
    ],
    "eventMotionDescription": [
     "2026-08-28T00:45:00-00:00...storm...288DEG...11KT...40.08,-76.1"
    ]
   }
  },
  "geometry": {
   "type": "Polygon",
   "coordinates": [
    [
     [
      -76.25,
      40.09
     ],
     [
      -76.21,
      40.14
     ],
     [
      -76.15,
      40.15
     ],
     [
      -76.05,
      40.11
     ],
     [
      -76.13,
      40.02
     ],
     [
      -76.25,
      40.09
     ]
    ]
   ]
  }
 },
 "severe": {
  "properties": {
   "event": "Severe Thunderstorm Warning",
   "category": "Met",
   "severity": "Severe",
   "urgency": "Immediate",
   "certainty": "Observed",
   "status": "Actual",
   "headline": "Severe Thunderstorm Warning issued August 28 at 1:20AM CDT until August 28 at 1:30AM CDT by NWS Dodge City KS",
   "description": "The storms which prompted the warning have weakened below severe\nlimits, and no longer pose an immediate threat to life or property.\nTherefore, the warning will be allowed to expire.  However, gusty\nw",
   "instruction": null,
   "response": "Shelter",
   "areaDesc": "Ellis, KS; Ness, KS; Rush, KS; Trego, KS",
   "sent": "2026-08-28T01:20:00-05:00",
   "onset": "2026-08-28T01:20:00-05:00",
   "expires": "2026-08-28T01:30:00-05:00",
   "id": "urn:oid:2.49.0.1.840.0.37adc63428cab5493e4dceb52526b5b5073d9f66.001.1",
   "parameters": {
    "VTEC": [
     "/O.EXP.KDDC.SV.W.0268.000000T0000Z-260828T0630Z/"
    ],
    "BLOCKCHANNEL": [
     "EAS",
     "NWEM",
     "CMAS"
    ],
    "eventMotionDescription": [
     "2026-08-28T06:20:00-00:00...storm...320DEG...30KT...38.94,-99.58 38.74,-99.59 38.64,-99.74 38.63,-99.98"
    ]
   }
  },
  "geometry": {
   "type": "Polygon",
   "coordinates": [
    [
     [
      -99.46,
      38.62
     ],
     [
      -99.61,
      38.55
     ],
     [
      -99.93,
      38.54
     ],
     [
      -100.17,
      38.7
     ],
     [
      -100.15,
      38.7
     ],
     [
      -100.15,
      38.79
     ]
    ]
   ]
  }
 },
 "advisory": {
  "properties": {
   "event": "Heat Advisory",
   "category": "Met",
   "severity": "Moderate",
   "urgency": "Expected",
   "certainty": "Likely",
   "status": "Actual",
   "headline": "Heat Advisory issued August 28 at 1:43AM AST until August 28 at 5:00PM AST by NWS San Juan PR",
   "description": "* WHAT...This level of heat affects most individuals sensitive to\nheat, especially those without effective cooling and/or adequate\nhydration. expected.\n\n* WHERE...Portions of Puerto Rico and Virgin Is",
   "instruction": "Take extra precautions when outside. Wear lightweight and loose\nfitting clothing. Try to limit strenuous activities to early morning\nor evening. Take action when you see symptoms of heat exhaustion and\nheat stroke.\n\nMonitor the latest forecasts and warnings for updates.",
   "response": "Execute",
   "areaDesc": "San Juan and Vicinity; Northeast; Southeast; Eastern Interior; North Central; Ponce and Vicinity; Northwest; Mayaguez and Vicinity; Southwest; Culebra; Vieques; St.Thomas...St. John.. and Adjacent Islands; St Croix",
   "sent": "2026-08-28T01:43:00-04:00",
   "onset": "2026-08-28T10:00:00-04:00",
   "expires": "2026-08-28T12:00:00-04:00",
   "id": "urn:oid:2.49.0.1.840.0.4d450c2b5a27efc185a9844d410cfdb7b8a34365.001.1",
   "parameters": {
    "VTEC": [
     "/O.NEW.TJSJ.HT.Y.0047.260828T1400Z-260828T2100Z/"
    ],
    "BLOCKCHANNEL": [
     "EAS",
     "NWEM",
     "CMAS"
    ]
   }
  },
  "geometry": null
 },
 "amber": {
  "properties": {
   "event": "Child Abduction Emergency",
   "category": "Rescue",
   "severity": "Extreme",
   "urgency": "Immediate",
   "certainty": "Observed",
   "status": "Actual",
   "headline": "AMBER Alert",
   "description": "AN AMBER ALERT IS BEING ISSUED BY THE CALIFORNIA HIGHWAY PATROL ON BEHALF OF THE LOS ANGELES POLICE DEPARTMENT.\n\nON AUGUST 27, 2026, AT 11 30 AM, JAX ROBOTTOM WAS TAKEN FROM LOS ANGELES, CALIFORNIA.  ",
   "instruction": null,
   "response": null,
   "areaDesc": "Los Angeles, CA",
   "sent": "2026-08-27T13:41:40-07:00",
   "onset": null,
   "expires": "2026-08-27T15:41:40-07:00",
   "id": "2709404419947592",
   "parameters": {
    "BLOCKCHANNEL": [
     "CAPEXCH",
     "CMAS"
    ]
   }
  },
  "geometry": null
 }
}
""")

TORNADO = A.parse(RECORDS["tornado"])
SEVERE = A.parse(RECORDS["severe"])
ADVISORY = A.parse(RECORDS["advisory"])
AMBER = A.parse(RECORDS["amber"])


# -- the finding, asserted rather than trusted ------------------------------

def test_severity_alone_cannot_tell_them_apart() -> None:
    """The premise of the whole design, checked against the real records.

    A tornado bearing down on somebody and an Amber Alert are the same on
    every field a textbook escalation reads. If this ever stops being true the
    design can be simpler, and if it stays true nobody should be tempted to
    simplify it.
    """
    for field in ("severity", "urgency", "certainty"):
        check(getattr(TORNADO, field) == getattr(AMBER, field),
              f"a tornado and an abduction now differ on {field}, so the "
              f"category gate may no longer be the only thing separating them")
    check(TORNADO.category != AMBER.category,
          "the two records no longer differ by category either, which would "
          "leave nothing at all to separate them")
    check(TORNADO.category == A.WEATHER, "a tornado is not categorised as weather")
    check(AMBER.category == "Rescue", "the abduction record changed category")


def test_the_gate_keeps_weather_and_nothing_else() -> None:
    kept = A.weather_only([TORNADO, SEVERE, ADVISORY, AMBER])
    check(AMBER not in kept, "an Amber Alert reached the login screen")
    check(len(kept) == 3, f"the gate kept {len(kept)} of four weather records")


def test_a_test_message_never_reaches_the_screen() -> None:
    """`status` is `Actual`, `Exercise`, `System`, `Test` or `Draft`.

    A routine monthly test taking over somebody's screen in red is the most
    embarrassing possible failure of this feature, and it is one comparison.
    """
    drill = A.parse(RECORDS["tornado"])
    drill.status = "Test"
    check(A.weather_only([drill]) == [],
          "a message marked Test was treated as a real emergency")


def test_how_loudly() -> None:
    check(A.tier(TORNADO) == A.TAKEOVER,
          f"a tornado warning is {A.tier(TORNADO)!r} rather than a takeover")
    check(A.tier(SEVERE) == A.BANNER,
          f"a severe thunderstorm warning is {A.tier(SEVERE)!r}")
    check(A.tier(ADVISORY) == A.LINE,
          f"a heat advisory is {A.tier(ADVISORY)!r}")


def test_the_two_decisions_stay_separate() -> None:
    """`tier` is only ever asked about alerts that got through the gate.

    Written as one condition the two collapse into each other and the bug
    comes back the first time somebody tidies the code, so the shape is the
    protection: `tier` does not look at category at all, and that is only safe
    because nothing calls it without gating first.
    """
    import inspect
    source = inspect.getsource(A.tier)
    check("category" not in source,
          "tier() reads the category, which means the two decisions have been "
          "folded together again")
    source = inspect.getsource(A.weather_only)
    check("severity" not in source and "urgency" not in source,
          "weather_only() reads severity, which means the gate has become "
          "conditional on how loud something is")


# -- one storm, however many messages it sends ------------------------------

def test_vtec_names_one_event_across_its_updates() -> None:
    action, identity = A._vtec_parts(
        "/O.NEW.KCTP.TO.W.0030.260828T0045Z-260828T0130Z/")
    check(action == "NEW", f"the VTEC action came out as {action!r}")
    check(identity == "KCTP.TO.W.0030",
          f"the event identity came out as {identity!r}")
    later, same = A._vtec_parts(
        "/O.CON.KCTP.TO.W.0030.000000T0000Z-260828T0130Z/")
    check(later == "CON", f"a continuation came out as {later!r}")
    check(same == identity,
          "the same storm got two identities, so it would alarm twice")
    check(A._vtec_parts("") == ("", ""), "an absent VTEC raised or invented one")
    check(A._vtec_parts("nonsense") == ("", ""), "a malformed VTEC was parsed")


def test_finished_and_expired_alerts_drop_out() -> None:
    now = _dt.datetime(2026, 8, 28, 12, 0, tzinfo=_dt.timezone.utc)
    live = A.parse(RECORDS["tornado"])
    live.action = "NEW"
    live.expires = now + _dt.timedelta(minutes=30)
    cancelled = A.parse(RECORDS["tornado"])
    cancelled.action = "CAN"
    cancelled.expires = now + _dt.timedelta(minutes=30)
    stale = A.parse(RECORDS["tornado"])
    stale.action = "NEW"
    stale.expires = now - _dt.timedelta(minutes=1)
    kept = A.live([live, cancelled, stale], now)
    check(kept == [live],
          f"{len(kept)} of three survived, and only one is still happening")


def test_one_storm_is_one_alert() -> None:
    early = A.parse(RECORDS["tornado"])
    early.identifier = "KCTP.TO.W.0030"
    early.sent = _dt.datetime(2026, 8, 28, 12, 0, tzinfo=_dt.timezone.utc)
    early.headline = "first"
    late = A.parse(RECORDS["tornado"])
    late.identifier = "KCTP.TO.W.0030"
    late.sent = _dt.datetime(2026, 8, 28, 12, 20, tzinfo=_dt.timezone.utc)
    late.headline = "second"
    other = A.parse(RECORDS["severe"])
    other.identifier = "KDDC.SV.W.0268"
    kept = A.newest([early, late, other])
    check(len(kept) == 2, f"{len(kept)} alerts for two storms")
    heads = {a.headline for a in kept}
    check("second" in heads and "first" not in heads,
          f"the older message won: {heads}")


def test_loudest_first_then_soonest() -> None:
    now = _dt.datetime(2026, 8, 28, 12, 0, tzinfo=_dt.timezone.utc)
    top = A.parse(RECORDS["tornado"])
    top.expires = now + _dt.timedelta(hours=4)
    middle = A.parse(RECORDS["severe"])
    middle.expires = now + _dt.timedelta(minutes=10)
    bottom = A.parse(RECORDS["advisory"])
    bottom.expires = now + _dt.timedelta(minutes=5)
    order = [a.event for a in A.rank([bottom, middle, top])]
    check(order[0] == top.event,
          f"an expiring advisory outranked a tornado warning: {order}")
    check(order[-1] == bottom.event, f"the quietest is not last: {order}")

    # Two of equal weight go by which runs out first.
    soon = A.parse(RECORDS["severe"])
    soon.expires = now + _dt.timedelta(minutes=5)
    later = A.parse(RECORDS["severe"])
    later.expires = now + _dt.timedelta(hours=2)
    check(A.rank([later, soon])[0] is soon,
          "two warnings of equal weight were not ordered by expiry")


# -- whether it was on the radio, and whether it is coming this way ---------

def test_broadcast_comes_from_the_field_not_a_guess() -> None:
    """`BLOCKCHANNEL` lists the channels a message is blocked from."""
    blocked = A.parse(RECORDS["tornado"])
    check(blocked.broadcast is False,
          "a message blocked from EAS was treated as having been broadcast")
    record = json.loads(json.dumps(RECORDS["tornado"]))
    record["properties"]["parameters"]["BLOCKCHANNEL"] = ["NWEM"]
    check(A.parse(record).broadcast is True,
          "a message blocked only from NWEM was treated as not broadcast")
    record["properties"]["parameters"].pop("BLOCKCHANNEL")
    check(A.parse(record).broadcast is True,
          "a message with no block list was treated as blocked")


def test_the_motion_vector_is_read() -> None:
    found = A._motion(
        "2026-08-28T00:45:00-00:00...storm...288DEG...11KT...40.08,-76.1")
    check(found is not None, "a real motion description did not parse")
    if found:
        check(found["bearing"] == 288, f"bearing came out {found['bearing']}")
        check(abs(found["knots"] - 11.0) < 0.01,
              f"speed came out {found['knots']}")
        check(abs(found["latitude"] - 40.08) < 0.01,
              f"latitude came out {found['latitude']}")
    check(A._motion("") is None, "an absent motion invented one")
    check(A._motion("...storm...288DEG...") is None,
          "a partial motion was accepted, which would give a false arrival time")


def test_coming_towards_you_and_going_away() -> None:
    """The arithmetic behind "it is heading this way".

    A storm at 40.0N 76.5W moving on a bearing of 90 degrees is heading east.
    A place east of it is in its way; a place west of it is not, and saying
    so is the difference between a warning and an alarm.
    """
    storm = A.parse(RECORDS["tornado"])
    storm.motion = {"bearing": 90, "knots": 30.0,
                    "latitude": 40.0, "longitude": -76.5}
    east = A.approaching(storm, 40.0, -76.0)
    west = A.approaching(storm, 40.0, -77.0)
    check(east is not None and east["towards"],
          f"a place directly in the storm's path is not called approaching: {east}")
    check(west is not None and not west["towards"],
          f"a place behind the storm is called approaching: {west}")
    check(east and east["minutes"] is not None and 30 <= east["minutes"] <= 70,
          f"the arrival estimate is not plausible: {east}")
    check(west and west["minutes"] is None,
          "a storm moving away was given an arrival time")
    check(A.approaching(ADVISORY, 40.0, -76.0) is None,
          "an alert with no motion vector was given a direction anyway")


def test_the_whole_pipeline_in_one_call() -> None:
    now = _dt.datetime(2026, 8, 28, 12, 0, tzinfo=_dt.timezone.utc)
    records = []
    for key in ("tornado", "severe", "advisory", "amber"):
        record = json.loads(json.dumps(RECORDS[key]))
        record["properties"]["parameters"]["VTEC"] = [
            f"/O.NEW.XXXX.{key[:2].upper()}.W.0001.000000T0000Z-260829T0000Z/"]
        record["properties"]["expires"] = "2026-08-28T18:00:00+00:00"
        records.append(record)
    out = A.shown(records, now)
    check(len(out) == 3, f"the pipeline returned {len(out)} of four records")
    check(all(a.category == A.WEATHER for a in out),
          "something that is not weather came out of the pipeline")
    check(A.tier(out[0]) == A.TAKEOVER,
          f"the loudest is not first: {[a.event for a in out]}")


def main() -> int:
    tests = sorted(n for n in globals() if n.startswith("test_"))
    for name in tests:
        globals()[name]()
    ran = sorted(n for n in globals() if n.startswith("test_"))
    if ran != tests:
        print(f"greeter-alerts: {len(tests)} found and {len(ran)} ran",
              file=sys.stderr)
        return 1
    if FAILURES:
        for failure in FAILURES:
            print(f"greeter-alerts: {failure}", file=sys.stderr)
        return 1
    print(f"greeter alerts test: PASS ({CHECKS} checks, {len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
