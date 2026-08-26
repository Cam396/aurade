#!/usr/bin/env bash
# Everything in the greeter that decides something, driven to its end.
# No display, no greetd, no account on the machine running this.
set -Eeuo pipefail
trap 'printf "%s: line %s gave up: %s\n" "${0##*/}" "$LINENO" "$BASH_COMMAND" >&2' ERR

here=$(cd -- "$(dirname -- "$0")" && pwd -P)
command -v python3 >/dev/null 2>&1 || {
  echo 'greeter tests: SKIP (python3 not available)'; exit 0; }

status=0
for test in protocol accounts sessions preferences shared; do
  python3 "${here}/tests/${test}_test.py" || status=1
done
# The window itself, on a headless compositor. Skips loudly rather than
# failing when the machine has no compositor, and says so in its own line so
# a run with no runtime coverage cannot be mistaken for a run with it.
bash "${here}/tests/test-runtime.sh" || status=1
exit "${status}"
