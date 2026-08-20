# AuraDE Host Bridge

`aurade-host-bridge` exposes standard Arch Linux host services through two
small D-Bus APIs intended for AuraDE Chromium adapters:

- `org.aurade.HostBridge1` on the system bus provides BlueZ, udisks2, and
  pacman operations.
- `org.aurade.DesktopBridge1` on the user session bus opens files and URIs
  with `gio open` or `xdg-open` in the correct desktop environment.

All methods return a JSON string with schema version 1, an operation name,
an `ok` boolean, and either `data` or a stable error object. No method accepts
a shell command or arbitrary executable. The service never invokes a shell.

## System API

The system service owns `org.aurade.HostBridge` at
`/org/aurade/HostBridge`. Interface `org.aurade.HostBridge1` provides:

| Area | Methods |
| --- | --- |
| General | `GetCapabilities`, `JobGet` |
| Bluetooth | `BluetoothGetState`, `BluetoothSetPowered`, `BluetoothStartDiscovery`, `BluetoothStopDiscovery`, `BluetoothPair`, `BluetoothConnect`, `BluetoothDisconnect`, `BluetoothForget` |
| Storage | `StorageList`, `StorageMount`, `StorageUnmount`, `StorageEject`, `StoragePowerOff`, `StorageFormat` |
| Packages | `PacmanListInstalled`, `PacmanQuery`, `PacmanListUpdates`, `PacmanUpgrade`, `PacmanUninstall` |

`Event(s json)` reports BlueZ and udisks2 topology/property invalidation plus
pacman job completion. Consumers should refresh the relevant state method
after an event instead of treating an event as a complete state snapshot.

Pacman upgrade and uninstall return a job ID immediately. They are serialized
because pacman supports only one database writer. `JobGet` exposes status and
bounded output to the Unix user that started the job, even when that user
reconnects with a different D-Bus unique name. On an AuraDE-installed Btrfs
system, an upgrade must first create a read-only root snapshot and preserve the
matching kernel, microcode, and initramfs behind the rollback boot entry. A
snapshot or boot-payload failure prevents pacman from starting.

## Session API

The activatable session service owns `org.aurade.DesktopBridge` at
`/org/aurade/DesktopBridge`. `MimeOpen(s target)` accepts an absolute local
path or a `file`, `http`, `https`, or `mailto` URI. Running this bridge on the
session bus preserves the user's MIME database, environment, and application
activation bus; the root system daemon never launches graphical programs.

## Security Boundaries

- D-Bus reads are unprivileged. Every mutating system method authorizes the
  original caller through polkit before the root service contacts its backend.
- Bluetooth and ordinary removable-media actions are allowed to an active
  local session. Package changes and formatting require administrator
  authentication.
- Package names, Bluetooth addresses, object paths, filesystem types, volume
  labels, MIME schemes, and job IDs use strict allowlists.
- Device mutations are restricted to udisks objects backed by removable media
  or a drive on an explicitly external bus. Blocks marked as system devices,
  mounted at a system path, or belonging to an internal drive are rejected.
  The caller must echo the exact `FORMAT /dev/...` token returned by
  `StorageList`.
- The bridge cannot make pacman package scripts fully sandboxed: a system
  upgrade intentionally runs trusted Arch package hooks as root. The D-Bus
  input surface cannot select a command, executable, option, or package whose
  name fails Arch's package-name grammar. A fixed denylist also prevents the
  desktop uninstall API from removing AuraDE, pacman, systemd, the kernel, or
  other boot-critical packages; an administrator can still manage those from
  a terminal or recovery environment.

## CLI

`aurade-hostctl` is both an operator tool and an executable API example:

```sh
aurade-hostctl --pretty capabilities
aurade-hostctl --pretty bluetooth state
aurade-hostctl bluetooth scan start
aurade-hostctl --pretty storage list
aurade-hostctl storage unmount /org/freedesktop/UDisks2/block_devices/sdb1
aurade-hostctl storage format \
  /org/freedesktop/UDisks2/block_devices/sdb1 ext4 \
  --label BACKUP --confirm 'FORMAT /dev/sdb1'
aurade-hostctl --pretty pacman updates
aurade-hostctl pacman upgrade
aurade-hostctl pacman job JOB_ID
aurade-hostctl mime open "$HOME/Documents/report.pdf"
aurade-hostctl events
```

Use global `--dry-run` with a mutating command to validate its arguments
without contacting D-Bus or changing the host.

## Testing

The test suite uses fake BlueZ/udisks facades, a fake command runner, and a
fake MIME process launcher. It does not need Bluetooth hardware, udisks2, or a
pacman transaction:

```sh
./run-tests.sh
```

## Chromium Work Still Required

This package supplies the host-side boundary only. AuraDE still needs thin
Chromium adapters that:

1. map `BluetoothGetState` and `Event` to `device::BluetoothAdapter` state and
   pairing UI requests;
2. map `StorageList` and storage events/actions into the Linux
   `DiskMountManager` implementation and Files error notifications;
3. route Files open-with actions to the session `MimeOpen` method;
4. map package query/jobs into application uninstall and update UI, including
   progress, completion, and rollback presentation.

Pairing agents and passkey/PIN prompts need a dedicated session-side BlueZ
agent in that Chromium integration. This bridge intentionally does not guess
or auto-accept pairing credentials.
