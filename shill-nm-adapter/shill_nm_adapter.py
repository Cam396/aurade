#!/usr/bin/python
"""shill-nm-adapter — Bridge between ChromeOS Shill DBus and NetworkManager.

Provides the ``org.chromium.flimflam`` DBus interface that ChromeOS Ash
expects, translating queries and signals to/from NetworkManager's own DBus
API.  No patches to Chromium are needed; the adapter is a standalone system
DBus daemon launched by systemd.

SPDX-License-Identifier: BSD-3-Clause
"""

from __future__ import annotations

import contextlib
import fcntl
import logging
import os
import socket
import struct
import sys
import uuid

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

# ---------------------------------------------------------------------------
# Shill DBus constants – mirrors third_party/cros_system_api/dbus/shill/
# ---------------------------------------------------------------------------

SHILL_SERVICE = "org.chromium.flimflam"
SHILL_MANAGER_PATH = "/"  # crosbug.com/20135
SHILL_MANAGER_IFACE = "org.chromium.flimflam.Manager"
SHILL_SERVICE_IFACE = "org.chromium.flimflam.Service"
SHILL_DEVICE_IFACE = "org.chromium.flimflam.Device"
SHILL_IPCONFIG_IFACE = "org.chromium.flimflam.IPConfig"
SHILL_PROFILE_IFACE = "org.chromium.flimflam.Profile"

NM_SERVICE = "org.freedesktop.NetworkManager"
NM_PATH = "/org/freedesktop/NetworkManager"
NM_IFACE = "org.freedesktop.NetworkManager"
NM_DEVICE_IFACE = "org.freedesktop.NetworkManager.Device"
NM_IP4CONFIG_IFACE = "org.freedesktop.NetworkManager.IP4Config"
NM_IP6CONFIG_IFACE = "org.freedesktop.NetworkManager.IP6Config"
NM_ACTIVE_CONNECTION = "org.freedesktop.NetworkManager.Connection.Active"
NM_STATE_CONNECTED_GLOBAL = 70
NM_DEVICE_STATE_ACTIVATED = 100
NM_DEVICE_TYPE_ETHERNET = 1
NM_DEVICE_TYPE_WIFI = 2

# Property names
PROP_DEVICES = "Devices"
PROP_SERVICES = "Services"
PROP_SERVICE_COMPLETE_LIST = "ServiceCompleteList"
PROP_ENABLED_TECHNOLOGIES = "EnabledTechnologies"
PROP_PROFILES = "Profiles"
PROP_AVAILABLE_TECHNOLOGIES = "AvailableTechnologies"
PROP_CONNECTED_TECHNOLOGIES = "ConnectedTechnologies"
PROP_DEFAULT_TECHNOLOGY = "DefaultTechnology"
PROP_CHECK_PORTAL_LIST = "CheckPortalList"
PROP_ARP_GATEWAY = "ArpGateway"
PROP_CONNECTABLE = "Connectable"
PROP_DEVICE = "Device"
PROP_GUID = "GUID"
PROP_IPCONFIG = "IPConfig"
PROP_IPCONFIGS = "IPConfigs"
PROP_NAME = "Name"
PROP_PROFILE = "Profile"
PROP_STATE = "State"
PROP_TYPE = "Type"
PROP_STRENGTH = "Strength"
PROP_AUTO_CONNECT = "AutoConnect"
PROP_VISIBLE = "Visible"
PROP_INTERFACE = "Interface"
PROP_ADDRESS = "Address"
PROP_METHOD = "Method"
PROP_POWER_SAVE = "PowerSave"
PROP_NAME_SERVERS = "NameServers"

SHILL_STATE_ONLINE = "online"
SHILL_STATE_READY = "ready"
SHILL_STATE_IDLE = "idle"
SHILL_STATE_ASSOCIATION = "association"
SHILL_STATE_CONFIGURATION = "configuration"
SHILL_STATE_NO_CONNECTIVITY = "no-connectivity"
SHILL_STATE_PORTAL = "portal"

SHILL_TYPE_ETHERNET = "ethernet"
SHILL_TYPE_WIFI = "wifi"
SHILL_TYPE_CELLULAR = "cellular"
SHILL_TYPE_VPN = "vpn"

