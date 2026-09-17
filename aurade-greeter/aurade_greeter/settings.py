"""How this login screen behaves, as somebody chose to have it behave.

Same shape and the same rules as `preferences.py`: read key and value, never
sourced, unknown keys ignored, bad values clamped rather than refused. This
file sits in front of the login prompt on a machine somebody may be trying to
rescue, so a stray line in it has to be survivable and a typo has to fall back
to the ordinary appearance rather than to a screen that will not draw.

The defaults are what the login screen did before any of this existed, with
one exception that is the whole reason this file needed a design decision
rather than a table.

**The weather is off.** Not off by default in the sense of a switch somebody
will find and flip: off because turning it on means this machine makes a
network request from its login screen, before anybody has authenticated, and
that is not a decision to make on a user's behalf. Everything else here
changes how the screen looks. This one changes what the machine does when
nobody is watching it.
"""

from __future__ import annotations

import os

from .copy import _

#: Where the answers live. Not under /etc/aurade-install, because that record
#: belongs to the installer and describes what somebody chose while installing.
#: This one describes a running machine and outlives it.
RECORD = os.environ.get("AURADE_GREETER_CONF", "/etc/aurade/greeter.conf")

DEFAULTS: dict[str, str] = {
    "photos": "rotate",
    "photo_interval": "120",
    "photo_card": "on",
    "weather": "off",
    "weather_place": "",
    "weather_latitude": "",
    "weather_longitude": "",
    "weather_units": "c",
    "weather_provider": "auto",
    "alerts": "on",
    "location": "on",
    #: Not a setting. Written by `_clamp` on every read and overwritten if
    #: somebody types it, because it records where the coordinate in this
    #: record came from and only this file knows that. Without it the worker
    #: cannot tell a latitude somebody typed from one derived a moment ago,
    #: and a network lookup would quietly replace a typed one.
    "location_from": "",
    "greeting": "hour",
}

#: Emergency alerts, and the one switch that turns all of them off.
#:
#: On by default, because a warning nobody sees is the only failure of this
#: feature that costs anything, and because it cannot do a thing on its own:
#: the weather is off until somebody turns it on, and this rides on that
#: request.
#:
#: Off means off the whole way down. No request is made, so there is no answer
#: to hide, no row on the panel, no banner and no sound. A setting that only
#: silences the noise while the machine keeps asking is a setting that lies
#: about what it did.
ALERTS_DEFAULT = True

#: Asking the network where this machine is, rather than guessing from the
#: timezone.
#:
#: On, and that is a change from how the weather itself is defaulted, because
#: it is a different question. The weather switch decides whether this screen
#: talks to anybody at all, and it is off. This one only decides which
#: coordinate the request it was already going to make carries, and a wrong
#: one is not more private, it is just wrong: `America/Chicago` gives Chicago
#: to a machine sitting in San Antonio.
#:
#: Off means the timezone stands. A typed coordinate beats both and no lookup
#: is made at all, which is the setting for somebody who wants the weather and
#: does not want this.
LOCATION_DEFAULT = True

#: Who to ask. `auto` sends United States coordinates to the National Weather
#: Service and everything else to Open-Meteo, which is the right answer for
#: almost everybody; the other two exist so that somebody debugging a wrong
#: forecast can pin the source rather than guess at it.
PROVIDERS = ("auto", "nws", "openmeteo")

#: A rotation faster than this is a slideshow, and a slideshow on a login
#: screen is somebody's migraine. Slower than a day is not a rotation.
INTERVAL_MIN = 20
INTERVAL_MAX = 86400

WORDS_ON = ("on", "yes", "true", "1")
WORDS_OFF = ("off", "no", "false", "0")


