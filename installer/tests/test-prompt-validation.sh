#!/usr/bin/env bash
# Behavioural tests for the installer's input validation.
#
# These exist because the previous coverage grepped aurade-installer for
# source text. That style of assertion passed against a keymap check whose
# find(1) group was split across newlines, so it rejected every layout
# including the default and looped forever at the prompt. Source text is not
# behaviour; this file runs the rules.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# Fixture roots so the rules can be exercised on a machine that has no
# tzdata, no i18n sources and no console keymaps installed.
install -d -m 0755 \
  "$TMP/zoneinfo/America" "$TMP/zoneinfo/Europe" \
  "$TMP/locales" \
  "$TMP/keymaps/i386/qwerty" "$TMP/keymaps/i386/azerty"
: >"$TMP/zoneinfo/UTC"
: >"$TMP/zoneinfo/America/Chicago"
: >"$TMP/zoneinfo/Europe/Paris"
: >"$TMP/zoneinfo/zone.tab"
: >"$TMP/zoneinfo/leapseconds"
: >"$TMP/locales/en_US"
: >"$TMP/locales/fr_FR"
: >"$TMP/keymaps/i386/qwerty/us.map.gz"
: >"$TMP/keymaps/i386/qwerty/us-altgr-intl.map.gz"
: >"$TMP/keymaps/i386/azerty/fr.map.gz"

export AURADE_ZONEINFO_DIR="$TMP/zoneinfo"
export AURADE_LOCALE_DIR="$TMP/locales"
export AURADE_KEYMAP_DIR="$TMP/keymaps"

# shellcheck source=../lib/aurade-validate.sh
. "$ROOT/installer/lib/aurade-validate.sh"

failures=0
accept() {
  local fn=$1 value=$2
  if ! "$fn" "$value"; then
    printf 'FAIL: %s should have accepted %q\n' "$fn" "$value" >&2
    failures=$((failures + 1))
  fi
}
reject() {
  local fn=$1 value=$2
  if "$fn" "$value"; then
    printf 'FAIL: %s should have rejected %q\n' "$fn" "$value" >&2
    failures=$((failures + 1))
  fi
}

# The default offered by every prompt must be accepted by its own rule.
# This is the exact regression that hung the installer.
accept aurade_valid_timezone UTC
accept aurade_valid_locale en_US.UTF-8
accept aurade_valid_keymap us
accept aurade_valid_hostname aurade
accept aurade_valid_arch_snapshot 2026/07/12

accept aurade_valid_timezone America/Chicago
accept aurade_valid_timezone Europe/Paris
reject aurade_valid_timezone America/Nowhere
reject aurade_valid_timezone zone.tab
reject aurade_valid_timezone leapseconds
reject aurade_valid_timezone ../../etc/passwd
reject aurade_valid_timezone ''
reject aurade_valid_timezone 'UTC; rm -rf /'

accept aurade_valid_locale fr_FR.UTF-8
accept aurade_valid_locale C
accept aurade_valid_locale C.UTF-8
accept aurade_valid_locale POSIX
reject aurade_valid_locale xx_YY.UTF-8
reject aurade_valid_locale ''
reject aurade_valid_locale '../../etc/passwd'

accept aurade_valid_keymap us-altgr-intl
accept aurade_valid_keymap fr
reject aurade_valid_keymap de
reject aurade_valid_keymap ''
reject aurade_valid_keymap '../../etc/passwd'
reject aurade_valid_keymap 'us; rm -rf /'

accept aurade_valid_username aurade
accept aurade_valid_username a
accept aurade_valid_username _test-user1
reject aurade_valid_username Aurade
reject aurade_valid_username 1abc
reject aurade_valid_username ''
reject aurade_valid_username 'has space'
reject aurade_valid_username root
reject aurade_valid_username nobody
reject aurade_valid_username systemd-network
reject aurade_valid_username "$(printf 'a%.0s' {1..33})"

accept aurade_valid_hostname aurade-laptop
accept aurade_valid_hostname a
accept aurade_valid_hostname host123
reject aurade_valid_hostname -leading
reject aurade_valid_hostname trailing-
reject aurade_valid_hostname 'has space'
reject aurade_valid_hostname 'under_score'
reject aurade_valid_hostname ''
reject aurade_valid_hostname "$(printf 'a%.0s' {1..64})"
reject aurade_valid_arch_snapshot 2026/02/30
reject aurade_valid_arch_snapshot 2026/13/01
reject aurade_valid_arch_snapshot 2026-07-12
reject aurade_valid_arch_snapshot ''

# The destructive confirmation gate must bind to the complete disk identity,
# not merely a reused /dev path. Virtual disks without serial/WWN remain
# usable through the size/model/transport tuple.
if ! aurade_target_identity_matches \
  /dev/vda 16G VirtIO disk '' '' /dev/vda 16G VirtIO disk '' ''; then
  fail 'matching virtual-disk identity was rejected'
fi
if aurade_target_identity_matches \
  /dev/vda 16G VirtIO disk SERIAL-1 WWN-1 /dev/vda 16G VirtIO disk SERIAL-2 WWN-1; then
  fail 'changed serial was accepted at the confirmation gate'
fi
if aurade_target_identity_matches \
  /dev/vda 16G VirtIO disk '' '' /dev/vda 32G VirtIO disk '' ''; then
  fail 'changed disk size was accepted at the confirmation gate'
fi

# A missing keymap directory must reject rather than abort the front end
# under `set -e`, so the prompt can explain itself instead of exiting.
AURADE_KEYMAP_DIR="$TMP/does-not-exist" reject aurade_valid_keymap us

if (( failures )); then
  printf 'installer prompt validation test: FAIL (%d)\n' "$failures" >&2
  exit 1
fi
echo 'installer prompt validation test: PASS'
