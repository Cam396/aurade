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

## What source tests can and cannot claim

`installer/tests/run.sh` proves input validation, package-lock integrity,
signature fixtures, journal structure, staging reproducibility, and refusal
before destructive commands. It does not prove partitioning, filesystems,
LUKS, pacstrap, bootctl, first boot, or power-loss recovery. Those require the
disposable execute-path run above and must remain open until their evidence is
attached to `RELEASE_STATUS.md`.
