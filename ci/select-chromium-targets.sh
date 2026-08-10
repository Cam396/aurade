#!/bin/bash
# Produce a deterministic, conservative validation plan from changed Chromium files.
set -euo pipefail

source_dir=""
changed_file=""
output=""

usage() {
  cat <<'EOF'
Usage: ci/select-chromium-targets.sh --source DIR --changed FILE --output FILE

Reads a newline-delimited changed-file list and writes a reviewable GN/Ninja
validation plan. This script does not run GN or Ninja.
EOF
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --source) source_dir="$2"; shift 2 ;;
    --changed) changed_file="$2"; shift 2 ;;
    --output) output="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -d "${source_dir}" ]] || { echo "Source directory not found: ${source_dir}" >&2; exit 2; }
[[ -r "${changed_file}" ]] || { echo "Changed-file list not found: ${changed_file}" >&2; exit 2; }
[[ -n "${output}" ]] || { echo "--output is required" >&2; exit 2; }

declare -A scopes=()
declare -A targets=([chrome]=1)
changed_count=0

while IFS= read -r path; do
  [[ -n "${path}" ]] || continue
  case "${path}" in
    /*|*..*|*//* )
      echo "Unsafe changed path: ${path}" >&2
      exit 1
      ;;
  esac
  changed_count=$((changed_count + 1))

  search_dir="${path%/*}"
  [[ "${search_dir}" != "${path}" ]] || search_dir="."
  while [[ "${search_dir}" != "." && -n "${search_dir}" ]]; do
    if [[ -f "${source_dir}/${search_dir}/BUILD.gn" ]]; then
      scopes["//${search_dir}:*"]=1
      break
    fi
    if [[ "${search_dir}" == */* ]]; then
      search_dir="${search_dir%/*}"
    else
      search_dir="."
    fi
  done

  case "${path}" in
    ash/*) targets[ash_unittests]=1 ;;
    chrome/browser/ash/*|chrome/test/*) targets[browser_tests]=1 ;;
    chromeos/*|components/*) targets[unit_tests]=1 ;;
    ui/file_manager/*|chrome/browser/resources/ash/*) targets[browser_tests]=1 ;;
  esac
done < "${changed_file}"

install -d -m 755 "$(dirname "${output}")"
tmp="${output}.tmp.$$"
trap 'rm -f "${tmp}"' EXIT
{
  echo "# AuraDE Chromium Candidate Target Plan"
  echo "changed_count=${changed_count}"
  echo
  echo "[changed_files]"
  sort -u "${changed_file}"
  echo
  echo "[gn_ref_queries]"
  while IFS= read -r path; do
    [[ -n "${path}" ]] && printf "gn refs \"\$AURADE_GN_OUT_DIR\" //%s --all\n" "${path}"
  done < <(sort -u "${changed_file}")
  echo
  echo "[nearest_gn_scopes]"
  if [[ "${#scopes[@]}" -gt 0 ]]; then
    printf '%s\n' "${!scopes[@]}" | sort
  fi
  echo
  echo "[conservative_ninja_targets]"
  printf '%s\n' "${!targets[@]}" | sort
} > "${tmp}"
mv -f "${tmp}" "${output}"
trap - EXIT

echo "Target plan written: ${output} (${changed_count} changed files)"
