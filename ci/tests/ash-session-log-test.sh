#!/usr/bin/env bash
# Keep session child diagnostics in the desktop log. Run the real child against
# a stub desktop so this checks behaviour rather than source text.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
CHILD="$ROOT/chromiumos-ash/chromiumos-ash-session-child.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fail() { echo "ash session log test: $*" >&2; exit 1; }

[[ -r $CHILD ]] || fail 'the session child script is missing'

stub="$TMP/stub-desktop"
cat >"$stub" <<'EOF'
#!/bin/bash
echo "STDOUT_MARKER $*"
echo "STDERR_MARKER" >&2
if [ -n "${STUB_BULK:-}" ]; then
    printf '%*s\n' "${STUB_BULK}" ''
fi
exit "${STUB_EXIT:-0}"
EOF
chmod 0755 "$stub"

session() {
  env -i PATH="$PATH" HOME="$TMP/home" XDG_STATE_HOME="$TMP/state" \
      AURADE_CHROME_COMMAND="$stub" \
      AURADE_SESSION_ERROR="$TMP/nonexistent-error-handler" \
      AURADE_REMOVABLE_AUTOMOUNT=0 \
      AURADE_SESSION_ON_EXIT=exit \
      "$@"
}

LOG="$TMP/state/aurade/ash.log"

# 1. Both streams reach the log rather than the console the desktop covers.
session bash "$CHILD" first-run >"$TMP/console" 2>&1 || \
  fail 'the session child exited non-zero on a clean run'
[[ -f $LOG ]] || fail 'no log file was written'
grep -Fq 'STDOUT_MARKER first-run' "$LOG" || fail 'stdout did not reach the log'
grep -Fq 'STDERR_MARKER' "$LOG" || \
  fail 'stderr did not reach the log, which is where the errors live'

# 2. Arguments still reach the desktop. A redirection that ate them would be a
# far worse bug than the one being fixed.
grep -Fq 'STDOUT_MARKER first-run' "$LOG" || \
  fail 'arguments were not passed through to the desktop'

# 3. Each start is marked, so a restart loop reads as a sequence of runs rather
# than one undelimited stream.
grep -Fq '=== AuraDE desktop starting' "$LOG" || fail 'no start marker was written'

# 4. The previous session survives as .1. Without this a desktop that crashes
# and comes back overwrites the log of the crash with the log of the recovery,
# which is precisely the evidence worth keeping.
session bash "$CHILD" second-run >"$TMP/console" 2>&1 || \
  fail 'the second run exited non-zero'
[[ -f "$LOG.1" ]] || fail 'the previous session was not rotated to .1'
grep -Fq 'first-run' "$LOG.1" || fail 'the rotated log does not hold the previous session'
grep -Fq 'second-run' "$LOG" || fail 'the current log does not hold the current session'
if grep -Fq 'first-run' "$LOG"; then
  fail 'the current log still holds the previous session, so it was not rotated'
fi

# 5. A log that grows without bound is its own outage on a 32GB eMMC. The
# rollover has to happen inside the restart loop and not only at startup,
# because the unbounded case is a desktop that crashes and restarts all night
# without the session ever ending.
rm -rf "$TMP/state"
session STUB_BULK=4096 AURADE_LOG_MAX_BYTES=1024 \
  AURADE_SESSION_ON_EXIT=restart AURADE_MAX_FAST_RESTARTS=3 \
  AURADE_RESTART_DELAY=0 \
  bash "$CHILD" bulk-run >"$TMP/console" 2>&1 || true
[[ -f $LOG ]] || fail 'the bulk run left no log'
# Three desktop starts, each larger than the cap. The log should hold the most
# recent one only: counting the start markers says that directly, where a size
# check would only say it after the fact.
starts=$(grep -c '=== AuraDE desktop starting' "$LOG" || true)
[[ $starts -eq 1 ]] || \
  fail "the log was not rolled over inside the restart loop (${starts} starts held)"
[[ -f "$LOG.1" ]] || fail 'the rolled over log was discarded rather than kept as .1'

# 6. If the state directory cannot be created the desktop still starts. A
# logging change must never be able to cost somebody their session.
env -i PATH="$PATH" HOME=/proc/aurade-nonexistent \
    XDG_STATE_HOME=/proc/aurade-nonexistent/state \
    AURADE_CHROME_COMMAND="$stub" \
    AURADE_SESSION_ERROR="$TMP/nonexistent-error-handler" \
    AURADE_REMOVABLE_AUTOMOUNT=0 AURADE_SESSION_ON_EXIT=exit \
    bash "$CHILD" fallback-run >"$TMP/fallback" 2>&1 || \
  fail 'the desktop did not start when the log directory was unwritable'
grep -Fq 'STDOUT_MARKER fallback-run' "$TMP/fallback" || \
  fail 'with no log available the output should fall back to the console, and did not'

# 7. A failing desktop still gets its output kept, which is the case that
# matters most, and its status still reaches the caller.
rm -rf "$TMP/state"
if session STUB_EXIT=3 bash "$CHILD" failing-run >"$TMP/console" 2>&1; then
  fail 'a desktop exiting 3 should propagate a non-zero status'
fi
grep -Fq 'STDERR_MARKER' "$LOG" || fail 'the failing run left no stderr in the log'

# 8. House style.
if grep -Pq '[\x{2013}\x{2014}]' "$CHILD"; then
  fail 'the session child contains an em or en dash'
fi

echo 'ash session log test: PASS'
