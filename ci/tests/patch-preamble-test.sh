#!/usr/bin/env bash
# A patch preamble is a place personal data hides.
#
# git format-patch writes an author line, a date and a subject above the first
# diff. Forty nine of the fifty patches here were produced with plain diff and
# start at "diff --git"; one arrived from a format-patch workflow carrying a
# real name and a real email address, and it sat in the series for days. The
# leak gate did not catch it because the address belongs to the repository
# owner, which is exactly why it is easy to leave in: it looks like it belongs.
#
# It does not. This repository is published, the patches are published with it,
# and an address in a patch header is an address in a scrape. The rule here is
# narrow on purpose: everything above the first "diff --git" must be empty, so
# there is nowhere for a header to live at all.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH_DIR="$ROOT/patches"

fail() { echo "patch preamble test: $*" >&2; exit 1; }

[[ -d $PATCH_DIR ]] || fail 'there is no patches directory'

shopt -s nullglob
patches=("$PATCH_DIR"/*.patch)
shopt -u nullglob
[[ ${#patches[@]} -gt 0 ]] || fail 'there are no patches to check'

checked=0
for patch in "${patches[@]}"; do
  name=$(basename -- "$patch")

  # Where the real content starts. Both forms are in use here and git apply
  # takes either: most patches open with "diff --git", and one plain unified
  # diff opens straight at "--- a/". A patch with neither is its own bug.
  first=$(awk '/^diff --git /{print NR; exit} /^--- /{print NR; exit}' "$patch")
  [[ -n $first ]] || fail "${name} contains neither a diff --git line nor a --- header"

  if [[ $first -ne 1 ]]; then
    offending=$(sed -n "1,$((first-1))p" "$patch" | grep -nE '[^[:space:]]' | head -3 || true)
    [[ -z $offending ]] || \
      fail "${name} has $((first-1)) line(s) above the first diff, which is where format-patch puts the author: ${offending//$'\n'/ | }"
  fi

  # Belt and braces. Even inside the diff, these markers only ever arrive from
  # a mail based workflow and never from the source itself.
  if grep -qE '^(From|Signed-off-by|Co-authored-by|Reported-by|Reviewed-by): ' "$patch"; then
    fail "${name} carries a mail workflow authorship trailer"
  fi
  if grep -qE '^From [0-9a-f]{40} ' "$patch"; then
    fail "${name} carries a format-patch commit line"
  fi
  checked=$((checked + 1))
done

echo "patch preamble test: PASS (${checked} patches, none carrying an authorship header)"
