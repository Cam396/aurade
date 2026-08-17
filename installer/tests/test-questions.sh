#!/usr/bin/env bash
# The question manifest's invariants, checked against fixture lookup roots.
#
# These are the three ways a data-driven question set goes wrong silently, and
# each one is a bug the user only meets after they have answered everything:
#
#   a default its own validator rejects, so enter does not work;
#   a validator name that does not exist, so nothing is validated at all;
#   a flag the engine does not parse, so the install dies at argument parsing
#   with the disk already selected.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fail() { echo "test-questions: $*" >&2; exit 1; }

# Fixture lookup roots, so the defaults are checked against a known-good tree
# rather than against whatever this machine happens to have installed.
install -d "$TMP/zoneinfo" "$TMP/locales" "$TMP/keymaps/i386/qwerty" "$TMP/block/nvme0n1"
: >"$TMP/zoneinfo/UTC"
install -d "$TMP/zoneinfo/America"
: >"$TMP/zoneinfo/America/Chicago"
: >"$TMP/locales/en_US"
: >"$TMP/keymaps/i386/qwerty/us.map.gz"
printf '%s\n' '2026/07/12' >"$TMP/snapshot"

export AURADE_ZONEINFO_DIR="$TMP/zoneinfo"
export AURADE_LOCALE_DIR="$TMP/locales"
export AURADE_KEYMAP_DIR="$TMP/keymaps"
export AURADE_BLOCK_DIR="$TMP/block"
export AURADE_SNAPSHOT_FILE="$TMP/snapshot"

# shellcheck source=../lib/aurade-validate.sh
. "$ROOT/installer/lib/aurade-validate.sh"
# shellcheck source=../lib/aurade-questions.sh
. "$ROOT/installer/lib/aurade-questions.sh"

(( ${#AURADE_QUESTION_IDS[@]} > 0 )) || fail 'manifest defines no questions'

# --- every question is complete and its ids are unique ---------------------
declare -A seen=()
for id in "${AURADE_QUESTION_IDS[@]}"; do
  [[ -z ${seen[$id]:-} ]] || fail "duplicate question id: $id"
  seen[$id]=1
  for field in label short help type default validator error advanced flag secret; do
    [[ -n ${AURADE_Q[$id.$field]+set} ]] || fail "$id is missing the '$field' field"
  done
  case $(aurade_question_field "$id" type) in
    disk|text|secret|bool|enum|date) ;;
    *) fail "$id has an unknown type: $(aurade_question_field "$id" type)" ;;
  esac
  case $(aurade_question_field "$id" advanced) in
    yes|no) ;;
    *) fail "$id has a non-boolean 'advanced' value" ;;
  esac
  case $(aurade_question_field "$id" secret) in
    yes|no) ;;
    *) fail "$id has a non-boolean 'secret' value" ;;
  esac
  [[ -n $(aurade_question_field "$id" error) ]] || fail "$id has no error message"
done

# --- every named validator exists ------------------------------------------
for id in "${AURADE_QUESTION_IDS[@]}"; do
  validator=$(aurade_question_field "$id" validator)
  [[ -n $validator ]] || continue
  declare -F "$validator" >/dev/null || fail "$id names a validator that does not exist: $validator"
done

# --- every non-empty default is accepted by its own validator --------------
# A default its own rule rejects is a prompt the user cannot leave by pressing
# enter, which is how the keymap prompt once became an unbreakable loop.
for id in "${AURADE_QUESTION_IDS[@]}"; do
  default=$(aurade_question_default "$id")
  [[ -n $default ]] || continue
  aurade_question_validate "$id" "$default" ||
    fail "$id default '$default' is rejected by its own validator"
done

# --- advanced questions are genuinely skippable ----------------------------
# Skipping the advanced section must still produce a complete argument list.
for id in "${AURADE_QUESTION_IDS[@]}"; do
  aurade_question_is_advanced "$id" || continue
  [[ -n $(aurade_question_default "$id") ]] ||
    fail "advanced question $id has no default, so skipping advanced options breaks the install"
done

# --- the snapshot default really does come from the image ------------------
[[ $(aurade_question_default snapshot) == 2026/07/12 ]] ||
  fail 'snapshot default did not come from the image snapshot file'
AURADE_SNAPSHOT_FILE=$TMP/absent
fallback=$(aurade_question_default snapshot)
aurade_valid_arch_snapshot "$fallback" ||
  fail "snapshot fallback '$fallback' is not a valid snapshot date"
AURADE_SNAPSHOT_FILE=$TMP/snapshot

# --- every flag is one the engine actually parses ---------------------------
# The join between the UI and the engine, and the one that rots quietly.
for id in "${AURADE_QUESTION_IDS[@]}"; do
  flag=$(aurade_question_field "$id" flag)
  [[ -n $flag ]] || continue
  grep -Eq "^[[:space:]]*(\S+\|)*${flag}\)" "$ROOT/installer/bin/aurade-install" ||
    fail "$id maps to $flag, which aurade-install does not parse"
done

