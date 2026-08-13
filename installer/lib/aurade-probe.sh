# shellcheck shell=bash
# shellcheck disable=SC2034  # the AURADE_PROBE_* results are read by whichever
#                              front end sources this file, which shellcheck
#                              cannot see across the source boundary.
# Renderer probe: decides whether a graphical installer can run, and explains
# itself when it cannot.
#
# This is the black-screen guarantee, and it is worth being precise about what
# it is guarding. The worst failure this product can have is not a failed
# install; it is a successful one, followed by a permanently black screen on
# first boot, on a machine whose disk has already been erased. The installer
# runs on the same graphics stack the desktop will, so the conditions for that
# failure are all observable here, while the disk is still intact and the user
# can still walk away.
#
# So the probe has two jobs, and the second is the important one. It picks a
# renderer, and it tells the user - before the erase gate, not after - that the
# desktop they are about to install will not start on this machine.
#
# Every lookup root is injectable. A probe that can only be tested on hardware
# that reproduces the failure is a probe that ships untested.

AURADE_PROBE_DRI_DIR=${AURADE_PROBE_DRI_DIR:-/dev/dri}
AURADE_PROBE_MEMINFO=${AURADE_PROBE_MEMINFO:-/proc/meminfo}
AURADE_PROBE_DRM_DIR=${AURADE_PROBE_DRM_DIR:-/sys/class/drm}

# Render nodes that exist but are not a GPU. vgem and vkms are kernel test and
# virtual devices; both publish a renderD* node, so a check that stops at "a
# render node exists" counts them as working graphics.
AURADE_PROBE_EXCLUDED_DRIVERS=${AURADE_PROBE_EXCLUDED_DRIVERS:-vgem vkms}

# The optional GL probe is bounded and may be absent. mesa-utils is on the
# installation image, so eglinfo is normally there, but the probe must never be
# the reason an install cannot start: a missing or slow eglinfo leaves the
# result exactly as the sysfs evidence alone made it.
AURADE_PROBE_GL_TIMEOUT=${AURADE_PROBE_GL_TIMEOUT:-5}

# Archiso's copy-on-write layer is RAM-backed by default. Extracting the shell
# packages into the live overlay and then running Chromium against them costs
# well over a gigabyte on top of the running system, so a machine that would
# technically start a compositor can still be one that should be given the text
# installer instead.
AURADE_PROBE_MIN_GUI_MIB=${AURADE_PROBE_MIN_GUI_MIB:-6144}

AURADE_PROBE_RENDERER=
AURADE_PROBE_REASON=
AURADE_PROBE_GRAPHICS=
AURADE_PROBE_MEMORY=
AURADE_PROBE_VIRT=
AURADE_PROBE_MEM_MIB=0
AURADE_PROBE_NODE=
AURADE_PROBE_DRIVER=
AURADE_PROBE_GL=

_probe_mem_mib() {
  local kib=0
  [[ -r $AURADE_PROBE_MEMINFO ]] || { printf '0'; return 0; }
  kib=$(awk '/^MemAvailable:/ { print $2; exit }' "$AURADE_PROBE_MEMINFO" 2>/dev/null || true)
  [[ $kib =~ ^[0-9]+$ ]] || kib=0
  printf '%s' "$(( kib / 1024 ))"
}

# The kernel driver behind a render node, from sysfs. Always available, needs
# no tools, and is the difference between "something published a device file"
# and "a graphics driver is loaded".
_probe_driver_for() {
  local node=$1 uevent driver=''
  uevent="$AURADE_PROBE_DRM_DIR/${node##*/}/device/uevent"
  if [[ -r $uevent ]]; then
    driver=$(awk -F= '/^DRIVER=/ { print $2; exit }' "$uevent" 2>/dev/null || true)
  fi
  printf '%s' "$driver"
}

_probe_driver_excluded() {
  local driver=$1 excluded
  [[ -n $driver ]] || return 1
  for excluded in $AURADE_PROBE_EXCLUDED_DRIVERS; do
    [[ $driver != "$excluded" ]] || return 0
  done
  return 1
}

