#!/usr/bin/env bash
# The renderer list, and the launcher that walks it.
#
# This is the code that decides whether anyone sees a window at all, and until
# now the answer on a machine with no hardware acceleration was "not unless you
# already know to type WLR_RENDERER=pixman". So both halves are tested: the
# order the list comes out in, and the launcher's rule for when to try the next
# entry.
#
# The launcher's rule is the subtle one. `cage` exits with its client's status,
# so the exit code cannot tell "the compositor never started" from "the user
# quit the installer". Getting it wrong in one direction restarts a
# half-answered installation under a different renderer; getting it wrong in
# the other leaves the black screen. The installer therefore reports having
# drawn, and that report is what these tests exercise.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fail() { echo "test-renderer-chain: $*" >&2; exit 1; }

install -d "$TMP/dri" "$TMP/drm" "$TMP/vulkan" "$TMP/bin" "$TMP/lib" "$TMP/stub"

# Two graphics devices and a virtual one:
#   card0  integrated, panel plugged in
#   card1  discrete NVIDIA, no connectors at all
#   card2  vkms, a kernel test device that publishes nodes and drives nothing
card() {
  local name=$1 driver=$2
  : >"$TMP/dri/$name"
  install -d "$TMP/drm/$name/device"
  printf 'DRIVER=%s\n' "$driver" >"$TMP/drm/$name/device/uevent"
}
card card0 i915
card card1 nvidia
card card2 vkms
install -d "$TMP/drm/card0-eDP-1" "$TMP/drm/card1-DP-1"
printf 'connected\n' >"$TMP/drm/card0-eDP-1/status"
printf 'disconnected\n' >"$TMP/drm/card1-DP-1/status"

export AURADE_RENDERER_DRI_DIR="$TMP/dri" AURADE_RENDERER_DRM_DIR="$TMP/drm"
export AURADE_RENDERER_VULKAN_DIR="$TMP/vulkan"

# shellcheck source=../lib/aurade-renderers.sh
. "$ROOT/installer/lib/aurade-renderers.sh"

# -- ordering ---------------------------------------------------------------

mapfile -t cards < <(aurade_renderer_cards)
[[ ${cards[0]} == "$TMP/dri/card0" ]] || \
  fail "the card with a display attached is not first: ${cards[*]}"
[[ ${cards[1]} == "$TMP/dri/card1" ]] || \
  fail "the card with no connected output is not second: ${cards[*]}"
