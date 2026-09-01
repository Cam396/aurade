#!/usr/bin/env bash
# Colouring the file type icons, and the four ways it goes wrong quietly.
#
# The icons are masks painted with background-color, so a colour per type is a
# pure CSS change. That cheapness is the trap: every failure mode here still
# parses, still ships, and still looks like a working app.
#
# One, scope. The same [file-type-icon] attribute is used by the directory
# tree and by the menus, so a rule written without #list-container in front of
# it repaints the sidebar too and the window turns into a carnival. The tree
# rules are also more specific than a bare attribute selector, so an unscoped
# rule loses there and wins everywhere else, which is the worst of both.
#
# Two, the resets. A selected row swaps its icon for a checkmark and a
# thumbnailed row swaps it for the thumbnail, both by setting background to
# none at a much higher specificity. Any !important here beats those and
# leaves a coloured square where the checkmark belongs.
#
# Three, scheme parity. A token defined in one scheme and not the other is
# invisible in whichever scheme the author was not looking at.
#
# Four, plain text. getIcon falls back to the type name when a type declares
# no icon of its own, so .txt files arrive as 'text', for which upstream has no
# rule at all. Text is the most common thing in a real folder, so a palette
# that skips it is a palette nobody sees.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0053-files-type-icon-colour.patch"

fail() { echo "files type icon colour test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0053 is missing'
grep -Fqx '0053-files-type-icon-colour.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0053 is not listed in SERIES'

added=$(grep '^+' "$PATCH" | grep -v '^+++' || true)
[[ -n $added ]] || fail 'patch 0053 adds nothing'
# Added lines with the comment bodies dropped, so an assertion cannot pass on
# the prose that explains the thing instead of the thing.
code=$(grep -vE '^\+[[:space:]]*(\*|/\*)' <<<"$added" || true)

# --- it must stay one file, and an existing one -----------------------------

targets=$(grep -c '^diff --git ' "$PATCH")
[[ $targets -eq 1 ]] || fail "expected exactly 1 file, found ${targets}"

grep -q '^+++ b/ui/file_manager/file_manager/foreground/css/file_types\.css$' "$PATCH" || \
  fail 'patch 0053 does not target foreground/css/file_types.css'

grep -q '^--- /dev/null$' "$PATCH" && \
  fail 'patch 0053 creates a new file, which can never reach a machine through a pak swap'

# --- every colour rule is scoped to the list --------------------------------

# Selectors are the added lines that open a block. Any of them that mentions
# file-type-icon must also carry #list-container, or it repaints the sidebar.
unscoped=$(grep -E '^\+.*\[file-type-icon=' <<<"$code" | grep -v '#list-container' || true)
[[ -z $unscoped ]] || \
  fail "these type rules are not scoped to #list-container: ${unscoped//$'\n'/ }"

scoped_rules=$(grep -cE '^\+#list-container \[file-type-icon=' <<<"$code" || true)
[[ $scoped_rules -ge 10 ]] || \
  fail "expected at least 10 scoped type rules, found ${scoped_rules}"

# --- it must not outrank the checkmark and thumbnail resets -----------------

grep -qi '!important' <<<"$code" && \
  fail 'an !important here beats the [selected] and .has-thumbnail resets'

# --- both schemes, defined the way the cascade actually reads ---------------

grep -q '^+@media (prefers-color-scheme: dark) {$' <<<"$added" || \
  fail 'patch 0053 defines no dark scheme'

grep -qE '^\+html:not\(body\),$' <<<"$code" || \
  fail 'patch 0053 does not use the html:not(body) selector, so :root would lose to it'

grep -qE '^\+[[:space:]]*:root[[:space:]]*\{' <<<"$code" && \
  fail 'a bare :root block is specificity (0,1,0) and loses to html:not(body)'

# --- plain text is covered, because it is the common case -------------------

grep -qE "^\+#list-container \[file-type-icon='text'\] \{$" <<<"$code" || \
  fail "no rule for [file-type-icon='text'], which is what .txt files actually get"

# --- the folder colour is the brand's, not a lookalike ----------------------

grep -qE '^\+[[:space:]]*--aurade-ft-folder: #6d4ea1;$' <<<"$code" || \
  fail 'the light folder colour is not the AuraDE light primary #6d4ea1'
grep -qE '^\+[[:space:]]*--aurade-ft-folder: #d1bcff;$' <<<"$code" || \
  fail 'the dark folder colour is not the AuraDE dark primary #d1bcff'

# --- structural checks that a rename or a dropped token cannot survive ------

python3 - "$PATCH" <<'PY' || exit 1
import re, sys

added = [l[1:] for l in open(sys.argv[1]).read().splitlines()
         if l.startswith('+') and not l.startswith('+++')]
text = '\n'.join(added)

def die(msg):
    print(f'files type icon colour test: {msg}', file=sys.stderr)
    raise SystemExit(1)

# Split on the dark media query: everything before it is the light scheme.
parts = text.split('@media (prefers-color-scheme: dark)')
if len(parts) != 2:
    die('expected exactly one dark scheme block')
light_src, dark_src = parts

tok = re.compile(r'(--aurade-ft-[a-z]+)\s*:\s*(#[0-9a-f]{6})\s*;')
light = dict(tok.findall(light_src))
dark = dict(tok.findall(dark_src))

if not light:
    die('no light scheme tokens found')

# A token defined in one scheme only is invisible in the other.
only_light = sorted(set(light) - set(dark))
only_dark = sorted(set(dark) - set(light))
if only_light:
    die(f'defined only in the light scheme: {", ".join(only_light)}')
if only_dark:
    die(f'defined only in the dark scheme: {", ".join(only_dark)}')

# A scheme that is a copy of the other is a scheme nobody adjusted.
same = [k for k in light if light[k] == dark[k]]
if same:
    die(f'light and dark share a value for: {", ".join(same)}')

# Every token defined must be used, and every token used must be defined.
used = set(re.findall(r'var\((--aurade-ft-[a-z]+)\)', text))
unused = sorted(set(light) - used)
undefined = sorted(used - set(light))
if unused:
    die(f'defined but never used: {", ".join(unused)}')
if undefined:
    die(f'used but never defined: {", ".join(undefined)}')

# The point of the patch is that a folder of files stops being one grey. If
# the palette collapses to a couple of colours it has stopped being that.
if len(set(light.values())) < 8:
    die(f'only {len(set(light.values()))} distinct light colours, the list would still read as flat')

print(f'files type icon colour test: PASS '
      f'({len(light)} types, both schemes, {len(set(light.values()))} distinct colours)')
PY
