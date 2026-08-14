#!/usr/bin/env bash
# Contract guard for the unresolved right-click/NetworkService runtime item.
# This verifies the evidence checklist only; it does not perform GUI actions,
# start a VM, or claim that the packaged runtime is healthy.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
review=$ROOT/NETWORKSERVICE_RIGHT_CLICK_REVIEW.md

grep -Fq '## Required disposable-VM evidence' "$review"
grep -Fq 'invoke a browser/content right-click menu' "$review"
grep -Fq 'invoke a shelf/window right-click menu' "$review"
grep -Fq 'repeat after connecting and' "$review"
grep -Fq 'disconnecting NetworkManager' "$review"
grep -Fq 'Watch `coredumpctl`, the Ash/Chrome log' "$review"
grep -Fq 'systemctl status NetworkManager' "$review"
grep -Fq 'do not describe the right-click/NetworkService' "$review"
grep -Fq 'without pretending that a shell smoke' "$review"
grep -Fq 'runner can perform human GUI actions' "$review"

echo 'right-click/NetworkService runtime contract: PASS (disposable-VM evidence still required)'
