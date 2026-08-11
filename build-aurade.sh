#!/usr/bin/env bash
# AuraDE low-effort build orchestrator.
#
# The supported binary path is x86_64 on an Arch host. ARM64 and other
# architectures run the source/bootstrap/patch path and stop before producing
# an untested binary or ISO.
set -Eeuo pipefail

PROGRAM=${0##*/}
SCRIPT_DIR=$(cd -- "$(dirname -- "$0")" && pwd -P)
REPO_ROOT=$SCRIPT_DIR
REPO_URL=${AURADE_REPO_URL:-https://github.com/Cam396/aurade.git}
REPO_REF=${AURADE_REPO_REF:-main}
WORKDIR=${AURADE_WORKDIR:-${XDG_CACHE_HOME:-${HOME}/.cache}/aurade}
TARGET_ARCH=${AURADE_TARGET_ARCH:-$(uname -m)}
JOBS=${AURADE_BOOTSTRAP_JOBS:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || printf 4)}
NO_DEPS=0
SOURCE_ONLY=0
DO_BUILD=0
DO_ISO=0
DO_TEST=0
ACTION_REQUESTED=0
PLAN_ONLY=0
REUSE_CHROMIUM=0
START_VM=0
VMX=
VM_HOST=${AURADE_VM_HOST:-}
INSTALLER_SNAPSHOT=${AURADE_ARCH_SNAPSHOT:-$(date -u +%Y/%m/%d)}

usage() {
  cat <<'EOF'
Usage: ./build-aurade.sh [options]

The default builds the packages. Use --all for packages plus an ISO. The
script may be run from a cloned AuraDE checkout or as a copied standalone
script; in the latter case it clones the public repository into the workdir.

Actions:
  --all                 Build the packages and then a package-locked ISO.
  --source-only         Clone/bootstrap Chromium and verify patches only.
  --packages            Build the complete 11-package repository (default).
  --iso                 Build an ISO from the verified local repository.
  --test                Run the complete VM smoke matrix after the build.
  --plan                Print the workflow without cloning, installing, or building.

Options:
  --repo URL            AuraDE repository to clone when not already in a repo.
  --ref REF             Branch, tag, or ref to clone. Default: main.
  --workdir DIR         State/cache/artifact directory outside the checkout.
  --arch ARCH           Target architecture (x86_64, aarch64, arm64, ...).
  --jobs N              Chromium bootstrap parallelism. Default: CPU count.
  --reuse-chromium      Reuse only the exact current Chromium package artifact.
  --no-deps             Do not install host dependencies automatically.
  --vmx FILE             VMware .vmx file to start before --test.
  --vm-host HOST        Guest address for --test (or AURADE_VM_HOST).
  --help                Show this help.

Environment:
  AURADE_WORKDIR        Persistent state directory, kept outside Git.
  AURADE_CHROMIUM_REVISION  Overrides pins/chromium.sha for an experiment.
  AURADE_REPO_KEY       Public repository key for signed ISO builds.
  AURADE_REPO_FINGERPRINT  Full fingerprint for signed ISO builds.
  AURADE_ALLOW_UNSIGNED=1  Permit a development-only unsigned ISO.

Architecture policy:
  x86_64 + Arch Linux: full packages/repository/ISO path.
  aarch64/arm64/other: source bootstrap and patch verification only. The
  chromiumos-ash recipe and release orchestrator are currently x86_64-only;
  the script refuses to pretend an ARM binary is tested.
EOF
}

die() {
  printf '%s: %s\n' "$PROGRAM" "$*" >&2
  exit 1
}

log() {
  printf '[%s] %s\n' "$PROGRAM" "$*"
}

warn() {
  printf '[%s] WARNING: %s\n' "$PROGRAM" "$*" >&2
}

as_root() {
  if [[ $(id -u) -eq 0 ]]; then
    "$@"
  else
    command -v sudo >/dev/null 2>&1 || die 'root privileges or sudo are required'
    sudo "$@"
  fi
}

as_root_env() {
  if [[ $(id -u) -eq 0 ]]; then
    env "$@"
  else
    command -v sudo >/dev/null 2>&1 || die 'root privileges or sudo are required'
    sudo env "$@"
  fi
}

have() {
  command -v "$1" >/dev/null 2>&1
}

is_arch_host() {
  [[ -f /etc/arch-release ]] && have pacman
}

canonical_arch() {
  case "$1" in
    x86_64|amd64) printf x86_64 ;;
    aarch64|arm64) printf aarch64 ;;
    armv7l|armv7) printf armv7l ;;
    riscv64) printf riscv64 ;;
    *) printf '%s' "$1" ;;
  esac
}

