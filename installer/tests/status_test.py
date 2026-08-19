#!/usr/bin/env python3
"""The clock, the battery and the network reading, against made up hardware.

`aurade_gui/status.py` is three readings taken from files, and every one of
them has a case that matters and no machine to test it on: a desktop with no
battery, a laptop at nine percent, a cable that is plugged in with no route
behind it. So the files are made up here, which is what the overridable paths
in that module exist for.

The last check is the one that would otherwise rot. The download rate is drawn
in both front ends from the same sampler file, and the two of them format it
independently: one in bash and one in Python. A rounding difference is two
installers reporting different speeds for the same download, so the numbers
are compared rather than the code being trusted to have stayed in step.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import tempfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                     "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "installer", "lib"))

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text + "\n")


def reload_with(**environment: str):
    for key, value in environment.items():
        os.environ[key] = value
    from aurade_gui import status  # noqa: PLC0415
    return importlib.reload(status)


with tempfile.TemporaryDirectory() as tmp:
    # -- a desktop ---------------------------------------------------------
    #
    # Mains only. It must draw no battery at all rather than a battery with a
    # question mark in it, because a desktop has not got one and saying so is
    # not information.
    power = os.path.join(tmp, "desktop-power")
    write(os.path.join(power, "AC", "type"), "Mains")
    write(os.path.join(power, "AC", "online"), "1")
    status = reload_with(AURADE_POWER_DIR=power)
    reading = status.battery()
    check(reading["percent"] is None,
          f"a desktop reported a battery at {reading['percent']}")
    check(reading["mains"] is True, "a desktop did not report mains power")

    # -- a laptop, unplugged and low --------------------------------------
    power = os.path.join(tmp, "low-power")
    write(os.path.join(power, "AC", "type"), "Mains")
    write(os.path.join(power, "AC", "online"), "0")
    write(os.path.join(power, "BAT0", "type"), "Battery")
    write(os.path.join(power, "BAT0", "capacity"), "9")
    write(os.path.join(power, "BAT0", "status"), "Discharging")
    status = reload_with(AURADE_POWER_DIR=power)
    reading = status.battery()
    check(reading["percent"] == 9, f"nine percent read as {reading['percent']}")
    check(reading["charging"] is False, "a discharging battery read as charging")
    check(reading["mains"] is False, "an unplugged laptop reported mains power")
    check(status.battery_icon(9, False) == "battery-empty-symbolic",
          "nine percent does not draw as empty")
    # Charging is its own icon and not a colour, because a battery at thirty
    # percent means two different things depending which way it is going.
    check(status.battery_icon(9, True) != status.battery_icon(9, False),
          "a charging battery draws exactly like a draining one")

    # -- a laptop, plugged in ---------------------------------------------
    power = os.path.join(tmp, "charging-power")
    write(os.path.join(power, "AC", "type"), "Mains")
    write(os.path.join(power, "AC", "online"), "1")
    write(os.path.join(power, "BAT0", "type"), "Battery")
    write(os.path.join(power, "BAT0", "capacity"), "34")
    write(os.path.join(power, "BAT0", "status"), "Charging")
    status = reload_with(AURADE_POWER_DIR=power)
    reading = status.battery()
    check(reading["charging"] is True, "a charging battery did not read as charging")

    # -- a kernel reporting nonsense --------------------------------------
    #
    # A status area that raises is worse than one that is blank, and this is
    # the screen that must not raise.
    power = os.path.join(tmp, "broken-power")
    write(os.path.join(power, "BAT0", "type"), "Battery")
    write(os.path.join(power, "BAT0", "capacity"), "not a number")
    status = reload_with(AURADE_POWER_DIR=power)
    check(status.battery()["percent"] is None,
          "a capacity that is not a number was read as one")
    status = reload_with(AURADE_POWER_DIR=os.path.join(tmp, "no-such-dir"))
    check(status.battery()["percent"] is None,
          "a missing power supply directory did not read as no battery")

    # -- the network -------------------------------------------------------
    net = os.path.join(tmp, "net-wired")
    write(os.path.join(net, "lo", "operstate"), "up")
    write(os.path.join(net, "enp0s3", "operstate"), "up")
    route = os.path.join(tmp, "route-up")
    write(route, "Iface\tDestination\tGateway\tFlags\n"
                 "enp0s3\t00000000\t0102A8C0\t0003")
    status = reload_with(AURADE_NET_DIR=net, AURADE_ROUTE_FILE=route)
    link = status.network()
    check(link["kind"] == "wired", f"a cable read as {link['kind']!r}")
    check(link["online"] is True, "a default route did not read as online")
    # Loopback is up on every machine ever made and is not a network.
    check(link["name"] != "lo", "loopback was reported as the network")

    # A cable in, and no route out. A real state, and exactly the one somebody
    # needs telling about rather than being shown a hopeful icon for.
    route = os.path.join(tmp, "route-none")
    write(route, "Iface\tDestination\tGateway\tFlags\n"
                 "enp0s3\t0101A8C0\t00000000\t0001")
    status = reload_with(AURADE_NET_DIR=net, AURADE_ROUTE_FILE=route)
    link = status.network()
    check(link["kind"] == "wired", "a cable with no route stopped being a cable")
    check(link["online"] is False, "a table with no default route read as online")
    check(status.network_icon("wired", False) != status.network_icon("wired", True),
          "connected and not connected draw the same")

    # A radio, and a cable that wins over it when both are up.
    #
    # Loopback is in this fixture and sorts before the radio, so a reader that
    # has stopped skipping it picks `lo`, calls it a cable and stops looking.
    # It sorts after `enp0s3`, which is why it belongs here and not in the
    # wired fixture above: there it would never be reached at all.
    net = os.path.join(tmp, "net-wifi")
    write(os.path.join(net, "lo", "operstate"), "up")
    write(os.path.join(net, "wlp3s0", "operstate"), "up")
    os.makedirs(os.path.join(net, "wlp3s0", "wireless"), exist_ok=True)
    status = reload_with(AURADE_NET_DIR=net, AURADE_ROUTE_FILE=route)
    check(status.network()["kind"] == "wifi", "a radio did not read as Wi-Fi")
    check(status.network()["name"] == "wlp3s0",
          f"the network was reported as {status.network()['name']!r}")
    write(os.path.join(net, "enp0s3", "operstate"), "up")
    status = reload_with(AURADE_NET_DIR=net, AURADE_ROUTE_FILE=route)
    check(status.network()["kind"] == "wired",
          "a radio was preferred over a cable that was also up")

    # An interface that is down is not the network.
    net = os.path.join(tmp, "net-down")
    write(os.path.join(net, "enp0s3", "operstate"), "down")
    status = reload_with(AURADE_NET_DIR=net, AURADE_ROUTE_FILE=route)
    check(status.network()["kind"] == "", "an interface that is down was chosen")

# -- the clock -------------------------------------------------------------

when = 1755600000.0
drawn = reload_with().clock(when)
check(len(drawn) == 5 and drawn[2] == ":",
      f"the clock drew {drawn!r}, which is not a time")

# -- the download rate, against the text installer's own formatter ----------

from aurade_gui import flow as F  # noqa: E402

TUI_LIB = os.path.join(ROOT, "installer", "lib", "aurade-tui.sh")
values = [0, 1, 999, 1023, 1024, 1025, 1536, 100000, 1048575, 1048576,
          1572864, 4404019, 12000000, 999999999]
script = "\n".join([f'. "{TUI_LIB}"'] +
                   [f'tui_rate {value}; printf "\\n"' for value in values])
result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
theirs = result.stdout.splitlines()
check(len(theirs) == len(values),
      f"the text installer's formatter produced {len(theirs)} answers, "
      f"not {len(values)}: {result.stderr.strip()}")
for value, there in zip(values, theirs):
    here = F.rate_label(value)
    check(here == there,
          f"{value} bytes a second is {here!r} in the graphical installer "
          f"and {there!r} in the text one")
check(F.rate_label(-1) == "", "a negative rate was drawn rather than dropped")

if FAILURES:
    for failure in FAILURES:
        print(f"status test: {failure}", file=sys.stderr)
    print(f"status test: FAIL ({len(FAILURES)})", file=sys.stderr)
    sys.exit(1)
print("status test: PASS")
