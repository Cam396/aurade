#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

install -d "$TMP/bin" "$TMP/root/boot/loader/entries" "$TMP/root/.snapshots"
install -d "$TMP/root/boot/aurade-rollback/factory"
printf '%s\n' baseline >"$TMP/root/upgrade-state"
printf '%s\n' factory-kernel >"$TMP/root/boot/aurade-rollback/factory/vmlinuz-linux"
printf '%s\n' kernel >"$TMP/root/boot/vmlinuz-linux"
printf '%s\n' microcode >"$TMP/root/boot/intel-ucode.img"
printf '%s\n' initramfs >"$TMP/root/boot/initramfs-linux.img"
cat >"$TMP/root/boot/loader/entries/aurade.conf" <<'EOF'
title AuraDE
linux /vmlinuz-linux
initrd /intel-ucode.img
initrd /initramfs-linux.img
options root=UUID=test rw rootflags=subvol=@ quiet
EOF
cp "$TMP/root/boot/loader/entries/aurade.conf" "$TMP/normal-entry"

cat >"$TMP/bin/btrfs" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ $1 == subvolume && $2 == snapshot && $3 == -r ]]; then
  mkdir -p "$5"
  # The fixture models the one piece of state that matters to this test: a
  # pre-update marker is captured in the read-only snapshot. It deliberately
  # does not pretend to clone a real Btrfs tree.
  if [[ -r "$4/upgrade-state" ]]; then
    cp -- "$4/upgrade-state" "$5/upgrade-state"
  fi
elif [[ $1 == subvolume && $2 == delete && $3 == -- ]]; then
  rm -rf -- "$4"
else
  exit 2
fi
EOF
chmod 0755 "$TMP/bin/btrfs"

if AURADE_ROLLBACK_RETENTION=0 \
  "$ROOT/installer/bin/aurade-recovery" help >"$TMP/retention.out" 2>&1; then
  echo 'invalid rollback retention unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'AURADE_ROLLBACK_RETENTION must be a positive integer' "$TMP/retention.out"

snapshot=$(PATH="$TMP/bin:$PATH" \
  "$ROOT/installer/bin/aurade-recovery" snapshot --root "$TMP/root" \
    --label pre-update --set-rollback)

[[ $snapshot == "$TMP/root/.snapshots/"manual-*-pre-update/snapshot ]]
grep -Fxq 'title AuraDE rollback (pre-update)' \
  "$TMP/root/boot/loader/entries/aurade-rollback.conf"
grep -Eq '^options root=UUID=test rw rootflags=subvol=@snapshots/manual-[0-9]{8}T[0-9]{6}Z-pre-update/snapshot$' \
  "$TMP/root/boot/loader/entries/aurade-rollback.conf"
! grep -Eq '^options .* quiet([[:space:]]|$)' \
  "$TMP/root/boot/loader/entries/aurade-rollback.conf"
grep -Eq '^linux /aurade-rollback/manual-[0-9]{8}T[0-9]{6}Z-pre-update/vmlinuz-linux$' \
  "$TMP/root/boot/loader/entries/aurade-rollback.conf"
grep -Eq '^initrd /aurade-rollback/manual-[0-9]{8}T[0-9]{6}Z-pre-update/initramfs-linux.img$' \
  "$TMP/root/boot/loader/entries/aurade-rollback.conf"
[[ $(<"$snapshot/upgrade-state") == baseline ]]

# Exercise the upgrade -> rollback sequence without claiming that a fixture
# can perform a real Btrfs rollback. The simulated upgrade mutates the live
# marker; boot-rollback must select the generated rollback entry, whose
# snapshot still contains the pre-update marker, while factory artifacts stay
# untouched.
printf '%s\n' upgraded >"$TMP/root/upgrade-state"
cat >"$TMP/bin/bootctl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >"${AURADE_TEST_BOOTCTL_LOG:?}"
EOF
chmod 0755 "$TMP/bin/bootctl"
AURADE_TEST_BOOTCTL_LOG="$TMP/bootctl.log" PATH="$TMP/bin:$PATH" \
  "$ROOT/installer/bin/aurade-recovery" boot-rollback --root "$TMP/root"
