#!/usr/bin/env bash
# The accessibility choices, and the one property that makes them worth having.
#
# A screen reader turned on to get through an install, on a machine that
# reboots into a desktop that does not speak, has not helped anybody. It has
# moved the wall one step further along. So the thing being tested here is not
# that the controls exist, it is that what they collect reaches the engine and
# that the engine writes it into the target.
#
# The other half is the one that is easy to forget: an install where nobody
# touched any of this has to be byte for byte the install it was before. A
# feature that quietly changes every install is not an option, it is a
# behaviour change wearing an option's clothes.
set -Eeuo pipefail
trap 'case $- in *e*) printf "%s: line %s gave up: %s\n" "${0##*/}" "$LINENO" "$BASH_COMMAND" >&2 ;; esac' ERR

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)

# The frame grows with the terminal, so the width is pinned here the way the
# height already is. Without it a screen rendered on a build machine with a
# wide terminal and the same screen rendered in CI are different screens, and
# every column measurement below is measuring the margin.
export AURADE_TUI_COLUMNS=68

TUI=$ROOT/installer/bin/aurade-installer-tui
ENGINE=$ROOT/installer/bin/aurade-install
failures=0
fail() { printf 'test-accessibility: %s\n' "$*" >&2; failures=$(( failures + 1 )); }

# The front end's state, exercised by sourcing the shared library the way the
# graphical bridge does rather than by driving a screen.
probe() {
  # `eval` rather than "$@": the point is to run in the shell that sourced the
  # library. Anything that spawns a second shell loses the functions being
  # tested and then reports them missing, which is a test of the harness.
  env AURADE_INSTALLER_TUI_LIB=1 bash -c '
    set -Eeuo pipefail
    . "$1"
    shift
    eval "$*"
  ' _ "$TUI" "$@"
}

# --- a default install is unchanged ----------------------------------------
out=$(probe 'access_engine_args; printf "%s" "${#ACCESS_ARGS[@]}"' 2>/dev/null || true)
[[ $out == 0 ]] ||
  fail "a default install would pass $out accessibility arguments, and should pass none"

