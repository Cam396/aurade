#!/usr/bin/env python3
"""How the login screen behaves, and what a hand edited file cannot make it do.

This record is edited by hand, on a machine somebody may be trying to rescue,
by somebody who is not reading a schema. So the rules that matter are the ones
about bad input: a typo has to land on the ordinary appearance rather than on
a screen that will not draw, and a value that would make the screen unusable
has to be clamped rather than obeyed.

The rule with the most behind it is the last one. Turning the weather on means
this machine makes a network request from its login screen before anybody has
authenticated. A record that asks for that without saying where to ask about
is not a request this screen can honour, and it resolves to off here, once, so
there is one place to look when somebody says they turned it on and nothing
happened.
"""
from __future__ import annotations

import os
import time
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..")))

from aurade_greeter import settings as S  # noqa: E402
from aurade_greeter import copy as C  # noqa: E402

FAILURES: list[str] = []


def check(ok: bool, message: str) -> None:
    if not ok:
        FAILURES.append(message)


def equal(got, want, message: str) -> None:
    check(got == want, f"{message}: expected {want!r}, got {got!r}")


def record(text: str) -> dict[str, str]:
    path = os.path.join(HERE, ".settings-test.conf")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    try:
        return S.read(path)
    finally:
        os.unlink(path)


# A machine with no record at all is every machine installed before this
# existed, and it has to look exactly as it did.
missing = S.read(os.path.join(HERE, "does-not-exist"))
check(missing == S.DEFAULTS or missing["photos"] == "rotate",
      "a missing record does not fall back to the defaults")
check(missing["weather"] == "off",
      "a missing record does not leave the weather off")

# Ordinary reading.
got = record("photos = fixed\nphoto_interval=300\ngreeting = plain\n")
check(got["photos"] == "fixed", f"photos read as {got['photos']}")
check(got["photo_interval"] == "300", f"interval read as {got['photo_interval']}")
check(got["greeting"] == "plain", f"greeting read as {got['greeting']}")

# Quotes come off, because somebody will type them.
check(record('weather_place = "Leeds"\n')["weather_place"] == "Leeds",
      "a quoted value keeps its quotes")

# Comments, blank lines and lines with no separator are skipped rather than
# treated as a failure to read the file.
got = record("# a note\n\nnonsense\nphotos=fixed\n")
check(got["photos"] == "fixed",
      "a stray line stopped the rest of the record being read")

# An unknown key is ignored. A newer greeter's file read by an older one has
# to work, or an upgrade that rolls back leaves somebody at a login screen
# that will not start.
got = record("something_new = yes\nphotos = fixed\n")
check(got["photos"] == "fixed",
      "an unknown key stopped the record being read")
check("something_new" not in got,
      "an unknown key was carried into the record rather than ignored")
check(set(got) == set(S.DEFAULTS),
      "the record grew keys nothing in this greeter knows how to act on")

# Bad values land on the default rather than being obeyed or refused.
check(record("photos = sideways\n")["photos"] == "rotate",
      "an unknown rotation mode was not replaced with the default")
check(record("greeting = shouty\n")["greeting"] == "hour",
      "an unknown greeting mode was not replaced with the default")
check(record("weather_units = kelvin\n")["weather_units"] == "c",
      "an unknown unit was not replaced with the default")
check(record("photo_interval = soon\n")["photo_interval"] == "120",
      "an interval that is not a number was not replaced with the default")

# Clamped, in both directions. A rotation faster than the floor is a slideshow
# and a slideshow on a login screen is somebody's migraine.
check(record("photo_interval = 1\n")["photo_interval"] == str(S.INTERVAL_MIN),
      "an impossibly fast rotation was not clamped")
check(record("photo_interval = 99999999\n")["photo_interval"] == str(S.INTERVAL_MAX),
      "an impossibly slow rotation was not clamped")

# The weather, which is the one that is about behaviour rather than looks.
on = ("weather = on\nweather_latitude = 53.8\nweather_longitude = -1.55\n")
got = record(on)
check(got["weather"] == "on", "a complete weather record did not turn it on")
check(S.coordinates(got) == (53.8, -1.55),
      f"the coordinates came back as {S.coordinates(got)}")

