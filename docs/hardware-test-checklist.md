# AuraDE hardware qualification checklist

Use this checklist with a disposable test machine and a matching ISO checksum.
It is intentionally generic. Keep serial numbers, raw logs, and machine access
details private.

## Before testing

- Back up the machine and confirm a recovery path.
- Record the model family, firmware mode, memory, storage type, and graphics
  family.
- Test on AC power first.
- Disconnect production accounts and private storage.
- Verify the ISO checksum and source revision.

## Installation pass

Record PASS, FAIL, or NOT PRESENT for each:

- UEFI boot and boot-menu entries.
- Graphical installer and text fallback.
- Display, pointer, keyboard, and touch input.
- Network scan, Wi-Fi association, and Ethernet.
- Plain installation and encrypted installation when supported.
- Progress updates, failure recovery, and diagnostic export.
- Reboot, first login, shutdown, and recovery entry.

## Desktop pass

- Display mode, scaling, brightness, and external display.
- Speakers, microphone, headphones, and volume controls.
- Wi-Fi reconnect, Ethernet, Bluetooth, and suspend/resume.
- Files, Settings, Diagnostics, Terminal, web apps, and context menus.
- Battery state, lid events, USB devices, and reboot.
- Three login and reboot cycles without a repeatable crash.

## Reporting

Public reports should contain the release or commit, model family, firmware
mode, result, and a short redacted description. Remove serial numbers, IP
addresses, user names, passwords, keys, private logs, and screenshots that show
personal information.
