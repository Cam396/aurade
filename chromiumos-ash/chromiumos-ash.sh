#!/bin/bash
# Launcher for ChromiumOS Ash desktop on Linux.
# Runs as the calling user with data stored in their home directory.
#
# Usage:
#   chromiumos-ash                 # interactive session (login manager)
#   chromiumos-ash --login-manager # same as above
#   chromiumos-ash --guest-session # skip sign-in, go straight to guest mode
set -e

CHROME="${AURADE_CHROME:-/usr/lib/chromiumos-ash/chrome}"
CHROME_SANDBOX="${AURADE_CHROME_SANDBOX:-/usr/lib/chromiumos-ash/chrome-sandbox}"
FEATURES_CONF="${AURADE_FEATURES_CONF:-/etc/aurade/features.conf}"
GOOGLE_API_CONF="${AURADE_GOOGLE_API_CONF:-/etc/aurade/google-api.conf}"

AURADE_EXPOSE_SYSTEM_VOLUMES="${AURADE_EXPOSE_SYSTEM_VOLUMES:-0}"
AURADE_DISABLE_SANDBOX="${AURADE_DISABLE_SANDBOX:-0}"
AURADE_OZONE_PLATFORM="${AURADE_OZONE_PLATFORM:-}"
AURADE_DEV_STUB_OOBE="${AURADE_DEV_STUB_OOBE:-0}"
AURADE_ENABLE_LOCAL_ACCOUNTS="${AURADE_ENABLE_LOCAL_ACCOUNTS:-1}"
AURADE_ASH_HOST_WINDOW_BOUNDS="${AURADE_ASH_HOST_WINDOW_BOUNDS:-}"
AURADE_DISPLAY_SCALE="${AURADE_DISPLAY_SCALE:-}"
AURADE_FEATURE_PROFILE="${AURADE_FEATURE_PROFILE:-}"
AURADE_LOCAL_AI_BACKEND="${AURADE_LOCAL_AI_BACKEND:-}"
AURADE_LOCAL_AI_MODEL="${AURADE_LOCAL_AI_MODEL:-}"
AURADE_LOCAL_AI_ENDPOINT="${AURADE_LOCAL_AI_ENDPOINT:-}"
AURADE_LOCAL_AI_EMBED_MODEL="${AURADE_LOCAL_AI_EMBED_MODEL:-}"
AURADE_LOCAL_AI_EMBED_DIM="${AURADE_LOCAL_AI_EMBED_DIM:-}"
AURADE_LOCAL_AI_BOOTSTRAP="${AURADE_LOCAL_AI_BOOTSTRAP:-1}"
AURADE_LOCAL_AI_AUTO_DOWNLOAD="${AURADE_LOCAL_AI_AUTO_DOWNLOAD:-}"
AURADE_DISABLE_CHROMEVOX_HINT_TIMER="${AURADE_DISABLE_CHROMEVOX_HINT_TIMER:-1}"
AURADE_CHROME_EXTRA_FLAGS="${AURADE_CHROME_EXTRA_FLAGS:-}"
AURADE_GOOGLE_API_CONF="${AURADE_GOOGLE_API_CONF:-${GOOGLE_API_CONF}}"
AURADE_SKIP_SHILL_CHECK="${AURADE_SKIP_SHILL_CHECK:-0}"
AURADE_USE_HOST_POWER_STATUS="${AURADE_USE_HOST_POWER_STATUS:-1}"
AURADE_ENABLE_PIPEWIRE_AUDIO="${AURADE_ENABLE_PIPEWIRE_AUDIO:-1}"
AURADE_ENABLE_LOCAL_AMBIENT_BACKEND="${AURADE_ENABLE_LOCAL_AMBIENT_BACKEND:-1}"
AURADE_SKIP_CHAPS_KEY_PERMISSION_UPDATES="${AURADE_SKIP_CHAPS_KEY_PERMISSION_UPDATES:-1}"
AURADE_DISABLE_EXTERNAL_METRICS="${AURADE_DISABLE_EXTERNAL_METRICS:-1}"
AURADE_STRUCTURED_METRICS_DIR="${AURADE_STRUCTURED_METRICS_DIR:-}"
AURADE_PERFETTO_DIR="${AURADE_PERFETTO_DIR:-}"
AURADE_DISABLE_SAMPLE_SYSTEM_WEB_APP="${AURADE_DISABLE_SAMPLE_SYSTEM_WEB_APP:-1}"
AURADE_DISABLE_CHROMEOS_CONNECTED_DEVICE_FEATURES="${AURADE_DISABLE_CHROMEOS_CONNECTED_DEVICE_FEATURES:-1}"
AURADE_DISABLE_ARC_FEATURES="${AURADE_DISABLE_ARC_FEATURES:-1}"
AURADE_USE_FLOSS_STUBS="${AURADE_USE_FLOSS_STUBS:-1}"
AURADE_ALLOW_GPU_COMPOSITING_FALLBACK="${AURADE_ALLOW_GPU_COMPOSITING_FALLBACK:-1}"
AURADE_ENABLE_WEB_SESSION_BRIDGE="${AURADE_ENABLE_WEB_SESSION_BRIDGE:-1}"
AURADE_WEB_SESSION_REMOTE_DEBUGGING_PORT="${AURADE_WEB_SESSION_REMOTE_DEBUGGING_PORT:-9222}"
AURADE_ENABLE_SPEECH_DISPATCHER="${AURADE_ENABLE_SPEECH_DISPATCHER:-1}"

