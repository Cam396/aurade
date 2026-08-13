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

printf '%s\n' 'session error reporting tests passed'
