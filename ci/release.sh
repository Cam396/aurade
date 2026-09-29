#!/usr/bin/env bash
# Turn a built ISO and signed repository into a GitHub release.
#
#   ci/release.sh check-repo
#       Check the hosted pacman repository (the repo-x86_64 release) the way
#       pacman will use it: the database is signed by the release key, and
#       every package and signature it names is up with the checksum it
#       records. Needs only curl, gpgv, bsdtar and python3; CI runs it weekly.
#   ci/release.sh fetch-published DIR
#       Download the hosted repository into DIR, checked against the digests
#       GitHub reports for each file, for the release build to reuse
#       (AURADE_PUBLISHED_REPO), so a version that is already published keeps
#       its published bytes.
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
#       database back and check it. AURADE_RELEASE_DRY_RUN=1 prints the plan
#       and changes nothing.
#
# Signing uses the key whose fingerprint is in AURADE_RELEASE_FINGERPRINT,
# from whatever GNUPGHOME points at. The key never enters the repository;
# only its public half does, in pins/aurade-release.gpg.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
GH_REPO=${AURADE_GH_REPO:-Cam396/aurade}
REPO_TAG=repo-x86_64
REPO_BASE="https://github.com/${GH_REPO}/releases/download/${REPO_TAG}"
ISO_NAME=aurade-1-x86_64.iso
PUBLIC_KEY=$ROOT/pins/aurade-release.gpg
PUBLIC_FINGERPRINT=BC390DCF360B2184DBBF008B8B2AB2EFE667CB69

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

# The same check against the pinned public key, for a machine with no
# release keyring (CI, or anyone checking the hosted repository).
verify_public() {
  local sig=$1 file=$2
  gpgv --status-fd 1 --keyring "$PUBLIC_KEY" "$sig" "$file" 2>/dev/null |
    grep -Eq "^\[GNUPG:\] VALIDSIG ${PUBLIC_FINGERPRINT} " ||
    die "${file##*/} is not signed by ${PUBLIC_FINGERPRINT}"
}

