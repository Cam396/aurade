"""Translated strings used by the greeter."""
from __future__ import annotations

import gettext as _gettext
import os as _os

#: Where installed catalogues live. Overridable so the suite can point at a
#: build directory without installing anything.
LOCALEDIR = _os.environ.get("AURADE_GREETER_LOCALEDIR", "/usr/share/locale")

#: The domain, matching the package name.
DOMAIN = "aurade-greeter"

def _translator():
    """Load the locale catalog, falling back to the English strings."""
    try:
        for path in _gettext.find(DOMAIN, LOCALEDIR, all=True) or []:
            with open(path, "rb") as handle:
                return _gettext.GNUTranslations(handle).gettext
    except Exception:  # noqa: BLE001 - a login screen, not a build tool
        pass
    return lambda text: text


_ = _translator()

#: The screen itself.
TITLE = _("Welcome back")
TITLE_FIRST = _("Welcome")
CHOOSE = _("Choose an account")

#: The password field and its button.
PASSWORD = _("Password")
#: The field, once it knows whose it is.
PASSWORD_FOR = _("{name}, your password")
SIGN_IN = _("Sign in")
SIGNING_IN = _("Signing in")

# Between choosing an account and the login service asking for anything there
# is a real pause, and an empty password box during it reads as a screen that
# is ignoring the person in front of it.
CHECKING = _("One moment.")

# The handoff. Between the greeter letting go and the desktop drawing its first
# frame the screen has nothing on it, and on this hardware that is eight to
# twenty two seconds. Somebody who is told what is happening waits; somebody
# looking at black assumes it broke.
HANDOFF_TITLE = _("Welcome back, {first}.")
HANDOFF_TITLE_PLAIN = _("Welcome back.")
HANDOFF_NOTE = _("Setting up your desktop.")
BACK = _("Choose a different account")

# -- the quick settings, and what the machine is doing ---------------------

PANEL_BRIGHTNESS = _("Brightness")
PANEL_BATTERY = _("Battery")
#: Beside the sentence, not inside it.
BATTERY_PERCENT = _("{percent}%")

#: What the battery is doing, in the order somebody would want to know it.
#: The percentage is beside these rather than inside them, because it is a
#: number and these are sentences.
BATTERY_CHARGING_IN = _("Charging, full in {time}")
BATTERY_CHARGING = _("Charging")
BATTERY_LEFT = _("About {time} left")
BATTERY_CHARGED = _("Charged")
BATTERY_PLUGGED = _("Plugged in")
BATTERY_ON = _("On battery")

#: Durations, said the way somebody would say them rather than in minutes.
#: Nobody says a hundred and sixty minutes.
DURATION_HOUR = _("an hour")
DURATION_HOURS = _("{hours} hours")
DURATION_HOUR_AND = _("an hour and {minutes} minutes")
DURATION_HOURS_AND = _("{hours} hours {minutes} minutes")
DURATION_MINUTE = _("a minute")
DURATION_MINUTES = _("{minutes} minutes")


def duration_words(minutes: int) -> str:
    """A count of minutes as a person would say it.

    Rounded to five minutes above an hour, because a battery estimate is a
    rate measured over the last few seconds and printing "2 hours 37 minutes"
    claims a precision the number does not have.
    """
    minutes = max(0, int(minutes))
    if minutes < 60:
        if minutes <= 1:
            return DURATION_MINUTE
        return DURATION_MINUTES.format(minutes=minutes)
    hours, rest = divmod(minutes, 60)
    rest = int(round(rest / 5.0)) * 5
    if rest >= 60:
        hours, rest = hours + 1, 0
    if rest == 0:
        return DURATION_HOUR if hours == 1 else DURATION_HOURS.format(
            hours=hours)
    if hours == 1:
        return DURATION_HOUR_AND.format(minutes=rest)
    return DURATION_HOURS_AND.format(hours=hours, minutes=rest)


