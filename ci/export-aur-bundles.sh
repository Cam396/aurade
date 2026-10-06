#!/usr/bin/env bash
# Export one directory per AUR package, ready to commit to its AUR git repo.
#
# The AUR keeps one git repository per package; this tree is a monorepo. Each
# package directory is copied as it is, with three changes so it builds from
# public sources and nothing else:
#
#   aurade-wallpapers  the photographs come from the tagged tree on GitHub
#                      (installer/wallpapers), not from AUR git, which is for
#                      recipes and not 46 MB of pictures
#   auradefs           the Rust workspace comes from the tag's source archive
#   chromiumos-ash-bin the signed release build, repackaged; its dependencies
#                      are read from chromiumos-ash/PKGBUILD so they cannot drift
#
# Every package keeps its own version, the same one the pacman repository
# carries, so the AUR and the repository never disagree about what is newer.
#
# Settings:
#   AURADE_AUR_OUTPUT           where to write (absolute, must not exist)
#   AURADE_AUR_REF              the git tag (or commit) the sources come from
#   AURADE_AUR_SOURCE_SHA256    SHA-256 of that ref's source archive; fetched and
#                               computed when unset
#   AURADE_AUR_CHROMIUM_SHA256  SHA-256 of the released chromiumos-ash package;
#   AURADE_AUR_CHROMIUM_PACKAGE or a local copy of that package to hash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
OUTPUT="${AURADE_AUR_OUTPUT:-}"
REF="${AURADE_AUR_REF:-}"
GITHUB=https://github.com/Cam396/aurade
BIN_RELEASE=repo-x86_64

SOURCE_PACKAGES=(
  aurade-account-helper
  aurade-system-helper
  shill-nm-adapter
  aurade-power
  aurade-hardware
  aurade-host-bridge
  aurade-login
  aurade-greeter
  aurade-ai
  aurade-webapp-shortcuts
  aurade-wallpapers
  auradefs
  aurade
  aurade-full
)

die() {
  printf 'export-aur-bundles: %s\n' "$*" >&2
  exit 1
}

sha256_of_url() {
  curl -fsSL "$1" | sha256sum | cut -d' ' -f1
}

