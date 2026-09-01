#!/usr/bin/env bash
# The Files modification time wording, held at the source.
#
# The interesting failures here are all off-by-one and all silent: a wrong
# bound does not crash, it just makes the column say something slightly untrue,
# which nobody files a bug about and everybody notices.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0040-files-human-modification-times.patch"

fail() { echo "files relative time test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0040 is missing'
grep -Fqx '0040-files-human-modification-times.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0040 is not listed in SERIES'

added=$(grep '^+' "$PATCH" | grep -v '^+++' || true)
[[ -n $added ]] || fail 'patch 0040 adds nothing'

# 1. A clock that is ahead must never produce "in 3 minutes ago". Without this
# guard a future timestamp yields a negative elapsed and falls into the minute
# branch, which is exactly the sort of thing that only shows up on a machine
# whose time is wrong, which is the machine least able to explain it.
grep -Fq 'elapsed < 0' <<<"$added" || \
  fail 'future timestamps are not guarded, so a fast clock reads as "ago"'

# 2. Yesterday keeps the upstream wording. The weekday branch must start beyond
# it: "Yesterday 10:15 PM" says more than "Tuesday 10:15 PM" does.
grep -Eq 'daysBack >= 1' <<<"$added" || \
  fail 'the weekday branch no longer starts where it should, so yesterday may be overridden'
grep -Eq 'daysBack < 6' <<<"$added" || \
  fail 'the weekday branch has no upper bound, so old files would show a weekday'

# 3. One minute is singular. Plural everywhere is the tell that nobody read it.
grep -Fq "'1 minute ago'" <<<"$added" || fail 'the singular minute case was removed'
grep -Fq 'minutes ago' <<<"$added" || fail 'the plural minute case was removed'
grep -Fq "'Just now'" <<<"$added" || fail 'the under-a-minute case was removed'

# 4. Returning null is what hands the decision back to the upstream wording, so
# the fallthrough has to stay explicit rather than becoming a string.
grep -Fq 'string|null' <<<"$added" || \
  fail 'the helper no longer returns null, so it can no longer defer to the upstream format'

# 5. House style.
if grep -Pq '[\x{2013}\x{2014}]' <<<"$added"; then
  fail 'the relative time copy contains an em or en dash'
fi

# 6. Every weekday is spelled, since an incomplete table silently prints
# undefined for one day a week.
for day in Sunday Monday Tuesday Wednesday Thursday Friday Saturday; do
  grep -Fq "'$day'" <<<"$added" || fail "the weekday table is missing $day"
done

echo 'files relative time test: PASS'
