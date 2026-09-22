#!/usr/bin/python
"""Focused protocol tests for the Shill and NetworkManager translation."""

from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("shill_nm_adapter.py")
SPEC = importlib.util.spec_from_file_location("shill_nm_adapter_tested", MODULE_PATH)
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


class FakeService:
    def __init__(self, service_type, security="none", ssid=b"", passphrase=None):
        self._svc_type = service_type
        self._props = {
            adapter.PROP_SECURITY: security,
            adapter.PROP_SSID: ssid,
            adapter.PROP_AUTO_CONNECT: True,
        }
        self._passphrase = passphrase
        self._iface_name = "wlan0"


# Cipher bits, so that the vectors below read as the radio reports them.
PAIR_CCMP = 0x08
GROUP_CCMP = 0x80
CCMP = PAIR_CCMP | GROUP_CCMP
PSK = adapter.NM_AP_SEC_KEY_MGMT_PSK
SAE = adapter.NM_AP_SEC_KEY_MGMT_SAE
EAP = adapter.NM_AP_SEC_KEY_MGMT_802_1X
OWE = adapter.NM_AP_SEC_KEY_MGMT_OWE
PRIVACY = adapter.NM_AP_FLAGS_PRIVACY


def test_wpa2_is_not_reported_as_wpa3():
    """The flags below were read off a real access point, SHELBY2.4, over the
    system bus.  0x188 is CCMP plus PSK, which is WPA2.  Reading WPA3 out of it
    made the adapter offer SAE to a network that cannot answer, so every attempt
    to join failed."""
    assert adapter.wifi_security(PRIVACY, 0, CCMP | PSK) == ("wpa2", "psk", True)
    assert adapter.wifi_security(PRIVACY, 0, CCMP | PSK)[0] != "wpa3"
    assert adapter.key_management("wpa2") == "wpa-psk"


def test_security_mapping():
    assert adapter.wifi_security(0, 0, 0) == ("none", "none", False)
    assert adapter.wifi_security(PRIVACY, 0, 0) == ("wep", "wep", True)
    # A cipher advertised with no key management bit is protected, not open.
    assert adapter.wifi_security(0, 2, 0) == ("wpa", "psk", True)
    assert adapter.wifi_security(0, CCMP | PSK, 0) == ("wpa", "psk", True)
    assert adapter.wifi_security(0, CCMP | PSK, CCMP | PSK) == ("wpa+wpa2", "psk", True)
    # Only SAE is WPA3.
    assert adapter.wifi_security(PRIVACY, 0, CCMP | SAE) == ("wpa3", "psk", True)
    # A transition mode network offers both, and is joined as the older one so
    # that a radio without SAE still associates.
    assert adapter.wifi_security(PRIVACY, 0, CCMP | PSK | SAE) == ("wpa2+wpa3", "psk", True)
    assert adapter.key_management("wpa2+wpa3") == "wpa-psk"
    assert adapter.key_management("wpa3") == "sae"


def test_enterprise_and_open_encryption_are_not_psk():
    """Ash asks for what SecurityClass says it needs.  Calling an enterprise
    network psk would put a passphrase box in front of something that wants a
    certificate, and calling Enhanced Open psk would demand a word that does
    not exist."""
    name, klass, required = adapter.wifi_security(PRIVACY, 0, CCMP | EAP)
    assert klass == "802_1x" and required
    assert name.endswith("-ent")

    name, klass, required = adapter.wifi_security(PRIVACY, 0, CCMP | SAE | EAP)
    assert (name, klass) == ("wpa3-ent", "802_1x")

    name, klass, required = adapter.wifi_security(PRIVACY, 0, OWE)
    assert (name, klass, required) == ("owe", "none", False)
    assert adapter.key_management("owe") == ""


