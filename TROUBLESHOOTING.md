# AuraDE troubleshooting

## The Chromium patch series does not apply

The source revision and `patches/SERIES` must match. Do not force a partial
application or continue to a build after a failed patch check.

```bash
CHROME_SRC=/path/to/chromium/src \
  ci/verify-patch-series.sh --expect-tree-match
```

Choose the immutable revision used by the current candidate controller or
source manifest. The package version is not enough to identify a Chromium
checkout.

## GN cannot find `.gn`

Run GN from the Chromium source root. Set `CHROME_SRC` to the checkout's
`src/` directory, not its parent or the AuraDE repository. The pinned package
builder sets this up automatically.

## The build wants to rebuild everything

Keep the warm checkout and `out/Ash` directory under `AURADE_WORKDIR`. Use the
current pinned package builder for normal iteration. For an interrupted clean
gate, use `AURADE_REUSE_CLEAN_OUTPUT=1` with
`ci/build-clean-arch-chromium-package.sh`; do not remove the whole work
directory first.

`AURADE_SKIP_GN_GEN=1` is valid only with clean-output reuse and an existing
`build.ninja` generated with identical GN arguments.

## `--reuse-chromium` refuses to run

That flag is intentionally strict. It only accepts the exact current
`chromiumos-ash` `pkgver-pkgrel` artifact from the pinned build work directory.
Rebuild Chromium when the source revision, patch series, package release, or
artifact path changed.

## Package smoke fails before compiling Chromium

Run it inside an Arch environment with the package tools installed:

```bash
AURADE_VERIFY_CHROMIUMOS_ASH=0 ci/arch-package-smoke.sh
```

Check `.SRCINFO`, `namcap`, missing build dependencies, and ownership of the
package work directory before starting a large build.

## The VM smoke script cannot connect

Start the guest with `vmrun`, wait for SSH, then check the address and user:

```bash
ssh root@<guest-ip> true
AURADE_VM_HOST=<guest-ip> ci/vm-smoke.sh --open-core-apps
```

The smoke script does not launch the VM, repair networking, or restart the
desktop session.

## A smoke test leaves state behind

The Files and terminal tests are intended for a disposable guest or snapshot.
Restore the snapshot, remove only the documented test paths, and rerun the
single failing gate before repeating the full matrix.

## ISO creation fails

Check that `mkarchiso` is installed, `AURADE_ARCH_SNAPSHOT` uses `YYYY/MM/DD`,
and `AURADE_REPO_DIR` contains the exact verified package set. Signed images
also require a readable public key, a full matching fingerprint, and every
package signature. Use `--stage-only` to validate the profile before spending
time in `mkarchiso`.

## The installer reports that an Arch download is too slow

The installer uses a dated Arch snapshot so the base system stays matched to
the package lock. The live image includes `reflector` and refreshes its live
session mirrorlist when networking comes up, but it does not replace the
installer's pinned snapshot with moving mirrors. The installer also uses a
single download stream, disables pacman's low-speed abort, and retries the
base transaction three times. If a first attempt still fails, reconnect the
network and rerun `aurade-installer`; the target is checked and repartitioned
only after the normal confirmation flow.

The installer now acquires and verifies the complete pinned Arch package
closure before `wipefs` or `sgdisk` runs. After acquisition it builds a local
file repository and pacstraps from that cache, so a transfer failure cannot
leave an existing installation erased and a later network drop cannot break
the base install. The image still keeps the dated snapshot rather than
silently switching to moving Reflector mirrors. The live `sshd` service is not
enabled by default; start it manually only after setting credentials.

### `keyring is not writable` or the installer keeps downloading the same packages

Use an ISO built after the writable-keyring fix. The installer now includes
`archlinux-keyring`, initializes a private writable keyring under its temporary
work directory, and uses isolated pacman database/cache paths. It also stops
immediately on a keyring or signature error instead of retrying the full
package set. An older ISO cannot receive this fix without being rebuilt.

If a rebuilt ISO still stops at this point, verify the live clock and network
before retrying. The failure is intentionally reported before `wipefs` or
`sgdisk`, so the target disk remains unchanged.

## Do not publish a workaround as a release

Unsigned packages, stale ISOs, failed runtime gates, and unclassified crashes
are development evidence. Record the failure and source/package identity,
then fix or explicitly waive it through the release controls in
[AURADE_RELEASE_PROCESS.md](AURADE_RELEASE_PROCESS.md).