# Pick the first render node backed by a real driver.
#   0  a usable node was found
#   1  no render node at all
#   2  render nodes exist, but every one of them is a virtual device
_probe_select_node() {
  local node driver excluded_driver=''
  AURADE_PROBE_NODE=
  AURADE_PROBE_DRIVER=
  [[ -d $AURADE_PROBE_DRI_DIR ]] || return 1
  for node in "$AURADE_PROBE_DRI_DIR"/renderD*; do
    [[ -e $node ]] || continue
    driver=$(_probe_driver_for "$node")
    if _probe_driver_excluded "$driver"; then
      [[ -n $excluded_driver ]] || excluded_driver=$driver
      continue
    fi
    AURADE_PROBE_NODE=$node
    AURADE_PROBE_DRIVER=$driver
    return 0
  done
  if [[ -n $excluded_driver ]]; then
    AURADE_PROBE_DRIVER=$excluded_driver
    return 2
  fi
  return 1
}

# The renderer string, if a tool on the image will tell us. Optional and time
# bounded; failure returns 1 and the caller carries on with sysfs evidence.
_probe_gl_renderer() {
  local output renderer
  command -v eglinfo >/dev/null 2>&1 || return 1
  command -v timeout >/dev/null 2>&1 || return 1
  output=$(timeout "$AURADE_PROBE_GL_TIMEOUT" eglinfo -B 2>/dev/null || true)
  [[ -n $output ]] || return 1
  renderer=$(printf '%s\n' "$output" |
    awk -F': *' 'tolower($0) ~ /renderer string/ { print $2; exit }')
  [[ -n $renderer ]] || return 1
  printf '%s' "$renderer"
}

# Mesa's software rasterisers. A desktop on one of these starts and draws, so
# this is not a black screen; it is a machine that will be painful to use.
_probe_is_software_renderer() {
  case ${1,,} in
    *llvmpipe*|*softpipe*|*swrast*|*"software rasterizer"*) return 0 ;;
    *) return 1 ;;
  esac
}

_probe_virt() {
  local virt=none
  if command -v systemd-detect-virt >/dev/null 2>&1; then
    virt=$(systemd-detect-virt 2>/dev/null || printf 'none')
  fi
  [[ -n $virt ]] || virt=none
  printf '%s' "$virt"
}

# Always returns 0. The engine and the front end both run under `set -e`, and a
# probe that exits non-zero for the ordinary "no graphics here" case would
# abort the installer rather than fall back to it, which is precisely the
# failure mode this file exists to prevent.
aurade_probe_renderer() {
  local selection=0
  AURADE_PROBE_VIRT=$(_probe_virt)
  AURADE_PROBE_MEM_MIB=$(_probe_mem_mib)
  AURADE_PROBE_MEMORY="$(( AURADE_PROBE_MEM_MIB / 1024 )).$(( (AURADE_PROBE_MEM_MIB % 1024) * 10 / 1024 ))G available, graphical mode needs $(( AURADE_PROBE_MIN_GUI_MIB / 1024 ))G"

  if [[ ${AURADE_FORCE_TUI:-0} == 1 ]]; then
    AURADE_PROBE_RENDERER=tui
    AURADE_PROBE_REASON=forced
    AURADE_PROBE_GRAPHICS='text installer selected explicitly'
    return 0
  fi

  if ! [[ -d $AURADE_PROBE_DRI_DIR ]]; then
    AURADE_PROBE_RENDERER=tui
    AURADE_PROBE_REASON=no-dri-dir
    AURADE_PROBE_GRAPHICS="no $AURADE_PROBE_DRI_DIR directory; the kernel found no supported GPU"
    return 0
  fi

  selection=0
  _probe_select_node || selection=$?
  case $selection in
    1)
      AURADE_PROBE_RENDERER=tui
      AURADE_PROBE_REASON=no-render-node
      AURADE_PROBE_GRAPHICS="no $AURADE_PROBE_DRI_DIR/renderD* device found"
      return 0
      ;;
    2)
      AURADE_PROBE_RENDERER=tui
      AURADE_PROBE_REASON=virtual-gpu-only
      AURADE_PROBE_GRAPHICS="only the $AURADE_PROBE_DRIVER virtual device was found, which is not a GPU"
      return 0
      ;;
  esac
  AURADE_PROBE_GRAPHICS="$AURADE_PROBE_NODE${AURADE_PROBE_DRIVER:+, driver $AURADE_PROBE_DRIVER}"

  # Optional, bounded, and never fatal. When it says nothing, the result stands
  # on the sysfs evidence and the wording claims no more than that.
  AURADE_PROBE_GL=$(_probe_gl_renderer || true)
  if [[ -n $AURADE_PROBE_GL ]]; then
    AURADE_PROBE_GRAPHICS="$AURADE_PROBE_GRAPHICS; renderer $AURADE_PROBE_GL"
    if _probe_is_software_renderer "$AURADE_PROBE_GL"; then
      AURADE_PROBE_RENDERER=tui
      AURADE_PROBE_REASON=software-rendering
      return 0
    fi
  fi

  if (( AURADE_PROBE_MEM_MIB < AURADE_PROBE_MIN_GUI_MIB )); then
    AURADE_PROBE_RENDERER=tui
    AURADE_PROBE_REASON=low-memory
    return 0
  fi

  AURADE_PROBE_RENDERER=gui
  AURADE_PROBE_REASON=ok
  return 0
}

