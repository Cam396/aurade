#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=${AURADE_ROOT_DIR:-/mnt/build/chromiumos}
OUT_DIR=${AURADE_NINJA_OUT_DIR:-${ROOT_DIR}/chromium_dev/src/out/Ash}
TMP_DIR=${AURADE_NINJA_TMPFS_DIR:-/tmp/ninja-tmpfs}
BACKUP_DIR=${AURADE_NINJA_TMPFS_BACKUP:-${ROOT_DIR}/.ninja-tmpfs-backups/Ash}
MANIFEST=${BACKUP_DIR}/symlink-manifest.txt

usage() {
  cat <<EOF
Usage: $0 <status|prepare-gen|link|seed|backup|restore|run -- command...>

Defaults:
  OUT_DIR=${OUT_DIR}
  TMP_DIR=${TMP_DIR}
  BACKUP_DIR=${BACKUP_DIR}

Commands:
  status   Show tmpfs, backup, and symlink counts.
  prepare-gen
           Recreate TMP_DIR parent directories for broken out/Ash ninja symlinks
           so gn gen can write metadata after /tmp was wiped.
  link     Replace out/Ash ninja metadata files with symlinks into TMP_DIR.
  seed     Copy current out/Ash ninja metadata into TMP_DIR, relink, and backup.
  backup   Copy TMP_DIR to BACKUP_DIR and save the symlink manifest.
  restore  Restore TMP_DIR from BACKUP_DIR, then relink out/Ash metadata.
  run      Run a build command, then backup TMP_DIR if it succeeds.
EOF
}

sync_tree() {
  local src=$1
  local dst=$2
  mkdir -p "${dst}"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete "${src%/}/" "${dst%/}/"
  else
    rm -rf "${dst}"
    mkdir -p "${dst}"
    cp -a "${src%/}/." "${dst%/}/"
  fi
}

ninja_file_list_from_out() {
  if [ -f "${OUT_DIR}/build.ninja" ] && [ -s "${MANIFEST}" ]; then
    printf '%s\n' build.ninja
    cat "${MANIFEST}"
    return 0
  fi

  # One directory walk is substantially faster than opening and parsing every
  # subninja serially on the persistent build disk. GN owns all *.ninja files
  # below a single output directory, so copying the complete set is correct.
  find "${OUT_DIR}" \( -type f -o -type l \) -name '*.ninja' -printf '%P\n' |
    sort
}

manifest_from_tmpfs() {
  find "${TMP_DIR}" -type f -name '*.ninja' -printf '%P\n' |
    awk '$0 != "build.ninja"' |
    sort
}

manifest_for_status() {
  if [ -s "${MANIFEST}" ]; then
    cat "${MANIFEST}"
  elif [ -d "${TMP_DIR}" ]; then
    manifest_from_tmpfs
  fi
}

