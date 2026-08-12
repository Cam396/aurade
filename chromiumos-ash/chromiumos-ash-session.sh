#!/bin/bash
# Full Wayland session wrapper for display managers.
# Starts a kiosk compositor, then runs AuraDE as the only client.
set -e

export AURADE_OZONE_PLATFORM="${AURADE_OZONE_PLATFORM:-wayland}"
export XDG_SESSION_TYPE="${XDG_SESSION_TYPE:-wayland}"
export AURADE_ENABLE_WESTON_INPUT_SETTINGS="${AURADE_ENABLE_WESTON_INPUT_SETTINGS:-1}"

# AuraDE compatibility: fail before Weston paints a blank screen when the
# kernel exposed no DRM render node. This is common with VMware 3D disabled
# and otherwise looks exactly like a rejected password. Software rendering is
# available as an explicit diagnostic override, not as the silent default.
if [[ "${AURADE_ALLOW_SOFTWARE_RENDERER:-0}" != 1 ]]; then
    render_node_found=0
    render_node_usable=0
    if [[ ! -d /dev/dri ]]; then
        if [[ -x /usr/bin/aurade-session-error ]]; then
            /usr/bin/aurade-session-error missing-dri 'the /dev/dri directory is absent' || true
        else
            printf '%s\n' 'AuraDE cannot start: /dev/dri is absent.' >&2
        fi
        exit 78
    fi
    for render_node in /dev/dri/renderD*; do
        [[ -e "${render_node}" ]] || continue
        render_node_found=1
        if [[ -r "${render_node}" && -w "${render_node}" ]]; then
            render_node_usable=1
            break
        fi
    done
    if [[ "${render_node_usable}" == 0 ]]; then
        error_kind=missing-render
        [[ "${render_node_found}" == 1 ]] && error_kind=render-permission
        if [[ -x /usr/bin/aurade-session-error ]]; then
            /usr/bin/aurade-session-error "${error_kind}" \
                'render-node preflight failed' || true
        else
            printf '%s\n' \
                'AuraDE cannot start: no usable DRM render device was found.' >&2
        fi
        exit 78
    fi
fi

if [ -z "${XDG_RUNTIME_DIR:-}" ]; then
    export XDG_RUNTIME_DIR="/run/user/$(id -u)"
fi
if ! mkdir -p "${XDG_RUNTIME_DIR}" 2>/dev/null; then
    export XDG_RUNTIME_DIR="${TMPDIR:-/tmp}/aurade-runtime-$(id -u)"
    if ! mkdir -p "${XDG_RUNTIME_DIR}" 2>/dev/null; then
        [[ -x /usr/bin/aurade-session-error ]] && \
            /usr/bin/aurade-session-error runtime-dir 'runtime directory creation failed' || true
        exit 78
    fi
fi
if ! chmod 700 "${XDG_RUNTIME_DIR}" 2>/dev/null ||
   [[ ! -O "${XDG_RUNTIME_DIR}" ]]; then
    [[ -x /usr/bin/aurade-session-error ]] && \
        /usr/bin/aurade-session-error runtime-dir 'runtime directory is not user-owned' || true
    exit 78
fi

if ! command -v weston >/dev/null 2>&1; then
    [[ -x /usr/bin/aurade-session-error ]] && \
        /usr/bin/aurade-session-error missing-weston 'weston command not found' || true
    exit 78
fi

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