# The contract here changed deliberately, and this is the assertion that
# changed with it. `weather = on` on its own used to switch itself back off,
# because there was nowhere to ask about. It now derives a location from the
# timezone, which is the whole point: turning the weather on should be one
# line, not three, and looking up your own latitude is a computer's job.
#
# The guarantee that assertion existed for survives below, in the case where
# nothing can be derived either.
_alone = record("weather = on\n")
check(_alone["weather"] == "on",
      "the weather did not turn on with a location it could derive")
check(S.coordinates(_alone) is not None,
      "the weather turned on with nowhere to ask about after all")
check(record("weather = on\nweather_latitude = 53.8\n")["weather"] == "off",
      "the weather turned on with only half a coordinate")
check(record("weather = on\nweather_latitude = 91\nweather_longitude = 0\n"
             )["weather"] == "off",
      "the weather turned on for a latitude off the globe")
check(record("weather = on\nweather_latitude = 0\nweather_longitude = 999\n"
             )["weather"] == "off",
      "the weather turned on for a longitude off the globe")
check(record("weather = on\nweather_latitude = north\nweather_longitude = 0\n"
             )["weather"] == "off",
      "the weather turned on for a coordinate that is not a number")
check(S.coordinates(record("weather = off\nweather_latitude = 53.8\n"
                           "weather_longitude = -1.55\n")) is None,
      "coordinates were handed out while the weather was off")

# Somewhere to ask about, named rather than measured.
#
# Requiring a latitude would mean telling somebody to go and look their own up,
# which is asking a person to do a computer's job. A typed name is enough to
# keep the weather on, and it is resolved to a coordinate once.
named = record("weather = on\nweather_place = Ardsley, NY\n")
check(named["weather"] == "on",
      "a place named in words was not enough to keep the weather on")
check(S.place(named) == "Ardsley, NY", "the typed place name was lost")
check(S.coordinates(named) is None,
      "a place with no coordinates handed out coordinates anyway")
check(S.place(record("weather = off\nweather_place = Ardsley, NY\n")) == "",
      "a place name was handed out while the weather was off")
check(record("weather = on\nweather_place = Ardsley\n"
             "weather_latitude = 999\nweather_longitude = 0\n"
             )["weather"] == "on",
      "a usable place name was thrown away because a coordinate was a typo")
check(S.coordinates(record("weather = on\nweather_place = Ardsley\n"
                           "weather_latitude = 999\nweather_longitude = 0\n"
                           )) is None,
      "a coordinate off the globe was handed out because a place name saved it")
# Whitespace is not a place name. It is now treated as nothing typed at all,
# so the timezone answers instead, and what must not happen is the spaces
# being carried through as though somebody had named somewhere.
_spaces = record("weather = on\nweather_place =    \n")
check(S.place(_spaces).strip() == S.place(_spaces),
      f"a place name of nothing but spaces survived: {S.place(_spaces)!r}")
check(S.coordinates(_spaces) is not None,
      "spaces for a place name left the weather with nowhere to ask about")

# Who to ask. Named services exist so somebody debugging a wrong forecast can
# pin the source rather than guess at it.
check(S.provider(record("")) == "auto", "the default service is not automatic")
check(S.provider(record("weather_provider = NWS\n")) == "nws",
      "a service named in capitals was not recognised")
check(S.provider(record("weather_provider = openmeteo\n")) == "openmeteo",
      "Open-Meteo could not be asked for by name")
check(S.provider(record("weather_provider = oracle\n")) == "auto",
      "a service that does not exist was not refused")
for name in S.PROVIDERS:
    check(S.provider(record(f"weather_provider = {name}\n")) == name,
          f"{name} is offered and not accepted")

# Degrees, in whichever of the two scales somebody grew up with.
check(S.units(record("")) == "c", "the default scale is not Celsius")
check(S.units(record("weather_units = F\n")) == "f",
      "Fahrenheit in capitals was not recognised")
check(S.units(record("weather_units = kelvin\n")) == "c",
      "a scale nothing here can render was not refused")

# The words people actually type.
for word in ("on", "yes", "true", "1", "ON", " Yes "):
    check(S.truthy(word, False), f"{word!r} did not read as on")
for word in ("off", "no", "false", "0", "OFF"):
    check(not S.truthy(word, True), f"{word!r} did not read as off")
