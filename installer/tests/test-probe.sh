#!/usr/bin/env bash
# The renderer probe, against fixture roots.
#
# The probe's job is to notice, before the erase gate, that the desktop being
# installed will not start on this machine. That failure mode - install
# succeeds, first boot is black, disk is already gone - is the worst one the
# product has, so the probe is tested against each condition that produces it
# rather than against the one machine that happens to be running the suite.
#
# The distinction the tests below insist on: a missing GPU predicts a black
# screen after installation, and low memory on the live image does not. The
# installed system has more memory available than the live image does, and
# telling a user their computer will not work when it will is its own failure.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fail() { echo "test-probe: $*" >&2; exit 1; }
check() { [[ $2 == "$3" ]] || fail "$1: expected '$3', got '$2'"; }

mem() { printf 'MemTotal:       %s kB\nMemAvailable:   %s kB\n' "$2" "$1" >"$TMP/meminfo.$3"; }
mem 16000000 16777216 big
mem 3900000 4194304 small

install -d "$TMP/vm-bin"
printf '#!/bin/sh\necho vmware\n' >"$TMP/vm-bin/systemd-detect-virt"
chmod +x "$TMP/vm-bin/systemd-detect-virt"

# Firmware probes use bootctl when available and otherwise read EFI state.
# These tiny fixtures keep the UI's early warning testable without fabricating
# firmware variables or touching the host's real efivars.
install -d "$TMP/boot-disabled" "$TMP/boot-enabled" "$TMP/empty-path" "$TMP/efi"
printf '#!/bin/sh\nprintf disabled\n' >"$TMP/boot-disabled/bootctl"
printf '#!/bin/sh\nprintf enabled\n' >"$TMP/boot-enabled/bootctl"
chmod +x "$TMP/boot-disabled/bootctl" "$TMP/boot-enabled/bootctl"

install -d "$TMP/dri-empty" "$TMP/dri-ok"
: >"$TMP/dri-ok/renderD128"
: >"$TMP/dri-ok/card0"

# A sysfs tree that says which driver is behind each render node. Without it a
# render node is just a device file, which is the overclaim these tests guard.
drm_tree() {
  local root=$1 node=$2 driver=$3
  install -d "$root/$node/device"
  printf 'DRIVER=%s\nMODALIAS=pci:v00008086\n' "$driver" >"$root/$node/device/uevent"
}
install -d "$TMP/drm-real" "$TMP/drm-virtual" "$TMP/drm-empty"
drm_tree "$TMP/drm-real" renderD128 i915
drm_tree "$TMP/drm-virtual" renderD128 vgem
install -d "$TMP/drm-vmware"
drm_tree "$TMP/drm-vmware" renderD128 vmwgfx
install -d "$TMP/dri-virtual"
: >"$TMP/dri-virtual/renderD128"

probe() {
  # A fresh shell each time: the probe sets globals, and a test that reused
  # them could pass on a value left behind by the previous case.
  env -u DISPLAY -u WAYLAND_DISPLAY AURADE_PROBE_GL_TIMEOUT=0.2 \
    AURADE_PROBE_DRI_DIR="$1" AURADE_PROBE_MEMINFO="$2" \
    AURADE_PROBE_MIN_GUI_MIB="${3:-6144}" AURADE_FORCE_TUI="${4:-0}" \
    AURADE_PROBE_DRM_DIR="${5:-$TMP/drm-empty}" PATH="${6:-$PATH}" \
    bash -c '
      set -Eeuo pipefail
      . '"$ROOT"'/installer/lib/aurade-probe.sh
      aurade_probe_renderer
      printf "%s|%s|%s|%s\n" "$AURADE_PROBE_RENDERER" "$AURADE_PROBE_REASON" \
        "$(aurade_probe_predicts_black_screen && printf yes || printf no)" \
        "$AURADE_PROBE_GRAPHICS"
    '
}

secure_state() {
  env AURADE_PROBE_EFI_DIR="$1" PATH="$2" /bin/bash -c '
    set -Eeuo pipefail
    . '"$ROOT"'/installer/lib/aurade-probe.sh
    aurade_probe_secure_boot
  '
}

check 'secure boot disabled fixture' "$(secure_state "$TMP/efi" "$TMP/boot-disabled")" disabled
check 'secure boot enabled fixture' "$(secure_state "$TMP/efi" "$TMP/boot-enabled")" enabled
check 'secure boot unknown fixture' "$(secure_state "$TMP/efi" "$TMP/empty-path")" unknown
check 'secure boot not applicable fixture' "$(secure_state "$TMP/absent-efi" "$TMP/empty-path")" not-applicable

