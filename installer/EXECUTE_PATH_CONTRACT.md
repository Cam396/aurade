# AuraDE execute-path validation contract

This document defines what must be proven before an ISO or package set is
called beta-ready. Source-level dry-runs and refusal fixtures are useful, but
they are not evidence that a disk install works. The contract keeps those
claims separate.

## Disposable boundary

An execute-path run may use only one explicitly named disposable target:

- a sparse loop device, a disposable VMware guest disk, or the named testing
  VM;
- no host boot disk, mounted host filesystem, production keyring, or real
  signing key;
- no snapshot of the user’s VM is required or created for this test;
- the operator records the exact target identity before the run and confirms
  that all mounts, mappings, loop devices, and temporary staging are gone
  afterwards.

An authoring agent may write fixtures and test code, but it must not fabricate
EFI state, keyrings, signatures, mounts, loop devices, or a passing result.
Any root operation is run by the maintainer in the disposable boundary, not by
an untrusted authoring process.

## Required assertions

The plain and LUKS2 paths are recorded separately. Each run must cover:

1. UEFI boot reaches the installer and the target identity confirmation.
2. Package acquisition and signature/hash verification finish before `wipefs`.
3. Partitioning creates the ESP and root partition with the expected types.
4. The plain path creates the Btrfs subvolumes; the encrypted path creates and
   opens a LUKS2 container with the expected initramfs hooks.
5. `pacstrap`, `genfstab`, the local package install, and `bootctl` complete.
6. First boot reaches the greeter, accepts the configured credentials, starts
   the session, and does not return to a black screen/greeter loop.
7. Normal boot, factory rollback, and a manual rollback snapshot are each
   exercised and recorded independently.
8. An injected failure after acquisition leaves a machine-readable journal,
   preserves the raw log separately, and leaves no leaked secrets or active
   mounts/mappings after cleanup.
9. When `AURADE_FAILURE_JOURNAL_DIR` is configured on a mounted disk-backed
   volume, an unexpected exit preserves a mode-0600 copy of the structured
   journal only. Package caches, temporary keyrings, passphrase files, and raw
   command output must not be copied into that directory. This evidence copy
   does not claim that the installer can resume; resume remains a separate
   transactional-recovery requirement.

## What source tests can and cannot claim

`installer/tests/run.sh` proves input validation, package-lock integrity,
signature fixtures, journal structure, staging reproducibility, and refusal
before destructive commands. It does not prove partitioning, filesystems,
LUKS, pacstrap, bootctl, first boot, or power-loss recovery. Those require the
disposable execute-path run above and must remain open until their evidence is
attached to `RELEASE_STATUS.md`.

## Bounded execute-path fixture

`installer/tests/test-execute-path-gate.sh` is an opt-in, root-only fixture
for the first safe part of that run. With
`AURADE_EXECUTE_PATH_TEST=1`, real UEFI boot, Secure Boot reported as disabled,
the required installer tooling, and a disposable loop-device boundary, it
creates a sparse 16-GiB backing file and attaches it as the target. It then
executes the real installer with `--execute --allow-loop` and an intentionally
impossible disk-backed staging-capacity requirement. The expected failure
occurs after execute-mode preflight and journal initialization but before
package acquisition, `wipefs`, partitioning, filesystems, mounts, or
bootloader work. The fixture checks target identity, journal preservation,
mode-0600 evidence, staging cleanup, and that the loop target has no new
partitions or mounts.

The default `installer/tests/run.sh` invocation records an explicit skip unless
the opt-in variable is set. A skip is evidence that this boundary was not
available; it is not an execute-path pass. A fixture pass means only that the
pre-acquisition cleanup boundary executed and was checked. It does not claim a
disk install, signatures, EFI state, first boot, rollback, or recovery. The
full disposable execute-path evidence remains open until a maintainer runs it
with real package acquisition and records the separate plain and LUKS2 results.
