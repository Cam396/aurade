"""The three things a computer normally tells you, which an installer does not.

Every desktop in the world has a clock, a battery and a network indicator in
one corner, and every one of those answers a question somebody has while an
installer is running:

    **the clock**, because an install takes ten minutes and the machine has
    just booted from a stick with no session on it, so there is nowhere else
    on the screen to find out how long this has been going or whether it is
    now late;

    **the battery**, because losing power part way through writing a
    filesystem leaves a disk that is neither the old system nor the new one,
    and the warning before the erase gate is a single moment while this is
    the whole ten minutes;

    **the network**, because half the install is a download, and "is it still
    connected" is the first thing anybody asks of a progress bar that has
    stopped moving.

None of it is decoration. It is the same three facts every other operating
system puts in the same corner, on the one screen that had none of them.

No ``gi`` import here, and no toolkit anywhere in it, so the reading can be
tested on a machine with no display and no battery. Everything comes from
files under ``/sys`` and ``/proc``, every path is overridable, and every read
is allowed to fail: a status area that raises is worse than one that is
blank.
"""

from __future__ import annotations

import os
import time

#: Where the kernel puts power supplies. The same variable the text installer
#: reads, so a test that fakes a battery fakes it for both front ends.
POWER_DIR = os.environ.get("AURADE_POWER_DIR", "/sys/class/power_supply")

#: Where the kernel puts network interfaces, and where it puts the routing
#: table. Both overridable for the same reason.
NET_DIR = os.environ.get("AURADE_NET_DIR", "/sys/class/net")
ROUTE_FILE = os.environ.get("AURADE_ROUTE_FILE", "/proc/net/route")

#: Below this, on battery, the battery reading is drawn as a warning rather
#: than as a fact. The same floor the text installer warns at, because two
#: front ends disagreeing about what counts as low is two products.
BATTERY_FLOOR = int(os.environ.get("AURADE_BATTERY_FLOOR", "40") or 40)


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def clock(when: float | None = None) -> str:
    """The local time, to the minute.

    Twenty four hour, because the installer runs before anybody has told this
    machine which they prefer and a wrong guess about that is worse than a
    format some people would not have chosen.
    """
    return time.strftime("%H:%M", time.localtime(when))


def battery() -> dict[str, object]:
    """What the battery is doing, or an empty answer on a machine with none.

    Returns ``percent``, ``charging`` and ``mains``. A desktop, a machine
    whose kernel reports nothing, and a battery with no capacity file all
    come back the same way, which is the way that draws nothing.
    """
    answer: dict[str, object] = {"percent": None, "charging": False,
                                 "mains": False}
    if not os.path.isdir(POWER_DIR):
        return answer
    try:
        supplies = sorted(os.listdir(POWER_DIR))
    except OSError:
        return answer
    for name in supplies:
        base = os.path.join(POWER_DIR, name)
        kind = _read(os.path.join(base, "type"))
        if kind in ("Mains", "USB"):
            if _read(os.path.join(base, "online")) == "1":
                answer["mains"] = True
            continue
        if kind != "Battery":
            continue
        capacity = _read(os.path.join(base, "capacity"))
        if not capacity.isdigit():
            continue
        answer["percent"] = int(capacity)
        state = _read(os.path.join(base, "status"))
        answer["charging"] = state in ("Charging", "Full")
    return answer


def _wireless(name: str) -> bool:
    base = os.path.join(NET_DIR, name)
    return (os.path.isdir(os.path.join(base, "wireless"))
            or os.path.exists(os.path.join(base, "phy80211")))


def routed() -> bool:
    """Whether there is a default route, which is the only honest test.

    An interface can be up, have a cable in it and a link light on, and still
    have no way out of the building. `operstate` answers "is this cable
    plugged in"; this answers the question somebody watching a download
    actually has.
    """
    try:
        with open(ROUTE_FILE, encoding="utf-8") as handle:
            rows = handle.read().splitlines()
    except OSError:
        return False
    for line in rows[1:]:
        fields = line.split()
        # Iface, Destination, Gateway, ... A destination of all zeroes is the
        # default route, whatever the interface is called.
        if len(fields) > 2 and fields[1] == "00000000":
            return True
    return False


def network() -> dict[str, object]:
    """Which interface is carrying this machine, if any.

    ``kind`` is ``wifi``, ``wired`` or an empty string, and ``online`` says
    whether there is a route out. The two are separate answers on purpose: a
    machine with a cable in it and no DHCP lease is a real state, and it is
    exactly the state somebody needs to be told about rather than shown a
    hopeful icon for.
    """
    answer: dict[str, object] = {"kind": "", "name": "", "online": routed()}
    try:
        names = sorted(os.listdir(NET_DIR))
    except OSError:
        return answer
    best = ""
    for name in names:
        if name == "lo":
            continue
        if _read(os.path.join(NET_DIR, name, "operstate")) != "up":
            continue
        # A cable wins over a radio when both are up, because that is the one
        # the packets are going down and it is the one that will not drop.
        if not _wireless(name):
            best = name
            answer["kind"] = "wired"
            break
        if not best:
            best = name
            answer["kind"] = "wifi"
    answer["name"] = best
    return answer


def battery_icon(percent: int | None, charging: bool) -> str:
    """The icon name for a battery at this level.

    Charging is its own icon rather than a colour, because a battery at 30
    percent means two entirely different things depending on which way it is
    going, and that difference must not be carried by colour alone.
    """
    if percent is None:
        return "battery-missing-symbolic"
    if charging:
        return "battery-good-charging-symbolic"
    if percent <= 10:
        return "battery-empty-symbolic"
    if percent <= 30:
        return "battery-caution-symbolic"
    if percent <= 60:
        return "battery-low-symbolic"
    if percent <= 90:
        return "battery-good-symbolic"
    return "battery-full-symbolic"


def network_icon(kind: str, online: bool) -> str:
    if kind == "wifi":
        return ("network-wireless-signal-good-symbolic" if online
                else "network-wireless-offline-symbolic")
    if kind == "wired":
        return ("network-wired-symbolic" if online
                else "network-wired-disconnected-symbolic")
    return "network-offline-symbolic"
