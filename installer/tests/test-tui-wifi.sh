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
printf '%s\n' \
  'kestrel-5g:00000000-0000-0000-0000-000000000001:802-11-wireless' \
  'kestrel-5g:00000000-0000-0000-0000-000000000002:wifi' \
  'Wired office:00000000-0000-0000-0000-000000000003:ethernet' \
  'Ghost:invalid:wifi' \
  >"$TMP/saved"

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
      "Ferry\\: Cross:82:WPA2:$active" 'kestrel-5g:67:WPA2:no' \
      'Pure WPA3:31:WPA3:no' 'Cafe OWE:26:OWE:no' \
      'Company:25:WPA2 802.1X:no' 'Old Lock:18:WEP:no' ;;
  '-t -f NAME,UUID,TYPE connection show')
    cat "$AURADE_TEST_WIFI_SAVED"
    for profile in "$AURADE_TEST_WIFI_PROFILE_DIR"/aurade-*.nmconnection; do
      [[ -f $profile && ! -L $profile ]] || continue
      name=$(sed -n 's/^id=//p' "$profile" | head -1)
      uuid=$(sed -n 's/^uuid=//p' "$profile" | head -1)
      name=${name//\\/\\\\}
      name=${name//:/\\:}
      printf '%s:%s:wifi\n' "$name" "$uuid"
    done ;;
  '-t -f NAME,TYPE connection show')
    printf '%s\n' 'kestrel-5g:802-11-wireless'
    for profile in "$AURADE_TEST_WIFI_PROFILE_DIR"/aurade-*.nmconnection; do
      [[ -f $profile && ! -L $profile ]] || continue
      name=$(sed -n 's/^id=//p' "$profile" | head -1)
      name=${name//\\/\\\\}
      name=${name//:/\\:}
      printf '%s:wifi\n' "$name"
    done ;;
  'connection load '*) : ;;
  'connection up uuid '*)
    [[ ${AURADE_TEST_WIFI_FAIL:-0} != 1 ]] || {
      printf 'Error: Secrets were required, but not provided.\n' >&2
      exit 4
    }
    printf 'connected\n' >"$AURADE_TEST_WIFI_STATE" ;;
  'connection up id '*) printf 'connected\n' >"$AURADE_TEST_WIFI_STATE" ;;
  'connection delete uuid '*)
    uuid=${*: -1}
    sed -i "/:$uuid:/d" "$AURADE_TEST_WIFI_SAVED" ;;
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
export AURADE_TEST_WIFI_SAVED="$TMP/saved"
export AURADE_TEST_WIFI_PROFILE_DIR="$TMP/live"
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
[[ ${AURADE_WIFI_AUTH[3]} == sae ]] || fail 'WPA3-only was classified as WPA2'
[[ ${AURADE_WIFI_AUTH[4]} == owe ]] || fail 'Enhanced Open was classified as password Wi-Fi'
[[ ${AURADE_WIFI_AUTH[5]} == enterprise ]] || fail 'account setup was classified as a password'
[[ ${AURADE_WIFI_AUTH[6]} == legacy ]] || fail 'WEP was classified as a WPA password'
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
WIFI_CURSOR=3
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
WIFI_CURSOR=0
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

# WPA3-only and Enhanced Open get their own keyfile types. Unsupported networks
# fail before a profile is written or a password is sent to nmcli.
aurade_wifi_connect 'Pure WPA3' tiny || fail 'WPA3-only rejected a valid SAE passphrase'
wpa3_profile=$(grep -lF 'ssid=Pure WPA3' "$TMP/live"/aurade-*.nmconnection)
grep -Fxq 'key-mgmt=sae' "$wpa3_profile" || fail 'WPA3-only got a WPA2 profile'
grep -Fxq 'psk=tiny' "$wpa3_profile" || fail 'the SAE password was lost'
aurade_wifi_connect 'Cafe OWE' '' || fail 'Enhanced Open could not connect'
owe_profile=$(grep -lF 'ssid=Cafe OWE' "$TMP/live"/aurade-*.nmconnection)
grep -Fxq 'key-mgmt=owe' "$owe_profile" || fail 'Enhanced Open got the wrong keyfile type'
! grep -Fq 'psk=' "$owe_profile" || fail 'Enhanced Open got a password'
before_profiles=$(find "$TMP/live" -name 'aurade-*.nmconnection' -type f | wc -l)
aurade_wifi_connect Company anything >/dev/null 2>&1 && fail 'enterprise Wi-Fi was given a personal profile'
[[ $AURADE_WIFI_ERROR == *'work or school account'* ]] || fail 'enterprise Wi-Fi has no useful explanation'
aurade_wifi_connect 'Old Lock' anything >/dev/null 2>&1 && fail 'WEP was given a WPA profile'
[[ $AURADE_WIFI_ERROR == *'older Wi-Fi security'* ]] || fail 'WEP has no useful explanation'
(( $(find "$TMP/live" -name 'aurade-*.nmconnection' -type f | wc -l) == before_profiles )) ||
  fail 'an unsupported network left a profile'

