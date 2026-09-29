#!/usr/bin/env bash
# Turn a built ISO and signed repository into a GitHub release.
#
#   ci/release.sh stage VERSION COMMIT ISO_DIR REPO_DIR OUT_DIR
#       Check the build, rename the ISO for VERSION, write the repository
#       archive, SHA256SUMS and its signature, and the release notes from the
#       CHANGELOG section for VERSION. Nothing leaves the machine.
#   ci/release.sh draft OUT_DIR
#       Tag the staged commit as vVERSION (or check an existing tag points at
#       it), push the tag, and create the GitHub release as a draft. A person
#       reads the draft and publishes it; this script never does.
#   ci/release.sh publish-repo OUT_DIR
#       After the release is public: bring the hosted pacman repository (the
#       repo-x86_64 release) in line with the staged one, then download its
#       database back and check it.
#
# Signing uses the key whose fingerprint is in AURADE_RELEASE_FINGERPRINT,
# from whatever GNUPGHOME points at. The key never enters the repository.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
GH_REPO=${AURADE_GH_REPO:-Cam396/aurade}
REPO_TAG=repo-x86_64
ISO_NAME=aurade-1-x86_64.iso

die() { printf 'release: %s\n' "$*" >&2; exit 1; }
say() { printf 'release: %s\n' "$*"; }
need() { command -v "$1" >/dev/null 2>&1 || die "missing command: $1"; }

fingerprint() {
  local fpr=${AURADE_RELEASE_FINGERPRINT:-}
  [[ $fpr =~ ^[0-9A-F]{40}$ ]] || die 'set AURADE_RELEASE_FINGERPRINT to the full release key fingerprint'
  printf '%s\n' "$fpr"
}

# gpg --verify prints the fingerprint of the key that made a good signature
# in its status output. A good signature from any other key is a failure.
verify_signature() {
  local sig=$1 file=$2 fpr=$3
  gpg --status-fd 1 --verify "$sig" "$file" 2>/dev/null |
    grep -Eq "^\[GNUPG:\] VALIDSIG ${fpr} " ||
    die "${file##*/} is not signed by ${fpr}"
}

changelog_section() {
  local version=$1
  awk -v v="$version" '
    $0 ~ "^## " { if (found) exit; if (index($0, "## " v ",") == 1 || $0 == "## " v) { found = 1; next } }
    found { print }
  ' "$ROOT/CHANGELOG.md"
}