def battery_words(reading: dict) -> str:
    """One sentence about the battery, from what the kernel would say.

    The state comes first and the time second, because somebody glancing at a
    lock screen wants to know whether it is going up or down before they want
    to know for how long, and the time is often not available at all.
    """
    state = str(reading.get("state") or "")
    minutes = reading.get("minutes")
    if state == "Full":
        return BATTERY_CHARGED
    if state == "Charging":
        if isinstance(minutes, int):
            return BATTERY_CHARGING_IN.format(time=duration_words(minutes))
        return BATTERY_CHARGING
    if state == "Discharging":
        if isinstance(minutes, int):
            return BATTERY_LEFT.format(time=duration_words(minutes))
        return BATTERY_ON
    return BATTERY_PLUGGED if reading.get("mains") else BATTERY_ON


#: The line under the clock, when the sky is doing something.
#:
#: Two shapes, because a spell the forecast does not see the end of has no
#: honest "until" and the edge of the data is not a time it stops.
SHADE_WEATHER = _("{words} until {time}")
SHADE_WEATHER_ON = _("{words}")

#: What a field says about itself before anything has gone wrong.
PASSWORD_HELP = _("Nothing you type here is stored by this screen.")
CAPS_LOCK = _("Caps Lock is on.")
#: Shown only after a password has been refused, and only then, because
#: before that it is a fact nobody needs and after it, it is the answer.
KEYBOARD_LAYOUT = _("This keyboard is set to {layout}.")

#: Failures. Each one says what happened and what to do about it, and neither
#: of them suggests the person made a mistake.
WRONG = _("That password did not work. Try it again, or choose another account.")
NO_ACCOUNTS = (
    _("This computer has no accounts yet. Start it from the installation media "
    "to set one up."))
SERVICE_GONE = (
    _("The login service is not answering. Restarting this computer will bring "
    "it back."))
SESSION_GONE = (
    _("That session could not be started. Choose another one, or restart this "
    "computer."))
OUTSIDE_GREETD = (
    _("This greeter was started on its own, so there is nothing to sign in to."))

#: The other user row, for accounts the list cannot show.
OTHER = _("Someone else")
OTHER_HELP = _("Type the username for an account that is not listed.")
USERNAME = _("Username")

#: The session picker, which most machines never show.
SESSION = _("Session")
SESSION_HELP = _("The desktop this account signs in to.")

#: The status area, bottom right, where a ChromeOS machine keeps it.
STATUS_AREA = _("System")
STATUS_AREA_HELP = _("The network, the battery, and how to restart this computer.")

#: What the pill says when it is read out rather than looked at. Three drawn
#: marks and a number are four facts to somebody looking and none at all to
#: somebody listening, so these are the same four in the order a person would
#: say them.
STATUS_NETWORK_ON = _("Connected to {name}.")
STATUS_NETWORK_UP = _("Connected.")
STATUS_NETWORK_DOWN = _("Connected to a network with no way out.")
STATUS_NO_NETWORK = _("Not connected.")
STATUS_BATTERY = _("Battery {percent} percent.")
STATUS_BATTERY_CHARGING = _("Battery {percent} percent, charging.")

#: The panel, which opens as a set of tiles and expands into one of them.
PANEL_NETWORK_POD = _("Network")
PANEL_ACCESS_POD = _("Accessibility")
PANEL_BACK = _("Back")
PANEL_ACCESS_STATE_ON = _("On")
PANEL_ACCESS_STATE_OFF = _("Off")
PANEL_NETWORK_OFF = _("Off")

DESCRIBE_NETWORK_POD = _("Opens the list of networks in range.")
DESCRIBE_ACCESS_POD = (_("The accessibility choices made during setup, still in "
                       "force on this computer."))

#: Named the way somebody would say them out loud, not the way the settings
#: file spells them.
ACCESS_CONTRAST = _("High contrast")
ACCESS_TEXT = _("Larger text")
ACCESS_MOTION = _("Reduced motion")

