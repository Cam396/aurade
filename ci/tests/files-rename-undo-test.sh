#!/usr/bin/env bash
# Undo a rename, from the toast that already undoes a delete.
#
# Five ways this goes wrong, none of them visible in a screenshot:
#
# One: undoing with moveTo. moveTo overwrites whatever sits at the
# destination. A toast lives for seconds, which is long enough for something
# to appear at the old name, and destroying it silently would be a worse bug
# than the mistyped name being undone. renameFile checks for an existing entry
# and throws, so the undo has to go through renameEntry.
#
# Two: a constructor parameter nobody passes. NamingController is built in one
# place, and a toast added to the signature without being handed over at that
# call site does not compile, which is the good case; asserting both halves
# keeps the failure from being a puzzle.
#
# Three: offering the undo on a removable root. That path renames a volume
# label through a different call that reports nothing back, so there is no
# renamed entry to reverse and nothing to hand the toast.
#
# Four: reading the old name too late. Today this one is latent rather than
# live: renameFile returns moveEntryTo's new entry and leaves the original
# alone, so entry.name still holds the old name afterwards. Nothing in the
# FileSystem API promises that, and the read costs nothing where it is, so the
# order is asserted rather than relied on.
#
# Five: a dialog on failure. The rename being undone already succeeded, so
# nothing is broken, and a modal in front of somebody who changed their mind
# twice is out of proportion.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0069-files-undo-a-rename.patch"