grep -Fq 'set-oneshot aurade-rollback.conf' "$TMP/bootctl.log"
[[ $(<"$TMP/root/upgrade-state") == upgraded ]]
[[ $(<"$snapshot/upgrade-state") == baseline ]]
[[ -e "$TMP/root/boot/aurade-rollback/factory/vmlinuz-linux" ]]

cmp -s "$TMP/root/boot/vmlinuz-linux" \
  "$TMP/root/boot/aurade-rollback/"manual-*-pre-update/vmlinuz-linux
cmp -s "$TMP/root/boot/aurade-rollback/factory/vmlinuz-linux" \
  <(printf '%s\n' factory-kernel)

# Retention prunes only old manual Btrfs snapshots and never touches the
# factory rollback artifacts. The fixture btrfs command models subvolume
# deletion without requiring a real block device.
mkdir -p \
  "$TMP/root/.snapshots/manual-20000101T000000Z-old-a/snapshot" \
  "$TMP/root/.snapshots/manual-20000102T000000Z-old-b/snapshot"
cp "$TMP/normal-entry" "$TMP/root/boot/loader/entries/aurade.conf"
PATH="$TMP/bin:$PATH" AURADE_ROLLBACK_RETENTION=2 \
  "$ROOT/installer/bin/aurade-recovery" snapshot --root "$TMP/root" \
    --label retained >/dev/null
manual_count=$(find "$TMP/root/.snapshots" -mindepth 2 -maxdepth 2 \
  -type d -name snapshot -path "$TMP/root/.snapshots/manual-*/snapshot" | wc -l)
[[ $manual_count -eq 2 ]] || {
  echo "retention kept $manual_count manual snapshots (expected 2)" >&2
  exit 1
}
[[ ! -e "$TMP/root/.snapshots/manual-20000101T000000Z-old-a" ]]
[[ ! -e "$TMP/root/.snapshots/manual-20000102T000000Z-old-b" ]]
[[ -e "$TMP/root/boot/aurade-rollback/factory/vmlinuz-linux" ]]

# A traversal-like boot artifact must be rejected before snapshot creation.
cat >"$TMP/root/boot/loader/entries/aurade.conf" <<'EOF'
title AuraDE
linux /../escape-kernel
options root=UUID=test rw rootflags=subvol=@ quiet
EOF
if PATH="$TMP/bin:$PATH" \
  "$ROOT/installer/bin/aurade-recovery" snapshot --root "$TMP/root" \
    --label malformed --set-rollback >"$TMP/malformed.out" 2>&1; then
  echo 'malformed boot artifact unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'unsafe boot artifact path' "$TMP/malformed.out"
if find "$TMP/root/.snapshots" -mindepth 1 -maxdepth 1 -name '*malformed*' -print -quit | grep -q .; then
  echo 'malformed path created a snapshot' >&2
  exit 1
fi

# Low ESP space must be rejected before the Btrfs snapshot or boot-entry edit.
cp "$TMP/normal-entry" "$TMP/root/boot/loader/entries/aurade.conf"
install -d "$TMP/low-space-bin"
cat >"$TMP/low-space-bin/df" <<'EOF'
#!/usr/bin/env bash
if [[ $1 == -B1 && $2 == --output=avail ]]; then
  printf '%s\n%s\n' Avail 0
else
  exec /usr/bin/df "$@"
fi
EOF
chmod 0755 "$TMP/low-space-bin/df"
if PATH="$TMP/low-space-bin:$TMP/bin:$PATH" \
  "$ROOT/installer/bin/aurade-recovery" snapshot --root "$TMP/root" \
    --label low-space --set-rollback >"$TMP/low-space.out" 2>&1; then
  echo 'low ESP space unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'not enough ESP space for rollback artifacts' "$TMP/low-space.out"
