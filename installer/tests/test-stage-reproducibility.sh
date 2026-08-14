#!/usr/bin/env bash
# Compare two identical stage-only profiles without building an ISO.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
install -d -m 0755 "$TMP/repo" "$TMP/package"

while IFS= read -r name; do
  [[ -n $name ]] || continue
  printf 'pkgname = %s\npkgver = 1.0-1\narch = any\n' "$name" \
    >"$TMP/package/.PKGINFO"
  bsdtar -cf "$TMP/repo/${name}-1.0-1-any.pkg.tar.zst" \
    -C "$TMP/package" .PKGINFO
done <"$ROOT/installer/expected-packages.txt"

stage() {
  local output=$1
  env \
    AURADE_ARCH_SNAPSHOT=2026/07/12 \
    AURADE_REPO_DIR="$TMP/repo" \
    AURADE_ALLOW_UNSIGNED=1 \
    AURADE_INSTALLER_WORK_ROOT="$output" \
    SOURCE_DATE_EPOCH=1783814400 \
    "$ROOT/installer/build-iso.sh" --stage-only >/dev/null
}

manifest() {
  local root=$1 path rel mode
  while IFS= read -r -d '' path; do
    rel=${path#"$root"/}
    mode=$(stat -c '%a' -- "$path")
    if [[ -d $path ]]; then
      printf 'D %s %s\n' "$rel" "$mode"
    elif [[ -L $path ]]; then
      printf 'L %s %s %s\n' "$rel" "$mode" "$(readlink -- "$path")"
    else
      printf 'F %s %s %s\n' "$rel" "$mode" "$(sha256sum "$path" | awk '{print $1}')"
    fi
  done < <(find "$root" -mindepth 1 \( -type d -o -type f -o -type l \) -print0 | sort -z)
}

stage "$TMP/one"
stage "$TMP/two"
manifest "$TMP/one/profile" >"$TMP/one.manifest"
manifest "$TMP/two/profile" >"$TMP/two.manifest"
if ! cmp -s "$TMP/one.manifest" "$TMP/two.manifest"; then
  diff -u "$TMP/one.manifest" "$TMP/two.manifest" >&2
  exit 1
fi

echo 'stage reproducibility test: PASS'
