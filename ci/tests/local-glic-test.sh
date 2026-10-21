#!/usr/bin/env bash
# Glic answered by Gemma on this computer.
#
# Three pieces have to agree. Patch 0160 lets a switch stand in for the
# Google account checks and lets the guest load over plain HTTP, but only
# from the guest origin on loopback. The launcher passes that switch and the
# guest URL when ai.conf asks for local Glic. aurade-glic.socket listens on
# the port the URL names. A rename or a new port on one side leaves the
# panel blank, and a looser origin check would let any HTTP page in the
# panel read the user's tabs.
#
# Then the server: it serves only its own files, and every page carries a
# fresh script nonce in both the page and its CSP, which is what lets the
# page run the Glic API Chrome sends it and nothing else.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCHES="$ROOT/patches"
PATCH=0160-glic-can-answer-with-gemma-on-this-computer.patch
LAUNCHER="$ROOT/chromiumos-ash/chromiumos-ash.sh"
AI="$ROOT/aurade-ai"
SWITCH=aurade-glic-local

fail() { echo "local glic test: $*" >&2; exit 1; }

# The code a patch adds to one file, without its comments.
code_in() {
  awk -v want="+++ b/$2" '
    /^diff --git / { on = 0; next }
    /^\+\+\+ / { on = ($0 == want); next }
    on && /^\+/ { print substr($0, 2) }
  ' "$1" | grep -v '^[[:space:]]*//' || true
}

[[ -r $PATCHES/$PATCH ]] || fail "patch 0160 is missing"
grep -Fxq "$PATCH" "$PATCHES/SERIES" || fail "patch 0160 is not listed in SERIES"

enabling=$(code_in "$PATCHES/$PATCH" chrome/browser/glic/public/glic_enabling.cc)
grep -Fq "\"$SWITCH\"" <<<"$enabling" || \
  fail "0160 no longer names --$SWITCH in glic_enabling.cc"
grep -Fq '!command_line->HasSwitch(kAuraDeGlicLocalSwitch)' <<<"$enabling" || \
  fail '0160 no longer skips the account checks under the switch'

policy=$(code_in "$PATCHES/$PATCH" chrome/browser/glic/host/glic_pwc_policy_delegate.cc)
grep -Fq "\"$SWITCH\"" <<<"$policy" || \
  fail "0160 no longer names --$SWITCH in the guest policy"
grep -Fq 'origin.host() == "127.0.0.1"' <<<"$policy" || \
  fail '0160 lets plain HTTP in from somewhere other than loopback'
grep -Fq 'origin.IsSameOriginWith(GetGuestOrigin(profile_))' <<<"$policy" || \
  fail '0160 lets plain HTTP in from an origin other than the guest'

# The launcher: the same switch, the guest URL on the socket's port, and
# only when ai.conf asks for it.
grep -Fq -- "--$SWITCH" "$LAUNCHER" || fail "the launcher does not pass --$SWITCH"
url=$(grep -oE -- '--glic-guest-url=http://127\.0\.0\.1:[0-9]+/' "$LAUNCHER" || true)
[[ -n $url ]] || fail 'the launcher does not point Glic at a loopback page'
port=${url##*:}; port=${port%/}
listen=$(sed -n 's/^ListenStream=//p' "$AI/aurade-glic.socket")
[[ $listen == "127.0.0.1:$port" ]] || \
  fail "the launcher uses port $port but aurade-glic.socket listens on $listen"
(( port < 1024 )) || fail "port $port is one any program can listen on"
grep -Fq '"${AURADE_GLIC:-web}" = "local"' "$LAUNCHER" || \
  fail 'the launcher no longer leaves Glic to Gemini unless asked'
grep -Fxq 'AURADE_GLIC=web' "$AI/aurade-ai.conf" || \
  fail 'ai.conf no longer defaults Glic to Gemini'

# The page: it takes the API only from Chrome's Glic panel, runs it with its
# nonce, and never parses model text as HTML.
js="$AI/glic.js"
grep -Fq "event.origin !== 'chrome://glic'" "$js" || \
  fail 'the page accepts the Glic API from any origin'
grep -Fq 'script.nonce = NONCE;' "$js" || fail 'the page runs the API without its nonce'
if grep -nE 'innerHTML|outerHTML|insertAdjacentHTML|document\.write' "$js"; then
  fail 'the page builds HTML from strings'
fi
grep -Fq 'nonce="{{nonce}}"' "$AI/glic-index.html" || fail 'the page has no nonce slot'

# The server, started the way the socket starts it, on the files laid out as
# the package installs them.
www=$(mktemp -d)
trap 'rm -rf "$www"' EXIT
cp "$AI/glic-index.html" "$www/index.html"
cp "$AI/glic.js" "$AI/glic.css" "$www/"
python3 -I - "$AI/aurade-glic-server" "$www" <<'PY'
import http.client, os, re, socket, subprocess, sys, time

server, root = sys.argv[1], sys.argv[2]
def fail(msg):
    print("local glic test:", msg, file=sys.stderr); sys.exit(1)

lsock = socket.socket()
lsock.bind(("127.0.0.1", 0))
lsock.listen(8)
port = lsock.getsockname()[1]
if lsock.fileno() != 3:
    os.dup2(lsock.fileno(), 3)
os.set_inheritable(3, True)
env = dict(os.environ, LISTEN_FDS="1", LISTEN_PID="", AURADE_GLIC_ROOT=root)
proc = subprocess.Popen([sys.executable, "-I", server], pass_fds=(3,), env=env)
if lsock.fileno() != 3:
    os.close(3)
lsock.close()
try:
    def get(path, method="GET"):
        for _ in range(50):
            try:
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                c.request(method, path)
                r = c.getresponse()
                return r.status, dict(r.getheaders()), r.read()
            except ConnectionRefusedError:
                time.sleep(0.1)
        fail("the server never answered")

    status, headers, body = get("/?authuser=a%40b&hl=en-US")
    if status != 200:
        fail("the page answered %d" % status)
    csp = headers.get("Content-Security-Policy", "")
    page = re.search(rb'nonce="([^"]+)"', body)
    if not page or page.group(1) == b"{{nonce}}":
        fail("the page went out without a nonce")
    if ("'nonce-%s'" % page.group(1).decode()) not in csp:
        fail("the page's nonce is not the one its CSP allows: " + csp)
    if "'unsafe-inline'" in csp or "'unsafe-eval'" in csp:
        fail("the CSP allows any inline script")
    if headers.get("X-Content-Type-Options") != "nosniff":
        fail("the page can be sniffed as another type")
    again = re.search(rb'nonce="([^"]+)"', get("/")[2]).group(1)
    if again == page.group(1):
        fail("two visits got the same nonce")
    for path in ("/glic.js", "/glic.css"):
        if get(path)[0] != 200:
            fail(path + " is not served")
    status, headers, body = get("/", "HEAD")
    if status != 200 or body:
        fail("HEAD does not answer with headers only")
    for path in ("/../aurade-glic-server", "/%2e%2e/aurade-glic-server",
                 "/..%2faurade-glic-server", "/glic/glic.js", "/.hidden.js",
                 "/missing.html", "/aurade-glic-server", "//etc/passwd"):
        if get(path)[0] != 404:
            fail(path + " is served")
    if get("/", "POST")[0] < 400:
        fail("POST is answered")
finally:
    proc.kill()
    proc.wait()

out = subprocess.run([sys.executable, "-I", server], env={}, capture_output=True, text=True)
if out.returncode == 0 or "aurade-glic.socket" not in out.stderr:
    fail("the server starts without the socket")
PY

echo "local glic test: PASS"
