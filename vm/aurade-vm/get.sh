#!/usr/bin/env bash
# Get aurade-vm on Linux or a Mac and start it.
#
#   curl -fsSL https://raw.githubusercontent.com/Cam396/aurade/main/vm/aurade-vm/get.sh | bash
#
# It downloads the aurade-vm program for this computer, checks it against the
# SHA-256 written into this script for that version (and the release key's
# signature too, when gpg is installed), and runs it. curl does not mark the
# file as quarantined the way a browser download is on a Mac, so nothing stops
# to ask about it; the checks are what make that safe. A file that does not
# match is deleted and never run.
#
# Options after `bash -s --` go to aurade-vm:
#   curl -fsSL .../get.sh | bash -s -- --release v1.1.2
#
# Settings, all optional, as environment variables:
#   AURADE_VM_BIN_DIR   where the program is kept (default ~/.local/share/aurade/bin)
#   AURADE_VM_BASE_URL  where to download from (for testing a build)
set -euo pipefail

# >>> pins (written by build.sh; do not edit by hand)
VERSION=1.0.0
PIN_linux_amd64=2610a43bcab223bd6507b7e42ffdb7143abccdf8a131b1a85213a02806d2ca35
PIN_linux_arm64=0c9e4c709f4b8f728326adbd1a641b5def13329c9db231bde0b0ad45ba5b456f
PIN_darwin_amd64=32b3f3bea0aaa0cee887e4980514f5bad28dacda0f7b1cb95c04da9b5f039650
PIN_darwin_arm64=f5498ad1a14f1e2574a445f33ad47ff1e212998819613d90b6b486a6df2ec469
# <<< pins

FINGERPRINT=BC390DCF360B2184DBBF008B8B2AB2EFE667CB69
say() { printf '\033[1maurade-vm:\033[0m %s\n' "$*"; }
die() { printf '\033[1maurade-vm:\033[0m %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

case $(uname -s) in
  Linux) os=linux ;;
  Darwin) os=darwin ;;
  *) die "this is $(uname -s); on Windows use the PowerShell line instead" ;;
esac
case $(uname -m) in
  x86_64|amd64) arch=amd64 ;;
  arm64|aarch64) arch=arm64 ;;
  *) die "aurade-vm is not built for $(uname -m)" ;;
esac
pin_var=PIN_${os}_${arch}
want=${!pin_var}
[[ -n $want ]] || die "no aurade-vm build is published for ${os}-${arch} yet"

sha256_of() {
  if have sha256sum; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

bin_dir=${AURADE_VM_BIN_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/aurade/bin}
exe=$bin_dir/aurade-vm
name=aurade-vm-$VERSION-$os-$arch
base=${AURADE_VM_BASE_URL:-https://github.com/Cam396/aurade/releases/download/aurade-vm-v$VERSION}
base=${base%/}

if [[ -x $exe && $(sha256_of "$exe") == "$want" ]]; then
  say "aurade-vm $VERSION is already here"
else
  have curl || die 'curl is needed to download aurade-vm'
  mkdir -p "$bin_dir"
  rm -f "$exe"
  say "downloading aurade-vm $VERSION"
  curl -fL --progress-bar --retry 3 -o "$exe.part" "$base/$name"
  got=$(sha256_of "$exe.part")
  if [[ $got != "$want" ]]; then
    rm -f "$exe.part"
    die "the download does not match the SHA-256 this script expects, so it was deleted (expected $want, got $got)"
  fi
  if have gpg; then
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    if curl -fsL -o "$tmp/SHA256SUMS" "$base/SHA256SUMS" &&
      curl -fsL -o "$tmp/SHA256SUMS.sig" "$base/SHA256SUMS.sig" &&
      curl -fsL -o "$tmp/key.asc" "https://github.com/Cam396/aurade/raw/main/pins/aurade-release.gpg"; then
      GNUPGHOME=$tmp gpg --batch --quiet --import "$tmp/key.asc" 2>/dev/null || true
      status=$(GNUPGHOME=$tmp gpg --batch --status-fd 1 --verify "$tmp/SHA256SUMS.sig" "$tmp/SHA256SUMS" 2>/dev/null || true)
      if ! grep -q "VALIDSIG ${FINGERPRINT} " <<<"$status" || ! grep -q "^$want  $name\$" "$tmp/SHA256SUMS"; then
        rm -f "$exe.part"
        die "the release's checksums are not signed by the AuraDE release key ${FINGERPRINT}, so the download was deleted"
      fi
      say "checked: SHA-256 and the release key's signature"
    else
      say "checked: SHA-256 (the signed checksums could not be fetched)"
    fi
  else
    say "checked: SHA-256 (install gpg to check the signature as well)"
  fi
  chmod 755 "$exe.part"
  mv -f "$exe.part" "$exe"
  if [[ $os == darwin ]] && have xattr; then
    xattr -d com.apple.quarantine "$exe" 2>/dev/null || true
  fi
fi

# Piped into bash, standard input is this script; the screens need the
# keyboard, which is the terminal. Opening it is the test: with no terminal at
# all the device exists and still cannot be opened.
if [[ ! -t 0 ]] && { : </dev/tty; } 2>/dev/null; then
  exec "$exe" "$@" </dev/tty
fi
exec "$exe" "$@"
