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
