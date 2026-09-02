#!/usr/bin/env bash
# Remembering your place in a folder, and the five ways it turns into a bug.
#
# One, restoring more than the scroll. Putting the selection or the focused row
# back as well would change what the next command acts on. A delete or a rename
# aimed at a row the app chose rather than the person did is far worse than a
# list that starts at the top, so this restores the view and nothing else.
#
# Two, restoring too early. directory-changed fires while the list still holds
# the previous folder's rows, so a position applied there lands on the wrong
# content. It has to wait for the scan, and then for a frame, because the scan
# completes before the rows have geometry and the assignment would be clamped
# against a stale height.
#
# Three, growing without bound. A map keyed by folder in a session left open
# for a week is a leak unless it is capped and evicts the coldest entry.
#
# Four, a stale key. The pending key must be cleared as it is used, or a later
# scan belonging to a different folder picks up a position meant for this one.
#
# Five, scrolling past the end. A folder can shrink while it is away.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0059-files-remember-your-place.patch"

fail() { echo "files scroll memory test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0059 is missing'
grep -Fqx '0059-files-remember-your-place.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0059 is not listed in SERIES'

targets=$(grep -c '^diff --git ' "$PATCH")
[[ $targets -eq 1 ]] || fail "expected exactly 1 file, found ${targets}"
grep -Fq '+++ b/ui/file_manager/file_manager/foreground/js/app_state_controller.ts' "$PATCH" || \
  fail 'patch 0059 does not touch app_state_controller.ts'
grep -q '^--- /dev/null$' "$PATCH" && \
  fail 'patch 0059 creates a new file, which can never reach a machine through a pak swap'

python3 - "$PATCH" <<'PY' || exit 1
import re, sys

added, ctx = [], []
for line in open(sys.argv[1]).read().splitlines():
    if line.startswith('+++') or line.startswith('---') or line.startswith('diff --git'):
        continue
    if line.startswith('+'):
        added.append(line[1:]); ctx.append(line[1:])
    elif line.startswith(' '):
        ctx.append(line[1:])

def die(msg):
    print(f'files scroll memory test: {msg}', file=sys.stderr)
    raise SystemExit(1)

def strip(text):
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    return re.sub(r'(?<![:/])//.*$', '', text, flags=re.M)

code = strip('\n'.join(added))
post = strip('\n'.join(ctx))

# --- the view only, never the selection -------------------------------------

for forbidden in ('selectedIndex', 'selectionModel', 'selectedItem',
                  'leadIndex', 'focus()', 'activate('):
    if forbidden in code:
        die(f'the restore touches {forbidden}; putting the selection back '
            'changes what the next command acts on, which is a far worse bug '
            'than starting at the top')

if 'scrollTop' not in code:
    die('nothing restores a scroll position at all')

# --- restored after the scan, and after a frame -----------------------------

if "'cur-dir-scan-completed'" not in code:
    die('the restore is not hung off the scan completing, so it would apply '
        "to the previous folder's rows")
if 'requestAnimationFrame' not in code:
    die('the position is applied in the same turn as the scan, before the rows '
        'have geometry, so it is clamped against a stale height')

# --- bounded, and evicts the coldest ----------------------------------------

if not re.search(r'AURADE_SCROLL_MEMORY_LIMIT\s*=\s*\d+', post):
    die('the memory has no limit, so a long session grows it without bound')
if 'while' not in code or 'delete' not in code:
    die('nothing evicts from the map once it is over the limit')
# Deleting before writing is what makes a rewrite move the key to the end of
# the insertion order, which is what makes the eviction least recently used
# rather than oldest ever seen.
delete_pos = code.find('this.auraDeScrollTops_.delete(previousKey)')
set_pos = code.find('this.auraDeScrollTops_.set(previousKey')
if delete_pos < 0 or set_pos < 0:
    die('the remember path does not both delete and set the key')
if delete_pos > set_pos:
    die('the key is written before it is deleted, so re-entering a folder does '
        'not refresh its position in the insertion order and the eviction '
        'drops the wrong entry')

# --- the pending key is cleared as it is used -------------------------------

if not re.search(r'const key = this\.auraDePendingScrollKey_;\s*\n\s*'
                 r'this\.auraDePendingScrollKey_ = null;', code):
    die('the pending key is not taken and cleared together, so a later scan '
        'for another folder could apply a position meant for this one')

# --- never past the end -----------------------------------------------------

if 'Math.min' not in code:
    die('the position is not clamped, so a folder that shrank while it was '
        'away would be scrolled past its end')
if 'scrollHeight' not in code or 'clientHeight' not in code:
    die('the clamp is not computed from the list geometry')

# --- a folder at the top costs nothing --------------------------------------

if not re.search(r'if\s*\(\s*top\s*>\s*0\s*\)', code):
    die('a folder sitting at the top is still stored, spending a slot to say '
        'there is nothing to restore')

print('files scroll memory test: PASS '
      '(view only, after the scan and a frame, bounded and least recently '
      'used, pending key cleared, clamped to the list)')
PY
