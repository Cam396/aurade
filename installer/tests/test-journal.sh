#!/usr/bin/env bash
# Behavioural tests for the install journal contract.
#
# The journal is what the progress display, the failure screen and the resume
# decision are all built from, so a malformed or lying record is not a cosmetic
# problem. Every assertion here runs the library and parses its output.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

export AURADE_JOURNAL_PATH="$TMP/journal.jsonl"
export AURADE_JOURNAL_RAW="$TMP/install.log"
export AURADE_FAILURE_JOURNAL_DIR="$TMP/failure-evidence"

# shellcheck source=../lib/aurade-journal.sh
. "$ROOT/installer/lib/aurade-journal.sh"

failures=0
fail() { printf 'FAIL: %s\n' "$*" >&2; failures=$((failures + 1)); }

jq_py() { python3 -c "$1" <"$AURADE_JOURNAL_PATH"; }

# ---- emit a representative stream -------------------------------------------
aurade_journal_init execute
aurade_journal_begin preflight 'checking hardware'
aurade_journal_ok preflight
aurade_journal_begin acquire 'downloading packages'
[[ $_J_ACTIVE_STAGE == acquire ]] || fail 'begin should record the active stage'
aurade_journal_progress acquire 42 '612/1041 packages'
aurade_journal_ok acquire
[[ -z $_J_ACTIVE_STAGE ]] || fail 'ok should clear the active stage'
aurade_journal_begin partition
aurade_journal_begin bootloader
aurade_journal_fail bootloader 1 esp-readonly \
  'bootctl could not write to the EFI system partition' \
  retry export log shell reboot
[[ -z $_J_ACTIVE_STAGE ]] || fail 'fail should clear the active stage'
# Values that would break naive JSON emission.
aurade_journal_emit configure running 'quote " backslash \ newline
tab	end'

# ---- every line must be valid JSON ------------------------------------------
if ! python3 - "$AURADE_JOURNAL_PATH" <<'PY'
import json, sys
bad = 0
for n, line in enumerate(open(sys.argv[1]), 1):
    line = line.strip()
    if not line:
        continue
    try:
        json.loads(line)
    except Exception as e:
        print("line %d is not valid JSON: %s" % (n, e), file=sys.stderr)
        bad += 1
sys.exit(1 if bad else 0)
PY
then
  fail 'journal contains invalid JSON'
fi

# ---- structural invariants ---------------------------------------------------
set +e
python3 - "$AURADE_JOURNAL_PATH" >"$TMP/checks" <<'PY'
import json, sys
recs = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
out = []

def check(name, cond):
    out.append("%s %s" % ("PASS" if cond else "FAIL", name))

check("every record has install_id", all(r.get("install_id") for r in recs))
check("install_id is stable", len({r["install_id"] for r in recs}) == 1)
check("seq is strictly increasing",
      [r["seq"] for r in recs] == sorted(r["seq"] for r in recs)
      and len({r["seq"] for r in recs}) == len(recs))
check("every record has attempt", all("attempt" in r for r in recs))
check("every record carries target identity",
      all({"path", "serial", "wwn", "size_bytes"} <= set(r["target"]) for r in recs))

rev = {r["stage"]: r["reversible"] for r in recs}
check("preflight is reversible", rev.get("preflight") is True)
check("acquire is reversible", rev.get("acquire") is True)
check("partition is NOT reversible", rev.get("partition") is False)
check("bootloader is NOT reversible", rev.get("bootloader") is False)

idem = {r["stage"]: r["idempotent"] for r in recs}
check("bootloader is idempotent", idem.get("bootloader") is True)

f = [r for r in recs if r["status"] == "failed"]
check("failure record exists", len(f) == 1)
if f:
    r = f[0]
    check("failure has bounded cause", r.get("cause") == "esp-readonly")
    check("failure has exit code", r.get("exit") == 1)
    check("failure lists remediation",
          r.get("remediation") == ["retry", "export", "log", "shell", "reboot"])
    check("idempotent failure is resumable", r.get("resumable") is True)

p = [r for r in recs if r.get("pct") is not None]
check("progress record carries pct", any(r["pct"] == 42 for r in p))
check("progress detail is caller-authored",
      any(r.get("message") == "612/1041 packages" for r in recs))

raw = open(sys.argv[1]).read()
check("every record occupies exactly one line",
      len([l for l in raw.splitlines() if l.strip()]) == len(recs))
check("newlines are escaped in the file, never literal",
      "\\n" in raw)
check("embedded control characters round-trip through the parser",
      any("\n" in r.get("message", "") and "\t" in r.get("message", "")
          for r in recs))
check("quotes and backslashes round-trip",
      any('quote " backslash \\' in r.get("message", "") for r in recs))

print("\n".join(out))
sys.exit(1 if any(l.startswith("FAIL") for l in out) else 0)
PY
rc=$?
set -e
cat "$TMP/checks"
(( rc == 0 )) || fail 'structural invariants violated'

# ---- the raw log must stay out of the structured stream ----------------------
aurade_journal_raw 'pacstrap: error: failed to commit transaction'
if grep -q 'failed to commit transaction' "$AURADE_JOURNAL_PATH"; then
  fail 'raw command output leaked into the JSONL stream'
