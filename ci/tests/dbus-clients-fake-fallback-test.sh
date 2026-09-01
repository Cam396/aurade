#!/usr/bin/env bash
# The D-Bus client fallback, and why removing it takes the whole desktop out.
#
# AuraDE builds with use_real_dbus_clients=true, which is asserted by
# chromium-network-config-test.sh and is in the PKGBUILD on purpose. That
# define makes InitializeDBusClient call T::Initialize(bus) with no null
# check. In August 2026 upstream hardened about seventy clients under
# chromeos/ash/components/dbus so that Initialize opens with CHECK(bus).
#
# On generic Linux DBusThreadManager has no global system bus, so that branch
# hands null to the first client in ash_dbus_helper's list,
# AnomalyDetectorClient, and the browser aborts inside
# PostEarlyInitialization. There is no window, nothing on screen, and the
# session supervisor gives up after five quick exits and falls back to the
# greeter. It is about as far from a diagnosable failure as a build can get,
# which is why this fixture exists.
#
# The fallback must stay inside the USE_REAL_DBUS_CLIENTS branch. Deleting the
# define instead would also stop the abort, but it would change which clients
# are real across the whole product, so that is not the fix and this fixture
# does not accept it.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0055-dbus-clients-fall-back-to-fakes.patch"

fail() { echo "dbus client fake fallback test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0055 is missing'
grep -Fqx '0055-dbus-clients-fall-back-to-fakes.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0055 is not listed in SERIES'

added=$(grep '^+' "$PATCH" | grep -v '^+++' || true)
removed=$(grep '^-' "$PATCH" | grep -v '^---' || true)
[[ -n $added ]] || fail 'patch 0055 adds nothing'
code=$(grep -vE '^\+[[:space:]]*(//|/\*|\*)' <<<"$added" || true)
result=$(grep -E '^[+ ]' "$PATCH" | grep -v '^+++' || true)

# --- one file, and the right one -------------------------------------------

# Two files, because there are two ways the fallback gets compiled out. The
# template in the header covers the fifty or so clients that go through
# InitializeDBusClient. hermes_clients is called directly by ash_dbus_helper
# and carries its own copy of the same guard, so fixing only the header moves
# the abort one step later instead of removing it.
targets=$(grep -c '^diff --git ' "$PATCH")
[[ $targets -eq 2 ]] || fail "expected exactly 2 files, found ${targets}"

grep -q '^+++ b/chromeos/dbus/init/initialize_dbus_client\.h$' "$PATCH" || \
  fail 'patch 0055 does not target chromeos/dbus/init/initialize_dbus_client.h'

grep -q '^+++ b/chromeos/ash/components/dbus/hermes/hermes_clients\.cc$' "$PATCH" || \
  fail 'patch 0055 does not fix hermes_clients.cc, so the abort just moves one client later'

grep -q '^--- /dev/null$' "$PATCH" && fail 'patch 0055 creates a new file'

# --- the unguarded call is what goes away ----------------------------------

grep -qE '^-[[:space:]]*T::Initialize\(bus\);[[:space:]]*$' <<<"$removed" || \
  fail 'the unguarded T::Initialize(bus) is not removed, so the abort remains'

# --- and a guarded pair is what replaces it --------------------------------

grep -qE '^\+[[:space:]]*if \(bus\) \{[[:space:]]*$' <<<"$code" || \
  fail 'no null check was added'
grep -qE '^\+[[:space:]]*T::InitializeFake\(\);[[:space:]]*$' <<<"$code" || \
  fail 'nothing falls back to a fake, so a null bus still aborts'

# --- the define must survive ------------------------------------------------

grep -qE '^-.*#if defined\(USE_REAL_DBUS_CLIENTS\)' <<<"$removed" && \
  fail 'the USE_REAL_DBUS_CLIENTS branch was removed rather than fixed'
grep -qE '^-.*#else' <<<"$removed" && \
  fail 'the non-flag branch was disturbed; this patch should only touch the flag branch'

# --- this patch is a guard, not the fix -------------------------------------

# The fix is that use_real_dbus_clients is gone from the build configuration,
# which chromium-network-config-test.sh enforces. With the flag off the branch
# this patch edits is not compiled at all, so nothing here is load bearing
# today. It stays because the abort it prevents is silent and total: a browser
# that dies in PostEarlyInitialization draws nothing, and the greeter that
# replaces it looks like an ordinary logout. Anyone who turns the flag back on
# should get fakes, not a dead desktop.
sed -e 's/#.*$//' "$ROOT/chromiumos-ash/PKGBUILD" | grep -Fq 'use_real_dbus_clients' && \
  fail 'the PKGBUILD sets use_real_dbus_clients again; that is the bug this patch only cushions'

true

# --- hermes: the same guard, its own copy -----------------------------------

# The early return has to stop being conditional on the define. Leaving the
# #if in place and only adding a branch inside it would compile out again.
grep -qE '^-[[:space:]]*#if !defined\(USE_REAL_DBUS_CLIENTS\)' "$PATCH" || \
  fail 'the hermes guard is still conditional on the define, so it still compiles out'

grep -qE '^[+ ][[:space:]]*return InitializeFakes\(\);' <<<"$result" || \
  fail 'hermes no longer falls back to fakes on a null bus'

grep -qE '^\+[[:space:]]*if \(!system_bus\) \{' <<<"$code" || \
  fail 'the hermes null check is gone'

grep -qE '^[+ ][[:space:]]*DCHECK\(system_bus\);' <<<"$result" || \
  fail 'the hermes DCHECK was deleted rather than made unreachable on a null bus'

# --- the resulting file must be balanced ------------------------------------

python3 - "$PATCH" <<'PY' || exit 1
import re, sys
raw = open(sys.argv[1]).read().splitlines()
# Only the header hunk is reasoned about below; hermes has its own checks.
lines, keep = [], False
for l in raw:
    if l.startswith('diff --git '):
        keep = 'initialize_dbus_client.h' in l
    if keep:
        lines.append(l)

def die(msg):
    print(f'dbus client fake fallback test: {msg}', file=sys.stderr)
    raise SystemExit(1)

# Reconstruct the post-patch file from the hunk: context plus additions.
after = [l[1:] for l in lines
         if (l.startswith(' ') or (l.startswith('+') and not l.startswith('+++')))]
body = '\n'.join(after)

# The hunk stops at the #else comment, so only the flag branch is in view.
# Exactly one of each belongs there: the real client and its fallback.
if body.count('T::InitializeFake();') != 1:
    die(f'expected 1 InitializeFake in the flag branch, found {body.count("T::InitializeFake();")}')
if body.count('T::Initialize(bus);') != 1:
    die(f'expected 1 real Initialize in the flag branch, found {body.count("T::Initialize(bus);")}')

# The guard has to sit inside the flag branch, not before it.
i_if = body.find('#if defined(USE_REAL_DBUS_CLIENTS)')
i_else = body.find('#else')
i_guard = body.find('if (bus) {')
if not (0 <= i_if < i_guard < i_else):
    die('the null check is not inside the USE_REAL_DBUS_CLIENTS branch')

print('dbus client fake fallback test: PASS '
      '(guard only; the flag is out of the build config)')
PY
