#!/usr/bin/env bash
# Telling one disk from another, which is the problem the erase gate does not
# solve.
#
# The gate is the last line of defence and it is a good one, but by the time
# somebody is typing a confirmation token they have already decided which disk
# is theirs. They decided it on the previous screen, from a list where two
# 512G NVMe drives look exactly alike, and the only thing that would have
# changed their mind is being told that one of them has Windows on it.
#
# So: what is on it, which one the installer is running from, and removable
# ones last so a fumbled arrow key cannot land on the stick that is currently
# being read from.
set -Eeuo pipefail
trap 'case $- in *e*) printf "%s: line %s gave up: %s\n" "${0##*/}" "$LINENO" "$BASH_COMMAND" >&2 ;; esac' ERR
# shellcheck source=assert.sh
. "$(dirname -- "$0")/assert.sh"


ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TUI=$ROOT/installer/bin/aurade-installer-tui
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
failures=0
fail() { printf 'test-disk-identity: %s\n' "$*" >&2; failures=$(( failures + 1 )); }

export AURADE_TUI_COLUMNS=68 AURADE_TUI_COLOR=none AURADE_TUI_FRAME=ascii
export AURADE_INSTALLER_TUI_LIB=1
# shellcheck source=../bin/aurade-installer-tui
. "$TUI"
unset AURADE_INSTALLER_TUI_LIB

# --- removable last ---------------------------------------------------------
#
# The kernel reports disks in whatever order it found them, and on a machine
# that booted from a USB stick that order regularly puts the stick first. The
# cursor starts at the top of the list.
printf '%s\n' \
  '/dev/sdb|28.7G|SanDisk Ultra|usb|4C53' \
  '/dev/nvme0n1|476.9G|Samsung SSD 980 PRO|nvme|S6B2' \
  '/dev/sdc|14.4G|Kingston DataTraveler|usb|0088' \
  '/dev/sda|931.5G|WDC WD10EZEX|sata|WD-WCC6' >"$TMP/disks"
AURADE_DISK_TABLE=$TMP/disks

order=$(disk_table | cut -d'|' -f1 | tr '\n' ' ')
[[ $order == '/dev/nvme0n1 /dev/sda /dev/sdb /dev/sdc ' ]] ||
  fail "removable disks were not moved to the end: got '$order'"

# The two that are not removable keep the order the kernel gave them, and so
# do the two that are. A sort would have reshuffled disks that have nothing to
# do with the question being asked.

# --- what is on it ----------------------------------------------------------
#
# Coarse on purpose. The question is "is that the one with my photographs on
# it", not "describe this partition table".
holds() {
  printf '%s\n' "/dev/test|$1" >"$TMP/contents"
  AURADE_DISK_CONTENTS=$TMP/contents disk_contents /dev/test
}
got=$(holds 'Windows')
[[ $got == 'Windows' ]] || fail "a described disk came back as '$got'"

# A disk nothing is known about says nothing rather than guessing.
: >"$TMP/contents"
got=$(AURADE_DISK_CONTENTS=$TMP/contents disk_contents /dev/test)
[[ -z $got ]] || fail "an undescribed disk claimed to hold '$got'"

# --- the disk the installer is running from ---------------------------------
#
# Worth naming rather than leaving to be inferred from "one of these is
# removable": a laptop installing from a USB stick with a second USB drive
# plugged in shows two removable disks, and only one of them would stop the
# install by being erased.
boot_from() {
  printf '%s\n' "$1 /run/archiso/bootmnt iso9660 ro 0 0" >"$TMP/mounts"
  AURADE_MOUNTS_FILE=$TMP/mounts boot_disk
}
got=$(boot_from /dev/sdb1)
[[ $got == /dev/sdb ]] || fail "a partition on sdb resolved to '$got'"
# The one that is genuinely easy to get wrong: nvme partitions keep a digit
# before the p, so stripping trailing digits turns nvme0n1p2 into nvme0n1p,
# and stripping everything from the first digit turns it into nvme.
got=$(boot_from /dev/nvme0n1p2)
[[ $got == /dev/nvme0n1 ]] || fail "a partition on nvme0n1 resolved to '$got'"
got=$(boot_from /dev/mmcblk0p1)
[[ $got == /dev/mmcblk0 ]] || fail "a partition on mmcblk0 resolved to '$got'"
# A whole disk mounted directly, which is what a dd-written stick looks like.
got=$(boot_from /dev/sdc)
[[ $got == /dev/sdc ]] || fail "a whole disk resolved to '$got'"
# Nothing mounted there at all is not an error, it is a machine that did not
# boot from removable media.
printf 'tmpfs /run tmpfs rw 0 0\n' >"$TMP/mounts"
got=$(AURADE_MOUNTS_FILE=$TMP/mounts boot_disk)
[[ -z $got ]] || fail "with no boot medium mounted, '$got' was named as one"

