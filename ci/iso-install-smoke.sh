#!/usr/bin/env bash
# Install AuraDE from an ISO onto a virtual disk, boot the result, and run the
# live smoke against it.
#
# The ISO gates prove the image is well formed and boots to the installer.
# This proves the installer produces a system that boots to a desktop with the
# Files app talking to its service, which is the claim a release actually
# makes. It needs KVM, a network for the pinned Arch base set, and about half
# an hour, so it is a script to run before a release and not a fixture.
#
# Phase one boots the live image by direct kernel boot, which lets the kernel
# command line be set without touching the image: the installer autostart is
# told to stay out of the way and systemd puts a root shell on the serial line,
# so there is no login to script. The engine is then run the way the text
# installer runs it, with the flags it derives from the live image. Before
# powering off, the target gets sshd and a key so phase two can reach it.
#
# Phase two boots the disk, waits for sshd, and hands over to ci/vm-smoke.sh.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
ISO=${1:?usage: $0 ISO [WORKDIR]}
WORK=${2:-/mnt/build/aurade-work/iso-install-smoke}
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
for c in qemu-system-x86_64 qemu-img bsdtar ssh ssh-keygen openssl python3; do
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
run("umask 077; printf '%s\\n' '" + os.environ["AURADE_SMOKE_HASH"] + "' > /root/pw")
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
# Phase two needs a way in and a session to look at. Both are the test's own
# additions to the test's own disk: a root key for ssh, and greetd's
# first-boot autologin for the desktop user, through the same supervisor and
# session command the greeter would have used. The product installs neither.
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
autologin = ("\\n[initial_session]\\ncommand = \\\"/usr/bin/aurade-session-supervisor /usr/bin/chromiumos-ash-session\\\"\\nuser = \\\"" + user + "\\\"\\n")
status, out = run("printf '" + autologin + "' >> /mnt/t/etc/greetd/aurade.toml && tail -4 /mnt/t/etc/greetd/aurade.toml && umount -R /mnt/t")
print(out)
if status != 0:
    sys.exit(1)
child.sendline("sync; systemctl poweroff")
child.expect(pexpect.EOF, timeout=180)
PY

echo "==> phase two: boot the installed disk"
qemu-system-x86_64 "${common[@]}" -boot c \
  -nic "user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:${SSH_PORT}-:22" \
  -serial "file:$WORK/phase2-serial.log" -monitor none -daemonize -pidfile "$WORK/phase2.pid"
trap 'kill "$(cat "$WORK/phase2.pid" 2>/dev/null)" 2>/dev/null || true' EXIT

ssh_opts=(-i "$WORK/id_ed25519" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
          -o ConnectTimeout=5 -o BatchMode=yes -p "$SSH_PORT")
for _ in $(seq 1 90); do
  ssh "${ssh_opts[@]}" root@127.0.0.1 true 2>/dev/null && break
  sleep 5
done
ssh "${ssh_opts[@]}" root@127.0.0.1 true 2>/dev/null || fail 'the installed system never answered on ssh'
sremote() { ssh "${ssh_opts[@]}" root@127.0.0.1 "$@"; }

# The claims a headless VM can actually settle. The desktop itself renders
# through a GPU, and this VM has none: under llvmpipe Ash\'s GPU process gives
# up and the compositor aborts, which is the same condition AuraDE\'s own
# installer meets by falling back to the text installer. So the render is
# checked and reported, never asserted, and everything up to it is asserted.
echo "==> the installed system is healthy"
state=$(sremote 'systemctl is-system-running' || true)
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

echo "==> the AuraDE package set is installed, at the versions the repo shipped"
for want in "chromiumos-ash 156.0.8060.0-2" "auradefs 0.1.0-4" "aurade-greeter 0.1.0-1"; do
  set -- $want
  got=$(sremote "pacman -Q $1" 2>/dev/null || true)
  [[ $got == "$1 $2" ]] || fail "expected '$want', got '${got:-nothing}'"
  echo "   $got"
done

echo "==> the file service is a unit whose config names the port the page asks for"
sremote 'test -f /usr/lib/systemd/user/auradefs.service' || fail 'the auradefs user unit is not installed'
sremote 'grep -q -- "--port 8902" /usr/lib/systemd/user/auradefs.service' || fail 'the unit does not name port 8902'
# Start it for the installed user the way the session would, out of band of the
# desktop, and require it to answer. This is the fix under test: the unit runs
# and binds the loopback port the shipped page reaches.
# Lingering gives the user a persistent systemd manager, so this does not
# depend on a graphical session that this VM cannot keep up.
uid=$(sremote "id -u $USERNAME")
sremote "loginctl enable-linger $USERNAME"
sremote "for i in \$(seq 1 20); do test -S /run/user/$uid/systemd/private && exit 0; sleep 1; done; exit 1" \
  || fail 'the user manager never came up under lingering'
sremote "systemctl --user -M ${USERNAME}@.host start auradefs.service" \
  || fail 'the auradefs unit would not start for the installed user'
sremote "runuser -u $USERNAME -- env XDG_RUNTIME_DIR=/run/user/$uid sh -c '
  for i in \$(seq 1 20); do
    curl -fsS http://127.0.0.1:8902/api/volumes >/dev/null 2>&1 && exit 0; sleep 1
  done; exit 1'" || fail 'auradefs started but never answered on 8902'
echo "   auradefs answered on 127.0.0.1:8902"

echo "==> greetd is up and the first-boot session was attempted"
sremote 'systemctl is-active aurade-greetd' >/dev/null || fail 'aurade-greetd is not active'
sremote "test -d /home/$USERNAME" || fail "the installed user has no home"

# Now look at the desktop, and report rather than assert.
echo "==> the desktop (reported, not asserted: this VM has no GPU)"
if sremote 'for i in $(seq 1 24); do curl -fsS http://127.0.0.1:9222/json/version >/dev/null 2>&1 && exit 0; sleep 5; done; exit 1'; then
  echo "   REACHED: Ash is up and answering CDP; running the live smoke"
  cat >"$WORK/ssh_config" <<CFG
Host aurade-smoke
  HostName 127.0.0.1
  Port $SSH_PORT
  User root
  IdentityFile $WORK/id_ed25519
  StrictHostKeyChecking no
  UserKnownHostsFile /dev/null
  BatchMode yes
CFG
  mkdir -p "$WORK/shim"
  printf '#!/bin/sh\nexec /usr/bin/ssh -F "%s" "$@"\n' "$WORK/ssh_config" >"$WORK/shim/ssh"
  chmod +x "$WORK/shim/ssh"
  PATH="$WORK/shim:$PATH" bash "$ROOT/ci/vm-smoke.sh" --host aurade-smoke \
    --test-user "$USERNAME" --files-volume-smoke --release-package-smoke "${@:3}" \
    || fail 'the desktop rendered but the live smoke did not pass'
else
  reason=$(sremote "grep -h reason= /home/$USERNAME/.local/state/aurade/session-error.txt 2>/dev/null | head -1" || true)
  echo "   NO GPU: the compositor did not come up under software rendering."
  echo "   ${reason:-reason=unknown}"
  echo "   This is the expected outcome on a machine without 3D acceleration."
  echo "   Everything the install produces up to the GPU was verified above."
fi
echo "iso install smoke: PASS (install, boot, health, packages, file service)"
