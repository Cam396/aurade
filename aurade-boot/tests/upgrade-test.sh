#!/usr/bin/env bash
# An encrypted install from before the unlock screen gets it on upgrade, and
# nothing else is touched.
#
# Runs aurade-boot-upgrade against made up roots, with a mkinitcpio and an
# lsinitcpio that write down what they were asked, and checks the files it
# leaves behind for each kind of install.
set -Eeuo pipefail

HERE=$(cd -- "$(dirname -- "$0")" && pwd -P)
SCRIPT=${1:-$HERE/../aurade-boot-upgrade}
TMP=$(mktemp -d)
trap 'rm -rf -- "$TMP"' EXIT

fail() { printf 'upgrade test: %s\n' "$*" >&2; exit 1; }

OLD='HOOKS=(base systemd autodetect microcode modconf kms keyboard sd-vconsole block sd-encrypt filesystems fsck)'
NEW='HOOKS=(base systemd autodetect microcode modconf kms keyboard sd-vconsole plymouth aurade-boot block sd-encrypt filesystems fsck)'
PLAIN='HOOKS=(base udev autodetect microcode modconf kms keyboard keymap consolefont block filesystems fsck)'
OPTIONS='options rd.luks.name=1234=root root=/dev/mapper/root rootflags=subvol=@ quiet'

cat >"$TMP/mkinitcpio" <<'FAKE'
#!/usr/bin/env bash
printf '%s legacy=%s\n' "$*" "${AURADE_BOOT_LEGACY_INPUT:-0}" >>"$FAKE_LOG"
if [[ $* == *-g* ]]; then
  [[ -z ${FAKE_TRIAL_FAIL:-} ]] || exit 1
  # As plymouth's hook does: the theme in the image is the one plymouthd.conf
  # names when the image is built.
  out=${*: -1}
  grep -qx 'Theme=aurade-boot' "$AURADE_BOOT_ROOT/etc/plymouth/plymouthd.conf" 2>/dev/null &&
    echo theme >"$out" || : >"$out"
  exit 0
fi
[[ -z ${FAKE_REAL_FAIL:-} || -e $FAKE_LOG.failed ]] || { : >"$FAKE_LOG.failed"; exit 1; }
exit 0
FAKE
cat >"$TMP/lsinitcpio" <<'FAKE'
#!/usr/bin/env bash
printf '%s\n' usr/bin/plymouthd usr/lib/systemd/systemd-cryptsetup
if [[ -z ${FAKE_NO_THEME:-} ]] && grep -qx theme "$1"; then
  echo usr/share/plymouth/themes/aurade-boot/aurade-boot.script
fi
FAKE
chmod 755 "$TMP/mkinitcpio" "$TMP/lsinitcpio"

n=0
machine() {
  local hooks=$1 options=$2 vconsole=${3:-'KEYMAP=us'}
  n=$((n + 1)); R=$TMP/root$n
  install -d "$R/etc" "$R/boot/loader/entries"
  printf '# mkinitcpio\nMODULES=()\n%s\n' "$hooks" >"$R/etc/mkinitcpio.conf"
  printf 'title AuraDE\nlinux /vmlinuz-linux\ninitrd /initramfs-linux.img\n%s\n' "$options" \
    >"$R/boot/loader/entries/aurade.conf"
  printf '%s\n' "$vconsole" >"$R/etc/vconsole.conf"
  : >"$R/boot/vmlinuz-linux"
  rm -f "$TMP/log" "$TMP/log.failed"
}
upgrade() {
  AURADE_BOOT_ROOT=$R AURADE_BOOT_MKINITCPIO=$TMP/mkinitcpio AURADE_BOOT_LSINITCPIO=$TMP/lsinitcpio \
    FAKE_LOG=$TMP/log bash "$SCRIPT" >"$TMP/out" 2>&1 || fail "the script failed: $(cat "$TMP/out")"
}
hooks_are() { [[ $(grep '^HOOKS=' "$R/etc/mkinitcpio.conf") == "$1" ]] || fail "$2: HOOKS is $(grep '^HOOKS=' "$R/etc/mkinitcpio.conf")"; }
options_are() { [[ $(grep '^options' "$R/boot/loader/entries/aurade.conf") == "$1" ]] || fail "$2: options are $(grep '^options' "$R/boot/loader/entries/aurade.conf")"; }
untouched() {
  hooks_are "$1" "$3"; options_are "$2" "$3"
  [[ ! -e $R/boot/loader/entries/aurade-text-unlock.conf ]] || fail "$3: a text unlock entry was written"
  [[ ! -e $R/etc/plymouth/plymouthd.conf ]] || fail "$3: plymouthd.conf was written"
  ! grep -q -- ' -P' "$TMP/log" 2>/dev/null || fail "$3: the initramfs was rebuilt"
}