if find "$TMP/root/.snapshots" -mindepth 1 -maxdepth 1 -name '*low-space*' -print -quit | grep -q .; then
  echo 'low ESP space created a snapshot' >&2
  exit 1
fi

# A failure after Btrfs snapshot creation must clean only the newly-created
# subvolume and partial rollback directory. The fixture's install wrapper
# injects failure while copying a boot artifact; the real btrfs deletion path
# is still exercised through the disposable fake command above.
install -d "$TMP/failing-install-bin"
cat >"$TMP/failing-install-bin/install" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
joined=" $* "
if [[ $joined == *'/boot/aurade-rollback/manual-'* && $joined != *' -d '* ]]; then
  exit 42
fi
exec /usr/bin/install "$@"
EOF
chmod 0755 "$TMP/failing-install-bin/install"
cp "$TMP/normal-entry" "$TMP/root/boot/loader/entries/aurade.conf"
if PATH="$TMP/failing-install-bin:$TMP/bin:$PATH" \
  "$ROOT/installer/bin/aurade-recovery" snapshot --root "$TMP/root" \
    --label injected --set-rollback >"$TMP/injected.out" 2>&1; then
  echo 'post-snapshot failure fixture unexpectedly passed' >&2
  exit 1
fi
if grep -Fq 'failed to remove partial snapshot' "$TMP/injected.out"; then
  echo 'post-snapshot failure left an orphan snapshot' >&2
  exit 1
fi
if find "$TMP/root/.snapshots" -mindepth 1 -maxdepth 1 -name '*injected*' -print -quit | grep -q .; then
  echo 'post-snapshot failure left a snapshot directory' >&2
  exit 1
fi
if find "$TMP/root/boot/aurade-rollback" -mindepth 1 -maxdepth 1 -name '*injected*' -print -quit | grep -q .; then
  echo 'post-snapshot failure left rollback artifacts' >&2
  exit 1
fi

# A failure while atomically installing the generated boot entry must also
# remove its temporary file. The pre-existing rollback entry remains intact;
# cleanup is limited to the newly-created snapshot, artifacts, and temp file.
install -d "$TMP/failing-mv-bin"
cat >"$TMP/failing-mv-bin/mv" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ ${1:-} == -f && ${2:-} == *.tmp.* ]]; then
  exit 43
fi
exec /usr/bin/mv "$@"
EOF
chmod 0755 "$TMP/failing-mv-bin/mv"
cp "$TMP/root/boot/loader/entries/aurade-rollback.conf" \
  "$TMP/rollback-entry-before-mv-failure"
cp "$TMP/normal-entry" "$TMP/root/boot/loader/entries/aurade.conf"
if PATH="$TMP/failing-mv-bin:$TMP/bin:$PATH" \
  "$ROOT/installer/bin/aurade-recovery" snapshot --root "$TMP/root" \
    --label mv-failure --set-rollback >"$TMP/mv-failure.out" 2>&1; then
  echo 'rollback-entry move failure fixture unexpectedly passed' >&2
  exit 1
fi
if find "$TMP/root/boot/loader/entries" -maxdepth 1 \
  -name 'aurade-rollback.conf.tmp.*' -print -quit | grep -q .; then
  echo 'rollback-entry move failure left a temporary entry' >&2
  exit 1
fi
cmp -s "$TMP/rollback-entry-before-mv-failure" \
  "$TMP/root/boot/loader/entries/aurade-rollback.conf"
if find "$TMP/root/.snapshots" -mindepth 1 -maxdepth 1 \
  -name '*mv-failure*' -print -quit | grep -q .; then
  echo 'rollback-entry move failure left a snapshot directory' >&2
  exit 1
fi
if find "$TMP/root/boot/aurade-rollback" -mindepth 1 -maxdepth 1 \
  -name '*mv-failure*' -print -quit | grep -q .; then
  echo 'rollback-entry move failure left rollback artifacts' >&2
  exit 1
fi

echo 'recovery rollback test: PASS'
