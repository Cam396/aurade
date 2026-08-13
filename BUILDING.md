# Building AuraDE

This is the canonical build path for the public pre-alpha source tree. It
keeps Chromium outside the Git repository, applies the ordered patch series,
and builds the complete Arch package set in an isolated validation root.

AuraDE is not a one-command binary distribution yet. A Chromium checkout is
large, the first sync can take hours, and the current public repository does
not publish a signed package repository. Treat every package and ISO produced
by this document as development output.

Choose a work directory outside the repository. The examples use a local
default; set `AURADE_WORKDIR` to a larger separate disk when needed:

```bash
export AURADE_WORKDIR="${AURADE_WORKDIR:-$PWD/.aurade-work}"
```

## Choose a path

- **Package-source smoke:** checks and builds the ten non-Chromium packages.
- **Pinned package build:** builds `chromiumos-ash`, the ten support packages,
  and a coherent local pacman repository.
- **ISO build:** stages a package-locked ArchISO from a verified repository.
- **Runtime validation:** starts a VMware guest and runs the checks in
  [TESTING.md](TESTING.md).

The maintainer-oriented details and optional candidate-controller gates are in
[`ci/README.md`](ci/README.md).

The full-build CI decision and runner sizing are documented in
[`CI-BUILD-STRATEGY.md`](CI-BUILD-STRATEGY.md). In short, standard public
GitHub-hosted runners are for the cheap checks; use a protected warm runner for
the Chromium/package/ISO release job.

## One-command workflow

On an Arch x86_64 host, the repository's orchestrator installs the host tools,
clones depot_tools when needed, bootstraps the pinned Chromium source, creates
the Arch validation root, builds the complete package repository, and can build
the ISO:

```bash
./build-aurade.sh --all
```

Inspect the plan without changing the host first:

```bash
./build-aurade.sh --plan --all
```

On ARM64 or another architecture, the safe path is source preparation and
patch verification only:

```bash
./build-aurade.sh --source-only --arch aarch64
```

That path proves the source and patch layer but deliberately does not claim a
working ARM binary, Arch repository, or ISO. The Chromium package recipe and
release orchestrator still need an architecture-specific build and runtime
qualification before those targets can be enabled.

## Prerequisites

Use an Arch Linux host, container, or validation root. The host needs:

- Git, Bash, `sudo`, `rsync`, and an SSH client.
- `base-devel`, `pacman`, `makepkg`, `namcap`, and `repo-add` for packages.
- `pacstrap` and `arch-chroot` for the isolated validation root.
- `gclient` and Chromium's build tools for the pinned source checkout.
- `archiso` and `mkarchiso` only when building an ISO.
- VMware `vmrun` on the host used for live validation.

Do not put Chromium checkouts, `chroot/`, `out/`, package caches, VM images,
logs, or signing keys in this repository. Use a separate work directory. The
scripts use `AURADE_WORKDIR` for build state; keep that directory outside the
Git checkout.

## 1. Clone and run the cheap checks

```bash
git clone https://github.com/Cam396/aurade.git
cd aurade

# Build and inspect the non-Chromium packages without starting a Chromium build.
AURADE_VERIFY_CHROMIUMOS_ASH=0 ci/arch-package-smoke.sh

# Check patch names, ordering, whitespace, and package metadata before a build.
git diff --check
ci/public-release-leak-gate.sh
```

Run the package smoke command inside an Arch validation root when the host is
not Arch Linux. `ci/bootstrap-arch-root.sh` installs the required root and
copies the source inputs into it.

## 2. Create the Arch validation root

This step requires root and may download the Arch build dependencies:

```bash
sudo AURADE_WORKDIR="$AURADE_WORKDIR" \
  ./ci/bootstrap-arch-root.sh
```

The validation root is `${AURADE_WORKDIR}/archroot`. To run only the cheap
package smoke test there:

```bash
sudo ./ci/run-in-arch-root.sh /usr/bin/runuser -u aurabuild -- \
  /usr/bin/bash -lc \
  'cd /build/aurade && AURADE_VERIFY_CHROMIUMOS_ASH=0 ci/arch-package-smoke.sh'
```

## 3. Bootstrap a pinned Chromium checkout

Use the immutable Chromium source commit in `pins/chromium.sha`. The package
version (`152.1660893`) is not a Git revision and must not be substituted for
one. The current 33-patch series applies cleanly to the committed pin.

```bash
./ci/bootstrap-chromium-src.sh \
  --revision "$(cat pins/chromium.sha)" \
  --target "$AURADE_WORKDIR/chromium-bootstrap" \
  --run --verify-series
```

The checkout remains pristine after `--verify-series`. The release builder
refreshes only the patch-owned files into a worktree before invoking
`makepkg`; do not manually copy patches into a different source tree.

## 4. Build the complete local package repository

Run this as root from the public repository. The Chromium checkout itself must
be owned by the unprivileged build user who ran the bootstrap step.

