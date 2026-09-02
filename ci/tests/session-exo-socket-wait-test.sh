#!/usr/bin/env bash
# The wait for exo's Wayland socket, exercised rather than grepped.
#
# Ash serves wayland-0 through exo. On a restart the outgoing Ash can still
# hold libwayland's flock on wayland-0.lock for several seconds, and the
# incoming one then dies in wayland_server_controller.cc on a DCHECK before it
# has drawn anything, spending one of the five fast restarts. The session child
# therefore waits for the lock to be released before launching Ash.
#
# Two things have to stay true and neither is visible to a grep for a symbol:
#
# It must never delete the lock or the socket. libwayland already unlinks a
# socket whose lock nobody holds. A lock somebody does hold is not stale, and
# removing it pulls the socket out from under a live session.
#
# It must give up. A desktop that never starts is worse than one more failed
# attempt, so the wait is bounded and the caller proceeds regardless.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
SCRIPT="$ROOT/chromiumos-ash/chromiumos-ash-session-child.sh"

fail() { echo "session exo socket test: $*" >&2; exit 1; }

[[ -r $SCRIPT ]] || fail 'the session child script is missing'
bash -n "$SCRIPT" || fail 'the session child script does not parse'

# --- source level contracts -------------------------------------------------

code=$(sed -e 's/#.*$//' "$SCRIPT")

grep -q 'wait_for_exo_socket' <<<"$code" || \
  fail 'the wait is gone entirely'

# The wait has to happen before Ash is launched, not after it has already
# failed, so the call must precede the CHROME_COMMAND invocation in the loop.
call_line=$(grep -n 'if ! wait_for_exo_socket; then' <<<"$code" | head -1 | cut -d: -f1)
chrome_line=$(grep -n '"\${CHROME_COMMAND}"' <<<"$code" | head -1 | cut -d: -f1)
[[ -n $call_line && -n $chrome_line ]] || \
  fail 'cannot locate the wait or the Ash launch in the restart loop'
[[ $call_line -lt $chrome_line ]] || \
  fail 'the wait runs after Ash is launched, which is no wait at all'

# Never destructive. Any rm touching the socket or its lock is the bug this
# whole fixture exists to prevent.
if grep -qE 'rm\b[^|;&]*(wayland|EXO_SOCKET|\.lock)' <<<"$code"; then
  fail 'the session child deletes the wayland socket or its lock; libwayland
already clears a genuinely stale one, and a held lock is not stale'
fi

grep -q 'EXO_SOCKET_TIMEOUT' <<<"$code" || \
  fail 'the wait is unbounded, so a stuck lock would mean no desktop at all'

# --- behaviour, by running the real function --------------------------------

fn=$(sed -n '/^wait_for_exo_socket() {$/,/^}$/p' "$SCRIPT")
[[ -n $fn ]] || fail 'cannot extract wait_for_exo_socket from the script'

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
eval "$fn"

EXO_SOCKET_TIMEOUT=3
export XDG_RUNTIME_DIR="$WORK"

# Each case gets its own socket name. flock spawns its command as a child which
# inherits the locked descriptor, so killing flock alone leaves the lock held
# and would silently poison the next case. Separate names make the cases
# independent of each other regardless, and the holders are killed by process
# group so nothing is left running either.
hold() {
    setsid flock -x "$1" -c "sleep $2" &
    HOLDER=$!
    sleep 0.5
}
release() {
    [[ -n ${HOLDER:-} ]] || return 0
    kill -- -"$HOLDER" 2>/dev/null || kill "$HOLDER" 2>/dev/null || true
    wait "$HOLDER" 2>/dev/null || true
    HOLDER=""
}
trap 'release; rm -rf "$WORK"' EXIT

# A: no lock file at all. Nothing to wait for.
EXO_SOCKET_NAME=wayland-a
LOCK="$WORK/${EXO_SOCKET_NAME}.lock"
start=$SECONDS
wait_for_exo_socket || fail 'A: returned failure when there is no lock file'
(( SECONDS - start <= 1 )) || fail 'A: waited despite there being no lock file'
# flock creates the file it is given. Probing a socket nobody is serving must
# not leave a lock behind for the next start to trip over.
[[ ! -e $LOCK ]] || fail 'A: probing created a lock file that did not exist'

# B: the lock file exists but nobody holds it. This is the stale case, and the
# right answer is to proceed immediately and let libwayland clean up.
EXO_SOCKET_NAME=wayland-b
LOCK="$WORK/${EXO_SOCKET_NAME}.lock"
: > "$LOCK"
start=$SECONDS
wait_for_exo_socket || fail 'B: treated an unheld lock as held'
(( SECONDS - start <= 1 )) || fail 'B: waited on a lock nobody holds'
[[ -e $LOCK ]] || fail 'B: the lock file was deleted, which is exactly what it must not do'

# C: somebody holds it for longer than the timeout. Give up, do not hang.
EXO_SOCKET_NAME=wayland-c
LOCK="$WORK/${EXO_SOCKET_NAME}.lock"
: > "$LOCK"
hold "$LOCK" 8
start=$SECONDS
if wait_for_exo_socket; then
  release
  fail 'C: reported the socket free while another process held the lock'
fi
elapsed=$(( SECONDS - start ))
release
(( elapsed >= EXO_SOCKET_TIMEOUT )) || \
  fail "C: gave up after ${elapsed}s, before the ${EXO_SOCKET_TIMEOUT}s timeout"
(( elapsed <= EXO_SOCKET_TIMEOUT + 2 )) || \
  fail "C: waited ${elapsed}s, well past its own timeout"
[[ -e $LOCK ]] || fail 'C: the lock file was deleted while another process held it'

# D: held, then released. This is the real restart: wait, then proceed.
EXO_SOCKET_NAME=wayland-d
LOCK="$WORK/${EXO_SOCKET_NAME}.lock"
: > "$LOCK"
hold "$LOCK" 2
start=$SECONDS
wait_for_exo_socket || fail 'D: gave up on a lock that was released in time'
elapsed=$(( SECONDS - start ))
release
(( elapsed >= 1 )) || fail 'D: returned before the holder had released the lock'
(( elapsed <= EXO_SOCKET_TIMEOUT )) || fail 'D: did not notice the release'

echo "session exo socket test: PASS (waits, never deletes, bounded, and returns as soon as the lock frees)"