fail() { echo "files rename undo test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0069 is missing'
grep -Fqx '0069-files-undo-a-rename.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0069 is not listed in SERIES, so the series never applies it'

targets=$(grep -c '^diff --git ' "$PATCH")
[[ $targets -eq 3 ]] || fail "expected exactly 3 files, found ${targets}"
for f in ui/chromeos/file_manager_strings.grdp \
         ui/file_manager/file_manager/foreground/js/file_manager.ts \
         ui/file_manager/file_manager/foreground/js/naming_controller.ts; do
  grep -Fq "+++ b/$f" "$PATCH" || fail "patch 0069 does not touch $f"
done

python3 - "$PATCH" <<'PY' || exit 1
import re, sys

raw = open(sys.argv[1]).read().splitlines()

def die(msg):
    print('files rename undo test: ' + msg, file=sys.stderr)
    raise SystemExit(1)

sections, cur = {}, None
for line in raw:
    if line.startswith('diff --git '):
        cur = line.split(' b/')[-1]
        sections[cur] = []
    elif cur:
        sections[cur].append(line)

def strip(lines):
    """Drop comment lines. The prose above this feature names every symbol the
    code uses, so a grep on the unstripped text passes on the explanation.

    Line oriented on purpose: a stripper spanning /* to */ with re.S ate real
    code once in this repository, because diff alignment can leave an added
    line holding an unbalanced /** whose closing */ is hundreds of lines away.
    """
    out = []
    for l in lines:
        s = re.sub(r'(?<![:/])//.*$', '', l)
        if s.strip():
            out.append(s)
    return '\n'.join(out)

def added(path, keep_comments=False):
    lines = (l[1:] for l in sections.get(path, [])
             if l.startswith('+') and not l.startswith('+++'))
    return '\n'.join(lines) if keep_comments else strip(lines)

def post(path):
    """Added lines plus untouched context: what the file reads like after."""
    lines = (l[1:] for l in sections.get(path, [])
             if (l.startswith('+') and not l.startswith('+++'))
             or l.startswith(' '))
    return strip(lines)

NAMING = 'ui/file_manager/file_manager/foreground/js/naming_controller.ts'
MAIN = 'ui/file_manager/file_manager/foreground/js/file_manager.ts'
GRDP = 'ui/chromeos/file_manager_strings.grdp'

naming = added(NAMING)
naming_post = post(NAMING)
main = added(MAIN)
grdp = added(GRDP, keep_comments=True)

# --- the toast reaches the controller, both halves --------------------------

if not re.search(r'private readonly toast_: FilesToast', naming):
    die('NamingController never takes a toast, so there is nothing to offer '
        'the undo on')
if "import type {FilesToast}" not in naming:
    die('FilesToast is not imported, so the constructor names a type that '
        'does not exist here')
if 'this.ui_.toast' not in main:
    die('file_manager.ts does not hand the toast to NamingController. A '
        'constructor parameter nobody passes is the one half of this that '
        'does not compile')

# --- the undo is a rename, not an overwrite ---------------------------------

if not re.search(r'await renameEntry\(renamed, oldName, volumeInfo, false\)',
                 naming):
    die('the undo does not go through renameEntry, which is the only call '
        'that checks whether something already sits at the old name')
if re.search(r'\.moveTo\(', naming):
    die('the undo calls moveTo, which overwrites whatever is at the '
        'destination. In the seconds a toast is on screen something can '
        'appear at the old name, and this would delete it silently')
if not re.search(r'onRenameEntry\(renamed, restored', naming):
    die('the restored entry is never given to the directory model, so the '
        'list goes on showing a name the file no longer has')

# --- and it does not offer an undo of the undo ------------------------------

# Bounded to the callback block, not run to the end of the added text. The
# method is defined earlier in the file than the line that calls it, so a slice
# taken to the end swallows the call site and reports the undo as recursive.
start = naming.find('callback: async () =>')
end = naming.find('});', start) if start >= 0 else -1
callback = naming[start:end] if start >= 0 and end > start else ''
if not callback:
    die('the toast action has no callback, so the Undo button does nothing')
if 'auraDeOfferRenameUndo_' in callback:
    die('undoing offers another undo, which is a toast that never ends')

# --- a removable root is left alone -----------------------------------------

if not re.search(r'if \(!isRemovableRoot\) \{\s*\n\s*this\.auraDeOfferRenameUndo_',
                 naming):
    die('the undo is offered without checking for a removable root, whose '
        'rename goes through renameVolume and reports no entry back, so there '
        'is nothing to reverse')

# --- the old name is read before the rename lands ---------------------------

read = naming_post.find('const auraDeOldName = entry.name;')
optimistic = naming_post.find('nameNode!.textContent = newName;')
renamed_at = naming_post.find('await renameEntry(entry, newName')
if read < 0 or optimistic < 0 or renamed_at < 0:
    die('cannot locate the rename: the patch no longer carries the name read, '
        'the optimistic relabel and the rename call together as context, so '
        'the order they happen in cannot be checked')
if not read < optimistic:
    die('the old name is read after the row has already been relabelled')
if not read < renamed_at:
    die('the old name is read after the rename rather than before it. It '
        'happens to survive today, because renameFile returns a new entry and '
        'does not touch the original, but nothing promises that and the read '
        'is free where it is')

# --- failure is a toast, not a dialog ---------------------------------------

if 'AURADE_RENAME_UNDO_FAILED' not in callback:
    die('a failed undo says nothing at all, so the file keeps the wrong name '
        'and nobody is told why')
if re.search(r'alertDialog_|showAsync|confirmDialog_', callback):
    die('a failed undo raises a dialog. Nothing is broken at that point, so a '
        'modal is out of proportion')

# --- the strings exist ------------------------------------------------------

for name in ('IDS_FILE_BROWSER_AURADE_UNDO_ACTION_LABEL',
             'IDS_FILE_BROWSER_AURADE_RENAME_UNDO_TOAST',
             'IDS_FILE_BROWSER_AURADE_RENAME_UNDO_FAILED'):
    if ('<message name="%s"' % name) not in grdp:
        die('%s is not defined, so the toast renders an empty string' % name)
    key = name[len('IDS_FILE_BROWSER_'):]
    if not re.search(r"str[f]?\('%s'" % key, naming):
        die('%s is defined and never used' % name)
PY

grep -nP '[\x{2014}\x{2013}]' "$PATCH" && \
  fail 'patch 0069 contains an em dash or an en dash' || true

echo 'files rename undo test: PASS '\
'(the toast reaches the controller and is handed over, the undo renames '\
'rather than overwrites, a removable root is left alone, the old name is read '\
'before the rename, and a failed undo is a toast)'