# --- no DRM directory at all: no GPU driver loaded --------------------------
IFS='|' read -r renderer reason black graphics < <(probe "$TMP/absent" "$TMP/meminfo.big")
check 'no dri dir renderer' "$renderer" tui
check 'no dri dir reason' "$reason" no-dri-dir
check 'no dri dir predicts black screen' "$black" yes

# --- DRM directory present but no render node -------------------------------
IFS='|' read -r renderer reason black graphics < <(probe "$TMP/dri-empty" "$TMP/meminfo.big")
check 'no render node renderer' "$renderer" tui
check 'no render node reason' "$reason" no-render-node
check 'no render node predicts black screen' "$black" yes
[[ $graphics == *renderD* ]] || fail 'the graphics detail does not name what was missing'

# --- render node present, but not enough memory for the live graphical path -
IFS='|' read -r renderer reason black graphics < <(probe "$TMP/dri-ok" "$TMP/meminfo.small")
check 'low memory renderer' "$renderer" tui
check 'low memory reason' "$reason" low-memory
check 'low memory does not predict a black screen' "$black" no

# --- render node and memory both fine ---------------------------------------
IFS='|' read -r renderer reason black graphics < <(probe "$TMP/dri-ok" "$TMP/meminfo.big")
check 'healthy renderer' "$renderer" gui
check 'healthy reason' "$reason" ok
check 'healthy does not predict a black screen' "$black" no
[[ $graphics == *renderD128* ]] || fail 'the probe did not report the render node it found'

# --- an operator can force the text installer -------------------------------
IFS='|' read -r renderer reason black graphics < <(probe "$TMP/dri-ok" "$TMP/meminfo.big" 6144 1)
check 'forced renderer' "$renderer" tui
check 'forced reason' "$reason" forced
check 'forcing text mode does not predict a black screen' "$black" no

# --- an unreadable meminfo is treated as not enough memory, not as a crash --
IFS='|' read -r renderer reason black graphics < <(probe "$TMP/dri-ok" "$TMP/absent-meminfo")
check 'unreadable meminfo renderer' "$renderer" tui
check 'unreadable meminfo reason' "$reason" low-memory

# --- a render node is not a claim about 3D acceleration ---------------------
# A renderD* device file proves a driver published a node. It does not prove
# working acceleration, and a screen that says otherwise is how a user comes to
# trust this check and then meets a black desktop.
advice_for() {
  env -u DISPLAY -u WAYLAND_DISPLAY AURADE_PROBE_GL_TIMEOUT=0.2 \
    AURADE_PROBE_DRI_DIR="$1" AURADE_PROBE_MEMINFO="$TMP/meminfo.big" \
    AURADE_PROBE_DRM_DIR="${2:-$TMP/drm-empty}" PATH="${3:-$PATH}" bash -c '
      set -Eeuo pipefail
      . '"$ROOT"'/installer/lib/aurade-probe.sh
      aurade_probe_renderer
      aurade_probe_advice
    '
}
healthy_advice=$(advice_for "$TMP/dri-ok" "$TMP/drm-real")
[[ $healthy_advice != *'can run the AuraDE desktop'* ]] ||
  fail 'the probe still claims a render node proves the desktop will run'
[[ $healthy_advice == *i915* ]] ||
  fail 'the probe does not name the driver it actually found'
[[ $healthy_advice == *'only proven once the desktop starts'* ]] ||
  fail 'the probe does not say what it has not established'

# The driver is reported in the graphics detail too.
IFS='|' read -r renderer reason black graphics < \
  <(probe "$TMP/dri-ok" "$TMP/meminfo.big" 6144 0 "$TMP/drm-real")
check 'real driver renderer' "$renderer" gui
check 'real driver reason' "$reason" ok
[[ $graphics == *'driver i915'* ]] || fail "the driver is missing from the detail: $graphics"

# --- a virtual device is not a GPU ------------------------------------------
# vgem and vkms publish render nodes and have no display output, so a check
# that stops at "a render node exists" counts them as working graphics.
IFS='|' read -r renderer reason black graphics < \
  <(probe "$TMP/dri-virtual" "$TMP/meminfo.big" 6144 0 "$TMP/drm-virtual")
check 'virtual gpu renderer' "$renderer" tui
check 'virtual gpu reason' "$reason" virtual-gpu-only
check 'virtual gpu predicts a black screen' "$black" yes
[[ $graphics == *vgem* ]] || fail 'the virtual device was not named'
virtual_advice=$(advice_for "$TMP/dri-virtual" "$TMP/drm-virtual")
[[ $virtual_advice == *'will not start'* ]] ||
  fail 'the virtual-device advice does not say the desktop will not start'

