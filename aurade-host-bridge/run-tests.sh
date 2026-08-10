#!/bin/bash
set -euo pipefail

root_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="${root_dir}"

python -m py_compile \
  "${root_dir}/aurade_host_bridge_core.py" \
  "${root_dir}/aurade_host_bridge.py" \
  "${root_dir}/aurade_desktop_bridge.py" \
  "${root_dir}/aurade_hostctl.py"
python -m unittest discover -s "${root_dir}/tests" -v
"${root_dir}/aurade_hostctl.py" --dry-run bluetooth pair AA:BB:CC:DD:EE:FF >/dev/null
"${root_dir}/aurade_hostctl.py" --dry-run storage format \
  /org/freedesktop/UDisks2/block_devices/sdb1 ext4 \
  --label TEST --confirm 'FORMAT /dev/sdb1' >/dev/null
"${root_dir}/aurade_hostctl.py" --dry-run pacman uninstall test-package >/dev/null

if command -v dbus-run-session >/dev/null && command -v gdbus >/dev/null; then
  export AURADE_TEST_ROOT="${root_dir}"
  # Variables are expanded by the inner shell.
  # shellcheck disable=SC2016
  env -u XDG_RUNTIME_DIR dbus-run-session -- bash -c '
    "${AURADE_TEST_ROOT}/aurade_desktop_bridge.py" >/tmp/aurade-desktop-bridge-test.log 2>&1 &
    service_pid=$!
    trap "kill ${service_pid} 2>/dev/null || true" EXIT
    sleep 0.5
    gdbus call --session --dest org.aurade.DesktopBridge \
      --object-path /org/aurade/DesktopBridge \
      --method org.aurade.DesktopBridge1.MimeOpen relative.txt
  ' | grep -q 'invalid_argument'
  # shellcheck disable=SC2016
  env -u XDG_RUNTIME_DIR dbus-run-session -- bash -c '
    python -c "import dbus, aurade_host_bridge as bridge; bridge.dbus.SystemBus = dbus.SessionBus; raise SystemExit(bridge.main())" >/tmp/aurade-host-bridge-test.log 2>&1 &
    service_pid=$!
    trap "kill ${service_pid} 2>/dev/null || true" EXIT
    sleep 0.5
    gdbus call --session --dest org.aurade.HostBridge \
      --object-path /org/aurade/HostBridge \
      --method org.aurade.HostBridge1.GetCapabilities
  ' | grep -q '"operation":"capabilities"'
fi
