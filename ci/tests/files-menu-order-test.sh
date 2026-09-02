#!/usr/bin/env bash
# Where the two new items sit in the context menu, and the four ways that goes
# wrong.
#
# One: a measurement in the middle of the clipboard group. Calculate size sat
# between Duplicate and Paste, which reads as a clipboard action, which it is
# not. It belongs with Get info: both answer "what is this" and neither changes
# anything.
#
# Two: breaking the clipboard group. Copy and Paste are muscle memory in that
# order, nothing that is not a copy may come between them, and nothing may come
# between Paste and Paste into folder.
#
# Three: moving the item in the wrong menu. paste-into-folder appears in two
# menus, so an unscoped edit moves the one nobody was looking at.
#
# Four: a move implemented as a copy. The item then appears twice, and the
# second one is live because both bind the same command id.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0067-files-the-menu-reads-in-order.patch"

fail() { echo "files menu order test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0067 is missing'
grep -Fqx '0067-files-the-menu-reads-in-order.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0067 is not listed in SERIES'

targets=$(grep -c '^diff --git ' "$PATCH")
[[ $targets -eq 1 ]] || fail "expected exactly 1 file, found ${targets}"

grep -Fq '+++ b/ui/file_manager/file_manager/main.html' "$PATCH" || \
  fail 'patch 0067 does not touch main.html'

python3 - "$PATCH" <<'PY' || exit 1
import re, sys

raw = open(sys.argv[1]).read().splitlines()

def die(msg):
    print(f'files menu order test: {msg}', file=sys.stderr)
    raise SystemExit(1)

# The menu as it reads after the patch: added lines plus untouched context, in
# file order. Removed lines are dropped, which is exactly the resulting menu.
after = [l[1:] for l in raw
         if (l.startswith('+') and not l.startswith('+++'))
         or l.startswith(' ')]

order = []
for line in after:
    m = re.search(r'command="#([a-z-]+)"', line)
    if m:
        order.append(m.group(1))
    elif '<hr' in line:
        order.append('|')

def pos(name):
    if name not in order:
        die(f'{name} is not in the hunk, so this fixture cannot see where it '
            'sits and every ordering assertion below would be vacuous')
    return order.index(name)

# --- nothing appears twice ---------------------------------------------------

for name in ('duplicate', 'calculate-size'):
    if order.count(name) != 1:
        die(f'{name} appears {order.count(name)} times. A move written as a '
            'copy leaves both live, because they bind the same command id')

# --- the clipboard triad is intact and uninterrupted -------------------------

# Cut sits one line above the hunk's context and is deliberately not asserted
# on: the fixture can only see what the patch carries, and a check against a
# name that is not there would be a check that can never fail.
if not (pos('copy') < pos('paste') < pos('paste-into-folder')):
    die('copy, paste and paste into folder are no longer in that order')
between = order[pos('copy') + 1:pos('paste')]
for name in between:
    if not name.startswith('copy'):
        die(f'{name} sits between Copy and Paste, interrupting the group that '
            'everybody reaches for without looking')

# --- Duplicate closes the clipboard group ------------------------------------

if pos('duplicate') != pos('paste-into-folder') + 1:
    die('Duplicate does not close the clipboard group. It is a copy and a '
        'paste in one step, so it reads as the last item of that group and as '
        'an interruption anywhere inside it')

# --- Calculate size goes with Get info ---------------------------------------

if pos('calculate-size') != pos('get-info') + 1:
    die('Calculate size is not beside Get info. Both answer what is this and '
        'neither changes anything, and a measurement inside the clipboard '
        'group reads as a clipboard action')
if pos('calculate-size') < pos('|'):
    die('Calculate size is still above the separator, so it is still in the '
        'clipboard group')

print('files menu order test: PASS '
      '(nothing duplicated, clipboard group intact, Duplicate closes it, '
      'Calculate size sits with Get info)')
PY
