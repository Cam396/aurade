#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# shellcheck source=../lib/aurade-staging.sh
. "$ROOT/installer/lib/aurade-staging.sh"

meminfo="$TMP/meminfo"
export AURADE_MEMINFO=$meminfo
export AURADE_STAGING_MEMORY_RESERVE_BYTES=805306368
package_bytes=1610612736

write_meminfo() {
  printf 'MemAvailable: %s kB\nSwapFree: %s kB\n' "$1" "$2" >"$meminfo"
}

expect_choice() {
  local expected=$1 requested=$2 free_bytes=$3 fs_type=$4 available_kib=$5 swap_kib=$6 actual
  export AURADE_WORKSPACE_FREE_BYTES=$free_bytes
  export AURADE_WORKSPACE_FS_TYPE=$fs_type
  write_meminfo "$available_kib" "$swap_kib"
  actual=$(aurade_select_package_staging "$requested" "$package_bytes" "$TMP")
  [[ $actual == "$expected" ]] || {
    printf 'expected %s staging, got %s\n' "$expected" "$actual" >&2
    exit 1
  }
}

# A four GiB overlay limit does not mean a four GiB RAM budget.
expect_choice target auto 4294967296 overlay 1572864 0

# Enough currently available memory lets the pre-erase route keep its safety
# property, with room left for the live installer.
expect_choice workspace auto 4294967296 overlay 3145728 0

# The smaller of the overlay cap and live memory is the real limit.
expect_choice target auto 1073741824 overlay 3145728 0

# Swap contributes to headroom when the live filesystem can use it.
expect_choice workspace auto 4294967296 tmpfs 1572864 1048576

# A disk-backed workspace is measured by its free disk space, not RAM.
expect_choice workspace auto 3221225472 ext4 1048576 0

# Explicit choices are predictable, and forcing the workspace route still
# refuses a package set that would exhaust it.
expect_choice target target 1 tmpfs 0 0
if aurade_select_package_staging workspace "$package_bytes" "$TMP" >/dev/null; then
  echo 'workspace staging unexpectedly fit without enough headroom' >&2
  exit 1
fi
if aurade_select_package_staging invalid "$package_bytes" "$TMP" >/dev/null 2>&1; then
  echo 'invalid staging mode unexpectedly passed' >&2
  exit 1
fi

echo 'installer package staging test: PASS'
