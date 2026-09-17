#!/usr/bin/env bash
# Read-only public-export leak gate. It never prints matched secret values.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf -- "$TMP"' EXIT

failures=0
current_failures=0
reviews=0
RECORD_HISTORY=0

for arg in "$@"; do
  case "$arg" in
    --record-history) RECORD_HISTORY=1 ;;
    -h|--help)
      printf 'usage: %s [--record-history]\n' "${0##*/}"
      printf '  --record-history  rewrite the historical baseline from the\n'
      printf '                    blobs that match today. Use it after a\n'
      printf '                    cleanup, never to silence a new finding.\n'
      exit 0
      ;;
    *) printf 'unknown argument: %s\n' "$arg" >&2; exit 2 ;;
  esac
done

report_matches() {
  local label=$1
  local pattern=$2
  local output=$3
  if [[ -s "$output" ]]; then
    local count
    count=$(wc -l <"$output")
    printf 'FAIL %-18s %s redacted match(es)\n' "$label" "$count"
    failures=$((failures + 1))
    current_failures=$((current_failures + 1))
  else
    printf 'PASS %-18s\n' "$label"
  fi
}

# Paths excluded from every pattern scan.
#
# The two gate scripts carry the patterns themselves. .gitignore has to name
# each internal document in order to block it, so naming one is the protection
# working rather than a leak. The gate's own test has to contain a private key,
# a bot token name and a personal path, because a test that cannot produce the
# thing being caught proves nothing. Excluding these four is what stops the
# gate from reporting its own machinery, and it excludes nothing a user or a
# build ever reads. Every one of them is small and read by a person.
#
# Kept as one list. The unreachable scan below used to carry its own copy of
# two of these four paths, and the two that were added here later were never
# added there, so the history check failed on .gitignore and on the gate's own
# test while reporting it as secret-like content. One list, read by both.
SCAN_EXCLUDE_PATHS=(
  'ci/public-release-leak-gate.sh'
  'ci/public-docs-gate.sh'
  '.gitignore'
  'installer/tests/test-leak-gate.sh'
)
SCAN_EXCLUDES=(
  ':!assets/**' ':!*.png' ':!*.jpg' ':!*.jpeg' ':!*.gif' ':!*.ico' ':!*.webp'
)
for excluded_path in "${SCAN_EXCLUDE_PATHS[@]}"; do
  SCAN_EXCLUDES+=(":!${excluded_path}")
done

HISTORY_BASELINE="${AURADE_LEAK_BASELINE:-$ROOT/ci/leak-gate-history-baseline}"

