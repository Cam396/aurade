#!/usr/bin/env bash
# The installer's modprobe hook for the open Broadcom drivers: wl on the chips
# only wl drives, the module asked for everywhere else.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
GUARD=$ROOT/lib/aurade-live-wl-guard
CONF=$ROOT/archiso/airootfs/etc/modprobe.d/aurade-live-broadcom-wl.conf
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fail() { echo "live wl guard test: $*" >&2; exit 1; }

# A modprobe that writes down what it was asked, and has wl or not.
cat >"$TMP/modprobe" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$CALLS"
if [[ $* == '-q wl' ]]; then
  [[ ${HAVE_WL:-1} == 1 ]]
fi
STUB
chmod +x "$TMP/modprobe"

machine() {
  local name=$1 device=$2
  mkdir -p "$TMP/$name/sys/bus/pci/devices/0000:03:00.0"
  printf '0x14e4\n' >"$TMP/$name/sys/bus/pci/devices/0000:03:00.0/vendor"
  printf '0x%s\n' "$device" >"$TMP/$name/sys/bus/pci/devices/0000:03:00.0/device"
}
machine mac 43a0      # BCM4360, a 2013 to 2015 MacBook Pro
machine macbook43 4331  # BCM4331, the open b43 claims it and has no firmware
machine brcmfmac 43ba # BCM43602, a 2016 MacBook Pro: the open driver works
mkdir -p "$TMP/plain/sys/bus/pci/devices"

guard() {
  local name=$1
  shift
  : >"$TMP/calls"
  CALLS=$TMP/calls AURADE_MODPROBE=$TMP/modprobe AURADE_HW_ROOT=$TMP/$name \
    AURADE_HARDWARE_LIB=$ROOT/lib/aurade-hardware.sh "${ENVS[@]}" "$GUARD" "$@" ||
    fail "the guard failed on $name"
  cat "$TMP/calls"
}
ENVS=(env)

out=$(guard mac bcma)
[[ $out == '-q wl' ]] || fail "a BCM4360 should get wl and nothing else, got: $out"

out=$(guard macbook43 b43 qos=0)
[[ $out == '-q wl' ]] || fail "a BCM4331 should get wl, not b43, got: $out"

out=$(guard brcmfmac bcma)
[[ $out == '--ignore-install bcma' ]] || fail "another Broadcom chip lost its open driver, got: $out"

out=$(guard plain ssb)
[[ $out == '--ignore-install ssb' ]] || fail "a machine without Broadcom Wi-Fi lost ssb, got: $out"

# An image built without wl: the open driver, which is better than nothing.
ENVS=(env HAVE_WL=0)
out=$(guard mac bcma)
[[ $out == $'-q wl\n--ignore-install bcma' ]] || fail "with no wl on the image, bcma did not load, got: $out"
ENVS=(env)

# Options from the command line reach the module.
out=$(guard plain b43 qos=0 verbose=1)
[[ $out == '--ignore-install b43 qos=0 verbose=1' ]] || fail "options were lost, got: $out"

# The hook is wired for every open driver that claims those chips, and points
# at where the image installs it.
for module in bcma ssb b43 brcmsmac; do
  grep -Fxq "install $module /usr/local/lib/aurade/aurade-live-wl-guard $module \$CMDLINE_OPTS" "$CONF" ||
    fail "$module is not routed through the guard"
done

grep -Fxq 'blacklist wl' "$CONF" ||
  fail 'wl is not blacklisted, and its alias loads it for every Wi-Fi card'

# udev loads wl for exactly the chips the installer's own list names.
RULE=$ROOT/archiso/airootfs/etc/udev/rules.d/60-aurade-live-wl.rules
rule_ids=$(sed -n -E 's/.*ATTR\{device\}=="([^"]+)".*/\1/p' "$RULE" | tr '|' '\n' | sed 's/^0x//' | sort)
lib_ids=$(AURADE_HW_ROOT=$TMP/plain bash -c '. "$1"; printf "%s\n" "${AURADE_HW_WL_DEVICES[@]}"' _ \
  "$ROOT/lib/aurade-hardware.sh" | sort)
[[ -n $rule_ids && $rule_ids == "$lib_ids" ]] ||
  fail "the udev rule's chips differ from AURADE_HW_WL_DEVICES: rule [${rule_ids//$'\n'/ }], list [${lib_ids//$'\n'/ }]"
grep -Fq 'RUN+="/usr/bin/modprobe wl"' "$RULE" ||
  fail "the udev rule does not load wl by name with modprobe, which a blacklist does not stop"

echo 'live wl guard test: PASS (BCM4360 and BCM4331 get wl, BCM43602 and others keep the open drivers, no wl falls back, options pass)'
