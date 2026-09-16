#!/bin/bash
# Run a command in the AuraDE Arch validation root with mount cleanup.
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "run-in-arch-root.sh must run as root." >&2
  exit 1
fi

WORKDIR="${AURADE_WORKDIR:-/mnt/build/aurade-work}"
ARCHROOT="${ARCHROOT:-${WORKDIR}/archroot}"
mounted_root=0

if [[ "$#" -eq 0 ]]; then
  set -- /usr/bin/bash
fi

# A container rather than a chroot, where one is available.
#
# Linux refuses CLONE_NEWUSER to any process whose filesystem root has been
# changed, so nothing inside an arch-chroot can make a user namespace, as root
# or otherwise: unshare --user answers "Operation not permitted" and bubblewrap
# says the kernel does not allow unprivileged user namespaces, which is true
# here but for the other reason. aurade-login's check drives its session
# supervisor through bwrap, so under arch-chroot that package can never build,
# on any kernel. systemd-nspawn enters the same directory as a container, where
# a user namespace is allowed, and the check runs.
#
# arch-chroot stays as the fallback: it is what a machine without systemd has,
# and every package whose tests do not need a namespace builds the same either
# way. AURADE_ARCH_ROOT_CHROOT=1 forces it.
if [[ "${AURADE_ARCH_ROOT_CHROOT:-0}" != 1 ]] && command -v systemd-nspawn >/dev/null 2>&1; then
  exec systemd-nspawn --quiet --directory="${ARCHROOT}" \
    --as-pid2 --keep-unit --register=no \
    --setenv=AURADE_IN_ARCH_ROOT=1 -- "$@"
fi

if ! mountpoint -q "${ARCHROOT}"; then
  mount --bind "${ARCHROOT}" "${ARCHROOT}"
  mounted_root=1
fi

cleanup() {
  if [[ "${mounted_root}" -eq 1 ]]; then
    umount -R "${ARCHROOT}"
  fi
}
trap cleanup EXIT

arch-chroot "${ARCHROOT}" "$@"