#: The network panel. The only thing on this screen somebody may have to
#: change before they can get in at all.
NETWORK = _("Network")
NETWORK_LOOKING = _("Looking for networks.")
NETWORK_NONE = _("No networks in range.")
NETWORK_NO_RADIO = _("This computer has no Wi-Fi radio switched on.")
NETWORK_UNREACHABLE = _("The login screen cannot reach the network settings.")
NETWORK_AGAIN = _("Look again")
NETWORK_ON = _("Connected")
NETWORK_SAVED = _("Saved")
NETWORK_LOCKED = _("Needs a password")
NETWORK_JOIN = _("Join {name}")
NETWORK_JOIN_BODY = _("This network needs a password. Nothing you type here is stored by this screen.")
NETWORK_JOIN_ACTION = _("Join")
NETWORK_CANCEL = _("Not now")
NETWORK_JOINING = _("Joining {name}.")
NETWORK_LEAVING = _("Disconnecting.")
NETWORK_REFUSED = _("That network could not be joined.")

#: Power, now inside the panel rather than loose in the corner.
RESTART = _("Restart")
SHUT_DOWN = _("Shut down")
RESTART_CONFIRM = _("Restart this computer?")
SHUT_DOWN_CONFIRM = _("Shut down this computer?")
POWER_BODY = _("Anything left unsaved in a signed in session will be lost.")
POWER_STAY = _("Keep this screen")

#: Read aloud, for the people who need it read aloud.
DESCRIBE_ACCOUNT = _("Sign in as {name}.")
DESCRIBE_PASSWORD = _("Password for {name}.")
DESCRIBE_SESSION = _("The desktop {name} signs in to.")
DESCRIBE_POWER = _("Power options for this computer.")
DESCRIBE_NETWORK = _("{name}, signal {bars} of 4.")

#: The weather, which is the one thing on this screen that is not about this
#: computer. It says less on the shelf than anywhere else in the product and
#: more behind a press than anywhere else, and both are deliberate.
WEATHER = _("Weather")
WEATHER_PILL_HELP = _("The weather where you are, and the week ahead.")
#: An alert on the panel. The headline comes from the service and is
#: written by the office that issued it, so it is not ours to reword.
WEATHER_ALERT_UNTIL = _("until {time}")
WEATHER_ALERT_NOW = _("now in force")
WEATHER_ALERTS = _("Weather warnings")

#: The sentence, which is the only thing on this panel a person could not have
#: worked out by looking out of the window. Every clause is arithmetic with
#: words attached, and each one is absent rather than hedged where the
#: arithmetic cannot answer.
OUTLOOK_RAIN = _("Rain")
OUTLOOK_SNOW = _("Snow")
#: Rain that has effectively already started.
#:
#: This was the word "shortly" dropped into "{kind} from {when}", which
#: produced "Rain from shortly". Every other value of `when` is a time, "from"
#: wants a time, and an adverb in the hole reads as a machine assembling a
#: sentence out of parts. Its own template instead.
OUTLOOK_MIDNIGHT = _("midnight")
OUTLOOK_MIDDAY = _("midday")
OUTLOOK_MORNING = _("{hour} in the morning")
OUTLOOK_AFTERNOON = _("{hour} in the afternoon")
OUTLOOK_EVENING = _("{hour} in the evening")
OUTLOOK_RAIN_ONLY = _("{kind} from {when}.")
OUTLOOK_RAIN_AMOUNT = _("{kind} from {when}, about {amount}.")
OUTLOOK_RAIN_SOON = _("{kind} within the hour.")
OUTLOOK_RAIN_SOON_AMOUNT = _("{kind} within the hour, about {amount}.")
OUTLOOK_RAIN_ENDS = _("Clearing by {when}.")
OUTLOOK_FRONT = _("A front comes through: {degrees} colder by {when}, "
                  "with the wind swinging {direction}.")
OUTLOOK_MUGGY = _("Muggy.")
OUTLOOK_UNSTABLE = _("The air is unstable, so a storm is possible even where "
                     "none is forecast.")
