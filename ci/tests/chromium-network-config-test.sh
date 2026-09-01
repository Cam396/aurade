#!/usr/bin/env bash
# The real network client boundary, and why it is no longer a build flag.
#
# What this protects has not changed: a build must never publish the desktop
# fake Shill services, because invented interfaces look exactly like real
# connections in Ash and nothing on screen says otherwise.
#
# What provides it has changed. Until 2026-08-31 the mechanism was
# use_real_dbus_clients=true, and this fixture asserted that flag was set.
# Patch 0038 replaced it: ash_dbus_helper now routes the Shill clients to their
# own narrowly scoped real bus on generic Linux, rather than to the global bus,
# which does not exist there. That routing is what makes networking real, and
# it does not need the flag.
#
# The flag is now actively harmful and must stay out:
#
#   2026-08-19 23:32  flag added, as the original real-Shill mechanism
#   2026-08-20 08:56  upstream gives about seventy clients under
#                     chromeos/ash/components/dbus a CHECK(bus) on Initialize
#   2026-08-31 17:00  patch 0038 lands and supersedes the flag
#
# chromeos/features.gni sets use_real_chromeos_services = use_real_dbus_clients,
# so the flag also drops the fake mojo service manager from the build. A binary
# built with it aborts in PostEarlyInitialization before any window is created,
# the session supervisor gives up after five quick exits, and greetd falls back
# to the greeter, which reads as an ordinary logout rather than a broken build.
# That is why this fixture now fails closed on the flag being present.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PKGBUILD="$ROOT/chromiumos-ash/PKGBUILD"
PACKAGER="$ROOT/ci/build-clean-arch-chromium-package.sh"
GATE="$ROOT/ci/chromium-candidate-gate.sh"
NETWORK_PATCH="$ROOT/patches/0004-session-lifecycle-generic-linux.patch"
SHILL_PATCH="$ROOT/patches/0038-shill-network-real-bus-linux.patch"

fail() { echo "Chromium network client configuration test: $*" >&2; exit 1; }

# --- the flag must not come back, anywhere that generates build args --------

# Comments are stripped first. These files now carry an explanation of why the
# flag is gone, and that explanation names the flag, so a grep over the whole
# file matches the reasoning rather than the code. A fixture that fails on its
# own documentation teaches people to delete the documentation.
code_of() { sed -e 's/#.*$//' "$1"; }

for f in "$PKGBUILD" "$PACKAGER" "$GATE"; do
  [[ -r $f ]] || fail "missing ${f##*/}"
  if code_of "$f" | grep -Fq 'use_real_dbus_clients'; then
    fail "${f##*/} sets use_real_dbus_clients, which builds a binary that aborts before any window appears"
  fi
done

# The old fail-closed check looked for the define in the generated build. A
# build that carries it is the broken one, so that check has to be gone too.
if code_of "$PKGBUILD" | grep -Fq -- '-DUSE_REAL_DBUS_CLIENTS'; then
  fail 'the PKGBUILD still requires the -DUSE_REAL_DBUS_CLIENTS define'
fi

# --- but the guard itself must still exist, pointed at the real mechanism ---

grep -Fq 'shill_clients::InitializeAuraDe' "$PKGBUILD" || \
  fail 'the PKGBUILD no longer fails closed on the real Shill routing being absent'
grep -Fq 'missing the real Shill routing' "$PKGBUILD" || \
  fail 'the fail closed message for the Shill routing is gone'

# --- and the patch that provides it must still provide it ------------------

[[ -r $SHILL_PATCH ]] || fail 'patch 0038 is missing'
grep -Fq 'InitializeAuraDe' "$SHILL_PATCH" || \
  fail 'patch 0038 no longer defines InitializeAuraDe'
grep -Fq 'GetAuraDeBluezSystemBus' "$SHILL_PATCH" || \
  fail 'patch 0038 no longer points Shill at the scoped real bus'

# --- the desktop fake clients stay gated the way 0004 gates them -----------

[[ -r $NETWORK_PATCH ]] || fail 'patch 0004 is missing'
grep -Fq '#if !defined(USE_REAL_DBUS_CLIENTS)' "$NETWORK_PATCH" || \
  fail 'patch 0004 no longer keeps the desktop fake clients behind the build definition'
grep -Fq 'FakeSessionManagerClient' "$NETWORK_PATCH" || \
  fail 'patch 0004 no longer references FakeSessionManagerClient'
grep -Fq 'FakePowerManagerClient' "$NETWORK_PATCH" || \
  fail 'patch 0004 no longer references FakePowerManagerClient'

echo 'Chromium network client configuration test: PASS (flag out, Shill routing guarded)'
