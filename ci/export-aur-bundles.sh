#!/usr/bin/env bash
# Export self-contained directories suitable for separate AUR package repos.
#
# The source tree is intentionally a monorepo, while the AUR expects one Git
# repository per package. This exporter copies only package inputs and emits
# a small x86_64 -bin wrapper for the currently published Chromium payload.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKDIR="${AURADE_WORKDIR:-${REPO_ROOT}/.aurade-work}"
OUTPUT="${AURADE_AUR_OUTPUT:-${WORKDIR}/aur-bundles}"
RELEASE_TAG="${AURADE_AUR_RELEASE_TAG:-v0.1.0-prealpha}"
RELEASE_ARCHIVE="${AURADE_AUR_RELEASE_ARCHIVE:-aurade-v0.1.0-prealpha-x86_64-repository.tar.gz}"
RELEASE_SHA256="${AURADE_AUR_ARCHIVE_SHA256:-}"
CHROMIUM_VERSION=${AURADE_AUR_CHROMIUM_VERSION:-}
CHROMIUM_PKGREL=${AURADE_AUR_CHROMIUM_PKGREL:-}
if [[ -z $CHROMIUM_VERSION ]]; then
  CHROMIUM_VERSION=$(awk -F= '$1 == "pkgver" {print $2; exit}' \
    "${REPO_ROOT}/chromiumos-ash/PKGBUILD")
fi
if [[ -z $CHROMIUM_PKGREL ]]; then
  CHROMIUM_PKGREL=$(awk -F= '$1 == "pkgrel" {print $2; exit}' \
    "${REPO_ROOT}/chromiumos-ash/PKGBUILD")
fi

SOURCE_PACKAGES=(
  aurade-account-helper
  aurade-system-helper
  shill-nm-adapter
  aurade-power
  aurade-host-bridge
  aurade-login
  aurade-ai
  aurade-webapp-shortcuts
  aurade
  aurade-full
)

die() {
  printf 'export-aur-bundles: %s\n' "$*" >&2
  exit 1
}

generate_srcinfo() {
  local package_dir="$1"
  local generated
  command -v makepkg >/dev/null 2>&1 || return 0
  generated="${package_dir}/.SRCINFO.generated"

  if (( EUID == 0 )); then
    local build_user="${AURADE_AUR_BUILD_USER:-aurabuild}"
    if ! command -v runuser >/dev/null 2>&1 || ! getent passwd "${build_user}" >/dev/null; then
      printf 'export-aur-bundles: makepkg available but no unprivileged build user; regenerate .SRCINFO with makepkg before upload\n' >&2
      return 0
    fi
    # makepkg checks that its build directory is writable even for
    # --printsrcinfo. The exporter itself may run as root, so hand this
    # package directory to the dedicated unprivileged build user first.
    chown -R "${build_user}:" "${package_dir}"
    runuser -u "${build_user}" -- bash -c 'cd -- "$1" && makepkg --printsrcinfo' \
      bash "${package_dir}" >"${generated}"
  else
    (cd "${package_dir}" && makepkg --printsrcinfo >"${generated}")
  fi
  install -m 0644 "${generated}" "${package_dir}/.SRCINFO"
  rm -f -- "${generated}"
}

