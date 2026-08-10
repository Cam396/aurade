# AuraDE CI Notes

`build-private-repo.sh` builds the local Arch packages into `private-repo/` and
creates a pacman database with `repo-add`.

`build-release-repo.sh` builds the seven small packages and combines them with
an explicitly supplied current `chromiumos-ash` artifact in a fresh staging
directory. `verify-release-repo.sh` requires exactly the current eleven-package
set, exact `.SRCINFO` metadata, matching repository-database versions, valid
package metadata/file lists, and cryptographically valid signatures when
`AURADE_REQUIRE_SIGNATURES=1`. A successful build atomically promotes staging
and keeps the previous repository as `.previous`.

`bootstrap-arch-root.sh` creates an Arch validation root on a host with
`pacstrap`, using `/mnt/build/aurade-work` by default for the root, pacman DB,
and package cache.

`run-in-arch-root.sh` runs a command inside that validation root, bind-mounting
the root only for the duration of the command and unmounting it on exit.

`pacman-aurade.conf` is an example client-side pacman repository stanza for the
private soak repo.

`write-source-manifest.sh` records the Chromium revision, current Chromium
worktree status, patch-series hashes, and package source hashes. It writes to
`/mnt/build/aurade-work/source-manifest.md` by default.

`export-chromium-diff.sh` exports selected tracked and untracked Chromium source
changes into the AuraDE patch series without hand-copying diffs. It writes temp
files under `AURADE_WORKDIR` and appends the generated patch to `patches/SERIES`
unless `--no-series` is used.

`verify-patch-series.sh` creates a detached scratch git worktree from
`chromium_dev/src`, validates `patches/SERIES`, and applies each listed patch in
order. It does not build Chromium; it catches missing files, duplicate series
entries, whitespace errors, and overlapping/non-applying patch hunks before CI
spends hours compiling. With `--expect-tree-match`, it additionally requires
every file changed in the `chromium_dev/src` working tree to byte-match the
patched scratch worktree, proving the series fully reproduces the current
source state. The series is maintained as disjoint per-subsystem patches: each
changed file is owned by exactly one patch, so patches cannot overlap and
apply order is not load-bearing.

`vm-smoke.sh` checks a live AuraDE VM over SSH. It verifies the deployed Chrome
hash when provided, the login-manager process, CDP, PipeWire graph, and
`aurade-audio` output/input state. With `--open-audio-settings`, it also opens
`chrome://os-settings/audio` through CDP and verifies the route title. With
`--open-core-apps`, it opens/verifies Files, Diagnostics, Settings, and the
Terminal target. With `--files-volume-smoke`, it runs `files-cdp-smoke.py`
inside the VM to verify all expected Files `local_root:*` volumes and shallow
root-directory reads. With `--files-ops-smoke` (implies `--files-volume-smoke`),
it also seeds a scratch file in `local_root:Downloads` as the desktop user and
exercises copy/read/delete through real Files IO tasks, verifying the copy's
on-disk ownership and content and that deletions reach the filesystem. With
`--files-archive-smoke` (also implies `--files-volume-smoke`), it creates a
user-owned tar archive, extracts it through a Files IO task, verifies the
member through both Files and the host filesystem, and deletes all test state
through another IO task. With
`--terminal-smoke`, it runs `ci/terminal-cdp-smoke.py` inside the VM: real
keystrokes are sent through the xterm.js terminal into the login shell and the
command's filesystem side effect is verified to run as the desktop user. With
`--session-lifecycle-smoke`, it verifies the
packaged AuraDE `org.chromium.SessionManager` shim, active local session,
primary user, local profile metadata, and absence of legacy stub login flags.
With `--accessibility-smoke`, it drives the live Text-to-Speech Settings page,
loads ChromeVox and Select-to-Speak, selects a real DOM range, and requires
both features to produce new native speech-dispatcher utterances. It also
verifies that generic Linux uses the system voice rather than the unavailable
ChromeOS enhanced-network TTS service. With `--release-package-smoke`, it
requires the exact current base-package versions, package ownership/integrity,
active udisks2/host-bridge removable-media services with no user udiskie
process, and absence of a ChromeOS update-engine process or service. Set
`AURADE_REMOVABLE_AUTOMOUNT=1` only to validate the explicit udiskie recovery
fallback instead.

`bootstrap-chromium-src.sh` creates a self-contained, pinned Chromium
checkout (depot_tools + gclient, `--no-history --shallow`, `target_os
chromeos`) so Arch CI does not depend on the developer's pre-synced
`chromium_dev/src`. It prints its plan by default; `--run` executes, `--verify-series`
proves `patches/SERIES` applies to the fresh checkout (scratch worktree),
and `--apply-series` applies the series into the checkout so it is ready
for `CHROME_SRC=<target>/src makepkg`. When building the package from a
bootstrapped tree, put the tree's `buildtools/linux64` and
`third_party/ninja` on `PATH` and make sure the checkout is owned by the
build user.