check(S.truthy("maybe", True) and not S.truthy("maybe", False),
      "an unrecognised word did not fall back to what the caller asked for")


# -- the keyboard, which is the other reason a right password is refused ----
#
# A login screen already warns about Caps Lock. The other cause is a keyboard
# laid out differently from the one the machine thinks it has, and nothing on
# this screen said a word about it: somebody on AZERTY against a QWERTY
# machine types a password they cannot see into a field that keeps saying no.
#
# Read from files rather than asked of the compositor, because this runs
# before anybody has logged in and the system layout is the layout. Three
# shapes, because the three places a system records it do not agree on one.
import tempfile as _tempfile



_dir = _tempfile.mkdtemp(prefix="aurade-layout-")


def _wrote(name: str, body: str) -> str:
    path = os.path.join(_dir, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)
    return path


_xorg = _wrote("00-keyboard.conf",
               'Section "InputClass"\n  Option "XkbLayout" "fr,us"\nEndSection\n')
_debian = _wrote("keyboard", '# a comment\nXKBLAYOUT="de"\nXKBVARIANT=""\n')
_console = _wrote("vconsole.conf", "KEYMAP=uk\n")
_commented = _wrote("commented", '#XKBLAYOUT="ru"\n')
# Commented out in the xorg shape as well, which is the one that needs the
# guard: the shell shape is already rejected because "#XKBLAYOUT" is not
# "XKBLAYOUT", and a test that only covers it proves the guard is unused.
_commented_xorg = _wrote("commented.conf",
                         '#  Option "XkbLayout" "ru"\n')

check(S.keyboard_layout((_xorg,)) == "fr",
      "an xorg snippet's XkbLayout was not read")
check(S.keyboard_layout((_debian,)) == "de",
      "a Debian keyboard record was not read")
check(S.keyboard_layout((_console,)) == "uk",
      "a vconsole KEYMAP was not read")
check(S.keyboard_layout((_commented,)) == "",
      "a commented out shell setting was read as though it were set")
check(S.keyboard_layout((_commented_xorg,)) == "",
      "a commented out xorg option was read as though it were set")
check(S.keyboard_layout(("/nowhere/at/all",)) == "",
      "a missing file raised instead of saying nothing")
# The first file that names one wins, so a machine configured twice is
# reported the way the more canonical of the two says.
check(S.keyboard_layout((_xorg, _debian)) == "fr",
      "the more canonical file did not win")
check(S.keyboard_layout(("/nowhere", _debian)) == "de",
      "a missing first file stopped the search instead of continuing it")

check(S.layout_words("fr") == "French", "a known layout was not spelled out")
check(S.layout_words("cz") == "Czech", "a known layout was not spelled out")
check(S.layout_words("zz") == "ZZ",
      "an unknown layout lost its code instead of being shown in capitals")
check(S.layout_words("") == "",
      "no layout produced a name anyway, which would print an empty sentence")


# -- where this machine is, from what it already knows ----------------------
#
# Turning the weather on meant opening a file and typing a latitude, which is
# most of the reason the setting stays untouched. The timezone this machine is
# already set to names a real place with a published coordinate, in a table
# tzdata has shipped all along.
#
# This does not move the decision about whether to make network requests from
# a login screen. It removes the busywork sitting behind it.
_ZONES = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                      "..", "..", "installer")  # unused, kept for symmetry


# Written inside a directory called `zoneinfo`, because that is how the
# reader recognises a zone name in the first place: it takes what
# `/etc/localtime` resolves to and keeps whatever follows `/zoneinfo/`. A
# fixture somewhere else would make `timezone_name` answer nothing and every
# assertion below would be about the wrong thing.
_ZONEDIR = os.path.join(_dir, "zoneinfo")
os.makedirs(_ZONEDIR, exist_ok=True)


def _zone_table(body: str) -> str:
    path = os.path.join(_ZONEDIR, "zone1970.tab")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)
    return path


_TABLE = _zone_table(
    "# a comment\n"
    "US\t+415100-0873900\tAmerica/Chicago\tCentral (most areas)\n"
    "FR\t+4852+00220\tEurope/Paris\n"
    "NZ\t-3652+17446\tPacific/Auckland\n")