def _clean(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value.strip()


# -- whether the clock can be believed -------------------------------------

#: How far behind its own software a clock has to be before saying so. A few
#: minutes is a slow machine; a day is a clock nobody has set.
CLOCK_SLACK = 86400.0


def clock_is_wrong(reference: str = "", now: float | None = None) -> bool:
    """Whether this machine's clock reads earlier than its own software.

    A login screen shows the time in ninety point type and stakes everything
    on it: the greeting, the occasion, which photograph suits the hour, and
    what time it is where the picture was taken. A dead coin cell makes all of
    that confidently wrong, and the screen has no idea.

    Asking whether the clock is *synchronised* needs a daemon, a subprocess or
    a bus, and answers "no" on plenty of machines that are perfectly correct.
    This asks a smaller question with no false answers in it: is the clock
    earlier than the files it is running from. A file cannot be written in the
    future, so a machine whose clock predates its own installation is wrong
    beyond argument, and that is the case worth reporting.

    It does not catch a clock that is merely late by an hour, and it is not
    supposed to. It catches the one that says 1970.
    """
    import time as _time  # noqa: PLC0415

    try:
        built = os.path.getmtime(reference or os.path.abspath(__file__))
    except OSError:
        return False
    return (now if now is not None else _time.time()) < built - CLOCK_SLACK


# -- what happens after the third wrong password ---------------------------

#: Where `pam_faillock` is switched on, and where it is configured.
#:
#: Read rather than assumed. A greeter that says "this account is locked for
#: ten minutes" on a machine with no lockout at all has invented a policy, and
#: a greeter that says nothing on a machine that does lock is the one somebody
#: stares at wondering what is broken.
PAM_FILES = ("/etc/pam.d/system-auth", "/etc/pam.d/system-login",
             "/etc/pam.d/greetd")
FAILLOCK_CONF = "/etc/security/faillock.conf"

#: `pam_faillock`'s own defaults, for the settings its config file leaves out.
#: They are the module's, not ours, and changing them here would make this
#: screen describe a policy the machine is not running.
FAILLOCK_DENY = 3
FAILLOCK_UNLOCK = 600


def _faillock_arguments(paths: tuple) -> dict[str, str] | None:
    """The module's own arguments, or nothing if it is not in the stack.

    Arguments on the `pam_faillock` line beat the config file, which is how
    PAM resolves them, so they are collected here and applied last.
    """
    found = None
    for path in paths:
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                lines = handle.readlines()
        except OSError:
            continue
        for line in lines:
            if line.lstrip().startswith("#") or "pam_faillock.so" not in line:
                continue
            found = found if found is not None else {}
            for word in line.split():
                if "=" in word:
                    key, _, value = word.partition("=")
                    found[key] = value
    return found


def lockout_policy(paths: tuple = (), conf: str = "") -> tuple[int, int] | None:
    """How many wrong passwords lock this account, and for how long.

    Nothing at all where `pam_faillock` is not in the stack, which is the
    answer on a machine that does not lock, and the only honest one: the
    alternative is a login screen explaining a rule it made up.
    """
    arguments = _faillock_arguments(paths or PAM_FILES)
    if arguments is None:
        return None
    settings: dict[str, str] = {}
    try:
        with open(conf or FAILLOCK_CONF, encoding="utf-8",
                  errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                key, _, value = line.partition("=")
                settings[key.strip()] = value.strip()
    except OSError:
        pass
    settings.update(arguments)

    def number(key: str, fallback: int) -> int:
        try:
            found = int(settings[key])
        except (KeyError, ValueError):
            return fallback
        return found if found > 0 else fallback

    return number("deny", FAILLOCK_DENY), number("unlock_time", FAILLOCK_UNLOCK)


# -- where this machine is, approximately, for nothing ---------------------

#: The table tzdata ships, which nobody seems to know is there. It carries a
#: coordinate for every one of the three hundred or so zones, in ISO 6709.
ZONE_TABLE = "/usr/share/zoneinfo/zone1970.tab"

#: And where the chosen zone is recorded, most reliable first.
ZONE_NAME = ("/etc/timezone",)
ZONE_LINK = "/etc/localtime"


def timezone_name(paths: tuple = (), link: str = "") -> str:
    """Which zone this machine is set to.

    The defaults are read from the module rather than bound into the
    signature. A constant used as a default argument is fixed at import and
    reassigning it afterwards does nothing at all, which makes it look
    configurable while quietly not being, and the test that tried to point
    this at an empty machine is how that turned up.
    """
    paths = paths or ZONE_NAME
    link = link or ZONE_LINK
    for path in paths:
        try:
            with open(path, encoding="utf-8") as handle:
                found = handle.read().strip()
        except OSError:
            continue
        if found:
            return found
    try:
        target = os.path.realpath(link)
    except OSError:
        return ""
    marker = "/zoneinfo/"
    if marker in target:
        return target.split(marker, 1)[1]
    return ""


def _degrees(text: str) -> float | None:
    """One ISO 6709 coordinate, as degrees.

    The format is a sign, then two or three digits of degrees, then two of
    minutes, then optionally two of seconds, with no separators at all. So
    `+415100` is forty one degrees fifty one minutes north and `-0873900` is
    eighty seven degrees thirty nine minutes west.
    """
    if len(text) < 5 or text[0] not in "+-":
        return None
    sign = -1.0 if text[0] == "-" else 1.0
    body = text[1:]
    wide = len(body) in (5, 7)
    head = 3 if wide else 2
    try:
        degrees = float(body[:head])
        minutes = float(body[head:head + 2])
        seconds = float(body[head + 2:head + 4]) if len(body) >= head + 4 else 0.0
    except ValueError:
        return None
    return sign * (degrees + minutes / 60.0 + seconds / 3600.0)


def _same_zone(directory: str, one: str, two: str) -> bool:
    """Whether two zone names name the same compiled zone.

    `US/Central` is a backward compatibility name for `America/Chicago`, and
    `zone1970.tab` lists only the canonical names, so a machine set to the old
    one is not in the table at all. tzdata ships the old names as links, so on
    almost every machine these are one inode wearing two names, and where the
    packaging copied instead of linking the bytes are still the same bytes,
    because it is the same compiled zone either way.

    Compared by identity first because it costs one stat and answers on every
    normal machine.
    """
    for name in (one, two):
        if name.startswith("/") or ".." in name.split("/"):
            return False
    first = os.path.join(directory, one)
    second = os.path.join(directory, two)
    try:
        here, there = os.stat(first), os.stat(second)
    except OSError:
        return False
    if (here.st_dev, here.st_ino) == (there.st_dev, there.st_ino):
        return True
    if here.st_size != there.st_size or not here.st_size:
        return False
    try:
        with open(first, "rb") as one_handle, open(second, "rb") as two_handle:
            return one_handle.read() == two_handle.read()
    except OSError:
        return False


def place_from_timezone(table: str = "",
                        zone: str = "") -> tuple[float, float, str] | None:
    """A coordinate and a name from the timezone, with nothing asked of anybody.

    Turning the weather on means opening a file and typing a latitude, which
    is most of the reason it stays off. The zone this machine is already set
    to names a real place with a published coordinate, so the configuration
    can be one line rather than three.

    It does not move the decision. The weather is still off until somebody
    turns it on, and the reason for that is written where the default lives:
    turning it on means this machine makes a network request from its login
    screen before anybody has authenticated. This only removes the busywork
    sitting behind that decision.

    **The coordinate is the zone's city, not yours.** `America/Chicago` gives
    Chicago whether the machine is in Chicago or in San Antonio, and those are
    twelve hundred kilometres and a different climate apart. That is a feature
    rather than an apology: the panel prints the place it is describing, so a
    wrong default is visible in one glance and invites the correction, where
    an empty setting invites giving up.
    """
    wanted = zone or timezone_name()
    if not wanted:
        return None
    where = table or ZONE_TABLE
    try:
        with open(where, encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except OSError:
        return None
    rows = []
    for line in lines:
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 3:
            rows.append((parts[2].strip(), parts[1].strip()))

    named = next((raw for zone_name, raw in rows if zone_name == wanted), None)
    canonical = wanted
    if named is None:
        # Resolve older aliases such as `US/Central`, `Asia/Calcutta`, and
        # `Europe/Kiev` against the canonical names in the zone table.
        directory = os.path.dirname(where)
        for zone_name, raw in rows:
            if _same_zone(directory, wanted, zone_name):
                named, canonical = raw, zone_name
                break
    if named is None:
        return None
    # The two coordinates run together with only the second sign to
    # separate them, so the split is on that sign rather than on a space.
    cut = max(named.rfind("+"), named.rfind("-"))
    if cut <= 0:
        return None
    latitude = _degrees(named[:cut])
    longitude = _degrees(named[cut:])
    if latitude is None or longitude is None:
        return None
    return latitude, longitude, canonical.rsplit("/", 1)[-1].replace("_", " ")
    return None


# -- the keyboard, which is not this machine's choice but is its state --
#
# Here rather than in `status.py`, which is carried from the installer
# byte for byte and is not the greeter's to change. This file already
# reads what a machine has been configured as, which is the same kind of
# question.

#: Where a system records the keyboard it was set up with, most canonical
#: first. systemd writes the first one, Debian the second, and a machine that
#: has only ever been configured from the console has the third.
LAYOUT_FILES = (
    "/etc/X11/xorg.conf.d/00-keyboard.conf",
    "/etc/default/keyboard",
    "/etc/vconsole.conf",
)

#: The layouts worth spelling out. Everything else is shown as its code in
#: capitals, which is still more use than nothing: somebody who set their
#: machine to `cz` recognises `CZ`.
LAYOUT_WORDS = {
    "us": _("US"), "gb": _("UK"), "uk": _("UK"), "de": _("German"), "fr": _("French"),
    "es": _("Spanish"), "it": _("Italian"), "pt": _("Portuguese"), "br": _("Brazilian"),
    "ru": _("Russian"), "ua": _("Ukrainian"), "pl": _("Polish"), "cz": _("Czech"),
    "se": _("Swedish"), "no": _("Norwegian"), "dk": _("Danish"), "fi": _("Finnish"),
    "nl": _("Dutch"), "be": _("Belgian"), "ch": _("Swiss"), "at": _("Austrian"),
    "tr": _("Turkish"), "gr": _("Greek"), "il": _("Hebrew"), "ara": _("Arabic"),
    "jp": _("Japanese"), "kr": _("Korean"), "cn": _("Chinese"), "in": _("Indian"),
    "ca": _("Canadian"), "latam": _("Latin American"), "dvorak": _("Dvorak"),
}


def keyboard_layout(paths: tuple = LAYOUT_FILES) -> str:
    """What the machine believes is under somebody's fingers.

    A login screen already warns about Caps Lock, which is the second most
    common reason a password that is definitely right is definitely refused.
    The first is a keyboard laid out differently from the one the machine
    thinks it has, and until now nothing on this screen said a word about it.
    Somebody on an AZERTY keyboard against a QWERTY machine types a password
    they cannot see, into a field that keeps saying no, with no way at all to
    find out why.

    Read rather than asked of the compositor, because this runs before anybody
    has logged in and the system layout is the layout. The first file that
    names one wins, so a machine configured twice is reported the way the more
    canonical of the two says.
    """
    for path in paths:
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except OSError:
            continue
        for key in ("XkbLayout", "XKBLAYOUT", "KEYMAP"):
            found = _setting(text, key)
            if found:
                return found.split(",")[0].strip()
    return ""


def _setting(text: str, key: str) -> str:
    """The value of `key`, from either a shell record or an xorg snippet."""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#") or key not in line:
            continue
        # `XKBLAYOUT="us"` and `Option "XkbLayout" "us"` in one reader,
        # because the three files this looks at use both spellings.
        if "=" in line and line.split("=", 1)[0].strip().strip('"') == key:
            return line.split("=", 1)[1].strip().strip('"').strip("'")
        parts = [p.strip('"') for p in line.split() if p.strip('"')]
        if key in parts:
            index = parts.index(key)
            if index + 1 < len(parts):
                return parts[index + 1]
    return ""


def layout_words(code: str) -> str:
    """The layout as somebody would say it, or its code in capitals."""
    if not code:
        return ""
    return LAYOUT_WORDS.get(code.lower(), code.upper())


def read(path: str = "") -> dict[str, str]:
    """The record, with every value already made safe to act on."""
    record = dict(DEFAULTS)
    where = path or RECORD
    try:
        with open(where, encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except OSError:
        return record
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().lower()
        # Unknown keys are ignored rather than rejected. A newer greeter's
        # file being read by an older one has to work, or an upgrade that
        # rolls back leaves somebody at a login screen that will not start.
        if key in record:
            record[key] = _clean(value)
    return _clamp(record)


def _clamp(record: dict[str, str]) -> dict[str, str]:
    if record["photos"] not in ("rotate", "fixed"):
        record["photos"] = DEFAULTS["photos"]
    record["photo_interval"] = str(interval(record["photo_interval"]))
    record["photo_card"] = "on" if truthy(record["photo_card"], True) else "off"
    record["weather"] = "on" if truthy(record["weather"], False) else "off"
    if record["weather_units"].lower() not in ("c", "f"):
        record["weather_units"] = DEFAULTS["weather_units"]
    record["weather_units"] = record["weather_units"].lower()
    if record["greeting"] not in ("hour", "plain"):
        record["greeting"] = DEFAULTS["greeting"]
    if record["weather_provider"].lower() not in PROVIDERS:
        record["weather_provider"] = DEFAULTS["weather_provider"]
    record["weather_provider"] = record["weather_provider"].lower()
    record["alerts"] = "on" if truthy(record["alerts"],
                                      ALERTS_DEFAULT) else "off"
    record["location"] = "on" if truthy(record["location"],
                                        LOCATION_DEFAULT) else "off"
    # Weather with nowhere to ask about is weather that will never arrive, so
    # it is switched off here rather than at the point of asking: one place to
    # look when somebody says they turned it on and nothing happened.
    #
    # Either a coordinate or a name will do. Requiring a latitude would mean
    # telling somebody to go and look up their own, which is asking a person
    # to do a computer's job; a name is resolved to a coordinate once and the
    # answer is kept.
    # Only where nothing at all was typed. A latitude somebody got wrong is a
    # mistake they need to see, and quietly replacing it with the timezone's
    # city would hide it behind weather for a place they have never been.
    asked = any(record.get(key, "").strip() for key in
                ("weather_place", "weather_latitude", "weather_longitude"))
    # Recorded before anything is derived, and recorded either way, so the
    # answer is never left over from a previous read of a different file.
    record["location_from"] = "typed" if asked else ""
    if not asked and not _locatable(record):
        # Nothing typed, so the timezone answers. `America/Chicago` names a
        # real place with a published coordinate, and a login screen that
        # already knows what time it is here should not have to ask where
        # here is before it can say whether it is raining.
        #
        # This does not turn anything on. The weather is still off until
        # somebody says otherwise, for the reason at the top of this file.
        # It only removes the busywork sitting behind that decision, which is
        # most of why the setting stays untouched.
        derived = place_from_timezone()
        if derived is not None:
            latitude, longitude, name = derived
            record["weather_latitude"] = f"{latitude:.4f}"
            record["weather_longitude"] = f"{longitude:.4f}"
            record["weather_place"] = record["weather_place"] or name
            record["location_from"] = "timezone"
    if not _locatable(record):
        record["weather"] = "off"
    return record


def _locatable(record: dict[str, str]) -> bool:
    """Whether this record says anywhere the weather could be asked about."""
    if record["weather"] != "on":
        return True
    if record["weather_place"].strip():
        return True
    return _coordinates_ok(record)


def _coordinates_ok(record: dict[str, str]) -> bool:
    """A pair of numbers that are actually on the globe."""
    try:
        lat = float(record["weather_latitude"])
        lon = float(record["weather_longitude"])
    except (KeyError, ValueError):
        return False
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def truthy(value: str, fallback: bool) -> bool:
    word = value.strip().lower()
    if word in WORDS_ON:
        return True
    if word in WORDS_OFF:
        return False
    return fallback


def interval(value: str) -> int:
    try:
        seconds = int(float(value))
    except ValueError:
        return int(DEFAULTS["photo_interval"])
    return max(INTERVAL_MIN, min(INTERVAL_MAX, seconds))


def rotates(record: dict[str, str]) -> bool:
    return record.get("photos") == "rotate"


def weather_on(record: dict[str, str]) -> bool:
    return record.get("weather") == "on"


def alerts_on(record: dict[str, str]) -> bool:
    """Whether this machine carries emergency alerts at all.

    Reads the weather switch as well, and not as politeness: alerts arrive on
    the back of the weather request and a machine with the weather off has
    already said no to asking a stranger where it is. One question, answered
    in one place, so that the caller cannot get half of it right.
    """
    return weather_on(record) and truthy(record.get("alerts", ""),
                                         ALERTS_DEFAULT)


def location_on(record: dict[str, str]) -> bool:
    """Whether to ask the network where this machine is.

    Three conditions, and the last is the one worth naming: a coordinate
    somebody typed is never replaced. They said where they are, and a service
    that thinks otherwise is wrong about a fact the person in the room knows
    better.
    """
    return (weather_on(record)
            and truthy(record.get("location", ""), LOCATION_DEFAULT)
            and record.get("location_from") != "typed")


def coordinates(record: dict[str, str]) -> tuple[float, float] | None:
    """Where to ask about, or nothing at all."""
    if not weather_on(record) or not _coordinates_ok(record):
        return None
    return (float(record["weather_latitude"]),
            float(record["weather_longitude"]))


def place(record: dict[str, str]) -> str:
    """The typed place name, for when there is no coordinate to use."""
    return record.get("weather_place", "").strip() if weather_on(record) else ""


def provider(record: dict[str, str]) -> str:
    return record.get("weather_provider", DEFAULTS["weather_provider"])


def units(record: dict[str, str]) -> str:
    return record.get("weather_units", DEFAULTS["weather_units"])