if [ -r "${FEATURES_CONF}" ]; then
    # shellcheck source=/dev/null
    . "${FEATURES_CONF}"
fi

if [ "${AURADE_DISABLE_SANDBOX}" != "1" ] && \
    [ -x "${CHROME_SANDBOX}" ] && \
    [ -z "${CHROME_DEVEL_SANDBOX:-}" ]; then
    export CHROME_DEVEL_SANDBOX="${CHROME_SANDBOX}"
fi

# --- Drop root to the original user ---------------------------------
if [ "$(id -u)" -eq 0 ]; then
    REAL_USER="${SUDO_USER:-$(logname 2>/dev/null)}"
    if [ -z "${REAL_USER}" ]; then
        echo "ERROR: Running as root but cannot determine the original user."
        echo "       Run this script as a regular user instead."
        exit 1
    fi
    REAL_HOME="$(getent passwd "${REAL_USER}" | cut -d: -f6)"
    # Re-exec as the real user with preserved environment
    exec runuser -u "${REAL_USER}" -- env \
        DISPLAY="${DISPLAY:-}" \
        WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-}" \
        XDG_SESSION_TYPE="${XDG_SESSION_TYPE:-}" \
        XDG_RUNTIME_DIR="/run/user/$(id -u "${REAL_USER}")" \
        DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-}" \
        CHROME_DEVEL_SANDBOX="${CHROME_DEVEL_SANDBOX:-}" \
        AURADE_CHROME="${CHROME}" \
        AURADE_CHROME_SANDBOX="${CHROME_SANDBOX}" \
        AURADE_FEATURES_CONF="${FEATURES_CONF}" \
        AURADE_GOOGLE_API_CONF="${AURADE_GOOGLE_API_CONF}" \
        AURADE_EXPOSE_SYSTEM_VOLUMES="${AURADE_EXPOSE_SYSTEM_VOLUMES}" \
        AURADE_DISABLE_SANDBOX="${AURADE_DISABLE_SANDBOX}" \
        AURADE_OZONE_PLATFORM="${AURADE_OZONE_PLATFORM}" \
        AURADE_DEV_STUB_OOBE="${AURADE_DEV_STUB_OOBE}" \
        AURADE_ENABLE_LOCAL_ACCOUNTS="${AURADE_ENABLE_LOCAL_ACCOUNTS}" \
        AURADE_ASH_HOST_WINDOW_BOUNDS="${AURADE_ASH_HOST_WINDOW_BOUNDS}" \
        AURADE_DISPLAY_SCALE="${AURADE_DISPLAY_SCALE}" \
        AURADE_FEATURE_PROFILE="${AURADE_FEATURE_PROFILE}" \
        AURADE_LOCAL_AI_BACKEND="${AURADE_LOCAL_AI_BACKEND}" \
        AURADE_LOCAL_AI_MODEL="${AURADE_LOCAL_AI_MODEL}" \
        AURADE_LOCAL_AI_ENDPOINT="${AURADE_LOCAL_AI_ENDPOINT}" \
        AURADE_LOCAL_AI_EMBED_MODEL="${AURADE_LOCAL_AI_EMBED_MODEL}" \
        AURADE_LOCAL_AI_EMBED_DIM="${AURADE_LOCAL_AI_EMBED_DIM}" \
        AURADE_LOCAL_AI_BOOTSTRAP="${AURADE_LOCAL_AI_BOOTSTRAP}" \
        AURADE_LOCAL_AI_AUTO_DOWNLOAD="${AURADE_LOCAL_AI_AUTO_DOWNLOAD}" \
        AURADE_DISABLE_CHROMEVOX_HINT_TIMER="${AURADE_DISABLE_CHROMEVOX_HINT_TIMER}" \
        AURADE_CHROME_EXTRA_FLAGS="${AURADE_CHROME_EXTRA_FLAGS}" \
        AURADE_SKIP_SHILL_CHECK="${AURADE_SKIP_SHILL_CHECK}" \
        AURADE_USE_HOST_POWER_STATUS="${AURADE_USE_HOST_POWER_STATUS}" \
        AURADE_ENABLE_PIPEWIRE_AUDIO="${AURADE_ENABLE_PIPEWIRE_AUDIO}" \
        AURADE_ENABLE_LOCAL_AMBIENT_BACKEND="${AURADE_ENABLE_LOCAL_AMBIENT_BACKEND}" \
        AURADE_SKIP_CHAPS_KEY_PERMISSION_UPDATES="${AURADE_SKIP_CHAPS_KEY_PERMISSION_UPDATES}" \
        AURADE_DISABLE_EXTERNAL_METRICS="${AURADE_DISABLE_EXTERNAL_METRICS}" \
        AURADE_STRUCTURED_METRICS_DIR="${AURADE_STRUCTURED_METRICS_DIR}" \
        AURADE_PERFETTO_DIR="${AURADE_PERFETTO_DIR}" \
        AURADE_DISABLE_SAMPLE_SYSTEM_WEB_APP="${AURADE_DISABLE_SAMPLE_SYSTEM_WEB_APP}" \
        AURADE_DISABLE_CHROMEOS_CONNECTED_DEVICE_FEATURES="${AURADE_DISABLE_CHROMEOS_CONNECTED_DEVICE_FEATURES}" \
        AURADE_DISABLE_ARC_FEATURES="${AURADE_DISABLE_ARC_FEATURES}" \
        AURADE_USE_FLOSS_STUBS="${AURADE_USE_FLOSS_STUBS}" \
        AURADE_ALLOW_GPU_COMPOSITING_FALLBACK="${AURADE_ALLOW_GPU_COMPOSITING_FALLBACK}" \
        AURADE_ENABLE_WEB_SESSION_BRIDGE="${AURADE_ENABLE_WEB_SESSION_BRIDGE}" \
        AURADE_WEB_SESSION_REMOTE_DEBUGGING_PORT="${AURADE_WEB_SESSION_REMOTE_DEBUGGING_PORT}" \
        AURADE_ENABLE_SPEECH_DISPATCHER="${AURADE_ENABLE_SPEECH_DISPATCHER}" \
        GOOGLE_API_KEY="${GOOGLE_API_KEY:-}" \
        GOOGLE_DEFAULT_CLIENT_ID="${GOOGLE_DEFAULT_CLIENT_ID:-}" \
        GOOGLE_DEFAULT_CLIENT_SECRET="${GOOGLE_DEFAULT_CLIENT_SECRET:-}" \
        GOOGLE_CLIENT_ID_MAIN="${GOOGLE_CLIENT_ID_MAIN:-}" \
        GOOGLE_CLIENT_SECRET_MAIN="${GOOGLE_CLIENT_SECRET_MAIN:-}" \
        HOME="${REAL_HOME}" \
        "${0}" "$@"
