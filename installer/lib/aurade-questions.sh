# shellcheck shell=bash
# The installer's question set, as data.
#
# The interactive front end used to carry this list as a sequence of hardcoded
# prompts. That works for exactly one renderer. The moment a second one exists
# it re-implements the same list, and from then on every wording fix, default
# change or new validator is two edits that will eventually be one edit.
#
# So the questions live here and the renderers read them. A renderer decides
# how a question looks; it does not decide what is asked, what the default is,
# or what counts as a valid answer.
#
# Three rules keep the manifest honest, and each has a test:
#
#   Every default must be accepted by its own validator. A default that its own
#   rule rejects is a prompt the user cannot get past by pressing enter.
#
#   Every validator named here must exist in aurade-validate.sh. A typo in a
#   function name is otherwise a silently accepted answer, because calling a
#   missing function in a conditional is just a failure.
#
#   Every `flag` must be one aurade-install actually parses. This is the join
#   between the UI and the engine, and it is the one that rots quietly: the
#   engine grows or drops an option and the front end keeps passing the old
#   one until an install fails at argument parsing, after the user has typed
#   everything in.
#
# Questions the engine cannot consume are not listed. The spec sketched
# `fslayout` and `swap` controls, but aurade-install has no flag for either and
# adding one is a change to the destructive path. A prompt that collects an
# answer nothing acts on is worse than no prompt, so they are out until the
# engine supports them.

# shellcheck disable=SC2034  # read by the front ends that source this file
declare -gA AURADE_Q=()
declare -ga AURADE_QUESTION_IDS=()