fi
grep -q 'failed to commit transaction' "$AURADE_JOURNAL_RAW" \
  || fail 'raw log did not receive the output'

# Failure persistence is opt-in and structured-only: the package cache and
# raw log must never be copied into the disk-backed evidence directory.
preserved=$(aurade_journal_preserve_failure)
[[ -r $preserved/journal.jsonl ]] || fail 'failure journal was not preserved'
[[ $(stat -c '%a' "$preserved/journal.jsonl") == 600 ]] || \
  fail 'preserved journal should be mode 600'
[[ ! -e $preserved/install.log ]] || fail 'raw log leaked into preserved evidence'
grep -Fq '"stage":"bootloader"' "$preserved/journal.jsonl" || \
  fail 'preserved journal contents are incomplete'

# ---- resume safety -----------------------------------------------------------
# A stage that cannot safely re-run must never be offered as resumable.
if aurade_journal_may_resume snapshot /dev/null; then
  fail 'snapshot must not be resumable'
fi
if aurade_journal_may_resume bootloader /dev/does-not-exist; then
  fail 'resume must refuse a missing device'
fi
# Identity mismatch must refuse even when the stage itself is idempotent.
_J_TARGET_SERIAL=SOME-OTHER-SERIAL
_J_TARGET_SIZE=999999999999
if aurade_journal_may_resume bootloader /dev/null; then
  fail 'resume must refuse when target identity does not match'
fi

# Resume identity matching is strict even when a device exposes no serial:
# a recorded WWN is sufficient, but an empty serial+WWN or a changed WWN is
# never accepted. This pure helper test avoids pretending /dev/null is a disk.
_J_TARGET_SERIAL=
_J_TARGET_WWN=wwn-expected
_J_TARGET_SIZE=4096
aurade_journal_target_identity_matches '' wwn-expected 4096 || \
  fail 'resume should accept a matching recorded WWN'
if aurade_journal_target_identity_matches '' wwn-other 4096; then
  fail 'resume accepted a changed WWN'
fi
_J_TARGET_WWN=
if aurade_journal_target_identity_matches '' '' 4096; then
  fail 'resume accepted a target with no stable identity'
fi

# A journal write failure must be observable to the caller rather than being
# silently ignored. A regular file in the parent path makes the fixture fail
# even when this suite runs as root.
blocked_parent="$TMP/journal-parent-file"
printf '%s\n' blocked >"$blocked_parent"
blocked_journal="$blocked_parent/journal.jsonl"
blocked_raw="$TMP/blocked.log"
if (
  export AURADE_JOURNAL_PATH="$blocked_journal" AURADE_JOURNAL_RAW="$blocked_raw"
  . "$ROOT/installer/lib/aurade-journal.sh"
  aurade_journal_init dry-run
) >"$TMP/blocked.out" 2>&1; then
  fail 'journal initialization unexpectedly succeeded under a file parent'
fi
grep -Fq 'cannot create structured journal' "$TMP/blocked.out"

# ---- permissions -------------------------------------------------------------
perms=$(stat -c '%a' "$AURADE_JOURNAL_PATH")
[[ $perms == 600 ]] || fail "journal should be mode 600, found $perms"

