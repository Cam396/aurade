#!/bin/bash
set -euo pipefail

root_dir="${AURADE_TEST_ROOT:-$(cd -- "$(dirname -- "$0")" && pwd -P)}"
supervisor="${root_dir}/aurade-session-supervisor"
session_control="${root_dir}/aurade-session-control"
greetd_vt="${root_dir}/aurade-greetd-vt"
static_config="${root_dir}/aurade.toml"
install_script="${root_dir}/aurade-login.install"
session_child="${AURADE_TEST_SESSION_CHILD:-${root_dir}/test-session-child}"
fake_greetd="${AURADE_TEST_GREETD:-${root_dir}/test-greetd}"
test_tmp="$(mktemp -d)"
supervisor_pids=()
session_group_pids=()

cleanup() {
  local pid
  for pid in "${session_group_pids[@]}"; do
    if [[ "${pid}" =~ ^[0-9]+$ ]]; then
      kill -KILL -- "-${pid}" 2>/dev/null || true
    fi
  done
  for pid in "${supervisor_pids[@]}"; do
    if [[ "${pid}" =~ ^[0-9]+$ ]] && kill -0 "${pid}" 2>/dev/null; then
      kill -TERM "${pid}" 2>/dev/null || true
    fi
  done
  rm -rf -- "${test_tmp}"
}
trap cleanup EXIT

