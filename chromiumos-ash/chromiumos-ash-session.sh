#!/bin/bash
# Full Wayland session wrapper for display managers.
# Starts a kiosk compositor, then runs AuraDE as the only client.
set -e

export AURADE_OZONE_PLATFORM="${AURADE_OZONE_PLATFORM:-wayland}"
export XDG_SESSION_TYPE="${XDG_SESSION_TYPE:-wayland}"
export AURADE_ENABLE_WESTON_INPUT_SETTINGS="${AURADE_ENABLE_WESTON_INPUT_SETTINGS:-1}"

WESTON_BACKEND="${AURADE_WESTON_BACKEND:-drm}"
SESSION_ERROR="${AURADE_SESSION_ERROR:-/usr/bin/aurade-session-error}"
DRI_DIR="${AURADE_DRI_DIR:-/dev/dri}"
SYSFS_DRM="${AURADE_SYSFS_DRM:-/sys/class/drm}"

# A render node with nothing behind it but software GL. virtio-gpu publishes
# one even when the host gives it no 3D, which is the default in several
# virtual machine managers. Mesa then has no driver for it, GBM cannot
# allocate the buffers Ash renders into, and Chrome's GPU process loses its
# context six times and takes the browser with it. Bit 0 of the virtio
# device's feature string is VIRTIO_GPU_F_VIRGL. Anything this cannot read is
# taken to have 3D, which is what the session assumed before it asked.
render_node_has_3d() {
    local device virtio driver
    device="$(readlink -f "${SYSFS_DRM}/${1##*/}/device" 2>/dev/null)" || return 0
    for virtio in "${device}"/virtio*; do
        [[ -r "${virtio}/features" ]] || continue
        driver="$(readlink -f "${virtio}/driver" 2>/dev/null)" || continue
        [[ "${driver##*/}" == virtio_gpu ]] || continue
        [[ "$(head -c 1 "${virtio}/features")" == 1 ]] || return 1
    done
    return 0
}

session_refuses() {
    local kind="$1" detail="$2" fallback="$3"
    if [[ -x "${SESSION_ERROR}" ]]; then
        "${SESSION_ERROR}" "${kind}" "${detail}" || true
    else
        printf '%s\n' "${fallback}" >&2
    fi
    exit 78
}

# AuraDE compatibility: decide how this desktop draws before Weston starts.
#
# A render node is the GPU. Without one, or with one that has no 3D behind
# it, the desktop still runs: Weston composites with pixman and Ash composites
# in software, which is how a virtual machine with no 3D, or a laptop whose
# graphics driver has none, gets a desktop instead of an error screen asking
# for hardware it does not have. It is slower, and it is not silent about it:
# the choice and its reason go to the journal and into the session
# environment, where the launcher reads it.
#
# What is still refused is what software cannot fix. With no /dev/dri there
# is no display device for the DRM backend to put a picture on at all. And a
# render node that exists but cannot be opened is a permissions fault on a
# machine that does have a GPU; drawing in software there would hide the fault
# behind a slower desktop, so it is reported instead.
#
# AURADE_ALLOW_SOFTWARE_RENDERER=0 restores the old rule of refusing whenever
# there is no GPU. AURADE_FORCE_SOFTWARE_RENDERING=1 draws in software even
# when there is one, for a GPU that is present and broken.
if [[ "${WESTON_BACKEND}" == drm && ! -d "${DRI_DIR}" ]]; then
    session_refuses missing-dri "the ${DRI_DIR} directory is absent" \
        "AuraDE cannot start: ${DRI_DIR} is absent."
fi
render_node_found=0
render_node_usable=0
render_node_no_3d=0
for render_node in "${DRI_DIR}"/renderD*; do
    [[ -e "${render_node}" ]] || continue
    render_node_found=1
    if ! render_node_has_3d "${render_node}"; then
        render_node_no_3d=1
        continue
    fi
    if [[ -r "${render_node}" && -w "${render_node}" ]]; then
        render_node_usable=1
        break
    fi
done
AURADE_SOFTWARE_RENDERING=0
software_reason='no usable GPU render device'
if [[ "${render_node_no_3d}" == 1 ]]; then
    software_reason='the GPU render device has no 3D behind it (virtio-gpu without virgl)'
fi
if [[ "${AURADE_FORCE_SOFTWARE_RENDERING:-0}" == 1 ]]; then
    AURADE_SOFTWARE_RENDERING=1
    software_reason='software rendering was asked for'
elif [[ "${render_node_usable}" == 0 ]]; then
    if [[ "${render_node_found}" == 1 && "${render_node_no_3d}" == 0 ]]; then
        session_refuses render-permission 'render-node preflight failed' \
            'AuraDE cannot start: the DRM render device cannot be opened.'
    elif [[ "${AURADE_ALLOW_SOFTWARE_RENDERER:-1}" == 1 ]]; then
        AURADE_SOFTWARE_RENDERING=1
    else
        session_refuses missing-render 'render-node preflight failed' \
            'AuraDE cannot start: no usable DRM render device was found.'
    fi
fi
export AURADE_SOFTWARE_RENDERING
if [[ "${AURADE_SOFTWARE_RENDERING}" == 1 ]]; then
    # An explicit renderer still wins, so a machine where software GL
    # composites better than pixman can say so in one variable.
    : "${AURADE_WESTON_RENDERER:=pixman}"
    if command -v logger >/dev/null 2>&1; then
        logger -t aurade-session -- \
            "${software_reason}; drawing the desktop in software (renderer=${AURADE_WESTON_RENDERER})" \
            2>/dev/null || true
    fi
fi

if [ -z "${XDG_RUNTIME_DIR:-}" ]; then
    XDG_RUNTIME_DIR="/run/user/$(id -u)"
    export XDG_RUNTIME_DIR
fi
if ! mkdir -p "${XDG_RUNTIME_DIR}" 2>/dev/null; then
    XDG_RUNTIME_DIR="${TMPDIR:-/tmp}/aurade-runtime-$(id -u)"
    export XDG_RUNTIME_DIR
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
