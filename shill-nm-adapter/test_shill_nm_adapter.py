#!/usr/bin/env python3
"""Pure tests for the Shill to NetworkManager translation rules.

The build host does not need a system D-Bus or NetworkManager daemon for these
checks.  Small local stubs let us test the part that must remain deterministic:
real access points become visible services, empty SSIDs do not, and secrets do
not enter the public Shill property dictionary.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types


def _install_stubs() -> None:
    dbus = types.ModuleType("dbus")
    dbus.PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"
    dbus.Array = lambda value=(), signature=None: list(value)
    dbus.ByteArray = bytes
    dbus.Boolean = bool
    dbus.Byte = int
    dbus.Int32 = int
    dbus.ObjectPath = str
    dbus.String = str
    dbus.Variant = object
    dbus.Interface = lambda obj, iface: obj

    class DBusException(Exception):
        pass

    exceptions = types.ModuleType("dbus.exceptions")
    exceptions.DBusException = DBusException
    dbus.exceptions = exceptions

    service = types.ModuleType("dbus.service")
    service.Object = type("Object", (), {
        "__init__": lambda self, conn, path: None,
        "remove_from_connection": lambda self: None,
    })
    service.BusName = object
    service.method = lambda *args, **kwargs: (lambda fn: fn)
    service.signal = lambda *args, **kwargs: (lambda fn: fn)
    dbus.service = service

    bus = types.ModuleType("dbus.bus")
    bus.BusConnection = object
    dbus.bus = bus
    mainloop = types.ModuleType("dbus.mainloop")
    mainloop_glib = types.ModuleType("dbus.mainloop.glib")
    mainloop_glib.DBusGMainLoop = lambda **kwargs: None
    mainloop.glib = mainloop_glib

    class GLibStub:
        @staticmethod
        def source_remove(_source):
            return None

        @staticmethod
        def timeout_add(_delay, _callback):
            return 1

    gi = types.ModuleType("gi")
    repository = types.ModuleType("gi.repository")
    repository.GLib = GLibStub
    gi.repository = repository

    sys.modules.update({
        "dbus": dbus,
        "dbus.bus": bus,
        "dbus.exceptions": exceptions,
        "dbus.service": service,
        "dbus.mainloop": mainloop,
        "dbus.mainloop.glib": mainloop_glib,
        "gi": gi,
        "gi.repository": repository,
    })


def _load():
    _install_stubs()
    path = pathlib.Path(__file__).with_name("shill_nm_adapter.py")
    spec = importlib.util.spec_from_file_location("shill_nm_adapter_tested", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


adapter = _load()


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    # A Wi-Fi-only machine must not inherit the old static Ethernet entry.
    # This is deliberately a pure assertion over the publication rules so it
    # remains testable without a system NetworkManager daemon.
    wifi_props = adapter._technology_properties(
        [adapter.SHILL_TYPE_WIFI, adapter.SHILL_TYPE_WIFI],
        [adapter.SHILL_TYPE_WIFI],
    )
    check(wifi_props[adapter.PROP_ENABLED_TECHNOLOGIES] == [adapter.SHILL_TYPE_WIFI],
          "Wi-Fi-only technology inventory contains a placeholder")
    check(wifi_props[adapter.PROP_DEFAULT_TECHNOLOGY] == adapter.SHILL_TYPE_WIFI,
          "Wi-Fi was not selected as the default technology")
    check(wifi_props[adapter.PROP_CHECK_PORTAL_LIST] == adapter.SHILL_TYPE_WIFI,
          "portal checks still advertise a missing technology")

    secured = adapter._access_point_record({
        "Ssid": b"Home WiFi",
        "HwAddress": "aa:bb:cc:dd:ee:ff",
        "Strength": 118,
        "Flags": 1,
        "WpaFlags": 0,
        "RsnFlags": 0x100,
        "Frequency": 2412,
    })
    check(secured is not None, "a real SSID was discarded")
    check(secured["name"] == "Home WiFi", "SSID name was not preserved")
    check(secured["hex_ssid"] == "486f6d652057694669", "HexSSID is incorrect")
    check(secured["strength"] == 100, "strength was not clamped to Shill's range")
    check(secured["security"] == "psk", "WPA or RSN was not classified as PSK")

    open_ap = adapter._access_point_record({
        "Ssid": b"Cafe",
        "HwAddress": "00:11:22:33:44:55",
        "Strength": 44,
        "Flags": 0,
        "WpaFlags": 0,
        "RsnFlags": 0,
    })
    check(open_ap["security"] == "none", "an open AP was marked encrypted")
    check(adapter._access_point_record({"Ssid": b""}) is None,
          "a hidden SSID was exposed as a blank network")

    malformed = adapter._access_point_record({"Ssid": b"bad\xffssid"})
    check("\ufffd" in malformed["name"], "invalid SSID bytes were not made UTF-8 safe")

    fake_shill = object.__new__(adapter.ShillDBus)
    fake_shill._manager = types.SimpleNamespace(_set_properties=lambda props: setattr(fake_shill, "published", props))
    fake_shill._services = {
        "/visible": types.SimpleNamespace(_props={adapter.PROP_VISIBLE: True}),
        "/hidden": types.SimpleNamespace(_props={adapter.PROP_VISIBLE: False}),
    }
    fake_shill.update_service_lists()
    check(fake_shill.published[adapter.PROP_SERVICES] == ["/visible"],
          "hidden services leaked into the visible service list")
    check(fake_shill.published[adapter.PROP_SERVICE_COMPLETE_LIST] == ["/visible", "/hidden"],
          "the complete service list lost a configured service")

    fake_store = types.SimpleNamespace(services={}, devices={}, ipconfigs={})
    service = adapter.Service(object(), "/service/one", fake_store, adapter.SHILL_TYPE_WIFI,
                              "Home WiFi", "one", ssid=b"Home WiFi", record=secured)
    service.set_property(adapter.PROP_PASSPHRASE, "do not publish me")
    check(adapter.PROP_PASSPHRASE not in service.GetProperties(),
          "Wi-Fi passphrase entered the public property dictionary")
    check(service.GetWiFiPassphrase() == "do not publish me",
          "the private passphrase was not retained for connection")
    service.set_state(adapter.SHILL_STATE_READY)
    check(service._props[adapter.PROP_IS_CONNECTED] is False,
          "a ready Wi-Fi service was marked connected")
    service.set_state(adapter.SHILL_STATE_ONLINE)
    check(service._props[adapter.PROP_IS_CONNECTED] is True,
          "an online Wi-Fi service was not marked connected")

    class FakeProps:
        def __init__(self, values):
            self.values = values

        def Get(self, _interface, name):
            return self.values[name]

        def GetAll(self, _interface):
            return dict(self.values)

        def connect_to_signal(self, *_args, **_kwargs):
            return None

    class FakeWifi(FakeProps):
        def GetAccessPoints(self):
            return ["/ap/one"]

        def RequestScan(self, _args):
            return None

    class FakeBus:
        def __init__(self):
            self.device = FakeWifi({
                "DeviceType": adapter.NM_DEVICE_TYPE_WIFI,
                "State": adapter.NM_DEVICE_STATE_DISCONNECTED,
                "Interface": "wlan0",
                "HwAddress": "00:11:22:33:44:55",
                "ActiveAccessPoint": "/",
            })
            self.ap = FakeProps({
                "Ssid": b"Home WiFi",
                "HwAddress": "aa:bb:cc:dd:ee:ff",
                "Strength": 73,
                "Flags": 1,
                "WpaFlags": 0,
                "RsnFlags": 0x100,
            })

        def get_object(self, _service, path):
            return {
                "/dev/wlan0": self.device,
                "/ap/one": self.ap,
            }[str(path)]

        def get_connection(self):
            return object()

    bus = FakeBus()
    fake_manager = types.SimpleNamespace(
        _set_property=lambda *_args: None,
        _refresh_technologies=lambda: None,
    )
    fake_shill = types.SimpleNamespace(
        bus=bus,
        manager=fake_manager,
        services={},
        devices={},
        ipconfigs={},
        update_service_lists=lambda: None,
    )
    monitor = object.__new__(adapter.NetworkManagerMonitor)
    monitor._bus = bus
    monitor._shill = fake_shill
    monitor._nm_devices = {}
    monitor._services_by_device = {}
    monitor._service_keys = {}
    monitor._service_meta = {}
    monitor._watched_devices = set()
    monitor._watched_wifi = set()
    monitor._scan_source = 0
    monitor._nm_iface = types.SimpleNamespace()
    monitor._nm_props = types.SimpleNamespace()
    monitor._add_device("/dev/wlan0")
    check(len(fake_shill.services) == 1,
          "one real AP did not become one Shill service")
    listed = next(iter(fake_shill.services.values()))
    check(listed._props[adapter.PROP_NAME] == "Home WiFi",
          "the adapter exposed the interface name instead of the SSID")
    check(listed._props[adapter.PROP_VISIBLE] is True,
          "a discovered AP was not visible")
    check(all("wlan0" not in str(path) for path in fake_shill.services),
          "the Wi-Fi interface itself became a dummy service")

    bus.device.values["State"] = adapter.NM_DEVICE_STATE_ACTIVATED
    bus.device.values["ActiveAccessPoint"] = "/ap/one"
    monitor._sync_wifi_services("/dev/wlan0")
    check(listed._props[adapter.PROP_STATE] == adapter.SHILL_STATE_ONLINE,
          "the active NetworkManager AP was not reported online")
    check(listed._props[adapter.PROP_IS_CONNECTED] is True,
          "the active NetworkManager AP was not reported connected")

    bus.device.values["State"] = adapter.NM_DEVICE_STATE_DISCONNECTED
    bus.device.values["ActiveAccessPoint"] = "/"
    monitor._sync_wifi_services("/dev/wlan0")
    check(listed._props[adapter.PROP_STATE] == adapter.SHILL_STATE_READY,
          "a disconnected Wi-Fi device did not expose a ready AP")
    check(listed._props[adapter.PROP_IS_CONNECTED] is False,
          "a disconnected Wi-Fi AP remained marked connected")
    print("shill adapter translation test: PASS")


if __name__ == "__main__":
    main()
