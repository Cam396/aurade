# AuraDE CI tools

The scripts in this directory are small, inspectable gates rather than a
second build system. Run the cheap ones locally before starting a long build.

## Source and package checks

~~~bash
ci/source-integrity-gate.sh
ci/public-release-leak-gate.sh
AURADE_VERIFY_CHROMIUMOS_ASH=0 ci/arch-package-smoke.sh
~~~

verify-patch-series.sh checks that the pinned Chromium source and patches/SERIES
describe the same tree. The package smoke scripts check PKGBUILD, .SRCINFO,
dependencies, and package contents.

## Installer and ISO checks

~~~bash
bash installer/tests/run.sh
ci/verify-iso-structure.sh path/to/image.iso
~~~

The installer suite must finish with an explicit pass result. ISO structure
checks do not prove a first boot, so a release still needs a disposable VM or
physical-machine pass.

## Runtime checks

Use the host hypervisor to start a disposable guest, attach the exact image,
and run only the smoke options appropriate to that image. Keep credentials and
guest addresses out of logs and issue reports. The runtime check should cover
boot, login, core applications, network state, power actions, and clean
shutdown.

## Release hygiene

Before attaching an artifact, record the source revision, package lock, ISO
checksum, build metadata, and SBOM. Run the public documentation gate and
review every operational reference it reports. CI output is evidence for a
release, not a substitute for a release note written for users.
