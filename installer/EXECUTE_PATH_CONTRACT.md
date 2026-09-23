# Installer execution validation

This document defines what an execute-path test must prove. It is a public test
contract, not a record of a particular machine or run.

## Disposable boundary

The test uses a disposable virtual disk or a machine whose contents can be
restored. It must never see a host disk, production key, private account, or
real user data. The test environment is created before the run and removed
after cleanup is verified.

The minimum fixture is a sparse loop device, a disposable VMware guest disk,
or another explicitly disposable target. It must prove `no host boot disk` in
the target set and must not fabricate EFI state, signatures,
mounts, loop devices, or passing results. `AURADE_EXECUTE_PATH_TEST=1` is an
opt-in switch and is valid only inside that disposable boundary.

## Required assertions

The plain and LUKS2 paths must prove, separately:

1. The selected disk identity is shown and confirmed immediately before the
   destructive boundary.
2. Partitioning and filesystem creation match the displayed plan.
3. LUKS2, when selected, protects the root data and accepts the test key.
4. Packages are acquired from the expected repository and installed.
5. The filesystem table and boot entry point at the created system.
6. The first boot reaches a login and a usable session.
7. Btrfs recovery entries work when snapshots are part of the plan.
8. An interrupted run leaves a journal, a diagnostic path, and a documented
   recovery action.
9. Cleanup removes temporary mappings, mounts, loops, and test credentials.

The record is the full disposable execute-path evidence. Package selection
and archive reachability are checked before any destructive disk operation.
When automatic staging has enough workspace headroom, package downloads and
signature verification also finish before the disk changes. When the installer
chooses the target disk to keep the live system within its memory budget,
packages are downloaded after formatting and verified before pacstrap. The
journal records which route ran and where a failure left the disk. The evidence
must also show `First boot reaches the greeter` and factory rollback returns to
the recorded snapshot. The machine-readable journal is part of the evidence,
including the reversibility boundary and cleanup result.

`installer/tests/test-execute-path-gate.sh` is a safe pre-acquisition fixture.
It checks the loop-backed refusal and cleanup path, but does not prove partitioning,
filesystem creation, pacstrap, bootloader installation, first boot, or factory
rollback. Those claims remain open until the named disposable VM provides them.

Structural tests and mocks may prove argument handling, but they must be
labelled as mocks. They cannot be reported as proof of partitioning, booting,
or recovery.
