#!/usr/bin/env bash
# Install AuraDE from an ISO onto a virtual disk, boot it, sign in, and walk
# the first-run setup to the desktop.
#
# The ISO gates prove the image is well formed and boots to the installer.
# This proves what a release claims: the installer produces a system that
# boots to the graphical login screen, signs in, runs the local account setup
# without waiting on Google, and reaches a desktop with the Files service
# answering. It needs KVM, socat, python3 pexpect, a network for the pinned
# Arch base set, and about half an hour, so it runs before a release and not
# as a fixture.
#
# Phase one boots the live image by direct kernel boot, which lets the kernel
# command line be set without touching the image: the installer autostart is
# told to stay out of the way and systemd puts a root shell on the serial line,
# so there is no login to script. The engine is then run the way the text
# installer runs it, with the flags it derives from the live image. Before
# powering off, the target gets sshd and a key so phase two can look inside.
#
# Phase two boots the disk on plain VGA, which is the software rendering path,
# and drives it through the QEMU monitor: keys to sign in and to answer the
# setup screens, screenshots as evidence. What passes or fails is read from
# the machine over ssh (processes, units, the journal's record of each setup
# screen), not from pixels.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
ISO=${1:?usage: $0 ISO [WORKDIR]}
WORK=${2:-${TMPDIR:-/var/tmp}/aurade-iso-install-smoke}
DISK_GB=${AURADE_SMOKE_DISK_GB:-40}
MEM=${AURADE_SMOKE_MEM:-4096}
CPUS=${AURADE_SMOKE_CPUS:-4}
# A free port unless one is named; a fixed default collided with the host's
# own sshd the first time this ran.
SSH_PORT=${AURADE_SMOKE_SSH_PORT:-$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')}
USERNAME=${AURADE_SMOKE_USER:-auratest}
OVMF_CODE=${OVMF_CODE:-/usr/share/edk2/x64/OVMF_CODE.4m.fd}
OVMF_VARS=${OVMF_VARS:-/usr/share/edk2/x64/OVMF_VARS.4m.fd}

fail() { echo "iso install smoke: $*" >&2; exit 1; }
for c in qemu-system-x86_64 qemu-img bsdtar ssh ssh-keygen openssl python3 socat; do
  command -v "$c" >/dev/null || fail "$c is missing"
done
python3 -c 'import pexpect' 2>/dev/null || fail 'python3 pexpect is missing'
[[ -r $ISO ]] || fail "no ISO at $ISO"
[[ -r /dev/kvm ]] || fail '/dev/kvm is not available'

mkdir -p "$WORK"
cp -f "$OVMF_VARS" "$WORK/OVMF_VARS.fd"
bsdtar -xf "$ISO" -C "$WORK" arch/boot/x86_64/vmlinuz-linux arch/boot/x86_64/initramfs-linux.img
KERNEL="$WORK/arch/boot/x86_64/vmlinuz-linux"
INITRD="$WORK/arch/boot/x86_64/initramfs-linux.img"
qemu-img create -q -f qcow2 "$WORK/disk.qcow2" "${DISK_GB}G"
[[ -f $WORK/id_ed25519 ]] || ssh-keygen -q -t ed25519 -N '' -f "$WORK/id_ed25519"
PUBKEY=$(cat "$WORK/id_ed25519.pub")
PASSWORD_HASH=$(openssl passwd -6 "$USERNAME")

common=(-machine q35,accel=kvm -cpu host -smp "$CPUS" -m "$MEM"
        -drive "if=pflash,format=raw,readonly=on,file=$OVMF_CODE"
        -drive "if=pflash,format=raw,file=$WORK/OVMF_VARS.fd"
        -drive "file=$WORK/disk.qcow2,if=virtio,format=qcow2"
        -display none -no-reboot)

echo "==> phase one: install from the live image"
AURADE_SMOKE_QEMU="qemu-system-x86_64 ${common[*]} -cdrom $ISO -kernel $KERNEL -initrd $INITRD -nic user,model=virtio-net-pci -serial stdio -monitor none" \
AURADE_SMOKE_APPEND="archisobasedir=arch archisolabel=AURADE_INSTALL cow_spacesize=4G aurade.installer=none systemd.debug_shell=ttyS0" \
AURADE_SMOKE_PUBKEY="$PUBKEY" AURADE_SMOKE_HASH="$PASSWORD_HASH" AURADE_SMOKE_USER="$USERNAME" \
AURADE_SMOKE_LOG="$WORK/phase1-serial.log" \
python3 - <<'PY'
import os, shlex, sys, time
import pexpect

qemu = shlex.split(os.environ["AURADE_SMOKE_QEMU"]) + ["-append", os.environ["AURADE_SMOKE_APPEND"]]
log = open(os.environ["AURADE_SMOKE_LOG"], "wb")
child = pexpect.spawn(qemu[0], qemu[1:], timeout=600, logfile=log, encoding=None)

def run(cmd, timeout=600, sentinel="__DONE__"):
    """Run one command in the debug shell and return its output up to the sentinel."""
    child.sendline(cmd + "; echo " + sentinel + "=$?")
    child.expect(sentinel.encode() + b"=(\\d+)", timeout=timeout)
    status = int(child.match.group(1))
    return status, child.before.decode("utf-8", "replace")

# The debug shell prints a prompt once the live system is up. Give the
# initramfs time to find the image and mount the overlay.
child.expect([b"sh-[0-9.]+# ", b"# $"], timeout=300)
run("stty -echo cols 200; export TERM=dumb")
status, out = run("cat /etc/aurade-installer/snapshot /etc/aurade-installer/repo-fingerprint")
print(out.strip())
run("(umask 077; printf '%s\\n' '" + os.environ["AURADE_SMOKE_HASH"] + "' > /root/pw)")
user = os.environ["AURADE_SMOKE_USER"]
cmd = ("/usr/local/sbin/aurade-install --target /dev/vda --username " + user +
       " --password-hash-file /root/pw --hostname aurade-smoke"
       " --arch-snapshot \"$(cat /etc/aurade-installer/snapshot)\""
       " --repo-key /opt/aurade/repo/aurade-repository.gpg"
       " --repo-fingerprint \"$(cat /etc/aurade-installer/repo-fingerprint)\""
       " --execute --confirm ERASE:/dev/vda")
print("==> " + cmd)
t0 = time.time()
status, out = run(cmd, timeout=3600)
print("==> install engine exit %d after %ds" % (status, time.time() - t0))
if status != 0:
    print(out[-6000:])
    sys.exit(1)
# Phase two needs a way in: a root key for ssh, which is the test's own
# addition to the test's own disk. It signs in through the graphical login
# screen the way a person does, so nothing else is added.
mount = ("mkdir -p /mnt/t && mount -o subvol=@ /dev/vda2 /mnt/t 2>/dev/null || "
         "mount /dev/vda2 /mnt/t")
status, out = run(mount)
if status != 0:
    status, out = run("lsblk -o NAME,FSTYPE,MOUNTPOINTS /dev/vda; blkid")
    print(out); sys.exit(1)
status, out = run("mkdir -p -m 700 /mnt/t/root/.ssh && printf '%s\\n' '" + os.environ["AURADE_SMOKE_PUBKEY"] +
                  "' > /mnt/t/root/.ssh/authorized_keys && chmod 600 /mnt/t/root/.ssh/authorized_keys"
                  " && printf 'PermitRootLogin prohibit-password\\n' > /mnt/t/etc/ssh/sshd_config.d/90-smoke.conf"
                  # Generate the host keys here rather than leaving them to
                  # sshdgenkeys.service at boot: sshd Wants it but does not
                  # Require it, so the two race and the first boot loses,
                  # leaving sshd to hit its start limit with no hostkeys.
                  " && for t in rsa ecdsa ed25519; do"
                  "   ssh-keygen -q -t $t -N '' -f /mnt/t/etc/ssh/ssh_host_${t}_key; done"
                  " && systemctl --root=/mnt/t enable sshd")
if status != 0:
    print(out); sys.exit(1)
status, out = run("tail -3 /mnt/t/etc/greetd/aurade.toml && umount -R /mnt/t")
print(out)
if status != 0:
    sys.exit(1)
child.sendline("sync; systemctl poweroff")
child.expect(pexpect.EOF, timeout=180)
PY

echo "==> phase two: boot the installed disk"
# Plain VGA with no render node, which is the software rendering path a VM
# without virgl takes. The monitor socket is how this script types and takes
# screenshots.
rm -f "$WORK/hmp.sock"
qemu-system-x86_64 "${common[@]}" -boot c -vga std \
  -nic "user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:${SSH_PORT}-:22" \
  -serial "file:$WORK/phase2-serial.log" \
  -monitor "unix:$WORK/hmp.sock,server,nowait" \
  -daemonize -pidfile "$WORK/phase2.pid"
trap 'kill "$(cat "$WORK/phase2.pid" 2>/dev/null)" 2>/dev/null || true' EXIT

ssh_opts=(-i "$WORK/id_ed25519" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
          -o ConnectTimeout=5 -o BatchMode=yes -p "$SSH_PORT")
for _ in $(seq 1 90); do
  ssh "${ssh_opts[@]}" root@127.0.0.1 true 2>/dev/null && break
  sleep 5
done
ssh "${ssh_opts[@]}" root@127.0.0.1 true 2>/dev/null || fail 'the installed system never answered on ssh'
sremote() { ssh "${ssh_opts[@]}" root@127.0.0.1 "$@"; }

hmp() { printf '%s\n' "$1" | socat -T 2 - "UNIX-CONNECT:$WORK/hmp.sock" >/dev/null; }
keys() { local k; for k in "$@"; do hmp "sendkey $k"; sleep 0.3; done; }
type_text() {
  local text=$1 i c
  for (( i = 0; i < ${#text}; i++ )); do
    c=${text:i:1}
    case $c in
      [a-z0-9]) hmp "sendkey $c" ;;
      [A-Z]) hmp "sendkey shift-${c,,}" ;;
      ' ') hmp 'sendkey spc' ;;
      *) fail "type_text has no key for '$c'" ;;
    esac
    sleep 0.08
  done
}
shot() {
  rm -f "$WORK/$1.ppm"
  hmp "screendump $WORK/$1.ppm"
  for _ in $(seq 1 50); do [[ -s $WORK/$1.ppm ]] && break; sleep 0.1; done
  echo "   screenshot: $WORK/$1.ppm"
}
# Wait for a line in this boot's journal, and print it.
wait_journal() {
  local pattern=$1 seconds=$2
  sremote "for i in \$(seq 1 $seconds); do journalctl -b --no-pager -o cat | grep -m1 -E '$pattern' && exit 0; sleep 1; done; exit 1"
}

