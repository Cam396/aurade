#!/usr/bin/env bash
# Fixture coverage for the release identity gate.
#
# The gate exists because the pin, the package and the built tree were allowed
# to describe three different Chromiums. A gate for that is only worth having
# if somebody has watched it fail, so this builds each disagreement in turn on
# a fixture tree and requires a refusal, then requires a pass on a tree where
# everything agrees.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

GOOD_REVISION=24fa005b92d6755b66ccee8ca7352d8fbfd0f6af
GOOD_VERSION=154.0.8015.0
OTHER_REVISION=106d3a4562d4269074ead2e8fd25e6c4466e25de

build_fixture() {
  rm -rf "$TMP/tree"
  install -d -m 0755 "$TMP/tree/pins" "$TMP/tree/chromiumos-ash"
  printf '%s\n' "$GOOD_REVISION" >"$TMP/tree/pins/chromium.sha"
  printf '%s\n' "$GOOD_VERSION" >"$TMP/tree/pins/chromium.version"
  # A fixture tree with a series, so the recorded digest is over something.
  install -d -m 0755 "$TMP/tree/patches"
  printf '0001-first.patch\n' >"$TMP/tree/patches/SERIES"
  printf -- '--- a/x\n+++ b/x\n' >"$TMP/tree/patches/0001-first.patch"
  local digest
  digest=$( { cat "$TMP/tree/patches/SERIES"
              sha256sum "$TMP/tree/patches/0001-first.patch"
            } | sha256sum | cut -d" " -f1 )
  printf 'revision=%s\nversion=%s\nseries=%s\nverified=2026-08-26T00:00:00Z\n' \
    "$GOOD_REVISION" "$GOOD_VERSION" "$digest" \
    >"$TMP/tree/pins/chromium.provenance"
  printf 'pkgname=chromiumos-ash\npkgver=%s\npkgrel=1\n' "$GOOD_VERSION" \
    >"$TMP/tree/chromiumos-ash/PKGBUILD"
  printf 'pkgbase = chromiumos-ash\n\tpkgver = %s\n\tpkgrel = 1\n' "$GOOD_VERSION" \
    >"$TMP/tree/chromiumos-ash/.SRCINFO"
}

gate() { AURADE_IDENTITY_ROOT="$TMP/tree" "$ROOT/ci/verify-release-identity.sh"; }

refuses() {
  local what=$1
  if gate >"$TMP/out" 2>&1; then
    printf 'release identity gate accepted %s\n' "$what" >&2
    cat "$TMP/out" >&2
    exit 1
  fi
}

# A tree where everything agrees.
build_fixture
gate >/dev/null

# The failure this gate was written for: a revision from one Chromium sitting
# next to a version from another, both perfectly well formed.
build_fixture
printf '%s\n' "$OTHER_REVISION" >"$TMP/tree/pins/chromium.sha"
refuses 'a revision that nothing has ever bound to the pinned version'

build_fixture
sed -i 's/^pkgver=.*/pkgver=154.0.8016.0/' "$TMP/tree/chromiumos-ash/PKGBUILD"
refuses 'a package declaring a different version from the pin'

build_fixture
sed -i 's/pkgver = .*/pkgver = 154.0.8016.0/' "$TMP/tree/chromiumos-ash/.SRCINFO"
refuses 'generated metadata declaring a different version from the pin'

build_fixture
rm -f "$TMP/tree/pins/chromium.provenance"
refuses 'a pin nothing has ever checked against a real tree'

# The failure that went unnoticed for weeks: the gate compared the pin against
# the package, the documentation and the checkout, and never asked whether the
# patch series applied to the revision it pinned.
build_fixture
printf '0002-added-later.patch\n' >>"$TMP/tree/patches/SERIES"
printf -- '--- a/y\n+++ b/y\n' >"$TMP/tree/patches/0002-added-later.patch"
refuses 'a series changed since anybody checked it against the revision'

build_fixture
sed -i '/^series=/d' "$TMP/tree/pins/chromium.provenance"
refuses 'a record that never recorded which series was checked'

build_fixture
printf 'not-a-revision\n' >"$TMP/tree/pins/chromium.sha"
refuses 'a revision that is not a revision'

build_fixture
printf '154\n' >"$TMP/tree/pins/chromium.version"
refuses 'a version that is not a version'

build_fixture
printf 'AuraDE ships Chromium 152.0.7947.0.\n' >"$TMP/tree/NOTES.md"
refuses 'a document naming a Chromium the pin does not'

# And the same document naming the right one is not a failure. A gate that
# refuses correct trees gets switched off within the week.
build_fixture
printf 'AuraDE ships Chromium %s.\n' "$GOOD_VERSION" >"$TMP/tree/NOTES.md"
gate >/dev/null

printf 'release identity fixture: PASS\n'
