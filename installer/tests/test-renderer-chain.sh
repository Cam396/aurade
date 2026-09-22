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

# shellcheck source=assert.sh
. "$(dirname -- "$0")/assert.sh"

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

# A seat this test owns.
#
# The launcher will not start a compositor without one, and it accepts either a
# seatd socket or a logind session. Nothing below stubbed either, so the seat
# came from whoever ran the test: an interactive shell has XDG_SESSION_ID and
# passes, and a systemd unit or a CI runner has no session, gets no seat, falls
# straight through to the text installer and never attempts a renderer at all.
# Every renderer assertion then failed for a reason that had nothing to do with
# renderers. So the socket is a real one, created here, and run_launcher drops
# XDG_SESSION_ID so the host's session can never decide the answer.
AURADE_TEST_SEAT_SOCKET="$TMP/seat.sock"
python3 -c 'import socket, sys; socket.socket(socket.AF_UNIX).bind(sys.argv[1])' \
  "$AURADE_TEST_SEAT_SOCKET"
[[ -S $AURADE_TEST_SEAT_SOCKET ]] || {
  echo 'test-renderer-chain: could not create a stand in seat socket' >&2
  exit 1
}
export AURADE_TEST_SEAT_SOCKET
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

# The pointer. A hardware cursor plane draws nothing at all on several virtual
# GPUs - the pointer moves, clicks land, and the screen never shows it - and
# an unset theme name resolves through an alias a live image need not have.
# Every candidate carries both, because the one that ends up working is not
# known in advance and an installer nobody can point at is not usable.
while IFS= read -r line; do
  [[ -n $line ]] || continue
  [[ $line == *WLR_NO_HARDWARE_CURSORS=1* ]] || \
    fail "a graphics candidate would draw its pointer in hardware: $line"
  [[ $line == *XCURSOR_THEME=Adwaita* ]] || \
    fail "a graphics candidate does not name a cursor theme: $line"
done < <(printf '%s\n' "${plan[@]}")
while IFS= read -r line; do
  [[ -n $line ]] || continue
  [[ $line == *XCURSOR_THEME=Adwaita* ]] || \
    fail "a client candidate does not name a cursor theme: $line"
done < <(aurade_renderer_client_plan)
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

# Safe graphics is the boot entry for a machine whose graphics stack reports
# success and then draws nothing. Negotiation cannot see that failure, so this
# path does not negotiate: one compositor candidate, one client candidate, both
# software, and no accelerated path offered at all.
safe_plan=$(AURADE_SAFE_GRAPHICS=1 bash -c ". '$ROOT/installer/lib/aurade-renderers.sh'; aurade_renderer_plan")
safe_clients=$(AURADE_SAFE_GRAPHICS=1 bash -c ". '$ROOT/installer/lib/aurade-renderers.sh'; aurade_renderer_client_plan")
(( $(printf '%s\n' "$safe_plan" | grep -c .) == 1 )) || \
  fail "safe graphics offered more than one compositor: $safe_plan"
(( $(printf '%s\n' "$safe_clients" | grep -c .) == 1 )) || \
  fail "safe graphics offered more than one drawing path: $safe_clients"
[[ $safe_plan == *WLR_RENDERER=pixman* ]] || \
  fail "safe graphics is not the software floor: $safe_plan"
[[ $safe_clients == *GSK_RENDERER=cairo* ]] || \
  fail "safe graphics still lets GTK reach for a GPU: $safe_clients"

# -- the launcher -----------------------------------------------------------
#
# A stub cage that fails for every renderer except the one named in
# AURADE_TEST_WORKING_RENDERER, and that touches the readiness file the way
# the real installer does when it actually draws.

install -m 0755 "$ROOT/installer/bin/aurade-installer-start" "$TMP/bin/"
# The real explainer, beside the launcher, because the launcher asks it what
# the kernel thought of a failed attempt and finds it the same way it finds
# everything else: next to itself, or in the installed location.
install -m 0755 "$ROOT/installer/bin/aurade-explain" "$TMP/bin/"
export AURADE_NOTES_FILE="$ROOT/installer/data/hardware-notes.tsv"
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
printf 'cage renderer=%s devices=%s gsk=%s disable=%s\n' \
  "${WLR_RENDERER:-unset}" "${WLR_DRM_DEVICES:-none}" \
  "${GSK_RENDERER:-default}" "${GDK_DISABLE:-none}" >>"$AURADE_TEST_LOG"
