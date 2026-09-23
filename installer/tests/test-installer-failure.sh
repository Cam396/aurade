#!/usr/bin/env bash
# Exercise the bounded failure view without starting the interactive frontend.
set -Eeuo pipefail
# These assertions are bare `grep -Fq` under `set -e`, so a stale expectation
# ends the run with an exit code and not one word about where. This makes each
# of them name itself on the way out. Guarded on errexit still being on,
# because a non-zero exit inside a deliberate `set +e` block is an expected
# result being collected, not an assertion giving up.
trap 'case $- in *e*) printf "%s: line %s gave up: %s\n" "${0##*/}" "$LINENO" "$BASH_COMMAND" >&2 ;; esac' ERR
# shellcheck source=assert.sh
. "$(dirname -- "$0")/assert.sh"


ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)

# The frame grows with the terminal, so the width is pinned here the way the
# height already is. Without it a screen rendered on a build machine with a
# wide terminal and the same screen rendered in CI are different screens, and
# every column measurement below is measuring the margin.
export AURADE_TUI_COLUMNS=68

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

cat >"$TMP/journal.jsonl" <<'EOF'
{"v":1,"stage":"package-check","status":"ok","message":"workspace"}
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
grep -Fq 'Nothing has been changed. A package could not be downloaded.' "$TMP/report.out"
grep -Fq 'The package archive could not be reached.' "$TMP/report.out"
# Exactly one next action, and it is the one for this cause.
grep -Fq 'Check the network connection, then start again.' "$TMP/report.out"
[[ $(grep -c 'then start again\.' "$TMP/report.out") -eq 1 ]]
grep -Fq 'Detail: archive unavailable' "$TMP/report.out"
refute grep -Fq 'PRIVATE_RAW_SECRET' "$TMP/report.out"
# No engine cause code reaches the screen.
refute grep -Fq 'network_error' "$TMP/report.out"

# A low-memory download happens after formatting, so its failure must describe
# the disk as already changed and use the target-disk download stage.
cat >"$TMP/target-journal.jsonl" <<'EOF'
{"v":1,"stage":"package-check","status":"ok","message":"target"}
{"v":1,"stage":"confirm","status":"ok"}
{"v":1,"stage":"partition","status":"ok"}
{"v":1,"stage":"format","status":"ok"}
{"v":1,"stage":"mount","status":"ok"}
{"v":1,"stage":"acquire-target","status":"failed","exit":1,"cause":"network_error","message":"archive unavailable","reversible":false,"remediation":["retry","export","log"]}
EOF
set +e
"$ROOT/installer/bin/aurade-install-failure" \
  --status 7 --journal "$TMP/target-journal.jsonl" --raw-log "$TMP/install.log" \
  --noninteractive >"$TMP/target-report.out" 2>&1
status=$?
set -e
[[ $status -eq 7 ]]
grep -Fq 'The install stopped while downloading packages to disk.' "$TMP/target-report.out"
grep -Fq 'The disk is partitioned and formatted. A package could not be downloaded.' \
  "$TMP/target-report.out"
! grep -Fq 'Nothing has been changed' "$TMP/target-report.out"

cat >"$TMP/escaped-journal.jsonl" <<'EOF'
{"stage":"package-check","status":"ok","message":"workspace"}
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
refute grep -Fq 'config' "$TMP/escaped.out"
grep -Fq 'Every file is in place.' "$TMP/escaped.out"
grep -Fq 'Save a report, then start again.' "$TMP/escaped.out"
# A message that contains a quoted field must not impersonate one.
#
# The message itself is echoed back under `Detail:`, so the word is on the
# screen once and has to be: refusing to print somebody's own failure message
# is not the protection here. What must not happen is the parser reading
# `"stage":"fake"` out of the middle of a string and believing it, which the
# headline above already proves it did not. So the check is that the word
# appears nowhere except in the message it came from.
#
# Written this way because the obvious version, a bare `! grep -Fq fake`, was
# true of the whole file and quietly wrong for eleven months, and because a
# bare `!` under `set -e` could not have failed even if it had been right.
grep -v '^Detail: ' "$TMP/escaped.out" >"$TMP/escaped.nodetail"
refute grep -Fq 'fake' "$TMP/escaped.nodetail"
# And the message that was echoed is the whole message, JSON escaping and all.
# Unescaping it for display would mean a `\n` in a journal message becoming a
# real newline in a report that is read a line at a time, which is how a
# message starts impersonating a field again.
grep -Fq 'Detail: quoted \"stage\":\"fake\" text' "$TMP/escaped.out"

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

# --- the report leads with one line -----------------------------------------
#
# Somebody whose machine will not boot is going to read this off a phone
# camera or paste it into a chat, so the first line has to carry the whole
# answer without a second line: which stage, which cause, which exit status.
[[ $(stat -c '%a' "$TMP/export/summary.txt") == 600 ]]
head -n 1 "$TMP/export/summary.txt" >"$TMP/summary.first"
grep -Fqx \
  'AuraDE install failed during Downloading packages (cause network_error), exit 7.' \
  "$TMP/summary.first"
