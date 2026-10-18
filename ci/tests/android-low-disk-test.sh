#!/usr/bin/env bash
# An Android image download that cannot fit says so before it starts, and
# touches nothing: the images already on disk stay as they are.
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mkdir "$TMP/images"
printf old > "$TMP/images/system.img"
cat > "$TMP/images.json" <<'JSON'
{"version": "2026-10-20", "base_url": "https://example.invalid/", "files": [
 {"name": "system.img", "sha256": "1111111111111111111111111111111111111111111111111111111111111111", "size": 2000000000}]}
JSON

python3 -I - "$ROOT/aurade-android/aurade-android" "$TMP" <<'PY'
import importlib.machinery, importlib.util, os, sys
path, tmp = sys.argv[1:3]
loader = importlib.machinery.SourceFileLoader("aurade_android", path)
spec = importlib.util.spec_from_loader("aurade_android", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)
mod.IMAGE_DIR = f"{tmp}/images"
logged, stages = [], []
mod.log = logged.append
A = mod.Android
obj = object.__new__(A)
obj.waiting = []
obj.refresh_manifest = lambda: None
obj.manifest_file = lambda: f"{tmp}/images.json"
obj.emit = lambda stage, percent: stages.append(stage)

class Stat:
    f_bavail, f_frsize = 100, 1 << 20  # 100 MB free
real = os.statvfs
os.statvfs = lambda p: Stat()
try:
    A.provision_worker(obj)
finally:
    os.statvfs = real

def check(name, cond):
    if not cond:
        print("android low disk: FAIL", name, logged, stages); sys.exit(1)

check("fails", "failed" in stages)
check("says why", any("not enough free disk space" in m for m in logged))
check("nothing downloaded", not os.path.exists(f"{tmp}/images/system.img.part"))
check("old image untouched", open(f"{tmp}/images/system.img").read() == "old")
print("android low disk test: PASS")
PY
