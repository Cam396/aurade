#!/usr/bin/env bash
# Everything in the greeter that decides something, driven to its end.
# No display, no greetd, no account on the machine running this.
set -Eeuo pipefail
trap 'printf "%s: line %s gave up: %s\n" "${0##*/}" "$LINENO" "$BASH_COMMAND" >&2' ERR

here=$(cd -- "$(dirname -- "$0")" && pwd -P)
command -v python3 >/dev/null 2>&1 || {
  echo 'greeter tests: SKIP (python3 not available)'; exit 0; }

status=0
# Enumerated, not listed. A hand written list of test names is a list that
# stops matching the directory, and when it does the suite goes green on a run
# that never executed the missing one. That has already happened once in this
# repository, to three tests at once.
#
# `runtime_test.py` is the one exclusion and it is not skipped: it needs a
# compositor, so `test-runtime.sh` below drives it and says so in its own line.
mapfile -t suites < <(cd -- "${here}/tests" && ls -1 ./*_test.py | sed 's|^\./||' | sort)
ran=0
for test in "${suites[@]}"; do
  [[ $test == runtime_test.py ]] && continue
  python3 "${here}/tests/${test}" || status=1
  ran=$(( ran + 1 ))
done
if (( ran + 1 != ${#suites[@]} )); then
  printf 'greeter tests: %s suites on disk and %s ran\n' \
    "${#suites[@]}" "$ran" >&2
  status=1
fi
# The window itself, on a headless compositor. Skips loudly rather than
# failing when the machine has no compositor, and says so in its own line so
# a run with no runtime coverage cannot be mistaken for a run with it.
bash "${here}/tests/test-runtime.sh" || status=1
exit "${status}"
