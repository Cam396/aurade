# AuraDE CI tools

The scripts in this directory are small, inspectable gates rather than a
second build system. Run the cheap ones locally before starting a long build.

## The CI jobs

`ci/run.sh` is the one entry point. The GitHub workflow calls these jobs by
name and holds no checks of its own, so a local run does exactly what CI does:

~~~bash
ci/run.sh fast            # lint and gates, a few seconds
ci/run.sh installer 2/4   # one shard of the installer suite, or all of it
ci/run.sh fixtures        # ci/tests and the component tests
ci/run.sh packages        # build, check() and install the Arch packages (docker or podman)
ci/run.sh install-hooks   # run `ci/run.sh fast` before every git push
~~~

In the workflow these run as parallel jobs, the installer suite in four
shards, and a final `ci-ok` job passes only when every other job passed. That
is the check to require on a branch. Actions are pinned by commit, and the
package job builds in an Arch container pinned by digest, against the Arch
archive snapshot in `pins/arch.snapshot`.

## Releases

`ci/release.sh` turns a built ISO and signed repository into a release:
`stage` checks every signature and writes the assets, SHA256SUMS and notes
from the CHANGELOG, `draft` tags the commit and uploads a draft release, and,
once a person has published it, `publish-repo` brings the hosted package
repository in line and reads it back. It never publishes a release itself.

A version that is already published keeps its published bytes. Rebuilding an
unchanged package still gives a different file (the build date is inside it),
and a database that describes the new file while the old one is still served
makes pacman refuse the download as corrupted. So the release repository is
built with `AURADE_PUBLISHED_REPO` pointing at a copy from
`ci/release.sh fetch-published`: `ci/reuse-published-packages.sh` swaps each
already published file back in, after checking its signature, and refuses if
the contents really changed without a new pkgrel.

`ci/release.sh check-repo` checks what is served the way pacman uses it: the
database is signed by the key in `pins/aurade-release.gpg`, and every package
it names is uploaded with the checksum it records. CI runs it on every push to
main, weekly and on demand (the `hosted` job), outside `ci-ok`, since a change
can neither break nor fix what is already published.

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
