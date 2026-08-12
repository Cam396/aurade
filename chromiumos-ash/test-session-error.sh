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

printf '%s\n' 'session error reporting tests passed'
