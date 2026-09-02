#!/usr/bin/env bash
# The gear menu stops offering what this system cannot do, and the six ways
# that goes wrong.
#
# One: removing the menu item and leaving the command reachable. Any other
# surface that binds the id gets the dead item back, and nothing says so.
#
# Two: hiding Help but not Send feedback, or the other way round. Both are
# ChromeOS routes: one opens a Google support page describing a system this is
# not, the other calls into a feedback app that is not installed here and
# therefore does nothing at all, silently.
#
# Three: leaving the item enabled while hidden. A hidden but enabled command
# still runs from a keyboard binding or a submenu.
#
# Four: an orphaned import. Removing the only use of isModal without removing
# the import fails the build, which is the good case; the bad case is somebody
# restoring the import to fix a build and quietly restoring the behaviour.
#
# Five: replacing the removed items with another link. There is no support site
# to promise, so a replacement link is the same broken promise with a new URL.
#
# Six: inventing a version. The Files app is served the browser's user agent
# and no build stamp of its own, so a user agent with no version has to fall
# back to the name alone rather than print undefined.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0064-files-menus-stop-promising-chromeos.patch"

fail() { echo "files honest menus test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0064 is missing'
grep -Fqx '0064-files-menus-stop-promising-chromeos.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0064 is not listed in SERIES'

targets=$(grep -c '^diff --git ' "$PATCH")
[[ $targets -eq 3 ]] || fail "expected exactly 3 files, found ${targets}"

for f in ui/file_manager/file_manager/foreground/js/command_handler.ts \
         ui/file_manager/file_manager/foreground/js/file_manager_commands.ts \
         ui/file_manager/file_manager/main.html; do
  grep -Fq "+++ b/$f" "$PATCH" || fail "patch 0064 does not touch $f"
done

python3 - "$PATCH" <<'PY' || exit 1
import re, sys

raw = open(sys.argv[1]).read().splitlines()

def die(msg):
    print(f'files honest menus test: {msg}', file=sys.stderr)
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

def removed(path):
    return '\n'.join(l[1:] for l in sections.get(path, [])
                     if l.startswith('-') and not l.startswith('---'))

def strip(text):
    """Line oriented: added lines come from every hunk and a doc comment can
    arrive with an opener and no closer, so a regex spanning the delimiters
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
cmds_gone = strip(removed(CMDS))
handler = added(HANDLER)
html_added = added(HTML)
html_gone = removed(HTML)

# --- both ChromeOS routes are turned off, in the command not just the menu ---

hides = re.findall(r'event\.canExecute = false;\s*\n\s*event\.command\.setHidden\(true\);',
                   cmds)
if len(hides) < 2:
    die(f'only {len(hides)} command is hidden at the source. Both Help and Send '
        'feedback have to be, or removing the menu item just moves the dead '
        'item to whatever else binds the id')

# Enabled and hidden is not the same as gone: a hidden command still runs from
# a keyboard binding. Every hide above pairs canExecute false with setHidden.
if re.search(r'event\.canExecute = true;\s*\n\s*event\.command\.setHidden\(true\)',
             cmds):
    die('a command is hidden while still enabled, so it runs from anything that '
        'is not the menu')

# --- the menu items are gone -------------------------------------------------

for gone in ('command="#volume-help"', 'command="#send-feedback"'):
    if gone not in html_gone:
        die(f'{gone} is still in the gear menu')

# --- and are not replaced by another link ------------------------------------

if re.search(r'https?://', html_added):
    die('the removed items were replaced with another link. There is no support '
        'site to promise, so a replacement URL is the same broken promise')
if re.search(r'visitURL\(', cmds):
    die('the replacement command opens a URL')

# --- the replacement is reachable --------------------------------------------

if "'about-aurade-files': new AboutAuraDeCommand()" not in handler:
    die('the About command is not registered, so its menu item is inert. '
        'Checking for the class name alone is not enough: the import line '
        'carries it too.')
if '<command id="about-aurade-files"' not in html_added:
    die('main.html never declares the About command')
if 'command="#about-aurade-files"' not in html_added:
    die('nothing in the gear menu invokes the About command')

# --- no invented version -----------------------------------------------------

if not re.search(r"match \? `AuraDE Files, on Chromium \$\{match\[1\]\}` :", cmds):
    die('the version is not read out of a match, so a user agent without one '
        'prints undefined into the toast')
if not re.search(r"'AuraDE Files'", cmds):
    die('there is no fallback for a user agent that carries no version')

# --- the orphaned import is removed ------------------------------------------

if "import {isModal} from '../../common/js/dialog_type.js';" not in cmds_gone:
    die('the isModal import is left behind with no use, which fails the build; '
        'the tempting repair is to restore the use, which restores the dead '
        'Help item')
if 'isModal' in cmds:
    die('isModal is used again, so the modal only hiding is back and Help '
        'returns outside a dialog')

print('files honest menus test: PASS '
      '(both routes hidden at the command, items removed, no replacement link, '
      'About reachable, version not invented, orphaned import removed)')
PY