# A hidden network needs an exact SSID, security choice, and a profile that
# continues probing for that SSID after the installed system boots.
aurade_wifi_connect 'Night Lobby' secretpass wpa-psk true || fail 'hidden WPA could not connect'
hidden_profile=$(grep -lF 'ssid=Night Lobby' "$TMP/live"/aurade-*.nmconnection)
grep -Fxq 'hidden=true' "$hidden_profile" || fail 'the hidden profile will not find its SSID'
grep -Fxq 'autoconnect=true' "$hidden_profile" || fail 'the hidden profile will not reconnect'
[[ $(stat -c %a "$hidden_profile") == 600 ]] || fail 'hidden profile permissions are not private'
aurade_wifi_connect Visible '' open true || fail 'hidden open network could not connect'
open_hidden_profile=$(grep -lF 'ssid=Visible' "$TMP/live"/aurade-*.nmconnection)
grep -Fxq 'hidden=true' "$open_hidden_profile" || fail 'hidden open network was not marked hidden'
aurade_wifi_connect 'Night Lobby' short wpa-psk true >/dev/null 2>&1 &&
  fail 'short WPA password was accepted for a hidden network'
aurade_wifi_connect 'Night Lobby' '' sae true >/dev/null 2>&1 &&
  fail 'empty WPA3 password was accepted for a hidden network'
long_ssid=$(printf '%033d' 0)
aurade_wifi_connect "$long_ssid" '' open true >/dev/null 2>&1 &&
  fail 'a network name over 32 bytes was accepted'
aurade_wifi_connect $'bad\nname' '' open true >/dev/null 2>&1 &&
  fail 'a control character reached a network keyfile'

# Radio and saved connection controls remain reachable without a disk.
guest_uuid=${open_profile##*/aurade-}
guest_uuid=${guest_uuid%.nmconnection}
keys w w r down down f f c
run_network >"$TMP/controls.out" || fail 'the network controls did not complete'
release
grep -Fq 'radio wifi off' "$TMP/calls" || fail 'Wi-Fi could not be turned off'
grep -Fq 'radio wifi on' "$TMP/calls" || fail 'Wi-Fi could not be turned on'
grep -Fq "connection delete uuid $guest_uuid" "$TMP/calls" ||
  fail 'the scanned saved network was not forgotten by UUID'
WIFI_CURSOR=0

# Hidden setup runs inside the same network page and keeps its private profile.
{
  echo h
  typed 'Night Guest'
  echo enter
  echo enter
  typed 'hiddenpass'
  echo enter
  echo c
} >"$TMP/keys"
exec {_TUI_KEYFD}<"$TMP/keys"; export _TUI_KEYFD
run_network >"$TMP/hidden.out" || fail 'the hidden-network flow did not complete'
release
hidden_ui_profile=$(grep -lF 'ssid=Night Guest' "$TMP/live"/aurade-*.nmconnection)
grep -Fxq 'hidden=true' "$hidden_ui_profile" || fail 'the TUI did not mark the network hidden'
grep -Fq 'Connected to Night Guest.' "$TMP/hidden.out" || fail 'the hidden join had no confirmation'
! grep -Fq 'hiddenpass' "$TMP/hidden.out" || fail 'the hidden password appeared on screen'
! grep -Fq 'hiddenpass' "$TMP/calls" || fail 'the hidden password reached nmcli argv'

# WPA3 Personal allows a short SAE passphrase and offers it as a distinct choice.
{
  echo h
  typed 'Night WPA3'
  echo enter
  echo down
  echo enter
  typed tiny
  echo enter
  echo c
} >"$TMP/keys"
exec {_TUI_KEYFD}<"$TMP/keys"; export _TUI_KEYFD
run_network >"$TMP/sae.out" || fail 'the hidden WPA3 flow did not complete'
release
sae_ui_profile=$(grep -lF 'ssid=Night WPA3' "$TMP/live"/aurade-*.nmconnection)
grep -Fxq 'key-mgmt=sae' "$sae_ui_profile" || fail 'the TUI did not use WPA3 Personal'

# Saved profiles include hidden networks that scans cannot show. UUID actions
# target one profile even when another saved connection has the same name.
aurade_wifi_saved_profiles || fail 'saved networks could not be listed'
[[ ${AURADE_WIFI_SAVED_NAMES[0]} == kestrel-5g &&
   ${AURADE_WIFI_SAVED_NAMES[1]} == kestrel-5g ]] ||
  fail 'duplicate saved names were collapsed'
for name in "${AURADE_WIFI_SAVED_NAMES[@]}"; do
  [[ $name != 'Wired office' && $name != Ghost ]] || fail 'a non-Wi-Fi or invalid profile was shown'
done
saved_hidden=-1
saved_colon=-1
for index in "${!AURADE_WIFI_SAVED_NAMES[@]}"; do
  case ${AURADE_WIFI_SAVED_NAMES[index]} in
    'Night Guest') saved_hidden=$index ;;
    'Ferry: Cross') saved_colon=$index ;;
  esac
