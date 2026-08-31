#!/usr/bin/env python3
"""The sentence, driven to each of its clauses and to silence.

Two properties matter more than the wording.

The first is that nothing is invented. A missing value produces no clause,
never a guess, because the panel has forty other numbers on it and one made up
number would poison the lot. Every test here that supplies `None` expects an
empty string back.

The second is that nothing is said twice. The hourly chart sits directly under
this sentence, so a clause restating the chart is noise, and the thresholds
below are what stops it: rain has to be likely or actually measurable, a front
needs all three of its signs, and a day has to be four degrees off its normal
before that is worth a reader's attention.
"""
from __future__ import annotations

import datetime as _dt
import os
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..")))

from aurade_greeter import outlook as O  # noqa: E402
from aurade_greeter import weather as W  # noqa: E402
from aurade_greeter import copy as C  # noqa: E402

FAILURES: list[str] = []
CHECKS = 0
ZONE = _dt.timezone.utc
NOW = _dt.datetime(2026, 8, 28, 6, 0, tzinfo=ZONE)


def check(condition: bool, message: str) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(message)


def hours(**series) -> list:
    """A run of hours from parallel lists, starting an hour from now."""
    length = max(len(v) for v in series.values())
    out = []
    for index in range(length):
        out.append(W.Hour(
            at=NOW + _dt.timedelta(hours=index + 1),
            **{name: values[index] if index < len(values) else None
               for name, values in series.items()}))
    return out


def report(**fields) -> W.Report:
    made = W.Report(latitude=41.0, longitude=-74.0)
    for name, value in fields.items():
        setattr(made, name, value)
    return made


# -- rain -------------------------------------------------------------------

def test_rain_says_when_and_how_much() -> None:
    said = O.rain(report(hours=hours(
        precipitation=[0, 0, 80, 90, 70, 0, 0],
        amount=[0.0, 0.0, 1.2, 2.0, 0.8, 0.0, 0.0])), NOW, "c")
    check("Rain" in said, f"the rain clause does not mention rain: {said!r}")
    check("4 mm" in said, f"the total is wrong or missing: {said!r}")
    check("Clearing" in said, f"the end of the run is missing: {said!r}")


def test_rain_in_inches_beside_fahrenheit() -> None:
    said = O.rain(report(hours=hours(
        precipitation=[0, 90, 90], amount=[0.0, 12.7, 12.7])), NOW, "f")
    check("in" in said and "mm" not in said,
          f"a Fahrenheit reader was told millimetres: {said!r}")


def test_snow_is_not_called_rain() -> None:
    said = O.rain(report(hours=hours(
        precipitation=[0, 90, 90], amount=[0.0, 3.0, 3.0],
        snow=[0.0, 3.0, 3.0])), NOW, "c")
    check("Snow" in said, f"snow was described as rain: {said!r}")


def test_a_dry_day_says_nothing_about_rain() -> None:
    said = O.rain(report(hours=hours(
        precipitation=[0, 5, 10, 5], amount=[0.0, 0.0, 0.0, 0.0])), NOW, "c")
    check(said == "", f"a dry day produced a rain clause: {said!r}")


def test_no_readings_produce_no_clause() -> None:
    check(O.rain(report(hours=[]), NOW, "c") == "",
          "an empty forecast produced a rain clause")
    check(O.rain(report(hours=hours(
        precipitation=[None, None], amount=[None, None])), NOW, "c") == "",
        "missing readings were treated as rain")


# -- the front --------------------------------------------------------------

def _front_series():
    """Pressure falling, wind swinging south to north, temperature dropping."""
    return hours(
        pressure=[1016, 1015, 1014, 1013, 1012, 1011, 1010, 1010,
                  1011, 1012, 1013, 1014],
        bearing=[180, 185, 190, 200, 230, 270, 300, 330, 350, 355, 0, 5],
        temperature=[24, 24, 23, 22, 20, 18, 16, 14, 13, 12, 12, 12])


def test_a_front_is_named_when_all_three_signs_agree() -> None:
    said = O.front(report(hours=_front_series()), NOW, "c")
    check("front" in said, f"a textbook front was not named: {said!r}")
    check("12" in said, f"the temperature drop is wrong: {said!r}")
    check("north" in said, f"the wind direction is wrong: {said!r}")


def test_the_front_drop_is_a_difference_not_a_temperature() -> None:
    """Twelve Celsius degrees of drop is twenty two Fahrenheit ones, not 53.

    The same mistake as the comparison with normal, in the same sentence, and
    invisible in both: the wording stays correct and only the number is wrong,
    by an amount that looks like weather.
    """
    said = O.front(report(hours=_front_series()), NOW, "f")
    check("22" in said, f"a twelve degree drop came out as: {said!r}")
    check("53" not in said,
          f"the drop was converted as though it were a temperature: {said!r}")


