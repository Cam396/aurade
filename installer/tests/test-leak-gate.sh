#!/usr/bin/env bash
# Exercise the release leak gate against clean trees, tracked secrets, internal
# notes, untracked files, ignored files, and history. A passing gate must also
# detect each of those fixtures when it is introduced.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
GATE=${AURADE_LEAK_GATE:-$ROOT/ci/public-release-leak-gate.sh}
failures=0

[[ -r $GATE ]] || { printf 'test-leak-gate: no gate at %s\n' "$GATE" >&2; exit 1; }

# Scratch repositories go beside the project, in the checkout's own parent,
# never in /tmp: on the build host /tmp is mounted without exec, and the parent
# is where the project keeps its working data. Taking the parent from the
# checkout rather than one machine's absolute path keeps this working on a
# developer clone and a CI runner too. AURADE_TEST_WORKDIR overrides it.
WORK=$(mktemp -d "${AURADE_TEST_WORKDIR:-${ROOT%/*}}/.leak-gate-test.XXXXXX")
trap 'rm -rf -- "$WORK"' EXIT

fail() { printf 'test-leak-gate: %s\n' "$*" >&2; failures=$(( failures + 1 )); }

# A repository with the gate in it and one ordinary commit.
new_repo() {
  local dir=$WORK/$1
  mkdir -p "$dir/ci"
  git -C "$dir" init -q
  git -C "$dir" config user.email tester@example.invalid
  git -C "$dir" config user.name Tester
  git -C "$dir" config commit.gpgsign false
  cp "$GATE" "$dir/ci/public-release-leak-gate.sh"
  printf 'AuraDE\n' >"$dir/README.md"
  git -C "$dir" add -A
  git -C "$dir" commit -qm 'initial'
  printf '%s' "$dir"
}

run_gate() { # dir [args...]
  local dir=$1; shift
  ( cd "$dir" && bash ci/public-release-leak-gate.sh "$@" >"$dir/.out" 2>&1 ) && return 0
  return $?
}

expect() { # description dir expected_rc [args...]
  local what=$1 dir=$2 want=$3; shift 3
  local rc=0
  run_gate "$dir" "$@" || rc=$?
  [[ $rc == "$want" ]] || fail "$what: exit $rc, wanted $want"
}

expect_says() { # description dir needle
  grep -Fq -- "$3" "$2/.out" || fail "$1: output never said '$3'"
}

# --- the tree as it stands blocks, without exception ----------------------

d=$(new_repo clean)
expect 'a clean repository passes' "$d" 0

d=$(new_repo tracked-key)
printf -- '-----BEGIN RSA PRIVATE KEY-----\nnot a real key\n' >"$d/deploy.pem"
git -C "$d" add -A && git -C "$d" commit -qm 'add key'
expect 'a private key in the tree fails' "$d" 1
expect_says 'a private key in the tree fails' "$d" 'FAIL credentials'

d=$(new_repo tracked-internal-doc)
printf 'internal planning\n' >"$d/AURADE_NOTES.md"
git -C "$d" add -f AURADE_NOTES.md && git -C "$d" commit -qm 'add note'
expect 'a tracked internal note fails' "$d" 1
expect_says 'a tracked internal note fails' "$d" 'internal notes are tracked'

d=$(new_repo tracked-handoff)
mkdir -p "$d/docs/handoff"
printf 'handoff\n' >"$d/docs/handoff/HANDOFF.md"
git -C "$d" add -f docs/handoff/HANDOFF.md && git -C "$d" commit -qm 'add handoff'
expect 'a tracked handoff document fails' "$d" 1
expect_says 'a tracked handoff document fails' "$d" 'internal notes are tracked'

# An uncommitted file is the one about to be committed, and the gate used to
# read the index only, so it ran clean on a working tree that held a key. That
# is how a real finding stayed invisible until after it had been committed.
d=$(new_repo untracked-key)
printf -- '-----BEGIN RSA PRIVATE KEY-----\nnot a real key\n' >"$d/staged.pem"
expect 'a private key that is not committed yet fails' "$d" 1
expect_says 'a private key that is not committed yet fails' "$d" 'FAIL credentials'

# Ignored files are not about to be committed, and scanning them would mean
# scanning build output and scratch. A key inside an ignored path is the
# operator's business and not this gate's.
d=$(new_repo ignored-key)
printf 'scratch/\n' >"$d/.gitignore"
git -C "$d" add -A && git -C "$d" commit -qm 'ignore scratch'
mkdir -p "$d/scratch"
printf -- '-----BEGIN RSA PRIVATE KEY-----\nnot a real key\n' >"$d/scratch/key.pem"
expect 'a key inside an ignored path passes' "$d" 0

