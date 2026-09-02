#!/usr/bin/env bash
# A session child whose session has gone must stop, exercised by orphaning a
# real one rather than by grepping for the check.
#
# The supervisor is not what stops it, and an earlier version of this comment
# claimed the wrong reason. It said the supervisor's "kill -TERM -- -${child_pid}"
# could not reach a session leader. It can. Reproduced both halves: a
# backgrounded process in a script is not a process group leader, so setsid does
# not fork, $! is this exact child, and the group kill is delivered.
#
# What is true is that the teardown does not always run. A supervisor that is
# killed outright never reaches that line, and the SIGHUP ending its session
# stops at us, because setsid gave us a session of our own so a hangup could not
# reach us. That is the point of setsid and also its price. So the child started
# at 15:27 outlived the weston that launched it, reparented to init, and kept
# restarting Ash against a socket the replacement session could not then have.
#
# Three things have to hold and none is visible to a grep:
#
# It must notice. $PPID is set once when bash starts and never follows a
# reparent, so a check written against it still names a process that has been
# gone for hours and the loop runs forever.
#
# It must notice a reparent, not one particular new parent. An orphan lands on
# init here and on a subreaper elsewhere.
#
# It must not fire on a child that was parented to init from the start, which is
# what a deliberately detached launch looks like.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
SCRIPT="$ROOT/chromiumos-ash/chromiumos-ash-session-child.sh"

fail() { echo "session orphan test: $*" >&2; exit 1; }

[[ -r $SCRIPT ]] || fail 'the session child script is missing'
bash -n "$SCRIPT" || fail 'the session child script does not parse'

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/run" "$WORK/state" "$WORK/bin"

# A stub Ash that records launches and returns immediately, so the restart loop
# spins as fast as it can and an unbounded one is obvious within seconds.
cat >"$WORK/bin/stub-ash" <<'STUB'
#!/usr/bin/env bash
echo launch >>"${STUB_LAUNCH_LOG}"
exit 0
STUB
chmod +x "$WORK/bin/stub-ash"

env_args=(
  XDG_RUNTIME_DIR="$WORK/run"
  XDG_STATE_HOME="$WORK/state"
  STUB_LAUNCH_LOG="$WORK/launches"
  AURADE_CHROME_COMMAND="$WORK/bin/stub-ash"
  AURADE_SESSION_ERROR="$WORK/bin/no-such-reporter"
  AURADE_EXO_SOCKET=wayland-orphan
  AURADE_EXO_SOCKET_TIMEOUT=1
  AURADE_RESTART_DELAY=0
  AURADE_FAST_RESTART_WINDOW=0
  AURADE_MAX_FAST_RESTARTS=100000
  AURADE_SESSION_ON_EXIT=restart
  AURADE_REMOVABLE_AUTOMOUNT=0
)

wait_gone() {  # pid seconds
    local pid=$1 limit=$2 waited=0
    while kill -0 "$pid" 2>/dev/null; do
        (( waited < limit )) || return 1
        sleep 1
        waited=$((waited + 1))
    done
    return 0
}

# --- A: orphaned mid loop. It has to stop. ----------------------------------

: >"$WORK/launches"
# An intermediate shell starts the script, stays a moment, and then exits, which
# is exactly what weston going away does to it: the parent changes and nothing
# else does.
#
# The pause matters and is not padding. Without it the intermediate exits before
# the script has run its first line, so the script reads a parent that is already
# the subreaper and there is no change left for it to see. That is a race in the
# test, not in the desktop: weston lives for hours before it dies. A run that
# skipped the pause showed pid=3131770 PPID=927 at startup while the intermediate
# was 3131768, and every later comparison agreed with the first.
setsid bash -c '
    echo "$$" > "'"$WORK"'/parent.pid"
    env "$@" bash "$0" >/dev/null 2>"'"$WORK"'/err" &
    echo "$!" > "'"$WORK"'/child.pid"
    sleep 3
    exit 0