`refresh-bootstrap-series.sh` safely updates an existing warm pinned checkout
to the current patch series without resetting it or scanning its large build
output. It constructs the series in a clean detached worktree, then refreshes
and byte-verifies only patch-owned files. Run it as the checkout owner.

`build-current-chromiumos-ash-package.sh` is the nightly/package entry point.
It refreshes the pinned checkout, copies current package sources into an
isolated work directory, builds with that checkout's GN/Ninja tools, and prints
the resulting package SHA-256. It never defaults to `chromium_dev/src`.

`build-release-candidate.sh` is the root orchestration entry point. It builds
the pinned Chromium package as the checkout owner, syncs all package inputs
into the Arch validation root, builds the small packages as unprivileged
`aurabuild`, verifies and atomically promotes the complete repository, and
writes the source manifest. `--reuse-chromium` is allowed only when the exact
current `pkgver-pkgrel` artifact already passed the pinned build.

`update-chromium-candidate.sh` is the weekly upstream controller. It resolves a
moving Chromium branch to an immutable commit in a CI-owned bare repository,
replays `patches/SERIES` in a detached worktree, writes a conflict report on the
first failing patch, runs selected gates in cost order, and atomically updates
the last-known-good pin only after every selected gate is green. It never
fetches, checks out, resets, or applies patches in `chromium_dev/src`. On first
run, that checkout can seed an independent bare repository using committed Git
objects only; subsequent runs fetch weekly deltas into the CI-owned copy.

Candidate IDs contain both the Chromium revision and patch-series digest. The
state root (default `/mnt/build/aurade-work/chromium-update`) retains candidate
metadata, transition history, per-gate logs, the replayed diff, changed files,
target plan, source manifest, conflict evidence, and promotion history. The
canonical `current` symlink is updated atomically, and
`pins/last-known-good-*` provides plain-text consumers with the same identity. `--rollback`
selects an earlier retained green generation without rebuilding it; `--resume`
retries an immutable failed generation even if the moving branch has advanced.

`materialize-chromium-candidate.sh` bridges source replay to real GN/build
gates. It maintains an isolated warm gclient checkout (default
`/mnt/build/aurade-work/chromium-candidate`), syncs exactly
`AURADE_CANDIDATE_SHA`, and leaves `src/out/Ash` intact between generations.
Before syncing, it restores only the union of previously and currently
patch-owned paths at the old base and refuses to proceed if any other source
dirt remains. It never runs `git clean` or resets the developer checkout. After
sync it fingerprints `.gclient`, `DEPS`, sysroot, and clang hook inputs; hooks
run only when the fingerprint changes, required tools are missing, or
`AURADE_FORCE_GCLIENT_HOOKS=1` is set. The series is then reapplied and a
tab-delimited descriptor publishes the exact `CHROME_SRC`, reusable
`AURADE_GN_OUT_DIR`, revision, and series digest. When the pipeline runs as
root, the helper defaults to the owner of `AURADE_CHROMIUM_REFERENCE` so depot
tools and build outputs are not created as root; set `AURADE_CANDIDATE_USER`
explicitly on builders without that reference checkout.

The safe scheduled default is `AURADE_UPDATE_GATES=replay`. Target-plan
generation is always part of replay. Selecting `gn`, `targeted`, `full-build`,
or `package` automatically inserts `materialize` before them. Optional gates
run in this order: `materialize`, `gn`, `targeted`, `full-build`, `package`,
`repo`, then `vm`. Override materialization with
`AURADE_MATERIALIZE_COMMAND`; configure remaining commands with
`AURADE_GN_COMMAND`, `AURADE_TARGETED_COMMAND`,
`AURADE_FULL_BUILD_COMMAND`, `AURADE_PACKAGE_COMMAND`,
`AURADE_REPO_COMMAND`, and `AURADE_VM_COMMAND`. Commands receive the immutable
candidate identity, source-only replay path, materialized `CHROME_SRC`,
changed-file list, target plan, and stable GN output path as environment
variables. The package gate defaults to `build-release-candidate.sh`, and the
repo gate defaults to `verify-release-repo.sh`.

`chromium-candidate-gate.sh` supplies the standard GN, production-library, and
full Chrome commands used by the example weekly configuration. It re-executes
as the checkout owner when the scheduler runs as root, so the persistent warm
output never acquires mixed ownership. The targeted gate compiles only
production libraries that are reused by the subsequent full build.

Safe inspection and execution examples:

