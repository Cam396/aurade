#!/usr/bin/env bash
# The package build hands the PKGBUILD the workspace it seeded.
#
# The PKGBUILD has no tarball: it reads the Cargo workspace that
# ci/build-auradefs-package.sh copies beside it. makepkg, told to build in
# BUILDDIR, puts ${srcdir} under BUILDDIR instead, so a PKGBUILD that falls
# back to ${srcdir}/auradefs-src reads an empty directory and the build stops
# at "not the auradefs workspace". The two have to name the same tree, and the
# only way to know they do is to run the script and see which tree the build
# opened.
#
# makepkg and cargo are stood in for here: what is under test is the path the
# build is given, not the compiler. The stub reproduces the one makepkg
# behaviour that caused this, ${srcdir} under BUILDDIR, and nothing else.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
SCRIPT="$ROOT/ci/build-auradefs-package.sh"
PKGBUILD="$ROOT/auradefs/PKGBUILD"

fail() { echo "auradefs package test: $*" >&2; exit 1; }

[[ -r $SCRIPT ]] || fail 'the package build script is missing'
[[ -r $PKGBUILD ]] || fail 'the auradefs PKGBUILD is missing'
command -v rsync >/dev/null 2>&1 || fail 'rsync is not installed'

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin"

# makepkg, as far as this contract is concerned: srcdir lives under BUILDDIR,
# the source=() entries are fetched into it, and the PKGBUILD's functions run
# from there.
cat >"$WORK/bin/makepkg" <<'STUB'
#!/usr/bin/env bash
set -Eeuo pipefail
here=$PWD
. ./PKGBUILD
srcdir="${BUILDDIR}/${pkgname}/src"
pkgdir="${BUILDDIR}/${pkgname}/pkg/${pkgname}"
rm -rf "$srcdir" "$pkgdir"
mkdir -p "$srcdir" "$pkgdir"
for entry in "${source[@]}"; do
    cp -a "${here}/${entry}" "${srcdir}/"
done
prepare
build
check
package
mkdir -p "${PKGDEST}"
tar -C "$pkgdir" -czf \
    "${PKGDEST}/${pkgname}-${pkgver}-${pkgrel}-x86_64.pkg.tar.gz" .
STUB

# cargo, as far as this contract is concerned: it records the tree it was run
# in and leaves a binary where the PKGBUILD packages one from.
cat >"$WORK/bin/cargo" <<'STUB'
#!/usr/bin/env bash
echo "$1 $PWD" >>"${STUB_CARGO_LOG}"
if [[ $1 == build ]]; then
    mkdir -p "${CARGO_TARGET_DIR}/release"
    printf '#!/bin/sh\nexit 0\n' >"${CARGO_TARGET_DIR}/release/auradefs"
    chmod +x "${CARGO_TARGET_DIR}/release/auradefs"
fi
exit 0
STUB

cat >"$WORK/bin/rustc" <<'STUB'
#!/usr/bin/env bash
echo 'host: x86_64-unknown-linux-gnu'
STUB
chmod +x "$WORK/bin/makepkg" "$WORK/bin/cargo" "$WORK/bin/rustc"

out=$(env PATH="$WORK/bin:$PATH" \
        AURADE_WORKDIR="$WORK/pkg" \
        STUB_CARGO_LOG="$WORK/cargo.log" \
        bash "$SCRIPT" 2>&1) || \
  fail "the package build did not finish: $out"

[[ -s $WORK/cargo.log ]] || fail "the build never reached cargo: $out"

seeded="$WORK/pkg/auradefs/src/auradefs-src"
[[ -f $seeded/Cargo.lock ]] || fail 'the script did not seed a workspace of its own'

while read -r phase tree; do
  [[ $tree == "$seeded" ]] || \
    fail "cargo ${phase} ran in ${tree}, which is not the seeded workspace ${seeded}"
done <"$WORK/cargo.log"

for phase in fetch build test; do
  grep -q "^${phase} " "$WORK/cargo.log" || \
    fail "the build never ran cargo ${phase}: $(cat "$WORK/cargo.log")"
done

grep -Eq '^built .*/auradefs-[^/]*\.pkg\.tar\.' <<<"$out" || \
  fail "the script did not report a package: $out"

echo 'auradefs package test: PASS'
