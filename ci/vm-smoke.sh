#!/bin/bash
# Live AuraDE VM smoke checks over SSH.
set -euo pipefail

VM_HOST="${AURADE_VM_HOST:-}"
VM_USER="${AURADE_VM_USER:-root}"
TEST_USER="${AURADE_TEST_USER:-auratest}"
EXPECTED_CHROME_SHA="${AURADE_EXPECTED_CHROME_SHA:-}"
REMOVABLE_AUTOMOUNT="${AURADE_REMOVABLE_AUTOMOUNT:-0}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
open_audio_settings=0
open_core_apps=0
files_volume_smoke=0
files_ops_smoke=0
files_archive_smoke=0
terminal_smoke=0
session_lifecycle_smoke=0
accessibility_smoke=0
release_package_smoke=0

usage() {
  cat <<'EOF'
Usage: ci/vm-smoke.sh [options]

Checks a running AuraDE VM over SSH. This script does not build Chromium and
does not launch/restart the desktop; it verifies the live session that is
already running.

Options:
  --host HOST              VM SSH host (required; or set AURADE_VM_HOST).
  --user USER              VM SSH user. Default: AURADE_VM_USER or root.
  --test-user USER         AuraDE desktop user. Default: AURADE_TEST_USER or auratest.
  --expected-chrome-sha S  Expected /usr/lib/chromiumos-ash/chrome SHA-256.
  --open-audio-settings    Open chrome://os-settings/audio through CDP and verify it.
  --open-core-apps         Open/verify Files, Diagnostics, Terminal, and Settings.
  --files-volume-smoke     Verify Files local_root volumes through CDP.
  --files-ops-smoke        Also exercise create/copy/rename/read/delete in
                           local_root:Downloads through the live Files page
                           (implies --files-volume-smoke).
  --files-archive-smoke    Extract/read/delete a tar archive through a Files
                           IO task (implies --files-volume-smoke).
  --terminal-smoke         Send a real shell command through the terminal app
                           and verify it executed as the desktop user.
  --session-lifecycle-smoke
                           Verify local account/session-manager lifecycle state.
  --accessibility-smoke    Exercise ChromeVox and Select-to-Speak through CDP
                           and require native Linux TTS utterances.
  --release-package-smoke  Verify current package versions/ownership,
                           removable-media services, and inert update_engine.
  -h, --help               Show this help.

Environment:
  AURADE_VM_HOST=<vm-address-or-hostname>
  AURADE_VM_USER=root
  AURADE_TEST_USER=auratest
  AURADE_EXPECTED_CHROME_SHA=<sha256>
  AURADE_VM_CHROME_LOG=<remote-log-path>  Optional Chrome log path for
                                --accessibility-smoke when stderr is a tty.
  AURADE_REMOVABLE_AUTOMOUNT=0  Expect Chromium/host-bridge automounting and
                                no user udiskie process. Set to 1 for the
                                explicit udiskie recovery fallback.
EOF
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --host)
      VM_HOST="$2"
      shift 2
      ;;
    --user)
      VM_USER="$2"
      shift 2
      ;;
    --test-user)
      TEST_USER="$2"
      shift 2
      ;;
    --expected-chrome-sha)
      EXPECTED_CHROME_SHA="$2"
      shift 2
      ;;
    --open-audio-settings)
      open_audio_settings=1
      shift
      ;;
    --open-core-apps)
      open_core_apps=1
      shift
      ;;
    --files-volume-smoke)
      files_volume_smoke=1
      shift
      ;;
    --files-ops-smoke)
      files_volume_smoke=1
      files_ops_smoke=1
      shift
      ;;
    --files-archive-smoke)
      files_volume_smoke=1
      files_archive_smoke=1
      shift
      ;;
    --terminal-smoke)
      terminal_smoke=1
      shift
      ;;
    --session-lifecycle-smoke)
      session_lifecycle_smoke=1
      shift
      ;;
    --accessibility-smoke)
      accessibility_smoke=1
      shift
      ;;
    --release-package-smoke)
      release_package_smoke=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "${VM_HOST}" ]]; then
  echo "Set AURADE_VM_HOST or pass --host HOST" >&2
  exit 2
