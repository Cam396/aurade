#!/usr/bin/env bash
# The Files service starts with the session and ends with it, exercised by
# running the real session child with a stub Ash and a stub service.
#
# Three things have to hold. The service is started before Ash, as this user,
# with the port the desktop names, so the app's first request is answered. It
# is ended when the session child ends, or a stale one would answer the next
# session's app with the last session's state. And a machine without the
# binary loses nothing but the app's backend: the desktop must still come up.
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

echo 'files service test: PASS'
