#!/usr/bin/python
"""Command-line client for AuraDE host bridges.

SPDX-License-Identifier: BSD-3-Clause
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import dbus
import dbus.mainloop.glib
from gi.repository import GLib

sys.path.insert(0, "/usr/lib/aurade-host-bridge")

from aurade_host_bridge_core import (
    BridgeError,
    MimeLauncher,
    normalize_open_target,
    response,
    validate_filesystem,
    validate_label,
    validate_mac,
    validate_object_path,
    validate_packages,
)


SYSTEM_SERVICE = "org.aurade.HostBridge"
SYSTEM_PATH = "/org/aurade/HostBridge"
SYSTEM_INTERFACE = "org.aurade.HostBridge1"
DESKTOP_SERVICE = "org.aurade.DesktopBridge"
DESKTOP_PATH = "/org/aurade/DesktopBridge"
DESKTOP_INTERFACE = "org.aurade.DesktopBridge1"
UDISKS_ROOT = "/org/freedesktop/UDisks2"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Control AuraDE Linux host integrations")
    result.add_argument("--dry-run", action="store_true", help="validate a mutation without contacting D-Bus")
    result.add_argument("--pretty", action="store_true", help="pretty-print JSON responses")
    commands = result.add_subparsers(dest="group", required=True)
    commands.add_parser("capabilities")
    commands.add_parser("events")

    bluetooth = commands.add_parser("bluetooth").add_subparsers(dest="action", required=True)
    bluetooth.add_parser("state")
    power = bluetooth.add_parser("power")
    power.add_argument("state", choices=("on", "off"))
    scan = bluetooth.add_parser("scan")
    scan.add_argument("state", choices=("start", "stop"))
    for action in ("pair", "connect", "disconnect", "forget"):
        item = bluetooth.add_parser(action)
        item.add_argument("address")

    storage = commands.add_parser("storage").add_subparsers(dest="action", required=True)
    storage.add_parser("list")
    mount = storage.add_parser("mount")
    mount.add_argument("block")
    mount.add_argument("--read-only", action="store_true")
    unmount = storage.add_parser("unmount")
    unmount.add_argument("block")
    unmount.add_argument("--force", action="store_true")
    for action in ("eject", "poweroff"):
        item = storage.add_parser(action)
        item.add_argument("drive")
    fmt = storage.add_parser("format")
    fmt.add_argument("block")
    fmt.add_argument("filesystem")
    fmt.add_argument("--label", default="")
    fmt.add_argument("--confirm", required=True, help='exact "FORMAT /dev/..." token returned by storage list')

    pacman = commands.add_parser("pacman").add_subparsers(dest="action", required=True)
    pacman.add_parser("installed")
    query = pacman.add_parser("query")
    query.add_argument("package")
    pacman.add_parser("updates")
    pacman.add_parser("upgrade")
    uninstall = pacman.add_parser("uninstall")
    uninstall.add_argument("packages", nargs="+")
    uninstall.add_argument("--remove-dependencies", action="store_true")
    job = pacman.add_parser("job")
    job.add_argument("job_id")

    mime = commands.add_parser("mime").add_subparsers(dest="action", required=True)
    opened = mime.add_parser("open")
    opened.add_argument("target")
    return result


def dry_run(args: argparse.Namespace) -> str:
    data: dict[str, Any]
    if args.group == "bluetooth":
        if args.action in {"pair", "connect", "disconnect", "forget"}:
            data = {"action": args.action, "address": validate_mac(args.address), "dry_run": True}
        elif args.action == "power":
            data = {"action": "power", "powered": args.state == "on", "dry_run": True}
        elif args.action == "scan":
            data = {"action": "scan", "start": args.state == "start", "dry_run": True}
        else:
            raise BridgeError("invalid_argument", "dry-run is only supported for mutations")
    elif args.group == "storage":
        if args.action in {"mount", "unmount"}:
            data = {"action": args.action, "block": validate_object_path(args.block, UDISKS_ROOT), "dry_run": True}
        elif args.action in {"eject", "poweroff"}:
            data = {"action": args.action, "drive": validate_object_path(args.drive, UDISKS_ROOT), "dry_run": True}
        elif args.action == "format":
            block = validate_object_path(args.block, UDISKS_ROOT)
            filesystem = validate_filesystem(args.filesystem)
            label = validate_label(args.label)
            if not args.confirm.startswith("FORMAT /dev/"):
                raise BridgeError("confirmation_required", "format confirmation must name a /dev target")
            data = {"action": "format", "block": block, "filesystem": filesystem,
                    "label": label, "confirmation": args.confirm, "dry_run": True}
        else:
            raise BridgeError("invalid_argument", "dry-run is only supported for mutations")
    elif args.group == "pacman":
        if args.action == "upgrade":
            data = {"action": "upgrade", "command": ["/usr/bin/pacman", "-Syu", "--noconfirm"], "dry_run": True}
        elif args.action == "uninstall":
            packages = validate_packages(args.packages)
            data = {"action": "uninstall", "packages": packages,
                    "remove_dependencies": args.remove_dependencies, "dry_run": True}
        else:
            raise BridgeError("invalid_argument", "dry-run is only supported for mutations")
    elif args.group == "mime" and args.action == "open":
        data = MimeLauncher().open(normalize_open_target(args.target), dry_run=True)
    else:
        raise BridgeError("invalid_argument", "dry-run is only supported for mutations")
    return response("dry-run", data)


def call_system(method: str, *args: Any, timeout: int = 300) -> str:
    bus = dbus.SystemBus()
    obj = bus.get_object(SYSTEM_SERVICE, SYSTEM_PATH)
    return str(getattr(dbus.Interface(obj, SYSTEM_INTERFACE), method)(*args, timeout=timeout))


def call_desktop(method: str, *args: Any) -> str:
    bus = dbus.SessionBus()
    obj = bus.get_object(DESKTOP_SERVICE, DESKTOP_PATH)
    return str(getattr(dbus.Interface(obj, DESKTOP_INTERFACE), method)(*args, timeout=30))


def real_call(args: argparse.Namespace) -> str:
    if args.group == "capabilities":
        return call_system("GetCapabilities")
    if args.group == "bluetooth":
        methods = {
            "state": ("BluetoothGetState", ()),
            "power": ("BluetoothSetPowered", (dbus.Boolean(args.state == "on"),)),
            "scan": ("BluetoothStartDiscovery" if args.state == "start" else "BluetoothStopDiscovery", ()),
            "pair": ("BluetoothPair", (validate_mac(args.address),)),
            "connect": ("BluetoothConnect", (validate_mac(args.address),)),
            "disconnect": ("BluetoothDisconnect", (validate_mac(args.address),)),
            "forget": ("BluetoothForget", (validate_mac(args.address),)),
        }
        method, call_args = methods[args.action]
        return call_system(method, *call_args)
    if args.group == "storage":
        if args.action == "list":
            return call_system("StorageList")
        if args.action == "mount":
            return call_system("StorageMount", dbus.ObjectPath(validate_object_path(args.block, UDISKS_ROOT)), dbus.Boolean(args.read_only))
        if args.action == "unmount":
            return call_system("StorageUnmount", dbus.ObjectPath(validate_object_path(args.block, UDISKS_ROOT)), dbus.Boolean(args.force))
        if args.action in {"eject", "poweroff"}:
            method = "StorageEject" if args.action == "eject" else "StoragePowerOff"
            return call_system(method, dbus.ObjectPath(validate_object_path(args.drive, UDISKS_ROOT)))
        return call_system(
            "StorageFormat", dbus.ObjectPath(validate_object_path(args.block, UDISKS_ROOT)),
            validate_filesystem(args.filesystem), validate_label(args.label), args.confirm,
        )
    if args.group == "pacman":
        if args.action == "installed":
            return call_system("PacmanListInstalled")
        if args.action == "query":
            return call_system("PacmanQuery", args.package)
        if args.action == "updates":
            return call_system("PacmanListUpdates", timeout=600)
        if args.action == "upgrade":
            return call_system("PacmanUpgrade", timeout=600)
        if args.action == "uninstall":
            return call_system("PacmanUninstall", dbus.Array(validate_packages(args.packages), signature="s"),
                               dbus.Boolean(args.remove_dependencies), timeout=600)
        return call_system("JobGet", args.job_id)
    if args.group == "mime" and args.action == "open":
        return call_desktop("MimeOpen", normalize_open_target(args.target))
    raise BridgeError("invalid_argument", "unsupported operation")


def events() -> int:
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    bus.add_signal_receiver(
        lambda payload: print(str(payload), flush=True),
        signal_name="Event", dbus_interface=SYSTEM_INTERFACE,
        bus_name=SYSTEM_SERVICE, path=SYSTEM_PATH,
    )
    try:
        GLib.MainLoop().run()
    except KeyboardInterrupt:
        return 0
    return 0


def main() -> int:
    args = parser().parse_args()
    if args.group == "events":
        if args.dry_run:
            print(response("dry-run", error=BridgeError("invalid_argument", "events cannot be dry-run")))
            return 2
        return events()
    try:
        output = dry_run(args) if args.dry_run else real_call(args)
        parsed = json.loads(output)
    except BridgeError as exc:
        parsed = json.loads(response("client", error=exc))
    except (dbus.DBusException, json.JSONDecodeError) as exc:
        parsed = json.loads(response("client", error=BridgeError("transport_error", str(exc))))
    print(json.dumps(parsed, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if parsed.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
