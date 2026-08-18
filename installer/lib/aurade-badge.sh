# The install fingerprint: a mark this machine gets and no other machine has.
#
# Every AuraDE install is identical by design, which is the point of a pinned
# snapshot and a reproducible package set, and it also means there is nothing
# anywhere that says "this one is mine". The fingerprint is that, and it costs
# a hash and twenty lines of drawing.
#
# It is derived, never collected. The inputs are the things that make a machine
# that machine, and every one of them is either an identifier somebody could
# use to recognise the hardware later or something a fingerprinting service
# would pay for. So they go into a digest and the digest is the only thing that
# is kept, drawn, written to disk or shown on a screen. There is no code path
# here that prints an input, and `aurade_badge_seed` is the only function that
# ever reads one.
#
# The drawing is symmetric because a symmetric mosaic reads as a designed mark
# and a random one reads as a corrupted screen. Half the columns come from the
# digest and the other half are the first half mirrored, which is the same
# trick the identicon on a code forge uses and for the same reason.

# Which digest command is available. sha256sum on a Linux image, shasum on
# anything else, and neither is a reason to fail an install.
_badge_digest() {
  local input=$1
  if command -v sha256sum >/dev/null 2>&1; then
    printf '%s' "$input" | sha256sum | cut -d' ' -f1
  elif command -v shasum >/dev/null 2>&1; then
    printf '%s' "$input" | shasum -a 256 | cut -d' ' -f1
  else
    printf ''
  fi
}

# The seed, as a hex digest, or empty when nothing identifying could be read.
#
# The sources are tried in order of how stable they are across reinstalls of
# the same machine, most stable first, and every one of them is optional. A
# virtual machine with no DMI and no machine-id still gets a fingerprint from
# the time and the target, which is unique to the install even though it is not
# unique to the hardware.
#
# AURADE_BADGE_MATERIAL stands in for the hardware, so this is testable
# without a motherboard. It replaces what is read off the machine and nothing
# else: everything below it still runs, which is the point. An override that
# returned a finished seed would leave the half of this function that decides
# what a fingerprint actually means untested, and that half is the half with
# an opinion in it.
aurade_badge_seed() {
  local when=${1:-} target=${2:-} material=''
  if [[ -n ${AURADE_BADGE_MATERIAL+set} ]]; then
    material=$AURADE_BADGE_MATERIAL
  else
    local source
    for source in /sys/class/dmi/id/product_uuid /sys/class/dmi/id/board_serial \
                  /sys/class/dmi/id/product_serial /etc/machine-id; do
      [[ -r $source ]] || continue
      material+=$(cat "$source" 2>/dev/null || true)
    done
    # One network address, and only as a fallback for machines that report no
    # board identity at all. Read from sysfs rather than by running `ip`, so
    # there is no command whose output could carry more than was asked for.
    if [[ -z ${material//[[:space:]]/} ]]; then
      local link
      for link in /sys/class/net/*/address; do
        [[ -r $link ]] || continue
        case $link in */lo/address) continue ;; esac
        material+=$(cat "$link" 2>/dev/null || true)
        break
      done
    fi
  fi
  # The install itself, so two machines that report nothing still differ, and
  # so reinstalling the same machine gives it a new mark rather than the old
  # one. A fingerprint that survives a reinstall would be a hardware
  # identifier, which is the thing this deliberately is not.
  material+="|${when}|${target}"
  _badge_digest "$material"
}

# The short code, which is the fingerprint in a form somebody can read out.
#
# Eight hex digits in two groups. Long enough that two machines in a room will
# not collide and short enough to say down a phone, which is the whole job:
# this is what goes in plain mode, in a support conversation, and on a braille
# display, where the mosaic is a row of characters that mean nothing.
aurade_badge_code() {
  local seed=$1 hex
  hex=$(printf '%s' "$seed" | tr -cd '0-9a-fA-F')
  [[ ${#hex} -ge 8 ]] || { printf ''; return 0; }
  hex=${hex:0:8}
  printf '%s-%s' "$(printf '%s' "${hex:0:4}" | tr 'a-f' 'A-F')" \
                 "$(printf '%s' "${hex:4:4}" | tr 'a-f' 'A-F')"
}

AURADE_BADGE_ROWS=5
AURADE_BADGE_HALF=5

# The mosaic, one row per line.
#
# Five rows of nine cells, of which the left five are drawn from the digest and
# the right four mirror them. Each cell is two characters wide so that a cell
# is about square in a terminal, where a character is roughly twice as tall as
# it is wide; drawn one character per cell the whole mark comes out squashed
# and stops reading as a seal.
#
# `fill` and `blank` are arguments rather than constants because the caller
# knows which of the three character tiers the terminal is in, and this file
# is also sourced by the engine, which is writing a file rather than drawing a
# screen and wants plain hashes.
aurade_badge_rows() {
  local seed=$1 fill=${2:-'##'} blank=${3:-'  '}
  local hex row column index digit bit line=''
  hex=$(printf '%s' "$seed" | tr -cd '0-9a-f')
  [[ ${#hex} -ge $(( AURADE_BADGE_ROWS * AURADE_BADGE_HALF )) ]] || return 0
  for (( row = 0; row < AURADE_BADGE_ROWS; row++ )); do
    line=''
    for (( column = 0; column < AURADE_BADGE_HALF; column++ )); do
      index=$(( row * AURADE_BADGE_HALF + column ))
      digit=$(( 16#${hex:index:1} ))
      # The low bit rather than a threshold. A threshold on a hex digit fills
      # slightly under half the cells and the mark comes out sparse and
      # lopsided; the low bit is an even split.
      bit=$(( digit & 1 ))
      if (( bit )); then line+=$fill; else line+=$blank; fi
    done
    # Mirrored, minus the centre column, which would otherwise be drawn twice
    # and put a two cell wide seam down the middle of every mark.
    for (( column = AURADE_BADGE_HALF - 2; column >= 0; column-- )); do
      index=$(( row * AURADE_BADGE_HALF + column ))
      digit=$(( 16#${hex:index:1} ))
      if (( digit & 1 )); then line+=$fill; else line+=$blank; fi
    done
    printf '%s\n' "$line"
  done
}
