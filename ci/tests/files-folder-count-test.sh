#!/usr/bin/env bash
# The toolbar says what is in the folder when nothing is selected.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0045-files-folder-item-count.patch"

fail() { echo "files folder count test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0045 is missing'
grep -Fqx '0045-files-folder-item-count.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0045 is not listed in SERIES'

added=$(grep '^+' "$PATCH" | grep -v '^+++' || true)
[[ -n $added ]] || fail 'patch 0045 adds nothing'
code=$(grep -vE '^\+[[:space:]]*(//|\*|/\*)' <<<"$added" || true)
[[ -n $code ]] || fail 'patch 0045 adds only comments'

# 1. The count has to follow the folder, not only the selection. Without these
# the number is whatever the folder held when it was last selected in, which is
# a stale number presented as a current one.
for event in 'cur-dir-scan-completed' 'cur-dir-rescan-completed' "'splice'"; do
  grep -Fq "$event" <<<"$code" || \
    fail "the label is not refreshed on $event, so the count goes stale"
done

# 2. An empty folder says nothing here. The empty state panel is already on
# screen saying it at length, and two voices saying the same thing in one view
# is worse than one.
grep -Fq 'if (!count)' <<<"$code" || \
  fail 'an empty folder no longer suppresses the count, so it now speaks twice'

# 3. One item is singular.
grep -Fq "'1 item'" <<<"$code" || fail 'the singular case was removed'
grep -Fq 'items' <<<"$code" || fail 'the plural case was removed'

# 4. Thousands are grouped. A bare 14237 in a toolbar is a number nobody reads.
grep -Fq 'toLocaleString()' <<<"$code" || fail 'the thousands grouping was removed'

# 5. The count comes from the list actually on screen, so the hidden files
# filter and any active search are already applied to it. Counting anything
# else would disagree with what the person can see.
grep -Fq 'getFileList().length' <<<"$code" || \
  fail 'the count no longer comes from the rendered list'

# 6. A selection still wins. The summary belongs to the empty selection case
# only, or selecting three files would hide how many are selected.
# The branch condition itself is a context line, so what is checked is that the
# added assignment sits directly under it.
if ! grep -A2 -F 'if (selection.totalCount === 0) {' "$PATCH" |
     grep -Eq '^\+ *text = this\.auraDeDirectorySummary_\(\);'; then
  fail 'the summary is no longer the empty selection branch'
fi

echo 'files folder count test: PASS'
