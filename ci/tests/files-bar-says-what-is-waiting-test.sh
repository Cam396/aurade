#!/usr/bin/env bash
# The status bar says what is on the clipboard.
#
# Patch 0071 dims the files a cut is waiting on, which answers "which ones"
# for as long as you are standing in the folder they live in. Walk into another
# folder to paste and the clipboard is invisible again, and that is precisely
# the moment you want to know whether there is still something on it. This adds
# a segment that says so.
#
# Six ways this goes wrong, none of them visible in a screenshot:
#
# One: relying on an event that a cut does not fire. A cut changes neither the
# selection nor the directory contents, so none of the things the toolbar
# already listens to fire, and the bar keeps whatever it last said.
#
# Two: reporting a copy as well. A copy leaves the originals where they are.
# Nothing is pending, and saying files are ready to move would be false.
#
# Three: leaving the text behind when the count goes to zero. A paste or an
# Escape would leave the bar promising a move that has already happened or has
# been taken back.
#
# Four: dropping the announcement when there is no data model. The rows cannot
# be repainted without one, but the count has still changed, so an early return
# above the dispatch loses the update.
#
# Five: adding the span to the stylesheet and not to main.html, or the reverse.
# Either way there is a rule with nothing to style or a span with no styling.
#
# Six: taking the auto margin off the count without giving it to something
# else. That margin is what holds the bar's layout apart; with no element
# carrying it every segment packs against the start.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0073-files-the-bar-says-what-is-waiting.patch"