# A zoneinfo directory beside that table, because a legacy zone name is
# resolved by asking which listed zone is the same compiled file. Chicago is
# linked, Paris is copied: tzdata links, but a packager who copied instead
# must not make the machine forget where it is, and the two paths through the
# comparison are otherwise never both taken.
os.makedirs(os.path.join(_ZONEDIR, "America"), exist_ok=True)
os.makedirs(os.path.join(_ZONEDIR, "Europe"), exist_ok=True)
os.makedirs(os.path.join(_ZONEDIR, "US"), exist_ok=True)
with open(os.path.join(_ZONEDIR, "America/Chicago"), "wb") as _handle:
    _handle.write(b"TZif2-shaped bytes for Chicago")
with open(os.path.join(_ZONEDIR, "Europe/Paris"), "wb") as _handle:
    _handle.write(b"TZif2-shaped bytes for Paris ")
for _old, _new in (("America/Chicago", "US/Central"),
                   ("Europe/Paris", "US/Copied")):
    _target = os.path.join(_ZONEDIR, _new)
    if os.path.exists(_target):
        os.remove(_target)
    if _new == "US/Central":
        os.link(os.path.join(_ZONEDIR, _old), _target)
    else:
        with open(os.path.join(_ZONEDIR, _old), "rb") as _read:
            with open(_target, "wb") as _write:
                _write.write(_read.read())

_chicago = S.place_from_timezone(_TABLE, "America/Chicago")
check(_chicago is not None, "the zone table did not yield Chicago")
if _chicago:
    check(abs(_chicago[0] - 41.85) < 0.02,
          f"Chicago's latitude came out {_chicago[0]}")
    check(abs(_chicago[1] + 87.65) < 0.02,
          f"Chicago's longitude came out {_chicago[1]}")
    check(_chicago[2] == "Chicago",
          f"the place is named {_chicago[2]!r}")

# Four digit minutes as well as six digit seconds, because the table uses both.
_paris = S.place_from_timezone(_TABLE, "Europe/Paris")
check(_paris and abs(_paris[0] - 48.8667) < 0.02,
      f"a coordinate without seconds was misread: {_paris}")

# And the southern hemisphere, where both signs are negative and the split
# between the two numbers is the only thing separating them.
_auckland = S.place_from_timezone(_TABLE, "Pacific/Auckland")
check(_auckland and _auckland[0] < 0 and _auckland[1] > 0,
      f"a southern, eastern coordinate came out wrong: {_auckland}")
check(_auckland and _auckland[2] == "Auckland",
      f"an underscore free name came out wrong: {_auckland}")

# Test a legacy timezone alias that is absent from the canonical table.
_legacy = S.place_from_timezone(_TABLE, "US/Central")
check(_legacy is not None,
      "a legacy zone name derived nothing, so a machine set from the old "
      "list has no idea where it is")
if _legacy:
    check(abs(_legacy[0] - 41.85) < 0.02,
          f"the legacy name found the wrong coordinate: {_legacy}")
    check(_legacy[2] == "Chicago",
          f"the legacy name is called {_legacy[2]!r} rather than the place "
          f"it actually is, which would print Central on the panel")

# Same again where the packaging copied the file instead of linking it, so
# the identity check misses and the bytes have to answer.
_copied = S.place_from_timezone(_TABLE, "US/Copied")
check(_copied is not None and _copied[2] == "Paris",
      f"a copied rather than linked zone file was not recognised: {_copied}")

check(S.place_from_timezone(_TABLE, "Nowhere/AtAll") is None,
      "an unknown zone produced a coordinate anyway")
# A name that climbs out of the zoneinfo directory, pointed at a file that
# is really there and really matches. `../../etc/passwd` was the first version
# of this and it could not fail: nothing is at that path relative to a
# temporary directory, so the comparison said no for the wrong reason and the
# guard could be deleted with the test still green.
_outside = os.path.join(_dir, "outside")
with open(os.path.join(_ZONEDIR, "America/Chicago"), "rb") as _read:
    with open(_outside, "wb") as _write:
        _write.write(_read.read())
check(os.path.exists(_outside), "the file this next check needs is not there")
check(S.place_from_timezone(_TABLE, "../outside") is None,
      "a zone name that climbs out of the zoneinfo directory was followed to "
      "a file that matched")
check(S.place_from_timezone("/no/such/table", "America/Chicago") is None,
      "a missing table raised instead of saying nothing")

