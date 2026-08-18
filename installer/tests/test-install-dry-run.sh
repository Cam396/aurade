#!/usr/bin/env bash
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
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
install -d -m 0755 "$TMP/repo" "$TMP/package"

make_package() {
  local name=$1 filename digest
  printf 'pkgname = %s\npkgver = 1.0-1\narch = any\n' "$name" \
    >"$TMP/package/.PKGINFO"
  filename=${name}-1.0-1-any.pkg.tar.zst
  bsdtar -cf "$TMP/repo/$filename" -C "$TMP/package" .PKGINFO
  digest=$(sha256sum "$TMP/repo/$filename" | awk '{print $1}')
  printf '%s %s %s 1.0-1 any\n' "$digest" "$filename" "$name" \
    >>"$TMP/packages.lock.unsorted"
}

make_package aurade
make_package chromiumos-ash
{
  printf '%s\n' '# sha256 filename pkgname pkgver arch'
  LC_ALL=C sort -k3,3 "$TMP/packages.lock.unsorted"
} >"$TMP/packages.lock"
printf '%s\n' "\$6\$audit\$not-a-plaintext-password" >"$TMP/password.hash"
printf '%s\n' 'audit-passphrase' >"$TMP/luks.passphrase"
chmod 0600 "$TMP/password.hash" "$TMP/luks.passphrase"

common=(
  --target /dev/aurade-test-disk
  --username audit
  --password-hash-file "$TMP/password.hash"
  --arch-snapshot 2026/07/12
  --bundle-dir "$TMP/repo"
  --package-lock "$TMP/packages.lock"
  --allow-unsigned
  --dry-run
)

if ! "$ROOT/installer/bin/aurade-install" "${common[@]}" \
    >"$TMP/plain.out" 2>&1; then
  cat "$TMP/plain.out" >&2
  exit 1
fi
grep -Fq -- '--typecode=2:8300' "$TMP/plain.out"
grep -Fq -- 'aurade-powerd.service aurade-host-bridge.service aurade-greetd.service' \
  "$TMP/plain.out"
grep -Fq -- 'seatd.service aurade-powerd.service' "$TMP/plain.out"
grep -Fq -- 'useradd -m -G wheel\,audio\,video\,input\,storage\,seat' "$TMP/plain.out"
grep -Fq -- 'chpasswd --encrypted' "$ROOT/installer/bin/aurade-install"
refute grep -Fq -- 'usermod --password "$(<"$PASSWORD_HASH_FILE")"' \
  "$ROOT/installer/bin/aurade-install"
grep -Fq -- '/boot/aurade-rollback/factory/vmlinuz-linux' "$TMP/plain.out"
grep -Fq -- 'intel-ucode' "$TMP/plain.out"
grep -Fq -- 'amd-ucode' "$TMP/plain.out"
grep -Fq -- 'sof-firmware' "$TMP/plain.out"
grep -Fq -- 'file:///var/cache/aurade/repo' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'pacstrap -M -G -C' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'GPGDir = ${ARCH_GPG_DIR}' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'LocalFileSigLevel = Required' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'pacman-key --gpgdir "$ARCH_GPG_DIR" --populate archlinux' "$ROOT/installer/bin/aurade-install"
grep -Fq -- '/usr/share/pacman/keyrings/archlinux.gpg' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'gpgv --keyring "$ARCH_GPG_DIR/pubring.gpg"' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'invalid Arch package signature' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'cause=keyring_error' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'cause=capacity_error' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'cause=network_error' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'aurade_journal_fail "$_J_ACTIVE_STAGE" "$status" cancelled' \
  "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'trap '\''handle_cancel 130'\'' INT' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'journal_message=${message:0:256}' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'without touching the target disk' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'private keys excluded' "$TMP/plain.out"

# --- the mark this machine gets and no other machine has --------------------
#
# Written into the installed system and announced nowhere, which is the whole
# of the idea: it is found by somebody who went looking. The summary carries
# the short code beside it so a support conversation can name an install
# without anybody having to read a mosaic down a telephone.
grep -Fq '/etc/aurade-install/badge' "$TMP/plain.out" ||
  { echo 'the plan never writes a fingerprint into the installed system' >&2; exit 1; }
