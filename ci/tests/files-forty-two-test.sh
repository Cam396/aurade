#!/usr/bin/env bash
# One quiet easter egg, and the two things it must never do.
#
# An easter egg earns its place by being invisible until found. It must not
# change what the app reports, and it must not linger once the condition that
# produced it is gone.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0047-files-forty-two.patch"

fail() { echo "files forty two test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0047 is missing'
grep -Fqx '0047-files-forty-two.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0047 is not listed in SERIES'

added=$(grep '^+' "$PATCH" | grep -v '^+++' || true)
[[ -n $added ]] || fail 'patch 0047 adds nothing'
code=$(grep -vE '^\+[[:space:]]*(//|\*|/\*)' <<<"$added" || true)
[[ -n $code ]] || fail 'patch 0047 adds only comments'

# 1. It is a tooltip and nothing else. The count itself has to stay true: a
# folder of 42 still reads "42 items", because an easter egg that lies about
# the data is a bug wearing a costume.
grep -Eq 'title = count === 42' <<<"$code" || \
  fail 'the egg no longer hangs off the title, so it may be altering what the label reports'
if grep -Eq '^\+.*(textContent|return).*42' <<<"$code"; then
  fail 'the egg reaches the label text, so the count itself is no longer honest'
fi

# 2. The ternary clears it. Assigned only on the match, the note would follow
# the person into the next folder and sit on a count of nine.
grep -Fq "42 ? 'The answer.' : ''" <<<"$code" || \
  fail 'the tooltip is not cleared when the count is anything else, so it lingers on the wrong folder'

# 3. Exactly forty two. A range would fire constantly and stop being a find.
grep -Fq '=== 42' <<<"$code" || fail 'the egg is no longer an exact match'

echo 'files forty two test: PASS'
