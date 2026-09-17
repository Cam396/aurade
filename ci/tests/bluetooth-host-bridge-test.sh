#!/usr/bin/env bash
# The Bluetooth surfaces already share CrosBluetoothConfig. This fixture keeps
# the generic Linux implementation at that seam and prevents it from drifting
# toward a second UI or a second system bus.
#
# Run with --mutation-audit to alter every protected property in memory and
# prove that the matching assertion fails. The audit never edits the patch.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH=${AURADE_BT_PATCH:-$ROOT/patches/0058-bluetooth-justworks-host-bridge.patch}
SERIES=$ROOT/patches/SERIES

python3 - "$PATCH" "$SERIES" "${1:-}" <<'PY'
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sys

patch_path = Path(sys.argv[1])
series_path = Path(sys.argv[2])
mode = sys.argv[3]

try:
    patch_text = patch_path.read_text(encoding="utf-8")
    series_text = series_path.read_text(encoding="utf-8")
except (OSError, UnicodeError) as error:
    print(f"bluetooth host bridge test: cannot read inputs: {error}",
          file=sys.stderr)
    raise SystemExit(1)

PATCH_NAME = "0058-bluetooth-justworks-host-bridge.patch"
SERVICE_CC = "chrome/browser/ash/dbus/aurade_bluetooth_service.cc"
SERVICE_H = "chrome/browser/ash/dbus/aurade_bluetooth_service.h"
SERVICE_TEST = "chrome/browser/ash/dbus/aurade_bluetooth_service_unittest.cc"
BUILD = "chrome/browser/ash/dbus/BUILD.gn"
MAIN = "chrome/browser/ash/main_parts/chrome_browser_main_parts_ash.cc"
PUBLIC_CC = "ash/public/cpp/bluetooth_config_service.cc"
PUBLIC_H = "ash/public/cpp/bluetooth_config_service.h"
EXPECTED_TARGETS = {
    PUBLIC_CC,
    PUBLIC_H,
    BUILD,
    SERVICE_CC,
    SERVICE_H,
    SERVICE_TEST,
    MAIN,
}


def split_sections(raw: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in raw.splitlines():
        if line.startswith("diff --git a/") and " b/" in line:
            current = line.split(" b/", 1)[1]
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(line)
    return sections


def declared_and_written(raw: str) -> list[tuple[str, str]]:
    """Each section's header path beside the path git will actually write to.

    git apply takes the destination from the +++ line, not from the diff --git
    header, so the two disagreeing means the patch edits a file its own header
    does not name. split_sections above reads only the header, which is enough
    to describe a well formed patch and not enough to police one: a patch whose
    header says ash/public/cpp and whose +++ line says aurade-host-bridge would
    pass the inventory and the host boundary check below while writing straight
    through both. Found by mutation, not by reading.
    """
    pairs: list[tuple[str, str]] = []
    declared: str | None = None
    for line in raw.splitlines():
        if line.startswith("diff --git a/") and " b/" in line:
            declared = line.split(" b/", 1)[1]
        elif line.startswith("+++ ") and declared is not None:
            written = line[4:].split("\t")[0]
            if written.startswith("b/"):
                written = written[2:]
            pairs.append((declared, written))
            declared = None
    return pairs


def added(section: list[str]) -> str:
    return "\n".join(
        line[1:] for line in section
        if line.startswith("+") and not line.startswith("+++")
    )


def strip_cpp_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?<![:/])//.*$", "", text, flags=re.M)


