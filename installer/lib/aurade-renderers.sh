# shellcheck shell=bash
# shellcheck disable=SC2034  # the AURADE_RENDERER_* results are read by the
#                              launcher that sources this file, across a
#                              boundary shellcheck cannot see.
# Renderer and cursor settings used by the graphical installer. The launcher
# tries accelerated paths first, then software fallbacks. Probe paths are
# overridable so the selection can be exercised on a build host.

# Compose the cursor in software; this works on virtual GPUs with no usable
# hardware cursor plane. Set the theme explicitly for both the compositor and
# GTK clients.
AURADE_RENDERER_CURSOR='WLR_NO_HARDWARE_CURSORS=1 XCURSOR_THEME=Adwaita XCURSOR_SIZE=24'
# GTK reads its own cursor settings.
AURADE_CLIENT_CURSOR='XCURSOR_THEME=Adwaita XCURSOR_SIZE=24'

AURADE_RENDERER_DRI_DIR=${AURADE_RENDERER_DRI_DIR:-${AURADE_PROBE_DRI_DIR:-/dev/dri}}
AURADE_RENDERER_DRM_DIR=${AURADE_RENDERER_DRM_DIR:-${AURADE_PROBE_DRM_DIR:-/sys/class/drm}}
AURADE_RENDERER_VULKAN_DIR=${AURADE_RENDERER_VULKAN_DIR:-/usr/share/vulkan/icd.d}

# Drivers that publish a render node but drive no display. Same list the probe
# uses, and for the same reason: a chain that tries to put a compositor on vkms
# spends two attempts finding out it cannot.
AURADE_RENDERER_EXCLUDED=${AURADE_RENDERER_EXCLUDED:-vgem vkms}

# VMware's virtual display is more reliable with software rendering first.
# Keep the setting overridable for other virtual adapters.
AURADE_RENDERER_SOFTWARE_FIRST=${AURADE_RENDERER_SOFTWARE_FIRST:-vmwgfx}

# Drivers that drive a display and have no 3D behind them, so asking for one
# can only ever fail.
#
# This is the shortcut worth having, and virtual machines are where it pays.
# The negotiation is written to try things for real rather than predict them,
# because predicting graphics is how you end up refusing to draw on a machine
# that would have been fine. But there is a difference between a driver that
# might not manage GL and a driver that has no GL implementation at all, and
# for the second kind an attempt is not evidence gathering, it is a wait.
#
# `bochs` and `qxl` are QEMU without virtio-gpu, `hyperv_drm` is Hyper-V,
# `vboxvideo` is VirtualBox without its additions, `simpledrm` is whatever the
# firmware left in the framebuffer, and `cirrus` and `vesa` are museums. Every
# one of them is a dumb framebuffer. A machine with only these gets software
# rendering as its first attempt rather than its third, which on a VM is the
# difference between a few seconds and most of a minute of black screen.
#
# vmwgfx, virtio_gpu, i915, amdgpu, radeon and nouveau are deliberately not
# here. All of them can do GL and all of them sometimes cannot, and that is
# exactly the case the negotiation exists for.
AURADE_RENDERER_NO_GL=${AURADE_RENDERER_NO_GL:-bochs qxl cirrus hyperv_drm vboxvideo simpledrm vesa ast mgag200}

#: Whether this driver has any 3D worth asking for.
_renderer_accelerated() {
  local driver=$1 dumb
  # An unknown driver is treated as capable, because the cost of trying and
  # failing is one attempt and the cost of assuming wrongly is a machine that
  # never draws with its graphics card.
  [[ -n $driver ]] || return 0
  for dumb in $AURADE_RENDERER_NO_GL; do
    [[ $driver != "$dumb" ]] || return 1
  done
  return 0
}

_renderer_software_first() {
  local driver=$1 preferred
  [[ -n $driver ]] || return 1
  for preferred in $AURADE_RENDERER_SOFTWARE_FIRST; do
    [[ $driver == "$preferred" ]] && return 0
  done
  return 1
}

aurade_renderer_prefers_software() {
  local card driver
  while IFS= read -r card; do
    [[ -n $card ]] || continue
    driver=$(_renderer_driver_for "$card")
    _renderer_software_first "$driver" && return 0
  done < <(aurade_renderer_cards)
  return 1
}

#: Whether any card on this machine has 3D worth asking for. Read by the client
#: plan, which has the same question to answer about GTK.
aurade_renderer_any_accelerated() {
  local card driver
  while IFS= read -r card; do
    [[ -n $card ]] || continue
    driver=$(_renderer_driver_for "$card")
    _renderer_accelerated "$driver" && return 0
  done < <(aurade_renderer_cards)
  return 1
}

