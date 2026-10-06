#!/usr/bin/env bash
# A desktop that goes away while its lock screen is up must not come back
# unlocked. The session child restarts Ash whenever it exits, and before the
# lock screen was Ash's own that was harmless; now a crash, or anybody who
# could kill the browser, would hand over the unlocked desktop. So the child
# ends the session instead, and the greeter asks for the password.
#
# The session manager stand in keeps a marker, owned by root, from lock to
# unlock. This runs the real script against a stub Ash and asserts three
# things: a marker written during the session ends it, a marker left over from
# an earlier session does not, and with no marker at all the desktop restarts
# as it always has.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
SCRIPT="$ROOT/chromiumos-ash/chromiumos-ash-session-child.sh"

fail() { echo "session locked exit test: $*" >&2; exit 1; }

[[ -r $SCRIPT ]] || fail 'the session child script is missing'
bash -n "$SCRIPT" || fail 'the session child script does not parse'

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/run" "$WORK/state" "$WORK/bin" "$WORK/lock"
MARKER="$WORK/lock/$(id -u)"

# A stub Ash that records each launch and, when asked, locks before it exits.
cat >"$WORK/bin/stub-ash" <<'STUB'
#!/usr/bin/env bash
echo "launch" >>"${STUB_LAUNCH_LOG}"
if [[ ${STUB_LOCK:-0} == 1 ]]; then
    echo locked >"${AURADE_LOCK_STATE_DIR}/$(id -u)"
fi
exit "${STUB_EXIT:-1}"
STUB
cat >"$WORK/bin/stub-control" <<'STUB'
#!/usr/bin/env bash
echo "$*" >>"${STUB_CONTROL_LOG}"
STUB
chmod +x "$WORK/bin/stub-ash" "$WORK/bin/stub-control"

run_session() {
    : >"$WORK/launches"
    : >"$WORK/control"
    set +e
    env XDG_RUNTIME_DIR="$WORK/run" \
        XDG_STATE_HOME="$WORK/state" \
        STUB_LAUNCH_LOG="$WORK/launches" \
        STUB_CONTROL_LOG="$WORK/control" \
        STUB_LOCK="${STUB_LOCK:-0}" \
        AURADE_LOCK_STATE_DIR="$WORK/lock" \
        AURADE_SESSION_CONTROL="$WORK/bin/stub-control" \
        AURADE_CHROME_COMMAND="$WORK/bin/stub-ash" \
        AURADE_SESSION_ERROR="$WORK/bin/no-such-reporter" \
        AURADE_EXO_SOCKET=wayland-test \
        AURADE_EXO_SOCKET_TIMEOUT=1 \
        AURADE_RESTART_DELAY=0 \
        AURADE_FAST_RESTART_WINDOW=60 \
        AURADE_MAX_FAST_RESTARTS=3 \
        AURADE_REMOVABLE_AUTOMOUNT=0 \
        timeout -k 2 20 bash "$SCRIPT" >"$WORK/out" 2>"$WORK/err"
    RC=$?
    set -e
    LAUNCHES=$(wc -l <"$WORK/launches")
}

# --- A: locked when it went away, so the session ends -----------------------

rm -f "$MARKER"
STUB_LOCK=1 run_session
(( LAUNCHES == 1 )) || \
  fail "A: started Ash ${LAUNCHES} times; after an exit while locked it must not \
start again, because it would come back unlocked"
grep -qx 'sign-out' "$WORK/control" || \
  fail 'A: did not end the session, so nothing sends the user back to the greeter'
(( RC == 0 )) || fail "A: exited ${RC}"
grep -q 'exited while locked' "$WORK/state/aurade/ash.log" || \
  fail 'A: the reason is not in the session log'

# --- B: a marker from an earlier session says nothing about this one --------

echo locked >"$MARKER"
touch -d '-1 hour' "$MARKER"
STUB_LOCK=0 run_session
(( LAUNCHES == 3 )) || \
  fail "B: launched ${LAUNCHES} times, expected the usual 3 restarts; a stale \
marker must not end a session that never locked"
[[ ! -s $WORK/control ]] || fail 'B: ended the session over a stale marker'

# --- C: no marker, restarts as always ---------------------------------------

rm -f "$MARKER"
STUB_LOCK=0 run_session
(( LAUNCHES == 3 )) || fail "C: launched ${LAUNCHES} times, expected 3"
[[ ! -s $WORK/control ]] || fail 'C: ended the session with no lock at all'

echo 'session locked exit test: PASS (ends the session when locked, ignores a stale marker, restarts otherwise)'
