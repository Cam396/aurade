#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf -- "$TMP"' EXIT
fail() { printf 'test-tui-wifi: %s\n' "$*" >&2; exit 1; }

install -d "$TMP/live" "$TMP/target" "$TMP/stub"
printf 'enabled\n' >"$TMP/radio"
printf 'disconnected\n' >"$TMP/state"
printf 'full\n' >"$TMP/connectivity"

cat >"$TMP/stub/nmcli" <<'STUB'
#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' "$*" >>"$AURADE_TEST_WIFI_CALLS"
case $* in
  '-t radio wifi') cat "$AURADE_TEST_WIFI_RADIO" ;;
  'radio wifi on') printf 'enabled\n' >"$AURADE_TEST_WIFI_RADIO" ;;
  'radio wifi off') printf 'disabled\n' >"$AURADE_TEST_WIFI_RADIO" ;;
  *'device status')
    if [[ $(cat "$AURADE_TEST_WIFI_STATE") == connected ]]; then
      printf '%s\n' 'wlan0:wifi:connected:Ferry\: Cross'
    else
      printf '%s\n' 'wlan0:wifi:disconnected:'
    fi ;;
  *'general status') cat "$AURADE_TEST_WIFI_CONNECTIVITY" ;;
  'device wifi rescan') : ;;
  *'device wifi list')
    active=no
    [[ $(cat "$AURADE_TEST_WIFI_STATE") != connected ]] || active='*'
    printf '%s\n' 'Ferry\: Cross:41:WPA2:no' 'Guest Lounge:38:--:no' \
      "Ferry\\: Cross:82:WPA2:$active" 'kestrel-5g:67:WPA2:no' ;;
  *'connection show') printf '%s\n' 'kestrel-5g:802-11-wireless' ;;
  'connection load '*) : ;;
  'connection up uuid '*)
    [[ ${AURADE_TEST_WIFI_FAIL:-0} != 1 ]] || {
      printf 'Error: Secrets were required, but not provided.\n' >&2
      exit 4
    }
    printf 'connected\n' >"$AURADE_TEST_WIFI_STATE" ;;
  'connection up id '*) printf 'connected\n' >"$AURADE_TEST_WIFI_STATE" ;;
  'connection delete '*) : ;;
esac
STUB
chmod +x "$TMP/stub/nmcli"

cat >"$TMP/stub/network-check" <<'STUB'
#!/usr/bin/env bash
printf '  A network connection is up.\n'
printf '  The pinned package snapshot answers.\n'
STUB
chmod +x "$TMP/stub/network-check"

export AURADE_NMCLI="$TMP/stub/nmcli"
export AURADE_NM_PROFILE_DIR="$TMP/live"
export AURADE_NETWORK_HELPER="$TMP/stub/network-check"
export AURADE_TEST_WIFI_CALLS="$TMP/calls"
export AURADE_TEST_WIFI_RADIO="$TMP/radio"
export AURADE_TEST_WIFI_STATE="$TMP/state"
export AURADE_TEST_WIFI_CONNECTIVITY="$TMP/connectivity"
export AURADE_TUI_PLAIN=1 AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii
export AURADE_TUI_HEIGHT=24 AURADE_TUI_COLUMNS=68
export AURADE_INSTALLER_TUI_LIB=1
. "$ROOT/installer/bin/aurade-installer-tui"
trap 'cleanup; rm -rf -- "$TMP"' EXIT
export AURADE_TUI_KEYS="$TMP/keys"

