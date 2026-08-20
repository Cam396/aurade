# AuraDE and Secure Boot

Secure Boot is a firmware policy. An installed loader and kernel must be signed
by a certificate that the firmware trusts.

When Secure Boot is enabled, the installer checks the available signing path
before it changes the disk. A supported setup can enroll an AuraDE certificate
on a new machine, or use a certificate that is already trusted by the
firmware. If neither path is available, the installer explains what is
missing before the erase gate instead of leaving an installation that cannot
boot.

The installer image itself may be unsigned during development. Some firmware
will require setup mode or a trusted removable-media path to boot it. ISO
signing is separate from signing the installed boot chain.

Keep signing keys offline, protected, and out of repositories, images, logs,
and diagnostic exports. Read the release notice for the exact certificate and
verification instructions used by a particular image.
