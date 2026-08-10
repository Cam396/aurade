#!/bin/bash
# build-chromeos-ash.sh — CI/CD pipeline for ChromiumOS Ash Arch packaging
#
# Orchestrates: depot_tools sync → patch → gn → ninja → package
#
# Usage:
#   ./build-chromeos-ash.sh prepare   # sync source + apply patches
#   ./build-chromeos-ash.sh build     # gn → ninja → package
#   ./build-chromeos-ash.sh all       # prepare + build (default)
#
# Environment variables:
#   CHROMIUMOS_DIR   ChromiumOS source root   (default: $PWD/src)
#   DEPOT_TOOLS_DIR  depot_tools checkout     (default: $PWD/depot_tools)
#   OUTPUT_DIR       gn/ninja output dir      (default: $CHROMIUMOS_DIR/out/Ash)
#   JOBS             ninja -j                 (default: $(nproc))
#
# This script is designed for CI/CD (GitHub Actions, Jenkins, etc.) but also
# works locally. Requires ~50 GB free disk and 2-4 hours build time.
#
# Arch Extra packaging:
#   After 'build', the 'package/' directory contains the staged Arch package
#   tree. Run 'makepkg --repackage' from the chromiumos-ash/ directory.
#
set -euo pipefail

# ── Config ───────────────────────────────────────────────────────────────────

export CHROMIUMOS_DIR="${CHROMIUMOS_DIR:-${PWD}/chromiumos}"
export DEPOT_TOOLS_DIR="${DEPOT_TOOLS_DIR:-${PWD}/depot_tools}"
export OUTPUT_DIR="${OUTPUT_DIR:-${CHROMIUMOS_DIR}/src/out/Ash}"
JOBS="${JOBS:-$(nproc)}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCH_DIR="${SCRIPT_DIR}/patches"
PKG_DIR="${SCRIPT_DIR}/chromiumos-ash"
STAGEDIR="${SCRIPT_DIR}/package-staging"

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BUILD_LOG="${SCRIPT_DIR}/build-${TIMESTAMP}.log"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ── Prerequisites ──────────────────────────────────────────────────────────────

check_prereqs() {
    local missing=()
    for cmd in git python3 ninja gn pkg-config; do
        if ! command -v "$cmd" &>/dev/null; then
            missing+=("$cmd")
        fi
    done
    if [ "${#missing[@]}" -gt 0 ]; then
        error "Missing required tools: ${missing[*]}"
        echo "Install them:"
        echo "  sudo pacman -S git python ninja gn pkgconf base-devel"
        exit 1
    fi
}

# ── Step 1: Sync source ────────────────────────────────────────────────────────

prepare_source() {
    info "Step 1/4: Syncing ChromiumOS source..."

    mkdir -p "${CHROMIUMOS_DIR}"
    cd "${CHROMIUMOS_DIR}"

    # Install depot_tools if needed
    if [ ! -d "${DEPOT_TOOLS_DIR}" ]; then
        info "Cloning depot_tools..."
        git clone --depth=1 \
            https://chromium.googlesource.com/chromium/tools/depot_tools.git \
            "${DEPOT_TOOLS_DIR}"
    fi
    export PATH="${DEPOT_TOOLS_DIR}:${PATH}"

    # Create .gclient file if needed
    if [ ! -f "${CHROMIUMOS_DIR}/src/.gclient" ]; then
        mkdir -p "${CHROMIUMOS_DIR}/src"
        cd "${CHROMIUMOS_DIR}/src"
        info "Running gclient config..."
        # Use the public ChromiumOS manifest
        gclient config --name=src \
            https://chromium.googlesource.com/chromiumos/manifest.git \
            --custom-var="checkout_sdk=false" \
            --custom-var="checkout_recovery_initramfs=false" \
            --custom-var="checkout_test_images=false"
    fi

    # Sync (this downloads the ~10 GB source tree)
    cd "${CHROMIUMOS_DIR}"
    info "Syncing with gclient sync (this may take a while)..."
    gclient sync --with_branch_heads --nohooks 2>&1 | tee -a "${BUILD_LOG}"
    cd "${CHROMIUMOS_DIR}/src"

    # Run hooks (needed for GN)
    info "Running gclient runhooks..."
    gclient runhooks 2>&1 | tee -a "${BUILD_LOG}"

    info "Source preparation complete."
}

# ── Step 2: Apply patches ─────────────────────────────────────────────────────

