#!/usr/bin/env bash
# The stat that killed the desktop.
#
# OpenLinuxVirtualTask::IsEnabled() called base::PathExists. MatchVirtualTasks()
# calls IsEnabled() on every virtual task for every non empty selection, and it
# takes a raw Profile*, so it runs on the browser UI thread. base::PathExists
# wraps its stat in a ScopedBlockingCall, which calls AssertBlockingAllowed, and
# blocking is disallowed there. With DCHECKs on that is fatal, so selecting
# files in the Files app took the whole session down and the supervisor
# restarted it with nothing on screen to say why. It was found by reading
# ~/.local/state/aurade/ash.log, which is the only reason it was found at all.
#
# The rule this encodes: nothing on the IsEnabled path may touch the disk
# synchronously. A cached answer, probed once off the thread, is the fix.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0052-files-no-blocking-stat-on-ui-thread.patch"

fail() { echo "files no blocking stat test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0052 is missing'
grep -Fqx '0052-files-no-blocking-stat-on-ui-thread.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0052 is not listed in SERIES'

added=$(grep '^+' "$PATCH" | grep -v '^+++' || true)
removed=$(grep '^-' "$PATCH" | grep -v '^---' || true)
[[ -n $added ]] || fail 'patch 0052 adds nothing'
code=$(grep -vE '^\+[[:space:]]*(//|\*|/\*)' <<<"$added" || true)
[[ -n $code ]] || fail 'patch 0052 adds only comments'

# 1. The synchronous stat is gone from where it was.
grep -Fq 'base::PathExists(base::FilePath(kAuraDeHostControlPath))' <<<"$removed" || \
  fail 'the original synchronous PathExists was not removed'

# 2. Whatever PathExists survives must be bound into a posted task, never
# called inline. A bare call is the whole defect coming back.
if grep -qE '^\+[^/]*[^d]\bbase::PathExists\(' <<<"$code" | grep -v 'BindOnce'; then
  fail 'PathExists is called inline again'
fi
grep -Fq 'base::BindOnce(&base::PathExists' <<<"$code" || \
  fail 'the stat is no longer handed to a posted task'
grep -Fq 'base::ThreadPool::PostTaskAndReplyWithResult' <<<"$code" || \
  fail 'there is no thread pool post, so the stat still runs on the caller thread'
grep -Fq 'base::MayBlock()' <<<"$code" || \
  fail 'the posted task does not declare MayBlock, which is what makes blocking legal'

# 3. IsEnabled answers from the cache, and never waits.
grep -Fq 'return host_control_present_' <<<"$code" || \
  fail 'IsEnabled no longer answers from the cached probe result'
if grep -qE 'RunLoop|WaitableEvent|\.Wait\(' <<<"$code"; then
  fail 'IsEnabled waits for the probe, which blocks the UI thread by another name'
fi

# 4. Probed once, not on every selection. Without the guard this posts a task
# per selection change forever.
grep -Fq 'probe_started_' <<<"$code" || \
  fail 'nothing guards the probe, so a task is posted on every selection change'
grep -Fq 'if (!probe_started_)' <<<"$code" || \
  fail 'the probe guard is not a one shot'

# 5. The reply must not outlive the task.
grep -Fq 'weak_ptr_factory_.GetWeakPtr()' <<<"$code" || \
  fail 'the reply callback does not use a weak pointer'

# 6. ChromeOS keeps its own behaviour and never pays for the probe.
grep -Fq 'base::SysInfo::IsRunningOnChromeOS()' <<<"$code" || \
  fail 'the ChromeOS branch was dropped, changing behaviour on ChromeOS images'

echo 'files no blocking stat test: PASS'
