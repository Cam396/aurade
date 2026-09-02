#!/usr/bin/env bash
# Folder sizes on demand, and the seven ways this one goes wrong.
#
# One: a new .ts file nobody added to file_names.gni. The TypeScript build
# enumerates its sources there, so an unregistered file is never compiled and
# the feature silently does not exist. Nothing else in the build complains.
#
# Two: measuring from the renderer. The size cell is redrawn on every scroll.
# A walk started there would read the whole tree under every folder on screen,
# repeatedly, and the app would appear to hang on a spinning disk. The cell may
# only read a measurement somebody already asked for.
#
# Three: losing the fallback. A folder nobody has measured has to keep showing
# what it showed before. Overwriting the metadata size unconditionally would
# put "0 B" on every unmeasured folder in the list.
#
# Four: a cache that is not really an LRU. A Map keeps insertion order, so
# setting a key that is already present leaves it at the front and the eviction
# throws away the entry most recently used.
#
# Five: two walks for one folder. Without a single flight guard, invoking twice
# reads the entire tree twice.
#
# Six: reading the size without reading chrome.runtime.lastError. A failed call
# still invokes the callback, so a folder that could not be read is otherwise
# indistinguishable from a folder holding nothing.
#
# Seven: a keyboard shortcut. Every free chord in this window is read by ash
# first, so a shortcut here takes one somebody already uses.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0061-files-how-big-is-that-folder.patch"

