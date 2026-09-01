#!/usr/bin/env bash
# The exact byte count behind the rounded size in the Files list.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0041-files-exact-byte-count.patch"

fail() { echo "files exact bytes test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0041 is missing'
grep -Fqx '0041-files-exact-byte-count.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0041 is not listed in SERIES'

added=$(grep '^+' "$PATCH" | grep -v '^+++' || true)
[[ -n $added ]] || fail 'patch 0041 adds nothing'

# 1. The assignment has to be unconditional. updateSize_ repaints cells that
# are recycled as the list scrolls, so a title set only when a size exists
# leaves the previous file's byte count sitting on a row that now shows a
# folder. Guarding the assignment is the obvious way to write this and it is
# the bug, which is why the shape is pinned rather than the behaviour.
grep -Eq '^\+ *div\.title = auraDeExactBytes\(' <<<"$added" || \
  fail 'the title is not assigned directly from the helper, so reused cells may keep a stale count'
if grep -Eq '^\+ *if *\(.*\) *\{? *div\.title' <<<"$added"; then
  fail 'the title assignment is guarded, so a recycled row keeps the previous byte count'
fi

# 2. The helper returns the empty string for every case where an exact count
# would be untrue, which is also what clears the cell.
for guard in 'special' 'isFinite' 'size < 0'; do
  grep -Fq "$guard" <<<"$added" || fail "the helper does not reject $guard"
done
grep -Fq "return '';" <<<"$added" || \
  fail 'the helper no longer returns an empty string, so it cannot clear a cell'

# 3. One byte is singular.
grep -Fq "'1 byte'" <<<"$added" || fail 'the singular byte case was removed'

# 4. Thousands are grouped, since an ungrouped ten digit number is exactly as
# unreadable as the rounded value it exists to clarify.
grep -Fq 'replace(' <<<"$added" || fail 'the thousands grouping was removed'

# 5. House style.
if grep -Pq '[\x{2013}\x{2014}]' <<<"$added"; then
  fail 'the byte count copy contains an em or en dash'
fi

echo 'files exact bytes test: PASS'
