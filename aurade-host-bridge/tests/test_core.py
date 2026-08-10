#!/usr/bin/python
"""Unit tests for the host bridge without real host daemons."""

from __future__ import annotations

import json
import unittest

from aurade_host_bridge import event_payload
from aurade_host_bridge_core import (
    BLUEZ_ADAPTER,
    BLUEZ_DEVICE,
    UDISKS_BLOCK,
    UDISKS_DRIVE,
    UDISKS_FILESYSTEM,
    BluetoothBackend,
    BridgeError,
    CommandResult,
    MimeLauncher,
    PacmanBackend,
    StorageBackend,
    normalize_open_target,
    response,
    validate_mac,
    validate_package,
)


class FakeFacade:
    def __init__(self, objects):
        self.objects = objects
        self.calls = []

    def managed_objects(self, service, root):
        return self.objects

    def call(self, service, path, interface, method, *args):
        self.calls.append((service, path, interface, method, args))
        if method == "Mount":
            return "/run/media/test/USB"
        return None

    def set_property(self, service, path, interface, prop, value):
        self.calls.append((service, path, interface, "Set", (prop, value)))


class FakeRunner:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def run(self, argv, *, timeout=120):
        self.calls.append((list(argv), timeout))
        return self.results.pop(0)


class FakeProcess:
    pid = 4242


class ValidationTest(unittest.TestCase):
    def test_event_envelope_keeps_source_and_legacy_domain_in_sync(self):
        payload = json.loads(event_payload("storage", "interfaces-added"))
        self.assertEqual(payload["source"], "storage")
        self.assertEqual(payload["domain"], payload["source"])
        self.assertEqual(payload["kind"], "interfaces-added")

    def test_strict_bluetooth_and_package_names(self):
        self.assertEqual(validate_mac("aa:bb:cc:dd:ee:ff"), "AA:BB:CC:DD:EE:FF")
        self.assertEqual(validate_package("linux-firmware"), "linux-firmware")
        for value in ("AA:BB", "AA:BB:CC:DD:EE:GG", "$(id)"):
            with self.assertRaises(BridgeError):
                validate_mac(value)
        for value in ("-R", "foo;id", "Foo", ""):
            with self.assertRaises(BridgeError):
                validate_package(value)

    def test_open_targets_reject_commands_and_remote_files(self):
        self.assertEqual(normalize_open_target("/tmp/report.pdf"), "/tmp/report.pdf")
        self.assertEqual(normalize_open_target("https://example.test/a"), "https://example.test/a")
        for value in ("relative.txt", "command:rm", "file://server/share/file", "/tmp/a\n--help"):
            with self.assertRaises(BridgeError):
                normalize_open_target(value)

    def test_response_does_not_expose_exception_types(self):
        payload = json.loads(response("test", error=BridgeError("denied", "no", {"safe": True})))
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "denied")
        self.assertEqual(payload["schema"], 1)


class BluetoothTest(unittest.TestCase):
    def setUp(self):
        self.objects = {
            "/org/bluez/hci0": {BLUEZ_ADAPTER: {
                "Address": "00:11:22:33:44:55", "Alias": "host", "Powered": True,
                "Discovering": False, "Pairable": True,
            }},
            "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF": {BLUEZ_DEVICE: {
                "Adapter": "/org/bluez/hci0", "Address": "AA:BB:CC:DD:EE:FF",
                "Name": "Headset", "Paired": True, "Connected": False,
                "Trusted": True, "RSSI": -41, "UUIDs": ["audio"],
            }},
        }
        self.facade = FakeFacade(self.objects)
        self.backend = BluetoothBackend(self.facade)

    def test_state_and_adapter_operations(self):
        state = self.backend.state()
        self.assertEqual(state["devices"][0]["name"], "Headset")
        self.assertFalse(self.backend.set_powered(True)["changed"])
        self.backend.set_powered(False)
        self.backend.discovery(True)
        self.assertEqual(self.facade.calls[0][3:], ("Set", ("Powered", False)))
        self.assertEqual(self.facade.calls[1][3], "StartDiscovery")

    def test_device_operations_use_known_object_only(self):
        self.backend.device_action("aa:bb:cc:dd:ee:ff", "connect")
        self.backend.device_action("AA:BB:CC:DD:EE:FF", "forget")
        self.assertEqual(self.facade.calls[0][3], "Connect")
        self.assertEqual(self.facade.calls[1][1], "/org/bluez/hci0")
        self.assertEqual(self.facade.calls[1][3], "RemoveDevice")
        with self.assertRaises(BridgeError):
            self.backend.device_action("11:22:33:44:55:66", "pair")


