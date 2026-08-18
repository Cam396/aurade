#!/usr/bin/env bash
# The other half of the accessibility promise: something on the installed
# system that reads the record back and confirms the settings survived.
set -Eeuo pipefail
trap 'case $- in *e*) printf "%s: line %s gave up: %s\n" "${0##*/}" "$LINENO" "$BASH_COMMAND" >&2 ;; esac' ERR

# shellcheck source=assert.sh
. "$(dirname -- "$0")/assert.sh"

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
CHECK="$ROOT/installer/bin/aurade-first-boot-accessibility"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# A system where every mechanism carries what it was supposed to.
good_system() {
  printf '[Settings]\ngtk-xft-dpi=147456\ngtk-enable-animations=0\ngtk-cursor-theme-size=32\ngtk-font-name=Atkinson Hyperlegible 11\n' >"$TMP/settings.ini"
  printf 'label, entry, textview { line-height: 1.75; letter-spacing: 0.2px; }\n' >"$TMP/gtk.css"
  printf '[org/gnome/desktop/a11y/interface]\nhigh-contrast=true\n' >"$TMP/dconf"
  printf '#!/usr/bin/env bash\nprintf "enabled\\n"\n' >"$TMP/systemctl"
  chmod +x "$TMP/systemctl"
}

# Everything the installer offers, all turned away from its default, so every
# branch below is a branch that ran.
printf 'screen_reader=yes\nbraille=yes\ncontrast=high\ntext_scale=150\nspacing=roomy\ntypeface=atkinson\nreduce_motion=yes\ncursor_size=32\n' >"$TMP/record"

run_check() {
  rm -f "$TMP/checked"
  AURADE_ACCESSIBILITY_RECORD="${1:-$TMP/record}" \
  AURADE_GTK_SETTINGS="$TMP/settings.ini" AURADE_GTK_CSS="$TMP/gtk.css" \
  AURADE_DCONF_FILE="$TMP/dconf" AURADE_ACCESSIBILITY_RESULT="$TMP/checked" \
  AURADE_SYSTEMCTL="$TMP/systemctl" "$CHECK" >"$TMP/out" 2>&1
}

# --- everything carried over ------------------------------------------------
good_system
run_check || { echo 'a system carrying every setting was reported as broken' >&2
               cat "$TMP/out" >&2; exit 1; }
grep -Fq 'all the accessibility settings carried over' "$TMP/checked"
# Silent. A first boot that announces a success nobody doubted is a first boot
# that teaches people to ignore it, and the next thing it says will be the one
# that mattered.
[[ ! -s $TMP/out ]] ||
  { echo "a clean first boot said something: $(cat "$TMP/out")" >&2; exit 1; }

# --- each mechanism, broken on its own --------------------------------------
#
# One at a time, because a check that only notices when everything is missing
# is a check that passes on the machine where one thing is.
break_one() {
  local what=$1 expect=$2
  good_system
  case $what in
    espeakup|brltty) printf '#!/usr/bin/env bash\nprintf "disabled\\n"\nexit 1\n' >"$TMP/systemctl" ;;
    contrast)  printf '[org/gnome/desktop/a11y/interface]\nhigh-contrast=false\n' >"$TMP/dconf" ;;
    scale)     sed -i 's/^gtk-xft-dpi=.*/gtk-xft-dpi=98304/' "$TMP/settings.ini" ;;
    motion)    sed -i '/^gtk-enable-animations=/d' "$TMP/settings.ini" ;;
    cursor)    sed -i 's/^gtk-cursor-theme-size=.*/gtk-cursor-theme-size=24/' "$TMP/settings.ini" ;;
    spacing)   printf '/* nothing */\n' >"$TMP/gtk.css" ;;
    typeface)  sed -i '/^gtk-font-name=/d' "$TMP/settings.ini" ;;
  esac
  if run_check; then
    echo "breaking $what was not noticed" >&2
    cat "$TMP/out" >&2
    exit 1
  fi
  grep -Fq "$expect" "$TMP/out" ||
    { echo "breaking $what said: $(cat "$TMP/out")" >&2; exit 1; }
  # Written down as well as said, because the console scrolls away.
  grep -Fq "$expect" "$TMP/checked"
}

break_one espeakup 'espeakup is not enabled'
break_one contrast 'high contrast was turned on'
break_one scale    'text size was set to 150%'
break_one motion   'reduced motion was turned on'
break_one cursor   'pointer size was set to 32'
break_one spacing  'line spacing was changed'
break_one typeface 'a typeface was chosen'