echo "==> the installed system is healthy"
state=$(sremote 'timeout 300 systemctl is-system-running --wait' || true)
case $state in
  running|degraded) echo "   is-system-running: $state" ;;
  *) fail "the installed system is $state, not running" ;;
esac
# A degraded system is only acceptable for units that fail for want of
# hardware this VM does not have; anything else is a real regression.
failed=$(sremote 'systemctl --failed --no-legend --plain | awk "{print \$1}"' || true)
for u in $failed; do
  case $u in
    ""|vboxservice.service|vmware-*) ;;
    *) fail "an installed unit failed that should not have: $u" ;;
  esac
done

echo "==> the AuraDE packages are the versions this tree builds"
for pkg in chromiumos-ash auradefs aurade-greeter aurade-login; do
  want="$pkg $(sed -n 's/^\tpkgver = //p' "$ROOT/$pkg/.SRCINFO" | head -1)-$(sed -n 's/^\tpkgrel = //p' "$ROOT/$pkg/.SRCINFO" | head -1)"
  got=$(sremote "pacman -Q $pkg" 2>/dev/null || true)
  [[ $got == "$want" ]] || fail "expected '$want', got '${got:-nothing}'"
  echo "   $got"
done

echo "==> the file service is a unit whose config names the port the page asks for"
sremote 'test -f /usr/lib/systemd/user/auradefs.service' || fail 'the auradefs user unit is not installed'
sremote 'grep -q -- "--port 8902" /usr/lib/systemd/user/auradefs.service' || fail 'the unit does not name port 8902'

