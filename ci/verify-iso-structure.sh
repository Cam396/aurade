#!/usr/bin/env bash
# Inspect an already-built ArchISO without booting or modifying a target disk.
set -Eeuo pipefail

usage() {
  printf '%s\n' 'Usage: ci/verify-iso-structure.sh ISO [--full]' >&2
}
ISO=${1:-}
FULL=0
if [[ $# -gt 1 ]]; then
  [[ ${2:-} == --full && $# -eq 2 ]] || { usage; exit 2; }
  FULL=1
fi
[[ -n $ISO ]] || { usage; exit 2; }
[[ $ISO == /* ]] || ISO=$(readlink -f -- "$ISO")
[[ -f $ISO ]] || { echo "verify-iso-structure: ISO does not exist: $ISO" >&2; exit 1; }
command -v bsdtar >/dev/null 2>&1 || {
  echo 'verify-iso-structure: bsdtar is required' >&2
  exit 1
}

TMP=$(mktemp -d)
trap 'rm -rf -- "$TMP"' EXIT
listing="$TMP/iso.list"
bsdtar -tf "$ISO" | sed 's#^\./##' >"$listing"
grep -Eiq '^EFI/BOOT/BOOTX64\.EFI$' "$listing" || {
  echo 'verify-iso-structure: UEFI x86_64 fallback loader is missing' >&2
  exit 1
}
grep -Fxq 'loader/loader.conf' "$listing" || {
  echo 'verify-iso-structure: systemd-boot loader.conf is missing' >&2
  exit 1
}
grep -Eq '^loader/entries/[^/]+\.conf$' "$listing" || {
  echo 'verify-iso-structure: no systemd-boot entry was found' >&2
  exit 1
}
loader_conf=$(bsdtar -xOf "$ISO" loader/loader.conf)
grep -Fxq 'editor no' <<<"$loader_conf" || {
  echo 'verify-iso-structure: ISO boot editor is not disabled' >&2
  exit 1
}
entry=$(grep -E '^loader/entries/[^/]+\.conf$' "$listing" | head -1)
entry_text=$(bsdtar -xOf "$ISO" "$entry")
grep -Fq 'cow_spacesize=' <<<"$entry_text" || {
  echo 'verify-iso-structure: live entry has no bounded COW space option' >&2
  exit 1
}

if (( FULL )); then
  command -v unsquashfs >/dev/null 2>&1 || {
    echo 'verify-iso-structure: unsquashfs is required for --full' >&2
    exit 1
  }
  squashfs=$(grep -E '^arch/[^/]+/airootfs\.sfs$' "$listing" | head -1)
  [[ -n $squashfs ]] || {
    echo 'verify-iso-structure: airootfs squashfs is missing' >&2
    exit 1
  }
  image="$TMP/airootfs.sfs"
  bsdtar -xOf "$ISO" "$squashfs" >"$image"
  contents="$TMP/airootfs.list"
  unsquashfs -l "$image" >"$contents"
  for required in \
    usr/local/sbin/aurade-installer \
    usr/local/sbin/aurade-install \
    usr/local/sbin/aurade-recovery \
    usr/local/lib/aurade/aurade-journal.sh \
    opt/aurade/repo/packages.lock \
    etc/aurade-installer/snapshot; do
    grep -Fq "squashfs-root/$required" "$contents" || {
      echo "verify-iso-structure: missing live payload: $required" >&2
      exit 1
    }
  done
fi

if (( FULL )); then
  printf 'ISO structure verification: PASS (UEFI, boot policy, squashfs payload)\n'
else
  printf 'ISO structure verification: PASS (UEFI and boot policy; use --full for squashfs payload)\n'
fi
