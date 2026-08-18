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
check_cause 'Secure Boot signing requires both a private key'   secure_boot_error
check_cause 'Secure Boot private key must not be group/world accessible' secure_boot_error
check_cause 'openssl is required for Secure Boot key validation' secure_boot_error
check_cause 'too old to enroll Secure Boot keys'               secure_boot_error
# The one that was wrong. `sbverify` failing produces a message containing the
# word signature, and while the signature arm sat above the Secure Boot arm
# this failure told somebody a package had not matched its signature and sent
# them to check the clock on their computer, during the bootloader stage, on a
# disk that had already been written.
check_cause 'Secure Boot signature verification failed'        secure_boot_error

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

# --- and all of the others, so none of them can drift unnoticed -------------
#
# The checks above pin intent: these nine messages *must* land in these
# buckets, and they say so by name. This pins state: every message the engine
# can produce, with the bucket it lands in today.
#
# The two are not the same thing and both are worth having. Nine hand written
# pins caught nothing about the other ninety one, and the one real
# misclassification found in this engine was in neither list: `sbverify`
# failing matched the signature arm before it reached the Secure Boot arm, and
# nothing anywhere said so.
#
# A changed bucket is not automatically a bug. It is a thing somebody has to
# look at, which is the entire point of writing it down.
FIXTURE="$ROOT/installer/tests/fixtures/die-causes.tsv"
current=$(
  for message in "${messages[@]}"; do
    printf '%s\t%s\n' "$(classify "$message")" "$message"
  # Deduplicated: the same sentence appears at more than one die call, and the
  # fixture is a map from a message to the bucket it lands in rather than a
  # census of call sites.
  done | LC_ALL=C sort -u
)
if [[ ! -r $FIXTURE ]]; then
  fail "there is no classification fixture at $FIXTURE"
elif ! diff -u <(LC_ALL=C sort "$FIXTURE") <(printf '%s\n' "$current") >"$ROOT/.die-cause.diff" 2>&1; then
  echo 'test-die-cause: a die message changed which explanation it gives a user.' >&2
  echo 'Lines starting - are what the fixture expects, + is what the engine does now.' >&2
  echo 'If the new bucket is right, update the fixture. If it is not, the words in' >&2
  echo 'the die call moved the failure into somebody else. Check what the front' >&2
  echo 'ends say for both codes before deciding.' >&2
  echo '' >&2
  echo 'To regenerate the fixture once you are sure:' >&2
  echo '  installer/tests/regenerate-die-causes.sh' >&2
  cat "$ROOT/.die-cause.diff" >&2
  rm -f "$ROOT/.die-cause.diff"
  failures=$(( failures + 1 ))
else
  rm -f "$ROOT/.die-cause.diff"
fi

(( failures == 0 )) || exit 1
printf 'installer die cause test: PASS (%s messages, %s pinned by name, all pinned by bucket)\n' \
  "${#messages[@]}" 10