def test_named_failures_reach_the_person_retyping():
    assert adapter.NM_REASON_TO_SHILL_ERROR[adapter.NM_REASON_NO_SECRETS] == "bad-passphrase"
    assert adapter.NM_REASON_TO_SHILL_ERROR[adapter.NM_REASON_SSID_NOT_FOUND] == "out-of-range"
    # A network that walked out of range is not a mistyped word.
    assert (adapter.NM_REASON_TO_SHILL_ERROR[adapter.NM_REASON_SSID_NOT_FOUND]
            != adapter.NM_REASON_TO_SHILL_ERROR[adapter.NM_REASON_NO_SECRETS])
    # An unmapped reason must not be dressed up as a bad passphrase.
    assert adapter.NM_REASON_TO_SHILL_ERROR.get(999) is None


def test_hidden_networks_are_asked_for_by_name():
    plain = adapter.wifi_settings(b"Cafe", "wpa2", "secret", iface="wlan0")
    assert not bool(plain["802-11-wireless"]["hidden"])
    hidden = adapter.wifi_settings(b"Back office", "wpa2", "secret",
                                   iface="wlan0", hidden=True)
    assert bool(hidden["802-11-wireless"]["hidden"])


def test_profile_shapes_and_secret_boundary():
    open_profile = adapter.wifi_settings(b"Cafe", "none", None, iface="wlan0")
    assert bytes(open_profile["802-11-wireless"]["ssid"]) == b"Cafe"
    assert "802-11-wireless-security" not in open_profile

    psk_profile = adapter.wifi_settings(b"Cafe", "wpa2", "correct horse", iface="wlan0")
    assert str(psk_profile["802-11-wireless-security"]["key-mgmt"]) == "wpa-psk"
    assert str(psk_profile["802-11-wireless-security"]["psk"]) == "correct horse"

    sae_profile = adapter.wifi_settings(b"Modern", "wpa3", "secret", iface="wlan0")
    assert str(sae_profile["802-11-wireless-security"]["key-mgmt"]) == "sae"

    wep_profile = adapter.wifi_settings(b"Legacy", "wep", "abc123", iface="wlan0")
    assert str(wep_profile["802-11-wireless-security"]["key-mgmt"]) == "none"
    assert str(wep_profile["802-11-wireless-security"]["wep-key0"]) == "abc123"

    fake = FakeService(adapter.SHILL_TYPE_WIFI, "wpa", b"Cafe", "secret")
    monitor = object.__new__(adapter.NetworkManagerMonitor)
    profile = monitor._settings_for_connect(fake)
    assert str(profile["802-11-wireless-security"]["psk"]) == "secret"
    assert adapter.PROP_PASSPHRASE not in fake._props


def test_ethernet_profile_and_state_mapping():
    profile = adapter.ethernet_settings("enp1s0")
    assert str(profile["connection"]["type"]) == "802-3-ethernet"
    assert str(profile["connection"]["interface-name"]) == "enp1s0"
    assert adapter._device_state_to_shill(30, False) == adapter.SHILL_STATE_READY
    assert adapter._device_state_to_shill(50, False) == adapter.SHILL_STATE_ASSOCIATION
    assert adapter._device_state_to_shill(70, False) == adapter.SHILL_STATE_CONFIGURATION
    assert adapter._device_state_to_shill(100, True) == adapter.SHILL_STATE_ONLINE
    # A radio that failed to join one network has not broken every other
    # network in the room.
    assert adapter._device_state_to_shill(120, True) == adapter.SHILL_STATE_FAILURE
    assert adapter._device_state_to_shill(120, False) == adapter.SHILL_STATE_IDLE


class RecordingConnection:
    def __init__(self):
        self.sent = []

    def send_message(self, message):
        self.sent.append(message)