fail() {
  local log line
  printf 'session supervisor test: %s\n' "$*" >&2
  for log in "${test_tmp}"/*supervisor.log; do
    [[ -f "${log}" ]] || continue
    printf '%s:\n' "${log}" >&2
    while IFS= read -r line; do
      printf '  %s\n' "${line}" >&2
    done <"${log}"
  done
  exit 1
}

wait_for_file() {
  local path="$1"
  for _ in {1..200}; do
    [[ -s "${path}" ]] && return 0
    sleep 0.05
  done
  fail "timed out waiting for ${path}"
}

wait_for_count() {
  local pattern="$1" expected="$2" path="$3" count
  for _ in {1..200}; do
    count="$(grep -c -- "${pattern}" "${path}" 2>/dev/null || true)"
    [[ "${count}" -ge "${expected}" ]] && return 0
    sleep 0.05
  done
  fail "timed out waiting for ${expected} matches of ${pattern} in ${path}"
}

bind_test_commands=()
for command_name in bash cat chmod flock install mkdir mv rm setsid sleep true; do
  command_path="$(type -P "${command_name}")"
  [[ -n "${command_path}" ]] || fail "missing test command: ${command_name}"
  bind_test_commands+=(--ro-bind "${command_path}" "/usr/bin/${command_name}")
done
command -v bwrap >/dev/null 2>&1 || fail "bubblewrap is required"

test_default_command() {
  local runtime_dir="${test_tmp}/default-runtime"
  local session_log="${test_tmp}/default-session.log"
  local launcher_pid supervisor_pid pid_file
  mkdir -p "${runtime_dir}"

  bwrap \
    --ro-bind / / \
    --bind "${test_tmp}" "${test_tmp}" \
    --tmpfs /usr/bin \
    "${bind_test_commands[@]}" \
    --ro-bind "${session_child}" /usr/bin/chromiumos-ash-session \
    --proc /proc \
    --dev /dev \
    --setenv XDG_RUNTIME_DIR "${runtime_dir}" \
    --setenv XDG_SESSION_ID aurade-default \
    --setenv AURADE_TEST_SESSION_LOG "${session_log}" \
    -- /usr/bin/bash "${supervisor}" \
      >"${test_tmp}/default-supervisor.log" 2>&1 &
  launcher_pid=$!

  pid_file="${runtime_dir}/aurade/sessions/aurade-default/session-supervisor.pid"
  wait_for_file "${pid_file}"
  read -r supervisor_pid <"${pid_file}"
  supervisor_pids+=("${supervisor_pid}")
  wait_for_count '^start ' 1 "${session_log}"
  grep -Eq '^start pid=[0-9]+ argc=0$' "${session_log}" || \
    fail "default command did not start without arguments"

  kill -TERM "${supervisor_pid}"
  wait "${launcher_pid}"
  [[ ! -e "${pid_file}" ]] || fail "default supervisor pid file survived stop"
}

test_cached_legacy_command_migrated() {
  local runtime_dir="${test_tmp}/cached-command-runtime"
  local session_log="${test_tmp}/cached-command-session.log"
  local launcher_pid supervisor_pid pid_file
  mkdir -p "${runtime_dir}"

  # This is the argv shape produced when tuigreet 0.9.1 restores pkgrel 1's
  # supervisor-valued remembered command and prefixes the pkgrel 2 wrapper.
  bwrap \
    --ro-bind / / \
    --bind "${test_tmp}" "${test_tmp}" \
    --tmpfs /usr/bin \
    "${bind_test_commands[@]}" \
    --ro-bind "${supervisor}" /usr/bin/aurade-session-supervisor \
    --ro-bind "${session_child}" /usr/bin/chromiumos-ash-session \
    --proc /proc \
    --dev /dev \
    --setenv XDG_RUNTIME_DIR "${runtime_dir}" \
    --setenv XDG_SESSION_ID aurade-cached-command \
    --setenv AURADE_TEST_SESSION_LOG "${session_log}" \
    -- /usr/bin/bash -c \
      'exec /usr/bin/bash /usr/bin/aurade-session-supervisor /usr/bin/aurade-session-supervisor' \
      >"${test_tmp}/cached-command-supervisor.log" 2>&1 &
  launcher_pid=$!

  pid_file="${runtime_dir}/aurade/sessions/aurade-cached-command/session-supervisor.pid"
  wait_for_file "${pid_file}"
  read -r supervisor_pid <"${pid_file}"
  supervisor_pids+=("${supervisor_pid}")
  wait_for_count '^start ' 1 "${session_log}"
  grep -Eq '^start pid=[0-9]+ argc=0$' "${session_log}" || \
    fail "cached legacy command did not resolve to the default session"
  grep -Fxq \
    'aurade-session-supervisor: replacing obsolete cached supervisor command' \
    "${test_tmp}/cached-command-supervisor.log" || \
    fail "cached legacy command migration was not reported"

  kill -TERM "${supervisor_pid}"
  wait "${launcher_pid}"
  [[ ! -e "${pid_file}" ]] || fail "cached-command pid file survived stop"
}

test_selected_command_restart_and_stop() {
  local runtime_dir="${test_tmp}/selected-runtime"
  local session_log="${test_tmp}/selected-session.log"
  local supervisor_pid pid_file first_child second_child
  mkdir -p "${runtime_dir}"

  AURADE_TEST_SESSION_LOG="${session_log}" \
    XDG_RUNTIME_DIR="${runtime_dir}" \
    XDG_SESSION_ID=aurade-selected \
    /usr/bin/bash "${supervisor}" "${session_child}" \
      'argument with spaces' 'literal*' '' '--flag=value' \
      >"${test_tmp}/selected-supervisor.log" 2>&1 &
  supervisor_pid=$!
  supervisor_pids+=("${supervisor_pid}")

  pid_file="${runtime_dir}/aurade/sessions/aurade-selected/session-supervisor.pid"
  wait_for_file "${pid_file}"
  [[ "$(<"${pid_file}")" == "${supervisor_pid}" ]] || \
    fail "pid file does not identify selected-command supervisor"
  wait_for_count '^start ' 1 "${session_log}"
  grep -Eq '^start pid=[0-9]+ argc=4$' "${session_log}" || \
    fail "selected command argument count changed"
  grep -Fxq 'arg[0]=<argument with spaces>' "${session_log}"
  grep -Fxq 'arg[1]=<literal*>' "${session_log}"
  grep -Fxq 'arg[2]=<>' "${session_log}"
  grep -Fxq 'arg[3]=<--flag=value>' "${session_log}"
  first_child="$(awk '/^start / { sub(/^.*pid=/, ""); sub(/ .*/, ""); print; exit }' "${session_log}")"

  kill -USR1 "${supervisor_pid}"
  wait_for_count '^start ' 2 "${session_log}"
  wait_for_count '^stop ' 1 "${session_log}"
  second_child="$(awk '/^start / { sub(/^.*pid=/, ""); sub(/ .*/, ""); pid=$0 } END { print pid }' "${session_log}")"
  [[ "${first_child}" != "${second_child}" ]] || \
    fail "restart reused the original child pid"
  ! kill -0 "${first_child}" 2>/dev/null || \
    fail "original child remained alive after restart"

  kill -TERM "${supervisor_pid}"
  wait "${supervisor_pid}"
  wait_for_count '^stop ' 2 "${session_log}"
  [[ ! -e "${pid_file}" ]] || fail "selected supervisor pid file survived stop"
}

