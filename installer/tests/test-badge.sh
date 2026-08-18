#!/usr/bin/env bash
# The install fingerprint: derived, never collected, and the same mark every
# time for the same install.
set -Eeuo pipefail
trap 'case $- in *e*) printf "%s: line %s gave up: %s\n" "${0##*/}" "$LINENO" "$BASH_COMMAND" >&2 ;; esac' ERR

# shellcheck source=assert.sh
. "$(dirname -- "$0")/assert.sh"

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
LIB="$ROOT/installer/lib/aurade-badge.sh"
ENGINE="$ROOT/installer/bin/aurade-install"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# shellcheck source=../lib/aurade-badge.sh
. "$LIB"

# One install, on one machine, at one moment. The material stands in for the
# hardware; the time and the target are the real arguments and still go
# through the real code.
WHEN=2026-08-18T04:12:00Z
TARGET=/dev/nvme0n1
seed_for() { AURADE_BADGE_MATERIAL=$1 aurade_badge_seed "$WHEN" "$TARGET"; }

# --- the same machine gets the same mark ------------------------------------
a=$(seed_for 'board-serial-0001')
b=$(seed_for 'board-serial-0001')
[[ -n $a && $a == "$b" ]] || { echo 'the same input gave two different seeds' >&2; exit 1; }
# --- a different machine gets a different mark ------------------------------
c=$(seed_for 'board-serial-0002')
[[ $a != "$c" ]] || { echo 'two machines got the same seed' >&2; exit 1; }
# One character of difference has to change the whole mark, or two machines
# off the same production line get marks nobody can tell apart.
rows_a=$(aurade_badge_rows "$a" '#' '.')
rows_c=$(aurade_badge_rows "$c" '#' '.')
[[ $rows_a != "$rows_c" ]] || { echo 'two seeds drew the same mark' >&2; exit 1; }
differing=0
while IFS= read -r pair; do
  [[ ${pair%%|*} == "${pair##*|}" ]] || differing=$(( differing + 1 ))
done < <(paste -d'|' <(printf '%s\n' "$rows_a") <(printf '%s\n' "$rows_c"))
(( differing >= 3 )) ||
  { echo "only $differing of 5 rows differ between two machines" >&2; exit 1; }

# --- reinstalling the same machine gives it a new mark ----------------------
#
# The install time is in the seed on purpose. A fingerprint that survived a
# reinstall would be a stable hardware identifier written into every machine
# in plain text, which is exactly the thing this is not: it identifies an
# install, and a reinstall is a different install.
same_machine_later=$(AURADE_BADGE_MATERIAL='board-serial-0001' \
  aurade_badge_seed '2026-09-01T09:30:00Z' "$TARGET")
[[ $a != "$same_machine_later" ]] ||
  { echo 'reinstalling the same machine gave back the same fingerprint' >&2; exit 1; }
# And the target is in it too, so two disks in one machine are two installs.
other_disk=$(AURADE_BADGE_MATERIAL='board-serial-0001' \
  aurade_badge_seed "$WHEN" /dev/sda)
[[ $a != "$other_disk" ]] ||
  { echo 'installing to a different disk gave back the same fingerprint' >&2; exit 1; }
# A machine that reports no hardware at all still gets a fingerprint, because
# the install itself is enough to be unique. A virtual machine with no DMI is
# the common case here, not a corner one.
bare=$(AURADE_BADGE_MATERIAL='' aurade_badge_seed "$WHEN" "$TARGET")
[[ $bare =~ ^[0-9a-f]{64}$ ]] ||
  { echo 'a machine reporting nothing got no fingerprint' >&2; exit 1; }
[[ -n $(aurade_badge_code "$bare") ]]
[[ $bare != "$a" ]]

