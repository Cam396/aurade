# shellcheck shell=bash
# NetworkManager operations shared by the text and graphical installers.

AURADE_WIFI_NMCLI=${AURADE_NMCLI:-nmcli}
AURADE_WIFI_PROFILE_DIR=${AURADE_NM_PROFILE_DIR:-/etc/NetworkManager/system-connections}
AURADE_WIFI_ERROR=
AURADE_WIFI_FIELDS=()
AURADE_WIFI_SSIDS=()
AURADE_WIFI_SIGNALS=()
AURADE_WIFI_SECURITY=()
AURADE_WIFI_AUTH=()
AURADE_WIFI_OPEN=()
AURADE_WIFI_ACTIVE=()
AURADE_WIFI_SAVED=()
AURADE_WIFI_SAVED_NAMES=()
AURADE_WIFI_SAVED_UUIDS=()
AURADE_WIFI_SAVED_CARRIED=()

aurade_wifi_available() { command -v "$AURADE_WIFI_NMCLI" >/dev/null 2>&1; }

# nmcli escapes both colons and backslashes in terse output.
aurade_wifi_fields() {
  local line=$1 field='' i c
  AURADE_WIFI_FIELDS=()
  for (( i = 0; i < ${#line}; i++ )); do
    c=${line:i:1}
    if [[ $c == "\\" && $(( i + 1 )) -lt ${#line} ]]; then
      i=$(( i + 1 ))
      field+=${line:i:1}
    elif [[ $c == ':' ]]; then
      AURADE_WIFI_FIELDS+=("$field")
      field=''
    else
      field+=$c
    fi
  done
  AURADE_WIFI_FIELDS+=("$field")
}

aurade_wifi_status() {
  local line
  AURADE_WIFI_AVAILABLE=false
  AURADE_WIFI_WIRED=false
  AURADE_WIFI_WIFI=false
  AURADE_WIFI_RADIO=unavailable
  AURADE_WIFI_SSID=
  AURADE_WIFI_CONNECTIVITY=
  aurade_wifi_available || return 0
  AURADE_WIFI_AVAILABLE=true
  while IFS= read -r line; do
    [[ -n $line ]] || continue
    aurade_wifi_fields "$line"
    case ${AURADE_WIFI_FIELDS[1]:-} in
      ethernet) [[ ${AURADE_WIFI_FIELDS[2]:-} != connected ]] || AURADE_WIFI_WIRED=true ;;
      wifi)
        AURADE_WIFI_WIFI=true
        if [[ ${AURADE_WIFI_FIELDS[2]:-} == connected ]]; then
          AURADE_WIFI_SSID=${AURADE_WIFI_FIELDS[3]:-}
        fi ;;
    esac
  done < <("$AURADE_WIFI_NMCLI" -t -f DEVICE,TYPE,STATE,CONNECTION device status 2>/dev/null || true)
  AURADE_WIFI_RADIO=$("$AURADE_WIFI_NMCLI" -t radio wifi 2>/dev/null || printf 'unavailable')
  [[ -n $AURADE_WIFI_RADIO ]] || AURADE_WIFI_RADIO=unavailable
  AURADE_WIFI_CONNECTIVITY=$("$AURADE_WIFI_NMCLI" -t -f CONNECTIVITY general status 2>/dev/null | head -1 || true)
}

aurade_wifi_saved() {
  local want=$1 line
  while IFS= read -r line; do
    [[ -n $line ]] || continue
    aurade_wifi_fields "$line"
    case ${AURADE_WIFI_FIELDS[1]:-} in 802-11-wireless|wifi) ;; *) continue ;; esac
    [[ ${AURADE_WIFI_FIELDS[0]:-} != "$want" ]] || return 0
  done < <("$AURADE_WIFI_NMCLI" -t -f NAME,TYPE connection show 2>/dev/null || true)
  return 1
}

aurade_wifi_saved_profiles() {
  local listing line name uuid type profile index
  AURADE_WIFI_SAVED_NAMES=()
  AURADE_WIFI_SAVED_UUIDS=()
  AURADE_WIFI_SAVED_CARRIED=()
  AURADE_WIFI_ERROR=
  if ! aurade_wifi_available; then
    AURADE_WIFI_ERROR='NetworkManager is not on this image'
    return 1
  fi
  if ! listing=$("$AURADE_WIFI_NMCLI" -t -f NAME,UUID,TYPE connection show 2>/dev/null); then
    AURADE_WIFI_ERROR='Saved networks could not be listed.'
    return 1
  fi
  while IFS= read -r line; do
    [[ -n $line ]] || continue
    aurade_wifi_fields "$line"
    name=${AURADE_WIFI_FIELDS[0]:-}
    uuid=${AURADE_WIFI_FIELDS[1]:-}
    type=${AURADE_WIFI_FIELDS[2]:-}
    [[ $type == wifi || $type == 802-11-wireless ]] || continue
    [[ $uuid =~ ^[[:xdigit:]]{8}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{12}$ ]] || continue
    index=${#AURADE_WIFI_SAVED_NAMES[@]}
    AURADE_WIFI_SAVED_NAMES[index]=$name
    AURADE_WIFI_SAVED_UUIDS[index]=$uuid
    AURADE_WIFI_SAVED_CARRIED[index]=false
    profile="$AURADE_WIFI_PROFILE_DIR/aurade-${uuid,,}.nmconnection"
    [[ ! -f $profile || -L $profile ]] || AURADE_WIFI_SAVED_CARRIED[index]=true
  done <<<"$listing"
  return 0
}

aurade_wifi_activate_profile() {
  local uuid=$1 output
  AURADE_WIFI_ERROR=
  if [[ ! $uuid =~ ^[[:xdigit:]]{8}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{12}$ ]]; then
    AURADE_WIFI_ERROR='That saved network is no longer available.'
    return 1
  fi
  if output=$("$AURADE_WIFI_NMCLI" connection up uuid "$uuid" 2>&1); then
    return 0
  fi
  AURADE_WIFI_ERROR=$(aurade_wifi_reason "$output" '')
  return 1
}

aurade_wifi_forget_profile() {
  local uuid=$1 profile
  AURADE_WIFI_ERROR=
  if [[ ! $uuid =~ ^[[:xdigit:]]{8}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{12}$ ]]; then
    AURADE_WIFI_ERROR='That saved network is no longer available.'
    return 1
  fi
  if ! "$AURADE_WIFI_NMCLI" connection delete uuid "$uuid" >/dev/null 2>&1; then
    AURADE_WIFI_ERROR='Could not forget that network.'
    return 1
  fi
  profile="$AURADE_WIFI_PROFILE_DIR/aurade-${uuid,,}.nmconnection"
  if [[ -f $profile && ! -L $profile ]] && ! rm -f -- "$profile"; then
    AURADE_WIFI_ERROR='The network was removed, but its local profile could not be cleared.'
    return 1
  fi
  return 0
}

aurade_wifi_classify() {
  local security=${1^^}
  case $security in
    ''|--) AURADE_WIFI_KIND=open ;;
    *802.1X*|*EAP*|*ENTERPRISE*) AURADE_WIFI_KIND=enterprise ;;
    *WEP*) AURADE_WIFI_KIND=legacy ;;
    *OWE*) AURADE_WIFI_KIND=owe ;;
    *WPA3*)
      if [[ $security == *WPA1* || $security == *WPA2* ]]; then
        AURADE_WIFI_KIND=wpa-psk
      else
        AURADE_WIFI_KIND=sae
      fi ;;
    *WPA*) AURADE_WIFI_KIND=wpa-psk ;;
    *) AURADE_WIFI_KIND=unknown ;;
  esac
}

