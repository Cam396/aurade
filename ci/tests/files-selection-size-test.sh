#!/usr/bin/env bash
# The Files toolbar says how much is selected, not only how many.
#
# Every assertion here is about honesty rather than formatting. A byte total
# that quietly omits the folders, or that is assembled from the files whose
# size happened to arrive, is a smaller number than the truth presented as the
# truth, and nobody would ever catch it by looking.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0042-files-selection-size.patch"

fail() { echo "files selection size test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0042 is missing'
grep -Fqx '0042-files-selection-size.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0042 is not listed in SERIES'

added=$(grep '^+' "$PATCH" | grep -v '^+++' || true)
[[ -n $added ]] || fail 'patch 0042 adds nothing'

# 1. The selection cannot total what it never fetched.
grep -Fq "'size'," <<<"$added" || \
  fail "the selection prefetch no longer asks for 'size', so the total is always unknown"

# 2. A folder's recorded size is the size of its directory record, not of what
# is inside it. Adding it in inflates the total by a number that means nothing.
grep -Fq 'entry.isFile' <<<"$added" || \
  fail 'directories are no longer excluded from the byte total'

# 3. Partial data must read as unknown. Without this a selection where one file
# is missing its size reports the sum of the rest as if it were the whole.
grep -Fq 'known = false' <<<"$added" || \
  fail 'a missing size no longer marks the total unknown'
grep -Eq 'totalBytesKnown = known' <<<"$added" || \
  fail 'the known flag no longer gates the total'
grep -Fq 'fileCount > 0' <<<"$added" || \
  fail 'a selection with no files can now claim a known total of zero bytes'

# 4. Non-numeric, infinite and negative sizes are all rejected rather than
# added, since each one produces a total that renders as nonsense.
for guard in "typeof size !== 'number'" 'Number.isFinite' 'size < 0'; do
  grep -Fq "$guard" <<<"$added" || fail "the size total does not reject $guard"
done

# 5. The size is shown only for an all-files selection.
grep -Fq 'selection.directoryCount === 0 && selection.totalBytesKnown' <<<"$added" || \
  fail 'the size is no longer restricted to selections that are entirely files'

# 6. computeAdditional resolves after the count is already on screen, so
# without a second listener the size would only ever appear on the next
# selection change.
grep -Fq 'EventType.CHANGE_THROTTLED, this.updateSelectionLabel_' <<<"$added" || \
  fail 'the label is not refreshed when the byte total arrives'

# 7. The count itself must survive. Regressing "3 files selected" into a bare
# size would be a much worse trade than the one being made. The label body
# survives untouched here, so it is not in the patch at all: three lines of
# context do not reach it. What is checkable, and what actually matters, is
# that no removal takes it away.
removed=$(grep '^-' "$PATCH" | grep -v '^---' || true)
for key in ONE_FILE_SELECTED MANY_FILES_SELECTED ONE_DIRECTORY_SELECTED \
           MANY_DIRECTORIES_SELECTED MANY_ENTRIES_SELECTED; do
  if grep -Fq "$key" <<<"$removed"; then
    fail "the $key case is deleted by this patch"
  fi
done

echo 'files selection size test: PASS'