```bash
# Network probe only; creates no state directory.
ci/update-chromium-candidate.sh --probe

# Print the immutable SHA, patch generation, and gates without mutation.
ci/update-chromium-candidate.sh --dry-run --gates replay,gn,targeted

# Source replay and conflict/target-plan gate; no Chromium build.
ci/update-chromium-candidate.sh --run

# Retry an infrastructure failure or restore a retained green generation.
ci/update-chromium-candidate.sh --resume <candidate-id>
ci/update-chromium-candidate.sh --rollback <candidate-id-or-unique-sha-prefix>
```

Run `ci/tests/update-chromium-candidate-test.sh` and
`ci/tests/materialize-chromium-candidate-test.sh` for the no-build regression
suite. They create temporary fake upstream, bare, and mocked gclient
repositories and verify
probe/dry-run immutability, dirty-checkout isolation, replay and conflict
evidence, gate order, failed-gate non-promotion, resume, rollback, locking,
patch ownership transitions, hook fingerprinting, and warm-output retention.

`build-clean-arch-chromium-package.sh` creates a fresh Chromium output tree and
drives the full `chromiumos-ash` build from inside the Arch validation root. It
is the expensive clean-environment gate for an Arch `extra` candidate, not the
normal incremental nightly path. After an interrupted build, rerun it with
`AURADE_REUSE_CLEAN_OUTPUT=1` to preserve and resume the existing Ninja output;
the package staging area is still rebuilt from scratch. Before either mode,
the builder requires all patch-owned files in the pinned checkout to match the
current series byte-for-byte. For a code-only interrupted build whose existing
GN graph is known to have the same arguments, add `AURADE_SKIP_GN_GEN=1`; this
is rejected unless reuse mode and an existing `build.ninja` are present.

Example systemd units for scheduling the fixed-pin release pipeline and weekly
upstream controller are under `ci/systemd/`. Install them only after placing
the repository at the path used by the services. Configure the weekly job from
`weekly-upstream.conf.example`; provision production signing secrets separately
through `/etc/aurade/release-build.conf` and do not put keys in the weekly file.
The weekly service has a `ConditionPathExists` guard and will not run until its
configuration exists. The example selects every release gate, so missing gate
commands fail closed instead of advancing the last-known-good pin.

`arch-package-smoke.sh` is the Arch-native package smoke test. Run it inside an
Arch VM, container, or chroot after installing the package dependencies. It
builds the small packages, runs `namcap`, verifies `chromiumos-ash` local
sources, and can optionally install the built packages. Its default package set
intentionally excludes `chromiumos-ash` so smoke checks do not start a huge
Chromium package build; `chromiumos-ash` is source-verified separately.

Expected nightly flow:

1. Bootstrap or sync the pinned checkout with `ci/bootstrap-chromium-src.sh`.
2. Run `ci/verify-patch-series.sh --expect-tree-match` against the developer
   tree as the source-export gate.
3. Create or refresh an Arch validation root with `ci/bootstrap-arch-root.sh`.
4. Run the package smoke test in the Arch validation root:
   ```bash
   ci/run-in-arch-root.sh /usr/bin/runuser -u aurabuild -- \
     /usr/bin/bash -lc 'cd /build/aurade && ci/arch-package-smoke.sh'
   ```
5. Run `ci/build-release-candidate.sh`; use `GPGKEY=<key-id>` for a candidate
   that is intended to leave the controlled builder.
6. Install the complete base package transaction on the VM and relaunch the
   whole compositor session.
7. Run the complete VM gate, including `--release-package-smoke`.
8. Run `ci/build-clean-arch-chromium-package.sh` before an Arch `extra`
   proposal or other public candidate.

Expected weekly upstream flow:

1. Run `ci/update-chromium-candidate.sh --probe` and record the resolved SHA.
2. Run `--run` with the replay gate. A conflict stops here without touching the
   last-known-good pin or developer checkout.
3. Enable `gn` and `targeted`; the controller automatically materializes the
   immutable candidate first. Consume `AURADE_CHANGED_FILES` and
   `AURADE_TARGET_PLAN` instead of compiling Chrome to discover basic API or
   `BUILD.gn` failures. Reuse `AURADE_GN_OUT_DIR` for every later gate.
4. Enable `full-build`, `package`, `repo`, and `vm` only after cheap gates pass.
   Reuse the same candidate checkout and output directory across these gates.
5. Consume the promoted SHA from
   `/mnt/build/aurade-work/chromium-update/pins/last-known-good-sha`. Promotion
   occurs only after all requested gates finish successfully.

Patch export example:

```bash
ci/export-chromium-diff.sh diagnostics-gpu \
  ash/webui/diagnostics_ui/backend/system \
  ash/webui/diagnostics_ui/resources
```

Patch-series verification:

```bash
ci/verify-patch-series.sh
ci/verify-patch-series.sh --expect-tree-match
ci/verify-patch-series.sh --base-ref origin/main
ci/verify-patch-series.sh --keep
```

