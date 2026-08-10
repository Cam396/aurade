#!/usr/bin/python
"""AuraDE system D-Bus bridge for standard Linux host services.

SPDX-License-Identifier: BSD-3-Clause
"""

from __future__ import annotations

import json
import logging
import os
import pwd
import shutil
import sys
import threading
import uuid
from typing import Any, Callable

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

sys.path.insert(0, "/usr/lib/aurade-host-bridge")

from aurade_host_bridge_core import (
    BLUEZ_SERVICE,
    BridgeError,
    BluetoothBackend,
    CommandRunner,
    PacmanBackend,
    StorageBackend,
    UDISKS_ROOT,
    UDISKS_SERVICE,
    response,
)


SERVICE = "org.aurade.HostBridge"
PATH = "/org/aurade/HostBridge"
INTERFACE = "org.aurade.HostBridge1"
POLKIT_SERVICE = "org.freedesktop.PolicyKit1"
POLKIT_PATH = "/org/freedesktop/PolicyKit1/Authority"
POLKIT_INTERFACE = "org.freedesktop.PolicyKit1.Authority"
OBJECT_MANAGER_INTERFACE = "org.freedesktop.DBus.ObjectManager"

ACTION_BLUETOOTH = "org.aurade.host-bridge.bluetooth-control"
ACTION_STORAGE = "org.aurade.host-bridge.storage-control"
ACTION_FORMAT = "org.aurade.host-bridge.storage-format"
ACTION_UPGRADE = "org.aurade.host-bridge.package-upgrade"
ACTION_UNINSTALL = "org.aurade.host-bridge.package-uninstall"

log = logging.getLogger("aurade-host-bridge")


