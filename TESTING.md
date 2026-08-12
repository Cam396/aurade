# Testing AuraDE

AuraDE's supported validation path is a running VMware guest checked over SSH.
QEMU is not the project validation target. Physical laptop testing remains a
separate qualification step.

## Boot the ISO

The live ISO opens an automatic root console on tty1. The live `root` account
has an empty password for console recovery and does not create `auratest`. Run
`aurade-installer` from that console to choose the installed username and
password. The live root session is for installation and recovery only, not a
shipped desktop login.

## Start the VM

Use the host's `vmrun` operation and wait for the guest to finish booting:

```bash
vmrun -T ws start "/path/to/aurade.vmx" nogui
```

For VMware guests, enable **Accelerate 3D graphics** (the VMX equivalent is
`mks.enable3d = "TRUE"`) before testing the installed desktop. Without it,
AuraDE's render preflight now stops before Weston and records an actionable
error under `~/.local/state/aurade/session-error.txt`. Older packages may still
allow Weston to start without a usable render device, after which Chromium may
abort after authentication and look like a black screen followed by a return to
the greeter. That is a graphics-capability failure, not evidence that the
account password was rejected.

Do not run the smoke script against a guest that is still booting. The script
does not start or restart the desktop session for you.

## Run the smoke matrix

Set the guest address and run the cheap session/core checks first:

```bash
export AURADE_VM_HOST=<guest-ip-or-hostname>
export AURADE_VM_USER=root
export AURADE_TEST_USER=auratest

ci/vm-smoke.sh \
  --open-core-apps \
  --open-audio-settings \
  --session-lifecycle-smoke \
  --release-package-smoke
```

Run the state-changing application checks in a disposable VM or snapshot:

```bash
ci/vm-smoke.sh \
  --files-ops-smoke \
  --files-archive-smoke \
  --terminal-smoke \
  --accessibility-smoke
```

`--files-ops-smoke`, `--files-archive-smoke`, and `--terminal-smoke` create
temporary test state as the desktop user and remove it when the check passes.
Use a snapshot when investigating a failure.

If the package contains a known Chromium binary, verify it too:

```bash
ci/vm-smoke.sh \
  --expected-chrome-sha <sha256> \
  --open-core-apps \
  --session-lifecycle-smoke \
  --release-package-smoke
```

The full option list is available with `ci/vm-smoke.sh --help`.

## Physical laptop qualification

VM results do not qualify hardware. On each laptop, test graphics, audio
input/output, Wi-Fi, Bluetooth, touchpad, brightness, battery, lid close,
suspend/resume, display hotplug, lock, sign-out, reboot, shutdown, USB storage,
and recovery. Use [AURADE_HARDWARE_TEST_PACKET.md](AURADE_HARDWARE_TEST_PACKET.md)
for the report fields and safety warnings.

## Report a failure

Include:

- AuraDE commit and immutable Chromium source revision.
- Exact package versions and SHA-256 values.
- VM or laptop model and firmware details.
- The exact command and smoke flags used.
- Relevant `journalctl`, `coredumpctl`, SSH, and smoke-log output.

Redact passwords, API keys, private URLs, and unredacted hardware reports.
