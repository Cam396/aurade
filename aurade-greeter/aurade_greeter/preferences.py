"""The accessibility choices somebody already made, read back at the greeter.

The installer asks whether somebody needs a screen reader, high contrast,
larger text, a different typeface, or less movement, and writes the answers to
`/etc/aurade-install/accessibility`. A first boot unit then checks those
answers reached the desktop.

Nothing checked they reached the login screen, and they did not. greetd starts
the greeter as its own user, and high contrast in particular is a dconf key
that GTK does not read on its own, so somebody who turned it on to get through
an install met a login screen without it. That is the worst place for this to
fail: the settings that would let them read the screen are behind the screen
they cannot read.

Read rather than sourced, key and value, with no eval anywhere. This file is
written by the installer and read by a process that sits in front of the login
prompt, and sourcing it would make a stray line in it a command.
"""

from __future__ import annotations

import os

#: Where the installer leaves its answers.
RECORD = "/etc/aurade-install/accessibility"

#: What this greeter can act on, and what it does when the record says nothing.
#:
#: The defaults are the ordinary appearance, so a machine with no record at
#: all, which is every machine installed before this existed, looks exactly as
#: it did.
DEFAULTS: dict[str, str] = {
    "contrast": "normal",
    "text_scale": "100",
    "reduce_motion": "no",
    "cursor_size": "24",
    "typeface": "system",
    "screen_reader": "no",
}

#: The typefaces the installer offers, and what to ask GTK for.
TYPEFACES = {
    "atkinson": "Atkinson Hyperlegible 11",
    "opendyslexic": "OpenDyslexic 11",
}

#: Text scale is a percentage. Below this the interface is unreadable and
#: above it a login panel does not fit on a laptop screen, and either way a
#: number outside the range is a record somebody has edited by hand into
#: something that cannot be honoured.
MIN_SCALE = 100
MAX_SCALE = 300


def read(path: str | None = None) -> dict[str, str]:
    """The record, or the ordinary appearance when there is not one."""
    path = path or os.environ.get("AURADE_GREETER_ACCESSIBILITY") or RECORD
    found = dict(DEFAULTS)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                key, separator, value = line.partition("=")
                if not separator:
                    continue
                key = key.strip()
                if key in found:
                    found[key] = value.strip()
    except OSError:
        return dict(DEFAULTS)
    return found


def wants_contrast(record: dict[str, str]) -> bool:
    return str(record.get("contrast", "")).lower() == "high"


def wants_stillness(record: dict[str, str]) -> bool:
    return str(record.get("reduce_motion", "")).lower() in ("yes", "true", "1")


def text_scale(record: dict[str, str]) -> int:
    """The scale as a percentage, clamped to something that can be drawn."""
    raw = str(record.get("text_scale", "")).strip()
    if not raw.isdigit():
        return MIN_SCALE
    return max(MIN_SCALE, min(MAX_SCALE, int(raw)))


def cursor_size(record: dict[str, str]) -> int:
    raw = str(record.get("cursor_size", "")).strip()
    if not raw.isdigit():
        return int(DEFAULTS["cursor_size"])
    return max(16, min(96, int(raw)))


def font_name(record: dict[str, str]) -> str:
    """The typeface to ask GTK for, or empty to leave the system's alone."""
    return TYPEFACES.get(str(record.get("typeface", "")).lower(), "")


def theme_for(record: dict[str, str], dark: bool, oled: bool = False) -> str:
    """Which of the five generated stylesheets this person should get."""
    if oled:
        return "oled"
    if wants_contrast(record):
        return "dark-hc" if dark else "light-hc"
    return "dark" if dark else "light"
