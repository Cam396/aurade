#!/bin/bash
# Child process supervised by the AuraDE Weston session.
# Keeps the desktop alive when Chrome/Ash exits for a shell restart.
set -u

RESTART_DELAY="${AURADE_RESTART_DELAY:-1}"
FAST_RESTART_WINDOW="${AURADE_FAST_RESTART_WINDOW:-60}"
MAX_FAST_RESTARTS="${AURADE_MAX_FAST_RESTARTS:-5}"
CHROME_COMMAND="${AURADE_CHROME_COMMAND:-/usr/bin/chromiumos-ash}"
SESSION_ERROR="${AURADE_SESSION_ERROR:-/usr/bin/aurade-session-error}"
FAST_RESTARTS=0
UDISKIE_PID=""

report_session_failure() {
    local detail="$1"
    if [ -x "${SESSION_ERROR}" ]; then
        "${SESSION_ERROR}" compositor-failed "${detail}" || true
    else
        printf '%s\n' "AuraDE desktop session failed: ${detail}" >&2
    fi
}

cleanup() {
    if [ -n "${UDISKIE_PID}" ]; then
        kill "${UDISKIE_PID}" 2>/dev/null || true
        wait "${UDISKIE_PID}" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

# AuraDE compatibility: Weston assigns WAYLAND_DISPLAY immediately before it
# launches this child. Publish that final environment to D-Bus activation and
# the user service manager so MIME handlers and desktop helpers are graphical.
export XDG_CURRENT_DESKTOP="${XDG_CURRENT_DESKTOP:-AuraDE}"
ACTIVATION_ENV=(XDG_CURRENT_DESKTOP XDG_SESSION_TYPE XDG_RUNTIME_DIR)
for variable in WAYLAND_DISPLAY DISPLAY DBUS_SESSION_BUS_ADDRESS; do
    [ -n "${!variable:-}" ] && ACTIVATION_ENV+=("${variable}")
done
if command -v dbus-update-activation-environment >/dev/null 2>&1; then
    dbus-update-activation-environment --systemd \
        "${ACTIVATION_ENV[@]}" 2>/dev/null || true
elif command -v systemctl >/dev/null 2>&1; then
    systemctl --user import-environment \
        "${ACTIVATION_ENV[@]}" 2>/dev/null || true
fi

# AuraDE compatibility: Chromium owns removable-media automounting through the
# host bridge. Keep udiskie only as an explicit recovery fallback so two
# independent automounters cannot race for the same UDisks device.
if [ "${AURADE_REMOVABLE_AUTOMOUNT:-0}" = "1" ] && \
        command -v udiskie >/dev/null 2>&1; then
    udiskie --automount --no-tray --no-notify &
    UDISKIE_PID="$!"
fi

while :; do
    START_TIME="$(date +%s)"
    "${CHROME_COMMAND}" "$@"
    STATUS="$?"
    END_TIME="$(date +%s)"
    RUNTIME="$((END_TIME - START_TIME))"

    if [ "${AURADE_SESSION_ON_EXIT:-restart}" = "exit" ]; then
        if [ "${STATUS}" -ne 0 ]; then
            report_session_failure "desktop exited with status=${STATUS} runtime=${RUNTIME}s"
        fi
        exit "${STATUS}"
    fi

    if [ "${RUNTIME}" -lt "${FAST_RESTART_WINDOW}" ]; then
        FAST_RESTARTS="$((FAST_RESTARTS + 1))"
    else
        FAST_RESTARTS=0
    fi

    if [ "${FAST_RESTARTS}" -ge "${MAX_FAST_RESTARTS}" ]; then
        detail="desktop exited ${FAST_RESTARTS} times quickly; last_status=${STATUS}"
        echo "AuraDE ${detail}; not restarting." >&2
        report_session_failure "${detail}"
        exit "${STATUS}"
    fi

    sleep "${RESTART_DELAY}"
done