if [[ ${WLR_RENDERER:-} != "${AURADE_TEST_WORKING_RENDERER:-never}" ]]; then
  exit 1     # the compositor never started: nothing is drawn
fi
# The compositor drew. This is what the real front end writes on first map.
printf 'mapped\n' >"$AURADE_GUI_READY_FILE"
if [[ -n ${AURADE_TEST_WORKING_GSK:-} \
      && ${GSK_RENDERER:-default} != "$AURADE_TEST_WORKING_GSK" ]]; then
  exit 1     # a window, then GTK dies on it: the client side, not the renderer
fi
[[ -z ${AURADE_TEST_STAGE:-} ]] || printf '%s\n' "$AURADE_TEST_STAGE" \
  >"$AURADE_GUI_READY_FILE"
exit "${AURADE_TEST_GUI_STATUS:-0}"
STUB
chmod +x "$TMP/bin/aurade-installer-gui" "$TMP/bin/aurade-installer-tui" "$TMP/stub/cage"

run_launcher() {
  : >"$TMP/log"
  # No DISPLAY and no WAYLAND_DISPLAY, because the launcher has a deliberate
  # shortcut for "already inside a session with a display" that runs the front
  # end directly and never starts a compositor. The build host has an X display
  # and the installation image does not, so without this the whole chain is
  # skipped and every assertion below passes on an empty log.
  env -u DISPLAY -u WAYLAND_DISPLAY -u WLR_RENDERER -u GSK_RENDERER \
    -u XDG_SESSION_ID \
    AURADE_SEAT_SOCKET="${AURADE_TEST_CASE_SEAT-$AURADE_TEST_SEAT_SOCKET}" \
    AURADE_TEST_LOG="$TMP/log" PATH="$TMP/stub:$PATH" \
    AURADE_RENDERER_DRI_DIR="$AURADE_RENDERER_DRI_DIR" \
    AURADE_RENDERER_DRM_DIR="$AURADE_RENDERER_DRM_DIR" \
    AURADE_RENDERER_VULKAN_DIR="$AURADE_RENDERER_VULKAN_DIR" \
    ${AURADE_TEST_WORKING_RENDERER:+AURADE_TEST_WORKING_RENDERER="$AURADE_TEST_WORKING_RENDERER"} \
    ${AURADE_TEST_WORKING_GSK:+AURADE_TEST_WORKING_GSK="$AURADE_TEST_WORKING_GSK"} \
    ${AURADE_TEST_STAGE:+AURADE_TEST_STAGE="$AURADE_TEST_STAGE"} \
    ${AURADE_TEST_GUI_STATUS:+AURADE_TEST_GUI_STATUS="$AURADE_TEST_GUI_STATUS"} \
    AURADE_NOTES_FILE="$AURADE_NOTES_FILE" \
    "$TMP/bin/aurade-installer-start" --graphical >>"$TMP/log" 2>&1 || true
}

reset_case() {
  unset AURADE_TEST_CASE_SEAT
  AURADE_TEST_WORKING_RENDERER=never
  AURADE_TEST_WORKING_GSK=
  AURADE_TEST_STAGE=
  AURADE_TEST_GUI_STATUS=
}

# Nothing but pixman works: every earlier renderer is attempted, in order, and
# the installer still ends up on the screen.
reset_case; AURADE_TEST_WORKING_RENDERER=pixman
run_launcher
grep -q 'renderer=vulkan devices=.*card0' "$TMP/log" || \
  fail 'the launcher did not try Vulkan on the connected card first'
grep -q 'renderer=gles2 devices=.*card1' "$TMP/log" || \
  fail 'the launcher skipped the second card'
grep -q 'renderer=pixman' "$TMP/log" || fail 'the launcher never reached pixman'
grep -q 'text installer ran' "$TMP/log" && \
  fail 'the launcher fell back to text even though a renderer worked'

# A compositor that never drew is not worth a second drawing path: no client
# setting can rescue a compositor that failed to start, and trying anyway
# makes the walk to a renderer that works several times longer.
(( $(grep -c 'renderer=vulkan devices=.*card0' "$TMP/log") == 1 )) || \
  fail 'a compositor that never drew was retried with other client settings'