# --- and all three of them reach the screen ---------------------------------
printf '%s\n' \
  '/dev/nvme0n1|Windows' \
  '/dev/sda|nothing on it yet' >"$TMP/contents"
printf '/dev/sdb1 /run/archiso/bootmnt iso9660 ro 0 0\n' >"$TMP/mounts"
env AURADE_DISK_TABLE="$TMP/disks" AURADE_DISK_CONTENTS="$TMP/contents" \
  AURADE_MOUNTS_FILE="$TMP/mounts" AURADE_TUI_HEIGHT=40 \
  "$TUI" --render question-target 2>/dev/null >"$TMP/screen"

grep -Fq 'Windows' "$TMP/screen" ||
  fail 'the disk list does not say which disk has Windows on it'
grep -Fq 'you started this installer from this one' "$TMP/screen" ||
  fail 'the disk list does not name the disk the installer is running from'
# The stick is last on the screen as well as last in the table.
last=$(grep -o '/dev/[a-z0-9]*' "$TMP/screen" | tail -1)
[[ $last == /dev/sdc ]] || fail "the last disk offered is '$last', not the removable one"

# And on the gate, which is the last chance to notice.
env AURADE_DISK_TABLE="$TMP/disks" AURADE_DISK_CONTENTS="$TMP/contents" \
  AURADE_RENDER_TARGET=/dev/nvme0n1 AURADE_TUI_HEIGHT=40 \
  "$TUI" --render gate 2>/dev/null >"$TMP/gate"
grep -Fq 'Windows' "$TMP/gate" ||
  fail 'the erase gate does not say what is on the disk it is about to erase'
# Never "unknown" anywhere on that screen. It reads as the installer having
# lost track of which disk it is talking about, on the one screen where that
# would be terrifying.
! grep -Fqw 'unknown' "$TMP/gate" ||
  fail 'the erase gate says "unknown" about a drive that simply did not report'

# --- how much life the drive says it has left -------------------------------
#
# An SSD that has been in a machine for eight years is a fine place to put an
# operating system right up until it is not, and the drive knows which it is
# long before the person choosing it does.
printf '%s\n' '/dev/nvme0n1|94' '/dev/sdb|9' '/dev/sdc|100' >"$TMP/health"

# The number itself, straight out of the reader.
got=$(AURADE_DISK_HEALTH=$TMP/health disk_wear /dev/nvme0n1)
[[ $got == 94 ]] || fail "the wear reader gave '$got' for a drive reporting 94"
# A drive that reports nothing gets nothing, rather than a zero that would read
# as a brand new drive.
got=$(AURADE_DISK_HEALTH=$TMP/health disk_wear /dev/no-such-disk)
[[ -z $got ]] || fail "a drive reporting nothing gave '$got'"

# Nothing at all until it is worth saying something. A drive at nine percent is
# a drive with nothing wrong with it, and a line on screen saying so teaches
# somebody to read every other line as a warning too.
got=$(AURADE_DISK_HEALTH=$TMP/health disk_wear_note /dev/sdb)
[[ -z $got ]] || fail "a healthy drive got the note '$got'"
got=$(AURADE_DISK_HEALTH=$TMP/health disk_wear_note /dev/nvme0n1)
[[ -n $got ]] || fail 'a drive with 94 percent of its life gone said nothing'
grep -Fq '94%' <<<"$got" || fail "the note does not carry the number: '$got'"
# The threshold is the boundary it claims to be, checked on both sides of it
# rather than at a value nowhere near it.
printf '%s\n' '/dev/edge|79' '/dev/over|80' >"$TMP/edge"
[[ -z $(AURADE_DISK_HEALTH=$TMP/edge disk_wear_note /dev/edge) ]] ||
  fail 'a drive one below the threshold was called out'
