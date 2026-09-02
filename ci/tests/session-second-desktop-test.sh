#!/usr/bin/env bash
# What the session child does when the display already has a compositor, and
# when Ash aborts, exercised by running the real script rather than grepping it.
#
# On 2 Sep this cost 202 aborted Ash launches over two and a quarter hours, and
# nothing on screen changed while it happened, because the desktop that was
# working belonged to the other supervisor. Two independent bugs had to line up:
#
# One: the wait for the exo socket gave up after its timeout and started Ash
# anyway, on the reasoning that no desktop is worse than one more failed
# attempt. A lock still held at that point belongs to a live compositor, and
# starting a second one aborts on a certainty.
#
# Two: the five strike fast restart guard never fired. It compares wall clock
# runtime against a sixty second window, and Ash aborting in two seconds still
# takes about ninety to get its children out of the way. So every attempt in the
# loop looked like a long healthy session and the counter reset every time.
#
# Either fix alone would have bounded it. Both are asserted here, and so is the
# thing that must not regress with them: an ordinary long session that ends for
# any reason other than an abort still resets the counter.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
SCRIPT="$ROOT/chromiumos-ash/chromiumos-ash-session-child.sh"

fail() { echo "session second desktop test: $*" >&2; exit 1; }

[[ -r $SCRIPT ]] || fail 'the session child script is missing'
bash -n "$SCRIPT" || fail 'the session child script does not parse'

WORK=$(mktemp -d)
HOLDER=""
release() {
    [[ -n ${HOLDER:-} ]] || return 0
    kill -- -"$HOLDER" 2>/dev/null || kill "$HOLDER" 2>/dev/null || true
    wait "$HOLDER" 2>/dev/null || true
    HOLDER=""
}
trap 'release; rm -rf "$WORK"' EXIT

# flock spawns its command as a child that inherits the locked descriptor, so
# the holder is killed by process group or the lock outlives the test.
hold() {
    setsid flock -x "$1" -c "sleep $2" &
    HOLDER=$!
    sleep 0.5
}

mkdir -p "$WORK/run" "$WORK/state" "$WORK/bin"

# A stub Ash that records each launch and exits how the case asks.
cat >"$WORK/bin/stub-ash" <<'STUB'
#!/usr/bin/env bash
echo "launch" >>"${STUB_LAUNCH_LOG}"
sleep "${STUB_SLEEP:-0}"
exit "${STUB_EXIT:-0}"
STUB
chmod +x "$WORK/bin/stub-ash"

# -k because the script traps TERM without exiting, so a plain timeout sends a
# signal the supervisor absorbs and then waits for a process that never stops.
# That is worth knowing about the script and is not what this fixture is for.
stopped_by_timeout() { (( RC == 124 || RC == 137 )); }

run_session() {  # timeout_seconds -> sets RC and LAUNCHES
    : >"$WORK/launches"
    set +e
    env XDG_RUNTIME_DIR="$WORK/run" \
        XDG_STATE_HOME="$WORK/state" \
        STUB_LAUNCH_LOG="$WORK/launches" \
        STUB_SLEEP="${STUB_SLEEP:-0}" \
        STUB_EXIT="${STUB_EXIT:-0}" \
        AURADE_CHROME_COMMAND="$WORK/bin/stub-ash" \
        AURADE_SESSION_ERROR="$WORK/bin/no-such-reporter" \
        AURADE_EXO_SOCKET="${EXO_NAME}" \
        AURADE_EXO_SOCKET_TIMEOUT=2 \
        AURADE_RESTART_DELAY=0 \
        AURADE_FAST_RESTART_WINDOW="${WINDOW:-1}" \
        AURADE_MAX_FAST_RESTARTS="${MAX_FAST:-2}" \
        AURADE_SESSION_ON_EXIT="${ON_EXIT:-restart}" \
        AURADE_REMOVABLE_AUTOMOUNT=0 \
        timeout -k 2 "$1" bash "$SCRIPT" >"$WORK/out" 2>"$WORK/err"
    RC=$?
    set -e
    LAUNCHES=$(wc -l <"$WORK/launches")
}

