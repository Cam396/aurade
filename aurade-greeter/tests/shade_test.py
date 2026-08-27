#!/usr/bin/env python3
"""The screen before anybody has touched it, and the two things it works out.

The greeting is a table and is here mostly so the boundaries cannot drift.
The occasions are the part worth testing properly, because they are the one
thing on this screen that claims to know something about the world, and a
login screen that announces the wrong solstice is worse than one that never
mentions it.

They are checked against the published 2026 turns, which is somebody else's
arithmetic rather than a rerun of this file's own. The first implementation
put three of the four on the wrong day and passed every test that compared it
to itself.

The card is the other half. Every line it draws has to be a line the manifest
actually carries, because a picture of nowhere in particular that grows a
place name has invented a fact about itself.
"""
from __future__ import annotations

import datetime as _dt
import os
import sys

# Before importing anything that pulls in GTK. A DISPLAY pointing at an X
# server that is not listening makes the GDK backend probe sit in SYN_SENT for
# about two minutes, which looks exactly like a hung test suite and is not one.
os.environ.pop("DISPLAY", None)
os.environ.setdefault("GTK_A11Y", "none")

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..")))

#: Where the pictures are, set before anything is imported.
#:
#: `brand` builds its list of candidate directories once, at import, from the
#: environment. Setting the variable after the import has no effect at all,
#: which is a quiet way to end up asserting against an empty set and calling
#: it a pass.
PICTURES = os.path.normpath(os.path.join(HERE, "..", "..", "installer",
                                         "wallpapers"))
if os.path.isdir(PICTURES):
    os.environ.setdefault("AURADE_WALLPAPER_DIR", PICTURES)

from aurade_greeter import copy as C  # noqa: E402
from aurade_greeter import shade as SH  # noqa: E402

FAILURES: list[str] = []
UTC = _dt.timezone.utc
try:
    from zoneinfo import ZoneInfo
    NEW_YORK = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - no tzdata on this machine
    NEW_YORK = None


def check(ok: bool, message: str) -> None:
    if not ok:
        FAILURES.append(message)


def at(year: int, month: int, day: int, hour: int = 12, zone=UTC):
    return _dt.datetime(year, month, day, hour, tzinfo=zone)


# -- the greeting -----------------------------------------------------------

for hour, wanted in ((5, "morning"), (9, "morning"), (11, "morning"),
                     (12, "afternoon"), (15, "afternoon"), (17, "afternoon"),
                     (18, "evening"), (23, "evening"), (0, "evening"),
                     (4, "evening")):
    said = SH.greeting(at(2026, 8, 27, hour))
    check(said == C.GREETING.format(part=wanted),
          f"{hour:02d}:00 was greeted with {said!r} rather than {wanted}")

# Every hour of the day is in exactly one band. A gap would leave somebody
# signing in at that hour looking at the fallback with no explanation.
for hour in range(24):
    matched = [part for start, end, part in SH.BANDS if start <= hour < end]
    check(len(matched) == 1,
          f"{hour:02d}:00 falls in {len(matched)} greeting bands, not one")

# The setting that turns the remark off is a return to what this screen said
# before any of this existed, not a downgrade to something new.
check(SH.greeting(at(2026, 8, 27, 9), "plain") == C.TITLE,
      "plain greeting is not the wording this screen used before")
check(SH.greeting(at(2026, 8, 27, 9), "plain", returning=False) == C.TITLE_FIRST,
      "a machine nobody has signed into yet is welcomed back")
check(SH.greeting(at(2026, 8, 27, 9), "hour", returning=False)
      == C.GREETING.format(part="morning"),
      "the hour greeting changed because nobody had signed in before")


# -- where the sun is -------------------------------------------------------

# Pinned against the published turns of 2026, in UTC.
TURNS = {
    _dt.date(2026, 3, 20): ("equinox", C.OCCASION_EQUINOX),
    _dt.date(2026, 6, 21): ("june", C.OCCASION_LONGEST),
    _dt.date(2026, 9, 23): ("equinox", C.OCCASION_EQUINOX),
    _dt.date(2026, 12, 21): ("december", C.OCCASION_SHORTEST),
}

said_days = []
day = _dt.date(2026, 1, 1)
while day <= _dt.date(2026, 12, 31):
    words = SH.occasion(at(day.year, day.month, day.day, 12), 41.0)
    if words:
        said_days.append((day, words))
    day += _dt.timedelta(days=1)

turns = [(d, w) for d, w in said_days if "moon" not in w.lower()]
check(len(turns) == 4,
      f"2026 had {len(turns)} solstices and equinoxes rather than four")
