#!/usr/bin/env python3
"""The network panel's rules, without a radio.

An account that needs the network to sign in, on a machine whose network is
not up, is a machine nobody can log into: the settings that would fix it are
behind the sign in that needs them. So this list has to be right about what it
shows, what it asks for, and what it says when NetworkManager refuses.

Every check here is about a person standing at a login screen deciding what to
press.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), ".."))
sys.path.insert(0, ROOT)

from aurade_greeter import network as N  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def net(ssid, strength=50, security="psk", saved=False, active=False):
    return N.Network(ssid, strength, security, saved, active)


# --- what kind of secret each network wants -------------------------------

def test_security_is_read_from_the_flags() -> None:
    check(N.security_of(0, 0, 0) == "none", "an open network was marked secured")
    check(N.security_of(N.AP_PRIVACY, 0, 0) == "wep",
          "an old WEP network was not recognised")
    check(N.security_of(N.AP_PRIVACY, 0x100, 0) == "psk",
          "a WPA network was not recognised")
    check(N.security_of(N.AP_PRIVACY, 0, N.AP_SAE) == "sae",
          "a WPA3 network was not recognised, so it would be handed a "
          "pre-shared key and never associate")
    check(N.security_of(N.AP_PRIVACY, 0x100, N.AP_SAE) == "psk",
          "a transitional network was forced onto SAE, so a profile saved "
          "before the router was upgraded stops working")


def test_a_saved_network_does_not_ask_again() -> None:
    check(net("Home", saved=True).needs_passphrase is False,
          "a saved network asked for a password NetworkManager already holds")
    check(net("Cafe", saved=False).needs_passphrase is True,
          "a network nobody has joined did not ask for a password")
    check(net("Open", security="none").needs_passphrase is False,
          "an open network asked for a password")


# --- what the list shows --------------------------------------------------

def test_one_row_per_network_not_one_per_radio() -> None:
    """Three access points on one name is one network to the person choosing."""
    merged = N.merge([net("Office", 40), net("Office", 82), net("Office", 61),
                      net("Other", 30)])
    names = [n.ssid for n in merged]
    check(names.count("Office") == 1,
          f"one network appeared {names.count('Office')} times, which shows "
          f"the shape of the building rather than the networks")
    office = next(n for n in merged if n.ssid == "Office")
    check(office.strength == 82,
          f"the strongest sighting was not kept: {office.strength}")


def test_merging_keeps_saved_and_connected_whichever_order_they_arrive() -> None:
    """Both orders, because only one of them exercises each branch.

    NetworkManager returns access points in whatever order it has them, so
    the sighting that knows the network is saved can arrive before or after
    the strongest one. Testing one order leaves the other free to drop it,
    and a saved network that forgets it is saved asks for a password nobody
    needs to type.
    """
    weak_first = N.merge([net("Office", 20, saved=True, active=True),
                          net("Office", 80)])[0]
    check(weak_first.saved,
          "the stronger sighting arriving second lost that it is saved")
    check(weak_first.active,
          "the stronger sighting arriving second lost that it is connected")
    check(weak_first.strength == 80,
          "the stronger sighting arriving second lost its signal")

    strong_first = N.merge([net("Office", 80),
                            net("Office", 20, saved=True, active=True)])[0]
    check(strong_first.saved,
          "the weaker sighting arriving second lost that it is saved")
    check(strong_first.active,
          "the weaker sighting arriving second lost that it is connected")
    check(strong_first.strength == 80,
          "the weaker sighting arriving second overwrote the signal")


def test_a_hidden_network_is_not_a_blank_row() -> None:
    merged = N.merge([net("", 90), net("Named", 20)])
    check([n.ssid for n in merged] == ["Named"],
          "a network with no name to show became a blank row in the list")


def test_the_order_puts_what_matters_first() -> None:
    """Somebody opening this is checking what they are on, or rejoining."""
    ordered = N.rank([net("Loud", 95), net("Known", 40, saved=True),
                      net("Current", 20, active=True), net("Quiet", 10)])
    check([n.ssid for n in ordered] == ["Current", "Known", "Loud", "Quiet"],
          f"the list reads {[n.ssid for n in ordered]}, which buries the "
          f"network they are on under whichever cafe is loudest")


def test_signal_becomes_bars_the_way_every_radio_counts() -> None:
    check(net("x", 100).bars == 4, "a full signal was not four bars")
    check(net("x", 60).bars == 3, "a good signal was not three bars")
    check(net("x", 40).bars == 2, "a fair signal was not two bars")
    check(net("x", 5).bars == 1, "a weak signal was not one bar")
    check(net("x", 0).bars == 0, "no signal at all drew a bar")


# --- what it says ---------------------------------------------------------

def test_the_status_line_says_what_the_radio_is_doing() -> None:
    check(N.state_words(N.STATE_ACTIVATED) == "Connected",
          "a working connection did not say so")
    check(N.state_words(N.STATE_NEED_AUTH) == "Waiting for the password",
          "a network waiting on a password said something else")
    check(N.state_words(N.STATE_FAILED) == "Could not connect",
          "a failed connection did not say so")
    check(N.state_words(N.STATE_UNAVAILABLE, "ethernet") == "No cable",
          "an unplugged cable was described as a radio being off")
    check(N.state_words(N.STATE_UNAVAILABLE, "wifi") == "Wi-Fi is off",
          "a switched off radio was described as a missing cable")


def test_a_refusal_is_translated_rather_than_repeated() -> None:
    """NetworkManager names D-Bus interfaces and polkit actions.

    Somebody at a login screen needs to know whether to try again, type
    something else, or give up and find a cable.
    """
    polkit = N.refusal_words(
        "org.freedesktop.NetworkManager.Error.NotAuthorized: "
        "insufficient privileges")
    check("sign in" in polkit.lower(),
          f"a permission refusal did not say what to do instead: {polkit!r}")
    check("polkit" not in polkit.lower() and "dbus" not in polkit.lower(),
          f"the refusal repeated the machine's words: {polkit!r}")

    wrong = N.refusal_words("NoSecrets: no secrets provided")
    check("password" in wrong.lower(),
          f"a wrong password was not described as one: {wrong!r}")

    # A network service that is not there is not a network that refused.
    # Nothing was attempted, and the answer is not another password.
    # Two spellings of the same thing, because D-Bus reports it either way
    # depending on which layer answers, and each is asserted on its own so
    # dropping one is not hidden by the other still matching.
    for text in ("GDBus.Error:org.freedesktop.DBus.Error.ServiceUnknown",
                 "The name org.freedesktop.NetworkManager was not provided "
                 "by any .service files"):
        absent = N.refusal_words(text)
        check("not running" in absent.lower(),
              f"an absent NetworkManager was described as a network that "
              f"would not join: {absent!r} for {text[:40]!r}")
        check("could not be joined" not in absent.lower(),
              f"an absent NetworkManager was blamed on the network: {absent!r}")

    quiet = N.refusal_words("org.freedesktop.DBus.Error.NoReply: timed out")
    check("not answering" in quiet.lower(),
          f"a service that never replied was described as a refusal: {quiet!r}")

    unknown = N.refusal_words("something nobody has seen before")
    check(unknown and "could not be joined" in unknown,
          "an unrecognised error produced no sentence at all")


# --- the profile ----------------------------------------------------------

def test_the_profile_asks_for_the_right_handshake() -> None:
    sae = N.wifi_profile("Modern", "sae", "a good long one", "wlan0")
    check(sae["802-11-wireless-security"]["key-mgmt"] == "sae",
          "a WPA3 network was given a pre-shared key profile, which never "
          "associates rather than reporting a wrong password")
    psk = N.wifi_profile("Home", "psk", "a good long one", "wlan0")
    check(psk["802-11-wireless-security"]["key-mgmt"] == "wpa-psk",
          "a WPA2 network was given an SAE profile")
    wep = N.wifi_profile("Ancient", "wep", "abc123", "wlan0")
    check(wep["802-11-wireless-security"]["key-mgmt"] == "none",
          "a WEP network was given a key management it does not have")


def test_an_open_network_gets_no_security_block() -> None:
    profile = N.wifi_profile("Cafe", "none", None, "wlan0")
    check("802-11-wireless-security" not in profile,
          "an open network was given a security block, which makes joining "
          "it fail")
    check(profile["802-11-wireless"]["ssid"] == b"Cafe",
          "the network name did not reach the profile as bytes")
    check(profile["connection"]["interface-name"] == "wlan0",
          "the profile does not name the radio it is for")


def test_a_secured_network_with_no_passphrase_gets_no_secret_block() -> None:
    """Rather than a block with an empty password in it, which fails oddly."""
    profile = N.wifi_profile("Cafe", "psk", None, "wlan0")
    check("802-11-wireless-security" not in profile,
          "a profile was built with an empty passphrase in it")


def test_the_name_survives_bytes_that_are_not_text() -> None:
    check(N.ssid_text(b"Caf\xc3\xa9") == "Café",
          "a network name with an accent in it did not decode")
    check("�" in N.ssid_text(b"bad\xffname"),
          "a network name with invalid bytes was not made safe to draw")
    check(N.ssid_text(b"padded\x00\x00") == "padded",
          "a padded network name kept its padding")


def main() -> int:
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            function()
    if FAILURES:
        print("greeter network test: FAIL")
        for failure in FAILURES:
            print(f"  {failure}")
        return 1
    print("greeter network test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
