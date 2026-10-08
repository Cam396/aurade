#!/usr/bin/env bash
# One entry point for every CI job.
#
# The workflow names these jobs and nothing else, so a run on this machine and
# a run on the GitHub runner do the same work. Before this, the workflow held
# its own copy of each check, and a check could pass here and fail there with
# nobody able to say which copy was wrong.
#
#   ci/run.sh lint            syntax, workflow lint, action runtimes, patch series,
#                             metadata, whitespace
#   ci/run.sh gates           release identity, source integrity, leak and docs gates
#   ci/run.sh installer [I/N] the installer suite, or shard I of N
#   ci/run.sh fixtures        ci/tests and the component tests
#   ci/run.sh packages        build, check and install the Arch packages in a clean
#                             Arch container (docker or podman)
#   ci/run.sh fast            lint and gates, which is what the pre-push hook runs
#   ci/run.sh changes BASE    whether anything since BASE affects the packages
#   ci/run.sh hosted          check the published pacman repository as pacman sees it
#   ci/run.sh drift           install the published packages on today's Arch and
#                             check every library and module they need still resolves
#   ci/run.sh setup-ubuntu    the distribution packages the Ubuntu jobs need
#   ci/run.sh install-hooks   use ci/hooks for this clone
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
cd "$ROOT"

# The package job's base image, by digest so a new upload under the same tag
# cannot change what CI tests. Packages then come from the Arch archive at the
# same snapshot the ISO installs from.
ARCH_IMAGE=docker.io/library/archlinux:base-devel@sha256:51dd3d24f7fba779e7c471caeee7804c50e8c134ad948e19685a1c83a42facc3
ARCH_SNAPSHOT=$(<"$ROOT/pins/arch.snapshot")
ACTIONLINT_VERSION=1.7.12
ACTIONLINT_SHA256=8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8

# The packages CI builds. chromiumos-ash needs a Chromium build, auradefs a
# Rust toolchain and the Files page, and aurade-wallpapers the staged images,
# so those three are left to the release build on the build machine.
CI_PACKAGES=(
  aurade-account-helper aurade-system-helper shill-nm-adapter aurade-power
  aurade-hardware aurade-host-bridge aurade-login aurade-greeter aurade-ai
  aurade-webapp-shortcuts aurade aurade-full
)
# The subset that installs without chromiumos-ash in a repository. The
# login and greeter packages depend on it, so their check() is what covers them.
CI_INSTALLABLE=(
  aurade-account-helper aurade-system-helper shill-nm-adapter aurade-power
  aurade-hardware aurade-host-bridge
)

group() {
  if [[ -n ${GITHUB_ACTIONS:-} ]]; then
    printf '::group::%s\n' "$*"
  else
    printf '\n== %s\n' "$*"
  fi
}
endgroup() {
  [[ -z ${GITHUB_ACTIONS:-} ]] || printf '::endgroup::\n'
}
die() {
  printf 'ci/run.sh: %s\n' "$*" >&2
  exit 1
}
as_root() {
  if (( EUID == 0 )); then "$@"; else sudo "$@"; fi
}

