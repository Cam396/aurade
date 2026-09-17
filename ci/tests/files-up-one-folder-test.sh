#!/usr/bin/env bash
# Alt+Up navigates to the parent and selects the folder just left.
#
# One: selecting straight after dispatching the change. The directory change is
# asynchronous, so that runs against the file list of the folder being left and
# selects nothing, or worse, the wrong thing.
#
# Two: listening for the scan only. A folder that is already cached need not be
# scanned again and announces itself as a rescan, and arriving somewhere
# familiar is the commonest case of going up there is.
#
# Three: never removing the listener. Every trip up would add another, and the
# tenth would select the entry from the first.
#
# Four: reading the entry being left after the dispatch. By then it is the
# parent, and the parent selects itself.
#
# Five: replacing Backspace rather than joining it. The new binding is the one
# other file managers use; the old one is the one this app's users already
# have in their fingers.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0074-files-up-one-folder-lands-where-you-were.patch"

fail() { echo "files up one folder test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0074 is missing'
grep -Fqx '0074-files-up-one-folder-lands-where-you-were.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0074 is not listed in SERIES, so the series never applies it'

targets=$(grep -c '^diff --git ' "$PATCH")
[[ $targets -eq 1 ]] || fail "expected exactly 1 file, found ${targets}"
grep -Fq '+++ b/ui/file_manager/file_manager/foreground/js/main_window_component.ts' \
  "$PATCH" || fail 'patch 0074 does not touch main_window_component.ts'

python3 - "$PATCH" <<'PY' || exit 1
import re, sys

raw = open(sys.argv[1]).read().splitlines()

def die(msg):
    print('files up one folder test: ' + msg, file=sys.stderr)
    raise SystemExit(1)

sections, cur = {}, None
for line in raw:
    if line.startswith('diff --git '):
        cur = line.split(' b/')[-1]
        sections[cur] = []
    elif cur:
        sections[cur].append(line)

def strip(lines):
    """Remove comments. Every decision is explained in prose immediately above
    the code that makes it, so a grep on unstripped text passes on the
    explanation alone. Stateful and line oriented rather than a re.S span, so
    an added line holding an unbalanced /** cannot eat the rest of the file."""
    out, in_block = [], False
    for l in lines:
        s = l
        if in_block:
            if '*/' in s:
                s = s.split('*/', 1)[1]
                in_block = False
            else:
                continue
        while '/*' in s:
            before, rest = s.split('/*', 1)
            if '*/' in rest:
                s = before + rest.split('*/', 1)[1]
            else:
                s = before
                in_block = True
                break
        s = re.sub(r'(?<![:/])//.*$', '', s)
        if s.strip():
            out.append(s)
    return '\n'.join(out)

WIN = 'ui/file_manager/file_manager/foreground/js/main_window_component.ts'
added = strip(l[1:] for l in sections.get(WIN, [])
              if l.startswith('+') and not l.startswith('+++'))
post = strip(l[1:] for l in sections.get(WIN, [])
             if (l.startswith('+') and not l.startswith('+++'))
             or l.startswith(' '))

# --- the new binding, joining the old one rather than replacing it ----------

if "case 'Alt-ArrowUp':" not in added:
    die('Alt+Up is still not bound, which is up one level in Explorer, GNOME '
        'Files, Dolphin and ChromeOS itself')
if "case 'Backspace':" not in post:
    die('Backspace no longer goes up, so the binding this app already had has '
        'been taken away from the people using it')
# They must share one body. Two cases with a break between them is two
# behaviours that will drift.
if not re.search(r"case 'Alt-ArrowUp':\s*\n\s*case 'Backspace':", post):
    die('Alt+Up and Backspace do not fall through to the same body, so they '
        'are two implementations of one idea and will drift apart')

# --- the entry being left is read before the navigation ---------------------

up = re.search(r'private auraDeGoUp_\(\)[^{]*\{(.*?)\n  \}', post, re.S)
if not up:
    die('auraDeGoUp_ is missing, so nothing goes up')
up_body = up.group(1)

if 'getCurrentDirEntry()' not in up_body:
    die('the folder being left is never read, so there is nothing to land on')
leaving_at = up_body.find('getCurrentDirEntry()')
dispatch_at = up_body.find('store.dispatch(')
if dispatch_at < 0:
    die('nothing dispatches the directory change')
if not leaving_at < dispatch_at:
    die('the folder being left is read after the navigation is dispatched, so '
        'by then it is the parent and the parent selects itself')
register_at = up_body.find('auraDeSelectOnceScanned_')
if register_at < 0:
    die('nothing arranges for the entry to be selected once the new folder '
        'has loaded, so going up still lands nowhere')
if not register_at < dispatch_at:
    die('the selection is arranged after the dispatch, which races the scan it '
        'is waiting for')

# --- and it waits for the load rather than selecting immediately ------------

sel = re.search(r'private auraDeSelectOnceScanned_\(', post)
if not sel:
    die('auraDeSelectOnceScanned_ is missing')
scanned = re.search(
    r'private auraDeSelectOnceScanned_\((?:.|\n)*?\{((?:.|\n)*?)\n  \}', post)
if not scanned:
    die('cannot read the body of auraDeSelectOnceScanned_')
body = scanned.group(1)

if 'selectEntry(' not in body:
    die('nothing selects the entry')
for ev in ('cur-dir-scan-completed', 'cur-dir-rescan-completed'):
    if "addEventListener('%s'" % ev not in body:
        die('the selection does not wait for %s, so going up into a folder '
            'that reports through that event lands nowhere. A cached folder '
            'reports a rescan, and arriving somewhere familiar is the '
            'commonest case of going up there is' % ev)
    if "removeEventListener('%s'" % ev not in body:
        die('the %s listener is never removed, so every trip up adds another '
            'and the tenth selects the entry from the first' % ev)
# Removed before the selection, not after: selectEntry can itself settle the
# list and re-enter, and a listener still registered at that point fires again.
remove_at = body.find('removeEventListener')
select_at = body.find('selectEntry(')
if not remove_at < select_at:
    die('the listeners are removed after the selection rather than before, so '
        'anything selectEntry settles can re-enter through a listener that is '
        'still registered')
PY

grep -nP '[\x{2014}\x{2013}]' "$PATCH" && \
  fail 'patch 0074 contains an em dash or an en dash' || true

echo 'files up one folder test: PASS '\
'(Alt+Up joins Backspace on one body, the folder being left is read before the '\
'navigation, and the selection waits for either completion event with both '\
'listeners removed before it fires)'
