#!/usr/bin/env bash
# Broadcom's wl driver for the installer, built for the installer's kernel.
#
#   build-live-wl.sh STAGE WORK
#
# Installed systems get broadcom-wl-dkms, which builds wl against their own
# kernel. The installer has no compiler and no kernel headers, and most Intel
# Macs had no Wi-Fi on it. So wl is built here, once, against linux-headers
# from the same Arch snapshot the image installs its kernel from, and only the
# module goes on the image: about 2 MB. STAGE is the staged archiso profile,
# its pacman.conf already pointing at the snapshot. WORK is scratch space.
#
# Run as root, like mkarchiso, with gcc and make on the builder.
set -Eeuo pipefail

STAGE=${1:?usage: build-live-wl.sh STAGE WORK}
WORK=${2:?usage: build-live-wl.sh STAGE WORK}

fail() { echo "build-live-wl: $*" >&2; exit 1; }

for command in pacman bsdtar make gcc zstd modinfo strip; do
  command -v "$command" >/dev/null || fail "$command is required"
done
grep -qx linux "$STAGE/packages.x86_64" || fail 'the image does not use the linux kernel package'
[[ $WORK == /* && $WORK != / ]] || fail 'WORK must be an absolute path other than /'

rm -rf -- "${WORK:?}"
install -d "$WORK/db" "$WORK/cache" "$WORK/headers" "$WORK/wl"

# The headers and the driver source from the image's own snapshot, the one
# its kernel comes from. --nodeps twice: only these files, not what they need
# to run.
pacman --config "$STAGE/pacman.conf" --dbpath "$WORK/db" --cachedir "$WORK/cache" \
  --noconfirm -Sy >/dev/null
pacman --config "$STAGE/pacman.conf" --dbpath "$WORK/db" --cachedir "$WORK/cache" \
  --noconfirm --nodeps --nodeps -Sw linux-headers broadcom-wl-dkms >/dev/null

one() {
  local found=("$WORK"/cache/"$1"-[0-9]*.pkg.tar.zst)
  [[ ${#found[@]} -eq 1 && -f ${found[0]} ]] || fail "expected one $1 package, found ${#found[@]}"
  printf '%s' "${found[0]}"
}
headers_pkg=$(one linux-headers)
wl_pkg=$(one broadcom-wl-dkms)

pkgver() { bsdtar -xOf "$1" .PKGINFO | awk -F' = ' '$1 == "pkgver" {print $2}'; }
# The kernel the image installs, as the same snapshot's database has it.
linux_ver=$(pacman --config "$STAGE/pacman.conf" --dbpath "$WORK/db" --nodeps --nodeps -Sp \
  --print-format '%v' linux)
[[ $linux_ver == "$(pkgver "$headers_pkg")-"* || $linux_ver == "$(pkgver "$headers_pkg")" ]] ||
  fail "linux $linux_ver and linux-headers $(pkgver "$headers_pkg") differ"

# The module directory name, from the headers package itself.
kver=$(bsdtar -tf "$headers_pkg" | sed -n -E 's|^usr/lib/modules/([^/]+)/build/Makefile$|\1|p')
[[ -n $kver && $kver != */* ]] || fail 'no kernel build directory in linux-headers'

bsdtar -xf "$headers_pkg" -C "$WORK/headers" "usr/lib/modules/$kver/build"
bsdtar -xf "$wl_pkg" -C "$WORK/wl"
kbuild=$WORK/headers/usr/lib/modules/$kver/build
src=$(find "$WORK/wl/usr/src" -mindepth 1 -maxdepth 1 -type d -name 'broadcom-wl-*' | head -1)
blob=$WORK/wl/usr/lib/broadcom-wl-dkms/wlc_hybrid.o_shipped
[[ -d $kbuild && -n $src && -r $blob ]] || fail 'the downloaded packages are not laid out as expected'

# The Makefile links Broadcom's binary part from where the package installs it.
grep -Fq '/usr/lib/broadcom-wl-dkms/wlc_hybrid.o_shipped' "$src/Makefile" ||
  fail 'the wl Makefile no longer names its binary part where this expects'
sed -i "s|/usr/lib/broadcom-wl-dkms/wlc_hybrid.o_shipped|$blob|" "$src/Makefile"

KBUILD_NOPEDANTIC=1 make -s -C "$kbuild" M="$src" -j"$(nproc)" modules >"$WORK/build.log" 2>&1 || {
  tail -40 "$WORK/build.log" >&2
  fail 'wl did not build'
}
module=$src/wl.ko
[[ -f $module ]] || fail 'the build left no wl.ko'
vermagic=$(modinfo -F vermagic "$module")
[[ $vermagic == "$kver "* ]] || fail "wl.ko is for '${vermagic%% *}', the image's kernel is $kver"

strip --strip-debug "$module"
zstd -q -19 --rm "$module" -o "$module.zst"
install -Dm0644 "$module.zst" "$STAGE/airootfs/usr/lib/modules/$kver/updates/wl.ko.zst"
install -Dm0644 "$WORK/wl/usr/share/licenses/broadcom-wl-dkms/LICENSE" \
  "$STAGE/airootfs/usr/share/licenses/broadcom-wl/LICENSE"
printf 'live_wl=%s %s %s\n' "$kver" "$(pkgver "$wl_pkg")" \
  "$(stat -c %s "$STAGE/airootfs/usr/lib/modules/$kver/updates/wl.ko.zst")"
