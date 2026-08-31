#!/usr/bin/python
"""Shill compatible NetworkManager bridge used by the Ash connection UI.

The desktop speaks ``org.chromium.flimflam`` while AuraDE uses the normal
NetworkManager stack.  This daemon exposes real devices and access points and
translates scan, connect, disconnect, forget, and technology power requests.
It deliberately does not invent cellular or placeholder Wi-Fi services.

SPDX-License-Identifier: BSD-3-Clause
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import logging
import socket
import struct
import uuid
from collections.abc import Iterable

import dbus
import dbus.lowlevel
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

SHILL_SERVICE = "org.chromium.flimflam"
SHILL_MANAGER_PATH = "/"
SHILL_MANAGER_IFACE = "org.chromium.flimflam.Manager"
SHILL_SERVICE_IFACE = "org.chromium.flimflam.Service"
SHILL_DEVICE_IFACE = "org.chromium.flimflam.Device"
SHILL_IPCONFIG_IFACE = "org.chromium.flimflam.IPConfig"
SHILL_PROFILE_IFACE = "org.chromium.flimflam.Profile"

NM_SERVICE = "org.freedesktop.NetworkManager"
NM_PATH = "/org/freedesktop/NetworkManager"
NM_IFACE = "org.freedesktop.NetworkManager"
NM_SETTINGS_PATH = "/org/freedesktop/NetworkManager/Settings"
NM_SETTINGS_IFACE = "org.freedesktop.NetworkManager.Settings"
NM_SETTINGS_CONNECTION_IFACE = "org.freedesktop.NetworkManager.Settings.Connection"
NM_DEVICE_IFACE = "org.freedesktop.NetworkManager.Device"
NM_WIFI_DEVICE_IFACE = "org.freedesktop.NetworkManager.Device.Wireless"
NM_AP_IFACE = "org.freedesktop.NetworkManager.AccessPoint"

NM_DEVICE_TYPE_ETHERNET = 1
NM_DEVICE_TYPE_WIFI = 2
NM_DEVICE_STATE_DISCONNECTED = 30
NM_DEVICE_STATE_PREPARE = 40
NM_DEVICE_STATE_CONFIG = 50
NM_DEVICE_STATE_NEED_AUTH = 60
NM_DEVICE_STATE_IP_CONFIG = 70
NM_DEVICE_STATE_IP_CHECK = 80
NM_DEVICE_STATE_SECONDARIES = 90
NM_DEVICE_STATE_ACTIVATED = 100
NM_DEVICE_STATE_DEACTIVATING = 110
NM_DEVICE_STATE_FAILED = 120
NM_AP_FLAGS_PRIVACY = 0x1

# NM80211ApSecurityFlags.  These are bit positions, not an enumeration, and the
# pairwise cipher bits sit below the key management bits.  Reading a key
# management question off a cipher bit is what made every WPA2 network claim to
# be WPA3.
NM_AP_SEC_KEY_MGMT_PSK = 0x100
NM_AP_SEC_KEY_MGMT_802_1X = 0x200
NM_AP_SEC_KEY_MGMT_SAE = 0x400
NM_AP_SEC_KEY_MGMT_OWE = 0x800
NM_AP_SEC_KEY_MGMT_OWE_TM = 0x1000
NM_AP_SEC_KEY_MGMT_EAP_SUITE_B_192 = 0x2000

NM_AP_SEC_ENTERPRISE = NM_AP_SEC_KEY_MGMT_802_1X | NM_AP_SEC_KEY_MGMT_EAP_SUITE_B_192
NM_AP_SEC_OWE_ANY = NM_AP_SEC_KEY_MGMT_OWE | NM_AP_SEC_KEY_MGMT_OWE_TM

# NMDeviceStateReason, for turning a failed association into words.
NM_REASON_NO_SECRETS = 7
NM_REASON_SUPPLICANT_DISCONNECT = 8
NM_REASON_SUPPLICANT_CONFIG_FAILED = 9
NM_REASON_SUPPLICANT_FAILED = 10
NM_REASON_SUPPLICANT_TIMEOUT = 11
NM_REASON_SSID_NOT_FOUND = 53

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
PROP_POWERED = "Powered"
PROP_SCANNING = "Scanning"
PROP_SECURITY_CLASS = "SecurityClass"
PROP_DEFAULT_SERVICE = "DefaultService"
PROP_HIDDEN_SSID = "WiFi.HiddenSSID"
PROP_ERROR_DETAILS = "ErrorDetails"
PROP_NAME_SERVERS = "NameServers"
PROP_SSID = "SSID"
PROP_SECURITY = "Security"
PROP_PASSPHRASE = "Passphrase"
PROP_PASSPHRASE_REQUIRED = "PassphraseRequired"
PROP_ERROR = "Error"

SHILL_STATE_ONLINE = "online"
SHILL_STATE_READY = "ready"
SHILL_STATE_IDLE = "idle"
SHILL_STATE_ASSOCIATION = "association"
SHILL_STATE_CONFIGURATION = "configuration"
SHILL_STATE_NO_CONNECTIVITY = "no-connectivity"
SHILL_STATE_FAILURE = "failure"

SHILL_TYPE_ETHERNET = "ethernet"
SHILL_TYPE_WIFI = "wifi"
SHILL_TYPE_CELLULAR = "cellular"
SHILL_TYPE_VPN = "vpn"

# Shill draws a distinction Ash depends on.  SecurityClass says what the user
# has to supply and is the property the connection UI reads.  Security is the
# finer label shown next to the network name.
SECURITY_CLASS_NONE = "none"
SECURITY_CLASS_WEP = "wep"
SECURITY_CLASS_PSK = "psk"
SECURITY_CLASS_8021X = "802_1x"

SECURITY_NONE = "none"
SECURITY_WEP = "wep"
SECURITY_WPA = "wpa"
SECURITY_WPA2 = "wpa2"
SECURITY_WPA_WPA2 = "wpa+wpa2"
SECURITY_WPA3 = "wpa3"
SECURITY_WPA2_WPA3 = "wpa2+wpa3"
SECURITY_OWE = "owe"
SECURITY_TRANS_OWE = "trans-owe"
SECURITY_WPA_ENTERPRISE = "wpa-ent"
SECURITY_WPA2_ENTERPRISE = "wpa2-ent"
SECURITY_WPA_WPA2_ENTERPRISE = "wpa+wpa2-ent"
SECURITY_WPA3_ENTERPRISE = "wpa3-ent"

SHILL_ERROR_BAD_PASSPHRASE = "bad-passphrase"
SHILL_ERROR_CONNECT_FAILED = "connect-failed"
SHILL_ERROR_OUT_OF_RANGE = "out-of-range"
SHILL_ERROR_NOT_ASSOCIATED = "not-associated"
SHILL_ERROR_NO_FAILURE = "no-failure"

# A failed association says why in NetworkManager's own vocabulary.  Only the
# reasons that mean something to a person are translated; the rest fall back to
# a plain connect failure rather than inventing a cause.
NM_REASON_TO_SHILL_ERROR = {
    NM_REASON_NO_SECRETS: SHILL_ERROR_BAD_PASSPHRASE,
    NM_REASON_SUPPLICANT_CONFIG_FAILED: SHILL_ERROR_BAD_PASSPHRASE,
    NM_REASON_SUPPLICANT_FAILED: SHILL_ERROR_BAD_PASSPHRASE,
    NM_REASON_SUPPLICANT_TIMEOUT: SHILL_ERROR_NOT_ASSOCIATED,
    NM_REASON_SUPPLICANT_DISCONNECT: SHILL_ERROR_NOT_ASSOCIATED,
    NM_REASON_SSID_NOT_FOUND: SHILL_ERROR_OUT_OF_RANGE,
}
SHALLOW_PROFILE_PATH = "/profile/default"

# Shill's own object path scheme.  Ash is not merely reading these paths, it
# checks them: ShillServiceClient refuses any service path that does not begin
# with /service/ and then hands the network handler a state with no type, which
# fails a DCHECK and takes the session down.  Devices and IPConfigs are not
# checked, but they follow the same scheme so the tree reads like Shill's.
SERVICE_PREFIX = "/service/"
DEVICE_PREFIX = "/device/"
IPCONFIG_PREFIX = "/ipconfig/"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("shill-nm-adapter")


def _plain(value):
    """Convert dbus-python scalar/container values to Python values."""
    if isinstance(value, dbus.ByteArray):
        return bytes(value)
    if isinstance(value, (dbus.String, dbus.ObjectPath)):
        return str(value)
    if isinstance(value, dbus.Boolean):
        return bool(value)
    if isinstance(value, (dbus.Byte, dbus.Int16, dbus.UInt16, dbus.Int32,
                          dbus.UInt32, dbus.Int64, dbus.UInt64, dbus.Double)):
        return int(value)
    if isinstance(value, dict):
        return {_plain(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, dbus.Array)):
        return [_plain(item) for item in value]
    return value


def _as_int(value, default: int = 0) -> int:
    try:
        return int(_plain(value))
    except (TypeError, ValueError):
        return default


def _ssid_bytes(value) -> bytes:
    value = _plain(value)
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8", "replace")
    return bytes(value or b"")


def _ssid_text(value) -> str:
    raw = _ssid_bytes(value)
    return raw.decode("utf-8", "replace") if raw else "Hidden network"


def _stable_id(*parts: object) -> str:
    value = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(value).hexdigest()[:24]


def _get_mac(iface: str) -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            info = fcntl.ioctl(
                sock.fileno(), 0x8927, struct.pack("256s", iface[:15].encode())
            )
        return ":".join(f"{item:02x}" for item in info[18:24])
    except (OSError, struct.error):
        return "00:00:00:00:00:00"


def _object_path(value) -> dbus.ObjectPath:
    return dbus.ObjectPath(str(value))


def _object_paths(paths: Iterable[str]) -> dbus.Array:
    return dbus.Array([_object_path(path) for path in paths], signature="o")


def _generate_guid() -> str:
    return uuid.uuid4().hex


def wifi_security(flags, wpa_flags, rsn_flags) -> tuple[str, str, bool]:
    """Return the Shill security, its security class, and whether a passphrase
    is required, from an access point's NetworkManager flags."""
    flags = _as_int(flags)
    wpa = _as_int(wpa_flags)
    rsn = _as_int(rsn_flags)
    both = wpa | rsn

    if both & NM_AP_SEC_ENTERPRISE:
        if rsn & NM_AP_SEC_KEY_MGMT_SAE:
            name = SECURITY_WPA3_ENTERPRISE
        elif wpa and rsn:
            name = SECURITY_WPA_WPA2_ENTERPRISE
        elif rsn:
            name = SECURITY_WPA2_ENTERPRISE
        else:
            name = SECURITY_WPA_ENTERPRISE
        return name, SECURITY_CLASS_8021X, True

    sae = bool(rsn & NM_AP_SEC_KEY_MGMT_SAE)
    psk = bool(both & NM_AP_SEC_KEY_MGMT_PSK)
    if sae and psk:
        return SECURITY_WPA2_WPA3, SECURITY_CLASS_PSK, True
    if sae:
        return SECURITY_WPA3, SECURITY_CLASS_PSK, True
    if psk:
        if wpa and rsn:
            name = SECURITY_WPA_WPA2
        elif rsn:
            name = SECURITY_WPA2
        else:
            name = SECURITY_WPA
        return name, SECURITY_CLASS_PSK, True

    if both and not (rsn & NM_AP_SEC_OWE_ANY):
        # Some access points advertise ciphers without ever setting a key
        # management bit.  Protected is the safe reading of that, not open.
        if wpa and rsn:
            name = SECURITY_WPA_WPA2
        elif rsn:
            name = SECURITY_WPA2
        else:
            name = SECURITY_WPA
        return name, SECURITY_CLASS_PSK, True

    if rsn & NM_AP_SEC_OWE_ANY:
        # Enhanced Open encrypts the air without asking anyone for a word.
        name = SECURITY_TRANS_OWE if rsn & NM_AP_SEC_KEY_MGMT_OWE_TM else SECURITY_OWE
        return name, SECURITY_CLASS_NONE, False

    if flags & NM_AP_FLAGS_PRIVACY:
        return SECURITY_WEP, SECURITY_CLASS_WEP, True
    return SECURITY_NONE, SECURITY_CLASS_NONE, False


