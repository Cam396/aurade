# AuraDE Secure Boot installation

AuraDE does not bypass Secure Boot. When the firmware reports Secure Boot
enabled, the installer signs the systemd-boot loader and the Linux kernel with
a per-install key and verifies both signatures before the disk is changed.
The current BLS layout keeps initramfs files separate, so this is Secure Boot
bootability and kernel signature enforcement; embedding and signing the whole
initramfs as a UKI remains a later hardening step.

There are two supported firmware states:

* **Setup mode:** the installer generates a key, asks systemd-boot to place
  native `PK.auth`, `KEK.auth`, and `db.auth` enrollment files on the ESP, and
  adds a manual `Enroll AuraDE Secure Boot keys` entry. Select that entry on the
  first boot, then enable Secure Boot in firmware. This is the supported path
  for a new AuraDE machine and for disposable VMs.
* **User mode:** the firmware already has the signing certificate enrolled.
  Supply the matching private key and certificate with
  `--secure-boot-key` and `--secure-boot-cert`, or with
  `AURADE_SECURE_BOOT_KEY` and `AURADE_SECURE_BOOT_CERT`. The installer checks
  that the pair matches and signs the new boot chain with it.

If Secure Boot is enabled in user mode and neither path is available, the
installer stops before acquisition or disk modification. Continuing with an
unsigned loader would produce an installation that cannot boot.

The private key is stored root-only at
`/etc/kernel/secure-boot-private-key.pem` so the installed system can re-sign
the kernel and systemd-boot after package updates. The pacman hook is
`90-aurade-secure-boot.hook`. Keep a recovery copy of the key; losing it does
not make the current install unbootable, but it prevents signing future boot
artifacts until a new key is enrolled.

The current AuraDE pre-alpha ISO is not itself distributed with a
Microsoft-trusted signature. A machine that refuses to boot unsigned removable
media must temporarily use firmware setup mode or a trusted boot medium to
start the installer. ISO signing is a separate release-provenance gate.
