#!/bin/bash
# The flags the launcher gives Chrome for a local account, checked without
# starting a real Chromium process.
#
# Chrome keeps only the last --disable-features on its command line, so two
# blocks that each pass one silently cancel each other. The launcher gathers
# every disabled feature into one flag, and this test holds it to that.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCHER="${AURADE_LAUNCHER_PATH:-${SCRIPT_DIR}/chromiumos-ash.sh}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT
chmod 777 "${TMP_DIR}"
mkdir -p "${TMP_DIR}/home" "${TMP_DIR}/config" "${TMP_DIR}/runtime"
chmod 700 "${TMP_DIR}/runtime"

fail() { echo "local account flags test: $*" >&2; exit 1; }

cat >"${TMP_DIR}/chrome" <<'CHROME'
#!/bin/bash
printf '%s\n' "$@" >"${AURADE_TEST_OUTPUT}"
CHROME
chmod 755 "${TMP_DIR}/chrome"

EXTRA_ENV=()
run_launcher() {
    local local_accounts=$1 profile=$2 connected=$3
    rm -f "${TMP_DIR}/output"
    env \
        HOME="${TMP_DIR}/home" \
        XDG_CONFIG_HOME="${TMP_DIR}/config" \
        XDG_RUNTIME_DIR="${TMP_DIR}/runtime" \
        AURADE_CHROME="${TMP_DIR}/chrome" \
        AURADE_CHROME_SANDBOX=/bin/false \
        AURADE_GOOGLE_API_CONF=/dev/null \
        AURADE_FEATURES_CONF=/dev/null \
        AURADE_TEST_OUTPUT="${TMP_DIR}/output" \
        AURADE_SKIP_SHILL_CHECK=1 \
        AURADE_ENABLE_PIPEWIRE_AUDIO=0 \
        AURADE_ENABLE_LOCAL_ACCOUNTS="${local_accounts}" \
        AURADE_DISABLE_CHROMEOS_CONNECTED_DEVICE_FEATURES="${connected}" \
        AURADE_LOCAL_AI_BOOTSTRAP=0 \
        AURADE_FEATURE_PROFILE="${profile}" \
        AURADE_OZONE_PLATFORM=x11 \
        AURADE_DISABLE_SANDBOX=1 \
        DBUS_SESSION_BUS_ADDRESS=disabled \
        "${EXTRA_ENV[@]}" \
        bash "${LAUNCHER}"
    [[ -s ${TMP_DIR}/output ]] || fail 'the launcher never reached Chrome'
}

disabled_flags() { grep -c '^--disable-features=' "${TMP_DIR}/output" || true; }
disabled_list() { sed -n 's/^--disable-features=//p' "${TMP_DIR}/output" | tr ',' '\n'; }

# A local account: no first-run Explore window, and the connected device
# features still off in a single flag.
run_launcher 1 standard 1
grep -Fxq -- '--aurade-enable-local-accounts' "${TMP_DIR}/output" || fail 'local accounts are not switched on'
grep -Fxq -- '--disable-first-run-ui' "${TMP_DIR}/output" || fail 'Explore still opens on first login'
[[ $(disabled_flags) == 1 ]] || fail "expected one --disable-features, found $(disabled_flags)"
disabled_list | grep -Fxq PhoneHub || fail 'the connected device features were lost'

# Without local accounts nothing here changes.
run_launcher 0 standard 0
if grep -Fxq -- '--disable-first-run-ui' "${TMP_DIR}/output"; then
    fail 'first-run UI is off without local accounts'
fi
[[ $(disabled_flags) == 0 ]] || fail 'features are disabled without a reason'

# Features switched on go in one flag as well, and the Plus profile's join
# the same one rather than replacing it.
enabled_flags() { grep -c '^--enable-features=' "${TMP_DIR}/output" || true; }
enabled_list() { sed -n 's/^--enable-features=//p' "${TMP_DIR}/output" | tr ',' '\n'; }
run_launcher 1 standard 1
[[ $(enabled_flags) == 1 ]] || fail "expected one --enable-features, found $(enabled_flags)"
enabled_list | grep -Fxq AudioFocusEnforcement || \
    fail 'starting one player no longer pauses the others'
run_launcher 1 plus 1
[[ $(enabled_flags) == 1 ]] || fail "plus: expected one --enable-features, found $(enabled_flags)"
enabled_list | grep -Fxq AudioFocusEnforcement || fail 'plus: the Plus features replaced the rest'
enabled_list | grep -Fxq FeatureManagement16Desks || fail 'plus: the Plus features are missing'

# The DevTools port takes over the desktop with no password, so a session
# starts without it, and only a test machine that asks for it gets it.
devtools() { grep -c -- '^--remote-debugging-port=' "${TMP_DIR}/output" || true; }
run_launcher 1 standard 1
[[ $(devtools) == 0 ]] || fail 'the DevTools port is open by default, so any program can take over the desktop'
EXTRA_ENV=(AURADE_ENABLE_DEVTOOLS_PORT=1)
run_launcher 1 standard 1
grep -Fxq -- '--remote-debugging-port=9222' "${TMP_DIR}/output" || fail 'a test machine that asks for the DevTools port does not get it'
grep -Fxq -- '--remote-debugging-address=127.0.0.1' "${TMP_DIR}/output" || fail 'the DevTools port is not limited to this machine'
EXTRA_ENV=()

echo "local account flags test: PASS"
