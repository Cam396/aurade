#!/usr/bin/env bash
# Keep the bytes of every package version that is already published.
#
#   ci/reuse-published-packages.sh REPO_DIR PUBLISHED_DIR
#
# Rebuilding a package that did not change still produces a different file:
# the build date and the build directory are inside it. Published as it is, a
# version users already have would silently change underneath them, and a
# machine holding the old copy (a cache, a mirror, the copy an install leaves
# on its own disk) would find it no longer matches the database. So a file
# whose exact name is already published is replaced by the published one,
# after its signature checks out against the repository key, and the database
# is rebuilt over the result. Only versions that are new keep their new bytes.
#
# Needs GPGKEY (to sign the new database) and AURADE_REPO_KEYRING (the public
# key the published signatures are checked against), as the release build does.
set -Eeuo pipefail

REPO_DIR=${1:?usage: $0 REPO_DIR PUBLISHED_DIR}
PUBLISHED=${2:?usage: $0 REPO_DIR PUBLISHED_DIR}
REPO_NAME=${REPO_NAME:-aurade}
: "${GPGKEY:?GPGKEY names the key that signs the database}"
: "${AURADE_REPO_KEYRING:?AURADE_REPO_KEYRING is the public key published packages are checked against}"

fail() { printf 'reuse-published: %s\n' "$*" >&2; exit 1; }

# Two builds of one version differ only in the build date and size fields.
# Anything else (a file, a mode, a dependency) is a change that needs a new
# version, and reusing the published bytes would silently drop it.
same_payload() {
  local a b rc=0
  # On disk, not tmpfs: an unchanged chromiumos-ash unpacks to gigabytes.
  a=$(mktemp -d -p "${TMPDIR:-/var/tmp}") b=$(mktemp -d -p "${TMPDIR:-/var/tmp}")
  bsdtar -xpf "$1" -C "$a" && bsdtar -xpf "$2" -C "$b" || rc=1
  if (( rc == 0 )); then
    rm -f "$a/.BUILDINFO" "$a/.MTREE" "$b/.BUILDINFO" "$b/.MTREE"
    sed -i -E '/^(builddate|size|packager) = /d' "$a/.PKGINFO" "$b/.PKGINFO"
    diff -r --no-dereference -q "$a" "$b" >&2 || rc=1
  fi
  rm -rf "$a" "$b"
  return "$rc"
}

kept=0
fresh=0
shopt -s nullglob
for package in "$REPO_DIR"/*.pkg.tar.*; do
  [[ $package == *.sig ]] && continue
  name=${package##*/}
  if [[ -f $PUBLISHED/$name ]]; then
    [[ -f $PUBLISHED/$name.sig ]] || fail "the published ${name} has no signature"
    gpgv --quiet --keyring "$AURADE_REPO_KEYRING" "$PUBLISHED/$name.sig" "$PUBLISHED/$name" 2>/dev/null ||
      fail "the published ${name} is not signed by the repository key"
    if ! cmp -s "$PUBLISHED/$name" "$package"; then
      same_payload "$PUBLISHED/$name" "$package" ||
        fail "${name} is already published with different contents; bump its pkgrel"
      cp -f "$PUBLISHED/$name" "$package"
    fi
    # Even identical bytes carry a new signature, with a new timestamp.
    cp -f "$PUBLISHED/$name.sig" "$package.sig"
    kept=$((kept + 1))
  else
    fresh=$((fresh + 1))
    printf 'reuse-published: new: %s\n' "$name"
  fi
done
shopt -u nullglob

rm -f "$REPO_DIR/$REPO_NAME".db* "$REPO_DIR/$REPO_NAME".files*
mapfile -t packages < <(find "$REPO_DIR" -maxdepth 1 -type f -name '*.pkg.tar.*' ! -name '*.sig' | sort)
repo-add --quiet --sign --key "$GPGKEY" "$REPO_DIR/$REPO_NAME.db.tar.gz" "${packages[@]}"
printf 'reuse-published: kept %s published package(s), %s new\n' "$kept" "$fresh"
