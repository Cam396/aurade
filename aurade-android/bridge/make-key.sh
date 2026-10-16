#!/usr/bin/env bash
# Makes the signing key for aurade-bridge.apk once. Keep the output out of git.
set -euo pipefail
out=${1:?directory for the key}
mkdir -p "$out"
openssl req -x509 -newkey rsa:3072 -sha256 -days 9125 -nodes \
  -subj "/CN=AuraDE Bridge" -keyout "$out/bridge.key.pem" -out "$out/bridge.x509.pem"
openssl pkcs8 -topk8 -nocrypt -inform PEM -outform DER -in "$out/bridge.key.pem" -out "$out/bridge.pk8"
chmod 600 "$out/bridge.key.pem" "$out/bridge.pk8"
