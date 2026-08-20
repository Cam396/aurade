# Building AuraDE

AuraDE keeps the Chromium source outside this repository. The public tree
contains package recipes, an ordered patch series, the installer, and the
checks that make a build repeatable.

## Before you start

Use an Arch Linux host or an isolated Arch build environment with enough disk
space for Chromium, package caches, and an ISO. Install Git, Bash, rsync,
base-devel, pacman, makepkg, namcap, repo-add, pacstrap, arch-chroot, and
archiso when you need an ISO.

Keep build state outside the checkout:

~~~bash
export AURADE_WORKDIR="$PWD/.build"
~~~

Do not place Chromium checkouts, VM images, signing keys, or build logs in the
Git tree.

## Cheap path

Start with checks that do not compile Chromium:

~~~bash
git diff --check
AURADE_VERIFY_CHROMIUMOS_ASH=0 ci/arch-package-smoke.sh
ci/source-integrity-gate.sh
ci/public-release-leak-gate.sh
~~~

Inspect the full plan before starting a long build:

~~~bash
./build-aurade.sh --plan --all
~~~

## Pinned Chromium path

Bootstrap the exact revision recorded in pins/chromium.sha and verify the
patch series before compiling:

~~~bash
ci/bootstrap-chromium-src.sh \
  --revision "$(cat pins/chromium.sha)" \
  --target "$AURADE_WORKDIR/chromium" \
  --run --verify-series

CHROME_SRC="$AURADE_WORKDIR/chromium/src" \
  ci/verify-patch-series.sh --expect-tree-match
~~~

The release builder uses the verified source and creates the package set in
the work directory. Do not mix packages made from different source revisions.

## Packages and ISO

The complete orchestrator can build the support packages, Chromium package,
local repository, and ISO:

~~~bash
./build-aurade.sh --all
~~~

Build an ISO only from a package repository that has passed its checksum and
signature checks. Unsigned images are development artifacts. They must not be
described as releases or installed on irreplaceable data.

The ISO profile is under installer/. Its staging checks can be run without
mkarchiso:

~~~bash
bash installer/tests/run.sh
~~~

## AUR packages

Package export is separate from the Chromium build:

~~~bash
ci/export-aur-bundles.sh
~~~

Run makepkg, regenerate .SRCINFO, run namcap, and inspect the package
contents before submitting anything. AUR publication is not a substitute for
signed release artifacts.

## Reproducibility and cleanup

Record the source revision, patch-series hash, package versions, snapshot date,
build arguments, and ISO checksum with every candidate. A clean rebuild must
produce the same metadata and package closure. Remove only the explicit work
directory when cleaning up, never a broad system path.
