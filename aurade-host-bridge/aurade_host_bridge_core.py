#!/usr/bin/python
"""Core backends and validation for AuraDE Linux host integration.

This module deliberately has no dependency on dbus-python so its security
boundaries can be unit tested on build hosts without BlueZ or udisks2.

SPDX-License-Identifier: BSD-3-Clause
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence


BLUEZ_SERVICE = "org.bluez"
BLUEZ_ROOT = "/"
BLUEZ_ADAPTER = "org.bluez.Adapter1"
BLUEZ_DEVICE = "org.bluez.Device1"

UDISKS_SERVICE = "org.freedesktop.UDisks2"
UDISKS_ROOT = "/org/freedesktop/UDisks2"
UDISKS_BLOCK = "org.freedesktop.UDisks2.Block"
UDISKS_FILESYSTEM = "org.freedesktop.UDisks2.Filesystem"
UDISKS_DRIVE = "org.freedesktop.UDisks2.Drive"

OBJECT_PATH_RE = re.compile(r"^/(?:[A-Za-z0-9_]+(?:/[A-Za-z0-9_]+)*)?$")
PACKAGE_RE = re.compile(r"^[a-z0-9@._+][a-z0-9@._+-]{0,127}$")
MAC_RE = re.compile(r"^(?:[0-9A-F]{2}:){5}[0-9A-F]{2}$")
FILESYSTEMS = frozenset({"btrfs", "exfat", "ext4", "f2fs", "vfat", "xfs"})
MIME_SCHEMES = frozenset({"file", "http", "https", "mailto"})
SYSTEM_MOUNTS = frozenset({"/", "/boot", "/boot/efi", "/efi", "/home", "/usr", "/var"})
EXTERNAL_BUSES = frozenset({"firewire", "sdio", "usb"})
PROTECTED_PACKAGES = frozenset({
    "aurade",
    "aurade-full",
    "aurade-host-bridge",
    "base",
    "bash",
    "chromiumos-ash",
    "dbus",
    "filesystem",
    "glibc",
    "linux",
    "networkmanager",
    "pacman",
    "polkit",
    "systemd",
    "weston",
})


class BridgeError(RuntimeError):
    """An error safe to return across the public bridge interface."""

    def __init__(self, code: str, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


def response(operation: str, data: Any = None, *, error: BridgeError | None = None) -> str:
    payload: dict[str, Any] = {
        "schema": 1,
        "operation": operation,
        "ok": error is None,
        "timestamp_ms": int(time.time() * 1000),
    }
    if error is None:
        payload["data"] = data
    else:
        payload["error"] = {
            "code": error.code,
            "message": error.message,
            "details": error.details,
        }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def to_python(value: Any) -> Any:
    """Convert dbus-python values (and plain values) into JSON-safe values."""
    if isinstance(value, bytes):
        return value.rstrip(b"\0").decode("utf-8", errors="replace")
    if isinstance(value, Mapping):
        return {str(key): to_python(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        # UDisks encodes byte strings as arrays of byte-sized integers.
        if value and all(isinstance(item, int) and 0 <= item <= 255 for item in value):
            return bytes(value).rstrip(b"\0").decode("utf-8", errors="replace")
        return [to_python(item) for item in value]
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return str(value)


def validate_object_path(path: str, prefix: str) -> str:
    path = str(path)
    if not OBJECT_PATH_RE.fullmatch(path) or not path.startswith(prefix + "/"):
        raise BridgeError("invalid_argument", f"invalid object path below {prefix}")
    return path


def validate_mac(address: str) -> str:
    normalized = str(address).upper()
    if not MAC_RE.fullmatch(normalized):
        raise BridgeError("invalid_argument", "Bluetooth address must be six hexadecimal octets")
    return normalized


def validate_package(name: str) -> str:
    name = str(name)
    if not PACKAGE_RE.fullmatch(name):
        raise BridgeError("invalid_argument", "invalid Arch package name")
    return name


def validate_packages(names: Iterable[str]) -> list[str]:
    result = [validate_package(name) for name in names]
    if not result or len(result) > 64:
        raise BridgeError("invalid_argument", "one to 64 package names are required")
    if len(result) != len(set(result)):
        raise BridgeError("invalid_argument", "duplicate package names are not allowed")
    return result


def validate_filesystem(filesystem: str) -> str:
    filesystem = str(filesystem).lower()
    if filesystem not in FILESYSTEMS:
        raise BridgeError("invalid_argument", "unsupported filesystem", {"allowed": sorted(FILESYSTEMS)})
    return filesystem


def validate_label(label: str) -> str:
    label = str(label)
    if len(label.encode("utf-8")) > 32 or any(ord(char) < 32 for char in label):
        raise BridgeError("invalid_argument", "volume label must contain at most 32 bytes and no controls")
    return label


def normalize_open_target(target: str) -> str:
    target = str(target)
    if not target or len(target) > 8192 or any(ord(char) < 32 for char in target):
        raise BridgeError("invalid_argument", "invalid MIME target")
    parsed = urllib.parse.urlsplit(target)
    if parsed.scheme:
        if parsed.scheme.lower() not in MIME_SCHEMES:
            raise BridgeError("invalid_argument", "unsupported URI scheme", {"allowed": sorted(MIME_SCHEMES)})
        if parsed.scheme.lower() == "file" and parsed.netloc not in ("", "localhost"):
            raise BridgeError("invalid_argument", "remote file URIs are not supported")
        return target
    if not os.path.isabs(target):
        raise BridgeError("invalid_argument", "file targets must be absolute paths")
    return target


class Facade(Protocol):
    def managed_objects(self, service: str, root: str) -> Mapping[str, Mapping[str, Mapping[str, Any]]]: ...
    def call(self, service: str, path: str, interface: str, method: str, *args: Any) -> Any: ...
    def set_property(self, service: str, path: str, interface: str, prop: str, value: Any) -> None: ...


class BluetoothBackend:
    def __init__(self, facade: Facade):
        self.facade = facade

    def _objects(self) -> Mapping[str, Mapping[str, Mapping[str, Any]]]:
        try:
            return self.facade.managed_objects(BLUEZ_SERVICE, BLUEZ_ROOT)
        except Exception as exc:
            raise BridgeError("backend_unavailable", "BlueZ is unavailable") from exc

    def state(self) -> dict[str, Any]:
        adapters: list[dict[str, Any]] = []
        devices: list[dict[str, Any]] = []
        for path, interfaces in self._objects().items():
            if BLUEZ_ADAPTER in interfaces:
                props = interfaces[BLUEZ_ADAPTER]
                adapters.append({
                    "path": str(path),
                    "address": str(props.get("Address", "")),
                    "alias": str(props.get("Alias", props.get("Name", ""))),
                    "powered": bool(props.get("Powered", False)),
                    "discovering": bool(props.get("Discovering", False)),
                    "pairable": bool(props.get("Pairable", False)),
                })
            if BLUEZ_DEVICE in interfaces:
                props = interfaces[BLUEZ_DEVICE]
                devices.append({
                    "path": str(path),
                    "adapter": str(props.get("Adapter", "")),
                    "address": str(props.get("Address", "")),
                    "name": str(props.get("Name", "")),
                    "alias": str(props.get("Alias", props.get("Name", ""))),
                    "icon": str(props.get("Icon", "")),
                    "paired": bool(props.get("Paired", False)),
                    "connected": bool(props.get("Connected", False)),
                    "trusted": bool(props.get("Trusted", False)),
                    "rssi": int(props.get("RSSI", 0)),
                    "uuids": [str(item) for item in props.get("UUIDs", [])],
                })
        return {"adapters": sorted(adapters, key=lambda item: item["path"]),
                "devices": sorted(devices, key=lambda item: item["address"])}

    def _adapter(self) -> str:
        for path, interfaces in self._objects().items():
            if BLUEZ_ADAPTER in interfaces:
                return str(path)
        raise BridgeError("not_found", "no Bluetooth adapter was found")

    def _device(self, address: str) -> tuple[str, Mapping[str, Any]]:
        address = validate_mac(address)
        for path, interfaces in self._objects().items():
            props = interfaces.get(BLUEZ_DEVICE)
            if props and str(props.get("Address", "")).upper() == address:
                return str(path), props
        raise BridgeError("not_found", "Bluetooth device was not found", {"address": address})

    def set_powered(self, powered: bool) -> dict[str, Any]:
        path = self._adapter()
        props = self._objects()[path][BLUEZ_ADAPTER]
        if bool(props.get("Powered", False)) == bool(powered):
            return {"adapter": path, "powered": bool(powered), "changed": False}
        self.facade.set_property(BLUEZ_SERVICE, path, BLUEZ_ADAPTER, "Powered", bool(powered))
        return {"adapter": path, "powered": bool(powered), "changed": True}

    def discovery(self, start: bool) -> dict[str, Any]:
        path = self._adapter()
        props = self._objects()[path][BLUEZ_ADAPTER]
        if bool(props.get("Discovering", False)) == bool(start):
            return {"adapter": path, "discovering": bool(start), "changed": False}
        self.facade.call(BLUEZ_SERVICE, path, BLUEZ_ADAPTER, "StartDiscovery" if start else "StopDiscovery")
        return {"adapter": path, "discovering": bool(start), "changed": True}

    def device_action(self, address: str, action: str) -> dict[str, Any]:
        if action not in {"pair", "connect", "disconnect", "forget"}:
            raise BridgeError("invalid_argument", "unsupported Bluetooth action")
        path, props = self._device(address)
        address = validate_mac(address)
        if action == "pair" and bool(props.get("Paired", False)):
            return {"address": address, "action": action, "changed": False}
        if action == "connect" and bool(props.get("Connected", False)):
            return {"address": address, "action": action, "changed": False}
        if action == "disconnect" and not bool(props.get("Connected", False)):
            return {"address": address, "action": action, "changed": False}
        if action == "forget":
            adapter = str(props.get("Adapter", ""))
            validate_object_path(adapter, "/org/bluez")
            self.facade.call(BLUEZ_SERVICE, adapter, BLUEZ_ADAPTER, "RemoveDevice", path)
        else:
            self.facade.call(BLUEZ_SERVICE, path, BLUEZ_DEVICE, action.capitalize())
        return {"address": address, "action": action, "changed": True}


def _decode_device(value: Any) -> str:
    decoded = to_python(value)
    return decoded if isinstance(decoded, str) else str(decoded)


def _decode_mounts(value: Any) -> list[str]:
    return [str(to_python(item)) for item in (value or [])]


class StorageBackend:
    def __init__(self, facade: Facade):
        self.facade = facade

    def _objects(self) -> Mapping[str, Mapping[str, Mapping[str, Any]]]:
        try:
            return self.facade.managed_objects(UDISKS_SERVICE, UDISKS_ROOT)
        except Exception as exc:
            raise BridgeError("backend_unavailable", "udisks2 is unavailable") from exc

    def state(self) -> dict[str, Any]:
        objects = self._objects()
        drives: list[dict[str, Any]] = []
        blocks: list[dict[str, Any]] = []
        for path, interfaces in objects.items():
            if UDISKS_DRIVE in interfaces:
                props = interfaces[UDISKS_DRIVE]
                drives.append({
                    "path": str(path),
                    "vendor": str(props.get("Vendor", "")),
                    "model": str(props.get("Model", "")),
                    "serial": str(props.get("Serial", "")),
                    "connection_bus": str(props.get("ConnectionBus", "")),
                    "removable": bool(props.get("Removable", False)),
                    "ejectable": bool(props.get("Ejectable", False)),
                    "media_available": bool(props.get("MediaAvailable", False)),
                    "size": int(props.get("Size", 0)),
                })
            if UDISKS_BLOCK in interfaces:
                block = interfaces[UDISKS_BLOCK]
                filesystem = interfaces.get(UDISKS_FILESYSTEM, {})
                device = _decode_device(block.get("PreferredDevice", block.get("Device", "")))
                blocks.append({
                    "path": str(path),
                    "device": device,
                    "drive": str(block.get("Drive", "/")),
                    "id_usage": str(block.get("IdUsage", "")),
                    "id_type": str(block.get("IdType", "")),
                    "id_label": str(block.get("IdLabel", "")),
                    "id_uuid": str(block.get("IdUUID", "")),
                    "size": int(block.get("Size", 0)),
                    "read_only": bool(block.get("ReadOnly", False)),
                    "hint_system": bool(block.get("HintSystem", False)),
                    "hint_ignore": bool(block.get("HintIgnore", False)),
                    "mount_points": _decode_mounts(filesystem.get("MountPoints", [])),
                    "can_mount": UDISKS_FILESYSTEM in interfaces,
                    "format_confirmation": f"FORMAT {device}",
                })
        return {"drives": sorted(drives, key=lambda item: item["path"]),
                "blocks": sorted(blocks, key=lambda item: item["device"])}

    def _object(self, path: str, interface: str) -> tuple[Mapping[str, Any], Mapping[str, Mapping[str, Any]]]:
        path = validate_object_path(path, UDISKS_ROOT)
        interfaces = self._objects().get(path)
        if not interfaces or interface not in interfaces:
            raise BridgeError("not_found", "udisks object or interface was not found")
        return interfaces[interface], interfaces

    @staticmethod
    def _external_drive(drive: Mapping[str, Any]) -> bool:
        return bool(drive.get("Removable", False)) or str(drive.get("ConnectionBus", "")) in EXTERNAL_BUSES

    def _safe_block(self, block_path: str, interface: str) -> tuple[Mapping[str, Any], Mapping[str, Mapping[str, Any]]]:
        _requested, interfaces = self._object(block_path, interface)
        block = interfaces.get(UDISKS_BLOCK)
        if not block:
            raise BridgeError("not_found", "storage object is not a block device")
        mounts = _decode_mounts(interfaces.get(UDISKS_FILESYSTEM, {}).get("MountPoints", []))
        if bool(block.get("HintSystem", False)) or SYSTEM_MOUNTS.intersection(mounts):
            raise BridgeError("system_device", "refusing to modify a system volume")
        drive_path = str(block.get("Drive", "/"))
        drive = self._objects().get(drive_path, {}).get(UDISKS_DRIVE, {})
        if not self._external_drive(drive):
            raise BridgeError("not_removable", "Files device operations are restricted to external media")
        return block, interfaces

    def _safe_drive(self, drive_path: str) -> Mapping[str, Any]:
        drive, _interfaces = self._object(drive_path, UDISKS_DRIVE)
        if not self._external_drive(drive):
            raise BridgeError("not_removable", "Files device operations are restricted to external media")
        for interfaces in self._objects().values():
            block = interfaces.get(UDISKS_BLOCK)
            if not block or str(block.get("Drive", "/")) != drive_path:
                continue
            mounts = _decode_mounts(interfaces.get(UDISKS_FILESYSTEM, {}).get("MountPoints", []))
            if bool(block.get("HintSystem", False)) or SYSTEM_MOUNTS.intersection(mounts):
                raise BridgeError("system_device", "refusing to modify a drive containing a system volume")
        return drive

    def mount(self, block_path: str, read_only: bool, as_user: str) -> dict[str, Any]:
        self._safe_block(block_path, UDISKS_FILESYSTEM)
        options = {"as-user": as_user}
        if read_only:
            options["options"] = "ro"
        mount_point = self.facade.call(
            UDISKS_SERVICE, block_path, UDISKS_FILESYSTEM, "Mount", options
        )
        return {"block": block_path, "mount_point": str(mount_point),
                "read_only": bool(read_only), "mounted_for": as_user}

    def unmount(self, block_path: str, force: bool) -> dict[str, Any]:
        self._safe_block(block_path, UDISKS_FILESYSTEM)
        options = {"force": True} if force else {}
        self.facade.call(UDISKS_SERVICE, block_path, UDISKS_FILESYSTEM, "Unmount", options)
        return {"block": block_path, "force": bool(force)}

    def drive_action(self, drive_path: str, action: str) -> dict[str, Any]:
        if action not in {"eject", "poweroff"}:
            raise BridgeError("invalid_argument", "unsupported drive action")
        self._safe_drive(drive_path)
        method = "Eject" if action == "eject" else "PowerOff"
        self.facade.call(UDISKS_SERVICE, drive_path, UDISKS_DRIVE, method, {})
        return {"drive": drive_path, "action": action}

    def format(self, block_path: str, filesystem: str, label: str, confirmation: str) -> dict[str, Any]:
        block, _interfaces = self._safe_block(block_path, UDISKS_BLOCK)
        filesystem = validate_filesystem(filesystem)
        label = validate_label(label)
        device = _decode_device(block.get("PreferredDevice", block.get("Device", "")))
        if confirmation != f"FORMAT {device}":
            raise BridgeError("confirmation_required", "format confirmation does not match the target device")
        options: dict[str, Any] = {}
        if label:
            options["label"] = label
        self.facade.call(UDISKS_SERVICE, block_path, UDISKS_BLOCK, "Format", filesystem, options)
        return {"block": block_path, "device": device, "filesystem": filesystem, "label": label}


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner:
    def run(self, argv: Sequence[str], *, timeout: int = 120) -> CommandResult:
        if not argv or not os.path.isabs(argv[0]):
            raise BridgeError("internal_error", "commands must use an absolute executable path")
        try:
            completed = subprocess.run(
                list(argv), check=False, capture_output=True, text=True,
                timeout=timeout, env={"LANG": "C.UTF-8", "PATH": "/usr/bin:/bin"},
            )
        except subprocess.TimeoutExpired as exc:
            raise BridgeError("timeout", "host command timed out") from exc
        return CommandResult(completed.returncode, completed.stdout[-262144:], completed.stderr[-262144:])


class PacmanBackend:
    def __init__(self, runner: CommandRunner, pacman: str = "/usr/bin/pacman",
                 checkupdates: str = "/usr/bin/checkupdates",
                 recovery: str = "/usr/local/sbin/aurade-recovery"):
        self.runner = runner
        self.pacman = pacman
        self.checkupdates = checkupdates
        self.recovery = recovery

    @staticmethod
    def _packages(output: str) -> list[dict[str, str]]:
        packages = []
        for line in output.splitlines():
            fields = line.split()
            if len(fields) >= 2 and PACKAGE_RE.fullmatch(fields[0]):
                package = {"name": fields[0], "version": fields[1]}
                if len(fields) >= 4 and fields[2] == "->":
                    package["available_version"] = fields[3]
                packages.append(package)
        return packages

    def installed(self) -> dict[str, Any]:
        result = self.runner.run([self.pacman, "-Q"], timeout=120)
        if result.returncode != 0:
            raise BridgeError("pacman_failed", "could not list installed packages", {"stderr": result.stderr})
        return {"packages": self._packages(result.stdout)}

    def query(self, name: str) -> dict[str, Any]:
        name = validate_package(name)
        result = self.runner.run([self.pacman, "-Q", name], timeout=30)
        if result.returncode == 1:
            return {"installed": False, "name": name}
        if result.returncode != 0:
            raise BridgeError("pacman_failed", "package query failed", {"stderr": result.stderr})
        packages = self._packages(result.stdout)
        return {"installed": True, "package": packages[0] if packages else {"name": name}}

    def updates(self) -> dict[str, Any]:
        if os.path.exists(self.checkupdates):
            result = self.runner.run([self.checkupdates], timeout=300)
            if result.returncode not in (0, 2):
                raise BridgeError("pacman_failed", "update query failed", {"stderr": result.stderr})
            return {"packages": self._packages(result.stdout), "refreshed": True}
        result = self.runner.run([self.pacman, "-Qu"], timeout=120)
        if result.returncode not in (0, 1):
            raise BridgeError("pacman_failed", "update query failed", {"stderr": result.stderr})
        return {"packages": self._packages(result.stdout), "refreshed": False}

    def upgrade_command(self) -> list[str]:
        return [self.pacman, "-Syu", "--noconfirm"]

    def prepare_upgrade(self) -> dict[str, Any]:
        if not os.path.isfile(self.recovery):
            return {"rollback_available": False}
        result = self.runner.run([
            self.recovery, "snapshot", "--label", "pre-update", "--set-rollback"
        ], timeout=600)
        if result.returncode != 0:
            raise BridgeError(
                "snapshot_failed",
                "the pre-update rollback snapshot could not be created",
                {"stderr": result.stderr},
            )
        snapshot = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
        return {"rollback_available": True, "rollback_snapshot": snapshot}

    def uninstall_command(self, names: Iterable[str], remove_dependencies: bool) -> list[str]:
        packages = validate_packages(names)
        protected = sorted(
            name for name in packages
            if name in PROTECTED_PACKAGES
            or name.startswith(("aurade-", "chromiumos-", "linux-"))
        )
        if protected:
            raise BridgeError(
                "protected_package",
                "core system packages cannot be uninstalled through the desktop bridge",
                {"packages": protected},
            )
        mode = "-Rns" if remove_dependencies else "-R"
        return [self.pacman, mode, "--noconfirm", *packages]


class MimeLauncher:
    def __init__(self, which: Callable[[str], str | None] = shutil.which,
                 spawn: Callable[..., Any] = subprocess.Popen):
        self.which = which
        self.spawn = spawn

    def open(self, target: str, *, dry_run: bool = False) -> dict[str, Any]:
        target = normalize_open_target(target)
        gio = self.which("gio")
        xdg_open = self.which("xdg-open")
        if gio:
            argv = [gio, "open", target]
        elif xdg_open:
            argv = [xdg_open, target]
        else:
            raise BridgeError("backend_unavailable", "neither gio nor xdg-open is installed")
        if dry_run:
            return {"target": target, "command": argv, "dry_run": True}
        process = self.spawn(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True,
        )
        return {"target": target, "pid": int(process.pid), "launcher": os.path.basename(argv[0])}
