#!/usr/bin/env bash
# What lets the Files window reach the service on loopback, and what keeps
# that opening narrow.
#
# Two separate things had to change and both have to stay. chrome://file-manager
# carries WebUI bindings, so unless its host is on the network-request
# allowlist the frame's default subresource factory is WebUIURLLoaderFactory,
# which does not refuse a foreign scheme: it reports a bad Mojo message and the
# renderer is killed. And a trusted chrome:// source sets neither default-src
# nor connect-src, so the allowlist entry on its own would leave this page able
# to reach any address on the internet. The patch has to carry both halves.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
PATCH="$ROOT/patches/0089-files-the-window-may-reach-the-service.patch"

fail() { echo "files window reaches the service test: $*" >&2; exit 1; }

[[ -r $PATCH ]] || fail 'patch 0089 is missing'
grep -Fqx '0089-files-the-window-may-reach-the-service.patch' "$ROOT/patches/SERIES" || \
  fail 'patch 0089 is not listed in SERIES'

# Only the added lines, and only the code among them: a grep for a symbol
# passes just as happily on the comment that explains the symbol.
added=$(grep '^+' "$PATCH" | grep -v '^+++' | sed 's/^+//')
[[ -n $added ]] || fail 'patch 0089 adds nothing'
code=$(grep -v '^[[:space:]]*//' <<<"$added")
[[ -n $code ]] || fail 'patch 0089 adds only comments'

# 1. The allowlist gains the Files host, as a term of the returned expression
# rather than as prose.
grep -Eq '^[[:space:]]*\|\|[[:space:]]*origin\.host\(\) == ash::file_manager::kChromeUIFileManagerHost' \
  <<<"$code" || fail 'the Files host is not added to IsWebUIAllowedToMakeNetworkRequests as a real term'

# 2. And the connect-src that keeps the opening to loopback. Both the
# directive and the source have to be in the code, not the comment. The
# value is split across adjacent C++ string literals, so it is joined back
# together before being read, and then read as a list of sources rather
# than searched for substrings: "http:" is a source of its own meaning
# every http origin, and it is also a prefix of the one source that is
# wanted, so a substring test cannot tell them apart.
grep -Fq 'CSPDirectiveName::ConnectSrc' <<<"$code" || \
  fail 'no connect-src override, so the allowlist would open the whole network'
csp=$(grep -o '"[^"]*"' <<<"$code" | tr -d '"' | tr -d '\n' \
      | grep -o 'connect-src[^;]*' | head -1)
[[ -n $csp ]] || fail 'the connect-src directive has no value'
read -r -a sources <<<"$csp"
unset "sources[0]"
[[ ${#sources[@]} -gt 0 ]] || fail "the connect-src has no sources: $csp"
loopback=0
for src in "${sources[@]}"; do
  case "$src" in
    "'self'"|blob:|data:|chrome://*) ;;
    http://127.0.0.1:*|http://\[::1\]:*) loopback=1 ;;
    *) fail "the connect-src names a source wider than loopback: $src (in: $csp)" ;;
  esac
done
(( loopback )) || fail "the connect-src does not permit the service on loopback: $csp"

# 4. Both halves in one patch. Splitting them across the series would let the
# allowlist land without the directive that narrows it.
files=$(grep -oE '^\+\+\+ b/.*' "$PATCH" | sed 's|^+++ b/||' | sort)
for want in ash/webui/file_manager/file_manager_ui.cc \
            chrome/browser/ui/webui/chrome_web_ui_controller_factory.cc; do
  grep -Fqx "$want" <<<"$files" || fail "patch 0089 does not touch $want"
done

echo "files window reaches the service test: ok"