fi

aurade_default_feature_profile() {
    local mem_total_kib=""
    if [ -r /proc/meminfo ]; then
        mem_total_kib="$(awk '/^MemTotal:/ { print $2; exit }' /proc/meminfo 2>/dev/null || true)"
    fi

    case "${mem_total_kib}" in
        ""|*[!0-9]*)
            echo "standard"
            ;;
        *)
            if [ "${mem_total_kib}" -ge 8388608 ]; then
                echo "plus"
            else
                echo "standard"
            fi
            ;;
    esac
}

aurade_normalize_feature_profile() {
    local profile="${1,,}"
    profile="${profile%\"}"
    profile="${profile#\"}"
    profile="${profile%\'}"
    profile="${profile#\'}"
    case "${profile}" in
        standard|plus|advanced_plus|advanced_plus_ai)
            echo "${profile}"
            ;;
        *)
            return 1
            ;;
    esac
}

aurade_read_feature_profile_config() {
    local config="$1"
    local key value
    [ -r "${config}" ] || return 0

    while IFS='=' read -r key value; do
        case "${key}" in
            AURADE_FEATURE_PROFILE|profile)
                echo "${value}"
                return 0
                ;;
        esac
    done <"${config}"
}

aurade_read_config_value() {
    local config="$1"
    local requested_key="$2"
    local key value
    [ -r "${config}" ] || return 0

    while IFS='=' read -r key value; do
        case "${key}" in
            "${requested_key}")
                echo "${value}"
                return 0
                ;;
        esac
    done <"${config}"
}