# Use the fixture for this check so the result is independent of the host zone.
_saved = (S.ZONE_TABLE, S.ZONE_NAME, S.ZONE_LINK)
_link = os.path.join(_dir, "localtime-central")
if os.path.lexists(_link):
    os.remove(_link)
os.symlink(os.path.join(_ZONEDIR, "US/Central"), _link)
try:
    S.ZONE_TABLE = _TABLE
    S.ZONE_NAME = ("/no/such/timezone",)
    S.ZONE_LINK = _link
    check(S.timezone_name() == "US/Central",
          f"the pinned zone read back as {S.timezone_name()!r}")
    _conf = _wrote("weather-on.conf", "weather = on\n")
    _record = S.read(_conf)
    check(_record["weather"] == "on",
          "the weather was switched off for want of a location it could "
          "derive")
    check(S.coordinates(_record) is not None,
          "no coordinate was derived from the timezone")
    check(_record["weather_place"] == "Chicago",
          f"the derived place is {_record['weather_place']!r}")
finally:
    S.ZONE_TABLE, S.ZONE_NAME, S.ZONE_LINK = _saved

# And an explicit place still wins, because a derived one is a starting point.
_conf = _wrote("weather-place.conf",
               "weather = on\nweather_place = Ardsley, NY\n"
               "weather_latitude = 41.0126\nweather_longitude = -73.8437\n")
_record = S.read(_conf)  # typed, so nothing is derived and no zone is read
check(S.place(_record) == "Ardsley, NY",
      "a typed place was overwritten by the timezone")
check(abs(S.coordinates(_record)[0] - 41.0126) < 0.001,
      "a typed coordinate was overwritten by the timezone")

# Off stays off, and nothing is looked up on its behalf.
#
# Checking the flag alone is not enough: it would pass on a record that had
# quietly grown a coordinate on a machine whose owner said no. The state is
# the assertion, and the guarantee is that a switched off feature does not
# read a file, derive anything, or leave a trace that it thought about it.
_conf = _wrote("weather-off.conf", "weather = off\n")
_off = S.read(_conf)
check(_off["weather"] == "off",
      "deriving a location switched the weather on by itself")
check(not _off["weather_latitude"] and not _off["weather_longitude"],
      f"a coordinate was derived for a machine with the weather switched "
      f"off: {_off['weather_latitude']!r}, {_off['weather_longitude']!r}")
check(not _off["weather_place"],
      f"a place was derived with the weather switched off: "
      f"{_off['weather_place']!r}")


# The old guarantee, kept: with nothing typed and nothing derivable, the
# weather switches itself off rather than sitting on a screen forever saying
# it is checking. Forced by pointing the zone table at nothing.
_saved_table = S.ZONE_TABLE
_saved_name = S.ZONE_NAME
_saved_link = S.ZONE_LINK
try:
    S.ZONE_TABLE = "/no/such/zone.tab"
    S.ZONE_NAME = ("/no/such/timezone",)
    S.ZONE_LINK = "/no/such/localtime"
    check(record("weather = on\n")["weather"] == "off",
          "the weather stayed on with nowhere to ask about and nothing to "
          "derive from")
finally:
    S.ZONE_TABLE = _saved_table
    S.ZONE_NAME = _saved_name
    S.ZONE_LINK = _saved_link


# -- whether the clock can be believed --------------------------------------
#
# The screen stakes a great deal on the time: the greeting, the occasion,
# which photograph suits the hour, and what time it is where that photograph
# was taken. A dead coin cell makes all of it confidently wrong.
#
# Asking whether the clock is synchronised needs a daemon and answers no on
# plenty of correct machines. This asks whether the clock predates the files
# it is running from, which cannot happen and therefore has no false answers.
_recent = _wrote("recent", "x")
check(S.clock_is_wrong(_recent) is False,
      "a machine with a correct clock was told its date is wrong")
check(S.clock_is_wrong(_recent, now=0.0) is True,
      "a clock reading 1970 was believed")
check(S.clock_is_wrong(_recent, now=time.time() - 3600) is False,
      "a clock an hour slow was called wrong, which would fire on every "
      "machine that drifts")
check(S.clock_is_wrong(_recent, now=time.time() - S.CLOCK_SLACK * 3) is True,
      "a clock three days behind its own software was believed")