SHALLOW_PROFILE_PATH = "/profile/default"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("shill-nm-adapter")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_mac(iface: str) -> str:
    """Return the MAC address for *iface* or a fallback."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        info = fcntl.ioctl(
            s.fileno(), 0x8927, struct.pack("256s", iface[:15].encode())
        )
        return ":".join(f"{b:02x}" for b in info[18:24])
    except (OSError, struct.error):
        return "00:00:00:00:00:00"


def _generate_guid() -> str:
    return uuid.uuid4().hex  # no hyphens — DBus object paths don't allow them


# ---------------------------------------------------------------------------
# Bus name ownership helper
# ---------------------------------------------------------------------------

class ShillDBus:
    """Manages the ``org.chromium.flimflam`` bus name and known objects."""

    def __init__(self, bus: dbus.Bus):
        self.bus = bus
        self._manager: "Manager" = None
        self._services: dict[str, "Service"] = {}
        self._devices: dict[str, "Device"] = {}
        self._ipconfigs: dict[str, "IPConfig"] = {}
        self._bus_name: dbus.service.BusName | None = None

    @property
    def manager(self) -> "Manager":
        return self._manager

    @manager.setter
    def manager(self, m: "Manager") -> None:
        self._manager = m

    @property
    def services(self) -> dict[str, "Service"]:
        return self._services

    @property
    def devices(self) -> dict[str, "Device"]:
        return self._devices

    @property
    def ipconfigs(self) -> dict[str, "IPConfig"]:
        return self._ipconfigs

    def acquire_name(self) -> None:
        """Request ownership of ``org.chromium.flimflam`` on the system bus."""
        try:
            self._bus_name = dbus.service.BusName(
                SHILL_SERVICE, bus=self.bus, allow_replacement=True, replace_existing=True
            )
            log.info("Acquired bus name %s", SHILL_SERVICE)
        except dbus.exceptions.DBusException as exc:
            log.fatal("Cannot acquire bus name %s: %s", SHILL_SERVICE, exc)
            sys.exit(1)

    def release_name(self) -> None:
        if self._bus_name is not None:
            self._bus_name = None
            try:
                self.bus.release_name(SHILL_SERVICE)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Base – Shared convenience for all Shill objects
# ---------------------------------------------------------------------------

class ShillObject(dbus.service.Object):
    """Mixin that provides ``org.freedesktop.DBus.Properties`` glue and
    the ``PropertyChanged`` signal helpers every Shill object needs."""

    def __init__(self, conn: dbus.bus.BusConnection, object_path: str):
        self._props: dict[str, dbus.Variant] = {}
        super().__init__(conn, object_path)

    # ---- org.freedesktop.DBus.Properties ----

    @dbus.service.method(
        dbus.PROPERTIES_IFACE,
        in_signature="ss",
        out_signature="v",
    )
    def Get(self, interface: str, prop: str) -> dbus.Variant:
        if interface != self._interface_name:
            raise dbus.exceptions.DBusException(
                "org.freedesktop.DBus.Error.InvalidArgs",
                f"No such interface: {interface}",
            )
        if prop not in self._props:
            raise dbus.exceptions.DBusException(
                "org.freedesktop.DBus.Error.InvalidArgs",
                f"No such property: {prop}",
            )
        return self._props[prop]

    @dbus.service.method(
        dbus.PROPERTIES_IFACE,
        in_signature="s",
        out_signature="a{sv}",
    )
    def GetAll(self, interface: str) -> dict:
        if interface == self._interface_name:
            return dict(self._props)
        raise dbus.exceptions.DBusException(
            "org.freedesktop.DBus.Error.InvalidArgs",
            f"No such interface: {interface}",
        )

    @dbus.service.method(
        dbus.PROPERTIES_IFACE,
        in_signature="ssv",
        out_signature="",
    )
    def Set(self, interface: str, prop: str, value: dbus.Variant) -> None:
        if interface != self._interface_name:
            raise dbus.exceptions.DBusException(
                "org.freedesktop.DBus.Error.InvalidArgs",
                f"No such interface: {interface}",
            )
        self._set_property(prop, value)

    # --- Shill PropertyChanged signal ---

    @dbus.service.signal(dbus.PROPERTIES_IFACE, signature="sa{sv}as")
    def PropertiesChanged(
        self, interface: str, changed: dict, invalidated: list
    ) -> None:
        pass  # signal body is empty; arguments carry the payload

    # -- internal helpers --

    def _set_property(self, name: str, value) -> None:
        old = self._props.get(name)
        if old == value:
            return
        self._props[name] = value
        # Emit standard PropertiesChanged signal
        self.PropertiesChanged(
            self._interface_name,
            {name: value},
            [],
        )

    def _set_properties(self, props: dict) -> None:
        changed = {}
        for k, v in props.items():
            if self._props.get(k) != v:
                self._props[k] = v
                changed[k] = v
        if changed:
            self.PropertiesChanged(self._interface_name, changed, [])

    def _export(self) -> None:
        """Idempotent — dbus.service.Object auto-exports on construction.

        Override if subclass needs deferred export.
        """


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class Manager(ShillObject):
    """Implements ``org.chromium.flimflam.Manager``."""

    def __init__(self, conn: dbus.bus.BusConnection, path: str, shill: ShillDBus):
        self._interface_name = SHILL_MANAGER_IFACE
        self._shill = shill
        self._nm_iface: dbus.Interface | None = None
        self._nm_props: dbus.Interface | None = None
        super().__init__(conn, path)
        self._init_properties()

    def _init_properties(self) -> None:
        self._props = {
            PROP_DEVICES: dbus.Array([], signature="o"),
            PROP_SERVICES: dbus.Array([], signature="o"),
            PROP_SERVICE_COMPLETE_LIST: dbus.Array([], signature="o"),
            PROP_ENABLED_TECHNOLOGIES: dbus.Array(
                [SHILL_TYPE_ETHERNET, SHILL_TYPE_WIFI], signature="s"
            ),
            PROP_PROFILES: dbus.Array(
                [dbus.ObjectPath(SHALLOW_PROFILE_PATH)], signature="o"
            ),
            PROP_AVAILABLE_TECHNOLOGIES: dbus.Array(
                [SHILL_TYPE_ETHERNET], signature="s"
            ),
            PROP_CONNECTED_TECHNOLOGIES: dbus.Array([], signature="s"),
            PROP_DEFAULT_TECHNOLOGY: SHILL_TYPE_ETHERNET,
            PROP_CHECK_PORTAL_LIST: SHILL_TYPE_ETHERNET,
            PROP_ARP_GATEWAY: dbus.Boolean(False),
        }

    def set_nm_proxy(self, nm_iface: dbus.Interface, nm_props: dbus.Interface) -> None:
        self._nm_iface = nm_iface
        self._nm_props = nm_props
        # Trigger an initial state refresh
        self._refresh_technologies()

    def _refresh_technologies(self) -> None:
        """Update connected/available technologies from NM state."""
        try:
            nm_devices = self._nm_iface.GetDevices() if self._nm_iface else []
        except Exception:
            nm_devices = []

        connected: list[str] = []
        available: list[str] = []

        for dev_path in nm_devices:
            try:
                dev_obj = self._shill.bus.get_object(NM_SERVICE, dev_path)
                dev_props = dbus.Interface(dev_obj, dbus.PROPERTIES_IFACE)
                dtype = dev_props.Get(NM_DEVICE_IFACE, "DeviceType")
                state = dev_props.Get(NM_DEVICE_IFACE, "State")
                iface = dev_props.Get(NM_DEVICE_IFACE, "Interface")
            except Exception:
                continue

            if dtype == NM_DEVICE_TYPE_ETHERNET:
                available.append(SHILL_TYPE_ETHERNET)
                if state >= NM_DEVICE_STATE_ACTIVATED:
                    connected.append(SHILL_TYPE_ETHERNET)
            elif dtype == NM_DEVICE_TYPE_WIFI:
                if SHILL_TYPE_WIFI not in available:
                    available.append(SHILL_TYPE_WIFI)

        self._set_properties({
            PROP_AVAILABLE_TECHNOLOGIES: dbus.Array(available, signature="s"),
            PROP_CONNECTED_TECHNOLOGIES: dbus.Array(connected, signature="s"),
            PROP_DEFAULT_TECHNOLOGY: connected[0] if connected else SHILL_TYPE_ETHERNET,
        })

    # -- Manager methods --

    @dbus.service.method(SHILL_MANAGER_IFACE, out_signature="a{sv}")
    def GetProperties(self) -> dict:
        return dict(self._props)

    @dbus.service.method(SHILL_MANAGER_IFACE, in_signature="a{sv}", out_signature="o")
    def GetService(self, args: dict) -> dbus.ObjectPath:
        """Find or create a service matching *args*."""
        for path, svc in self._shill.services.items():
            props = svc._props
            if args.get(PROP_TYPE, props.get(PROP_TYPE)) == props.get(PROP_TYPE):
                return dbus.ObjectPath(path)
        # No match — create a new one
        return self._create_service(args)

    @dbus.service.method(SHILL_MANAGER_IFACE, in_signature="a{sv}", out_signature="o")
    def ConfigureService(self, args: dict) -> dbus.ObjectPath:
        return self._create_service(args)

    @dbus.service.method(SHILL_MANAGER_IFACE, in_signature="oa{sv}", out_signature="o")
    def ConfigureServiceForProfile(self, profile_path: dbus.ObjectPath, args: dict) -> dbus.ObjectPath:
        return self._create_service(args)

    @dbus.service.method(SHILL_MANAGER_IFACE, in_signature="", out_signature="")
    def ScanAndConnectToBestServices(self) -> None:
        log.info("ScanAndConnectToBestServices called (no-op)")

    @dbus.service.method(SHILL_MANAGER_IFACE, in_signature="s", out_signature="")
    def RequestScan(self, type_str: str) -> None:
        log.info("RequestScan(%s) called (no-op)", type_str)

    @dbus.service.method(SHILL_MANAGER_IFACE, in_signature="s", out_signature="")
    def EnableTechnology(self, type_str: str) -> None:
        log.info("EnableTechnology(%s)", type_str)

    @dbus.service.method(SHILL_MANAGER_IFACE, in_signature="s", out_signature="")
    def DisableTechnology(self, type_str: str) -> None:
        log.info("DisableTechnology(%s) — ignored", type_str)

    @dbus.service.method(SHILL_MANAGER_IFACE, in_signature="a{sv}", out_signature="o")
    def FindMatchingService(self, args: dict) -> dbus.ObjectPath:
        for path, svc in self._shill.services.items():
            for k, v in args.items():
                if svc._props.get(k) != v:
                    break
            else:
                return dbus.ObjectPath(path)
        raise dbus.exceptions.DBusException(
            "org.chromium.flimflam.Error.NotFound",
            "No matching service found",
        )

    # -- internal --

    def _create_service(self, props: dict) -> dbus.ObjectPath:
        svc_type = props.get(PROP_TYPE, SHILL_TYPE_ETHERNET)
        iface_name = props.get(PROP_NAME, "eth0")
        guid = props.get(PROP_GUID, _generate_guid())
        path = f"/org/chromium/flimflam/Service/{guid}"
        if path not in self._shill.services:
            svc = Service(
                self._shill.bus.get_connection(),  # type: ignore[arg-type]
                path,
                self._shill,
                svc_type,
                iface_name,
                guid,
            )
            self._shill.services[path] = svc
            # Update manager lists
            svc_paths = list(self._shill.services.keys())
            self._set_properties({
                PROP_SERVICES: dbus.Array([dbus.ObjectPath(p) for p in svc_paths], signature="o"),
                PROP_SERVICE_COMPLETE_LIST: dbus.Array([dbus.ObjectPath(p) for p in svc_paths], signature="o"),
            })
            log.info("Created service %s (%s)", path, iface_name)
        return dbus.ObjectPath(path)


# ---------------------------------------------------------------------------
# Service (aka network connection)
# ---------------------------------------------------------------------------

class Service(ShillObject):
    """Implements ``org.chromium.flimflam.Service``."""

    def __init__(
        self,
        conn: dbus.bus.BusConnection,
        path: str,
        shill: ShillDBus,
        svc_type: str,
        iface_name: str,
        guid: str,
    ):
        self._interface_name = SHILL_SERVICE_IFACE
        self._shill = shill
        self._svc_type = svc_type
        self._iface_name = iface_name
        self._guid = guid
        super().__init__(conn, path)
        self._props = {
            PROP_TYPE: svc_type,
            PROP_GUID: guid,
            PROP_NAME: iface_name,
            PROP_STATE: SHILL_STATE_ONLINE,
            PROP_CONNECTABLE: dbus.Boolean(True),
            PROP_PROFILE: dbus.ObjectPath(SHALLOW_PROFILE_PATH),
            PROP_DEVICE: dbus.ObjectPath(f"/org/chromium/flimflam/Device/{iface_name}"),
            PROP_STRENGTH: dbus.Int32(0),
            PROP_AUTO_CONNECT: dbus.Boolean(True),
            PROP_VISIBLE: dbus.Boolean(True),
        }

    # -- Service methods --

    @dbus.service.method(SHILL_SERVICE_IFACE, out_signature="a{sv}")
    def GetProperties(self) -> dict:
        return dict(self._props)

    @dbus.service.method(SHILL_SERVICE_IFACE, in_signature="a{sv}", out_signature="")
    def SetProperties(self, props: dict) -> None:
        self._set_properties(props)

    @dbus.service.method(SHILL_SERVICE_IFACE, out_signature="")
    def Connect(self) -> None:
        log.info("Service.Connect() called for %s (no-op)", self._props.get(PROP_GUID))

    @dbus.service.method(SHILL_SERVICE_IFACE, out_signature="")
    def Disconnect(self) -> None:
        log.info("Service.Disconnect() called for %s (no-op)", self._props.get(PROP_GUID))

    @dbus.service.method(SHILL_SERVICE_IFACE, out_signature="")
    def Remove(self) -> None:
        log.info("Service.Remove() called for %s (no-op)", self._props.get(PROP_GUID))

    # -- public mutators --

    def set_state(self, state: str) -> None:
        self._set_property(PROP_STATE, state)


# ---------------------------------------------------------------------------
# Device
# ---------------------------------------------------------------------------

class Device(ShillObject):
    """Implements ``org.chromium.flimflam.Device``."""

    def __init__(
        self,
        conn: dbus.bus.BusConnection,
        path: str,
        shill: ShillDBus,
        iface_name: str,
        dev_type: str,
        mac: str,
    ):
        self._interface_name = SHILL_DEVICE_IFACE
        self._shill = shill
        self._ipconfig_path = f"/org/chromium/flimflam/IPConfig/{iface_name}"
        super().__init__(conn, path)
        self._props = {
            PROP_TYPE: dev_type,
            PROP_NAME: iface_name,
            PROP_INTERFACE: iface_name,
            PROP_ADDRESS: mac,
            PROP_IPCONFIGS: dbus.Array([dbus.ObjectPath(self._ipconfig_path)], signature="o"),
            PROP_POWER_SAVE: dbus.Boolean(False),
        }
        # Ensure IPConfig object exists
        if self._ipconfig_path not in shill.ipconfigs:
            ipcfg = IPConfig(conn, self._ipconfig_path, iface_name)
            shill.ipconfigs[self._ipconfig_path] = ipcfg

    # -- Device methods --

    @dbus.service.method(SHILL_DEVICE_IFACE, out_signature="a{sv}")
    def GetProperties(self) -> dict:
        return dict(self._props)

    @dbus.service.method(SHILL_DEVICE_IFACE, in_signature="sv", out_signature="")
    def SetProperty(self, name: str, value: dbus.Variant) -> None:
        self._set_property(name, value)


# ---------------------------------------------------------------------------
# IPConfig
# ---------------------------------------------------------------------------

class IPConfig(ShillObject):
    """Implements ``org.chromium.flimflam.IPConfig``."""

    def __init__(self, conn: dbus.bus.BusConnection, path: str, iface_name: str):
        self._interface_name = SHILL_IPCONFIG_IFACE
        super().__init__(conn, path)
        self._props = {
            PROP_ADDRESS: "0.0.0.0",
            PROP_METHOD: "ipv4",
            PROP_NAME_SERVERS: dbus.Array([], signature="s"),
        }

    @dbus.service.method(SHILL_IPCONFIG_IFACE, out_signature="a{sv}")
    def GetProperties(self) -> dict:
        return dict(self._props)


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

class Profile(ShillObject):
    """Implements ``org.chromium.flimflam.Profile`` (stub)."""

    def __init__(self, conn: dbus.bus.BusConnection, path: str):
        self._interface_name = SHILL_PROFILE_IFACE
        self._props = {
            PROP_NAME: "default",
        }
        super().__init__(conn, path)

    @dbus.service.method(SHILL_PROFILE_IFACE, out_signature="a{sv}")
    def GetProperties(self) -> dict:
        return dict(self._props)

    @dbus.service.method(SHILL_PROFILE_IFACE, in_signature="a{sv}", out_signature="")
    def SetProperties(self, props: dict) -> None:
        self._set_properties(props)

    @dbus.service.method(SHILL_PROFILE_IFACE, out_signature="ao")
    def GetServices(self) -> list:
        return [
            dbus.ObjectPath(p)
            for p in self._shill.services.keys()
        ]

    @dbus.service.method(SHILL_PROFILE_IFACE, in_signature="s", out_signature="")
    def DeleteEntry(self, entry_path: str) -> None:
        log.info("Profile.DeleteEntry(%s) (no-op)", entry_path)


# ---------------------------------------------------------------------------
# NM monitor – watches NetworkManager for state changes
# ---------------------------------------------------------------------------

class NetworkManagerMonitor:
    """Subscribes to NM signals and updates the Shill object tree."""

    def __init__(self, bus: dbus.Bus, shill: ShillDBus):
        self._bus = bus
        self._shill = shill
        self._nm_obj = bus.get_object(NM_SERVICE, NM_PATH)
        self._nm_iface = dbus.Interface(self._nm_obj, NM_IFACE)
        self._nm_props = dbus.Interface(self._nm_obj, dbus.PROPERTIES_IFACE)

        # Current mapping of NM device path → Shill service path
        self._nm_devices: dict[str, str] = {}

    def start(self) -> None:
        self._shill.manager.set_nm_proxy(self._nm_iface, self._nm_props)
        # Sync initial state
        self._sync_devices()
        # Subscribe to NM signals
        self._nm_obj.connect_to_signal(
            "DeviceAdded", self._on_device_added, dbus_interface=NM_IFACE
        )
        self._nm_obj.connect_to_signal(
            "DeviceRemoved", self._on_device_removed, dbus_interface=NM_IFACE
        )
        # Also watch NMState (connectivity changes)
        self._nm_props.connect_to_signal(
            "PropertiesChanged", self._on_nm_properties_changed
        )
        # Watch for device property changes (state, etc.)
        dev_paths = self._nm_devices.copy()
        for dev_path in dev_paths:
            self._watch_device(dev_path)

        log.info(
            "NM monitor started — %d device(s) tracked",
            len(self._nm_devices),
        )
        self._shill.manager._refresh_technologies()

    def _watch_device(self, dev_path: str) -> None:
        """Subscribe to property changes on a specific NM device."""
        try:
            dev_obj = self._bus.get_object(NM_SERVICE, dev_path)
            dev_props = dbus.Interface(dev_obj, dbus.PROPERTIES_IFACE)
            dev_props.connect_to_signal(
                "PropertiesChanged",
                lambda iface, changed, invalid: self._on_device_props_changed(
                    dev_path, changed
                ),
            )
        except Exception as exc:
            log.warning("Cannot watch device %s: %s", dev_path, exc)

    def _sync_devices(self) -> None:
        """Build the initial device→service mapping from NM state."""
        try:
            nm_dev_paths = self._nm_iface.GetDevices()
        except Exception:
            nm_dev_paths = []

        for dev_path in nm_dev_paths:
            self._add_device(dev_path)

    def _add_device(self, dev_path: str) -> None:
        """Create Shill Device+Service for an NM device."""
        try:
            dev_obj = self._bus.get_object(NM_SERVICE, dev_path)
            dev_props = dbus.Interface(dev_obj, dbus.PROPERTIES_IFACE)
            dtype = dev_props.Get(NM_DEVICE_IFACE, "DeviceType")
            state = dev_props.Get(NM_DEVICE_IFACE, "State")
            iface = dev_props.Get(NM_DEVICE_IFACE, "Interface")
            mac = dev_props.Get(NM_DEVICE_IFACE, "HwAddress")
        except Exception as exc:
            log.warning("Cannot read NM device %s: %s", dev_path, exc)
            return

        if dtype == NM_DEVICE_TYPE_ETHERNET:
            shill_type = SHILL_TYPE_ETHERNET
        elif dtype == NM_DEVICE_TYPE_WIFI:
            shill_type = SHILL_TYPE_WIFI
        else:
            return  # Skip cellular, VPN, etc.

        # Create Shill device
        dev_shill_path = f"/org/chromium/flimflam/Device/{iface}"
        if dev_shill_path not in self._shill.devices:
            dev = Device(
                self._bus.get_connection(),  # type: ignore[arg-type]
                dev_shill_path,
                self._shill,
                iface,
                shill_type,
                mac,
            )
            self._shill.devices[dev_shill_path] = dev
            log.info("Added device %s (%s)", dev_shill_path, iface)

            # Update manager Devices list
            manager = self._shill.manager
            manager._set_property(
                PROP_DEVICES,
                dbus.Array(
                    [dbus.ObjectPath(p) for p in self._shill.devices.keys()],
                    signature="o",
                ),
            )
        self._watch_device(dev_path)

        # Create Shill service for this device
        nm_state = self._nm_to_shill_state(state)
        guid = _generate_guid()
        svc_path = f"/org/chromium/flimflam/Service/{guid}"
        if svc_path not in self._shill.services:
            svc = Service(
                self._bus.get_connection(),  # type: ignore[arg-type]
                svc_path,
                self._shill,
                shill_type,
                iface,
                guid,
            )
            svc.set_state(nm_state)
            self._shill.services[svc_path] = svc
            # Update manager service lists
            manager = self._shill.manager
            service_paths = list(self._shill.services.keys())
            manager._set_properties({
                PROP_SERVICES: dbus.Array(
                    [dbus.ObjectPath(p) for p in service_paths], signature="o"
                ),
                PROP_SERVICE_COMPLETE_LIST: dbus.Array(
                    [dbus.ObjectPath(p) for p in service_paths], signature="o"
                ),
            })
            log.info(
                "Added service %s (%s, state=%s)", svc_path, iface, nm_state
            )

        self._nm_devices[dev_path] = svc_path

    def _remove_device(self, dev_path: str) -> None:
        svc_path = self._nm_devices.pop(dev_path, None)
        if svc_path and svc_path in self._shill.services:
            del self._shill.services[svc_path]
            log.info("Removed service %s", svc_path)
            manager = self._shill.manager
            service_paths = list(self._shill.services.keys())
            manager._set_properties({
                PROP_SERVICES: dbus.Array(
                    [dbus.ObjectPath(p) for p in service_paths], signature="o"
                ),
                PROP_SERVICE_COMPLETE_LIST: dbus.Array(
                    [dbus.ObjectPath(p) for p in service_paths], signature="o"
                ),
            })

    def _on_device_added(self, dev_path: str) -> None:
        log.info("NM device added: %s", dev_path)
        self._add_device(dev_path)
        self._shill.manager._refresh_technologies()

    def _on_device_removed(self, dev_path: str) -> None:
        log.info("NM device removed: %s", dev_path)
        self._remove_device(dev_path)
        self._shill.manager._refresh_technologies()

    def _on_device_props_changed(self, dev_path: str, changed: dict) -> None:
        if "State" in changed:
            new_state = changed["State"]
            shill_state = self._nm_to_shill_state(new_state)
            svc_path = self._nm_devices.get(dev_path)
            if svc_path and svc_path in self._shill.services:
                self._shill.services[svc_path].set_state(shill_state)
                log.debug("Device %s → Shill state %s", dev_path, shill_state)
            self._shill.manager._refresh_technologies()

    def _on_nm_properties_changed(
        self, iface: str, changed: dict, invalid: list
    ) -> None:
        log.debug("NM properties changed: %s", changed)

    @staticmethod
    def _nm_to_shill_state(nm_state: int) -> str:
        """Map NM device state → Shill state string."""
        if nm_state >= 100:  # NM_DEVICE_STATE_ACTIVATED
            # Check NM connectivity for "online" vs "ready"
            # For simplicity, assume "online" (the connectivity check is async)
            return SHILL_STATE_ONLINE
        elif nm_state >= 50:  # CONNECTING
            return SHILL_STATE_ASSOCIATION
        else:
            return SHILL_STATE_IDLE


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    bus = dbus.SystemBus()

    # Container for all Shill objects
    shill = ShillDBus(bus)

    # Acquire the org.chromium.flimflam bus name
    shill.acquire_name()

    # Create the Manager at path "/"
    mgr = Manager(bus.get_connection(), SHILL_MANAGER_PATH, shill)
    shill.manager = mgr

    # Create a default profile
    Profile(bus.get_connection(), SHALLOW_PROFILE_PATH)

    # Start NM monitor (connects to NM and syncs devices)
    monitor = NetworkManagerMonitor(bus, shill)
    monitor.start()

    log.info("shill-nm-adapter ready — listening on system bus")

    loop = GLib.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        pass
    finally:
        shill.release_name()
        log.info("shill-nm-adapter stopped")


if __name__ == "__main__":
    main()