aurade_apply_google_api_config() {
    local config="$1"
    local value
    [ -r "${config}" ] || return 0

    if [ -z "${GOOGLE_API_KEY:-}" ]; then
        value="$(aurade_read_config_value "${config}" "GOOGLE_API_KEY")"
        [ -z "${value}" ] || GOOGLE_API_KEY="${value}"
    fi
    if [ -z "${GOOGLE_DEFAULT_CLIENT_ID:-}" ]; then
        value="$(aurade_read_config_value "${config}" "GOOGLE_DEFAULT_CLIENT_ID")"
        [ -z "${value}" ] || GOOGLE_DEFAULT_CLIENT_ID="${value}"
    fi
    if [ -z "${GOOGLE_DEFAULT_CLIENT_SECRET:-}" ]; then
        value="$(aurade_read_config_value "${config}" "GOOGLE_DEFAULT_CLIENT_SECRET")"
        [ -z "${value}" ] || GOOGLE_DEFAULT_CLIENT_SECRET="${value}"
    fi
    if [ -z "${GOOGLE_CLIENT_ID_MAIN:-}" ]; then
        value="$(aurade_read_config_value "${config}" "GOOGLE_CLIENT_ID_MAIN")"
        [ -z "${value}" ] || GOOGLE_CLIENT_ID_MAIN="${value}"
    fi
    if [ -z "${GOOGLE_CLIENT_SECRET_MAIN:-}" ]; then
        value="$(aurade_read_config_value "${config}" "GOOGLE_CLIENT_SECRET_MAIN")"
        [ -z "${value}" ] || GOOGLE_CLIENT_SECRET_MAIN="${value}"
    fi
}

aurade_join_csv() {
    local joined=""
    local item
    for item in "$@"; do
        if [ -z "${joined}" ]; then
            joined="${item}"
        else
            joined="${joined},${item}"
        fi
    done
    echo "${joined}"
}

if [ -z "${AURADE_STRUCTURED_METRICS_DIR}" ]; then
    AURADE_STRUCTURED_METRICS_DIR="${XDG_STATE_HOME:-${HOME}/.local/state}/aurade/metrics/structured"
fi
if [ -z "${AURADE_PERFETTO_DIR}" ]; then
    AURADE_PERFETTO_DIR="${XDG_RUNTIME_DIR:-${XDG_STATE_HOME:-${HOME}/.local/state}/aurade}/perfetto"
fi

