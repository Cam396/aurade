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
    DiskUsageBackend,
    MimeLauncher,
    PacmanBackend,
    StorageBackend,
    normalize_open_target,
    parse_btrfs_qgroups,
    parse_btrfs_subvolumes,
    parse_btrfs_usage,
    parse_installed_size,
    parse_size,
    plain_breakdown,
    response,
    storage_breakdown,
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


# Real shapes, copied from what these tools actually print. A parser tested
# against output invented to suit it is a parser tested against itself.
BTRFS_USAGE = """Overall:
    Device size:\t\t\t 500107862016
    Device allocated:\t\t  64424509440
    Device unallocated:\t\t 435683352576
    Device missing:\t\t\t            0
    Used:\t\t\t\t  51539607552
    Free (estimated):\t\t 447626903552\t(min: 229785227264)
    Data ratio:\t\t\t\t         1.00
    Metadata ratio:\t\t\t         2.00
"""

BTRFS_QGROUPS = """qgroupid         rfer         excl
--------         ----         ----
0/5             16384        16384
0/256     34359738368  21474836480
0/257     21474836480  17179869184
0/300     34359738368   4294967296
0/301     34359738368   2147483648
1/0       55834574848  38654705664
"""

BTRFS_SUBVOLUMES = """ID 256 gen 4021 top level 5 path @
ID 257 gen 4020 top level 5 path @home
ID 300 gen 3001 top level 5 path <FS_TREE>/@snapshots/2026-08-01-pre-update
ID 301 gen 3400 top level 5 path <FS_TREE>/@snapshots/2026-08-20-pre-update
"""

PACMAN_INFO = """Name            : bash
Version         : 5.3-1
Installed Size  : 8.20 MiB

Name            : linux
Version         : 6.18-1
Installed Size  : 142.50 MiB

Name            : chromiumos-ash
Version         : 154.0.8015.0-1
Installed Size  : 1.20 GiB
"""


