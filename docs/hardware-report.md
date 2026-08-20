# AuraDE Hardware Report Tool

`aurade-hardware-report` is a small support tool for real-machine bring-up.
It is intentionally part of the public `aurade` package rather than the large
`chromiumos-ash` payload, so it can be updated and validated without rebuilding
Chromium.

## Why It Exists

The VMware image is useful for desktop workflow testing, but it does not cover
the hardware path that matters for a daily-driver desktop environment: low-memory
laptops, Intel/AMD/NVIDIA DRM, touchpads, audio stacks, suspend, external
displays, and sensor/fan devices.

The report gives AuraDE maintainers a repeatable snapshot from those machines:

| Area | Captured Examples |
|------|-------------------|
| System | OS release, kernel, failed services, logind sessions, inhibitors |
| AuraDE | installed package versions, launcher-owned files, Chrome process flags |
| CPU/RAM/storage | `lscpu`, memory, block devices, mounts |
| Storage health | `smartctl --scan-open` and read-only SMART health summaries when available |
| GPU/display | PCI kernel drivers, `/dev/dri`, DRM sysfs, GL/EGL/Vulkan/VAAPI summaries |
| Sensors | `lm_sensors` output and hwmon sysfs values |
| Power | `/sys/class/power_supply`, `/sys/class/backlight`, lid state, `upower`, `brightnessctl` |
| Audio | PipeWire/WirePlumber/Pulse views, ALSA device lists |
| Input | libinput devices and `/proc/bus/input/devices` |
| Network | IP routes, NetworkManager state, shill adapter status |
| Logs | bounded boot/user journal slices, dmesg warnings, AuraDE launch log |

## Usage

```bash
aurade-hardware-report
```

For deeper debugging:

```bash
aurade-hardware-report --full
```

The command prints the path to a `tar.gz` archive. The archive is created with
mode `0600` and the working directory is created with a restrictive umask.

## Privacy Boundary

The tool redacts common Google/API key, secret, and token patterns and does not
copy `/etc/aurade/google-api.conf`. It still collects hardware IDs, package
lists, usernames, and logs, so users should review archives before posting them
publicly.

## Packaging Notes

The tool lives in the `aurade` package:

- no Chromium rebuild required;
- no optional AI dependency;
- no model download;
- no default behavior changes.

`brightnessctl` and `upower` are optional dependencies. If installed, their
output is captured; if absent, the report records the missing command instead of
failing.

This is meant to support potato-laptop and real-hardware validation, not to
change AuraDE's runtime profile selection.
