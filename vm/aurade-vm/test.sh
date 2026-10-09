#!/usr/bin/env bash
# aurade-vm's tests, and a build for every host it ships for, so a change that
# only breaks the Windows or macOS build is caught here rather than at release.
set -Eeuo pipefail

HERE=$(cd -- "$(dirname -- "$0")" && pwd -P)
cd "$HERE"

command -v go >/dev/null 2>&1 || {
  echo 'aurade-vm test: SKIP (go not installed)'
  exit 0
}

unformatted=$(gofmt -l .)
[[ -z $unformatted ]] || {
  echo "aurade-vm test: not gofmt-formatted: $unformatted" >&2
  exit 1
}
bash -n get.sh
go vet ./...
go test ./...
for target in windows/amd64 linux/amd64 darwin/amd64 darwin/arm64; do
  CGO_ENABLED=0 GOOS=${target%/*} GOARCH=${target#*/} go build -o /dev/null .
done
echo 'aurade-vm test: PASS'
