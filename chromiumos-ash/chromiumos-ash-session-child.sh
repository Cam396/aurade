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
X11_BRIDGE_PID=""
AURADEFS_PID=""
AURADEFS_UNIT=""
EXO_SOCKET_NAME="${AURADE_EXO_SOCKET:-wayland-0}"
EXO_SOCKET_TIMEOUT="${AURADE_EXO_SOCKET_TIMEOUT:-10}"

# Record the original parent. The runtime check reads /proc because $PPID is
# updated by the shell.
PARENT_PID="${PPID:-0}"

report_session_failure() {
    local detail="$1"
    if [ -x "${SESSION_ERROR}" ]; then
        "${SESSION_ERROR}" compositor-failed "${detail}" || true
    else
        printf '%s\n' "AuraDE desktop session failed: ${detail}" >&2
    fi
}

# Wait for the outgoing Ash process to release its Wayland socket before a
# restart. Removing a live lock would break the current session.
# Stop if the supervisor disappears. A changed parent marks an orphaned session;
# a process already started under init is left alone.
parent_is_gone() {
    local now
    now="$(awk '{print $4}' "/proc/$$/stat" 2>/dev/null)" || return 1
    [ -n "${PARENT_PID}" ] && [ "${PARENT_PID}" != "0" ] && \
        [ "${PARENT_PID}" != "1" ] && [ "${now}" != "${PARENT_PID}" ]
}

# AuraDE: which process holds the socket lock, for the message below.
#
# Best effort and never load bearing. /proc/locks lists the pid in field 5 and
# major:minor:inode in field 6, so the inode from stat identifies the row. This
# is the lookup that had to be done by hand the first time this went wrong, and
# writing it down is most of the value: the log line "another compositor is
# running" is true and says nothing about which one.
exo_lock_holder() {
    local lock="$1" inode
    inode="$(stat -c %i "${lock}" 2>/dev/null)" || return 1
    [ -r /proc/locks ] || return 1
    awk -v ino="${inode}" \
        '$2 == "FLOCK" && $6 ~ (":" ino "$") { print $5; exit }' \
        /proc/locks 2>/dev/null
}

wait_for_exo_socket() {
    local runtime_dir="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
    local lock="${runtime_dir}/${EXO_SOCKET_NAME}.lock"
    [ -e "${lock}" ] || return 0
    command -v flock >/dev/null 2>&1 || return 0

    local waited=0
    while [ "${waited}" -lt "${EXO_SOCKET_TIMEOUT}" ]; do
        # Asking whether a flock is held means trying to take it; there is no
        # read-only form. It is dropped the moment this returns, and Ash does
        # not reach exo for about a second after launch, so the gap this opens
        # is not one anything can land in.
        if flock -n "${lock}" true 2>/dev/null; then
            return 0
        fi
        sleep 1
        waited="$((waited + 1))"
    done
    return 1
}

# AuraDE: X11 applications.
#
# exo, the display Linux applications open on, speaks Wayland only, so an
# application with no Wayland support started, found no display and exited.
# xwayland-satellite runs Xwayland as an ordinary exo client, each X11 window
# its own window with the desktop's frame, and the launcher hands applications
# the display it serves through AURADE_HOST_APP_X11_DISPLAY.
#
# The display is chosen once, before the first desktop starts, because Ash
# reads it from its environment. The bridge itself runs once per desktop: it
# is a client of that desktop's exo and ends with it, so the loop below
# starts one with every launch and stops it when the launch returns. In
# software rendering there is no exo, so there is nothing to bridge to.
X11_DISPLAY=""
pick_x11_display() {
    local number sockets="${AURADE_X11_SOCKET_DIR:-/tmp/.X11-unix}"
    local locks="${AURADE_X11_LOCK_DIR:-/tmp}"
    for number in $(seq 0 63); do
        if [ ! -e "${sockets}/X${number}" ] && [ ! -e "${locks}/.X${number}-lock" ]; then
            printf ':%s\n' "${number}"
            return 0
        fi
    done
    return 1
}
if [ "${AURADE_SOFTWARE_RENDERING:-0}" != "1" ] && \
        command -v xwayland-satellite >/dev/null 2>&1 && \
        X11_DISPLAY="$(pick_x11_display)"; then
    export AURADE_HOST_APP_X11_DISPLAY="${X11_DISPLAY}"
fi

