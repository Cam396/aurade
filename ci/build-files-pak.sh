#!/bin/bash
# Put the Files window into a built resources.pak.
#
# The page is a resource rather than something compiled into Chromium, so this
# is the step that gets it into a release, and it belongs in the build. Twice
# now a pak has been made by hand and shipped a page that drew perfectly and
# ran nothing: 03f784d on the test VM, and the 154 pak of 2026-09-15. Both
# named the script foreground/js/main.rollup.js, which is what the resource is
# called and not where it is served, and both went around the path rule in
# ci/pak-set-resources.py to do it. Nothing here passes --allow-new-paths: if
# the tool refuses, the script path is wrong and the refusal is the answer.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

usage() {
  echo "usage: $(basename "$0") <chromium output directory>" >&2
  echo >&2
  echo "  AURADE_FILES_PAGE_SCRIPT  the path the Files app serves the page's" >&2
  echo "                            script at (default foreground/js/main.js)" >&2
  exit 2
}
[ $# -eq 1 ] || usage

OUT_DIR="$(cd "$1" && pwd)"
PAK="${OUT_DIR}/resources.pak"
STOCK="${PAK}.pre-aurade"

# The one thing here that cannot be derived. A pak records no paths at all, and
# the resource is named IDR_..._MAIN_ROLLUP_JS while the data source serves it
# at foreground/js/main.js, so the name is not the path and never was.
SCRIPT_PATH="${AURADE_FILES_PAGE_SCRIPT:-foreground/js/main.js}"

[ -f "${PAK}" ] || { echo "ERROR: no resources.pak in ${OUT_DIR}" >&2; exit 1; }
for tool in "${REPO_ROOT}/ci/build-files-page.sh" "${REPO_ROOT}/ci/pak-set-resources.py"; do
  [ -r "${tool}" ] || { echo "ERROR: ${tool} is missing" >&2; exit 1; }
done

carries_page() {  # pak -> 0 if the AuraDE page is already in it
  python3 - "$1" <<'PY'
import gzip, struct, sys
d = open(sys.argv[1], "rb").read()
count, = struct.unpack_from("<H", d, 8)
ents = [struct.unpack_from("<HI", d, 12 + i * 6) for i in range(count + 1)]
for i in range(count):
    p = d[ents[i][1]:ents[i + 1][1]]
    if p[:2] == b"\x1f\x8b":
        try:
            p = gzip.decompress(p)
        except Exception:
            continue
    if b'data-path="~"' in p:
        sys.exit(0)
sys.exit(1)
PY
}

# Injecting twice must be the same as injecting once, so the stock pak is kept
# beside the build and every run starts from it. Taking that copy from a pak
# that already holds the page would make the page its own baseline and there
# would be no way back to the SWA's own.
if [ -f "${STOCK}" ]; then
  cp -a "${STOCK}" "${PAK}"
elif carries_page "${PAK}"; then
  echo "ERROR: ${PAK} already carries the Files page and ${STOCK} is missing," >&2
  echo "       so the stock pak cannot be recovered. Rebuild it with ninja." >&2
  exit 1
else
  cp -a "${PAK}" "${STOCK}"
fi

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

AURADE_FILES_PAGE_SCRIPT="${SCRIPT_PATH}" \
  "${REPO_ROOT}/ci/build-files-page.sh" "${WORK}/page" >/dev/null

python3 "${REPO_ROOT}/ci/pak-set-resources.py" "${STOCK}" "${WORK}/resources.pak" \
  --set "chrome://file-manager/init_globals.js=${WORK}/page/files.html" \
  --set "auraDeExactTime=${WORK}/page/files.js" \
  --expect "files.html:data-path=\"~\"" \
  --expect "files.html:${SCRIPT_PATH}"

# Only now over the build's own pak, so a refusal above leaves it untouched.
install -m 644 "${WORK}/resources.pak" "${PAK}"
carries_page "${PAK}" || {
  echo "ERROR: the written pak does not carry the page" >&2
  cp -a "${STOCK}" "${PAK}"
  exit 1
}
echo "Files page placed into ${PAK} (script at ${SCRIPT_PATH})"
