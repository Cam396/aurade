#!/usr/bin/env bash
# The Files window builds from this tree, the same way twice, carrying
# nothing of the machine that built it.
#
# The page is a resource, not compiled into Chromium, so the package build is
# the only thing standing between these sources and a released file. Three
# things have to hold. The build is reproducible, or a release cannot be
# compared with a rebuild of its own sources. It names the script at the path
# it will be served at, because a pak records no paths and the wrong one gives
# a page that draws perfectly and runs nothing. And nothing of the build
# machine reaches the page: no path, no user, no host name, and no clock.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
BUILD="$ROOT/ci/build-files-page.sh"

fail() { echo "files page test: $*" >&2; exit 1; }

[[ -x $BUILD ]] || fail 'ci/build-files-page.sh is missing or not executable'
command -v python3 >/dev/null 2>&1 || fail 'python3 is not installed'

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# A date named rather than taken from the clock, and a script path that is not
# the default, so neither can pass by being what the builder would do anyway.
STAMP=1700000000
WANT_DATE=$(python3 -c "
import datetime
print(datetime.datetime.fromtimestamp($STAMP, datetime.timezone.utc).strftime('%-d %b %Y %H:%M'))")
SCRIPT_PATH='foreground/js/main.js'

build_into() {  # dir
    env SOURCE_DATE_EPOCH="$STAMP" \
        AURADE_FILES_PAGE_SCRIPT="$SCRIPT_PATH" \
        "$BUILD" "$1" >"$WORK/out.$(basename "$1")" 2>&1 || \
      fail "the build failed: $(cat "$WORK/out.$(basename "$1")")"
}

build_into "$WORK/one"
build_into "$WORK/two"

for produced in files.html files.js; do
    [[ -s $WORK/one/$produced ]] || fail "the build produced no ${produced}"
    cmp -s "$WORK/one/$produced" "$WORK/two/$produced" || \
      fail "two builds of the same sources differ in ${produced}"
done

# The script tag asks for the path it was given, and the page loads no other
# script: the data source's script-src is 'self' and an inline one would not run.
tags=$(grep -o '<script[^>]*>' "$WORK/one/files.html" || true)
[[ $tags == "<script src=\"$SCRIPT_PATH\">" ]] || \
  fail "the page's script tags are ${tags:-none}, not a single src=${SCRIPT_PATH}"

# No date but the one the build was given.
dates=$(grep -ohE '\b[0-9]{1,2} [A-Z][a-z]{2} [0-9]{4} [0-9]{2}:[0-9]{2}' \
          "$WORK/one/files.html" "$WORK/one/files.js" | sort -u || true)
[[ -n $dates ]] || fail 'the page carries no date at all, so this proves nothing'
while read -r line; do
    [[ $line == "$WANT_DATE" ]] || \
      fail "the page carries ${line}, which is not the date the build was given (${WANT_DATE})"
done <<<"$dates"

# Nothing of this machine: a home or scratch path, the user, the host, or the
# name of the temporary folder the builder opens on.
leaks=$(grep -ohE '/(root|home/[^/"'"'"'< ]+|mnt/[^"'"'"'< ]+|tmp/[^"'"'"'< ]+)' \
          "$WORK/one/files.html" "$WORK/one/files.js" | sort -u | head -5 || true)
[[ -z $leaks ]] || fail "the page names paths of the build machine: $(tr '\n' ' ' <<<"$leaks")"
# The user as a path element and not as a bare word: "root" is a word this
# page uses for other things, and /root is already covered above.
me=$(id -un)
for token in "aurade-ship-home" "/home/$me" "/Users/$me" "$(uname -n)"; do
    [[ ${#token} -gt 2 ]] || continue
    grep -qF -- "$token" "$WORK/one/files.html" "$WORK/one/files.js" && \
      fail "the page names ${token}, which belongs to the build machine"
done

# The window opens on the home the service resolves, not on a folder of this box.
grep -q 'data-path="~"' "$WORK/one/files.html" || \
  fail 'the shipped window does not open on ~'

if command -v node >/dev/null 2>&1; then
    node --check "$WORK/one/files.js" >/dev/null 2>&1 || \
      fail 'the shipped script does not parse'
fi

echo 'files page test: PASS'
