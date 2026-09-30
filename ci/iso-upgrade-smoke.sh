#!/usr/bin/env bash
# Install an older AuraDE release, turn on online updates with the command the
# README gives its users, update, and then check the result the way
# ci/iso-install-smoke.sh checks a fresh install.
#
#   ci/iso-upgrade-smoke.sh OLD_ISO [NEW_REPO_DIR] [WORKDIR]
#
# 1.0.0 and 1.1.0 installs read only the repository copy on their own disk, so
# they never see an update until the README's command is run once. This runs
# that command verbatim, as the first thing on the installed machine, against
# the real hosted repository and the real Arch mirrors, and runs it twice to
# show a second paste changes nothing.
#
# Before a release is published its packages are not hosted yet. NEW_REPO_DIR
# stands in for them: it is served from this machine, the hosted server line
# is pointed at it for one more update, and then put back. Without it, the
# update takes whatever is hosted. Either way the smoke that follows requires
# the package versions this tree builds, first-run setup, the desktop, and a
# clean sign out and back in.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
OLD_ISO=${1:?usage: $0 OLD_ISO [NEW_REPO_DIR] [WORKDIR]}
NEW_REPO=${2:-}
WORK=${3:-${TMPDIR:-/var/tmp}/aurade-iso-upgrade-smoke}
HOSTED=https://github.com/Cam396/aurade/releases/download/repo-x86_64
OVMF_CODE=${OVMF_CODE:-/usr/share/edk2/x64/OVMF_CODE.4m.fd}

fail() { echo "iso upgrade smoke: $*" >&2; exit 1; }
[[ -z $NEW_REPO || -f $NEW_REPO/aurade.db ]] || fail "no repository at $NEW_REPO"

# The command exactly as users copy it.
CMD=$(awk '/<!-- enable-updates -->/ { on = 1; next } on && /^```sh$/ { grab = 1; next } grab && /^```$/ { exit } grab { print }' "$ROOT/README.md")
[[ -n $CMD && $CMD != *$'\n'* ]] || fail 'the README has no one-line enable-updates command'
echo "==> the README's command: $CMD"

# A pristine copy of the installed disk lets a rerun skip the install.
if [[ -f $WORK/installed.qcow2 && -f $WORK/installed-vars.fd ]]; then
  echo "==> reusing the installed older release in $WORK"
else
  AURADE_SMOKE_INSTALL_ONLY=1 "$ROOT/ci/iso-install-smoke.sh" "$OLD_ISO" "$WORK"
  cp -f "$WORK/disk.qcow2" "$WORK/installed.qcow2"
  cp -f "$WORK/OVMF_VARS.fd" "$WORK/installed-vars.fd"
fi
cp -f "$WORK/installed.qcow2" "$WORK/disk.qcow2"
cp -f "$WORK/installed-vars.fd" "$WORK/OVMF_VARS.fd"

echo "==> boot the older release"
SSH_PORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
qemu-system-x86_64 -machine q35,accel=kvm -cpu host -smp 4 -m 4096 \
  -drive "if=pflash,format=raw,readonly=on,file=$OVMF_CODE" \
  -drive "if=pflash,format=raw,file=$WORK/OVMF_VARS.fd" \
  -drive "file=$WORK/disk.qcow2,if=virtio,format=qcow2" \
  -display none -no-reboot -boot c \
  -nic "user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:${SSH_PORT}-:22" \
  -serial "file:$WORK/upgrade-serial.log" -daemonize -pidfile "$WORK/upgrade.pid"
server_pid=
cleanup() {
  kill "$(cat "$WORK/upgrade.pid" 2>/dev/null)" 2>/dev/null || true
  [[ -z $server_pid ]] || kill "$server_pid" 2>/dev/null || true
}
trap cleanup EXIT
ssh_opts=(-i "$WORK/id_ed25519" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
          -o ConnectTimeout=5 -o BatchMode=yes -o LogLevel=ERROR -p "$SSH_PORT")
for _ in $(seq 1 90); do
  ssh "${ssh_opts[@]}" root@127.0.0.1 true 2>/dev/null && break
  sleep 5
done
sremote() { ssh "${ssh_opts[@]}" root@127.0.0.1 "$@"; }
sremote true || fail 'the older release never answered on ssh'
echo "   $(sremote 'pacman -Q chromiumos-ash aurade-greeter | tr "\n" " "')"
sremote 'cat /etc/pacman.d/aurade-mirrorlist' | sed 's/^/   before: /'

echo "==> paste the command"
# Every pacman question is answered with its default, as pressing Enter does.
sremote "yes '' | bash -c $(printf '%q' "$CMD")" >"$WORK/enable-updates.log" 2>&1 ||
  { tail -40 "$WORK/enable-updates.log"; fail 'the README command failed'; }
tail -3 "$WORK/enable-updates.log" | sed 's/^/   /'
mirrors=$(sremote 'cat /etc/pacman.d/aurade-mirrorlist')
[[ $(sed -n 1p <<<"$mirrors") == "Server = $HOSTED" ]] || fail 'the hosted repository is not the first server'
[[ $(sed -n 2p <<<"$mirrors") == Server\ =\ file://* ]] || fail 'the copy on the disk is no longer the fallback'
sremote 'pacman -Sy 2>&1' | grep -q 'aurade' || fail 'pacman did not fetch the aurade database'
echo "==> paste it again"
sremote "yes '' | bash -c $(printf '%q' "$CMD")" >>"$WORK/enable-updates.log" 2>&1 || fail 'the second paste failed'
[[ $(sremote 'cat /etc/pacman.d/aurade-mirrorlist') == "$mirrors" ]] || fail 'a second paste changed the mirror list'
echo "   the mirror list is unchanged"

if [[ -n $NEW_REPO ]]; then
  echo "==> update to the packages in $NEW_REPO, standing in for the hosted repository"
  port=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
  python3 -m http.server "$port" --bind 127.0.0.1 --directory "$NEW_REPO" >"$WORK/repo-server.log" 2>&1 &
  server_pid=$!
  sleep 1
  # QEMU's user network reaches this machine's loopback at 10.0.2.2.
  sremote "sed -i 's#^Server = ${HOSTED}\$#Server = http://10.0.2.2:${port}#' /etc/pacman.d/aurade-mirrorlist &&
           pacman -Syu --noconfirm" >"$WORK/update.log" 2>&1 ||
    { tail -40 "$WORK/update.log"; fail 'updating to the new packages failed'; }
  sremote "sed -i 's#^Server = http://10.0.2.2:${port}\$#Server = ${HOSTED}#' /etc/pacman.d/aurade-mirrorlist"
  [[ $(sremote 'cat /etc/pacman.d/aurade-mirrorlist') == "$mirrors" ]] || fail 'the mirror list was not put back'
  kill "$server_pid"; server_pid=
fi
sremote 'pacman -Dk' >/dev/null || fail 'the updated system has broken dependencies'
echo "   $(sremote 'pacman -Q chromiumos-ash aurade-greeter | tr "\n" " "')"
sremote 'sync; systemctl poweroff' || true
for _ in $(seq 1 60); do kill -0 "$(cat "$WORK/upgrade.pid" 2>/dev/null)" 2>/dev/null || break; sleep 2; done

echo "==> the updated machine, checked like a fresh install"
AURADE_SMOKE_REUSE_DISK=1 "$ROOT/ci/iso-install-smoke.sh" "$OLD_ISO" "$WORK"
echo "iso upgrade smoke: PASS (older release, README command twice, update, then the full smoke)"
