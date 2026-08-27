#!/usr/bin/env bash
# The greeter window, built and interrogated on a headless compositor.
#
# Same shape as the installer's runtime test, and for the same reason: a
# widget tree can be assembled from correct calls in the correct order and
# still be wrong, because containment and focus are runtime rules. The greeter
# inherits both hazards from the installer, including the one where focusing a
# list outlines the whole list and announces the word list to somebody who
# needed to hear a name.
set -Eeuo pipefail

HERE=$(cd -- "$(dirname -- "$0")" && pwd -P)
PACKAGE=$(cd -- "${HERE}/.." && pwd -P)
TMP=$(mktemp -d)

cleanup() {
  [[ -z ${WESTON_PID:-} ]] || kill "$WESTON_PID" 2>/dev/null || true
  rm -rf "$TMP"
}
trap cleanup EXIT

skip() { echo "greeter runtime test: SKIP ($1)"; exit 0; }

command -v python3 >/dev/null 2>&1 || skip 'python3 not available'
command -v weston >/dev/null 2>&1 || skip 'no headless compositor (weston)'

# No GPU, no session bus, no input method daemon and no accessibility bus on a
# build host. Each of these is a hang or a crash if GTK goes looking for it.
export GSK_RENDERER=cairo LIBGL_ALWAYS_SOFTWARE=1
export GTK_USE_PORTAL=0 GIO_USE_VFS=local GTK_A11Y=none NO_AT_BRIDGE=1
export GTK_IM_MODULE=gtk-im-context-simple
unset DBUS_SESSION_BUS_ADDRESS DISPLAY

# A broken or partially installed GI stack can block while probing a display
# backend instead of returning an import error. Never turn that into an
# unbounded run. The timeout is generous because a cold font cache on a slow
# filesystem is a one time cost that looks exactly like a hang.
timeout 120s python3 - <<'PY' 2>/dev/null || skip 'GTK 4 and libadwaita are not usable here'
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: F401
PY

install -d "$TMP/xdg" "$TMP/users" "$TMP/icons" "$TMP/state" "$TMP/sessions"
chmod 700 "$TMP/xdg"
cat >"$TMP/passwd" <<'EOF'
root:x:0:0:root:/root:/bin/bash
bin:x:1:1::/:/usr/bin/nologin
ada:x:1000:1000:Ada Lovelace,Room 4,555-0100:/home/ada:/bin/bash
grace:x:1001:1001:Grace Hopper:/home/grace:/bin/bash
EOF
printf 'UID_MIN 1000\nUID_MAX 60000\n' >"$TMP/login.defs"
cat >"$TMP/sessions/chromiumos-ash-wayland.desktop" <<'EOF'
[Desktop Entry]
Name=AuraDE
Exec=/usr/bin/chromiumos-ash-session
Type=Application
EOF

export XDG_RUNTIME_DIR="$TMP/xdg"
export AURADE_GREETER_PASSWD="$TMP/passwd"
export AURADE_GREETER_LOGIN_DEFS="$TMP/login.defs"
export AURADE_GREETER_SERVICE_DIR="$TMP/users"
export AURADE_GREETER_ICON_DIR="$TMP/icons"
export AURADE_GREETER_STATE="$TMP/state/last-user"
export AURADE_GREETER_SESSION_DIR="$TMP/sessions"
# Nothing in this test may restart or stop the machine running it.
export AURADE_GREETER_POWER_COMMAND="/bin/false"

# The weather, switched on, so the pill and the panel behind it are actually
# built and can be interrogated. The reading itself is written to the cache by
# the python side before any window exists, and a cache written a moment ago
# is fresh, so nothing here reaches the network. A runtime test that asked a
# weather service would fail on a build host with no route out, which is a
# test reporting on the machine rather than on the product.
cat >"$TMP/greeter.conf" <<'EOF'
weather = on
weather_place = Ardsley, NY
weather_latitude = 41.0126
weather_longitude = -73.8437
EOF
export AURADE_GREETER_CONF="$TMP/greeter.conf"
export AURADE_WEATHER_CACHE="$TMP/weather.json"

weston --backend=headless --width=1280 --height=860 --shell=kiosk-shell.so \
  --socket=wl-aurade-greeter --idle-time=0 >"$TMP/weston.log" 2>&1 &
WESTON_PID=$!
disown "$WESTON_PID" 2>/dev/null || true
for _ in $(seq 1 40); do
  [[ -S $XDG_RUNTIME_DIR/wl-aurade-greeter ]] && break
  sleep 0.25
done
[[ -S $XDG_RUNTIME_DIR/wl-aurade-greeter ]] || skip 'weston did not start here'
export WAYLAND_DISPLAY=wl-aurade-greeter

python3 "${PACKAGE}/tests/runtime_test.py"
