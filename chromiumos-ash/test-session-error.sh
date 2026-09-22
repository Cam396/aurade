#!/usr/bin/env bash
set -euo pipefail

error_script="${1:?path to aurade-session-error is required}"
workdir="$(mktemp -d)"
trap 'rm -rf "${workdir}"' EXIT
mkdir -p "${workdir}/state"
: >"${workdir}/tty"

set +e
AURADE_ERROR_STATE_DIR="${workdir}/state" \
  AURADE_ERROR_TTY="${workdir}/tty" \
  "${error_script}" missing-render 'unit-test' \
  >"${workdir}/stdout" 2>"${workdir}/stderr"
status=$?
set -e
[[ "${status}" == 78 ]]
grep -Fq 'No usable DRM render device was found.' "${workdir}/stderr"
grep -Fq 'Enable VMware 3D acceleration' "${workdir}/stderr"
grep -Fq 'kind=missing-render' "${workdir}/state/session-error.txt"
grep -Fq 'detail=unit-test' "${workdir}/state/session-error.txt"
grep -Fq 'AuraDE could not start the desktop' "${workdir}/tty"

set +e
AURADE_ERROR_STATE_DIR="${workdir}/state" \
  AURADE_ERROR_TTY="${workdir}/tty" \
  "${error_script}" compositor-failed 'status=134' \
  >"${workdir}/stdout" 2>"${workdir}/stderr"
status=$?
set -e
[[ "${status}" == 79 ]]
grep -Fq 'The compositor exited before a usable desktop appeared.' "${workdir}/stderr"
grep -Fq 'detail=status=134' "${workdir}/state/session-error.txt"

# Caller-supplied diagnostics must not inject report fields or terminal
# control sequences. The helper keeps the detail on one bounded line.
unsafe_detail=$'status=7\nINJECTED=1\t\e[2J'
set +e
AURADE_ERROR_STATE_DIR="${workdir}/state" \
  AURADE_ERROR_TTY="${workdir}/tty" \
  "${error_script}" session-failed "${unsafe_detail}" \
  >"${workdir}/unsafe-stdout" 2>"${workdir}/unsafe-stderr"
status=$?
set -e
[[ "${status}" == 79 ]]
grep -Fq 'detail=status=7 INJECTED=1  [2J' "${workdir}/state/session-error.txt"
! grep -Fq $'\nINJECTED=1' "${workdir}/state/session-error.txt"
! grep -Fq $'\033' "${workdir}/state/session-error.txt"

# The Ash child must surface a crash-loop as a structured compositor failure
# instead of silently returning to the greeter. Use disposable stubs; no real
# browser, D-Bus session, or compositor is started.
cat >"${workdir}/chrome-fails" <<'EOF'
#!/usr/bin/env bash
exit 42
EOF
cat >"${workdir}/session-error" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >"${AURADE_TEST_SESSION_ERROR:?}"
exit 79
EOF
chmod 0755 "${workdir}/chrome-fails" "${workdir}/session-error"
set +e
AURADE_CHROME_COMMAND="${workdir}/chrome-fails" \
  AURADE_SESSION_ERROR="${workdir}/session-error" \
  AURADE_RESTART_DELAY=0 AURADE_FAST_RESTART_WINDOW=60 \
  AURADE_MAX_FAST_RESTARTS=2 AURADE_TEST_SESSION_ERROR="${workdir}/child-error" \
  PATH="${workdir}:${PATH}" \
  "$(dirname "${error_script}")/chromiumos-ash-session-child.sh" \
  >"${workdir}/child-stdout" 2>"${workdir}/child-stderr"
status=$?
set -e
[[ "${status}" == 42 ]]
grep -Fq 'compositor-failed' "${workdir}/child-error"
grep -Fq 'last_status=42' "${workdir}/child-error"