check(S.clock_is_wrong("/no/such/reference") is False,
      "an unreadable reference produced a warning rather than silence")

# -- the one switch for emergency alerts ------------------------------------
#
# It turns everything off: no request, no row on the panel, no banner, no
# sound. That is why the question is answered here rather than at each place
# something is drawn, and why the answer includes the weather switch: alerts
# ride on the weather request, and a machine that has not agreed to make that
# request has already answered this.

_here = "weather = on\nweather_latitude = 29.42\nweather_longitude = -98.49\n"

check(record("")["alerts"] == "on",
      "emergency alerts are not on by default")
check(S.alerts_on(record(_here)) is True,
      "a machine with the weather on and nothing said about alerts refuses "
      "to carry them")
for _word in S.WORDS_OFF:
    check(S.alerts_on(record(_here + f"alerts = {_word}\n")) is False,
          f"alerts = {_word} did not switch emergency alerts off")
for _word in S.WORDS_ON:
    check(S.alerts_on(record(_here + f"alerts = {_word}\n")) is True,
          f"alerts = {_word} did not switch emergency alerts on")
check(record(_here + "alerts = sometimes\n")["alerts"] == "on",
      "a value nobody can read was not clamped back to the default")
check(S.alerts_on(record("weather = off\n")) is False,
      "a machine with the weather off says it carries emergency alerts, and "
      "the request they would arrive on is never made")
check(S.alerts_on(record("weather = off\nalerts = on\n")) is False,
      "alerts = on outvoted the weather being off, which would put a network "
      "request on the login screen of a machine whose owner said no")

# -- asking the network where this machine is -------------------------------
#
# Location lookup is enabled by default but must respect a typed coordinate.

check(record("")["location"] == "on",
      "asking the network for a location is not on by default")
for _word in S.WORDS_OFF:
    check(S.location_on(record(_here + f"location = {_word}\n")) is False,
          f"location = {_word} did not switch the lookup off")
check(S.location_on(record(_here)) is False,
      "a record with a typed coordinate would still be overridden by a "
      "network lookup, which throws away what somebody told this machine")
check(record(_here)["location_from"] == "typed",
      f"a typed coordinate is recorded as "
      f"{record(_here)['location_from']!r} rather than typed")
check(S.location_on(record("weather = off\n")) is False,
      "the network would be asked where a machine is on a machine that is "
      "not making any requests at all")

# The case this feature is for: weather on, nothing typed, so the timezone
# filled the coordinate in and the network is allowed to do better.
_saved = (S.ZONE_TABLE, S.ZONE_NAME, S.ZONE_LINK)
try:
    S.ZONE_TABLE = _TABLE
    S.ZONE_NAME = ("/no/such/timezone",)
    S.ZONE_LINK = _link
    _derived = S.read(_wrote("weather-derived.conf", "weather = on\n"))
    check(_derived["location_from"] == "timezone",
          f"a derived coordinate is recorded as "
          f"{_derived['location_from']!r} rather than timezone")
    check(S.location_on(_derived) is True,
          "the network is not asked on the one record this whole feature is "
          "for: weather on, nothing typed, coordinate guessed")
    check(S.location_on(dict(_derived, location="off")) is False,
          "location = off did not stop the lookup on a derived record")

    # And it is not a setting, however much it looks like one in the file.
    _typed_in = S.read(_wrote("weather-lied.conf",
                              "weather = on\nlocation_from = typed\n"))
    check(_typed_in["location_from"] == "timezone",
          "location_from was taken from the file, so writing one word in a "
          "config file switches the lookup off with no setting to find")
finally:
    S.ZONE_TABLE, S.ZONE_NAME, S.ZONE_LINK = _saved

# -- what happens after the third wrong password ----------------------------
#
# Read the lockout policy from the configured PAM files.

_pam = _wrote("system-auth",
              "auth       required   pam_faillock.so      preauth\n"
              "auth       [default=die] pam_faillock.so   authfail\n")
_lockconf = _wrote("faillock.conf", "# a comment\ndeny = 5\nunlock_time = 1200\n")

check(S.lockout_policy((_pam,), _lockconf) == (5, 1200),
      "the configured policy was not read")