test_failed_session_retries_before_greeter_return() {
  local runtime_dir="${test_tmp}/failed-runtime"
  local failure_log="${test_tmp}/failed-session.log"
  local failing_child="${test_tmp}/failing-session-child"
  local output="${test_tmp}/failed-supervisor.log"
  local supervisor_pid status
  mkdir -p "${runtime_dir}"
  cat >"${failing_child}" <<'EOF'
#!/bin/bash
set -u
printf 'failed-start pid=%s\n' "$$" >>"${AURADE_TEST_SESSION_LOG}"
exit 7
EOF
  chmod 755 "${failing_child}"

  AURADE_TEST_SESSION_LOG="${failure_log}" \
    AURADE_SUPERVISOR_MAX_SESSION_FAILURES=2 \
    AURADE_SUPERVISOR_RETRY_DELAY_SECONDS=0 \
    XDG_RUNTIME_DIR="${runtime_dir}" \
    XDG_SESSION_ID=aurade-failed \
    /usr/bin/bash "${supervisor}" "${failing_child}" >"${output}" 2>&1 &
  supervisor_pid=$!
  if wait "${supervisor_pid}"; then
    fail "failed session unexpectedly returned success"
  else
    status=$?
  fi
  [[ "${status}" == 7 ]] || fail "failed session returned status ${status}, expected 7"
  [[ "$(grep -c '^failed-start ' "${failure_log}")" == 2 ]] || \
    fail "failed session was not retried exactly once"
  grep -Fxq \
    'aurade-session-supervisor: session exited with status 7; retry 1/2' \
    "${output}" || fail "retry diagnostic was not emitted"
  grep -Fxq \
    'aurade-session-supervisor: session failed 2 times; returning to greeter' \
    "${output}" || fail "final failure diagnostic was not emitted"
  [[ ! -e "${runtime_dir}/aurade/sessions/aurade-failed/session-supervisor.pid" ]] || \
    fail "failed session pid file survived greeter return"
}

test_empty_command_rejected() {
  local runtime_dir="${test_tmp}/empty-command-runtime"
  local output="${test_tmp}/empty-command-supervisor.log"
  mkdir -p "${runtime_dir}"

  if XDG_RUNTIME_DIR="${runtime_dir}" \
      XDG_SESSION_ID=aurade-empty \
      /usr/bin/bash "${supervisor}" '' >"${output}" 2>&1; then
    fail "empty selected command unexpectedly started"
  fi
  grep -Fxq 'aurade-session-supervisor: session command cannot be empty' \
    "${output}" || fail "empty selected command did not report its error"
  [[ ! -e "${runtime_dir}/aurade/sessions/aurade-empty/session-supervisor.pid" ]] || \
    fail "empty selected command created a supervisor pid file"
}

test_invalid_session_ids_rejected() {
  local runtime_dir="${test_tmp}/invalid-id-runtime"
  local invalid_id output
  mkdir -p "${runtime_dir}"

  for invalid_id in . .. 'bad/id'; do
    output="${test_tmp}/invalid-id-${invalid_id//\//_}-supervisor.log"
    if XDG_RUNTIME_DIR="${runtime_dir}" \
        XDG_SESSION_ID="${invalid_id}" \
        /usr/bin/bash "${supervisor}" "${session_child}" >"${output}" 2>&1; then
      fail "supervisor accepted invalid XDG_SESSION_ID ${invalid_id}"
    fi
    grep -Fxq 'aurade-session-supervisor: invalid XDG_SESSION_ID' "${output}" || \
      fail "supervisor did not report invalid XDG_SESSION_ID ${invalid_id}"

    output="${test_tmp}/invalid-id-${invalid_id//\//_}-control.log"
    if XDG_RUNTIME_DIR="${runtime_dir}" \
        XDG_SESSION_ID="${invalid_id}" \
        /usr/bin/bash "${session_control}" status >"${output}" 2>&1; then
      fail "session control accepted invalid XDG_SESSION_ID ${invalid_id}"
    fi
    grep -Fxq 'aurade-session-control: no valid logind session' "${output}" || \
      fail "session control did not report invalid XDG_SESSION_ID ${invalid_id}"
  done
}