fail() { echo "files folder size test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0061 is missing'
grep -Fqx '0061-files-how-big-is-that-folder.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0061 is not listed in SERIES'

targets=$(grep -c '^diff --git ' "$PATCH")
[[ $targets -eq 6 ]] || fail "expected exactly 6 files, found ${targets}"

for f in ui/file_manager/file_manager/foreground/js/aurade_folder_size.ts \
         ui/file_manager/file_names.gni \
         ui/file_manager/file_manager/foreground/js/command_handler.ts \
         ui/file_manager/file_manager/foreground/js/file_manager_commands.ts \
         ui/file_manager/file_manager/foreground/js/ui/file_table.ts \
         ui/file_manager/file_manager/main.html; do
  grep -Fq "+++ b/$f" "$PATCH" || fail "patch 0061 does not touch $f"
done

python3 - "$PATCH" <<'PY' || exit 1
import re, sys

raw = open(sys.argv[1]).read().splitlines()

def die(msg):
    print(f'files folder size test: {msg}', file=sys.stderr)
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

def post(path):
    """Added lines plus untouched context: what the file reads like afterwards."""
    return '\n'.join(l[1:] for l in sections.get(path, [])
                     if (l.startswith('+') and not l.startswith('+++'))
                     or l.startswith(' '))

def strip(text):
    """Comments explain the code and would satisfy a grep for it on their own."""
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    return re.sub(r'(?<![:/])//.*$', '', text, flags=re.M)

MOD = 'ui/file_manager/file_manager/foreground/js/aurade_folder_size.ts'
GNI = 'ui/file_manager/file_names.gni'
HANDLER = 'ui/file_manager/file_manager/foreground/js/command_handler.ts'
CMDS = 'ui/file_manager/file_manager/foreground/js/file_manager_commands.ts'
TABLE = 'ui/file_manager/file_manager/foreground/js/ui/file_table.ts'
HTML = 'ui/file_manager/file_manager/main.html'

mod = strip(added(MOD))
gni = added(GNI)
handler = added(HANDLER)
cmds = strip(added(CMDS))
table_added = strip(added(TABLE))
table_post = strip(post(TABLE))
html = added(HTML)

# --- the new file has to be in the build ------------------------------------

if 'aurade_folder_size.ts' not in gni:
    die('the new module is not added to file_names.gni, so the TypeScript '
        'build never compiles it and the feature does not exist on the machine')

# --- the command is reachable ------------------------------------------------

if "'calculate-size': new CalculateSizeCommand()" not in handler:
    die('the command is not registered in the command table, so the menu item '
        'is inert. Checking for the class name alone is not enough: the import '
        'line carries it too.')
if not re.search(r'<command id="calculate-size"', html):
    die('main.html never declares the command, so nothing binds the id')
if not re.search(r'<cr-menu-item command="#calculate-size"', html):
    die('nothing in the context menu invokes the command, so there is no way '
        'to reach it')

# --- no keyboard shortcut ----------------------------------------------------

decl = re.search(r'<command id="calculate-size"[^>]*>', html)
if decl and 'shortcut' in decl.group(0):
    die('the command takes a keyboard shortcut. Ash reads every chord in this '
        'window first, so this quietly takes one somebody already uses')

# --- the picker dialogs do not grow the item --------------------------------

item = re.search(r'<cr-menu-item command="#calculate-size"[^>]*>', html)
if not item or 'visibleif="full-page"' not in item.group(0):
    die('the menu item is not marked full-page only, so the file picker '
        'dialogs would offer a measurement nothing in them can show')

# --- the renderer reads, it never measures ----------------------------------

# The call, not the symbol. The import line carries the name too, so a cell
# that stopped calling it would still satisfy a bare name check.
if not re.search(r'auraDeMeasuredFolderSize\(entry\)', table_added):
    die('the size cell never calls the lookup, so a measured folder still '
        'shows a dash')
if re.search(r'\bauraDeMeasureFolderSize\b', table_added):
    die('the size cell starts a measurement. It is redrawn on every scroll, '
        'so this walks the tree under every visible folder, repeatedly')

# --- an unmeasured folder keeps what it had ---------------------------------

if not re.search(r'measured === undefined \? metadata\.size : measured',
                 table_added):
    die('the measured value does not fall back to the metadata size, so every '
        'folder nobody has measured renders with the wrong number')
if 'formatSize(size, special)' not in table_post:
    die('the cell no longer formats through formatSize, which is what turns '
        'the directory sentinel into a dash')

# --- the cache is a real LRU ------------------------------------------------

if not re.search(r'folderSizes\.delete\(url\);\s*\n\s*folderSizes\.set\(url',
                 mod):
    die('the cache sets without deleting first, so rewriting an existing key '
        'leaves it at the front of the Map and the eviction discards the entry '
        'most recently used')
if not re.search(r'while \(folderSizes\.size > AURADE_FOLDER_SIZE_LIMIT\)', mod):
    die('nothing evicts, so a long session holds a number for every folder it '
        'ever measured')

# --- one walk per folder ----------------------------------------------------

if not re.search(r'const existing = inFlight\.get\(url\);\s*\n\s*if \(existing\)',
                 mod):
    die('a second invocation on the same folder does not join the first walk, '
        'so it reads the whole tree again')
if not re.search(r'\.finally\(\(\) => \{\s*\n\s*inFlight\.delete\(url\);', mod):
    die('the in flight entry is never cleared, so a folder measured once can '
        'never be measured again and a rename or a copy into it is invisible')

# --- a failed walk is not a folder holding nothing --------------------------

if 'chrome.runtime.lastError' not in mod:
    die('the callback does not read chrome.runtime.lastError. A failed call '
        'still invokes the callback, so an unreadable folder would be recorded '
        'as holding zero bytes')

# --- only real filesystem directories ---------------------------------------

# Again the call and its argument, not the symbol: the import line at the top
# of the module carries the name whether or not anything still uses it.
if not re.search(r'isNativeEntry\(unwrapEntry\(entry\)', mod):
    die('non native entries are not turned away, so getDirectorySize is handed '
        'a fake root that it cannot walk')
if not re.search(r'if \(!entry \|\| !entry\.isDirectory\)', mod):
    die('a file can be handed to the walk')

# --- a mixed selection does not offer a total it cannot compute -------------

if not re.search(r'entries\.every\(auraDeCanMeasureSize\)', cmds):
    die('the command is offered when only some of the selection is a folder, '
        'so it would quietly measure the folders, ignore the files, and show a '
        'total that nothing on screen explains')
if not re.search(r'event\.command\.setHidden\(!canMeasure\)', cmds):
    die('the item stays in the menu when it cannot run')

print('files folder size test: PASS '
      '(registered in the build, reachable, no chord taken, renderer reads '
      'only, fallback kept, real LRU, single flight, failures told apart, '
      'whole selection measurable)')
PY
