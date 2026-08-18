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

# shellcheck source=assert.sh
. "$(dirname -- "$0")/assert.sh"

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
  "$ROOT/installer/lib/aurade-copy.sh" \
  "$ROOT/installer/lib/aurade-renderers.sh" \
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
# A compositor that starts and whose client draws. The readiness file is how
# the launcher tells "a renderer worked" from "cage exited"; a stub that omits
# it is a stub for a machine where nothing ever appeared, which is a different
# test - test-renderer-chain.sh covers that side.
cat >"$TMP/stub/cage" <<'STUB'
#!/usr/bin/env bash
printf 'cage %s\n' "$*" >>"$AURADE_LAUNCH_LOG"
printf 'runtime=%s mode=%s\n' "${XDG_RUNTIME_DIR:-unset}" \
  "$(stat -c '%a' -- "${XDG_RUNTIME_DIR:-/missing}" 2>/dev/null || printf 'missing')" \
  >>"$AURADE_LAUNCH_LOG"
[[ -n ${XDG_RUNTIME_DIR:-} && -d $XDG_RUNTIME_DIR && \
   $(stat -c '%a' -- "$XDG_RUNTIME_DIR" 2>/dev/null) == 700 ]] || exit 1
[[ -z ${AURADE_GUI_READY_FILE:-} ]] || printf 'mapped\n' >"$AURADE_GUI_READY_FILE"
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
export AURADE_RUNTIME_BASE="$TMP"
unset WAYLAND_DISPLAY DISPLAY XDG_RUNTIME_DIR || true

launch() { : >"$TMP/launch.log"; }
logged() { grep -Fq -- "$1" "$TMP/launch.log"; }

# --- the entry point falls back rather than failing --------------------------

launch
out=$(PYTHONPATH="$TMP/no-gi" AURADE_PROBE_DRI_DIR="$TMP/dri" \
  "$TMP/bin/aurade-installer-gui" --journal "$TMP/j" --raw-log "$TMP/r" 2>&1) ||
  fail "the entry point failed instead of falling back: $out"
logged 'tui ' || fail 'a missing toolkit did not reach the text installer'
grep -q 'graphical toolkit is not installed' <<<"$out" ||
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

# Inside a compositor the launcher started, the fallback works the other way
# round. There is no terminal behind this process, so a text installer started
# here draws onto a surface with no keyboard in front of it; the launcher still
# owns the real console. So the front end reports that it declined and exits,
# and the handover happens out there.
launch
status=0
out=$(PYTHONPATH="$TMP/no-gi" AURADE_PROBE_DRI_DIR="$TMP/dri" \
  AURADE_GUI_READY_FILE="$TMP/stage" \
  "$TMP/bin/aurade-installer-gui" --journal "$TMP/j" --raw-log "$TMP/r" 2>&1) ||
  status=$?
(( status == 1 )) ||
  fail "a launcher-managed front end did not report a failure (status $status)"
! logged 'tui ' ||
  fail 'the text installer was started inside a compositor nobody can type into'
[[ $(cat "$TMP/stage" 2>/dev/null) == declined ]] ||
  fail "the front end did not tell the launcher it had declined: $(cat "$TMP/stage" 2>/dev/null)"
grep -q 'graphical toolkit is not installed' <<<"$out" ||
  fail "the launcher-managed fallback did not say why: $out"
rm -f "$TMP/stage"

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
grep -q 'graphical toolkit is not installed' <<<"$out" ||
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
runtime=$(awk -F= '$1 == "runtime" {print $2; exit}' "$TMP/launch.log")
[[ -n $runtime ]] || fail 'the launcher did not provide a Wayland runtime directory'
[[ ! -e $runtime ]] || fail 'the private Wayland runtime directory was not cleaned up'

launch
PATH="$TMP/stub:$PATH" AURADE_PROBE_DRI_DIR="$TMP/dri" \
  "$TMP/bin/aurade-installer-start" --plan-only >/dev/null 2>&1 ||
  fail 'the launcher failed in plan-only mode'
grep -q -- '--plan-only' "$TMP/launch.log" ||
  fail 'plan-only was dropped on the way to the graphical installer'

# --- the boot menu choice reaches a front end --------------------------------
#
# Four boot entries, one per front end, and a kernel command line is the only
# channel between the menu and the booted system. What the entry asks for and
# what starts have to be the same thing, and neither half is visible from the
# other, so this checks the mapping directly.
AUTOSTART=$ROOT/installer/archiso/airootfs/usr/local/sbin/aurade-installer-autostart
cat >"$TMP/bin/start-recorder" <<'STUB'
#!/usr/bin/env bash
printf 'start %s\n' "$*" >>"$AURADE_LAUNCH_LOG"
exit 0
STUB
chmod +x "$TMP/bin/start-recorder"

