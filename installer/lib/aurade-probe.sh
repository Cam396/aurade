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

_probe_mem_mib() {
  local kib=0
  [[ -r $AURADE_PROBE_MEMINFO ]] || { printf '0'; return 0; }
  kib=$(awk '/^MemAvailable:/ { print $2; exit }' "$AURADE_PROBE_MEMINFO" 2>/dev/null || true)
  [[ $kib =~ ^[0-9]+$ ]] || kib=0
  printf '%s' "$(( kib / 1024 ))"
}

_probe_render_node() {
  local node
  [[ -d $AURADE_PROBE_DRI_DIR ]] || return 1
  for node in "$AURADE_PROBE_DRI_DIR"/renderD*; do
    [[ -e $node ]] || continue
    printf '%s' "$node"
    return 0
  done
  return 1
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
  local node=''
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

  if ! node=$(_probe_render_node); then
    AURADE_PROBE_RENDERER=tui
    AURADE_PROBE_REASON=no-render-node
    AURADE_PROBE_GRAPHICS="no $AURADE_PROBE_DRI_DIR/renderD* device found"
    return 0
  fi
  AURADE_PROBE_GRAPHICS="$node"

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
      printf '%s' 'This computer can run the AuraDE desktop.'
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
    no-dri-dir|no-render-node) return 0 ;;
    *) return 1 ;;
  esac
}