def test_property_changes_are_announced_the_way_ash_listens():
    """Ash subscribes to Shill's own PropertyChanged on the Shill interface, not
    to the standard properties signal.  A list built only from the standard one
    is correct when it is first read and then never moves again."""
    obj = object.__new__(adapter.ShillObject)
    obj._props = {}
    obj._path = "/org/chromium/flimflam/Service/Wifi_test"
    obj._interface_name = adapter.SHILL_SERVICE_IFACE
    obj._conn = RecordingConnection()
    obj.PropertiesChanged = lambda *args, **kwargs: None

    obj._set_property(adapter.PROP_STATE, "online")
    assert len(obj._conn.sent) == 1
    message = obj._conn.sent[0]
    assert message.get_interface() == adapter.SHILL_SERVICE_IFACE
    assert message.get_member() == "PropertyChanged"
    assert message.get_path() == obj._path
    assert list(message.get_args_list()) == ["State", "online"]

    # A write that changes nothing must not wake anybody up.
    obj._set_property(adapter.PROP_STATE, "online")
    assert len(obj._conn.sent) == 1

    obj._set_properties({adapter.PROP_STRENGTH: 60, adapter.PROP_NAME: "Cafe"})
    assert len(obj._conn.sent) == 3
    assert {tuple(m.get_args_list()) for m in obj._conn.sent[1:]} == {
        ("Strength", 60), ("Name", "Cafe"),
    }


class FakeConnection:
    def __init__(self, settings):
        self._settings = settings

    def GetSettings(self):
        return self._settings


class FakeSettings:
    def __init__(self, connections):
        self._connections = connections

    def ListConnections(self):
        return list(self._connections)


def test_a_saved_network_is_recognised_as_saved():
    """NetworkManager returns a saved SSID as an array of bytes.  Comparing that
    against the scanned SSID without normalising both sides matched nothing, so
    every saved network was treated as new: the passphrase was asked for again
    and a second profile was written on every connect."""
    as_nm_returns_it = [ord(c) for c in "SHELBY2.4"]
    monitor = object.__new__(adapter.NetworkManagerMonitor)
    monitor._settings_iface = FakeSettings(["/nm/Settings/1"])
    monitor._obj = lambda path: FakeConnection({
        "connection": {"type": "802-11-wireless", "interface-name": "wlp1s0"},
        "802-11-wireless": {"ssid": as_nm_returns_it},
    })

    import types
    monitor._connection_proxy = lambda path: monitor._obj(path)
    original = adapter.dbus.Interface
    adapter.dbus.Interface = lambda obj, iface: obj
    try:
        found = monitor._saved_connection(b"SHELBY2.4", "wlp1s0", "802-11-wireless")
        missing = monitor._saved_connection(b"Somewhere else", "wlp1s0", "802-11-wireless")
    finally:
        adapter.dbus.Interface = original

    assert found == "/nm/Settings/1"
    # A network that was never saved must still come back empty.
    assert missing == ""


def test_a_network_typed_in_by_hand_lands_on_a_real_radio():
    """Joining a hidden network gives Shill the network's name and nothing
    about the radio.  Using the name as the interface writes a profile bound to
    a device that does not exist, and NetworkManager refuses to activate it."""
    monitor = object.__new__(adapter.NetworkManagerMonitor)
    monitor._nm_devices = {
        "/nm/Devices/1": {"type": adapter.SHILL_TYPE_ETHERNET, "iface": "enp1s0"},
        "/nm/Devices/2": {"type": adapter.SHILL_TYPE_WIFI, "iface": "wlp1s0"},
    }
    assert monitor.first_device(adapter.SHILL_TYPE_WIFI) == ("/nm/Devices/2", "wlp1s0")
    assert monitor.first_device(adapter.SHILL_TYPE_ETHERNET) == ("/nm/Devices/1", "enp1s0")
    # A technology with no radio fitted must not borrow another one.
    assert monitor.first_device(adapter.SHILL_TYPE_CELLULAR) == ("", "")

    # The path Ash actually takes when someone types a network in by hand.
    args = {adapter.PROP_TYPE: adapter.SHILL_TYPE_WIFI,
            adapter.PROP_NAME: "Back office",
            adapter.PROP_HIDDEN_SSID: True}
    device_path, iface = adapter.configured_device(monitor, adapter.SHILL_TYPE_WIFI, args)
    assert (device_path, iface) == ("/nm/Devices/2", "wlp1s0")
    assert iface != "Back office", "the network name is not an interface name"

    # With no radio of that kind, fall back to whatever the caller named rather
    # than to the network's own name.
    empty = object.__new__(adapter.NetworkManagerMonitor)
    empty._nm_devices = {}
    assert adapter.configured_device(empty, adapter.SHILL_TYPE_WIFI, args) == ("", "")
    named = dict(args, **{adapter.PROP_INTERFACE: "wlan9"})
    assert adapter.configured_device(empty, adapter.SHILL_TYPE_WIFI, named) == ("", "wlan9")

    settings = adapter.wifi_settings(b"Back office", "wpa2", "secret",
                                     iface=iface, hidden=True)
    assert str(settings["connection"]["interface-name"]) == "wlp1s0"
    assert str(settings["connection"]["id"]) == "Back office"


