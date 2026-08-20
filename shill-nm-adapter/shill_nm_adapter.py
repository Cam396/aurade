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
NM_DEVICE_WIRED_IFACE = "org.freedesktop.NetworkManager.Device.Wired"
NM_DEVICE_WIFI_IFACE = "org.freedesktop.NetworkManager.Device.Wireless"
NM_ACCESS_POINT_IFACE = "org.freedesktop.NetworkManager.AccessPoint"
NM_SETTINGS_PATH = "/org/freedesktop/NetworkManager/Settings"
NM_SETTINGS_IFACE = "org.freedesktop.NetworkManager.Settings"
NM_CONNECTION_IFACE = "org.freedesktop.NetworkManager.Settings.Connection"
NM_IP4CONFIG_IFACE = "org.freedesktop.NetworkManager.IP4Config"
NM_IP6CONFIG_IFACE = "org.freedesktop.NetworkManager.IP6Config"
NM_ACTIVE_CONNECTION = "org.freedesktop.NetworkManager.Connection.Active"
NM_STATE_CONNECTED_GLOBAL = 70
NM_DEVICE_STATE_UNAVAILABLE = 20
NM_DEVICE_STATE_DISCONNECTED = 30
NM_DEVICE_STATE_ACTIVATED = 100
NM_DEVICE_TYPE_ETHERNET = 1
NM_DEVICE_TYPE_WIFI = 2
NM_AP_FLAGS_PRIVACY = 1

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

# Wi-Fi service properties.  They are kept as constants because Ash uses the
# exact Shill spelling and a typo silently turns a real access point into an
# unselectable row.
PROP_PASSPHRASE = "Passphrase"
PROP_WIFI_BSSID = "WiFi.BSSID"
PROP_WIFI_HEX_SSID = "WiFi.HexSSID"
PROP_WIFI_SSID = "WiFi.SSID"
PROP_WIFI_SECURITY = "Security"
PROP_SECURITY_CLASS = "SecurityClass"
PROP_WIFI_HIDDEN = "WiFi.HiddenSSID"
PROP_WIFI_MODE = "Mode"
PROP_IS_CONNECTED = "IsConnected"
PROP_ERROR = "Error"
PROP_ERROR_DETAILS = "ErrorDetails"

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


def _as_bytes(value) -> bytes:
    """Return a D-Bus byte array as bytes without leaking it to logs."""
    if value is None:
        return b""
    try:
        return bytes(value)
    except (TypeError, ValueError):
        return b""


def _ssid_text(raw_ssid: bytes) -> str:
    """Make an arbitrary 802.11 SSID safe for Shill's UTF-8 Name field."""
    return raw_ssid.decode("utf-8", "replace")


def _security_class(flags: int, wpa_flags: int, rsn_flags: int) -> str:
    """Map NetworkManager AP security flags to Shill's coarse classes."""
    if not (flags & NM_AP_FLAGS_PRIVACY) and not (wpa_flags or rsn_flags):
        return "none"
    if wpa_flags or rsn_flags:
        return "psk"
    return "wep"


def _technology_properties(available: list[str], connected: list[str]) -> dict:
    """Return manager technology fields derived only from real NM devices."""
    available = list(dict.fromkeys(available))
    connected = list(dict.fromkeys(connected))
    enabled = list(available)
    default = connected[0] if connected else (enabled[0] if enabled else "")
    return {
        PROP_ENABLED_TECHNOLOGIES: enabled,
        PROP_AVAILABLE_TECHNOLOGIES: available,
        PROP_CONNECTED_TECHNOLOGIES: connected,
        PROP_DEFAULT_TECHNOLOGY: default,
        PROP_CHECK_PORTAL_LIST: ",".join(enabled),
    }


