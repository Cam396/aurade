#!/usr/bin/env bash
# Copy path, and the two ways it can quietly lie.
#
# The first is the clipboard trap that Copy name documents: a text copy raised
# through document.execCommand('copy') is intercepted by the Files document
# copy handler and rewritten into a file copy, so the user gets neither the
# text nor an error.
#
# The second belongs to this command alone. The path is computed from
# PathComponent, the same computation the details panel uses for File
# location, and PathComponent returns an empty list for an entry it cannot
# place. If those empty results stop being filtered out, selecting a fake root
# alongside real files writes blank lines into the clipboard, and selecting
# only a fake root writes an empty string over whatever the person had. Both
# look like a working command from the outside.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0049-files-copy-path.patch"

fail() { echo "files copy path test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0049 is missing'
grep -Fqx '0049-files-copy-path.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0049 is not listed in SERIES'

added=$(grep '^+' "$PATCH" | grep -v '^+++' || true)
[[ -n $added ]] || fail 'patch 0049 adds nothing'

# Comment lines are stripped before anything is asserted about the code, so
# that an assertion cannot pass by reading the comment that explains the trap
# it is meant to catch. That mistake has already been made three times here.
code=$(grep -vE '^\+[[:space:]]*(//|\*|/\*)' <<<"$added" || true)
[[ -n $code ]] || fail 'patch 0049 adds only comments'

# 1. The interception.
grep -Fq 'navigator.clipboard.writeText' <<<"$code" || \
  fail 'the clipboard write no longer uses the async API, so Files will intercept it'
if grep -Eq "execCommand\(['\"]copy" <<<"$code"; then
  fail "execCommand('copy') is intercepted by the document copy handler and silently writes file entries instead"
fi

# 2. The path is the one the window already shows. Computing it any other way
# means the string somebody pastes disagrees with the string they can see.
grep -Fq 'PathComponent.computeComponentsFromEntry' <<<"$code" || \
  fail 'the path is no longer computed the way the details panel computes it'
grep -Fq ".name).join('/')" <<<"$code" || \
  fail 'the components are no longer joined the way File location joins them'

# 3. An entry PathComponent cannot place yields an empty string, and an empty
# string must never reach the clipboard.
grep -Fq 'filter(' <<<"$code" || \
  fail 'unplaceable entries are no longer filtered, so blank lines reach the clipboard'
grep -Fq 'path.length > 0' <<<"$code" || \
  fail 'the filter no longer drops empty paths'
grep -Fq 'paths.length === 0' <<<"$code" || \
  fail 'a selection that places nowhere would now overwrite the clipboard with nothing'

# 4. A clipboard write can be refused, and a person who is not told will paste
# a stale clipboard and never know why the wrong path arrived.
grep -Fq '.catch(' <<<"$code" || \
  fail 'a refused clipboard write is no longer reported to anybody'

# 5. Both outcomes are spoken as well as shown. A toast is invisible to a
# screen reader.
[[ $(grep -c 'speakA11yMessage' <<<"$code") -ge 2 ]] || \
  fail 'the success and failure paths do not both announce themselves'
[[ $(grep -c 'toast.show' <<<"$code") -ge 2 ]] || \
  fail 'the success and failure paths do not both show a toast'

# 6. One path per line, so a multiple selection pastes as a list.
grep -q "paths\.join('.n')" <<<"$code" || \
  fail 'the paths are no longer joined by newline'

# 7. The label counts, for the same reason Copy name counts.
grep -Fq 'count > 1' <<<"$code" || fail 'the label no longer distinguishes one path from several'
# Anchored on the ternary, not on the bare words. The menu declaration in
# main.html also reads Copy path, so an unanchored match passes even after the
# singular label is gone from the command.
grep -Fq ": 'Copy path'" <<<"$code" || fail 'the singular label was removed from the command'
grep -Fq 'label="Copy path"' <<<"$code" || fail 'the singular label was removed from the menu'

# 8. Nothing to copy means nothing offered.
grep -Fq 'event.canExecute = count > 0' <<<"$code" || \
  fail 'the command no longer disables itself on an empty selection'
grep -Fq 'setHidden(count === 0)' <<<"$code" || \
  fail 'the command no longer hides itself on an empty selection'

# 9. No keyboard shortcut. Ctrl+Shift+N looked free inside Files and is bound
# in ash/public/cpp/accelerators.h to a new incognito window, which is how this
# command ended up reachable by menu only.
if grep -Eq '^\+.*<command id="copy-path".*shortcut=' <<<"$added"; then
  fail 'copy-path declares a shortcut, which collides with an existing binding'
fi

# 10. Declared, registered and reachable. A command missing any one of the
# three is dead markup that nothing reports.
grep -Fq '<command id="copy-path"' <<<"$code" || fail 'the command element is missing from main.html'
grep -Fq "'copy-path': new CopyPathCommand()" <<<"$code" || \
  fail 'the command is not registered in the command handler'
grep -Fq 'command="#copy-path"' <<<"$code" || \
  fail 'the command has no context menu item, so there is no way to reach it'

echo 'files copy path test: PASS'
