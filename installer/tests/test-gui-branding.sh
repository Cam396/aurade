#!/usr/bin/env bash
# Keep the graphical installer recognisably AuraDE instead of allowing a
# future refactor to collapse it back into an unbranded Adwaita form.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
APP=$ROOT/installer/lib/aurade_gui/app.py
BUILD=$ROOT/installer/build-iso.sh
PROFILE=$ROOT/installer/archiso/profiledef.sh

grep -Fq 'AURADE_CSS' "$APP"
grep -Fq '.aurade-rail' "$APP"
grep -Fq '.aurade-welcome' "$APP"
grep -Fq 'Nothing is written until you confirm' "$APP"
grep -Fq 'AURADE · CHROMEOS-INSPIRED SETUP' "$APP"
grep -Fq '_build_rail' "$APP"
grep -Fq 'aurade-mark.png' "$APP"
grep -Fq 'aurade-logo.png' "$APP"
grep -Fq 'aurade-mark.png' "$BUILD"
grep -Fq 'aurade-logo.png' "$BUILD"
grep -Fq '/usr/local/share/aurade/aurade-mark.png' "$PROFILE"
grep -Fq '/usr/local/share/aurade/aurade-logo.png' "$PROFILE"
[[ -s $ROOT/assets/aurade-mark.png ]]
[[ -s $ROOT/assets/aurade-logo.png ]]

echo 'installer GUI branding test: PASS'