[[ -n $(AURADE_DISK_HEALTH=$TMP/edge disk_wear_note /dev/over) ]] ||
  fail 'a drive exactly at the threshold said nothing'

# A drive that answers with something that is not a percentage has not
# answered. Silence, rather than a note carrying whatever the firmware said.
printf '%s\n' '/dev/junk|not-a-number' '/dev/huge|4294967295' '/dev/neg|-3' \
  '/dev/blank|' '/dev/pad|007' >"$TMP/bad"
for bad in /dev/junk /dev/huge /dev/neg /dev/blank; do
  got=$(AURADE_DISK_HEALTH=$TMP/bad disk_wear "$bad")
  [[ -z $got ]] || fail "a drive answering nonsense gave '$got' for $bad"
  got=$(AURADE_DISK_HEALTH=$TMP/bad disk_wear_note "$bad")
  [[ -z $got ]] || fail "a drive answering nonsense got the note '$got'"
done
# A padded number is a number. `08` is a syntax error to bash arithmetic
# rather than eight, which is the kind of thing firmware does.
got=$(AURADE_DISK_HEALTH=$TMP/bad disk_wear /dev/pad)
[[ $got == 7 ]] || fail "a zero padded 007 read as '$got'"
# `08` and `09` are the ones that bite: valid decimal, invalid octal, and an
# arithmetic error rather than a wrong answer, so a drive reporting eight
# percent wear would go silent instead of reporting eight percent.
printf '%s\n' '/dev/pad8|08' '/dev/pad9|09' '/dev/pad85|085' >>"$TMP/bad"
[[ $(AURADE_DISK_HEALTH=$TMP/bad disk_wear /dev/pad8) == 8 ]] ||
  fail "a drive reporting 08 read as '$(AURADE_DISK_HEALTH=$TMP/bad disk_wear /dev/pad8)'"
[[ $(AURADE_DISK_HEALTH=$TMP/bad disk_wear /dev/pad9) == 9 ]] ||
  fail 'a drive reporting 09 was not read as nine'
# And one over the threshold, so the octal path is exercised where it changes
# what somebody sees rather than only where it changes a number.
[[ -n $(AURADE_DISK_HEALTH=$TMP/bad disk_wear_note /dev/pad85) ]] ||
  fail 'a drive reporting 085 percent wear said nothing'

# On the list, under the disk it belongs to, and only under that one.
env AURADE_DISK_TABLE="$TMP/disks" AURADE_DISK_CONTENTS="$TMP/contents" \
  AURADE_DISK_HEALTH="$TMP/health" AURADE_TUI_HEIGHT=40 \
  "$TUI" --render question-target 2>/dev/null >"$TMP/wear"
grep -Fq '94% of its write life used' "$TMP/wear" ||
  fail 'the disk list does not report a worn drive'
[[ $(grep -c 'write life used' "$TMP/wear") -eq 2 ]] ||
  fail 'the wrong number of drives were called out as worn'

# And on the gate, which is the screen somebody reads once they have decided.
env AURADE_DISK_TABLE="$TMP/disks" AURADE_DISK_CONTENTS="$TMP/contents" \
  AURADE_DISK_HEALTH="$TMP/health" AURADE_RENDER_TARGET=/dev/nvme0n1 \
  AURADE_TUI_HEIGHT=40 "$TUI" --render gate 2>/dev/null >"$TMP/gatewear"
grep -Fq '94%' "$TMP/gatewear" ||
  fail 'the erase gate does not say how worn the drive it is about to erase is'
# It never blocks and it never advises. The drive reported a number, and that
# is the entire claim being made.
refute grep -Eqi 'replace|should not|do not install|failing|dying' "$TMP/gatewear"

# A healthy target says nothing on the gate either, so the line means what it
# says wherever it appears.
env AURADE_DISK_TABLE="$TMP/disks" AURADE_DISK_CONTENTS="$TMP/contents" \
  AURADE_DISK_HEALTH="$TMP/health" AURADE_RENDER_TARGET=/dev/sdb \
  AURADE_TUI_HEIGHT=40 "$TUI" --render gate 2>/dev/null >"$TMP/gatefine"
refute grep -Fq 'write life' "$TMP/gatefine"
refute grep -Fqw 'Wear' "$TMP/gatefine"

(( failures == 0 )) || exit 1
echo 'installer disk identity test: PASS (contents named, boot medium named, removable last, wear reported)'
