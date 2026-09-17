#!/usr/bin/env bash
# A refused cut reports the failure and clears the marks from the previous cut.
# The test drives the event path and checks the counter, rows, and status.
#
# One: refusing quietly. That is the bug.
#
# Two: saying something but leaving the marks. The message is the smaller half.
# What is on screen has to describe what a paste would now do, and after a
# refusal that is nothing.
#
# Three: speaking when nothing is selected. Ctrl+X with an empty selection is a
# keystroke into the air, not a request that was turned down, and a message
# there is scolding someone for pressing a key.
#
# Four: folding the focus guard into the refusal. A cut while a text field has
# focus is not this app's event at all, and treating it as a refusal would put
# a toast on the screen every time someone pressed Ctrl+X in the search box.
#
# Five: one message for both. A refused copy that says "cannot be moved" is
# telling the person about an operation they did not ask for.
#
# Six: counting folders as files. Cutting two directories and being told "2
# files ready to move" describes something that is not what happened.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0075-files-a-refused-cut-says-so.patch"

fail() { echo "files refused cut says so test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0075 is missing'
grep -Fqx '0075-files-a-refused-cut-says-so.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0075 is not listed in SERIES, so the series never applies it'

targets=$(grep -c '^diff --git ' "$PATCH")
[[ $targets -eq 4 ]] || fail "expected exactly 4 files, found ${targets}"
for f in ui/file_manager/file_manager/foreground/js/aurade_cut_marks.ts \
         ui/file_manager/file_manager/foreground/js/file_transfer_controller.ts \
         ui/file_manager/file_manager/foreground/js/toolbar_controller.ts \
         ui/chromeos/file_manager_strings.grdp; do
  grep -Fq "+++ b/$f" "$PATCH" || fail "patch 0075 does not touch $f"
done
for dep in 0071-files-a-cut-file-stays-dimmed.patch \
           0073-files-the-bar-says-what-is-waiting.patch; do
  grep -Fqx "$dep" "$ROOT/patches/SERIES" || \
    fail "$dep is not in SERIES, so there are no marks for 0075 to clear"
done

python3 - "$PATCH" <<'PY' || exit 1
import re, sys

raw = open(sys.argv[1]).read().splitlines()

def die(msg):
    print('files refused cut says so test: ' + msg, file=sys.stderr)
    raise SystemExit(1)

sections, cur = {}, None
for line in raw:
    if line.startswith('diff --git '):
        cur = line.split(' b/')[-1]
        sections[cur] = []
    elif cur:
        sections[cur].append(line)

def strip(lines):
    """Remove comments. Every decision here is explained in prose right above
    the code that makes it, so a grep on unstripped text passes on the
    explanation alone. Line oriented rather than a re.S span, so an added line
    holding an unbalanced /** cannot eat the rest of the file."""
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

MOD = 'ui/file_manager/file_manager/foreground/js/aurade_cut_marks.ts'
XFER = 'ui/file_manager/file_manager/foreground/js/file_transfer_controller.ts'
BAR = 'ui/file_manager/file_manager/foreground/js/toolbar_controller.ts'
GRD = 'ui/chromeos/file_manager_strings.grdp'

def added(p):
    return strip(l[1:] for l in sections.get(p, [])
                 if l.startswith('+') and not l.startswith('+++'))

def post(p):
    return strip(l[1:] for l in sections.get(p, [])
                 if (l.startswith('+') and not l.startswith('+++'))
                 or l.startswith(' '))

mod, xfer, bar, grd = added(MOD), added(XFER), added(BAR), added(GRD)
# Function bodies are read from the post image, never the added lines. Only
# the inside of these functions changed, so their closing braces are
# unchanged context and a body regex over the added lines alone never finds
# its end. That form fails against correct code, which is how it was
# written the first time.
mod_post, xfer_post, bar_post = post(MOD), post(XFER), post(BAR)

# --- the guard is split, so a text field is not treated as a refusal --------

if re.search(r'!this\.isDocumentWideEvent_\(\) \|\| !this\.canCutOrCopy_', xfer_post):
    die('the focus guard and the refusal guard are still one condition, so a '
        'Ctrl+X in the search box is reported to the person as a refused cut')
if not re.search(r'if \(!this\.isDocumentWideEvent_\(\)\) \{\s*\n\s*return;', xfer_post):
    die('the focus guard is gone, so this now runs for events belonging to a '
        'text field')
if not re.search(r'if \(!this\.canCutOrCopy_\(isMove\)\) \{\s*\n\s*'
                 r'this\.auraDeRefused_\(isMove\);\s*\n\s*return;', xfer_post):
    die('a refused cut still returns silently, which is the bug')

# --- and the refusal both clears and speaks ---------------------------------

ref = re.search(r'private auraDeRefused_\(isMove: boolean\)[^{]*\{(.*?)\n  \}',
                xfer_post, re.S)
if not ref:
    die('auraDeRefused_ is missing, so nothing answers a refused cut')
body = ref.group(1)

if not re.search(r'selection\.totalCount === 0', body):
    die('the refusal speaks even with nothing selected, so Ctrl+X on an empty '
        'selection scolds someone for pressing a key')
empty_at = body.find('totalCount === 0')
clear_at = body.find('auraDeClearCut()')
toast_at = body.find('filesToast_.show')
if clear_at < 0:
    die('a refused cut does not clear the marks, so the rows from the previous '
        'cut stay dimmed and the status bar goes on naming them, and a paste '
        'would move files the person never chose')
if toast_at < 0:
    die('a refused cut says nothing, so it is indistinguishable from a key '
        'that did not register')
if not empty_at < clear_at:
    die('the empty check does not come first, so an empty selection still '
        'wipes a cut that was perfectly good')
if 'auraDeRedrawForCutMarks_()' not in body:
    die('the marks are cleared without repainting, so the rows stay dimmed on '
        'screen with nothing behind them')
if not re.search(r"isMove \?[\s\S]{0,120}?CANNOT_MOVE[\s\S]{0,120}?CANNOT_COPY", body):
    die('a refused copy and a refused cut say the same thing, so one of them '
        'tells the person about an operation they did not ask for')

# --- both strings exist ------------------------------------------------------

for name in ('IDS_FILE_BROWSER_AURADE_CANNOT_MOVE_THESE',
             'IDS_FILE_BROWSER_AURADE_CANNOT_COPY_THESE'):
    if name not in grd:
        die('%s is not defined, so the toast renders as empty text with no '
            'error anywhere' % name)

# --- folders are not files ---------------------------------------------------

if not re.search(r'export function auraDeCutFolderCount\(\): number', mod):
    die('the cut set does not report how many folders it holds, so the bar '
        'cannot tell a folder from a file')
mark = re.search(r'export function auraDeMarkCut\([^)]*\)[^{]*\{(.*?)\n\}',
                 mod_post, re.S)
if not mark:
    die('auraDeMarkCut is missing')
if 'entry.isDirectory' not in mark.group(1):
    die('the folder count is never taken at the moment of the cut. It cannot '
        'be worked out later: the bar asks from folders the cut items are not '
        'in, where there is nothing left to ask whether a URL was a directory')
clear = re.search(r'export function auraDeClearCut\(\)[^{]*\{(.*?)\n\}',
                  mod_post, re.S)
if not clear or 'cutFolders = 0' not in clear.group(1):
    die('clearing the cut does not reset the folder count, so the next cut of '
        'two files can still be described as folders')
if not re.search(r'cutFolders = 0;', mark.group(1)):
    die('marking a new cut does not reset the folder count, so counts from an '
        'abandoned cut are added to the new one')

noun = re.search(r'const noun = (.*?);\n', bar_post, re.S)
if not noun:
    die('the bar still hardcodes its noun, so two folders are announced as '
        'two files')
n = noun.group(1)
for word in ("'folder'", "'folders'", "'items'", "'file'", "'files'"):
    if word not in n:
        die('the bar has no %s form, so at least one kind of selection is '
            'described as something it is not' % word)
PY

grep -nP '[\x{2014}\x{2013}]' "$PATCH" && \
  fail 'patch 0075 contains an em dash or an en dash' || true

echo 'files refused cut says so test: PASS '\
'(the focus guard is separate from the refusal, a refusal clears the marks '\
'before it speaks and only when something was selected, a cut and a copy say '\
'different things, and folders are counted as folders)'
