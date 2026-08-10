#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

install -d "$TMP/bin" "$TMP/root/boot/loader/entries" "$TMP/root/.snapshots"
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

cat >"$TMP/bin/btrfs" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ $1 == subvolume && $2 == snapshot && $3 == -r ]]
mkdir -p "$5"
EOF
chmod 0755 "$TMP/bin/btrfs"

snapshot=$(PATH="$TMP/bin:$PATH" \
  "$ROOT/installer/bin/aurade-recovery" snapshot --root "$TMP/root" \
    --label pre-update --set-rollback)

[[ $snapshot == "$TMP/root/.snapshots/"manual-*-pre-update/snapshot ]]
grep -Fxq 'title AuraDE rollback (pre-update)' \
  "$TMP/root/boot/loader/entries/aurade-rollback.conf"
grep -Eq '^options root=UUID=test rw rootflags=subvol=@snapshots/manual-[0-9]{8}T[0-9]{6}Z-pre-update/snapshot quiet$' \
  "$TMP/root/boot/loader/entries/aurade-rollback.conf"
grep -Eq '^linux /aurade-rollback/manual-[0-9]{8}T[0-9]{6}Z-pre-update/vmlinuz-linux$' \
  "$TMP/root/boot/loader/entries/aurade-rollback.conf"
grep -Eq '^initrd /aurade-rollback/manual-[0-9]{8}T[0-9]{6}Z-pre-update/initramfs-linux.img$' \
  "$TMP/root/boot/loader/entries/aurade-rollback.conf"
cmp -s "$TMP/root/boot/vmlinuz-linux" \
  "$TMP/root/boot/aurade-rollback/"manual-*-pre-update/vmlinuz-linux

echo 'recovery rollback test: PASS'