# The engine's cause code belongs in the report and never on the screen: the
# report is read by whoever is answering, the screen by whoever is stuck. Both
# halves are asserted so neither drifts into the other.
refute grep -Fq 'network_error' "$TMP/report.out"
# Short enough that "leads with" stays true. The provenance under it is three
# lines and a blank; a summary that grows a paragraph is no longer a summary.
[[ $(wc -l <"$TMP/export/summary.txt") -le 6 ]]
grep -Fq 'Journal: journal.jsonl' "$TMP/export/summary.txt"
grep -Fq 'Log: install.log' "$TMP/export/summary.txt"
# The raw log is copied verbatim next to it, and the summary is not allowed to
# quote from it. This is what stops a future "include the last line of the log"
# from putting a secret into the one file people paste into chat.
refute grep -Fq 'PRIVATE_RAW_SECRET' "$TMP/export/summary.txt"

# A failure recorded with no stage still gets a first line. The branch exists
# because a summary that reads "failed during ,  exit 7." is worse than no
# summary, and an engine that dies before it opens a stage is the case that
# produces it.
cat >"$TMP/stageless.jsonl" <<'EOF'
{"v":1,"status":"failed","message":"stopped before a stage was opened"}
EOF
set +e
"$ROOT/installer/bin/aurade-install-failure" \
  --status 4 --journal "$TMP/stageless.jsonl" --raw-log "$TMP/install.log" \
  --export "$TMP/stageless-export" >"$TMP/stageless.out" 2>&1
status=$?
set -e
[[ $status -eq 4 ]]
head -n 1 "$TMP/stageless-export/summary.txt" >"$TMP/stageless.first"
grep -Fqx 'AuraDE install failed, exit 4. No stage was recorded.' "$TMP/stageless.first"

if "$ROOT/installer/bin/aurade-install-failure" --status 7 --journal "$TMP/missing-journal" \
  --raw-log "$TMP/missing-log" --export "$TMP/missing-export" >"$TMP/missing.out" 2>&1; then
  echo 'empty diagnostic export unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'nothing to save yet' "$TMP/missing.out"

if "$ROOT/installer/bin/aurade-install-failure" --status >"$TMP/missing-arg.out" 2>&1; then
  echo 'missing status argument unexpectedly passed' >&2
  exit 1
fi
grep -Fq -- '--status requires an argument' "$TMP/missing-arg.out"

# --- where a saved report goes ----------------------------------------------
#
# The default is under /run, which is tmpfs, so the report a user saves after a
# failed install is gone the moment they do the obvious next thing and restart.
# The save appeared to work, it named a path, and the file is not there when it
# is finally wanted. That is a bug wearing a feature's clothes.
#
# So the front end looks for somewhere a removable disk is mounted first, and
# when there is nowhere it says out loud that what it wrote is in memory.
export AURADE_INSTALLER_TUI_LIB=1
# shellcheck source=../bin/aurade-installer-tui
. "$ROOT/installer/bin/aurade-installer-tui"
unset AURADE_INSTALLER_TUI_LIB

install -d "$TMP/media/AURADE-STICK" "$TMP/media/GHOST" "$TMP/nothing" "$TMP/run"
EXPORT_DIR=$TMP/run
# One stick actually mounted, and one directory left behind by a stick that
# was unplugged. The second is writable and would silently take the report.
printf '%s\n' \
  "/dev/sdz1 $TMP/media/AURADE-STICK vfat rw,noatime 0 0" \
  "tmpfs $TMP/media tmpfs rw 0 0" >"$TMP/mounts"
AURADE_MOUNTS_FILE=$TMP/mounts

AURADE_MEDIA_DIRS=$TMP/media
export_root
[[ $EXPORT_ROOT == "$TMP/media/AURADE-STICK/aurade-install" ]] ||
  { echo "a mounted stick was not chosen: got '$EXPORT_ROOT'" >&2; exit 1; }
(( EXPORT_VOLATILE == 0 )) ||
  { echo 'a real filesystem was reported as volatile' >&2; exit 1; }

if export_durable "$TMP/media/GHOST"; then
  echo 'a directory left behind by an unplugged stick was accepted' >&2
  exit 1
fi

AURADE_MEDIA_DIRS=$TMP/nothing
export_root
[[ $EXPORT_ROOT == "$TMP/run" ]] ||
  { echo "with nothing mounted the report should stay put: got '$EXPORT_ROOT'" >&2; exit 1; }
(( EXPORT_VOLATILE == 1 )) ||
  { echo 'the in-memory fallback was not reported as volatile' >&2; exit 1; }

# The disk being installed to is never a candidate, however it came to be
# searched. A report about a half written disk, written onto that disk, is the
# one destination worse than losing it.
AURADE_TARGET_MOUNT=$TMP/media/AURADE-STICK
if export_durable "$TMP/media/AURADE-STICK"; then
  echo 'the target mountpoint was accepted as a place to save a report' >&2
  exit 1
fi

echo 'installer failure view test: PASS'