# name<TAB>sha256 for every file on the repository release, as GitHub
# reports it. This, not the SHA256SUMS file among them, is what is served.
hosted_digests() {
  local -a auth=()
  [[ -n ${GH_TOKEN:-${GITHUB_TOKEN:-}} ]] && auth=(-H "Authorization: Bearer ${GH_TOKEN:-${GITHUB_TOKEN:-}}")
  curl -fsSL "${auth[@]}" -H 'Accept: application/vnd.github+json' \
    "https://api.github.com/repos/${GH_REPO}/releases/tags/${REPO_TAG}?per_page=100" |
    python3 -c '
import json, sys
for a in json.load(sys.stdin)["assets"]:
    d = a.get("digest") or ""
    if not d.startswith("sha256:"):
        sys.exit("release: GitHub reported no sha256 for " + a["name"])
    print(a["name"] + "\t" + d[7:])
' | sort
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
  # What GitHub serves, not the SHA256SUMS file among it: that file can say
  # one thing while an older upload of a package is what is really there.
  hosted_digests | awk -F '\t' '{ print $2 "  " $1 }' >"$hosted/SHA256SUMS"

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
  if [[ -n ${AURADE_RELEASE_DRY_RUN:-} ]]; then
    printf '  upload %s\n' "${upload_first[@]##*/}" "${upload_last[@]##*/}"
    (( ${#remove[@]} == 0 )) || printf '  remove %s\n' "${remove[@]}"
    rm -rf -- "$hosted"
    say 'dry run: nothing was changed'
    return
  fi
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
  cmd_check_repo
}

cmd_check_repo() {
  need curl; need gpgv; need bsdtar; need python3
  local tmp problems=0 name sum
  tmp=$(mktemp -d)
  trap 'rm -rf -- "$tmp"' RETURN
  hosted_digests >"$tmp/digests"
  digest() { awk -F '\t' -v n="$1" '$1 == n { print $2 }' "$tmp/digests"; }
  problem() { printf 'release: check-repo: %s\n' "$*" >&2; problems=$((problems + 1)); }

  local db
  for db in aurade.db aurade.files; do
    curl -fsSL -o "$tmp/$db" "$REPO_BASE/$db"
    curl -fsSL -o "$tmp/$db.sig" "$REPO_BASE/$db.sig"
    verify_public "$tmp/$db.sig" "$tmp/$db"
    [[ $(digest "$db") == "$(digest "$db.tar.gz")" && $(digest "$db.sig") == "$(digest "$db.tar.gz.sig")" ]] ||
      problem "${db} and ${db}.tar.gz are not the same file"
  done

  # Every package the database names is up, with the checksum it records and
  # the signature it embeds. pacman refuses a download that differs.
  mkdir "$tmp/db"
  bsdtar -xf "$tmp/aurade.db" -C "$tmp/db"
  local -A named=()
  local desc file want sig
  for desc in "$tmp"/db/*/desc; do
    file=$(sed -n '/^%FILENAME%$/{n;p;q}' "$desc")
    want=$(sed -n '/^%SHA256SUM%$/{n;p;q}' "$desc")
    # repo-add embeds the signature only with --include-sigs; pacman then
    # uses the embedded one, so it has to be the one that is uploaded.
    sig=$(sed -n '/^%PGPSIG%$/{n;p;q}' "$desc")
    named[$file]=1 named[$file.sig]=1
    case $(digest "$file") in
      "") problem "${file} is in the database but not uploaded" ;;
      "$want") ;;
      *) problem "${file} is not the file the database describes; pacman will refuse it" ;;
    esac
    [[ -n $(digest "$file.sig") ]] || problem "${file}.sig is not uploaded"
    if [[ -n $sig && $(digest "$file.sig") != "$(base64 -d <<<"$sig" | sha256sum | cut -d' ' -f1)" ]]; then
      problem "${file}.sig is not the signature the database carries"
    fi
  done

  # Nothing stale is left beside them, and SHA256SUMS describes what is up.
  while IFS=$'\t' read -r name sum; do
    case $name in
      aurade.db|aurade.db.*|aurade.files|aurade.files.*|SHA256SUMS) ;;
      *) [[ -n ${named[$name]:-} ]] || problem "${name} is uploaded but the database does not name it" ;;
    esac
  done <"$tmp/digests"
  curl -fsSL -o "$tmp/SHA256SUMS" "$REPO_BASE/SHA256SUMS"
  while read -r sum name; do
    [[ $(digest "$name") == "$sum" ]] || problem "SHA256SUMS is wrong about ${name}"
  done <"$tmp/SHA256SUMS"

  (( problems == 0 )) || die "the hosted repository has ${problems} problem(s)"
  say "the hosted repository is consistent: ${#named[@]} package files, database signed by ${PUBLIC_FINGERPRINT}"
}

cmd_fetch_published() {
  local dir=${1:?dir} name sum
  need curl; need sha256sum; need gpgv
  mkdir -p "$dir"
  hosted_digests >"$dir/.digests"
  while IFS=$'\t' read -r name sum; do
    [[ $name == *.pkg.tar.* ]] || continue
    [[ -f $dir/$name ]] && [[ $(sha256sum "$dir/$name" | cut -d' ' -f1) == "$sum" ]] && continue
    curl -fsSL -o "$dir/$name" "$REPO_BASE/$name"
    [[ $(sha256sum "$dir/$name" | cut -d' ' -f1) == "$sum" ]] || die "${name} downloaded with the wrong checksum"
  done <"$dir/.digests"
  for name in "$dir"/*.pkg.tar.*; do
    [[ $name == *.sig ]] && continue
    verify_public "$name.sig" "$name"
  done
  rm -f "$dir/.digests"
  say "fetched the published packages into ${dir}, each signed by the release key"
}

case ${1:-} in
  check-repo) shift; cmd_check_repo "$@" ;;
  fetch-published) shift; cmd_fetch_published "$@" ;;
  stage) shift; cmd_stage "$@" ;;
  draft) shift; cmd_draft "$@" ;;
  publish-repo) shift; cmd_publish_repo "$@" ;;
  *) sed -n '2,27p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