_renderer_driver_for() {
  local card=$1 uevent
  uevent="$AURADE_RENDERER_DRM_DIR/${card##*/}/device/uevent"
  [[ -r $uevent ]] || return 0
  awk -F= '/^DRIVER=/ { print $2; exit }' "$uevent" 2>/dev/null || true
}

# Whether anything is plugged into this card. A connector directory is named
# `cardN-<CONNECTOR>` and carries a `status` file reading `connected` or
# `disconnected`; the card itself has no status.
_renderer_has_output() {
  local card=${1##*/} connector status
  for connector in "$AURADE_RENDERER_DRM_DIR/$card"-*; do
    [[ -r $connector/status ]] || continue
    read -r status <"$connector/status" 2>/dev/null || continue
    [[ $status == connected ]] || continue
    return 0
  done
  return 1
}

_renderer_vulkan_available() {
  local icd
  for icd in "$AURADE_RENDERER_VULKAN_DIR"/*.json; do
    [[ -r $icd ]] || continue
    return 0
  done
  return 1
}

_renderer_excluded() {
  local driver=$1 excluded
  [[ -n $driver ]] || return 1
  for excluded in $AURADE_RENDERER_EXCLUDED; do
    [[ $driver != "$excluded" ]] || return 0
  done
  return 1
}

# The cards this machine has, with the ones wired to a display first.
#
# Order within each group is whatever the kernel numbered them, which is
# stable across a boot and is the only ordering available without asking a
# graphics API - and asking a graphics API is the thing that fails on exactly
# the machines this list exists for.
aurade_renderer_cards() {
  local card driver connected=() disconnected=()
  for card in "$AURADE_RENDERER_DRI_DIR"/card*; do
    [[ -e $card ]] || continue
    driver=$(_renderer_driver_for "$card")
    _renderer_excluded "$driver" && continue
    if _renderer_has_output "$card"; then
      connected+=("$card")
    else
      disconnected+=("$card")
    fi
  done
  printf '%s\n' ${connected[@]+"${connected[@]}"} ${disconnected[@]+"${disconnected[@]}"}
}

# One candidate per line: `LABEL<TAB>KEY=VALUE KEY=VALUE ...`
#
# The label is what the user is told is being tried, so it names the hardware
# rather than the API where it can.
aurade_renderer_plan() {
  local card driver vulkan=0 label
  _renderer_vulkan_available && vulkan=1

  # Safe graphics: the floor, and only the floor.
  #
  # The negotiation is good at finding a path that works and cannot see a
  # driver that reports success and then draws nothing - the failure that
  # produces a black screen with no message and no way back. This is the boot
  # entry for that machine: skip every accelerated path, including the ones
  # that would appear to work.
  if [[ ${AURADE_SAFE_GRAPHICS:-0} == 1 ]]; then
    printf '%s\t%s\n' 'software (pixman)' \
      "$AURADE_RENDERER_CURSOR WLR_RENDERER=pixman"
    return 0
  fi

  # An explicit choice is tried first and never discarded. Someone who typed
  # `WLR_RENDERER=pixman aurade-installer-start` has already worked out
  # something about this machine, and silently overriding them - which is what
  # the per-attempt `env` does - turns their finding into a mystery.
  if [[ -n ${WLR_RENDERER:-} ]]; then
    printf '%s\t%s\n' "$WLR_RENDERER (from the environment)" \
      "$AURADE_RENDERER_CURSOR WLR_RENDERER=$WLR_RENDERER${WLR_DRM_DEVICES:+ WLR_DRM_DEVICES=$WLR_DRM_DEVICES}"
  fi

  # vmwgfx is the one supported virtual adapter whose accelerated path is
  # known to fail after mapping on common VMware guests. Reach a usable page
  # immediately, then keep the normal candidates below as a recovery path.
  if [[ -z ${WLR_RENDERER:-} ]] && aurade_renderer_prefers_software; then
    printf '%s\t%s\n' 'virtual graphics (software first)' \
      "$AURADE_RENDERER_CURSOR WLR_RENDERER=pixman"
  fi

  while IFS= read -r card; do
    [[ -n $card ]] || continue
    driver=$(_renderer_driver_for "$card")
    label=${driver:-graphics}
    # A dumb framebuffer gets one entry and it is the one that works. Offering
    # it Vulkan and then GLES is two attempts spent proving something already
    # known from the driver's name.
    if ! _renderer_accelerated "$driver"; then
      printf '%s\t%s\n' "$label (software)" \
        "$AURADE_RENDERER_CURSOR WLR_RENDERER=pixman WLR_DRM_DEVICES=$card"
      continue
    fi
    if (( vulkan )); then
      printf '%s\t%s\n' "$label (Vulkan)" \
        "$AURADE_RENDERER_CURSOR WLR_RENDERER=vulkan WLR_DRM_DEVICES=$card"
    fi
    printf '%s\t%s\n' "$label (OpenGL)" \
      "$AURADE_RENDERER_CURSOR WLR_RENDERER=gles2 WLR_DRM_DEVICES=$card"
  done < <(aurade_renderer_cards)

  # Software GL. Still a real GL context for GTK, and it works on a machine
  # whose kernel driver loaded but whose userspace acceleration did not.
  printf '%s\t%s\n' 'software OpenGL' \
    "$AURADE_RENDERER_CURSOR WLR_RENDERER=gles2 LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe"

  # The floor. No GL at all on the compositor side: wlroots composites with
  # pixman. This is the one that cannot fail for want of a driver, which is
  # why it is last and why it is always present.
  printf '%s\t%s\n' 'software (pixman)' \
    "$AURADE_RENDERER_CURSOR WLR_RENDERER=pixman"
}

# What to try on the *client* side, for a compositor that already started.
#
# A working compositor is only half of it. GTK 4 picks its own drawing path -
# Vulkan, then GL, then cairo - and on a virtual GPU the paths that look
# available are frequently the ones that do not work: the driver advertises
# dma-buf import, GTK hands the compositor a buffer built on a modifier the
# driver cannot actually share, and the Wayland connection dies with a
# protocol error a fraction of a second after the window appears. That is a
# black screen too, and no amount of changing the compositor's renderer fixes
# it, because the compositor was never the thing that failed.
#
# So each compositor that manages to draw gets these tried under it, in order,
# and the launcher can tell the two axes apart: a window that never appeared
# is the compositor's fault, and a window that appeared and then died is this
# list's problem.
#
# `GDK_BACKEND=wayland` is on every entry rather than left to autodetection.
# Inside `cage` there is no X server to fall back to, so an autodetected
# fallback can only ever end in a less specific failure message.
aurade_renderer_client_plan() {
  if [[ ${AURADE_SAFE_GRAPHICS:-0} == 1 ]]; then
    printf '%s\t%s\n' 'GTK software drawing' \
      "GDK_BACKEND=wayland $AURADE_CLIENT_CURSOR GSK_RENDERER=cairo GDK_DISABLE=dmabuf,offload,vulkan,gl LIBGL_ALWAYS_SOFTWARE=1"
    return 0
  fi

  # As with the compositor list, an explicit choice is honoured first.
  if [[ -n ${GSK_RENDERER:-} ]]; then
    printf '%s\t%s\n' "GTK $GSK_RENDERER (from the environment)" \
      "GDK_BACKEND=wayland $AURADE_CLIENT_CURSOR GSK_RENDERER=$GSK_RENDERER"
  fi

  # Keep VMware's first visible attempt on the same reliable software path as
  # the compositor. If cairo itself is unavailable, the existing GL entries
  # below remain available and the launcher still negotiates them normally.
  if [[ -z ${GSK_RENDERER:-} ]] && aurade_renderer_prefers_software; then
    printf '%s\t%s\n' 'GTK software drawing (virtual graphics)' \
      "GDK_BACKEND=wayland $AURADE_CLIENT_CURSOR GSK_RENDERER=cairo GDK_DISABLE=dmabuf,offload,vulkan,gl LIBGL_ALWAYS_SOFTWARE=1"
  fi

  # The same shortcut on the client side. On a machine whose only display
  # driver is a dumb framebuffer there is no hardware for GTK to draw with
  # either, and asking for it is one more window that opens and dies.
  if ! aurade_renderer_any_accelerated; then
    printf '%s\t%s\n' 'GTK software drawing' \
      "GDK_BACKEND=wayland $AURADE_CLIENT_CURSOR GSK_RENDERER=cairo GDK_DISABLE=dmabuf,offload,vulkan,gl LIBGL_ALWAYS_SOFTWARE=1"
    return 0
  fi

  printf '%s\t%s\n' 'GTK hardware drawing' \
    "GDK_BACKEND=wayland $AURADE_CLIENT_CURSOR"

  # Same GL, without the buffer-sharing shortcuts. This is the entry that
  # covers the common virtual-GPU failure above, and it still draws with GL.
  printf '%s\t%s\n' 'GTK without buffer sharing' \
    "GDK_BACKEND=wayland $AURADE_CLIENT_CURSOR GSK_RENDERER=gl GDK_DISABLE=dmabuf,offload,vulkan"

  # No GL on the client side at all. Cairo through shared memory is the oldest
  # and least demanding thing GTK can do, and it is the counterpart of pixman:
  # slow, correct, and dependent on nothing but the compositor being there.
  printf '%s\t%s\n' 'GTK software drawing' \
    "GDK_BACKEND=wayland $AURADE_CLIENT_CURSOR GSK_RENDERER=cairo GDK_DISABLE=dmabuf,offload,vulkan,gl LIBGL_ALWAYS_SOFTWARE=1"
}
