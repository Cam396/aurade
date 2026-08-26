"""The live half of the network panel: NetworkManager, over the system bus.

`network.py` holds every rule and can be driven from a fixture. This file
holds the calls, and holds nothing else: no decision about ordering, naming,
security classes or what to say when something is refused lives here, because
none of that could then be tested.

Gio rather than python-dbus, because the greeter already links GObject and
adding a second bus binding to a login screen is a second thing that can fail
before anybody has signed in.

Every call is synchronous and every caller runs it on a worker thread. A
scan takes seconds and NetworkManager is entitled to take its time answering;
a login screen that stops repainting while it waits looks exactly like one
that has crashed.
"""

from __future__ import annotations

import gi

gi.require_version("Gio", "2.0")

from gi.repository import Gio, GLib  # noqa: E402

from . import network as N  # noqa: E402


class Client:
    """NetworkManager, or an honest failure to reach it."""

    def __init__(self, bus=None) -> None:
        self._bus = bus
        self._cache: dict[str, Gio.DBusProxy] = {}

    # -- plumbing ----------------------------------------------------------

    @property
    def bus(self):
        if self._bus is None:
            try:
                self._bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            except GLib.Error as exc:
                raise N.NetworkError(
                    "This computer has no system bus, so the login screen "
                    "cannot see the network.") from exc
        return self._bus

    def _proxy(self, path: str, interface: str) -> Gio.DBusProxy:
        key = f"{path}\n{interface}"
        proxy = self._cache.get(key)
        if proxy is None:
            try:
                proxy = Gio.DBusProxy.new_sync(
                    self.bus, Gio.DBusProxyFlags.DO_NOT_AUTO_START, None,
                    N.NM, path, interface, None)
            except GLib.Error as exc:
                raise N.NetworkError(N.refusal_words(str(exc))) from exc
            self._cache[key] = proxy
        return proxy

    def _get(self, path: str, interface: str, prop: str):
        """One property, through the Properties interface.

        Not through the proxy's own cache: a proxy built with
        DO_NOT_AUTO_START may have no cached properties at all, and a panel
        that silently reads None for every signal strength draws an empty
        list rather than an error.
        """
        try:
            reply = self._proxy(path, "org.freedesktop.DBus.Properties").call_sync(
                "Get", GLib.Variant("(ss)", (interface, prop)),
                Gio.DBusCallFlags.NONE, 8000, None)
        except GLib.Error as exc:
            raise N.NetworkError(N.refusal_words(str(exc))) from exc
        return reply.unpack()[0]

    def _call(self, path: str, interface: str, method: str,
              args: GLib.Variant | None = None, timeout: int = 30000):
        try:
            return self._proxy(path, interface).call_sync(
                method, args, Gio.DBusCallFlags.NONE, timeout, None)
        except GLib.Error as exc:
            raise N.NetworkError(N.refusal_words(str(exc))) from exc

    # -- what is here ------------------------------------------------------

    def devices(self) -> list[dict]:
        """Every device this screen has an opinion about, Wi-Fi and cable."""
        reply = self._call(N.NM_PATH, N.NM_IFACE, "GetDevices", None, 8000)
        found = []
        for path in reply.unpack()[0]:
            try:
                kind = int(self._get(path, N.NM_DEVICE, "DeviceType"))
                if kind not in (N.TYPE_WIFI, N.TYPE_ETHERNET):
                    continue
                found.append({
                    "path": path,
                    "kind": "wifi" if kind == N.TYPE_WIFI else "ethernet",
                    "iface": str(self._get(path, N.NM_DEVICE, "Interface")),
                    "state": int(self._get(path, N.NM_DEVICE, "State")),
                })
            except N.NetworkError:
                # One unreadable device is one row, not the whole panel.
                continue
        return found

    def wifi_device(self) -> dict | None:
        for device in self.devices():
            if device["kind"] == "wifi":
                return device
        return None

    def saved_names(self) -> set:
        """Network names NetworkManager already holds a profile for."""
        names = set()
        try:
            reply = self._call(N.NM_SETTINGS_PATH, N.NM_SETTINGS,
                               "ListConnections", None, 8000)
        except N.NetworkError:
            return names
        for path in reply.unpack()[0]:
            try:
                settings = self._call(
                    path, "org.freedesktop.NetworkManager.Settings.Connection",
                    "GetSettings", None, 8000).unpack()[0]
            except N.NetworkError:
                continue
            wireless = settings.get("802-11-wireless") or {}
            ssid = wireless.get("ssid")
            if ssid is not None:
                names.add(N.ssid_text(ssid))
        return names

    def scan(self, device_path: str) -> None:
        """Ask for a fresh sweep. Results arrive whenever they arrive."""
        self._call(device_path, N.NM_WIRELESS, "RequestScan",
                   GLib.Variant("(a{sv})", ({},)), 20000)

    def networks(self, device_path: str) -> list[N.Network]:
        """What the radio can see, as the list shows it."""
        reply = self._call(device_path, N.NM_WIRELESS, "GetAllAccessPoints",
                           None, 8000)
        try:
            active = str(self._get(device_path, N.NM_WIRELESS,
                                   "ActiveAccessPoint"))
        except N.NetworkError:
            active = "/"
        saved = self.saved_names()
        seen = []
        for path in reply.unpack()[0]:
            try:
                ssid = N.ssid_text(self._get(path, N.NM_AP, "Ssid"))
                seen.append(N.Network(
                    ssid=ssid,
                    strength=int(self._get(path, N.NM_AP, "Strength")),
                    security=N.security_of(
                        int(self._get(path, N.NM_AP, "Flags")),
                        int(self._get(path, N.NM_AP, "WpaFlags")),
                        int(self._get(path, N.NM_AP, "RsnFlags"))),
                    saved=ssid in saved,
                    active=path == active,
                    path=path,
                ))
            except N.NetworkError:
                continue
        return N.merge(seen)

    # -- doing something about it -----------------------------------------

    def join(self, device: dict, chosen: N.Network,
             passphrase: str | None) -> None:
        """Join one network, writing a profile only when there is not one.

        A saved network is activated as it stands. Rewriting its profile on
        every join is how a working network acquires a broken passphrase from
        somebody who typed into the wrong box.
        """
        if chosen.saved and not passphrase:
            for path, name in self._saved_paths().items():
                if name == chosen.ssid:
                    self._call(N.NM_PATH, N.NM_IFACE, "ActivateConnection",
                               GLib.Variant("(ooo)", (path, device["path"],
                                                      chosen.path or "/")))
                    return
        profile = N.wifi_profile(chosen.ssid, chosen.security, passphrase,
                                 device["iface"])
        self._call(N.NM_PATH, N.NM_IFACE, "AddAndActivateConnection",
                   GLib.Variant("(a{sa{sv}}oo)",
                                (_variantise(profile), device["path"],
                                 chosen.path or "/")), 60000)

    def leave(self, device: dict) -> None:
        self._call(device["path"], N.NM_DEVICE, "Disconnect", None, 20000)

    def _saved_paths(self) -> dict:
        found = {}
        try:
            reply = self._call(N.NM_SETTINGS_PATH, N.NM_SETTINGS,
                               "ListConnections", None, 8000)
        except N.NetworkError:
            return found
        for path in reply.unpack()[0]:
            try:
                settings = self._call(
                    path, "org.freedesktop.NetworkManager.Settings.Connection",
                    "GetSettings", None, 8000).unpack()[0]
            except N.NetworkError:
                continue
            wireless = settings.get("802-11-wireless") or {}
            if wireless.get("ssid") is not None:
                found[path] = N.ssid_text(wireless["ssid"])
        return found


def _variantise(profile: dict) -> dict:
    """A plain profile as the nested variant dictionary NetworkManager wants.

    Typed by hand rather than left to inference, because a Python string and
    a byte array are the same thing to a guess and are not the same thing to
    NetworkManager: an SSID sent as a string is a connection that never comes
    up, with no error worth reading.
    """
    out: dict = {}
    for section, values in profile.items():
        block = {}
        for key, value in values.items():
            if isinstance(value, bytes):
                block[key] = GLib.Variant("ay", value)
            elif isinstance(value, bool):
                block[key] = GLib.Variant("b", value)
            elif isinstance(value, int):
                block[key] = GLib.Variant("u", value)
            else:
                block[key] = GLib.Variant("s", str(value))
        out[section] = block
    return out
