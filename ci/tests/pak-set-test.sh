#!/usr/bin/env bash
# The page placed into a pak, against a pak built for the test.
#
# Same rule as the swap tool's test: resources.pak carries every WebUI on the
# system, so the tool's own assertions have to be shown to fire, and a failed
# run must leave nothing behind that looks like a pak.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TOOL="$ROOT/ci/pak-set-resources.py"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fail() { echo "pak set test: $*" >&2; exit 1; }
[[ -r $TOOL ]] || fail 'ci/pak-set-resources.py is missing'

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

# The html slot is found by a text only it holds; "shared marker" is in two
# resources, so asking for it must be refused.
# The old page names the script path it is served at; a replacement has to
# ask for that same path, because nothing in a pak says what path a resource
# has and a path that does not resolve leaves a page that renders and does
# nothing.
target = [(100, b"unchanged one, shared marker"),
          (200, gzip.compress(b"the old bundle, run().then(fileManager.start)")),
          (300, b"unchanged two, shared marker"),
          (400, gzip.compress(b'<!DOCTYPE HTML> old page with init_globals.js'
                              b' in it <script src="foreground/js/main.js">'
                              b'</script>')),
          (500, b"unchanged three")]
write(os.path.join(tmp, "target.pak"), target, [(9001, 0), (9002, 2)])
open(os.path.join(tmp, "files.html"), "wb").write(b'<meta charset="utf-8"><div class="win" data-path="~"></div><script src="foreground/js/main.js"></script>' * 40)
open(os.path.join(tmp, "files-wrong-path.html"), "wb").write(b'<meta charset="utf-8"><div class="win" data-path="~"></div><script src="foreground/js/main.rollup.js"></script>' * 40)
open(os.path.join(tmp, "files.js"), "wb").write(b"(() => { enterLive(); })();\n")
PY

out=$("$TOOL" "$TMP/target.pak" "$TMP/out.pak" \
  --set "init_globals.js=$TMP/files.html" \
  --set "run().then(fileManager.start)=$TMP/files.js" \
  --expect 'files.html:foreground/js/main.js' \
  --expect 'files.js:enterLive();' 2>&1) || fail "the tool failed on a valid run: $out"

grep -Fq 'files.html -> resource 400' <<<"$out" || fail "the page did not land in the html slot: $out"
grep -Fq 'files.js -> resource 200' <<<"$out" || fail "the script did not land in the bundle slot: $out"
grep -Fq '2 placed' <<<"$out" || fail "the tool did not report two placements: $out"

# The unchanged resources really are untouched, the placed ones come back out
# intact, and the id set and the alias table are stable.
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
assert gzip.decompress(final[400]) == open(tmp + "/files.html", "rb").read()
assert gzip.decompress(final[200]) == open(tmp + "/files.js", "rb").read()
assert final[100] == b"unchanged one, shared marker" and final[500] == b"unchanged three"
print("pak set test: offsets, aliases and untouched resources all hold")
PY

# The verifier has to be able to fail, and a failed run leaves no output.
if "$TOOL" "$TMP/target.pak" "$TMP/out2.pak" --set "shared marker=$TMP/files.js" >/dev/null 2>&1; then
  fail 'a text held by two resources did not fail the tool'
fi
[[ -e "$TMP/out2.pak" ]] && fail 'a failed run left its output behind'
if "$TOOL" "$TMP/target.pak" "$TMP/out3.pak" --set "no such text anywhere=$TMP/files.js" >/dev/null 2>&1; then
  fail 'a text held by no resource did not fail the tool'
fi
if "$TOOL" "$TMP/target.pak" "$TMP/out4.pak" --set "init_globals.js=$TMP/files.html" \
     --expect 'files.html:this string is not in there' >/dev/null 2>&1; then
  fail 'an unmet expectation did not fail the tool'
fi
[[ -e "$TMP/out4.pak" ]] && fail 'a failed expectation left its output behind'

# A page whose script asks for a path the page it replaces never asked for.
# The pak says nothing about what path a resource is served at, so such a
# page renders from its inline markup and never runs, which is the one
# failure that looks like success. Refused by default, allowed on request.
if "$TOOL" "$TMP/target.pak" "$TMP/out5.pak" \
     --set "init_globals.js=$TMP/files-wrong-path.html" \
     --set "run().then(fileManager.start)=$TMP/files.js" >/dev/null 2>&1; then
  fail 'a script path the old page never asked for did not fail the tool'
fi
[[ -e "$TMP/out5.pak" ]] && fail 'the refused path left its output behind'
"$TOOL" "$TMP/target.pak" "$TMP/out6.pak" --allow-new-paths \
   --set "init_globals.js=$TMP/files-wrong-path.html" \
   --set "run().then(fileManager.start)=$TMP/files.js" >/dev/null 2>&1 \
  || fail 'the escape hatch did not let a new path through'
[[ -e "$TMP/out6.pak" ]] || fail 'the escape hatch wrote nothing'

echo 'pak set test: PASS'
