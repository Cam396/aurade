#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

for command in openssl sbsign sbverify; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "secure boot signing fixture: SKIP ($command is unavailable)"
    exit 0
  }
done

install -d -m 0700 "$TMP/etc/kernel" \
  "$TMP/usr/lib/systemd/boot/efi" "$TMP/boot"
openssl req -new -x509 -newkey rsa:2048 -nodes \
  -subj '/CN=AuraDE Secure Boot test/' -days 1 \
  -keyout "$TMP/etc/kernel/secure-boot-private-key.pem" \
  -out "$TMP/etc/kernel/secure-boot-certificate.pem" >/dev/null 2>&1
chmod 0600 "$TMP/etc/kernel/secure-boot-private-key.pem"

# A real PE/COFF systemd-boot image is used rather than a text fixture. This
# catches a wrong signing command, output truncation, and certificate mismatch.
stub=/usr/lib/systemd/boot/efi/systemd-bootx64.efi
[[ -r $stub ]] || { echo 'secure boot signing fixture: SKIP (systemd-boot image unavailable)'; exit 0; }
cp "$stub" "$TMP/usr/lib/systemd/boot/efi/systemd-bootx64.efi"
cp "$stub" "$TMP/boot/vmlinuz-linux"

AURADE_SECURE_BOOT_ROOT="$TMP" "$ROOT/installer/bin/aurade-secure-boot-sign"
sbverify --cert "$TMP/etc/kernel/secure-boot-certificate.pem" \
  "$TMP/usr/lib/systemd/boot/efi/systemd-bootx64.efi.signed" >/dev/null
sbverify --cert "$TMP/etc/kernel/secure-boot-certificate.pem" \
  "$TMP/boot/vmlinuz-linux" >/dev/null
[[ ! -e $TMP/etc/kernel/secure-boot-private-key.pem.signed ]]
printf '%s\n' 'secure boot signing fixture: PASS'
