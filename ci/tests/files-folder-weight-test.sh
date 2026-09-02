#!/usr/bin/env bash
# What the files in this folder weigh, and the eight ways it goes wrong.
#
# One: counting the folders. A directory's size in this metadata is the size of
# the directory record, not of what is inside it. Adding those in produces a
# number that is wrong by an amount nobody can see.
#
# Two: not saying so. Leaving the folders out silently makes a short number
# look like a total. The wording has to change when there are folders present.
#
# Three: a partial total. The scan prefetches sizes in chunks and the last of
# them can still be in flight, so a size that has not arrived has to mean "say
# nothing", never "zero".
#
# Four: an infinite fetch. Asking for the missing sizes and repainting is what
# makes the number appear; doing it without a key means a file whose size never
# arrives fetches, repaints, finds the cache still short, and fetches again for
# as long as the folder is open.
#
# Five: a late answer painting the wrong folder. The repaint has to check that
# the folder that asked is still the folder on screen.
#
# Six: losing the forty two note. It is rarer and more interesting than a
# housekeeping hint and has to win the tooltip.
#
# Seven: a stale hint. The detail has to be cleared on the way in, or a folder
# with no subfolders inherits the previous folder's hint.
#
# Eight: a hole. A list read mid splice hands back undefined, and a total that
# stepped over it would be quietly short.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0062-files-what-this-folder-weighs.patch"

fail() { echo "files folder weight test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0062 is missing'
grep -Fqx '0062-files-what-this-folder-weighs.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0062 is not listed in SERIES'

targets=$(grep -c '^diff --git ' "$PATCH")
[[ $targets -eq 2 ]] || fail "expected exactly 2 files, found ${targets}"

for f in ui/file_manager/file_manager/foreground/js/toolbar_controller.ts \
         ui/file_manager/file_manager/foreground/js/file_manager.ts; do
  grep -Fq "+++ b/$f" "$PATCH" || fail "patch 0062 does not touch $f"
done

python3 - "$PATCH" <<'PY' || exit 1
import re, sys

raw = open(sys.argv[1]).read().splitlines()

def die(msg):
    print(f'files folder weight test: {msg}', file=sys.stderr)
    raise SystemExit(1)

sections, cur = {}, None
for line in raw:
    if line.startswith('diff --git '):
        cur = line.split(' b/')[-1]
        sections[cur] = []
    elif cur:
        sections[cur].append(line)

def added(path):
    return '\n'.join(l[1:] for l in sections.get(path, [])
                     if l.startswith('+') and not l.startswith('+++'))

def strip(text):
    """Comments explain the code and would satisfy a grep for it on their own."""
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    return re.sub(r'(?<![:/])//.*$', '', text, flags=re.M)

TC = 'ui/file_manager/file_manager/foreground/js/toolbar_controller.ts'
FM = 'ui/file_manager/file_manager/foreground/js/file_manager.ts'

tc = strip(added(TC))
fm = strip(added(FM))

# --- the controller is actually given a metadata model ----------------------

if not re.search(r'private metadataModel_: MetadataModel', tc):
    die('the controller never takes a metadata model, so it has no source for '
        'the sizes')
if not re.search(r'this\.ui_, this\.metadataModel_\)', fm):
    die('the metadata model is never passed in at the construction site, so '
        'the parameter is undefined at runtime')

# --- folders are counted apart, never totalled ------------------------------

if not re.search(r'if \(entry\.isDirectory\) \{\s*\n\s*folders\+\+;', tc):
    die('directories are not separated out, so their directory record size is '
        'added to the total as though it were their contents')

# --- the wording says what was counted --------------------------------------

if not re.search(r'if \(folders === 0\) \{\s*\n\s*return total;', tc):
    die('the bare total is not reserved for a folder with no subfolders, so '
        'either every folder claims a full total or none of them do')
if 'in 1 file' not in tc or 'files.length.toLocaleString()} files' not in tc:
    die('the total never says how many files it covers, so a short number is '
        'presented as the whole folder')
if 'right click menu' not in tc:
    die('nothing tells the reader how to find out what the uncounted folders '
        'hold, which is the one thing the hint is for')

# --- a missing size means silence, not zero ---------------------------------

if not re.search(
        r"if \(typeof size !== 'number' \|\| !isFinite\(size\) \|\| size < 0\) \{"
        r"[^}]*?return '';", tc, re.S):
    die('a size that has not arrived does not stop the total, so it is counted '
        'as zero and the folder reads lighter than it is')

# --- the fetch cannot loop --------------------------------------------------

if not re.search(r'if \(this\.auraDeWeightKey_ === key\) \{\s*\n\s*return;', tc):
    die('the fetch is not keyed, so a file whose size never arrives fetches and '
        'repaints for as long as the folder stays open')
if not re.search(r'this\.auraDeWeightKey_ = key;\s*\n\s*this\.metadataModel_\.get\(',
                 tc):
    die('the key is not claimed before the fetch starts, so two repaints in the '
        'same tick both fetch')
if not re.search(r'files\.length\}`', tc):
    die('the key does not include the number of rows, so a splice into the same '
        'folder never asks again and the total stays blank')

# --- a late answer cannot paint another folder ------------------------------

if not re.search(r'\.then\(\(\) => \{\s*\n\s*if \(this\.auraDeWeightKey_ === key\)',
                 tc):
    die('the repaint after the fetch is not guarded, so one folder total can '
        'land under another folder name')

# --- forty two still wins the tooltip ---------------------------------------

if not re.search(
        r'count\.title = this\.filesSelectedLabel_\.title \|\| '
        r'this\.auraDeCountDetail_', tc):
    die('the forty two note no longer takes precedence over the housekeeping '
        'hint, or has been dropped entirely')

# --- no stale hint ----------------------------------------------------------

if not re.search(r"auraDeDirectoryWeight_\(\): string \{\s*\n\s*"
                 r"this\.auraDeCountDetail_ = '';", tc):
    die('the hover detail is not cleared on the way in, so a folder with no '
        'subfolders keeps the previous folder count on its tooltip')

# --- a hole in the list is not stepped over ---------------------------------

if not re.search(r"if \(!entry\) \{\s*\n\s*return '';", tc):
    die('a list read mid splice hands back undefined and the total steps over '
        'it, so the number is quietly short')

print('files folder weight test: PASS '
      '(model wired in, folders separated, wording honest, no partial total, '
      'fetch keyed and guarded, forty two wins, no stale hint, holes refused)')
PY