export AURADE_USE_HOST_POWER_STATUS
export AURADE_ENABLE_PIPEWIRE_AUDIO
export AURADE_ENABLE_LOCAL_AMBIENT_BACKEND
export AURADE_SKIP_CHAPS_KEY_PERMISSION_UPDATES
export AURADE_DISABLE_EXTERNAL_METRICS
export AURADE_STRUCTURED_METRICS_DIR
export AURADE_PERFETTO_DIR
export AURADE_DISABLE_SAMPLE_SYSTEM_WEB_APP
export AURADE_DISABLE_CHROMEOS_CONNECTED_DEVICE_FEATURES
export AURADE_DISABLE_ARC_FEATURES
export AURADE_USE_FLOSS_STUBS
export AURADE_ALLOW_GPU_COMPOSITING_FALLBACK

aurade_apply_google_api_config "${AURADE_GOOGLE_API_CONF}"
aurade_apply_google_api_config "${XDG_CONFIG_HOME:-${HOME}/.config}/aurade/google-api.conf"
export GOOGLE_API_KEY
export GOOGLE_DEFAULT_CLIENT_ID
export GOOGLE_DEFAULT_CLIENT_SECRET
export GOOGLE_CLIENT_ID_MAIN
export GOOGLE_CLIENT_SECRET_MAIN

if [ -z "${AURADE_DISPLAY_SCALE}" ]; then
    AURADE_DISPLAY_CONFIG="${XDG_CONFIG_HOME:-${HOME}/.config}/aurade/display.conf"
    if [ -r "${AURADE_DISPLAY_CONFIG}" ]; then
        while IFS='=' read -r key value; do
            if [ "${key}" = "scale" ] && [ -n "${value}" ]; then
                AURADE_DISPLAY_SCALE="${value}"
                break
            fi
        done <"${AURADE_DISPLAY_CONFIG}"
    fi
fi
export AURADE_DISPLAY_SCALE

AURADE_USER_FEATURES_CONFIG="${XDG_CONFIG_HOME:-${HOME}/.config}/aurade/features.conf"
AURADE_CONFIGURED_FEATURE_PROFILE="$(aurade_read_feature_profile_config "${AURADE_USER_FEATURES_CONFIG}")"
if [ -n "${AURADE_CONFIGURED_FEATURE_PROFILE}" ]; then
    AURADE_FEATURE_PROFILE="${AURADE_CONFIGURED_FEATURE_PROFILE}"
fi
if [ -z "${AURADE_LOCAL_AI_BACKEND}" ]; then
    AURADE_LOCAL_AI_BACKEND="$(aurade_read_config_value "${AURADE_USER_FEATURES_CONFIG}" "AURADE_LOCAL_AI_BACKEND")"
fi
if [ -z "${AURADE_LOCAL_AI_MODEL}" ]; then
    AURADE_LOCAL_AI_MODEL="$(aurade_read_config_value "${AURADE_USER_FEATURES_CONFIG}" "AURADE_LOCAL_AI_MODEL")"
fi
if [ -z "${AURADE_LOCAL_AI_ENDPOINT}" ]; then
    AURADE_LOCAL_AI_ENDPOINT="$(aurade_read_config_value "${AURADE_USER_FEATURES_CONFIG}" "AURADE_LOCAL_AI_ENDPOINT")"
fi
if [ -z "${AURADE_LOCAL_AI_EMBED_MODEL}" ]; then
    AURADE_LOCAL_AI_EMBED_MODEL="$(aurade_read_config_value "${AURADE_USER_FEATURES_CONFIG}" "AURADE_LOCAL_AI_EMBED_MODEL")"
fi
if [ -z "${AURADE_LOCAL_AI_EMBED_DIM}" ]; then
    AURADE_LOCAL_AI_EMBED_DIM="$(aurade_read_config_value "${AURADE_USER_FEATURES_CONFIG}" "AURADE_LOCAL_AI_EMBED_DIM")"
fi
if [ -z "${AURADE_LOCAL_AI_AUTO_DOWNLOAD}" ]; then
    AURADE_LOCAL_AI_AUTO_DOWNLOAD="$(aurade_read_config_value "${AURADE_USER_FEATURES_CONFIG}" "AURADE_LOCAL_AI_AUTO_DOWNLOAD")"
