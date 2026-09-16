#!/usr/bin/env bash
# Run the greeter's vendored-copy comparison somewhere it can actually compare.
#
# aurade-greeter carries nine files copied from installer/lib/aurade_gui,
# because the installer only exists on the installation media and the greeter
# only exists on the installed system, so neither can import the other.
# aurade-greeter/tests/shared_test.py compares every copy against its original
# byte for byte.
#
# That test resolves the originals relative to itself, so inside a makepkg
# build it looks under $srcdir, where the installer tree has never been staged.
# It is honest about it, it prints NOTHING TO COMPARE and returns 0 rather
# than claiming a pass, but nothing in ci/tests or the workflow ran it, so the
# only place it ever executed was the one place it could not do its job. Nine
# vendored files had no drift check at all.
#
# Run from the repository, where the originals are, and refuse the quiet run.
set -Eeuo pipefail

HERE=$(cd -- "$(dirname -- "$0")" && pwd -P)
REPO=$(cd -- "$HERE/../.." && pwd -P)
GREETER="$REPO/aurade-greeter"

fail() { printf 'greeter shared design: %s\n' "$*" >&2; exit 1; }

[[ -d $GREETER ]] || fail "no aurade-greeter package at $GREETER"
[[ -d $REPO/installer/lib/aurade_gui ]] ||
  fail "the originals are not at installer/lib/aurade_gui, so nothing would be compared"

output=$(cd -- "$GREETER" && python3 tests/shared_test.py 2>&1) || {
  printf '%s\n' "$output" | sed 's/^/  /' >&2
  fail "the vendored copies differ from their originals"
}

# The whole point of this fixture. A run that compares nothing passes inside
# makepkg; here it is a failure, because here the originals are present.
if grep -Fq 'NOTHING TO COMPARE' <<<"$output"; then
  printf '%s\n' "$output" | sed 's/^/  /' >&2
  fail "the comparison went inert in the one place it was supposed to work"
fi

grep -Eq 'PASS \([0-9]+ copies identical\)' <<<"$output" ||
  fail "unrecognised result, so nothing can be concluded: $output"

printf '  %s\n' "$output"
