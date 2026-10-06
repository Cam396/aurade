#!/usr/bin/env bash
# aurade-open-url, what xdg-open runs for a link: web pages and files become
# tabs through org.aurade.Browser, on the desktop's bus, and nothing else is
# sent there.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
OPEN=$ROOT/chromiumos-ash/aurade-open-url
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fail() { echo "aurade-open-url test: $*" >&2; exit 1; }

mkdir -p "$TMP/bin" "$TMP/run/aurade" "$TMP/cwd"
cat >"$TMP/bin/busctl" <<'STUB'
#!/usr/bin/env bash
printf '%s|%s\n' "$DBUS_SESSION_BUS_ADDRESS" "$*" >>"$CALLS"
STUB
chmod +x "$TMP/bin/busctl"
printf 'DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/desktop-bus\nOTHER=1\n' >"$TMP/run/aurade/app-environment"
: >"$TMP/cwd/notes 50% #1?.html"

open_url() {
  : >"$TMP/calls"
  (cd "$TMP/cwd" && CALLS=$TMP/calls PATH=$TMP/bin:$PATH XDG_RUNTIME_DIR=$TMP/run \
    DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/user-bus sh "$OPEN" "$@") 2>"$TMP/err"
}
sent() { sed -n 's/.*OpenURL s //p' "$TMP/calls"; }

open_url https://example.org/a?b=1#c || fail 'a web page was refused'
grep -q '^unix:path=/tmp/desktop-bus|--user call org.aurade.Browser /org/aurade/Browser org.aurade.Browser OpenURL s ' "$TMP/calls" ||
  fail "the call did not go to the desktop's bus: $(cat "$TMP/calls")"
[[ $(sent) == 'https://example.org/a?b=1#c' ]] || fail "a web address was changed: $(sent)"

open_url '/home/a/page one.html' || fail 'an absolute file was refused'
[[ $(sent) == 'file:///home/a/page one.html' ]] || fail "an absolute file became: $(sent)"

open_url 'notes 50% #1?.html' || fail 'a file in the current folder was refused'
[[ $(sent) == "file://$TMP/cwd/notes 50%25 %231%3F.html" ]] ||
  fail "a file name with %, # and ? was not escaped: $(sent)"

if open_url 'javascript:alert(1)'; then fail 'javascript: was accepted'; fi
[[ ! -s $TMP/calls ]] || fail "javascript: reached the browser: $(cat "$TMP/calls")"
if open_url 'mailto:someone@example.org'; then fail 'mailto: was accepted'; fi
[[ ! -s $TMP/calls ]] || fail "mailto: reached the browser as a file: $(cat "$TMP/calls")"

# One bad argument does not stop the others.
if open_url 'mailto:x' https://example.org/; then fail 'a refused argument did not fail the run'; fi
[[ $(sent) == 'https://example.org/' ]] || fail "the good argument after a bad one was dropped: $(sent)"

echo 'aurade-open-url test: PASS (desktop bus, web pages untouched, files escaped, other schemes refused)'
