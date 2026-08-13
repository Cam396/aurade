#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
CONTRACT=$ROOT/installer/EXECUTE_PATH_CONTRACT.md
[[ -r $CONTRACT ]] || { echo 'execute-path contract is missing' >&2; exit 1; }

for marker in \
  'sparse loop device, a disposable VMware guest disk' \
  'no host boot disk' \
  'must not fabricate' \
  'plain and LUKS2 paths' \
  'Package acquisition and signature/hash verification finish before' \
  'First boot reaches the greeter' \
  'factory rollback' \
  'machine-readable journal' \
  'does not prove partitioning'; do
  grep -Fq -- "$marker" "$CONTRACT" || {
    echo "execute-path contract missing required assertion: $marker" >&2
    exit 1
  }
done

echo 'execute-path validation contract test: PASS'