aurade_wifi_scan() {
  local listing line ssid signal security active index found
  AURADE_WIFI_SSIDS=()
  AURADE_WIFI_SIGNALS=()
  AURADE_WIFI_SECURITY=()
  AURADE_WIFI_AUTH=()
  AURADE_WIFI_OPEN=()
  AURADE_WIFI_ACTIVE=()
  AURADE_WIFI_SAVED=()
  if ! aurade_wifi_available; then
    AURADE_WIFI_ERROR='NetworkManager is not on this image'
    return 1
  fi
  "$AURADE_WIFI_NMCLI" device wifi rescan >/dev/null 2>&1 || true
  if ! listing=$("$AURADE_WIFI_NMCLI" -t -f SSID,SIGNAL,SECURITY,IN-USE device wifi list 2>/dev/null); then
    AURADE_WIFI_ERROR='Wi-Fi could not be scanned. Turn it on or connect a cable.'
    return 1
  fi
  while IFS= read -r line; do
    [[ -n $line ]] || continue
    aurade_wifi_fields "$line"
    ssid=${AURADE_WIFI_FIELDS[0]:-}
    [[ -n $ssid ]] || continue
    signal=${AURADE_WIFI_FIELDS[1]:-0}
    [[ $signal =~ ^[0-9]{1,3}$ ]] || signal=0
    signal=$(( 10#$signal ))
    (( signal <= 100 )) || signal=100
    security=${AURADE_WIFI_FIELDS[2]:-}
    active=${AURADE_WIFI_FIELDS[3]:-no}
    found=-1
    for index in "${!AURADE_WIFI_SSIDS[@]}"; do
      if [[ ${AURADE_WIFI_SSIDS[index]} == "$ssid" ]]; then
        found=$index
        break
      fi
    done
    if (( found >= 0 )); then
      if [[ $active == yes || $active == '*' ]]; then
        AURADE_WIFI_ACTIVE[found]=true
      fi
      if (( signal <= AURADE_WIFI_SIGNALS[found] )); then
        continue
      fi
    fi
    if (( found < 0 )); then
      found=${#AURADE_WIFI_SSIDS[@]}
    fi
    AURADE_WIFI_SSIDS[found]=$ssid
    AURADE_WIFI_SIGNALS[found]=$signal
    AURADE_WIFI_SECURITY[found]=$security
    aurade_wifi_classify "$security"
    AURADE_WIFI_AUTH[found]=$AURADE_WIFI_KIND
    AURADE_WIFI_OPEN[found]=false
    [[ -n $security && $security != -- ]] || AURADE_WIFI_OPEN[found]=true
    AURADE_WIFI_ACTIVE[found]=${AURADE_WIFI_ACTIVE[found]:-false}
    [[ $active != yes && $active != '*' ]] || AURADE_WIFI_ACTIVE[found]=true
    AURADE_WIFI_SAVED[found]=false
    aurade_wifi_saved "$ssid" && AURADE_WIFI_SAVED[found]=true
  done <<<"$listing"
  AURADE_WIFI_ERROR=
  return 0
}

aurade_wifi_reason() {
  local message=${1,,} psk=$2
  case $message in
    *'secrets were required'*|*'no secrets'*|*'802.1x supplicant'*)
      if [[ -n $psk ]]; then
        printf '%s' 'That password was not accepted. Check it and try again.'
      else
        printf '%s' 'This network needs a password.'
      fi ;;
    *timeout*|*'timed out'*)
      printf '%s' 'The network did not answer in time. Move closer to the router, or try again.' ;;
    *'not authorized'*|*'not permitted'*)
      printf '%s' 'This session is not allowed to change network settings.' ;;
    *'no network with ssid'*|*'not found'*)
      printf '%s' 'That network is no longer in range.' ;;
    *)
      printf '%s' 'Could not join that network. Check the password, or pick another network.' ;;
  esac
}

