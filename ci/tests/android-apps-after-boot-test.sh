#!/usr/bin/env bash
# Ash asks for the app list as soon as it turns Android on, before Android has
# booted, and gets nothing. The service has to tell it the apps changed once
# the boot is done, even when the installed packages are the same as before.
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

class Alive:
    pid = 1
    def poll(self):
        return None

state = {"booted": "0"}
def guest(*args, **kw):
    if args[0] == "/system/bin/getprop":
        return Done(state["booted"] + "\n")
    if args[:2] == ("/system/bin/pm", "list"):
        return Done("package:com.cron.calendar versionCode:1\n")
    raise AssertionError(args)

changed = []
obj = object.__new__(mod.Android)
obj.guest = guest
obj.session = (1000, Alive())
obj.sync_gamepads = lambda: None
obj.logcat = Alive()
obj.log_src = 1
obj.AppsChanged = lambda: changed.append(1)

def check(name, cond):
    if not cond:
        print("android apps after boot: FAIL", name, changed); sys.exit(1)

def start():
    obj.apps_seen = None
    obj.apps_booted = False

start()
obj.poll_apps()
check("nothing is reported while Android boots", changed == [])
state["booted"] = "1"
obj.poll_apps()
check("the first list after the boot is reported", changed == [1])
obj.poll_apps()
check("an unchanged list is not reported again", changed == [1])

# Turned off and on again: same packages, a new boot.
state["booted"] = "0"
start()
obj.poll_apps()
state["booted"] = "1"
obj.poll_apps()
check("a restart reports the apps again", changed == [1, 1])
check("the watchers reset the boot", "self.apps_booted = False" in open(path).read().split("def start_watchers", 1)[1].split("def ", 1)[0])
print("android apps after boot: PASS")
PY