test_symlink_state_rejected() {
  local runtime_dir="${test_tmp}/symlink-runtime"
  local target="${test_tmp}/symlink-target"
  local output="${test_tmp}/symlink-supervisor.log"
  mkdir -p "${runtime_dir}" "${target}"
  ln -s "${target}" "${runtime_dir}/aurade"

  if AURADE_TEST_SESSION_LOG="${test_tmp}/symlink-session.log" \
      XDG_RUNTIME_DIR="${runtime_dir}" \
      XDG_SESSION_ID=aurade-symlink \
      /usr/bin/bash "${supervisor}" "${session_child}" >"${output}" 2>&1; then
    fail "supervisor accepted a symlink state root"
  fi
  grep -Fq 'refusing symlink state directory' "${output}" || \
    fail "symlink state rejection did not report its error"
  [[ ! -e "${target}/sessions" ]] || \
    fail "supervisor followed the symlink state root"
}

test_session_scoped_pidfiles() {
  local runtime_dir="${test_tmp}/scoped-runtime"
  local first_log="${test_tmp}/scoped-first-session.log"
  local second_log="${test_tmp}/scoped-second-session.log"
  local first_pid second_pid first_pid_file second_pid_file second_starts second_stops
  mkdir -p "${runtime_dir}"

  AURADE_TEST_SESSION_LOG="${first_log}" \
    XDG_RUNTIME_DIR="${runtime_dir}" \
    XDG_SESSION_ID=aurade-scope-a \
    /usr/bin/bash "${supervisor}" "${session_child}" first \
      >"${test_tmp}/scoped-first-supervisor.log" 2>&1 &
  first_pid=$!
  supervisor_pids+=("${first_pid}")

  AURADE_TEST_SESSION_LOG="${second_log}" \
    XDG_RUNTIME_DIR="${runtime_dir}" \
    XDG_SESSION_ID=aurade-scope-b \
    /usr/bin/bash "${supervisor}" "${session_child}" second \
      >"${test_tmp}/scoped-second-supervisor.log" 2>&1 &
  second_pid=$!
  supervisor_pids+=("${second_pid}")

  first_pid_file="${runtime_dir}/aurade/sessions/aurade-scope-a/session-supervisor.pid"
  second_pid_file="${runtime_dir}/aurade/sessions/aurade-scope-b/session-supervisor.pid"
  wait_for_file "${first_pid_file}"
  wait_for_file "${second_pid_file}"
  [[ "$(<"${first_pid_file}")" == "${first_pid}" ]] || \
    fail "first scoped pid file identifies the wrong supervisor"
  [[ "$(<"${second_pid_file}")" == "${second_pid}" ]] || \
    fail "second scoped pid file identifies the wrong supervisor"
  wait_for_count '^start ' 1 "${first_log}"
  wait_for_count '^start ' 1 "${second_log}"

  kill -USR1 "${first_pid}"
  wait_for_count '^start ' 2 "${first_log}"
  wait_for_count '^stop ' 1 "${first_log}"
  second_starts="$(grep -c '^start ' "${second_log}")"
  second_stops="$(grep -c '^stop ' "${second_log}" || true)"
  [[ "${second_starts}" == 1 && "${second_stops}" == 0 ]] || \
    fail "restarting one session disturbed another session for the same UID"

  kill -TERM "${first_pid}" "${second_pid}"
  wait "${first_pid}"
  wait "${second_pid}"
  [[ ! -e "${first_pid_file}" && ! -e "${second_pid_file}" ]] || \
    fail "a scoped supervisor pid file survived stop"
}