# --- nothing identifying survives into the output ---------------------------
#
# The whole design is that the inputs go into a digest and the digest is the
# only thing kept. This is the assertion that says so: a serial that reached
# the screen, the file or the code would be a hardware identifier written down
# in plain text on every machine.
secret='SERIAL-DEADBEEF-0123456789'
s=$(seed_for "$secret")
refute grep -Fq "$secret" <<<"$s"
refute grep -Fq 'DEADBEEF' <<<"$s"
refute grep -Fq 'DEADBEEF' <<<"$(aurade_badge_code "$s")"
refute grep -Fq 'DEADBEEF' <<<"$(aurade_badge_rows "$s" '#' '.')"
# A digest is hex and nothing else, so nothing can hide in it.
[[ $s =~ ^[0-9a-f]{64}$ ]] || { echo "the seed is not a sha256 digest: '$s'" >&2; exit 1; }

# --- the short code ---------------------------------------------------------
code=$(aurade_badge_code "$a")
[[ $code =~ ^[0-9A-F]{4}-[0-9A-F]{4}$ ]] ||
  { echo "the code is not four and four: '$code'" >&2; exit 1; }
# Upper case, because it is read aloud and typed back, and `b8` and `B8` being
# the same thing has to be true without anybody being told.
[[ $code == "${code^^}" ]]
# Derived from the seed, so the code on the phone and the mark on the screen
# are the same fingerprint.
[[ $code == "$(aurade_badge_code "$b")" ]]
[[ $code != "$(aurade_badge_code "$c")" ]]
# Nothing to say when there is nothing to say, rather than a mark meaning
# "this machine reported nothing", which is itself a thing about the machine.
[[ -z $(aurade_badge_code '') ]]
[[ -z $(aurade_badge_code 'abc') ]]
[[ -z $(aurade_badge_rows '') ]]
[[ -z $(aurade_badge_rows 'abc') ]]

# --- the mark is a mark and not a smear -------------------------------------
mapfile -t rows < <(aurade_badge_rows "$a" 'AB' '..')
[[ ${#rows[@]} -eq 5 ]] || { echo "the mark is ${#rows[@]} rows, not 5" >&2; exit 1; }
for row in "${rows[@]}"; do
  # Nine cells of two characters. Two wide because a terminal character is
  # about twice as tall as it is wide, and one character per cell draws a seal
  # squashed to half height.
  [[ ${#row} -eq 18 ]] || { echo "a row is ${#row} characters, not 18" >&2; exit 1; }
  # Symmetric down the middle. This is what makes it read as a designed mark
  # rather than as a corrupted screen, and it is the only visual property
  # worth pinning.
  cells=''
  for (( i = 0; i < ${#row}; i += 2 )); do cells+=${row:i:1}; done
  [[ $cells == "$(rev <<<"$cells")" ]] ||
    { echo "a row is not symmetric: '$row'" >&2; exit 1; }
done
# Neither blank nor solid. Both are marks somebody would read as a failure to
# draw one, and a hex threshold rather than the low bit produces the first.
whole=$(printf '%s' "${rows[@]}")
refute grep -Eq '^(\.\.)+$' <<<"$whole"
refute grep -Eq '^(AB)+$' <<<"$whole"

# Averaged over many machines the mark is about half filled, which is the
# property that makes them look like a set rather than like noise or like a
# mostly empty grid.
filled=0
total=0
for n in $(seq 1 60); do
  s=$(seed_for "machine-$n")
  art=$(aurade_badge_rows "$s" 'A' '.')
  filled=$(( filled + $(tr -cd 'A' <<<"$art" | wc -c) ))
  total=$(( total + $(tr -cd 'A.' <<<"$art" | wc -c) ))
done
share=$(( filled * 100 / total ))
(( share >= 40 && share <= 60 )) ||
  { echo "marks are $share percent filled on average, which is not a balanced mark" >&2; exit 1; }

# The engine's half of this is asserted in test-install-dry-run.sh, which
# already stands up the package fixture a plan needs. Repeating that here to
# keep one test self contained would be repeating the part most likely to rot.
grep -Fq 'aurade_badge_seed' "$ENGINE" ||
  { echo 'the engine does not derive a fingerprint at all' >&2; exit 1; }

echo 'install fingerprint test: PASS'