grep -Fq '/etc/aurade-install/summary' "$TMP/plain.out"
# The seed is derived from board identifiers and one network address, and none
# of them may survive into anything written down. The engine holds them in
# BADGE_SEED only long enough to hash, so what must never appear in a plan is
# the material itself.
refute grep -Eq 'product_uuid|board_serial|product_serial' "$TMP/plain.out"
# A keyring failure stops rather than retries. This used to be asserted by
# grepping for a phrase inside the error message, which pinned the wording of
# a sentence in place of the behaviour it described. The behaviour is that
# `pacman_keyring_failure` short circuits into a `die`, and the wording is
# free to improve.
grep -Fq -- 'pacman_keyring_failure' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'die_keyring_failure() {' "$ROOT/installer/bin/aurade-install"
awk '/^die_keyring_failure\(\) \{/,/^\}/' "$ROOT/installer/bin/aurade-install" |
  grep -Fq -- 'die ' ||
  { echo 'die_keyring_failure no longer dies' >&2; exit 1; }
# ...and the message it dies with still classifies as a keyring failure, which
# is what tests/test-die-cause.sh pins by name.
grep -Fq -- 'installer staging filesystem has ' "$TMP/plain.out"
grep -Fq -- 'Set AURADE_INSTALL_WORK_DIR to a directory on a disk' "$ROOT/installer/bin/aurade-install"
# The three Secure Boot states each get told to the user before the erase gate:
# on and trusted, on and untrusted, and unreadable. Matched on the state rather
# than on the sentence, because the sentences have been rewritten once already.
#
# These used to be asserted against `bin/aurade-installer`, a third front end
# that was packaged onto the image and reachable from nothing. Testing the
# engine's behaviour by grepping a front end's source is the wrong shape twice
# over: it passes when the front end is unreachable, and it passes when the
# engine changes underneath it. They now point at the two front ends that ship,
# and at the engine itself.
BRIDGE=$ROOT/installer/bin/aurade-installer-gui-bridge
TUI=$ROOT/installer/bin/aurade-installer-tui
grep -Fq -- 'Secure Boot' "$BRIDGE"
grep -Fq -- 'setup mode' "$BRIDGE"
grep -Fq -- 'Could not tell whether Secure Boot is on' "$BRIDGE"
grep -Fq -- 'Secure Boot state could not be read' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'without signing' "$ROOT/installer/bin/aurade-install"
grep -Fq -- '--secure-boot-auto-enroll yes' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'firmware setup mode' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'pre-enrolled signing certificate' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'sbsigntools' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'secure-boot-enroll' "$ROOT/installer/bin/aurade-install"
grep -Fq -- 'AURADE_SECURE_BOOT_KEY' "$ROOT/installer/bin/aurade-installer-tui"
# The rules themselves are exercised by test-prompt-validation.sh against
# fixture roots. Assert only that the front ends delegate to them instead of
# re-implementing the checks inline, where they cannot be tested.
#
# One shared manifest, one validator per question, and both front ends reaching
# them through `aurade_question_validate`. That is the property worth pinning:
# a front end that grew its own copy of a rule is a front end that will
# disagree with the engine about what a valid hostname is.
grep -Fq -- 'aurade_question_validate' "$TUI"
grep -Fq -- 'aurade_question_validate' "$BRIDGE"
grep -Fq -- 'loadkeys' "$TUI"
# The two things said before the disk question: AuraDE takes the whole disk,
# and there is no swap unless you add one.
acquire_line=$(grep -n -- '--disable-sandbox -Syy' "$TMP/plain.out" | head -1 | cut -d: -f1)
wipe_line=$(grep -n -- 'wipefs --all --force' "$TMP/plain.out" | head -1 | cut -d: -f1)
(( acquire_line < wipe_line ))
if grep -Fq -- 'cryptsetup luksFormat' "$TMP/plain.out"; then
  echo 'unencrypted plan unexpectedly formats LUKS' >&2
  exit 1
fi

if ! "$ROOT/installer/bin/aurade-install" "${common[@]}" --encrypt \
    --luks-passphrase-file "$TMP/luks.passphrase" >"$TMP/encrypted.out" 2>&1; then
  cat "$TMP/encrypted.out" >&2
  exit 1
fi
grep -Fq -- '--typecode=2:8309' "$TMP/encrypted.out"
grep -Fq -- 'cryptsetup luksFormat --type luks2 --batch-mode' "$TMP/encrypted.out"
grep -Fq -- '/boot/aurade-rollback/factory/initramfs-linux.img' "$TMP/encrypted.out"

# ---------------------------------------------------------------------------
# Storage shape
#
# The default is the only shape this product shipped before these options
# existed, and the first assertion here is that it did not move: no swap file,
# a Btrfs root, subvolumes, a factory snapshot and a rollback entry. Everything
# after it checks that choosing something else actually changes the plan, and -
# more importantly - that the consequences of choosing it are carried through
# rather than left as a half-configured system.
# ---------------------------------------------------------------------------