# _q ID key value [key value ...]
_q() {
  local id=$1
  shift
  AURADE_QUESTION_IDS+=("$id")
  while (($#)); do
    AURADE_Q["$id.$1"]=$2
    shift 2
  done
}

# Field reference:
#   label     headline shown on the question's screen
#   short     column name on the review screen
#   help      one or two sentences, plain language, no jargon
#   type      disk | text | secret | bool | enum | date
#   default   pre-filled answer; empty means the user must supply one
#   validator function from aurade-validate.sh, or empty for none
#   error     shown when the validator rejects; says what a good answer is
#   advanced  yes -> hidden behind the advanced toggle
#   flag      aurade-install option this answer is passed as
#   secret    yes -> never journalled, never echoed, never written to a log

_q target \
  label 'Where should AuraDE be installed?' \
  short 'Disk' \
  help 'Everything on the disk you choose will be erased. You can still go back or cancel after this step.' \
  type disk \
  default '' \
  validator aurade_valid_target \
  error 'Choose one of the disks listed above.' \
  advanced no \
  flag --target \
  secret no

_q hostname \
  label 'What should this computer be called?' \
  short 'Computer name' \
  help 'Other devices on your network see this name. Letters, digits and hyphens.' \
  type text \
  default aurade \
  validator aurade_valid_hostname \
  error 'Use 1-63 letters, digits or inner hyphens, for example aurade-laptop.' \
  advanced no \
  flag --hostname \
  secret no

_q username \
  label 'Choose your username' \
  short 'Username' \
  help 'This is your account on this computer. It cannot be changed later without recreating the account.' \
  type text \
  default '' \
  validator aurade_valid_username \
  error 'Start with a lowercase letter, then lowercase letters, digits, _ or -. Reserved system names are not available.' \
  advanced no \
  flag --username \
  secret no

_q password \
  label 'Set your password' \
  short 'Password' \
  help 'You will type this to sign in. It is hashed immediately and never written anywhere in readable form.' \
  type secret \
  default '' \
  validator '' \
  error 'The two entries did not match, or the password was empty.' \
  advanced no \
  flag --password-hash-file \
  secret yes

_q encrypt \
  label 'Encrypt this disk?' \
  short 'Encryption' \
  help 'Encryption protects your files if the computer is lost or stolen. You will type a passphrase each time it starts.' \
  type bool \
  default yes \
  validator '' \
  error 'Answer yes or no.' \
  advanced no \
  flag --encrypt \
  secret no

_q luks_passphrase \
  label 'Set your disk encryption passphrase' \
  short 'Disk passphrase' \
  help 'This unlocks the disk at startup. It is separate from your password, and it cannot be recovered if forgotten.' \
  type secret \
  default '' \
  validator '' \
  error 'The two entries did not match, or the passphrase was empty.' \
  advanced no \
  flag --luks-passphrase-file \
  secret yes

_q keymap \
  label 'Keyboard layout' \
  short 'Keyboard' \
  help 'Pick the layout printed on your keyboard. Test it in the field below before continuing.' \
  type enum \
  default us \
  validator aurade_valid_keymap \
  error 'Name an installed keymap, for example us or us-altgr-intl.' \
  advanced no \
  flag --keymap \
  secret no

_q timezone \
  label 'Time zone' \
  short 'Time zone' \
  help 'Used for the clock and for scheduled tasks.' \
  type enum \
  default UTC \
  validator aurade_valid_timezone \
  error 'Name an installed zone, for example America/Chicago or UTC.' \
  advanced no \
  flag --timezone \
  secret no

_q locale \
  label 'Language and region' \
  short 'Language' \
  help 'Sets the language, and how dates, numbers and currency are shown.' \
  type enum \
  default en_US.UTF-8 \
  validator aurade_valid_locale \
  error 'Name an installed locale, for example en_US.UTF-8 or C.UTF-8.' \
  advanced no \
  flag --locale \
  secret no

_q snapshot \
  label 'Arch package snapshot' \
  short 'Package snapshot' \
  help 'AuraDE installs from a pinned day in the Arch Linux Archive, so two installs from the same image match. Change this only if you know why.' \
  type date \
  default '' \
  validator aurade_valid_arch_snapshot \
  error 'Use a real calendar date in YYYY/MM/DD format.' \
  advanced yes \
  flag --arch-snapshot \
  secret no

_q repo_url \
  label 'Package source' \
  short 'Package source' \
  help 'Where the installed system looks for AuraDE updates. The default points at the copy written to the disk.' \
  type text \
  default 'file:///var/cache/aurade/repo' \
  validator '' \
  error 'Enter a package repository URL.' \
  advanced yes \
  flag --repo-url \
  secret no

# The order questions are asked in on the default path. Advanced questions are
# not listed: they are reachable only through the advanced toggle, and they all
# have working defaults, which is what makes them skippable.
# shellcheck disable=SC2034  # read by the front ends that source this file
AURADE_QUESTION_ORDER=(
  locale keymap timezone
  target
  hostname username password
  encrypt luks_passphrase
)

aurade_question_field() {
  local id=$1 field=$2
  printf '%s' "${AURADE_Q[$id.$field]-}"
}

# Where the image records the snapshot it was built against.
AURADE_SNAPSHOT_FILE=${AURADE_SNAPSHOT_FILE:-/etc/aurade-installer/snapshot}

# The default answer, resolved.
#
# Most defaults are literals. The snapshot date cannot be, because the right
# answer is whatever archive day this image was built against, and that is only
# knowable at runtime. Leaving it blank in the manifest and resolving it here
# is what keeps the advanced section genuinely optional: `--arch-snapshot` is
# required by the engine, so a blank default would mean anyone who never opened
# advanced options answered every question and then failed at argument parsing.
aurade_question_default() {
  local id=$1 value
  value=$(aurade_question_field "$id" default)
  if [[ -z $value ]]; then
    case $id in
      snapshot)
        if [[ -r $AURADE_SNAPSHOT_FILE ]]; then
          read -r value <"$AURADE_SNAPSHOT_FILE" || true
        fi
        [[ -n $value ]] || value=$(date -u +%Y/%m/%d)
        ;;
    esac
  fi
  printf '%s' "$value"
}

aurade_question_exists() {
  [[ -n ${AURADE_Q[$1.label]-} ]]
}

aurade_question_is_advanced() {
  [[ $(aurade_question_field "$1" advanced) == yes ]]
}

aurade_question_is_secret() {
  [[ $(aurade_question_field "$1" secret) == yes ]]
}

# Validate an answer using whichever rule the manifest names. Questions with no
# validator accept anything non-empty; questions with one delegate entirely, so
# there is never a second copy of a rule living in a renderer.
aurade_question_validate() {
  local id=$1 answer=$2 validator
  validator=$(aurade_question_field "$id" validator)
  if [[ -z $validator ]]; then
    [[ -n $answer ]]
    return
  fi
  "$validator" "$answer"
}

# A whole-disk block device that is not the medium we booted from. Lives here
# rather than in aurade-validate.sh because it is the one rule that has to look
# at live hardware; the fixture root keeps it testable anyway.
AURADE_BLOCK_DIR=${AURADE_BLOCK_DIR:-/sys/block}

aurade_valid_target() {
  local target=$1 name
  [[ -n $target ]] || return 1
  [[ $target == /dev/* ]] || return 1
  [[ $target != *..* ]] || return 1
  name=${target#/dev/}
  name=${name//\//!}
  [[ -d "$AURADE_BLOCK_DIR/$name" ]] || return 1
  # Partitions carry a `partition` attribute; whole disks do not. Installing to
  # a partition would silently skip the partition table the bootloader needs.
  [[ ! -e "$AURADE_BLOCK_DIR/$name/partition" ]] || return 1
  return 0
}
