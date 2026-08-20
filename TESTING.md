# Testing AuraDE

The test suite is split into cheap source checks, package checks, installer
fixtures, and runtime checks. A green source suite is useful evidence, but it
is not a substitute for booting the exact ISO on a disposable machine.

## Source and package checks

Run these before asking someone else to test an image:

~~~bash
git diff --check
ci/source-integrity-gate.sh
ci/public-release-leak-gate.sh
bash installer/tests/run.sh
~~~

The installer suite covers the GUI and text flows, journal rules, refusal
paths, graphics fallback, package staging, recovery fixtures, and public
contracts. A test that skips a runtime dependency must say SKIP; do not report
it as a pass.

## Disposable VM pass

Use a VM that can be erased and recreated. Start it through the host
hypervisor, attach only the candidate ISO and a disposable virtual disk, and
record the exact image checksum.

Check the following separately:

1. UEFI boot and the text fallback.
2. The graphical installer with hardware rendering.
3. The graphical installer with software rendering.
4. A plain Btrfs installation.
5. A LUKS2 installation.
6. Reboot, login, session startup, and shutdown.
7. Factory and manual rollback when Btrfs snapshots are selected.
8. Failure export and cleanup after an interrupted run.

Never use a host disk, a production key, or a private account in this pass.
QEMU is useful for ISO structure and boot-menu checks; the runtime gate is a
VM or real machine with a visible display.

## Hardware pass

For each laptop, record only the model family, firmware mode, and result. Test
display, audio, Wi-Fi, Ethernet, Bluetooth, keyboard, touchpad, suspend,
resume, USB, reboot, recovery, and encrypted boot. Low-memory and eMMC
systems deserve a separate row because they expose timing and swap problems
that a fast desktop hides.

## Reporting

A useful report says what image was used, what hardware family was tested, the
first failing action, and whether it repeats. Redact serial numbers, IP
addresses, user names, passwords, keys, raw coredumps, and private paths.
Attach a checksum and a short log excerpt rather than a whole home directory.
