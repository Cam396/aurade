#!/usr/bin/env bash
# The Files window reaches the pak from the build, and cannot reach it wrong.
#
# ci/pak-set-resources.py already refuses a page that asks for a path the page
# it replaces never asked for, and pak-set-test.sh proves that refusal fires.
# What that leaves is the wiring: a build step that calls the tool, from the
# stock pak every time, and never with --allow-new-paths. The two paks that
# shipped a page which drew and did nothing were both made by hand, so this
# tests the step rather than the tool.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
STEP="$ROOT/ci/build-files-pak.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fail() { echo "files pak test: $*" >&2; exit 1; }
[[ -x $STEP ]] || fail 'ci/build-files-pak.sh is missing or not executable'
command -v python3 >/dev/null 2>&1 || fail 'python3 is not installed'

# A pak shaped like the one the Files app is served from: the page slot holds
# the text the step finds it by and names the script path it is served at, the
# script slot holds the needle, and the rest must come through untouched.
mkdir -p "$TMP/out"
python3 - "$TMP/out/resources.pak" <<'PY'
import gzip, struct, sys
def write(path, entries, aliases, encoding=1):
    count = len(entries)
    head = struct.pack("<IBBBBHH", 5, encoding, 0, 0, 0, count, len(aliases))
    offset = 12 + (count + 1) * 6 + len(aliases) * 4
    table = b""
    for rid, blob in entries:
        table += struct.pack("<HI", rid, offset); offset += len(blob)
    table += struct.pack("<HI", 0, offset)
    alias = b"".join(struct.pack("<HH", a, b) for a, b in aliases)
    open(path, "wb").write(head + table + alias + b"".join(b for _, b in entries))
write(sys.argv[1], [
    (100, b"another webui, left alone"),
    (200, gzip.compress(b"the old bundle, auraDeExactTime lives here")),
    (300, gzip.compress(b'<!DOCTYPE HTML><script src="chrome://file-manager/init_globals.js">'
                        b'</script><script type="module" '
                        b'src="chrome://file-manager/foreground/js/main.js"></script>')),
    (400, b"and another, left alone"),
], [(9001, 0)])
PY
cp -a "$TMP/out/resources.pak" "$TMP/original.pak"

carries() { python3 - "$1" <<'PY'
import gzip, struct, sys
d = open(sys.argv[1], "rb").read()
count, = struct.unpack_from("<H", d, 8)
e = [struct.unpack_from("<HI", d, 12 + i * 6) for i in range(count + 1)]
for i in range(count):
    p = d[e[i][1]:e[i + 1][1]]
    if p[:2] == b"\x1f\x8b":
        try: p = gzip.decompress(p)
        except Exception: continue
    if b'data-path="~"' in p: sys.exit(0)
sys.exit(1)
PY
}

# 1. The valid run places the page and keeps the stock pak beside it.
"$STEP" "$TMP/out" >"$TMP/run1.log" 2>&1 || fail "the step failed: $(cat "$TMP/run1.log")"
carries "$TMP/out/resources.pak" || fail 'the page did not reach the pak'
[[ -f $TMP/out/resources.pak.pre-aurade ]] || fail 'the stock pak was not kept'
cmp -s "$TMP/out/resources.pak.pre-aurade" "$TMP/original.pak" \
  || fail 'the kept pak is not the stock one'

# 2. Twice is the same as once: the second run starts from the stock pak, not
#    from its own output, or each build would layer on the last.
cp -a "$TMP/out/resources.pak" "$TMP/first.pak"
"$STEP" "$TMP/out" >/dev/null 2>&1 || fail 'the second run failed'
cmp -s "$TMP/first.pak" "$TMP/out/resources.pak" || fail 'the step is not idempotent'

# 3. The script path is the one the page it replaces asked for. This is the
#    failure that looks like success, so the step must not be able to produce
#    it: a path the old page never named is refused and nothing is written.
cp -a "$TMP/original.pak" "$TMP/out/resources.pak"
rm -f "$TMP/out/resources.pak.pre-aurade"
if AURADE_FILES_PAGE_SCRIPT='foreground/js/main.rollup.js' \
     "$STEP" "$TMP/out" >"$TMP/run3.log" 2>&1; then
  fail 'a script path the page never asked for was accepted'
fi
if carries "$TMP/out/resources.pak"; then
  fail 'the refused run still wrote the page into the pak'
fi

# 4. A pak that already holds the page is not snapshotted as the stock one,
#    or the page becomes its own baseline and the SWA's page is unrecoverable.
cp -a "$TMP/first.pak" "$TMP/out/resources.pak"
rm -f "$TMP/out/resources.pak.pre-aurade"
if "$STEP" "$TMP/out" >"$TMP/run4.log" 2>&1; then
  fail 'a pak already holding the page was taken as stock'
fi
grep -q 'stock pak cannot be recovered' "$TMP/run4.log" \
  || fail "the refusal did not say why: $(cat "$TMP/run4.log")"

echo 'files pak test: PASS'