# --- the default path asks every question the engine requires ---------------
# aurade-install refuses without these; if the default order omits one and it
# has no default either, the user answers everything and then hits an argument
# error.
for required in target username password snapshot; do
  covered=0
  for id in "${AURADE_QUESTION_ORDER[@]}"; do
    [[ $id != "$required" ]] || covered=1
  done
  if (( ! covered )); then
    [[ -n $(aurade_question_default "$required") ]] ||
      fail "$required is neither on the default path nor defaulted"
  fi
done

# --- the ordered set is real, visible and complete --------------------------
for id in "${AURADE_QUESTION_ORDER[@]}"; do
  aurade_question_exists "$id" || fail "question order names a question that does not exist: $id"
  ! aurade_question_is_advanced "$id" ||
    fail "$id is marked advanced but appears on the default path"
done
for id in "${AURADE_QUESTION_IDS[@]}"; do
  aurade_question_is_advanced "$id" && continue
  listed=0
  for ordered in "${AURADE_QUESTION_ORDER[@]}"; do
    [[ $ordered != "$id" ]] || listed=1
  done
  (( listed )) || fail "$id is not advanced but never gets asked"
done

# --- secrets are declared, and the declaration is used ----------------------
for id in password luks_passphrase; do
  aurade_question_is_secret "$id" || fail "$id is not marked secret"
done
for id in "${AURADE_QUESTION_IDS[@]}"; do
  aurade_question_is_secret "$id" || continue
  [[ $(aurade_question_field "$id" type) == secret ]] ||
    fail "$id is marked secret but is not a secret-typed question"
done

# --- the target rule accepts whole disks and rejects partitions -------------
install -d "$TMP/block/nvme0n1p1"
: >"$TMP/block/nvme0n1p1/partition"
aurade_valid_target /dev/nvme0n1 || fail 'a whole disk was rejected'
! aurade_valid_target /dev/nvme0n1p1 || fail 'a partition was accepted as an install target'
! aurade_valid_target /dev/does-not-exist || fail 'a nonexistent device was accepted'
! aurade_valid_target '' || fail 'an empty target was accepted'
! aurade_valid_target /dev/../etc/passwd || fail 'a traversing path was accepted'
! aurade_valid_target nvme0n1 || fail 'a bare name outside /dev was accepted'

# --- validation delegates rather than re-implementing -----------------------
aurade_question_validate hostname aurade || fail 'valid hostname rejected'
! aurade_question_validate hostname '-bad' || fail 'invalid hostname accepted'
! aurade_question_validate username root || fail 'reserved username accepted'
! aurade_question_validate snapshot 2026/02/30 || fail 'impossible date accepted'
! aurade_question_validate repo_url '' || fail 'empty answer accepted for an unvalidated question'
aurade_question_validate repo_url 'file:///var/cache/aurade/repo' || fail 'unvalidated question rejected a non-empty answer'

# --- the two answers that can be guessed from one already given -------------
#
# Somebody who has just chosen French is about to meet a list of a hundred and
# forty keyboard layouts with `us` selected and the one they want two hundred
# entries down. The locale is already on the screen and was given willingly,
# so it is used, and the guess is only ever a starting position: the list still
# opens on it and one arrow key overrides it.
#
# The time zone is guessed the same way and deliberately not from the network.
# An installer that makes an outbound request to a location service, before
# anybody has agreed to anything, is a thing to be asked for rather than
# assumed.
install -d "$TMP/zoneinfo/Europe" "$TMP/zoneinfo/Asia"
: >"$TMP/zoneinfo/Europe/Paris"
: >"$TMP/zoneinfo/Europe/London"
: >"$TMP/keymaps/i386/qwerty/fr.map.gz"
: >"$TMP/keymaps/i386/qwerty/uk.map.gz"
declare -A ANSWERS=()

ANSWERS[locale]=fr_FR.UTF-8
[[ $(aurade_question_default keymap) == fr ]] ||
  fail "a French locale did not suggest the French layout"
[[ $(aurade_question_default timezone) == Europe/Paris ]] ||
  fail 'a French locale did not suggest the French time zone'

ANSWERS[locale]=en_GB.UTF-8
[[ $(aurade_question_default keymap) == uk ]] ||
  fail 'a British locale did not suggest the British layout'

# Where the territory has more than one time zone, the guess is not made. A
# wrong zone confidently filled in is worse than UTC, because UTC is obviously
# a placeholder and America/New_York is not.
ANSWERS[locale]=en_US.UTF-8
[[ $(aurade_question_default timezone) == UTC ]] ||
  fail 'a territory with six time zones was given one anyway'

# A guess this image cannot actually load is not offered. The keymap list is
# built from what is on the image, and a default that is not in it is a prompt
# nobody can accept with enter.
ANSWERS[locale]=ja_JP.UTF-8
[[ $(aurade_question_default keymap) == us ]] ||
  fail 'a layout missing from the image was suggested anyway'

# And with nothing chosen at all, the manifest's own defaults stand.
ANSWERS=()
[[ $(aurade_question_default keymap) == us ]] ||
  fail 'the keymap default changed with no locale answered'
[[ $(aurade_question_default timezone) == UTC ]] ||
  fail 'the time zone default changed with no locale answered'

echo 'installer question schema test: PASS'