# The session decides how the desktop draws before weston starts. A GPU it can
# open means the usual renderer; no GPU means pixman and software compositing
# instead of an error screen asking for hardware the machine does not have.
# What software cannot fix is still refused. Stubs throughout: nothing real is
# started and nothing reaches this machine's journal.
session_script="$(dirname "${error_script}")/chromiumos-ash-session.sh"
stubs="${workdir}/stubs"
mkdir -p "${stubs}"
cat >"${stubs}/weston" <<'EOF'
#!/usr/bin/env bash
{
  printf 'software=%s\n' "${AURADE_SOFTWARE_RENDERING:-unset}"
  printf 'arg=%s\n' "$@"
} >"${AURADE_TEST_WESTON_LOG:?}"
EOF
cat >"${stubs}/dbus-run-session" <<'EOF'
#!/usr/bin/env bash
[[ "${1:-}" == -- ]] && shift
exec "$@"
EOF
cat >"${stubs}/logger" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"${AURADE_TEST_LOGGER_LOG:?}"
EOF
chmod 0755 "${stubs}/weston" "${stubs}/dbus-run-session" "${stubs}/logger"

mkdir -p "${workdir}/dri-none" "${workdir}/dri-gpu"
: >"${workdir}/dri-none/card0"
: >"${workdir}/dri-gpu/card0"
: >"${workdir}/dri-gpu/renderD128"

run_session() {
  local dri="$1"
  shift
  mkdir -p "${workdir}/runtime"
  chmod 700 "${workdir}/runtime"
  rm -f "${workdir}/weston.log" "${workdir}/logger.log" "${workdir}/child-error"
  set +e
  env "$@" \
    AURADE_DRI_DIR="${dri}" \
    AURADE_SESSION_ERROR="${workdir}/session-error" \
    AURADE_TEST_SESSION_ERROR="${workdir}/child-error" \
    AURADE_TEST_WESTON_LOG="${workdir}/weston.log" \
    AURADE_TEST_LOGGER_LOG="${workdir}/logger.log" \
    XDG_RUNTIME_DIR="${workdir}/runtime" \
    PATH="${stubs}:${PATH}" \
    bash "${session_script}" >"${workdir}/session-stdout" 2>"${workdir}/session-stderr"
  session_status=$?
  set -e
}

# No render node at all: the desktop draws in software, and says so.
run_session "${workdir}/dri-none"
[[ "${session_status}" == 0 ]]
grep -Fxq 'arg=--renderer=pixman' "${workdir}/weston.log"
grep -Fxq 'software=1' "${workdir}/weston.log"
grep -Fq 'drawing the desktop in software' "${workdir}/logger.log"

# A render node this user can open: nothing changes from before.
run_session "${workdir}/dri-gpu"
[[ "${session_status}" == 0 ]]
grep -Fxq 'arg=--renderer=auto' "${workdir}/weston.log"
grep -Fxq 'software=0' "${workdir}/weston.log"
[[ ! -e "${workdir}/logger.log" ]]

# The old rule on request: no GPU is an error, and weston never starts.
run_session "${workdir}/dri-none" AURADE_ALLOW_SOFTWARE_RENDERER=0
[[ "${session_status}" == 78 ]]
grep -Fq 'missing-render' "${workdir}/child-error"
[[ ! -e "${workdir}/weston.log" ]]

# A GPU that is present and broken can be told to draw in software anyway.
run_session "${workdir}/dri-gpu" AURADE_FORCE_SOFTWARE_RENDERING=1
[[ "${session_status}" == 0 ]]
grep -Fxq 'arg=--renderer=pixman' "${workdir}/weston.log"
grep -Fxq 'software=1' "${workdir}/weston.log"

# An explicit renderer still wins over the software default.
run_session "${workdir}/dri-none" AURADE_WESTON_RENDERER=gl
[[ "${session_status}" == 0 ]]
grep -Fxq 'arg=--renderer=gl' "${workdir}/weston.log"
grep -Fxq 'software=1' "${workdir}/weston.log"

# No display device at all is still refused on the DRM backend...
run_session "${workdir}/no-such-dri"
[[ "${session_status}" == 78 ]]
grep -Fq 'missing-dri' "${workdir}/child-error"
[[ ! -e "${workdir}/weston.log" ]]