def key_management(security: str) -> str:
    """NetworkManager's key-mgmt for a Shill security name.  A transition mode
    network is joined as WPA2 so that hardware without SAE still associates."""
    if security == SECURITY_WPA3:
        return "sae"
    if security in (SECURITY_WPA, SECURITY_WPA2, SECURITY_WPA_WPA2, SECURITY_WPA2_WPA3):
        return "wpa-psk"
    return ""


def wifi_settings(ssid, security: str, passphrase: str | None, *, iface: str,
                  autoconnect: bool = True, hidden: bool = False) -> dict:
    """Build an NM profile.  The passphrase is never logged or returned by GetProperties."""
    settings = {
        "connection": {
            "id": dbus.String(_ssid_text(ssid)),
            "type": dbus.String("802-11-wireless"),
            "interface-name": dbus.String(iface),
            "autoconnect": dbus.Boolean(autoconnect),
        },
        "802-11-wireless": {
            "ssid": dbus.ByteArray(_ssid_bytes(ssid)),
            "mode": dbus.String("infrastructure"),
            # A hidden network never answers a broadcast probe, so NetworkManager
            # has to be told to ask for it by name.
            "hidden": dbus.Boolean(bool(hidden)),
        },
        "ipv4": {"method": dbus.String("auto")},
        "ipv6": {"method": dbus.String("auto")},
    }
    key_mgmt = key_management(security)
    if key_mgmt and passphrase:
        settings["802-11-wireless-security"] = {
            "key-mgmt": dbus.String(key_mgmt),
            "psk": dbus.String(passphrase),
        }
    elif security == SECURITY_WEP and passphrase:
        settings["802-11-wireless-security"] = {
            "key-mgmt": dbus.String("none"),
            "wep-key0": dbus.String(passphrase),
            "wep-key-type": dbus.UInt32(1),
        }
    return settings


def ethernet_settings(iface: str, *, autoconnect: bool = True) -> dict:
    return {
        "connection": {
            "id": dbus.String("Ethernet"),
            "type": dbus.String("802-3-ethernet"),
            "interface-name": dbus.String(iface),
            "autoconnect": dbus.Boolean(autoconnect),
        },
        "802-3-ethernet": {},
        "ipv4": {"method": dbus.String("auto")},
        "ipv6": {"method": dbus.String("auto")},
    }


def shill_service_path(kind: str, identity: str) -> str:
    """Where a service lives on the bus.  Ash checks this prefix and drops any
    service that does not carry it, so it is not cosmetic."""
    return f"{SERVICE_PREFIX}{kind}_{identity}"