done
(( saved_hidden >= 0 && saved_colon >= 0 )) || fail 'a hidden or escaped network was lost'
[[ ${AURADE_WIFI_SAVED_CARRIED[saved_hidden]} == true ]] || fail 'the hidden profile was marked live only'
[[ ${AURADE_WIFI_SAVED_CARRIED[0]} == false ]] || fail 'a preexisting profile was marked for install'
saved_hidden_uuid=${AURADE_WIFI_SAVED_UUIDS[saved_hidden]}
WIFI_SAVED_CURSOR=$saved_hidden
screen_wifi_saved "$WIFI_SAVED_CURSOR" >"$TMP/saved-page.out"
(( $(wc -l <"$TMP/saved-page.out") <= 24 )) || fail 'saved networks scroll off a 24-line console'
grep -Fq 'New system' "$TMP/saved-page.out" || fail 'the profile carryover is not shown'
screen_wifi_saved 0 >"$TMP/saved-first.out"
grep -Fq 'Live only' "$TMP/saved-first.out" || fail 'live-only profiles are not marked'
grep -Fq 'kestrel-5g #0001' "$TMP/saved-first.out" || fail 'duplicate profiles look identical'
grep -Fq 'kestrel-5g #0002' "$TMP/saved-first.out" || fail 'duplicate profiles look identical'
WIFI_SAVED_NOTICE='More than one saved connection uses this name. Choose one.'
screen_wifi_saved 0 >"$TMP/saved-notice.out"
(( $(wc -l <"$TMP/saved-notice.out") <= 24 )) ||
  fail 'the saved page with a notice scrolls off a 24-line console'
WIFI_SAVED_NOTICE=

WIFI_SAVED_CURSOR=$saved_hidden
keys s enter c
run_network >"$TMP/saved-reconnect.out" || fail 'saved network reconnect did not complete'
release
grep -Fq "connection up uuid $saved_hidden_uuid" "$TMP/calls" ||
  fail 'the hidden network was not reconnected by UUID'
grep -Fq 'Connected to Night Guest.' "$TMP/saved-reconnect.out" ||
  fail 'the saved-network page gave no connection result'

# A scanned name with two saved profiles asks which one to use.
WIFI_CURSOR=1
keys enter down enter c
run_network >"$TMP/duplicate-scan.out" || fail 'duplicate-name scan entry did not complete'
release
grep -Fq 'More than one saved connection uses this name.' "$TMP/duplicate-scan.out" ||
  fail 'the scan page silently chose a duplicate saved name'
grep -Fq 'connection up uuid 00000000-0000-0000-0000-000000000002' "$TMP/calls" ||
  fail 'the scan page did not use the selected duplicate profile'

WIFI_SAVED_CURSOR=1
keys s enter c
run_network >"$TMP/duplicate-reconnect.out" || fail 'duplicate-name reconnect did not complete'
release
grep -Fq 'connection up uuid 00000000-0000-0000-0000-000000000002' "$TMP/calls" ||
  fail 'a duplicate saved name reconnected by ambiguous ID'