def event_payload(source: str, kind: str, **fields: Any) -> str:
    """Build a stable event envelope for desktop consumers."""
    payload = {
        "schema": 1,
        "source": source,
        # AuraDE compatibility: Chromium 152 candidates used `domain` before
        # the bridge contract settled on `source`; keep the alias for upgrades.
        "domain": source,
        "kind": kind,
        **fields,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


class DBusFacade:
    """Minimal D-Bus surface consumed by the testable core backends."""

    def __init__(self, bus: dbus.SystemBus):
        self.bus = bus

    def managed_objects(self, service: str, root: str):
        obj = self.bus.get_object(service, root)
        return dbus.Interface(obj, OBJECT_MANAGER_INTERFACE).GetManagedObjects()

    def call(self, service: str, path: str, interface: str, method: str, *args: Any):
        obj = self.bus.get_object(service, path)
        return getattr(dbus.Interface(obj, interface), method)(*args)

    def set_property(self, service: str, path: str, interface: str, prop: str, value: Any) -> None:
        obj = self.bus.get_object(service, path)
        dbus.Interface(obj, dbus.PROPERTIES_IFACE).Set(interface, prop, value)


class Authorizer:
    def __init__(self, bus: dbus.SystemBus):
        self.bus = bus

    def require(self, sender: str, action: str) -> None:
        try:
            authority = dbus.Interface(
                self.bus.get_object(POLKIT_SERVICE, POLKIT_PATH), POLKIT_INTERFACE
            )
            authorized, _challenge, _details = authority.CheckAuthorization(
                ("system-bus-name", {"name": sender}), action, {}, 1, "", timeout=300
            )
        except dbus.DBusException as exc:
            raise BridgeError("authorization_unavailable", "polkit authorization failed") from exc
        if not authorized:
            raise BridgeError("not_authorized", "the requested operation was not authorized")


class HostBridge(dbus.service.Object):
    def __init__(self, bus: dbus.SystemBus):
        self.bus = bus
        self.facade = DBusFacade(bus)
        self.bluetooth = BluetoothBackend(self.facade)
        self.storage = StorageBackend(self.facade)
        self.runner = CommandRunner()
        self.pacman = PacmanBackend(self.runner)
        self.authorizer = Authorizer(bus)
        self.jobs: dict[str, dict[str, Any]] = {}
        self.jobs_lock = threading.Lock()
        self.pacman_job_running = False
        super().__init__(bus, PATH)
        self._subscribe_events()

    def _subscribe_events(self) -> None:
        for service in (BLUEZ_SERVICE, UDISKS_SERVICE):
            self.bus.add_signal_receiver(
                self._interfaces_added,
                signal_name="InterfacesAdded",
                dbus_interface=OBJECT_MANAGER_INTERFACE,
                bus_name=service,
                sender_keyword="sender",
            )
            self.bus.add_signal_receiver(
                self._interfaces_removed,
                signal_name="InterfacesRemoved",
                dbus_interface=OBJECT_MANAGER_INTERFACE,
                bus_name=service,
                sender_keyword="sender",
            )
            self.bus.add_signal_receiver(
                self._properties_changed,
                signal_name="PropertiesChanged",
                dbus_interface=dbus.PROPERTIES_IFACE,
                bus_name=service,
                path_keyword="path",
                sender_keyword="sender",
            )

    @staticmethod
    def _source(path: str) -> str | None:
        if str(path).startswith("/org/bluez/"):
            return "bluetooth"
        if str(path).startswith(UDISKS_ROOT + "/"):
            return "storage"
        return None

    def _emit(self, source: str, kind: str, **fields: Any) -> None:
        self.Event(event_payload(source, kind, **fields))

    def _interfaces_added(self, path, interfaces, sender=None) -> None:
        source = self._source(str(path))
        if source:
            self._emit(source, "interfaces-added", path=str(path), interfaces=sorted(map(str, interfaces.keys())))

    def _interfaces_removed(self, path, interfaces, sender=None) -> None:
        source = self._source(str(path))
        if source:
            self._emit(source, "interfaces-removed", path=str(path), interfaces=sorted(map(str, interfaces)))

    def _properties_changed(self, interface, changed, invalidated, path=None, sender=None) -> None:
        source = self._source(str(path))
        if source:
            self._emit(
                source,
                "properties-changed",
                path=str(path),
                interface=str(interface),
                changed=sorted(map(str, changed.keys())),
                invalidated=sorted(map(str, invalidated)),
            )

    def _invoke(self, operation: str, function: Callable[[], Any]) -> str:
        try:
            return response(operation, function())
        except BridgeError as exc:
            return response(operation, error=exc)
        except dbus.DBusException as exc:
            log.warning("%s failed: %s", operation, exc)
            error = BridgeError("backend_failed", "host service operation failed", {"dbus_error": exc.get_dbus_name()})
            return response(operation, error=error)
        except Exception:
            log.exception("unexpected failure in %s", operation)
            return response(operation, error=BridgeError("internal_error", "unexpected bridge failure"))

    def _authorized(self, sender: str, action: str, function: Callable[[], Any]) -> Any:
        self.authorizer.require(sender, action)
        return function()

    def _sender_uid(self, sender: str) -> int:
        try:
            return int(self.bus.get_unix_user(sender))
        except dbus.DBusException as exc:
            raise BridgeError("transport_error", "could not identify the D-Bus caller") from exc

    def _sender_username(self, sender: str) -> str:
        try:
            return pwd.getpwuid(self._sender_uid(sender)).pw_name
        except KeyError as exc:
            raise BridgeError("transport_error", "the D-Bus caller has no local user") from exc

    @dbus.service.signal(INTERFACE, signature="s")
    def Event(self, event_json: str) -> None:
        pass

    @dbus.service.method(INTERFACE, in_signature="", out_signature="s")
    def GetCapabilities(self) -> str:
        def capabilities() -> dict[str, Any]:
            daemon = dbus.Interface(
                self.bus.get_object(dbus.BUS_DAEMON_NAME, dbus.BUS_DAEMON_PATH),
                dbus.BUS_DAEMON_IFACE,
            )
            def owner(name: str) -> bool:
                try:
                    return bool(daemon.NameHasOwner(name))
                except dbus.DBusException:
                    return False
            return {
                "api": 1,
                "bluetooth": owner(BLUEZ_SERVICE),
                "storage": owner(UDISKS_SERVICE),
                "polkit": owner(POLKIT_SERVICE),
                "pacman": os.path.isfile("/usr/bin/pacman"),
                "checkupdates": os.path.isfile("/usr/bin/checkupdates"),
                "session_mime_bridge": shutil.which("gio") is not None or shutil.which("xdg-open") is not None,
            }
        return self._invoke("capabilities", capabilities)

    @dbus.service.method(INTERFACE, in_signature="", out_signature="s")
    def BluetoothGetState(self) -> str:
        return self._invoke("bluetooth.state", self.bluetooth.state)

    @dbus.service.method(INTERFACE, in_signature="b", out_signature="s", sender_keyword="sender")
    def BluetoothSetPowered(self, powered: bool, sender: str = "") -> str:
        return self._invoke("bluetooth.power", lambda: self._authorized(
            sender, ACTION_BLUETOOTH, lambda: self.bluetooth.set_powered(bool(powered))))

    @dbus.service.method(INTERFACE, in_signature="", out_signature="s", sender_keyword="sender")
    def BluetoothStartDiscovery(self, sender: str = "") -> str:
        return self._invoke("bluetooth.discovery.start", lambda: self._authorized(
            sender, ACTION_BLUETOOTH, lambda: self.bluetooth.discovery(True)))

    @dbus.service.method(INTERFACE, in_signature="", out_signature="s", sender_keyword="sender")
    def BluetoothStopDiscovery(self, sender: str = "") -> str:
        return self._invoke("bluetooth.discovery.stop", lambda: self._authorized(
            sender, ACTION_BLUETOOTH, lambda: self.bluetooth.discovery(False)))

    def _bluetooth_device(self, address: str, action: str, sender: str) -> str:
        return self._invoke(f"bluetooth.{action}", lambda: self._authorized(
            sender, ACTION_BLUETOOTH, lambda: self.bluetooth.device_action(address, action)))

    @dbus.service.method(INTERFACE, in_signature="s", out_signature="s", sender_keyword="sender")
    def BluetoothPair(self, address: str, sender: str = "") -> str:
        return self._bluetooth_device(address, "pair", sender)

    @dbus.service.method(INTERFACE, in_signature="s", out_signature="s", sender_keyword="sender")
    def BluetoothConnect(self, address: str, sender: str = "") -> str:
        return self._bluetooth_device(address, "connect", sender)

    @dbus.service.method(INTERFACE, in_signature="s", out_signature="s", sender_keyword="sender")
    def BluetoothDisconnect(self, address: str, sender: str = "") -> str:
        return self._bluetooth_device(address, "disconnect", sender)

    @dbus.service.method(INTERFACE, in_signature="s", out_signature="s", sender_keyword="sender")
    def BluetoothForget(self, address: str, sender: str = "") -> str:
        return self._bluetooth_device(address, "forget", sender)

    @dbus.service.method(INTERFACE, in_signature="", out_signature="s")
    def StorageList(self) -> str:
        return self._invoke("storage.list", self.storage.state)

    @dbus.service.method(INTERFACE, in_signature="ob", out_signature="s", sender_keyword="sender")
    def StorageMount(self, block_path: str, read_only: bool, sender: str = "") -> str:
        return self._invoke("storage.mount", lambda: self._authorized(
            sender, ACTION_STORAGE,
            lambda: self.storage.mount(str(block_path), bool(read_only),
                                       self._sender_username(sender))))

    @dbus.service.method(INTERFACE, in_signature="ob", out_signature="s", sender_keyword="sender")
    def StorageUnmount(self, block_path: str, force: bool, sender: str = "") -> str:
        return self._invoke("storage.unmount", lambda: self._authorized(
            sender, ACTION_STORAGE, lambda: self.storage.unmount(str(block_path), bool(force))))

    @dbus.service.method(INTERFACE, in_signature="o", out_signature="s", sender_keyword="sender")
    def StorageEject(self, drive_path: str, sender: str = "") -> str:
        return self._invoke("storage.eject", lambda: self._authorized(
            sender, ACTION_STORAGE, lambda: self.storage.drive_action(str(drive_path), "eject")))

    @dbus.service.method(INTERFACE, in_signature="o", out_signature="s", sender_keyword="sender")
    def StoragePowerOff(self, drive_path: str, sender: str = "") -> str:
        return self._invoke("storage.poweroff", lambda: self._authorized(
            sender, ACTION_STORAGE, lambda: self.storage.drive_action(str(drive_path), "poweroff")))

    @dbus.service.method(INTERFACE, in_signature="osss", out_signature="s", sender_keyword="sender")
    def StorageFormat(self, block_path: str, filesystem: str, label: str,
                      confirmation: str, sender: str = "") -> str:
        return self._invoke("storage.format", lambda: self._authorized(
            sender, ACTION_FORMAT, lambda: self.storage.format(
                str(block_path), filesystem, label, confirmation)))

    @dbus.service.method(INTERFACE, in_signature="", out_signature="s")
    def PacmanListInstalled(self) -> str:
        return self._invoke("pacman.installed", self.pacman.installed)

    @dbus.service.method(INTERFACE, in_signature="s", out_signature="s")
    def PacmanQuery(self, name: str) -> str:
        return self._invoke("pacman.query", lambda: self.pacman.query(name))

    @dbus.service.method(INTERFACE, in_signature="", out_signature="s")
    def PacmanListUpdates(self) -> str:
        return self._invoke("pacman.updates", self.pacman.updates)

    def _start_job(self, sender: str, operation: str, argv: list[str]) -> dict[str, Any]:
        owner_uid = self._sender_uid(sender)
        with self.jobs_lock:
            if self.pacman_job_running:
                raise BridgeError("busy", "another package operation is already running")
            self.pacman_job_running = True
            job_id = uuid.uuid4().hex
            self.jobs[job_id] = {
                "id": job_id,
                "owner_uid": owner_uid,
                "operation": operation,
                "state": "running",
                "started_ms": int(GLib.get_real_time() / 1000),
            }
            while len(self.jobs) > 32:
                oldest = next(iter(self.jobs))
                if oldest != job_id:
                    self.jobs.pop(oldest)
                else:
                    break
        threading.Thread(
            target=self._run_job, args=(job_id, operation, argv), daemon=True,
            name=f"aurade-{operation}-{job_id[:8]}",
        ).start()
        return {"job_id": job_id, "state": "running", "operation": operation}

    def _run_job(self, job_id: str, operation: str, argv: list[str]) -> None:
        try:
            rollback = self.pacman.prepare_upgrade() if operation == "upgrade" else {}
            result = self.runner.run(argv, timeout=7200)
            update = {
                "state": "succeeded" if result.returncode == 0 else "failed",
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                **rollback,
            }
        except BridgeError as exc:
            update = {"state": "failed", "error": {"code": exc.code, "message": exc.message}}
        except Exception:
            log.exception("package job %s failed", job_id)
            update = {"state": "failed", "error": {"code": "internal_error", "message": "package job failed"}}
        GLib.idle_add(self._finish_job, job_id, update)

    def _finish_job(self, job_id: str, update: dict[str, Any]) -> bool:
        with self.jobs_lock:
            job = self.jobs.get(job_id)
            if job is not None:
                job.update(update)
                job["finished_ms"] = int(GLib.get_real_time() / 1000)
            self.pacman_job_running = False
        if job is not None:
            self._emit("pacman", "job-completed", job_id=job_id,
                       operation=job["operation"], state=job["state"])
        return GLib.SOURCE_REMOVE

    @dbus.service.method(INTERFACE, in_signature="", out_signature="s", sender_keyword="sender")
    def PacmanUpgrade(self, sender: str = "") -> str:
        return self._invoke("pacman.upgrade", lambda: self._authorized(
            sender, ACTION_UPGRADE,
            lambda: self._start_job(sender, "upgrade", self.pacman.upgrade_command())))

    @dbus.service.method(INTERFACE, in_signature="asb", out_signature="s", sender_keyword="sender")
    def PacmanUninstall(self, packages, remove_dependencies: bool, sender: str = "") -> str:
        return self._invoke("pacman.uninstall", lambda: self._authorized(
            sender, ACTION_UNINSTALL,
            lambda: self._start_job(sender, "uninstall", self.pacman.uninstall_command(
                list(map(str, packages)), bool(remove_dependencies)))))

    @dbus.service.method(INTERFACE, in_signature="s", out_signature="s", sender_keyword="sender")
    def JobGet(self, job_id: str, sender: str = "") -> str:
        def get_job() -> dict[str, Any]:
            if not isinstance(job_id, str) or len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
                raise BridgeError("invalid_argument", "invalid job identifier")
            with self.jobs_lock:
                job = dict(self.jobs.get(job_id, {}))
            if not job:
                raise BridgeError("not_found", "job was not found")
            caller_uid = self._sender_uid(sender)
            if caller_uid not in (job["owner_uid"], 0):
                raise BridgeError("not_authorized", "job belongs to another caller")
            job.pop("owner_uid", None)
            return job
        return self._invoke("job.get", get_job)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    bus_name = dbus.service.BusName(SERVICE, bus=bus, do_not_queue=True)
    bridge = HostBridge(bus)
    log.info("providing %s", SERVICE)
    GLib.MainLoop().run()
    del bridge
    del bus_name
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
