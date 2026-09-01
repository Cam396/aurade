#!/usr/bin/env bash
# The resource transplant, against paks built for the test.
#
# resources.pak carries every WebUI on the system, so a wrong offset is not one
# broken app, it is the whole desktop. The tool asserts its own result and this
# fixture asserts that those assertions actually fire, because a verifier that
# cannot fail is decoration.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TOOL="$ROOT/ci/pak-swap-resources.py"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fail() { echo "pak swap test: $*" >&2; exit 1; }
[[ -r $TOOL ]] || fail 'ci/pak-swap-resources.py is missing'

# Two paks sharing three ids. The donor holds different bytes for two of them,
# a longer payload for one and a shorter one for the other, so the offset
# arithmetic is exercised in both directions.
python3 - "$TMP" <<'PY'
import gzip, os, struct, sys
tmp = sys.argv[1]

def write(path, entries, aliases, encoding=1):
    count = len(entries)
    out = struct.pack("<IBBBBHH", 5, encoding, 0, 0, 0, count, len(aliases))
    offset = 12 + (count + 1) * 6 + len(aliases) * 4
    table = b""
    for rid, blob in entries:
        table += struct.pack("<HI", rid, offset)
        offset += len(blob)
    table += struct.pack("<HI", 0, offset)
    alias = b"".join(struct.pack("<HH", a, b) for a, b in aliases)
    open(path, "wb").write(out + table + alias + b"".join(b for _, b in entries))

target = [(100, b"unchanged one"),
          (200, gzip.compress(b"old bundle, short")),
          (300, b"unchanged two"),
          (400, gzip.compress(b"old html, this one is quite a lot longer")),
          (500, b"unchanged three")]
donor = [(200, gzip.compress(b"new bundle, considerably longer than before")),
         (400, gzip.compress(b"new html, shorter")),
         (300, b"unchanged two"),
         (999, b"donor only, must be skipped")]
donor.sort()
write(os.path.join(tmp, "target.pak"), target, [(9001, 0), (9002, 2)])
write(os.path.join(tmp, "donor.pak"), donor, [])
PY

out=$("$TOOL" "$TMP/target.pak" "$TMP/donor.pak" "$TMP/out.pak" \
  --expect '200:new bundle, considerably longer' \
  --expect '400:new html, shorter' 2>&1) || fail "the tool failed on a valid swap: $out"

# 1. Both differing ids swapped, and only those.
grep -Fq 'swapping 2 resource(s): [200, 400]' <<<"$out" || \
  fail "the tool did not swap exactly the two differing ids: $out"
grep -Fq 'exactly 2 changed' <<<"$out" || \
  fail "the tool did not confirm exactly two entries changed: $out"

# 2. An id the donor has and the target does not is skipped, not inserted.
# Inserting changes the resource count and the order the reader binary
# searches, and the machine renders without it today.
grep -Fq 'skipped, present in the donor and absent from the target: [999]' <<<"$out" || \
  fail "the donor-only id was not reported as skipped: $out"

# 3. The unchanged resources really are untouched, and the id set is stable.
python3 - "$TMP" <<'PY'
import gzip, struct, sys
tmp = sys.argv[1]
def parse(p):
    d = open(p, "rb").read()
    count, ac = struct.unpack_from("<HH", d, 8)
    ents = [struct.unpack_from("<HI", d, 12 + i * 6) for i in range(count + 1)]
    ab = 12 + (count + 1) * 6
    al = [struct.unpack_from("<HH", d, ab + i * 4) for i in range(ac)]
    return al, [(ents[i][0], d[ents[i][1]:ents[i + 1][1]]) for i in range(count)]

a_al, a = parse(tmp + "/target.pak")
b_al, b = parse(tmp + "/out.pak")
assert [r for r, _ in a] == [r for r, _ in b], "id order changed"
assert a_al == b_al, "alias table changed"
changed = [r for (r, x), (_, y) in zip(a, b) if x != y]
assert changed == [200, 400], "changed %s" % changed
final = dict(b)
assert gzip.decompress(final[200]) == b"new bundle, considerably longer than before"
assert gzip.decompress(final[400]) == b"new html, shorter"
assert final[100] == b"unchanged one" and final[500] == b"unchanged three"
print("pak swap test: offsets, aliases and untouched resources all hold")
PY

# 4. The verifier has to be able to fail. A tool that always reports success is
# worse than no tool, because it is trusted.
if "$TOOL" "$TMP/target.pak" "$TMP/donor.pak" "$TMP/out2.pak" \
     --expect '200:this string is not in there' >/dev/null 2>&1; then
  fail 'an unmet expectation did not fail the tool'
fi
# And it takes the file with it. A non-zero exit that leaves a plausible
# looking pak on disk is how the wrong one gets installed by somebody who read
# the filename and not the exit code.
[[ -e "$TMP/out2.pak" ]] && fail 'a failed run left its output behind'
if "$TOOL" "$TMP/target.pak" "$TMP/donor.pak" "$TMP/out3.pak" \
     --ids 4242 >/dev/null 2>&1; then
  fail 'an id absent from both paks did not fail the tool'
fi
if "$TOOL" "$TMP/target.pak" "$TMP/target.pak" "$TMP/out4.pak" >/dev/null 2>&1; then
  fail 'swapping a pak with itself should find nothing to do and fail'
fi

echo 'pak swap test: PASS'