# ...and is not a question for a backend that does not use one.
run_session "${workdir}/no-such-dri" AURADE_WESTON_BACKEND=headless
[[ "${session_status}" == 0 ]]
grep -Fxq 'arg=--backend=headless' "${workdir}/weston.log"
grep -Fxq 'software=1' "${workdir}/weston.log"

# A render node that exists but cannot be opened is a permissions fault on a
# machine with a GPU. It is reported, not papered over with software. Root can
# open any file whatever its mode, so this one only runs unprivileged.
if [[ "$(id -u)" != 0 ]]; then
  mkdir -p "${workdir}/dri-locked"
  : >"${workdir}/dri-locked/card0"
  : >"${workdir}/dri-locked/renderD128"
  chmod 000 "${workdir}/dri-locked/renderD128"
  run_session "${workdir}/dri-locked"
  [[ "${session_status}" == 78 ]]
  grep -Fq 'render-permission' "${workdir}/child-error"
  [[ ! -e "${workdir}/weston.log" ]]
fi

# The other half of the same decision: the launcher turns the session's
# software mode into software compositing. A ChromeOS build refuses that unless
# the fallback is allowed, so software mode allows it even over a features.conf
# that says otherwise. Run as root the launcher hands itself to the login user,
# which is why these directories are open the way the OAuth test's are.
launcher="$(dirname "${error_script}")/chromiumos-ash.sh"
lt="${workdir}/launcher"
mkdir -p "${lt}/home" "${lt}/config" "${lt}/runtime"
chmod 700 "${lt}/runtime"
chmod 755 "${workdir}"
chmod 777 "${lt}"
cat >"${lt}/chrome" <<'EOF'
#!/bin/bash
{
  printf 'fallback=%s\n' "${AURADE_ALLOW_GPU_COMPOSITING_FALLBACK:-unset}"
  printf 'arg=%s\n' "$@"
} >"${AURADE_TEST_OUTPUT:?}"
EOF
chmod 755 "${lt}/chrome"

run_launcher() {
  rm -f "${lt}/output"
  env "$@" \
    HOME="${lt}/home" \
    XDG_CONFIG_HOME="${lt}/config" \
    XDG_RUNTIME_DIR="${lt}/runtime" \
    AURADE_CHROME="${lt}/chrome" \
    AURADE_CHROME_SANDBOX=/bin/false \
    AURADE_GOOGLE_API_CONF=/dev/null \
    AURADE_TEST_OUTPUT="${lt}/output" \
    AURADE_SKIP_SHILL_CHECK=1 \
    AURADE_ENABLE_PIPEWIRE_AUDIO=0 \
    AURADE_ENABLE_LOCAL_ACCOUNTS=0 \
    AURADE_LOCAL_AI_BOOTSTRAP=0 \
    AURADE_FEATURE_PROFILE=standard \
    AURADE_OZONE_PLATFORM=wayland \
    AURADE_DISABLE_SANDBOX=1 \
    DBUS_SESSION_BUS_ADDRESS=disabled \
    bash "${launcher}" >"${lt}/launcher.log" 2>&1
}

run_launcher AURADE_SOFTWARE_RENDERING=1 AURADE_ALLOW_GPU_COMPOSITING_FALLBACK=0
grep -Fxq 'arg=--disable-gpu-compositing' "${lt}/output"
grep -Fxq 'fallback=1' "${lt}/output"
# exo has no software path and took the desktop down with it at startup, so
# software mode does not ask for it.
if grep -Fxq 'arg=--enable-wayland-server' "${lt}/output"; then
  echo 'the launcher asked for the exo Wayland server in software mode' >&2
  exit 1
fi
grep -Fxq 'arg=--login-manager' "${lt}/output"

run_launcher AURADE_SOFTWARE_RENDERING=0
grep -Fxq 'arg=--ozone-platform=wayland' "${lt}/output"
grep -Fxq 'arg=--enable-wayland-server' "${lt}/output"
if grep -Fxq 'arg=--disable-gpu-compositing' "${lt}/output"; then
  echo 'the launcher asked for software compositing on a machine with a GPU' >&2
  exit 1
fi

printf '%s\n' 'session error reporting tests passed'
