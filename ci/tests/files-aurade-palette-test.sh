#!/usr/bin/env bash
# The Files palette, and the two ways it silently does nothing.
#
# First, the selector. Chromium's token generators emit "html:not(body)", which
# is specificity (0,1,1). A ":root" block is (0,1,0) and loses to it, so an
# override written that way is parsed, applied, and beaten, and the app looks
# exactly as it did. That is not a hypothetical: it is what the first version
# of this patch did, and it took a full build and deploy to the hardware to
# notice, because nothing anywhere reports it.
#
# Second, the file it lives in. A new stylesheet would mint a new pak resource
# id, and ci/pak-swap-resources.py refuses to insert ids the target does not
# already have, so a new file can never reach a machine without a full chrome
# link. The theme therefore has to be appended to a stylesheet that already
# ships and that is already linked after chrome://theme/colors.css.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0051-files-aurade-palette.patch"

fail() { echo "files aurade palette test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0051 is missing'
grep -Fqx '0051-files-aurade-palette.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0051 is not listed in SERIES'

added=$(grep '^+' "$PATCH" | grep -v '^+++' || true)
[[ -n $added ]] || fail 'patch 0051 adds nothing'
code=$(grep -vE '^\+[[:space:]]*(\*|/\*)' <<<"$added" || true)

# 1. It must land in a file that already ships. One file, and that file.
files=$(grep '^diff --git' "$PATCH" | sed 's|diff --git a/||;s| b/.*||' | sort -u)
[[ $files == 'ui/file_manager/file_manager/foreground/css/file_manager.css' ]] || \
  fail "the theme must be appended to file_manager.css, which already ships; it touches: ${files//$'\n'/ }"
if grep -q '^--- /dev/null' "$PATCH"; then
  fail 'the patch creates a new file, which mints a pak id the swap tool cannot insert'
fi

# 2. The selector that actually wins.
grep -Fq 'html:not(body)' <<<"$code" || \
  fail 'the override does not use html:not(body), so colors.css outranks it and nothing changes'
# A bare :root block at the start of a line is the losing form.
if grep -qE '^\+[[:space:]]*:root[[:space:]]*[,{]' <<<"$code"; then
  fail 'a :root block is specificity (0,1,0) and loses to colors.css html:not(body)'
fi

# 3. Both schemes, or one theme's ink lands on the other theme's paper.
grep -Fq 'prefers-color-scheme: dark' <<<"$code" || \
  fail 'there is no dark block, so dark mode keeps the ChromeOS palette'

# 4. Every role defined for light is defined for dark, and the other way round.
python3 - "$PATCH" <<'PY'
import re, sys
lines = [l[1:] for l in open(sys.argv[1], encoding='utf-8').read().split('\n')
         if l.startswith('+') and not l.startswith('+++')]
text = '\n'.join(lines)
cut = text.find('prefers-color-scheme: dark')
if cut < 0:
    raise SystemExit('files aurade palette test: no dark block to compare')
tok = lambda s: set(re.findall(r'--cros-sys-([a-z0-9_]+)\s*:', s))
light, dark = tok(text[:cut]), tok(text[cut:])
if not light:
    raise SystemExit('files aurade palette test: the light block defines no tokens')
only_light, only_dark = sorted(light - dark), sorted(dark - light)
if only_light or only_dark:
    raise SystemExit(
        'files aurade palette test: %d role(s) defined in only one scheme, '
        'which renders one theme on the other: light only %s, dark only %s'
        % (len(only_light) + len(only_dark), only_light, only_dark))
print('   %d roles, defined in both schemes' % len(light))
PY

# 5. The values are AuraDE's, not invented and not ChromeOS's. These two come
# straight from installer/lib/aurade_gui/tokens.py and are what makes the
# navigation pill lilac instead of amber.
grep -Fq '#6d4ea1' <<<"$code" || fail 'the light primary is not AuraDE lilac #6d4ea1'
grep -Fq '#d1bcff' <<<"$code" || fail 'the dark primary is not AuraDE lilac #d1bcff'
grep -Fq -- '--cros-sys-primary:' <<<"$code" || \
  fail 'the primary role is not overridden, which is the one the navigation pill reads'

echo 'files aurade palette test: PASS'