install_dependencies() {
  (( NO_DEPS )) && return

  if is_arch_host; then
    log 'installing Arch host dependencies'
    as_root pacman -S --needed --noconfirm \
      base-devel bubblewrap git curl rsync sudo python ninja gn clang lld \
      bison flex gperf nodejs python-pip patch shellcheck shfmt namcap \
      pacman-contrib devtools arch-install-scripts openssh
    return
  fi

  if have apt-get; then
    if (( DO_BUILD || DO_ISO )); then
      die 'package/ISO builds require an Arch host or Arch validation environment; use --source-only on this host'
    fi
    log 'installing source-bootstrap dependencies with apt'
    as_root apt-get update
    as_root apt-get install -y git curl rsync python3 python3-venv ninja-build \
      clang lld bison flex gperf nodejs npm patch openssh-client
    return
  fi

  die 'unsupported host: install Git, curl, rsync, Python, and an Arch build environment first'
}

locate_repo() {
  if [[ -f "$REPO_ROOT/pins/chromium.sha" && -d "$REPO_ROOT/patches" ]]; then
    return
  fi

  local clone_dir="$WORKDIR/source"
  mkdir -p "$WORKDIR"
  if [[ ! -d "$clone_dir/.git" ]]; then
    log 'cloning AuraDE source into a private work directory'
    if [[ "$REPO_REF" =~ ^[0-9a-fA-F]{40}$ ]]; then
      git clone --filter=blob:none "$REPO_URL" "$clone_dir"
      git -C "$clone_dir" fetch --depth=1 origin "$REPO_REF"
      git -C "$clone_dir" checkout --detach "$REPO_REF"
    else
      git clone --depth=1 --branch "$REPO_REF" "$REPO_URL" "$clone_dir"
    fi
  fi
  REPO_ROOT=$clone_dir
}

prepare_depot_tools() {
  local depot_tools=${AURADE_DEPOT_TOOLS:-$WORKDIR/depot_tools}
  if [[ ! -x "$depot_tools/gclient" ]]; then
    log 'cloning Chromium depot_tools'
    mkdir -p "$(dirname "$depot_tools")"
    git clone --depth=1 https://chromium.googlesource.com/chromium/tools/depot_tools.git "$depot_tools"
  fi
  printf '%s\n' "$depot_tools"
}

prepare_chromium() {
  local pin=${AURADE_CHROMIUM_REVISION:-}
  [[ -n "$pin" ]] || pin=$(tr -d '[:space:]' < "$REPO_ROOT/pins/chromium.sha")
  [[ "$pin" =~ ^[0-9a-fA-F]{40}$ ]] || die 'Chromium pin must be a 40-character Git SHA'

  local target="$WORKDIR/chromium-bootstrap"
  local chrome_src="$target/src"
  local depot_tools
  depot_tools=$(prepare_depot_tools)

  if [[ -d "$chrome_src/.git" ]] &&
     [[ $(git -C "$chrome_src" rev-parse HEAD) == "$pin" ]]; then
    log "reusing Chromium checkout at $pin"
    CHROME_SRC="$chrome_src" AURADE_WORKDIR="$WORKDIR" \
      "$REPO_ROOT/ci/verify-patch-series.sh"
  else
    log "bootstrapping Chromium at $pin; the first sync is large"
    AURADE_DEPOT_TOOLS="$depot_tools" AURADE_BOOTSTRAP_JOBS="$JOBS" \
      "$REPO_ROOT/ci/bootstrap-chromium-src.sh" \
      --revision "$pin" --target "$target" --run --verify-series
  fi
  CHROME_SRC=$chrome_src
  export CHROME_SRC
}

run_installer_tests() {
  log 'running installer dry-run, ISO staging, and recovery tests'
  bash "$REPO_ROOT/installer/tests/run.sh"
}

build_packages() {
  [[ $(canonical_arch "$TARGET_ARCH") == x86_64 ]] || {
    die "binary/package builds are currently x86_64-only; source preparation succeeded for ${TARGET_ARCH}"
  }
  is_arch_host || die 'full package builds require an Arch host; use an Arch VM/container or --source-only'

  log 'bootstrapping the Arch validation root'
  as_root_env AURADE_WORKDIR="$WORKDIR" "$REPO_ROOT/ci/bootstrap-arch-root.sh"

  if (( REUSE_CHROMIUM )); then
    log 'building small packages and reusing the exact Chromium artifact'
    as_root_env CHROME_SRC="$CHROME_SRC" AURADE_WORKDIR="$WORKDIR" \
      "$REPO_ROOT/ci/build-release-candidate.sh" --reuse-chromium
  else
    log 'building Chromium and the complete 11-package repository'
    as_root_env CHROME_SRC="$CHROME_SRC" AURADE_WORKDIR="$WORKDIR" \
      "$REPO_ROOT/ci/build-release-candidate.sh"
  fi
}