for date, wanted in TURNS.items():
    found = [w for d, w in turns if d == date]
    check(found == [wanted[1]],
          f"{date} should say {wanted[1]!r} and says {found!r}")

# Twelve moons and four turns, and nothing on any other day. A line that
# appeared every morning would be furniture.
check(12 <= len(said_days) <= 22,
      f"{len(said_days)} days of 2026 say something, which is too many or too few")
check(len(said_days) < 30, "the occasion line is close to being permanent")

# The reader's own day, not a UTC one. The September equinox of 2026 falls at
# six minutes past midnight UTC, which is the previous evening in New York.
if NEW_YORK is not None:
    check(SH.occasion(at(2026, 9, 22, 20, NEW_YORK), 41.0) == C.OCCASION_EQUINOX,
          "an equinox that happened during a New York evening was put on the "
          "wrong day for a reader in New York")
    check(SH.occasion(at(2026, 9, 23, 20, NEW_YORK), 41.0) != C.OCCASION_EQUINOX,
          "the equinox was announced twice in New York")

# The longest day in Oslo is the shortest in Wellington.
june = at(2026, 6, 21)
december = at(2026, 12, 21)
check(SH.occasion(june, 59.9) == C.OCCASION_LONGEST,
      "the June solstice is not the longest day in the north")
check(SH.occasion(june, -41.3) == C.OCCASION_SHORTEST,
      "the June solstice is not the shortest day in the south")
check(SH.occasion(december, 59.9) == C.OCCASION_SHORTEST,
      "the December solstice is not the shortest day in the north")
check(SH.occasion(december, -41.3) == C.OCCASION_LONGEST,
      "the December solstice is not the longest day in the south")
check(SH.occasion(june, 0.0) == C.OCCASION_LONGEST,
      "the equator was treated as southern")
check(SH.occasion(june, None) == C.OCCASION_SOLSTICE,
      "a machine that does not know where it is still picked a hemisphere")
check(SH.occasion(december, None) == C.OCCASION_SOLSTICE,
      "a machine that does not know where it is still picked a hemisphere")
check(SH.occasion(at(2026, 3, 20), None) == C.OCCASION_EQUINOX,
      "an equinox needed a latitude, and it does not")

# The longitude itself, which is what the turns are read off.
check(abs(SH.solar_longitude(at(2026, 3, 20, 15)) - 0.0) < 1.0
      or abs(SH.solar_longitude(at(2026, 3, 20, 15)) - 360.0) < 1.0,
      "the sun was not at the vernal point at the March equinox")
check(abs(SH.solar_longitude(at(2026, 6, 21, 8)) - 90.0) < 1.0,
      "the sun was not a quarter round at the June solstice")
check(abs(SH.solar_longitude(at(2026, 9, 23, 0)) - 180.0) < 1.0,
      "the sun was not half round at the September equinox")
check(abs(SH.solar_longitude(at(2026, 12, 21, 21)) - 270.0) < 1.0,
      "the sun was not three quarters round at the December solstice")
for moment in (at(2020, 1, 1), at(2030, 7, 15), at(1999, 12, 31)):
    value = SH.solar_longitude(moment)
    check(0.0 <= value < 360.0,
          f"the sun's longitude came out {value} at {moment}")

# A day is a day. Asking about a window shorter than a degree of travel must
# not find a crossing that is not in it.
check(SH.quarter_crossed(at(2026, 6, 1, 0), at(2026, 6, 2, 0)) is None,
      "a turn was found on a day with no turn in it")
check(SH.quarter_crossed(at(2026, 6, 21, 0), at(2026, 6, 22, 0)) == 90.0,
      "the June solstice was not found in the day it falls on")
# Midnight to midnight, not noon to noon. The June solstice of 2026 is at
# twenty five past eight in the morning, so a window that opens at noon has
# already missed it, and must say so rather than reporting the next one.
check(SH.quarter_crossed(at(2026, 6, 21, 12), at(2026, 6, 22, 12)) is None,
      "a window opening after the turn still reported the turn")

# The moon, on the one night a month it is worth mentioning.
moons = [d for d, w in said_days if w == C.OCCASION_FULL_MOON]
check(11 <= len(moons) <= 18,
      f"2026 had {len(moons)} full moon evenings, which is not about twelve")
check(all(w in (C.OCCASION_EQUINOX, C.OCCASION_SOLSTICE, C.OCCASION_LONGEST,
                C.OCCASION_SHORTEST, C.OCCASION_FULL_MOON)
          for _d, w in said_days),
      "the shade said something that is not one of the five things it can say")


# -- what the card can honestly say ------------------------------------------