test_unscoped_fallback_fails_closed() {
  local runtime_dir="${test_tmp}/fallback-runtime"
  local first_log="${test_tmp}/fallback-first-session.log"
  local first_pid pid_file output
  mkdir -p "${runtime_dir}"

  env -u XDG_SESSION_ID \
    AURADE_TEST_SESSION_LOG="${first_log}" \
    XDG_RUNTIME_DIR="${runtime_dir}" \
    /usr/bin/bash "${supervisor}" "${session_child}" \
      >"${test_tmp}/fallback-first-supervisor.log" 2>&1 &
  first_pid=$!
  supervisor_pids+=("${first_pid}")
  pid_file="${runtime_dir}/aurade/session-supervisor.pid"
  wait_for_file "${pid_file}"
  wait_for_count '^start ' 1 "${first_log}"

  output="${test_tmp}/fallback-collision-supervisor.log"
  if env -u XDG_SESSION_ID \
      AURADE_TEST_SESSION_LOG="${test_tmp}/fallback-collision-session.log" \
      XDG_RUNTIME_DIR="${runtime_dir}" \
      /usr/bin/bash "${supervisor}" "${session_child}" >"${output}" 2>&1; then
    fail "a second unscoped supervisor unexpectedly acquired the fallback slot"
  fi
  grep -Fxq \
    'aurade-session-supervisor: unscoped fallback already has an active supervisor' \
    "${output}" || fail "unscoped collision did not report its error"
  [[ "$(<"${pid_file}")" == "${first_pid}" ]] || \
    fail "unscoped collision replaced the live supervisor pid"

  kill -TERM "${first_pid}"
  wait "${first_pid}"
  [[ ! -e "${pid_file}" ]] || fail "unscoped supervisor pid file survived stop"
}

test_supervisor_crash_fails_closed() {
  local runtime_dir="${test_tmp}/crash-runtime"
  local session_log="${test_tmp}/crash-session.log"
  local supervisor_pid child_pid pid_file output replacement_started=0
  mkdir -p "${runtime_dir}"

  AURADE_TEST_SESSION_LOG="${session_log}" \
    XDG_RUNTIME_DIR="${runtime_dir}" \
    XDG_SESSION_ID=aurade-crash \
    /usr/bin/bash "${supervisor}" "${session_child}" \
      >"${test_tmp}/crash-supervisor.log" 2>&1 &
  supervisor_pid=$!
  supervisor_pids+=("${supervisor_pid}")
  pid_file="${runtime_dir}/aurade/sessions/aurade-crash/session-supervisor.pid"
  wait_for_file "${pid_file}"
  wait_for_count '^start ' 1 "${session_log}"
  child_pid="$(sed -n 's/^start pid=\([0-9][0-9]*\).*/\1/p' "${session_log}" | head -1)"
  [[ "${child_pid}" =~ ^[0-9]+$ ]] || fail "could not identify crash-test child"
  session_group_pids+=("${child_pid}")
  [[ -e "/proc/${child_pid}/fd/9" ]] || \
    fail "session child did not inherit the fail-closed lock"

  kill -KILL "${supervisor_pid}"
  wait "${supervisor_pid}" 2>/dev/null || true
  kill -0 "${child_pid}" 2>/dev/null || \
    fail "session child did not survive the simulated supervisor crash"

  output="${test_tmp}/crash-replacement-blocked.log"
  if XDG_RUNTIME_DIR="${runtime_dir}" \
      XDG_SESSION_ID=aurade-crash \
      /usr/bin/bash "${supervisor}" /usr/bin/true >"${output}" 2>&1; then
    fail "replacement supervisor started alongside an orphaned session"
  fi
  grep -Fxq \
    'aurade-session-supervisor: session aurade-crash already has an active supervisor' \
    "${output}" || fail "orphan lock collision did not report its error"

  kill -KILL -- "-${child_pid}" 2>/dev/null || true
  for _ in {1..100}; do
    if XDG_RUNTIME_DIR="${runtime_dir}" \
        XDG_SESSION_ID=aurade-crash \
        /usr/bin/bash "${supervisor}" /usr/bin/true \
          >"${test_tmp}/crash-replacement-after-child.log" 2>&1; then
      replacement_started=1
      break
    fi
    sleep 0.02
  done
  [[ "${replacement_started}" == 1 ]] || \
    fail "replacement supervisor remained locked after the orphan exited"
}

