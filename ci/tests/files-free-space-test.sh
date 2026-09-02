#!/usr/bin/env bash
# Free space in the status bar, and the five ways it goes wrong quietly.
#
# One, the query cadence. updateSelectionLabel_ runs on every selection change,
# so hanging the refresh off it would mean a filesystem query per arrow key.
# Free space can only move when the contents move or the volume does, so the
# refresh has to be bound to those events and to nothing else.
#
# Two, the race. The query is asynchronous and the user can leave the folder
# while it is in flight. Without a request number the late answer paints the
# previous volume's figure onto the current one, which is worse than a blank.
#
# Three, the volumes that have no answer. Provided filesystems, media views and
# archives have no size worth reporting. Drive has one but it comes from a
# quota API rather than the filesystem, and asking for it here would add a
# network round trip to every directory scan.
#
# Four, the failure text. The gear menu can say "Failed to retrieve space info"
# because somebody opened it on purpose. A bar that is on screen permanently
# cannot; it has to fall silent.
#
# Five, the copy. SPACE_AVAILABLE is already translated into every locale the
# OS ships. Writing fresh English here would be the only untranslated string in
# the window.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0056-files-status-bar-free-space.patch"

fail() { echo "files free space test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0056 is missing'
grep -Fqx '0056-files-status-bar-free-space.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0056 is not listed in SERIES'

# --- exactly the three files it needs ---------------------------------------

targets=$(grep -c '^diff --git ' "$PATCH")
[[ $targets -eq 3 ]] || fail "expected exactly 3 files, found ${targets}"

for f in main.html foreground/css/file_manager.css \
         foreground/js/toolbar_controller.ts; do
  grep -Fq "+++ b/ui/file_manager/file_manager/$f" "$PATCH" || \
    fail "patch 0056 does not touch $f"
done

grep -q '^--- /dev/null$' "$PATCH" && \
  fail 'patch 0056 creates a new file, which can never reach a machine through a pak swap'

grep -Fq '+                  <span id="aurade-status-space"></span>' "$PATCH" || \
  fail 'the free space span is not added to main.html'

python3 - "$PATCH" <<'PY' || exit 1
import re, sys

raw = open(sys.argv[1]).read().splitlines()

def die(msg):
    print(f'files free space test: {msg}', file=sys.stderr)
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

def removed(path):
    return [l[1:] for l in sections.get(path, [])
            if l.startswith('-') and not l.startswith('---')]

CSS = 'ui/file_manager/file_manager/foreground/css/file_manager.css'
TS = 'ui/file_manager/file_manager/foreground/js/toolbar_controller.ts'

css_added = added(CSS)
css = '\n'.join(css_added)
ts_added = added(TS)

# Comments explain the rules below. Strip them so no check can pass on the
# sentence describing it rather than on the code doing it.
def strip_comments(text):
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    # Trailing comments count too. A check that only stripped whole comment
    # lines would pass on "false) // VolumeType.DRIVE", which is the comment
    # explaining the rule sitting where the code enforcing it used to be. The
    # lookbehind spares "chrome://resources/..." in the import paths.
    return re.sub(r'(?<![:/])//.*$', '', text, flags=re.M)

ts = strip_comments('\n'.join(ts_added))
css_code = strip_comments(css)

# --- the bar keeps theming --------------------------------------------------

hexes = re.findall(r'#[0-9a-fA-F]{3,8}\b', css_code)
if hexes:
    die(f'the free space CSS hardcodes {", ".join(sorted(set(hexes)))} '
        'instead of inheriting the bar\'s token')

# --- the layout, now that three spans share two ends ------------------------

if 'justify-content: space-between;' not in '\n'.join(removed(CSS)):
    die('space-between is still on the bar; with the middle span empty it '
        'centres whichever of the two right hand spans has text')
if not re.search(r'#aurade-status-count\s*\{[^}]*margin-inline-end:\s*auto',
                 css_code, re.S):
    die('the count does not push the other spans away, so the free space '
        'would not sit at the end of the bar')
if '#aurade-status-space' not in css_code:
    die('the free space span is never styled')

# --- the refresh is bound to content, never to selection --------------------

binds = [i for i, l in enumerate(ts_added)
         if 'auraDeRefreshFreeSpace_.bind(this)' in l]
if len(binds) != 3:
    die(f'expected 3 refresh listeners, found {len(binds)}')

wanted = {'cur-dir-scan-completed', 'cur-dir-rescan-completed', "'splice'"}
seen = set()
for i in binds:
    context = '\n'.join(ts_added[max(0, i - 2):i + 1])
    for name in wanted:
        if name in context:
            seen.add(name)
if seen != wanted:
    die('the refresh is not bound to exactly the content and directory '
        f'events; matched {sorted(seen)}')

for selection_event in ('EventType.CHANGE', 'onSelectionChanged_'):
    if re.search(re.escape(selection_event) + r'.{0,120}auraDeRefreshFreeSpace_',
                 ts, re.S):
        die('the refresh is wired to a selection change, which would query '
            'the filesystem once per keypress')

# --- the race guard ---------------------------------------------------------

if '++this.auraDeSpaceRequest_' not in ts:
    die('no request number is taken, so a slow answer cannot be told from a '
        'current one')
if not re.search(r'if\s*\(\s*request\s*!==\s*this\.auraDeSpaceRequest_\s*\)', ts):
    die('a late answer is never discarded, so leaving a folder mid query '
        'paints the old volume\'s figure onto the new one')

# --- the volumes that have no answer ----------------------------------------

for volume in ('PROVIDED', 'MEDIA_VIEW', 'ARCHIVE', 'DRIVE'):
    if f'VolumeType.{volume}' not in ts:
        die(f'{volume} is not excluded, so the bar would report a figure that '
            'is either unknowable or fetched over the network')

# --- a failure is silent, not loud ------------------------------------------

if 'FAILED_SPACE_INFO' in ts:
    die('a failed query writes an error into a bar that is on screen '
        'permanently; it has to fall silent instead')
if 'catch' not in ts:
    die('the query is not guarded, so a rejected promise becomes an '
        'unhandled rejection on every scan of an unreadable volume')

# --- the copy is the translated one -----------------------------------------

if "'SPACE_AVAILABLE'" not in ts:
    die('the bar does not reuse the translated SPACE_AVAILABLE string')
if 'bytesToString(' not in ts:
    die('the byte count is not run through bytesToString, so it would not be '
        'formatted or localised like every other size in the app')

# --- the two right hand spans share one slot --------------------------------

if 'hasSelection' not in ts:
    die('the free space and the selection do not share the slot, so they '
        'would overprint each other')

print('files free space test: PASS '
      '(3 files, content bound refresh, race guarded, 4 volume types excluded, '
      'silent on failure, translated copy)')
PY