fi
AURADE_REQUESTED_FEATURE_PROFILE="${AURADE_FEATURE_PROFILE}"
if AURADE_NORMALIZED_FEATURE_PROFILE="$(aurade_normalize_feature_profile "${AURADE_FEATURE_PROFILE}")"; then
    AURADE_FEATURE_PROFILE="${AURADE_NORMALIZED_FEATURE_PROFILE}"
else
    if [ -n "${AURADE_REQUESTED_FEATURE_PROFILE}" ]; then
        echo "WARNING: unknown AURADE_FEATURE_PROFILE=${AURADE_REQUESTED_FEATURE_PROFILE}; using automatic profile." >&2
    fi
    AURADE_FEATURE_PROFILE="$(aurade_default_feature_profile)"
fi
export AURADE_FEATURE_PROFILE

if [ "${AURADE_FEATURE_PROFILE}" = "advanced_plus_ai" ]; then
    AURADE_LOCAL_AI_BACKEND="${AURADE_LOCAL_AI_BACKEND:-ollama}"
    AURADE_LOCAL_AI_MODEL="${AURADE_LOCAL_AI_MODEL:-gemma4:e2b-it-qat}"
    AURADE_LOCAL_AI_ENDPOINT="${AURADE_LOCAL_AI_ENDPOINT:-http://127.0.0.1:11434}"
    AURADE_LOCAL_AI_AUTO_DOWNLOAD="${AURADE_LOCAL_AI_AUTO_DOWNLOAD:-1}"
    # AuraDE compatibility: local embedding model for history embeddings.
    AURADE_LOCAL_AI_EMBED_MODEL="${AURADE_LOCAL_AI_EMBED_MODEL:-embeddinggemma}"
    AURADE_LOCAL_AI_EMBED_DIM="${AURADE_LOCAL_AI_EMBED_DIM:-768}"
fi
export AURADE_LOCAL_AI_BACKEND
export AURADE_LOCAL_AI_MODEL
export AURADE_LOCAL_AI_ENDPOINT
export AURADE_LOCAL_AI_BOOTSTRAP
export AURADE_LOCAL_AI_AUTO_DOWNLOAD
export AURADE_LOCAL_AI_EMBED_MODEL
export AURADE_LOCAL_AI_EMBED_DIM

# --- Now running as the real user -----------------------------------
AURADE_DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}/aurade"
USER_DATA_DIR="${AURADE_DATA_HOME}/chromiumos-ash"
LEGACY_USER_DATA_DIR="${XDG_DATA_HOME:-${HOME}/.local/share}/chromiumos-ash"

# Ensure DBus is running
if [ -z "${DBUS_SESSION_BUS_ADDRESS}" ]; then
    eval "$(dbus-launch --sh-syntax)"
    export DBUS_SESSION_BUS_ADDRESS
    trap 'kill "${DBUS_SESSION_BUS_PID}"' EXIT
fi

# Ensure the shill-nm-adapter is running (needs system DBus, not session)
if [ "${AURADE_SKIP_SHILL_CHECK}" != "1" ] && \
    ! dbus-send --system --dest=org.chromium.flimflam \
    / org.chromium.flimflam.Manager.GetProperties \
    >/dev/null 2>&1; then
    echo "Starting shill-nm-adapter..."
    if command -v systemctl &>/dev/null; then
        systemctl --user start shill-nm-adapter 2>/dev/null || \
        sudo systemctl start shill-nm-adapter 2>/dev/null || true
    fi
    echo "WARNING: shill-nm-adapter not running. Network may not work."
fi

if [ "${AURADE_ENABLE_PIPEWIRE_AUDIO}" = "1" ] && \
    command -v aurade-audio >/dev/null 2>&1; then
    if ! aurade-audio ensure >/dev/null 2>&1; then
        echo "WARNING: PipeWire audio stack is not ready. Run 'aurade-audio status' for details." >&2
    fi
fi