' "$SCRIPT" "${env_args[@]}" &
sleep 2
CHILD=$(cat "$WORK/child.pid" 2>/dev/null || true)
PARENT=$(cat "$WORK/parent.pid" 2>/dev/null || true)
[[ -n ${CHILD:-} ]] || fail 'A: could not start the session child'
[[ -n ${PARENT:-} ]] || fail 'A: could not start the intermediate shell'
kill -0 "$CHILD" 2>/dev/null || fail 'A: the session child was gone before it \
was orphaned, so the rest of this case would pass without proving anything'

wait_gone "$PARENT" 8 || fail 'A: the intermediate shell never exited, so \
nothing was orphaned'
before=$(wc -l <"$WORK/launches" 2>/dev/null || echo 0)

# Five seconds after the parent is gone, not twelve. The check sits at the top
# of the restart loop and one pass through that loop is milliseconds here, so a
# child still alive after five is a child that is never going to notice.
if ! wait_gone "$CHILD" 5; then
    kill -KILL "$CHILD" 2>/dev/null || true
    launches=$(wc -l <"$WORK/launches" 2>/dev/null || echo 0)
    fail "A: the session child was orphaned and kept running, ${launches} \
launches and counting. \$PPID does not follow a reparent, so a check written \
against it never fires"
fi

grep -q 'stopping rather than restarting' "$WORK/err" || \
  fail 'A: it stopped without saying why, so the next person sees a session \
that vanished for no stated reason'
LOG="$WORK/state/aurade/ash.log"
[[ -f $LOG ]] && grep -q 'session orphaned' "$LOG" || \
  fail 'A: the reason is not in the session log, which is the file anybody \
actually reads afterwards'

# Launches from after the reparent, not from the whole run. Everything before it
# was a healthy session doing its job, and counting those would only measure how
# long the pause above is.
after=$(wc -l <"$WORK/launches" 2>/dev/null || echo 0)
(( after - before < 20 )) || \
  fail "A: launched Ash $((after - before)) more times after being orphaned, \
which is a loop that happened to be interrupted rather than a check that fired"

# --- B: a parent that stays. It must not stop. ------------------------------

: >"$WORK/launches"
env "${env_args[@]}" AURADE_SESSION_ON_EXIT=exit bash "$SCRIPT" \
  >/dev/null 2>"$WORK/err2" || fail 'B: exited non zero under a live parent'
(( $(wc -l <"$WORK/launches") == 1 )) || \
  fail 'B: did not launch Ash under a live parent, so the orphan check fires \
when the parent is still there and no desktop ever starts'
grep -q 'stopping rather than restarting' "$WORK/err2" && \
  fail 'B: reported itself orphaned while its parent was alive' || true

# --- C: the check reads the live parent, not $PPID ---------------------------

fn=$(sed -n '/^parent_is_gone() {$/,/^}$/p' "$SCRIPT")
[[ -n $fn ]] || fail 'C: cannot extract parent_is_gone from the script'
grep -q '/proc/\$\$/stat' <<<"$fn" || \
  fail 'C: the check does not read /proc/$$/stat. $PPID is set once when bash \
starts and never follows a reparent, and /proc/self inside a command \
substitution is awk, not this script'
grep -q '/proc/self/stat' <<<"$fn" && \
  fail 'C: the check reads /proc/self/stat from a command substitution, where \
self is awk and the answer is a process that lives for microseconds' || true
grep -qE '\$PPID' <<<"$fn" && \
  fail 'C: the check uses $PPID, which cannot see a reparent' || true

# --- D: a child already on init at startup is left alone --------------------

eval "$fn"
PARENT_PID=1
parent_is_gone && \
  fail 'D: a child that was parented to init from the start reports itself \
orphaned, which breaks a deliberately detached launch' || true
PARENT_PID=0
parent_is_gone && fail 'D: an unreadable original parent is treated as orphaned' || true

echo 'session orphan test: PASS '\
'(stops when reparented, says so on stderr and in the log, keeps running under '\
'a live parent, reads the live parent rather than $PPID, leaves a detached '\
'start alone)'