def validate(raw: str, series: str) -> list[str]:
    failures: list[str] = []
    sections = split_sections(raw)
    targets = set(sections)
    service = strip_cpp_comments(added(sections.get(SERVICE_CC, [])))
    header = added(sections.get(SERVICE_H, []))
    build = strip_cpp_comments(added(sections.get(BUILD, [])))
    main = strip_cpp_comments(added(sections.get(MAIN, [])))
    public = strip_cpp_comments(
        added(sections.get(PUBLIC_CC, [])) + "\n" +
        added(sections.get(PUBLIC_H, [])))
    tests = strip_cpp_comments(added(sections.get(SERVICE_TEST, [])))
    all_added = strip_cpp_comments("\n".join(added(value)
                                                for value in sections.values()))

    listed = [line.strip() for line in series.splitlines()
              if line.strip() == PATCH_NAME]
    if listed != [PATCH_NAME]:
        failures.append("series")

    if targets != EXPECTED_TARGETS:
        failures.append("targets")

    pairs = declared_and_written(raw)
    written = {path for _, path in pairs}
    if any(declared != path for declared, path in pairs):
        failures.append("header-mismatch")

    if any(path.startswith("aurade-host-bridge/")
           for path in targets | written):
        failures.append("host-boundary")

    if (public.count("SetBluetoothConfigServiceBinderForGenericLinux(") != 2 or
            "if (GetGenericLinuxBinder())" not in public or
            "GetGenericLinuxBinder().Run(std::move(receiver));" not in public):
        failures.append("binder-route")

    if not all(token in main for token in (
            '"ash/public/cpp/bluetooth_config_service.h"',
            '"chrome/browser/ash/dbus/aurade_bluetooth_service.h"',
            "std::make_unique<AuraDeBluetoothService>(GetAuraDeSharedSystemBus())")):
        failures.append("shared-bus")

    methods = {
        "BluetoothGetState": 1,
        "BluetoothSetPowered": 1,
        "BluetoothStartDiscovery": 2,
        "BluetoothStopDiscovery": 2,
        "BluetoothPair": 1,
        "BluetoothConnect": 1,
        "BluetoothDisconnect": 1,
        "BluetoothForget": 1,
    }
    if any(service.count(f'"{method}"') != count
           for method, count in methods.items()):
        failures.append("bridge-methods")

    if not all(token in service for token in (
            "ConnectToSignal(",
            "kHostBridgeInterface, kHostBridgeEvent",
            '*source == "bluetooth"',
            "RefreshState();")):
        failures.append("event-refresh")

    if ("json.size() > kMaxBridgeResponseBytes" not in service or
            "devices->size() > kMaxDevices" not in service or
            service.count("!base::IsStringUTF8(json)") != 2):
        failures.append("response-bounds")

    states = (
        "BluetoothSystemState::kUnavailable",
        "BluetoothSystemState::kDisabled",
        "BluetoothSystemState::kDisabling",
        "BluetoothSystemState::kEnabled",
        "BluetoothSystemState::kEnabling",
    )
    if any(state not in service for state in states):
        failures.append("system-state")

    if ("if (device.paired)" not in service or
            "if (!device.paired)" not in service or
            service.count("OnDiscoveredDevicesListChanged(BuildDiscoveredDevices())") != 2):
        failures.append("device-lists")

    if ("std::move(callback).Run(response.ok);" not in service or
            service.count("PairingResult::kSuccess") != 1 or
            service.count("PairingResult::kAuthFailed") != 1 or
            service.count("PairingResult::kNonAuthFailure") != 2):
        failures.append("operation-results")

    if not all(token in service for token in (
            "constexpr int kHostBridgeTimeoutMs = 30000;",
            'reason.find("agent")')) or service.count(
                "OnBluetoothDiscoveryStopped();") != 2:
        failures.append("pairing-boundary")
    if not all(token in header for token in (
            "JustWorks pairing are",
            "PIN and passkey pairing require a BlueZ agent",
            "finish with a pairing failure")):
        failures.append("pairing-limitation")

    if (build.count('"aurade_bluetooth_service.cc"') != 2 or
            build.count('"aurade_bluetooth_service.h"') != 1 or
            build.count('"aurade_bluetooth_service_unittest.cc"') != 2 or
            'executable("aurade_bluetooth_service_tests")' not in build):
        failures.append("build-wiring")

    if main.count("SetBluetoothConfigServiceBinderForGenericLinux({});") != 2:
        failures.append("cleanup")

    if "InitializeDBusClient" in all_added or "use_real_dbus_clients" in all_added:
        failures.append("forbidden-dbus")

    if (tests.count("invalid_utf8") != 3 or
            "1024 * 1024 + 1" not in tests or
            "index < 257" not in tests or
            "not-an-address" not in tests or
            "AuthenticationRejected" not in tests):
        failures.append("unit-coverage")

    if re.search("[\u2013\u2014]", raw):
        failures.append("house-style")
    if re.search(r"(?i)\bgenerated by (?:a tool|an automated tool)\b", raw):
        failures.append("house-style")

    return failures


@dataclass(frozen=True)
class Mutation:
    name: str
    assertion: str
    old: str
    new: str
    target: str = "patch"


