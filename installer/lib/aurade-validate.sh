# shellcheck shell=bash
# Shared input validation for the AuraDE installer front ends.
#
# These rules live in their own sourceable file for one reason: they depend on
# data that only exists on a live installation image (zoneinfo, i18n locales,
# console keymaps). Keeping them here lets the test suite point the lookup
# roots at fixtures and assert real accept/reject behaviour on any machine,
# instead of grepping the front end for source text that may not even run.
#
# Every function is side-effect free and returns 0 for accept, 1 for reject.

AURADE_ZONEINFO_DIR=${AURADE_ZONEINFO_DIR:-/usr/share/zoneinfo}
AURADE_LOCALE_DIR=${AURADE_LOCALE_DIR:-/usr/share/i18n/locales}
AURADE_KEYMAP_DIR=${AURADE_KEYMAP_DIR:-/usr/share/kbd/keymaps}

# Terminal transitions can leave CR/LF delimiters in a line read after a
# long package-acquisition phase. Normalize only those line delimiters; the
# destructive confirmation caller still performs an exact token comparison,
# so other control bytes remain a refusal.
aurade_normalize_confirmation() {
  local value=$1
  value=${value//$'\r'/}
  value=${value//$'\n'/}
  printf '%s' "$value"
}

# A timezone must name an installed zone file. The excluded names are the
# metadata files tzdata ships alongside the zones; they are readable but are
# not valid values for timedatectl/localtime.
aurade_valid_timezone() {
  local timezone=$1
  [[ -n $timezone ]] || return 1
  [[ $timezone =~ ^[A-Za-z0-9_+.-]+(/[A-Za-z0-9_+.-]+)*$ ]] || return 1
  [[ $timezone != *..* ]] || return 1
  [[ $timezone != *.tab ]] || return 1
  case $timezone in
    iso3166.tab|zone.tab|zone1970.tab|leapseconds|leap-seconds.list|tzdata.zi)
      return 1
      ;;
  esac
  [[ -f "$AURADE_ZONEINFO_DIR/$timezone" ]] || return 1
  return 0
}

# C, POSIX and C.UTF-8 are always available from glibc itself and have no
# entry under the i18n locale source directory.
aurade_valid_locale() {
  local locale=$1 locale_name
  [[ -n $locale ]] || return 1
  [[ $locale =~ ^[A-Za-z0-9_.@-]+$ ]] || return 1
  case $locale in
    C|POSIX|C.UTF-8) return 0 ;;
  esac
  locale_name=${locale%%[@.]*}
  [[ -n $locale_name ]] || return 1
  [[ -f "$AURADE_LOCALE_DIR/$locale_name" ]] || return 1
  return 0
}

# Console keymaps are stored in per-layout subdirectories with several
# possible extensions, so this is a search rather than a direct stat.
aurade_valid_keymap() {
  local keymap=$1
  [[ -n $keymap ]] || return 1
  [[ $keymap =~ ^[A-Za-z0-9_.@+-]+$ ]] || return 1
  [[ -d $AURADE_KEYMAP_DIR ]] || return 1
  find "$AURADE_KEYMAP_DIR" -type f \
    \( -name "$keymap.map.gz" -o -name "$keymap.map" -o -name "$keymap.kmap.gz" \) \
    -print -quit 2>/dev/null | grep -q .
}

aurade_valid_username() {
  local username=$1
  [[ $username =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || return 1
  # Names the installed base system already owns; useradd would fail late,
  # after the disk has been erased.
  case $username in
    root|bin|daemon|mail|ftp|http|nobody|dbus|systemd-*|polkitd|greeter) return 1 ;;
  esac
  return 0
}

# RFC 1123 host label rules: letters, digits and inner hyphens only.
aurade_valid_hostname() {
  local hostname=$1
  [[ -n $hostname ]] || return 1
  (( ${#hostname} <= 63 )) || return 1
  [[ $hostname =~ ^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?$ ]] || return 1
  return 0
}

aurade_valid_arch_snapshot() {
  local snapshot=$1 normalized
  [[ $snapshot =~ ^20[0-9]{2}/(0[1-9]|1[0-2])/(0[1-9]|[12][0-9]|3[01])$ ]] || return 1
  normalized=$(date -u -d "${snapshot//\//-}" +%Y/%m/%d 2>/dev/null || true)
  [[ $normalized == "$snapshot" ]]
}

# Compare the disk selected before the prompts with the disk still present at
# the destructive confirmation gate. Model/transport/size are always required;
# a serial or WWN, when the device exposes one, is an additional stable match.
# This keeps ordinary virtual disks usable while refusing a changed identity
# between the dry run and erase confirmation.
aurade_target_identity_matches() {
  local expected_path=$1 expected_size=$2 expected_model=$3 expected_transport=$4
  local expected_serial=$5 expected_wwn=$6 current_path=$7 current_size=$8
  local current_model=$9 current_transport=${10} current_serial=${11} current_wwn=${12}
  [[ $expected_path == "$current_path" &&
     $expected_size == "$current_size" &&
     $expected_model == "$current_model" &&
     $expected_transport == "$current_transport" ]] || return 1
  [[ -z $expected_serial || $expected_serial == "$current_serial" ]] || return 1
  [[ -z $expected_wwn || $expected_wwn == "$current_wwn" ]] || return 1
  return 0
}