[[ ${OUTPUT} = /* && ${OUTPUT} != / ]] ||
  die 'AURADE_AUR_OUTPUT must be an absolute, non-root path'
[[ ! -e ${OUTPUT} ]] ||
  die "output already exists; choose another path or remove it first: ${OUTPUT}"
[[ ${REF} =~ ^[A-Za-z0-9._-]+$ ]] ||
  die 'AURADE_AUR_REF must name the git tag (or commit) the sources come from'

archive_url="${GITHUB}/archive/${REF}.tar.gz"
# GitHub names the top directory after the repository and the ref, without a
# leading v on a version tag.
archive_dir="aurade-${REF#v}"
source_sha="${AURADE_AUR_SOURCE_SHA256:-$(sha256_of_url "${archive_url}")}"
[[ ${source_sha} =~ ^[[:xdigit:]]{64}$ ]] ||
  die 'the source archive digest is not a SHA-256'

chromium_ver=$(awk -F= '$1 == "pkgver" {print $2; exit}' "${REPO_ROOT}/chromiumos-ash/PKGBUILD")
chromium_rel=$(awk -F= '$1 == "pkgrel" {print $2; exit}' "${REPO_ROOT}/chromiumos-ash/PKGBUILD")
chromium_file="chromiumos-ash-${chromium_ver}-${chromium_rel}-x86_64.pkg.tar.zst"
chromium_sha="${AURADE_AUR_CHROMIUM_SHA256:-}"
if [[ -z ${chromium_sha} && -n ${AURADE_AUR_CHROMIUM_PACKAGE:-} ]]; then
  [[ $(basename "${AURADE_AUR_CHROMIUM_PACKAGE}") == "${chromium_file}" ]] ||
    die "AURADE_AUR_CHROMIUM_PACKAGE is not ${chromium_file}"
  chromium_sha=$(sha256sum "${AURADE_AUR_CHROMIUM_PACKAGE}" | cut -d' ' -f1)
fi
[[ ${chromium_sha} =~ ^[[:xdigit:]]{64}$ ]] ||
  die "set AURADE_AUR_CHROMIUM_SHA256 or AURADE_AUR_CHROMIUM_PACKAGE for ${chromium_file}"

mkdir -p "${OUTPUT}"

# Single-quote a value for a PKGBUILD array.
quote() {
  local value=${1//\'/\'\\\'\'}
  printf "    '%s'\n" "${value}"
}

copy_package() {
  local package=$1 dir="${OUTPUT}/$1"
  [[ -f ${REPO_ROOT}/${package}/PKGBUILD ]] || die "missing package directory: ${package}"
  mkdir -p "${dir}"
  # What git tracks, and nothing a local build left behind (pkg/, src/, staged
  # wallpapers, a Rust target directory).
  git -C "${REPO_ROOT}" ls-files -z -- "${package}" |
    while IFS= read -r -d '' file; do
      install -Dm"$(stat -c '%a' "${REPO_ROOT}/${file}")" \
        "${REPO_ROOT}/${file}" "${OUTPUT}/${file}"
    done

  # Rewritten below for some packages; ci/aur-package-smoke.sh writes it fresh.
  rm -f "${dir}/.SRCINFO"
  case ${package} in
    aurade-wallpapers)
      # Each photograph is downloaded from the tagged tree under its own name.
      sed -i -E "s#^(\s*)'([A-Za-z0-9._-]+\.png)'#\1'\2::${GITHUB}/raw/${REF}/installer/wallpapers/\2'#" \
        "${dir}/PKGBUILD"
      ;;
    auradefs)
      # The workspace is the tag's own, unpacked by makepkg; nothing is vendored
      # into AUR git. Cargo.lock pins every crate.
      rm -rf "${dir}/workspace"
      python3 - "${dir}/PKGBUILD" "${archive_url}" "${archive_dir}" "${source_sha}" <<'EOF'
import re, sys
path, url, top, sha = sys.argv[1:]
s = open(path).read()
s = s.replace("source=(\n", f"source=(\n  'aurade-src.tar.gz::{url}'\n", 1)
s = s.replace("sha256sums=(", f"sha256sums=('{sha}'\n            ", 1)
s = s.replace("${srcdir}/auradefs-src", "${srcdir}/" + top + "/auradefs/workspace")
open(path, "w").write(s)
EOF
      ;;
  esac
  # A dependency on the Chromium package names the -bin package, which is the
  # one the AUR has. Helpers resolve that name directly.
  sed -i -E "s/(['\"])chromiumos-ash(>=|['\"])/\1chromiumos-ash-bin\2/" "${dir}/PKGBUILD"

  if find "${dir}" -type f -size +1M -print -quit | grep -q .; then
    die "${package}: a file over 1 MiB would go into AUR git"
  fi
}

for package in "${SOURCE_PACKAGES[@]}"; do
  copy_package "${package}"
done

# --- chromiumos-ash-bin ------------------------------------------------------
read_array() {
  (
    # shellcheck disable=SC1091
    source "${REPO_ROOT}/chromiumos-ash/PKGBUILD"
    local -n arr=$1
    printf '%s\n' "${arr[@]}"
  )
}
mapfile -t ash_depends < <(read_array depends)
mapfile -t ash_optdepends < <(read_array optdepends)
mapfile -t ash_backup < <(read_array backup)
(( ${#ash_depends[@]} > 10 )) || die 'could not read the chromiumos-ash dependencies'

bin="${OUTPUT}/chromiumos-ash-bin"
mkdir -p "${bin}"
install -m644 "${REPO_ROOT}/chromiumos-ash/LICENSE" "${bin}/LICENSE"
{
  cat <<EOF
# Maintainer: AuraDE Contributors
# Generated by ci/export-aur-bundles.sh from chromiumos-ash/PKGBUILD.
pkgname=chromiumos-ash-bin
pkgver=${chromium_ver}
pkgrel=${chromium_rel}
pkgdesc="ChromeOS Ash desktop for Linux, as built for AuraDE (prebuilt)"
arch=('x86_64')
url="${GITHUB}"
license=('BSD-3-Clause')
provides=("chromiumos-ash=\${pkgver}-\${pkgrel}")
conflicts=('chromiumos-ash')
options=('!strip' '!debug')
EOF
  echo 'depends=('; for d in "${ash_depends[@]}"; do quote "$d"; done; echo ')'
  echo 'optdepends=('; for d in "${ash_optdepends[@]}"; do quote "$d"; done; echo ')'
  echo 'backup=('; for d in "${ash_backup[@]}"; do quote "$d"; done; echo ')'
  cat <<EOF
# The release's own package, unpacked as it is. The build behind it is the one
# the pacman repository and the ISO install, from the same tag.
source=("${GITHUB}/releases/download/${BIN_RELEASE}/chromiumos-ash-\${pkgver}-\${pkgrel}-\${CARCH}.pkg.tar.zst"
        'LICENSE')
noextract=("chromiumos-ash-\${pkgver}-\${pkgrel}-\${CARCH}.pkg.tar.zst")
sha256sums=('${chromium_sha}'
            '$(sha256sum "${REPO_ROOT}/chromiumos-ash/LICENSE" | cut -d' ' -f1)')

package() {
    bsdtar --exclude='.BUILDINFO' --exclude='.MTREE' --exclude='.PKGINFO' \\
        --exclude='.INSTALL' --no-same-owner \\
        -xpf "\${srcdir}/chromiumos-ash-\${pkgver}-\${pkgrel}-\${CARCH}.pkg.tar.zst" \\
        -C "\${pkgdir}"
    install -Dm644 "\${srcdir}/LICENSE" "\${pkgdir}/usr/share/licenses/\${pkgname}/LICENSE"
}
EOF
} >"${bin}/PKGBUILD"

cat >"${OUTPUT}/AUR-EXPORT.md" <<EOF
# AuraDE AUR export

From ${REF} ($(git -C "${REPO_ROOT}" rev-parse --short=12 HEAD 2>/dev/null || echo unknown)).
One directory per AUR repository. Before pushing, in each directory as an
unprivileged user: \`makepkg --printsrcinfo > .SRCINFO\`, \`namcap PKGBUILD\`,
\`makepkg --verifysource\`. ci/aur-package-smoke.sh does all three.
EOF

printf 'AUR bundles exported to %s\n' "${OUTPUT}"
printf 'Packages: %s plus chromiumos-ash-bin\n' "${#SOURCE_PACKAGES[@]}"
