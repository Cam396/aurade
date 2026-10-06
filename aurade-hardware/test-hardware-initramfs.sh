#!/usr/bin/env bash
# The unlock prompt's keyboard drivers go into the initramfs of exactly the
# machines that need them.
#
# Sources the mkinitcpio drop-in the way mkinitcpio does, after the main
# configuration, against firmware names written to a directory, and checks
# the MODULES it leaves behind.
set -Eeuo pipefail

HERE=$(cd -- "$(dirname -- "$0")" && pwd -P)
DROPIN=${1:-$HERE/90-aurade-hardware.conf}
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fail() { echo "hardware initramfs test: $*" >&2; exit 1; }

modules_for() {
  local product=$1
  mkdir -p "$TMP/$product/sys/class/dmi/id"
  printf '%s\n' "$product" >"$TMP/$product/sys/class/dmi/id/product_name"
  AURADE_HW_ROOT="$TMP/$product" bash -c '
    MODULES=(existing)
    . "$1"
    printf "%s\n" "${MODULES[@]}"
    [[ -z ${_aurade_product+set} ]] || echo LEAKED' _ "$DROPIN"
}

has() { grep -Fxq -- "$2" <<<"$1"; }

out=$(modules_for 'Surface Laptop')
has "$out" 'surface_kbd?' || fail 'the Surface Laptop 1 keyboard driver is missing'
has "$out" 'surface_aggregator?' || fail 'the Surface Aggregator is missing on the Laptop 1'
has "$out" '8250_dw?' || fail 'the serial line to the Surface Aggregator is missing'
has "$out" 'existing' || fail 'the drop-in replaced the modules it should add to'

out=$(modules_for 'Surface Laptop 2')
has "$out" 'surface_kbd?' || fail 'the Surface Laptop 2 keyboard driver is missing'

out=$(modules_for 'Surface Laptop 4')
has "$out" 'surface_hid?' || fail 'the Surface Laptop 4 keyboard driver is missing'
has "$out" 'surface_kbd?' && fail 'the Laptop 4 got the Laptop 1 driver instead of its own'

out=$(modules_for 'MacBookPro13,3')
has "$out" 'applespi?' || fail 'the 2016 MacBook Pro keyboard driver is missing'

out=$(modules_for 'MacBookPro11,1')
[[ $out == existing ]] || fail "a 2014 MacBook Pro, whose keyboard is USB, got extra modules: $out"

out=$(modules_for 'XPS 13 9310')
[[ $out == existing ]] || fail "a machine that needs nothing got: $out"

# No firmware name at all, as in a container building an image.
out=$(AURADE_HW_ROOT="$TMP/nowhere" bash -c 'MODULES=(existing); . "$1"; printf "%s\n" "${MODULES[@]}"' _ "$DROPIN")
[[ $out == existing ]] || fail "with no firmware name the drop-in still added: $out"

# Every module is optional, so a kernel without one still builds.
if awk '/MODULES\+=\(/ {in_list = 1; sub(/.*MODULES\+=\(/, "")}
         in_list {line = $0; if (sub(/\).*/, "", line)) in_list = 0; print line}' "$DROPIN" |
    tr -s ' ' '\n' | grep -Eq '^[a-z0-9_]+$'; then
  fail 'a module is not marked optional, and a kernel without it would fail the build'
fi

echo 'hardware initramfs test: PASS (Surface Laptop 1, 2 and 4, 2016 and 2014 MacBook Pro, other machines)'