refute grep -Fq -- 'mkswap' "$TMP/plain.out"
refute grep -Fq -- 'mkswapfile' "$TMP/plain.out"
refute grep -Fq -- 'zram' "$TMP/plain.out"
grep -Fq -- 'mkfs.btrfs' "$TMP/plain.out"
grep -Fq -- 'btrfs subvolume create' "$TMP/plain.out"
grep -Fq -- 'boot options: root=UUID=<root-filesystem-uuid> rw rootflags=subvol=@ quiet' "$TMP/plain.out"

plan() {
  local name=$1
  shift
  if ! "$ROOT/installer/bin/aurade-install" "${common[@]}" "$@" \
      >"$TMP/$name.out" 2>&1; then
    echo "dry run failed: $name" >&2
    cat "$TMP/$name.out" >&2
    exit 1
  fi
}

# --- accessibility survives the reboot, or it is not accessibility ---------
#
# The whole point of collecting these in the installer is that they reach the
# installed system. A setting that is true for the ten minutes of an install
# and gone after the restart has moved the wall rather than removed it, so this
# checks the writes actually happen rather than that the flags parse.
plan a11y --screen-reader yes --braille yes --contrast high \
  --text-scale 125 --reduce-motion yes --cursor-size 32 --spacing roomy \
  --typeface atkinson
# The record, which is what the installed system reads back to confirm.
grep -Fq -- '/etc/aurade-install/accessibility' "$TMP/a11y.out" ||
  { echo 'the accessibility record is not written into the target' >&2; exit 1; }
# The two mechanisms that make the settings take effect.
grep -Fq -- '/etc/xdg/gtk-4.0/settings.ini' "$TMP/a11y.out" ||
  { echo 'the GTK defaults are not written into the target' >&2; exit 1; }
grep -Fq -- '/etc/dconf/db/local.d/00-aurade-accessibility' "$TMP/a11y.out" ||
  { echo 'the dconf defaults are not written into the target' >&2; exit 1; }
# And the daemons, which have to be enabled rather than started because the
# target is not running.
grep -Fq -- 'systemctl enable espeakup.service' "$TMP/a11y.out" ||
  { echo 'espeakup is not enabled on the installed system' >&2; exit 1; }
grep -Fq -- 'systemctl enable brltty.service' "$TMP/a11y.out" ||
  { echo 'brltty is not enabled on the installed system' >&2; exit 1; }
# Line spacing has no GTK setting and no dconf key, so it travels as the one
# thing it can: a stylesheet every GTK 4 application on the target reads.
grep -Fq -- '/etc/xdg/gtk-4.0/gtk.css' "$TMP/a11y.out" ||
  { echo 'line spacing is not written into the installed system' >&2; exit 1; }
# The face has to be installed on the target, not only named there. A font name
# written for a family that is not present does not error: it renders in the
# default face, and somebody who needed the other one cannot tell.
grep -Fq -- 'ttf-atkinson-hyperlegible' "$TMP/a11y.out" ||
  { echo 'the chosen typeface is not installed onto the target' >&2; exit 1; }
# The reader has to exist on the installed system, not only on the image.
grep -Fq -- 'espeakup' "$TMP/a11y.out" ||
  { echo 'espeakup is not installed onto the target' >&2; exit 1; }

# An install that asks for none of this is the install it was before. The
# default path must not gain files, services or packages.
plan a11y_default
! grep -Fq -- '/etc/dconf/db/local.d/00-aurade-accessibility' "$TMP/a11y_default.out" ||
  { echo 'a default install writes accessibility dconf defaults it was not asked for' >&2; exit 1; }
! grep -Fq -- 'systemctl enable espeakup.service' "$TMP/a11y_default.out" ||
  { echo 'a default install enables a screen reader nobody asked for' >&2; exit 1; }
! grep -Fq -- '/etc/xdg/gtk-4.0/gtk.css' "$TMP/a11y_default.out" ||
  { echo 'a default install restyles every GTK application on the target' >&2; exit 1; }

refuses() {
  local expected=$1
  shift
  if "$ROOT/installer/bin/aurade-install" "${common[@]}" "$@" \
      >"$TMP/refusal.out" 2>&1; then
    echo "expected a refusal for: $*" >&2
    exit 1
  fi
  grep -Fq -- "$expected" "$TMP/refusal.out" || {
    echo "wrong refusal for: $*" >&2
    cat "$TMP/refusal.out" >&2
    exit 1
  }
}

