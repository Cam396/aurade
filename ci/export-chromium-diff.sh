#!/bin/bash
# Export selected Chromium worktree changes into the AuraDE patch series.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CHROME_SRC="${CHROME_SRC:-${REPO_ROOT}/chromium_dev/src}"
PATCH_DIR="${PATCH_DIR:-${REPO_ROOT}/patches}"
SERIES_FILE="${SERIES_FILE:-${PATCH_DIR}/SERIES}"
WORKDIR="${AURADE_WORKDIR:-/mnt/build/aurade-work}"

force=0
append_series=1
slug=""
paths=()

usage() {
  cat <<'EOF'
Usage: ci/export-chromium-diff.sh [options] <slug> <path> [path...]

Exports selected changes from chromium_dev/src into patches/NNNN-<slug>.patch
and appends that patch to patches/SERIES.

Options:
  --force       Overwrite an existing patch with the same generated name.
  --no-series   Do not append the generated patch to patches/SERIES.
  -h, --help    Show this help.

Examples:
  ci/export-chromium-diff.sh diagnostics-gpu \
    ash/webui/diagnostics_ui/backend/system \
    ash/webui/diagnostics_ui/resources

  CHROME_SRC=/mnt/build/chromiumos/chromium_dev/src \
    ci/export-chromium-diff.sh top-shelf ash/shelf ash/system/tray
EOF
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --force)
      force=1
      shift
      ;;
    --no-series)
      append_series=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      if [[ -z "${slug}" ]]; then
        slug="$1"
      else
        paths+=("$1")
      fi
      shift
      ;;
  esac
done

while [[ "$#" -gt 0 ]]; do
  paths+=("$1")
  shift
done

if [[ -z "${slug}" || "${#paths[@]}" -eq 0 ]]; then
  usage >&2
  exit 2
fi

if [[ ! -d "${CHROME_SRC}/.git" ]]; then
  echo "Chromium source git repo not found: ${CHROME_SRC}" >&2
  exit 1
fi

slug="$(printf '%s' "${slug}" \
  | tr '[:upper:]' '[:lower:]' \
  | sed -E 's/[^a-z0-9._-]+/-/g; s/^-+//; s/-+$//')"
if [[ -z "${slug}" ]]; then
  echo "Slug becomes empty after normalization." >&2
  exit 2
fi

next_patch_number() {
  local current max=0
  while IFS= read -r current; do
    [[ -z "${current}" ]] && continue
    current="${current%%-*}"
    [[ "${current}" =~ ^[0-9]+$ ]] || continue
    if ((10#${current} > max)); then
      max=$((10#${current}))
    fi
  done < <(
    {
      find "${PATCH_DIR}" -maxdepth 1 -type f \
        -name '[0-9][0-9][0-9][0-9]-*.patch' \
        -printf '%f\n' 2>/dev/null
      if [[ -r "${SERIES_FILE}" ]]; then
        sed -E 's/[[:space:]]+#.*$//; /^[[:space:]]*($|#)/d; s/^[[:space:]]+//; s/[[:space:]]+$//' \
          "${SERIES_FILE}"
      fi
    } | sort -u
  )
  printf '%04d' "$((max + 1))"
}

normalize_path() {
  local path="$1"
  case "${path}" in
    "${CHROME_SRC}"/*)
      path="${path#"${CHROME_SRC}/"}"
      ;;
  esac
  path="${path#./}"
  printf '%s\n' "${path}"
}

normalized_paths=()
for path in "${paths[@]}"; do
  normalized_paths+=("$(normalize_path "${path}")")
done

mapfile -t untracked_paths < <(
  git -C "${CHROME_SRC}" ls-files --others --exclude-standard -- \
    "${normalized_paths[@]}" | sort -u
)

install -d -m 755 "${WORKDIR}" "${PATCH_DIR}"
tmp_patch="$(mktemp "${WORKDIR}/aurade-export-patch.XXXXXX")"
trap 'rm -f "${tmp_patch}"' EXIT

git -C "${CHROME_SRC}" diff --binary -- "${normalized_paths[@]}" >"${tmp_patch}"

for untracked_path in "${untracked_paths[@]}"; do
  git -C "${CHROME_SRC}" diff --no-index --binary -- /dev/null \
    "${untracked_path}" >>"${tmp_patch}" || true
done

if [[ ! -s "${tmp_patch}" ]]; then
  echo "No tracked or untracked changes found for selected paths." >&2
  exit 1
fi

git -C "${CHROME_SRC}" diff --check -- "${normalized_paths[@]}"

patch_name="$(next_patch_number)-${slug}.patch"
patch_path="${PATCH_DIR}/${patch_name}"
if [[ -e "${patch_path}" && "${force}" != "1" ]]; then
  echo "Patch already exists: ${patch_path}" >&2
  echo "Use --force to overwrite it." >&2
  exit 1
fi

mv "${tmp_patch}" "${patch_path}"
chmod 644 "${patch_path}"
trap - EXIT

if [[ "${append_series}" == "1" ]]; then
  touch "${SERIES_FILE}"
  if ! grep -Fxq "${patch_name}" "${SERIES_FILE}"; then
    printf '%s\n' "${patch_name}" >>"${SERIES_FILE}"
  fi
fi

echo "Wrote ${patch_path}"
