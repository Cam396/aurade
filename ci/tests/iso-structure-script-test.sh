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

# Full-mode provenance fixture: the final squashfs must contain exactly the
# archives named by packages.lock, and their bytes must match the locked
# SHA-256 values. This is deliberately tiny; the real gate uses the same
# unsquashfs path against the release image.
install -d \
  "$TMP/squash/opt/aurade/repo" \
  "$TMP/squash/usr/local/sbin" \
  "$TMP/squash/usr/local/lib/aurade" \
  "$TMP/squash/etc/aurade-installer"
for helper in aurade-installer aurade-install aurade-recovery \
  aurade-installer-gui aurade-installer-gui-bridge aurade-installer-start; do
  printf '%s\n' helper >"$TMP/squash/usr/local/sbin/$helper"
done
printf '%s\n' journal >"$TMP/squash/usr/local/lib/aurade/aurade-journal.sh"
install -d "$TMP/squash/usr/local/lib/aurade/aurade_gui"
for module in __init__ app bridge flow; do
  printf '%s\n' "$module" >"$TMP/squash/usr/local/lib/aurade/aurade_gui/$module.py"
done
printf '%s\n' enabled >"$TMP/squash/etc/aurade-installer/gui-enabled"
printf '%s\n' '{}' >"$TMP/squash/etc/aurade-installer/gui-release-manifest.json"
printf '%s\n' 2026/07/12 >"$TMP/squash/etc/aurade-installer/snapshot"
install -d "$TMP/package"
printf '%s\n' 'pkgname = aurade' 'pkgver = 1.0-1' 'arch = any' \
  >"$TMP/package/.PKGINFO"
bsdtar -cf "$TMP/squash/opt/aurade/repo/aurade-1.0-1-any.pkg.tar.zst" \
  -C "$TMP/package" .PKGINFO
package_digest=$(sha256sum \
  "$TMP/squash/opt/aurade/repo/aurade-1.0-1-any.pkg.tar.zst" | awk '{print $1}')
printf '%s %s aurade 1.0-1 any\n' "$package_digest" \
  aurade-1.0-1-any.pkg.tar.zst \
  >"$TMP/squash/opt/aurade/repo/packages.lock"
install -d "$TMP/iso-tree/arch/x86_64"
mksquashfs "$TMP/squash" "$TMP/iso-tree/arch/x86_64/airootfs.sfs" \
  -noappend -quiet
install -d "$TMP/iso-tree/EFI/BOOT" "$TMP/iso-tree/loader/entries"
printf '%s\n' boot >"$TMP/iso-tree/EFI/BOOT/BOOTX64.EFI"
printf '%s\n' 'default aurade.conf' 'editor no' >"$TMP/iso-tree/loader/loader.conf"
printf '%s\n' 'title AuraDE' 'options cow_spacesize=4G' \
  >"$TMP/iso-tree/loader/entries/01-aurade-linux.conf"
(cd "$TMP/iso-tree" && bsdtar -cf "$TMP/full.iso" .)
"$ROOT/ci/verify-iso-structure.sh" "$TMP/full.iso" --full

# A changed archive with the old lock digest must fail the final-artifact gate.
printf '%s\n' changed >"$TMP/package/README"
bsdtar -cf "$TMP/squash/opt/aurade/repo/aurade-1.0-1-any.pkg.tar.zst" \
  -C "$TMP/package" .PKGINFO README
mksquashfs "$TMP/squash" "$TMP/iso-tree/arch/x86_64/airootfs.sfs" \
  -noappend -quiet
(cd "$TMP/iso-tree" && bsdtar -cf "$TMP/tampered-full.iso" .)
if "$ROOT/ci/verify-iso-structure.sh" "$TMP/tampered-full.iso" --full \
    >"$TMP/tampered-full.out" 2>&1; then
  echo 'ISO with a changed locked archive unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'package checksum mismatch' "$TMP/tampered-full.out"

# An unlisted archive must fail even when the listed archive itself is valid.
cp "$TMP/squash/opt/aurade/repo/aurade-1.0-1-any.pkg.tar.zst" \
  "$TMP/squash/opt/aurade/repo/extra-1.0-1-any.pkg.tar.zst"
# Restore the locked archive and rebuild the tiny squashfs.
rm -f "$TMP/package/README"
printf '%s\n' 'pkgname = aurade' 'pkgver = 1.0-1' 'arch = any' \
  >"$TMP/package/.PKGINFO"
bsdtar -cf "$TMP/squash/opt/aurade/repo/aurade-1.0-1-any.pkg.tar.zst" \
  -C "$TMP/package" .PKGINFO
mksquashfs "$TMP/squash" "$TMP/iso-tree/arch/x86_64/airootfs.sfs" \
  -noappend -quiet
(cd "$TMP/iso-tree" && bsdtar -cf "$TMP/unlisted-full.iso" .)
if "$ROOT/ci/verify-iso-structure.sh" "$TMP/unlisted-full.iso" --full \
    >"$TMP/unlisted.out" 2>&1; then
  echo 'ISO with an unlisted archive unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'unlisted package archive' "$TMP/unlisted.out"

echo 'ISO structure script test: PASS'
