#!/usr/bin/env bash
# Sorting by Size ranks folders by the size the column is showing.
#
# Patch 0061 gave the Size column a real number for a folder. Sorting by that
# column then went on ignoring it, so clicking Size ranked the files and left
# every folder in name order, which answers the wrong question: the folders are
# usually where the room went.
#
# Four ways this goes wrong and none of them is visible in a screenshot:
#
# One: measuring from the comparator. A comparator runs O(n log n) times and a
# measurement is a recursive walk of the filesystem, so a single sort would
# start thousands of walks and the window would stop responding. Only the cache
# may be read here.
#
# Two: treating an unmeasured folder as zero. Every folder nobody has looked at
# would sort as empty, and the ones that are genuinely empty would be
# indistinguishable from the ones that are simply unknown.
#
# Three: losing the rule that directories precede files. That guard runs before
# anything here and reversing the two would scatter folders through the list.
#
# Four: putting the block after the metadata read, where the ordinary file path
# has already returned.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0068-files-sort-folders-by-what-they-weigh.patch"

fail() { echo "files sort by weight test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0068 is missing'
grep -Fqx '0068-files-sort-folders-by-what-they-weigh.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0068 is not listed in SERIES, so the series never applies it'

targets=$(grep -c '^diff --git ' "$PATCH")
[[ $targets -eq 1 ]] || fail "expected exactly 1 file, found ${targets}"
grep -Fq '+++ b/ui/file_manager/file_manager/foreground/js/file_list_model.ts' \
  "$PATCH" || fail 'patch 0068 does not touch file_list_model.ts'

python3 - "$PATCH" <<'PY' || exit 1
import re, sys

raw = open(sys.argv[1]).read().splitlines()

def die(msg):
    print('files sort by weight test: ' + msg, file=sys.stderr)
    raise SystemExit(1)

body = [l for l in raw if not l.startswith('+++') and not l.startswith('---')
        and not l.startswith('diff --git ')]

def strip(lines):
    """Drop comment lines. The prose above this block names every symbol the
    code below uses, so a grep run against the unstripped text would pass on
    the explanation alone.

    Line oriented on purpose. A stripper spanning /* to */ with re.S ate real
    code once already in this repository, because diff alignment can leave an
    added line holding an unbalanced /** and the next */ is then hundreds of
    lines away."""
    out = []
    for l in lines:
        s = re.sub(r'(?<![:/])//.*$', '', l)
        if s.strip():
            out.append(s)
    return '\n'.join(out)

added = strip(l[1:] for l in body if l.startswith('+'))
# Added lines plus untouched context: what the function reads like afterwards.
post = strip(l[1:] for l in body if l.startswith('+') or l.startswith(' '))

# --- the cache is imported, and from the module that owns it ----------------

if not re.search(r'^import \{[^}]*\bauraDeMeasuredFolderSize\b[^}]*\} '
                 r"from '\./aurade_folder_size\.js';", added, re.M):
    die('auraDeMeasuredFolderSize is not imported from ./aurade_folder_size.js, '
        'so the comparator references a name that does not exist and sorting by '
        'Size throws')

# --- it reads the cache, for both sides -------------------------------------

for side in ('a', 'b'):
    if 'auraDeMeasuredFolderSize(%s)' % side not in added:
        die('the comparator never reads the cached size of %s, so it cannot be '
            'ordering by it' % side)

# --- and never starts a walk from inside a comparator -----------------------

if re.search(r'\bauraDeMeasureFolderSize\s*\(', added):
    die('the comparator calls auraDeMeasureFolderSize, which walks the '
        'filesystem. A comparator runs O(n log n) times, so one sort becomes '
        'thousands of recursive walks and the window stops responding')

# --- an unknown size is not a zero ------------------------------------------

if not re.search(r'aMeasured !== undefined\s*&&\s*bMeasured !== undefined',
                 added):
    die('the comparator does not require both sizes to be known before '
        'ordering by them, so a folder nobody has measured sorts as undefined '
        'and the comparison is not a number')
if re.search(r'[ab]Measured\s*(\|\||\?\?)\s*0', added):
    die('an unmeasured folder is coerced to 0, which sorts every folder nobody '
        'has looked at alongside the genuinely empty ones')
if not re.search(r'return compareName\(a, b\);', added):
    die('the comparator does not fall back to name order, so folders whose '
        'sizes are unknown or equal come back in whatever order they arrived')

# --- the block is a directory only path -------------------------------------

if not re.search(r'if \(a\.isDirectory && b\.isDirectory\) \{', added):
    die('the new block is not guarded on both entries being directories, so it '
        'runs for ordinary files, whose size never reaches this cache and is '
        'therefore always undefined')

# --- and it sits between the two lines it has to sit between ----------------
#
# All three are context the patch carries, so this is an assertion about where
# the block landed and not about the rest of the file. It is why 0068 is
# generated with -U10: at the default width a block moved far enough out of
# place takes one of the anchors out of the hunk with it, and then the check
# below cannot run and the die above fires instead. Both catch it, but only one
# of them says what is actually wrong.

guard = post.find('a.isDirectory === this.isDescendingOrder_')
block = post.find('if (a.isDirectory && b.isDirectory)')
meta = post.find("this.metadataModel_.getCache([a, b], ['size'])")
if guard < 0 or block < 0 or meta < 0:
    die('cannot locate the comparator: the patch no longer carries the '
        'directories-precede-files guard, the new block and the metadata read '
        'as context, so where the block landed cannot be checked')
if not guard < block:
    die('the new block runs before the rule that directories precede files, so '
        'folders and files interleave')
if not block < meta:
    die('the new block sits after the metadata size read, where the ordinary '
        'file path has already returned, so it never runs')
PY

grep -nP '[\x{2014}\x{2013}]' "$PATCH" && \
  fail 'patch 0068 contains an em dash or an en dash' || true

echo 'files sort by weight test: PASS '\
'(reads the cache for both sides, never walks from a comparator, keeps an '\
'unknown size out of the ordering, falls back to name, and sits between the '\
'directory guard and the metadata read)'