keys() {
  printf '%s\n' "$@" >"$TMP/keys"
  exec {_TUI_KEYFD}<"$TMP/keys"
  export _TUI_KEYFD
}
release() { exec {_TUI_KEYFD}<&-; unset _TUI_KEYFD; }
typed() {
  local value=$1 i
  for (( i = 0; i < ${#value}; i++ )); do
    if [[ ${value:i:1} == ' ' ]]; then printf 'space\n'; else printf '%s\n' "${value:i:1}"; fi
  done
}

# The strongest sighting wins even when it appears after a weaker one.
aurade_wifi_scan || fail 'the shared backend could not scan'
[[ ${AURADE_WIFI_SSIDS[0]} == 'Ferry: Cross' ]] || fail 'the escaped SSID was lost'
[[ ${AURADE_WIFI_SIGNALS[0]} == 82 ]] || fail 'a weaker duplicate won'
wifi_sort
[[ ${WIFI_VIEW_ORDER[0]} == 0 ]] || fail 'the strongest network was not first'
SECRET_REVEAL=0
screen_wifi_password 'Ferry: Cross' 'short' >"$TMP/short.out"
! grep -Fq 'will still be accepted' "$TMP/short.out" ||
  fail 'the Wi-Fi prompt says a short password will be accepted'

password='reticulated osprey 88'
{
  echo enter
  typed "$password"
  echo enter
  echo d
  echo enter
  echo c
} >"$TMP/keys"
exec {_TUI_KEYFD}<"$TMP/keys"; export _TUI_KEYFD
run_network >"$TMP/join.out" || fail 'the Wi-Fi flow did not complete'
release
[[ $(cat "$TMP/state") == connected ]] || fail 'the selected network did not connect'
aurade_wifi_scan || fail 'the active network could not be rescanned'
[[ ${AURADE_WIFI_ACTIVE[0]} == true ]] || fail 'NetworkManager active marker was missed'
grep -Fq 'Connected to Ferry: Cross.' "$TMP/join.out" || fail 'the TUI did not confirm the connection'
grep -Fq 'The pinned package snapshot answers.' "$TMP/join.out" || fail 'the connection check did not appear'
! grep -Fq "$password" "$TMP/join.out" || fail 'the password appeared on screen'
! grep -Fq "$password" "$TMP/calls" || fail 'the password reached nmcli argv'
mapfile -t profiles < <(find "$TMP/live" -name 'aurade-*.nmconnection' -type f)
(( ${#profiles[@]} == 1 )) || fail 'the connection did not leave exactly one profile'
[[ $(stat -c %a "${profiles[0]}") == 600 ]] || fail 'the live profile is not private'
grep -Fq "psk=$password" "${profiles[0]}" || fail 'the profile lost its password'

# The same private profile reaches the installed system. A symlink is ignored.
ln -s /etc/shadow "$TMP/live/aurade-bad.nmconnection"
aurade_wifi_copy_profiles "$TMP/target"
dest="$TMP/target/etc/NetworkManager/system-connections"
[[ -f $dest/${profiles[0]##*/} ]] || fail 'the installed system lost the Wi-Fi connection'
[[ $(stat -c %a "$dest/${profiles[0]##*/}") == 600 ]] || fail 'the installed profile is not private'
[[ ! -e $dest/aurade-bad.nmconnection ]] || fail 'a symlink was copied into the target'

# A failed association cleans its profile and never prints the secret.
printf 'disconnected\n' >"$TMP/state"
export AURADE_TEST_WIFI_FAIL=1
{
  echo enter
  typed "$password"
  echo enter
  echo esc
  echo c
} >"$TMP/keys"
exec {_TUI_KEYFD}<"$TMP/keys"; export _TUI_KEYFD
run_network >"$TMP/fail.out" || fail 'the failed join trapped the user'
release
grep -Fq 'That password was not accepted.' "$TMP/fail.out" || fail 'the error was not actionable'
! grep -Fq "$password" "$TMP/fail.out" || fail 'the failed password appeared on screen'
(( $(find "$TMP/live" -name 'aurade-*.nmconnection' -type f | wc -l) == 1 )) ||
  fail 'a failed connection left a profile behind'
unset AURADE_TEST_WIFI_FAIL

# Open networks get no password section. A saved profile is reused.
aurade_wifi_connect 'Guest Lounge' '' || fail 'the open network did not connect'
mapfile -t profiles < <(find "$TMP/live" -name 'aurade-*.nmconnection' -type f)
(( ${#profiles[@]} == 2 )) || fail 'the open network did not make one profile'
open_profile=$(grep -lF 'ssid=Guest Lounge' "${profiles[@]}")
[[ -n $open_profile ]] || fail 'the open network profile was not found'
! grep -Fq '[wifi-security]' "$open_profile" || fail 'the open network got a password section'
aurade_wifi_connect 'kestrel-5g' '' || fail 'the saved network did not connect'
(( $(find "$TMP/live" -name 'aurade-*.nmconnection' -type f | wc -l) == 2 )) ||
  fail 'joining a saved network made another profile'
grep -Fq 'connection up id kestrel-5g' "$TMP/calls" || fail 'the saved profile was not reused'

# Radio and saved connection controls remain reachable without a disk.
keys w w r down f f c
run_network >"$TMP/controls.out" || fail 'the network controls did not complete'
release
grep -Fq 'radio wifi off' "$TMP/calls" || fail 'Wi-Fi could not be turned off'
grep -Fq 'radio wifi on' "$TMP/calls" || fail 'Wi-Fi could not be turned on'
grep -Fq 'connection delete id kestrel-5g' "$TMP/calls" || fail 'a saved network could not be forgotten'

# Many networks stay paged on a short console. Untrusted names cannot repaint it.
AURADE_WIFI_SSIDS=()
AURADE_WIFI_SIGNALS=()
AURADE_WIFI_SECURITY=()
AURADE_WIFI_OPEN=()
AURADE_WIFI_ACTIVE=()
AURADE_WIFI_SAVED=()
for (( i = 0; i < 14; i++ )); do
  AURADE_WIFI_SSIDS[i]="Network $i"
  AURADE_WIFI_SIGNALS[i]=$(( 90 - i ))
  AURADE_WIFI_SECURITY[i]=WPA2
  AURADE_WIFI_OPEN[i]=false
  AURADE_WIFI_ACTIVE[i]=false
  AURADE_WIFI_SAVED[i]=false
done
wifi_sort
screen_network 9 >"$TMP/paged.out"
(( $(wc -l <"$TMP/paged.out") <= 24 )) || fail 'the network list scrolls a 24-line console'
grep -Fq '> Network 9' "$TMP/paged.out" || fail 'the selected network is offscreen'
[[ $(wifi_name $'\033[2JNetwork') == '[2JNetwork' ]] || fail 'an SSID can repaint the terminal'

old_nmcli=$AURADE_WIFI_NMCLI
AURADE_WIFI_NMCLI="$TMP/missing-nmcli"
keys c
run_network >"$TMP/missing.out" || fail 'missing NetworkManager trapped the user'
release
grep -Fq 'Wi-Fi cannot be set up here' "$TMP/missing.out" ||
  fail 'missing NetworkManager was not explained'
AURADE_WIFI_NMCLI=$old_nmcli

printf 'installer TUI Wi-Fi test: PASS\n'