WIFI_SAVED_CURSOR=1
keys s f f esc c
run_network >"$TMP/duplicate-forget.out" || fail 'duplicate-name forget did not complete'
release
grep -Fq 'connection delete uuid 00000000-0000-0000-0000-000000000002' "$TMP/calls" ||
  fail 'a duplicate saved name was deleted by ambiguous ID'
grep -Fq ':00000000-0000-0000-0000-000000000001:' "$TMP/saved" ||
  fail 'forgetting one duplicate removed the other'

aurade_wifi_saved_profiles || fail 'saved networks disappeared after forgetting one'
saved_hidden=-1
for index in "${!AURADE_WIFI_SAVED_NAMES[@]}"; do
  [[ ${AURADE_WIFI_SAVED_UUIDS[index]} != "$saved_hidden_uuid" ]] || saved_hidden=$index
done
(( saved_hidden >= 0 )) || fail 'the hidden saved network disappeared unexpectedly'
WIFI_SAVED_CURSOR=$saved_hidden
keys s f f esc c
run_network >"$TMP/saved-forget.out" || fail 'hidden saved network forget did not complete'
release
grep -Fq "connection delete uuid $saved_hidden_uuid" "$TMP/calls" ||
  fail 'the hidden network was not forgotten by UUID'
[[ ! -e $hidden_ui_profile ]] || fail 'a forgotten profile would still reach the installed system'
grep -Fq 'will not follow you to the new system' "$TMP/saved-forget.out" ||
  fail 'the forget screen hid the installed-system effect'

# Scanned WPA3 and Enhanced Open networks follow the right prompt path.
wpa3_uuid=${wpa3_profile##*/aurade-}
wpa3_uuid=${wpa3_uuid%.nmconnection}
owe_uuid=${owe_profile##*/aurade-}
owe_uuid=${owe_uuid%.nmconnection}
aurade_wifi_forget_profile "$wpa3_uuid" || fail 'the old WPA3 test profile could not be cleared'
aurade_wifi_forget_profile "$owe_uuid" || fail 'the old OWE test profile could not be cleared'
WIFI_CURSOR=0
{
  echo down; echo down; echo down; echo enter
  typed tiny
  echo enter; echo c
} >"$TMP/keys"
exec {_TUI_KEYFD}<"$TMP/keys"; export _TUI_KEYFD
run_network >"$TMP/visible-sae.out" || fail 'visible WPA3 did not complete'
release
grep -Fq 'Password for Pure WPA3' "$TMP/visible-sae.out" ||
  fail 'visible WPA3 did not ask for its password'
grep -Fq 'Connected to Pure WPA3.' "$TMP/visible-sae.out" ||
  fail 'visible WPA3 did not join'
WIFI_CURSOR=0
{ echo down; echo down; echo down; echo down; echo enter; echo c; } >"$TMP/keys"
exec {_TUI_KEYFD}<"$TMP/keys"; export _TUI_KEYFD
run_network >"$TMP/visible-owe.out" || fail 'visible Enhanced Open did not complete'
release
grep -Fq 'Connected to Cafe OWE.' "$TMP/visible-owe.out" ||
  fail 'visible Enhanced Open did not join'
! grep -Fq 'Password for Cafe OWE' "$TMP/visible-owe.out" ||
  fail 'Enhanced Open asked for a password'
WIFI_CURSOR=0
{ echo down; echo down; echo down; echo down; echo down; echo enter; echo c; } >"$TMP/keys"
exec {_TUI_KEYFD}<"$TMP/keys"; export _TUI_KEYFD
run_network >"$TMP/enterprise.out" || fail 'enterprise Wi-Fi trapped the user'
release
grep -Fq 'work or school account setup' "$TMP/enterprise.out" ||
  fail 'enterprise Wi-Fi still shows a password prompt'

# Many networks stay paged on a short console. Untrusted names cannot repaint it.
AURADE_WIFI_SSIDS=()
AURADE_WIFI_SIGNALS=()
AURADE_WIFI_SECURITY=()
AURADE_WIFI_AUTH=()
AURADE_WIFI_OPEN=()
AURADE_WIFI_ACTIVE=()
AURADE_WIFI_SAVED=()
for (( i = 0; i < 14; i++ )); do
  AURADE_WIFI_SSIDS[i]="Network $i"
  AURADE_WIFI_SIGNALS[i]=$(( 90 - i ))
  AURADE_WIFI_SECURITY[i]=WPA2
  AURADE_WIFI_AUTH[i]=wpa-psk
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
