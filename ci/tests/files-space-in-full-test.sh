#!/usr/bin/env bash
# The full storage numbers behind the gear menu's bar.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0046-files-space-in-full.patch"

fail() { echo "files space in full test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0046 is missing'
grep -Fqx '0046-files-space-in-full.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0046 is not listed in SERIES'

added=$(grep '^+' "$PATCH" | grep -v '^+++' || true)
[[ -n $added ]] || fail 'patch 0046 adds nothing'
code=$(grep -vE '^\+[[:space:]]*(//|\*|/\*)' <<<"$added" || true)
[[ -n $code ]] || fail 'patch 0046 adds only comments'

# 1. The total is the whole point. A bar shows a proportion and the label shows
# one number, so between them they never say how big the disk is, and "12.3 GB
# available" means something quite different on a 32GB eMMC.
grep -Fq 'bytesToString(spaceInfo.totalSize)' <<<"$code" || \
  fail 'the total size is no longer in the tooltip, which is the only thing it added'

# 2. The percentage is rounded rather than printed raw, or the tooltip reads
# 58.33333333333333% used.
grep -Fq 'Math.round(' <<<"$code" || fail 'the percentage is no longer rounded'

# 3. Cleared on every path that does not set it. The gear menu element is
# reused each time the menu opens, so a title left from the previous volume
# would describe a drive the person is no longer looking at.
[[ $(grep -c "volumeSpaceInfo.title = '';" <<<"$code") -ge 2 ]] || \
  fail 'the tooltip is not cleared on the unlimited and failed paths, so it can describe the wrong volume'

echo 'files space in full test: PASS'
