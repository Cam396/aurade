#!/bin/bash
# Full Wayland session wrapper for display managers.
# Starts a kiosk compositor, then runs AuraDE as the only client.
set -e

export AURADE_OZONE_PLATFORM="${AURADE_OZONE_PLATFORM:-wayland}"
export XDG_SESSION_TYPE="${XDG_SESSION_TYPE:-wayland}"
export AURADE_ENABLE_WESTON_INPUT_SETTINGS="${AURADE_ENABLE_WESTON_INPUT_SETTINGS:-1}"

if [ -z "${XDG_RUNTIME_DIR:-}" ]; then
    export XDG_RUNTIME_DIR="/run/user/$(id -u)"
fi
if ! mkdir -p "${XDG_RUNTIME_DIR}" 2>/dev/null; then
    export XDG_RUNTIME_DIR="${TMPDIR:-/tmp}/aurade-runtime-$(id -u)"
    mkdir -p "${XDG_RUNTIME_DIR}"
fi
chmod 700 "${XDG_RUNTIME_DIR}" 2>/dev/null || true

WESTON_BACKEND="${AURADE_WESTON_BACKEND:-drm}"
WESTON_ARGS=(
    --backend="${WESTON_BACKEND}"
    --shell="${AURADE_WESTON_SHELL:-kiosk-shell.so}"
    --renderer="${AURADE_WESTON_RENDERER:-auto}"
    --socket="${AURADE_WESTON_SOCKET:-wayland-1}"
    --idle-time=0
)

if [ "${WESTON_BACKEND}" = "drm" ]; then
    WESTON_ARGS+=(--continue-without-input)
fi

if [ -z "${AURADE_WESTON_CONFIG:-}" ] && [ -r "${XDG_CONFIG_HOME:-${HOME}/.config}/weston.ini" ]; then
    AURADE_WESTON_CONFIG="${XDG_CONFIG_HOME:-${HOME}/.config}/weston.ini"
fi

if [ -n "${AURADE_WESTON_CONFIG:-}" ]; then
    WESTON_ARGS+=(--config="${AURADE_WESTON_CONFIG}")
else
    WESTON_ARGS+=(--no-config)
fi

SESSION_CHILD="${AURADE_SESSION_CHILD:-/usr/bin/chromiumos-ash-session-child}"

if command -v dbus-run-session >/dev/null 2>&1; then
    exec dbus-run-session -- weston "${WESTON_ARGS[@]}" -- "${SESSION_CHILD}" "$@"
fi

exec weston "${WESTON_ARGS[@]}" -- "${SESSION_CHILD}" "$@"