# `logged` is a substring match and the autostart's own messages contain the
# word; this asks whether the recorder ran at all.
started() { grep -q '^start ' "$TMP/launch.log"; }

autostart() {
  launch
  rm -f "$TMP/autostart-stamp"
  printf '%s\n' "$1" >"$TMP/cmdline"
  AURADE_CMDLINE_FILE="$TMP/cmdline" AURADE_INSTALLER_START="$TMP/bin/start-recorder" \
    AURADE_AUTOSTART_STAMP="$TMP/autostart-stamp" \
    "$AUTOSTART" >>"$TMP/launch.log" 2>&1 || return $?
}

# The same call again, without clearing the stamp: this is what the next login
# on the same console looks like.
autostart_again() {
  launch
  AURADE_CMDLINE_FILE="$TMP/cmdline" AURADE_INSTALLER_START="$TMP/bin/start-recorder" \
    AURADE_AUTOSTART_STAMP="$TMP/autostart-stamp" \
    "$AUTOSTART" >>"$TMP/launch.log" 2>&1 || return $?
}

autostart 'root=live quiet aurade.installer=gui' || fail 'the graphical entry failed'
logged 'start --graphical' || fail 'the graphical boot entry did not start the graphical installer'

# --- the boot screen is gone before anything tries to draw -------------------
#
# This is the one that turned a working graphical installer into a black
# screen and a text installer, on the default boot entry, on real hardware.
#
# `splash` puts plymouth on tty1, and plymouth holds DRM master until it is
# told to go. `cage` opens the graphics device itself and asks to become DRM
# master, which cannot succeed while plymouth is still there. So every renderer
# in the negotiation failed in turn, none of them for a reason that had
# anything to do with graphics, and all of it happened behind the boot screen
# that was causing it. What the user saw was the boot screen, then black for as
# long as the chain took, then the text installer.
#
# Every getty on the image already waits for plymouth. This unit replaces the
# getty on tty1 and did not inherit the one line that made it work.
cat >"$TMP/bin/plymouth" <<'STUB'
#!/usr/bin/env bash
printf 'plymouth %s
' "$*" >>"$AURADE_LAUNCH_LOG"
# `--ping` succeeding is what says a boot screen is actually up.
exit 0
STUB
chmod +x "$TMP/bin/plymouth"

launch
rm -f "$TMP/autostart-stamp"
printf '%s
' 'root=live quiet splash aurade.installer=gui' >"$TMP/cmdline"
PATH="$TMP/bin:$PATH" AURADE_CMDLINE_FILE="$TMP/cmdline"   AURADE_INSTALLER_START="$TMP/bin/start-recorder"   AURADE_AUTOSTART_STAMP="$TMP/autostart-stamp"   "$AUTOSTART" >>"$TMP/launch.log" 2>&1 ||
  fail 'the graphical entry failed with a boot screen up'
logged 'plymouth quit' || fail 'the boot screen was left up while the installer tried to draw'
logged 'plymouth --wait' ||
  fail 'the installer did not wait for the boot screen to actually go'
# Order is the whole point. Quitting after the front end has started is the
# same bug with a longer delay in front of it.
quit_line=$(grep -n '^plymouth quit' "$TMP/launch.log" | head -1 | cut -d: -f1)
start_line=$(grep -n '^start ' "$TMP/launch.log" | head -1 | cut -d: -f1)
[[ -n $quit_line && -n $start_line ]] ||
  fail 'could not tell when the boot screen went and when the installer started'
(( quit_line < start_line )) ||
  fail 'the installer started before the boot screen was retired'

# And an image with no plymouth on it still gets an installer. Three of the six
# boot entries have no `splash`, and a recovery image might have no plymouth at
# all, so this must not become a new way to end up with nothing.
cat >"$TMP/bin-noplymouth-start" <<'STUB'
#!/usr/bin/env bash
printf 'start %s
' "$*" >>"$AURADE_LAUNCH_LOG"
exit 0
STUB
chmod +x "$TMP/bin-noplymouth-start"
launch
rm -f "$TMP/autostart-stamp"
printf '%s
' 'root=live quiet aurade.installer=gui' >"$TMP/cmdline"
PATH=/usr/bin:/bin AURADE_CMDLINE_FILE="$TMP/cmdline"   AURADE_INSTALLER_START="$TMP/bin-noplymouth-start"   AURADE_AUTOSTART_STAMP="$TMP/autostart-stamp"   "$AUTOSTART" >>"$TMP/launch.log" 2>&1 ||
  fail 'an image with no boot screen failed to start the installer'