# A password goes into a mode-0600 NetworkManager keyfile, never into argv.
aurade_wifi_connect() {
  local ssid=$1 psk=$2 auth=${3:-} hidden=${4:-false} uuid profile output index
  local LC_ALL=C
  AURADE_WIFI_ERROR=
  if ! aurade_wifi_available; then
    AURADE_WIFI_ERROR='NetworkManager is not on this image'
    return 1
  fi
  if [[ -z $ssid || $ssid == *[[:cntrl:]]* ]]; then
    AURADE_WIFI_ERROR='Choose a network first.'
    return 1
  fi
  if (( ${#ssid} > 32 )); then
    AURADE_WIFI_ERROR='That network name is too long.'
    return 1
  fi
  if [[ $psk == *[[:cntrl:]]* ]]; then
    AURADE_WIFI_ERROR='That password contains a character Wi-Fi cannot use.'
    return 1
  fi
  if [[ $hidden != true && $hidden != false ]]; then
    AURADE_WIFI_ERROR='Hidden-network setting is invalid.'
    return 1
  fi
  if [[ -z $psk && -z $auth && $hidden == false ]] && aurade_wifi_saved "$ssid"; then
    if output=$("$AURADE_WIFI_NMCLI" connection up id "$ssid" 2>&1); then
      return 0
    fi
    AURADE_WIFI_ERROR=$(aurade_wifi_reason "$output" '')
    return 1
  fi
  if [[ -z $auth ]]; then
    for index in "${!AURADE_WIFI_SSIDS[@]}"; do
      if [[ ${AURADE_WIFI_SSIDS[index]} == "$ssid" ]]; then
        auth=${AURADE_WIFI_AUTH[index]:-}
        break
      fi
    done
  fi
  [[ -n $auth ]] || { if [[ -n $psk ]]; then auth=wpa-psk; else auth=open; fi; }
  case $auth in
    enterprise)
      AURADE_WIFI_ERROR='This network needs work or school account setup. Use another network or a cable.'
      return 1 ;;
    legacy)
      AURADE_WIFI_ERROR='This older Wi-Fi security type is not supported here. Use another network or a cable.'
      return 1 ;;
    unknown)
      AURADE_WIFI_ERROR='This network uses a security type the installer does not recognize.'
      return 1 ;;
    open|owe)
      if [[ -n $psk ]]; then
        AURADE_WIFI_ERROR='This network does not use a password.'
        return 1
      fi ;;
    wpa-psk|sae)
      if [[ -z $psk ]]; then
        AURADE_WIFI_ERROR='This network needs a password.'
        return 1
      fi ;;
    *)
      AURADE_WIFI_ERROR='This network uses a security type the installer does not recognize.'
      return 1 ;;
  esac
  if [[ $auth == wpa-psk ]]; then
    if (( ${#psk} < 8 )); then
      AURADE_WIFI_ERROR='A Wi-Fi password is at least 8 characters.'
      return 1
    fi
    if (( ${#psk} > 63 )) &&
       ! { (( ${#psk} == 64 )) && [[ $psk =~ ^[0-9a-fA-F]+$ ]]; }; then
      AURADE_WIFI_ERROR='A Wi-Fi password is at most 63 characters.'
      return 1
    fi
  fi
  if ! install -d -m 0700 -- "$AURADE_WIFI_PROFILE_DIR" 2>/dev/null; then
    AURADE_WIFI_ERROR='Cannot write a network profile on this system.'
    return 1
  fi
  uuid=$(cat /proc/sys/kernel/random/uuid 2>/dev/null || printf 'aurade-%s' "$$")
  profile="$AURADE_WIFI_PROFILE_DIR/aurade-${uuid}.nmconnection"
  if ! (
    umask 077
    {
      printf '[connection]\nid=%s\nuuid=%s\ntype=wifi\nautoconnect=true\n\n' "$ssid" "$uuid"
      printf '[wifi]\nmode=infrastructure\nssid=%s\n' "$ssid"
      [[ $hidden != true ]] || printf 'hidden=true\n'
      [[ $auth == open ]] || printf 'security=802-11-wireless-security\n'
      printf '\n'
      if [[ $auth != open ]]; then
        printf '[wifi-security]\nkey-mgmt=%s\n' "$auth"
        [[ $auth != wpa-psk && $auth != sae ]] || printf 'psk=%s\n' "$psk"
        printf '\n'
      fi
      printf '[ipv4]\nmethod=auto\n\n[ipv6]\nmethod=auto\n'
    } >"$profile"
  ); then
    rm -f -- "$profile"
    AURADE_WIFI_ERROR='Cannot write a network profile on this system.'
    return 1
  fi
  chmod 600 -- "$profile"
  if ! "$AURADE_WIFI_NMCLI" connection load "$profile" >/dev/null 2>&1; then
    rm -f -- "$profile"
    AURADE_WIFI_ERROR='Could not save that network profile.'
    return 1
  fi
  if ! output=$("$AURADE_WIFI_NMCLI" connection up uuid "$uuid" 2>&1); then
    "$AURADE_WIFI_NMCLI" connection delete uuid "$uuid" >/dev/null 2>&1 || true
    rm -f -- "$profile"
    AURADE_WIFI_ERROR=$(aurade_wifi_reason "$output" "$psk")
    return 1
  fi
  return 0
}

aurade_wifi_forget() {
  local ssid=$1
  AURADE_WIFI_ERROR=
  if ! aurade_wifi_available; then
    AURADE_WIFI_ERROR='NetworkManager is not on this image'
    return 1
  fi
  if ! aurade_wifi_saved "$ssid"; then
    AURADE_WIFI_ERROR='This network is not saved.'
    return 1
  fi
  if "$AURADE_WIFI_NMCLI" connection delete id "$ssid" >/dev/null 2>&1; then
    return 0
  fi
  AURADE_WIFI_ERROR='Could not forget that network.'
  return 1
}

aurade_wifi_radio() {
  local want=$1
  AURADE_WIFI_ERROR=
  if ! aurade_wifi_available; then
    AURADE_WIFI_ERROR='NetworkManager is not on this image'
    return 1
  fi
  case $want in
    on|off) ;;
    *) AURADE_WIFI_ERROR='The radio is either on or off.'; return 1 ;;
  esac
  if "$AURADE_WIFI_NMCLI" radio wifi "$want" >/dev/null 2>&1; then
    return 0
  fi
  AURADE_WIFI_ERROR="Could not turn the Wi-Fi radio $want."
  return 1
}

# Only profiles created by the installer are carried into the installed OS.
aurade_wifi_copy_profiles() {
  local profile dest="$1/etc/NetworkManager/system-connections"
  for profile in "$AURADE_WIFI_PROFILE_DIR"/aurade-*.nmconnection; do
    [[ -f $profile && ! -L $profile ]] || continue
    install -d -m 0700 -- "$dest"
    install -m 0600 -- "$profile" "$dest/${profile##*/}"
  done
}
