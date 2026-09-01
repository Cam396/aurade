#!/usr/bin/env bash
# The Files empty states, checked at the source so a rebase cannot quietly
# undo them. Two of these look like style and are not.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0039-files-empty-states-and-search.patch"

fail() { echo "files empty state test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0039 is missing'
grep -Fqx '0039-files-empty-states-and-search.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0039 is not listed in SERIES'

# Only the added lines are this patch's contract. Checking the whole file would
# pass on context lines that upstream owns.
added=$(grep '^+' "$PATCH" | grep -v '^+++' || true)
[[ -n $added ]] || fail 'patch 0039 adds nothing'

# 1. An ordinary folder gets an empty state. Upstream leaves svgRef null for a
# plain directory, so updateUi_ returns before unhiding the panel and the
# folder people open most often renders as blank space.
grep -Fq 'AURADE_EMPTY_FOLDER' <<<"$added" || \
  fail 'no empty state for ordinary folders'
grep -Fq 'auraDeEmptyFolder = true' <<<"$added" || \
  fail 'the ordinary folder empty state is never switched on'

# 2. It must be tracked by a flag, never by comparing svgRef. This empty state
# reuses the Recents illustration, so the two constants hold the same string,
# and `svgRef === AURADE_EMPTY_FOLDER` would answer true for Recents as well
# and replace the Recents copy with folder copy. That reads as a typo and is a
# behaviour change, so it is pinned here.
grep -Eq 'svgRef *=== *AURADE_EMPTY_FOLDER' <<<"$added" && \
  fail 'the empty state is selected by comparing svgRef, which also matches Recents'

# 3. The chosen line must be stable for a given folder on a given day. A
# message that rerolls on every redraw reads as a rendering glitch rather than
# a flourish, so randomness is not allowed to decide it.
grep -Fq 'Math.random' <<<"$added" && \
  fail 'the empty state line is chosen randomly, so it changes on every redraw'
grep -Fq '86400000' <<<"$added" || \
  fail 'the empty state line is not derived from the day, so it cannot be stable'

# 4. The folders that carry their own copy. A generic line everywhere would
# make the whole feature pointless.
for root in DOWNLOADS MY_FILES REMOVABLE; do
  grep -Fq "RootType.$root" <<<"$added" || fail "no empty state copy for $root"
done

# 5. House style. Em and en dashes are banned across this project, and product
# copy is exactly where they creep in.
if grep -Pq '[\x{2013}\x{2014}]' <<<"$added"; then
  fail 'the empty state copy contains an em or en dash'
fi

# 6. The one joke, kept honest. Colossal Cave has answered xyzzy with
# "Nothing happens." since 1977 and the reply is the whole point of it.
# Match the comparison and not the word: the comment above it also says
# xyzzy, so a bare grep passes happily after the check itself is changed.
grep -Eq "query *=== *'xyzzy'" <<<"$added" || fail 'the xyzzy response was removed'
grep -Fq 'Nothing happens.' <<<"$added" || \
  fail 'xyzzy no longer answers with the line it exists to answer with'

echo 'files empty state test: PASS'
