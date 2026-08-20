# AuraDE release signing

Signing answers one simple question: did this file come from the release that
the project named? A checksum detects damage. A signature also binds the file
to a project key.

## What a release should contain

A signed release publishes:

- The ISO and its SHA-256 checksum.
- The package repository database and package checksums.
- Build metadata with the exact source and patch revisions.
- An SBOM describing the image contents.
- The public signing fingerprint and verification instructions.

The ISO signer and package-repository signer should be separate. The primary
identity should remain offline, with short-lived signing subkeys used only in
the controlled release process.

## Development artifacts

Unsigned packages and images are development artifacts. They must be labeled
as such and must not be described as stable or trusted. Never put a private key
in the repository, an ISO, a package, a CI log, or a support bundle.

## Rotation and incident response

If a signing key may be compromised, stop promotion, revoke or replace the
affected key, publish the new fingerprint through an authenticated channel,
and identify affected artifacts. Keep old fingerprints and revocation records
so historical releases remain explainable.

## Verification

Use the verification commands shipped in ci/ and compare the displayed
fingerprint with the one in the release notice. If a checksum, signature, SBOM,
or fingerprint is missing or mismatched, do not boot or install the artifact.