class StorageTest(unittest.TestCase):
    block_path = "/org/freedesktop/UDisks2/block_devices/sdb1"
    drive_path = "/org/freedesktop/UDisks2/drives/USB"

    def objects(self, *, system=False, removable=True):
        return {
            self.drive_path: {UDISKS_DRIVE: {
                "Vendor": "Test", "Model": "Disk", "Removable": removable,
                "Ejectable": True, "MediaAvailable": True, "Size": 1000,
                "ConnectionBus": "" if removable else "ata",
            }},
            self.block_path: {
                UDISKS_BLOCK: {
                    "PreferredDevice": b"/dev/sdb1\0", "Drive": self.drive_path,
                    "IdUsage": "filesystem", "IdType": "ext4", "IdLabel": "USB",
                    "Size": 1000, "HintSystem": system,
                },
                UDISKS_FILESYSTEM: {"MountPoints": []},
            },
        }

    def test_enumerate_mount_unmount_and_remove(self):
        facade = FakeFacade(self.objects())
        backend = StorageBackend(facade)
        state = backend.state()
        self.assertEqual(state["blocks"][0]["device"], "/dev/sdb1")
        self.assertEqual(state["blocks"][0]["format_confirmation"], "FORMAT /dev/sdb1")
        self.assertEqual(backend.mount(self.block_path, True, "test")["mount_point"], "/run/media/test/USB")
        self.assertEqual(facade.calls[0][4][0], {"as-user": "test", "options": "ro"})
        backend.unmount(self.block_path, False)
        backend.drive_action(self.drive_path, "eject")
        backend.drive_action(self.drive_path, "poweroff")
        self.assertEqual([call[3] for call in facade.calls], ["Mount", "Unmount", "Eject", "PowerOff"])

    def test_format_requires_exact_confirmation_and_removable_media(self):
        facade = FakeFacade(self.objects())
        backend = StorageBackend(facade)
        with self.assertRaisesRegex(BridgeError, "confirmation"):
            backend.format(self.block_path, "ext4", "USB", "yes")
        result = backend.format(self.block_path, "ext4", "USB", "FORMAT /dev/sdb1")
        self.assertEqual(result["filesystem"], "ext4")
        self.assertEqual(facade.calls[-1][3], "Format")
        with self.assertRaisesRegex(BridgeError, "system"):
            system_backend = StorageBackend(FakeFacade(self.objects(system=True)))
            system_backend.format(self.block_path, "ext4", "", "FORMAT /dev/sdb1")
        with self.assertRaisesRegex(BridgeError, "system"):
            system_backend.unmount(self.block_path, False)
        with self.assertRaisesRegex(BridgeError, "external"):
            StorageBackend(FakeFacade(self.objects(removable=False))).format(
                self.block_path, "ext4", "", "FORMAT /dev/sdb1")

    def test_fixed_usb_media_is_treated_as_external(self):
        objects = self.objects(removable=False)
        objects[self.drive_path][UDISKS_DRIVE]["ConnectionBus"] = "usb"
        backend = StorageBackend(FakeFacade(objects))
        self.assertEqual(backend.mount(self.block_path, False, "test")["mount_point"], "/run/media/test/USB")


class PacmanAndMimeTest(unittest.TestCase):
    def test_pacman_queries_parse_structured_results(self):
        runner = FakeRunner([
            CommandResult(0, "alpha 1.0\nbeta 2.0\n", ""),
            CommandResult(0, "alpha 1.0\n", ""),
            CommandResult(0, "alpha 1.0 -> 1.1\n", ""),
        ])
        backend = PacmanBackend(runner, checkupdates="/definitely/not-installed")
        self.assertEqual(len(backend.installed()["packages"]), 2)
        self.assertTrue(backend.query("alpha")["installed"])
        update = backend.updates()["packages"][0]
        self.assertEqual(update["available_version"], "1.1")
        self.assertEqual(backend.uninstall_command(["alpha"], True),
                         ["/usr/bin/pacman", "-Rns", "--noconfirm", "alpha"])
        with self.assertRaisesRegex(BridgeError, "core system"):
            backend.uninstall_command(["systemd"], False)

    def test_upgrade_snapshot_failure_blocks_pacman(self):
        runner = FakeRunner([CommandResult(1, "", "snapshot failed")])
        backend = PacmanBackend(runner, recovery=__file__)
        with self.assertRaisesRegex(BridgeError, "rollback snapshot"):
            backend.prepare_upgrade()
        self.assertEqual(runner.calls[0][0][1:],
                         ["snapshot", "--label", "pre-update", "--set-rollback"])

    def test_mime_launcher_never_invokes_a_shell(self):
        calls = []
        def spawn(argv, **kwargs):
            calls.append((argv, kwargs))
            return FakeProcess()
        launcher = MimeLauncher(which=lambda name: "/usr/bin/gio" if name == "gio" else None, spawn=spawn)
        result = launcher.open("https://example.test/a?x=$(id)")
        self.assertEqual(result["pid"], 4242)
        self.assertEqual(calls[0][0], ["/usr/bin/gio", "open", "https://example.test/a?x=$(id)"])
        self.assertNotIn("shell", calls[0][1])


if __name__ == "__main__":
    unittest.main()