def shill_device_path(iface: str) -> str:
    return f"{DEVICE_PREFIX}{iface}" if iface else "/"


def configured_device(monitor, svc_type: str, args: dict) -> tuple[str, str]:
    """The NetworkManager device path and interface for a network typed in by
    hand.  Such a request carries the network's own name and nothing about the
    radio it should use.  Name is the network, not the interface, and writing it
    into interface-name leaves NetworkManager holding a profile bound to a
    device that does not exist, which it then refuses to bring up."""
    device_path, iface = "", ""
    if monitor is not None:
        device_path, iface = monitor.first_device(svc_type)
    if not iface:
        iface = str(args.get(PROP_INTERFACE, ""))
    return device_path, iface


def _technology_is_enabled(kind: str, *, wireless_enabled: bool,
                            networking_enabled: bool) -> bool:
    """Translate NetworkManager's global and radio switches to Shill state."""
    if not networking_enabled:
        return False
    return kind != SHILL_TYPE_WIFI or wireless_enabled


def _device_state_to_shill(state: int, active: bool) -> str:
    if state == NM_DEVICE_STATE_FAILED:
        return SHILL_STATE_FAILURE if active else SHILL_STATE_IDLE
    if state in (NM_DEVICE_STATE_PREPARE, NM_DEVICE_STATE_CONFIG,
                 NM_DEVICE_STATE_NEED_AUTH):
        return SHILL_STATE_ASSOCIATION
    if state in (NM_DEVICE_STATE_IP_CONFIG, NM_DEVICE_STATE_IP_CHECK,
                 NM_DEVICE_STATE_SECONDARIES):
        return SHILL_STATE_CONFIGURATION
    if active and state == NM_DEVICE_STATE_ACTIVATED:
        return SHILL_STATE_ONLINE
    if state >= NM_DEVICE_STATE_DEACTIVATING:
        return SHILL_STATE_IDLE
    return SHILL_STATE_READY if state >= NM_DEVICE_STATE_DISCONNECTED else SHILL_STATE_IDLE


def _profile_for(saved: str):
    """Shill files a service under a profile only once it has been saved.  Ash
    reads any non empty profile as this is a known network, so handing the
    default profile to every access point in range files the whole
    neighbourhood under Known networks."""
    return _object_path(SHALLOW_PROFILE_PATH) if saved else dbus.String("")


def _service_state_to_shill(state: int, active: bool) -> str:
    """A network the machine is not on is idle, however busy the radio happens
    to be.  The device mapping answers ready for anything past disconnected,
    which is right for a device and wrong for a service: Ash reads ready as
    connected and lists every access point in the room as one."""
    if not active:
        return SHILL_STATE_IDLE
    return _device_state_to_shill(state, True)


class ShillDBus:
    def __init__(self, bus: dbus.Bus):
        self.bus = bus
        self._manager: Manager | None = None
        self._services: dict[str, Service] = {}
        self._devices: dict[str, Device] = {}
        self._ipconfigs: dict[str, IPConfig] = {}
        self._profiles: dict[str, Profile] = {}
        self._bus_name: dbus.service.BusName | None = None

    @property
    def manager(self) -> "Manager":
        return self._manager

    @manager.setter
    def manager(self, manager: "Manager") -> None:
        self._manager = manager

    @property
    def services(self) -> dict[str, "Service"]:
        return self._services

    @property
    def devices(self) -> dict[str, "Device"]:
        return self._devices

    @property
    def ipconfigs(self) -> dict[str, "IPConfig"]:
        return self._ipconfigs

    @property
    def profiles(self) -> dict[str, "Profile"]:
        return self._profiles

    def acquire_name(self) -> None:
        self._bus_name = dbus.service.BusName(
            SHILL_SERVICE, bus=self.bus, allow_replacement=True, replace_existing=True
        )
        log.info("Acquired bus name %s", SHILL_SERVICE)

    def release_name(self) -> None:
        if self._bus_name is not None:
            self._bus_name = None
            with contextlib.suppress(Exception):
                self.bus.release_name(SHILL_SERVICE)


class ShillObject(dbus.service.Object):
    """Common D-Bus property implementation for Shill objects."""

    _interface_name = ""

    def __init__(self, conn: dbus.bus.BusConnection, object_path: str):
        self._props: dict[str, object] = {}
        self._path = str(object_path)
        self._conn = conn
        super().__init__(conn, object_path)

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="ss", out_signature="v")
    def Get(self, interface: str, prop: str):
        if interface != self._interface_name or prop not in self._props:
            raise dbus.exceptions.DBusException(
                "org.freedesktop.DBus.Error.InvalidArgs", "Unknown property"
            )
        return self._props[prop]

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface: str) -> dict:
        if interface != self._interface_name:
            raise dbus.exceptions.DBusException(
                "org.freedesktop.DBus.Error.InvalidArgs", "Unknown interface"
            )
        return dict(self._props)

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="ssv", out_signature="")
    def Set(self, interface: str, prop: str, value) -> None:
        if interface != self._interface_name:
            raise dbus.exceptions.DBusException(
                "org.freedesktop.DBus.Error.InvalidArgs", "Unknown interface"
            )
        self._set_property(prop, value)

    @dbus.service.signal(dbus.PROPERTIES_IFACE, signature="sa{sv}as")
    def PropertiesChanged(self, interface: str, changed: dict, invalidated: list) -> None:
        pass

    def _emit_shill_property_changed(self, name: str, value) -> None:
        """Shill announces one property at a time on its own interface.  Ash
        subscribes to that signal and not to the standard properties one, so a
        list built only from PropertiesChanged would never move again after the
        first read."""
        try:
            message = dbus.lowlevel.SignalMessage(
                self._path, self._interface_name, "PropertyChanged"
            )
            message.append(name, value, signature="sv")
            self._conn.send_message(message)
        except Exception as exc:
            log.debug("Cannot announce %s on %s: %s", name, self._path, exc)

    def _set_property(self, name: str, value) -> None:
        if self._props.get(name) == value:
            return
        self._props[name] = value
        self.PropertiesChanged(self._interface_name, {name: value}, [])
        self._emit_shill_property_changed(name, value)

    def _set_properties(self, props: dict) -> None:
        changed = {key: value for key, value in props.items() if self._props.get(key) != value}
        if changed:
            self._props.update(changed)
            self.PropertiesChanged(self._interface_name, changed, [])
            for key, value in changed.items():
                self._emit_shill_property_changed(key, value)


