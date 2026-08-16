#!/usr/bin/env bash
# The engine picks a cause code by matching its own prose.
#
# `die` in aurade-install runs the message it was handed through a case
# statement and writes the resulting code into the journal. Both front ends
# then turn that code into the sentence the user reads and the one action they
# are offered. So the words inside a `die` call are not just words: change
# "could not acquire the package set" to "the packages could not be
# downloaded" and the same failure stops being a network problem and starts
# being an unclassified one, with a different explanation and a different
# next step, and nothing anywhere fails.
#
# This test is the thing that fails. It takes every message the engine can
# reach at a journalled stage, runs it through the same classifier, and pins
# the answer. Rewording is fine. Rewording into a different bucket is not.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
ENGINE=$ROOT/installer/bin/aurade-install
failures=0

fail() { printf 'test-die-cause: %s\n' "$*" >&2; failures=$(( failures + 1 )); }

# The classifier, lifted out of `die` by reading it rather than by copying it.
# If the case block moves or changes shape this extraction stops matching and
# the test says so, which is the point: a silent copy would drift.
classifier=$(awk '
  /^  local message=\$\* cause=installer_error/ { inside = 1 }
  inside && /^    case \$message in/ { emit = 1 }
  emit { print }
  emit && /^    esac/ { exit }
' "$ENGINE")
[[ $classifier == *'case $message in'* && $classifier == *keyring_error* ]] ||
  { echo 'test-die-cause: could not find the classifier in aurade-install' >&2; exit 1; }

classify() {
  local message=$1
  bash -c "
    set -Eeuo pipefail
    message=\$1
    cause=installer_error
$classifier
    printf '%s' \"\$cause\"
  " _ "$message"
}

# --- every message the engine can reach at a journalled stage ---------------
#
# Extracted from the engine rather than typed here, so a new `die` that lands
# in the wrong bucket cannot be added without this list noticing.
mapfile -t messages < <(
  grep -oE "die '[^']+'" "$ENGINE" | sed "s/^die '//; s/'\$//"
)
(( ${#messages[@]} >= 20 )) ||
  fail "only found ${#messages[@]} die messages, which suggests the extraction broke"

# --- the pinned answers ----------------------------------------------------
#
# Each entry is a message fragment and the cause it must classify as. Only the
# messages a user can actually reach are listed: argument validation runs
# before any stage is active, so `die` never journals it.
check_cause() {
  local fragment=$1 want=$2 message='' candidate got
  for candidate in "${messages[@]}"; do
    [[ $candidate == *"$fragment"* ]] || continue
    message=$candidate
    break
  done
  [[ -n $message ]] || { fail "no engine message contains '$fragment'"; return; }
  got=$(classify "$message")
  [[ $got == "$want" ]] ||
    fail "'$fragment' classifies as $got, expected $want"
}

check_cause 'the package signing keyring could not be set up' keyring_error
check_cause 'did not match their signatures'                  keyring_error
check_cause 'missing the Arch signing keyring'                 keyring_error
check_cause 'could not all be downloaded from the archive'     network_error
check_cause 'no EFI system partition'                          target_error
check_cause 'trusts no key that can start AuraDE'              secure_boot_error
check_cause 'whether the firmware is in setup mode'            secure_boot_error
check_cause 'will not erase a disk without knowing'            secure_boot_error
check_cause 'too old to enrol Secure Boot keys'                secure_boot_error

# --- and the codes still line up with the copy ------------------------------
#
# A cause the engine can emit but lib/aurade-copy.sh has no sentence for shows
# the user the stage explanation alone. That is a deliberate fallback for an
# unknown code, not somewhere a known one should quietly end up.
# shellcheck source=../lib/aurade-copy.sh
. "$ROOT/installer/lib/aurade-copy.sh"
for code in keyring_error capacity_error network_error secure_boot_error \
            target_error storage_error unexpected_exit cancelled; do
  [[ -n $(cause_explanation "$code") ]] ||
    fail "the engine emits $code and the copy library has no sentence for it"
  [[ -n $(cause_next_step "$code") ]] ||
    fail "the engine emits $code and the copy library has no next step for it"
done
# The catch-all is the one code that deliberately says nothing, because it
# means the classifier did not recognise the message.
[[ -z $(cause_explanation installer_error) ]] ||
  fail 'installer_error grew an explanation it cannot honestly give'

(( failures == 0 )) || exit 1
printf 'installer die cause test: PASS (%s messages, %s pinned)\n' \
  "${#messages[@]}" 9
