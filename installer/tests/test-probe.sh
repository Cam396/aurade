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

install -d "$TMP/dri-empty" "$TMP/dri-ok"
: >"$TMP/dri-ok/renderD128"
: >"$TMP/dri-ok/card0"

probe() {
  # A fresh shell each time: the probe sets globals, and a test that reused
  # them could pass on a value left behind by the previous case.
  env AURADE_PROBE_DRI_DIR="$1" AURADE_PROBE_MEMINFO="$2" \
    AURADE_PROBE_MIN_GUI_MIB="${3:-6144}" AURADE_FORCE_TUI="${4:-0}" \
    bash -c '
      set -Eeuo pipefail
      . '"$ROOT"'/installer/lib/aurade-probe.sh
      aurade_probe_renderer
      printf "%s|%s|%s|%s\n" "$AURADE_PROBE_RENDERER" "$AURADE_PROBE_REASON" \
        "$(aurade_probe_predicts_black_screen && printf yes || printf no)" \
        "$AURADE_PROBE_GRAPHICS"
    '
}

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
  env AURADE_PROBE_DRI_DIR="$TMP/absent" AURADE_PROBE_MEMINFO="$TMP/meminfo.big" \
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
for reason in ok forced no-dri-dir no-render-node low-memory; do
  text=$(env AURADE_PROBE_DRI_DIR="$TMP/dri-ok" AURADE_PROBE_MEMINFO="$TMP/meminfo.big" bash -c '
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