class Manager(ShillObject):
    def __init__(self, conn: dbus.bus.BusConnection, path: str, shill: ShillDBus):
        self._interface_name = SHILL_MANAGER_IFACE
        self._shill = shill
        self._monitor: NetworkManagerMonitor | None = None
        self._nm_iface: dbus.Interface | None = None
        self._nm_props: dbus.Interface | None = None
        super().__init__(conn, path)
        self._props = {
            PROP_DEVICES: _object_paths([]),
            PROP_SERVICES: _object_paths([]),
            PROP_SERVICE_COMPLETE_LIST: _object_paths([]),
            PROP_ENABLED_TECHNOLOGIES: dbus.Array([], signature="s"),
            PROP_PROFILES: _object_paths([SHALLOW_PROFILE_PATH]),
            PROP_AVAILABLE_TECHNOLOGIES: dbus.Array([], signature="s"),
            PROP_CONNECTED_TECHNOLOGIES: dbus.Array([], signature="s"),
            PROP_DEFAULT_TECHNOLOGY: dbus.String(""),
            PROP_CHECK_PORTAL_LIST: dbus.String(""),
            PROP_ARP_GATEWAY: dbus.Boolean(False),
            PROP_STATE: dbus.String(SHILL_STATE_IDLE),
            PROP_DEFAULT_SERVICE: _object_path("/"),
        }

    def set_monitor(self, monitor: "NetworkManagerMonitor") -> None:
        self._monitor = monitor

    def set_nm_proxy(self, nm_iface: dbus.Interface, nm_props: dbus.Interface) -> None:
        self._nm_iface = nm_iface
        self._nm_props = nm_props
        self._refresh_technologies()

    def publish_devices(self) -> None:
        self._set_property(PROP_DEVICES, _object_paths(self._shill.devices))

    def publish_services(self) -> None:
        paths = list(self._shill.services)
        self._set_properties({
            PROP_SERVICES: _object_paths(paths),
            PROP_SERVICE_COMPLETE_LIST: _object_paths(paths),
        })

    def _refresh_technologies(self) -> None:
        if self._monitor:
            available, connected = self._monitor.technology_state()
            enabled = self._monitor.enabled_technology_state()
        else:
            available, enabled, connected = [], [], []
        default_service = "/"
        for path, service in self._shill.services.items():
            if str(service._props.get(PROP_STATE, "")) == SHILL_STATE_ONLINE:
                default_service = path
                break
        self._set_properties({
            PROP_AVAILABLE_TECHNOLOGIES: dbus.Array(available, signature="s"),
            PROP_ENABLED_TECHNOLOGIES: dbus.Array(enabled, signature="s"),
            PROP_CONNECTED_TECHNOLOGIES: dbus.Array(connected, signature="s"),
            PROP_DEFAULT_TECHNOLOGY: dbus.String(connected[0] if connected else (enabled[0] if enabled else "")),
            PROP_CHECK_PORTAL_LIST: dbus.String(connected[0] if connected else ""),
            PROP_STATE: dbus.String(SHILL_STATE_ONLINE if connected else SHILL_STATE_IDLE),
            PROP_DEFAULT_SERVICE: _object_path(default_service),
        })

    @dbus.service.method(SHILL_MANAGER_IFACE, out_signature="a{sv}")
    def GetProperties(self) -> dict:
        return dict(self._props)

    @dbus.service.method(SHILL_MANAGER_IFACE, in_signature="sv", out_signature="")
    def SetProperty(self, name: str, value) -> None:
        """Ash sets manager wide switches such as P2PAllowed on startup.  Shill
        answers these, so an adapter that does not is reported as a network
        error on every sign in."""
        self._set_property(str(name), value)

    @dbus.service.method(SHILL_MANAGER_IFACE, out_signature="a{sv}")
    def GetNetworksForGeolocation(self) -> dict:
        """Shill answers this with the access points in range so that a location
        can be looked up from them.  AuraDE does not hand the neighbourhood's
        radios to anybody, so the answer is empty by design.  It is answered
        rather than left missing because a missing method is reported as a
        network error on every sign in."""
        return dbus.Dictionary({}, signature="sv")

    @dbus.service.method(SHILL_MANAGER_IFACE, in_signature="u", out_signature="")
    def SetNetworkThrottlingStatus(self, rate: int) -> None:
        # NetworkManager has no rate limiter to hand this to.  Accepted so the
        # caller is answered, and deliberately not acted on.
        return

    @dbus.service.method(SHILL_MANAGER_IFACE, in_signature="as", out_signature="")
    def SetDNSProxyDOHProviders(self, providers: list) -> None:
        # Name resolution belongs to the host here, not to the desktop.
        return

    @dbus.service.method(SHILL_MANAGER_IFACE, in_signature="a{sv}", out_signature="o")
    def GetService(self, args: dict) -> dbus.ObjectPath:
        for path, service in self._shill.services.items():
            if all(service._props.get(key) == value for key, value in args.items()):
                return _object_path(path)
        return self._create_configured_service(args)

    @dbus.service.method(SHILL_MANAGER_IFACE, in_signature="a{sv}", out_signature="o")
    def ConfigureService(self, args: dict) -> dbus.ObjectPath:
        return self._create_configured_service(args)

    @dbus.service.method(SHILL_MANAGER_IFACE, in_signature="oa{sv}", out_signature="o")
    def ConfigureServiceForProfile(self, profile_path: dbus.ObjectPath, args: dict) -> dbus.ObjectPath:
        return self._create_configured_service(args, str(profile_path))

    @dbus.service.method(SHILL_MANAGER_IFACE, in_signature="", out_signature="")
    def ScanAndConnectToBestServices(self) -> None:
        if self._monitor:
            self._monitor.request_scan(SHILL_TYPE_WIFI)

    @dbus.service.method(SHILL_MANAGER_IFACE, in_signature="s", out_signature="")
    def RequestScan(self, type_str: str) -> None:
        if self._monitor:
            self._monitor.request_scan(str(type_str))

    @dbus.service.method(SHILL_MANAGER_IFACE, in_signature="s", out_signature="")
    def EnableTechnology(self, type_str: str) -> None:
        if self._monitor:
            self._monitor.set_technology(str(type_str), True)

    @dbus.service.method(SHILL_MANAGER_IFACE, in_signature="s", out_signature="")
    def DisableTechnology(self, type_str: str) -> None:
        if self._monitor:
            self._monitor.set_technology(str(type_str), False)

    @dbus.service.method(SHILL_MANAGER_IFACE, in_signature="a{sv}", out_signature="o")
    def FindMatchingService(self, args: dict) -> dbus.ObjectPath:
        for path, service in self._shill.services.items():
            if all(service._props.get(key) == value for key, value in args.items()):
                return _object_path(path)
        raise dbus.exceptions.DBusException(
            "org.chromium.flimflam.Error.NotFound", "No matching service found"
        )

    def _create_configured_service(self, args: dict, profile: str = SHALLOW_PROFILE_PATH) -> dbus.ObjectPath:
        svc_type = str(args.get(PROP_TYPE, SHILL_TYPE_ETHERNET))
        device_path, iface = configured_device(self._monitor, svc_type, args)
        guid = str(args.get(PROP_GUID, _generate_guid()))
        path = f"{SERVICE_PREFIX}{guid}"
        service = Service(
            self._shill.bus.get_connection(), path, self._shill, svc_type, iface, guid,
            monitor=self._monitor, profile=profile, initial_props=dict(args), configured=True,
            nm_device_path=device_path,
        )
        self._shill.services[path] = service
        self.publish_services()
        return _object_path(path)


