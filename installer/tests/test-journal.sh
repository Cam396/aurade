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

# ---- permissions -------------------------------------------------------------
perms=$(stat -c '%a' "$AURADE_JOURNAL_PATH")
[[ $perms == 600 ]] || fail "journal should be mode 600, found $perms"

if (( failures )); then
  printf 'installer journal test: FAIL (%d)\n' "$failures" >&2
  exit 1
fi
echo 'installer journal test: PASS'