fi

if [[ "${REMOVABLE_AUTOMOUNT}" != "0" &&
      "${REMOVABLE_AUTOMOUNT}" != "1" ]]; then
  echo "AURADE_REMOVABLE_AUTOMOUNT must be 0 or 1" >&2
  exit 2
fi

ssh_cmd=(ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8 "${VM_USER}@${VM_HOST}")

remote() {
  "${ssh_cmd[@]}" "$@"
}

require_remote() {
  local description="$1"
  shift
  echo "==> ${description}"
  remote "$@"
}

cdp_targets() {
  remote 'curl -fsS http://127.0.0.1:9222/json/list'
}

verify_cdp_target() {
  local label="$1"
  local url="$2"
  local title_regex="$3"
  local url_regex="$4"
  local targets

  echo "==> Checking ${label}"
  targets="$(cdp_targets)"
  if printf '%s\n' "${targets}" | grep -Eq "${url_regex}"; then
    echo "${label} is already open."
  elif [[ -n "${url}" ]]; then
    echo "Opening ${label}."
    if ! remote "curl -fsS -X PUT \"http://127.0.0.1:9222/json/new?${url}\" >/dev/null 2>/dev/null"; then
      echo "CDP new-target request failed; checking whether ${label} opened anyway."
    fi
    sleep 2
    targets="$(cdp_targets)"
  else
    echo "${label} is not open and no launch URL was provided." >&2
    printf '%s\n' "${targets}" >&2
    exit 1
  fi

  if ! printf '%s\n' "${targets}" | grep -Eq "${url_regex}"; then
    echo "CDP target URL check failed for ${label}" >&2
    printf '%s\n' "${targets}" >&2
    exit 1
  fi
  if [[ -n "${title_regex}" ]] && ! printf '%s\n' "${targets}" | grep -Eq "${title_regex}"; then
    echo "CDP target title check failed for ${label}" >&2
    printf '%s\n' "${targets}" >&2
    exit 1
  fi
  printf '%s\n' "${targets}" | grep -E "${url_regex}" | head -4
  if [[ -n "${title_regex}" ]]; then
    printf '%s\n' "${targets}" | grep -E "${title_regex}" | head -4
  fi
}

echo "AuraDE VM smoke target: ${VM_USER}@${VM_HOST} (${TEST_USER})"

require_remote "VM reachable" 'date'

chrome_sha="$(remote "sha256sum /usr/lib/chromiumos-ash/chrome | awk '{print \$1}'")"
echo "Chrome SHA-256: ${chrome_sha}"
if [[ -n "${EXPECTED_CHROME_SHA}" && "${chrome_sha}" != "${EXPECTED_CHROME_SHA}" ]]; then
  echo "Expected Chrome SHA-256 ${EXPECTED_CHROME_SHA}, got ${chrome_sha}" >&2
  exit 1
fi

require_remote "AuraDE package state" \
  'pacman -Q aurade chromiumos-ash pipewire wireplumber pipewire-pulse 2>/dev/null'

require_remote "Chrome login-manager process" \
  'pgrep -a -f "^/usr/lib/chromiumos-ash/chrome --login-manager"'

