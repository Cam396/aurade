#!/usr/bin/env bash
# Exercise the bounded failure view without starting the interactive frontend.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

cat >"$TMP/journal.jsonl" <<'EOF'
{"v":1,"stage":"acquire","status":"failed","message":"archive unavailable","cause":"archive-unreachable","remediation":["retry","export","log"]}
EOF
printf '%s\n' 'PRIVATE_RAW_SECRET=must-not-be-printed' >"$TMP/install.log"

set +e
"$ROOT/installer/bin/aurade-install-failure" \
  --status 7 --journal "$TMP/journal.jsonl" --raw-log "$TMP/install.log" \
  --noninteractive >"$TMP/report.out" 2>&1
status=$?
set -e
[[ $status -eq 7 ]]
grep -Fq 'stage: acquire' "$TMP/report.out"
grep -Fq 'cause: archive-unreachable' "$TMP/report.out"
grep -Fq 'detail: archive unavailable' "$TMP/report.out"
! grep -Fq 'PRIVATE_RAW_SECRET' "$TMP/report.out"

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
grep -Fq 'stage: configure' "$TMP/escaped.out"
grep -Fq 'cause: config\\path' "$TMP/escaped.out"
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
grep -Fq 'Diagnostic logs exported' "$TMP/export.out"

if "$ROOT/installer/bin/aurade-install-failure" --status 7 --journal "$TMP/missing-journal" \
  --raw-log "$TMP/missing-log" --export "$TMP/missing-export" >"$TMP/missing.out" 2>&1; then
  echo 'empty diagnostic export unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'no readable journal or raw log' "$TMP/missing.out"

if "$ROOT/installer/bin/aurade-install-failure" --status >"$TMP/missing-arg.out" 2>&1; then
  echo 'missing status argument unexpectedly passed' >&2
  exit 1
fi
grep -Fq -- '--status requires an argument' "$TMP/missing-arg.out"

echo 'installer failure view test: PASS'