OUTLOOK_WARMER = _("{degrees} warmer than usual for the date.")
OUTLOOK_COLDER = _("{degrees} colder than usual for the date.")
WEATHER_LOOKING = _("Checking the weather")
WEATHER_UNKNOWN = _("Weather")
WEATHER_NO_ANSWER = _("No answer from the weather service yet.")
WEATHER_AGAIN = _("Check again")
DESCRIBE_WEATHER_AGAIN = _("Asks the weather service for a new reading.")

#: The hero. `H` and `L` rather than the words, because this pair sits under
#: a temperature three times its size and the words fight it.
WEATHER_FEELS = _("Feels like {degrees}")
#: And why, where there is a why. Heat index and wind chill are different
#: calculations meaning different things, and the panel called both of them
#: the same thing, which leaves the number unexplained in exactly the
#: conditions where somebody wants it explained.
WEATHER_FEELS_HUMID = _("Feels like {degrees}, from the humidity")
WEATHER_FEELS_WIND = _("Feels like {degrees}, from the wind")
WEATHER_RANGE = _("H {high}   L {low}")

#: The readings. Each caption is the word somebody would use out loud, and
#: each note underneath says what the number means rather than repeating it.
WEATHER_HUMIDITY = _("Humidity")
WEATHER_DEW = _("Dew point {degrees}")
WEATHER_WIND = _("Wind")
WEATHER_GUST = _("Gusting {speed}")
WEATHER_FROM = _("From the {direction}")
WEATHER_UV = _("UV index")
WEATHER_PRESSURE = _("Pressure")
WEATHER_PRESSURE_LOW = _("Low, unsettled")
WEATHER_PRESSURE_NORMAL = _("Normal")
WEATHER_PRESSURE_HIGH = _("High, settled")
WEATHER_VISIBILITY = _("Visibility")
WEATHER_VISIBILITY_POOR = _("Poor")
WEATHER_VISIBILITY_FAIR = _("Reduced")
WEATHER_VISIBILITY_GOOD = _("Clear")
WEATHER_MOON = _("Moon")
WEATHER_MOON_LIT = _("{percent} percent lit")

#: The sun's own day, said as a length rather than as two clock readings, so
#: nobody has to subtract one time from another to learn the useful part.
WEATHER_DAYLIGHT = _("{hours}h {minutes}m of daylight")
WEATHER_SUNRISE = _("Sunrise at {time}")
WEATHER_SUNSET_IN = _("{hours}h {minutes}m until sunset")
WEATHER_AFTER_DARK = _("The sun has set")
WEATHER_NO_SUNSET = _("The sun neither rises nor sets here today")

#: The week. Spelled out for the two days people count from, and left as
#: weekday names after that.
#: What the drawn charts say when they are read out rather than looked at.
#:
#: A chart is a picture of numbers, and the numbers are nowhere else on the
#: panel. Marked decorative, which is what every `Drawn` widget is by
#: default, the whole forecast is simply absent for anybody using a screen
#: reader while the barometric pressure beside it is announced.
WEATHER_HOURS_CHART = _("Hourly forecast")
WEATHER_DAYS_CHART = _("The week ahead")
WEATHER_SUN_CHART = _("Daylight")
WEATHER_SPOKEN_HOUR = _("{time}, {degrees}")
WEATHER_SPOKEN_DAY = _("{name}, {condition}, {low} to {high}")
WEATHER_SPOKEN_RAIN = _("{chance} percent chance of rain at {time}.")
WEATHER_SPOKEN_NOTHING = _("No reading yet.")

WEATHER_TODAY = _("Today")
WEATHER_TOMORROW = _("Tomorrow")

#: Said out loud, for anybody who is listening rather than looking. The pill
#: shows a mark and a number; this is the same fact as a sentence.
WEATHER_SAID = _("{degrees}, {condition}, in {place}.")
WEATHER_SAID_HERE = _("{degrees}, {condition}.")

