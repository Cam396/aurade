#!/usr/bin/env bash
# Read-only public-export leak gate. It never prints matched secret values.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf -- "$TMP"' EXIT

failures=0
reviews=0

report_matches() {
  local label=$1
  local pattern=$2
  local output=$3
  if [[ -s "$output" ]]; then
    local count
    count=$(wc -l <"$output")
    printf 'FAIL %-18s %s redacted match(es)\n' "$label" "$count"
    failures=$((failures + 1))
  else
    printf 'PASS %-18s\n' "$label"
  fi
}

scan_current_and_history() {
  local label=$1
  local pattern=$2
  local current="$TMP/${label}.current"
  local history="$TMP/${label}.history"
  local -a commits=()
  : >"$current"
  : >"$history"

  git -C "$ROOT" grep -I -n -E "$pattern" -- . \
    ':!assets/**' ':!*.png' ':!*.jpg' ':!*.jpeg' ':!*.gif' ':!*.ico' ':!*.webp' \
    ':!ci/public-release-leak-gate.sh' >"$current" 2>/dev/null || true
  mapfile -t commits < <(git -C "$ROOT" rev-list --all)
  if ((${#commits[@]})); then
    git -C "$ROOT" grep -I -n -E "$pattern" "${commits[@]}" -- . \
      ':!assets/**' ':!*.png' ':!*.jpg' ':!*.jpeg' ':!*.gif' ':!*.ico' ':!*.webp' \
      ':!ci/public-release-leak-gate.sh' >"$history" 2>/dev/null || true
  fi
  cat "$current" "$history" >"$TMP/${label}.all"
  report_matches "$label" "$pattern" "$TMP/${label}.all"
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
    grep -a -n -E -- '-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----|DISCORD_MESSAGE_PACKET|\.discord-bot-token|(^|[^[:alnum:]])(sk-|gh[pousr]_)[A-Za-z0-9_-]{16,}' \
      >>"$unreachable_matches" 2>/dev/null || true
}

# Scan unreachable commits with paths so the scanner does not flag its own
# credential-pattern source code. Reachable/history scans above already exclude
# this public scanner path; applying the same rule to unreachable trees avoids a
# false positive without weakening checks for any user or build artifact.
while IFS= read -r commit; do
  [[ -n "$commit" ]] || continue
  while read -r _mode type blob path; do
    [[ $type == blob && -n $blob ]] || continue
    if [[ $path == ci/public-release-leak-gate.sh ]]; then
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
else
  printf 'PASS %-18s no secret-like unreachable blob content\n' history
fi

# These are public-facing status terms, not credentials. Keep the count visible
# so a maintainer reviews changes without making ordinary release notes fail.
git -C "$ROOT" grep -I -n -E 'NetworkService|SIGSEGV|coredump|private staff|Administrator' -- . \
  ':!assets/**' ':!*.png' ':!*.jpg' ':!*.jpeg' ':!*.gif' ':!*.ico' ':!*.webp' >"$TMP/operational-review" 2>/dev/null || true
if [[ -s "$TMP/operational-review" ]]; then
  reviews=$(wc -l <"$TMP/operational-review")
fi
printf 'REVIEW %-17s %s public operational reference(s)\n' operational "$reviews"

if (( failures )); then
  printf 'VERDICT FAIL (%s blocking category failure(s))\n' "$failures"
  exit 1
fi
printf 'VERDICT PASS (credential/history/artifact gate clear; operational references require human review)\n'