somewhere = {
    "title": "Bagan, Myanmar", "place": "Bagan, Myanmar",
    "zone": "Asia/Yangon",
    "note": "Brick temples standing out of the morning haze across the plain.",
    "fact": "Myanmar keeps its clocks half an hour off the hour.",
}
nowhere = {"title": "A river between hills", "place": "", "zone": "",
           "note": "A river running out of frame between two slopes.",
           "fact": ""}

lines = SH.card_lines(somewhere)
check(lines["title"] == "Bagan, Myanmar", "the card lost the title")
check(lines["note"] == somewhere["note"], "the card lost the sentence")
check(lines["fact"] == somewhere["fact"], "the card lost the fact")
check("there" in lines["when"] or lines["when"] == "",
      f"the time line reads {lines['when']!r}, which does not say where")

blank = SH.card_lines(nowhere)
check(blank["title"] == "A river between hills",
      "a picture of nowhere lost its title")
check(blank["note"] == nowhere["note"], "a picture of nowhere lost its sentence")
check(blank["when"] == "",
      "a picture with no zone was given a time it could not know")
check(blank["fact"] == "",
      "a picture of nowhere was given a fact about somewhere")

empty = SH.card_lines(None)
check(set(empty) == {"title", "when", "note", "fact"},
      "the card's shape changes depending on whether there is a picture")
check(not any(empty.values()),
      "a card with no picture at all still had something to say")
check(SH.card_lines({})["title"] == "",
      "an empty manifest row produced a title")

# A zone the database does not have must lose the line rather than the card.
odd = dict(somewhere)
odd["zone"] = "Mars/Olympus_Mons"
check(SH.card_lines(odd)["when"] == "",
      "an unknown time zone produced a time")
check(SH.card_lines(odd)["title"] == somewhere["title"],
      "an unknown time zone cost the card its title as well")

# -- which picture suits this hour -------------------------------------------

# Every hour of the day answers to exactly one band on a machine that does not
# know where it is. A gap would leave the fallback picking at that hour with no
# explanation.
for hour in range(24):
    matched = [part for start, end, part in SH.CLOCK_BANDS if start <= hour < end]
    check(len(matched) <= 1, f"{hour:02d}:00 falls in {len(matched)} clock bands")
    said = SH.light_now(at(2026, 8, 27, hour))
    check(said in ("dawn", "day", "dusk", "night"),
          f"{hour:02d}:00 was called {said!r}, which is not a kind of light")

# With a coordinate the sun answers instead of the clock, and the two disagree
# exactly where they should. In Tromso in June the clock says the small hours
# and the sun is well up, and a screen that put an aurora on the wall there
# would be the only thing in the room that had not noticed.
TROMSO = (69.65, 18.96)
check(SH.light_now(at(2026, 6, 21, 3), *TROMSO) == "day",
      "the midnight sun was called night")
check(SH.light_now(at(2026, 6, 21, 3)) == "night",
      "without a coordinate three in the morning stopped being night")
# In December the sun there never clears the horizon, so no hour of that day
# may be called day. Its highest point is about four degrees below, which is
# real twilight and not night, and calling it night would be as wrong in the
# other direction.
december = {SH.light_now(at(2026, 12, 21, hour), *TROMSO) for hour in range(24)}
check("day" not in december,
      f"the polar night had daylight in it: {sorted(december)}")
check(december & {"dawn", "dusk"},
      "the polar night had no twilight in it, and its noon is four degrees "
      "below the horizon")
check("night" in december, "the polar night had no night in it")

ARDSLEY = (41.0126, -73.8437)
if NEW_YORK is not None:
    check(SH.light_now(at(2026, 8, 27, 13, NEW_YORK), *ARDSLEY) == "day",
          "one in the afternoon in August was not day")
    check(SH.light_now(at(2026, 8, 27, 2, NEW_YORK), *ARDSLEY) == "night",
          "two in the morning was not night")
    check(SH.light_now(at(2026, 8, 27, 6, NEW_YORK), *ARDSLEY) == "dawn",
          "an hour before sunrise was not dawn")
    check(SH.light_now(at(2026, 8, 27, 20, NEW_YORK), *ARDSLEY) == "dusk",
          "half an hour after sunset was not dusk")
    # Dawn and dusk are told apart by which side of the day they are on, not
    # by the height of the sun, which is the same at both.
    morning = SH.light_now(at(2026, 8, 27, 6, NEW_YORK), *ARDSLEY)
    evening = SH.light_now(at(2026, 8, 27, 20, NEW_YORK), *ARDSLEY)
    check(morning != evening,
          "the same low sun was called the same thing morning and evening")

