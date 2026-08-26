"""Wi-Fi from the login screen, because otherwise there is no way in.

An account that needs the network to sign in, on a machine whose network is
not up, is a machine nobody can log into. The desktop where the Wi-Fi settings
live is on the far side of the sign in that needs the Wi-Fi. Every serious
login screen solves this and the way they solve it is a network applet.

This is the part that decides things, with no toolkit in it: what the radio
can see, what it is doing, and what to say about it. The D-Bus calls go
through a facade so the whole thing can be driven from a fixture, which is the
same shape `aurade-host-bridge` uses and for the same reason.

Talking to NetworkManager from the greeter needs permission. Scanning is free,
activating a connection is not, and the polkit rule that grants it to the
greeter user ships with this package. Without it every connect returns
NotAuthorized, which is a sentence this file is careful to translate rather
than pass through.
"""

from __future__ import annotations

NM = "org.freedesktop.NetworkManager"
NM_PATH = "/org/freedesktop/NetworkManager"
NM_SETTINGS_PATH = "/org/freedesktop/NetworkManager/Settings"
NM_IFACE = NM
NM_DEVICE = "org.freedesktop.NetworkManager.Device"
NM_WIRELESS = "org.freedesktop.NetworkManager.Device.Wireless"
NM_AP = "org.freedesktop.NetworkManager.AccessPoint"
NM_SETTINGS = "org.freedesktop.NetworkManager.Settings"

#: Device types, of the many, that this screen shows.
TYPE_ETHERNET = 1
TYPE_WIFI = 2

#: Device states worth naming. Everything above ACTIVATED is worse than it.
STATE_UNAVAILABLE = 20
STATE_DISCONNECTED = 30
STATE_PREPARE = 40
STATE_CONFIG = 50
STATE_NEED_AUTH = 60
STATE_IP_CONFIG = 70
STATE_ACTIVATED = 100
STATE_DEACTIVATING = 110
STATE_FAILED = 120

#: Access point flags.
AP_PRIVACY = 0x1
#: The RSN flag NetworkManager sets for SAE, which is WPA3's handshake.
AP_SAE = 0x400


class NetworkError(RuntimeError):
    """Something went wrong that a person needs a sentence about."""


class Network:
    """One access point, as the list shows it."""

    __slots__ = ("ssid", "strength", "security", "saved", "active", "path")

    def __init__(self, ssid: str, strength: int, security: str,
                 saved: bool = False, active: bool = False,
                 path: str = "") -> None:
        self.ssid = ssid
        self.strength = strength
        self.security = security
        self.saved = saved
        self.active = active
        self.path = path

    @property
    def secured(self) -> bool:
        return self.security != "none"

    @property
    def needs_passphrase(self) -> bool:
        """Whether joining this one will ask for something.

        A saved network does not, because NetworkManager already holds the
        secret. Asking anyway is how somebody ends up typing a password they
        set two years ago on a network that would have joined by itself.
        """
        return self.secured and not self.saved

    @property
    def bars(self) -> int:
        """Nought to four, the way every other radio indicator counts."""
        if self.strength >= 75:
            return 4
        if self.strength >= 55:
            return 3
        if self.strength >= 30:
            return 2
        if self.strength > 0:
            return 1
        return 0

    def __repr__(self) -> str:  # pragma: no cover - debugging only
        return f"Network({self.ssid!r}, {self.strength}, {self.security!r})"


def security_of(flags: int, wpa: int, rsn: int) -> str:
    """What kind of secret this access point wants, if any.

    WPA3 is told apart because it needs SAE rather than a pre-shared key. An
    access point offering only SAE that is handed a wpa-psk profile does not
    report a wrong password, it never associates, and the person is told the
    network stopped responding.
    """
    if not (flags & AP_PRIVACY) and not (wpa or rsn):
        return "none"
    if rsn & AP_SAE and not wpa:
        return "sae"
    if wpa or rsn:
        return "psk"
    return "wep"