# Ensure user data dir exists. Migrate the old pre-XDG-AuraDE path once.
if [ ! -e "${USER_DATA_DIR}" ] && [ -d "${LEGACY_USER_DATA_DIR}" ]; then
    mkdir -p "${AURADE_DATA_HOME}"
    mv "${LEGACY_USER_DATA_DIR}" "${USER_DATA_DIR}"
fi
mkdir -p "${USER_DATA_DIR}"
mkdir -p \
    "${AURADE_STRUCTURED_METRICS_DIR}/chromium/storage/flushed" \
    "${AURADE_STRUCTURED_METRICS_DIR}/chromium" \
    "${AURADE_PERFETTO_DIR}"

export PERFETTO_PRODUCER_SOCK_NAME="${PERFETTO_PRODUCER_SOCK_NAME:-${AURADE_PERFETTO_DIR}/traced-producer.sock}"
export PERFETTO_CONSUMER_SOCK_NAME="${PERFETTO_CONSUMER_SOCK_NAME:-${AURADE_PERFETTO_DIR}/traced-consumer.sock}"

if [ "${AURADE_ENABLE_LOCAL_ACCOUNTS}" = "1" ]; then
    AURADE_LOCAL_USERNAME="${USER:-$(id -un)}"
    mkdir -p \
        "${HOME}/Desktop" \
        "${HOME}/Documents" \
        "${HOME}/Downloads" \
        "${HOME}/Music" \
        "${HOME}/Pictures" \
        "${HOME}/Videos" \
        "${USER_DATA_DIR}/.home_user/local-${AURADE_LOCAL_USERNAME}"
fi

if [ "${AURADE_FEATURE_PROFILE}" = "advanced_plus_ai" ] && \
    [ "${AURADE_LOCAL_AI_BOOTSTRAP}" = "1" ]; then
    if command -v aurade-ai-bootstrap >/dev/null 2>&1; then
        aurade-ai-bootstrap --background || true
    else
        echo "WARNING: advanced_plus_ai selected but aurade-ai is not installed; local AI bootstrap skipped." >&2
    fi
fi

if [ -z "${AURADE_OZONE_PLATFORM}" ]; then
    if [ -n "${WAYLAND_DISPLAY:-}" ]; then
        AURADE_OZONE_PLATFORM=wayland
    else
        AURADE_OZONE_PLATFORM=x11
    fi
fi

LOGIN_FLAGS=(--login-manager)

# Default flags for ChromeOS Ash desktop on Linux
FLAGS=(
    "${LOGIN_FLAGS[@]}"
    --ozone-platform="${AURADE_OZONE_PLATFORM}"
    --user-data-dir="${USER_DATA_DIR}"
    --enable-logging=stderr
    --log-level=0
    --v=0
    --disable-sync
    --enable-wayland-server
)

if [ "${AURADE_FEATURE_PROFILE}" = "plus" ] || \
    [ "${AURADE_FEATURE_PROFILE}" = "advanced_plus" ] || \
    [ "${AURADE_FEATURE_PROFILE}" = "advanced_plus_ai" ]; then
    # AuraDE compatibility: expose the stable local parts of the Chromebook
    # Plus-style feature set without claiming certified Chromebook Plus
    # hardware or enabling Google-service/OOBE-dependent gates.
    AURADE_PLUS_FEATURES=(
        FeatureManagementRoundedWindows
        FeatureManagement16Desks
        FeatureManagementTimeOfDayWallpaper
        FeatureManagementTimeOfDayScreenSaver
        FeatureManagementLocalImageSearch
        FilesLocalImageSearch
    )
    if [ "${AURADE_FEATURE_PROFILE}" = "advanced_plus" ] || \
        [ "${AURADE_FEATURE_PROFILE}" = "advanced_plus_ai" ]; then
        # AuraDE compatibility: opt-in experimental non-AI surface area.
        # These are open ChromiumOS/Ash gates that may still need Linux
        # integration work, but they are not primarily local-model features.
        AURADE_PLUS_FEATURES+=(
            FeatureManagementBorealis
            FeatureManagementGameDashboardRecordGame
            FeatureManagementShowoff
            FeatureManagementVideoConference
        )
    fi
    if [ "${AURADE_FEATURE_PROFILE}" = "advanced_plus_ai" ]; then
        # AuraDE compatibility: opt-in AI surface area. These gates expose UI
        # that expects Google services, DLC payloads, or model providers on
        # ChromeOS; AuraDE should back them with the exported local Gemma-class
        # provider contract instead of proprietary Gemini Nano payloads.
        AURADE_PLUS_FEATURES+=(
            FeatureManagementConchGenAi
            FeatureManagementGeminiAppPreinstall
            FeatureManagementGlic
            FeatureManagementHistoryEmbedding
            HistoryEmbeddings
            FeatureManagementLobster
            FeatureManagementMahi
            FeatureManagementOrca
            FeatureManagementPassageEmbedder
            FeatureManagementScanner
            FeatureManagementSeaPen
            OrcaDogfood
        )
        # AuraDE compatibility: local Mahi does not use the ChromeOS
        # variations-country or Google-account eligibility services. Restrict
        # the override to the explicit local-AI profile so the UI is reachable
        # only when the local provider contract is enabled.
        FLAGS+=(--mahi-restrictions-override)
    fi
    FLAGS+=(--enable-features="$(aurade_join_csv "${AURADE_PLUS_FEATURES[@]}")")