apply_patches() {
    info "Step 2/4: Applying ChromiumOS Ash patches..."

    local src_dir="${CHROMIUMOS_DIR}/src"

    # Collect patch files. Prefer an explicit series file so CI applies the
    # same patch order across shells and future patch renames.
    local patches=()
    if [ -f "${PATCH_DIR}/SERIES" ]; then
        local patch_entry
        while IFS= read -r patch_entry; do
            [[ -z "${patch_entry}" || "${patch_entry}" == \#* ]] && continue
            patches+=("${PATCH_DIR}/${patch_entry}")
        done < "${PATCH_DIR}/SERIES"
    else
        local p
        for p in "${PATCH_DIR}"/*.patch; do
            [ -f "$p" ] && patches+=("$p")
        done
    fi

    if [ "${#patches[@]}" -eq 0 ]; then
        info "No patches to apply."
        return
    fi

    cd "${src_dir}"
    for patch_file in "${patches[@]}"; do
        if [ ! -f "${patch_file}" ]; then
            error "Patch listed but not found: ${patch_file}"
            exit 1
        fi
        info "  Applying $(basename "${patch_file}")..."
        if git apply --index "${patch_file}" 2>/dev/null || \
           patch -p1 -N < "${patch_file}" 2>/dev/null; then
            info "    ✓ $(basename "${patch_file}")"
        else
            warn "    ${patch_file} may already be applied — skipping."
        fi
    done
}

# ── Step 3: Build ──────────────────────────────────────────────────────────────

build_chrome() {
    info "Step 3/4: Building ChromeOS Ash..."

    local src_dir="${CHROMIUMOS_DIR}/src"

    if [ ! -d "${src_dir}" ]; then
        error "Source not found at ${src_dir}. Run 'prepare' first."
        exit 1
    fi

    cd "${src_dir}"

    # Configure GN
    info "Configuring GN (target_os=\"chromeos\", Ozone X11/Wayland/DRM)..."
    gn gen "${OUTPUT_DIR}" --args="
        target_os = \"chromeos\"
        is_debug = false
        is_component_build = false
        is_official_build = false
        symbol_level = 0
        use_ozone = true
        ozone_platform_wayland = true
        enable_rust = true
    " 2>&1 | tee -a "${BUILD_LOG}"

    # Build chrome binary and setuid sandbox helper.
    info "Running ninja (targets: chrome chrome_sandbox, jobs: ${JOBS})..."
    info "This will take 2-4 hours..."
    ninja -C "${OUTPUT_DIR}" -j"${JOBS}" chrome chrome_sandbox 2>&1 | tee -a "${BUILD_LOG}"

    # Verify the binary
    if [ ! -f "${OUTPUT_DIR}/chrome" ]; then
        error "Build failed — chrome binary not found at ${OUTPUT_DIR}/chrome"
        exit 1
    fi

    local size
    size=$(stat -c%s "${OUTPUT_DIR}/chrome" 2>/dev/null || stat -f%z "${OUTPUT_DIR}/chrome" 2>/dev/null)
    local md5
    md5=$(md5sum "${OUTPUT_DIR}/chrome" | cut -d' ' -f1)
    info "Build complete — chrome: ${size} bytes, md5: ${md5}"
}

# ── Step 4: Package ────────────────────────────────────────────────────────────

package_chrome() {
    info "Step 4/4: Staging Arch package..."

    rm -rf "${STAGEDIR}"
    mkdir -p "${STAGEDIR}/usr/lib/chromiumos-ash"
    mkdir -p "${STAGEDIR}/usr/bin"
    mkdir -p "${STAGEDIR}/etc/aurade"

    # Install chrome binary
    install -m755 "${OUTPUT_DIR}/chrome" \
        "${STAGEDIR}/usr/lib/chromiumos-ash/chrome"

    # Install resources
    for dir in resources locales; do
        if [ -d "${OUTPUT_DIR}/${dir}" ]; then
            cp -r "${OUTPUT_DIR}/${dir}" "${STAGEDIR}/usr/lib/chromiumos-ash/"
        fi
    done

    # Install launcher scripts
    install -m755 "${PKG_DIR}/chromiumos-ash.sh" \
        "${STAGEDIR}/usr/bin/chromiumos-ash"

    # Install session entry
    install -Dm644 "${PKG_DIR}/chromiumos-ash.desktop" \
        "${STAGEDIR}/usr/share/wayland-sessions/chromiumos-ash.desktop"

    # Install feature defaults.
    install -Dm644 "${PKG_DIR}/aurade.features.conf" \
        "${STAGEDIR}/etc/aurade/features.conf"

    # Compute package metadata
    local size
    size=$(du -sh "${STAGEDIR}" | cut -f1)
    info "Package staged at ${STAGEDIR} (${size})"

    # Optionally build the Arch package
    if command -v makepkg &>/dev/null; then
        info "Building Arch package with makepkg..."
        mkdir -p "${PKG_DIR}/pkg/chromiumos-ash"
        cp -r "${STAGEDIR}/." "${PKG_DIR}/pkg/chromiumos-ash/"
        cd "${PKG_DIR}"
        PKGEXT='.pkg.tar.zst' makepkg --repackage --clean 2>&1 | tee -a "${BUILD_LOG}"
        info "Package built: $(find "${PKG_DIR}" -name '*.pkg.tar.zst' -print)"
    else
        info "makepkg not found — package staged at ${STAGEDIR}"
    fi
}

# ── Verification ────────────────────────────────────────────────────────────────

verify() {
    info "Verifying build..."

    local binary="${OUTPUT_DIR}/chrome"
    if [ ! -f "${binary}" ]; then
        error "Binary not found — build may have failed"
        return 1
    fi

    # Verify it's an ELF executable
    file "${binary}" | grep -q ELF || {
        error "Binary is not an ELF file"
        return 1
    }

    # Verify it links (dry-run)
    if ldd "${binary}" &>/dev/null; then
        info "Dynamic linking: OK"
    else
        warn "ldd failed — may be statically linked or have missing deps"
    fi

    info "Verification passed."
}

# ── Command dispatch ───────────────────────────────────────────────────────────

cmd_prepare() {
    check_prereqs
    prepare_source
    apply_patches
}

cmd_build() {
    check_prereqs
    build_chrome
    verify
    package_chrome
}

cmd_all() {
    cmd_prepare
    cmd_build
}

# ── Main ───────────────────────────────────────────────────────────────────────

mkdir -p "$(dirname "${BUILD_LOG}")"

case "${1:-all}" in
    prepare)
        cmd_prepare
        ;;
    build)
        cmd_build
        ;;
    all)
        cmd_all
        ;;
    verify)
        verify
        ;;
    *)
        echo "Usage: $0 {prepare|build|all|verify}"
        echo ""
        echo "  prepare   Sync ChromiumOS source and apply patches"
        echo "  build     Build chrome binary and stage Arch package"
        echo "  all       prepare + build (default)"
        echo "  verify    Check the built binary"
        exit 1
        ;;
esac

info "Done."
