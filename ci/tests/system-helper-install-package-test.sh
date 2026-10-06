#!/usr/bin/env bash
# Exercise the safe package-install dispatch without installing anything.
#
# The helper's install path is privileged in production. This fixture replaces
# the current helper's id and pacman commands with recording stubs, so it tests
# argument order and failure boundaries without host mutation.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
ORIGINAL_HELPER="$ROOT/aurade-system-helper/aurade-system-helper"
TMP=$(mktemp -d "${TMPDIR:-/tmp}/aurade-install-package.XXXXXX")
trap 'rm -rf "$TMP"' EXIT

fail() { echo "system helper install-package test: $*" >&2; exit 1; }

[[ -r $ORIGINAL_HELPER ]] || fail 'helper is missing'

stub_dir="$TMP/bin"
mkdir -p "$stub_dir"
cat >"$stub_dir/id" <<'EOF'
#!/usr/bin/env bash
if [[ "${1:-}" == "-u" ]]; then
  echo 0
else
  echo "unexpected id request" >&2
  exit 2
fi
EOF
cat >"$stub_dir/pacman" <<'EOF'
#!/usr/bin/env bash
for arg in "$@"; do
  printf '[%s]\n' "$arg" >>"$AURADE_INSTALL_CALLS"
done
exit "$(cat "$AURADE_INSTALL_PACMAN_RC")"
EOF
chmod 0755 "$stub_dir/id" "$stub_dir/pacman"

package_path="$TMP/test package.pkg.tar.zst"
printf 'not a package, never passed to pacman\n' >"$package_path"

reset_stubs() {
  : >"$TMP/calls"
  printf '%s\n' "${1:-0}" >"$TMP/pacman.rc"
}

run_helper() {
  local helper="$1"
  shift
  AURADE_INSTALL_CALLS="$TMP/calls" \
    AURADE_INSTALL_PACMAN_RC="$TMP/pacman.rc" \
    PATH="$stub_dir:$PATH" "$helper" "$@" >"$TMP/out" 2>&1
}

run_valid() {
  reset_stubs 0
  if ! run_helper "$1" install-package "$package_path"; then
    return 1
  fi
  expected=$'[-Qip]\n['"$package_path"$']\n[-U]\n[--needed]\n[--noconfirm]\n['"$package_path"$']'
  [[ "$(<"$TMP/calls")" == "$expected" ]] || return 1
}

run_metadata_failure() {
  reset_stubs 7
  local status
  if run_helper "$1" install-package "$package_path"; then
    status=0
  else
    status=$?
  fi
  [[ $status -ne 0 ]] || return 1
  grep -Fxq -- '[-Qip]' "$TMP/calls" || return 1
  if grep -Fxq -- '[-U]' "$TMP/calls"; then
    return 1
  fi
}

run_bad_extension() {
  reset_stubs 0
  printf 'not a package\n' >"$TMP/test-package.txt"
  if run_helper "$1" install-package "$TMP/test-package.txt"; then
    return 1
  fi
  [[ ! -s "$TMP/calls" ]]
}

run_relative_path() {
  reset_stubs 0
  printf 'not a package\n' >"$TMP/test-package.pkg.tar.zst"
  local old_pwd
  old_pwd=$PWD
  cd "$TMP"
  if run_helper "$1" install-package "test-package.pkg.tar.zst"; then
    cd "$old_pwd"
    return 1
  fi
  cd "$old_pwd"
  [[ ! -s "$TMP/calls" ]]
}

run_extra_argument() {
  reset_stubs 0
  if run_helper "$1" install-package "$package_path" extra; then
    return 1
  fi
  [[ ! -s "$TMP/calls" ]]
}

baseline_hash=$(sha256sum "$ORIGINAL_HELPER")

run_valid "$ORIGINAL_HELPER" || fail 'valid package did not run metadata then install'
run_metadata_failure "$ORIGINAL_HELPER" || fail 'metadata failure did not stop install'
run_bad_extension "$ORIGINAL_HELPER" || fail 'invalid extension reached pacman'
run_relative_path "$ORIGINAL_HELPER" || fail 'relative package path was accepted'
run_extra_argument "$ORIGINAL_HELPER" || fail 'extra argument was accepted'

if [[ "${1:-}" != "--mutation-audit" ]]; then
  echo 'system helper install-package test: PASS (5 behavioral cases)'
  exit 0
fi

mutate_and_expect_failure() {
  local name="$1" old="$2" new="$3" scenario="$4"
  local copy="$TMP/helper-$name"
  cp -- "$ORIGINAL_HELPER" "$copy"
  python3 - "$copy" "$old" "$new" <<'PY'
from pathlib import Path
import sys

path, old, new = sys.argv[1:]
text = Path(path).read_text()
if text.count(old) != 1:
    raise SystemExit(f"mutation anchor count for {path}: {text.count(old)}")
Path(path).write_text(text.replace(old, new, 1))
PY
  chmod 0755 "$copy"
  set +e
  case "$scenario" in
    valid) run_valid "$copy";;
    metadata) run_metadata_failure "$copy";;
    extension) run_bad_extension "$copy";;
    relative) run_relative_path "$copy";;
    arguments) run_extra_argument "$copy";;
    *) fail "unknown mutation scenario $scenario";;
  esac
  local status=$?
  set -e
  if [[ $status -eq 0 ]]; then
    echo "mutation $name: NOT CAUGHT"
    return 1
  fi
  echo "mutation $name: caught"
}

mutate_and_expect_failure metadata-call \
  'pacman -Qip "${package_path}" >/dev/null' \
  ': # metadata call removed' valid
mutate_and_expect_failure install-call \
  'exec pacman -U --needed --noconfirm "${package_path}"' \
  'exit 0 # install call removed' valid
mutate_and_expect_failure call-order \
  'pacman -Qip "${package_path}" >/dev/null' \
  'pacman -U --needed --noconfirm "${package_path}"' valid
mutate_and_expect_failure metadata-status \
  'pacman -Qip "${package_path}" >/dev/null' \
  'pacman -Qip "${package_path}" >/dev/null || true' metadata
mutate_and_expect_failure extension-check \
  '*) die "unsupported package extension" ;;' \
  '*) : ;;' extension
mutate_and_expect_failure absolute-check \
  '[[ "${package_path}" = /* ]] || die "package path must be absolute"' \
  ': # absolute path check removed' relative
mutate_and_expect_failure argument-count \
  $'  require_root\n  [[ "$#" -eq 1 ]] || { usage; exit 2; }' \
  $'  require_root\n  : # argument count check removed' arguments

after_hash=$(sha256sum "$ORIGINAL_HELPER")
[[ "$after_hash" == "$baseline_hash" ]] || fail 'original helper changed during mutation audit'
echo "system helper install-package mutation audit: PASS (7 mutations; baseline byte identity)"