def ssid_text(raw) -> str:
    """The name, out of the bytes, without letting a bad one end the list."""
    try:
        return bytes(raw).decode("utf-8", "replace").rstrip("\x00")
    except (TypeError, ValueError):
        return ""


def rank(networks: list[Network]) -> list[Network]:
    """The order the list is shown in.

    Connected first, then saved, then by signal. Somebody opening this panel
    is either checking what they are on or joining something they have joined
    before; a list sorted purely by signal buries both under whichever café is
    loudest.
    """
    return sorted(
        networks,
        key=lambda n: (not n.active, not n.saved, -n.strength, n.ssid.lower()),
    )


def merge(seen: list[Network]) -> list[Network]:
    """One row per name, keeping the strongest sighting.

    A network with three access points is one network to the person choosing
    it. Showing it three times is showing them the shape of the building.
    """
    best: dict[str, Network] = {}
    for network in seen:
        if not network.ssid:
            # A hidden network has no name to show. It is reachable by typing
            # the name, which is a different control, not a blank row.
            continue
        current = best.get(network.ssid)
        if current is None or network.strength > current.strength:
            if current is not None:
                network.saved = network.saved or current.saved
                network.active = network.active or current.active
            best[network.ssid] = network
        else:
            current.saved = current.saved or network.saved
            current.active = current.active or network.active
    return rank(list(best.values()))


def state_words(state: int, kind: str = "wifi") -> str:
    """What the status line says the radio is doing."""
    if state == STATE_ACTIVATED:
        return "Connected"
    if state in (STATE_PREPARE, STATE_CONFIG):
        return "Connecting"
    if state == STATE_NEED_AUTH:
        return "Waiting for the password"
    if state == STATE_IP_CONFIG:
        return "Getting an address"
    if state == STATE_FAILED:
        return "Could not connect"
    if state == STATE_DEACTIVATING:
        return "Disconnecting"
    if state == STATE_UNAVAILABLE:
        return "No cable" if kind == "ethernet" else "Wi-Fi is off"
    return "Not connected"


#: What to say when NetworkManager refuses, rather than what it said.
#:
#: Its own errors name D-Bus interfaces and polkit actions. Somebody standing
#: at a login screen needs to know whether to try again, type something else,
#: or give up and use a cable.
REFUSALS = {
    "NotAuthorized": ("This computer will not let the login screen change "
                      "the network. Sign in and change it there."),
    "AccessDenied": ("This computer will not let the login screen change "
                     "the network. Sign in and change it there."),
    "NoSecrets": "That password did not work. Try it again.",
    "SecretsRequired": "That network needs a password.",
    "UnknownDevice": "This computer has no Wi-Fi radio that is switched on.",
    "ConnectionInvalid": "That network could not be joined with those details.",
}


def refusal_words(error: str) -> str:
    """Translate a NetworkManager error into something worth reading."""
    for token, words in REFUSALS.items():
        if token.lower() in str(error).lower():
            return words
    return "That network could not be joined."


def wifi_profile(ssid: str, security: str, passphrase: str | None,
                 iface: str) -> dict:
    """The NetworkManager profile for joining one network.

    Not saved to disk by the greeter beyond what NetworkManager does with it.
    The passphrase goes into the profile and the profile goes to
    NetworkManager; nothing here writes it anywhere else or hands it back.
    """
    profile: dict = {
        "connection": {
            "id": ssid,
            "type": "802-11-wireless",
            "interface-name": iface,
            "autoconnect": True,
        },
        "802-11-wireless": {
            "ssid": ssid.encode("utf-8"),
            "mode": "infrastructure",
        },
        "ipv4": {"method": "auto"},
        "ipv6": {"method": "auto"},
    }
    if security in ("psk", "sae") and passphrase:
        profile["802-11-wireless-security"] = {
            "key-mgmt": "sae" if security == "sae" else "wpa-psk",
            "psk": passphrase,
        }
    elif security == "wep" and passphrase:
        profile["802-11-wireless-security"] = {
            "key-mgmt": "none",
            "wep-key0": passphrase,
            "wep-key-type": 2,
        }
    return profile
