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
# Questions the engine cannot consume are not listed. That rule is what kept
# `fslayout` and `swap` out of this file until the engine grew `--filesystem`,
# `--swap`, `--swap-size` and `--layout`; they are here now because those flags
# exist and are tested, not because the screen looked empty without them.

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
  help 'Everything on the disk you pick is erased. You can still go back.' \
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
  help 'This is the name other devices see. Letters, digits and hyphens.' \
  type text \
  default aurade \
  validator aurade_valid_hostname \
  error 'Use 1-63 letters, digits or inner hyphens, for example aurade-laptop.' \
  advanced no \
  flag --hostname \
  secret no

_q username \
  label 'Pick a username' \
  short 'Username' \
  help 'This is your account. It cannot be changed later without making a new one.' \
  type text \
  default '' \
  validator aurade_valid_username \
  error 'Start with a lowercase letter, then lowercase letters, digits, underscores or hyphens. Some names are already taken by the system.' \
  advanced no \
  flag --username \
  secret no

_q password \
  label 'Set a password' \
  short 'Password' \
  help 'You will type this to sign in. It is hashed straight away and never stored in readable form.' \
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
  help 'Your files stay unreadable to anyone without the passphrase. You will type it every time this computer starts.' \
  type bool \
  default yes \
  validator '' \
  error 'Answer yes or no.' \
  advanced no \
  flag --encrypt \
  secret no

_q luks_passphrase \
  label 'Set a disk passphrase' \
  short 'Disk passphrase' \
  help 'This unlocks the disk at startup. It is not your account password, and it cannot be recovered if you forget it.' \
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
  help 'Pick the layout printed on your keyboard. Try it in the box below.' \
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
  help 'Sets the clock.' \
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
  help 'Sets the language, and how dates and numbers look.' \
  type enum \
  default en_US.UTF-8 \
  validator aurade_valid_locale \
  error 'Name an installed locale, for example en_US.UTF-8 or C.UTF-8.' \
  advanced no \
  flag --locale \
  secret no

_q layout \
  label 'How should the disk be used?' \
  short 'Disk layout' \
  help 'Erase gives AuraDE the whole disk. Alongside keeps what is there and uses free space that is already unallocated. It never shrinks a partition to make room.' \
  type enum \
  default wipe \
  validator aurade_valid_layout \
  error 'Choose wipe or alongside.' \
  advanced yes \
  flag --layout \
  secret no

_q filesystem \
  label 'Root filesystem' \
  short 'Filesystem' \
  help 'Btrfs is the default and the only one that can take a snapshot to roll back to. ext4 and xfs install a system that boots and updates, with nothing to roll back to.' \
  type enum \
  default btrfs \
  validator aurade_valid_filesystem \
  error 'Choose btrfs, ext4 or xfs.' \
  advanced yes \
  flag --filesystem \
  secret no

_q swap \
  label 'Swap' \
  short 'Swap' \
  help 'A swap file lives inside the root filesystem, so encrypting the disk encrypts the swap with it. zram compresses what is already in memory and never touches the disk.' \
  type enum \
  default none \
  validator aurade_valid_swap \
  error 'Choose none, file or zram.' \
  advanced yes \
  flag --swap \
  secret no

_q swap_size \
  label 'Swap size' \
  short 'Swap size' \
  help 'Auto keeps a desktop responsive when memory runs short. Hibernate makes the file big enough to hold everything in memory, so the computer can be switched off and come back where it was.' \
  type enum \
  default auto \
  validator aurade_valid_swap_size \
  error 'Choose auto, hibernate, or a size such as 8G.' \
  advanced yes \
  flag --swap-size \
  secret no

_q snapshot \
  label 'Arch package snapshot' \
  short 'Package snapshot' \
  help 'AuraDE installs from a pinned day in the Arch archive, so two installs from the same image match.' \
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

# The word the user has to type at the gate, derived from the answers rather
# than from a literal in a renderer.
#
# It lives here because two front ends and the engine all have to agree on it,
# and because the word has to be true: `alongside` does not erase anything, and
# a gate that demands ERASE for an install that erases nothing teaches people
# to type ERASE without reading it. That habit is the failure this gate exists
# to prevent, so the token names the operation.
aurade_confirmation_token() {
  local target=$1 layout=${2:-wipe}
  if [[ $layout == alongside ]]; then
    printf 'INSTALL:%s' "$target"
  else
    printf 'ERASE:%s' "$target"
  fi
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