class Service(ShillObject):
    def __init__(
        self, conn: dbus.bus.BusConnection, path: str, shill: ShillDBus,
        svc_type: str, iface_name: str, guid: str, *,
        monitor: "NetworkManagerMonitor | None" = None,
        profile: str = "",
        nm_device_path: str | None = None,
        ap_paths: Iterable[str] = (), nm_connection_path: str | None = None,
        initial_props: dict | None = None, configured: bool = False,
    ):
        self._interface_name = SHILL_SERVICE_IFACE
        self._shill = shill
        self._monitor = monitor
        self._svc_type = svc_type
        self._iface_name = iface_name
        self._guid = guid
        self._nm_device_path = str(nm_device_path or "")
        self._nm_ap_paths = {str(item) for item in ap_paths}
        self._nm_connection_path = str(nm_connection_path or "")
        self._passphrase: str | None = None
        self._configured = configured
        super().__init__(conn, path)
        device_path = shill_device_path(iface_name)
        self._props = {
            PROP_TYPE: dbus.String(svc_type), PROP_GUID: dbus.String(guid),
            PROP_NAME: dbus.String("Ethernet" if svc_type == SHILL_TYPE_ETHERNET else "Hidden network"),
            PROP_STATE: dbus.String(SHILL_STATE_IDLE), PROP_CONNECTABLE: dbus.Boolean(True),
            PROP_PROFILE: _profile_for(profile), PROP_DEVICE: _object_path(device_path),
            PROP_STRENGTH: dbus.Byte(0), PROP_AUTO_CONNECT: dbus.Boolean(True),
            PROP_VISIBLE: dbus.Boolean(True), PROP_SECURITY: dbus.String(SECURITY_NONE),
            PROP_SECURITY_CLASS: dbus.String(SECURITY_CLASS_NONE),
            PROP_HIDDEN_SSID: dbus.Boolean(False), PROP_ERROR_DETAILS: dbus.String(""),
            PROP_PASSPHRASE_REQUIRED: dbus.Boolean(False), PROP_ERROR: dbus.String(""),
        }
        if svc_type == SHILL_TYPE_WIFI:
            self._props[PROP_SSID] = dbus.ByteArray(b"")
        if initial_props:
            self._set_initial_props(initial_props)

    @property
    def nm_device_path(self) -> str:
        return self._nm_device_path

    @property
    def nm_ap_paths(self) -> set[str]:
        return self._nm_ap_paths

    @property
    def nm_connection_path(self) -> str:
        return self._nm_connection_path

    def _set_initial_props(self, props: dict) -> None:
        for key, value in props.items():
            if key == PROP_PASSPHRASE:
                self._passphrase = str(_plain(value))
            elif key in self._props:
                self._props[key] = value
        if PROP_NAME in props and PROP_SSID not in props and self._svc_type == SHILL_TYPE_WIFI:
            self._props[PROP_SSID] = dbus.ByteArray(_ssid_bytes(props[PROP_NAME]))

    @dbus.service.method(SHILL_SERVICE_IFACE, out_signature="a{sv}")
    def GetProperties(self) -> dict:
        return dict(self._props)

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="ssv", out_signature="")
    def Set(self, interface: str, prop: str, value) -> None:
        if interface != self._interface_name:
            raise dbus.exceptions.DBusException(
                "org.freedesktop.DBus.Error.InvalidArgs", "Unknown interface"
            )
        if prop == PROP_PASSPHRASE:
            self._passphrase = str(_plain(value))
            return
        if prop in self._props:
            self._set_property(prop, value)
            return
        raise dbus.exceptions.DBusException(
            "org.freedesktop.DBus.Error.InvalidArgs", "Unknown property"
        )

    @dbus.service.method(SHILL_SERVICE_IFACE, in_signature="a{sv}", out_signature="")
    def SetProperties(self, props: dict) -> None:
        public = {}
        for key, value in props.items():
            if key == PROP_PASSPHRASE:
                self._passphrase = str(_plain(value))
            elif key in self._props:
                public[key] = value
        self._set_properties(public)

    @dbus.service.method(SHILL_SERVICE_IFACE, out_signature="")
    def Connect(self) -> None:
        if self._monitor is None:
            raise dbus.exceptions.DBusException(
                "org.chromium.flimflam.Error.NotSupported", "NetworkManager is unavailable"
            )
        self._monitor.connect_service(self)

    @dbus.service.method(SHILL_SERVICE_IFACE, out_signature="")
    def Disconnect(self) -> None:
        if self._monitor:
            self._monitor.disconnect_service(self)

    @dbus.service.method(SHILL_SERVICE_IFACE, out_signature="")
    def Remove(self) -> None:
        if self._monitor:
            self._monitor.remove_service(self)
        else:
            self._shill.services.pop(self._path, None)

    def set_state(self, state: str) -> None:
        self._set_property(PROP_STATE, dbus.String(state))

    def set_error(self, message: str) -> None:
        self._set_properties({PROP_ERROR_DETAILS: dbus.String(message),
                              PROP_ERROR: dbus.String(SHILL_ERROR_CONNECT_FAILED),
                              PROP_STATE: dbus.String(SHILL_STATE_FAILURE)})

    def set_failure(self, error: str) -> None:
        """Record a named Shill failure.  A bad passphrase also has to put the
        service back into asking for one, or the person is shown a failure with
        no way to correct it."""
        props = {PROP_ERROR: dbus.String(error), PROP_STATE: dbus.String(SHILL_STATE_FAILURE)}
        if error == SHILL_ERROR_BAD_PASSPHRASE:
            self._passphrase = None
            props[PROP_PASSPHRASE_REQUIRED] = dbus.Boolean(True)
        self._set_properties(props)

    def clear_error(self) -> None:
        self._set_properties({PROP_ERROR: dbus.String(""), PROP_ERROR_DETAILS: dbus.String("")})

    def set_nm_identity(self, *, device_path: str, ap_paths: Iterable[str], connection_path: str | None = None) -> None:
        self._nm_device_path = str(device_path)
        self._nm_ap_paths = {str(item) for item in ap_paths}
        if connection_path is not None:
            self._nm_connection_path = str(connection_path)


class Device(ShillObject):
    def __init__(self, conn: dbus.bus.BusConnection, path: str, shill: ShillDBus,
                 iface_name: str, dev_type: str, mac: str):
        self._interface_name = SHILL_DEVICE_IFACE
        self._shill = shill
        ipconfig_path = f"{IPCONFIG_PREFIX}{iface_name}"
        super().__init__(conn, path)
        self._props = {
            PROP_TYPE: dbus.String(dev_type), PROP_NAME: dbus.String(iface_name),
            PROP_INTERFACE: dbus.String(iface_name), PROP_ADDRESS: dbus.String(mac),
            PROP_IPCONFIG: _object_path(ipconfig_path), PROP_IPCONFIGS: _object_paths([ipconfig_path]),
            PROP_POWER_SAVE: dbus.Boolean(False), PROP_STATE: dbus.String(SHILL_STATE_IDLE),
            # Ash draws the per technology toggle from Powered.  Without it the
            # radio reads as off while the machine is plainly online.
            PROP_POWERED: dbus.Boolean(True), PROP_SCANNING: dbus.Boolean(False),
        }
        if ipconfig_path not in shill.ipconfigs:
            shill.ipconfigs[ipconfig_path] = IPConfig(conn, ipconfig_path, iface_name)

    @dbus.service.method(SHILL_DEVICE_IFACE, out_signature="a{sv}")
    def GetProperties(self) -> dict:
        return dict(self._props)

    @dbus.service.method(SHILL_DEVICE_IFACE, in_signature="sv", out_signature="")
    def SetProperty(self, name: str, value) -> None:
        self._set_property(name, value)


class IPConfig(ShillObject):
    def __init__(self, conn: dbus.bus.BusConnection, path: str, iface_name: str):
        self._interface_name = SHILL_IPCONFIG_IFACE
        super().__init__(conn, path)
        self._props = {
            PROP_ADDRESS: dbus.String("0.0.0.0"), PROP_METHOD: dbus.String("ipv4"),
            PROP_NAME_SERVERS: dbus.Array([], signature="s"),
        }

    @dbus.service.method(SHILL_IPCONFIG_IFACE, out_signature="a{sv}")
    def GetProperties(self) -> dict:
        return dict(self._props)