# --- the optional GL probe is optional, bounded, and believed when present --
install -d "$TMP/gl-soft" "$TMP/gl-hard" "$TMP/gl-broken"
printf '#!/bin/sh\necho "OpenGL renderer string: llvmpipe (LLVM 16.0.6, 256 bits)"\n' \
  >"$TMP/gl-soft/eglinfo"
printf '#!/bin/sh\necho "OpenGL renderer string: Mesa Intel(R) UHD Graphics 620"\n' \
  >"$TMP/gl-hard/eglinfo"
printf '#!/bin/sh\nexit 1\n' >"$TMP/gl-broken/eglinfo"
chmod +x "$TMP"/gl-*/eglinfo

IFS='|' read -r renderer reason black graphics < \
  <(probe "$TMP/dri-ok" "$TMP/meminfo.big" 6144 0 "$TMP/drm-real" "$TMP/gl-soft:$PATH")
check 'software rendering renderer' "$renderer" tui
check 'software rendering reason' "$reason" software-rendering
check 'software rendering is not a black screen' "$black" no
[[ $graphics == *llvmpipe* ]] || fail 'the software renderer was not reported'
soft_advice=$(advice_for "$TMP/dri-ok" "$TMP/drm-real" "$TMP/gl-soft:$PATH")
[[ $soft_advice == *'drawn in software'* ]] ||
  fail 'the software-rendering advice does not explain itself'
[[ $soft_advice != *'will not start'* ]] ||
  fail 'software rendering was described as a machine that cannot run the desktop'

IFS='|' read -r renderer reason black graphics < \
  <(probe "$TMP/dri-ok" "$TMP/meminfo.big" 6144 0 "$TMP/drm-real" "$TMP/gl-hard:$PATH")
check 'hardware rendering renderer' "$renderer" gui
check 'hardware rendering reason' "$reason" ok
hard_advice=$(advice_for "$TMP/dri-ok" "$TMP/drm-real" "$TMP/gl-hard:$PATH")
[[ $hard_advice == *'Hardware rendering is available'* ]] ||
  fail 'a real renderer was not reported as hardware rendering'

# VMware can publish a render node while a headless live console still lacks a
# visible DRM output for Cage. Auto mode must choose the text path instead of
# presenting a blank compositor screen; the explicit override remains covered
# below so this is not a way to disable GUI diagnostics.
IFS='|' read -r renderer reason black graphics < \
  <(probe "$TMP/dri-ok" "$TMP/meminfo.big" 6144 0 "$TMP/drm-vmware" "$TMP/vm-bin:$PATH")
check 'headless vmware renderer' "$renderer" tui
check 'headless vmware reason' "$reason" vmware-kms-uncertain
check 'headless vmware does not predict black screen' "$black" no
vmware_gui_advice=$(advice_for "$TMP/dri-ok" "$TMP/drm-vmware" "$TMP/vm-bin:$PATH")
[[ $vmware_gui_advice == *'visible DRM output'* ]] ||
  fail 'headless VMware advice does not explain the display limitation'