(( ${#cards[@]} == 2 )) || fail "the vkms virtual device was not excluded: ${cards[*]}"

# No Vulkan driver installed: the chain must not spend an attempt on it.
mapfile -t plan < <(aurade_renderer_plan)
printf '%s\n' "${plan[@]}" | grep -q 'WLR_RENDERER=vulkan' && \
  fail 'vulkan is offered with no ICD installed'

printf '%s\n' "${plan[@]}" | tail -1 | grep -q 'WLR_RENDERER=pixman' || \
  fail 'the software floor is not the last thing tried'
printf '%s\n' "${plan[@]}" | grep -q 'LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe' || \
  fail 'software OpenGL is not tried before giving up on GL entirely'

# The integrated card comes before the discrete one, and the discrete one is
# the NVIDIA card, which needs the cursor workaround wlroots requires.
first_gpu=$(printf '%s\n' "${plan[@]}" | grep -n 'WLR_DRM_DEVICES' | head -1)
[[ $first_gpu == *card0* ]] || fail "the first GPU attempt is not card0: $first_gpu"
nvidia_line=$(printf '%s\n' "${plan[@]}" | grep 'card1' | head -1)
[[ $nvidia_line == *WLR_NO_HARDWARE_CURSORS=1* ]] || \
  fail "the NVIDIA attempt does not disable hardware cursors: $nvidia_line"
[[ $nvidia_line == *nvidia* ]] || \
  fail "the NVIDIA attempt is not labelled with the driver: $nvidia_line"

# With a Vulkan driver present it is tried, and tried before OpenGL.
: >"$TMP/vulkan/intel_icd.x86_64.json"
mapfile -t plan < <(aurade_renderer_plan)
vulkan_at=$(printf '%s\n' "${plan[@]}" | grep -n 'WLR_RENDERER=vulkan' | head -1 | cut -d: -f1)
gles_at=$(printf '%s\n' "${plan[@]}" | grep -n 'WLR_RENDERER=gles2' | head -1 | cut -d: -f1)
[[ -n $vulkan_at ]] || fail 'vulkan is not offered even with an ICD installed'
(( vulkan_at < gles_at )) || fail 'OpenGL is tried before Vulkan'

# -- the launcher -----------------------------------------------------------
#
# A stub cage that fails for every renderer except the one named in
# AURADE_TEST_WORKING_RENDERER, and that touches the readiness file the way
# the real installer does when it actually draws.

install -m 0755 "$ROOT/installer/bin/aurade-installer-start" "$TMP/bin/"
install -m 0644 "$ROOT/installer/lib/aurade-renderers.sh" \
  "$ROOT/installer/lib/aurade-probe.sh" "$TMP/lib/"
cat >"$TMP/bin/aurade-installer-gui" <<'STUB'
#!/usr/bin/env bash
exit 0
STUB
cat >"$TMP/bin/aurade-installer-tui" <<'STUB'
#!/usr/bin/env bash
printf 'text installer ran\n' >>"$AURADE_TEST_LOG"
exit 0
STUB
cat >"$TMP/stub/cage" <<'STUB'
#!/usr/bin/env bash
printf 'cage renderer=%s devices=%s\n' "${WLR_RENDERER:-unset}" \
  "${WLR_DRM_DEVICES:-none}" >>"$AURADE_TEST_LOG"
if [[ ${WLR_RENDERER:-} == "${AURADE_TEST_WORKING_RENDERER:-never}" ]]; then
  # This is what the real front end does the moment its window is mapped.
  printf 'mapped\n' >"$AURADE_GUI_READY_FILE"
  exit "${AURADE_TEST_GUI_STATUS:-0}"
fi
exit 1
STUB
chmod +x "$TMP/bin/aurade-installer-gui" "$TMP/bin/aurade-installer-tui" "$TMP/stub/cage"

run_launcher() {
  : >"$TMP/log"
  # No DISPLAY and no WAYLAND_DISPLAY, because the launcher has a deliberate
  # shortcut for "already inside a session with a display" that runs the front
  # end directly and never starts a compositor. The build host has an X display
  # and the installation image does not, so without this the whole chain is
  # skipped and every assertion below passes on an empty log.
  env -u DISPLAY -u WAYLAND_DISPLAY \
    AURADE_TEST_LOG="$TMP/log" PATH="$TMP/stub:$PATH" \
    AURADE_RENDERER_DRI_DIR="$AURADE_RENDERER_DRI_DIR" \
    AURADE_RENDERER_DRM_DIR="$AURADE_RENDERER_DRM_DIR" \
    AURADE_RENDERER_VULKAN_DIR="$AURADE_RENDERER_VULKAN_DIR" \
    ${AURADE_TEST_WORKING_RENDERER:+AURADE_TEST_WORKING_RENDERER="$AURADE_TEST_WORKING_RENDERER"} \
    ${AURADE_TEST_GUI_STATUS:+AURADE_TEST_GUI_STATUS="$AURADE_TEST_GUI_STATUS"} \
    "$TMP/bin/aurade-installer-start" --graphical >>"$TMP/log" 2>&1 || true
}

# Nothing but pixman works: every earlier renderer is attempted, in order, and
# the installer still ends up on the screen.
AURADE_TEST_WORKING_RENDERER=pixman; AURADE_TEST_GUI_STATUS=
run_launcher
grep -q 'renderer=vulkan devices=.*card0' "$TMP/log" || \
  fail 'the launcher did not try Vulkan on the connected card first'
grep -q 'renderer=gles2 devices=.*card1' "$TMP/log" || \
  fail 'the launcher skipped the second card'
grep -q 'renderer=pixman' "$TMP/log" || fail 'the launcher never reached pixman'
grep -q 'text installer ran' "$TMP/log" && \
  fail 'the launcher fell back to text even though a renderer worked'

# The first renderer works: nothing after it is attempted. Restarting a
# working installer to try a "better" renderer would be the worst outcome here.
AURADE_TEST_WORKING_RENDERER=vulkan; AURADE_TEST_GUI_STATUS=
run_launcher
grep -q 'renderer=pixman' "$TMP/log" && \
  fail 'the launcher kept trying renderers after one had drawn'

# The installer drew and then exited non-zero, which is a user who quit or an
# installation that failed. Neither is a renderer problem, so the launcher must
# not restart it under a different renderer or hand over to the text installer.
AURADE_TEST_WORKING_RENDERER=vulkan; AURADE_TEST_GUI_STATUS=1
run_launcher
(( $(grep -c '^cage ' "$TMP/log") == 1 )) || \
  fail 'a non-zero exit after drawing was treated as a renderer failure'
grep -q 'text installer ran' "$TMP/log" && \
  fail 'the launcher fell back to text after the installer had already drawn'

# Nothing works at all. The text installer is the guarantee, and it runs.
AURADE_TEST_WORKING_RENDERER=never; AURADE_TEST_GUI_STATUS=
run_launcher
grep -q 'text installer ran' "$TMP/log" || \
  fail 'no renderer worked and the text installer was not started'

echo 'installer renderer chain test: PASS'