class Profile(ShillObject):
    def __init__(self, conn: dbus.bus.BusConnection, path: str, shill: ShillDBus):
        self._interface_name = SHILL_PROFILE_IFACE
        self._shill = shill
        super().__init__(conn, path)
        self._props = {PROP_NAME: dbus.String("default")}

    @dbus.service.method(SHILL_PROFILE_IFACE, out_signature="a{sv}")
    def GetProperties(self) -> dict:
        return dict(self._props)

    @dbus.service.method(SHILL_PROFILE_IFACE, in_signature="a{sv}", out_signature="")
    def SetProperties(self, props: dict) -> None:
        self._set_properties(props)

    @dbus.service.method(SHILL_PROFILE_IFACE, out_signature="ao")
    def GetServices(self) -> list:
        return [_object_path(path) for path in self._shill.services]

    @dbus.service.method(SHILL_PROFILE_IFACE, in_signature="s", out_signature="")
    def DeleteEntry(self, entry_path: str) -> None:
        service = self._shill.services.get(str(entry_path))
        if service is not None:
            service.Remove()


NM_TYPE_TO_SHILL = {
    NM_DEVICE_TYPE_ETHERNET: SHILL_TYPE_ETHERNET,
    NM_DEVICE_TYPE_WIFI: SHILL_TYPE_WIFI,
}


