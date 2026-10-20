#!/usr/bin/env bash
# Android's own screens behind the windows (the desktop wallpaper, the home
# screen) are tasks too. The window layer never shows them, so the service
# must not tell Ash about them, or the shelf gets an app with no window.
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)

python3 -I - "$ROOT/aurade-android/aurade-android" <<'PY'
import importlib.machinery, importlib.util, os, sys
path = sys.argv[1]
loader = importlib.machinery.SourceFileLoader("aurade_android", path)
spec = importlib.util.spec_from_loader("aurade_android", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)
mod.log = lambda m: None

created = []
obj = object.__new__(mod.Android)
obj.log_buf = ""
obj.TaskCreated = lambda tid, pkg, act: created.append((tid, pkg, act))
obj.TaskDestroyed = lambda tid: None

r, w = os.pipe()
os.write(w, (
    "I/WayDroidService(  630): taskCreated 14 \n"
    "I/WayDroidService(  630): taskCreated 14 com.cron.calendar/.MainActivity\n"
    "I/WayDroidService(  630): taskCreated 15 com.android.systemui/com.android.wm.shell.desktopmode.DesktopWallpaperActivity\n"
    "I/WayDroidService(  630): taskCreated 13 com.android.launcher3/com.android.launcher3.uioverrides.QuickstepLauncher\n"
    "I/WayDroidService(  630): taskCreated 16 com.android.settings/.FallbackHome\n"
    "I/WayDroidService(  630): taskCreated 17 com.android.settings/.Settings\n"
    "I/WayDroidService(  630): taskCreated 18 com.android.systemui/.SomeOtherActivity\n"
).encode())
os.close(w)
obj.on_log(r, 0)
os.close(r)

def check(name, cond):
    if not cond:
        print("android hidden tasks: FAIL", name, created); sys.exit(1)

ids = [c[0] for c in created]
check("an app reaches Ash", (14, "com.cron.calendar", "com.cron.calendar.MainActivity") in created)
check("the desktop wallpaper does not", 15 not in ids)
check("the home screen does not", 13 not in ids)
check("the boot placeholder does not", 16 not in ids)
check("Settings itself still does", 17 in ids)
check("other system UI activities still do", 18 in ids)
print("android hidden tasks: PASS")
PY