UBUNTU_PACKAGES=(libarchive-tools squashfs-tools gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-glib-2.0 libspa-0.2-dev)
job_setup_ubuntu() {
  group 'distribution packages'
  local -a missing=()
  local pkg
  for pkg in "${UBUNTU_PACKAGES[@]}"; do
    dpkg-query -W -f '${Status}' "$pkg" 2>/dev/null | grep -q 'ok installed' || missing+=("$pkg")
  done
  if (( ${#missing[@]} )); then
    # man-db rebuilds its index after every install, which is most of the
    # time an install takes on a runner. The package lists the runner image
    # ships are usually fresh enough; update them only if the install fails.
    as_root rm -f /var/lib/man-db/auto-update
    as_root apt-get install -y -q --no-install-recommends "${missing[@]}" ||
      { as_root apt-get update -q && as_root apt-get install -y -q --no-install-recommends "${missing[@]}"; }
  fi
  echo "installed: ${UBUNTU_PACKAGES[*]}"
  endgroup
}

fetch_actionlint() {
  local cache=${XDG_CACHE_HOME:-$HOME/.cache}/aurade-ci/actionlint-$ACTIONLINT_VERSION
  local tarball="$cache/actionlint.tar.gz"
  if [[ ! -x $cache/actionlint ]]; then
    mkdir -p "$cache"
    curl -fsSL -o "$tarball" \
      "https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/actionlint_${ACTIONLINT_VERSION}_linux_amd64.tar.gz"
    printf '%s  %s\n' "$ACTIONLINT_SHA256" "$tarball" | sha256sum -c --quiet - ||
      die 'the actionlint download does not match its pinned checksum'
    tar -xzf "$tarball" -C "$cache" actionlint
    rm -f "$tarball"
  fi
  printf '%s\n' "$cache/actionlint"
}

job_lint() {
  local file

  group 'shell syntax'
  while IFS= read -r -d '' file; do
    bash -n "$file"
  done < <(git ls-files -z -- '*.sh')
  endgroup

  group 'python syntax'
  git ls-files -z -- '*.py' | python3 -B -c '
import sys
paths = [p for p in sys.stdin.read().split("\0") if p]
for path in paths:
    with open(path, encoding="utf-8") as handle:
        compile(handle.read(), path, "exec")
print(f"{len(paths)} python files compile")
'
  endgroup

  group 'workflow lint'
  "$(fetch_actionlint)" -color .github/workflows/*.yml
  endgroup

  # GitHub retires JavaScript action runtimes on a schedule (Node 20 went in
  # 2026) and only warns on the runs that still use one. Every action is
  # pinned by commit, so its action.yml at that commit says exactly which
  # runtime it needs; anything older than node24 fails here instead.
  group 'action runtimes'
  local ref using count=0
  while IFS= read -r ref; do
    using=$(curl -fsSL "https://raw.githubusercontent.com/${ref%@*}/${ref#*@}/action.yml" |
      python3 -c 'import sys, yaml; print(yaml.safe_load(sys.stdin)["runs"]["using"])') ||
      die "could not read the runtime from action.yml for ${ref}"
    case $using in
      node2[4-9]|node[3-9][0-9]|composite|docker) ;;
      *) die "${ref} runs on '${using:-unknown}'; pin a release that runs on node24 or later" ;;
    esac
    printf '%s: %s\n' "$ref" "$using"
    count=$((count + 1))
  done < <(sed -n 's/^[[:space:]]*-\{0,1\}[[:space:]]*uses:[[:space:]]*\([^ #]*@[0-9a-f]\{40\}\).*/\1/p' .github/workflows/*.yml | sort -u)
  (( count > 0 )) || die 'found no pinned actions to check'
  # A tag or branch reference would let the runtime change under the pin.
  ! grep -nE '^[[:space:]]*-?[[:space:]]*uses:[[:space:]]*[^ #]+@' .github/workflows/*.yml |
    grep -vE '@[0-9a-f]{40}([[:space:]]|$)' || die 'the action above is not pinned by a full commit hash'
  endgroup

  group 'patch series manifest'
  local -a patches
  mapfile -t patches < <(sed '/^[[:space:]]*#/d;/^[[:space:]]*$/d' patches/SERIES)
  (( ${#patches[@]} > 0 )) || die 'patches/SERIES lists no patches'
  for file in "${patches[@]}"; do
    [[ -f patches/$file ]] || die "patches/SERIES names a missing patch: $file"
  done
  [[ $(printf '%s\n' "${patches[@]}" | sort -u | wc -l) -eq ${#patches[@]} ]] ||
    die 'patches/SERIES names a patch twice'
  printf '%s patches, all present, none repeated\n' "${#patches[@]}"
  endgroup

  group 'package metadata'
  while IFS= read -r file; do
    [[ -f $file/PKGBUILD && -f $file/.SRCINFO ]] || die "$file is missing PKGBUILD or .SRCINFO"
  done <installer/expected-packages.txt
  endgroup

  # Patch files carry diff context, where a blank line is a single space, so
  # they are left out. The rest is checked against the commit before this one
  # and against anything not yet committed.
  group 'whitespace'
  if git rev-parse -q --verify HEAD^ >/dev/null; then
    git diff --check HEAD^ HEAD -- . ':!patches/*.patch'
  fi
  git diff --check HEAD -- . ':!patches/*.patch'
  endgroup
}

job_gates() {
  group 'release identity'; ci/verify-release-identity.sh; endgroup
  group 'source integrity'; ci/source-integrity-gate.sh; endgroup
  group 'public release leak gate'; ci/public-release-leak-gate.sh; endgroup
  group 'public documentation gate'; ci/public-docs-gate.sh; endgroup
}

job_installer() {
  local shard=${1:-}
  AURADE_TEST_SHARD=$shard installer/tests/run.sh
}

job_fixtures() {
  group 'ci/tests'; ci/tests/run.sh; endgroup
  group 'host bridge'; aurade-host-bridge/run-tests.sh; endgroup
  group 'NetworkManager adapter'; python3 -B shill-nm-adapter/test_shill_nm_adapter.py; endgroup
  group 'aurade-vm'; vm/aurade-vm/test.sh; endgroup
  group 'launcher'
  bash chromiumos-ash/test-session-error.sh chromiumos-ash/aurade-session-error
  bash chromiumos-ash/test-local-account-flags.sh
  bash chromiumos-ash/test-google-api-config.sh
  endgroup
}

# Whether a change could affect the Arch packages, for the workflow to decide
# whether the slow package job runs. Anything it cannot compare against, a new
# branch or a missing commit, counts as yes.
PACKAGE_PATHS='^(aurade[^/]*|shill-nm-adapter|chromiumos-ash)/|^installer/wallpapers/|^ci/(run|arch-package-smoke|build-private-repo)\.sh$|^pins/arch\.snapshot$|^\.github/workflows/'
job_changes() {
  local base=${1:-} packages=true
  if [[ -n $base && ! $base =~ ^0+$ ]] && git cat-file -e "${base}^{commit}" 2>/dev/null; then
    if ! git diff --name-only "$base" HEAD | grep -qE "$PACKAGE_PATHS"; then
      packages=false
    fi
  fi
  echo "packages=$packages"
  [[ -z ${GITHUB_OUTPUT:-} ]] || echo "packages=$packages" >>"$GITHUB_OUTPUT"
}

job_fast() {
  job_lint
  job_gates
}

# The published repository is outside this tree, so a push cannot break it
# and a pull request cannot fix it. It runs on its own schedule instead of
# gating changes, and fails loudly when what is served stops matching.
job_hosted() {
  group 'hosted pacman repository'; ci/release.sh check-repo; endgroup
}

# Installed machines update Arch from the live mirrors, but the packages were
# built against the snapshot in pins/arch.snapshot. When Arch moves a library
# on (an ICU or Python bump is the usual one), a machine that runs
# `pacman -Syu` can be left with a desktop that will not start, and nothing in
# this tree changed. This installs what is published onto today's Arch, in a
# container that is deliberately not pinned, and fails on anything that no
# longer resolves, so the rebuild happens before somebody's update.
DRIFT_IMAGE=docker.io/library/archlinux:base-devel
HOSTED_REPO=https://github.com/Cam396/aurade/releases/download/repo-x86_64
job_drift() {
  if [[ -n ${AURADE_IN_CI_CONTAINER:-} ]]; then
    drift_in_container
    return
  fi
  local engine out="$ROOT/.ci-out"
  engine=$(command -v docker || command -v podman) ||
    die 'the drift job needs docker or podman'
  mkdir -p "$out"
  chmod 0777 "$out"
  "$engine" pull -q "$DRIFT_IMAGE" >/dev/null
  "$engine" run --rm -e AURADE_IN_CI_CONTAINER=1 \
    -v "$ROOT:/src:ro" -v "$out:/out" "$DRIFT_IMAGE" bash /src/ci/run.sh drift
  if [[ -n ${GITHUB_STEP_SUMMARY:-} && -f $out/drift.md ]]; then
    cat "$out/drift.md" >>"$GITHUB_STEP_SUMMARY"
  fi
}

drift_in_container() {
  local problems=0 pkg file missing
  local -a pkgs files elves
  problem() { printf 'drift: %s\n' "$*" >&2; problems=$((problems + 1)); }

  group 'pacman keys and the published repository'
  sed -i 's/^#\?ParallelDownloads.*/ParallelDownloads = 8/' /etc/pacman.conf
  pacman-key --init >/dev/null 2>&1
  pacman-key --populate archlinux >/dev/null 2>&1
  pacman-key --add /src/pins/aurade-release.gpg >/dev/null 2>&1
  pacman-key --lsign-key BC390DCF360B2184DBBF008B8B2AB2EFE667CB69 >/dev/null 2>&1
  printf '\n[aurade]\nSigLevel = Required\nServer = %s\n' "$HOSTED_REPO" >>/etc/pacman.conf
  pacman -Syu --noconfirm >/dev/null
  mapfile -t pkgs < <(pacman -Slq aurade)
  (( ${#pkgs[@]} > 0 )) || die 'the published repository lists no packages'
  echo "published: ${pkgs[*]}"
  endgroup

  group 'install every published package on current Arch'
  # Install scriptlets that talk to a running systemd complain in a container
  # and carry on; a package that cannot be installed at all fails here.
  pacman -S --noconfirm --needed "${pkgs[@]}" >/tmp/drift-install.log 2>&1 ||
    { tail -40 /tmp/drift-install.log; die 'the published packages no longer install on current Arch'; }
  pacman -Dk >/dev/null || problem 'pacman reports broken dependencies'
  endgroup

  group 'every AuraDE binary and library still finds what it links'
  mapfile -t files < <(pacman -Qlq "${pkgs[@]}" | grep -v '/$' | sort -u)
  for file in "${files[@]}"; do
    [[ -f $file && ! -L $file ]] || continue
    [[ $(head -c4 "$file" 2>/dev/null | od -An -c | tr -d ' ') == 177ELF ]] || continue
    elves+=("$file")
    missing=$(ldd "$file" 2>/dev/null | awk '/not found/ { print $1 }' | sort -u | tr '\n' ' ')
    [[ -z $missing ]] || problem "${file} cannot find: ${missing}"
  done
  echo "${#elves[@]} ELF files checked"
  # ldd shows the libraries; loading the browser shows the symbols as well.
  /usr/lib/chromiumos-ash/chrome --version ||
    problem 'the browser no longer starts against current Arch libraries'
  endgroup

  group 'every AuraDE Python file compiles, and the login screen imports'
  local -a py=()
  for file in "${files[@]}"; do
    [[ -f $file ]] || continue
    if [[ $file == *.py ]] || head -1 "$file" 2>/dev/null | grep -Eq '^#!.*python'; then
      py+=("$file")
    fi
  done
  python3 - "${py[@]}" <<'PY' || problem 'an AuraDE Python file no longer compiles'
import sys
bad = 0
for path in sys.argv[1:]:
    try:
        compile(open(path, encoding="utf-8").read(), path, "exec")
    except SyntaxError as exc:
        print(f"drift: {path}: {exc}", file=sys.stderr)
        bad += 1
print(f"{len(sys.argv) - 1} Python files compile under {sys.version.split()[0]}")
sys.exit(1 if bad else 0)
PY
  python3 -c 'import sys; sys.path.insert(0, "/usr/lib/aurade-greeter"); import aurade_greeter.app' ||
    problem 'the login screen no longer imports against current Arch Python and GTK'
  endgroup

  {
    echo '### Arch drift'
    echo
    echo '| | |'
    echo '|---|---|'
    local name
    for name in glibc icu python gtk4 weston chromiumos-ash aurade-greeter; do
      echo "| ${name} | $(pacman -Q "$name" 2>/dev/null | cut -d' ' -f2) |"
    done
    echo
    if (( problems )); then
      echo "**${problems} problem(s)**: a machine running \`pacman -Syu\` today would hit them."
    else
      echo 'Everything published still resolves on current Arch.'
    fi
  } >/out/drift.md
  (( problems == 0 )) || die "${problems} problem(s) against current Arch"
  echo 'drift: everything published still resolves on current Arch'
}

job_install_hooks() {
  git config core.hooksPath ci/hooks
  echo 'ci/run.sh: this clone now runs ci/hooks (git push --no-verify skips them)'
}

# --- packages ---------------------------------------------------------------

job_packages() {
  if [[ -n ${AURADE_IN_CI_CONTAINER:-} ]]; then
    packages_in_container
    return
  fi
  local engine
  engine=$(command -v docker || command -v podman) ||
    die 'the package job needs docker or podman'
  # Ubuntu 24.04 refuses unprivileged user namespaces through AppArmor, and a
  # privileged container does not lift that for the unprivileged builder
  # inside it: bwrap fails to write its uid map. Only on a CI runner, which is
  # thrown away afterwards; a local run leaves the host's settings alone.
  local restrict=/proc/sys/kernel/apparmor_restrict_unprivileged_userns
  if [[ -n ${GITHUB_ACTIONS:-} && -r $restrict && $(<"$restrict") == 1 ]]; then
    as_root sysctl -q -w kernel.apparmor_restrict_unprivileged_userns=0
  fi
  local out="$ROOT/.ci-out" cache="${AURADE_PACMAN_CACHE:-$ROOT/.ci-cache/pacman}"
  mkdir -p "$out" "$cache"
  chmod 0777 "$out"
  # Privileged, because aurade-login's check() runs its supervisor inside
  # bubblewrap, and a default container profile refuses the user namespace.
  "$engine" run --rm --privileged \
    -e AURADE_IN_CI_CONTAINER=1 \
    -v "$ROOT:/src:ro" \
    -v "$out:/out" \
    -v "$cache:/var/cache/pacman/pkg" \
    "$ARCH_IMAGE" bash /src/ci/run.sh packages
  # The container writes as root. Hand the output and the pacman cache back,
  # or the cache step cannot read what it is meant to save.
  if [[ -n ${GITHUB_ACTIONS:-} ]]; then
    as_root chown -R "$(id -u):$(id -g)" "$out" "$cache"
  fi
  if [[ -n ${GITHUB_STEP_SUMMARY:-} && -f $out/summary.md ]]; then
    cat "$out/summary.md" >>"$GITHUB_STEP_SUMMARY"
  fi
}

# Every depends, makedepends and checkdepends of the packages CI builds, less
# the packages themselves, from their .SRCINFO. makepkg runs with --nodeps, so
# what check() needs has to be installed before it starts.
package_dependencies() {
  local own dir
  own=$(for dir in $(<installer/expected-packages.txt); do
          sed -n 's/^pkgname = //p' "$dir/.SRCINFO"
        done | sort -u)
  for dir in "${CI_PACKAGES[@]}"; do
    sed -nE 's/^[[:space:]]*(depends|makedepends|checkdepends) = ([^<>=:]+).*/\2/p' "$dir/.SRCINFO"
  done | sort -u | grep -vxF -f <(printf '%s\n' "$own")
}

packages_in_container() {
  local work=/work repo=/work/.ci-repo

  group "pacman at the ${ARCH_SNAPSHOT} snapshot"
  printf 'Server = https://archive.archlinux.org/repos/%s/$repo/os/$arch\n' "$ARCH_SNAPSHOT" \
    >/etc/pacman.d/mirrorlist
  pacman -Syuu --noconfirm --noprogressbar
  endgroup

  group 'copy the tree for an unprivileged build'
  mkdir -p "$work"
  tar -C /src --exclude=./.build --exclude=./.ci-out --exclude=./.ci-cache -cf - . |
    tar -C "$work" -xf -
  cd "$work"
  useradd --create-home builder
  chown -R builder: "$work"
  endgroup

  group 'build and check dependencies'
  local -a deps
  mapfile -t deps < <(package_dependencies)
  printf '%s\n' "${deps[@]}"
  pacman -S --needed --noconfirm --noprogressbar namcap git python "${deps[@]}"
  endgroup

  group '.SRCINFO matches PKGBUILD'
  local dir
  for dir in $(<installer/expected-packages.txt); do
    runuser -u builder -- bash -c 'cd "$1" && makepkg --printsrcinfo' _ "$work/$dir" |
      diff -u "$work/$dir/.SRCINFO" - || die "$dir/.SRCINFO is stale; regenerate it with makepkg --printsrcinfo"
  done
  echo "every .SRCINFO matches its PKGBUILD"
  endgroup

  # The greeter's check() draws the login screen over a photograph and fails
  # without one. On a build machine they come from an installed
  # aurade-wallpapers; here they come from the checkout.
  group 'build, check() and namcap'
  runuser -u builder -- env \
    AURADE_WALLPAPER_DIR="$work/installer/wallpapers" \
    AURADE_PACKAGES="${CI_PACKAGES[*]}" \
    AURADE_SKIP_INSTALLER_TESTS=1 \
    AURADE_SKIP_UNIT_VERIFY=1 \
    REPO_DIR="$repo" \
    bash ci/arch-package-smoke.sh
  endgroup

  group 'install, verify files and units'
  local -a files=() units=()
  local name
  for name in "${CI_INSTALLABLE[@]}"; do
    files+=("$(find "$repo" -maxdepth 1 -name "${name}-[0-9]*.pkg.tar.*" ! -name '*.sig' | sort | tail -1)")
  done
  pacman -U --noconfirm --noprogressbar "${files[@]}"
  pacman -Qk "${CI_INSTALLABLE[@]}"
  mapfile -t units < <(pacman -Qlq "${CI_INSTALLABLE[@]}" | grep -E '^/usr/lib/systemd/system/[^/]+\.service$')
  systemd-analyze verify "${units[@]}"
  printf '%s units verify\n' "${#units[@]}"
  endgroup

  cp "$repo"/*.pkg.tar.* /out/
  {
    printf '### Packages\n\n| Package | Size |\n|---|---|\n'
    for name in "$repo"/*.pkg.tar.*; do
      [[ $name == *.sig ]] && continue
      printf '| %s | %s KiB |\n' "${name##*/}" "$(( $(stat -c %s "$name") / 1024 ))"
    done
  } >/out/summary.md
}

# --- dispatch ---------------------------------------------------------------

job=${1:-}
[[ -n $job ]] || { sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
shift
case $job in
  lint) job_lint ;;
  gates) job_gates ;;
  installer) job_installer "$@" ;;
  fixtures) job_fixtures ;;
  packages) job_packages ;;
  fast) job_fast ;;
  changes) job_changes "$@" ;;
  hosted) job_hosted ;;
  drift) job_drift ;;
  setup-ubuntu) job_setup_ubuntu ;;
  install-hooks) job_install_hooks ;;
  *) die "unknown job: $job" ;;
esac
