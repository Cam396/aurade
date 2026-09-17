#!/usr/bin/env bash
# Stage the photographs named by the PKGBUILD beside the package sources.
# The installer catalog is the source; the package directory is a build staging
# area and does not keep a second copy in git.
set -Eeuo pipefail

HERE=$(cd -- "$(dirname -- "$0")" && pwd -P)
REPO=$(cd -- "$HERE/.." && pwd -P)
PACKAGE="$REPO/aurade-wallpapers"
PICTURES=${AURADE_WALLPAPER_SOURCE:-$REPO/installer/wallpapers}

fail() { printf 'stage-wallpapers: %s\n' "$*" >&2; exit 1; }

[[ -f $PACKAGE/PKGBUILD ]] || fail "no PKGBUILD at $PACKAGE"
[[ -d $PICTURES ]] || fail "no photographs at $PICTURES"

mapfile -t wanted < <(
  sed -n '/^source=(/,/^)/p' "$PACKAGE/PKGBUILD" |
    grep -oE "'[^']+\.png'" | tr -d "'"
)
(( ${#wanted[@]} )) || fail "the PKGBUILD names no photographs, so nothing would ship"

staged=0
for name in "${wanted[@]}"; do
  src="$PICTURES/$name"
  [[ -f $src ]] || fail "the PKGBUILD names $name and $PICTURES does not have it"
  dest="$PACKAGE/$name"
  # Only when it actually differs, so a rebuild does not rewrite 65MB and
  # makepkg does not see every picture as freshly changed.
  if [[ ! -f $dest ]] || ! cmp -s "$src" "$dest"; then
    install -m644 "$src" "$dest"
    staged=$((staged + 1))
  fi
done

# Keep the packaged manifest in sync with the installer catalog.
if ! cmp -s "$PICTURES/manifest.tsv" "$PACKAGE/manifest.tsv"; then
  install -m644 "$PICTURES/manifest.tsv" "$PACKAGE/manifest.tsv"
  staged=$((staged + 1))
fi

printf 'stage-wallpapers: %d photographs in place (%d refreshed)\n' \
  "${#wanted[@]}" "$staged"
