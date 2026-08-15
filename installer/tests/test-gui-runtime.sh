#!/usr/bin/env bash
# The graphical installer, built and interrogated on a headless compositor.
#
# Everything else that tests this front end reads its source. That caught real
# bugs and missed a whole class of them: a widget tree can be assembled from
# correct calls in the correct order and still be wrong, because the toolkit
# has containment rules that only exist at runtime. The enum pickers shipped
# broken for exactly that reason.
#
# GTK needs a compositor to give a window a size, so one is started here. It is
# `weston --backend=headless`, which is the same shape as the `cage` the image
# actually ships - a Wayland compositor with a kiosk shell and one client - and
# it needs no GPU, no display and no seat. When it is not installed, the test
# skips rather than failing: the build host is not required to have it, and the
# source-level tests still run.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)

cleanup() {
  [[ -z ${WESTON_PID:-} ]] || kill "$WESTON_PID" 2>/dev/null || true
  rm -rf "$TMP"
}
trap cleanup EXIT

skip() { echo "installer GUI runtime test: SKIP ($1)"; exit 0; }

command -v python3 >/dev/null 2>&1 || skip 'python3 not available'
command -v weston >/dev/null 2>&1 || skip 'no headless compositor (weston)'
python3 - <<'PY' 2>/dev/null || skip 'GTK 4 and libadwaita are not usable here'
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: F401
PY

install -d "$TMP/zoneinfo/America" "$TMP/zoneinfo/Europe" "$TMP/locales" \
  "$TMP/keymaps/i386/qwerty" "$TMP/block/sda" "$TMP/block/nvme0n1" \
  "$TMP/dri" "$TMP/drm/renderD128/device" "$TMP/run" "$TMP/stub" \
  "$TMP/bundle" "$TMP/efi" "$TMP/nm" "$TMP/xdg"
: >"$TMP/zoneinfo/UTC"
for _zone in America/Chicago Europe/London Europe/Paris; do : >"$TMP/zoneinfo/$_zone"; done
for _locale in en_US en_GB fr_FR de_DE ja_JP; do : >"$TMP/locales/$_locale"; done
for _keymap in us uk fr de dvorak; do : >"$TMP/keymaps/i386/qwerty/$_keymap.map.gz"; done
: >"$TMP/dri/renderD128"
printf 'DRIVER=i915\n' >"$TMP/drm/renderD128/device/uevent"
printf 'MemAvailable:   16000000 kB\n' >"$TMP/meminfo"
printf '%s\n' \
  '/dev/nvme0n1|476.9G|Samsung SSD 980 PRO|nvme|S6B2NS0T900123X' \
  '/dev/sda|931.5G|WDC WD10EZEX|sata|WD-WCC6Y4KP1234' >"$TMP/disks"
printf '%s\n' '2026/07/12' >"$TMP/snapshot"
printf '#!/usr/bin/env bash\nprintf "stub engine\\n"\nexit 0\n' >"$TMP/stub-engine"
printf '#!/usr/bin/env bash\n[[ $* == *is-secure-boot* ]] && printf "disabled\\n"\nexit 0\n' \
  >"$TMP/stub/bootctl"
printf '#!/usr/bin/env bash\nexit 1\n' >"$TMP/stub/nmcli"
chmod +x "$TMP/stub-engine" "$TMP/stub/bootctl" "$TMP/stub/nmcli"

export PATH="$TMP/stub:$PATH"
export AURADE_ZONEINFO_DIR="$TMP/zoneinfo" AURADE_LOCALE_DIR="$TMP/locales"
export AURADE_KEYMAP_DIR="$TMP/keymaps" AURADE_BLOCK_DIR="$TMP/block"
export AURADE_DISK_TABLE="$TMP/disks" AURADE_PROBE_MEMINFO="$TMP/meminfo"
export AURADE_PROBE_DRM_DIR="$TMP/drm" AURADE_PROBE_DRI_DIR="$TMP/dri"
export AURADE_SNAPSHOT_FILE="$TMP/snapshot" AURADE_EFI_DIR="$TMP/efi"
export AURADE_INSTALL_ENGINE="$TMP/stub-engine" AURADE_BUNDLE_DIR="$TMP/bundle"
export AURADE_JOURNAL_PATH="$TMP/run/journal.jsonl"
export AURADE_JOURNAL_RAW="$TMP/run/install.log"
export AURADE_ASSET_DIR="$ROOT/installer/assets"
export AURADE_NM_PROFILE_DIR="$TMP/nm"
export XDG_RUNTIME_DIR="$TMP/xdg"
chmod 700 "$XDG_RUNTIME_DIR"
# No GPU, no session bus, no input method daemon and no accessibility bus on a
# build host. Each of these is a hang or a crash if GTK goes looking for it.
export GSK_RENDERER=cairo LIBGL_ALWAYS_SOFTWARE=1
export GTK_USE_PORTAL=0 GIO_USE_VFS=local GTK_A11Y=none NO_AT_BRIDGE=1
export GTK_IM_MODULE=gtk-im-context-simple
unset DBUS_SESSION_BUS_ADDRESS DISPLAY

weston --backend=headless --width=1280 --height=860 --shell=kiosk-shell.so \
  --socket=wl-aurade-test --idle-time=0 >"$TMP/weston.log" 2>&1 &
WESTON_PID=$!
for _ in $(seq 1 40); do
  [[ -S $XDG_RUNTIME_DIR/wl-aurade-test ]] && break
  sleep 0.25
done
[[ -S $XDG_RUNTIME_DIR/wl-aurade-test ]] || skip 'weston did not start here'
export WAYLAND_DISPLAY=wl-aurade-test

status=0
python3 "$ROOT/installer/tests/gui_runtime_test.py" || status=$?
exit "$status"
