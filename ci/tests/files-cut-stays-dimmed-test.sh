#!/usr/bin/env bash
# A cut file stays dimmed until it is pasted. The patch must register every
# source file, apply the class while rows render, and clear the marks after a
# copy or paste. The checks below cover those cases and the visible repaint.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0071-files-a-cut-file-stays-dimmed.patch"

fail() { echo "files cut stays dimmed test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0071 is missing'
grep -Fqx '0071-files-a-cut-file-stays-dimmed.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0071 is not listed in SERIES, so the series never applies it'

targets=$(grep -c '^diff --git ' "$PATCH")
[[ $targets -eq 5 ]] || fail "expected exactly 5 files, found ${targets}"
for f in ui/file_manager/file_manager/foreground/js/aurade_cut_marks.ts \
         ui/file_manager/file_names.gni \
         ui/file_manager/file_manager/foreground/css/file_manager.css \
         ui/file_manager/file_manager/foreground/js/file_transfer_controller.ts \
         ui/file_manager/file_manager/foreground/js/ui/file_table_list.ts; do
  grep -Fq "+++ b/$f" "$PATCH" || fail "patch 0071 does not touch $f"
done

python3 - "$PATCH" <<'PY' || exit 1
import re, sys

raw = open(sys.argv[1]).read().splitlines()

def die(msg):
    print('files cut stays dimmed test: ' + msg, file=sys.stderr)
    raise SystemExit(1)

sections, cur = {}, None
for line in raw:
    if line.startswith('diff --git '):
        cur = line.split(' b/')[-1]
        sections[cur] = []
    elif cur:
        sections[cur].append(line)

def strip(lines):
    """Remove comments. The prose in the new module explains the whole design,
    so a grep on unstripped text passes on the explanation alone.

    Stateful and line oriented, never a re.S span from /* to */. That form ate
    real code in this repository once, because diff alignment can leave an added
    line holding an unbalanced /** whose closing */ is hundreds of lines below.
    Tracking the state per file section cannot run away like that."""
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

def added(path):
    return strip(l[1:] for l in sections.get(path, [])
                 if l.startswith('+') and not l.startswith('+++'))

def post(path):
    return strip(l[1:] for l in sections.get(path, [])
                 if (l.startswith('+') and not l.startswith('+++'))
                 or l.startswith(' '))

MOD = 'ui/file_manager/file_manager/foreground/js/aurade_cut_marks.ts'
GNI = 'ui/file_manager/file_names.gni'
CSS = 'ui/file_manager/file_manager/foreground/css/file_manager.css'
XFER = 'ui/file_manager/file_manager/foreground/js/file_transfer_controller.ts'
LIST = 'ui/file_manager/file_manager/foreground/js/ui/file_table_list.ts'

mod, gni, css = added(MOD), added(GNI), added(CSS)
xfer, xfer_post = added(XFER), post(XFER)
lst, lst_post = added(LIST), post(LIST)

# --- the new module is in the build -----------------------------------------

if 'aurade_cut_marks.ts' not in gni:
    die('the new module is not added to file_names.gni, so the TypeScript '
        'build never compiles it and the feature does not exist on the machine')

# --- the set is keyed by URL ------------------------------------------------

if not re.search(r'cutUrls\.add\(entry\.toURL\(\)\)', mod):
    die('entries are not stored by URL, so a row rebuilt during scrolling '
        'holds a different object and stops matching what was cut')
if not re.search(r'cutUrls\.has\(entry\.toURL\(\)\)', mod):
    die('the lookup does not use the URL, so it cannot match what was stored')
# The empty check in auraDeIsCut is not decoration. That function runs from the
# row renderer for every visible row on every scroll, and without it each row
# pays for an entry.toURL() to ask a set that is empty. Set.has on an empty set
# is false either way, so this can only ever be caught by asserting on it.
is_cut_body = re.search(
    r'export function auraDeIsCut\([^{]*\{(.*?)\n\}', mod, re.S)
if not is_cut_body:
    die('auraDeIsCut is gone, so no row can know it was cut')
if 'cutUrls.size === 0' not in is_cut_body.group(1):
    die('auraDeIsCut does not short circuit on an empty set, so every rendered '
        'row builds a URL to query a set that holds nothing, on every scroll')

# --- a second cut replaces the first ----------------------------------------

if not re.search(r'export function auraDeMarkCut[^}]*cutUrls\.clear\(\)',
                 mod, re.S):
    die('marking a new cut does not clear the previous one, so files from an '
        'abandoned cut stay dimmed alongside the real ones')

# --- clearing reports whether it did anything -------------------------------

# Scoped to auraDeClearCut's own body. auraDeIsCut carries the identical
# early return, so a bare search for it passes even after auraDeClearCut has
# lost it entirely. That is how this assertion first failed to fail.
clear_body = re.search(
    r'export function auraDeClearCut\(\)[^{]*\{(.*?)\n\}', mod, re.S)
if not clear_body:
    die('auraDeClearCut is gone, so nothing can forget a cut')
if 'return false' not in clear_body.group(1):
    die('auraDeClearCut does not report an empty set, so every copy and paste '
        'forces a full list redraw whether or not anything was marked')
if 'cutUrls.clear()' not in clear_body.group(1):
    die('auraDeClearCut does not actually clear the set')

# --- the class is applied while the row renders -----------------------------

if not re.search(r"li\.classList\.toggle\('aurade-cut', auraDeIsCut\(entry\)\)",
                 lst):
    die('the row is never marked from the render path, so the dimming does not '
        'survive a row being recycled by scrolling')
# Anchored between two toggles that only exist inside
# updateListItemExternalProps, rather than on the function declaration. The
# declaration sits more than ten lines above and is not in the hunk, so
# asserting on it could never fail for the right reason.
before = lst_post.find("'is-dlp-restricted', externalProps.isDlpRestricted")
toggle = lst_post.find("li.classList.toggle('aurade-cut'")
after = lst_post.find("li.classList.toggle('shortcut'")
if before < 0 or toggle < 0 or after < 0:
    die('cannot locate the row updater: the patch no longer carries the dlp '
        'and shortcut toggles around the new one as context, so whether the '
        'marking landed inside updateListItemExternalProps cannot be checked')
if not before < toggle < after:
    die('the aurade-cut toggle is not inside updateListItemExternalProps, '
        'which is the only function that runs for every rendered row')

# --- a cut marks, a copy forgets ---------------------------------------------

if not re.search(r'if \(isMove\) \{\s*\n\s*auraDeMarkCut\(', xfer):
    die('a cut does not mark anything, or marks on copy as well, which would '
        'dim files that are not going anywhere')
if not re.search(r'\} else if \(auraDeClearCut\(\)\) \{', xfer):
    die('a copy does not clear a previous cut, so the old files stay dimmed '
        'while the clipboard now holds something else entirely')

# --- a paste forgets ----------------------------------------------------------

consumed = re.search(r"if \(effect === 'move'\) \{\s*\n\s*if \(auraDeClearCut\(\)\)",
                     xfer_post)
if not consumed:
    die('a completed move does not clear the marks, so the files stay dimmed '
        'after they have already been pasted somewhere else')

# --- the repaint is real, and is not called from the render path -------------

if 'auraDeRedrawForCutMarks_' in lst:
    die('the row renderer triggers a repaint, which is a render that causes a '
        'render')

# Over the post image, not the added lines. The whole method is added but its
# closing brace is not: it is the unchanged brace that already closed the
# method below it, so in the added lines alone the body runs on into the next
# hunk and the bound never arrives. Ended on a two space closing brace so a
# method defined before its caller cannot swallow the call site and read as
# something it is not.
repaint = re.search(
    r'private auraDeRedrawForCutMarks_\(\)[^{]*\{(.*?)\n  \}',
    xfer_post, re.S)
if not repaint:
    die('nothing repaints the rows, so the dimming only appears on whatever '
        'happens to be rendered next')
body = repaint.group(1)

if re.search(r'\.redraw\(\)', body):
    die('the repaint calls redraw. Redraw reuses the rows it already has: '
        'mergeItems takes cachedItems_[index] when one exists and only calls '
        'createItem when it does not, so the render path that applies the '
        'class never runs again for a row already on screen. This dims nothing '
        'on the rows in front of the person who just pressed the keys')
if not re.search(r"querySelectorAll<ListItem>\('li'\)", body):
    die('the repaint does not walk the rows that are on screen, so the rows '
        'rendered before the cut are never brought into line with it')
if 'listIndex' not in body:
    die('the repaint does not read listIndex, so it cannot map a row back to '
        'the entry it was drawn from')
if not re.search(r'model\.item\(index\)', body):
    die('the repaint never looks the entry up, so it cannot know which of the '
        'rows on screen are the cut ones')
if not re.search(r"classList\.toggle\('aurade-cut', auraDeIsCut\(entry\)\)",
                 body):
    die('the repaint walks the rows without toggling the class, so nothing '
        'changes on screen')
# toggle, not add. A copy and a paste call this to clear, and an add would
# leave every previously cut row dimmed forever.
if re.search(r"classList\.add\('aurade-cut'", body):
    die('the repaint adds the class rather than toggling it, so a copy or a '
        'paste can never take the dimming back off')

# --- and it is visibly different from the existing flash ---------------------

if not re.search(r'\.aurade-cut \{\s*\n\s*opacity: 0\.5;', css):
    die('the cut style is missing or is not an opacity, so nothing changes on '
        'screen')
if re.search(r'\.aurade-cut \{\s*\n\s*opacity: 0\.8;', css):
    die('the cut style reuses the 0.8 of the hundred millisecond flash, which '
        'is too slight to still read as unsettled a minute later')
PY

grep -nP '[\x{2014}\x{2013}]' "$PATCH" && \
  fail 'patch 0071 contains an em dash or an en dash' || true

echo 'files cut stays dimmed test: PASS '\
'(registered in the build, keyed by URL, marked from the render path so it '\
'survives scrolling, cleared by a copy and by a paste, repainted from the '\
'action and never from the renderer, repainted by walking the rows rather than '\
'by a redraw that would not have touched them, and dimmed further than the '\
'existing flash)'