if [[ "${release_package_smoke}" == "1" ]]; then
  expected_package_file="${AURADE_EXPECTED_PACKAGES_FILE:-${SCRIPT_DIR}/../installer/expected-packages.txt}"
  [[ -r "${expected_package_file}" ]] || {
    echo "Expected package list is unreadable: ${expected_package_file}" >&2
    exit 1
  }
  mapfile -t release_packages < <(
    sed -E '/^[[:space:]]*(#|$)/d; s/[[:space:]]+$//' "${expected_package_file}"
  )
  ((${#release_packages[@]} > 0)) || {
    echo "Expected package list is empty: ${expected_package_file}" >&2
    exit 1
  }
  for package_dir in "${release_packages[@]}"; do
    pkgver="$(awk -F= '$1 == "pkgver" { print $2; exit }' \
      "${REPO_ROOT}/${package_dir}/PKGBUILD")"
    pkgrel="$(awk -F= '$1 == "pkgrel" { print $2; exit }' \
      "${REPO_ROOT}/${package_dir}/PKGBUILD")"
    actual_version="$(remote "pacman -Q '${package_dir}' | awk '{print \$2}'")"
    if [[ "${actual_version}" != "${pkgver}-${pkgrel}" ]]; then
      echo "${package_dir}: expected ${pkgver}-${pkgrel}, got ${actual_version}" >&2
      exit 1
    fi
  done
  require_remote "AuraDE package ownership and integrity" \
    "pacman -Qk aurade-account-helper aurade-system-helper shill-nm-adapter aurade-power aurade-host-bridge chromiumos-ash aurade-login aurade-ai aurade-webapp-shortcuts aurade aurade-full > /tmp/aurade-package-audit && ! grep -Eq ', [1-9][0-9]* missing files' /tmp/aurade-package-audit && pacman -Qo /usr/bin/aurade /usr/bin/aurade-power-status /usr/bin/aurade-hostctl /usr/bin/aurade-session-control /usr/lib/chromiumos-ash/chrome >/dev/null"
  removable_media_check="runuser -u '${TEST_USER}' -- udisksctl status >/dev/null && systemctl is-active --quiet udisks2.service && systemctl is-active --quiet aurade-host-bridge.service && test -d /run/media"
  if [[ "${REMOVABLE_AUTOMOUNT}" == "1" ]]; then
    removable_media_check+=" && pacman -Qo /usr/bin/udiskie >/dev/null && pgrep -u '${TEST_USER}' -x udiskie >/dev/null"
  else
    removable_media_check+=" && ! pgrep -u '${TEST_USER}' -x udiskie >/dev/null"
  fi
  require_remote "Removable-media session integration" \
    "${removable_media_check}"
  require_remote "Archive extraction runtime" \
    "command -v tar gzip bzip2 xz zstd lzip 7z unrar >/dev/null"
  require_remote "ChromeOS update engine is inert" \
    "! pgrep -x update_engine >/dev/null && ! systemctl cat update_engine.service >/dev/null 2>&1"
fi

if [[ "${session_lifecycle_smoke}" == "1" ]]; then
  local_account="${TEST_USER}@local.aurade"

  require_remote "AuraDE local-account command line" \
    "tr '\0' '\n' </proc/\$(pgrep -f '^/usr/lib/chromiumos-ash/chrome --login-manager' | head -1)/cmdline | grep -q -- '--aurade-enable-local-accounts' && ! tr '\0' '\n' </proc/\$(pgrep -f '^/usr/lib/chromiumos-ash/chrome --login-manager' | head -1)/cmdline | grep -E -- '--stub-auth|--stub-config'"

  require_remote "SessionManager shim service" \
    "test -x /usr/lib/chromiumos-ash/aurade-session-manager-shim.py && systemctl is-active --quiet aurade-session-manager.service"

  require_remote "SessionManager active local session" \
    "busctl --system call org.chromium.SessionManager /org/chromium/SessionManager org.chromium.SessionManagerInterface RetrieveSessionState | grep -q 's \"started\"' && busctl --system call org.chromium.SessionManager /org/chromium/SessionManager org.chromium.SessionManagerInterface RetrievePrimarySession | grep -q '${local_account}' && busctl --system call org.chromium.SessionManager /org/chromium/SessionManager org.chromium.SessionManagerInterface RetrieveActiveSessions | grep -q '${local_account}'"

  require_remote "AuraDE local profile state" \
    "runuser -u '${TEST_USER}' -- python3 - <<'PY'
import json
from pathlib import Path
profile = json.loads(Path.home().joinpath('.config/aurade/profile.json').read_text())
local_state = Path.home().joinpath('.local/share/aurade/chromiumos-ash/Local State').read_text()
assert profile.get('account_id') == '${local_account}', profile
assert profile.get('linux_username') == '${TEST_USER}', profile
assert '${local_account}' in local_state
assert 'cam@example.com' not in local_state
PY"
fi

echo "==> Chrome DevTools protocol"
remote 'curl -fsS http://127.0.0.1:9222/json/version' | \
  grep -E '"Browser"|"webSocketDebuggerUrl"'

if [[ "${open_audio_settings}" == "1" ]]; then
  verify_cdp_target \
    "Audio Settings" \
    "chrome://os-settings/audio" \
    '"title": "Settings' \
    '"url": "chrome://os-settings/audio"'
fi

if [[ "${open_core_apps}" == "1" ]]; then
  verify_cdp_target \
    "Files" \
    "chrome://file-manager/" \
    '"title": "Files' \
    '"url": "chrome://file-manager/'
  verify_cdp_target \
    "Diagnostics" \
    "chrome://diagnostics/" \
    '' \
    '"url": "chrome://diagnostics/'
  verify_cdp_target \
    "Settings" \
    "chrome://settings/" \
    '"title": "Settings' \
    '"url": "chrome://settings/'
  verify_cdp_target \
    "Terminal" \
    "chrome-untrusted://terminal/html/terminal.html" \
    '"title": ".*@.*:.*"' \
    '"url": "chrome-untrusted://terminal/html/terminal.html"'
fi

if [[ "${files_volume_smoke}" == "1" ]]; then
  echo "==> Files local-root volumes"
  files_smoke_args="--test-user '${TEST_USER}'"
  if [[ "${files_ops_smoke}" == "1" ]]; then
    files_smoke_args+=" --file-ops-smoke"
  fi
  if [[ "${files_archive_smoke}" == "1" ]]; then
    files_smoke_args+=" --archive-smoke"
  fi
  "${ssh_cmd[@]}" "python3 - ${files_smoke_args}" < ci/files-cdp-smoke.py
fi

if [[ "${terminal_smoke}" == "1" ]]; then
  echo "==> Terminal shell round-trip"
  "${ssh_cmd[@]}" "python3 - --test-user '${TEST_USER}'" < ci/terminal-cdp-smoke.py
fi

if [[ "${accessibility_smoke}" == "1" ]]; then
  verify_cdp_target "Accessibility Settings" \
    "chrome://os-settings/osAccessibility" "Settings" \
    '"url": "chrome://os-settings/'
  echo "==> ChromeVox and Select-to-Speak"
  remote "cat > /tmp/aurade-accessibility-cdp-smoke.py" \
    < "$(dirname "$0")/accessibility-cdp-smoke.py"
  remote "chmod 755 /tmp/aurade-accessibility-cdp-smoke.py"
  chrome_pid="$(remote \
    "pgrep -o -f '^/usr/lib/chromiumos-ash/chrome --login-manager'")"
  if [[ -n "${AURADE_VM_CHROME_LOG:-}" ]]; then
    chrome_log="${AURADE_VM_CHROME_LOG}"
  else
    chrome_log="$(remote "readlink /proc/${chrome_pid}/fd/2")"
  fi
  remote "python3 /tmp/aurade-accessibility-cdp-smoke.py \
    --chrome-log '${chrome_log}'"
fi

echo "==> PipeWire graph"
remote "uid=\$(id -u '${TEST_USER}'); runuser -u '${TEST_USER}' -- env XDG_RUNTIME_DIR=/run/user/\${uid} DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/\${uid}/bus wpctl status" | \
  grep -E 'chrome|Chromium input|Sinks:|Sources:|Audio' || {
    echo "PipeWire graph did not show expected Chrome/audio entries" >&2
    exit 1
  }

echo "==> AuraDE audio helper"
audio_json="$(remote "uid=\$(id -u '${TEST_USER}'); runuser -u '${TEST_USER}' -- env XDG_RUNTIME_DIR=/run/user/\${uid} DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/\${uid}/bus aurade-audio status-json")"
printf '%s\n' "${audio_json}" | grep -q '"backend": "pipewire-pulse"'
printf '%s\n' "${audio_json}" | grep -q '"direction": "output"'
printf '%s\n' "${audio_json}" | grep -q '"direction": "input"'
printf '%s\n' "${audio_json}" | grep -E '"backend"|"direction"|"description"'

echo "VM smoke passed"