vmware_override=$(env \
  AURADE_ALLOW_VMWARE_GUI=1 AURADE_PROBE_GL_TIMEOUT=0.2 \
  AURADE_PROBE_DRI_DIR="$TMP/dri-ok" AURADE_PROBE_MEMINFO="$TMP/meminfo.big" \
  AURADE_PROBE_DRM_DIR="$TMP/drm-vmware" PATH="$TMP/vm-bin:$PATH" bash -c '
    set -Eeuo pipefail
    . '"$ROOT"'/installer/lib/aurade-probe.sh
    aurade_probe_renderer
    printf "%s|%s\n" "$AURADE_PROBE_RENDERER" "$AURADE_PROBE_REASON"
  ')
[[ $vmware_override == 'gui|ok' ]] ||
  fail "explicit VMware GUI override was ignored: $vmware_override"

# A broken or absent eglinfo must leave the sysfs result exactly as it was.
IFS='|' read -r renderer reason black graphics < \
  <(probe "$TMP/dri-ok" "$TMP/meminfo.big" 6144 0 "$TMP/drm-real" "$TMP/gl-broken:$PATH")
check 'broken eglinfo renderer' "$renderer" gui
check 'broken eglinfo reason' "$reason" ok
[[ $graphics != *renderer* ]] || fail 'a failing GL probe still claimed a renderer'

# --- the pre-erase warning for a missing GPU is unchanged -------------------
IFS='|' read -r renderer reason black graphics < \
  <(probe "$TMP/dri-empty" "$TMP/meminfo.big" 6144 0 "$TMP/drm-real")
check 'no render node renderer, still' "$renderer" tui
check 'no render node reason, still' "$reason" no-render-node
check 'no render node still predicts a black screen' "$black" yes

# --- the probe never fails ---------------------------------------------------
# The front end runs under `set -e`. A probe that exits non-zero for the
# ordinary "no graphics here" case would abort the installer rather than fall
# back to it, which is exactly the failure this file exists to prevent.
env AURADE_PROBE_DRI_DIR="$TMP/absent" AURADE_PROBE_MEMINFO="$TMP/absent" bash -c '
  set -Eeuo pipefail
  . '"$ROOT"'/installer/lib/aurade-probe.sh
  aurade_probe_renderer
  echo reached-the-end
' >"$TMP/errexit.out" 2>&1 || fail 'the probe aborted a script running under set -e'
grep -Fq reached-the-end "$TMP/errexit.out" || fail 'the probe did not return control'

# --- advice is specific, and names the virtual machine when there is one -----
advice() {
  env -u DISPLAY -u WAYLAND_DISPLAY AURADE_PROBE_GL_TIMEOUT=0.2 \
    AURADE_PROBE_DRI_DIR="$TMP/absent" AURADE_PROBE_MEMINFO="$TMP/meminfo.big" \
    PATH="$1:$PATH" bash -c '
      set -Eeuo pipefail
      . '"$ROOT"'/installer/lib/aurade-probe.sh
      aurade_probe_renderer
      aurade_probe_advice
    '
}
install -d "$TMP/vm-bin" "$TMP/bare-bin"
printf '#!/bin/sh\necho vmware\n' >"$TMP/vm-bin/systemd-detect-virt"
printf '#!/bin/sh\necho none\n' >"$TMP/bare-bin/systemd-detect-virt"
chmod +x "$TMP/vm-bin/systemd-detect-virt" "$TMP/bare-bin/systemd-detect-virt"

vm_advice=$(advice "$TMP/vm-bin")
[[ $vm_advice == *vmware* ]] || fail 'the advice does not name the virtual machine type'
[[ $vm_advice == *'display settings'* ]] ||
  fail 'the advice does not tell a VM user where to enable 3D'

bare_advice=$(advice "$TMP/bare-bin")
[[ $bare_advice != *'display settings'* ]] ||
  fail 'bare metal was given virtual machine advice'
[[ $bare_advice == *'no working graphics driver'* ]] ||
  fail 'bare metal was not told what is actually wrong'

# --- every reason code has advice written for it -----------------------------
for reason in ok forced no-dri-dir no-render-node low-memory virtual-gpu-only software-rendering vmware-kms-uncertain; do
  text=$(env -u DISPLAY -u WAYLAND_DISPLAY AURADE_PROBE_GL_TIMEOUT=0.2 \
    AURADE_PROBE_DRI_DIR="$TMP/dri-ok" AURADE_PROBE_MEMINFO="$TMP/meminfo.big" bash -c '
    . '"$ROOT"'/installer/lib/aurade-probe.sh
    AURADE_PROBE_VIRT=none
    aurade_probe_advice '"$reason"'
  ')
  [[ -n $text ]] || fail "reason '$reason' has no advice"
  [[ $text != 'Continuing in text mode.' ]] ||
    fail "reason '$reason' fell through to the catch-all advice"
done

# --- the fallback screen renders what the probe found ------------------------
render_fallback() {
  env AURADE_PROBE_DRI_DIR="$1" AURADE_PROBE_MEMINFO="$2" \
    AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii PATH="$3:$PATH" \
    "$ROOT/installer/bin/aurade-installer-tui" --render fallback
}
render_fallback "$TMP/absent" "$TMP/meminfo.big" "$TMP/vm-bin" >"$TMP/fallback.out"
grep -Fq 'Running the text installer' "$TMP/fallback.out" ||
  fail 'the fallback screen does not say what it is doing'
grep -Fq 'no working 3D acceleration' "$TMP/fallback.out" ||
  fail 'the fallback screen does not explain why the graphical installer did not start'
grep -Fq 'vmware' "$TMP/fallback.out" ||
  fail 'the fallback screen does not pass the virtual machine advice through'
grep -Fq 'enable 3D' "$TMP/fallback.out" ||
  fail 'the fallback screen does not tell the user what to change'

# Low memory is a different message: it must not claim the desktop is broken.
render_fallback "$TMP/dri-ok" "$TMP/meminfo.small" "$TMP/bare-bin" >"$TMP/lowmem.out"
grep -Fq 'not enough free memory' "$TMP/lowmem.out" ||
  fail 'the low-memory fallback does not explain itself'
! grep -Fq 'no working 3D acceleration' "$TMP/lowmem.out" ||
  fail 'a low-memory machine was told it has no 3D acceleration'

echo 'installer graphics probe test: PASS'
