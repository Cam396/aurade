#!/usr/bin/env bash
# Each kind of machine gets what it needs and nothing else.
#
# Describes machines as directories of sysfs files and asks the hardware
# library what it would install. The trap it guards: broadcom-wl switches off
# the open drivers for every Broadcom chip, so it must only go on a machine
# whose chip needs it. And a Surface needs nothing beyond what every install
# carries, so it must not start pulling in packages.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
LIB=$ROOT/installer/lib/aurade-hardware.sh
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fail() { echo "hardware test: $*" >&2; exit 1; }

# machine NAME VENDOR PRODUCT [VENDOR:DEVICE...]
machine() {
  local dir=$TMP/$1 vendor=$2 product=$3 pci n=0
  shift 3
  mkdir -p "$dir/sys/class/dmi/id" "$dir/sys/bus/pci/devices"
  printf '%s\n' "$vendor" >"$dir/sys/class/dmi/id/sys_vendor"
  printf '%s\n' "$product" >"$dir/sys/class/dmi/id/product_name"
  # Every machine has a host bridge that matches nothing.
  set -- 8086:1237 "$@"
  for pci in "$@"; do
    mkdir -p "$dir/sys/bus/pci/devices/0000:00:0$n.0"
    printf '0x%s\n' "${pci%%:*}" >"$dir/sys/bus/pci/devices/0000:00:0$n.0/vendor"
    printf '0x%s\n' "${pci##*:}" >"$dir/sys/bus/pci/devices/0000:00:0$n.0/device"
    n=$((n + 1))
  done
}

detect() {
  AURADE_HW_ROOT=$TMP/$1 bash -c '. "$1"; aurade_hw_detect
    printf "packages=%s\n" "${HW_PACKAGES[*]}"
    printf "summary=%s\n" "$HW_SUMMARY"
    printf "note=%s\n" "${HW_NOTES[@]}"' _ "$LIB"
}

has() { grep -Fxq -- "$2" <<<"$1"; }

machine laptop1 'Microsoft Corporation' 'Surface Laptop' 11ab:2b38
machine go 'Microsoft Corporation' 'Surface Go' 168c:003e
machine macbook 'Apple Inc.' 'MacBookPro11,1' 14e4:43a0
machine t2 'Apple Inc.' 'MacBookPro15,2' 106b:1801 14e4:4464
machine chromebook 'Google' 'Drawcia' 8086:4df0
machine dell 'Dell Inc.' 'XPS 13 9310' 14e4:43b1
machine plain 'LENOVO' '20XW' 8086:a0f0 168c:003e
machine brcmfmac 'Dell Inc.' 'Inspiron' 14e4:43ba

for surface in laptop1 go; do
  out=$(detect "$surface")
  has "$out" 'packages=' || fail "$surface: a Surface pulled in packages it does not need: $out"
  grep -q '^note=.*touchscreen and pen need the linux-surface kernel' <<<"$out" ||
    fail "$surface: nobody is told the touchscreen needs another kernel"
done
has "$(detect laptop1)" 'summary=Microsoft Surface Laptop' || fail 'the Surface Laptop is not recognised'

out=$(detect macbook)
has "$out" 'packages=broadcom-wl-dkms linux-headers' ||
  fail "MacBook with a BCM4360: the driver, or the headers it is built against, is missing: $out"

out=$(detect t2)
has "$out" 'packages=' || fail "T2 Mac: installed something for hardware it cannot drive: $out"
grep -q '^note=.*T2' <<<"$out" || fail 'T2 Mac: the person is not told the keyboard and Wi-Fi need more'

out=$(detect chromebook)
has "$out" 'packages=' || fail "Chromebook: $out"
has "$out" 'summary=Chromebook (Drawcia)' || fail "Chromebook: not recognised: $out"

out=$(detect dell)
has "$out" 'packages=broadcom-wl-dkms linux-headers' || fail "a PC with a BCM4352 needs the driver too: $out"

out=$(detect plain)
has "$out" 'packages=' || fail "a plain laptop got extras: $out"
has "$out" 'note=' || fail "a plain laptop got a note: $out"

out=$(detect brcmfmac)
has "$out" 'packages=' ||
  fail "broadcom-wl went on a chip the open driver handles, and would switch that driver off: $out"

echo 'hardware test: PASS (Surface Laptop and Go, Broadcom Mac and PC, T2 Mac, Chromebook, plain PCs)'
