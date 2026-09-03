#!/bin/bash
# Prove the port and session suite actually bites.
#
# Two patches shipped earlier in this project that compiled, passed a full
# mutation audit of their own assertions, and did nothing at all on the
# hardware. The lesson was not "write more tests", it was that a test which
# passes when you break the thing it names is not a test. So every assertion
# here is checked by breaking the code it covers and requiring the suite to
# fail, by name.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
CHROME_SRC="${CHROME_SRC:-${REPO}/chromium_dev/src}"
AURADE="${CHROME_SRC}/ui/file_manager/file_manager/aurade"

fail() { printf 'aurade port mutation test: %s\n' "$*" >&2; exit 1; }
[ -d "$AURADE" ] || fail "the aurade sources are not at $AURADE (set CHROME_SRC)"

AURADE="$AURADE" python3 - <<'PYEOF'
import os
import subprocess
import sys

A = os.environ["AURADE"]

# label, file, the code to break, what to replace it with, the test that must
# then fail by name.
MUTATIONS = [
    ("the session drops its buffered replay, reopening the list/watch race",
     "session/navigation_session.ts",
     """      listed = true;
      for (const event of buffered) {
        if (event.revision > this.revision) {
          this.applyChange(event);
        }
      }""",
     "      listed = true;",
     "a change that lands during the listing is not lost"),

    ("the session stops cancelling the navigation it is replacing",
     "session/navigation_session.ts",
     "    this.controller?.abort();\n    const controller = new AbortController();",
     "    const controller = new AbortController();",
     "navigating again abandons the first listing"),

    ("the session stops pruning the selection when an entry is removed",
     "session/navigation_session.ts",
     """        for (const key of gone) {
          this.selection.delete(key);
        }""",
     "        void gone;",
     "a removed entry drops out of the selection"),

    ("a range selection collapses to the single item clicked",
     "session/navigation_session.ts",
     """        this.selection = new Set(
            this.entries.slice(lo, hi + 1).map(entry => entry.key));""",
     "        this.selection = new Set([key]);",
     "a range selection is resolved over indices"),

    ("the backend stops honouring the abort signal while listing",
     "port/mock_backend.ts",
     """      if (options.signal?.aborted) {
        return;
      }
      const slice = all.slice(i, i + size);""",
     "      const slice = all.slice(i, i + size);",
     "stops listing when the caller aborts"),

    ("the backend stops advancing the revision when something changes",
     "port/mock_backend.ts",
     """  private bump(key: FileKey): number {
    const next = (this.revisions.get(key) ?? 1) + 1;""",
     """  private bump(key: FileKey): number {
    const next = (this.revisions.get(key) ?? 1);""",
     "the revision advances between a listing and a later change"),

    ("the backend returns every metadata field regardless of the request",
     "port/mock_backend.ts",
     """      const picked: Record<string, unknown> = {};
      for (const field of fields) {
        if (field in node.metadata) {
          picked[field] = (node.metadata as Record<string, unknown>)[field];
        }
      }
      out.set(key, picked as Metadata);""",
     "      void fields;\n      out.set(key, {...node.metadata, mimeType: 'text/plain'});",
     "returns metadata in one batch, limited to the fields asked for"),
]

caught = 0
escaped = []
for label, relative, old, new, expected in MUTATIONS:
    path = os.path.join(A, relative)
    original = open(path).read()
    if original.count(old) != 1:
        escaped.append("%s: anchor matched %d times, so it was never applied"
                       % (label, original.count(old)))
        continue
    open(path, "w").write(original.replace(old, new, 1))
    try:
        run = subprocess.run(["bash", os.path.join(A, "tests/run.sh")],
                             capture_output=True, text=True, timeout=300)
        output = run.stdout + run.stderr
        if run.returncode != 0 and expected in output:
            print("  caught      %s" % label)
            caught += 1
        elif run.returncode != 0:
            escaped.append("%s: the suite failed, but not via '%s'"
                           % (label, expected))
        else:
            escaped.append("%s: NOT CAUGHT" % label)
    finally:
        open(path, "w").write(original)

for line in escaped:
    print("  escaped     %s" % line)
print("aurade port mutation test: %d caught, %d escaped"
      % (caught, len(escaped)))
sys.exit(1 if escaped else 0)
PYEOF
rc=$?
[ "$rc" -eq 0 ] || fail "a mutation went uncaught"
echo "aurade port mutation test: PASS"
