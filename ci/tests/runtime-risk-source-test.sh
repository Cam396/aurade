#!/usr/bin/env bash
# Source-level regression guard for the unresolved right-click/runtime risk.
# This does not claim that a packaged ISO or VM is fixed.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
series=$ROOT/patches/SERIES
null_guard=$ROOT/patches/0009-misc-null-guards.patch
session_init=$ROOT/patches/0011-login-shelf-active-user-init.patch

grep -Fxq '0009-misc-null-guards.patch' "$series"
grep -Fxq '0011-login-shelf-active-user-init.patch' "$series"

# The context-menu path must not dereference an unset active-account optional.
grep -Fq 'if (show_for_current_user && current_account_id_.has_value())' \
  "$null_guard"
grep -Fq 'if (current_account_id_.has_value() &&' "$null_guard"
grep -Fq 'transient window creation (e.g. right-click context menu)' \
  "$null_guard"

# The Linux session shim must initialize the Ash observers when the normal
# session_manager fan-out is unavailable.
grep -Fq 'muwm->OnActiveUserSessionChanged(account_id);' "$session_init"
grep -Fq 'desks_client->OnActiveUserSessionChanged(account_id);' "$session_init"

echo 'runtime-risk source regression guard: PASS (runtime VM evidence still required)'