# --- .gitignore naming what it blocks is the guard working, not a leak -----

d=$(new_repo tracked-bot-token)
printf 'not a real token\n' >"$d/.discord-bot-token"
git -C "$d" add -f .discord-bot-token && git -C "$d" commit -qm 'add token'
expect 'a tracked bot token fails' "$d" 1
expect_says 'a tracked bot token fails' "$d" 'internal notes are tracked'

d=$(new_repo ignore-names-doc)
printf 'DISCORD_MESSAGE_PACKET.md\nAURADE_*.md\nNEXT_STEPS.md\ndocs/handoff/\n' >"$d/.gitignore"
git -C "$d" add -A && git -C "$d" commit -qm 'ignore internal docs'
expect 'an ignore list naming internal docs passes' "$d" 0
expect_says 'an ignore list naming internal docs passes' "$d" 'PASS private_packet'

# --- history is held to a baseline that can shrink and never grow ----------

# One personal path, committed and then deleted. It is unreachable from the
# tree and permanently present in history, which is the case that used to make
# the gate red forever.
seed_history() { # dir file [distinguishing-text]
  # The text has to differ per file. Git addresses content, so two files
  # holding the same bytes are the same blob, and the baseline would rightly
  # call the second one already known.
  printf 'see /mnt/c/Users/someone/Downloads for the %s build\n' "${3:-$2}" >"$1/$2"
  git -C "$1" add -f "$2" && git -C "$1" commit -qm "add $2"
  git -C "$1" rm -q --cached "$2" && rm -f "$1/$2"
  git -C "$1" commit -qm "remove $2"
}

d=$(new_repo history-unrecorded)
seed_history "$d" OLD_NOTES.md
expect 'an unrecorded historical blob fails' "$d" 1
expect_says 'an unrecorded historical blob fails' "$d" 'entered history'
expect_says 'an unrecorded historical blob names the path' "$d" 'OLD_NOTES.md'

expect 'recording a clean tree succeeds' "$d" 0 --record-history
[[ -r $d/ci/leak-gate-history-baseline ]] ||
  fail 'recording a clean tree succeeds: no baseline was written'
grep -q 'someone' "$d/ci/leak-gate-history-baseline" &&
  fail 'the baseline must never record a matched value'
expect 'a recorded historical blob passes' "$d" 0
expect_says 'a recorded historical blob passes' "$d" 'none new'

# The same bytes at a new path are the same blob, so history gained nothing
# it did not already hold and the gate stays quiet. That is the content
# addressed baseline working as intended, and it is pinned here so nobody
# later reads the silence as a miss. The working tree check is what catches a
# copy that is actually tracked.
cp "$d/ci/leak-gate-history-baseline" "$WORK/baseline-before"
seed_history "$d" COPY_OF_NOTES.md OLD_NOTES.md
expect 'the same bytes at a new path are already known' "$d" 0
expect_says 'the same bytes at a new path are already known' "$d" 'none new'

# A second offence with content history has never held is new and must fail.
# The baseline marks what is already there; it is not permission for more.
seed_history "$d" SECOND_NOTES.md second
expect 'a new historical blob fails after recording' "$d" 1
expect_says 'a new historical blob fails after recording' "$d" 'SECOND_NOTES.md'
grep -Fq 'OLD_NOTES.md' "$d/.out" &&
  fail 'a new historical blob fails after recording: reported an already known blob'

# --- recording is not a way to make a red gate green -----------------------

d=$(new_repo record-refuses)
seed_history "$d" OLD_NOTES.md
printf -- '-----BEGIN RSA PRIVATE KEY-----\nnot a real key\n' >"$d/deploy.pem"
git -C "$d" add -A && git -C "$d" commit -qm 'add key'
expect 'recording refuses while a finding stands' "$d" 1 --record-history
expect_says 'recording refuses while a finding stands' "$d" 'refusing to record'
[[ -r $d/ci/leak-gate-history-baseline ]] &&
  fail 'recording refuses while a finding stands: a baseline was written anyway'

# --- the gate rejects arguments it does not understand ---------------------

d=$(new_repo bad-argument)
expect 'an unknown argument is refused' "$d" 2 --erase-history

if (( failures )); then
  printf 'test-leak-gate: FAIL (%s)\n' "$failures" >&2
  exit 1
fi
printf 'test-leak-gate: PASS\n'
