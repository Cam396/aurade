#!/usr/bin/env bash
# Build aurade-vm for every host it runs on, with checksums, and sign the
# checksums when a key is given.
#
#   vm/aurade-vm/build.sh VERSION [OUTDIR]
#
# GPGKEY (a fingerprint) signs SHA256SUMS with that key from GNUPGHOME. The
# one-line installers check that signature against the release key, so a
# build signed with any other key is for testing only.
#
# PIN=1 writes this version and its hashes into get.ps1 and get.sh, which is
# what those scripts check a download against. Commit that change with the
# release, or the scripts keep fetching the previous version.
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
if [[ ${PIN:-0} == 1 ]]; then
  python3 - "$HERE" "$VERSION" "$OUT/SHA256SUMS" <<'PY'
import re, sys
here, version, sums = sys.argv[1:]
pins = {}
for line in open(sums):
    digest, name = line.split()
    m = re.fullmatch(r"aurade-vm-" + re.escape(version) + r"-(\w+)-(\w+)(\.exe)?", name)
    if m:
        pins[(m[1], m[2])] = digest
def swap(path, block):
    s = open(path).read()
    new = re.sub(r"(# >>> pins[^\n]*\n).*?(# <<< pins)", lambda m: m[1] + block + m[2], s, flags=re.S)
    assert new != s or block in s, path
    open(path, "w").write(new)
swap(f"{here}/get.ps1", f"$Version = '{version}'\n$Pins = @{{\n" + "".join(
    f"  'windows-{a}' = '{pins.get(('windows', a), '')}'\n" for a in ("amd64", "arm64")) + "}\n")
swap(f"{here}/get.sh", f"VERSION={version}\n" + "".join(
    f"PIN_{o}_{a}={pins.get((o, a), '')}\n" for o in ("linux", "darwin") for a in ("amd64", "arm64")))
PY
  echo "pinned $VERSION in get.ps1 and get.sh"
fi
echo "$OUT"
