# AuraDE CI and build strategy

CI is split by cost and risk. Fast checks run on ordinary runners. Chromium
and ISO work runs only when the source, package lock, and build inputs are
known, because a long build should not hide a simple source error.

## Fast checks

- Shell syntax and whitespace.
- Package metadata and .SRCINFO consistency.
- Patch-series integrity.
- Installer unit and refusal tests.
- Public documentation and credential scans.
- ISO staging and structure checks.

## Expensive checks

- Chromium compilation from the pinned source revision.
- Package repository assembly.
- ISO creation.
- Disposable VM boot and installation checks.
- Hardware qualification before a stable release.

Every expensive job records the source revision, patch-series hash, package
versions, build arguments, checksum, and result. A skipped runtime dependency
is reported as skipped, not passed.

## Build hygiene

Build outputs, caches, VM images, signing keys, and logs stay outside the
repository. CI must fail closed on checksum, signature, package-lock, or
public-leak failures. A release job must not publish an artifact that has not
passed its declared gates.