check(S.lockout_policy((_pam,), "/no/such/faillock.conf")
      == (S.FAILLOCK_DENY, S.FAILLOCK_UNLOCK),
      "with no config file the module's own defaults were not used")

# Arguments on the PAM line beat the config file, which is how PAM resolves
# them. Getting this backwards means describing a policy the machine is not
# running, which is the one outcome worse than saying nothing.
_args = _wrote("system-auth-args",
               "auth required pam_faillock.so preauth deny=2 unlock_time=60\n")
check(S.lockout_policy((_args,), _lockconf) == (2, 60),
      "the config file outvoted the arguments on the pam_faillock line")

_none = _wrote("system-auth-none", "auth required pam_unix.so\n")
check(S.lockout_policy((_none,), _lockconf) is None,
      "a machine with no lockout configured was told it has one")
_off = _wrote("system-auth-off",
              "# auth required pam_faillock.so preauth\n")
check(S.lockout_policy((_off,), _lockconf) is None,
      "a commented out pam_faillock line counted as configured")
check(S.lockout_policy(("/no/such/pam",), _lockconf) is None,
      "an unreadable PAM stack produced a policy")

_zero = _wrote("faillock-zero.conf", "deny = 0\nunlock_time = -5\n")
check(S.lockout_policy((_pam,), _zero) == (S.FAILLOCK_DENY, S.FAILLOCK_UNLOCK),
      "nonsense numbers were used as a policy rather than falling back")
_junk = _wrote("faillock-junk.conf", "deny = soon\n")
check(S.lockout_policy((_pam,), _junk)[0] == S.FAILLOCK_DENY,
      "a deny that is not a number was not fallen back from")

check(C.locked_words(600) != C.locked_words(60),
      "the same sentence is used for ten minutes and for one")
check("1 minutes" not in C.locked_words(60),
      f"a one minute lock reads as {C.locked_words(60)!r}")
check("11" in C.locked_words(601),
      f"a lock of ten minutes and one second rounds down, so the screen "
      f"promises a time it does not keep: {C.locked_words(601)!r}")

# -- the battery, and how long it has ---------------------------------------
#
# Battery time may use either energy/power or charge/current units.

from aurade_greeter import status as ST  # noqa: E402


def _cell(name: str, **files) -> str:
    where = os.path.join(_dir, "power", name)
    os.makedirs(where, exist_ok=True)
    for key, value in files.items():
        with open(os.path.join(where, key), "w", encoding="utf-8") as handle:
            handle.write(str(value))
    return where


_draining = _cell("draining", status="Discharging", energy_now=30000000,
                  energy_full=60000000, power_now=15000000)
equal(ST._battery_minutes(_draining, "Discharging"), 120,
      "two hours of charge at that rate did not read as two hours")

_amps = _cell("amps", status="Discharging", charge_now=1830000,
              charge_full=3660000, current_now=915000)
equal(ST._battery_minutes(_amps, "Discharging"), 120,
      "the amp hour vocabulary was not read, which is the one the machine "
      "this ships to actually uses")

# Deliberately not half full. It was, and half full is the one charge where
# the room left and the charge held are the same number, so the fixture could
# not tell the two apart and the assertion passed either way.
_filling = _cell("filling", status="Charging", charge_now=915000,
                 charge_full=3660000, current_now=915000)
equal(ST._battery_minutes(_filling, "Charging"), 180,
      "charging counts the charge held rather than the room left")

# Three guards, three fixtures. They were one fixture, and any one of the
# three could be deleted with the test still green because the other two
# happened to cover the same reading. A guard that is only ever exercised
# alongside another guard is a guard nothing is holding.
#
# One: neither charging nor discharging. The rate here is perfectly healthy,
# so only the state check can be what refuses it.
_resting = _cell("resting", status="Full", charge_now=1830000,
                 charge_full=3660000, current_now=915000)
check(ST._battery_minutes(_resting, "Full") is None,
      "a battery that is neither filling nor emptying was given a time, and "
      "the rate it reports at rest is meaningless")

# Two: a rate too small to divide by, on a charge small enough that the
# answer would still look plausible. This is the trickle a full battery
# reports, and the number it produces is the confident nonsense.
_trickle = _cell("trickle", status="Discharging", charge_now=20000,
                 charge_full=3660000, current_now=1000)
check(ST._battery_minutes(_trickle, "Discharging") is None,
      "a current too small to divide by produced a time anyway")