log_file() { echo "$WORK/state/aurade/ash.log"; }

# --- A: the display already has a compositor --------------------------------

EXO_NAME=wayland-a
: >"$WORK/run/${EXO_NAME}.lock"
hold "$WORK/run/${EXO_NAME}.lock" 30
STUB_SLEEP=0 STUB_EXIT=0 ON_EXIT=restart run_session 15
release

(( LAUNCHES == 0 )) || \
  fail "A: started Ash ${LAUNCHES} time(s) while another compositor held the socket"
(( RC == 0 )) || \
  fail "A: exited ${RC}. Declining to be the second desktop is not a failure, and \
a non zero exit puts an error in front of somebody whose desktop is working"
grep -q 'not starting a second desktop' "$WORK/err" || \
  fail 'A: said nothing on stderr about why it declined'
[[ -f $(log_file) ]] || fail 'A: no session log was written'
grep -q 'session declined' "$(log_file)" || \
  fail 'A: the refusal is not in the log, which is the file anybody actually reads'
grep -qE 'pid [0-9]+' "$(log_file)" || \
  fail 'A: the refusal does not name the process holding the socket, which is \
the lookup that had to be done by hand the first time this went wrong'

# --- B: nobody holds it, so start normally ----------------------------------

EXO_NAME=wayland-b
: >"$WORK/run/${EXO_NAME}.lock"
STUB_SLEEP=0 STUB_EXIT=0 ON_EXIT=exit run_session 15
(( LAUNCHES == 1 )) || fail "B: launched ${LAUNCHES} times, expected 1"
(( RC == 0 )) || fail "B: exited ${RC} on a clean run"

# --- C: an abort is bounded even when teardown outlasts the window ----------

EXO_NAME=wayland-c
: >"$WORK/run/${EXO_NAME}.lock"
# Every launch runs longer than the fast restart window, which is exactly the
# shape that defeated the old counter.
STUB_SLEEP=2 WINDOW=1 MAX_FAST=2 STUB_EXIT=134 ON_EXIT=restart run_session 25
if stopped_by_timeout; then
  fail 'C: the loop never stopped. An abort that outlasts the fast restart '\
'window still resets the counter, which is the two hundred and two launch bug'
fi
(( LAUNCHES == 2 )) || \
  fail "C: launched ${LAUNCHES} times, expected exactly MAX_FAST_RESTARTS=2"

# --- D: and a long session that is not an abort still resets ----------------

EXO_NAME=wayland-d
: >"$WORK/run/${EXO_NAME}.lock"
# Same timings, ordinary failure status. The guard must not fire, or every
# desktop that ran a while and exited badly would refuse to come back.
STUB_SLEEP=2 WINDOW=1 MAX_FAST=2 STUB_EXIT=1 ON_EXIT=restart run_session 12
if ! stopped_by_timeout; then
  fail "D: the loop stopped on its own (rc=${RC}) after a non abort exit, so \
the counter no longer resets for a session that ran longer than the window"
fi
(( LAUNCHES > 2 )) || \
  fail "D: launched only ${LAUNCHES} times, so the guard fired on an exit that \
is not an abort"

# --- E: the holder lookup returns a real pid --------------------------------

holder_fn=$(sed -n '/^exo_lock_holder() {$/,/^}$/p' "$SCRIPT")
[[ -n $holder_fn ]] || fail 'E: cannot extract exo_lock_holder from the script'
eval "$holder_fn"

EXO_NAME=wayland-e
LOCK="$WORK/run/${EXO_NAME}.lock"
: >"$LOCK"
got=$(exo_lock_holder "$LOCK" || true)
[[ -z $got ]] || fail "E: named pid ${got} as holding a lock nobody holds"
hold "$LOCK" 20
got=$(exo_lock_holder "$LOCK" || true)
release
[[ $got =~ ^[0-9]+$ ]] || \
  fail "E: returned '${got}' for a lock that was genuinely held; the refusal \
message would then name nobody"

echo 'session second desktop test: PASS '\
'(declines rather than looping, exits zero, names the holder, logs it, an '\
'abort is bounded however long teardown takes, a non abort still resets)'
