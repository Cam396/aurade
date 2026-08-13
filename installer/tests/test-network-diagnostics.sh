#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
install -d "$TMP/bin"

cat >"$TMP/bin/ip" <<'EOF'
#!/usr/bin/env bash
if [[ $1 == -o ]]; then printf '%s\n' '2: eth0: <UP> mtu 1500'
else printf '%s\n' 'default via 192.0.2.1 dev eth0'
fi
EOF
cat >"$TMP/bin/getent" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' '192.0.2.53 STREAM archive.archlinux.org'
EOF
cat >"$TMP/bin/timedatectl" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' yes
EOF
cat >"$TMP/bin/curl" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >"${AURADE_CURL_LOG:?}"
EOF
chmod 0755 "$TMP/bin"/*

export AURADE_CURL_LOG="$TMP/curl.log"
PATH="$TMP/bin:$PATH" "$ROOT/installer/archiso/airootfs/usr/local/sbin/aurade-network-diagnostics" \
  --snapshot 2026/07/12 >"$TMP/ok.out"
grep -Fq 'Network preflight: ready' "$TMP/ok.out"
grep -Fq 'pinned Arch snapshot responds (2026/07/12)' "$TMP/ok.out"
grep -Fq 'repos/2026/07/12/core/os/x86_64' "$TMP/curl.log"

if PATH="$TMP/bin:$PATH" "$ROOT/installer/archiso/airootfs/usr/local/sbin/aurade-network-diagnostics" \
  --snapshot not-a-date >"$TMP/bad-snapshot.out" 2>&1; then
  echo 'malformed snapshot unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'configured Arch snapshot is malformed' "$TMP/bad-snapshot.out"

cat >"$TMP/bin/ip" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
cat >"$TMP/bin/getent" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
cat >"$TMP/bin/timedatectl" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' no
EOF
cat >"$TMP/bin/curl" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
chmod 0755 "$TMP/bin"/*
if PATH="$TMP/bin:$PATH" "$ROOT/installer/archiso/airootfs/usr/local/sbin/aurade-network-diagnostics" \
  --snapshot 2026/07/12 \
  >"$TMP/fail.out" 2>&1; then
  echo 'network diagnostics unexpectedly passed' >&2
  exit 1
fi
grep -Fq 'no active network interface' "$TMP/fail.out"
grep -Fq 'DNS cannot resolve archive.archlinux.org' "$TMP/fail.out"
grep -Fq 'system clock is not synchronized' "$TMP/fail.out"
grep -Fq 'pinned Arch snapshot is unreachable' "$TMP/fail.out"

echo 'network diagnostics test: PASS'