prepare_gen_targets() {
  if [ ! -d "${OUT_DIR}" ]; then
    echo "missing OUT_DIR: ${OUT_DIR}" >&2
    exit 1
  fi

  mkdir -p "${TMP_DIR}" "${BACKUP_DIR}"
  local dir_list unique_dir_list out_dir rel
  dir_list=$(mktemp)
  unique_dir_list=$(mktemp)

  find "${OUT_DIR}" -type l -name '*.ninja' -printf '%h\n' >"${dir_list}"
  sort -u "${dir_list}" >"${unique_dir_list}"

  while IFS= read -r out_dir; do
    [ -n "${out_dir}" ] || continue
    rel=${out_dir#"${OUT_DIR}"}
    rel=${rel#/}
    if [ -n "${rel}" ]; then
      mkdir -p "${TMP_DIR}/${rel}"
    else
      mkdir -p "${TMP_DIR}"
    fi
  done <"${unique_dir_list}"

  printf 'prepared tmpfs parent directories for %s ninja metadata directories\n' "$(wc -l <"${unique_dir_list}")"
  rm -f "${dir_list}" "${unique_dir_list}"
}

link_tmpfs() {
  if [ ! -d "${TMP_DIR}" ]; then
    echo "missing TMP_DIR: ${TMP_DIR}" >&2
    exit 1
  fi
  if [ ! -d "${OUT_DIR}" ]; then
    echo "missing OUT_DIR: ${OUT_DIR}" >&2
    exit 1
  fi

  { printf '%s\n' build.ninja; manifest_for_status; } | while IFS= read -r rel; do
    [ -n "${rel}" ] || continue
    [ -f "${TMP_DIR}/${rel}" ] || continue
    mkdir -p "$(dirname "${OUT_DIR}/${rel}")"
    ln -sfn "${TMP_DIR}/${rel}" "${OUT_DIR}/${rel}"
  done
}

seed_tmpfs_from_out() {
  if [ ! -d "${OUT_DIR}" ]; then
    echo "missing OUT_DIR: ${OUT_DIR}" >&2
    exit 1
  fi

  mkdir -p "${TMP_DIR}"
  mkdir -p "${BACKUP_DIR}"
  local file_list
  file_list=$(mktemp)
  ninja_file_list_from_out >"${file_list}"

  if command -v rsync >/dev/null 2>&1; then
    rsync -aL --files-from="${file_list}" "${OUT_DIR%/}/" "${TMP_DIR%/}/"
  else
    while IFS= read -r rel; do
      [ -n "${rel}" ] || continue
      [ -f "${OUT_DIR}/${rel}" ] || continue
      mkdir -p "$(dirname "${TMP_DIR}/${rel}")"
      cp -L "${OUT_DIR}/${rel}" "${TMP_DIR}/${rel}"
    done <"${file_list}"
  fi
  awk '$0 != "build.ninja"' "${file_list}" >"${MANIFEST}"
  rm -f "${file_list}"

  link_tmpfs
  backup_tmpfs
}

backup_tmpfs() {
  if [ ! -d "${TMP_DIR}" ]; then
    echo "missing TMP_DIR: ${TMP_DIR}" >&2
    exit 1
  fi
  mkdir -p "${BACKUP_DIR}"
  if [ ! -s "${MANIFEST}" ]; then
    manifest_from_tmpfs >"${MANIFEST}"
  fi
  sync_tree "${TMP_DIR}" "${BACKUP_DIR}/ninja-tmpfs"
  date -Is >"${BACKUP_DIR}/last-backup.txt"
}

restore_tmpfs() {
  if [ ! -d "${BACKUP_DIR}/ninja-tmpfs" ]; then
    echo "missing backup: ${BACKUP_DIR}/ninja-tmpfs" >&2
    exit 1
  fi
  mkdir -p "${TMP_DIR}"
  sync_tree "${BACKUP_DIR}/ninja-tmpfs" "${TMP_DIR}"

  local manifest_file=${MANIFEST}
  if [ ! -s "${manifest_file}" ]; then
    manifest_file=$(mktemp)
    manifest_from_tmpfs >"${manifest_file}"
  fi

  { printf '%s\n' build.ninja; cat "${manifest_file}"; } | while IFS= read -r rel; do
    [ -n "${rel}" ] || continue
    [ -f "${TMP_DIR}/${rel}" ] || continue
    mkdir -p "$(dirname "${OUT_DIR}/${rel}")"
    ln -sfn "${TMP_DIR}/${rel}" "${OUT_DIR}/${rel}"
  done
}

status() {
  echo "OUT_DIR=${OUT_DIR}"
  echo "TMP_DIR=${TMP_DIR}"
  echo "BACKUP_DIR=${BACKUP_DIR}"
  printf 'tmpfs files: '
  if [ -d "${TMP_DIR}" ]; then
    find "${TMP_DIR}" -type f 2>/dev/null | wc -l
  else
    echo 0
  fi
  printf 'manifest ninja files: '; manifest_for_status | wc -l
  printf 'root regular ninja files: '
  if [ -d "${OUT_DIR}" ]; then
    find "${OUT_DIR}" -maxdepth 1 -type f -name '*.ninja' 2>/dev/null | wc -l
  else
    echo 0
  fi
  if [ "${AURADE_NINJA_STATUS_DU:-0}" = "1" ]; then
    [ -d "${TMP_DIR}" ] && du -sh "${TMP_DIR}" || true
    [ -d "${BACKUP_DIR}" ] && du -sh "${BACKUP_DIR}" || true
  fi
  [ -f "${BACKUP_DIR}/last-backup.txt" ] && cat "${BACKUP_DIR}/last-backup.txt"
  return 0
}

cmd=${1:-}
case "${cmd}" in
  status)
    status
    ;;
  prepare-gen)
    prepare_gen_targets
    status
    ;;
  link)
    link_tmpfs
    status
    ;;
  seed)
    seed_tmpfs_from_out
    status
    ;;
  backup)
    backup_tmpfs
    status
    ;;
  restore)
    restore_tmpfs
    status
    ;;
  run)
    shift
    [ "${1:-}" = "--" ] && shift
    [ "$#" -gt 0 ] || { usage; exit 2; }
    "$@"
    backup_tmpfs
    ;;
  *)
    usage
    exit 2
    ;;
esac