# Waits for this desktop's exo socket, then serves X11 on it until stopped. A
# socket left by the previous desktop can be found first and refuse the
# connection, so a bridge that ends early is started again, a bounded number
# of times rather than in a tight loop.
# X11 applications read their settings from the X server, which comes up
# fresh with every bridge. AuraDE's defaults go first so the user's own
# ~/.Xresources, merged after them, wins. xrdb runs cpp unless told not to,
# and cpp is not always installed.
load_x11_resources() {
    command -v xrdb >/dev/null 2>&1 || return 0
    local x_socket="${AURADE_X11_SOCKET_DIR:-/tmp/.X11-unix}/X${X11_DISPLAY#:}"
    local waited=0 file
    while [ ! -S "${x_socket}" ] && [ "${waited}" -lt 40 ]; do
        sleep 0.25
        waited="$((waited + 1))"
    done
    [ -S "${x_socket}" ] || return 0
    for file in "${AURADE_X11_RESOURCES:-/usr/share/aurade/Xresources}" "${HOME}/.Xresources"; do
        [ -r "${file}" ] || continue
        DISPLAY="${X11_DISPLAY}" xrdb -merge "${file}" 2>/dev/null ||
            DISPLAY="${X11_DISPLAY}" xrdb -nocpp -merge "${file}" || true
    done
}

# GTK 4 and libadwaita read one stylesheet from the user's config and none
# from the system, so AuraDE's look reaches them through a file there that only
# imports the shared one, which updates with the package. An existing file is
# the user's and is left alone, an emptied one included, so clearing the
# import line is how to opt out.
link_gtk_style() {
    local style="${AURADE_GTK4_STYLE:-/usr/share/aurade/gtk-4.0/gtk.css}"
    local dir="${XDG_CONFIG_HOME:-${HOME}/.config}/gtk-4.0"
    # The desktop's colours, which Ash writes into the runtime directory when
    # it starts and again whenever they change. Imported after the style, so
    # libadwaita applications take Ash's surfaces in both light and dark.
    local colors="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/aurade/gtk-4.0/colors.css"
    local ours="@import url(\"file://${style}\");"
    local ours_colors="@import url(\"file://${colors}\");"
    [ -r "${style}" ] || return 0
    [ -L "${dir}/gtk.css" ] && return 0
    if [ -e "${dir}/gtk.css" ]; then
        # A file an earlier AuraDE wrote gets the colours line under its
        # style line; one without our line is the person's own and is left
        # alone.
        grep -qxF "${ours}" "${dir}/gtk.css" 2>/dev/null || return 0
        grep -qF "/aurade/gtk-4.0/colors.css" "${dir}/gtk.css" && return 0
        awk -v ours="${ours}" -v add="${ours_colors}" \
            '{ print } $0 == ours && !done { print add; done = 1 }' \
            "${dir}/gtk.css" >"${dir}/gtk.css.aurade-new" 2>/dev/null &&
            mv -f "${dir}/gtk.css.aurade-new" "${dir}/gtk.css" 2>/dev/null ||
            rm -f "${dir}/gtk.css.aurade-new" 2>/dev/null || true
        return 0
    fi
    mkdir -p "${dir}" 2>/dev/null || return 0
    printf '%s\n' \
        "/* Added by AuraDE so GTK apps match the desktop. Remove the lines below" \
        "   to opt out; anything else in this file is yours. */" \
        "${ours}" \
        "${ours_colors}" >"${dir}/gtk.css" 2>/dev/null || true
}

start_x11_bridge() {
    [ -n "${X11_DISPLAY}" ] || return 0
    local socket="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/${EXO_SOCKET_NAME}"
    (
        child=""
        # Waited for, so the bridge is gone, and its display free, before the
        # next desktop is started on it.
        trap '[ -n "${child}" ] && kill "${child}" 2>/dev/null && wait "${child}"; exit 0' TERM INT
        for attempt in $(seq 1 10); do
            waited=0
            while [ ! -S "${socket}" ] && [ "${waited}" -lt 120 ]; do
                sleep 0.5
                waited="$((waited + 1))"
            done
            [ -S "${socket}" ] || exit 0
            WAYLAND_DISPLAY="${EXO_SOCKET_NAME}" xwayland-satellite "${X11_DISPLAY}" &
            child="$!"
            load_x11_resources &
            wait "${child}"
            child=""
            sleep 2
        done
    ) >>"${AURADE_LOG_DIR:-/tmp}/xwayland-satellite.log" 2>&1 &
    X11_BRIDGE_PID="$!"
}

stop_x11_bridge() {
    [ -n "${X11_BRIDGE_PID}" ] || return 0
    kill "${X11_BRIDGE_PID}" 2>/dev/null || true
    wait "${X11_BRIDGE_PID}" 2>/dev/null || true
    X11_BRIDGE_PID=""
}

