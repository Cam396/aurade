#!/usr/bin/env bash
# The initramfs hook, on a machine made of files: which photographs and which
# drawn sizes it puts in the image, and what it says about the keyboard.
set -Eeuo pipefail
trap 'printf "%s: line %s gave up: %s\n" "${0##*/}" "$LINENO" "$BASH_COMMAND" >&2' ERR

HERE=$(cd -- "$(dirname -- "$0")" && pwd -P)
PACKAGE=$(cd -- "$HERE/.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf -- "$TMP"' EXIT

fail() {
  printf 'hook test: %s\n' "$*" >&2
  exit 1
}

# mkinitcpio's side of the contract, as much of it as the hook uses.
BUILDROOT=$TMP/buildroot
warning() {
  local format=$1
  shift
  # shellcheck disable=SC2059
  printf "$format\n" "$@" >>"$TMP/warnings"
}
add_file() {
  printf '%s -> %s\n' "$1" "$2" >>"$TMP/added"
  # As mkinitcpio does: something already there, followed through a link,
  # that compares equal is left alone.
  if [[ -e $BUILDROOT$2 && -f $BUILDROOT$2 ]] && cmp -s -- "$1" "$BUILDROOT$2"; then
    return 0
  fi
  install -D -m "${3:-0644}" -- "$1" "$BUILDROOT$2"
}
plymouth-set-default-theme() {
  printf '%s\n' "${THEME_NAME:-aurade-boot}"
}

# The theme as the package installs it: the drawn sizes, and a link per slot
# into the wallpapers.
export AURADE_BOOT_THEME=$TMP/theme
mkdir -p "$TMP/wallpapers" "$AURADE_BOOT_THEME"
printf '[Plymouth Theme]\nName=AuraDE\n' >"$AURADE_BOOT_THEME/aurade-boot.plymouth"
for size in s075 s100 s125 s150 s175 s200 s250 s300; do
  mkdir -p "$AURADE_BOOT_THEME/$size"
  printf 'png\n' >"$AURADE_BOOT_THEME/$size/dot.png"
done
for slot in 0 1 2 3 4 5 6 7; do
  printf 'photograph %s\n' "$slot" >"$TMP/wallpapers/w$slot.png"
  # Absolute, the harder case: in the image a link like this still finds the
  # host's file, and an add_file that follows it copies nothing.
  ln -s "$TMP/wallpapers/w$slot.png" "$AURADE_BOOT_THEME/photo-$slot.png"
done

# The rules file, the parts of it the names come from.
export AURADE_BOOT_XKB_RULES=$TMP/base.lst
cat >"$AURADE_BOOT_XKB_RULES" <<'EOF'
! model
  pc105           Generic 105-key PC
! layout
  us              English (US)
  de              German
  ru              Russian
! variant
  dvorak          us: English (Dvorak)
  nodeadkeys      de: German (no dead keys)
EOF
export AURADE_BOOT_VCONSOLE=$TMP/vconsole.conf
export AURADE_BOOT_CMDLINES=$TMP/cmdline
printf 'root=/dev/mapper/aurade-root rw quiet splash\n' >"$TMP/cmdline"

# shellcheck source=../initcpio/install/aurade-boot
. "$PACKAGE/initcpio/install/aurade-boot"

name_for() {
  printf '%b' "$1" >"$AURADE_BOOT_VCONSOLE"
  rm -f "$TMP/warnings"
  aurade_boot_keyboard_name
}

# --- the keyboard -----------------------------------------------------------

[[ -z $(name_for 'KEYMAP=us\n') ]] || fail 'a US keymap is not worth a word'
[[ -z $(name_for 'KEYMAP=us\nXKBLAYOUT=us\nXKBMODEL=pc105+inet\n') ]] || fail 'nor a US layout'
[[ $(name_for 'KEYMAP=de-latin1\nXKBLAYOUT=de\nXKBMODEL=pc105\n') == German ]] || fail 'de'
[[ $(name_for 'KEYMAP=de-latin1\nXKBLAYOUT="de"\nXKBVARIANT=nodeadkeys\n') == 'German (no dead keys)' ]] ||
  fail 'a variant, quoted the way localectl quotes'
[[ $(name_for 'KEYMAP=dvorak\nXKBLAYOUT=us\nXKBVARIANT=dvorak\n') == 'English (Dvorak)' ]] ||
  fail 'a US layout with a variant is worth naming'
[[ $(name_for 'KEYMAP=ru\nXKBLAYOUT=ru,us\n') == Russian ]] || fail 'plymouth starts on the first layout'
[[ $(name_for 'KEYMAP=xx\nXKBLAYOUT=xx\n') == xx ]] || fail 'a layout the rules do not know keeps its code'

# A console keymap with no layout beside it: through the console when the
# command line says so, and a warning at build time when it does not, because
# that is a passphrase read on a US layout.
printf 'quiet splash plymouth.use-legacy-input\n' >"$TMP/cmdline"
[[ $(name_for 'KEYMAP=pl\n') == pl ]] || fail 'the console keymap, named'
[[ ! -s $TMP/warnings ]] || fail 'a console read through the console is not a mistake'
printf 'quiet splash\n' >"$TMP/cmdline"
name_for 'KEYMAP=pl\n' >"$TMP/name"
[[ $(<"$TMP/name") == pl ]] || fail 'still named'
grep -Fq 'KEYMAP=pl but no XKBLAYOUT' "$TMP/warnings" || fail 'and warned about'
AURADE_BOOT_LEGACY_INPUT=1 name_for 'KEYMAP=pl\n' >/dev/null
[[ ! -s $TMP/warnings ]] || fail 'the installer saying so counts, before the entry exists'

# --- the sizes --------------------------------------------------------------

export AURADE_BOOT_DRM=$TMP/drm
screen() {
  mkdir -p "$AURADE_BOOT_DRM/$1"
  printf '%s\n' "$2" >"$AURADE_BOOT_DRM/$1/status"
  printf '%s\n' "${3:-}" >"$AURADE_BOOT_DRM/$1/modes"
}
kept() {
  rm -rf -- "${BUILDROOT:?}"
  mkdir -p "$BUILDROOT$AURADE_BOOT_THEME"
  cp -r "$AURADE_BOOT_THEME"/s[0-9]* "$BUILDROOT$AURADE_BOOT_THEME/"
  aurade_boot_keep_sizes "$AURADE_BOOT_THEME"
  (cd "$BUILDROOT$AURADE_BOOT_THEME" && printf '%s ' s[0-9]*)
}

[[ $(kept) == 's075 s100 s125 s150 s175 s200 s250 s300 ' ]] || fail 'no screen to measure keeps everything'
screen card0-eDP-1 connected 2256x1504
screen card0-DP-1 disconnected
[[ $(kept) == 's100 s150 ' ]] || fail "a Surface Laptop panel keeps 1.5x and 1x, not $(kept)"
screen card1-HDMI-A-1 connected 3840x2160
[[ $(kept) == 's100 s150 s200 ' ]] || fail "a 4K monitor beside it adds 2x, not $(kept)"
rm -rf -- "${AURADE_BOOT_DRM:?}"
screen card0-eDP-1 connected 1366x768
[[ $(kept) == 's075 s100 ' ]] || fail "a 768 line panel keeps 0.75x, not $(kept)"

# --- the photographs and the theme file --------------------------------------

rm -rf -- "${BUILDROOT:?}" "$TMP/added"
mkdir -p "$BUILDROOT$AURADE_BOOT_THEME"
# What plymouth's hook leaves: the links, copied as links, pointing nowhere.
cp -P "$AURADE_BOOT_THEME"/photo-*.png "$BUILDROOT$AURADE_BOOT_THEME/"
cp -r "$AURADE_BOOT_THEME"/s[0-9]* "$BUILDROOT$AURADE_BOOT_THEME/"
printf 'KEYMAP=de-latin1\nXKBLAYOUT=de\n' >"$AURADE_BOOT_VCONSOLE"
AURADE_BOOT_PHOTOS=3 build

[[ $(grep -c '/wallpapers/w[0-7].png -> ' "$TMP/added") == 3 ]] || fail 'three photographs, as asked'
real=0
for slot in 0 1 2 3 4 5 6 7; do
  file=$BUILDROOT$AURADE_BOOT_THEME/photo-$slot.png
  if [[ -f $file && ! -L $file ]]; then
    [[ $(<"$file") == "photograph $slot" ]] || fail "slot $slot holds another slot's picture"
    real=$((real + 1))
  fi
done
(( real == 3 )) || fail "three slots are pictures in the image, not $real"
grep -Fxq 'keyboard=German' "$BUILDROOT$AURADE_BOOT_THEME/aurade-boot.plymouth" ||
  fail 'the theme file in the image carries the layout'
grep -Fxq '[script-env-vars]' "$BUILDROOT$AURADE_BOOT_THEME/aurade-boot.plymouth" ||
  fail 'as a script variable'
grep -Fq 'keyboard=' "$AURADE_BOOT_THEME/aurade-boot.plymouth" &&
  fail 'and leaves the installed theme file alone'

# Another theme chosen: the hook adds nothing.
rm -f "$TMP/added"
THEME_NAME=bgrt build
[[ ! -e $TMP/added ]] || fail 'a machine on another theme gets nothing from this hook'

echo 'aurade-boot hook test: PASS'