[[ "${OUTPUT}" = /* && "${OUTPUT}" != / ]] ||
  die 'AURADE_AUR_OUTPUT must be an absolute, non-root path'
[[ "${RELEASE_TAG}" =~ ^[A-Za-z0-9._/-]+$ ]] ||
  die 'AURADE_AUR_RELEASE_TAG contains unsupported characters'
[[ "${RELEASE_ARCHIVE}" =~ ^[A-Za-z0-9._-]+$ ]] ||
  die 'AURADE_AUR_RELEASE_ARCHIVE contains unsupported characters'
[[ -n "${RELEASE_SHA256}" ]] ||
  die 'AURADE_AUR_ARCHIVE_SHA256 is required; copy the current release archive digest instead of using stale metadata'
[[ "${RELEASE_SHA256}" =~ ^[[:xdigit:]]{64}$ ]] ||
  die 'AURADE_AUR_ARCHIVE_SHA256 must be a 64-character hex digest'
[[ "${CHROMIUM_VERSION}" =~ ^[0-9]+([.][0-9]+)*$ ]] ||
  die 'AURADE_AUR_CHROMIUM_VERSION must be a numeric package version'
[[ "${CHROMIUM_PKGREL}" =~ ^[0-9]+$ ]] ||
  die 'AURADE_AUR_CHROMIUM_PKGREL must be numeric'
[[ ! -e "${OUTPUT}" ]] ||
  die "output already exists; choose another path or remove it first: ${OUTPUT}"

mkdir -p "${OUTPUT}"

copy_package() {
  local package="$1"
  local package_dir="${OUTPUT}/${package}"
  [[ -f "${REPO_ROOT}/${package}/PKGBUILD" ]] ||
    die "missing package directory: ${package}"
  mkdir -p "${package_dir}"
  cp -a "${REPO_ROOT}/${package}/." "${package_dir}/"
  local modified=0
  if (( EUID == 0 )) && command -v chown >/dev/null 2>&1; then
    local build_user="${AURADE_AUR_BUILD_USER:-aurabuild}"
    if getent passwd "${build_user}" >/dev/null; then
      chown -R "${build_user}:" "${package_dir}"
    fi
  fi

  # AUR helpers resolve dependency names before installing packages. Point
  # the generated meta/session helpers at the explicit -bin provider rather
  # than relying on a virtual provide that an AUR helper may not discover.
  case "${package}" in
    aurade)
      sed -i 's/chromiumos-ash>=/chromiumos-ash-bin>=/' \
        "${package_dir}/PKGBUILD"
      rm -f "${package_dir}/.SRCINFO"
      modified=1
      ;;
    aurade-login|aurade-webapp-shortcuts)
      sed -i "s/'chromiumos-ash'/'chromiumos-ash-bin'/g" \
        "${package_dir}/PKGBUILD"
      rm -f "${package_dir}/.SRCINFO"
      modified=1
      ;;
  esac

  if (( modified )); then
    generate_srcinfo "${package_dir}"
  fi

  find "${package_dir}" -type f -size +50M -print -quit | {
    read -r oversized || true
    [[ -z "${oversized}" ]] || die "unexpected oversized AUR input: ${oversized}"
  }
}

for package in "${SOURCE_PACKAGES[@]}"; do
  copy_package "${package}"
done

release_archive_template="${RELEASE_ARCHIVE//x86_64/\$CARCH}"
release_url_template="https://github.com/Cam396/aurade/releases/download/${RELEASE_TAG}/${release_archive_template}"
mkdir -p "${OUTPUT}/chromiumos-ash-bin"
cat >"${OUTPUT}/chromiumos-ash-bin/PKGBUILD" <<EOF
# Maintainer: AuraDE Contributors
# Generated by ci/export-aur-bundles.sh. This is the x86_64 binary AUR path.
pkgname=chromiumos-ash-bin
pkgver=${CHROMIUM_VERSION}
pkgrel=${CHROMIUM_PKGREL}
pkgdesc="Prebuilt ChromeOS Ash desktop environment for Linux (AuraDE development build)"
arch=('x86_64')
url="https://github.com/Cam396/aurade"
license=('BSD-3-Clause')
depends=(
    'shill-nm-adapter'
    'bash'
    'dbus'
    'dbus-glib'
    'util-linux'
    'python'
    'python-dbus'
    'python-gobject'
    'libgl'
    'wayland'
    'weston'
    'seatd'
    'xorg-xwayland'
    'libxkbcommon'
    'libx11'
    'libxcb'
    'libxcomposite'
    'libxdamage'
    'libxext'
    'libxfixes'
    'libxi'
    'libxrandr'
    'libxrender'
    'libxss'
    'libxtst'
    'pango'
    'cairo'
    'nss'
    'nspr'
    'alsa-lib'
    'pipewire'
    'minizip'
    'libevent'
    'libdrm'
    'mesa'
    'hwdata'
    'harfbuzz'
    'freetype2'
    'ttf-roboto'
    'libpng'
    'libjpeg-turbo'
    'tar'
    'gzip'
    'bzip2'
    'xz'
    'zstd'
    'lzip'
    '7zip'
    'unrar'
    'aurade-system-helper'
    'aurade-account-helper'
    'polkit'
    'pam'
    'shadow'
    'accountsservice'
)
optdepends=(
    'lm_sensors: userspace sensor discovery and setup tools for host hwmon devices'
    'vulkan-driver: hardware Vulkan acceleration when supported by the GPU'
    'mesa-utils: GPU smoke-test tools such as glxinfo and eglinfo'
    'aurade-ai: Advanced Plus AI local Gemma model bootstrap'
    'aurade-login: PAM greeter, lock screen, and logind session controls'
    'aurade-power: event-driven Linux laptop suspend and power lifecycle bridge'
    'aurade-host-bridge: BlueZ, udisks2, MIME, and pacman host integration'
    'udiskie: opt-in recovery automounter when AURADE_REMOVABLE_AUTOMOUNT=1'
)
provides=("chromiumos-ash=\${pkgver}-\${pkgrel}")
conflicts=('chromiumos-ash')
source=("aurade-repository.tar.gz::${release_url_template}")
sha256sums=('${RELEASE_SHA256}')

package() {
    local -a payloads=()
    while IFS= read -r payload; do
        payloads+=("\$payload")
    done < <(find "\${srcdir}/repository" -maxdepth 1 -type f \\
        -name "chromiumos-ash-\${pkgver}-\${pkgrel}-\${CARCH}.pkg.tar.*" \\
        ! -name '*.sig' -print)
    if (( \${#payloads[@]} != 1 )); then
        printf 'expected exactly one Chromium payload in release archive, found %s\\n' \\
            "\${#payloads[@]}" >&2
        return 1
    fi
    local payload="\${payloads[0]}"
    bsdtar --exclude='.BUILDINFO' --exclude='.MTREE' --exclude='.PKGINFO' \\
        --no-same-owner -xpf "\${payload}" -C "\${pkgdir}"
}
EOF

if (( EUID == 0 )) && command -v chown >/dev/null 2>&1; then
  build_user="${AURADE_AUR_BUILD_USER:-aurabuild}"
  if getent passwd "${build_user}" >/dev/null; then
    chown -R "${build_user}:" "${OUTPUT}/chromiumos-ash-bin"
  fi
fi
generate_srcinfo "${OUTPUT}/chromiumos-ash-bin"

commit="$(git -C "${REPO_ROOT}" rev-parse --short=12 HEAD 2>/dev/null || printf unknown)"
cat >"${OUTPUT}/AUR-EXPORT.md" <<EOF
# AuraDE AUR export

Generated from AuraDE commit ${commit}.

The directories below are intentionally self-contained because the AUR uses
one Git repository per package. Upload each package directory to its own AUR
repository only after the current VM/hardware feedback is accepted.

The chromiumos-ash-bin package is the current x86_64 development path. It
downloads the unsigned Chromium payload from the GitHub release
${RELEASE_TAG} and verifies SHA-256 ${RELEASE_SHA256}. It provides
chromiumos-ash for manual installs; generated AUR meta/session packages use
the explicit chromiumos-ash-bin dependency so AUR helpers resolve it.
There is no ARM binary claim.

When an unprivileged Arch build user and \`makepkg\` are available, the exporter
regenerates \`.SRCINFO\` for transformed/generated packages. Otherwise, run
\`makepkg --printsrcinfo\` as an unprivileged Arch user before upload. In every
case, run \`namcap PKGBUILD\` and \`makepkg --verifysource\` in every directory.
Do not upload the parent repository, private engineering documents, VM
credentials, build logs, ISO files, or package archives to an AUR package repo.
EOF

printf 'AUR bundles exported to %s\n' "${OUTPUT}"
printf 'Packages: %s plus chromiumos-ash-bin\n' "${#SOURCE_PACKAGES[@]}"