logged 'start --graphical' ||
  fail 'an image with no plymouth on it did not reach the installer'

# Plymouth installed, and no boot screen up. This is not a corner: three of the
# six boot entries carry no `splash` on purpose, so on those the daemon was
# never started and there is nothing to quit.
#
# It matters because `plymouth --wait` blocks until the daemon goes away, and
# asking it to wait for a daemon that never existed is a console that stops
# before the installer starts. The guard is `--ping`, and this is the case that
# makes it load bearing rather than decorative.
cat >"$TMP/bin/plymouth" <<'STUB'
#!/usr/bin/env bash
printf 'plymouth %s\n' "$*" >>"$AURADE_LAUNCH_LOG"
# No daemon: the ping fails, and anything that waits for one waits forever.
case ${1-} in
  --ping) exit 1 ;;
  --wait) sleep 300 ;;
esac
exit 0
STUB
chmod +x "$TMP/bin/plymouth"
launch
rm -f "$TMP/autostart-stamp"
printf '%s\n' 'root=live quiet aurade.installer=gui' >"$TMP/cmdline"
timeout 20 env PATH="$TMP/bin:$PATH" AURADE_CMDLINE_FILE="$TMP/cmdline" \
  AURADE_INSTALLER_START="$TMP/bin/start-recorder" \
  AURADE_AUTOSTART_STAMP="$TMP/autostart-stamp" \
  "$AUTOSTART" >>"$TMP/launch.log" 2>&1
timeout_status=$?
(( timeout_status != 124 )) ||
  fail 'the installer waited forever for a boot screen that was never up'
logged 'start --graphical' ||
  fail 'a boot entry with no boot screen did not reach the installer'
refute grep -Fq 'plymouth --wait' "$TMP/launch.log"

autostart 'root=live aurade.installer=text quiet' || fail 'the text entry failed'
logged 'start --text' || fail 'the text boot entry did not start the text installer'

autostart 'aurade.installer=safe' || fail 'the safe graphics entry failed'
logged 'start --graphical --safe-graphics' ||
  fail 'the safe graphics boot entry did not skip acceleration'

# The recovery console is the entry that starts nothing. Someone who chose it
# is here to run commands, and an installer on top of that is in the way.
autostart 'aurade.installer=none' || fail 'the recovery console entry failed'
! started || fail 'the recovery console entry started an installer anyway'

# No parameter at all - a hand-typed boot, or an older entry - is the console
# too. Guessing at an installer for someone who did not ask for one is the
# same mistake in the other direction.
autostart 'root=live quiet' || fail 'a command line with no request failed'
! started || fail 'a command line with no request started an installer'

# A typo in a boot entry is a typo, not an instruction.
autostart 'aurade.installer=graphical' || fail 'an unknown front end failed instead of saying so'
! started || fail 'an unknown front end name started something anyway'
grep -q 'not one of the installers' "$TMP/launch.log" ||
  fail 'an unknown front end name was not reported'
grep -q 'graphical' "$TMP/launch.log" ||
  fail 'the unknown name itself was not quoted back'
# A dead end is not a dead end if it says how to get out of it.
grep -q 'aurade-installer-start' "$TMP/launch.log" ||
  fail 'an unknown front end name left the console with no way forward'

# Quitting the installer must not start it again. The console is an autologin
# getty: the login shell ends when the installer exits, agetty starts another
# one, and an installer that starts itself on every login is an installer with
# no way out of it.
autostart 'aurade.installer=gui' || fail 'the graphical entry failed'
logged 'start --graphical' || fail 'the first login did not start the installer'
autostart_again || fail 'the second login failed'
! started || fail 'quitting the installer started it again on the next login'
grep -q 'already run on this console' "$TMP/launch.log" ||
  fail 'the second login did not say why it started nothing'

# The kernel takes the last occurrence of a repeated parameter; so does this.
autostart 'aurade.installer=gui aurade.installer=text' || fail 'a repeated request failed'
logged 'start --text' || fail 'a repeated request did not resolve the way the kernel resolves it'

echo 'installer GUI launch test: PASS'
