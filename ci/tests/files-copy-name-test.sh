#!/usr/bin/env bash
# Copy name, and the trap underneath it.
#
# Files listens for the copy event on the document and rewrites the clipboard
# with the selected file entries. Any text copy raised through
# document.execCommand('copy') is therefore silently replaced by a file copy:
# the user gets neither the text they asked for nor an error, and nothing in
# the app looks wrong. That is the failure this fixture exists to prevent,
# because it is invisible in review and the obvious way to write the feature.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0044-files-copy-name.patch"

fail() { echo "files copy name test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0044 is missing'
grep -Fqx '0044-files-copy-name.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0044 is not listed in SERIES'

added=$(grep '^+' "$PATCH" | grep -v '^+++' || true)
[[ -n $added ]] || fail 'patch 0044 adds nothing'

# Comment lines are stripped before anything is asserted about the code. The
# comment here explains the execCommand trap by naming it, and an assertion
# that reads the explanation instead of the code passes whether or not the code
# is right. That mistake has already been made twice in this suite.
code=$(grep -vE '^\+[[:space:]]*(//|\*|/\*)' <<<"$added" || true)
[[ -n $code ]] || fail 'patch 0044 adds only comments'

# 1. The interception. This is the whole reason the async API is used.
grep -Fq 'navigator.clipboard.writeText' <<<"$code" || \
  fail 'the clipboard write no longer uses the async API, so Files will intercept it'
if grep -Eq "execCommand\(['\"]copy" <<<"$code"; then
  fail "execCommand('copy') is intercepted by the document copy handler and silently writes file entries instead"
fi

# 2. A clipboard write can be refused, and a person who is not told will paste
# a stale clipboard into a message and never know why the wrong name arrived.
grep -Fq '.catch(' <<<"$code" || \
  fail 'a refused clipboard write is no longer reported to anybody'

# 3. Both outcomes are spoken as well as shown. A toast is invisible to a
# screen reader.
[[ $(grep -c 'speakA11yMessage' <<<"$code") -ge 2 ]] || \
  fail 'the success and failure paths do not both announce themselves'
[[ $(grep -c 'toast.show' <<<"$code") -ge 2 ]] || \
  fail 'the success and failure paths do not both show a toast'

# 4. One name per line, so a multiple selection pastes as a list.
grep -q "names\.join('.n')" <<<"$code" || \
  fail 'the names are no longer joined by newline'

# 5. The label has to count, or "Copy name" over nine files reads as though it
# will copy one of them.
grep -Fq 'count > 1' <<<"$code" || fail 'the label no longer distinguishes one name from several'
grep -Fq 'Copy name' <<<"$code" || fail 'the singular label was removed'

# 6. Nothing to copy means nothing offered.
grep -Fq 'event.canExecute = count > 0' <<<"$code" || \
  fail 'the command no longer disables itself on an empty selection'
grep -Fq 'setHidden(count === 0)' <<<"$code" || \
  fail 'the command no longer hides itself on an empty selection'

# 7. No keyboard shortcut. Ctrl+Shift+C is inspect-element, and taking a key
# somebody already uses is worse than one more trip to the context menu.
if grep -Eq '^\+.*<command id="copy-name".*shortcut=' <<<"$added"; then
  fail 'copy-name declares a shortcut, which collides with an existing binding'
fi

# 8. Declared, registered and reachable. A command missing any one of the three
# is dead markup that nothing reports.
grep -Fq '<command id="copy-name"' <<<"$code" || fail 'the command element is missing from main.html'
grep -Fq "'copy-name': new CopyNameCommand()" <<<"$code" || \
  fail 'the command is not registered in the command handler'
grep -Fq 'command="#copy-name"' <<<"$code" || \
  fail 'the command has no context menu item, so there is no way to reach it'

echo 'files copy name test: PASS'