# A process can exit from the middle of a stage without a helper-specific
# cause. The engine's EXIT trap must still leave a bounded, secret-free record
# that the failure UI can render.
unexpected_journal="$TMP/unexpected.jsonl"
unexpected_raw="$TMP/unexpected.log"
unexpected_script="$TMP/unexpected-exit.sh"
cat >"$unexpected_script" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
. "${AURADE_TEST_JOURNAL_LIB}"
aurade_journal_init execute /dev/does-not-exist
aurade_journal_begin pacstrap 'installing the base system'
cleanup() {
  local status=$?
  set +e
  if (( status != 0 )) && [[ -n ${_J_ACTIVE_STAGE:-} ]]; then
    aurade_journal_fail "$_J_ACTIVE_STAGE" "$status" unexpected_exit \
      'installer stopped unexpectedly. The private install log records where.' \
      log shell reboot
  fi
  aurade_journal_preserve_failure >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT
exit 23
EOF
chmod 0755 "$unexpected_script"
if AURADE_TEST_JOURNAL_LIB="$ROOT/installer/lib/aurade-journal.sh" \
  AURADE_JOURNAL_PATH="$unexpected_journal" AURADE_JOURNAL_RAW="$unexpected_raw" \
  AURADE_FAILURE_JOURNAL_DIR="$TMP/unexpected-failures" \
  "$unexpected_script"; then
  fail 'unexpected-exit fixture unexpectedly returned success'
fi
python3 - "$unexpected_journal" <<'PY'
import json, sys
records = [json.loads(line) for line in open(sys.argv[1]) if line.strip()]
assert any(
    record.get("stage") == "pacstrap"
    and record.get("status") == "failed"
    and record.get("cause") == "unexpected_exit"
    and record.get("exit") == 23
    and record.get("remediation") == ["log", "shell", "reboot"]
    for record in records
), records
PY
preserved_unexpected=$(find "$TMP/unexpected-failures" -type f -name journal.jsonl -print -quit)
[[ -n $preserved_unexpected ]] || fail 'unexpected exit did not preserve the journal'
[[ ! -e ${preserved_unexpected%/journal.jsonl}/install.log ]] || \
  fail 'unexpected-exit preservation copied the raw log'

# A specific fatal cause clears the active stage before EXIT; cleanup must
# still preserve the journal rather than treating the record as success.
classified_journal="$TMP/classified.jsonl"
classified_script="$TMP/classified-exit.sh"
cat >"$classified_script" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
. "${AURADE_TEST_JOURNAL_LIB}"
aurade_journal_init execute /dev/does-not-exist
aurade_journal_begin acquire 'downloading packages'
aurade_journal_fail acquire 1 keyring_error 'keyring setup failed' log shell reboot
cleanup() {
  local status=$?
  set +e
  aurade_journal_preserve_failure >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT
exit 41
EOF
chmod 0755 "$classified_script"
if AURADE_TEST_JOURNAL_LIB="$ROOT/installer/lib/aurade-journal.sh" \
  AURADE_JOURNAL_PATH="$classified_journal" \
  AURADE_FAILURE_JOURNAL_DIR="$TMP/classified-failures" \
  "$classified_script"; then
  fail 'classified fatal fixture unexpectedly returned success'
fi
classified_preserved=$(find "$TMP/classified-failures" -type f -name journal.jsonl -print -quit)
[[ -n $classified_preserved ]] || fail 'classified fatal journal was not preserved'
grep -Fq '"cause":"keyring_error"' "$classified_preserved" || \
  fail 'classified fatal cause was not preserved'

# --- pacstrap reports how far through it is --------------------------------
#
# This is the six minute step, and it used to report nothing at all, so the
# bar sat still for the longest part of the install. That is exactly when
# somebody starts wondering whether the machine has stopped.
#
# Three things are checked, and the third is the one that was wrong twice.
PACSTRAP_TMP=$TMP/pacstrap
install -d "$PACSTRAP_TMP"
(
  set -Eeuo pipefail
  export AURADE_JOURNAL_PATH=$PACSTRAP_TMP/journal.jsonl
  # shellcheck source=../lib/aurade-journal.sh
  . "$ROOT/installer/lib/aurade-journal.sh"
  aurade_journal_init execute /dev/sda >/dev/null 2>&1 || true
  _PACSTRAP_MARK='@@aurade-pacstrap-status@@'
  # The real function, lifted out of the engine so it can be driven without
  # one. Copying it would test the copy.
  eval "$(sed -n '/^run_pacstrap_logged() {/,/^}/p' "$ROOT/installer/bin/aurade-install")"

  pretend_pacstrap() {
    printf 'resolving dependencies...\n'
    local i
    for i in 1 40 90 160 260 331; do
      printf '( %s/331) installing package-%s\n' "$i" "$i"
    done
    return 0
  }
  run_pacstrap_logged "$PACSTRAP_TMP/attempt.log" pretend_pacstrap

  # And a failure, which has to come back as the status pacstrap exited with
  # rather than as a generic one. The cause codes downstream are chosen from
  # it, so flattening every failure to 1 makes every failure look the same.
  failing_pacstrap() { printf '( 3/331) installing x\n'; return 17; }
  status=0
  run_pacstrap_logged "$PACSTRAP_TMP/attempt.log" failing_pacstrap || status=$?
  printf '%s\n' "$status" >"$PACSTRAP_TMP/status"
) || fail 'the pacstrap progress reader could not be driven'

grep -q '"pct":' "$PACSTRAP_TMP/journal.jsonl" ||
  fail 'pacstrap wrote no progress at all, so the bar cannot move during it'
grep -Fq '331 of 331 packages' "$PACSTRAP_TMP/journal.jsonl" ||
  fail 'pacstrap never reported reaching the end of the transaction'

# The sequence numbers, which is the reason the reader does not run at the end
# of a pipe. A `while read` on the right of a pipe is a subshell, the counter
# increments inside it and is thrown away, and every record after pacstrap
# reuses a number already on disk.
duplicates=$(grep -o '"seq":[0-9]*' "$PACSTRAP_TMP/journal.jsonl" |
  sed 's/.*://' | sort -n | uniq -d | wc -l)
(( duplicates == 0 )) ||
  fail "pacstrap progress reused $duplicates journal sequence numbers"

status=$(cat "$PACSTRAP_TMP/status" 2>/dev/null || printf '')
[[ $status == 17 ]] ||
  fail "a pacstrap that exited 17 was reported as '$status'"

# And the marker the status travels on never reaches the log a human reads.
! grep -q 'aurade-pacstrap-status' "$PACSTRAP_TMP/attempt.log" ||
  fail 'the internal status marker was written into the installer log'

if (( failures )); then
  printf 'installer journal test: FAIL (%d)\n' "$failures" >&2
  exit 1
fi
echo 'installer journal test: PASS'
