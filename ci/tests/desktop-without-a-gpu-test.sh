#!/usr/bin/env bash
# What keeps the desktop drawing on a machine whose GPU cannot draw it.
#
# Three patches, and each one going missing in a rebase is a crash on some
# machine. 0090 lets the transport factory switch to software compositing and
# keeps exo from starting without GPU compositing. 0091 gives the GPU process
# the display compositor mode a Chromebook is built without, so a GPU that
# fails every time ends in software instead of in "GPU process isn't usable.
# Goodbye." 0092 has exo refuse a window it has no way to draw, because
# building one without a GPU context crashed the whole desktop.
#
# All of it is gated on one environment variable, which the launcher exports.
# A rename on either side would switch the fallback off without a word, so the
# name is checked on both sides.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCHES="$ROOT/patches"
LAUNCHER="$ROOT/chromiumos-ash/chromiumos-ash.sh"
VARIABLE=AURADE_ALLOW_GPU_COMPOSITING_FALLBACK

fail() { echo "desktop without a GPU test: $*" >&2; exit 1; }

# The code a patch adds to one file, without its comments: a grep for a
# symbol passes just as happily on the comment that explains the symbol.
code_in() {
  awk -v want="+++ b/$2" '
    /^diff --git / { on = 0; next }
    /^\+\+\+ / { on = ($0 == want); next }
    on && /^\+/ { print substr($0, 2) }
  ' "$1" | grep -v '^[[:space:]]*//' || true
}

declare -A NAME=(
  [0090]=0090-the-desktop-draws-without-a-gpu.patch
  [0091]=0091-a-gpu-that-keeps-failing-ends-in-software.patch
  [0092]=0092-exo-refuses-windows-it-cannot-draw.patch
)
previous=0
for id in 0090 0091 0092; do
  [[ -r $PATCHES/${NAME[$id]} ]] || fail "patch $id is missing"
  line=$(grep -Fnx "${NAME[$id]}" "$PATCHES/SERIES" | cut -d: -f1 || true)
  [[ -n $line ]] || fail "patch $id is not listed in SERIES"
  (( line > previous )) || fail "patch $id is listed before the patch it builds on"
  previous=$line
done

# 0090. The transport factory switches under the variable and still refuses
# without it; the GPU process's own request is passed on under it; and exo
# stays off without a GPU context.
factory=$(code_in "$PATCHES/${NAME[0090]}" content/browser/compositor/viz_process_transport_factory.cc)
grep -Fq "\"$VARIABLE\"" <<<"$factory" || \
  fail '0090 no longer reads the fallback variable in the transport factory'
grep -Fq 'Switching to software compositing' <<<"$factory" || \
  fail '0090 no longer switches the transport factory to software'
grep -Fq 'LOG(FATAL)' <<<"$factory" || \
  fail '0090 no longer refuses when the fallback is not allowed'
host=$(code_in "$PATCHES/${NAME[0090]}" content/browser/gpu/gpu_process_host.cc)
grep -Fq "\"$VARIABLE\"" <<<"$host" || \
  fail "0090 no longer passes the GPU process's request on under the fallback variable"
parts=$(code_in "$PATCHES/${NAME[0090]}" chrome/browser/exo_parts.cc)
grep -Fq 'SharedMainThreadRasterContextProvider()' <<<"$parts" && \
  grep -Fq 'return nullptr;' <<<"$parts" || \
  fail '0090 no longer keeps exo off without GPU compositing'

# 0091. The display compositor mode, on ChromeOS only, and only when the
# variable allows it.
modes=$(code_in "$PATCHES/${NAME[0091]}" content/browser/gpu/gpu_data_manager_impl_private.cc)
grep -Fq '#if BUILDFLAG(IS_CHROMEOS)' <<<"$modes" || \
  fail '0091 is not confined to ChromeOS'
grep -Fq "\"$VARIABLE\"" <<<"$modes" || \
  fail '0091 no longer reads the fallback variable'
grep -Fq '!= "0"' <<<"$modes" || \
  fail '0091 adds the mode whatever the variable says'
grep -Fq 'fallback_modes_.push_back(gpu::GpuMode::DISPLAY_COMPOSITOR);' <<<"$modes" || \
  fail '0091 no longer adds the display compositor mode'

# 0092. The guard asks for the context, and both window factories a Linux
# application reaches ask the guard. The hunk header names the function each
# added line lands in.
display=$(code_in "$PATCHES/${NAME[0092]}" components/exo/display.cc)
grep -Fq 'SharedMainThreadRasterContextProvider()' <<<"$display" || \
  fail '0092 no longer asks for the GPU context'
guarded=$(awk '
  /^@@ / { hunk = $0; next }
  /^\+[[:space:]]*if \(!CanHostWindows\(\)\) \{/ { print hunk }
' "$PATCHES/${NAME[0092]}")
for factory_name in 'Display::CreateShellSurface(' 'Display::CreateXdgShellSurface('; do
  grep -Fq "$factory_name" <<<"$guarded" || \
    fail "0092 no longer guards ${factory_name%(}, so that window crashes a software desktop"
done

# The launcher, which is where the variable comes from.
grep -Fqx "export $VARIABLE" "$LAUNCHER" || \
  fail "the launcher does not export $VARIABLE, so none of this is ever allowed"
grep -Fqx "$VARIABLE=\"\${$VARIABLE:-1}\"" "$LAUNCHER" || \
  fail 'the launcher no longer allows the fallback unless told otherwise'

echo "desktop without a GPU test: ok"
