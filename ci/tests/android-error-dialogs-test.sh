#!/usr/bin/env bash
# Android's dialog for an app that stopped responding never reaches the
# desktop yet takes all input, so the service turns those dialogs off at
# every start, and only writes the setting when it is not already on.
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)

python3 -I - "$ROOT/aurade-android/aurade-android" <<'PY'
import importlib.machinery, importlib.util, sys
path = sys.argv[1]
loader = importlib.machinery.SourceFileLoader("aurade_android", path)
spec = importlib.util.spec_from_loader("aurade_android", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)
mod.log = lambda m: None

class Done:
    stderr = ""
    def __init__(self, out):
        self.stdout = out

value = {"v": "null"}
shell = []
def guest(*args, **kw):
    shell.append(args)
    if args[1] == "get":
        return Done(value["v"] + "\n")
    if args[1] == "put":
        value["v"] = args[4]
    return Done("")

def check(name, cond):
    if not cond:
        print("android error dialogs: FAIL", name, shell); sys.exit(1)

obj = object.__new__(mod.Android)
obj.guest = guest
obj.hide_error_dialogs()
check("a fresh Android gets the dialogs turned off", value["v"] == "1")
shell.clear()
obj.hide_error_dialogs()
check("the setting is not written again", not any(a[1] == "put" for a in shell))
check("each start runs it", "self.hide_error_dialogs()" in open(path).read().split("def ensure_bridge", 1)[1].split("def skip_setup_wizard", 1)[0])
print("android error dialogs: PASS")
PY
