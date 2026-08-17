#!/usr/bin/env bash
set -Eeuo pipefail
# These assertions are bare `grep -Fq` under `set -e`, so a stale expectation
# ends the run with an exit code and not one word about where. This makes each
# of them name itself on the way out. Guarded on errexit still being on,
# because a non-zero exit inside a deliberate `set +e` block is an expected
# result being collected, not an assertion giving up.
trap 'case $- in *e*) printf "%s: line %s gave up: %s\n" "${0##*/}" "$LINENO" "$BASH_COMMAND" >&2 ;; esac' ERR

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
install -d -m 0755 "$TMP/bin"

cat >"$TMP/bin/reflector" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
save=
previous=
for arg in "$@"; do
  if [[ $previous == --save ]]; then save=$arg; fi
  previous=$arg
done
[[ -n $save ]] || exit 2
printf '%s\n' 'Server = https://mirror.example.invalid/$repo/os/$arch' >"$save"
EOF
chmod 0755 "$TMP/bin/reflector"

printf '%s\n' 'Server = https://archive.archlinux.org/repos/2026/07/12/$repo/os/$arch' \
  >"$TMP/mirrorlist"
printf '%s\n' 'Server = https://archive.archlinux.org/repos/2026/07/12/$repo/os/$arch' \
  >"$TMP/pacman.conf"
PATH="$TMP/bin:$PATH" \
  AURADE_MIRRORLIST="$TMP/mirrorlist" \
  AURADE_PACMAN_CONF="$TMP/pacman.conf" \
  "$ROOT/installer/archiso/airootfs/usr/local/sbin/aurade-refresh-mirrors" \
  >"$TMP/success.out" 2>&1
grep -Fxq 'Server = https://mirror.example.invalid/$repo/os/$arch' "$TMP/mirrorlist"
grep -Fxq 'Server = https://archive.archlinux.org/repos/2026/07/12/$repo/os/$arch' "$TMP/pacman.conf"
grep -Fq 'live pacman.conf was left unchanged' "$TMP/success.out"

# A failed discovery must leave both the bundled list and the pinned config
# untouched so troubleshooting remains reproducible.
printf '%s\n' 'Server = https://archive.archlinux.org/repos/2026/07/12/$repo/os/$arch' \
  >"$TMP/mirrorlist"
printf '%s\n' 'Server = https://archive.archlinux.org/repos/2026/07/12/$repo/os/$arch' \
  >"$TMP/pacman.conf"
cat >"$TMP/bin/reflector" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
chmod 0755 "$TMP/bin/reflector"
PATH="$TMP/bin:$PATH" \
  AURADE_MIRRORLIST="$TMP/mirrorlist" \
  AURADE_PACMAN_CONF="$TMP/pacman.conf" \
  "$ROOT/installer/archiso/airootfs/usr/local/sbin/aurade-refresh-mirrors" \
  >"$TMP/failure.out" 2>&1
grep -Fxq 'Server = https://archive.archlinux.org/repos/2026/07/12/$repo/os/$arch' "$TMP/mirrorlist"
grep -Fxq 'Server = https://archive.archlinux.org/repos/2026/07/12/$repo/os/$arch' "$TMP/pacman.conf"
grep -Fq 'mirror discovery failed' "$TMP/failure.out"

echo 'refresh mirrors test: PASS'