class NetworkManagerMonitor:
    def __init__(self, bus: dbus.Bus, shill: ShillDBus):
        self._bus = bus
        self._shill = shill
        self._nm_obj = bus.get_object(NM_SERVICE, NM_PATH)
        self._nm_iface = dbus.Interface(self._nm_obj, NM_IFACE)
        self._nm_props = dbus.Interface(self._nm_obj, dbus.PROPERTIES_IFACE)
        settings_obj = bus.get_object(NM_SERVICE, NM_SETTINGS_PATH)
        self._settings_iface = dbus.Interface(settings_obj, NM_SETTINGS_IFACE)
        self._nm_devices: dict[str, dict[str, object]] = {}
        self._ap_to_service: dict[str, str] = {}
        self._device_to_services: dict[str, set[str]] = {}
        self._watched_devices: set[str] = set()
        self._watched_aps: set[str] = set()

    def start(self) -> None:
        self._shill.manager.set_monitor(self)
        self._shill.manager.set_nm_proxy(self._nm_iface, self._nm_props)
        self._sync_devices()
        self._nm_obj.connect_to_signal("DeviceAdded", self._on_device_added, dbus_interface=NM_IFACE)
        self._nm_obj.connect_to_signal("DeviceRemoved", self._on_device_removed, dbus_interface=NM_IFACE)
        self._nm_props.connect_to_signal("PropertiesChanged", self._on_nm_properties_changed)
        GLib.timeout_add_seconds(10, self._periodic_sync)
        log.info("NetworkManager monitor started with %d device(s)", len(self._nm_devices))

    def technology_state(self) -> tuple[list[str], list[str]]:
        available: list[str] = []
        connected: list[str] = []
        for info in self._nm_devices.values():
            kind = str(info["type"])
            if kind not in available:
                available.append(kind)
            if _as_int(info.get("state")) == NM_DEVICE_STATE_ACTIVATED and kind not in connected:
                connected.append(kind)
        return available, connected

    def enabled_technology_state(self) -> list[str]:
        try:
            networking_enabled = bool(self._nm_props.Get(NM_IFACE, "NetworkingEnabled"))
        except Exception:
            networking_enabled = True
        try:
            wireless_enabled = bool(self._nm_props.Get(NM_IFACE, "WirelessEnabled"))
        except Exception:
            wireless_enabled = True
        enabled: list[str] = []
        for info in self._nm_devices.values():
            kind = str(info["type"])
            if kind not in enabled and _technology_is_enabled(
                    kind,
                    wireless_enabled=wireless_enabled,
                    networking_enabled=networking_enabled):
                enabled.append(kind)
        return enabled

    def _obj(self, path: str):
        return self._bus.get_object(NM_SERVICE, path)

    def _props_for(self, path: str) -> dbus.Interface:
        return dbus.Interface(self._obj(path), dbus.PROPERTIES_IFACE)

    def _device_info(self, path: str) -> dict[str, object] | None:
        try:
            props = self._props_for(path)
            dtype = _as_int(props.Get(NM_DEVICE_IFACE, "DeviceType"))
            shill_type = NM_TYPE_TO_SHILL.get(dtype)
            if not shill_type:
                return None
            return {
                "type": shill_type,
                "state": _as_int(props.Get(NM_DEVICE_IFACE, "State")),
                "iface": str(props.Get(NM_DEVICE_IFACE, "Interface")),
                "mac": str(props.Get(NM_DEVICE_IFACE, "HwAddress")),
            }
        except Exception as exc:
            log.warning("Cannot read NetworkManager device %s: %s", path, exc)
            return None

    def _sync_devices(self) -> None:
        try:
            paths = [str(path) for path in self._nm_iface.GetDevices()]
        except Exception as exc:
            log.warning("Cannot enumerate NetworkManager devices: %s", exc)
            paths = []
        for path in list(self._nm_devices):
            if path not in paths:
                self._remove_device(path)
        for path in paths:
            self._add_device(path)
        self._publish()

    def _add_device(self, path: str) -> None:
        info = self._device_info(path)
        if not info:
            return
        self._nm_devices[path] = info
        iface = str(info["iface"])
        shill_path = shill_device_path(iface)
        if shill_path not in self._shill.devices:
            self._shill.devices[shill_path] = Device(
                self._bus.get_connection(), shill_path, self._shill,
                iface, str(info["type"]), str(info["mac"]),
            )
        self._watch_device(path)
        if info["type"] == SHILL_TYPE_WIFI:
            self._sync_access_points(path)
        else:
            self._sync_ethernet_service(path)

    def _remove_device(self, path: str) -> None:
        for service_path in self._device_to_services.pop(path, set()):
            self._drop_service(service_path)
        info = self._nm_devices.pop(path, None)
        if info:
            device = self._shill.devices.pop(
                shill_device_path(info["iface"]), None
            )
            if device is not None:
                with contextlib.suppress(Exception):
                    device.remove_from_connection()
        self._publish()

    def _watch_device(self, path: str) -> None:
        if path in self._watched_devices:
            return
        self._watched_devices.add(path)
        try:
            obj = self._obj(path)
            props = dbus.Interface(obj, dbus.PROPERTIES_IFACE)
            props.connect_to_signal(
                "PropertiesChanged",
                lambda iface, changed, invalid, device=path: self._on_device_props_changed(device, changed),
            )
            if self._nm_devices[path]["type"] == SHILL_TYPE_WIFI:
                wifi = dbus.Interface(obj, NM_WIFI_DEVICE_IFACE)
                wifi.connect_to_signal(
                    "AccessPointAdded",
                    lambda ap, device=path: self._sync_access_points(device),
                )
                wifi.connect_to_signal(
                    "AccessPointRemoved",
                    lambda ap, device=path: self._sync_access_points(device),
                )
        except Exception as exc:
            log.warning("Cannot watch NetworkManager device %s: %s", path, exc)

    def _watch_ap(self, path: str) -> None:
        if path in self._watched_aps:
            return
        self._watched_aps.add(path)
        try:
            props = self._props_for(path)
            props.connect_to_signal(
                "PropertiesChanged",
                lambda iface, changed, invalid, ap=path: self._on_ap_props_changed(ap),
            )
        except Exception as exc:
            log.debug("Cannot watch access point %s: %s", path, exc)

    def _ap_info(self, path: str) -> dict[str, object] | None:
        try:
            props = self._props_for(path)
            ssid = _ssid_bytes(props.Get(NM_AP_IFACE, "Ssid"))
            security, security_class, required = wifi_security(
                props.Get(NM_AP_IFACE, "Flags"),
                props.Get(NM_AP_IFACE, "WpaFlags"),
                props.Get(NM_AP_IFACE, "RsnFlags"),
            )
            return {
                "ssid": ssid, "name": _ssid_text(ssid),
                "strength": max(0, min(100, _as_int(props.Get(NM_AP_IFACE, "Strength")))),
                "security": security, "security_class": security_class,
                "required": required,
            }
        except Exception as exc:
            log.debug("Cannot read access point %s: %s", path, exc)
            return None

    def _saved_connection(self, ssid: bytes, iface: str, connection_type: str) -> str:
        try:
            for path in self._settings_iface.ListConnections():
                conn = dbus.Interface(self._obj(str(path)), NM_SETTINGS_CONNECTION_IFACE)
                settings = _plain(conn.GetSettings())
                connection = settings.get("connection", {})
                if connection.get("type") != connection_type:
                    continue
                if connection.get("interface-name", iface) not in (None, iface):
                    continue
                if connection_type == "802-11-wireless":
                    # NetworkManager hands the saved SSID back as an array of
                    # bytes, not a byte array, so a direct comparison against
                    # the scanned SSID never matches and every saved network
                    # looks new.
                    saved = _ssid_bytes(settings.get("802-11-wireless", {}).get("ssid", b""))
                    if saved != _ssid_bytes(ssid):
                        continue
                return str(path)
        except Exception as exc:
            log.debug("Cannot inspect saved NetworkManager connections: %s", exc)
        return ""

    def _sync_access_points(self, device_path: str) -> None:
        info = self._nm_devices.get(device_path)
        if not info:
            return
        try:
            wifi = dbus.Interface(self._obj(device_path), NM_WIFI_DEVICE_IFACE)
            ap_paths = [str(path) for path in wifi.GetAccessPoints()]
        except Exception as exc:
            log.debug("Cannot enumerate access points for %s: %s", device_path, exc)
            ap_paths = []
        groups: dict[bytes, list[tuple[str, dict[str, object]]]] = {}
        for ap_path in ap_paths:
            ap_info = self._ap_info(ap_path)
            if not ap_info or not ap_info["ssid"]:
                continue
            groups.setdefault(ap_info["ssid"], []).append((ap_path, ap_info))
            self._watch_ap(ap_path)
        old = set(self._device_to_services.get(device_path, set()))
        current: set[str] = set()
        for ssid, entries in groups.items():
            entries.sort(key=lambda item: int(item[1]["strength"]), reverse=True)
            best_path, best = entries[0]
            service_path = shill_service_path("wifi", _stable_id(device_path, ssid))
            connection_path = self._saved_connection(ssid, str(info["iface"]), "802-11-wireless")
            service = self._shill.services.get(service_path)
            if service is None:
                service = Service(
                    self._bus.get_connection(), service_path, self._shill,
                    SHILL_TYPE_WIFI, str(info["iface"]), _stable_id(device_path, ssid),
                    monitor=self, nm_device_path=device_path,
                    ap_paths=[path for path, _ in entries], nm_connection_path=connection_path,
                )
                self._shill.services[service_path] = service
            else:
                service.set_nm_identity(
                    device_path=device_path,
                    ap_paths=[path for path, _ in entries],
                    connection_path=connection_path,
                )
            service._set_properties({
                PROP_NAME: dbus.String(str(best["name"])),
                PROP_SSID: dbus.ByteArray(ssid),
                PROP_STRENGTH: dbus.Byte(int(best["strength"])),
                PROP_SECURITY: dbus.String(str(best["security"])),
                PROP_SECURITY_CLASS: dbus.String(str(best["security_class"])),
                PROP_PROFILE: _profile_for(connection_path),
                PROP_PASSPHRASE_REQUIRED: dbus.Boolean(bool(best["required"] and not connection_path)),
                PROP_DEVICE: _object_path(shill_device_path(info["iface"])),
                PROP_VISIBLE: dbus.Boolean(True),
            })
            current.add(service_path)
            for ap_path, _ in entries:
                self._ap_to_service[ap_path] = service_path
        for service_path in old - current:
            self._drop_service(service_path)
        self._device_to_services[device_path] = current
        self._set_scanning(device_path, False)
        self._refresh_service_states(device_path)
        self._publish()

    def _sync_ethernet_service(self, device_path: str) -> None:
        info = self._nm_devices.get(device_path)
        if not info:
            return
        service_path = shill_service_path("ethernet", _stable_id(device_path))
        connection_path = self._saved_connection(b"", str(info["iface"]), "802-3-ethernet")
        service = self._shill.services.get(service_path)
        if service is None:
            service = Service(
                self._bus.get_connection(), service_path, self._shill,
                SHILL_TYPE_ETHERNET, str(info["iface"]), _stable_id(device_path),
                monitor=self, nm_device_path=device_path, nm_connection_path=connection_path,
            )
            self._shill.services[service_path] = service
        else:
            service.set_nm_identity(device_path=device_path, ap_paths=(), connection_path=connection_path)
        service._set_properties({
            PROP_NAME: dbus.String("Ethernet"),
            PROP_PROFILE: _profile_for(connection_path),
        })
        self._device_to_services[device_path] = {service_path}
        self._refresh_service_states(device_path)
        self._publish()

    def _refresh_service_states(self, device_path: str) -> None:
        info = self._nm_devices.get(device_path)
        if not info:
            return
        reason = 0
        try:
            props = self._props_for(device_path)
            state = _as_int(props.Get(NM_DEVICE_IFACE, "State"))
            active_connection = str(props.Get(NM_DEVICE_IFACE, "ActiveConnection"))
            active_ap = str(props.Get(NM_WIFI_DEVICE_IFACE, "ActiveAccessPoint")) if info["type"] == SHILL_TYPE_WIFI else "/"
            with contextlib.suppress(Exception):
                reason = _as_int(tuple(props.Get(NM_DEVICE_IFACE, "StateReason"))[1])
        except Exception:
            state = _as_int(info.get("state"))
            active_connection = "/"
            active_ap = "/"
        info["state"] = state
        failure = NM_REASON_TO_SHILL_ERROR.get(reason, SHILL_ERROR_CONNECT_FAILED)
        for service_path in self._device_to_services.get(device_path, set()):
            service = self._shill.services.get(service_path)
            if service is None:
                continue
            active = service.nm_connection_path == active_connection or active_ap in service.nm_ap_paths
            if state == NM_DEVICE_STATE_FAILED and active:
                # Say which way it failed.  A wrong word is not the same as a
                # network that walked out of range, and the person retyping it
                # deserves to be told which happened.
                service.set_failure(failure)
            else:
                if active:
                    service.clear_error()
                service.set_state(_service_state_to_shill(state, active))
        device = self._shill.devices.get(shill_device_path(info["iface"]))
        if device is not None:
            device._set_property(
                PROP_STATE,
                dbus.String(_device_state_to_shill(state, bool(active_connection != "/"))),
            )

    def _set_scanning(self, device_path: str, scanning: bool) -> None:
        info = self._nm_devices.get(device_path)
        if not info:
            return
        device = self._shill.devices.get(shill_device_path(info["iface"]))
        if device is not None:
            device._set_property(PROP_SCANNING, dbus.Boolean(scanning))

    def first_device(self, kind: str) -> tuple[str, str]:
        """The NetworkManager device path and interface name to hang a manually
        configured network on."""
        for path, info in self._nm_devices.items():
            if str(info["type"]) == kind:
                return path, str(info["iface"])
        return "", ""

    def request_scan(self, type_str: str) -> None:
        if type_str not in ("", SHILL_TYPE_WIFI):
            return
        for device_path, info in self._nm_devices.items():
            if info["type"] != SHILL_TYPE_WIFI:
                continue
            try:
                dbus.Interface(self._obj(device_path), NM_WIFI_DEVICE_IFACE).RequestScan({})
                self._set_scanning(device_path, True)
            except Exception as exc:
                raise dbus.exceptions.DBusException(
                    "org.chromium.flimflam.Error.OperationFailed", str(exc)
                ) from exc

    def set_technology(self, type_str: str, enabled: bool) -> None:
        try:
            if type_str == SHILL_TYPE_WIFI:
                self._nm_props.Set(NM_IFACE, "WirelessEnabled", dbus.Boolean(enabled))
            elif type_str == SHILL_TYPE_ETHERNET:
                self._nm_props.Set(NM_IFACE, "NetworkingEnabled", dbus.Boolean(enabled))
            self._shill.manager._refresh_technologies()
        except Exception as exc:
            raise dbus.exceptions.DBusException(
                "org.chromium.flimflam.Error.OperationFailed", str(exc)
            ) from exc

    def _connection_proxy(self, path: str):
        return dbus.Interface(self._obj(path), NM_SETTINGS_CONNECTION_IFACE)

    def _settings_for_service(self, service: Service) -> dict:
        if not service.nm_connection_path:
            return {}
        try:
            return _plain(self._connection_proxy(service.nm_connection_path).GetSettings())
        except Exception:
            return {}

    def _settings_for_connect(self, service: Service) -> dict:
        if service._svc_type == SHILL_TYPE_WIFI:
            return wifi_settings(
                service._props.get(PROP_SSID, dbus.ByteArray(b"")),
                str(service._props.get(PROP_SECURITY, "none")),
                service._passphrase,
                iface=service._iface_name,
                autoconnect=bool(service._props.get(PROP_AUTO_CONNECT, True)),
                hidden=bool(service._props.get(PROP_HIDDEN_SSID, False)),
            )
        return ethernet_settings(service._iface_name, autoconnect=bool(service._props.get(PROP_AUTO_CONNECT, True)))

    def connect_service(self, service: Service) -> None:
        service.clear_error()
        service.set_state(SHILL_STATE_ASSOCIATION)
        if service._svc_type == SHILL_TYPE_WIFI and bool(service._props.get(PROP_PASSPHRASE_REQUIRED)) and not service._passphrase:
            service._set_property(PROP_PASSPHRASE_REQUIRED, dbus.Boolean(True))
            raise dbus.exceptions.DBusException(
                "org.chromium.flimflam.Error.PassphraseRequired", "A passphrase is required"
            )
        try:
            settings = self._settings_for_connect(service)
            device = _object_path(service.nm_device_path or "/")
            specific = _object_path(next(iter(service.nm_ap_paths), "/"))
            if service.nm_connection_path:
                if service._passphrase or not self._settings_for_service(service):
                    self._connection_proxy(service.nm_connection_path).Update(settings)
                self._nm_iface.ActivateConnection(
                    _object_path(service.nm_connection_path), device, specific
                )
            else:
                _, connection_path = self._nm_iface.AddAndActivateConnection(settings, device, specific)
                service._nm_connection_path = str(connection_path)
            self._refresh_service_states(service.nm_device_path)
        except dbus.exceptions.DBusException:
            raise
        except Exception as exc:
            message = str(exc).splitlines()[0][:240]
            service.set_error(message)
            raise dbus.exceptions.DBusException(
                "org.chromium.flimflam.Error.OperationFailed", message
            ) from exc

    def disconnect_service(self, service: Service) -> None:
        try:
            props = self._props_for(service.nm_device_path)
            active = str(props.Get(NM_DEVICE_IFACE, "ActiveConnection"))
            if active != "/":
                self._nm_iface.DeactivateConnection(_object_path(active))
            service.set_state(SHILL_STATE_READY)
            self._refresh_service_states(service.nm_device_path)
        except Exception as exc:
            message = str(exc).splitlines()[0][:240]
            service.set_error(message)
            raise dbus.exceptions.DBusException(
                "org.chromium.flimflam.Error.OperationFailed", message
            ) from exc

    def remove_service(self, service: Service) -> None:
        if service.nm_connection_path:
            with contextlib.suppress(Exception):
                self._connection_proxy(service.nm_connection_path).Delete()
        if service._svc_type == SHILL_TYPE_WIFI and service.nm_ap_paths:
            service._nm_connection_path = ""
            service._passphrase = None
            service.clear_error()
            return
        self._drop_service(service._path)
        self._publish()

    def _drop_service(self, path: str) -> None:
        service = self._shill.services.pop(path, None)
        if service is None:
            return
        for ap_path in service.nm_ap_paths:
            self._ap_to_service.pop(ap_path, None)
        with contextlib.suppress(Exception):
            service.remove_from_connection()

    def _publish(self) -> None:
        self._shill.manager.publish_devices()
        self._shill.manager.publish_services()
        self._shill.manager._refresh_technologies()

    def _on_device_added(self, path: str) -> None:
        self._add_device(str(path))
        self._publish()

    def _on_device_removed(self, path: str) -> None:
        self._remove_device(str(path))

    def _on_device_props_changed(self, path: str, changed: dict) -> None:
        if path not in self._nm_devices:
            return
        if "State" in changed:
            self._nm_devices[path]["state"] = _as_int(changed["State"])
        self._refresh_service_states(path)
        self._shill.manager._refresh_technologies()

    def _on_ap_props_changed(self, ap_path: str) -> None:
        service_path = self._ap_to_service.get(ap_path)
        if service_path is not None and service_path in self._shill.services:
            self._sync_access_points(self._shill.services[service_path].nm_device_path)

    def _on_nm_properties_changed(self, iface: str, changed: dict, invalid: list) -> None:
        self._shill.manager._refresh_technologies()

    def _periodic_sync(self) -> bool:
        self._sync_devices()
        return True


def main() -> None:
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    shill = ShillDBus(bus)
    shill.acquire_name()
    manager = Manager(bus.get_connection(), SHILL_MANAGER_PATH, shill)
    shill.manager = manager
    profile = Profile(bus.get_connection(), SHALLOW_PROFILE_PATH, shill)
    shill.profiles[SHALLOW_PROFILE_PATH] = profile
    monitor = NetworkManagerMonitor(bus, shill)
    monitor.start()
    log.info("shill-nm-adapter ready")
    try:
        GLib.MainLoop().run()
    except KeyboardInterrupt:
        pass
    finally:
        shill.release_name()
        log.info("shill-nm-adapter stopped")


if __name__ == "__main__":
    main()