# Three: a rate large enough to trust, giving an answer no battery has.
_forever = _cell("forever", status="Discharging", charge_now=100,
                 charge_full=100, current_now=2)
check(ST._battery_minutes(_forever, "Discharging") is None,
      "fifty hours of battery was printed as fact")

_absent = _cell("absent", status="Discharging")
check(ST._battery_minutes(_absent, "Discharging") is None,
      "a battery with no rate files produced a time")

# The sentence.
equal(C.battery_words({"state": "Full", "minutes": None}), C.BATTERY_CHARGED,
      "a full battery is not described as charged")
check("{time}" not in C.battery_words({"state": "Charging", "minutes": 45}),
      "the charging sentence was left with its placeholder in it")
check(C.battery_words({"state": "Charging", "minutes": None})
      == C.BATTERY_CHARGING,
      "charging with no estimate invented one")
check(C.battery_words({"state": "Discharging", "minutes": None})
      == C.BATTERY_ON,
      "discharging with no estimate invented one")
equal(C.battery_words({"state": "", "mains": True}), C.BATTERY_PLUGGED,
      "a machine on mains with no battery state was not described")

# Durations, said the way somebody says them.
equal(C.duration_words(45), C.DURATION_MINUTES.format(minutes=45),
      "three quarters of an hour was not said in minutes")
equal(C.duration_words(60), C.DURATION_HOUR, "an hour was not said as one")
equal(C.duration_words(120), C.DURATION_HOURS.format(hours=2),
      "two hours was not said as two hours")
check("37" not in C.duration_words(157),
      f"a battery estimate claims a precision it does not have: "
      f"{C.duration_words(157)!r}")
check(C.duration_words(1) == C.DURATION_MINUTE,
      "one minute reads as a plural")
check(C.duration_words(0) == C.DURATION_MINUTE,
      "no minutes at all produced something other than the smallest thing "
      "this can say")


# -- the brightness ---------------------------------------------------------

from aurade_greeter import backlight as BL  # noqa: E402

_bl = os.path.join(_dir, "backlight")
os.makedirs(os.path.join(_bl, "panel0"), exist_ok=True)
with open(os.path.join(_bl, "panel0", "brightness"), "w") as _h:
    _h.write("128")
with open(os.path.join(_bl, "panel0", "max_brightness"), "w") as _h:
    _h.write("255")

equal(BL.device(_bl), "panel0", "the backlight was not found")
check(abs((BL.level(_bl) or 0) - 128 / 255) < 1e-6,
      f"the level read back as {BL.level(_bl)}")
equal(BL.steps(_bl), 255, "the step count was not read")
equal(BL.device(os.path.join(_dir, "no-backlight-here")), "",
      "a missing directory produced a backlight")

# A directory that exists and holds something that is not a backlight. The
# check above only proved `os.listdir` raising, so the test that a device is
# actually a device could be deleted with everything still green.
os.makedirs(os.path.join(_dir, "not-backlights", "leftovers"), exist_ok=True)
equal(BL.device(os.path.join(_dir, "not-backlights")), "",
      "a directory with no max_brightness in it was driven as a backlight")

# Never all the way off. A black screen on a login screen, set by somebody
# who then cannot see the slider they just moved, has no way back.
check(BL.raw(0.0, 255) > 0, "the floor let the screen go entirely black")
check(BL.raw(0.0, 255) <= 255 * 0.06,
      f"the floor is not near the bottom: {BL.raw(0.0, 255)}")
equal(BL.raw(1.0, 255), 255, "full brightness did not reach the top step")
equal(BL.raw(0.5, 100), 50, "half was not half")
# On a scale that does not divide evenly, which is where rounding and
# truncation part company. Every earlier case landed on a whole number and
# proved nothing about either.
equal(BL.raw(0.5, 255), 128,
      "the level is truncated rather than rounded, so a slider dragged to a "
      "number arrives one step below it")
equal(BL.raw(0.9, 255), 230, "nine tenths did not round to the nearest step")
equal(BL.raw(9.0, 255), 255, "a value above one went past the top step")

if FAILURES:
    for failure in FAILURES:
        print(f"greeter-settings: {failure}", file=sys.stderr)
    sys.exit(1)
print("greeter settings test: PASS")
