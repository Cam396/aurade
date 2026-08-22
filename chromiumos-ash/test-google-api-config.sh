#!/bin/bash
# Verify OAuth fallback loading without starting a real Chromium process.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCHER="${SCRIPT_DIR}/chromiumos-ash.sh"
# makepkg copies sources into a separate `src/` directory, so the package
# check needs to walk up one level instead of looking beside the test script.
PKGBUILD="${AURADE_PKGBUILD_PATH:-${SCRIPT_DIR}/../PKGBUILD}"
CI_DIR="${AURADE_CI_DIR:-${SCRIPT_DIR}/../ci}"
TMP_DIR="$(mktemp -d "${SCRIPT_DIR}/.google-api-test.XXXXXX")"
trap 'rm -rf "${TMP_DIR}"' EXIT
chmod 777 "${TMP_DIR}"

# The sanctioned OAuth configuration may leave GOOGLE_API_KEY empty.  Guard
# the package recipe here so a future refactor does not make valid OAuth
# credentials impossible to build with.
if grep -Fq ': "${GOOGLE_API_KEY:?GOOGLE_API_KEY is required}"' "${PKGBUILD}"; then
    echo "OAuth config test: API key must remain optional" >&2
    exit 1
fi
grep -Fq ': "${GOOGLE_DEFAULT_CLIENT_ID:?GOOGLE_DEFAULT_CLIENT_ID is required}"' "${PKGBUILD}"
grep -Fq ': "${GOOGLE_DEFAULT_CLIENT_SECRET:?GOOGLE_DEFAULT_CLIENT_SECRET is required}"' "${PKGBUILD}"

if [[ -d "${CI_DIR}" ]]; then
    for build_script in \
        build-current-chromiumos-ash-package.sh \
        build-release-candidate.sh \
        build-clean-arch-chromium-package.sh; do
        grep -Fq 'AURADE_GOOGLE_API_CONFIG' "${CI_DIR}/${build_script}"
    done
    if grep -Fq ': "${GOOGLE_API_KEY:?GOOGLE_API_KEY is required}"' \
        "${CI_DIR}/build-clean-arch-chromium-package.sh"; then
        echo "OAuth config test: clean build must not require an API key" >&2
        exit 1
    fi
    grep -Fq 'AURADE_GOOGLE_API_CONFIG=/build/aurade-private/google-api.conf' \
        "${CI_DIR}/build-clean-arch-chromium-package.sh"
fi

mkdir -p "${TMP_DIR}/home" "${TMP_DIR}/config" "${TMP_DIR}/runtime"
chmod 700 "${TMP_DIR}/runtime"
DEFAULT_ID='fixture-default-id'
DEFAULT_VALUE='fixture-default-value'
cat >"${TMP_DIR}/default.conf" <<EOF
GOOGLE_API_KEY=
GOOGLE_DEFAULT_CLIENT_ID=${DEFAULT_ID}
GOOGLE_DEFAULT_CLIENT_SECRET=${DEFAULT_VALUE}
GOOGLE_CLIENT_ID_MAIN=${DEFAULT_ID}
GOOGLE_CLIENT_SECRET_MAIN=${DEFAULT_VALUE}
EOF
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
        XDG_RUNTIME_DIR="${TMP_DIR}/runtime" \
        AURADE_CHROME="${TMP_DIR}/chrome" \
        AURADE_CHROME_SANDBOX=/bin/false \
        AURADE_GOOGLE_API_CONF="${TMP_DIR}/default.conf" \
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
grep -Fxq "default_id=${DEFAULT_ID}" "${TMP_DIR}/output"
grep -Fxq "default_secret=${DEFAULT_VALUE}" "${TMP_DIR}/output"
grep -Fxq "main_id=${DEFAULT_ID}" "${TMP_DIR}/output"
grep -Fxq "main_secret=${DEFAULT_VALUE}" "${TMP_DIR}/output"

run_launcher $'GOOGLE_DEFAULT_CLIENT_ID=user-id\nGOOGLE_CLIENT_SECRET_MAIN=user-secret'
grep -Fxq 'default_id=user-id' "${TMP_DIR}/output"
grep -Fxq 'main_secret=user-secret' "${TMP_DIR}/output"
grep -Fxq "default_secret=${DEFAULT_VALUE}" "${TMP_DIR}/output"
grep -Fxq "main_id=${DEFAULT_ID}" "${TMP_DIR}/output"

echo "Chromium OAuth configuration test: PASS"
