#!/usr/bin/env bash
# The Files service starts with the session and ends with it, exercised by
# running the real session child with a stub Ash and a stub service.
#
# Three things have to hold. The service is started before Ash, as this user,
# with the port the desktop names, so the app's first request is answered. It
# is ended when the session child ends, or a stale one would answer the next
# session's app with the last session's state. And a machine without the
# binary loses nothing but the app's backend: the desktop must still come up.
#
# Two more, since the service became a packaged user unit. On the port the
# shipped page asks for, and with a user manager to hand it to, the session
# starts the unit and starts nothing else: two launchers on one port was the
# shape of the bug, and the unit is where the restart, the journal and the
# hardening live. And when the manager will not take it, the direct launch
# still happens, so a session with no manager is exactly as served as before.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
SCRIPT="$ROOT/chromiumos-ash/chromiumos-ash-session-child.sh"

fail() { echo "files service test: $*" >&2; exit 1; }

[[ -r $SCRIPT ]] || fail 'the session child script is missing'
bash -n "$SCRIPT" || fail 'the session child script does not parse'

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/run" "$WORK/state" "$WORK/bin"

# A stub Ash that records whether the service was already up when it started,
# then exits so the session ends on its own.
cat >"$WORK/bin/stub-ash" <<'STUB'
#!/usr/bin/env bash
if [[ -r ${STUB_SERVICE_PID_FILE} ]] && kill -0 "$(cat "${STUB_SERVICE_PID_FILE}")" 2>/dev/null; then
    echo service-up >>"${STUB_LAUNCH_LOG}"
else
    echo service-down >>"${STUB_LAUNCH_LOG}"
fi
exit 0
STUB
chmod +x "$WORK/bin/stub-ash"

# A stub service that records its arguments and its user and then waits to be
# ended, which is what the real one does.
cat >"$WORK/bin/auradefs" <<'STUB'
#!/usr/bin/env bash
echo "$$" >"${STUB_SERVICE_PID_FILE}"
echo "args=$* user=$(id -un)" >>"${STUB_SERVICE_LOG}"
trap 'exit 0' TERM
while :; do sleep 1; done
STUB
chmod +x "$WORK/bin/auradefs"