fail() { echo "files bar says what is waiting test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0073 is missing'
grep -Fqx '0073-files-the-bar-says-what-is-waiting.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0073 is not listed in SERIES, so the series never applies it'

targets=$(grep -c '^diff --git ' "$PATCH")
[[ $targets -eq 5 ]] || fail "expected exactly 5 files, found ${targets}"
for f in ui/file_manager/file_manager/foreground/js/aurade_cut_marks.ts \
         ui/file_manager/file_manager/foreground/js/file_transfer_controller.ts \
         ui/file_manager/file_manager/foreground/js/toolbar_controller.ts \
         ui/file_manager/file_manager/foreground/css/file_manager.css \
         ui/file_manager/file_manager/main.html; do
  grep -Fq "+++ b/$f" "$PATCH" || fail "patch 0073 does not touch $f"
done

# 0071 owns the set this counts, and 0054 owns the bar it writes into.
for dep in 0071-files-a-cut-file-stays-dimmed.patch 0054-files-status-bar.patch; do
  grep -Fqx "$dep" "$ROOT/patches/SERIES" || \
    fail "$dep is not in SERIES, so 0073 has nothing to count or nowhere to say it"
done

python3 - "$PATCH" <<'PY' || exit 1
import re, sys

raw = open(sys.argv[1]).read().splitlines()

def die(msg):
    print('files bar says what is waiting test: ' + msg, file=sys.stderr)
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
    explanation alone.

    Stateful and line oriented, never a re.S span from /* to */, because diff
    alignment can leave an added line holding an unbalanced /** whose closing
    */ is hundreds of lines below."""
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
CSS = 'ui/file_manager/file_manager/foreground/css/file_manager.css'
HTML = 'ui/file_manager/file_manager/main.html'

def added(path):
    return strip(l[1:] for l in sections.get(path, [])
                 if l.startswith('+') and not l.startswith('+++'))

def post(path):
    return strip(l[1:] for l in sections.get(path, [])
                 if (l.startswith('+') and not l.startswith('+++'))
                 or l.startswith(' '))

mod, xfer, bar = added(MOD), added(XFER), added(BAR)
xfer_post, bar_post = post(XFER), post(BAR)
css, css_post, html = added(CSS), post(CSS), added(HTML)

# --- the count is exposed ----------------------------------------------------

if not re.search(r'export function auraDeCutCount\(\): number \{\s*\n\s*'
                 r'return cutUrls\.size;', mod):
    die('the cut set does not report its size, so nothing can say how many '
        'files are waiting')

# --- a cut announces itself --------------------------------------------------

if "dispatchEvent(new CustomEvent('aurade-cut-changed'))" not in xfer:
    die('a cut announces nothing, so the bar keeps whatever it last said: a '
        'cut changes neither the selection nor the directory, so none of the '
        'events the toolbar already listens to fire for it')

# The dispatch has to be reachable when there is no data model. The rows cannot
# be repainted without one, but the count has still changed.
repaint = re.search(
    r'private auraDeRedrawForCutMarks_\(\)[^{]*\{(.*?)\n  \}', xfer_post, re.S)
if not repaint:
    die('cannot find the repaint, so whether the announcement is reachable '
        'cannot be checked')
body = repaint.group(1)
guard = re.search(r'if \(!model\) \{\s*\n\s*return;', body)
if guard:
    die('the repaint still returns early when there is no data model, so the '
        'announcement below it never runs and the bar is left stale')
if not re.search(r'if \(model\) \{', body):
    die('the row walk is no longer guarded on the model at all, so it throws '
        'when there is none')
model_at = body.find('if (model) {')
dispatch_at = body.find('aurade-cut-changed')
if not model_at < dispatch_at:
    die('the announcement does not come after the row walk, so the bar can be '
        'told before the rows it describes have been brought into line')

# --- the bar listens and reports ---------------------------------------------

if not re.search(r"document\.addEventListener\(\s*'aurade-cut-changed',"
                 r"\s*this\.auraDeUpdateClipboard_\.bind\(this\)\)", bar):
    die('the toolbar does not listen for the announcement, so the segment only '
        'ever changes when something else happens to redraw the bar')

clip = re.search(
    r'private auraDeUpdateClipboard_\(\)[^{]*\{(.*?)\n  \}', bar_post, re.S)
if not clip:
    die('auraDeUpdateClipboard_ is missing, so nothing writes the segment')
clip_body = clip.group(1)

if 'auraDeCutCount()' not in clip_body:
    die('the segment is not written from the cut count')
# Zero has to blank it. Otherwise a paste or an Escape leaves the bar promising
# a move that has already happened or has been taken back.
#
# Scoped to the textContent assignment. A bare search for the zero test is
# answered by the title assignment three lines below, which carries an
# identical one, so it passed with the text left saying "7 files ready to move"
# forever. That is the third time in this repository an assertion has been
# satisfied by something other than the thing it was about.
text_assign = re.search(r'el\.textContent = (.*?);\n', clip_body, re.S)
if not text_assign:
    die('nothing assigns the segment text')
if not re.search(r"count === 0 \?\s*\n?\s*'' :", text_assign.group(1)):
    die('the segment text is not cleared when nothing is waiting, so after a '
        'paste or an Escape the bar still promises a move')
if "el.title = " not in clip_body:
    die('the segment carries no explanation, so a person who has forgotten '
        'what it means has nowhere to look')
# The title has to be cleared with the text, or an empty span keeps a tooltip.
if not re.search(r"el\.title = count === 0 \?", clip_body):
    die('the title outlives the text, so an empty segment still shows a '
        'tooltip about files that are no longer waiting')
if re.search(r"\bcount === 1 \?", clip_body) is None:
    die('the segment does not have a singular form, so it says 1 files')

# It is painted from the ordinary redraw as well, or a window whose bar is
# drawn while a cut is already live starts blank.
if 'this.auraDeUpdateClipboard_();' not in bar:
    die('the segment is only ever written from the event, so the first draw of '
        'the bar leaves it blank until the next cut')

# --- the span exists, and is styled ------------------------------------------

if 'id="aurade-status-clipboard"' not in html:
    die('the span is not in main.html, so there is nothing for any of this to '
        'write into')
if '#aurade-status-clipboard' not in css:
    die('the span is not styled, so it inherits nothing and sits wherever the '
        'flexbox puts it')
# And specifically in the group that gets tabular figures and an ellipsis. A
# count that ticks in proportional digits makes the whole bar jitter, and a
# long note with no ellipsis pushes the free space off the end.
shared = re.search(r'((?:#aurade-status-[a-z]+,\n)+#aurade-status-[a-z]+ \{)',
                   css_post)
if not shared or '#aurade-status-clipboard' not in shared.group(1):
    die('the segment is left out of the shared rule, so it gets neither '
        'tabular figures nor an ellipsis: the count jitters as it changes and '
        'a long note pushes the free space off the end of the bar')
# The auto margin is what holds the bar apart, and it moved from the count to
# the note. Checked on the post image, not the added lines: only the selector
# changed, so `margin-inline-end: auto;` and its closing brace are unchanged
# context and never appear as additions at all. An assertion on the added lines
# here fails against correct code, which is how this one was written first.
holder = re.search(r'#aurade-status-clipboard \{\s*\n\s*margin-inline-end: auto;',
                   css_post)
if not holder:
    die('the auto margin is not on the clipboard note, so the note is pushed '
        'out to the far end with the free space rather than sitting beside '
        'what is in this folder')
if re.search(r'#aurade-status-count \{\s*\n\s*margin-inline-end: auto;',
             css_post):
    die('the count still carries the auto margin as well, so there are two '
        'and everything between them is pushed apart')
PY

grep -nP '[\x{2014}\x{2013}]' "$PATCH" && \
  fail 'patch 0073 contains an em dash or an en dash' || true

echo 'files bar says what is waiting test: PASS '\
'(the count is exposed, a cut announces itself even with no model, the bar '\
'listens and reports it, zero blanks both the text and the tooltip, there is a '\
'singular form, and the auto margin moved rather than vanished)'
