#!/usr/bin/env bash
# Exercise the cheap ISO-structure checks with an archive-shaped fixture.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

assert_output_contains() {
  local needle=$1 output_file=$2
  if ! grep -Fq -- "$needle" "$output_file"; then
    echo "ISO structure fixture: expected output not found: ${needle}" >&2
    sed -n '1,120p' "$output_file" >&2
    return 1
  fi
}

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
assert_output_contains 'ISO boot editor is not disabled' "$TMP/bad.out"

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
python3 - "$TMP/squash/etc/aurade-installer/gui-release-manifest.json" <<'PY'
import json
import pathlib
import sys

paths = [
    "installer/bin/aurade-installer-gui",
    "installer/bin/aurade-installer-gui-bridge",
    "installer/bin/aurade-installer-start",
    "installer/lib/aurade-probe.sh",
    "installer/lib/aurade-questions.sh",
    "installer/lib/aurade-validate.sh",
    "installer/lib/aurade-journal.sh",
    "installer/lib/aurade-tui.sh",
    "installer/lib/aurade_gui/__init__.py",
    "installer/lib/aurade_gui/app.py",
    "installer/lib/aurade_gui/bridge.py",
    "installer/lib/aurade_gui/flow.py",
]
manifest = {
    "schema": 1,
    "release": "0.2.0",
    "status": "candidate",
    "architectures": ["x86_64"],
    "payload": [{"path": path, "sha256": "0" * 64} for path in paths],
    "runtime_packages": ["cage", "gtk4", "libadwaita", "python-gobject"],
    "public_release_policy": {
        "gui_in_0_1_0": False,
        "artifact_signature_required": True,
        "full_profile_build_required": True,
        "physical_accelerated_runtime_required": True,
    },
}
pathlib.Path(sys.argv[1]).write_text(json.dumps(manifest), encoding="utf-8")
PY
cp "$TMP/squash/etc/aurade-installer/gui-release-manifest.json" \
  "$TMP/valid-gui-release-manifest.json"
printf '%s\n' 2026/07/12 >"$TMP/squash/etc/aurade-installer/snapshot"
install -d "$TMP/package"
printf '%s\n' 'pkgname = aurade' 'pkgver = 1.0-1' 'arch = any' \
  >"$TMP/package/.PKGINFO"
bsdtar -cf "$TMP/squash/opt/aurade/repo/aurade-1.0-1-any.pkg.tar.zst" \
  -C "$TMP/package" .PKGINFO
cp "$TMP/squash/opt/aurade/repo/aurade-1.0-1-any.pkg.tar.zst" \
  "$TMP/valid-package.pkg.tar.zst"
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
printf 'release_channel=candidate\ngui_release=1\ngui_manifest_sha256=%s\n' \
  "$(sha256sum "$TMP/valid-gui-release-manifest.json" | awk '{print $1}')" \
  >"$TMP/full.iso.build-info"
"$ROOT/ci/verify-iso-structure.sh" "$TMP/full.iso" --full
"$ROOT/ci/verify-iso-structure.sh" "$TMP/full.iso" --full --require-gui

# A GUI payload built on the unsigned development channel is not a releasable
# 0.2.0 candidate, even when its embedded manifest is otherwise valid.
sed 's/^release_channel=.*/release_channel=development/' \
  "$TMP/full.iso.build-info" >"$TMP/dev-gui.iso.build-info"
if mv "$TMP/dev-gui.iso.build-info" "$TMP/full.iso.build-info" && \
  "$ROOT/ci/verify-iso-structure.sh" "$TMP/full.iso" --full --require-gui \
    >"$TMP/dev-gui.out" 2>&1; then
  echo 'development-channel GUI ISO unexpectedly passed the release gate' >&2
  exit 1
fi
assert_output_contains 'must use candidate or public build channel' "$TMP/dev-gui.out"
cp "$TMP/full.iso.build-info" "$TMP/valid-gui.build-info"
# The mutation above intentionally replaces the sidecar; restore the valid
# candidate metadata before the later manifest and payload mutations.
sed 's/^release_channel=.*/release_channel=candidate/' \
  "$TMP/valid-gui.build-info" >"$TMP/full.iso.build-info"

# A malformed or downgraded embedded GUI manifest must fail the explicit
# 0.2.0 artifact gate even when all GUI files and the marker are present.
printf '%s\n' '{"schema":1,"release":"0.1.0"}' \
  >"$TMP/squash/etc/aurade-installer/gui-release-manifest.json"
mksquashfs "$TMP/squash" "$TMP/iso-tree/arch/x86_64/airootfs.sfs" \
  -noappend -quiet
(cd "$TMP/iso-tree" && bsdtar -cf "$TMP/bad-gui-manifest.iso" .)
printf 'release_channel=candidate\ngui_release=1\ngui_manifest_sha256=%s\n' \
  "$(sha256sum "$TMP/squash/etc/aurade-installer/gui-release-manifest.json" | awk '{print $1}')" \
  >"$TMP/bad-gui-manifest.iso.build-info"
if "$ROOT/ci/verify-iso-structure.sh" "$TMP/bad-gui-manifest.iso" \
    --full --require-gui >"$TMP/bad-gui-manifest.out" 2>&1; then
  echo 'ISO with a downgraded GUI manifest unexpectedly passed' >&2
  exit 1
fi
assert_output_contains 'embedded GUI manifest is not a 0.2.0 candidate' \
  "$TMP/bad-gui-manifest.out"

# Restore the valid manifest before the package-integrity mutations below.
cp "$TMP/valid-gui-release-manifest.json" \
  "$TMP/squash/etc/aurade-installer/gui-release-manifest.json"

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
assert_output_contains 'package checksum mismatch' "$TMP/tampered-full.out"

# An unlisted archive must fail even when the listed archive itself is valid.
cp "$TMP/squash/opt/aurade/repo/aurade-1.0-1-any.pkg.tar.zst" \
  "$TMP/squash/opt/aurade/repo/extra-1.0-1-any.pkg.tar.zst"
# Restore the locked archive and rebuild the tiny squashfs.
rm -f "$TMP/package/README"
cp "$TMP/valid-package.pkg.tar.zst" \
  "$TMP/squash/opt/aurade/repo/aurade-1.0-1-any.pkg.tar.zst"
mksquashfs "$TMP/squash" "$TMP/iso-tree/arch/x86_64/airootfs.sfs" \
  -noappend -quiet
(cd "$TMP/iso-tree" && bsdtar -cf "$TMP/unlisted-full.iso" .)
if "$ROOT/ci/verify-iso-structure.sh" "$TMP/unlisted-full.iso" --full \
    >"$TMP/unlisted.out" 2>&1; then
  echo 'ISO with an unlisted archive unexpectedly passed' >&2
  exit 1
fi
assert_output_contains 'unlisted package archive' "$TMP/unlisted.out"

echo 'ISO structure script test: PASS'
