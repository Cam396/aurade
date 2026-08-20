# AuraDE on Arch and the AUR

AuraDE is developed for Arch Linux. The AUR is a publication channel for
recipes, not a replacement for a signed binary repository or a tested ISO.

## Package layout

The repository contains the base package, the Ash package, the account and
login helpers, the power and host integrations, the web shortcuts, the local
assistant option, and the NetworkManager bridge. Packages are kept separate so
people can inspect the dependency boundary and install only what they need.

## Build a local package

From an Arch build environment:

~~~bash
makepkg --syncdeps --cleanbuild
namcap PKGBUILD
makepkg --printsrcinfo > .SRCINFO
~~~

Inspect the package file list and the license before installing it. Repeat the
same checks for every package in a proposed upload. ci/export-aur-bundles.sh
can create self-contained upload directories without copying Chromium
checkouts, ISO files, logs, or private material.

## Publication checklist

Before an upload, confirm:

- The version in PKGBUILD and .SRCINFO matches.
- Sources have stable checksums.
- Dependencies are complete and available in Arch repositories.
- The package does not start services without a clear reason.
- No credentials, private paths, or build-machine assumptions are present.
- The package has been tested on a clean Arch installation.

Do not upload a development snapshot as a stable release. Wait for the signed
release notice and use the exact version it names.
