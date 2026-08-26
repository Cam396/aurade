#!/usr/bin/env bash
# One Chromium, said the same way everywhere.
#
# The revision, the version and the package all describe the same thing, and
# they lived in three files that nothing compared. They drifted: the pin held
# a 152 revision, the package declared 154.0.8015.0, and the tree that was
# actually built was a third thing. Anybody following the documented build
# path would have synced 152 and packaged it as 154, and the artifact would
# not have been traceable to any source at all.
#
# This is the comparison. It needs no network, no checkout and no build, so
# there is no excuse for it not to run on every change.
set -Eeuo pipefail

# Overridable so the gate can be pointed at a fixture tree. A gate nobody can
# aim at a broken repository is a gate nobody has watched fail.
ROOT=${AURADE_IDENTITY_ROOT:-$(cd -- "$(dirname -- "$0")/.." && pwd -P)}
FAILURES=0

fail() {
  printf 'release identity: %s\n' "$1" >&2
  FAILURES=$((FAILURES + 1))
}

read_pin() {
  local file="${ROOT}/pins/$1"
  [[ -r ${file} ]] || { fail "pins/$1 is missing"; return 1; }
  tr -d '[:space:]' < "${file}"
}

revision=$(read_pin chromium.sha || true)
version=$(read_pin chromium.version || true)

# --- record mode -----------------------------------------------------------
#
# Binding a revision to a version needs the checkout, and most runs do not
# have one. So the binding is recorded once, against a real tree, and every
# later run checks the pin against that record. Changing either half of the
# pin without re-recording fails, which is the exact failure this gate exists
# for: a 152 revision sitting next to a 154 version, both well formed, with
# nothing in the repository able to notice.
if [[ ${1:-} == --record ]]; then
  src=${AURADE_CHROMIUM_SRC:-}
  [[ -n ${src} && -d ${src} ]] || {
    echo "release identity: --record needs AURADE_CHROMIUM_SRC pointing at a checkout" >&2
    exit 2
  }
  tree_version=$(
    awk -F= '/^MAJOR/{a=$2} /^MINOR/{b=$2} /^BUILD/{c=$2} /^PATCH/{d=$2}
             END{printf "%s.%s.%s.%s", a, b, c, d}' "${src}/chrome/VERSION"
  )
  tree_revision=$(git -C "${src}" rev-parse HEAD)
  cat > "${ROOT}/pins/chromium.provenance" <<PROV
revision=${tree_revision}
version=${tree_version}
verified=$(date -u +%Y-%m-%dT%H:%M:%SZ)
PROV
  printf 'release identity: recorded %s at %s\n' "${tree_version}" "${tree_revision:0:12}"
  exit 0
fi

# --- the pin is well formed ------------------------------------------------

if [[ ! ${revision} =~ ^[0-9a-f]{40}$ ]]; then
  fail "pins/chromium.sha is not a 40 character git revision: '${revision}'"
fi
if [[ ! ${version} =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  fail "pins/chromium.version is not a Chromium version: '${version}'"
fi

# --- the revision and the version were seen together, once, on a real tree -

provenance="${ROOT}/pins/chromium.provenance"
if [[ -r ${provenance} ]]; then
  recorded_revision=$(sed -n 's/^revision=//p' "${provenance}" | head -1)
  recorded_version=$(sed -n 's/^version=//p' "${provenance}" | head -1)
  if [[ ${recorded_revision} != "${revision}" ]]; then
    fail "the pinned revision ${revision:0:12} was never checked against a tree; the record is for ${recorded_revision:0:12}"
  fi
  if [[ ${recorded_version} != "${version}" ]]; then
    fail "the pinned version ${version} was never seen on that revision; the record says ${recorded_version}"
  fi
else
  fail "pins/chromium.provenance is missing, so nothing has ever confirmed that this revision carries this version"
fi

# --- the package says the same thing --------------------------------------

pkgbuild="${ROOT}/chromiumos-ash/PKGBUILD"
if [[ -r ${pkgbuild} ]]; then
  pkgver=$(sed -n 's/^pkgver=\(.*\)$/\1/p' "${pkgbuild}" | head -1)
  if [[ ${pkgver} != "${version}" ]]; then
    fail "chromiumos-ash/PKGBUILD declares pkgver=${pkgver}, the pin says ${version}"
  fi
else
  fail "chromiumos-ash/PKGBUILD is missing"
fi

srcinfo="${ROOT}/chromiumos-ash/.SRCINFO"
if [[ -r ${srcinfo} ]]; then
  srcver=$(sed -n 's/^[[:space:]]*pkgver = \(.*\)$/\1/p' "${srcinfo}" | head -1)
  if [[ ${srcver} != "${version}" ]]; then
    fail "chromiumos-ash/.SRCINFO declares pkgver = ${srcver}, the pin says ${version}"
  fi
fi

# --- and so does the checkout, when there is one --------------------------
#
# Optional on purpose. A source tree is gigabytes and most changes do not have
# one to hand, but when it is there it is the only thing that can prove the
# pin describes a revision that exists and carries the version claimed for it.

src=${AURADE_CHROMIUM_SRC:-}
if [[ -n ${src} && -d ${src} ]]; then
  if [[ -r ${src}/chrome/VERSION ]]; then
    tree_version=$(
      awk -F= '/^MAJOR/{a=$2} /^MINOR/{b=$2} /^BUILD/{c=$2} /^PATCH/{d=$2}
               END{printf "%s.%s.%s.%s", a, b, c, d}' "${src}/chrome/VERSION"
    )
    if [[ ${tree_version} != "${version}" ]]; then
      fail "the checkout is ${tree_version}, the pin says ${version}"
    fi
  else
    fail "AURADE_CHROMIUM_SRC has no chrome/VERSION"
  fi
  if tree_revision=$(git -C "${src}" rev-parse HEAD 2>/dev/null); then
    if [[ ${tree_revision} != "${revision}" ]]; then
      fail "the checkout is at ${tree_revision:0:12}, the pin says ${revision:0:12}"
    fi
  fi
fi

# --- nothing else in the tree names a different Chromium ------------------
#
# A version in prose is a claim somebody will believe. When it disagrees with
# the pin it is worse than no claim, because it is specific.

if [[ -n ${version} ]]; then
  stray=$(
    grep -rIn --exclude-dir=.git --exclude-dir=patches \
      --include='*.md' -oE '\b1[0-9]{2}\.0\.[0-9]{4}\.[0-9]+\b' "${ROOT}" 2>/dev/null \
      | grep -v ":${version}\$" || true
  )
  if [[ -n ${stray} ]]; then
    while IFS= read -r line; do
      fail "a document names a different Chromium: ${line#"${ROOT}/"}"
    done <<< "${stray}"
  fi
fi

if (( FAILURES > 0 )); then
  printf 'release identity: %d disagreement(s); the artifact is not traceable to a source\n' \
    "${FAILURES}" >&2
  exit 1
fi

printf 'release identity: PASS (Chromium %s at %s)\n' "${version}" "${revision:0:12}"
