"""Read and set display brightness through logind."""
from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio  # noqa: E402

BACKLIGHT_DIR = os.environ.get("AURADE_BACKLIGHT_DIR", "/sys/class/backlight")

#: Never all the way off.
#:
#: Zero is a black screen with no way back for somebody who cannot see the
#: slider they just moved, on a login screen, before they have signed in. The
#: floor is low enough to be dark in a bedroom and high enough to find.
FLOOR = 0.05

SESSION = "/org/freedesktop/login1/session/auto"


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def device(where: str = "") -> str:
    """Which backlight to drive, or nothing on a machine with none.

    The first by name, and named rather than guessed at again later, so that
    reading and setting cannot end up talking about different panels on a
    machine that has two.
    """
    root = where or BACKLIGHT_DIR
    try:
        found = sorted(os.listdir(root))
    except OSError:
        return ""
    for name in found:
        if _read(os.path.join(root, name, "max_brightness")).isdigit():
            return name
    return ""


def level(where: str = "", name: str = "") -> float | None:
    """Where the brightness is now, from nothing to one."""
    root = where or BACKLIGHT_DIR
    name = name or device(root)
    if not name:
        return None
    now = _read(os.path.join(root, name, "brightness"))
    top = _read(os.path.join(root, name, "max_brightness"))
    if not now.isdigit() or not top.isdigit() or int(top) <= 0:
        return None
    return max(0.0, min(1.0, int(now) / int(top)))


def steps(where: str = "", name: str = "") -> int | None:
    root = where or BACKLIGHT_DIR
    name = name or device(root)
    top = _read(os.path.join(root, name, "max_brightness")) if name else ""
    return int(top) if top.isdigit() and int(top) > 0 else None


def raw(fraction: float, top: int) -> int:
    """One fraction as the number the kernel wants, floored and rounded.

    Rounded rather than truncated, so dragging a slider to a hundred percent
    arrives at a hundred percent rather than one step below it, which is the
    kind of thing somebody notices and cannot explain.
    """
    return max(1, min(top, int(round(max(FLOOR, min(1.0, fraction)) * top))))


def set_level(fraction: float, where: str = "", name: str = "",
              bus=None) -> bool:
    """Ask logind to move it. False where there is nothing to move."""
    root = where or BACKLIGHT_DIR
    name = name or device(root)
    top = steps(root, name)
    if not name or top is None:
        return False
    try:
        connection = bus or Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        connection.call_sync(
            "org.freedesktop.login1", SESSION,
            "org.freedesktop.login1.Session", "SetBrightness",
            GLibVariant("(ssu)", ("backlight", name, raw(fraction, top))),
            None, Gio.DBusCallFlags.NONE, 4000, None)
    except Exception:  # noqa: BLE001 - a slider, never a traceback
        return False
    return True


def GLibVariant(signature: str, values):  # noqa: N802 - reads as a constructor
    from gi.repository import GLib  # noqa: PLC0415

    return GLib.Variant(signature, values)
