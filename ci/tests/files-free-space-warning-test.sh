#!/usr/bin/env bash
# The low space warning, and the four ways a threshold like this goes wrong.
#
# One, a percentage on its own. A tenth of a two terabyte disk is two hundred
# gigabytes, and warning somebody with that much room left teaches them to
# ignore the warning.
#
# Two, an absolute on its own. Twenty gigabytes is most of the eMMC these
# machines ship with, so the warning would come on at the factory and never go
# off again.
#
# Taking the smaller of the two is right on both, which is why this fixture
# insists on Math.min of a fraction and a constant rather than either alone.
#
# Three, the tint outliving the text. The span is shared with the selection, so
# every path that clears the text has to clear the class and the title with it,
# or an empty span keeps a warning colour and a stale tooltip.
#
# Four, the colour. A full disk is a thing to see coming, so it is the warning
# role and not the error one, and it comes from a token so it themes.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0057-files-free-space-detail-and-warning.patch"

fail() { echo "files free space warning test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0057 is missing'
grep -Fqx '0057-files-free-space-detail-and-warning.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0057 is not listed in SERIES'

targets=$(grep -c '^diff --git ' "$PATCH")
[[ $targets -eq 2 ]] || fail "expected exactly 2 files, found ${targets}"

for f in foreground/css/file_manager.css foreground/js/toolbar_controller.ts; do
  grep -Fq "+++ b/ui/file_manager/file_manager/$f" "$PATCH" || \
    fail "patch 0057 does not touch $f"
done

grep -q '^--- /dev/null$' "$PATCH" && \
  fail 'patch 0057 creates a new file, which can never reach a machine through a pak swap'

python3 - "$PATCH" <<'PY' || exit 1
import re, sys

raw = open(sys.argv[1]).read().splitlines()

def die(msg):
    print(f'files free space warning test: {msg}', file=sys.stderr)
    raise SystemExit(1)

sections, cur = {}, None
for line in raw:
    if line.startswith('diff --git '):
        cur = line.split(' b/')[-1]
        sections[cur] = []
    elif cur:
        sections[cur].append(line)

def added(path):
    return [l[1:] for l in sections.get(path, [])
            if l.startswith('+') and not l.startswith('+++')]

def post(path):
    # Added lines plus untouched context: what the file looks like after the
    # patch, within the hunks it touches. The request guard lives here rather
    # than in added(), because this patch grows the signature above it and
    # leaves the guard itself alone.
    return [l[1:] if l[:1] in '+ ' else '' for l in sections.get(path, [])
            if not l.startswith('+++') and not l.startswith('---')
            and l[:1] in '+ ']

CSS = 'ui/file_manager/file_manager/foreground/css/file_manager.css'
TS = 'ui/file_manager/file_manager/foreground/js/toolbar_controller.ts'

def strip_comments(text):
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    # Trailing comments count too, or a check passes on the sentence describing
    # the rule sitting where the code enforcing it used to be. The lookbehind
    # spares chrome:// style paths.
    return re.sub(r'(?<![:/])//.*$', '', text, flags=re.M)

css = strip_comments('\n'.join(added(CSS)))
ts = strip_comments('\n'.join(added(TS)))
ts_post = strip_comments('\n'.join(post(TS)))

# --- the threshold ----------------------------------------------------------

m = re.search(r'Math\.min\(([^;]*?)\)\s*;', ts, re.S)
if not m:
    die('the low water mark is not Math.min of two terms, so it is either a '
        'bare percentage or a bare byte count and wrong on one disk size or '
        'the other')
terms = m.group(1)
if not re.search(r'totalSize\s*\*\s*0?\.\d+', terms):
    die('the low water mark has no fraction of the disk in it')
if not re.search(r'\d+\s*\*\s*1024\s*\*\s*1024\s*\*\s*1024', terms):
    die('the low water mark has no absolute byte ceiling in it')

if not re.search(r'remaining\s*<\s*lowWater', ts):
    die('nothing is compared against the low water mark')

# --- the colour -------------------------------------------------------------

hexes = re.findall(r'#[0-9a-fA-F]{3,8}\b',
                   re.sub(r'#aurade[\w-]*', '', css))
if hexes:
    die(f'the warning tint hardcodes {", ".join(sorted(set(hexes)))} '
        'instead of a theme token')
if '--cros-sys-warning' not in css:
    die('the low state does not use the warning token')
if '--cros-sys-error' in css:
    die('a nearly full disk uses the error role, which is for something that '
        'has already failed rather than something to see coming')

# --- the tint and the tooltip never outlive the text ------------------------

toggles = re.findall(r"classList\.toggle\(\s*'aurade-space-low'", ts)
if len(toggles) < 2:
    die(f'the low class is toggled in {len(toggles)} place(s); both the '
        'refresh and the shared slot have to set it, or a selection leaves a '
        'warning colour on an empty span')

if not re.search(r"hasSelection\s*\?\s*''\s*:\s*this\.auraDeSpaceDetail_", ts):
    die('the tooltip is not cleared when the selection takes the slot, so an '
        'empty span keeps a stale hover')

if not re.search(r'!hasSelection\s*&&\s*this\.auraDeSpaceLow_', ts):
    die('the low class is not gated on there being no selection')

# --- the detail is remembered, not refetched --------------------------------

for field in ('auraDeSpaceDetail_', 'auraDeSpaceLow_'):
    if f'this.{field} =' not in ts:
        die(f'{field} is never remembered, so deselecting would have to ask '
            'the filesystem again')

# --- the race guard survived the signature change ---------------------------

if not re.search(r'if\s*\(\s*request\s*!==\s*this\.auraDeSpaceRequest_\s*\)',
                 ts_post):
    die('the request guard was dropped when the setter grew arguments')

# --- the hover says the same thing the gear menu says -----------------------

if '% used' not in ts:
    die('the hover detail does not report how much of the disk is used')
if 'bytesToString(stats.totalSize)' not in ts:
    die('the hover detail never renders the size of the disk, which is the '
        'thing that makes the available figure mean anything. Checking for '
        'totalSize alone is not enough: the threshold maths mentions it too.')

print('files free space warning test: PASS '
      '(min of fraction and ceiling, warning token, tint and tooltip cleared '
      'with the text, request guard intact)')
PY
