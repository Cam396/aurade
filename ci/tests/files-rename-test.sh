#!/usr/bin/env bash
# Rename, the way people coming from another desktop expect it.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0048-files-rename-expectations.patch"

fail() { echo "files rename test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0048 is missing'
grep -Fqx '0048-files-rename-expectations.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0048 is not listed in SERIES'

added=$(grep '^+' "$PATCH" | grep -v '^+++' || true)
[[ -n $added ]] || fail 'patch 0048 adds nothing'
# Comments here name the very things being asserted, so they come out of the
# haystack before anything is checked. HTML comments too, since the F2
# rationale spells out "F2" three times.
code=$(grep -vE '^\+[[:space:]]*(//|\*|/\*|<!--|[a-z].*-->$)' <<<"$added" |
       grep -vE '^\+[[:space:]]+(and|arriving|it\.|with one\.|collapses|selection|respond\.|A name|then a)' || true)
[[ -n $code ]] || fail 'patch 0048 adds only comments'

# 1. F2 is added and Ctrl+Enter survives. Replacing one shortcut with another
# trades one group of people's habit for another's, which is not the trade.
# The command element itself is unchanged, so it is a context line here and
# only the shortcut line is added. Anchor on the context and read the addition
# under it.
shortcut=$(grep -A2 -F 'command id="rename"' "$PATCH" | grep -E '^\+.*shortcut=' || true)
[[ -n $shortcut ]] || fail 'the rename command no longer declares a shortcut'
grep -Fq 'F2' <<<"$shortcut" || fail 'F2 was not added to the rename shortcut'
grep -Fq 'Enter|Ctrl' <<<"$shortcut" || \
  fail 'Ctrl+Enter was dropped, so anyone already used to it loses rename'

# 2. Bare F2. With a modifier it stops being the key people actually press,
# and the parser treats every unrecognised token before a pipe as a modifier.
grep -Eq 'shortcut="Enter\|Ctrl F2"' <<<"$shortcut" || \
  fail 'F2 is not declared bare, so it will not match an unmodified F2 press'

# 3. The dotfile guard. lastIndexOf returns 0 for .bashrc, so the old
# `!== -1` selected nothing at all and renaming a dotfile looked like the app
# ignoring the keypress.
grep -Fq 'selectionEnd > 0' <<<"$code" || \
  fail 'the stem selection no longer excludes a leading dot, so dotfiles select nothing'
if grep -Eq 'selectionEnd (!== *-1|>= *0)' <<<"$code"; then
  fail 'the guard admits index 0 again, which is the dotfile bug'
fi

# 4. Ordinary files keep their stem selection: the branch is narrowed, not
# removed, or renaming report.pdf would select the extension too.
grep -Fq 'currentEntry.isFile' <<<"$code" || \
  fail 'the file check was dropped from the stem selection'

echo 'files rename test: PASS'
