#!/usr/bin/env bash
# Fixture coverage for the real network client build boundary.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PKGBUILD="$ROOT/chromiumos-ash/PKGBUILD"

grep -Fq 'use_real_dbus_clients = true' "$PKGBUILD"
grep -Fq -- "-DUSE_REAL_DBUS_CLIENTS" "$PKGBUILD"
grep -Fq 'toolchain.ninja' "$PKGBUILD"
grep -Fq 'generated Chromium build is missing real D-Bus clients' "$PKGBUILD"

echo 'Chromium network client configuration test: PASS'
