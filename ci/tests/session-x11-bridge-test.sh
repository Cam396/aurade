#!/usr/bin/env bash
# X11 applications reach exo through xwayland-satellite, which the session
# child starts for each desktop once that desktop's exo socket exists. Run the
# real child against a stub desktop and a stub bridge, so this checks what the
# session does rather than what its source says.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
CHILD="$ROOT/chromiumos-ash/chromiumos-ash-session-child.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fail() { echo "session x11 bridge test: $*" >&2; exit 1; }

[[ -r $CHILD ]] || fail 'the session child script is missing'
mkdir -p "$TMP/bin" "$TMP/run" "$TMP/sockets" "$TMP/locks"
EVENTS="$TMP/events"

# The bridge says when it starts and on what, and when it is stopped.
cat >"$TMP/bin/xwayland-satellite" <<'STUB'
#!/bin/bash
echo "bridge start $1 wayland=${WAYLAND_DISPLAY:-}" >>"$AURADE_TEST_EVENTS"
# Asked to, it puts up the X socket the way Xwayland would.
xsocket="${AURADE_X11_SOCKET_DIR}/X${1#:}"
if [ -n "${AURADE_TEST_XSOCKET:-}" ]; then
  python3 -c 'import socket,sys; s=socket.socket(socket.AF_UNIX); s.bind(sys.argv[1])' "$xsocket"
fi
trap 'rm -f "$xsocket"; echo "bridge stopped $1" >>"$AURADE_TEST_EVENTS"; exit 0' TERM
while :; do sleep 0.1; done
STUB
# The desktop says which display it was given, puts up an exo socket as Ash
# does, gives the bridge a moment to find it, and takes it down on the way out.
cat >"$TMP/stub-desktop" <<'STUB'
#!/bin/bash
echo "desktop display=${AURADE_HOST_APP_X11_DISPLAY:-none}" >>"$AURADE_TEST_EVENTS"
python3 -c 'import socket,sys; s=socket.socket(socket.AF_UNIX); s.bind(sys.argv[1])' \
    "$XDG_RUNTIME_DIR/wayland-0"
sleep 3
rm -f "$XDG_RUNTIME_DIR/wayland-0"
exit 0
STUB
# xrdb says what it merged and how. Told to, it fails unless it is spared
# the preprocessor, as it does where cpp is not installed.
cat >"$TMP/bin/xrdb" <<'STUB'
#!/bin/bash
nocpp=no
[ "$1" = -nocpp ] && { nocpp=yes; shift; }
if [ -n "${AURADE_TEST_NO_CPP:-}" ] && [ "$nocpp" = no ]; then exit 1; fi
echo "xrdb $1 $2 display=${DISPLAY:-} nocpp=$nocpp" >>"$AURADE_TEST_EVENTS"
STUB
chmod 0755 "$TMP/bin/xwayland-satellite" "$TMP/stub-desktop" "$TMP/bin/xrdb"

session() {
  : >"$EVENTS"
  env -i PATH="${SESSION_PATH:-$TMP/bin:$PATH}" HOME="$TMP/home" \
      XDG_STATE_HOME="$TMP/state" XDG_RUNTIME_DIR="$TMP/run" \
      AURADE_TEST_EVENTS="$EVENTS" \
      AURADE_X11_SOCKET_DIR="$TMP/sockets" AURADE_X11_LOCK_DIR="$TMP/locks" \
      AURADE_CHROME_COMMAND="$TMP/stub-desktop" \
      AURADE_SESSION_ERROR="$TMP/nonexistent-error-handler" \
      AURADE_REMOVABLE_AUTOMOUNT=0 AURADE_SESSION_ON_EXIT=exit \
      AURADE_RESTART_DELAY=0 AURADE_X11_RESOURCES="$TMP/defaults" \
      "$@" bash "$CHILD" >"$TMP/console" 2>&1 || true
}

# 1. With a GPU, the desktop is handed the display, and the bridge serves it on
# that desktop's exo, then stops when the desktop does.
session
grep -Fxq 'desktop display=:0' "$EVENTS" || fail "the desktop was not handed :0: $(cat "$EVENTS")"
grep -Fxq 'bridge start :0 wayland=wayland-0' "$EVENTS" || \
  fail "the bridge did not start on the desktop's exo: $(cat "$EVENTS")"
grep -Fxq 'bridge stopped :0' "$EVENTS" || fail 'the bridge outlived its desktop'

