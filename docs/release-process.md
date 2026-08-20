# AuraDE release process

This is the public shape of a release. Private signing operations, build
machines, and unreleased test material stay outside the repository.

## 1. Prepare

- Choose an exact source revision and patch-series revision.
- Record package versions, the Arch snapshot, build arguments, and the ISO
  source date.
- Build from a clean checkout and keep the work directory separate.

## 2. Verify

- Run the source, package, installer, and ISO structure gates.
- Generate a checksum manifest and an SBOM.
- Verify that the package closure matches the lock file.
- Boot the exact ISO in a disposable VM.
- Complete the plain and encrypted install paths, reboot, login, and rollback
  checks that the release claims.
- Run the hardware matrix appropriate to the release.

## 3. Sign and publish

Only signed artifacts can be called a release. Publish the ISO, package
repository metadata, checksums, detached signatures, SBOM, source revision, and
a short changelog together. Publish the public signing fingerprint through two
independent project channels.

## 4. Communicate honestly

The release note should say what changed, what was tested, and what remains
experimental. Keep development artifacts clearly labeled. Do not turn a
source-level test into a hardware claim, and do not hide a known installer or
network limitation behind a vague success statement.

## 5. Roll back

If a release is withdrawn, mark it clearly, stop promotion, publish the reason,
and provide the verification and recovery steps. Preserve signed records so a
future maintainer can explain what happened without exposing private logs or
credentials.