test_watchdog_drops_lock_fd() {
  local runtime_dir="${test_tmp}/watchdog-runtime"
  local session_log="${test_tmp}/watchdog-session.log"
  local supervisor_pid child_pid second_child pid_file watchdog_pid="" candidate
  mkdir -p "${runtime_dir}"

  AURADE_TEST_IGNORE_TERM=1 \
    AURADE_SUPERVISOR_STOP_GRACE_SECONDS=1 \
    AURADE_SUPERVISOR_STOP_KILL_SECONDS=0.2 \
    AURADE_TEST_SESSION_LOG="${session_log}" \
    XDG_RUNTIME_DIR="${runtime_dir}" \
    XDG_SESSION_ID=aurade-watchdog \
    /usr/bin/bash "${supervisor}" "${session_child}" \
      >"${test_tmp}/watchdog-supervisor.log" 2>&1 &
  supervisor_pid=$!
  supervisor_pids+=("${supervisor_pid}")
  pid_file="${runtime_dir}/aurade/sessions/aurade-watchdog/session-supervisor.pid"
  wait_for_file "${pid_file}"
  wait_for_count '^start ' 1 "${session_log}"
  child_pid="$(sed -n 's/^start pid=\([0-9][0-9]*\).*/\1/p' "${session_log}" | head -1)"
  [[ "${child_pid}" =~ ^[0-9]+$ ]] || fail "could not identify watchdog-test child"
  session_group_pids+=("${child_pid}")

  kill -USR1 "${supervisor_pid}"
  for _ in {1..100}; do
    while read -r candidate; do
      if [[ "${candidate}" =~ ^[0-9]+$ && "${candidate}" != "${child_pid}" ]]; then
        watchdog_pid="${candidate}"
        break
      fi
    done < <(ps -o pid= --ppid "${supervisor_pid}" | tr -d ' ')
    [[ -n "${watchdog_pid}" ]] && break
    sleep 0.01
  done
  [[ "${watchdog_pid}" =~ ^[0-9]+$ ]] || fail "watchdog process was not observed"
  [[ ! -e "/proc/${watchdog_pid}/fd/9" ]] || \
    fail "watchdog inherited the session lock fd"

  wait_for_count '^start ' 2 "${session_log}"
  second_child="$(sed -n 's/^start pid=\([0-9][0-9]*\).*/\1/p' "${session_log}" | tail -1)"
  [[ "${second_child}" =~ ^[0-9]+$ && "${second_child}" != "${child_pid}" ]] || \
    fail "watchdog did not force a fresh session child"
  session_group_pids+=("${second_child}")

  kill -TERM "${supervisor_pid}"
  wait "${supervisor_pid}"
  [[ ! -e "${pid_file}" ]] || fail "watchdog supervisor pid file survived stop"
}

test_session_control_restarts_own_scope() {
  local runtime_dir="${test_tmp}/control-runtime"
  local session_log="${test_tmp}/control-session.log"
  local fake_bin="${test_tmp}/control-bin"
  local supervisor_pid
  mkdir -p "${runtime_dir}" "${fake_bin}"
  cat >"${fake_bin}/loginctl" <<'EOF'
#!/bin/bash
if [[ "${1:-}" == show-session && "${3:-}" == --property=User ]]; then
  printf '%s\n' "${AURADE_TEST_UID:?}"
  exit 0
fi
exit 1
EOF
  chmod 755 "${fake_bin}/loginctl"

  AURADE_TEST_SESSION_LOG="${session_log}" \
    XDG_RUNTIME_DIR="${runtime_dir}" \
    XDG_SESSION_ID=aurade-control \
    /usr/bin/bash "${supervisor}" "${session_child}" \
      >"${test_tmp}/control-supervisor.log" 2>&1 &
  supervisor_pid=$!
  supervisor_pids+=("${supervisor_pid}")
  wait_for_file \
    "${runtime_dir}/aurade/sessions/aurade-control/session-supervisor.pid"
  wait_for_count '^start ' 1 "${session_log}"

  AURADE_TEST_UID="$(id -u)" \
    PATH="${fake_bin}:${PATH}" \
    XDG_RUNTIME_DIR="${runtime_dir}" \
    XDG_SESSION_ID=aurade-control \
    /usr/bin/bash "${session_control}" restart
  wait_for_count '^start ' 2 "${session_log}"
  wait_for_count '^stop ' 1 "${session_log}"

  kill -TERM "${supervisor_pid}"
  wait "${supervisor_pid}"
}