# The first renderer works: nothing after it is attempted. Restarting a
# working installer to try a "better" renderer would be the worst outcome here.
reset_case; AURADE_TEST_WORKING_RENDERER=vulkan
run_launcher
grep -q 'renderer=pixman' "$TMP/log" && \
  fail 'the launcher kept trying renderers after one had drawn'

# The compositor comes up on the first try and the window appears - and then
# GTK dies on it, which is the virtual-GPU failure this chain exists for. The
# renderer is not the problem, so the launcher must stay on this compositor
# and work down the client drawing paths instead of walking away from a
# graphics device that demonstrably works.
reset_case
AURADE_TEST_WORKING_RENDERER=vulkan
AURADE_TEST_WORKING_GSK=cairo
run_launcher
grep -q 'renderer=vulkan .*gsk=cairo' "$TMP/log" || \
  fail 'the launcher never tried a software client drawing path'
grep -q 'renderer=pixman' "$TMP/log" && \
  fail 'the launcher changed the compositor renderer to fix a client failure'
grep -q 'text installer ran' "$TMP/log" && \
  fail 'the launcher fell back to text with a client path left untried'
first_retry=$(grep '^cage ' "$TMP/log" | sed -n 2p)
[[ $first_retry == *disable=*dmabuf* ]] || \
  fail "the retry after a mapped window did not drop buffer sharing: $first_retry"

# The window appeared and the process exited cleanly without the user ever
# pressing Continue: that is someone who looked at the first screen and quit.
# The installer worked. Trying another renderer would put it back on screen
# after they closed it.
reset_case; AURADE_TEST_WORKING_RENDERER=vulkan
run_launcher
(( $(grep -c '^cage ' "$TMP/log") == 1 )) || \
  fail 'a clean exit at the first screen was treated as a renderer failure'
grep -q 'text installer ran' "$TMP/log" && \
  fail 'the launcher fell back to text after a clean exit'

# The user got as far as answering something and the installer then failed.
# Whatever went wrong, it is not the renderer, and a restart would throw away
# the answers already on the screen.
reset_case
AURADE_TEST_WORKING_RENDERER=vulkan
AURADE_TEST_STAGE=engaged
AURADE_TEST_GUI_STATUS=1
run_launcher
(( $(grep -c '^cage ' "$TMP/log") == 1 )) || \
  fail 'a failure after the user had answered was retried under another renderer'
grep -q 'text installer ran' "$TMP/log" && \
  fail 'the launcher fell back to text after the user had already answered'

# Nothing works at all. The text installer is the guarantee, and it runs.
reset_case
run_launcher
grep -q 'text installer ran' "$TMP/log" || \
  fail 'no renderer worked and the text installer was not started'
grep -q 'what each attempt printed is in' "$TMP/log" || \
  fail 'the chain failed without saying where the attempt output was kept'

# A window that drew and then vanished, with the kernel having an opinion.
#
# The graphical installer records its own crashes, and there is one death it
# cannot record: the kernel killing it. An out of memory kill is SIGKILL, so
# there is no handler, no traceback and no file, and all that is left is a
# window that went away for no stated reason. The evidence is in the kernel
# log, in the format nobody reads, and `aurade-explain` exists to turn that
# into a sentence.
reset_case
cat >"$TMP/stub/dmesg" <<'STUB'
#!/usr/bin/env bash
printf '[  312.4] Out of memory: Killed process 812 (aurade-installer-gui)\n'
STUB
chmod +x "$TMP/stub/dmesg"
AURADE_TEST_WORKING_RENDERER=vulkan
AURADE_TEST_STAGE=mapped
AURADE_TEST_GUI_STATUS=1
run_launcher
grep -Fq 'ran out of memory' "$TMP/log" ||
  fail 'a window killed by the kernel was reported without saying the kernel killed it'
rm -f "$TMP/stub/dmesg"

# And a quiet kernel says nothing at all, because a paragraph about a machine
# where nothing is wrong is noise on a screen somebody is already worried about.
reset_case
cat >"$TMP/stub/dmesg" <<'STUB'
#!/usr/bin/env bash
printf '[    0.0] Linux version 6.12.4-aurade\n[    1.2] usb 1-1: new high-speed USB device number 2\n'
STUB
chmod +x "$TMP/stub/dmesg"
AURADE_TEST_WORKING_RENDERER=vulkan
AURADE_TEST_STAGE=mapped
AURADE_TEST_GUI_STATUS=1
run_launcher
# Asserted on what reaches the console rather than on what reaches the attempt
# log, because the console is the thing a person is looking at and the attempt
# log is in a temporary directory this test never opens. The first version of
# this checked the header that only ever goes to the log, so removing the guard
# entirely still passed.
refute grep -Fq 'Nothing in this log' "$TMP/log"
rm -f "$TMP/stub/dmesg"

