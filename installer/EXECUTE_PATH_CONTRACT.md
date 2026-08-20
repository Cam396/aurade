# Installer execution validation

This document defines what an execute-path test must prove. It is a public test
contract, not a record of a particular machine or run.

## Disposable boundary

The test uses a disposable virtual disk or a machine whose contents can be
restored. It must never see a host disk, production key, private account, or
real user data. The test environment is created before the run and removed
after cleanup is verified.

## Required assertions

The plain and encrypted paths must prove, separately:

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

Structural tests and mocks may prove argument handling, but they must be
labelled as mocks. They cannot be reported as proof of partitioning, booting,
or recovery.
