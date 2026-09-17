#!/usr/bin/env bash
# Escape cancels a cut and clears its marks without changing the clipboard.
#
# Clear the asynchronous clipboard directly; the command dispatcher does not
# emit the cut event needed to update the payload.
#
# Do not clear clipboard data owned by another application.
#
# Preserve Escape for dialogs and search when no cut is active.
#
# Ignore modified Escape.
#
# Leave text fields to handle Escape themselves.
#
# Repaint only when a cut was active.
#
# Register the handler on the document because focus can be anywhere in Files.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0072-files-escape-takes-back-a-cut.patch"

fail() { echo "files escape takes back a cut test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0072 is missing'
grep -Fqx '0072-files-escape-takes-back-a-cut.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0072 is not listed in SERIES, so the series never applies it'

targets=$(grep -c '^diff --git ' "$PATCH")
[[ $targets -eq 1 ]] || fail "expected exactly 1 file, found ${targets}"
grep -Fq '+++ b/ui/file_manager/file_manager/foreground/js/file_transfer_controller.ts' \
  "$PATCH" || fail 'patch 0072 does not touch file_transfer_controller.ts'

# 0071 owns the marks and the repaint this patch calls. Without it there is
# nothing to take back and the handler would not compile.
grep -Fqx '0071-files-a-cut-file-stays-dimmed.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0071 is not in SERIES, so nothing marks a cut for 0072 to clear'

python3 - "$PATCH" <<'PY' || exit 1
import re, sys

raw = open(sys.argv[1]).read().splitlines()

def die(msg):
    print('files escape takes back a cut test: ' + msg, file=sys.stderr)
    raise SystemExit(1)

sections, cur = {}, None
for line in raw:
    if line.startswith('diff --git '):
        cur = line.split(' b/')[-1]
        sections[cur] = []
    elif cur:
        sections[cur].append(line)

def strip(lines):
    """Remove comments. The prose above the handler explains every decision it
    makes, so a grep on unstripped text passes on the explanation alone.

    Stateful and line oriented, never a re.S span from /* to */, because diff
    alignment can leave an added line holding an unbalanced /** whose closing
    */ is hundreds of lines below. That form ate real code here once."""
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

XFER = 'ui/file_manager/file_manager/foreground/js/file_transfer_controller.ts'
added = strip(l[1:] for l in sections.get(XFER, [])
              if l.startswith('+') and not l.startswith('+++'))
post = strip(l[1:] for l in sections.get(XFER, [])
             if (l.startswith('+') and not l.startswith('+++'))
             or l.startswith(' '))

# --- the handler is on the document, next to the rest of the clipboard ------

if not re.search(r"this\.document_\.addEventListener\(\s*'keydown',"
                 r"\s*this\.auraDeOnKeyDown_\.bind\(this\)\)", added):
    die('the handler is not registered on the document, so Escape only reaches '
        'it when focus happens to be somewhere convenient, and a cut can be '
        'made with the directory tree focused')
# Anchored on the paste registration, which is the last line of
# attachCopyPasteHandlers_ and is context rather than an added line. The
# method declaration is far above and outside the hunk, so asserting on it
# could never fail for the right reason.
paste_at = post.find("this.document_.addEventListener('paste'")
key_at = post.find("'keydown', this.auraDeOnKeyDown_")
if paste_at < 0 or key_at < 0:
    die('cannot locate the clipboard handler registrations, so whether the '
        'keydown listener landed in attachCopyPasteHandlers_ cannot be checked')
if not paste_at < key_at:
    die('the keydown listener is not registered alongside the other clipboard '
        'handlers')

# --- scoped to the handler body ---------------------------------------------

# Ended on a two space closing brace. The method is added but the brace that
# ends it may be context, so the added lines alone can run on past it.
body_match = re.search(
    r'private auraDeOnKeyDown_\([^)]*\)[^{]*\{(.*?)\n  \}', post, re.S)
if not body_match:
    die('auraDeOnKeyDown_ is missing, so nothing takes a cut back')
body = body_match.group(1)

# --- it is Escape, and only bare Escape -------------------------------------

if "event.key !== 'Escape'" not in body:
    die('the handler does not check for Escape, so it runs on every key the '
        'document sees')
for mod in ('ctrlKey', 'altKey', 'metaKey', 'shiftKey'):
    if mod not in body:
        die('the handler does not exclude %s, so a modified Escape, which '
            'means something else entirely, also throws the cut away' % mod)

# --- not while a text field has focus ---------------------------------------

if 'isDocumentWideEvent_()' not in body:
    die('the handler does not reuse the focus guard, so Escape in the rename '
        'box or the search field, where it means cancel this edit, also '
        'discards the cut')

# --- nothing happens when there was no cut ----------------------------------

if not re.search(r'if \(!auraDeClearCut\(\)\) \{\s*\n\s*return;', body):
    die('the handler does not return early when nothing was cut, so every '
        'Escape in the app walks the rows and rewrites the system clipboard')
# Order matters: the repaint has to come after the clear, or it paints the
# rows from a set that still holds everything and nothing changes on screen.
clear_at = body.find('auraDeClearCut()')
paint_at = body.find('auraDeRedrawForCutMarks_()')
if clear_at < 0 or paint_at < 0:
    die('the handler does not both clear and repaint')
if not clear_at < paint_at:
    die('the rows are repainted before the marks are cleared, so they are '
        'painted from a set that still holds every cut file and the dimming '
        'stays exactly where it was')

# --- the clipboard goes too --------------------------------------------------

if 'auraDeForgetClipboardCut_()' not in body:
    die('the system clipboard is not emptied, so the dimming goes but Ctrl+V '
        'still moves the files, and the screen and the keyboard now disagree')

forget = re.search(
    r'private auraDeForgetClipboardCut_\(\)[^{]*\{(.*?)\n  \}', post, re.S)
if not forget:
    die('auraDeForgetClipboardCut_ is missing, so nothing empties the clipboard')
forget_body = forget.group(1)

# The whole point of the rewrite. execCommand('cut') on the dispatcher iframe
# returns false and fires no event, so an fs/clear payload is never written and
# the clipboard keeps the cut. This is asserted rather than remembered because
# it reads exactly like the working code a few methods below it.
if "'fs/clear'" in forget_body:
    die('the clipboard is cleared with an fs/clear payload through '
        "execCommand('cut'), which returns false on the dispatcher iframe and "
        'fires no cut event, so nothing is ever written and paste stays '
        'enabled. This shipped once and did nothing')
if 'navigator.clipboard.writeText' not in forget_body:
    die('the clipboard is not written through the async clipboard, which is '
        'the only route that works here')

# Guarded, so Escape cannot take away a clipboard that belongs to another app.
if "getData('fs/sources')" not in forget_body:
    die('the clipboard is emptied without checking it still holds a cut, so '
        'pressing Escape in Files destroys whatever another application had '
        'put there')
if "getData('fs/effectallowed') === 'move'" not in forget_body:
    die('the guard does not check the clipboard describes a move, so Escape '
        'after a cut also throws away a copy made in between')
guard_at = forget_body.find("getData('fs/sources')")
write_at = forget_body.find('navigator.clipboard.writeText')
if not guard_at < write_at:
    die('the clipboard is written before it is checked, so the guard cannot '
        'prevent anything')
if not re.search(r'if \(!holdsOurCut\) \{\s*\n\s*return;', forget_body):
    die('the guard is computed and not acted on, so every Escape after a cut '
        'empties the system clipboard whatever it holds')
if '.catch(' not in forget_body:
    die('the clipboard write is unhandled, so a rejected permission becomes an '
        'unhandled rejection in the console on an ordinary Escape')

# --- and the key is not swallowed -------------------------------------------

# preventDefault on the clipboard event inside simulateCommand_ is required
# and is not this. Checked on the handler's own parameter name, which is why
# the inner callback takes a different one.
if re.search(r'\bevent\.preventDefault\(\)', body):
    die('the handler swallows Escape, so cancelling a dialog and leaving '
        'search stop working for any press that follows a cut')
if re.search(r'\bevent\.stopPropagation\(\)', body):
    die('the handler stops Escape propagating, with the same effect')
PY

grep -nP '[\x{2014}\x{2013}]' "$PATCH" && \
  fail 'patch 0072 contains an em dash or an en dash' || true

echo 'files escape takes back a cut test: PASS '\
'(bare Escape only, never in a text field, nothing done when nothing was cut, '\
'cleared before the repaint, the system clipboard emptied through the async '\
'clipboard and only when it still holds the cut, and the key left alone for '\
'everything else it already means)'