def test_service_paths_carry_the_prefix_ash_insists_on():
    """ShillServiceClient::GetHelper refuses any service path that does not
    begin with /service/, logs Invalid service path, and returns no helper. The
    network handler then builds a NetworkState with no type, and the empty
    specifier fails a DCHECK that takes the whole session down in a login loop.
    This is not cosmetic and it cannot be caught by anything that does not run
    Ash against the adapter."""
    assert adapter.SERVICE_PREFIX == "/service/"
    wifi = adapter.shill_service_path("wifi", "abc123")
    ethernet = adapter.shill_service_path("ethernet", "def456")
    for path in (wifi, ethernet):
        assert path.startswith("/service/"), path
    # Two networks must not collide.
    assert wifi != adapter.shill_service_path("wifi", "zzz999")

    assert adapter.shill_device_path("wlp1s0") == "/device/wlp1s0"
    # No interface means no device, not a path ending in nothing.
    assert adapter.shill_device_path("") == "/"


def test_only_the_network_we_are_on_reads_as_connected():
    """Shill's ready means connected but not yet online, and Ash draws it as
    Connected. Handing that to every access point in range put the word
    Connected under all four networks in the room."""
    ACTIVATED = 100
    assert adapter._service_state_to_shill(ACTIVATED, True) == adapter.SHILL_STATE_ONLINE
    assert adapter._service_state_to_shill(ACTIVATED, False) == adapter.SHILL_STATE_IDLE
    # A radio busy joining one network says nothing about the others.
    for state in (40, 50, 60, 70, 80, 90):
        assert adapter._service_state_to_shill(state, False) == adapter.SHILL_STATE_IDLE, state
    assert adapter._service_state_to_shill(50, True) == adapter.SHILL_STATE_ASSOCIATION
    assert adapter._service_state_to_shill(70, True) == adapter.SHILL_STATE_CONFIGURATION
    # The device mapping keeps its own meaning, which is what devices need.
    assert adapter._device_state_to_shill(50, False) == adapter.SHILL_STATE_ASSOCIATION


def test_known_means_saved_and_nothing_else():
    """NetworkState::IsInProfile is true for any non empty profile path, and Ash
    files those under Known networks. Stamping the default profile on every
    access point in range filed the whole neighbourhood as known."""
    saved = adapter._profile_for("/nm/Settings/1")
    unsaved = adapter._profile_for("")
    assert str(saved) == adapter.SHALLOW_PROFILE_PATH
    # Empty, not the root path: Ash reads "/" as a non empty string and would
    # still call the network known.
    assert str(unsaved) == ""
    assert str(unsaved) != "/"
    assert saved != unsaved


def test_enabled_technology_translation():
    assert adapter._technology_is_enabled(
        adapter.SHILL_TYPE_WIFI, wireless_enabled=True, networking_enabled=True
    )
    assert not adapter._technology_is_enabled(
        adapter.SHILL_TYPE_WIFI, wireless_enabled=False, networking_enabled=True
    )
    assert adapter._technology_is_enabled(
        adapter.SHILL_TYPE_ETHERNET, wireless_enabled=False, networking_enabled=True
    )
    assert not adapter._technology_is_enabled(
        adapter.SHILL_TYPE_ETHERNET, wireless_enabled=True, networking_enabled=False
    )


