#!/bin/bash
# Verify OAuth fallback loading without starting a real Chromium process.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCHER="${SCRIPT_DIR}/chromiumos-ash.sh"
TMP_DIR="$(mktemp -d "${SCRIPT_DIR}/.google-api-test.XXXXXX")"
trap 'rm -rf "${TMP_DIR}"' EXIT
chmod 777 "${TMP_DIR}"

mkdir -p "${TMP_DIR}/home" "${TMP_DIR}/config"
cat >"${TMP_DIR}/chrome" <<'EOF'
#!/bin/bash
{
    printf 'default_id=%s\n' "${GOOGLE_DEFAULT_CLIENT_ID:-}"
    printf 'default_secret=%s\n' "${GOOGLE_DEFAULT_CLIENT_SECRET:-}"
    printf 'main_id=%s\n' "${GOOGLE_CLIENT_ID_MAIN:-}"
    printf 'main_secret=%s\n' "${GOOGLE_CLIENT_SECRET_MAIN:-}"
} >"${AURADE_TEST_OUTPUT}"
EOF
chmod 755 "${TMP_DIR}/chrome"

run_launcher() {
    local user_config="${1:-}"
    rm -f "${TMP_DIR}/output"
    rm -rf "${TMP_DIR}/config/aurade"
    if [[ -n "${user_config}" ]]; then
        mkdir -p "${TMP_DIR}/config/aurade"
        printf '%s\n' "${user_config}" >"${TMP_DIR}/config/aurade/google-api.conf"
    fi
    env \
        HOME="${TMP_DIR}/home" \
        XDG_CONFIG_HOME="${TMP_DIR}/config" \
        AURADE_CHROME="${TMP_DIR}/chrome" \
        AURADE_CHROME_SANDBOX=/bin/false \
        AURADE_GOOGLE_API_CONF="${SCRIPT_DIR}/google-api.conf" \
        AURADE_TEST_OUTPUT="${TMP_DIR}/output" \
        AURADE_SKIP_SHILL_CHECK=1 \
        AURADE_ENABLE_PIPEWIRE_AUDIO=0 \
        AURADE_ENABLE_LOCAL_ACCOUNTS=0 \
        AURADE_LOCAL_AI_BOOTSTRAP=0 \
        AURADE_FEATURE_PROFILE=standard \
        AURADE_OZONE_PLATFORM=x11 \
        AURADE_DISABLE_SANDBOX=1 \
        DBUS_SESSION_BUS_ADDRESS=disabled \
        bash "${LAUNCHER}"
}

run_launcher
grep -Fxq 'default_id=77185425430.apps.googleusercontent.com' "${TMP_DIR}/output"
grep -Fxq 'default_secret=OTJgUOQcT7lO7GsGZq2G4IlT' "${TMP_DIR}/output"
grep -Fxq 'main_id=77185425430.apps.googleusercontent.com' "${TMP_DIR}/output"
grep -Fxq 'main_secret=OTJgUOQcT7lO7GsGZq2G4IlT' "${TMP_DIR}/output"

run_launcher $'GOOGLE_DEFAULT_CLIENT_ID=user-id\nGOOGLE_CLIENT_SECRET_MAIN=user-secret'
grep -Fxq 'default_id=user-id' "${TMP_DIR}/output"
grep -Fxq 'main_secret=user-secret' "${TMP_DIR}/output"
grep -Fxq 'default_secret=OTJgUOQcT7lO7GsGZq2G4IlT' "${TMP_DIR}/output"
grep -Fxq 'main_id=77185425430.apps.googleusercontent.com' "${TMP_DIR}/output"

echo "Chromium OAuth configuration test: PASS"