# The person asked to leave.
#
# `cage` is a kiosk compositor with no VT-switch bindings, so Quit is the only
# way out of the graphical installer, and a Quit that ends the process looked
# exactly like a window that died. The launcher does the right thing for a
# window that died: it starts another one. So Quit restarted the installer, and
# there was no way out of it at all. This is the one case where the exit status
# must not be consulted, because leaving is a decision and not an outcome.
reset_case
AURADE_TEST_WORKING_RENDERER=vulkan
AURADE_TEST_STAGE=quit
AURADE_TEST_GUI_STATUS=1
run_launcher
(( $(grep -c '^cage ' "$TMP/log") == 1 )) || \
  fail 'quitting the installer started another one'
grep -q 'text installer ran' "$TMP/log" && \
  fail 'quitting the graphical installer dropped into the text one'
grep -q 'Nothing has been written to any disk' "$TMP/log" || \
  fail 'leaving the installer did not say the disk was untouched'

# The front end itself says the graphical installer cannot run here - no
# toolkit, or a probe that predicts a black screen. That is not a renderer
# finding, and walking the rest of the list only delays the text installer.
reset_case
AURADE_TEST_WORKING_RENDERER=vulkan
AURADE_TEST_STAGE=declined
AURADE_TEST_GUI_STATUS=1
run_launcher
(( $(grep -c '^cage ' "$TMP/log") == 1 )) || \
  fail 'a front end that declined to draw was retried under other renderers'
grep -q 'text installer ran' "$TMP/log" || \
  fail 'a front end that declined to draw did not reach the text installer'

# An explicit choice is honoured rather than overridden. This is the command
# the user had to type before any of this existed, and it must still mean what
# it says.
: >"$TMP/log"
env -u DISPLAY -u WAYLAND_DISPLAY -u XDG_SESSION_ID WLR_RENDERER=pixman \
  AURADE_SEAT_SOCKET="$AURADE_TEST_SEAT_SOCKET" \
  AURADE_TEST_LOG="$TMP/log" PATH="$TMP/stub:$PATH" \
  AURADE_RENDERER_DRI_DIR="$AURADE_RENDERER_DRI_DIR" \
  AURADE_RENDERER_DRM_DIR="$AURADE_RENDERER_DRM_DIR" \
  AURADE_RENDERER_VULKAN_DIR="$AURADE_RENDERER_VULKAN_DIR" \
  AURADE_TEST_WORKING_RENDERER=pixman \
  "$TMP/bin/aurade-installer-start" --graphical >>"$TMP/log" 2>&1 || true
[[ $(grep -c '^cage ' "$TMP/log") == 1 ]] || \
  fail 'an explicit WLR_RENDERER was not tried first'
grep -q '^cage renderer=pixman' "$TMP/log" || \
  fail 'an explicit WLR_RENDERER was overridden by the chain'


# With no seat at all the launcher must say so and put the text installer on
# the screen. This is the path that had no test, which is why a clean
# environment could turn every renderer assertion above into a failure with no
# hint as to the cause. The message is asserted too, because a silent fallback
# to text is the black screen this file exists to prevent, one step later.
reset_case
AURADE_TEST_CASE_SEAT="$TMP/no-such-seat.sock"
AURADE_TEST_WORKING_RENDERER=pixman
cat >"$TMP/stub/systemctl" <<'STUB'
#!/bin/sh
# The launcher tries to start seatd when it cannot find a seat. On a build host
# that is a real service on a real machine, so it is stubbed to do nothing.
exit 1
STUB
chmod +x "$TMP/stub/systemctl"
run_launcher
rm -f "$TMP/stub/systemctl"
grep -q 'no seat manager is running' "$TMP/log" || \
  fail 'the launcher did not say that no seat manager was available'
grep -q 'text installer ran' "$TMP/log" || \
  fail 'with no seat the launcher did not fall back to the text installer'
grep -q 'renderer=' "$TMP/log" && \
  fail 'with no seat the launcher tried a renderer anyway'
