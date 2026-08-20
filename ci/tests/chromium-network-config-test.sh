#!/usr/bin/env bash
# Fixture coverage for the real network client build boundary.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PKGBUILD="$ROOT/chromiumos-ash/PKGBUILD"
NETWORK_PATCH="$ROOT/patches/0004-session-lifecycle-generic-linux.patch"

grep -Fq 'use_real_dbus_clients = true' "$PKGBUILD"
grep -Fq -- "-DUSE_REAL_DBUS_CLIENTS" "$PKGBUILD"
grep -Fq 'toolchain.ninja' "$PKGBUILD"
grep -Fq 'generated Chromium build is missing real D-Bus clients' "$PKGBUILD"

# The package guard is only useful if the patch series still gates the desktop
# fake clients behind the same build definition. Keep this fixture source based
# so it fails before a package or image can publish demo network services.
grep -Fq '#if !defined(USE_REAL_DBUS_CLIENTS)' "$NETWORK_PATCH"
grep -Fq 'FakeSessionManagerClient' "$NETWORK_PATCH"
grep -Fq 'FakePowerManagerClient' "$NETWORK_PATCH"

echo 'Chromium network client configuration test: PASS'