mutations = [
    Mutation("series entry", "series", PATCH_NAME,
             "0058-bluetooth-missing.patch", "series"),
    Mutation("target inventory", "targets",
             "diff --git a/ash/public/cpp/bluetooth_config_service.cc b/ash/public/cpp/bluetooth_config_service.cc",
             "diff --git a/ash/public/cpp/bluetooth_config_service.cc b/ash/public/cpp/bluetooth_config_service-moved.cc"),
    Mutation("host boundary", "host-boundary", "", "\ndiff --git a/aurade-host-bridge/x b/aurade-host-bridge/x\n"),
    Mutation("written path disagrees with the header", "header-mismatch",
             "+++ b/ash/public/cpp/bluetooth_config_service.cc",
             "+++ b/ash/public/cpp/bluetooth_config_service-moved.cc"),
    Mutation("host bridge reached through the +++ line", "host-boundary",
             "+++ b/ash/public/cpp/bluetooth_config_service.cc",
             "+++ b/aurade-host-bridge/aurade_host_bridge.py"),
    Mutation("binder setter", "binder-route",
             "SetBluetoothConfigServiceBinderForGenericLinux(",
             "SetBluetoothConfigServiceBinderMissing("),
    Mutation("binder branch", "binder-route",
             "if (GetGenericLinuxBinder())", "if (false)"),
    Mutation("binder dispatch", "binder-route",
             "GetGenericLinuxBinder().Run(std::move(receiver));",
             "bluetooth_config::BindToInProcessInstance(std::move(receiver));"),
    Mutation("public header include", "shared-bus",
             '+#include "ash/public/cpp/bluetooth_config_service.h"',
             '+#include "ash/public/cpp/missing_bluetooth_service.h"'),
    Mutation("service header include", "shared-bus",
             ' #include "chrome/browser/ash/dbus/ash_dbus_helper.h"\n'
             '+#include "chrome/browser/ash/dbus/aurade_bluetooth_service.h"',
             ' #include "chrome/browser/ash/dbus/ash_dbus_helper.h"\n'
             '+#include "chrome/browser/ash/dbus/missing_bluetooth_service.h"'),
    Mutation("shared bus", "shared-bus", "GetAuraDeSharedSystemBus()",
             "nullptr"),
]

for method in (
        "BluetoothGetState", "BluetoothSetPowered", "BluetoothStartDiscovery",
        "BluetoothStopDiscovery", "BluetoothPair", "BluetoothConnect",
        "BluetoothDisconnect", "BluetoothForget"):
    mutations.append(Mutation(f"method {method}", "bridge-methods",
                              f'"{method}"', f'"Missing{method}"'))