fi

if [ -n "${AURADE_ASH_HOST_WINDOW_BOUNDS}" ]; then
    FLAGS+=(--ash-host-window-bounds="${AURADE_ASH_HOST_WINDOW_BOUNDS}")
fi

if [ "${AURADE_ENABLE_LOCAL_ACCOUNTS}" = "1" ]; then
    FLAGS+=(--aurade-enable-local-accounts)
fi

if [ "${AURADE_DISABLE_CHROMEVOX_HINT_TIMER}" = "1" ]; then
    FLAGS+=(--disable-oobe-chromevox-hint-timer-for-testing)
fi

if [ "${AURADE_DISABLE_SAMPLE_SYSTEM_WEB_APP}" = "1" ]; then
    FLAGS+=(--aurade-disable-sample-system-web-app)
fi

if [ "${AURADE_DEV_STUB_OOBE}" = "1" ]; then
    FLAGS+=(--stub-config --stub-auth)
fi

if [ "${AURADE_DISABLE_ARC_FEATURES}" = "1" ]; then
    FLAGS+=(--aurade-disable-arc-features)
fi

if [ "${AURADE_USE_FLOSS_STUBS}" = "1" ]; then
    FLAGS+=(--aurade-use-floss-stubs)
fi

if [ "${AURADE_DISABLE_SANDBOX}" = "1" ]; then
    FLAGS+=(--no-sandbox --disable-gpu-sandbox)
fi

if [ "${AURADE_EXPOSE_SYSTEM_VOLUMES}" = "1" ]; then
    FLAGS+=(--aurade-expose-system-volumes)
fi

if [ "${AURADE_DISABLE_CHROMEOS_CONNECTED_DEVICE_FEATURES}" = "1" ]; then
    FLAGS+=(
        --aurade-disable-chromeos-connected-device-features
        "--disable-features=PhoneHub,EcheSWA,EcheSWASendStartSignaling,EcheSWACheckAndroidNetworkInfo"
    )
fi

if [ "${AURADE_ENABLE_WEB_SESSION_BRIDGE}" = "1" ]; then
    FLAGS+=(
        --remote-debugging-address=127.0.0.1
        "--remote-debugging-port=${AURADE_WEB_SESSION_REMOTE_DEBUGGING_PORT}"
    )
fi

if [ "${AURADE_ENABLE_SPEECH_DISPATCHER}" = "1" ]; then
    FLAGS+=(--enable-speech-dispatcher)
fi

if [ -n "${AURADE_CHROME_EXTRA_FLAGS}" ]; then
    read -r -a EXTRA_FLAGS <<<"${AURADE_CHROME_EXTRA_FLAGS}"
    FLAGS+=("${EXTRA_FLAGS[@]}")
fi

# Forward any extra CLI args
FLAGS+=("$@")

exec "${CHROME}" "${FLAGS[@]}"