build_iso() {
  local repo_dir="$WORKDIR/private-repo"
  [[ -d "$repo_dir" ]] || die "verified package repository missing: $repo_dir"
  local allow_unsigned=${AURADE_ALLOW_UNSIGNED:-}
  if [[ -z "$allow_unsigned" ]]; then
    if [[ -n "${AURADE_REPO_KEY:-}" && -n "${AURADE_REPO_FINGERPRINT:-}" ]]; then
      allow_unsigned=0
    else
      allow_unsigned=1
      warn 'building a development-only unsigned ISO; provide a public key and fingerprint for a signed image'
    fi
  fi

  log "building package-locked ISO for Arch snapshot $INSTALLER_SNAPSHOT"
  as_root_env \
    AURADE_ARCH_SNAPSHOT="$INSTALLER_SNAPSHOT" \
    AURADE_REPO_DIR="$repo_dir" \
    AURADE_REPO_URL="${AURADE_REPO_URL:-file:///var/cache/aurade/repo}" \
    AURADE_ALLOW_UNSIGNED="$allow_unsigned" \
    AURADE_INSTALLER_WORK_ROOT="$WORKDIR/installer" \
    "$REPO_ROOT/installer/build-iso.sh"
}

run_vm_tests() {
  [[ -n "$VM_HOST" ]] || die '--test requires --vm-host or AURADE_VM_HOST'
  if (( START_VM )); then
    [[ -n "$VMX" ]] || die '--vmx is required when starting a VM'
    have vmrun || die 'vmrun is required for --vmx'
    log 'starting the VM through vmrun'
    vmrun -T ws start "$VMX" nogui
  fi
  log 'running the complete VM smoke matrix'
  AURADE_VM_HOST="$VM_HOST" "$REPO_ROOT/ci/vm-smoke.sh" \
    --open-core-apps --open-audio-settings --session-lifecycle-smoke \
    --release-package-smoke --files-ops-smoke --files-archive-smoke \
    --terminal-smoke --accessibility-smoke
}

while (($#)); do
  case "$1" in
    --all) ACTION_REQUESTED=1; DO_BUILD=1; DO_ISO=1; shift ;;
    --source-only) ACTION_REQUESTED=1; SOURCE_ONLY=1; DO_BUILD=0; DO_ISO=0; shift ;;
    --packages) ACTION_REQUESTED=1; DO_BUILD=1; shift ;;
    --iso) ACTION_REQUESTED=1; DO_ISO=1; shift ;;
    --test) ACTION_REQUESTED=1; DO_TEST=1; shift ;;
    --plan) PLAN_ONLY=1; shift ;;
    --repo) REPO_URL=${2:?}; shift 2 ;;
    --ref) REPO_REF=${2:?}; shift 2 ;;
    --workdir) WORKDIR=${2:?}; shift 2 ;;
    --arch) TARGET_ARCH=${2:?}; shift 2 ;;
    --jobs) JOBS=${2:?}; shift 2 ;;
    --reuse-chromium) REUSE_CHROMIUM=1; shift ;;
    --no-deps) NO_DEPS=1; shift ;;
    --vmx) VMX=${2:?}; START_VM=1; shift 2 ;;
    --vm-host) VM_HOST=${2:?}; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1 (use --help)" ;;
  esac
done

[[ "$WORKDIR" = /* && "$WORKDIR" != / ]] || die '--workdir must be an absolute, non-root path'
(( ACTION_REQUESTED )) || DO_BUILD=1
if (( PLAN_ONLY )); then
  log "repository: $REPO_URL ($REPO_REF)"
  log "workdir: $WORKDIR"
  log "target architecture: $(canonical_arch "$TARGET_ARCH")"
  log "actions: build=$DO_BUILD iso=$DO_ISO test=$DO_TEST source_only=$SOURCE_ONLY"
  log "dependency installation: $((NO_DEPS ? 0 : 1))"
  exit 0
fi
mkdir -p "$WORKDIR"
TARGET_ARCH=$(canonical_arch "$TARGET_ARCH")
locate_repo
install_dependencies
run_installer_tests
prepare_chromium

if (( SOURCE_ONLY )); then
  log "source preparation complete for $TARGET_ARCH"
elif [[ "$TARGET_ARCH" != x86_64 ]]; then
  warn "${TARGET_ARCH} is experimental: stopping after source/patch verification; no binary or ISO was produced"
elif (( DO_BUILD )); then
  build_packages
fi

if (( DO_ISO )); then
  [[ "$TARGET_ARCH" == x86_64 ]] || die '--iso is currently supported only for x86_64'
  (( DO_BUILD )) || warn 'building ISO from an existing repository; no package build was requested'
  build_iso
fi

if (( DO_TEST )); then
  run_vm_tests
fi

log 'AuraDE AIO workflow complete'
