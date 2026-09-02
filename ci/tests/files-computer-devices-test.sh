#!/usr/bin/env bash
# The Devices panel in Computer, and the six ways it goes wrong.
#
# One, and worst: a new .ts file that nobody added to file_names.gni. The
# TypeScript build enumerates its sources there, so an unregistered file is
# never compiled, the import resolves to nothing, and the feature simply does
# not exist on the machine. Nothing else in the build complains.
#
# Two, the panel showing outside Computer. It answers a question the rest of
# the app does not ask, and a device list stapled above every folder would be
# noise in all of them.
#
# Three, a stale panel behind hidden. Emptying it on the way out is what stops
# the previous machine state flashing up on the way back in.
#
# Four, a slow capacity query painting a panel that has since been rebuilt.
#
# Five, a volume that cannot report its size disappearing. The machine has that
# disk whether or not statvfs answered, so the row stays and the bar goes.
#
# Six, inventing facts. A filesystem the store does not know is left out, never
# guessed, because a wrong filesystem sitting next to a Format command is worse
# than a blank.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0060-files-computer-shows-your-disks.patch"
CONTROLLER='ui/file_manager/file_manager/foreground/js/aurade_devices_controller.ts'

fail() { echo "files computer devices test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0060 is missing'
grep -Fqx '0060-files-computer-shows-your-disks.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0060 is not listed in SERIES'

targets=$(grep -c '^diff --git ' "$PATCH")
[[ $targets -eq 5 ]] || fail "expected exactly 5 files, found ${targets}"

for f in "$CONTROLLER" \
         ui/file_manager/file_names.gni \
         ui/file_manager/file_manager/main.html \
         ui/file_manager/file_manager/foreground/css/file_manager.css \
         ui/file_manager/file_manager/foreground/js/file_manager.ts; do
  grep -Fq "+++ b/$f" "$PATCH" || fail "patch 0060 does not touch $f"
done

python3 - "$PATCH" <<'PY' || exit 1
import re, sys

raw = open(sys.argv[1]).read().splitlines()

def die(msg):
    print(f'files computer devices test: {msg}', file=sys.stderr)
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
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    return re.sub(r'(?<![:/])//.*$', '', text, flags=re.M)

CTRL = 'ui/file_manager/file_manager/foreground/js/aurade_devices_controller.ts'
GNI = 'ui/file_manager/file_names.gni'
CSS = 'ui/file_manager/file_manager/foreground/css/file_manager.css'
HTML = 'ui/file_manager/file_manager/main.html'
MAIN = 'ui/file_manager/file_manager/foreground/js/file_manager.ts'

ctrl = strip(added(CTRL))
gni = added(GNI)
css = strip(added(CSS))
html = added(HTML)
main = strip(added(MAIN))

# --- the new file has to be in the build, or it is dead text ----------------

if 'aurade_devices_controller.ts' not in gni:
    die('the new controller is not added to file_names.gni, so the TypeScript '
        'build never compiles it and the feature does not exist on the machine')
if 'new AuraDeDevicesController(' not in main:
    die('nothing constructs the controller, so it is compiled and never runs. '
        'Checking for the class name alone is not enough: the import line '
        'carries it too.')
if "from './aurade_devices_controller.js'" not in main:
    die('the controller is never imported')

# --- only in Computer -------------------------------------------------------

if 'RootType.LOCAL_ROOT' not in ctrl:
    die('the panel is not gated on the Computer root, so it would appear above '
        'every folder in the app')
if not re.search(r'\.hidden = !onComputer', ctrl):
    die('the panel visibility is not driven by whether this is Computer')

# --- emptied on the way out -------------------------------------------------

if not re.search(r'if \(!onComputer\) \{[^}]*textContent = \'\'', ctrl, re.S):
    die('the panel keeps its rows when hidden, so the previous machine state '
        'flashes up on the way back in')

# --- a late capacity answer cannot paint a rebuilt panel --------------------

if 'this.render_++' not in ctrl:
    die('renders are not numbered, so a slow capacity query cannot be told '
        'from a current one')
if not re.search(r'if \(render !== this\.render_\)', ctrl):
    die('a late capacity answer is never discarded')

# --- a disk that cannot answer keeps its row --------------------------------

if not re.search(r'if \(!stats \|\| !stats\.totalSize\) \{\s*\n\s*meter\.hidden = true;',
                 ctrl):
    die('a volume whose size cannot be read does not simply lose its bar; the '
        'row has to survive or hardware disappears because a stat call failed')

# --- no invented facts ------------------------------------------------------

if not re.search(r'if \(volume\.diskFileSystemType\)', ctrl):
    die('the filesystem is not guarded, so an unknown one would be rendered as '
        'undefined or guessed at')

# --- the icons are the artwork already in the tree --------------------------

if 'images/volumes/' not in css:
    die('the device icons do not come from the volume artwork already shipped')
for icon in ('hard_drive.svg', 'usb.svg', 'sd.svg', 'computer.svg'):
    if icon not in css:
        die(f'no rule draws {icon}, so that device type renders as nothing')
for prop in ('-webkit-mask-size', '-webkit-mask-repeat'):
    if prop not in css:
        die(f'the icons are missing {prop}, so they do not render at the right '
            'size or tile instead of sitting once in the middle')

# Every icon rule, not just one of them. A single icon that regressed to
# background-image would still leave -webkit-mask-image present elsewhere and
# would render as a fixed colour picture that looks wrong in one scheme.
icon_rules = re.findall(r"\[aurade-device-icon='[a-z]+'\]\s*\{([^}]*)\}", css)
if len(icon_rules) < 4:
    die(f'only {len(icon_rules)} device icon rules found; the common device '
        'types would render as nothing')
for body in icon_rules:
    if '-webkit-mask-image' not in body:
        die('a device icon is drawn without -webkit-mask-image, so it arrives '
            'as a fixed colour picture rather than taking the theme colour')
if 'background-image' in css:
    die('a device icon uses background-image, which cannot be tinted by the '
        'theme the way every other icon in this app is')

hexes = re.findall(r'#[0-9a-fA-F]{3,8}\b', re.sub(r'#aurade[\w-]*', '', css))
if hexes:
    die(f'the panel hardcodes {", ".join(sorted(set(hexes)))} instead of tokens')

# --- it takes height from the list, it does not float over it ---------------

if not re.search(r'#aurade-devices \{[^}]*flex: none', css, re.S):
    die('the panel is not flex: none, so it would grow with the window and '
        'push the listing out of view')
if re.search(r'#aurade-devices \{[^}]*position:\s*(absolute|fixed)', css, re.S):
    die('a positioned panel floats over the list instead of taking space')

# --- the picker dialogs never grow a device panel ---------------------------

if 'visibleif="full-page"' not in html:
    die('the panel is not marked full-page only, so the file picker dialogs '
        'would grow a device list they have no use for')

print('files computer devices test: PASS '
      '(registered in the build, Computer only, emptied when hidden, render '
      'guarded, rows survive a failed stat, shipped artwork, tokens only)')
PY
