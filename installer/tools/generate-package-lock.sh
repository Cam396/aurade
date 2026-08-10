#!/usr/bin/env bash
# Create the exact, sorted package lock consumed by aurade-install.
set -Eeuo pipefail

REPO_DIR=${1:?Usage: generate-package-lock.sh REPO_DIR OUTPUT [EXPECTED_NAMES]}
OUTPUT=${2:?Usage: generate-package-lock.sh REPO_DIR OUTPUT [EXPECTED_NAMES]}
EXPECTED=${3:-$(cd -- "$(dirname -- "$0")/.." && pwd -P)/expected-packages.txt}

command -v bsdtar >/dev/null || { echo 'generate-package-lock: bsdtar is required' >&2; exit 1; }
[[ -d $REPO_DIR ]] || { echo "generate-package-lock: repository not found: $REPO_DIR" >&2; exit 1; }
[[ -r $EXPECTED ]] || { echo "generate-package-lock: expected package list not found: $EXPECTED" >&2; exit 1; }

tmp=$(mktemp)
names=$(mktemp)
trap 'rm -f "$tmp" "$names"' EXIT

while IFS= read -r -d '' package; do
  filename=${package##*/}
  pkginfo=$(bsdtar -xOf "$package" .PKGINFO) || { echo "generate-package-lock: cannot read $filename" >&2; exit 1; }
  pkgname=$(awk -F ' = ' '$1 == "pkgname" {print $2; exit}' <<<"$pkginfo")
  pkgver=$(awk -F ' = ' '$1 == "pkgver" {print $2; exit}' <<<"$pkginfo")
  arch=$(awk -F ' = ' '$1 == "arch" {print $2; exit}' <<<"$pkginfo")
  [[ -n $pkgname && -n $pkgver && -n $arch ]] || { echo "generate-package-lock: incomplete .PKGINFO in $filename" >&2; exit 1; }
  printf '%s\n' "$pkgname" >>"$names"
  printf '%s %s %s %s %s\n' "$(sha256sum "$package" | awk '{print $1}')" "$filename" "$pkgname" "$pkgver" "$arch" >>"$tmp"
done < <(find "$REPO_DIR" -maxdepth 1 -type f -name '*.pkg.tar.*' ! -name '*.sig' -print0 | sort -z)

[[ -s $tmp ]] || { echo 'generate-package-lock: repository contains no package archives' >&2; exit 1; }
sort -u "$names" -o "$names"
sort -u "$EXPECTED" | sed '/^$/d;/^#/d' >"$tmp.expected"
trap 'rm -f "$tmp" "$names" "$tmp.expected"' EXIT
if ! diff -u "$tmp.expected" "$names"; then
  echo 'generate-package-lock: repository package names do not match the release set' >&2
  exit 1
fi
if [[ $(wc -l <"$names") -ne $(wc -l <"$tmp") ]]; then
  echo 'generate-package-lock: repository contains multiple versions of a package' >&2
  exit 1
fi

install -Dm0644 /dev/null "$OUTPUT"
{
  printf '%s\n' '# sha256 filename pkgname pkgver arch'
  LC_ALL=C sort -k3,3 "$tmp"
} >"$OUTPUT"
sha256sum -c <(awk -v dir="$REPO_DIR" '!/^#/ {print $1 "  " dir "/" $2}' "$OUTPUT") >/dev/null
printf '%s\n' "$OUTPUT"