# The working tree is what an export publishes, so a match there is blocking
# without exception. History is a separate question: 554 commits cannot be
# edited, and counting them made the gate fail forever, which is the same as
# having no gate. So history is held to a baseline of the exact blobs already
# known to match. A blob is content addressed, so ordinary commits that do not
# change the file reuse the same blob and the set stays still. Any blob outside
# the baseline is new offending content and fails. Baseline entries that
# disappear are a cleanup and never fail. The set can shrink and never grow.
scan_current_and_history() {
  local label=$1
  local pattern=$2
  assert_pattern_runs "$label" "$pattern"
  local current="$TMP/${label}.current"
  local -a commits=()
  : >"$current"

  # --untracked as well as tracked. `git grep` reads the index by default, so
  # a file that has not been committed yet is invisible to it, and a file that
  # has not been committed yet is precisely the one about to be. This gate ran
  # clean on a working tree that contained a private key for that reason, and
  # only started failing once the file was committed. Ignored files stay out,
  # which is what keeps build output and scratch from being scanned.
  git -C "$ROOT" grep -I -n -E --untracked -e "$pattern" -- . "${SCAN_EXCLUDES[@]}" \
    >"$current" 2>/dev/null || true
  report_matches "$label" "$pattern" "$current"

  local seen="$TMP/${label}.blobs"
  : >"$seen"
  mapfile -t commits < <(git -C "$ROOT" rev-list --all)
  if ((${#commits[@]})); then
    local ref path blob
    while IFS= read -r ref; do
      [[ -n $ref ]] || continue
      path=${ref#*:}
      blob=$(git -C "$ROOT" rev-parse "$ref" 2>/dev/null) || continue
      printf '%s %s %s\n' "$label" "$blob" "$path"
    done < <(git -C "$ROOT" grep -I -l -E -e "$pattern" "${commits[@]}" -- . \
      "${SCAN_EXCLUDES[@]}" 2>/dev/null) | sort -u >"$seen"
  fi

  local known="$TMP/${label}.known"
  : >"$known"
  if [[ -r $HISTORY_BASELINE ]]; then
    grep -v '^[[:space:]]*\(#\|$\)' "$HISTORY_BASELINE" 2>/dev/null |
      awk -v l="$label" '$1 == l {print $1, $2, $3}' | sort -u >"$known" || true
  fi

  local novel="$TMP/${label}.novel"
  comm -23 <(cut -d" " -f1,2 "$seen" | sort -u) \
           <(cut -d" " -f1,2 "$known" | sort -u) >"$novel" || true

  if [[ -s "$novel" ]]; then
    local n
    n=$(wc -l <"$novel")
    printf 'FAIL %-18s %s new offending blob(s) entered history\n' "${label}-history" "$n"
    printf '  paths (values never printed):\n' >&2
    cut -d" " -f2 "$novel" | sort -u >"$TMP/${label}.novel-blobs"
    awk 'NR == FNR { want[$1] = 1; next } want[$2] { print $3 }' \
      "$TMP/${label}.novel-blobs" "$seen" |
      sort | uniq -c |
      while read -r versions path; do
        printf '    %s (%s version(s) in history)\n' "$path" "$versions" >&2
      done
    printf '  re-record with: ci/public-release-leak-gate.sh --record-history\n' >&2
    failures=$((failures + 1))
  else
    printf 'PASS %-18s %s known historical blob(s), none new\n' \
      "${label}-history" "$(wc -l <"$seen")"
  fi
  cat "$seen" >>"$TMP/history-record"
}

: >"$TMP/history-record"

# git grep reads a leading "-" as an option, and the scans discard stderr so
# that a matched line can never be printed. Together those turned a broken
# pattern into a silent PASS. Every pattern is proven runnable here, with
# output discarded, before anything is trusted to have scanned.
assert_pattern_runs() {
  local label=$1 pattern=$2 rc=0
  git -C "$ROOT" grep -I -l -E --untracked -e "$pattern" -- . >/dev/null 2>&1 || rc=$?
  # 0 is a match and 1 is no match. Both mean the pattern ran. Anything else
  # is git refusing the pattern, which must never read as a clean scan.
  if (( rc != 0 && rc != 1 )); then
    printf 'public leak gate: pattern for %s is not runnable (git exit %s)\n' \
      "$label" "$rc" >&2
    exit 1
  fi
}

printf 'AuraDE public release leak gate\n'
printf 'Repository: %s\n' "$ROOT"

scan_current_and_history credentials \
  '-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----|(^|[^[:alnum:]])(sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|AIza[0-9A-Za-z_-]{20,}|xox[baprs]-[0-9A-Za-z-]{20,})' 
scan_current_and_history discord_tokens \
  '(^|[^[:alnum:]])[MN][A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{20,}([^[:alnum:]]|$)'
scan_current_and_history private_packet \
  'DISCORD_MESSAGE_PACKET|\.discord-bot-token|MTUzNjIy'
scan_current_and_history personal_paths \
  "/mnt/c/Users/|/Users/[A-Za-z0-9._-]+/|C:\\\\Users\\\\"

large="$TMP/large"
git -C "$ROOT" ls-tree -r --long HEAD | awk '$4 > 52428800 {print}' >"$large"
if [[ -s "$large" ]]; then
  printf 'FAIL %-18s oversized tracked artifact(s)\n' artifacts
  failures=$((failures + 1))
  current_failures=$((current_failures + 1))
else
  printf 'PASS %-18s no tracked file over 50 MiB\n' artifacts
fi

unreachable="$TMP/unreachable"
git -C "$ROOT" fsck --no-reflogs --unreachable --no-progress 2>/dev/null >"$unreachable" || true
unreachable_matches="$TMP/unreachable-matches"
: >"$unreachable_matches"
declare -A scanned_blobs=()
declare -A excluded_blobs=()
scan_unreachable_blob() {
  local blob=$1
  [[ -n ${scanned_blobs[$blob]:-} || -n ${excluded_blobs[$blob]:-} ]] && return 0
  scanned_blobs[$blob]=1
  git -C "$ROOT" cat-file blob "$blob" 2>/dev/null |
    grep -a -n -E -e '-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----|DISCORD_MESSAGE_PACKET|\.discord-bot-token|(^|[^[:alnum:]])(sk-|gh[pousr]_)[A-Za-z0-9_-]{16,}' \
      >>"$unreachable_matches" 2>/dev/null || true
}

# Scan unreachable commits with paths so the scanner does not flag its own
# credential-pattern source code. The excluded paths are exactly the four in
# SCAN_EXCLUDE_PATHS, so an addition there reaches this scan too. It excludes
# nothing a user or a build ever reads.
path_is_excluded() {
  local candidate=$1 excluded
  for excluded in "${SCAN_EXCLUDE_PATHS[@]}"; do
    [[ $candidate == "$excluded" ]] && return 0
  done
  return 1
}
while IFS= read -r commit; do
  [[ -n "$commit" ]] || continue
  while read -r _mode type blob path; do
    [[ $type == blob && -n $blob ]] || continue
    if path_is_excluded "$path"; then
      excluded_blobs[$blob]=1
      continue
    fi
    unset "excluded_blobs[$blob]"
    scan_unreachable_blob "$blob"
  done < <(git -C "$ROOT" ls-tree -r --full-tree "$commit")
done < <(awk '$2 == "commit" {print $3}' "$unreachable")

# Orphaned unreachable blobs have no path to classify, so they are scanned as
# well. Blobs already excluded from the known scanner path stay excluded.
while IFS= read -r blob; do
  [[ -n "$blob" ]] || continue
  scan_unreachable_blob "$blob"
done < <(awk '$2 == "blob" {print $3}' "$unreachable")
if [[ -s "$unreachable_matches" ]]; then
  printf 'FAIL %-18s secret-like unreachable blob content\n' history
  failures=$((failures + 1))
  current_failures=$((current_failures + 1))
else
  printf 'PASS %-18s no secret-like unreachable blob content\n' history
fi

# These are public-facing status terms, not credentials. Keep the count visible
# so a maintainer reviews changes without making ordinary release notes fail.
git -C "$ROOT" grep -I -n -E -e 'NetworkService|SIGSEGV|coredump|private staff|Administrator' -- . \
  "${SCAN_EXCLUDES[@]}" >"$TMP/operational-review" 2>/dev/null || true
if [[ -s "$TMP/operational-review" ]]; then
  reviews=$(wc -l <"$TMP/operational-review")
fi
printf 'REVIEW %-17s %s public operational reference(s)\n' operational "$reviews"

# --- internal notes must not be tracked -----------------------------------
#
# A set of documents was scrubbed from the public repository because they
# carry machine paths, VM addresses, build hosts, session transcripts and
# internal planning language. The bot token at the top of the list is not a
# document; it is here because this array is the only mechanical answer to
# "what must never be tracked", and a credential belongs in that answer more
# than anything else does. The scans below read file contents; this reads what
# git is tracking, and a token file whose contents matched nothing would still
# be caught here. They are still wanted locally and are listed in
# .gitignore so they can sit beside the code without being committed.
#
# .gitignore is a convenience, not a guard: it says nothing about files that
# are already tracked, and `git add -f` ignores it entirely. This is the
# guard. It asks git what is actually tracked, which is the only question
# that decides what reaches a remote.
INTERNAL_DOCS=(
  '.discord-bot-token'
  'AURADE_*.md'
  'ARCH_EXTRA_READINESS.md'
  'DISCORD_MESSAGE_PACKET.md'
  'IMAGE_REVIEW.md'
  'TOOLS_HANDOFF.md'
  'GUI_TUI_HANDOFF.md'
  'NETWORKSERVICE_RIGHT_CLICK_REVIEW.md'
  'NEXT_STEPS.md'
  'docs/handoff/*'
  'REFERENCE.md'
  'RELEASE_STATUS.md'
  'TERMINAL_HANDOFF.md'
  'handoff.md'
  'private-docs/*'
  'files-app/BACKEND_BACKLOG.md'
)

tracked_internal=$(git -C "$ROOT" ls-files -- "${INTERNAL_DOCS[@]}" 2>/dev/null || true)
if [[ -n ${tracked_internal} ]]; then
  printf 'public leak gate: internal notes are tracked and would reach a remote:\n' >&2
  printf '  %s\n' ${tracked_internal} >&2
  printf 'public leak gate: keep them locally, run `git rm --cached` on each.\n' >&2
  failures=$((failures + 1))
  current_failures=$((current_failures + 1))
fi

if (( RECORD_HISTORY )); then
  # Recording answers one question only: what is already in history. It is
  # not a way to make a red gate green. Anything wrong with the tree as it
  # stands today is still wrong after recording, so refuse and say so.
  if (( current_failures )); then
    printf 'public leak gate: refusing to record while %s finding(s) stand\n' \
      "$current_failures" >&2
    printf 'public leak gate: fix the working tree first, then record.\n' >&2
    exit 1
  fi
  {
    printf '# AuraDE leak gate: historical blobs already known to match.\n'
    printf '#\n'
    printf '# One line per offending blob: label, blob object id, and the path\n'
    printf '# it was last seen at. Matched values are never recorded. History\n'
    printf '# cannot be edited, so this file marks what is already in it. The\n'
    printf '# gate fails on any blob absent from this list, which is how new\n'
    printf '# offending content is caught. Entries only ever get removed.\n'
    printf '#\n'
    printf '# Rewritten by: %s --record-history\n' "${0##*/}"
    sort -u "$TMP/history-record"
  } >"$HISTORY_BASELINE"
  printf 'recorded %s historical blob(s) to %s\n' \
    "$(sort -u "$TMP/history-record" | wc -l)" "$HISTORY_BASELINE"
  exit 0
fi

if (( failures )); then
  printf 'VERDICT FAIL (%s blocking category failure(s))\n' "$failures"
  exit 1
fi
printf 'VERDICT PASS (credential/history/artifact gate clear; operational references require human review)\n'
