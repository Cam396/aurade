#!/usr/bin/env bash
# Duplicate, and the seven ways it goes wrong.
#
# One, and worst: duplicating a selection that is not in this folder. In search
# results and in Recent the rows come from wherever they live, so a copy into
# the folder on screen would fetch the file into a folder it was never in, from
# a command that promised to leave things where they are.
#
# Two: comparing the path without the volume. fullPath is relative to its own
# filesystem, so two volumes can hold the same one and the parent check passes
# for a file on another disk.
#
# Three: checking only in canExecute. That runs when the menu is built. A
# command reached from anywhere else runs against whatever the selection is by
# then, so execute has to check again.
#
# Four: offering it in Trash. A duplicate of a deleted file is not a thing
# anybody wants, and the restore path would then have two of them.
#
# Five: offering it on a read only volume, where it can only fail.
#
# Six: renaming by hand. The copy task already runs its destination through
# GenerateUnusedFilename, so any name computed here would be a second, worse
# implementation that disagrees with the one Files uses everywhere else.
#
# Seven: taking a keyboard chord. Ash reads every chord in this window first,
# and Ctrl+D is already spoken for.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0066-files-duplicate.patch"

fail() { echo "files duplicate test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0066 is missing'
grep -Fqx '0066-files-duplicate.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0066 is not listed in SERIES'

targets=$(grep -c '^diff --git ' "$PATCH")
[[ $targets -eq 3 ]] || fail "expected exactly 3 files, found ${targets}"

for f in ui/file_manager/file_manager/foreground/js/command_handler.ts \
         ui/file_manager/file_manager/foreground/js/file_manager_commands.ts \
         ui/file_manager/file_manager/main.html; do
  grep -Fq "+++ b/$f" "$PATCH" || fail "patch 0066 does not touch $f"
done

python3 - "$PATCH" <<'PY' || exit 1
import re, sys

raw = open(sys.argv[1]).read().splitlines()

def die(msg):
    print(f'files duplicate test: {msg}', file=sys.stderr)
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
    """Line oriented: added lines come from every hunk, so a doc comment can
    arrive with an opener and no closer and a regex spanning the delimiters
    would eat real code."""
    text = re.sub(r'/\*.*?\*/', '', text)
    kept = []
    for line in text.split('\n'):
        head = line.lstrip()
        if head.startswith('*') or head.startswith('/*') or head.startswith('//'):
            continue
        kept.append(re.sub(r'(?<![:/])//.*$', '', line))
    return '\n'.join(kept)

CMDS = 'ui/file_manager/file_manager/foreground/js/file_manager_commands.ts'
HANDLER = 'ui/file_manager/file_manager/foreground/js/command_handler.ts'
HTML = 'ui/file_manager/file_manager/main.html'

cmds = strip(added(CMDS))
handler = added(HANDLER)
html = added(HTML)

# --- the selection has to live here -----------------------------------------

if not re.search(r'if \(parent !== dir\) \{\s*\n\s*return false;', cmds):
    die('the parent folder is not compared, so a selection from search results '
        'or Recent would be copied into the folder on screen, which is a fetch '
        'and not a duplicate')
if not re.search(r'volumeManager\.getVolumeInfo\(entry\) ===\s*\n?\s*'
                 r'volumeManager\.getVolumeInfo\(dirEntry\)', cmds):
    die('the volume is not compared. fullPath is relative to its own '
        'filesystem, so the parent check alone passes for a file on another '
        'disk that happens to share the path')

# --- checked in both places --------------------------------------------------

sits = len(re.findall(r'auraDeSitsIn\(entry, dirEntry, fileManager\.volumeManager\)',
                      cmds))
if sits < 2:
    die(f'the folder check appears {sits} time(s). canExecute runs when the '
        'menu is built, so execute has to check again for a command reached '
        'from anywhere else')

# --- the guards --------------------------------------------------------------

# Counted, not merely present. The guard belongs in both execute and
# canExecute for the same reason the folder check does, and a bare presence
# test is satisfied by whichever one survives.
trash = len(re.findall(r'isOnTrashRoot\(fileManager\)', cmds))
if trash < 2:
    die(f'the Trash guard appears {trash} time(s). It belongs in canExecute so '
        'the item does not appear, and in execute so a command reached from '
        'anywhere else cannot duplicate a deleted file')
if 'fileManager.directoryModel.isReadOnly()' not in cmds:
    die('Duplicate is offered on a read only volume, where it can only fail')
if not re.search(r'entries\.length > 0', cmds):
    die('Duplicate is offered with nothing selected')
if 'shouldShowMenuItemsForEntry' not in cmds:
    die('entries that the app hides its menu items for are duplicated anyway')

# --- the copy task does the naming -------------------------------------------

if not re.search(r'startIOTask\(\s*\n?\s*chrome\.fileManagerPrivate\.IoTaskType\.COPY,',
                 cmds):
    die('the duplicate is not a copy task, so it does not get the naming, the '
        'progress panel or the error reporting that every other copy gets')
if not re.search(r'destinationFolder: dirEntry', cmds):
    die('the destination is not the current folder, so the copy lands '
        'somewhere else entirely')
if re.search(r'\(\d\)|copy\)|\bcopyName\b|" \(1\)"', cmds):
    die('a name is computed here. GenerateUnusedFilename already runs on every '
        'copy destination, and a second implementation would disagree with the '
        'one Files uses everywhere else')

# --- reachable, and without taking a chord -----------------------------------

if "'duplicate': new DuplicateCommand()" not in handler:
    die('the command is not registered, so the menu item is inert. Checking '
        'for the class name alone is not enough: the import line carries it too')
decl = re.search(r'<command id="duplicate"[^>]*>', html)
if not decl:
    die('main.html never declares the command')
if 'shortcut' in decl.group(0):
    die('the command takes a keyboard shortcut. Ash reads every chord in this '
        'window first, and Ctrl+D is already spoken for')
item = re.search(r'<cr-menu-item command="#duplicate"[^>]*>', html)
if not item:
    die('nothing in the context menu invokes the command')
if 'visibleif="full-page"' not in item.group(0):
    die('the menu item is not full-page only, so the file picker dialogs would '
        'offer it')

print('files duplicate test: PASS '
      '(selection must live here, volume compared, checked twice, trash and '
      'read only refused, naming left to the copy task, reachable, no chord)')
PY
