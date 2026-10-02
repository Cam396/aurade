#!/usr/bin/env bash
# The boot screen and disk unlock: aurade-boot's own tests.
#
# The theme is three things that have to agree, the generator, the plymouth
# script and the archive of what the generator drew, and plymouth reports
# none of the ways they can disagree: a missing image or a stale size is a
# screen that quietly shows less. The initramfs hook decides which of the
# photographs and drawn sizes go into the image and what the screen says
# about the keyboard, which is the difference between a passphrase typed on
# the right layout and a locked disk.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)

# A source edited without its checksum re-recorded fails at build time with a
# message about corruption; here it fails with the file's name.
PYTHONDONTWRITEBYTECODE=1 python3 -I "$ROOT/aurade-boot/tools/record-sums.py" --check
PYTHONDONTWRITEBYTECODE=1 python3 -I "$ROOT/aurade-boot/tests/assets_test.py"
bash "$ROOT/aurade-boot/tests/hook-test.sh"
