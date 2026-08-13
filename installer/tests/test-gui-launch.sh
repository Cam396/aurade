#!/usr/bin/env bash
# Which installer actually starts, and what happens when the graphical one
# cannot.
#
# The handoff document names one invariant above the others: the text installer
# stays usable when no graphical renderer is available. That is a claim about
# what these two launchers do on a machine with no toolkit, no compositor and
# no display, so it is tested on exactly such a machine - this one - with the
# toolkit's presence and absence both supplied as fixtures rather than left to
# whatever the build host happens to have installed.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fail() { echo "test-gui-launch: $*" >&2; exit 1; }

command -v python3 >/dev/null 2>&1 || {
  echo 'installer GUI launch test: SKIP (python3 not available)'
  exit 0
}

install -d "$TMP/bin" "$TMP/lib" "$TMP/no-gi/gi" "$TMP/fake-gi/gi" \
  "$TMP/dri" "$TMP/empty-dri" "$TMP/stub"

# An image layout with the front ends, the libraries and nothing else.
install -m 0755 "$ROOT/installer/bin/aurade-installer-gui" \
  "$ROOT/installer/bin/aurade-installer-gui-bridge" \
  "$ROOT/installer/bin/aurade-installer-start" "$TMP/bin/"
install -m 0644 "$ROOT/installer/lib/aurade-validate.sh" \
  "$ROOT/installer/lib/aurade-questions.sh" "$ROOT/installer/lib/aurade-tui.sh" \
  "$ROOT/installer/lib/aurade-probe.sh" "$ROOT/installer/lib/aurade-journal.sh" \
  "$TMP/lib/"
