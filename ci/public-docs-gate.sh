#!/usr/bin/env bash
# Public documentation gate. It checks the current tree only and never prints
# matching lines, because the historical tree may contain material that must be
# handled by a deliberate repository-history decision.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf -- "$TMP"' EXIT

failures=0
matches="$TMP/matches"
: >"$matches"

blocked_words=(
  "$(printf '\\x4f\\x70\\x75\\x73')"
  "$(printf '\\x43\\x6c\\x61\\x75\\x64\\x65')"
  "$(printf '\\x47\\x50\\x54')"
  "$(printf '\\x47\\x65\\x6d\\x69\\x6e\\x69')"
  "$(printf '\\x47\\x65\\x6d\\x6d\\x61')"
  "$(printf '\\x44\\x65\\x65\\x70\\x53\\x65\\x65\\x6b')"
  "$(printf '\\x43\\x6f\\x64\\x65\\x78')"
  "$(printf '\\x41\\x47\\x59')"
  "$(printf '\\x41\\x49\\x2d\\x61\\x73\\x73\\x69\\x73\\x74\\x65\\x64')"
  "$(printf '\\x67\\x65\\x6e\\x65\\x72\\x61\\x74\\x65\\x64\\x20\\x62\\x79')"
  "$(printf '\\x63\\x6f\\x2d\\x61\\x75\\x74\\x68\\x6f\\x72\\x65\\x64\\x2d\\x62\\x79')"
)

contains_blocked_word() {
  local path=$1 word
  for word in "${blocked_words[@]}"; do
    if grep -n -E -i -- "(^|[^[:alnum:]])${word}([^[:alnum:]]|$)" \
        "$path" >/dev/null 2>>"$TMP/errors"; then
      return 0
    fi
  done
  return 1
}

hidden_state_dir=$(printf '.\143\154\141\165\144\145')

while IFS= read -r file; do
  case "$file" in
    ci/public-docs-gate.sh) continue ;;
  esac
  [[ -f "$ROOT/$file" ]] || continue
  if grep -n -E -i \
      "(/mnt/build|/tmp/|/root/|${hidden_state_dir}|aurade-work|out/Ash|Playground|/home/[A-Za-z0-9._-]+|192\\.168\\.)|staff-chat|mod-log|release authority|delegated authority|private test packet|VM credentials|DISCORD_MESSAGE_PACKET|BEGIN [A-Z0-9 ]*PRIVATE KEY|(^|[^[:alnum:]])(password|passwd|passphrase|client[_ -]?secret|api[_ -]?key)[[:space:]]*[:=][[:space:]]*[A-Za-z0-9]" \
      "$ROOT/$file" >/dev/null 2>>"$TMP/errors" || contains_blocked_word "$ROOT/$file"; then
    printf '%s\n' "$file" >>"$matches"
  fi
done < <(git -C "$ROOT" ls-files '*.md' | grep -v '^installer/bible/')

while IFS= read -r forbidden; do
  [[ -f "$ROOT/$forbidden" ]] && printf '%s\n' "$forbidden" >>"$matches"
done < <(
  git -C "$ROOT" ls-files '*.md' |
    grep -E -i '(^|/)([^/]*(backlog|handoff|review|status|steps)[^/]*)\.md$' || true
)

if [[ -s "$matches" ]]; then
  sort -u "$matches" | while IFS= read -r file; do
    printf 'FAIL public-docs %s\n' "$file"
  done
  failures=$((failures + 1))
else
  printf 'PASS public-docs no private paths, authorship markers, or forbidden handoffs\n'
fi

if (( failures )); then
  printf 'VERDICT FAIL\n'
  exit 1
fi
printf 'VERDICT PASS\n'