# --- what is set travels ---------------------------------------------------
out=$(probe '
  access_set screen_reader yes
  access_set text_scale 125
  access_engine_args
  printf "%s\n" "${ACCESS_ARGS[@]}"' 2>/dev/null || true)
grep -Fqx -- '--screen-reader' <<<"$out" || fail 'a screen reader choice does not reach the engine'
grep -Fqx -- 'yes' <<<"$out" || fail 'the screen reader value does not reach the engine'
grep -Fqx -- '--text-scale' <<<"$out" || fail 'a text scale choice does not reach the engine'
grep -Fqx -- '125' <<<"$out" || fail 'the text scale value does not reach the engine'
# And only what was set. Two choices are four arguments, not twelve.
(( $(wc -l <<<"$out") == 4 )) ||
  fail "two choices produced $(wc -l <<<"$out") arguments, so defaults are being emitted"

# --- a bad value is refused by the front end, not passed on -----------------
for pair in 'text_scale 137' 'contrast lurid' 'screen_reader maybe' 'cursor_size 7'; do
  set -- $pair
  if probe "access_set $1 $2" 2>/dev/null; then
    fail "the front end accepted $1=$2, which the engine would then refuse"
  fi
done

# --- and the engine refuses the same values --------------------------------
#
# Two checks of one rule, on purpose. The front end's is what makes a mistake a
# refusal in the interface; the engine's is what makes it a refusal at all,
# because the engine is reachable without a front end.
for pair in '--text-scale 137' '--contrast lurid' '--screen-reader maybe' '--cursor-size 7'; do
  set -- $pair
  if "$ENGINE" --target /dev/aurade-nonexistent --username a "$1" "$2" --dry-run \
      >/dev/null 2>&1; then
    fail "the engine accepted $1 $2"
  fi
done

# --- every key the front end knows, the engine also knows ------------------
#
# The pair that drifts. The front end holds the list of choices and the engine
# holds the flags, and a key added to one and not the other is a control that
# silently does nothing.
#
# One key on the panel deliberately stops here: a heartbeat has nothing to
# survive the restart into, because the install it reports on is over. That
# exception is a written list rather than an inferred one, so a key that loses
# its flag by accident fails here instead of quietly ceasing to be sent.
keys=$(probe 'printf "%s\n" "${ACCESS_ORDER[@]}"' 2>/dev/null || true)
local_keys=$(probe 'printf "%s\n" "${ACCESS_LOCAL[@]}"' 2>/dev/null || true)
[[ -n $local_keys ]] || fail 'no key is declared front end only'
while IFS= read -r key; do
  [[ -n $key ]] || continue
  flag=$(probe "printf '%s' \"\${ACCESS_FLAGS[$key]:-}\"" 2>/dev/null || true)
  if grep -Fqx -- "$key" <<<"$local_keys"; then
    # A local key with a flag is a control somebody meant to send and did not.
    [[ -z $flag ]] ||
      fail "$key is declared front end only and yet carries the engine flag $flag"
    probe "access_travels $key" 2>/dev/null &&
      fail "$key is in ACCESS_LOCAL and access_travels still says it travels"
    continue
  fi
  [[ -n $flag ]] || { fail "$key has no engine flag"; continue; }
  probe "access_travels $key" 2>/dev/null ||
    fail "$key carries the flag $flag and access_travels says it does not travel"
  grep -Fq -- "    $flag)" "$ENGINE" ||
    fail "the front end offers $key as $flag and the engine does not accept it"
done <<<"$keys"
# Every front-end-only key is a key the panel actually offers.
while IFS= read -r key; do
  [[ -n $key ]] || continue
  grep -Fqx -- "$key" <<<"$keys" ||
    fail "$key is declared front end only and is not on the panel at all"
done <<<"$local_keys"

# A setting that stops at the front end must not reach the engine even when it
# is turned on, which is the half of the contract a missing flag alone does not
# prove: `access_engine_args` could just as easily send an empty flag.
#
# The status is checked as well as the output. A probe that dies partway
# through prints nothing, and nothing is also what a correctly skipped setting
# looks like, so without this an `access_engine_args` that crashes on the very
# key being tested would read as one that quietly declined to send it.
build_args() {
  local out status
  out=$(probe "$1; access_engine_args; printf '%s ' \"\${ACCESS_ARGS[@]+\"\${ACCESS_ARGS[@]}\"}\"" 2>&1)
  status=$?
  (( status == 0 )) ||
    fail "building the engine arguments after '$1' failed with $status: $out"
  printf '%s' "$out"
}
args=$(build_args 'ACCESS[heartbeat]=yes')
case $args in
  *heartbeat*) fail "turning the heartbeat on put '$args' on the engine command line" ;;
