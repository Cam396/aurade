#!/usr/bin/env bash
# Exercise the bounded failure view without starting the interactive frontend.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

cat >"$TMP/journal.jsonl" <<'EOF'
{"v":1,"stage":"acquire","status":"failed","message":"archive unavailable","cause":"network_error","remediation":["retry","export","log"]}
EOF
printf '%s\n' 'PRIVATE_RAW_SECRET=must-not-be-printed' >"$TMP/install.log"

set +e
"$ROOT/installer/bin/aurade-install-failure" \
  --status 7 --journal "$TMP/journal.jsonl" --raw-log "$TMP/install.log" \
  --noninteractive >"$TMP/report.out" 2>&1
status=$?
set -e
[[ $status -eq 7 ]]
# The report is built from lib/aurade-copy.sh, so these assertions are also
# what pins the failure helper and the two front ends to the same sentences.
grep -Fq 'The install stopped while downloading packages.' "$TMP/report.out"
# Disk state leads, before any reason for it.
grep -Fq 'Nothing has been changed and no disk was touched.' "$TMP/report.out"
grep -Fq 'The package archive could not be reached.' "$TMP/report.out"
# Exactly one next action, and it is the one for this cause.
grep -Fq 'Check the network connection, then start again.' "$TMP/report.out"
[[ $(grep -c 'then start again\.' "$TMP/report.out") -eq 1 ]]
grep -Fq 'Detail: archive unavailable' "$TMP/report.out"
! grep -Fq 'PRIVATE_RAW_SECRET' "$TMP/report.out"
# No engine cause code reaches the screen.
! grep -Fq 'network_error' "$TMP/report.out"

cat >"$TMP/escaped-journal.jsonl" <<'EOF'
{"stage":"configure","status":"failed","message":"quoted \"stage\":\"fake\" text","cause":"config\\path"}
EOF
set +e
"$ROOT/installer/bin/aurade-install-failure" \
  --status 9 --journal "$TMP/escaped-journal.jsonl" --raw-log "$TMP/install.log" \
  --noninteractive >"$TMP/escaped.out" 2>&1
status=$?
set -e
[[ $status -eq 9 ]]
grep -Fq 'The install stopped while setting things up.' "$TMP/escaped.out"
# An unrecognised cause code is silence plus the stage explanation, never the
# token itself. Printing `keyring_error` at somebody whose install just died is
# the regression this asserts against.
! grep -Fq 'config' "$TMP/escaped.out"
grep -Fq 'Every file is in place.' "$TMP/escaped.out"
grep -Fq 'Save a report, then start again.' "$TMP/escaped.out"
# A message that contains a quoted field must not impersonate one.
! grep -Fq 'fake' "$TMP/escaped.out"

set +e
"$ROOT/installer/bin/aurade-install-failure" \
  --status 7 --journal "$TMP/journal.jsonl" --raw-log "$TMP/install.log" \
  --export "$TMP/export" >"$TMP/export.out" 2>&1
status=$?
set -e
[[ $status -eq 7 ]]
[[ $(stat -c '%a' "$TMP/export/journal.jsonl") == 600 ]]
[[ $(stat -c '%a' "$TMP/export/install.log") == 600 ]]
grep -Fq 'Report saved to' "$TMP/export.out"

if "$ROOT/installer/bin/aurade-install-failure" --status 7 --journal "$TMP/missing-journal" \
  --raw-log "$TMP/missing-log" --export "$TMP/missing-export" >"$TMP/missing.out" 2>&1; then
  echo 'empty diagnostic export unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'there is nothing to save yet' "$TMP/missing.out"

if "$ROOT/installer/bin/aurade-install-failure" --status >"$TMP/missing-arg.out" 2>&1; then
  echo 'missing status argument unexpectedly passed' >&2
  exit 1
fi
grep -Fq -- '--status requires an argument' "$TMP/missing-arg.out"

echo 'installer failure view test: PASS'