reset_case

# --- the seat, which is what actually stopped this working -------------------
#
# wlroots asks libseat for a seat before it looks at a graphics device, and
# libseat has exactly two ways to give it one: the seatd daemon on
# /run/seatd.sock, or a logind session. The autostart is a systemd oneshot and
# has no logind session, and seatd was on the image and never enabled. So every
# compositor entry failed identically, before any renderer was chosen, and a
# machine with working graphics spent the length of the chain failing and
# landed in the text installer.
#
# The fix applied to that was `LIBSEAT_BACKEND=builtin` on every entry, and
# there was a test here asserting the setting was present on every entry. It
# passed. `builtin` is a real libseat backend and it is a build option that
# Arch does not enable, so the string is not in the shipped library at all, and
# every entry went on failing one error message later:
#
#   [libseat] No backend matched name 'builtin'
#
# The test checked that a setting was there. Nothing checked it named anything,
# which was the entire question, and the suite reported a working installer for
# three days.
#
# So the assertion is inverted. Naming a backend can only narrow what libseat
# would have tried by itself, and the one time it was done it narrowed it to
# nothing. If a future change does name one, it has to be a backend that
# exists.
LIBSEAT_REAL='seatd logind'
named=0
while IFS=$'\t' read -r label settings; do
  [[ -n $label ]] || continue
  case $settings in
    *LIBSEAT_BACKEND=*)
      backend=${settings##*LIBSEAT_BACKEND=}
      backend=${backend%% *}
      case " $LIBSEAT_REAL " in
        *" $backend "*) ;;
        *) echo "test-renderer-chain: '$label' asks for a libseat backend that does not exist: $backend" >&2
           named=$(( named + 1 )) ;;
      esac
      ;;
  esac
done < <(aurade_renderer_plan)
(( named == 0 )) || exit 1

# The obvious strengthening of that check is to read the names out of a real
# libseat instead of a list in this file, and it is wrong, which is worth
# writing down because it looks right and it was tried.
#
# Which backends exist is decided when libseat is compiled, and the build host
# is not the image. This tree builds on Ubuntu, whose libseat carries `logind`
# and `builtin` and no `seatd`. The Arch image it produces carries `seatd` and
# `logind` and no `builtin`. So checking the host's library would have failed
# on the correct setting and passed on the one that was broken, which is worse
# than not checking at all.
#
# The library that matters is the one pacman installs during the ISO build, and
# it does not exist when this runs. Naming no backend is what makes that
# unanswerable question stop mattering.

# The daemon is on the image, and it is enabled. Being on the image was already
# true and was not enough: nothing started it, so the socket every entry needs
# was never there.
grep -Fxq 'seatd' "$ROOT/installer/archiso/packages.x86_64" || {
  echo 'test-renderer-chain: seatd is not on the image' >&2
  exit 1
}
grep -Fq 'multi-user.target.wants/seatd.service' "$ROOT/installer/build-iso.sh" || {
  echo 'test-renderer-chain: seatd is on the image and nothing starts it' >&2
  exit 1
}

# --- a dumb framebuffer is not negotiated with ---------------------------------
#
# The negotiation tries things for real rather than predicting them, because
# predicting graphics is how you refuse to draw on a machine that would have
# been fine. But there is a difference between a driver that might not manage
# GL and one that has no GL at all, and for the second an attempt is not
# evidence, it is a wait. On a virtual machine that wait is most of the black
# screen somebody sits through.
install -d "$TMP/dumb-dri" "$TMP/dumb-drm/card0/device" "$TMP/dumb-drm/card0-Virtual-1"
: >"$TMP/dumb-dri/card0"
# Real kernels publish this driver as `bochs-drm`, not `bochs`; the shortcut
# has to fire on the name the kernel actually reports, suffix and all.
printf 'DRIVER=bochs-drm\n' >"$TMP/dumb-drm/card0/device/uevent"
printf 'connected\n' >"$TMP/dumb-drm/card0-Virtual-1/status"

AURADE_RENDERER_DRI_DIR="$TMP/dumb-dri" AURADE_RENDERER_DRM_DIR="$TMP/dumb-drm" \
  bash -c '. "'"$ROOT"'/installer/lib/aurade-renderers.sh"; aurade_renderer_plan' >"$TMP/dumb.plan"