class StorageReadingTest(unittest.TestCase):
    def test_sizes_are_read_not_guessed(self):
        self.assertEqual(parse_size("8.20 MiB"), int(8.20 * 1024 ** 2))
        self.assertEqual(parse_size("1.20 GiB"), int(1.20 * 1024 ** 3))
        self.assertEqual(parse_size("512 B"), 512)
        # A unit nobody has checked is worth nothing, not a wrong number.
        self.assertEqual(parse_size("4 furlongs"), 0)
        self.assertEqual(parse_size(""), 0)
        self.assertEqual(parse_size("about a gigabyte"), 0)

    def test_btrfs_usage_is_the_volume_not_the_filesystem(self):
        usage = parse_btrfs_usage(BTRFS_USAGE)
        self.assertEqual(usage["total"], 500107862016)
        self.assertEqual(usage["used"], 51539607552)
        # The estimate carries a parenthesised minimum after it, which is not
        # part of the number.
        self.assertEqual(usage["free"], 447626903552)

    def test_qgroups_carry_both_numbers(self):
        qgroups = parse_btrfs_qgroups(BTRFS_QGROUPS)
        self.assertEqual(qgroups["256"], {"referenced": 34359738368,
                                          "exclusive": 21474836480})
        self.assertEqual(qgroups["300"]["exclusive"], 4294967296)
        # The header lines are not subvolumes.
        self.assertNotIn("rfer", qgroups)
        # Nor is a level one accounting group. 1/0 is not subvolume 0, and
        # reading it as one puts a total spanning several subvolumes onto a
        # row carrying one subvolume's name.
        self.assertEqual(qgroups.get("0", {}).get("exclusive"), None)
        self.assertEqual(len(qgroups), 5)

    def test_subvolume_paths_lose_the_tree_prefix(self):
        subvolumes = parse_btrfs_subvolumes(BTRFS_SUBVOLUMES)
        paths = [entry["path"] for entry in subvolumes]
        self.assertEqual(paths, ["@", "@home",
                                 "@snapshots/2026-08-01-pre-update",
                                 "@snapshots/2026-08-20-pre-update"])
        self.assertEqual(subvolumes[0]["id"], "256")

    def test_installed_size_adds_up(self):
        total = parse_installed_size(PACMAN_INFO)
        expected = int(8.20 * 1024 ** 2) + int(142.50 * 1024 ** 2) + int(1.20 * 1024 ** 3)
        self.assertEqual(total, expected)

    def test_snapshots_are_sized_by_what_deleting_them_returns(self):
        """Referenced bytes would offer space that is not there.

        Both snapshots reference 32GiB, the same 32GiB the live system
        references. Reporting that would tell somebody they could reclaim
        64GiB from a volume holding 48GiB in total.
        """
        breakdown = storage_breakdown(
            parse_btrfs_usage(BTRFS_USAGE),
            parse_btrfs_qgroups(BTRFS_QGROUPS),
            parse_btrfs_subvolumes(BTRFS_SUBVOLUMES),
            parse_installed_size(PACMAN_INFO),
        )
        rows = {row["key"]: row for row in breakdown["rows"]}
        self.assertEqual(rows["snapshots"]["bytes"], 4294967296 + 2147483648)
        self.assertEqual(rows["snapshots"]["count"], 2)
        self.assertLess(rows["snapshots"]["bytes"], breakdown["used"])

    def test_no_row_is_a_remainder_pretending_to_be_a_measurement(self):
        breakdown = storage_breakdown(
            parse_btrfs_usage(BTRFS_USAGE),
            parse_btrfs_qgroups(BTRFS_QGROUPS),
            parse_btrfs_subvolumes(BTRFS_SUBVOLUMES),
            parse_installed_size(PACMAN_INFO),
        )
        rows = {row["key"]: row for row in breakdown["rows"]}
        self.assertFalse(rows["shared"]["measured"],
                         "blocks belonging to no one row were presented as a measurement")
        self.assertTrue(rows["packages"]["measured"])
        self.assertTrue(rows["home"]["measured"])
        for row in breakdown["rows"]:
            self.assertIn("measured", row,
                          f"the {row['key']} row does not say whether anybody counted it")

    def test_packages_never_exceed_the_volume_they_sit_on(self):
        """pacman's own figure is an estimate and can overshoot."""
        breakdown = storage_breakdown(
            parse_btrfs_usage(BTRFS_USAGE),
            parse_btrfs_qgroups(BTRFS_QGROUPS),
            parse_btrfs_subvolumes(BTRFS_SUBVOLUMES),
            10 ** 15,
        )
        rows = {row["key"]: row for row in breakdown["rows"]}
        self.assertLessEqual(rows["packages"]["bytes"], 21474836480)
        self.assertGreaterEqual(rows["system"]["bytes"], 0)

    def test_a_volume_with_quotas_off_says_so_instead_of_guessing(self):
        breakdown = storage_breakdown(
            parse_btrfs_usage(BTRFS_USAGE), {},
            parse_btrfs_subvolumes(BTRFS_SUBVOLUMES), 0)
        rows = {row["key"]: row for row in breakdown["rows"]}
        self.assertEqual(rows["snapshots"]["bytes"], 0)
        self.assertFalse(rows["system"]["measured"])
        self.assertEqual(breakdown["total"], 500107862016)

    def test_a_filesystem_that_is_not_btrfs_gets_no_invented_rows(self):
        breakdown = plain_breakdown(500107862016, 447626903552)
        self.assertEqual(breakdown["rows"], [])
        self.assertFalse(breakdown["detailed"])
        self.assertEqual(breakdown["used"], 500107862016 - 447626903552)

    def test_the_whole_reading_from_a_fake_disk(self):
        runner = FakeRunner([
            CommandResult(0, "/dev/nvme0n1p2[/@] btrfs\n", ""),   # findmnt
            CommandResult(0, BTRFS_USAGE, ""),                    # filesystem usage
            CommandResult(0, BTRFS_QGROUPS, ""),                  # qgroup show
            CommandResult(0, BTRFS_SUBVOLUMES, ""),               # subvolume list
            CommandResult(0, PACMAN_INFO, ""),                    # pacman -Qi
            CommandResult(0, "500107862016\n", ""),               # lsblk
        ])
        backend = DiskUsageBackend(runner)
        state = backend.state()
        self.assertEqual(state["filesystem"], "btrfs")
        # The subvolume bracket is not part of the device name, and lsblk
        # would refuse it.
        self.assertEqual(state["device"], "/dev/nvme0n1p2")
        self.assertTrue(state["detailed"])
        self.assertTrue(state["quotas"])
        rows = {row["key"]: row for row in state["rows"]}
        self.assertEqual(rows["home"]["bytes"], 17179869184)
        self.assertEqual(rows["snapshots"]["count"], 2)
        lsblk_call = [call for call in runner.calls if "lsblk" in call[0][0]]
        self.assertEqual(lsblk_call[0][0][-1], "/dev/nvme0n1p2")

    def test_the_two_pages_report_the_same_snapshot_bytes(self):
        """The storage page and the snapshot page must agree.

        They are two views of one number. If they can disagree, one of them is
        lying and nobody can tell which.
        """
        def fresh():
            return FakeRunner([
                CommandResult(0, "/dev/nvme0n1p2[/@] btrfs\n", ""),
                CommandResult(0, BTRFS_USAGE, ""),
                CommandResult(0, BTRFS_QGROUPS, ""),
                CommandResult(0, BTRFS_SUBVOLUMES, ""),
                CommandResult(0, PACMAN_INFO, ""),
                CommandResult(0, "500107862016\n", ""),
            ])

        storage = DiskUsageBackend(fresh()).state()
        listing = DiskUsageBackend(FakeRunner([
            CommandResult(0, "/dev/nvme0n1p2[/@] btrfs\n", ""),
            CommandResult(0, BTRFS_QGROUPS, ""),
            CommandResult(0, BTRFS_SUBVOLUMES, ""),
        ])).snapshots()
        page_total = {row["key"]: row for row in storage["rows"]}["snapshots"]["bytes"]
        listed_total = sum(item["reclaimable"] for item in listing["snapshots"])
        self.assertEqual(page_total, listed_total)
        self.assertEqual(len(listing["snapshots"]), 2)
        self.assertEqual(listing["snapshots"][0]["name"], "2026-08-01-pre-update")

    def test_a_volume_with_quotas_off_stops_claiming_a_breakdown(self):
        """Through the backend, where the decision is actually made.

        The rows still exist, because the interface has a shape, but every one
        of them says nobody counted it and the breakdown says it is not
        detailed. A storage page drawing a pie chart from these would be
        drawing a picture of zero.
        """
        runner = FakeRunner([
            CommandResult(0, "/dev/nvme0n1p2[/@] btrfs\n", ""),
            CommandResult(0, BTRFS_USAGE, ""),
            CommandResult(1, "", "ERROR: can't list qgroups: quotas not enabled"),
            CommandResult(0, BTRFS_SUBVOLUMES, ""),
            CommandResult(0, PACMAN_INFO, ""),
            CommandResult(0, "500107862016\n", ""),
        ])
        state = DiskUsageBackend(runner).state()
        self.assertFalse(state["quotas"])
        self.assertFalse(state["detailed"],
                         "a volume with no quota data still claimed a breakdown")
        for row in state["rows"]:
            self.assertFalse(row["measured"],
                             f"the {row['key']} row was presented as counted")
        # The totals are still true, because they do not come from quotas.
        self.assertEqual(state["total"], 500107862016)
        self.assertEqual(state["used"], 51539607552)

    def test_an_unreadable_filesystem_is_an_error_not_a_zero(self):
        runner = FakeRunner([CommandResult(1, "", "findmnt: no such target")])
        with self.assertRaises(BridgeError):
            DiskUsageBackend(runner).state()