# The two rules in `suited` do two different jobs, so they are checked apart.
SET = [
    {"file": "night.png", "light": "night", "luminance": 0.04},
    {"file": "day.png", "light": "day", "luminance": 0.22},
    {"file": "whiteout.png", "light": "day", "luminance": 0.51},
    {"file": "untellable.png", "light": "", "luminance": 0.09},
]
small = at(2026, 8, 27, 3)
noon = at(2026, 8, 27, 13)

names = {e["file"] for e in SH.suited(SET, "day", small)}
check("whiteout.png" not in names,
      "a white out was offered at three in the morning")
check("whiteout.png" in {e["file"] for e in SH.suited(SET, "day", noon)},
      "a bright picture was refused at one in the afternoon")
check("untellable.png" in {e["file"] for e in SH.suited(SET, "night", noon)},
      "a picture whose light cannot be told was refused an hour")
check("untellable.png" in {e["file"] for e in SH.suited(SET, "dusk", noon)},
      "a picture whose light cannot be told was refused another hour")
check({e["file"] for e in SH.suited(SET, "night", noon)} == {"night.png", "untellable.png"},
      "the night band picked up a picture that is not night")
# Giving way rather than emptying: an hour nothing matches gets everything.
check(len(SH.suited(SET, "dawn", noon)) >= 1,
      "an hour with no matching picture was given nothing to draw")
check(SH.suited([], "day", noon) == [],
      "an empty set produced a picture out of nowhere")
# And the cap gives way too, rather than leaving a machine with no wallpaper.
bright = [{"file": "a.png", "light": "day", "luminance": 0.9}]
check(SH.suited(bright, "night", small) == bright,
      "a set where every picture is bright left the screen with none")

# -- against the real set, where there is one --------------------------------

# Guarded on whether the pictures were actually read, not on whether a
# relative path exists. The path is `../../installer/wallpapers`, which
# resolves to nothing when this file is run from a copy, and three mutations
# survived a run that had quietly skipped every assertion below.
from aurade_greeter import brand  # noqa: E402

every = brand.wallpapers()
if every:
    check(len(every) > 10, f"only {len(every)} pictures were read from the set")
    for entry in every:
        check(entry["light"] in ("", "dawn", "day", "dusk", "night"),
              f"{entry['file']} has light {entry['light']!r}, which is not a "
              f"kind of light")
        check(0.0 < entry["luminance"] < 1.0,
              f"{entry['file']} measured {entry['luminance']} luminance")

    # The one that matters: no picture is unreachable. A photograph that no
    # hour of any season will ever choose is a photograph that was shipped and
    # cannot be seen, and nothing else in the repository would notice.
    reachable = set()
    for month in (1, 4, 7, 10):
        for hour in range(24):
            when = at(2026, month, 15, hour)
            light = SH.light_now(when, *ARDSLEY)
            for entry in SH.suited(every, light, when):
                reachable.add(entry["file"])
    stranded = sorted({e["file"] for e in every} - reachable)
    check(not stranded, f"these pictures no hour will ever choose: {stranded}")

    # And every band has something in it, so no hour falls back to the whole
    # set and quietly stops matching at all.
    for band in ("dawn", "day", "dusk", "night"):
        have = [e for e in every if e["light"] == band]
        check(have, f"the set has no {band} picture at all")
    # And the low light hours are worth having. The obvious thresholds are
    # civil twilight, plus and minus six degrees, and they leave five of the
    # twenty eight pictures showing for about an hour a day each end. This is
    # the assertion that says the wider window is deliberate.
    hours = {"dawn": 0, "day": 0, "dusk": 0, "night": 0}
    for month in (1, 4, 7, 10):
        for hour in range(24):
            when = at(2026, month, 15, hour)
            hours[SH.light_now(when, *ARDSLEY)] += 1
    low = hours["dawn"] + hours["dusk"]
    check(low >= 14,
          f"only {low} of 96 sampled hours are low light, so the dawn and dusk "
          f"pictures barely appear")
    check(hours["day"] > 20 and hours["night"] > 20,
          f"the day and night bands are lopsided: {hours}")
else:
    print("greeter-shade: not covered: the real picture set is not in this tree",
          file=sys.stderr)

# A measurement the manifest does not carry, or carries badly. An older
# manifest has no such column at all, and the honest reading of an absent
# brightness is that the picture is not known to be bright.
check(brand._fraction("0.25") == 0.25, "a measurement was not read")
check(brand._fraction("") == 0.0, "an absent measurement raised or invented")
check(brand._fraction("bright") == 0.0, "a word was read as a measurement")
check(brand._fraction(None) == 0.0, "a missing field raised")

if FAILURES:
    for failure in FAILURES:
        print(f"greeter-shade: {failure}", file=sys.stderr)
    sys.exit(1)
print(f"greeter shade test: PASS ({len(said_days)} days of 2026 say something, "
      f"{len(turns)} turns)")
