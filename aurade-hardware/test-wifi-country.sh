#!/usr/bin/env bash
# The Wi-Fi country comes from the time zone, and nothing else.
#
# Runs aurade-wifi-country against a made up root, with an iw that writes
# down what it was asked, and checks the country for each kind of time zone
# link. Also checks the power saving setting says off.
set -Eeuo pipefail

HERE=$(cd -- "$(dirname -- "$0")" && pwd -P)
SCRIPT=${1:-$HERE/aurade-wifi-country}
NMCONF=${2:-$HERE/90-aurade-wifi.conf}
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fail() { echo "wifi country test: $*" >&2; exit 1; }

ROOT=$TMP/root
install -d "$ROOT/etc" "$ROOT/usr/share/zoneinfo"
printf '%s\n' '# a comment line' \
  $'US\t+415100-0873900\tAmerica/Chicago\tCentral (most areas)' \
  $'DE\t+5230+01322\tEurope/Berlin\tmost of Germany' \
  $'JP\t+353916+1394441\tAsia/Tokyo' >"$ROOT/usr/share/zoneinfo/zone.tab"
printf '%s\n' 'L America/Chicago US/Central' 'L Etc/UTC UTC' \
  >"$ROOT/usr/share/zoneinfo/tzdata.zi"

cat >"$TMP/iw" <<'IW'
#!/usr/bin/env bash
if [[ $* == 'reg get' ]]; then
  printf 'global\ncountry %s: DFS-UNSET\n' "${IW_CURRENT:-00}"
  printf 'phy#0\ncountry 99: DFS-UNSET\n'
  exit 0
fi
printf '%s\n' "$*" >>"$IW_LOG"
[[ -z ${IW_FAIL:-} ]]
IW
chmod 755 "$TMP/iw"

asked() {
  local link=$1
  rm -f "$ROOT/etc/localtime" "$TMP/iw.log"
  [[ -z $link ]] || ln -s "$link" "$ROOT/etc/localtime"
  AURADE_WIFI_ROOT=$ROOT AURADE_WIFI_IW=$TMP/iw IW_LOG=$TMP/iw.log \
    bash "$SCRIPT" >/dev/null || fail "failed for '$link'"
  cat "$TMP/iw.log" 2>/dev/null || true
}

expect() {
  local link=$1 want=$2 got
  got=$(asked "$link")
  [[ $got == "$want" ]] || fail "'$link' asked iw for '$got', expected '$want'"
}

expect /usr/share/zoneinfo/America/Chicago 'reg set US'
expect ../usr/share/zoneinfo/Europe/Berlin 'reg set DE'
expect /usr/share/zoneinfo/posix/Asia/Tokyo 'reg set JP'
expect /usr/share/zoneinfo/US/Central 'reg set US'
expect /usr/share/zoneinfo/UTC ''
expect /usr/share/zoneinfo/Etc/UTC ''
expect /usr/share/zoneinfo/Nowhere/Atlantis ''
expect /some/other/file ''
expect '' ''

# Already the country: nothing is asked of iw.
got=$(IW_CURRENT=US asked /usr/share/zoneinfo/America/Chicago)
[[ -z $got ]] || fail "asked iw for '$got' with the country already set"
# Set to another one: it is changed.
got=$(IW_CURRENT=DE asked /usr/share/zoneinfo/America/Chicago)
[[ $got == 'reg set US' ]] || fail "asked iw for '$got' when moving from DE"

# A card that refuses the country is reported, not a failed unit.
IW_FAIL=1 asked /usr/share/zoneinfo/America/Chicago >/dev/null

grep -qx 'wifi.powersave=2' "$NMCONF" || fail 'power saving is not set to off'

# The dispatcher hook runs the script for Wi-Fi coming up, and nothing else.
DISPATCH=${3:-$HERE/90-aurade-wifi-country.dispatcher}
hook() {
  sed "s#/usr/lib/aurade/aurade-wifi-country#$TMP/ran#; s#/sys/class/net#$TMP/net#" \
    "$DISPATCH" >"$TMP/hook"
  printf '#!/bin/sh\necho ran\n' >"$TMP/ran"; chmod 755 "$TMP/ran"
  sh "$TMP/hook" "$@"
}
install -d "$TMP/net/wlan0/wireless" "$TMP/net/eth0"
[[ $(hook wlan0 up) == ran ]] || fail 'the hook did not run for Wi-Fi coming up'
[[ -z $(hook eth0 up) ]] || fail 'the hook ran for a wired connection'
[[ -z $(hook wlan0 down) ]] || fail 'the hook ran for Wi-Fi going down'
echo "wifi country test: PASS"