def _access_point_record(props: dict) -> dict | None:
    """Normalize one NetworkManager access point for the Shill layer.

    Empty SSIDs are hidden networks.  They are deliberately not exposed as a
    fake visible row because Ash would render an empty network and then send
    credentials to it.  A hidden network can still be requested explicitly
    through Manager.GetService using WiFi.HexSSID.
    """
    raw_ssid = _as_bytes(props.get("Ssid"))
    if not raw_ssid:
        return None
    flags = int(props.get("Flags", 0))
    wpa_flags = int(props.get("WpaFlags", 0))
    rsn_flags = int(props.get("RsnFlags", 0))
    return {
        "raw_ssid": raw_ssid,
        "name": _ssid_text(raw_ssid),
        "hex_ssid": raw_ssid.hex(),
        "bssid": str(props.get("HwAddress", "")),
        "strength": max(0, min(100, int(props.get("Strength", 0)))),
        "security": _security_class(flags, wpa_flags, rsn_flags),
        "security_name": (
            "WPA2" if rsn_flags else "WPA" if wpa_flags else
            "WEP" if flags & NM_AP_FLAGS_PRIVACY else "none"
        ),
        "frequency": int(props.get("Frequency", 0)),
    }

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

    def update_service_lists(self) -> None:
        """Publish the real visible and complete service sets.

        The old bridge published a synthetic interface service even when no
        network had been discovered.  Ash treats that object as a real network
        and renders dummy rows.  Keep the two Shill lists derived from the
        objects that the monitor actually observed instead.
        """
        if self._manager is None:
            return
        all_paths = list(self._services.keys())
        visible_paths = [
            path for path in all_paths
            if bool(self._services[path]._props.get(PROP_VISIBLE, True))
        ]
        self._manager._set_properties({
            PROP_SERVICES: dbus.Array(
                [dbus.ObjectPath(path) for path in visible_paths], signature="o"
            ),
            PROP_SERVICE_COMPLETE_LIST: dbus.Array(
                [dbus.ObjectPath(path) for path in all_paths], signature="o"
            ),
        })

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
        self._monitor: "NetworkManagerMonitor | None" = None
        super().__init__(conn, path)
        self._init_properties()

    def _init_properties(self) -> None:
        self._props = {
            PROP_DEVICES: dbus.Array([], signature="o"),
            PROP_SERVICES: dbus.Array([], signature="o"),
            PROP_SERVICE_COMPLETE_LIST: dbus.Array([], signature="o"),
            # Do not advertise technologies merely because the Shill API knows
            # their names.  Ash treats EnabledTechnologies as a real device
            # inventory and renders a row for every entry.  The old static
            # ethernet plus wifi list therefore created an Ethernet control on
            # Wi-Fi-only machines before NetworkManager had reported devices.
            PROP_ENABLED_TECHNOLOGIES: dbus.Array([], signature="s"),
            PROP_PROFILES: dbus.Array(
                [dbus.ObjectPath(SHALLOW_PROFILE_PATH)], signature="o"
            ),
            PROP_AVAILABLE_TECHNOLOGIES: dbus.Array([], signature="s"),
            PROP_CONNECTED_TECHNOLOGIES: dbus.Array([], signature="s"),
            PROP_DEFAULT_TECHNOLOGY: "",
            PROP_CHECK_PORTAL_LIST: "",
            PROP_ARP_GATEWAY: dbus.Boolean(False),
        }

    def set_nm_proxy(self, nm_iface: dbus.Interface, nm_props: dbus.Interface) -> None:
        self._nm_iface = nm_iface
        self._nm_props = nm_props
        # Trigger an initial state refresh
        self._refresh_technologies()

    def set_monitor(self, monitor: "NetworkManagerMonitor") -> None:
        self._monitor = monitor

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
                if state >= NM_DEVICE_STATE_ACTIVATED:
                    connected.append(SHILL_TYPE_WIFI)

        # EnabledTechnologies is consumed as an inventory by Ash, not as a
        # capability bitmask.  Keep it in lockstep with actual NM devices so
        # an absent Ethernet controller or cellular modem cannot become a
        # placeholder row in the network menu.
        technology_props = _technology_properties(available, connected)
        self._set_properties({
            PROP_ENABLED_TECHNOLOGIES: dbus.Array(
                technology_props[PROP_ENABLED_TECHNOLOGIES], signature="s"
            ),
            PROP_AVAILABLE_TECHNOLOGIES: dbus.Array(
                technology_props[PROP_AVAILABLE_TECHNOLOGIES], signature="s"
            ),
            PROP_CONNECTED_TECHNOLOGIES: dbus.Array(
                technology_props[PROP_CONNECTED_TECHNOLOGIES], signature="s"
            ),
            PROP_DEFAULT_TECHNOLOGY: technology_props[PROP_DEFAULT_TECHNOLOGY],
            PROP_CHECK_PORTAL_LIST: technology_props[PROP_CHECK_PORTAL_LIST],
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
            match = True
            for key in (
                PROP_TYPE,
                PROP_GUID,
                PROP_DEVICE,
                PROP_WIFI_HEX_SSID,
                PROP_WIFI_SSID,
                PROP_NAME,
            ):
                if key in args and str(args[key]) != str(props.get(key, "")):
                    match = False
                    break
            if match:
                return dbus.ObjectPath(path)
        # No match — create a new one
        if self._monitor is not None:
            requested = self._monitor.create_requested_service(args)
            if requested is not None:
                return requested
        return self._create_service(args)

    @dbus.service.method(SHILL_MANAGER_IFACE, in_signature="a{sv}", out_signature="o")
    def ConfigureService(self, args: dict) -> dbus.ObjectPath:
        if args.get(PROP_TYPE) == SHILL_TYPE_WIFI and self._monitor is not None:
            requested = self._monitor.create_requested_service(args)
            if requested is not None:
                return requested
        return self._create_service(args)

    @dbus.service.method(SHILL_MANAGER_IFACE, in_signature="oa{sv}", out_signature="o")
    def ConfigureServiceForProfile(self, profile_path: dbus.ObjectPath, args: dict) -> dbus.ObjectPath:
        if args.get(PROP_TYPE) == SHILL_TYPE_WIFI and self._monitor is not None:
            requested = self._monitor.create_requested_service(args)
            if requested is not None:
                return requested
        return self._create_service(args)

    @dbus.service.method(SHILL_MANAGER_IFACE, in_signature="", out_signature="")
    def ScanAndConnectToBestServices(self) -> None:
        if self._monitor is not None:
            self._monitor.request_scan(SHILL_TYPE_WIFI)

    @dbus.service.method(SHILL_MANAGER_IFACE, in_signature="s", out_signature="")
    def RequestScan(self, type_str: str) -> None:
        if self._monitor is not None:
            self._monitor.request_scan(type_str)
        else:
            log.warning("RequestScan(%s) before NetworkManager monitor is ready", type_str)

    @dbus.service.method(SHILL_MANAGER_IFACE, in_signature="s", out_signature="")
    def EnableTechnology(self, type_str: str) -> None:
        if self._monitor is not None:
            self._monitor.set_technology_enabled(type_str, True)

    @dbus.service.method(SHILL_MANAGER_IFACE, in_signature="s", out_signature="")
    def DisableTechnology(self, type_str: str) -> None:
        if self._monitor is not None:
            self._monitor.set_technology_enabled(type_str, False)

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
        if svc_type == SHILL_TYPE_WIFI and self._monitor is not None:
            requested = self._monitor.create_requested_service(props)
            if requested is not None:
                return requested
            raise dbus.exceptions.DBusException(
                "org.chromium.flimflam.Error.InvalidArguments",
                "A Wi-Fi service needs WiFi.HexSSID",
            )
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
            self._shill.update_service_lists()
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
        monitor: "NetworkManagerMonitor | None" = None,
        nm_device_path: str | None = None,
        ssid: bytes | None = None,
        record: dict | None = None,
        visible: bool = True,
    ):
        self._interface_name = SHILL_SERVICE_IFACE
        self._shill = shill
        self._monitor = monitor
        self._svc_type = svc_type
        self._iface_name = iface_name
        self._guid = guid
        self._nm_device_path = nm_device_path
        self._nm_connection_path: str | None = None
        self._ssid = ssid or b""
        self._passphrase: str | None = None
        self._record = record or {}
        super().__init__(conn, path)
        self._props = {
            PROP_TYPE: svc_type,
            PROP_GUID: guid,
            PROP_NAME: (record or {}).get("name", iface_name),
            PROP_STATE: SHILL_STATE_IDLE,
            PROP_CONNECTABLE: dbus.Boolean(True),
            PROP_PROFILE: dbus.ObjectPath(SHALLOW_PROFILE_PATH),
            PROP_DEVICE: dbus.ObjectPath(f"/org/chromium/flimflam/Device/{iface_name}"),
            PROP_STRENGTH: dbus.Byte(0),
            PROP_AUTO_CONNECT: dbus.Boolean(False),
            PROP_VISIBLE: dbus.Boolean(visible),
        }
        if svc_type == SHILL_TYPE_WIFI:
            self._props.update({
                PROP_WIFI_SSID: (record or {}).get("name", iface_name),
                PROP_WIFI_HEX_SSID: self._ssid.hex(),
                PROP_WIFI_BSSID: str(self._record.get("bssid", "")),
                PROP_SECURITY_CLASS: str(self._record.get("security", "none")),
                PROP_WIFI_SECURITY: str(self._record.get("security_name", "none")),
                PROP_WIFI_MODE: "managed",
                PROP_WIFI_HIDDEN: dbus.Boolean(not bool(self._ssid)),
                PROP_IS_CONNECTED: dbus.Boolean(False),
            })
            self.update_access_point(self._record, False)

    # -- Service methods --

    @dbus.service.method(SHILL_SERVICE_IFACE, out_signature="a{sv}")
    def GetProperties(self) -> dict:
        return dict(self._props)

    @dbus.service.method(SHILL_SERVICE_IFACE, in_signature="a{sv}", out_signature="")
    def SetProperties(self, props: dict) -> None:
        for name, value in props.items():
            self.set_property(name, value)

    @dbus.service.method(SHILL_SERVICE_IFACE, in_signature="sv", out_signature="")
    def SetProperty(self, name: str, value) -> None:
        self.set_property(name, value)

    @dbus.service.method(
        dbus.PROPERTIES_IFACE,
        in_signature="ssv",
        out_signature="",
    )
    def Set(self, interface: str, name: str, value) -> None:
        if interface != self._interface_name:
            raise dbus.exceptions.DBusException(
                "org.freedesktop.DBus.Error.InvalidArgs",
                f"No such interface: {interface}",
            )
        self.set_property(name, value)

    @dbus.service.method(SHILL_SERVICE_IFACE, in_signature="s", out_signature="")
    def ClearProperty(self, name: str) -> None:
        if name == PROP_PASSPHRASE:
            self._passphrase = None
            return
        self._props.pop(name, None)

    def set_property(self, name: str, value) -> None:
        # Never put a passphrase in _props.  GetProperties is consumed by UI
        # code and logs, while the secret is only needed for one NM activation.
        if name in (PROP_PASSPHRASE, "WiFi.Passphrase"):
            self._passphrase = str(value)
            return
        self._set_property(name, value)

    @dbus.service.method(SHILL_SERVICE_IFACE, out_signature="")
    def Connect(self) -> None:
        if self._monitor is None:
            raise dbus.exceptions.DBusException(
                "org.chromium.flimflam.Error.OperationFailed",
                "NetworkManager monitor is not ready",
            )
        self._monitor.connect_service(self)

    @dbus.service.method(SHILL_SERVICE_IFACE, out_signature="")
    def Disconnect(self) -> None:
        if self._monitor is not None:
            self._monitor.disconnect_service(self)

    @dbus.service.method(SHILL_SERVICE_IFACE, out_signature="")
    def Remove(self) -> None:
        if self._monitor is not None:
            self._monitor.remove_service(self)

    @dbus.service.method(SHILL_SERVICE_IFACE, out_signature="s")
    def GetWiFiPassphrase(self) -> str:
        if self._svc_type != SHILL_TYPE_WIFI or self._passphrase is None:
            raise dbus.exceptions.DBusException(
                "org.chromium.flimflam.Error.NotSupported",
                "No saved Wi-Fi passphrase",
            )
        return self._passphrase

    # -- public mutators --

    def set_state(self, state: str) -> None:
        self._set_properties({
            PROP_STATE: state,
            PROP_IS_CONNECTED: dbus.Boolean(state == SHILL_STATE_ONLINE),
        })

    def update_access_point(self, record: dict, connected: bool) -> None:
        """Refresh one real AP sighting without creating synthetic rows."""
        if self._svc_type != SHILL_TYPE_WIFI:
            return
        self._record = record
        self._set_properties({
            PROP_NAME: record.get("name", self._props.get(PROP_NAME, "")),
            PROP_WIFI_SSID: record.get("name", self._props.get(PROP_WIFI_SSID, "")),
            PROP_WIFI_BSSID: str(record.get("bssid", "")),
            PROP_STRENGTH: dbus.Byte(int(record.get("strength", 0))),
            PROP_SECURITY_CLASS: str(record.get("security", "none")),
            PROP_WIFI_SECURITY: str(record.get("security_name", "none")),
            PROP_IS_CONNECTED: dbus.Boolean(connected),
        })


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

    def __init__(self, conn: dbus.bus.BusConnection, path: str, shill: ShillDBus):
        self._interface_name = SHILL_PROFILE_IFACE
        self._shill = shill
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
    """Subscribe to NetworkManager and expose only real Shill services."""

    def __init__(self, bus: dbus.Bus, shill: ShillDBus):
        self._bus = bus
        self._shill = shill
        self._nm_obj = bus.get_object(NM_SERVICE, NM_PATH)
        self._nm_iface = dbus.Interface(self._nm_obj, NM_IFACE)
        self._nm_props = dbus.Interface(self._nm_obj, dbus.PROPERTIES_IFACE)
        self._nm_devices: dict[str, str] = {}
        self._services_by_device: dict[str, set[str]] = {}
        self._service_keys: dict[tuple[str, str, str], str] = {}
        self._service_meta: dict[str, dict] = {}
        self._watched_devices: set[str] = set()
        self._watched_wifi: set[str] = set()
        self._scan_source = 0

    def start(self) -> None:
        self._shill.manager.set_nm_proxy(self._nm_iface, self._nm_props)
        self._shill.manager.set_monitor(self)
        self._sync_devices()
        self._nm_obj.connect_to_signal(
            "DeviceAdded", self._on_device_added, dbus_interface=NM_IFACE
        )
        self._nm_obj.connect_to_signal(
            "DeviceRemoved", self._on_device_removed, dbus_interface=NM_IFACE
        )
        self._nm_props.connect_to_signal(
            "PropertiesChanged", self._on_nm_properties_changed
        )
        self._shill.manager._refresh_technologies()
        self._shill.update_service_lists()
        log.info("NM monitor started - %d device(s) tracked", len(self._nm_devices))

    def _device(self, dev_path: str):
        return self._bus.get_object(NM_SERVICE, dev_path)

    def _device_props(self, dev_path: str):
        return dbus.Interface(self._device(dev_path), dbus.PROPERTIES_IFACE)

    def _watch_device(self, dev_path: str) -> None:
        if dev_path in self._watched_devices:
            return
        try:
            dev_props = self._device_props(dev_path)
            dev_props.connect_to_signal(
                "PropertiesChanged",
                lambda iface, changed, invalid: self._on_device_props_changed(
                    dev_path, changed
                ),
            )
            self._watched_devices.add(dev_path)
        except Exception as exc:
            log.warning("Cannot watch device %s: %s", dev_path, exc)

    def _sync_devices(self) -> None:
        try:
            nm_dev_paths = self._nm_iface.GetDevices()
        except Exception as exc:
            log.warning("Cannot enumerate NetworkManager devices: %s", exc)
            nm_dev_paths = []
        for dev_path in nm_dev_paths:
            self._add_device(str(dev_path))

    def _add_device(self, dev_path: str) -> None:
        """Add a device and then derive services from NM state.

        Wi-Fi devices are not themselves networks.  The previous code exposed
        one always-online service for the interface, which is the source of
        the dummy rows seen in the ChromeOS network menu.
        """
        try:
            dev_props = self._device_props(dev_path)
            dtype = int(dev_props.Get(NM_DEVICE_IFACE, "DeviceType"))
            state = int(dev_props.Get(NM_DEVICE_IFACE, "State"))
            iface = str(dev_props.Get(NM_DEVICE_IFACE, "Interface"))
            mac = str(dev_props.Get(NM_DEVICE_IFACE, "HwAddress"))
        except Exception as exc:
            log.warning("Cannot read NM device %s: %s", dev_path, exc)
            return
        if dtype not in (NM_DEVICE_TYPE_ETHERNET, NM_DEVICE_TYPE_WIFI):
            return

        self._nm_devices[dev_path] = iface
        self._services_by_device.setdefault(dev_path, set())
        dev_shill_path = f"/org/chromium/flimflam/Device/{iface}"
        if dev_shill_path not in self._shill.devices:
            self._shill.devices[dev_shill_path] = Device(
                self._bus.get_connection(),  # type: ignore[arg-type]
                dev_shill_path,
                self._shill,
                iface,
                SHILL_TYPE_ETHERNET if dtype == NM_DEVICE_TYPE_ETHERNET else SHILL_TYPE_WIFI,
                mac,
            )
            self._shill.manager._set_property(
                PROP_DEVICES,
                dbus.Array(
                    [dbus.ObjectPath(p) for p in self._shill.devices], signature="o"
                ),
            )
        self._watch_device(dev_path)
        if dtype == NM_DEVICE_TYPE_WIFI:
            self._watch_wifi(dev_path)
            self._sync_wifi_services(dev_path)
        else:
            self._sync_ethernet_service(dev_path, state, iface)

    def _new_service(
        self,
        dev_path: str,
        svc_type: str,
        iface: str,
        guid: str,
        *,
        record: dict | None = None,
        visible: bool = True,
    ) -> Service:
        raw_ssid = (record or {}).get("raw_ssid", b"")
        svc_path = f"/org/chromium/flimflam/Service/{guid}"
        svc = Service(
            self._bus.get_connection(),  # type: ignore[arg-type]
            svc_path,
            self._shill,
            svc_type,
            iface,
            guid,
            monitor=self,
            nm_device_path=dev_path,
            ssid=raw_ssid,
            record=record,
            visible=visible,
        )
        self._shill.services[svc_path] = svc
        self._services_by_device.setdefault(dev_path, set()).add(svc_path)
        self._service_meta[svc_path] = {"device": dev_path, "hidden": not visible}
        return svc

    def _sync_ethernet_service(self, dev_path: str, state: int, iface: str) -> None:
        key = (dev_path, "ethernet", "")
        svc_path = self._service_keys.get(key)
        if svc_path is None:
            svc = self._new_service(
                dev_path, SHILL_TYPE_ETHERNET, iface, _generate_guid()
            )
            svc_path = f"/org/chromium/flimflam/Service/{svc._guid}"
            self._service_keys[key] = svc_path
        svc = self._shill.services[svc_path]
        svc.set_state(self._nm_to_shill_state(state))
        self._shill.update_service_lists()

    def _wifi_access_points(self, dev_path: str) -> list[dict]:
        try:
            wifi = dbus.Interface(self._device(dev_path), NM_DEVICE_WIFI_IFACE)
            ap_paths = wifi.GetAccessPoints()
        except Exception as exc:
            log.warning("Cannot enumerate Wi-Fi access points on %s: %s", dev_path, exc)
            return []
        records: dict[tuple[str, str], dict] = {}
        for ap_path in ap_paths:
            try:
                ap_obj = self._bus.get_object(NM_SERVICE, ap_path)
                props = dbus.Interface(ap_obj, dbus.PROPERTIES_IFACE).GetAll(
                    NM_ACCESS_POINT_IFACE
                )
            except Exception as exc:
                log.debug("Cannot read Wi-Fi access point %s: %s", ap_path, exc)
                continue
            record = _access_point_record(props)
            if record is None:
                continue
            key = (record["hex_ssid"], record["security"])
            if key not in records or record["strength"] > records[key]["strength"]:
                record["ap_path"] = str(ap_path)
                records[key] = record
        return list(records.values())

    def _watch_wifi(self, dev_path: str) -> None:
        if dev_path in self._watched_wifi:
            return
        try:
            wifi = dbus.Interface(self._device(dev_path), NM_DEVICE_WIFI_IFACE)
            wifi.connect_to_signal(
                "AccessPointAdded",
                lambda _path: self._sync_wifi_services(dev_path),
            )
            wifi.connect_to_signal(
                "AccessPointRemoved",
                lambda _path: self._sync_wifi_services(dev_path),
            )
            self._watched_wifi.add(dev_path)
        except Exception as exc:
            log.debug("Cannot watch Wi-Fi access points on %s: %s", dev_path, exc)

    def _sync_wifi_services(self, dev_path: str) -> None:
        iface = self._nm_devices.get(dev_path, "wlan0")
        try:
            dev_props = self._device_props(dev_path)
            state = int(dev_props.Get(NM_DEVICE_IFACE, "State"))
            # ActiveAccessPoint belongs to NetworkManager's wireless device
            # interface, not the common device interface. Reading it from the
            # latter silently falls into the disconnected path, so a network
            # that is actually carrying the session appears idle in Ash.
            active_ap = str(dev_props.Get(NM_DEVICE_WIFI_IFACE, "ActiveAccessPoint"))
        except Exception:
            state = NM_DEVICE_STATE_DISCONNECTED
            active_ap = "/"
        seen: set[tuple[str, str]] = set()
        for record in self._wifi_access_points(dev_path):
            key = (record["hex_ssid"], record["security"])
            seen.add(key)
            service_key = (dev_path, key[0], key[1])
            svc_path = self._service_keys.get(service_key)
            if svc_path is None:
                svc = self._new_service(
                    dev_path, SHILL_TYPE_WIFI, iface, _generate_guid(), record=record
                )
                svc_path = f"/org/chromium/flimflam/Service/{svc._guid}"
                self._service_keys[service_key] = svc_path
            svc = self._shill.services[svc_path]
            connected = state >= NM_DEVICE_STATE_ACTIVATED and (
                active_ap != "/" and active_ap == record.get("ap_path")
            )
            svc.update_access_point(record, connected)
            svc.set_state(
                SHILL_STATE_ONLINE if connected else (
                    SHILL_STATE_READY
                    if state >= NM_DEVICE_STATE_DISCONNECTED
                    else SHILL_STATE_IDLE
                )
            )
        # A scan can make a previously visible AP disappear.  Remove only
        # discovered rows; hidden configured services remain available.
        for svc_path in list(self._services_by_device.get(dev_path, ())):
            meta = self._service_meta.get(svc_path, {})
            if meta.get("hidden"):
                continue
            svc = self._shill.services.get(svc_path)
            if svc is None or svc._svc_type != SHILL_TYPE_WIFI:
                continue
            svc_key = (
                dev_path,
                str(svc._props.get(PROP_WIFI_HEX_SSID, "")),
                str(svc._props.get(PROP_SECURITY_CLASS, "none")),
            )
            if (svc_key[1], svc_key[2]) not in seen:
                self._remove_service_path(svc_path)
                self._service_keys.pop(svc_key, None)
        self._shill.update_service_lists()

    def create_requested_service(self, args: dict) -> dbus.ObjectPath | None:
        """Create a hidden Wi-Fi service only when Ash asks for one."""
        if args.get(PROP_TYPE) != SHILL_TYPE_WIFI:
            return None
        hex_ssid = str(args.get(PROP_WIFI_HEX_SSID, ""))
        if not hex_ssid and args.get(PROP_WIFI_SSID):
            hex_ssid = _as_bytes(str(args[PROP_WIFI_SSID]).encode("utf-8")).hex()
        if not hex_ssid:
            return None
        try:
            raw_ssid = bytes.fromhex(hex_ssid)
        except ValueError:
            return None
        dev_path = next(
            (path for path in self._nm_devices
             if self._device_type(path) == NM_DEVICE_TYPE_WIFI),
            None,
        )
        if dev_path is None:
            return None
        security = str(args.get(PROP_SECURITY_CLASS, "psk"))
        record = {
            "raw_ssid": raw_ssid,
            "name": _ssid_text(raw_ssid),
            "hex_ssid": hex_ssid,
            "bssid": "",
            "strength": 0,
            "security": security,
            "security_name": "WPA2" if security == "psk" else security,
        }
        key = (dev_path, hex_ssid, security)
        if key in self._service_keys:
            return dbus.ObjectPath(self._service_keys[key])
        iface = self._nm_devices[dev_path]
        svc = self._new_service(
            dev_path,
            SHILL_TYPE_WIFI,
            iface,
            str(args.get(PROP_GUID, _generate_guid())),
            record=record,
            visible=False,
        )
        svc_path = f"/org/chromium/flimflam/Service/{svc._guid}"
        self._service_keys[key] = svc_path
        self._shill.update_service_lists()
        return dbus.ObjectPath(svc_path)

    def request_scan(self, type_str: str) -> None:
        if type_str not in (SHILL_TYPE_WIFI, "wifi", ""):
            return
        for dev_path in self._nm_devices:
            if self._device_type(dev_path) != NM_DEVICE_TYPE_WIFI:
                continue
            try:
                dbus.Interface(self._device(dev_path), NM_DEVICE_WIFI_IFACE).RequestScan({})
            except Exception as exc:
                log.warning("Wi-Fi scan request failed on %s: %s", dev_path, exc)
        if self._scan_source:
            GLib.source_remove(self._scan_source)
        self._scan_source = GLib.timeout_add(1500, self._finish_scan)

    def _finish_scan(self) -> bool:
        self._scan_source = 0
        for dev_path in self._nm_devices:
            if self._device_type(dev_path) == NM_DEVICE_TYPE_WIFI:
                self._sync_wifi_services(dev_path)
        return False

    def set_technology_enabled(self, type_str: str, enabled: bool) -> None:
        if type_str not in (SHILL_TYPE_WIFI, "wifi"):
            return
        try:
            self._nm_props.Set(
                NM_IFACE,
                "WirelessEnabled",
                dbus.Boolean(enabled),
            )
        except Exception as exc:
            log.warning("Cannot set Wi-Fi radio state to %s: %s", enabled, exc)

    def _find_nm_connection(self, service: Service):
        try:
            settings_obj = self._bus.get_object(NM_SERVICE, NM_SETTINGS_PATH)
            settings = dbus.Interface(settings_obj, NM_SETTINGS_IFACE)
            for connection_path in settings.ListConnections():
                connection = dbus.Interface(
                    self._bus.get_object(NM_SERVICE, connection_path),
                    NM_CONNECTION_IFACE,
                )
                values = connection.GetSettings()
                cprops = values.get("connection", {})
                wifi = values.get("802-11-wireless", {})
                if cprops.get("type") != "802-11-wireless":
                    continue
                if _as_bytes(wifi.get("ssid")) == service._ssid:
                    return connection_path
        except Exception as exc:
            log.debug("Cannot inspect saved NetworkManager connections: %s", exc)
        return None

    def _connection_settings(self, service: Service) -> dict:
        security = str(service._props.get(PROP_SECURITY_CLASS, "none"))
        settings = {
            "connection": {
                "id": service._props.get(PROP_NAME, service._iface_name),
                "type": "802-11-wireless",
                "uuid": str(uuid.uuid4()),
                "interface-name": service._iface_name,
            },
            "802-11-wireless": {
                "ssid": dbus.ByteArray(service._ssid),
                "mode": "infrastructure",
            },
            "ipv4": {"method": "auto"},
            "ipv6": {"method": "auto"},
        }
        if security == "none":
            return settings
        if security == "wep":
            raise dbus.exceptions.DBusException(
                "org.chromium.flimflam.Error.NotSupported",
                "WEP networks are not supported by AuraDE yet",
            )
        if not service._passphrase:
            raise dbus.exceptions.DBusException(
                "org.chromium.flimflam.Error.InvalidPassphrase",
                "This Wi-Fi network needs a passphrase",
            )
        settings["802-11-wireless-security"] = {
            "key-mgmt": "wpa-psk",
            "psk": service._passphrase,
        }
        return settings

    def connect_service(self, service: Service) -> None:
        if service._svc_type != SHILL_TYPE_WIFI:
            service.set_state(SHILL_STATE_READY)
            return
        service.set_state(SHILL_STATE_ASSOCIATION)
        try:
            settings_obj = self._bus.get_object(NM_SERVICE, NM_SETTINGS_PATH)
            settings = dbus.Interface(settings_obj, NM_SETTINGS_IFACE)
            connection_path = self._find_nm_connection(service)
            if connection_path is None:
                nm_settings = self._connection_settings(service)
                connection_path = settings.AddConnection(nm_settings)
            elif service._passphrase:
                # A selected network may already have a saved profile. Only
                # update its secrets when Ash supplied a new passphrase; a
                # normal reconnect must not ask the UI to reveal one again.
                nm_settings = self._connection_settings(service)
                dbus.Interface(
                    self._bus.get_object(NM_SERVICE, connection_path),
                    NM_CONNECTION_IFACE,
                ).Update(nm_settings)
            active = self._nm_iface.ActivateConnection(
                connection_path,
                dbus.ObjectPath(service._nm_device_path),
                dbus.ObjectPath("/"),
            )
            service._nm_connection_path = str(connection_path)
            log.info("Requested NetworkManager activation for %s", service._props.get(PROP_NAME))
            del active
        except dbus.exceptions.DBusException:
            service.set_state(SHILL_STATE_IDLE)
            raise
        except Exception as exc:
            service._set_properties({
                PROP_STATE: SHILL_STATE_IDLE,
                PROP_ERROR: "operation-failed",
                PROP_ERROR_DETAILS: "NetworkManager could not activate this network",
            })
            raise dbus.exceptions.DBusException(
                "org.chromium.flimflam.Error.OperationFailed",
                "NetworkManager could not activate this network",
            ) from exc

    def disconnect_service(self, service: Service) -> None:
        try:
            dbus.Interface(self._device(service._nm_device_path), NM_DEVICE_IFACE).Disconnect()
        except Exception as exc:
            log.debug("NetworkManager disconnect failed for %s: %s", service._iface_name, exc)
        service.set_state(SHILL_STATE_IDLE)

    def remove_service(self, service: Service) -> None:
        if service._nm_connection_path:
            try:
                dbus.Interface(
                    self._bus.get_object(NM_SERVICE, service._nm_connection_path),
                    NM_CONNECTION_IFACE,
                ).Delete()
            except Exception as exc:
                log.debug("Cannot delete NetworkManager profile: %s", exc)
        svc_path = f"/org/chromium/flimflam/Service/{service._guid}"
        self._remove_service_path(svc_path)
        self._shill.update_service_lists()

    def _remove_service_path(self, svc_path: str) -> None:
        svc = self._shill.services.pop(svc_path, None)
        if svc is None:
            return
        for paths in self._services_by_device.values():
            paths.discard(svc_path)
        self._service_meta.pop(svc_path, None)
        for key, path in list(self._service_keys.items()):
            if path == svc_path:
                self._service_keys.pop(key, None)
        try:
            svc.remove_from_connection()
        except Exception:
            pass

    def _remove_device(self, dev_path: str) -> None:
        for svc_path in list(self._services_by_device.pop(dev_path, ())):
            self._remove_service_path(svc_path)
        iface = self._nm_devices.pop(dev_path, None)
        self._watched_devices.discard(dev_path)
        self._watched_wifi.discard(dev_path)
        if iface:
            device_path = f"/org/chromium/flimflam/Device/{iface}"
            device = self._shill.devices.pop(device_path, None)
            if device is not None:
                try:
                    device.remove_from_connection()
                except Exception:
                    pass
            self._shill.manager._set_property(
                PROP_DEVICES,
                dbus.Array(
                    [dbus.ObjectPath(p) for p in self._shill.devices], signature="o"
                ),
            )
        self._shill.update_service_lists()

    def _on_device_added(self, dev_path: str) -> None:
        log.info("NM device added: %s", dev_path)
        self._add_device(str(dev_path))
        self._shill.manager._refresh_technologies()

    def _on_device_removed(self, dev_path: str) -> None:
        log.info("NM device removed: %s", dev_path)
        self._remove_device(str(dev_path))
        self._shill.manager._refresh_technologies()

    def _on_device_props_changed(self, dev_path: str, changed: dict) -> None:
        if "State" not in changed and "ActiveAccessPoint" not in changed:
            return
        if self._device_type(dev_path) == NM_DEVICE_TYPE_WIFI:
            self._sync_wifi_services(dev_path)
        else:
            iface = self._nm_devices.get(dev_path, "eth0")
            self._sync_ethernet_service(dev_path, int(changed.get("State", 30)), iface)
        self._shill.manager._refresh_technologies()

    def _on_nm_properties_changed(self, iface: str, changed: dict, invalid: list) -> None:
        if "WirelessEnabled" in changed:
            for dev_path in self._nm_devices:
                if self._device_type(dev_path) == NM_DEVICE_TYPE_WIFI:
                    self._sync_wifi_services(dev_path)

    def _device_type(self, dev_path: str) -> int:
        try:
            return int(self._device_props(dev_path).Get(NM_DEVICE_IFACE, "DeviceType"))
        except Exception:
            return 0

    @staticmethod
    def _nm_to_shill_state(nm_state: int) -> str:
        if nm_state >= NM_DEVICE_STATE_ACTIVATED:
            return SHILL_STATE_ONLINE
        if nm_state >= 50:
            return SHILL_STATE_ASSOCIATION
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
    Profile(bus.get_connection(), SHALLOW_PROFILE_PATH, shill)

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
