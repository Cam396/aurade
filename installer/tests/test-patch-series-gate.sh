#!/usr/bin/env bash
# `--expect-tree-match` is the gate that says the patch series still describes
# the tree it is supposed to build. Nothing tested it, and it did not work.
#
# A Chromium checkout is two things sharing a directory: a git tree, and a set
# of directories gclient puts there. Git reports the second kind as typechanges
# and untracked directories, because it recorded a file or a gitlink where a
# real directory now sits. The check asked `[[ -f ]]` and called everything
# that was not a regular file a working tree delete, so on this tree 138
# gclient paths counted as mismatches and the gate read FAIL no matter what the
# patches did. It could not tell a patch that failed to reproduce a file from a
# toolchain directory, which means it never answered its own question.
#
# The rules asserted here are the ones that replaced it, each in both
# directions, against a small repository built for the purpose:
#
#   a regular file must byte-match, whether or not a patch claims it, because
#   an unrecorded modification is drift and catching it is most of the value;
#   a typechange or an untracked directory is gclient's business and is
#   counted rather than failed; a delete fails only where the series touches
#   the path; and a path the series claims that the tree does not carry at all
#   is a patch that has quietly stopped doing its job.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
GATE=${AURADE_SERIES_GATE:-$ROOT/ci/verify-patch-series.sh}
failures=0

[[ -r $GATE ]] || { printf 'test-patch-series-gate: no gate at %s\n' "$GATE" >&2; exit 1; }

# Beside the project, in the checkout's own parent, never /tmp: /tmp here is
# mounted without exec and the guardrails put project data beside the checkout
# anyway. Deriving the parent from the checkout rather than one machine's
# absolute path keeps a developer clone and a CI runner working too, not only
# the build host; AURADE_TEST_WORKDIR overrides it.
WORK=$(mktemp -d "${AURADE_TEST_WORKDIR:-${ROOT%/*}}/.series-gate-test.XXXXXX")
trap 'rm -rf -- "$WORK"' EXIT

fail() { printf 'test-patch-series-gate: %s\n' "$*" >&2; failures=$(( failures + 1 )); }

# A repository holding two files, and a one patch series that modifies one of
# them. The tree then has the patch applied, so the series reproduces it.
new_case() {
  local name=$1
  local dir=$WORK/$name
  mkdir -p "$dir/src" "$dir/patches"
  git -C "$dir/src" init -q
  git -C "$dir/src" config user.email tester@example.invalid
  git -C "$dir/src" config user.name Tester
  git -C "$dir/src" config commit.gpgsign false
  printf 'one\n' >"$dir/src/owned.txt"
  printf 'untouched\n' >"$dir/src/other.txt"
  git -C "$dir/src" add -A
  git -C "$dir/src" commit -qm base
  cat >"$dir/patches/0001-owned.patch" <<'PATCH'
diff --git a/owned.txt b/owned.txt
--- a/owned.txt
+++ b/owned.txt
@@ -1 +1 @@
-one
+patched
PATCH
  printf '0001-owned.patch\n' >"$dir/patches/SERIES"
  # The working tree carries the patched content, which is the state the gate
  # is asked to confirm.
  printf 'patched\n' >"$dir/src/owned.txt"
  printf '%s' "$dir"
}

run_gate() { # dir
  local dir=$1 rc=0
  CHROME_SRC="$dir/src" PATCH_DIR="$dir/patches" SERIES_FILE="$dir/patches/SERIES" \
    AURADE_WORKDIR="$dir/work" bash "$GATE" --expect-tree-match \
    >"$dir/out" 2>&1 || rc=$?
  return $rc
}

expect() { # description dir expected_rc
  local what=$1 dir=$2 want=$3 rc=0
  run_gate "$dir" || rc=$?
  [[ $rc == "$want" ]] || { fail "$what: exit $rc, wanted $want"; sed 's/^/      /' "$dir/out" >&2; }
}

expect_says() { grep -Fq -- "$3" "$2/out" || fail "$1: output never said '$3'"; }

# --- the tree the series describes ----------------------------------------

d=$(new_case clean)
expect 'a tree the series reproduces passes' "$d" 0
expect_says 'a tree the series reproduces passes' "$d" 'Series reproduces the working tree'

d=$(new_case wrong-content)
printf 'something else\n' >"$d/src/owned.txt"
expect 'a patched file with the wrong content fails' "$d" 1
expect_says 'a patched file with the wrong content fails' "$d" 'does not reproduce'

# A modified file no patch records is drift. The gate is the only thing that
# would ever say so, which is why it compares files the series never claims.
d=$(new_case drift)
printf 'edited by hand\n' >"$d/src/other.txt"
expect 'an unrecorded modification fails' "$d" 1
expect_says 'an unrecorded modification fails' "$d" 'does not reproduce'

# --- gclient's directories are not the series' business --------------------

# The fixtures here are the shapes the real tree actually has, checked against
# it rather than imagined: a tracked file that gclient replaced with a symlink
# reports as a typechange, and a toolchain directory reports as one untracked
# path that git does not descend into. Getting these wrong is easy and makes
# the test agree with a gate that would still be broken.
d=$(new_case typechange)
rm -f "$d/src/other.txt"
ln -s /dev/null "$d/src/other.txt"
[[ $(git -C "$d/src" status --porcelain) == \ T* ]] || \
  fail 'the typechange fixture does not produce a typechange'
expect 'a file replaced by a symlink passes' "$d" 0
expect_says 'a file replaced by a symlink passes' "$d" 'gclient paths skipped'

d=$(new_case untracked-dir)
mkdir -p "$d/elsewhere/bin"
printf 'binary\n' >"$d/elsewhere/bin/tool"
ln -s "$d/elsewhere" "$d/src/toolchain"
expect 'an untracked toolchain directory passes' "$d" 0
expect_says 'an untracked toolchain directory passes' "$d" 'gclient paths skipped'

# An ordinary untracked file is a different thing entirely: a file added to the
# tree that no patch records is drift, and the gate is the only place it would
# ever be noticed.
d=$(new_case untracked-file)
printf 'added by hand\n' >"$d/src/stray.txt"
expect 'an unrecorded new file fails' "$d" 1
expect_says 'an unrecorded new file fails' "$d" 'does not reproduce'

# --- deletes, which the series cannot express ------------------------------

d=$(new_case delete-outside)
rm -f "$d/src/other.txt"
expect 'a delete the series never touches passes' "$d" 0

d=$(new_case delete-owned)
rm -f "$d/src/owned.txt"
expect 'a delete of a file the series patches fails' "$d" 1
expect_says 'a delete of a file the series patches fails' "$d" 'working tree deleted'

# --- a patch that no longer does anything ----------------------------------

# The tree is put back to its base content, so the patch still applies to the
# scratch worktree while the real tree shows no sign of it. Nothing reaches
# `git status`, so the byte comparison above cannot see it at all.
d=$(new_case claims-nothing)
printf 'one\n' >"$d/src/owned.txt"
expect 'a patch the tree does not carry fails' "$d" 1
expect_says 'a patch the tree does not carry fails' "$d" 'does not carry'

# --- the scratch worktree is not left behind -------------------------------

d=$(new_case cleanup)
run_gate "$d" || true
leftover=$(find "$d/work" -maxdepth 1 -name 'aurade-patch-verify.*' 2>/dev/null | wc -l)
(( leftover == 0 )) || fail "a passing run left $leftover scratch worktree(s) behind"

if (( failures )); then
  printf 'test-patch-series-gate: FAIL (%s)\n' "$failures" >&2
  exit 1
fi
printf 'test-patch-series-gate: PASS\n'
