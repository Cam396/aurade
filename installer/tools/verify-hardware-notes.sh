#!/usr/bin/env bash
# Check that the strings in the catalogue are strings something really prints.
#
# The catalogue is the one file here that could be entirely plausible and
# entirely wrong. Every entry is a sentence about a log line, and a sentence
# about a log line that no program emits is worse than no entry at all: it
# never fires, so it is never noticed, and it makes the file look bigger and
# better tested than it is. A generated catalogue is exactly the shape of
# thing that fills up with those.
#
# So the `evidence` column of every kernel entry names the file and line in the
# kernel source that emits it, and this checks that claim. Point it at a kernel
# tree:
#
#   installer/tools/verify-hardware-notes.sh /path/to/linux
#
# It is not in `tests/run.sh`, because the suite must run on a machine with no
# kernel source on it. It is run when the catalogue grows, and what it prints
# is pasted into the commit that grew it.
#
# A string in a printk is a format string, so the literal in the catalogue has
# to be a run of it with no substitutions in the middle. "APIC error on CPU"
# is checkable. "APIC error on CPU3: 40" is not, and is also wrong, because it
# would only ever match one machine.
set -Eeuo pipefail

SELF=${0##*/}
ROOT=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
CATALOGUE=${AURADE_NOTES_FILE:-$ROOT/data/hardware-notes.tsv}

KERNEL=${1:-}
[[ -n $KERNEL ]] || { echo "usage: $SELF /path/to/linux [catalogue]" >&2; exit 2; }
[[ -d $KERNEL ]] || { echo "$SELF: no kernel tree at $KERNEL" >&2; exit 2; }
[[ -f $KERNEL/Kbuild ]] || { echo "$SELF: $KERNEL does not look like a kernel tree" >&2; exit 2; }
[[ -z ${2-} ]] || CATALOGUE=$2

ok=0 missing=0 skipped=0 moved=0
declare -a MISSING=() MOVED=()

while IFS=$'\t' read -r key source severity what todo evidence || [[ -n ${key:-} ]]; do
  [[ -n ${key:-} && $key != '#'* ]] || continue
  if [[ $source != kernel || $evidence == '-' ]]; then
    (( ++skipped ))
    continue
  fi
  # The evidence is `path:line` relative to the kernel tree. Check the string
  # is at that line first, because that is the claim being made, and only fall
  # back to searching the tree when it is not: a string that moved is a note
  # that is still true with stale provenance, and a string that is nowhere is
  # a note about something that does not happen.
  file=${evidence%%:*}
  line=${evidence##*:}
  if [[ -f $KERNEL/$file ]] && sed -n "${line}p" "$KERNEL/$file" 2>/dev/null | grep -qF -- "$key"; then
    (( ++ok ))
    continue
  fi
  found=$(grep -rlF --include='*.c' --include='*.h' -- "$key" "$KERNEL" 2>/dev/null | head -1 || true)
  if [[ -n $found ]]; then
    where=$(grep -nF -m1 -- "$key" "$found" | cut -d: -f1)
    MOVED+=("$key	${evidence}	${found#"$KERNEL/"}:$where")
    (( ++moved ))
  else
    MISSING+=("$key	$evidence")
    (( ++missing ))
  fi
done <"$CATALOGUE"

printf '%s entries verified at the line they name\n' "$ok"
printf '%s entries not from the kernel, or with no evidence to check\n' "$skipped"

if (( moved )); then
  printf '\n%s entries whose string moved. The note is still true. Update the evidence:\n' "$moved"
  printf '  %s\n' "${MOVED[@]}"
fi

if (( missing )); then
  printf '\n%s entries whose string is not in this kernel at all:\n' "$missing"
  printf '  %s\n' "${MISSING[@]}"
  printf '\nA string that is nowhere in the source is a note about something that\n'
  printf 'never happens. Either the string is wrong or it belongs to a driver that\n'
  printf 'is out of tree, and either way the entry needs a person to look at it.\n'
  exit 1
fi

exit 0