esac
[[ -z ${args// /} ]] ||
  fail "turning only the heartbeat on changed the engine command line to '$args'"
# And a setting that does travel still does, so the check above is not passing
# because nothing reaches the engine any more.
args=$(build_args 'ACCESS[contrast]=high')
[[ $args == '--contrast high '* ]] ||
  fail "turning contrast up sent '$args' rather than --contrast high"
# Both at once: the one that travels goes and the one that does not stays.
args=$(build_args 'ACCESS[contrast]=high; ACCESS[heartbeat]=yes')
[[ $args == '--contrast high '* ]] ||
  fail "with the heartbeat on as well, contrast sent '$args'"
case $args in
  *heartbeat*) fail "the heartbeat rode along with contrast as '$args'" ;;
esac

# --- the key that reaches it ------------------------------------------------
#
# F1 rather than a letter, because every other screen consumes printable keys
# as text: a letter is a letter in a hostname field and part of the token at
# the erase gate. And not a chord, because somebody navigating with one switch
# cannot press two keys at once.
#
# The decoder folds every unrecognised escape sequence into `esc`, so before
# this was decoded, pressing F1 did not do nothing. It went back a screen.
got=$(probe 'tui_decode_key "$(printf "\033OP")"' 2>/dev/null || true)
[[ $got == f1 ]] || fail "xterm's F1 decodes as '$got', not f1"
got=$(probe 'tui_decode_key "$(printf "\033[[A")"' 2>/dev/null || true)
[[ $got == f1 ]] || fail "the linux console's F1 decodes as '$got', not f1"
got=$(probe 'tui_decode_key "$(printf "\033[11~")"' 2>/dev/null || true)
[[ $got == f1 ]] || fail "the numbered F1 decodes as '$got', not f1"

# Long copy is wrapped to the frame, so a sentence is not necessarily on one
# line. Flatten before matching, or the assertion is really about where the
# wrap landed.
flatten() { tr '\n' ' ' | tr -s ' '; }

# It is written down where somebody starts.
welcome=$(env AURADE_TUI_HEIGHT=34 AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii \
  "$TUI" --render welcome 2>/dev/null)
grep -Fq 'f1  accessibility' <<<"$welcome" ||
  fail 'the welcome screen does not say the accessibility key exists'

# And the screen itself lists every choice it is supposed to.
screen=$(env AURADE_TUI_PLAIN=1 AURADE_TUI_HEIGHT=34 "$TUI" --render access 2>/dev/null)
for label in 'Screen reader' 'Braille display' 'Contrast' 'Text size' \
             'Reduce motion' 'Pointer size'; do
  grep -Fq "$label" <<<"$screen" || fail "the accessibility screen never offers '$label'"
done
# It has to say what it is for. A settings screen that does not explain that
# these survive the restart is a settings screen nobody trusts with anything.
flatten <<<"$screen" | grep -Fq 'carried into the installed system' ||
  fail 'the accessibility screen does not say the choices survive the reboot'

# --- the graphical front end reaches the same state -------------------------
#
# Not a second copy of the choices. The bridge sources the text installer, so
# both front ends are reading and writing one set of variables, and this is
# what proves it rather than assuming it: set a value through the bridge, read
# it back through the bridge, and see the engine argument it produces.
BRIDGE=$ROOT/installer/bin/aurade-installer-gui-bridge
bridge_out=$(printf '%s\n' 'access-set contrast=high' 'access' 'quit' |
  env AURADE_TUI_KEYS= "$BRIDGE" --plan-only 2>/dev/null || true)
grep -Fq '"contrast":{"value":"high"' <<<"$bridge_out" ||
  fail 'a choice set through the bridge does not read back through the bridge'
grep -Fq '"label":"Screen reader"' <<<"$bridge_out" ||
  fail 'the bridge does not offer the choices in words a chooser can read'

# A refusal in the interface rather than at install time.
bad=$(printf '%s\n' 'access-set contrast=lurid' 'quit' |
  env AURADE_TUI_KEYS= "$BRIDGE" --plan-only 2>/dev/null || true)
grep -Fq '"ok":false' <<<"$bad" ||
  fail 'the bridge accepted a value the engine would refuse'

# And it works in plan-only mode, because somebody checking a plan still has to
# be able to read the screen they are checking it on.
grep -Fq '"ok":true' <<<"$bridge_out" ||
  fail 'the accessibility commands are unavailable in plan-only mode'

# --- the boot menu's choice has to travel too --------------------------------
#
# The gap this closes: the speech entry starts espeakup itself, so somebody
# boots it, installs with a talking installer, and reboots into silence. The
# reader was started by a shell script and never became an answer. Presetting
# it makes the boot menu's choice an answer like any other.
out=$(env AURADE_ACCESS_SCREEN_READER=yes AURADE_INSTALLER_TUI_LIB=1 bash -c '
  set -Eeuo pipefail
  . "$1"
  access_engine_args
  printf "%s\n" "${ACCESS_ARGS[@]}"' _ "$TUI" 2>/dev/null || true)
grep -Fqx -- '--screen-reader' <<<"$out" ||
  fail 'a choice preset by the boot menu never reaches the engine'

# And the entry that needs it actually sets it.
grep -Fq 'AURADE_ACCESS_SCREEN_READER=yes' \
  "$ROOT/installer/archiso/airootfs/usr/local/sbin/aurade-installer-autostart" ||
  fail 'the speech boot entry does not record the choice it just made'

# A typo in a boot entry must not stop an install.
out=$(env AURADE_ACCESS_CONTRAST=lurid AURADE_INSTALLER_TUI_LIB=1 bash -c '
  set -Eeuo pipefail
  . "$1"
  printf "%s" "${ACCESS[contrast]}"' _ "$TUI" 2>/dev/null || true)
[[ $out == normal ]] ||
  fail "an unusable preset left contrast as '$out' instead of ignoring it"

# --- and the installer obeys what it collects --------------------------------
#
# Recording without obeying is the failure that makes a settings screen
# untrustworthy: nothing appears to happen, so people press it twice.
before=$(env AURADE_TUI_HEIGHT=40 AURADE_TIP_RARITY=0 "$TUI" --render progress \
  2>/dev/null | grep -cE '^\|  [:.=*#+-]{20,}' || true)
after=$(env AURADE_ACCESS_REDUCE_MOTION=yes AURADE_TUI_HEIGHT=40 AURADE_TIP_RARITY=0 \
  "$TUI" --render progress 2>/dev/null | grep -cE '^\|  [:.=*#+-]{20,}' || true)
(( before > 0 )) || fail 'the progress screen draws no aurora to begin with'
(( after == 0 )) || fail "reduce motion left $after rows of aurora moving"

# --- the erase gate: fairer, and not one bit easier -------------------------
#
# Typing `ERASE:/dev/nvme0n1` exactly is a real motor and cognitive load and it
# is the one thing in this product that must not be weakened. Everything here
# makes it possible to *check* what was typed. Nothing makes the comparison
# more forgiving.

# Spelled back with the punctuation named, because `/dev/nvme0n1` heard at
# speaking speed is a run of sounds rather than a string.
out=$(probe 'gate_spelling "ERASE:/dev/sda"' 2>/dev/null || true)
[[ $out == 'E R A S E colon slash d e v slash s d a' ]] ||
  fail "the gate spells its token as '$out'"

# On request, not by default: four lines of noise to somebody who can see the
# field, and the only way to check it for somebody who cannot.
plain_gate=$(env AURADE_TUI_HEIGHT=40 AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii \
  "$TUI" --render gate 2>/dev/null)
! grep -Fq 'You typed:' <<<"$plain_gate" ||
  fail 'the gate spells the token back without being asked'
spelled=$(env GATE_SPELL=1 AURADE_TUI_HEIGHT=40 AURADE_TUI_COLOR=none \
  AURADE_TUI_FRAME=ascii "$TUI" --render gate 2>/dev/null)
grep -Fq 'You typed:' <<<"$spelled" ||
  fail 'the gate cannot be asked to spell the token back'
grep -Fq 'f2  spell it back' <<<"$plain_gate" ||
  fail 'the gate does not say the spelling key exists'

# F2 has to decode, or the key is another way to trip the escape fallback.
for seq in 'OQ' '[[B' '[12~'; do
  got=$(probe "tui_decode_key \"\$(printf '\033%s' '$seq')\"" 2>/dev/null || true)
  [[ $got == f2 ]] || fail "F2 as ESC$seq decodes as '$got', not f2"
done

# And nothing is normalised. The token is compared whole, with no trimming and
# no case folding, in the front end and again in the engine.
grep -Fq '[[ $typed == "$token" ]]' "$TUI" ||
  fail 'the gate no longer compares the typed token whole'
! grep -qE 'typed=\$\{typed(,,|\^\^)\}|typed=\$\(.*tr ' "$TUI" ||
  fail 'the gate folds or rewrites what was typed before comparing it'

# --- sound, and where it must not appear ------------------------------------
#
# One bell for finished, three for stopped. A pattern rather than a pitch,
# because a terminal bell has one pitch and two things somebody can tell apart
# across a room without looking is the whole requirement.
#
# The important half is the second one: a bell written to stdout would land in
# the middle of a rendered frame and every width measurement in the render
# tests would be measuring a control character.
for screen in done failure; do
  out=$(env AURADE_TUI_HEIGHT=40 AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii \
    "$TUI" --render "$screen" 2>/dev/null | tr -d '\n')
  case $out in
    *$'\a'*) fail "the $screen screen writes a bell into its own rendering" ;;
  esac
done

# Both front ends agree on the pattern, or a machine sounds like two products.
grep -Fq 'tui_bell 1' "$TUI" || fail 'the text installer does not ring once when it finishes'
grep -Fq 'tui_bell 3' "$TUI" || fail 'the text installer does not ring three times when it stops'
# Two for still working, which is the only short pattern the other two leave.
grep -Fq 'tui_bell 2' "$TUI" || fail 'the text installer has no heartbeat'
# Off unless somebody asks for it. A sound every thirty seconds is a fault for
# everybody who did not want one.
[[ $(probe 'printf "%s" "${ACCESS_DEFAULT[heartbeat]}"') == no ]] ||
  fail 'the heartbeat is on by default'
# The first ring is a whole interval away. One at the moment you press enter
# has told you nothing you did not just do.
rings=$(probe '
  AURADE_HEARTBEAT_SECONDS=1
  ACCESS[heartbeat]=yes
  count=0
  tui_bell() { count=$(( count + 1 )); }
  EPOCHSECONDS=1000 progress_heartbeat
  EPOCHSECONDS=1000 progress_heartbeat
  printf "%s" "$count"' 2>/dev/null || true)
[[ $rings == 0 ]] || fail "the heartbeat rang $rings times before one interval had passed"
# And it does ring once the interval has passed, then waits for the next.
rings=$(probe '
  AURADE_HEARTBEAT_SECONDS=30
  ACCESS[heartbeat]=yes
  count=0
  tui_bell() { count=$(( count + 1 )); }
  PROGRESS_HEARTBEAT_AT=1000
  EPOCHSECONDS=1029 progress_heartbeat
  EPOCHSECONDS=1030 progress_heartbeat
  EPOCHSECONDS=1031 progress_heartbeat
  printf "%s" "$count"' 2>/dev/null || true)
[[ $rings == 1 ]] || fail "the heartbeat rang $rings times across one interval boundary"
# Silent while it is off, which is the default and therefore the common case.
rings=$(probe '
  AURADE_HEARTBEAT_SECONDS=1
  count=0
  tui_bell() { count=$(( count + 1 )); }
  PROGRESS_HEARTBEAT_AT=1000
  EPOCHSECONDS=2000 progress_heartbeat
  printf "%s" "$count"' 2>/dev/null || true)
[[ $rings == 0 ]] || fail 'the heartbeat rings even when it is turned off'
grep -Fq 'self._sound(1)' "$ROOT/installer/lib/aurade_gui/app.py" ||
  fail 'the graphical installer does not ring once when it finishes'
grep -Fq 'self._sound(3)' "$ROOT/installer/lib/aurade_gui/app.py" ||
  fail 'the graphical installer does not ring three times when it stops'

# --- the faces are on the image, and in the snapshot ------------------------
#
# Both halves matter and they fail differently. A package that is not in the
# pinned Arch snapshot fails the whole install loudly. A font name written for
# a family that is not installed fails silently: it renders in the default
# face, and the person who chose it has no way to know it did not happen.
#
# So the choice only exists because both are in the snapshot, which was checked
# against the archive rather than against today's repositories, and this is
# what stops somebody removing one and leaving the choice behind.
for _face in ttf-atkinson-hyperlegible otf-opendyslexic-nerd; do
  grep -Fxq "$_face" "$ROOT/installer/archiso/packages.x86_64" ||
    fail "$_face is offered as a choice and is not on the image"
done
grep -Fq 'ttf-atkinson-hyperlegible' "$ENGINE" ||
  fail 'choosing Atkinson does not install it onto the target'
grep -Fq 'otf-opendyslexic-nerd' "$ENGINE" ||
  fail 'choosing OpenDyslexic does not install it onto the target'

# The graphical front end resolves the family against what the machine has
# rather than trusting a name, because the Nerd Fonts build does not
# necessarily keep the plain family name.
grep -Fq 'list_families' "$ROOT/installer/lib/aurade_gui/app.py" ||
  fail 'the typeface is applied without checking the family exists'

# --- text size on a console that has no text size ---------------------------
#
# The graphical front end scales by dpi. A virtual console cannot: its text is
# exactly as tall as the font, so the only way to make it larger is to load a
# taller one. Three sizes, matching the three steps, and gated on the console
# that has fonts to load.
grep -Fq 'ter-124n' "$TUI" || fail 'text scale 125 does not load a larger console font'
grep -Fq 'ter-132n' "$TUI" || fail 'text scale 150 does not load a larger console font'
grep -Fq 'command -v setfont' "$TUI" ||
  fail 'the console font is changed without checking setfont exists'
# A taller font means fewer rows, and the frame is measured in rows, so the
# height has to be asked for again rather than remembered from boot.
grep -Fq 'AURADE_TUI_HEIGHT=$(tput lines' "$TUI" ||
  fail 'the frame does not re-measure after the console font changes'

(( failures == 0 )) || exit 1
printf 'installer accessibility test: PASS (%s choices, defaults unchanged, both ends agree)\n' \
  "$(wc -l <<<"$keys")"
