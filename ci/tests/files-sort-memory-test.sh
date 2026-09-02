#!/usr/bin/env bash
# A folder keeps the order you put it in, and the six ways it goes wrong.
#
# One, and worst: reading back your own sort. The sorted event does not say who
# asked for it. Applying a folder's remembered order without a guard is read as
# a fresh choice, copied into the app wide preference, and from there onto every
# folder that has no order of its own. One visit to a folder sorted by size
# quietly resorts the whole app.
#
# Two: a guard that sticks. If a throw inside the sort leaves the flag set,
# every order the user chooses afterwards is silently discarded as one of ours.
#
# Three: falling back to whatever the previous folder was showing instead of to
# the default. Which order an unsorted folder opens in would then depend on the
# route taken to it.
#
# Four: sorting when nothing has changed. The sorted event fires and the list
# rebuilds every row for no change at all.
#
# Five: a cache that is not really an LRU. A Map keeps insertion order, so
# writing a key that is already there leaves it at the front and the eviction
# discards the folder most recently used.
#
# Six: unbounded growth. A window left open for a week would keep an order for
# every folder it ever visited.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0063-files-a-folder-keeps-its-order.patch"

fail() { echo "files sort memory test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0063 is missing'
grep -Fqx '0063-files-a-folder-keeps-its-order.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0063 is not listed in SERIES'

targets=$(grep -c '^diff --git ' "$PATCH")
[[ $targets -eq 1 ]] || fail "expected exactly 1 file, found ${targets}"

grep -Fq '+++ b/ui/file_manager/file_manager/foreground/js/app_state_controller.ts' \
  "$PATCH" || fail 'patch 0063 does not touch app_state_controller.ts'

python3 - "$PATCH" <<'PY' || exit 1
import re, sys

raw = open(sys.argv[1]).read().splitlines()

def die(msg):
    print(f'files sort memory test: {msg}', file=sys.stderr)
    raise SystemExit(1)

added = '\n'.join(l[1:] for l in raw
                  if l.startswith('+') and not l.startswith('+++'))
post = '\n'.join(l[1:] for l in raw
                 if (l.startswith('+') and not l.startswith('+++'))
                 or l.startswith(' '))

def strip(text):
    """Comments explain the code and would satisfy a grep for it on their own.

    Line oriented on purpose. Added lines are gathered from every hunk and
    concatenated, so a doc comment can arrive with its opener and no closer:
    diff is free to mark either instance of an identical /** as the added one.
    A regex spanning /* to */ then eats every line of code between the stray
    opener and the next closer, and the assertions about that code pass or fail
    for a reason that has nothing to do with the patch. Dropping comment lines
    one at a time cannot be thrown off that way.
    """
    text = re.sub(r'/\*.*?\*/', '', text)
    kept = []
    for line in text.split('\n'):
        head = line.lstrip()
        if head.startswith('*') or head.startswith('/*') or head.startswith('//'):
            continue
        kept.append(re.sub(r'(?<![:/])//.*$', '', line))
    return '\n'.join(kept)

code = strip(added)
whole = strip(post)

# --- our own sort is never read back as a choice ----------------------------

if not re.search(r'if \(this\.auraDeApplyingSort_\) \{\s*\n\s*return;', code):
    die('the sorted handler does not turn away a sort this controller applied, '
        'so a remembered order is copied into the app wide preference and '
        'spreads to every folder that has none of its own')
if not re.search(r'this\.auraDeApplyingSort_ = true;\s*\n\s*try \{', code):
    die('the flag is not claimed immediately before the sort, so the sorted '
        'event can fire outside the window it guards')

# --- the guard cannot stick -------------------------------------------------

if not re.search(r'\} finally \{\s*\n\s*this\.auraDeApplyingSort_ = false;',
                 code):
    die('the flag is cleared without a finally, so a throw inside the sort '
        'leaves it set and every later user sort is discarded as one of ours')

# --- the default, not the previous folder -----------------------------------

if not re.search(
        r'const field = remembered \? remembered\.field : '
        r'this\.fileListSortField_', code):
    die('a folder with no remembered order does not fall back to the app wide '
        'default, so which order it opens in depends on the route taken to it')
if not re.search(
        r'const direction =\s*\n?\s*remembered \? remembered\.direction : '
        r'this\.fileListSortDirection_', code):
    die('the direction has no fallback of its own')

# --- no pointless resort ----------------------------------------------------

if not re.search(
        r'if \(status\.field === field && status\.direction === direction\) \{'
        r'\s*\n\s*return;', code):
    die('the order is applied even when it already matches, so arriving in a '
        'folder rebuilds every row in the list for no change')

# --- it runs on arrival, not only at the Recent boundary --------------------

if not re.search(r'if \(!isOnRecent\) \{\s*\n\s*this\.auraDeApplySort_\(', code):
    die('the remembered order is not applied on every arrival, so it only '
        'takes effect when crossing into or out of Recent')
if not re.search(r'auraDeApplySort_\(fileListModel, fileData\.key\)', code):
    die('the folder key is not passed to the apply, so it cannot tell which '
        'folder was just opened')

# --- Recent keeps its own order ---------------------------------------------

# Anchored to the line above it, which the patch carries as context. The
# isRecentRoot test itself sits four lines back and is not in any hunk, so
# asserting on it directly would be an assertion that can never fail.
if not re.search(
        r'this\.fileListSortDirection_ = currentSortStatus\.direction;\s*\n\s*'
        r'this\.auraDeRememberSort_\(currentSortStatus\);', whole):
    die('the per folder record is not made in the same branch that updates the '
        'app wide preference, so Recent could write its forced order into both')

# --- a real LRU, and bounded ------------------------------------------------

if not re.search(
        r'this\.auraDeSortByDirectory_\.delete\(key\);\s*\n\s*'
        r'this\.auraDeSortByDirectory_\.set\(', code):
    die('the map sets without deleting first, so rewriting an existing key '
        'leaves it at the front and the eviction discards the folder most '
        'recently used')
if not re.search(
        r'while \(this\.auraDeSortByDirectory_\.size > '
        r'AURADE_SORT_MEMORY_LIMIT\)', code):
    die('nothing evicts, so a window left open keeps an order for every folder '
        'it ever visited')
if not re.search(r'AURADE_SORT_MEMORY_LIMIT = \d+;', code):
    die('the limit is never defined')

# --- a half filled status is not recorded -----------------------------------

if not re.search(r'if \(!key \|\| !status\.field \|\| !status\.direction\)',
                 code):
    die('a sort status with no field or no direction is recorded anyway, and '
        'applying it later would sort by nothing')

print('files sort memory test: PASS '
      '(own sorts not read back, guard cannot stick, falls back to the default, '
      'no pointless resort, applied on arrival, Recent untouched, real LRU, '
      'bounded, half filled status refused)')
PY
