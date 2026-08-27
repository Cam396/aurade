#!/usr/bin/env bash
# Render the greeter on a headless compositor, for design review.
set -Eeuo pipefail
HERE=$(cd -- "$(dirname -- "$0")" && pwd -P)
PACKAGE=$(cd -- "${HERE}/.." && pwd -P)
TMP=$(mktemp -d)
cleanup() { [[ -z ${WESTON_PID:-} ]] || kill "$WESTON_PID" 2>/dev/null || true; rm -rf "$TMP"; }
trap cleanup EXIT

export GSK_RENDERER=cairo LIBGL_ALWAYS_SOFTWARE=1
export GTK_USE_PORTAL=0 GIO_USE_VFS=local GTK_A11Y=none NO_AT_BRIDGE=1
export GTK_IM_MODULE=gtk-im-context-simple
unset DBUS_SESSION_BUS_ADDRESS DISPLAY

install -d "$TMP/xdg" "$TMP/users" "$TMP/icons" "$TMP/state" "$TMP/sessions" "$TMP/power"
chmod 700 "$TMP/xdg"
cat >"$TMP/passwd" <<'EOF'
root:x:0:0:root:/root:/bin/bash
ada:x:1000:1000:Ada Lovelace,,,:/home/ada:/bin/bash
grace:x:1001:1001:Grace Hopper:/home/grace:/bin/bash
kate:x:1002:1002:Katherine Johnson:/home/kate:/bin/bash
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
export AURADE_GREETER_POWER_COMMAND="/bin/false"
export AURADE_POWER_DIR="$TMP/power"
# The pictures, so the screenshot shows the product rather than the
# fallback the product draws when it cannot find them.
AURADE_WALLPAPER_DIR="${AURADE_WALLPAPER_DIR:-${PACKAGE}/../installer/wallpapers}"
export AURADE_WALLPAPER_DIR
export AURADE_SHOT_DIR="${AURADE_SHOT_DIR:-/mnt/build/aurade-work/private-docs/greeter-shot}"
# The weather, switched on and pointed at somewhere with weather in it. The
# reading itself is written to the cache by the python side, so this render
# never touches the network and looks the same on a machine with no network
# at all.
cat >"$TMP/greeter.conf" <<'EOF'
weather = on
weather_place = Ardsley, NY
weather_latitude = 41.0126
weather_longitude = -73.8437
weather_units = c
EOF
export AURADE_GREETER_CONF="$TMP/greeter.conf"
export AURADE_WEATHER_CACHE="$TMP/weather.json"

# Two passes, because one of these pictures does not fit on a screen.
#
# The login screen itself is shot at a laptop's size, which is the whole point
# of looking at it. The weather panel is taller than any screen it will ever
# open on, which is what the scroller inside it is for, and a popover cannot
# be allocated taller than the window holding it. So the part under the fold
# is shot again on a compositor tall enough to hold all of it.
shots() {
  local height=$1 socket=$2 set=$3
  weston --backend=headless --width=1280 --height="$height" \
    --shell=kiosk-shell.so --socket="$socket" --idle-time=0 \
    >"$TMP/weston-${set}.log" 2>&1 &
  WESTON_PID=$!
  disown "$WESTON_PID" 2>/dev/null || true
  for _ in $(seq 1 40); do
    [[ -S $XDG_RUNTIME_DIR/$socket ]] && break
    sleep 0.25
  done
  [[ -S $XDG_RUNTIME_DIR/$socket ]] || { echo "weston did not start" >&2; return 1; }
  WAYLAND_DISPLAY="$socket" AURADE_SHOT_SET="$set" \
    python3 "${PACKAGE}/tools/capture-screens.py"
  kill "$WESTON_PID" 2>/dev/null || true
  WESTON_PID=
}

shots 860 wl-aurade-shots screens
shots 1600 wl-aurade-tall weather-full