env_args=(
  XDG_RUNTIME_DIR="$WORK/run"
  XDG_STATE_HOME="$WORK/state"
  STUB_LAUNCH_LOG="$WORK/launches"
  STUB_SERVICE_LOG="$WORK/service"
  STUB_SERVICE_PID_FILE="$WORK/service.pid"
  AURADE_CHROME_COMMAND="$WORK/bin/stub-ash"
  AURADE_SESSION_ERROR="$WORK/bin/no-such-reporter"
  AURADE_EXO_SOCKET=wayland-files-service
  AURADE_EXO_SOCKET_TIMEOUT=1
  AURADE_RESTART_DELAY=0
  AURADE_SESSION_ON_EXIT=exit
  AURADE_REMOVABLE_AUTOMOUNT=0
  AURADE_FILES_PORT=8917
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

# --- A: with the binary on PATH. --------------------------------------------
: >"$WORK/launches"; : >"$WORK/service"; rm -f "$WORK/service.pid"
env "${env_args[@]}" PATH="$WORK/bin:$PATH" bash "$SCRIPT" >/dev/null 2>"$WORK/err" || true
[[ -s $WORK/service ]] || fail "A: the service was never started: $(cat "$WORK/err")"
grep -q "args=--port 8917 " "$WORK/service" || \
  fail "A: the service was not given the desktop's port: $(cat "$WORK/service")"
grep -q "user=$(id -un)" "$WORK/service" || \
  fail "A: the service did not run as the session user: $(cat "$WORK/service")"
grep -q '^service-up$' "$WORK/launches" || \
  fail "A: Ash started before the service was up: $(cat "$WORK/launches")"
SVC=$(cat "$WORK/service.pid")
wait_gone "$SVC" 5 || { kill -KILL "$SVC" 2>/dev/null || true; \
  fail 'A: the service outlived the session child; a stale one would answer the next session'; }
[[ -f $WORK/state/aurade/auradefs.log ]] || \
  fail 'A: the service has no log beside the desktop'"'"'s'

# --- B: without the binary. The desktop still comes up. ---------------------
: >"$WORK/launches"; : >"$WORK/service"; rm -f "$WORK/service.pid" "$WORK/bin/auradefs"
env "${env_args[@]}" PATH="$WORK/bin:$PATH" bash "$SCRIPT" >/dev/null 2>"$WORK/err2" || true
grep -q '^service-down$' "$WORK/launches" || \
  fail "B: Ash did not start without the service: $(cat "$WORK/err2")"
[[ ! -s $WORK/service ]] || fail 'B: something started a service that is not installed'

# --- C: the port the page asks for, and a manager that takes the unit. -----
# The stub manager and the stub Ash share one sequence log, so the order the
# session did things in is a fact and not an inference.
cat >"$WORK/bin/auradefs" <<'STUB'
#!/usr/bin/env bash
echo "$$" >"${STUB_SERVICE_PID_FILE}"
echo "args=$* user=$(id -un)" >>"${STUB_SERVICE_LOG}"
trap 'exit 0' TERM
while :; do sleep 1; done
STUB
chmod +x "$WORK/bin/auradefs"
cat >"$WORK/bin/systemctl" <<'STUB'
#!/usr/bin/env bash
case "$*" in
  "--user start auradefs.service") echo unit-start >>"${STUB_SEQUENCE}"; exit "${STUB_UNIT_START_STATUS:-0}" ;;
  "--user stop auradefs.service")  echo unit-stop  >>"${STUB_SEQUENCE}"; exit 0 ;;
esac
exit 0
STUB
chmod +x "$WORK/bin/systemctl"
cat >"$WORK/bin/stub-ash" <<'STUB'
#!/usr/bin/env bash
echo ash >>"${STUB_SEQUENCE}"
exit 0
STUB
chmod +x "$WORK/bin/stub-ash"

: >"$WORK/service"; : >"$WORK/sequence"; rm -f "$WORK/service.pid"
env "${env_args[@]}" AURADE_FILES_PORT= STUB_SEQUENCE="$WORK/sequence" \
  PATH="$WORK/bin:$PATH" bash "$SCRIPT" >/dev/null 2>"$WORK/err3" || true
[[ "$(tr '\n' ' ' <"$WORK/sequence")" == "unit-start ash unit-stop " ]] || \
  fail "C: expected the unit started before Ash and stopped after it, got: $(tr '\n' ' ' <"$WORK/sequence")"
[[ ! -s $WORK/service ]] || \
  fail "C: the unit was started and a second daemon was launched beside it: $(cat "$WORK/service")"

# --- D: the same, but the manager refuses. The direct launch still happens. -
: >"$WORK/service"; : >"$WORK/sequence"; rm -f "$WORK/service.pid"
env "${env_args[@]}" AURADE_FILES_PORT= STUB_SEQUENCE="$WORK/sequence" STUB_UNIT_START_STATUS=1 \
  PATH="$WORK/bin:$PATH" bash "$SCRIPT" >/dev/null 2>"$WORK/err4" || true
grep -q '^unit-start$' "$WORK/sequence" || fail 'D: the unit was never even tried'
grep -q '^unit-stop$' "$WORK/sequence" && fail 'D: a unit that never started was stopped'
grep -q "args=--port 8902 " "$WORK/service" || \
  fail "D: with the manager refusing, no daemon was launched on the page's port: $(cat "$WORK/service")"
SVC=$(cat "$WORK/service.pid")
wait_gone "$SVC" 5 || { kill -KILL "$SVC" 2>/dev/null || true; \
  fail 'D: the fallback daemon outlived the session child'; }

echo 'files service test: PASS'