install -d "$TMP/lib/aurade_gui"
install -m 0644 "$ROOT"/installer/lib/aurade_gui/*.py "$TMP/lib/aurade_gui/"

# A text installer that records how it was invoked instead of installing.
#
# The model process sources this same file as its library, which is the whole
# point of the arrangement, so the shim keeps that half real and stubs only the
# half that would otherwise ask for a disk.
cat >"$TMP/bin/aurade-installer-tui" <<'STUB'
#!/usr/bin/env bash
if [[ -n ${AURADE_INSTALLER_TUI_LIB:-} ]]; then
  # shellcheck source=/dev/null
  . "$AURADE_REAL_TUI"
  return 0 2>/dev/null || exit 0
fi
printf 'tui %s\n' "$*" >>"$AURADE_LAUNCH_LOG"
exit 0
STUB
cat >"$TMP/stub/cage" <<'STUB'
#!/usr/bin/env bash
printf 'cage %s\n' "$*" >>"$AURADE_LAUNCH_LOG"
exit 0
STUB
chmod +x "$TMP/bin/aurade-installer-tui" "$TMP/stub/cage"

# PyGObject, absent and present. The absent one raises on import the way a
# missing package does; the present one satisfies exactly the calls the entry
# point makes, and nothing more, so a future import here fails loudly.
printf 'raise ImportError("no PyGObject on this image")\n' >"$TMP/no-gi/gi/__init__.py"
cat >"$TMP/fake-gi/gi/__init__.py" <<'PY'
def require_version(namespace, version):
    return None
PY
install -d "$TMP/fake-gi/gi/repository"
printf 'class Gtk: pass\nclass Adw: pass\n' >"$TMP/fake-gi/gi/repository/__init__.py"

printf 'MemAvailable:   16000000 kB\n' >"$TMP/meminfo"
printf '%s\n' '/dev/sda|931.5G|WDC WD10EZEX|sata|WD-WCC6Y4KP1234' >"$TMP/disks"
: >"$TMP/dri/renderD128"
install -d "$TMP/drm/renderD128/device"
printf 'DRIVER=i915\n' >"$TMP/drm/renderD128/device/uevent"

export AURADE_ZONEINFO_DIR="$TMP" AURADE_LOCALE_DIR="$TMP"
export AURADE_KEYMAP_DIR="$TMP" AURADE_BLOCK_DIR="$TMP"
export AURADE_DISK_TABLE="$TMP/disks" AURADE_PROBE_MEMINFO="$TMP/meminfo"
export AURADE_PROBE_DRM_DIR="$TMP/drm"
export AURADE_LAUNCH_LOG="$TMP/launch.log"
export AURADE_REAL_TUI="$ROOT/installer/bin/aurade-installer-tui"
export TMPDIR="$TMP"
unset WAYLAND_DISPLAY DISPLAY || true

launch() { : >"$TMP/launch.log"; }
logged() { grep -Fq -- "$1" "$TMP/launch.log"; }

# --- the entry point falls back rather than failing --------------------------

launch
out=$(PYTHONPATH="$TMP/no-gi" AURADE_PROBE_DRI_DIR="$TMP/dri" \
  "$TMP/bin/aurade-installer-gui" --journal "$TMP/j" --raw-log "$TMP/r" 2>&1) ||
  fail "the entry point failed instead of falling back: $out"
logged 'tui ' || fail 'a missing toolkit did not reach the text installer'
grep -q 'PyGObject is not installed' <<<"$out" ||
  fail "a missing toolkit did not say so: $out"
logged '--journal' || fail 'the journal path was not passed to the text installer'

# A present toolkit and no display is still a fallback, not a crash.
launch
out=$(PYTHONPATH="$TMP/fake-gi" AURADE_PROBE_DRI_DIR="$TMP/dri" \
  "$TMP/bin/aurade-installer-gui" --journal "$TMP/j" --raw-log "$TMP/r" 2>&1) ||
  fail "a display-less session failed instead of falling back: $out"
grep -q 'no display is running' <<<"$out" || fail "the reason was not stated: $out"
logged 'tui ' || fail 'a display-less session did not reach the text installer'

# A probe that predicts a black screen is a fallback even with a toolkit and a
# display, because the probe's finding is about the machine, not the toolkit.
launch
out=$(PYTHONPATH="$TMP/fake-gi" AURADE_PROBE_DRI_DIR="$TMP/empty-dri" \
  WAYLAND_DISPLAY=wayland-0 \
  "$TMP/bin/aurade-installer-gui" --journal "$TMP/j" --raw-log "$TMP/r" 2>&1) ||
  fail "a machine with no GPU failed instead of falling back: $out"
grep -q '3D acceleration' <<<"$out" || fail "the graphics advice was not shown: $out"
logged 'tui ' || fail 'a machine with no GPU did not reach the text installer'

# --plan-only survives the handover. A session the user started as plan-only
# must not become one that can erase because the toolkit was missing.
launch
PYTHONPATH="$TMP/no-gi" AURADE_PROBE_DRI_DIR="$TMP/dri" \
  "$TMP/bin/aurade-installer-gui" --plan-only >/dev/null 2>&1 ||
  fail 'plan-only failed to fall back'
logged '--plan-only' || fail 'plan-only was dropped on the way to the text installer'

# --- self-check reports rather than guesses ----------------------------------

out=$(PYTHONPATH="$TMP/fake-gi" AURADE_PROBE_DRI_DIR="$TMP/dri" \
  "$TMP/bin/aurade-installer-gui" --self-check 2>&1) ||
  fail "self-check failed with a usable toolkit: $out"
grep -q '^toolkit: ok$' <<<"$out" || fail "self-check misreported the toolkit: $out"
grep -q '^renderer: gui (ok)$' <<<"$out" || fail "self-check misreported the probe: $out"

status=0
out=$(PYTHONPATH="$TMP/no-gi" AURADE_PROBE_DRI_DIR="$TMP/dri" \
  "$TMP/bin/aurade-installer-gui" --self-check 2>&1) || status=$?
(( status == 1 )) || fail "self-check passed without a toolkit (status $status)"
grep -q 'PyGObject is not installed' <<<"$out" ||
  fail "self-check did not name the missing toolkit: $out"

# --- the launcher chooses, and says what it chose ----------------------------

launch
PATH="$TMP/stub:$PATH" AURADE_PROBE_DRI_DIR="$TMP/dri" \
  "$TMP/bin/aurade-installer-start" --text >/dev/null 2>&1 ||
  fail '--text did not start the text installer'
logged 'tui' || fail '--text did not reach the text installer'
! logged 'cage' || fail '--text started a compositor'

launch
AURADE_FORCE_TUI=1 PATH="$TMP/stub:$PATH" AURADE_PROBE_DRI_DIR="$TMP/dri" \
  "$TMP/bin/aurade-installer-start" >/dev/null 2>&1 ||
  fail 'AURADE_FORCE_TUI did not start the text installer'
logged 'tui' || fail 'AURADE_FORCE_TUI did not reach the text installer'

launch
out=$(PATH="$TMP/stub:$PATH" AURADE_PROBE_DRI_DIR="$TMP/empty-dri" \
  "$TMP/bin/aurade-installer-start" 2>&1) ||
  fail "the launcher failed on a machine with no GPU: $out"
logged 'tui' || fail 'a machine with no GPU did not reach the text installer'
! logged 'cage' || fail 'a machine with no GPU started a compositor'
grep -q '3D acceleration' <<<"$out" ||
  fail "the launcher did not repeat the graphics advice: $out"

# A usable machine with no compositor on the image is still a text install, and
# the message says which of the two things was missing. The compositor lives in
# the stub directory and nowhere else, so leaving that off the search path is
# what "this image has no compositor" looks like - unless the build host has
# one of its own, in which case this one case cannot be staged here.
if command -v cage >/dev/null 2>&1; then
  echo 'test-gui-launch: NOTE (build host has cage; missing-compositor case not staged)'
else
launch
out=$(AURADE_PROBE_DRI_DIR="$TMP/dri" \
  "$TMP/bin/aurade-installer-start" 2>&1) ||
  fail "the launcher failed without a compositor: $out"
grep -q 'no compositor on this image' <<<"$out" ||
  fail "the missing compositor was not named: $out"
logged 'tui' || fail 'a missing compositor did not reach the text installer'
fi

launch
PATH="$TMP/stub:$PATH" AURADE_PROBE_DRI_DIR="$TMP/dri" \
  "$TMP/bin/aurade-installer-start" >/dev/null 2>&1 ||
  fail 'the launcher failed on a usable machine'
logged 'cage -- ' || fail 'a usable machine did not start the compositor'
grep -q 'aurade-installer-gui' "$TMP/launch.log" ||
  fail 'the compositor was not given the graphical installer'
! logged 'tui' || fail 'a usable machine started the text installer as well'

launch
PATH="$TMP/stub:$PATH" AURADE_PROBE_DRI_DIR="$TMP/dri" \
  "$TMP/bin/aurade-installer-start" --plan-only >/dev/null 2>&1 ||
  fail 'the launcher failed in plan-only mode'
grep -q -- '--plan-only' "$TMP/launch.log" ||
  fail 'plan-only was dropped on the way to the graphical installer'

# --graphical must reach the GUI with its explicit force override, rather than
# merely bypassing the shell-side probe and then being rejected by the Python
# launcher after it probes again.
launch
PATH="$TMP/stub:$PATH" AURADE_PROBE_DRI_DIR="$TMP/empty-dri" \
  "$TMP/bin/aurade-installer-start" --graphical >/dev/null 2>&1 ||
  fail '--graphical failed to start the graphical path'
grep -q -- '--force' "$TMP/launch.log" ||
  fail '--graphical did not carry the force override to the GUI'

echo 'installer GUI launch test: PASS'
