#!/usr/bin/env bash
# Package download survives a slow link.
#
# The download stage runs pacman under `timeout`. When the timeout fires,
# pacman is killed without removing the lock in the installer's private
# database, and before this test existed every later attempt failed in a second
# with "unable to lock database". Each attempt also wiped the cache, so a link
# that could not fetch the whole set in one attempt could never install.
#
# This test lifts download_arch_packages out of the engine, gives it a fake
# pacman, and checks four things: a stale lock is cleared, an attempt that
# grew the cache does not count as a failure, an attempt that made no progress
# does, and a bad signature still clears the cache.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
ENGINE=$ROOT/installer/bin/aurade-install
failures=0

fail() { printf 'test-acquire-resume: %s\n' "$*" >&2; failures=$(( failures + 1 )); }

func=$(awk '
  /^download_arch_packages\(\) \{/ { inside = 1 }
  inside { print }
  inside && /^\}/ { exit }
' "$ENGINE")
[[ $func == *'pacman --config'* && $func == *'db.lck'* ]] ||
  { echo 'test-acquire-resume: could not find download_arch_packages in aurade-install' >&2; exit 1; }

scratch=$(mktemp -d "${AURADE_TEST_WORKDIR:-${TMPDIR:-/tmp}}/acquire-resume.XXXXXX")
trap 'rm -rf -- "$scratch"' EXIT

# A fake pacman. The scenario file says what each call does, one line per
# call: "lock N" leaves a lock and adds N bytes then exits 124 as a killed
# pacman would, "grow N" adds N bytes and exits 1, "fail" adds nothing and
# exits 1, "ok" writes the final package and exits 0.
mkdir -p "$scratch/bin"
cat >"$scratch/bin/pacman" <<'EOF'
#!/usr/bin/env bash
set -u
db=$FAKE_DB; cache=$FAKE_CACHE; state=$FAKE_STATE
if [[ -e $db/db.lck ]]; then
  echo 'error: failed to init transaction (unable to lock database)'
  exit 1
fi
n=$(( $(cat "$state.n" 2>/dev/null || echo 0) + 1 ))
echo "$n" >"$state.n"
step=$(sed -n "${n}p" "$state")
case $step in
  lock\ *) : >"$db/db.lck"; head -c "${step#lock }" /dev/zero >>"$cache/big.pkg.tar.zst.part"; exit 124 ;;
  grow\ *) head -c "${step#grow }" /dev/zero >>"$cache/big.pkg.tar.zst.part"; exit 1 ;;
  fail) exit 1 ;;
  ok) rm -f "$cache/big.pkg.tar.zst.part"; echo pkg >"$cache/big.pkg.tar.zst"; exit 0 ;;
  *) echo "fake pacman: no step $n"; exit 1 ;;
esac
EOF
chmod +x "$scratch/bin/pacman"

# Runs download_arch_packages against one scenario. Prints "acquired" or the
# die message, then the log lines, then whether the cache was cleared by a
# signature failure.
run_case() {
  local name=$1; shift
  local dir=$scratch/$name
  mkdir -p "$dir/cache" "$dir/db" "$dir/work"
  printf '%s\n' "$@" >"$dir/state"
  PATH=$scratch/bin:$PATH FAKE_DB=$dir/db FAKE_CACHE=$dir/cache FAKE_STATE=$dir/state \
  SIG_BAD=${SIG_BAD:-0} bash -c "
    set -Eeuo pipefail
    ARCH_CACHE=$dir/cache ARCH_DB_PATH=$dir/db WORK_DIR=$dir/work
    ARCH_PACMAN_CONF=/dev/null TARGET=/dev/fake BASE_PACKAGES=(base)
    log() { printf 'LOG %s\n' \"\$*\"; }
    die() { printf 'DIE %s\n' \"\$*\"; exit 3; }
    start_rate_sampler() { :; }
    stop_rate_sampler() { :; }
    run_download_logged() { shift 2; \"\$@\" >/dev/null 2>&1; }
    timeout() { shift 2; \"\$@\"; }
    sig_calls=0
    verify_arch_package_signatures() {
      sig_calls=\$(( sig_calls + 1 ))
      (( SIG_BAD == 0 || sig_calls > 1 ))
    }
    pacman_keyring_failure() { return 1; }
    repo-add() { :; }
    write_arch_local_pacman_conf() { :; }
$func
    download_arch_packages 0
    echo ACQUIRED
  " 2>&1 || true
}

# 1. A killed attempt leaves a lock. The next attempt must not trip on it.
out=$(run_case stale-lock 'lock 100' 'ok')
[[ $out == *ACQUIRED* ]] || fail "stale lock: expected the second attempt to succeed, got: $out"

# 2. A slow link: five attempts that each grow the cache, then success. The old
# loop gave up after three.
out=$(run_case slow-link 'grow 10' 'grow 10' 'grow 10' 'grow 10' 'grow 10' 'ok')
[[ $out == *ACQUIRED* ]] || fail "slow link: expected success after five growing attempts, got: $out"
[[ $out == *'Continuing where it stopped'* ]] || fail 'slow link: progress was not reported'
[[ $out != *'Trying once more'* ]] || fail 'slow link: a growing attempt was counted as a failure'

# 3. No progress at all still gives up after three failures, with the message
# the cause classifier knows.
out=$(run_case dead-link 'fail' 'fail' 'fail' 'ok')
[[ $out == *'DIE the packages could not all be downloaded from the archive before changing the disk'* ]] ||
  fail "dead link: expected the download failure after three attempts, got: $out"
[[ $out != *ACQUIRED* ]] || fail 'dead link: a fourth attempt ran'

# 4. A bad signature clears the cache before the next attempt.
out=$(SIG_BAD=1 run_case bad-signature 'ok' 'ok')
[[ $out == *'signatures were invalid. Clearing the cache'* && $out == *ACQUIRED* ]] ||
  fail "bad signature: expected a cleared cache and a second attempt, got: $out"

# 5. The attempt cap holds even when every attempt grows the cache.
steps=(); for _ in $(seq 1 20); do steps+=('grow 1'); done
out=$(AURADE_ARCH_ACQUIRE_MAX_ATTEMPTS=4 run_case capped "${steps[@]}")
[[ $out == *'DIE the packages could not all be downloaded'* ]] ||
  fail "capped: expected the attempt cap to stop the loop, got: $out"
(( $(cat "$scratch/capped/state.n") == 4 )) || fail "capped: expected 4 attempts, saw $(cat "$scratch/capped/state.n")"

if (( failures )); then
  printf 'test-acquire-resume: %d failure(s)\n' "$failures" >&2
  exit 1
fi
echo 'test-acquire-resume: ok'
