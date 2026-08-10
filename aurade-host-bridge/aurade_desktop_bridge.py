#!/usr/bin/python
"""AuraDE session D-Bus bridge for MIME/file association launches.

SPDX-License-Identifier: BSD-3-Clause
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Callable

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

sys.path.insert(0, "/usr/lib/aurade-host-bridge")

from aurade_host_bridge_core import BridgeError, MimeLauncher, response


SERVICE = "org.aurade.DesktopBridge"
PATH = "/org/aurade/DesktopBridge"
INTERFACE = "org.aurade.DesktopBridge1"
log = logging.getLogger("aurade-desktop-bridge")


class DesktopBridge(dbus.service.Object):
    def __init__(self, bus: dbus.SessionBus):
        self.launcher = MimeLauncher()
        super().__init__(bus, PATH)

    def _invoke(self, operation: str, function: Callable[[], Any]) -> str:
        try:
            return response(operation, function())
        except BridgeError as exc:
            return response(operation, error=exc)
        except Exception:
            log.exception("unexpected failure in %s", operation)
            return response(operation, error=BridgeError("internal_error", "unexpected bridge failure"))

    @dbus.service.method(INTERFACE, in_signature="s", out_signature="s")
    def MimeOpen(self, target: str) -> str:
        return self._invoke("mime.open", lambda: self.launcher.open(target))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    bus_name = dbus.service.BusName(SERVICE, bus=bus, do_not_queue=True)
    bridge = DesktopBridge(bus)
    GLib.MainLoop().run()
    del bridge
    del bus_name
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