VM smoke:

```bash
ci/vm-smoke.sh --open-audio-settings
AURADE_EXPECTED_CHROME_SHA=<sha256> ci/vm-smoke.sh --release-package-smoke --session-lifecycle-smoke --open-audio-settings --open-core-apps --files-ops-smoke --files-archive-smoke --terminal-smoke --accessibility-smoke
```

Useful variables:

- `AURADE_PACKAGES="aurade-system-helper shill-nm-adapter"` builds a subset.
- `AURADE_PACKAGES="aurade-ai"` builds only the optional Advanced Plus AI
  bootstrap package; it depends on Arch's `ollama` package but does not download
  a model at package build time.
- `AURADE_PACKAGES="aurade-webapp-shortcuts"` builds only the optional neutral
  web app launchers. It does not bundle Google API keys, OAuth clients, or
  Google product icons.
- `AURADE_PACKAGES="aurade aurade-full"` builds only the public base and full
  meta packages. `aurade-full` depends on `aurade-ai`; `aurade` intentionally
  does not.

Public install shape:

- `pacman -S aurade` installs the base desktop, non-AI helpers, neutral web app
  launchers, sensor tools, and GPU diagnostic tools.
- `pacman -S aurade-full` installs `aurade` plus `aurade-ai`.
- `AURADE_WORKDIR=/mnt/build/aurade-work` controls where the Arch validation
  root and pacman cache are created by `bootstrap-arch-root.sh`.
- `REPO_DIR=/mnt/build/aurade-work/private-repo` writes artifacts outside the
  source tree.
- `MAKEPKG_FLAGS="--force --noconfirm --clean"` avoids implicit dependency
  installation in pre-provisioned CI roots.
- `AURADE_NODEPS_PACKAGES="..."` controls which script/meta packages are built
  with `--nodeps` after stripping `--syncdeps`; by default this covers every
  small AuraDE package and leaves the large `chromiumos-ash` package alone.
- `CHROME_SRC=/path/to/src ci/export-chromium-diff.sh <slug> <paths...>`
  overrides the Chromium checkout used when exporting patch files.
- `CHROME_SRC=/path/to/src ci/verify-patch-series.sh` overrides the Chromium
  checkout used when validating `patches/SERIES`.
- `AURADE_PATCH_BASE_REF=<ref>` controls which Chromium ref the patch verifier
  uses for its scratch worktree.
- `AURADE_VM_HOST`, `AURADE_VM_USER`, `AURADE_TEST_USER`, and
  `AURADE_EXPECTED_CHROME_SHA` configure `ci/vm-smoke.sh`.
- `GPGKEY=<key-id>` signs package files and the repo database.
- `AURADE_SIGN_PACKAGES=0` leaves package files unsigned while still allowing
  repo database signing when `GPGKEY` is set.
- `AURADE_INSTALL_SMOKE=1 ci/arch-package-smoke.sh` additionally installs the
  built packages; run this only as root in a disposable Arch validation root.

## Chromium/Ash Incremental Builds

The current packaged build output is `chromium_dev/src/out/Ash` with
`is_component_build=false`. Keep that output directory stable. Do not flip
`is_component_build`, `use_system_minigbm`, Rust, or remote-exec args in-place
unless you intentionally want a large rebuild.

Before starting a full build, dry-run it:

```bash
cd chromium_dev/src
ninja -C out/Ash -n chrome
```

Expected steady-state results:

- No source changes: `ninja: no work to do` after roughly 30 seconds of graph
  scanning.
- Small Ash C++ change: a few steps, usually object compile(s), `libash.a`, and
  `LINK ./chrome`.
- Thousands of steps: stop and inspect. That means the output directory is not
  warm for the current GN args, a source sync changed broad inputs, or generated
  build metadata was lost/stale.

For fast compile validation before paying the static Chrome link cost, build the
specific object targets first:

```bash
ninja -C out/Ash -j"$(nproc)" obj/ash/ash/window_tree_host_manager.o
```

Only build `chrome` when you need a deployable binary.

`out/Ash` intentionally keeps generated `.ninja` metadata symlinked into
`/tmp/ninja-tmpfs` for much faster incremental graph loading. Back it up after a
successful rebuild so reboot or `/tmp` cleanup does not destroy that speed path:

```bash
ci/ninja-tmpfs-cache.sh backup
```

To run a build and back up the tmpfs metadata only if the build succeeds:

```bash
ci/ninja-tmpfs-cache.sh run -- ninja -C chromium_dev/src/out/Ash -j"$(nproc)" chrome
```

After reboot or tmpfs loss:

```bash
ci/ninja-tmpfs-cache.sh restore
```

The private repo is the soak channel. Arch `extra` remains the target, but the
private repo provides upgrade history, logs, and package artifacts before an
official packaging proposal.