echo "==> the graphical login screen is what greetd runs"
sremote 'grep -q "^command = \"/usr/lib/aurade-greeter/aurade-greeter-session\"" /etc/greetd/aurade.toml' ||
  fail 'greetd is not configured for the graphical login screen'
sremote 'for i in $(seq 1 60); do pgrep -f "^/usr/bin/python3? /usr/bin/aurade-greeter|/usr/bin/aurade-greeter" >/dev/null && exit 0; sleep 1; done; exit 1' ||
  fail 'the graphical login screen never started'
sremote 'test ! -s /var/lib/aurade-greeter/quick-exits' || fail 'the login screen already fell back to text'
sleep 5
shot 1-greeter

echo "==> sign in through the login screen"
keys ret; sleep 2
keys ret; sleep 2
type_text "$USERNAME"
keys ret
sremote "for i in \$(seq 1 90); do pgrep -u $USERNAME -f -- '--aurade-enable-local-accounts' >/dev/null && exit 0; sleep 1; done; exit 1" ||
  fail 'signing in did not start the desktop session'
wait_journal 'OOBE finished loading' 120 >/dev/null || fail 'first-run setup never loaded'
sleep 5
shot 2-welcome

echo "==> first-run setup, as a local account"
# The focus order these keys rely on: Get started has focus on the welcome
# screen; on the account screen two tabs reach Next; on the local account form
# the first tab is Back, then the name, the hint, and Continue.
keys ret; sleep 8
keys tab tab ret; sleep 5
shot 3-local-account
keys tab tab; type_text 'Aura Test'; keys tab tab ret
wait_journal 'aura-local-account exited with reason: StartSession' 30 >/dev/null ||
  fail 'the local account form did not start the session'