def test_identity_and_device_filtering():
    assert adapter._stable_id("device", b"Cafe") == adapter._stable_id("device", b"Cafe")
    assert adapter._stable_id("device", b"Cafe") != adapter._stable_id("device", b"Other")
    assert adapter.NM_TYPE_TO_SHILL == {
        adapter.NM_DEVICE_TYPE_ETHERNET: adapter.SHILL_TYPE_ETHERNET,
        adapter.NM_DEVICE_TYPE_WIFI: adapter.SHILL_TYPE_WIFI,
    }
    assert adapter.SHILL_TYPE_CELLULAR not in adapter.NM_TYPE_TO_SHILL.values()
    assert adapter._ssid_text(b"") == "Hidden network"


class FakeProps:
    def __init__(self, values):
        self._values = values

    def Get(self, iface, name):
        return self._values[(iface, name)]


class RecordingService:
    def __init__(self, connection_path=""):
        self.nm_connection_path = connection_path
        self.nm_ap_paths = set()
        self.states = []

    def set_state(self, state):
        self.states.append(state)

    def clear_error(self):
        pass

    def set_failure(self, error):
        self.states.append("failure:" + error)


def test_a_connected_cable_is_online_to_ash():
    """NetworkManager names a device's active connection by its active
    connection object and the service keeps the saved profile, which is a
    different path for the same connection.  Compared directly they never
    matched: a cable NetworkManager called connected, full connectivity, was
    idle to Ash, and first run stayed on its network screen with Next greyed
    out on every machine without Wi-Fi.  The paths are the ones a virtual
    machine with one wired interface actually reported."""
    import types

    def states_for(active_connection, saved):
        monitor = object.__new__(adapter.NetworkManagerMonitor)
        monitor._nm_devices = {
            "/org/freedesktop/NetworkManager/Devices/2": {
                "type": adapter.SHILL_TYPE_ETHERNET, "iface": "enp0s2"},
        }
        service = RecordingService(saved)
        monitor._device_to_services = {
            "/org/freedesktop/NetworkManager/Devices/2": {"/service/ethernet_test"},
        }
        monitor._shill = types.SimpleNamespace(
            services={"/service/ethernet_test": service}, devices={})
        props = {
            "/org/freedesktop/NetworkManager/Devices/2": FakeProps({
                (adapter.NM_DEVICE_IFACE, "State"): adapter.NM_DEVICE_STATE_ACTIVATED,
                (adapter.NM_DEVICE_IFACE, "ActiveConnection"): active_connection,
                (adapter.NM_DEVICE_IFACE, "StateReason"): (adapter.NM_DEVICE_STATE_ACTIVATED, 0),
            }),
            "/org/freedesktop/NetworkManager/ActiveConnection/2": FakeProps({
                (adapter.NM_ACTIVE_CONNECTION_IFACE, "Connection"):
                    "/org/freedesktop/NetworkManager/Settings/2",
            }),
        }
        monitor._props_for = lambda path: props[path]
        monitor._refresh_service_states("/org/freedesktop/NetworkManager/Devices/2")
        return service.states

    active = "/org/freedesktop/NetworkManager/ActiveConnection/2"
    saved = "/org/freedesktop/NetworkManager/Settings/2"
    assert states_for(active, saved) == [adapter.SHILL_STATE_ONLINE]
    # Connected with a profile other than the one the adapter took for the
    # saved one is still the one Ethernet service that device has.
    assert states_for(active, "") == [adapter.SHILL_STATE_ONLINE]
    # No active connection is not online, whatever the device state says.
    assert states_for("/", saved) == [adapter.SHILL_STATE_IDLE]


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_")]
    for test in tests:
        test()
    print(f"shill adapter tests: {len(tests)} PASS")
