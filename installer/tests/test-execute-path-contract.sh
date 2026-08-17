#!/usr/bin/env bash
set -Eeuo pipefail
# These assertions are bare `grep -Fq` under `set -e`, so a stale expectation
# ends the run with an exit code and not one word about where. This makes each
# of them name itself on the way out. Guarded on errexit still being on,
# because a non-zero exit inside a deliberate `set +e` block is an expected
# result being collected, not an assertion giving up.
trap 'case $- in *e*) printf "%s: line %s gave up: %s\n" "${0##*/}" "$LINENO" "$BASH_COMMAND" >&2 ;; esac' ERR

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
  'does not prove partitioning' \
  'installer/tests/test-execute-path-gate.sh' \
  'AURADE_EXECUTE_PATH_TEST=1' \
  'full disposable execute-path evidence'; do
  grep -Fq -- "$marker" "$CONTRACT" || {
    echo "execute-path contract missing required assertion: $marker" >&2
    exit 1
  }
done

echo 'execute-path validation contract test: PASS'
