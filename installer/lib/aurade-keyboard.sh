#!/usr/bin/env bash
# The keyboard a console keymap types, in XKB's terms.
#
# The installer asks for a console keymap, because the text installer runs on
# a console and a console is where one can be tried. Everything after the
# console reads keys through XKB instead: the graphical installer, the unlock
# screen, the login screen. A password is only typed the same way in all of
# them when all of them are given the same layout, so there is one conversion
# and every one of them uses this one.
#
# systemd's table first, which is the one `localectl set-keymap` uses. Then
# the few keymaps the installer names in words that the table leaves out, each
# checked against the console keymap it stands for. A matching name is not
# enough, and `cz` is why: the console's is QWERTY and XKB's is QWERTZ, which
# would put Y and Z in each other's places in every password. A keymap neither
# knows has no XKB layout, and callers have to treat that as exactly that.

AURADE_KBD_MODEL_MAP=${AURADE_KBD_MODEL_MAP:-/usr/share/systemd/kbd-model-map}

# The keymap, then layout, model, variant and options, as in systemd's table.
AURADE_KEYMAP_XKB_EXTRA='pl	pl	pc105	-	-
cz	cz	pc105	qwerty	-
colemak	us	pc105	colemak	-'

# Prints layout, model, variant and options, separated by tabs, with "-" for
# none. Fails, printing nothing, for a keymap with no XKB layout.
aurade_keymap_xkb() {
  local keymap=$1 found=''
  [[ -n $keymap ]] || return 1
  if [[ -r $AURADE_KBD_MODEL_MAP ]]; then
    found=$(awk -v k="$keymap" '
      $1 !~ /^#/ && $1 == k { print $2 "\t" $3 "\t" $4 "\t" $5; exit }' "$AURADE_KBD_MODEL_MAP")
  fi
  if [[ -z $found ]]; then
    found=$(awk -F '\t' -v k="$keymap" '
      $1 == k { print $2 "\t" $3 "\t" $4 "\t" $5; exit }' <<<"$AURADE_KEYMAP_XKB_EXTRA")
  fi
  [[ -n $found ]] || return 1
  printf '%s\n' "$found"
}