```bash
sudo env \
  CHROME_SRC="$AURADE_WORKDIR/chromium-bootstrap/src" \
  AURADE_WORKDIR="$AURADE_WORKDIR" \
  ./ci/build-release-candidate.sh
```

The output is promoted atomically to:

```text
$AURADE_WORKDIR/private-repo/
```

The builder also writes the Chromium/package source manifest to
`$AURADE_WORKDIR/source-manifest.md`. The repository verifier writes
`SHA256SUMS` and rejects missing, duplicate, stale, unsigned-when-required, or
unexpected packages.

If the exact current `chromiumos-ash` `pkgver-pkgrel` package already passed
the pinned build, the small-package/repository phase can be repeated without
rebuilding Chromium:

```bash
sudo env AURADE_WORKDIR="$AURADE_WORKDIR" \
  ./ci/build-release-candidate.sh --reuse-chromium
```

Do not use `--reuse-chromium` for an artifact from another source revision or
package release.

## 5. Build an ISO

The ISO builder consumes a verified package repository and records a package
lock, snapshot date, source date, and ISO checksum. Signed images require a
public repository key and its full fingerprint. Unsigned images are for local
development only.

First, stage and inspect an unsigned development profile:

```bash
sudo env \
  AURADE_ARCH_SNAPSHOT=YYYY/MM/DD \
  AURADE_REPO_DIR="$AURADE_WORKDIR/private-repo" \
  AURADE_ALLOW_UNSIGNED=1 \
  AURADE_INSTALLER_WORK_ROOT="$AURADE_WORKDIR/installer" \
  ./installer/build-iso.sh --stage-only
```

For a real image, omit `AURADE_ALLOW_UNSIGNED=1` and provide
`AURADE_REPO_KEY` and `AURADE_REPO_FINGERPRINT` for the signed repository.
The complete image and its sidecar metadata are written under
`AURADE_ISO_OUTPUT_DIR` or the installer work directory's `output/` folder.
The builder records ISO size and package-closure count/bytes in `.build-info`
and rejects an image larger than `AURADE_MAX_ISO_BYTES` (4 GiB by default).
Set that variable explicitly when a documented release profile requires a
different ceiling; do not remove the check for a release build.

The live image automatically opens a root console on tty1 for installation and
recovery. The live `root` account has an empty password on the console;
`aurade-installer` prompts for the username and password that will exist on the
installed system. The live root console is intentionally separate from the
installed AuraDE login flow.

The installer performs a pre-destructive acquisition phase: it downloads and
verifies the complete dated Arch package closure, creates a temporary local
repository, and only then permits disk erasure. The post-install repository
defaults to the staged local `file:///var/cache/aurade/repo` database for this
unsigned development image; pass a real HTTPS repository URL and signing key
for a beta image. The installer requires UEFI, installs both Intel and AMD
microcode, selects the matching initrd at install time, and checks boot
artifacts, enabled services, the locked root account, and repository contents
before reporting success.

Do not call an unsigned ISO stable, publish it as a supported download, or
install it on a machine whose data cannot be restored.

## Prepare the AUR upload packet

After VM and hardware feedback, export the package directories for the AUR:

```bash
export AURADE_AUR_OUTPUT="$AURADE_WORKDIR/aur-bundles"
ci/export-aur-bundles.sh
```

This emits ten source/helper package directories plus the x86_64
`chromiumos-ash-bin` package, which consumes the matching unsigned development
payload from the GitHub release and provides `chromiumos-ash`; generated AUR
meta-packages name the `-bin` dependency explicitly for AUR helper resolution.
The large
Chromium source recipe remains a maintainer build path rather than a one-click
AUR build. See [AURADE_AUR.md](AURADE_AUR.md) for the per-package validation and
upload checklist. Do not upload the generated packet until the feedback gate
is accepted.

## 6. Validate the result

Start the guest with the host's VMware operation before running the smoke
checks. Then follow [TESTING.md](TESTING.md), including the package, session,
core-app, Files, terminal, audio, accessibility, and release-package gates.

Record the source revision, patch-series digest, package versions, SHA-256
values, VM image identifier, hardware model, and relevant logs with every
candidate.

## Incremental builds and cleanup

Keep the bootstrap checkout and its `out/Ash` directory in the work directory
between builds. A source or package-script change should refresh the warm
checkout and reuse existing Ninja outputs when GN arguments are unchanged.

For the explicit clean Arch gate, an interrupted build can be resumed with:

```bash
AURADE_REUSE_CLEAN_OUTPUT=1 ci/build-clean-arch-chromium-package.sh
```

Only add `AURADE_SKIP_GN_GEN=1` when reusing an existing output directory whose
`build.ninja` was generated with the same arguments. Do not delete the entire
work directory to fix a package-only failure; remove only the affected staging
or package output after checking the failure log.
