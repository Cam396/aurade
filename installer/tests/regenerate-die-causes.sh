#!/usr/bin/env bash
# Rewrite tests/fixtures/die-causes.tsv from what the engine does now.
#
# Run this only after looking at the diff test-die-cause.sh printed and
# deciding the new buckets are right. The fixture is not a cache: it is the
# record of which explanation and which next step each failure gives somebody,
# and regenerating it without reading the diff turns the one test that guards
# that into a rubber stamp.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
ENGINE="$ROOT/installer/bin/aurade-install"
FIXTURE="$ROOT/installer/tests/fixtures/die-causes.tsv"

# Lifted out of `die` by reading it, the same way the test does, so this cannot
# drift into classifying by a second copy of the rules.
classifier=$(awk '
  /^  local message=\$\* cause=installer_error/ { inside = 1 }
  inside && /^    case \$message in/ { emit = 1 }
  emit { print }
  emit && /^    esac/ { exit }
' "$ENGINE")
[[ $classifier == *'case $message in'* ]] ||
  { echo 'could not find the classifier in aurade-install' >&2; exit 1; }

grep -oE "die '[^']+'" "$ENGINE" | sed "s/^die '//; s/'\$//" | LC_ALL=C sort -u |
  while IFS= read -r message; do
    cause=$(bash -c "
      set -Eeuo pipefail
      message=\$1
      cause=installer_error
$classifier
      printf '%s' \"\$cause\"" _ "$message")
    printf '%s\t%s\n' "$cause" "$message"
  done | LC_ALL=C sort >"$FIXTURE"

printf 'wrote %s (%s messages)\n' "$FIXTURE" "$(wc -l <"$FIXTURE")"
