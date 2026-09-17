#!/usr/bin/env bash
# Test the power actions and polkit rule used by aurade-system-helper.
# loginctl does not provide these verbs; systemctl handles the requests.
#
# Three: the status was read after the `fi` rather than in the `else`. After an
# `if` whose condition fails and which has no else, `$?` is the status of the
# `if`, which is 0, so every failure was reported as "failed (0)".
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
HELPER="$ROOT/aurade-system-helper/aurade-system-helper"
RULES="$ROOT/aurade-system-helper/49-aurade-power.rules"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fail() { echo "system helper power test: $*" >&2; exit 1; }

# Build a stub PATH. Each stub records how it was called, prints something
# recognisable on stderr, and exits with the code named by its own .rc file.
#
# loginctl is still stubbed even though the helper must never call it. That is
# the point: without a stub, a helper that reached for loginctl would find the
# real one, and on a machine without it the call would vanish into `command -v`
# instead of failing the test.
stub_dir="$TMP/bin"
mkdir -p "$stub_dir"
for name in loginctl systemctl; do
  cat >"$stub_dir/$name" <<EOF
#!/bin/bash
printf '%s\n' "\$*" >>"$TMP/$name.calls"
echo "$name said no" >&2
exit \$(cat "$TMP/$name.rc")
EOF
  chmod 0755 "$stub_dir/$name"
done

reset_stubs() {
  : >"$TMP/loginctl.calls"
  : >"$TMP/systemctl.calls"
  printf '%s\n' "${1:-0}" >"$TMP/loginctl.rc"
  printf '%s\n' "${2:-0}" >"$TMP/systemctl.rc"
}

run_helper() {
  PATH="$stub_dir:$PATH" "$HELPER" "$@" >"$TMP/out" 2>&1
}

# 1. systemd answers, and that is the end of it.
reset_stubs 0 0
run_helper reboot || fail 'reboot failed when systemctl succeeded'
grep -Fq 'reboot' "$TMP/systemctl.calls" || fail 'systemctl was never called'

# 2. loginctl is never asked, for any power action. It has no poweroff, reboot
# or suspend verb, so asking it only ever produced "Unknown command verb" in
# Ash's log ahead of the call that actually worked.
for action in reboot poweroff suspend; do
  reset_stubs 0 0
  run_helper "$action" || fail "$action was rejected"
  [[ ! -s "$TMP/loginctl.calls" ]] || \
    fail "$action was sent to loginctl, which has no such verb and never has"
  grep -Fq "$action" "$TMP/systemctl.calls" || fail "$action never reached systemctl"
done

# 3. systemd refuses. The helper must fail loudly rather than exit clean,
# because a silent success is what left the desktop on its shutdown animation.
reset_stubs 0 1
if run_helper reboot; then
  fail 'helper reported success when systemctl refused'
fi
grep -Fq 'could not reboot' "$TMP/out" || fail 'no explanation when the call failed'
grep -Fq 'systemctl said no' "$TMP/out" || \
  fail "the refusal's own words are not reported, so the log names no cause"

# 4. And the status reported is the real one. Read after the `fi` it is the
# status of the `if`, which is 0, and every failure reads "failed (0)": a
# number that is always the same is not information.
reset_stubs 0 7
if run_helper reboot; then fail 'helper reported success on exit 7'; fi
grep -Fq 'failed (7)' "$TMP/out" || \
  fail 'the reported status is not the one systemctl exited with'
if grep -Fq 'failed (0)' "$TMP/out"; then
  fail 'a failure is reported as status 0, which is the bug this checks for'
fi

# 5. Never wait for an authentication agent that no session provides. Without
# this the call hangs instead of failing, and a hang cannot be diagnosed.
reset_stubs 0 0
run_helper poweroff || fail 'poweroff failed'
grep -Fq -- '--no-ask-password' "$TMP/systemctl.calls" || \
  fail 'systemctl was called without --no-ask-password'

# 6. Only the actions the menu offers, and nothing else.
reset_stubs 0 0
if run_helper hibernate; then fail 'hibernate was accepted'; fi
if run_helper 'reboot; rm -rf /'; then fail 'a compound argument was accepted'; fi
[[ ! -s "$TMP/systemctl.calls" ]] || fail 'a rejected action still reached systemctl'

# 7. The polkit rule has to cover the multiple-sessions variants. greetd leaves
# its greeter session registered, so logind sees two sessions and checks
# reboot-multiple-sessions, whose default is auth_admin_keep. Covering only the
# single-session actions looks correct and fixes nothing.
[[ -r $RULES ]] || fail 'the polkit rule is missing'
for action in \
  org.freedesktop.login1.reboot \
  org.freedesktop.login1.reboot-multiple-sessions \
  org.freedesktop.login1.power-off \
  org.freedesktop.login1.power-off-multiple-sessions \
  org.freedesktop.login1.suspend \
  org.freedesktop.login1.suspend-multiple-sessions; do
  grep -Fq "\"$action\"" "$RULES" || fail "the polkit rule does not cover $action"
done

# 8. The rule must not hand the machine to a remote session, and must not
# broaden past the owner's group. Read the code and not the file: the comment
# above the rule names both guards, so grepping the whole file passes happily
# after someone deletes them. Everything from polkit.addRule onward is code.
sed -n '/^polkit.addRule/,$p' "$RULES" >"$TMP/rule-body"
[[ -s "$TMP/rule-body" ]] || fail 'the polkit rule has no addRule body'
grep -Fq 'subject.local' "$TMP/rule-body" || fail 'the polkit rule does not require a local session'
grep -Fq 'isInGroup("wheel")' "$TMP/rule-body" || fail 'the polkit rule does not scope to wheel'
if grep -Fq 'org.freedesktop.login1.hibernate' "$RULES"; then
  fail 'the rule allows hibernate, which this system does not support'
fi

# 9. Packaging: the rule is worthless if it is not installed.
grep -Fq '49-aurade-power.rules' "$ROOT/aurade-system-helper/PKGBUILD" || \
  fail 'the polkit rule is not in the PKGBUILD source list'
grep -Fq 'polkit-1/rules.d/49-aurade-power.rules' "$ROOT/aurade-system-helper/PKGBUILD" || \
  fail 'the polkit rule is never installed by package()'
sources=$(grep -c '^	source = ' "$ROOT/aurade-system-helper/.SRCINFO")
sums=$(grep -c '^	sha256sums = ' "$ROOT/aurade-system-helper/.SRCINFO")
[[ $sources -eq $sums ]] || \
  fail ".SRCINFO lists $sources sources against $sums checksums"

# 10. install-package still refuses to run unprivileged. The power path above
# deliberately does not require root, so prove that did not leak across.
reset_stubs 0 0
if [[ $(id -u) -ne 0 ]]; then
  if run_helper install-package /tmp/x.pkg.tar.zst; then
    fail 'install-package ran without root'
  fi
  grep -Fq 'pkexec' "$TMP/out" || fail 'install-package did not explain it needs pkexec'
fi

echo 'system helper power test: PASS'
