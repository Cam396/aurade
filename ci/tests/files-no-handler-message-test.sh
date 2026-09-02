#!/usr/bin/env bash
# What Files says when nothing opens a file, and the five ways it goes wrong.
#
# These four messages are the most visible ChromeOS text left in the app. They
# appear whenever somebody opens a file with no handler, which on a fresh Arch
# install is often, and every one of them named ChromeOS and offered a Google
# support link describing a system this is not.
#
# One: leaving any of the four. They are reached from one switch in
# file_tasks.ts, so fixing three of them leaves the fourth waiting.
#
# Two: replacing the Google link with another link. AuraDE has no support site,
# so a replacement URL is the same broken promise with a new address.
#
# Three: keeping the link markup. The text is rendered with showHtml, so a left
# behind anchor tag renders as a dead link rather than as visible markup, and
# nothing looks wrong until somebody clicks it.
#
# Four: leaving the $1 placeholder. The caller still passes the help URL, so a
# surviving $1 would print the Google URL into the sentence as plain text.
#
# Five: saying nothing useful. "Not supported" is true and worthless. The
# message has to say what to do about it.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0065-files-say-something-true-when-nothing-opens.patch"

fail() { echo "files no handler message test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0065 is missing'
grep -Fqx '0065-files-say-something-true-when-nothing-opens.patch' \
  "$ROOT/patches/SERIES" || fail 'patch 0065 is not listed in SERIES'

targets=$(grep -c '^diff --git ' "$PATCH")
[[ $targets -eq 1 ]] || fail "expected exactly 1 file, found ${targets}"

grep -Fq '+++ b/ui/chromeos/file_manager_strings.grdp' "$PATCH" || \
  fail 'patch 0065 does not touch the Files strings'

python3 - "$PATCH" <<'PY' || exit 1
import re, sys

raw = open(sys.argv[1]).read().splitlines()

def die(msg):
    print(f'files no handler message test: {msg}', file=sys.stderr)
    raise SystemExit(1)

added = '\n'.join(l[1:] for l in raw
                  if l.startswith('+') and not l.startswith('+++'))
removed = '\n'.join(l[1:] for l in raw
                    if l.startswith('-') and not l.startswith('---'))

# The message bodies only, never the desc attribute. A desc is documentation
# for translators and is not shown to anybody, so a rule applied to it would
# pass or fail on text no user can read.
def bodies(text):
    # Split on the opening tag rather than matching through </message>. The
    # closing tag is identical before and after, so diff keeps it as context
    # and it appears in neither the added nor the removed lines. A regex
    # anchored on it matches nothing and every assertion below silently
    # becomes an assertion about an empty set.
    out = {}
    parts = re.split(r'<message name="IDS_FILE_BROWSER_(NO_TASK_FOR_[A-Z_]+)"',
                     text)
    for i in range(1, len(parts), 2):
        name = parts[i]
        chunk = parts[i + 1]
        body = chunk.split('>', 1)[1] if '>' in chunk else ''
        out[name] = ' '.join(body.replace('</message>', ' ').split())
    return out

new = bodies(added)
old = bodies(removed)

REACHED = ('NO_TASK_FOR_FILE', 'NO_TASK_FOR_EXECUTABLE', 'NO_TASK_FOR_DMG',
           'NO_TASK_FOR_CRX')

for name in REACHED:
    if name not in old:
        die(f'{name} is not rewritten. All four are reached from one switch in '
            'file_tasks.ts, so leaving one leaves it waiting')
    if name not in new:
        die(f'{name} is removed rather than replaced, so the app would show an '
            'empty dialog')

for name, body in new.items():
    if re.search(r'ChromeOS|Chrome OS|Chrome device', body):
        die(f'{name} still names ChromeOS')
    if re.search(r'support\.google\.com|Google Chrome|Chrome Web Store', body):
        die(f'{name} still points at Google')
    if re.search(r'https?://', body):
        die(f'{name} carries a link. AuraDE has no support site, so any URL '
            'here is the same broken promise with a new address')
    if re.search(r'&lt;a |BEGIN_LINK|END_LINK', body):
        die(f'{name} keeps the anchor markup. showHtml renders it, so it would '
            'be a dead link that looks like a live one')
    if '$1' in body:
        die(f'{name} keeps the $1 placeholder, and the caller still passes the '
            'help URL, so the Google URL prints into the sentence')

# --- the common one has to be actionable ------------------------------------

common = new['NO_TASK_FOR_FILE']
if not re.search(r'\bInstall\b', common):
    die('the message for a file with no handler does not say what to do about '
        'it. On this system the answer is to install something that opens it, '
        'and a message that only reports the problem is worth nothing')

# --- the platform ones stay honest about what they are ----------------------

if 'Windows' not in new['NO_TASK_FOR_EXECUTABLE']:
    die('the Windows executable message no longer says it is a Windows program')
if 'macOS' not in new['NO_TASK_FOR_DMG']:
    die('the disk image message no longer says which system it is for')

# --- and none of them acquired a dash ---------------------------------------

for name, body in new.items():
    # Escapes and not the characters themselves: this file is checked by
    # ci/tests/house-style-test.sh, which bans both dashes tree wide, and a
    # literal one here fails that gate even though it is the thing being
    # looked for.
    if re.search('[\\u2013\\u2014]', body):
        die(f'{name} contains an em or en dash')

print('files no handler message test: PASS '
      f'({len(new)} messages rewritten, no ChromeOS naming, no link, no dead '
      'markup, no stray placeholder, the common one says what to do)')
PY