def test_one_sign_alone_is_not_a_front() -> None:
    """Weather, not a front. Saying so would be the panel guessing."""
    only_pressure = hours(
        pressure=[1016, 1015, 1014, 1013, 1012, 1011, 1010, 1010],
        bearing=[180] * 8, temperature=[24] * 8)
    check(O.front(report(hours=only_pressure), NOW, "c") == "",
          "a pressure fall alone was called a front")

    only_wind = hours(
        pressure=[1016] * 8, bearing=[180, 200, 240, 280, 320, 350, 10, 20],
        temperature=[24] * 8)
    check(O.front(report(hours=only_wind), NOW, "c") == "",
          "a wind shift alone was called a front")

    only_cold = hours(
        pressure=[1016] * 8, bearing=[180] * 8,
        temperature=[24, 22, 20, 18, 16, 14, 13, 12])
    check(O.front(report(hours=only_cold), NOW, "c") == "",
          "a cooling evening alone was called a front")


def test_a_short_series_is_not_guessed_at() -> None:
    short = hours(pressure=[1016, 1010], bearing=[180, 0],
                  temperature=[24, 12])
    check(O.front(report(hours=short), NOW, "c") == "",
          "two hours were enough to declare a front")


# -- the air ----------------------------------------------------------------

def test_unstable_air_outranks_muggy() -> None:
    made = report(hours=hours(cape=[400, 1800, 2000]))
    made.now.dew_point = 22.0
    said = O.close(made, NOW, "c")
    check("unstable" in said,
          f"high instability was not mentioned: {said!r}")


def test_muggy_when_the_dew_point_says_so() -> None:
    made = report(hours=hours(cape=[100, 200]))
    made.now.dew_point = 21.5
    check("Muggy" in O.close(made, NOW, "c"),
          "a dew point above twenty was not called muggy")
    made.now.dew_point = 12.0
    check(O.close(made, NOW, "c") == "",
          "a dry day was called muggy")


# -- against the normal -----------------------------------------------------

def test_unusual_days_are_named_and_ordinary_ones_are_not() -> None:
    check("warmer" in O.against_normal(34.0, 28.0, "c"),
          "six degrees above normal was not called warmer")
    check("colder" in O.against_normal(22.0, 28.0, "c"),
          "six degrees below normal was not called colder")
    check(O.against_normal(29.0, 28.0, "c") == "",
          "a degree above normal was worth a sentence")
    check(O.against_normal(None, 28.0, "c") == "",
          "an unknown high was compared with a normal anyway")
    check(O.against_normal(34.0, None, "c") == "",
          "a high was compared with an unknown normal")


def test_the_difference_is_in_the_readers_units() -> None:
    """Six Celsius degrees of difference is eleven Fahrenheit ones."""
    said = O.against_normal(34.0, 28.0, "f")
    check("11" in said, f"the difference was not converted: {said!r}")


# -- everything together ----------------------------------------------------

def test_the_whole_sentence_is_ordered_by_how_soon_it_matters() -> None:
    made = report(hours=_front_series())
    for index, hour in enumerate(made.hours):
        hour.precipitation = 90 if index < 3 else 0
        hour.amount = 2.0 if index < 3 else 0.0
        hour.cape = 2000.0
    made.days = [W.Day(date=_dt.date(2026, 8, 28), high=34.0, low=20.0)]
    made.now.dew_point = 22.0
    said = O.sentence(made, NOW, "c", normal=26.0)
    check(said.index("Rain") < said.index("front"),
          f"the front is described before the rain: {said!r}")
    check(said.index("front") < said.index("unstable"),
          f"the air is described before the front: {said!r}")
    check("warmer" in said, f"the comparison with normal is missing: {said!r}")
    check(said.index("unstable") < said.index("warmer"),
          f"the comparison came before the air: {said!r}")


def test_a_report_with_nothing_to_say_says_nothing() -> None:
    check(O.sentence(report(), NOW, "c") == "",
          "an empty report produced a sentence")


def _oclock_words(moment) -> str:
    """The module's own words for an hour, so the test does not write a
    second copy of them and then hold the module to it."""
    return O._oclock(moment)


