#!/bin/bash
# Build the Files window into an output directory.
#
# Writes files.html and files.js from files-app/. The build is deterministic:
# the same sources give the same two files, byte for byte, whatever machine
# ran it and whenever. See files-app/README.md for what ship mode changes and
# why the script path matters.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SOURCE_DIR="${REPO_ROOT}/files-app"

usage() {
  echo "usage: $(basename "$0") <output directory>" >&2
  echo >&2
  echo "  AURADE_FILES_PAGE_SCRIPT   the path the page's script tag asks for" >&2
  echo "                             (default files.js)" >&2
  exit 2
}

[ $# -eq 1 ] || usage
OUT_DIR="$1"

command -v python3 >/dev/null 2>&1 || {
  echo "Missing required command: python3" >&2
  exit 2
}
[ -f "${SOURCE_DIR}/build_v3.py" ] || {
  echo "ERROR: ${SOURCE_DIR} is not the Files window source" >&2
  exit 1
}

mkdir -p "${OUT_DIR}"
OUT_DIR="$(cd "${OUT_DIR}" && pwd)"

# The builder writes nothing else and reads nothing of this machine in ship
# mode, so it can run from the source directory without leaving anything in it.
cd "${SOURCE_DIR}"
AURADE_SHIP="${OUT_DIR}" \
AURADE_SHIP_SCRIPT="${AURADE_FILES_PAGE_SCRIPT:-files.js}" \
  python3 build_v3.py >/dev/null

for produced in files.html files.js; do
  [ -s "${OUT_DIR}/${produced}" ] || {
    echo "ERROR: the build produced no ${produced}" >&2
    exit 1
  }
done

echo "built ${OUT_DIR}/files.html and ${OUT_DIR}/files.js"