# The sentence that turns a reason code into something a person can act on.
# Bounded set: adding a reason means writing its advice, which is the point.
aurade_probe_advice() {
  case ${1:-$AURADE_PROBE_REASON} in
    ok)
      # Narrow to what was actually established. A render node proves a driver
      # published a device file, not that 3D acceleration works, and claiming
      # the latter is how a user ends up trusting this screen and then meeting
      # a black desktop.
      if [[ -n $AURADE_PROBE_GL ]]; then
        printf '%s' "Hardware rendering is available through $AURADE_PROBE_GL."
      elif [[ -n $AURADE_PROBE_DRIVER ]]; then
        printf '%s' "The $AURADE_PROBE_DRIVER driver is loaded and provides a render node. That is as far as this check goes; whether 3D acceleration works is only proven once the desktop starts."
      else
        printf '%s' 'A render node is present, but the driver behind it could not be identified. That is as far as this check goes; whether 3D acceleration works is only proven once the desktop starts.'
      fi
      ;;
    virtual-gpu-only)
      printf '%s' "The only graphics device found is $AURADE_PROBE_DRIVER, a virtual device with no display output. AuraDE's desktop will not start on it. If this is a virtual machine, give it a real graphics adapter with 3D acceleration enabled."
      ;;
    software-rendering)
      printf '%s' "Graphics are being drawn in software by $AURADE_PROBE_GL rather than by a GPU. The desktop will start, but it will be slow enough to be unpleasant. On a virtual machine, enabling 3D acceleration usually fixes this."
      ;;
    forced)
      printf '%s' 'The text installer does exactly the same thing as the graphical one.'
      ;;
    no-dri-dir|no-render-node)
      if [[ $AURADE_PROBE_VIRT != none ]]; then
        printf '%s' "AuraDE's desktop needs 3D acceleration. This is a $AURADE_PROBE_VIRT virtual machine; enable 3D acceleration in its display settings before installing, or the desktop will not start after installation."
      else
        printf '%s' "AuraDE's desktop needs 3D acceleration, and this computer has no working graphics driver. Installing now will produce a system that starts but shows no desktop."
      fi
      ;;
    low-memory)
      printf '%s' 'There is not enough free memory to run the graphical installer from the installation media. The installed system has more memory available than the live image does, so this does not by itself mean the desktop will be unusable.'
      ;;
    *)
      printf '%s' 'Continuing in text mode.'
      ;;
  esac
}

# Whether the probe result predicts a black screen after installation, as
# opposed to merely declining to run a graphical installer now. Low memory on
# the live image says nothing about the installed system; a missing GPU does.
aurade_probe_predicts_black_screen() {
  case ${1:-$AURADE_PROBE_REASON} in
    no-dri-dir|no-render-node|virtual-gpu-only) return 0 ;;
    *) return 1 ;;
  esac
}
