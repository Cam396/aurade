# AuraDE hardware validation

This page records public, user-visible results. Detailed logs and raw hardware
reports stay private.

## Current matrix

| Hardware class | Install | Desktop | Network | Notes |
| --- | --- | --- | --- | --- |
| VMware UEFI guest | Pass | Pass | Pass | Repeatable GUI, text, reboot, and rollback checks |
| Low-memory eMMC laptop | Pass | Pass with limits | Ethernet pass, Wi-Fi integration open | Slow storage and limited memory expose timing and swap issues |
| Intel laptop | Pending | Pending | Pending | Requires a physical qualification run |
| AMD laptop | Pending | Pending | Pending | Requires a physical qualification run |

## Low-memory eMMC result

A small, older laptop with limited memory and eMMC storage completed the AuraDE
installation and reached the ChromeOS-style desktop. The local account,
first login, wired networking, audio, wallpaper, theme, and session controls
worked.

The machine is slow, as expected for this hardware class. The graphical
installer can remain on the erase page while the engine starts, and swap setup
can report a recoverable warning before the installation continues. Wi-Fi is
visible to NetworkManager but the ChromeOS-style network surface still needs a
faithful access-point and connect operation. These are open integration and
performance issues, not a claim that the machine is fully qualified.

## What remains

- Capture and fix the progress transition on low-memory systems.
- Classify the swap warning from a post-boot service report.
- Finish the NetworkManager Wi-Fi scan and association path.
- Repeat the pass after the next exact ISO build.
- Add Intel and AMD hardware results before a stable release claim.
