# AuraDE troubleshooting

Start with the exact release or commit and a short description of what is on
screen. Do not retry a destructive step on a disk containing data you need.

## The patch series does not apply

Make sure the Chromium checkout is the revision in pins/chromium.sha and that
the tree has no local changes. Then run:

~~~bash
CHROME_SRC=/path/to/chromium/src ci/verify-patch-series.sh --expect-tree-match
~~~

Do not resolve a conflict by silently dropping an AuraDE patch. Record the
conflict and update the patch deliberately.

## The build wants to rebuild everything

This usually means the source revision, GN arguments, or package release does
not match the recorded candidate. Inspect the plan first. Reuse a Chromium
build only when the source revision and package metadata are identical.

## Package smoke fails

Run the failing command on an Arch host or in the supported Arch environment.
Check that the package database is current, the build user can write its work
directory, and every .SRCINFO matches its PKGBUILD. Do not work around a
signature or checksum failure by disabling verification.

## The ISO does not boot

Check the ISO checksum, confirm UEFI mode, and inspect the boot entries in the
staged image. If the image has only a firmware entry, rebuild from a clean
profile and rerun the ISO structure test. A missing boot entry is a packaging
failure, not a reason to erase a disk again.

## The graphical installer is slow or blank

The live image tries several display paths. A virtual GPU or a machine without
3D acceleration can take a while before the fallback appears. If the screen
does not recover, choose the text installer from the boot menu. Keep the
attempt log and report the renderer, display hardware, and elapsed time.

## Wi-Fi is missing

Confirm that NetworkManager sees the adapter and that the radio is not blocked
by a hardware switch or firmware setting. A USB Ethernet connection can help
finish an installation, but it does not fix a missing Wi-Fi bridge. Report the
adapter family and the visible network state without including access-point
passwords.

## Secure Boot refuses the result

The installed boot chain must be signed by a key trusted by the firmware. Read
the Secure Boot guidance before changing firmware settings. Never copy a
private signing key into the repository or an ISO.

## Low-memory installation failures

Close other live-session applications, use disk-backed staging when available,
and check free space before starting. If swap setup reports an error but the
installation continues, capture the post-boot service status and report it as
a qualification issue rather than repeating the erase step.

## Reporting a new problem

Open an issue with the release or commit, hardware family, firmware mode,
reproduction steps, and a redacted excerpt. Use SECURITY.md for
vulnerabilities. Never publish credentials, private logs, or a complete
diagnostic archive.