wait_journal 'drive-pinning exited' 60 >/dev/null || fail 'first-run setup stalled after the account form'
journal=$(sremote 'journalctl -b --no-pager -o short-unix | grep "Wizard screen"')
printf '%s\n' "$journal" | sed -n '/aura-local-account exited/,$p' | sed 's/^[^ ]* [^ ]* [^ ]* \[[^]]*\] (LOGIN) /   /' | head -40
# Local accounts skip every screen that needs Google. A screen that waits on
# Google instead shows a loading card until its request times out.
for screen in locale-switch categories-selection perks-discovery gemini-intro password-selection; do
  printf '%s\n' "$journal" | grep -q "Wizard screen ${screen} exited with reason: NotApplicable" ||
    fail "${screen} was shown or waited on instead of being skipped"
done
! printf '%s\n' "$journal" | grep -q 'Wizard screen guest-tos' || fail 'guest mode was offered'
start=$(printf '%s\n' "$journal" | awk '/aura-local-account exited with reason: StartSession/ {print int($1); exit}')
end=$(printf '%s\n' "$journal" | awk '/drive-pinning exited/ {print int($1); exit}')
(( end - start <= 5 )) || fail "the account form took $(( end - start ))s to reach display size; something waited"
echo "   the account form reached display size in $(( end - start ))s"
sleep 5
shot 4-display-size
# Display size: focus starts outside the dialog, and the sixth tab reaches Next.
keys tab tab tab tab tab tab ret; sleep 6
keys ret
wait_journal 'theme-selection exited' 30 >/dev/null || fail 'the theme step did not finish'

echo "==> the desktop"
sremote "for i in \$(seq 1 60); do curl -fsS http://127.0.0.1:9222/json/list 2>/dev/null | grep -q '\"type\": \"page\"' && exit 0; sleep 2; done; exit 1" ||
  fail 'the desktop never opened a browser page'
sleep 5
shot 5-desktop
cores=$(sremote 'ls /var/lib/systemd/coredump 2>/dev/null | wc -l')
[[ $cores == 0 ]] || fail "the first login left ${cores} core dump(s)"

echo "==> the file service answers for the signed in user"
uid=$(sremote "id -u $USERNAME")
sremote "runuser -u $USERNAME -- env XDG_RUNTIME_DIR=/run/user/$uid sh -c '
  systemctl --user start auradefs.service
  for i in \$(seq 1 20); do
    curl -fsS http://127.0.0.1:8902/api/volumes >/dev/null 2>&1 && exit 0; sleep 1
  done; exit 1'" || fail 'auradefs never answered on 8902'
echo "   auradefs answered on 127.0.0.1:8902"

echo "iso install smoke: PASS (install, graphical sign in, local first run, desktop, file service)"
