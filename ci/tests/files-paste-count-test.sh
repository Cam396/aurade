#!/usr/bin/env bash
# The paste menu says how much is on the clipboard, and the two ways that goes
# wrong quietly.
#
# The first is cost. Reading the clipboard means synchronously driving
# execCommand on a hidden iframe, and canExecute runs on every selection change
# and every menu open. Taking the count in a second simulated paste would
# double that work to report one number, and nothing in the app would look
# wrong: it would just get slower.
#
# The second is the label. The base label is translated and the count is
# appended to it, so the original has to be remembered and the label rebuilt
# from it every time. Appending to whatever the label currently holds gives
# Paste (3) (3) (3) within a few menu opens, which only shows up in use.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0050-files-paste-count.patch"

fail() { echo "files paste count test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0050 is missing'
grep -Fqx '0050-files-paste-count.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0050 is not listed in SERIES'

added=$(grep '^+' "$PATCH" | grep -v '^+++' || true)
removed=$(grep '^-' "$PATCH" | grep -v '^---' || true)
# The patched shape of the regions this touches: what the patch adds, plus the
# context it sits in, with the removed lines dropped. Some of what is asserted
# below is about code the patch keeps rather than code it writes.
result=$(grep -E '^[+ ]' "$PATCH" | grep -v '^+++' || true)
[[ -n $added ]] || fail 'patch 0050 adds nothing'

# Comments are stripped before anything is asserted about the code, so that an
# assertion cannot pass by reading the comment that explains the trap it exists
# to catch.
code=$(grep -vE '^\+[[:space:]]*(//|\*|/\*)' <<<"$added" || true)
[[ -n $code ]] || fail 'patch 0050 adds only comments'

# 1. One simulated paste, not two. The count has to be taken inside the
# callback that already decides whether pasting is possible.
[[ $(grep -c "simulateCommand_('paste'" <<<"$result") -eq 1 ]] || \
  fail 'the clipboard is simulated more than once, so opening a menu costs double what it did'
grep -Fq 'state.enabled = !!this.canPasteOrDrop_(clipboardData, destinationEntry)' <<<"$code" || \
  fail 'the enabled answer no longer comes from the same simulated paste as the count'

# 2. The old entry point keeps working. Three commands and the unit tests call
# it, and a delegate that stops delegating fails silently as an always-false
# paste.
grep -Fq 'return this.queryPasteCommandState(destinationEntry).enabled' <<<"$code" || \
  fail 'queryPasteCommandEnabled no longer delegates to the combined query'

# 3. The count comes from the entries the cut or copy actually wrote, one URL
# per line.
grep -Fq "getData('fs/sources')" <<<"$code" || \
  fail 'the count no longer reads the entries the clipboard is holding'
grep -q "sources\.split('.n')\.length" <<<"$code" || \
  fail 'the count no longer counts lines'
# An empty string splits into one empty element, which reports one item on an
# empty clipboard.
grep -Fq 'sources ? sources.split' <<<"$code" || \
  fail 'an empty clipboard would be counted as holding one item'

# 4. The label is rebuilt from the remembered original, never appended to.
grep -Fq 'WeakMap' <<<"$code" || \
  fail 'the original label is no longer remembered per command'
grep -Fq 'auraDePasteLabels.get(command)' <<<"$code" || \
  fail 'the remembered label is never read back'
grep -Fq 'base = command.label' <<<"$code" || \
  fail 'nothing captures the original label'
grep -Fq 'command.label = count > 1 ? `${base} (${count})` : base' <<<"$code" || \
  fail 'the label is not rebuilt from the base on both branches, so counts will compound'

# 5. Appended, not replaced. The base label is translated and the number is
# not, so replacing it would ship English to every other locale.
if grep -Eq "command\.label = ['\`](Paste|Move|Copy)" <<<"$code"; then
  fail 'the translated paste label was replaced with an English string'
fi

# 6. All three paste commands, because all three appear in a menu: the file
# context menu, the folder context menu, and the blank space menu. Converting
# two of the three leaves one item silently without a count.
[[ $(grep -c 'auraDeLabelPaste(event.command' <<<"$code") -eq 3 ]] || \
  fail 'the count is not applied to all three paste commands'
[[ $(grep -c 'fileTransferController.queryPasteCommandEnabled(' <<<"$removed") -eq 3 ]] || \
  fail 'the three command call sites were not all moved onto the combined query'
[[ $(grep -c 'fileTransferController?.queryPasteCommandState(' <<<"$code") -eq 3 ]] || \
  fail 'not every converted call site reaches the combined query'
# A call site can be converted for the label and left on the boolean query,
# which reads as a paste item that never learns to count.
if grep -Fq 'fileTransferController?.queryPasteCommandEnabled(' <<<"$code"; then
  fail 'a command still asks the boolean query, so its count is always zero'
fi

# 7. The unit tests mock the transfer controller by hand, so a command that
# starts asking it a new question does not fail an assertion, it throws on an
# undefined method. Both mocks have to learn the new one.
[[ $(grep -c 'queryPasteCommandState: () =>' <<<"$code") -eq 2 ]] || \
  fail 'the two hand written unit test mocks were not both taught the new query'
grep -Fq 'queryPasteCommandState: () => ({enabled: true, count: 1})' <<<"$code" || \
  fail 'the unit test mock does not return the shape the commands read'

echo 'files paste count test: PASS'