refute grep -q 'WLR_RENDERER=gles2 WLR_DRM_DEVICES=' "$TMP/dumb.plan"
refute grep -q 'WLR_RENDERER=vulkan' "$TMP/dumb.plan"
grep -q 'WLR_RENDERER=pixman' "$TMP/dumb.plan" ||
  { echo 'test-renderer-chain: a dumb framebuffer got no way to draw at all' >&2; exit 1; }
# The software entries at the end are still there, because a card that cannot
# be opened at all still has to fall through to something.
grep -q 'software OpenGL' "$TMP/dumb.plan" ||
  { echo 'test-renderer-chain: the software fallbacks were dropped along with the accelerated ones' >&2; exit 1; }

AURADE_RENDERER_DRI_DIR="$TMP/dumb-dri" AURADE_RENDERER_DRM_DIR="$TMP/dumb-drm" \
  bash -c '. "'"$ROOT"'/installer/lib/aurade-renderers.sh"; aurade_renderer_client_plan' >"$TMP/dumb.clients"
[[ $(wc -l <"$TMP/dumb.clients") -eq 1 ]] ||
  { echo "test-renderer-chain: a machine with no 3D got $(wc -l <"$TMP/dumb.clients") client attempts, not 1" >&2; exit 1; }
grep -q 'GSK_RENDERER=cairo' "$TMP/dumb.clients" ||
  { echo 'test-renderer-chain: the one client attempt on a dumb framebuffer still asks for hardware' >&2; exit 1; }

# And a real card is still negotiated with, because "might not manage GL" is
# exactly the case the chain exists for and predicting it is how a working
# graphics card gets refused.
AURADE_RENDERER_DRI_DIR="$TMP/dri" AURADE_RENDERER_DRM_DIR="$TMP/drm" \
  bash -c '. "'"$ROOT"'/installer/lib/aurade-renderers.sh"; aurade_renderer_plan' >"$TMP/real.plan"
grep -q 'WLR_RENDERER=gles2 WLR_DRM_DEVICES=' "$TMP/real.plan" ||
  { echo 'test-renderer-chain: a real graphics card was skipped as though it had no 3D' >&2; exit 1; }

# VMware's vmwgfx driver can expose a working DRM device while its accelerated
# Wayland buffer path fails after the first GTK window maps. The launcher must
# show the software page first on that known adapter, instead of making a user
# wait through the accelerated matrix, while keeping those candidates available
# below as fallbacks.
install -d "$TMP/vm-dri" "$TMP/vm-drm/card0/device" "$TMP/vm-drm/card0-Virtual-1"
: >"$TMP/vm-dri/card0"
printf 'DRIVER=vmwgfx\n' >"$TMP/vm-drm/card0/device/uevent"
printf 'connected\n' >"$TMP/vm-drm/card0-Virtual-1/status"

AURADE_RENDERER_DRI_DIR="$TMP/vm-dri" AURADE_RENDERER_DRM_DIR="$TMP/vm-drm" \
  bash -c '. "'"$ROOT"'/installer/lib/aurade-renderers.sh"; aurade_renderer_plan' \
  >"$TMP/vm.plan"
vm_first=$(head -n 1 "$TMP/vm.plan")
[[ $vm_first == *WLR_RENDERER=pixman* ]] ||
  { echo 'test-renderer-chain: vmwgfx did not get the software-first compositor path' >&2; exit 1; }
grep -q 'WLR_RENDERER=gles2 WLR_DRM_DEVICES=' "$TMP/vm.plan" ||
  { echo 'test-renderer-chain: vmwgfx lost its accelerated fallback' >&2; exit 1; }

AURADE_RENDERER_DRI_DIR="$TMP/vm-dri" AURADE_RENDERER_DRM_DIR="$TMP/vm-drm" \
  bash -c '. "'"$ROOT"'/installer/lib/aurade-renderers.sh"; aurade_renderer_client_plan' \
  >"$TMP/vm.clients"
vm_client_first=$(head -n 1 "$TMP/vm.clients")
[[ $vm_client_first == *GSK_RENDERER=cairo* ]] ||
  { echo 'test-renderer-chain: vmwgfx did not get the software-first client path' >&2; exit 1; }
grep -q 'GTK hardware drawing' "$TMP/vm.clients" ||
  { echo 'test-renderer-chain: vmwgfx lost its accelerated client fallback' >&2; exit 1; }

echo 'installer renderer chain test: PASS'