def test_rain_that_has_already_started_is_a_sentence() -> None:
    """"Rain from shortly" is not something a person says.

    Every other value in that hole is a time, and "from" wants a time. The
    word "shortly" dropped into it read as a machine assembling a sentence out
    of parts, which is the one thing this whole module exists not to do.
    """
    here = _dt.datetime(2026, 8, 28, 14, 30)
    soon = W.Report(now=W.Now(temperature=18.0), hours=[
        W.Hour(at=here + _dt.timedelta(minutes=30 + n * 60),
               condition=W.RAIN, precipitation=90 if n < 3 else 5,
               amount=2.0 if n < 3 else 0.0) for n in range(10)])
    said = O.rain(soon, here)
    check("from shortly" not in said, f"the sentence still reads {said!r}")
    check(said.startswith(C.OUTLOOK_RAIN),
          f"the sentence no longer starts with the kind of weather: {said!r}")
    check("shortly" not in said.split(".")[0],
          f"an adverb is still standing where a time belongs: {said!r}")

    # The same case with nothing worth measuring, because the two go through
    # different templates and the first version of this only ever exercised
    # the one that carries an amount.
    trace = W.Report(now=W.Now(temperature=18.0), hours=[
        W.Hour(at=here + _dt.timedelta(minutes=30 + n * 60),
               condition=W.RAIN, precipitation=90 if n < 3 else 5,
               amount=0.0) for n in range(10)])
    dry_said = O.rain(trace, here)
    check(dry_said, "rain likely but unmeasurable said nothing at all")
    check("from shortly" not in dry_said,
          f"the sentence with no amount in it still reads {dry_said!r}")

    # A run that starts hours out names the hour rather than the next minute.
    #
    # Asserted on the shape it must not use. It was asserted on the digit six
    # appearing somewhere in the sentence, and six millimetres of rain put a
    # six in the sentence, so the check passed with the hour deleted entirely.
    later = W.Report(now=W.Now(temperature=18.0), hours=[
        W.Hour(at=here + _dt.timedelta(hours=n),
               condition=W.RAIN, precipitation=90 if 4 <= n < 7 else 5,
               amount=2.0 if 4 <= n < 7 else 0.0) for n in range(12)])
    said = O.rain(later, here)
    hour = _oclock_words(here + _dt.timedelta(hours=4))
    check(hour and hour in said,
          f"rain four hours away lost its hour: {said!r} does not contain "
          f"{hour!r}")
    check("within the hour" not in said,
          f"rain four hours away is described as imminent: {said!r}")


def test_the_sky_now_and_when_it_stops() -> None:
    """The line under the clock, and the silence that is its normal state."""
    here = _dt.datetime(2026, 8, 28, 14, 0)

    wet = W.Report(now=W.Now(temperature=18.0), hours=[
        W.Hour(at=here + _dt.timedelta(hours=n),
               condition=W.HEAVY_RAIN if n < 3 else W.CLOUDY)
        for n in range(10)])
    found = O.spell(wet, here)
    check(found is not None, "a downpour produced no line at all")
    if found:
        kind, words, ends = found
        check(kind == W.HEAVY_RAIN, f"the spell is {kind!r}")
        check(words == W.WORDS[W.HEAVY_RAIN],
              f"the words are {words!r}, and the intensity is meant to be "
              f"carried by them rather than composed beside them")
        check(ends == here + _dt.timedelta(hours=3),
              f"the spell ends at {ends}, which is not the first dry hour")

    dry = W.Report(now=W.Now(temperature=18.0), hours=[
        W.Hour(at=here + _dt.timedelta(hours=n), condition=W.PARTLY)
        for n in range(10)])
    check(O.spell(dry, here) is None,
          "a partly cloudy afternoon was announced on the lock screen")

    # Rain that outlasts the forecast has no honest end.
    forever = W.Report(now=W.Now(temperature=18.0), hours=[
        W.Hour(at=here + _dt.timedelta(hours=n), condition=W.RAIN)
        for n in range(10)])
    found = O.spell(forever, here)
    check(found is not None and found[2] is None,
          f"the edge of the forecast was dressed up as a time it stops: "
          f"{found}")

    check(O.spell(W.Report(), here) is None,
          "a report with no hours in it produced a spell")


def main() -> int:
    tests = sorted(n for n in globals() if n.startswith("test_"))
    for name in tests:
        globals()[name]()
    ran = sorted(n for n in globals() if n.startswith("test_"))
    if ran != tests:
        print(f"greeter-outlook: {len(tests)} found and {len(ran)} ran",
              file=sys.stderr)
        return 1
    if FAILURES:
        for failure in FAILURES:
            print(f"greeter-outlook: {failure}", file=sys.stderr)
        return 1
    print(f"greeter outlook test: PASS ({CHECKS} checks, {len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
