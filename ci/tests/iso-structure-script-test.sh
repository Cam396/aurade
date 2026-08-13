#!/usr/bin/env bash
# Exercise the cheap ISO-structure checks with an archive-shaped fixture.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
install -d "$TMP/tree/EFI/BOOT" "$TMP/tree/loader/entries"
printf '%s\n' boot >"$TMP/tree/EFI/BOOT/BOOTx64.EFI"
printf '%s\n' 'default aurade.conf' 'editor no' >"$TMP/tree/loader/loader.conf"
printf '%s\n' 'title AuraDE' 'options cow_spacesize=4G' \
  >"$TMP/tree/loader/entries/01-aurade-linux.conf"
(cd "$TMP/tree" && bsdtar -cf "$TMP/fixture.iso" .)

"$ROOT/ci/verify-iso-structure.sh" "$TMP/fixture.iso"
printf '%s\n' 'editor yes' >"$TMP/tree/loader/loader.conf"
(cd "$TMP/tree" && bsdtar -cf "$TMP/bad.iso" .)
if "$ROOT/ci/verify-iso-structure.sh" "$TMP/bad.iso" >"$TMP/bad.out" 2>&1; then
  echo 'ISO with editable boot loader unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'ISO boot editor is not disabled' "$TMP/bad.out"

echo 'ISO structure script test: PASS'
