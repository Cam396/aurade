#!/usr/bin/env bash
# Builds aurade-bridge.apk with the Android build tools from a LineageOS tree.
# Usage: AOSP=/path/to/tree KEY=/path/to/key-dir ./build.sh
#   KEY holds bridge.pk8 and bridge.x509.pem (made once with make-key.sh and kept
#   out of the repository).
set -euo pipefail
here=$(cd -- "$(dirname -- "$0")" && pwd -P)
AOSP=${AOSP:?set AOSP to the Android tree}
KEY=${KEY:?set KEY to the directory with bridge.pk8 and bridge.x509.pem}
host=$AOSP/out/host/linux-x86
jar=$AOSP/prebuilts/sdk/35/public/android.jar
work=$(mktemp -d "${TMPDIR:-/tmp}/aurade-bridge.XXXXXX")
trap 'rm -rf -- "${work:?}"' EXIT

mkdir -p "$work/res" "$work/classes"
"$host/bin/aapt2" compile --dir "$here/res" -o "$work/res.zip"
"$host/bin/aapt2" link -o "$work/base.apk" -I "$jar" --manifest "$here/AndroidManifest.xml" \
  --min-sdk-version 29 --target-sdk-version 35 "$work/res.zip"
javac -source 17 -target 17 -cp "$jar" -d "$work/classes" "$here"/src/org/aurade/bridge/*.java
"$host/bin/d8" --lib "$jar" --min-api 29 --output "$work" "$work/classes"/org/aurade/bridge/*.class
(cd "$work" && cp base.apk unaligned.apk && zip -q -j unaligned.apk classes.dex)
"$host/bin/zipalign" -f 4 "$work/unaligned.apk" "$work/aligned.apk"
java -Djava.library.path="$host/lib64" -jar "$host/framework/signapk.jar" \
  "$KEY/bridge.x509.pem" "$KEY/bridge.pk8" "$work/aligned.apk" "$here/../aurade-bridge.apk"
echo "built $here/../aurade-bridge.apk"
