#!/usr/bin/env bash
# A file dragged from the desktop onto an Android window reaches that app as a
# share, and only the window layer is believed about what was dropped: a log
# line any app can write does not hand over files.
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
printf 'hello' > "$TMP/hello world.txt"

python3 -I - "$ROOT/aurade-android/aurade-android" "$TMP" <<'PY'
import importlib.machinery, importlib.util, os, subprocess, sys
path, tmp = sys.argv[1:3]
loader = importlib.machinery.SourceFileLoader("aurade_android", path)
spec = importlib.util.spec_from_loader("aurade_android", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)
logged, shell, staged = [], [], []
mod.log = logged.append
mod.GLib.idle_add = lambda fn: fn()

class Live:
    def poll(self):
        return None

class Done:
    stdout, stderr = "", ""

A = mod.Android
obj = object.__new__(A)
obj.session = (0, Live())
obj.log_buf = ""
obj.hwc_pid = lambda: 242
obj.stage_inbox = lambda uid, p: (staged.append(p), ("tok", "hello_world.txt"))[1]
replies = []
def guest(*args, **kw):
    shell.append(args)
    r = Done()
    r.stdout = replies.pop(0) if replies else ""
    return r
obj.guest = guest
real_run = subprocess.run
subprocess.run = lambda cmd, **kw: real_run(["true"] if cmd[0] == "runuser" and "-r" in cmd and os.path.isfile(cmd[-1]) else ["false"], **kw)

def feed(line):
    r, w = os.pipe()
    os.write(w, (line + "\n").encode())
    os.close(w)
    obj.on_log(r, mod.GLib.IO_IN)
    os.close(r)

def check(name, cond):
    if not cond:
        print("android drop: FAIL", name, logged, shell, staged); sys.exit(1)

uri = "file://" + tmp.replace(" ", "%20") + "/hello%20world.txt"
feed(f"I/AuraDEDnd(  999): files app=org.example.notes {uri}")
check("a line from another process is not believed", not shell and not staged)
check("and is reported", any("did not come from the window layer" in m for m in logged))

feed(f"I/AuraDEDnd(  242): files app=org.example.notes {uri} https://example.invalid/x file://remote.example/etc/passwd file:///nonexistent")
sends = [a for a in shell if "android.intent.action.SEND" in a]
check("the dropped file is shared to the app under it", len(sends) == 1 and "-p" in sends[0]
      and sends[0][sends[0].index("-p") + 1] == "org.example.notes")
check("as a content address from the inbox", "content://org.aurade.bridge.inbox/tok/hello_world.txt" in sends[0])
check("with its type", "text/plain" in sends[0])
check("only the one local readable file", staged == [f"{tmp}/hello world.txt"])

shell.clear(); staged.clear()
replies[:] = ["Error: Activity not started, unable to resolve Intent"]
feed(f"I/AuraDEDnd(  242): files app=org.example.viewer {uri}")
check("an app with no share target is asked to view it", any("android.intent.action.VIEW" in a for a in shell))

shell.clear()
feed(f"I/AuraDEDnd(  242): files app= {uri}")
check("a window with no app gets nothing", not shell)
print("android drop test: PASS")
PY
