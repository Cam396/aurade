#!/usr/bin/env bash
# The exact timestamp behind the friendly date in the Files list.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0043-files-exact-timestamp.patch"

fail() { echo "files exact time test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0043 is missing'
grep -Fqx '0043-files-exact-timestamp.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0043 is not listed in SERIES'

added=$(grep '^+' "$PATCH" | grep -v '^+++' || true)
[[ -n $added ]] || fail 'patch 0043 adds nothing'

# 1. Unconditional, for the same reason as the byte count: updateDate_ repaints
# cells recycled by scrolling, so a title set only when a time exists leaves the
# previous file's timestamp on a row showing something else. Guarding it is the
# obvious way to write this and it is the bug.
grep -Eq '^\+ *div\.title = auraDeExactTime\(' <<<"$added" || \
  fail 'the title is not assigned directly from the helper, so a reused row may keep a stale time'
if grep -Eq '^\+ *if *\(.*\) *\{? *div\.title' <<<"$added"; then
  fail 'the title assignment is guarded, so a recycled row keeps the previous timestamp'
fi

# 2. Every case where a timestamp would be untrue returns the empty string,
# which is also what clears the cell.
for guard in 'modTime === undefined' 'isFinite'; do
  grep -Fq "$guard" <<<"$added" || fail "the helper does not reject $guard"
done
grep -Fq "return '';" <<<"$added" || \
  fail 'the helper no longer returns an empty string, so it cannot clear a tooltip'

# 3. A tooltip is never worth throwing over. dateStyle and timeStyle are widely
# supported and not universally, and an exception here would take the whole
# row render with it.
grep -Fq 'catch' <<<"$added" || \
  fail 'the formatting call is no longer guarded, so an unsupported option would break the row'

# 4. The date has to carry its year and its seconds, or it answers none of the
# questions the friendly form leaves open.
grep -Fq "dateStyle: 'full'" <<<"$added" || fail 'the full date was dropped'
grep -Fq "timeStyle: 'medium'" <<<"$added" || fail 'the seconds were dropped'

# 5. The locale stays the viewer's. A hardcoded one would show a British user
# an American date and read as a bug in the app.
grep -Fq 'undefined, {dateStyle' <<<"$added" || \
  fail 'the tooltip no longer uses the viewer locale'

echo 'files exact time test: PASS'
