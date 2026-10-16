#!/usr/bin/env bash
# aurade-apk-check tells the truth about what an app brings.
#
# It builds small fake APKs (a zip is all the checker reads) and pins the
# verdict for each: Java only, x86_64 native, ARM only, ARM plus x86_64,
# Google services, Play Integrity, and a file that is not an APK.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
CHECK=$ROOT/aurade-android/aurade-apk-check
work=$(mktemp -d "${TMPDIR:-/tmp}/apk-check.XXXXXX")
trap 'rm -rf -- "$work"' EXIT
failures=0
fail() { printf 'apk-check-test: %s\n' "$*" >&2; failures=$(( failures + 1 )); }

mkapk() { # name dex-text lib...
  local name=$1 dex=$2; shift 2
  python3 -I - "$work/$name.apk" "$dex" "$@" <<'PY'
import sys, zipfile
out, dex, libs = sys.argv[1], sys.argv[2], sys.argv[3:]
with zipfile.ZipFile(out, 'w') as z:
    z.writestr('AndroidManifest.xml', b'manifest')
    z.writestr('classes.dex', dex.encode())
    for l in libs:
        z.writestr(l, b'\x7fELF')
PY
}

verdict() { python3 -I "$CHECK" --json "$work/$1.apk" | python3 -I -c 'import json,sys; print(json.load(sys.stdin)[0]["verdict"])'; }

mkapk java 'hello'
mkapk x64 'hello' lib/x86_64/libgame.so lib/arm64-v8a/libgame.so
mkapk armonly 'hello' lib/arm64-v8a/libgame.so lib/armeabi-v7a/libgame.so
mkapk gms 'Lcom.google.android.gms.maps.MapView;'
mkapk integrity 'com.google.android.play.core.integrity.IntegrityManagerFactory com.google.android.gms'
mkapk weird 'hello' lib/mips/libx.so
printf 'not a zip' >"$work/bad.apk"

[[ $(verdict java) == runs ]] || fail "java only: expected runs, got $(verdict java)"
[[ $(verdict x64) == runs ]] || fail "x86_64 plus arm64: expected runs, got $(verdict x64)"
[[ $(verdict armonly) == needs-arm-translation ]] || fail "arm only: expected needs-arm-translation, got $(verdict armonly)"
[[ $(verdict gms) == runs-with-microg ]] || fail "gms: expected runs-with-microg, got $(verdict gms)"
[[ $(verdict integrity) == blocked ]] || fail "integrity: expected blocked, got $(verdict integrity)"
[[ $(verdict weird) == blocked ]] || fail "other cpu: expected blocked, got $(verdict weird)"
[[ $(python3 -I "$CHECK" --json "$work/bad.apk" | python3 -I -c 'import json,sys; print(json.load(sys.stdin)[0]["verdict"])') == blocked ]] || fail "not an apk: expected blocked"
python3 -I "$CHECK" "$work/java.apk" >/dev/null || fail "java only: exit status should be 0"
if python3 -I "$CHECK" "$work/armonly.apk" >/dev/null; then fail "arm only: exit status should not be 0"; fi

(( failures == 0 )) || { printf 'apk-check-test: %d failure(s)\n' "$failures" >&2; exit 1; }
echo 'apk-check-test: ok'