cmd_stage() {
  local version=${1:?version} commit=${2:?commit} iso_dir=${3:?iso dir} repo_dir=${4:?repo dir} out=${5:?out dir}
  need gpg; need sha256sum; need git
  [[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "version must look like 1.2.3, not ${version}"
  local fpr; fpr=$(fingerprint)
  commit=$(git -C "$ROOT" rev-parse --verify "${commit}^{commit}") || die "unknown commit ${commit}"
  git -C "$ROOT" fetch -q origin main
  git -C "$ROOT" merge-base --is-ancestor "$commit" origin/main ||
    die "${commit} is not on origin/main; release only what is public"

  local notes; notes=$(changelog_section "$version")
  [[ -n ${notes//[[:space:]]/} ]] || die "CHANGELOG.md has no section for ${version}"

  local iso=$iso_dir/$ISO_NAME
  for f in "$iso" "$iso.sig" "$iso.sbom.spdx.json" "$iso.sbom.spdx.json.sig" "$iso.build-info" "$repo_dir/aurade.db" "$repo_dir/SHA256SUMS"; do
    [[ -f $f ]] || die "missing ${f}"
  done
  grep -qx "iso_signing_fingerprint=${fpr}" "$iso.build-info" || die 'the ISO was not built for the release key'
  grep -qx "repo_fingerprint=${fpr}" "$iso.build-info" || die 'the ISO trusts a repository key other than the release key'
  verify_signature "$iso.sig" "$iso" "$fpr"
  verify_signature "$iso.sbom.spdx.json.sig" "$iso.sbom.spdx.json" "$fpr"
  verify_signature "$repo_dir/aurade.db.sig" "$repo_dir/aurade.db" "$fpr"
  (cd "$repo_dir" && sha256sum -c --quiet SHA256SUMS) || die 'the repository does not match its SHA256SUMS'
  local pkg
  for pkg in "$repo_dir"/*.pkg.tar.*; do
    [[ $pkg == *.sig ]] && continue
    verify_signature "$pkg.sig" "$pkg" "$fpr"
  done
  say 'the ISO, SBOM, database and every package are signed by the release key'

  [[ ! -e $out ]] || die "${out} already exists"
  mkdir -p "$out"
  local base="aurade-v${version}-x86_64"
  cp "$iso" "$out/$base.iso"
  cp "$iso.sig" "$out/$base.iso.sig"
  cp "$iso.sbom.spdx.json" "$out/$base.iso.sbom.spdx.json"
  cp "$iso.sbom.spdx.json.sig" "$out/$base.iso.sbom.spdx.json.sig"
  cp "$iso.build-info" "$out/$base.iso.build-info"
  (cd "$out" && sha256sum "$base.iso" >"$base.iso.sha256")
  gpg --armor --export "$fpr" >"$out/aurade-repository.asc"
  gpg --export "$fpr" >"$out/aurade-repository.gpg"

  local epoch stage
  epoch=$(sed -n 's/^source_date_epoch=//p' "$iso.build-info")
  stage=$(mktemp -d)
  mkdir "$stage/repository"
  cp -a "$repo_dir/." "$stage/repository/"
  tar --sort=name --owner=0 --group=0 --numeric-owner --mtime="@${epoch:-0}" \
    -C "$stage" -czf "$out/$base-repository.tar.gz" repository
  rm -rf -- "$stage"
  mkdir "$out/repository"
  cp -a "$repo_dir/." "$out/repository/"

  (cd "$out" && sha256sum aurade-repository.asc aurade-repository.gpg "$base".iso "$base".iso.sig \
      "$base".iso.sha256 "$base".iso.build-info "$base".iso.sbom.spdx.json \
      "$base".iso.sbom.spdx.json.sig "$base-repository.tar.gz" >SHA256SUMS)
  gpg --batch --yes --local-user "$fpr" --detach-sign -o "$out/SHA256SUMS.sig" "$out/SHA256SUMS"
  verify_signature "$out/SHA256SUMS.sig" "$out/SHA256SUMS" "$fpr"

  local iso_sum repo_sum
  iso_sum=$(cut -d' ' -f1 "$out/$base.iso.sha256")
  repo_sum=$(sha256sum "$out/$base-repository.tar.gz" | cut -d' ' -f1)
  {
    printf '%s\n' "$notes"
    printf '\n## Verify\n\n'
    printf '    gpg --import aurade-repository.asc\n'
    printf '    gpg --verify SHA256SUMS.sig SHA256SUMS\n'
    printf '    sha256sum -c --ignore-missing SHA256SUMS\n'
    printf '    gpg --verify %s.iso.sig %s.iso\n\n' "$base" "$base"
    printf -- '- ISO SHA-256: `%s`\n' "$iso_sum"
    printf -- '- Repository archive SHA-256: `%s`\n' "$repo_sum"
    printf -- '- Release key: `%s`\n' "$fpr"
  } >"$out/notes.md"
  printf 'version=%s\ncommit=%s\nfingerprint=%s\n' "$version" "$commit" "$fpr" >"$out/release.env"
  say "staged ${version} from ${commit:0:12} in ${out}"
  say "edit ${out}/notes.md if the release wants an introduction, then run: ci/release.sh draft ${out}"
}

load_stage() {
  local out=$1
  [[ -f $out/release.env ]] || die "${out} was not made by ci/release.sh stage"
  # shellcheck disable=SC1091
  source "$out/release.env"
  (cd "$out" && sha256sum -c --quiet SHA256SUMS) || die "${out} no longer matches its SHA256SUMS"
  verify_signature "$out/SHA256SUMS.sig" "$out/SHA256SUMS" "$fingerprint"
}

cmd_draft() {
  local out=${1:?out dir}
  need gh; need gpg
  load_stage "$out"
  local tag="v${version}" existing
  if existing=$(git -C "$ROOT" rev-parse -q --verify "refs/tags/${tag}^{commit}"); then
    [[ $existing == "$commit" ]] || die "${tag} already points at ${existing:0:12}, not ${commit:0:12}"
  else
    git -C "$ROOT" tag "$tag" "$commit"
  fi
  git -C "$ROOT" push origin "refs/tags/${tag}"
  local base="aurade-v${version}-x86_64"
  gh release create "$tag" -R "$GH_REPO" --draft --verify-tag \
    --title "AuraDE ${version}" --notes-file "$out/notes.md" \
    "$out/$base.iso" "$out/$base.iso.sig" "$out/$base.iso.sha256" \
    "$out/$base.iso.build-info" "$out/$base.iso.sbom.spdx.json" \
    "$out/$base.iso.sbom.spdx.json.sig" "$out/$base-repository.tar.gz" \
    "$out/aurade-repository.asc" "$out/aurade-repository.gpg" \
    "$out/SHA256SUMS" "$out/SHA256SUMS.sig"
  # GitHub records a digest for every asset. Each one has to be the file here.
  local name digest
  while read -r name digest; do
    [[ $digest == "sha256:$(sha256sum "$out/$name" | cut -d' ' -f1)" ]] ||
      die "the uploaded ${name} does not match the staged file"
  done < <(gh release view "$tag" -R "$GH_REPO" --json assets -q '.assets[] | "\(.name) \(.digest)"')
  say "draft ${tag} is up and every asset matches; publish it with: gh release edit ${tag} -R ${GH_REPO} --draft=false --latest"
}

cmd_publish_repo() {
  local out=${1:?out dir}
  need gh; need gpg; need curl
  load_stage "$out"
  local draft
  draft=$(gh release view "v${version}" -R "$GH_REPO" --json isDraft -q .isDraft) ||
    die "there is no release v${version}"
  [[ $draft == false ]] || die "v${version} is still a draft; publish it before its packages"

  local local_repo="$out/repository" hosted
  hosted=$(mktemp -d)
  curl -fsSL -o "$hosted/SHA256SUMS" "https://github.com/${GH_REPO}/releases/download/${REPO_TAG}/SHA256SUMS"

  # Packages and their signatures first, the database after them, so a client
  # that syncs mid-update never sees a database naming a file that is not up.
  # SHA256SUMS lists every package, signature and database archive. The four
  # names pacman fetches (aurade.db, aurade.files and their signatures) are
  # links to those archives, so they always go up, last.
  local -a upload_first=() upload_last=() remove=()
  local sum name
  while read -r sum name; do
    grep -qxF "${sum}  ${name}" "$hosted/SHA256SUMS" && continue
    case $name in
      aurade.db.*|aurade.files.*) upload_last+=("$local_repo/$name") ;;
      *) upload_first+=("$local_repo/$name") ;;
    esac
  done <"$local_repo/SHA256SUMS"
  upload_last+=("$local_repo/aurade.db" "$local_repo/aurade.db.sig"
                "$local_repo/aurade.files" "$local_repo/aurade.files.sig"
                "$local_repo/SHA256SUMS")
  mapfile -t remove < <(comm -13 <(awk '{print $2}' "$local_repo/SHA256SUMS" | sort) \
                                 <(awk '{print $2}' "$hosted/SHA256SUMS" | sort))

  say "packages to upload: ${#upload_first[@]}, database files: ${#upload_last[@]}, assets to remove: ${#remove[@]}"
  (( ${#upload_first[@]} == 0 )) || gh release upload "$REPO_TAG" -R "$GH_REPO" --clobber "${upload_first[@]}"
  gh release upload "$REPO_TAG" -R "$GH_REPO" --clobber "${upload_last[@]}"
  for name in "${remove[@]}"; do
    gh release delete-asset "$REPO_TAG" "$name" -R "$GH_REPO" -y
  done

  local check
  check=$(mktemp -d)
  curl -fsSL -o "$check/aurade.db" "https://github.com/${GH_REPO}/releases/download/${REPO_TAG}/aurade.db"
  curl -fsSL -o "$check/aurade.db.sig" "https://github.com/${GH_REPO}/releases/download/${REPO_TAG}/aurade.db.sig"
  cmp -s "$check/aurade.db" "$local_repo/aurade.db" || die 'the hosted database is not the staged one'
  verify_signature "$check/aurade.db.sig" "$check/aurade.db" "$fingerprint"
  rm -rf -- "$hosted" "$check"
  say "the hosted repository serves the ${version} database, signed by the release key"
}

case ${1:-} in
  stage) shift; cmd_stage "$@" ;;
  draft) shift; cmd_draft "$@" ;;
  publish-repo) shift; cmd_publish_repo "$@" ;;
  *) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