test_greetd_config_consistency() {
  local generated_dir="${test_tmp}/generated-greetd"
  local expected_command static_command generated_command
  mkdir -p "${generated_dir}"

  bwrap \
    --ro-bind / / \
    --bind "${test_tmp}" "${test_tmp}" \
    --tmpfs /usr/bin \
    "${bind_test_commands[@]}" \
    --ro-bind "${fake_greetd}" /usr/bin/greetd \
    --tmpfs /run \
    --bind "${generated_dir}" /run/aurade-login \
    --proc /proc \
    --dev /dev \
    -- /usr/bin/bash "${greetd_vt}" 8

  static_command="$(grep '^command = ' "${static_config}")"
  generated_command="$(grep '^command = ' "${generated_dir}/greetd-vt8.toml")"
  expected_command='command = "tuigreet --time --remember --remember-user-session --asterisks --sessions /usr/share/wayland-sessions --session-wrapper /usr/bin/aurade-session-supervisor --cmd /usr/bin/chromiumos-ash-session"'
  [[ "${static_command}" == "${expected_command}" ]] || \
    fail "static greetd command is not the supervised command"
  [[ "${generated_command}" == "${static_command}" ]] || \
    fail "generated and static greetd commands differ"
  grep -Fxq 'vt = 8' "${generated_dir}/greetd-vt8.toml" || \
    fail "secondary greetd config used the wrong VT"
}

test_legacy_config_migration() {
  local config="${test_tmp}/legacy-aurade.toml"
  local untouched="${test_tmp}/custom-aurade.toml"
  local legacy replacement before after
  legacy='command = "tuigreet --time --remember --remember-user-session --asterisks --sessions /usr/share/wayland-sessions --cmd /usr/bin/aurade-session-supervisor"'
  replacement='command = "tuigreet --time --remember --remember-user-session --asterisks --sessions /usr/share/wayland-sessions --session-wrapper /usr/bin/aurade-session-supervisor --cmd /usr/bin/chromiumos-ash-session"'

  printf '%s\n' \
    '[terminal]' \
    'vt = 1' \
    '' \
    '[default_session]' \
    "${legacy}" \
    'user = "custom-greeter"' >"${config}"
  chmod 640 "${config}"
  (
    # shellcheck source=aurade-login.install
    source "${install_script}"
    _aurade_migrate_legacy_config "${config}"
  )
  grep -Fqx -- "${replacement}" "${config}" || \
    fail "legacy greetd command was not migrated"
  ! grep -Fqx -- "${legacy}" "${config}" || \
    fail "legacy greetd command survived migration"
  grep -Fxq 'user = "custom-greeter"' "${config}" || \
    fail "greetd migration discarded an unrelated customization"
  [[ "$(stat -c %a "${config}")" == 640 ]] || \
    fail "greetd migration changed config permissions"

  printf '%s\n' '[default_session]' 'command = "custom-session"' >"${untouched}"
  before="$(sha256sum "${untouched}")"
  (
    # shellcheck source=aurade-login.install
    source "${install_script}"
    _aurade_migrate_legacy_config "${untouched}"
  )
  after="$(sha256sum "${untouched}")"
  [[ "${before}" == "${after}" ]] || \
    fail "greetd migration changed a genuinely custom command"
}

bash -n "${supervisor}" "${session_control}" "${greetd_vt}"
test_default_command
test_cached_legacy_command_migrated
test_selected_command_restart_and_stop
test_failed_session_retries_before_greeter_return
test_empty_command_rejected
test_invalid_session_ids_rejected
test_symlink_state_rejected
test_session_scoped_pidfiles
test_unscoped_fallback_fails_closed
test_supervisor_crash_fails_closed
test_watchdog_drops_lock_fd
test_session_control_restarts_own_scope
test_greetd_config_consistency
test_legacy_config_migration

printf 'session supervisor test: PASS\n'