# The braille case needs its own systemctl, since one stub answers for both.
good_system
printf '#!/usr/bin/env bash\ncase $2 in espeakup.service) printf "enabled\\n" ;; *) printf "disabled\\n"; exit 1 ;; esac\n' >"$TMP/systemctl"
refute run_check
grep -Fq 'brltty is not enabled' "$TMP/out"
refute grep -Fq 'espeakup is not enabled' "$TMP/out"

# --- a default is not something to check ------------------------------------
#
# A setting still at its default carried over by definition, and complaining
# about one would be complaining that nothing happened. This is the case that
# every install with untouched accessibility hits, so it is the one that must
# not produce a false alarm.
good_system
printf '#!/usr/bin/env bash\nprintf "disabled\\n"\nexit 1\n' >"$TMP/systemctl"
printf 'screen_reader=no\nbraille=no\ncontrast=normal\ntext_scale=100\nspacing=normal\ntypeface=system\nreduce_motion=no\ncursor_size=24\n' >"$TMP/defaults"
run_check "$TMP/defaults" ||
  { echo 'an install with nothing changed was reported as broken' >&2
    cat "$TMP/out" >&2; exit 1; }
[[ ! -s $TMP/out ]]

# --- no record at all -------------------------------------------------------
# An install from before this existed. Inventing a complaint about it would be
# this check's first act being a false alarm.
run_check "$TMP/no-such-record" ||
  { echo 'a missing record was treated as a fault' >&2; exit 1; }
grep -Fq 'nothing to confirm' "$TMP/out"

# --- the record is read, never run ------------------------------------------
# It is written by the installer and read by a unit running as root on first
# boot. Sourcing it would make a stray line in it a command.
refute grep -Eq '^\s*(\.|source|eval) ' "$CHECK"
printf 'screen_reader=no\ntouch %s/PWNED\ncontrast=normal\n' "$TMP" >"$TMP/hostile"
good_system
run_check "$TMP/hostile" || true
[[ ! -e $TMP/PWNED ]] || { echo 'the record was executed' >&2; exit 1; }

# --- the unit, read as a unit -----------------------------------------------
#
# Against the file the installed system actually gets, not against the engine's
# source. The first version of this grepped the engine for `SuccessExitStatus=0
# 1` and passed with the setting removed, because the phrase also appeared in
# the comment explaining it three lines above. Grepping a program's source for
# a string is not a test of what the program does.
UNIT="$ROOT/installer/units/aurade-first-boot-accessibility.service"
[[ -r $UNIT ]] || { echo 'there is no first boot unit' >&2; exit 1; }
# Strip the comments first, so nothing below can be satisfied by prose.
grep -v '^[[:space:]]*#' "$UNIT" >"$TMP/unit"

grep -Fqx 'ExecStart=/usr/local/bin/aurade-first-boot-accessibility' "$TMP/unit" ||
  { echo 'the unit does not run the check' >&2; exit 1; }
grep -Fqx 'Type=oneshot' "$TMP/unit"
grep -Fqx 'WantedBy=multi-user.target' "$TMP/unit" ||
  { echo 'the unit is never wanted by anything, so enabling it does nothing' >&2; exit 1; }
# Once, and these two are what make it once: the record it reads and the
# result it writes.
grep -Fqx 'ConditionPathExists=/etc/aurade-install/accessibility' "$TMP/unit" ||
  { echo 'the unit runs on installs that have no record to check' >&2; exit 1; }
grep -Fqx 'ConditionPathExists=!/var/lib/aurade/accessibility-checked' "$TMP/unit" ||
  { echo 'there is nothing stopping the unit running on every boot' >&2; exit 1; }
# A fault reported is the check working, so the unit does not also go red. The
# person this protects cannot read `systemctl --failed`.
grep -Fqx 'SuccessExitStatus=0 1' "$TMP/unit" ||
  { echo 'a machine that lost its accessibility settings also boots degraded' >&2; exit 1; }
# The console, because somebody whose screen reader did not start cannot read
# a file and has no desktop yet either.
grep -Fqx 'StandardOutput=journal+console' "$TMP/unit" ||
  { echo 'a fault is written to the journal and never said out loud' >&2; exit 1; }
# What the engine does with the two of them is asserted in
# test-install-dry-run.sh, against the plan it prints rather than against its
# source. Grepping the source cannot tell `install` from `:`, which is how the
# first version of that assertion passed against an engine that had stopped
# installing the unit while still mentioning its path.

echo 'first boot accessibility test: PASS'