cleanup() {
    stop_x11_bridge
    if [ -n "${UDISKIE_PID}" ]; then
        kill "${UDISKIE_PID}" 2>/dev/null || true
        wait "${UDISKIE_PID}" 2>/dev/null || true
    fi
    if [ -n "${AURADEFS_PID}" ]; then
        kill "${AURADEFS_PID}" 2>/dev/null || true
        wait "${AURADEFS_PID}" 2>/dev/null || true
    fi
    if [ -n "${AURADEFS_UNIT}" ]; then
        systemctl --user stop "${AURADEFS_UNIT}" 2>/dev/null || true
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

# AuraDE: the file service behind the Files app. The app reads and changes
# the machine through it, on loopback, as this user; one per session, started
# before Ash so the app's first request is answered, and ended with the
# session. A missing binary is not an error here: the app says so itself, and
# the rest of the desktop is unharmed.
#
# Where there is a user service manager it runs as the packaged unit, because
# that is where Restart=on-failure, the journal and the unit's hardening are.
# The direct launch below is the same daemon without them, for a session that
# has no manager, or one that overrides the port: the unit pins 8902 because
# the page shipped in resources.pak asks for exactly that. Starting a unit is
# idempotent, so a manager that has already started it, now or in a future
# where something on this machine reaches graphical-session.target, does not
# make a second daemon fight the first for the port. Nothing here enables
# anything: the session owns the service's lifetime, both ends of it.
if command -v auradefs >/dev/null 2>&1; then
    if [ "${AURADE_FILES_PORT:-8902}" = "8902" ] && \
            command -v systemctl >/dev/null 2>&1 && \
            systemctl --user start auradefs.service 2>/dev/null; then
        AURADEFS_UNIT="auradefs.service"
    else
        AURADEFS_LOG="${AURADE_LOG_DIR:-${XDG_STATE_HOME:-${HOME}/.local/state}/aurade}"
        mkdir -p "${AURADEFS_LOG}" 2>/dev/null || AURADEFS_LOG="${TMPDIR:-/tmp}"
        auradefs --port "${AURADE_FILES_PORT:-8902}" \
            >>"${AURADEFS_LOG}/auradefs.log" 2>&1 &
        AURADEFS_PID="$!"
    fi
fi

# AuraDE: keep what the desktop says.
#
# Ash writes its diagnostics to stdout and stderr, and this session inherited
# /dev/tty1, so everything it reported went to a console the desktop covers and
# was then gone. A reboot request that failed left no trace anywhere on the
# machine: not in the journal, not in a file, nowhere. That is not a small
# inconvenience, it is the difference between a bug that can be read and a bug
# that has to be reproduced.
#
# The previous run is kept as .1, because the restart loop below would
# otherwise overwrite the log of the crash with the log of the restart that
# followed it, which is exactly the evidence worth having.
AURADE_LOG=""
AURADE_LOG_DIR="${XDG_STATE_HOME:-${HOME}/.local/state}/aurade"
AURADE_LOG_MAX_BYTES="${AURADE_LOG_MAX_BYTES:-67108864}"
if mkdir -p "${AURADE_LOG_DIR}" 2>/dev/null; then
    AURADE_LOG="${AURADE_LOG_DIR}/ash.log"
    if [ -f "${AURADE_LOG}" ]; then
        mv -f "${AURADE_LOG}" "${AURADE_LOG}.1" 2>/dev/null || AURADE_LOG=""
    fi
fi

SESSION_STARTED="$(date +%s)"
while :; do
    if parent_is_gone; then
        detail="the session that started this desktop is gone"
        echo "AuraDE: ${detail}; stopping rather than restarting into it." >&2
        if [ -n "${AURADE_LOG}" ]; then
            printf '=== AuraDE session orphaned %s: %s ===\n' \
                "$(date -Is 2>/dev/null || date)" "${detail}" \
                >>"${AURADE_LOG}" 2>/dev/null || true
        fi
        exit 0
    fi
    if ! wait_for_exo_socket; then
        # AuraDE: a lock still held after the wait means another compositor
        # owns this display, and starting would abort on a certainty.
        #
        # This used to start anyway, on the reasoning that no desktop is worse
        # than one more failed attempt. That reasoning was wrong, and it cost
        # two hundred and two aborted Ash launches over two and a quarter hours
        # on 2 Sep before anybody noticed, because nothing on screen changes
        # while it happens.
        #
        # It is wrong because the timeout cannot fire during an ordinary
        # restart. The flock belongs to the browser process, and this loop does
        # not reach here until the previous launch has returned, which is after
        # that process is gone and its lock with it. So the wait only fails when
        # somebody else holds the socket, and somebody else holding the socket
        # is not a condition that starting fixes.
        holder="$(exo_lock_holder "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/${EXO_SOCKET_NAME}.lock" 2>/dev/null || true)"
        detail="${EXO_SOCKET_NAME} is held by another compositor"
        [ -n "${holder}" ] && detail="${detail} (pid ${holder})"
        echo "AuraDE: ${detail}; not starting a second desktop." >&2
        if [ -n "${AURADE_LOG}" ]; then
            # Into the log as well as stderr, because stderr here goes wherever
            # the session manager sent it and the log is the file somebody
            # actually reads afterwards.
            printf '=== AuraDE session declined %s: %s ===\n' \
                "$(date -Is 2>/dev/null || date)" "${detail}" \
                >>"${AURADE_LOG}" 2>/dev/null || true
        fi
        # Zero, not a failure. This session has correctly decided it is the
        # spare, and reporting a compositor failure would put an error in front
        # of somebody whose desktop is working.
        exit 0
    fi
    START_TIME="$(date +%s)"
    link_gtk_style
    start_x11_bridge
    if [ -n "${AURADE_LOG}" ]; then
        # A desktop that logs its way through the disk is its own outage, so
        # roll over rather than grow without bound.
        LOG_BYTES="$(wc -c <"${AURADE_LOG}" 2>/dev/null || echo 0)"
        if [ "${LOG_BYTES}" -ge "${AURADE_LOG_MAX_BYTES}" ]; then
            mv -f "${AURADE_LOG}" "${AURADE_LOG}.1" 2>/dev/null || true
        fi
        printf '=== AuraDE desktop starting %s ===\n' "$(date -Is 2>/dev/null || date)" \
            >>"${AURADE_LOG}" 2>/dev/null || true
        "${CHROME_COMMAND}" "$@" >>"${AURADE_LOG}" 2>&1
        STATUS="$?"
    else
        "${CHROME_COMMAND}" "$@"
        STATUS="$?"
    fi
    stop_x11_bridge
    END_TIME="$(date +%s)"

    # AuraDE: a desktop that went away while its lock screen was up is not
    # started again, because it would come back unlocked. The session ends
    # instead, and the greeter asks for the password. The session manager
    # stand in keeps the marker, as root, from lock to unlock. One older than
    # this session was left by a session that ended locked, and the next
    # desktop to start clears it; it says nothing about this one.
    LOCK_MARKER="${AURADE_LOCK_STATE_DIR:-/run/aurade-lock}/$(id -u)"
    LOCK_TIME="$(stat -c %Y "${LOCK_MARKER}" 2>/dev/null || echo 0)"
    if [ -e "${LOCK_MARKER}" ] && [ "${LOCK_TIME}" -ge "${SESSION_STARTED}" ]; then
        echo "AuraDE: the desktop exited while locked; ending the session." >&2
        if [ -n "${AURADE_LOG}" ]; then
            printf '=== AuraDE desktop exited while locked %s; session ends ===\n' \
                "$(date -Is 2>/dev/null || date)" >>"${AURADE_LOG}" 2>/dev/null || true
        fi
        if [ -x "${AURADE_SESSION_CONTROL:-/usr/bin/aurade-session-control}" ]; then
            AURADE_SIGN_OUT_DETACHED=1 \
                "${AURADE_SESSION_CONTROL:-/usr/bin/aurade-session-control}" sign-out || true
        fi
        exit 0
    fi
    RUNTIME="$((END_TIME - START_TIME))"

    if [ "${AURADE_SESSION_ON_EXIT:-restart}" = "exit" ]; then
        if [ "${STATUS}" -ne 0 ]; then
            report_session_failure "desktop exited with status=${STATUS} runtime=${RUNTIME}s"
        fi
        exit "${STATUS}"
    fi

    # AuraDE: an abort counts however long the teardown took.
    #
    # The window is wall clock, and Ash aborting in two seconds still takes
    # about ninety to get its child processes out of the way, which is longer
    # than the window. So every attempt in a crash loop looked like a long
    # healthy session, the counter reset every time, and the five strike guard
    # below never fired once in two hundred and two attempts.
    #
    # 134 is SIGABRT, which is what a failed CHECK or DCHECK produces. It is
    # never how a healthy desktop exits, so it is safe to count on its own, and
    # narrow enough not to catch a logout, which arrives as a clean status or as
    # SIGTERM.
    if [ "${RUNTIME}" -lt "${FAST_RESTART_WINDOW}" ] || [ "${STATUS}" -eq 134 ]; then
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