# A swap file on Btrfs must be made by mkswapfile, which is the call that turns
# copy-on-write and compression off. fallocate plus mkswap produces a file the
# kernel refuses to swap to, so the tool used here is the assertion.
plan swapfile --swap file --swap-size 4G
grep -Fq -- 'btrfs filesystem mkswapfile --size 4096m' "$TMP/swapfile.out"
grep -Fq -- '/swap/swapfile none swap defaults 0 0' "$TMP/swapfile.out"
refute grep -Fq -- 'resume_offset' "$TMP/swapfile.out"

plan hibernate --swap file --swap-size hibernate
grep -Fq -- 'resume=UUID=<root-filesystem-uuid> resume_offset=<swapfile-offset>' "$TMP/hibernate.out"
grep -Fq -- 'add the mkinitcpio resume hook' "$TMP/hibernate.out"

plan zram --swap zram
grep -Fq -- 'zram-generator.conf' "$TMP/zram.out"
refute grep -Fq -- 'mkswapfile' "$TMP/zram.out"

# ext4 has no subvolumes, so it has no factory snapshot; the rollback entry
# must be absent rather than present and broken.
plan ext4 --filesystem ext4
grep -Fq -- 'mkfs.ext4' "$TMP/ext4.out"
refute grep -Fq -- 'btrfs subvolume create' "$TMP/ext4.out"
refute grep -Fq -- 'aurade-rollback.conf' "$TMP/ext4.out"
refute grep -Fq -- 'rootflags=subvol=@' "$TMP/ext4.out"
grep -Fq -- 'boot options: root=UUID=<root-filesystem-uuid> rw quiet' "$TMP/ext4.out"
grep -Fq -- 'no factory snapshot and no rollback boot entry' "$TMP/ext4.out"

# xfs, on a machine that can make one. The build host frequently cannot, and
# that is the point of the second half: a plan for a shape whose mkfs is
# missing has to fail here, in the plan, rather than after the erase token has
# been typed. The image ships xfsprogs so that this shape is real.
install -d "$TMP/fsbin"
printf '#!/usr/bin/env bash\nexit 0\n' >"$TMP/fsbin/mkfs.xfs"
chmod +x "$TMP/fsbin/mkfs.xfs"
saved_path=$PATH
PATH="$TMP/fsbin:$saved_path"
plan xfs --filesystem xfs
grep -Fq -- 'mkfs.xfs' "$TMP/xfs.out"

# The same shape on an image without the tool. This is the failure a real
# image produced: every question answered, the disk confirmed by name, and
# then a stopped install. Whatever the host has, take it out of reach first,
# so this asserts on every build machine rather than only on the ones that
# happen to lack xfsprogs.
PATH=$saved_path
while xfs_tool=$(command -v mkfs.xfs 2>/dev/null); do
  xfs_dir=${xfs_tool%/*}
  PATH=$(printf '%s' "$PATH" | tr ':' '\n' | grep -Fxv "$xfs_dir" | paste -sd:)
  [[ -n $PATH ]] || break
done
command -v mkfs.xfs >/dev/null 2>&1 && { echo 'could not stage a host without mkfs.xfs' >&2; exit 1; }
refuses 'required command not found: mkfs.xfs' --filesystem xfs
PATH=$saved_path

# Installing alongside must not wipe, must not zap, and must not reformat the
# EFI system partition it was asked to share.
plan alongside --layout alongside
refute grep -Fq -- 'wipefs --all --force' "$TMP/alongside.out"
refute grep -Fq -- 'sgdisk --zap-all' "$TMP/alongside.out"
refute grep -Fq -- 'mkfs.fat' "$TMP/alongside.out"
grep -Fq -- 'sgdisk --largest-new=0' "$TMP/alongside.out"
grep -Fq -- 'keeping the existing EFI system partition' "$TMP/alongside.out"
grep -Fq -- 'INSTALL:/dev/aurade-test-disk' "$TMP/alongside.out"
grep -Fq -- 'ERASE:/dev/aurade-test-disk' "$TMP/plain.out"

refuses '--filesystem must be btrfs, ext4 or xfs' --filesystem zfs
refuses '--swap must be none, file or zram' --swap partition
refuses '--swap-size must be auto, hibernate, or a size like 8G' --swap-size huge
refuses '--layout must be wipe or alongside' --layout resize
refuses 'zram swap lives in memory' --swap zram --swap-size hibernate
refuses 'which xfs does not provide' --filesystem xfs --swap file --swap-size hibernate

echo 'installer dry-run test: PASS'
