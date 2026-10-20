#!/usr/bin/env bash
# Android takes the desktop's time zone when it starts and follows a change
# made later, with its own detection turned off; a zone it already has is not
# set again, and a name that is not a time zone is never passed on.
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)

python3 -I - "$ROOT/aurade-android/aurade-android" <<'PY'
import importlib.machinery, importlib.util, sys, threading
path = sys.argv[1]
loader = importlib.machinery.SourceFileLoader("aurade_android", path)
spec = importlib.util.spec_from_loader("aurade_android", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)
mod.log = lambda m: None

def check(name, cond):
    if not cond:
        print("android time zone: FAIL", name, shell); sys.exit(1)

class Live:
    def poll(self):
        return None

class Done:
    stderr = ""
    def __init__(self, out):
        self.stdout = out

state = {"persist.sys.timezone": "GMT", "auto_time_zone": "1"}
shell = []
def guest(*args, **kw):
    shell.append(args)
    if args[0].endswith("getprop"):
        return Done(state[args[1]] + "\n")
    if args[0].endswith("settings") and args[1] == "get":
        return Done(state[args[3]] + "\n")
    if args[0].endswith("settings") and args[1] == "put":
        state[args[3]] = args[4]
    if args[0].endswith("cmd") and args[1:3] == ("alarm", "set-timezone"):
        state["persist.sys.timezone"] = args[3]
    return Done("")

obj = object.__new__(mod.Android)
obj.guest = guest
obj.session = (1000, Live())
host_time_zone = mod.host_time_zone
mod.host_time_zone = lambda: "America/Chicago"

obj.sync_time_zone()
check("start gives Android the desktop's zone", state["persist.sys.timezone"] == "America/Chicago")
check("and turns its own detection off", state["auto_time_zone"] == "0")
check("detection goes off before the zone is set",
      [a[1] for a in shell if a[1] in ("put", "alarm")] == ["put", "alarm"])

shell.clear()
obj.sync_time_zone()
check("a zone Android already has is not set again", not any(a[1] in ("put", "alarm") for a in shell))

threads = []
real_thread = threading.Thread
class Now(real_thread):
    def start(self):
        threads.append(self)
        self.run()
mod.threading.Thread = Now
obj.on_timedate("org.freedesktop.timedate1", {"Timezone": "Europe/Berlin"}, [])
check("a change on the desktop reaches a running Android", state["persist.sys.timezone"] == "Europe/Berlin")

obj.on_timedate("org.freedesktop.timedate1", {"NTP": True}, [])
obj.on_timedate("org.freedesktop.timedate1", {"Timezone": "Europe/Berlin; reboot"}, [])
check("other properties and a bad name are ignored", len(threads) == 1)

obj.session = None
obj.on_timedate("org.freedesktop.timedate1", {"Timezone": "Asia/Tokyo"}, [])
check("nothing runs while Android is off", len(threads) == 1)

import os
real_readlink = os.readlink
for target, want in [("/usr/share/zoneinfo/America/Chicago", "America/Chicago"),
                     ("../usr/share/zoneinfo/UTC", "UTC"),
                     ("/usr/share/zoneinfo/posix/Asia/Kolkata", "Asia/Kolkata"),
                     ("/usr/share/zoneinfo/Etc/GMT+5", "Etc/GMT+5"),
                     ("/usr/share/zoneinfo/../../../etc/shadow", None),
                     ("/opt/somewhere/else", None)]:
    os.readlink = lambda p, t=target: t
    got = host_time_zone()
    check(f"{target} reads as {want} (got {got})", got == want)
os.readlink = real_readlink
print("android time zone: PASS")
PY