# A 1.1 encrypted install: switched over, with a way back.
machine "$OLD" "$OPTIONS"
upgrade
hooks_are "$NEW" 'old encrypted install'
options_are "$OPTIONS splash rd.luks.options=tries=0" 'old encrypted install'
T=$R/boot/loader/entries/aurade-text-unlock.conf
grep -qx 'title AuraDE, text disk unlock' "$T" || fail 'the text unlock entry has the wrong title'
grep -qx "$OPTIONS plymouth.enable=0" "$T" || fail 'the text unlock entry does not turn plymouth off'
grep -qx 'Theme=aurade-boot' "$R/etc/plymouth/plymouthd.conf" || fail 'plymouth is not set to the AuraDE theme'
grep -qx "$OLD" "$R/etc/mkinitcpio.conf.before-aurade-boot" || fail 'no copy of the old mkinitcpio.conf'
grep -q -- '-g ' "$TMP/log" || fail 'no trial build before the change'
grep -q -- '^-P legacy=0' "$TMP/log" || fail 'the initramfs was not rebuilt'
grep -q 'now unlocked on the AuraDE unlock screen' "$TMP/out" || fail 'the change was not reported'

# Run again: nothing more changes.
cp "$R/boot/loader/entries/aurade.conf" "$TMP/entry-once"; rm -f "$TMP/log"
upgrade
cmp -s "$TMP/entry-once" "$R/boot/loader/entries/aurade.conf" || fail 'a second run changed the boot entry'
[[ ! -e $TMP/log ]] || fail 'a second run ran mkinitcpio'

# A German keyboard with no XKB layout reads keys through the console.
machine "$OLD" "$OPTIONS" 'KEYMAP=de-latin1'
upgrade
options_are "$OPTIONS splash plymouth.use-legacy-input rd.luks.options=tries=0" 'German console keymap'
grep -q -- '^-P legacy=1' "$TMP/log" || fail 'the German rebuild did not name the layout'
machine "$OLD" "$OPTIONS" $'KEYMAP=de-latin1\nXKBLAYOUT=de'
upgrade
options_are "$OPTIONS splash rd.luks.options=tries=0" 'German keymap with an XKB layout'

# Unlock options of its own are kept, not given a second set.
machine "$OLD" "$OPTIONS rd.luks.options=discard"
upgrade
options_are "$OPTIONS rd.luks.options=discard splash" 'own unlock options'

# Not encrypted, edited by hand, or an unknown boot entry: left alone.
machine "$PLAIN" 'options root=UUID=1234 rw quiet'
upgrade
untouched "$PLAIN" 'options root=UUID=1234 rw quiet' 'plain install'
[[ ! -s $TMP/out ]] || fail "a plain install was told something: $(cat "$TMP/out")"
CUSTOM='HOOKS=(base systemd autodetect modconf kms keyboard sd-vconsole block sd-encrypt lvm2 filesystems fsck)'
machine "$CUSTOM" "$OPTIONS"
upgrade
untouched "$CUSTOM" "$OPTIONS" 'hand edited hooks'
grep -q 'changed by hand' "$TMP/out" || fail 'hand edited hooks were not explained'
machine "$OLD" 'options root=/dev/sda2 quiet'
upgrade
untouched "$OLD" 'options root=/dev/sda2 quiet' 'unknown boot entry'

# Arch's own plymouthd.conf is kept, and comes back if the trial fails.
machine "$OLD" "$OPTIONS"
install -d "$R/etc/plymouth"; printf '[Daemon]\n#Theme=bgrt\n' >"$R/etc/plymouth/plymouthd.conf"
FAKE_TRIAL_FAIL=1 upgrade
grep -qx '#Theme=bgrt' "$R/etc/plymouth/plymouthd.conf" || fail 'a failed trial did not put plymouthd.conf back'
upgrade
grep -qx 'Theme=aurade-boot' "$R/etc/plymouth/plymouthd.conf" || fail 'plymouthd.conf was not set'
grep -qx '#Theme=bgrt' "$R/etc/plymouth/plymouthd.conf.before-aurade-boot" || fail 'no copy of the old plymouthd.conf'

# Failures: nothing changes, or everything is put back.
machine "$OLD" "$OPTIONS"
FAKE_TRIAL_FAIL=1 upgrade
untouched "$OLD" "$OPTIONS" 'failed trial build'
machine "$OLD" "$OPTIONS"
FAKE_NO_THEME=1 upgrade
untouched "$OLD" "$OPTIONS" 'trial image without the theme'
machine "$OLD" "$OPTIONS"
FAKE_REAL_FAIL=1 upgrade
hooks_are "$OLD" 'failed real build'
options_are "$OPTIONS" 'failed real build'
[[ ! -e $R/boot/loader/entries/aurade-text-unlock.conf ]] || fail 'failed real build: the text entry stayed'
[[ ! -e $R/etc/plymouth/plymouthd.conf ]] || fail 'failed real build: plymouthd.conf stayed'
[[ $(grep -c -- '^-P' "$TMP/log") == 2 ]] || fail 'failed real build: the old initramfs was not rebuilt'

echo "upgrade test: PASS"