# 2. Displays already taken, by a socket or a lock, are skipped.
touch "$TMP/sockets/X0" "$TMP/locks/.X1-lock"
session
grep -Fxq 'desktop display=:2' "$EVENTS" || fail "a taken display was reused: $(cat "$EVENTS")"
rm -f "$TMP/sockets/X0" "$TMP/locks/.X1-lock"

# 3. Each desktop gets its own bridge, on the same display, and each is stopped.
session AURADE_SESSION_ON_EXIT=restart AURADE_MAX_FAST_RESTARTS=2
[[ $(grep -c '^bridge start :0 ' "$EVENTS") -eq 2 ]] || \
  fail "a restarted desktop did not get a bridge of its own: $(cat "$EVENTS")"
[[ $(grep -c '^bridge stopped :0$' "$EVENTS") -eq 2 ]] || fail 'a bridge was left running across a restart'
[[ $(grep -c '^desktop display=:0$' "$EVENTS") -eq 2 ]] || fail 'the display changed across a restart'

# 4. Drawing in software there is no exo, so no display is offered and nothing
# is started that could only fail.
session AURADE_SOFTWARE_RENDERING=1
grep -Fxq 'desktop display=none' "$EVENTS" || fail 'a display was offered with no exo to serve it'
if grep -q '^bridge' "$EVENTS"; then fail 'a bridge was started in software rendering'; fi

# 5. Without xwayland-satellite installed the desktop still starts, offered
# nothing.
mkdir -p "$TMP/nobridge"
for tool in python3 bash sleep rm seq date mkdir mv wc awk stat flock cat id; do
  path=$(command -v "$tool" 2>/dev/null) && ln -sf "$path" "$TMP/nobridge/$tool"
done
SESSION_PATH="$TMP/nobridge" session
grep -Fxq 'desktop display=none' "$EVENTS" || fail "a display was offered with no bridge installed: $(cat "$EVENTS")"

# 6. Once the X server is up, AuraDE's defaults are merged into it and then
# the user's own ~/.Xresources, so the user's win; without cpp both still load.
echo 'XTerm*faceSize: 11' >"$TMP/defaults"
mkdir -p "$TMP/home"
echo 'XTerm*faceSize: 14' >"$TMP/home/.Xresources"
session AURADE_TEST_XSOCKET=1
grep -q '^xrdb ' "$EVENTS" || fail "nothing was merged into the X server: $(cat "$EVENTS")"
[[ $(grep '^xrdb ' "$EVENTS" | head -1) == "xrdb -merge $TMP/defaults display=:0 nocpp=no" ]] || \
  fail "AuraDE's defaults were not merged first: $(cat "$EVENTS")"
[[ $(grep '^xrdb ' "$EVENTS" | sed -n 2p) == "xrdb -merge $TMP/home/.Xresources display=:0 nocpp=no" ]] || \
  fail "the user's ~/.Xresources was not merged after the defaults: $(cat "$EVENTS")"
session AURADE_TEST_XSOCKET=1 AURADE_TEST_NO_CPP=1
[[ $(grep -c '^xrdb .* nocpp=yes$' "$EVENTS") -eq 2 ]] || \
  fail "without cpp the resources were not loaded: $(cat "$EVENTS")"
rm -f "$TMP/home/.Xresources"

# 7. GTK 4 apps are pointed at AuraDE's stylesheet through the user's gtk.css,
# made only when there is none; one the user has, even emptied, is theirs.
echo 'windowcontrols {}' >"$TMP/gtk4.css"
session AURADE_GTK4_STYLE="$TMP/gtk4.css"
grep -Fxq "@import url(\"file://$TMP/gtk4.css\");" "$TMP/home/.config/gtk-4.0/gtk.css" 2>/dev/null || \
  fail "the user's gtk.css does not import AuraDE's style: $(cat "$TMP/home/.config/gtk-4.0/gtk.css" 2>&1)"
: >"$TMP/home/.config/gtk-4.0/gtk.css"
session AURADE_GTK4_STYLE="$TMP/gtk4.css"
[[ ! -s $TMP/home/.config/gtk-4.0/gtk.css ]] || fail "the user's own gtk.css was overwritten"

echo 'session x11 bridge test: PASS (handed to the desktop, served on its exo, skips taken displays, one per desktop, none in software or without the bridge, X defaults then the user'"'"'s, GTK style only where the user has none)'