mutations.extend([
    Mutation("event connection", "event-refresh", "kHostBridgeInterface, kHostBridgeEvent",
             "kHostBridgeInterface, \"MissingEvent\""),
    Mutation("event source", "event-refresh", '*source == "bluetooth"',
             '*source == "storage"'),
    Mutation("response byte cap", "response-bounds",
             "json.size() > kMaxBridgeResponseBytes", "false"),
    Mutation("device count cap", "response-bounds",
             "devices->size() > kMaxDevices", "false"),
    Mutation("UTF8 validation", "response-bounds",
             "!base::IsStringUTF8(json)", "false"),
    Mutation("unavailable state", "system-state",
             "BluetoothSystemState::kUnavailable", "BluetoothSystemState::kDisabled",),
    Mutation("disabled state", "system-state",
             "BluetoothSystemState::kDisabled", "BluetoothSystemState::kUnavailable"),
    Mutation("disabling state", "system-state",
             "BluetoothSystemState::kDisabling", "BluetoothSystemState::kDisabled"),
    Mutation("enabled state", "system-state",
             "BluetoothSystemState::kEnabled", "BluetoothSystemState::kDisabled"),
    Mutation("enabling state", "system-state",
             "BluetoothSystemState::kEnabling", "BluetoothSystemState::kEnabled"),
    Mutation("paired list", "device-lists", "if (device.paired)", "if (false)"),
    Mutation("discovered list", "device-lists", "if (!device.paired)", "if (false)"),
    Mutation("discovery delivery", "device-lists",
             "OnDiscoveredDevicesListChanged(BuildDiscoveredDevices())",
             "OnBluetoothDiscoveryStopped()"),
    Mutation("operation callback", "operation-results",
             "std::move(callback).Run(response.ok);",
             "std::move(callback).Run(false);"),
    Mutation("pair success", "operation-results", "PairingResult::kSuccess",
             "PairingResult::kNonAuthFailure"),
    Mutation("auth failure", "operation-results", "PairingResult::kAuthFailed",
             "PairingResult::kNonAuthFailure"),
    Mutation("non-auth failure", "operation-results",
             "PairingResult::kNonAuthFailure", "PairingResult::kAuthFailed"),
    Mutation("bounded call", "pairing-boundary",
             "constexpr int kHostBridgeTimeoutMs = 30000;",
             "constexpr int kHostBridgeTimeoutMs = 0;"),
    Mutation("agent failure", "pairing-boundary", 'reason.find("agent")',
             'reason.find("never-agent")'),
    Mutation("stopped callback", "pairing-boundary",
             "OnBluetoothDiscoveryStopped();", "OnBluetoothDiscoveryStarted({});"),
    Mutation("JustWorks scope", "pairing-limitation", "JustWorks pairing are",
             "all pairing modes are"),
    Mutation("PIN limitation", "pairing-limitation",
             "PIN and passkey pairing require a BlueZ agent",
             "PIN and passkey pairing are supported"),
    Mutation("failure promise", "pairing-limitation",
             "finish with a pairing failure", "wait for pairing"),
    Mutation("service source build", "build-wiring",
             '"aurade_bluetooth_service.cc"', '"missing_bluetooth_service.cc"'),
    Mutation("service header build", "build-wiring",
             '"aurade_bluetooth_service.h"', '"missing_bluetooth_service.h"'),
    Mutation("unit source build", "build-wiring",
             '"aurade_bluetooth_service_unittest.cc"',
             '"missing_bluetooth_service_unittest.cc"'),
    Mutation("standalone test target", "build-wiring",
             'executable("aurade_bluetooth_service_tests")',
             'group("aurade_bluetooth_service_tests")'),
    Mutation("first cleanup", "cleanup",
             "SetBluetoothConfigServiceBinderForGenericLinux({});",
             "SetBluetoothConfigServiceBinderForGenericLinuxMissing({});"),
    Mutation("forbidden client init", "forbidden-dbus", "",
             "\n+InitializeDBusClient();\n"),
    Mutation("invalid UTF8 test", "unit-coverage", "invalid_utf8",
             "valid_utf8"),
    Mutation("oversize test", "unit-coverage", "1024 * 1024 + 1",
             "1024"),
    Mutation("device count test", "unit-coverage", "index < 257",
             "index < 2"),
    Mutation("bad address test", "unit-coverage", "not-an-address",
             "01:23:45:67:89:ab"),
    Mutation("interactive failure test", "unit-coverage",
             "AuthenticationRejected", "BackendUnavailable"),
    Mutation("dash style", "house-style", "", "\n+// bad \u2014 dash\n"),
    Mutation("generated attribution", "house-style", "", "\n+// Generated by a tool\n"),
])


def apply_mutation(mutation: Mutation, raw: str, series: str) -> tuple[str, str]:
    if mutation.target == "series":
        if mutation.old not in series:
            raise ValueError(f"mutation source is absent: {mutation.name}")
        return raw, series.replace(mutation.old, mutation.new, 1)
    if mutation.old:
        if mutation.old not in raw:
            raise ValueError(f"mutation source is absent: {mutation.name}")
        return raw.replace(mutation.old, mutation.new, 1), series
    return raw + mutation.new, series


baseline_failures = validate(patch_text, series_text)
if baseline_failures:
    print("bluetooth host bridge test: FAIL: " +
          ", ".join(sorted(set(baseline_failures))), file=sys.stderr)
    raise SystemExit(1)

if mode == "--mutation-audit":
    print("mutation | assertion | result")
    print("--- | --- | ---")
    for mutation in mutations:
        mutated_patch, mutated_series = apply_mutation(
            mutation, patch_text, series_text)
        failures = validate(mutated_patch, mutated_series)
        if mutation.assertion not in failures:
            print(f"{mutation.name} | {mutation.assertion} | NOT CAUGHT")
            raise SystemExit(1)
        print(f"{mutation.name} | {mutation.assertion} | caught")
    print(f"bluetooth host bridge mutation audit: PASS ({len(mutations)} mutations)")
elif mode:
    print(f"bluetooth host bridge test: unknown option: {mode}", file=sys.stderr)
    raise SystemExit(2)
else:
    print("bluetooth host bridge test: PASS")
PY
