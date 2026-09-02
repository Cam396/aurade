#!/usr/bin/env bash
# Type a few letters and land on the file.
#
# Six ways this goes wrong and not one of them shows up in a screenshot:
#
# One: swallowing keys inside the rename box. The keydown handler on
# #list-container sees the rename input's keys, and the existing guard returns
# early for an INPUT. If type ahead runs before that guard, typing a new file
# name jumps the selection around underneath you and the rename lands on the
# wrong row.
#
# Two: stealing real shortcuts. Ctrl, Alt and Meta belong to commands. Shift
# does not, and excluding it would make capital letters unsearchable.
#
# Three: eating named keys. ArrowDown, Escape and F2 all arrive as keydown.
# A length check on event.key separates printable keys from named ones without
# a list that would rot.
#
# Four: a bare space. A file name can contain one, so it has to be typeable
# once a search is running, but on an empty buffer a lone space still belongs
# to whatever else wants it.
#
# Five: repeating a letter searching for it doubled. Pressing p four times has
# to walk through the files starting with p, which is what every other file
# manager does and therefore what fingers expect.
#
# Six: preventDefault on a key that did nothing. If no file matched, the key
# has to stay available to everything downstream.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0070-files-type-to-jump.patch"

fail() { echo "files type to jump test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0070 is missing'
grep -Fqx '0070-files-type-to-jump.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0070 is not listed in SERIES, so the series never applies it'

targets=$(grep -c '^diff --git ' "$PATCH")
[[ $targets -eq 1 ]] || fail "expected exactly 1 file, found ${targets}"
grep -Fq '+++ b/ui/file_manager/file_manager/foreground/js/ui/list_container.ts' \
  "$PATCH" || fail 'patch 0070 does not touch list_container.ts'

python3 - "$PATCH" <<'PY' || exit 1
import re, sys

raw = open(sys.argv[1]).read().splitlines()

def die(msg):
    print('files type to jump test: ' + msg, file=sys.stderr)
    raise SystemExit(1)

body = [l for l in raw if not l.startswith('+++') and not l.startswith('---')
        and not l.startswith('diff --git ')]

def strip(lines):
    """Drop comment lines. The prose here names every symbol the code uses, so
    a grep on the unstripped text would pass on the explanation alone.

    Line oriented on purpose: a stripper spanning /* to */ with re.S ate real
    code once in this repository, because diff alignment can leave an added
    line holding an unbalanced /** whose closing */ is far below."""
    out = []
    for l in lines:
        s = re.sub(r'(?<![:/])//.*$', '', l)
        if s.strip():
            out.append(s)
    return '\n'.join(out)

added = strip(l[1:] for l in body if l.startswith('+'))
post = strip(l[1:] for l in body if l.startswith('+') or l.startswith(' '))

# --- the rename guard still runs first --------------------------------------

guard = post.find("srcElement?.tagName === 'INPUT'")
call = post.find('this.auraDeTypeAhead_(event as KeyboardEvent)')
if guard < 0 or call < 0:
    die('cannot locate the handler: the patch no longer carries the INPUT '
        'guard and the type ahead call together as context, so their order '
        'cannot be checked')
if not guard < call:
    die('type ahead runs before the rename input guard, so typing a new file '
        'name jumps the selection around and the rename lands on another row')

# --- modifiers ---------------------------------------------------------------

mods = re.search(r'if \(([^)]*(?:ctrlKey|altKey|metaKey)[^)]*)\) \{', added)
if not mods:
    die('nothing checks for Ctrl, Alt or Meta, so type ahead swallows real '
        'shortcuts before the commands can see them')
for m in ('ctrlKey', 'altKey', 'metaKey'):
    if m not in mods.group(1):
        die('the modifier guard does not cover %s' % m)
if 'shiftKey' in mods.group(1):
    die('the modifier guard excludes Shift, which is how capital letters are '
        'typed, so any name beginning with one becomes unreachable')

# --- printable keys only -----------------------------------------------------

if not re.search(r'event\.key\.length !== 1', added):
    die('nothing separates printable keys from named ones, so ArrowDown, '
        'Escape and F2 are treated as search text')

# --- a bare space does not start a search ------------------------------------

if not re.search(r"typed === ' ' && !previous", added):
    die('a bare space starts a search on an empty buffer, taking the key from '
        'whatever else uses it')

# --- repeating a letter cycles ----------------------------------------------

if not re.search(r'const cycling = previous === typed;', added):
    die('repeating one letter extends the buffer instead of walking through '
        'the files starting with it, so pressing p twice searches for pp')
if not re.search(r'const buffer = cycling \? typed : previous \+ typed;', added):
    die('the buffer does not distinguish a repeat from an extension')

# --- the search wraps and is case insensitive --------------------------------

if not re.search(r'% model\.length', added):
    die('the scan does not wrap, so a match above the selection is never found')
if not re.search(r'\.toLowerCase\(\)\.startsWith\(buffer\)', added) or \
        not re.search(r'event\.key\.toLowerCase\(\)', added):
    die('the match is case sensitive on one side or both, so typing r misses '
        'Reports')

# --- it actually moves the view ---------------------------------------------

if not re.search(r'selection\.selectedIndex = index;', added):
    die('a match is found and never selected')
if not re.search(r'list\.scrollIndexIntoView\(index\)', added):
    die('the match is selected without being scrolled to, so on a long list '
        'the selection moves somewhere off screen')

# --- and only swallows a key that did something ------------------------------

swallow = re.search(
    r'if \(this\.auraDeTypeAhead_\(event as KeyboardEvent\)\) \{\s*\n\s*'
    r'event\.preventDefault\(\);', added)
if not swallow:
    die('preventDefault is not gated on the jump having happened, so a key '
        'that matched nothing is taken away from everything downstream')

# --- the buffer expires ------------------------------------------------------

if not re.search(r'const AURADE_TYPE_AHEAD_RESET_MS = \d+;', added):
    die('there is no reset window, so a prefix typed minutes ago is still '
        'being extended')
if not re.search(r'> AURADE_TYPE_AHEAD_RESET_MS', added):
    die('the reset window is declared and never compared against')
PY

grep -nP '[\x{2014}\x{2013}]' "$PATCH" && \
  fail 'patch 0070 contains an em dash or an en dash' || true

echo 'files type to jump test: PASS '\
'(runs after the rename guard, leaves Ctrl Alt and Meta alone but not Shift, '\
'printable keys only, space continues but never starts, a repeated letter '\
'cycles, the scan wraps and ignores case, and it only swallows a key that moved)'
