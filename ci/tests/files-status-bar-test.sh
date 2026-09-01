#!/usr/bin/env bash
# The status bar, and the four ways it breaks something else while looking fine.
#
# One, the picker. main.html is the same document for the full app and for the
# open and save dialogs. queryRequiredElement throws when it finds nothing, so
# looking the bar up that way turns every file picker in the OS into a broken
# one. The lookup has to tolerate absence, and the bar has to carry
# visibleif="full-page" so it never appears there in the first place.
#
# Two, the layout. The bar earns its place at the bottom by being flex: none
# next to a flex: auto list inside a column panel. Written as a positioned
# element instead it would sit on top of the last row, which looks correct
# until a folder is long enough to scroll.
#
# Three, narrowing. TypeScript drops narrowing on a mutable property across a
# method call, and this code calls one between the null check and the use, so
# the elements have to be held in locals. Reading them back off this compiles
# only while nothing in between is a call, which is a thing a later edit
# quietly breaks.
#
# Four, the title. auraDeDirectorySummary_ is what sets the title carrying the
# forty two note. Reading the title before calling it shows the previous
# folder's answer, which is worse than showing none.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0054-files-status-bar.patch"

fail() { echo "files status bar test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0054 is missing'
grep -Fqx '0054-files-status-bar.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0054 is not listed in SERIES'

added=$(grep '^+' "$PATCH" | grep -v '^+++' || true)
[[ -n $added ]] || fail 'patch 0054 adds nothing'
code=$(grep -vE '^\+[[:space:]]*(\*|/\*|//)' <<<"$added" || true)

# --- exactly the three files it needs ---------------------------------------

targets=$(grep -c '^diff --git ' "$PATCH")
[[ $targets -eq 3 ]] || fail "expected exactly 3 files, found ${targets}"

for f in main.html foreground/css/file_manager.css \
         foreground/js/toolbar_controller.ts; do
  grep -Fq "+++ b/ui/file_manager/file_manager/$f" "$PATCH" || \
    fail "patch 0054 does not touch $f"
done

grep -q '^--- /dev/null$' "$PATCH" && \
  fail 'patch 0054 creates a new file, which can never reach a machine through a pak swap'

# --- the markup -------------------------------------------------------------

grep -Fq '+                <div id="aurade-status-bar" visibleif="full-page">' <<<"$code" || \
  fail 'the bar is missing, or is missing visibleif="full-page" so it would appear in the file pickers'

for id in aurade-status-count aurade-status-selection; do
  grep -Fq "<span id=\"$id\"></span>" <<<"$code" || fail "the $id span is missing"
done

# --- the layout contract ----------------------------------------------------

grep -qE '^\+  flex: none;$' <<<"$code" || \
  fail 'the bar is not flex: none, so it will not keep its height beside a flex: auto list'

grep -qE '^\+  position: (absolute|fixed);' <<<"$code" && \
  fail 'a positioned bar overlays the last row instead of taking space from the list'

# --- the lookup must tolerate absence ---------------------------------------

grep -q 'queryRequiredElement' <<<"$code" && \
  fail 'queryRequiredElement throws when absent, which breaks the file pickers'

grep -qE '^\+    if \(!count \|\| !selectionEl\) \{$' <<<"$code" || \
  fail 'the null guard is gone, so the pickers would throw on every selection change'

# --- structural checks ------------------------------------------------------

python3 - "$PATCH" <<'PY' || exit 1
import re, sys

raw = open(sys.argv[1]).read().splitlines()

def die(msg):
    print(f'files status bar test: {msg}', file=sys.stderr)
    raise SystemExit(1)

# Split the patch into per-file sections so each can be checked on its own.
sections, cur = {}, None
for line in raw:
    if line.startswith('diff --git '):
        cur = line.split(' b/')[-1]
        sections[cur] = []
    elif cur:
        sections[cur].append(line)

def added(path):
    return [l[1:] for l in sections[path]
            if l.startswith('+') and not l.startswith('+++')]

css = '\n'.join(added('ui/file_manager/file_manager/foreground/css/file_manager.css'))
ts = '\n'.join(added('ui/file_manager/file_manager/foreground/js/toolbar_controller.ts'))

# The bar has to theme with everything else, so no literal colours.
hexes = re.findall(r'#[0-9a-fA-F]{3,8}\b', re.sub(r'/\*.*?\*/', '', css, flags=re.S))
if hexes:
    die(f'the status bar CSS hardcodes {", ".join(sorted(set(hexes)))} instead of theme tokens')
for token in ('--cros-sys-separator', '--cros-sys-on_surface_variant',
              '--cros-sys-primary'):
    if token not in css:
        die(f'the status bar CSS does not use {token}')

# Strip comments before reasoning about the code's order.
body = re.sub(r'/\*.*?\*/', '', ts, flags=re.S)

# The elements must be used through locals, never read back off this after the
# guard, or strict mode loses the narrowing across auraDeDirectorySummary_.
for prop in ('auraDeStatusCount_', 'auraDeStatusSelection_'):
    for use in (f'this.{prop}.textContent', f'this.{prop}.title'):
        if use in body:
            die(f'{use} reads the property back after the guard, '
                f'which does not narrow across a method call')

if 'const count = this.auraDeStatusCount_ ??' not in body:
    die('the count element is not held in a local')
if 'const selectionEl = this.auraDeStatusSelection_ ??' not in body:
    die('the selection element is not held in a local')

# The summary call has to come before the title is read from the label.
call = body.find('this.auraDeDirectorySummary_()')
title = body.find('count.title = this.filesSelectedLabel_.title')
if call < 0:
    die('auraDeDirectorySummary_ is never called, so the count would go stale')
if title < 0:
    die('the forty two title is never mirrored onto the bar, so it stays unreachable')
if call > title:
    die('the title is read before auraDeDirectorySummary_ sets it, '
        'so the bar shows the previous folder\'s note')

# An empty folder says so rather than going blank.
if "'Empty folder'" not in body:
    die('an empty folder leaves the bar blank, which reads as broken')

# The selection half stays empty with no selection, so it does not just repeat
# what the toolbar is already showing.
if 'totalCount === 0' not in body:
    die('the selection half does not clear itself when nothing is selected')

print('files status bar test: PASS '
      '(3 files, tokens not literals, locals not properties, summary before title)')
PY
