#!/usr/bin/env bash
# Push an export from ci/export-aur-bundles.sh to the AUR, one git repo per package.
#
#   ci/publish-aur.sh EXPORT_DIR
#
# Without AUR_SSH_KEY (a path to the private key the AUR account holds) this is
# a dry run: it clones each AUR repo read-only over https, shows what would
# change, and pushes nothing. A package the AUR does not have yet is created by
# its first push; the clone of a repo that does not exist is empty, which git
# treats the same way.
#
# Run it only after ci/aur-package-smoke.sh has passed on the same export, so
# a package that does not build never reaches anyone.
set -Eeuo pipefail

EXPORT=${1:-}
die() { printf 'publish-aur: %s\n' "$*" >&2; exit 1; }
[[ -d ${EXPORT} ]] || die "usage: $0 EXPORT_DIR"
command -v makepkg >/dev/null || die 'makepkg is needed to write .SRCINFO'

KEY=${AUR_SSH_KEY:-}
WORK=$(mktemp -d)
trap 'rm -rf "${WORK}"' EXIT
if [[ -n ${KEY} ]]; then
  [[ -r ${KEY} ]] || die "cannot read AUR_SSH_KEY ${KEY}"
  export GIT_SSH_COMMAND="ssh -i ${KEY} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
  remote() { printf 'ssh://aur@aur.archlinux.org/%s.git' "$1"; }
else
  echo 'publish-aur: no AUR_SSH_KEY, dry run'
  remote() { printf 'https://aur.archlinux.org/%s.git' "$1"; }
fi

changed=0
for dir in "${EXPORT}"/*/; do
  pkg=$(basename "${dir}")
  [[ -f ${dir}/PKGBUILD ]] || continue
  repo=${WORK}/${pkg}
  git clone -q "$(remote "${pkg}")" "${repo}" 2>/dev/null || git init -q "${repo}"
  # The AUR repo holds exactly what the export holds, so a file dropped from a
  # package is dropped there too.
  find "${repo}" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
  cp -a "${dir}/." "${repo}/"
  rm -f "${repo}"/*.log
  (cd "${repo}" && makepkg --printsrcinfo > .SRCINFO)
  ver=$(sed -n 's/^\tpkgver = //p' "${repo}/.SRCINFO" | head -1)
  rel=$(sed -n 's/^\tpkgrel = //p' "${repo}/.SRCINFO" | head -1)
  git -C "${repo}" add -A
  if git -C "${repo}" diff --cached --quiet 2>/dev/null; then
    printf '%-26s %s-%s unchanged\n' "${pkg}" "${ver}" "${rel}"
    continue
  fi
  changed=$((changed + 1))
  printf '%-26s %s-%s\n' "${pkg}" "${ver}" "${rel}"
  git -C "${repo}" diff --cached --stat | tail -1 | sed 's/^/    /'
  if [[ -n ${KEY} ]]; then
    git -C "${repo}" -c user.name="AuraDE" -c user.email="aurade@users.noreply.github.com" \
      commit -q -m "${ver}-${rel}"
    git -C "${repo}" push -q origin HEAD:master
  fi
done
printf 'publish-aur: %s package(s) %s\n' "${changed}" "$([[ -n ${KEY} ]] && echo pushed || echo would change)"
