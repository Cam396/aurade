#!/usr/bin/env bash
# Build aurade-vm for every host it runs on, with checksums, and sign the
# checksums when a key is given.
#
#   vm/aurade-vm/build.sh VERSION [OUTDIR]
#
# GPGKEY (a fingerprint) signs SHA256SUMS with that key from GNUPGHOME. The
# one-line installers check that signature against the release key, so a
# build signed with any other key is for testing only.
set -Eeuo pipefail

VERSION=${1:?usage: build.sh VERSION [OUTDIR]}
HERE=$(cd -- "$(dirname -- "$0")" && pwd -P)
OUT=$(realpath -m -- "${2:-$HERE/dist}")
[[ $VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?$ ]] || {
  echo "build.sh: the version is like 0.1.0 or 0.1.0-rc1, not '$VERSION'" >&2
  exit 2
}

install -d -- "$OUT"
cd "$HERE"
for target in windows/amd64 windows/arm64 linux/amd64 linux/arm64 darwin/amd64 darwin/arm64; do
  os=${target%/*} arch=${target#*/}
  name="aurade-vm-$VERSION-$os-$arch"
  [[ $os != windows ]] || name+=.exe
  CGO_ENABLED=0 GOOS=$os GOARCH=$arch go build -trimpath \
    -ldflags "-s -w -buildid= -X main.version=$VERSION" -o "$OUT/$name" .
  echo "built $name"
done

cd "$OUT"
sha256sum -- aurade-vm-"$VERSION"-* >SHA256SUMS
if [[ -n ${GPGKEY:-} ]]; then
  rm -f SHA256SUMS.sig
  gpg --batch --yes --local-user "$GPGKEY" --detach-sign --output SHA256SUMS.sig SHA256SUMS
  echo "signed SHA256SUMS with $GPGKEY"
fi
echo "$OUT"