#: The shade, which is what this screen is before anybody has touched it.
#: A clock, a date, a greeting, and the picture saying what it is. Nothing
#: else, because everything else belongs to the person who has not arrived yet.
GREETING = _("Good {part}")
#: Shown under the date when the clock reads earlier than the software it is
#: running. Not "unsynchronised", which is true of many correct machines, but
#: wrong beyond argument, which is what a dead coin cell looks like.
CLOCK_WRONG = _("The date is wrong. Nothing has set this machine's clock.")

SHADE_HINT = _("Press any key, or click, to sign in")
SHADE_LABEL = _("Locked")
SHADE_HELP = _("Press any key, or click, to choose an account.")

#: The picture's own card. Every line is drawn only when there is something
#: true to put in it, so a photograph of nowhere in particular carries a title
#: and a sentence and stops there.
CARD_LABEL = _("About this picture")
CARD_TIMES = _("{there} there, {here} here")
CARD_TIME_THERE = _("{there} there")

#: The days the sun turns or crosses, and the nights the moon is full. Eleven
#: or so lines a year, and nothing on any other day. A line that appears every
#: morning is furniture; one that appears eleven times is somebody having
#: thought about it.
OCCASION_EQUINOX = _("Equinox today. Day and night are almost the same length.")
OCCASION_SOLSTICE = _("Solstice today. The sun turns back.")
OCCASION_LONGEST = _("The longest day of the year.")
OCCASION_SHORTEST = _("The shortest day of the year.")
OCCASION_FULL_MOON = _("Full moon tonight.")


# -- warnings, off the panel and onto the screen ----------------------------
#
# The panel carries every admitted warning as a row. These are for the two
# tiers that come out of it: a strip across the top, and the screen itself.

#: The distance line. Three of them, because a storm moving away is a
#: different sentence from one heading here, and one heading here with no
#: usable speed is a third.
ALERT_MOTION_TOWARDS = _("{miles} miles away, heading this way")
ALERT_MOTION_MINUTES = _("{miles} miles away. About {minutes} minutes.")
ALERT_MOTION_AWAY = _("{miles} miles away, moving off")

#: Under it, the track itself.
ALERT_HEADING = _("Moving {way} at {mph} mph")

#: And the way out. Said plainly, because somebody reading this may be trying
#: to sign in to call for help and needs to know the screen will let them.
ALERT_DISMISS = _("Press any key to continue")


# -- what happens after the third wrong password ---------------------------
#
# The stack below this screen locks an account after a few wrong passwords,
# and until now the screen went on saying the password did not work, over and
# over, with nothing to show for it. That reads as a broken machine rather
# than as one protecting somebody, and the difference is a sentence.
#
# The numbers come from `pam_faillock`'s own configuration, read at the time,
# so this describes the policy the machine is actually running rather than one
# invented here. Where there is no lockout configured at all, none of this is
# ever said.

LOCKOUT_SOON = _("One more wrong password will lock this account.")
LOCKED_MINUTES = _("This account is locked for about {minutes} minutes. "
                   "Nothing is broken. It unlocks itself.")
LOCKED_MINUTE = _("This account is locked for about a minute. Nothing is "
                  "broken. It unlocks itself.")


def locked_words(seconds: int) -> str:
    """How long the lock lasts, said the way a person would say it.

    Rounded up, because a lock that says ten minutes and lasts ten minutes and
    one second is a screen somebody stands in front of feeling lied to.
    """
    minutes = max(1, -(-int(seconds) // 60))
    if minutes == 1:
        return LOCKED_MINUTE
    return LOCKED_MINUTES.format(minutes=minutes)


# -- the air, and which way the barometer is going -------------------------

WEATHER_AIR = _("Air quality")
#: Advice first, then the band's own name in brackets, the same shape the
#: ultraviolet note uses.
WEATHER_AIR_NOTE = _("{advice} ({band})")

#: The direction, which is most of what a barometer is for. Written to sit
#: after the band, so the line reads "Normal, and falling."
WEATHER_PRESSURE_FALLING = _("and falling")
WEATHER_PRESSURE_RISING = _("and rising")
WEATHER_PRESSURE_STEADY = _("and steady")
