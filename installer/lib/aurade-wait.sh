#!/usr/bin/env bash
# The part of the install that is just waiting.
#
# Every other screen in this installer is measured in seconds. This one is
# measured in ten minutes, and until now it held a title, a list and a bar. The
# longest screen in the product was the least designed one, which is backwards.
#
# Three things live here, and none of them can touch the install:
#
#   the tips, read from lib/aurade-tips, shared with the graphical front end so
#   that the two installers never tell the same person different things;
#
#   an aurora, drawn in text, which is the brand ribbon at the only fidelity a
#   virtual console has;
#
#   a snake, because ten minutes is a long time and somebody who cannot do
#   anything else should at least be able to do something.
#
# Nothing in this file reads the journal, runs a command, or has any way to
# reach the engine. The worst a bug here can do is draw badly.

# --------------------------------------------------------------------------
# Tips
# --------------------------------------------------------------------------

AURADE_TIPS=()
AURADE_TIPS_NEXT=()
AURADE_TIPS_RARE=()
AURADE_TIPS_LOADED=0

#: How often the rare lane comes up. One rotation in this many, on average.
AURADE_TIP_RARITY=${AURADE_TIP_RARITY:-40}

aurade_tips_load() {
  (( ! AURADE_TIPS_LOADED )) || return 0
  local file=${AURADE_TIPS_FILE:-} candidate lane text
  if [[ -z $file ]]; then
    for candidate in /usr/local/lib/aurade/aurade-tips \
                     "${BASH_SOURCE[0]%/*}/aurade-tips"; do
      [[ -r $candidate ]] || continue
      file=$candidate
      break
    done
  fi
  AURADE_TIPS_LOADED=1
  [[ -n $file && -r $file ]] || return 0
  while IFS=$'\t' read -r lane text; do
    [[ -n $lane && $lane != '#'* ]] || continue
    [[ -n $text ]] || continue
    case $lane in
      tip)  AURADE_TIPS+=("$text") ;;
      next) AURADE_TIPS_NEXT+=("$text") ;;
      rare) AURADE_TIPS_RARE+=("$text") ;;
    esac
  done <"$file"
  return 0
}

# The tip for a given rotation.
#
# Walking the list in order rather than picking at random, because random
# repeats and a repeat on a screen somebody is staring at reads as a screen
# that has frozen. The `next` lane is interleaved every fourth rotation, so
# what to do after the restart keeps coming back around without crowding out
# everything else.
#
# The rare lane is the exception and is genuinely random, because something
# that turns up on a fixed schedule is not a surprise the second time.
aurade_tip_for() {
  local index=${1:-0} pool
  aurade_tips_load
  if (( ${#AURADE_TIPS_RARE[@]} > 0 && AURADE_TIP_RARITY > 0 )) &&
     (( RANDOM % AURADE_TIP_RARITY == 0 )); then
    printf '%s' "${AURADE_TIPS_RARE[RANDOM % ${#AURADE_TIPS_RARE[@]}]}"
    return 0
  fi
  if (( index % 4 == 3 && ${#AURADE_TIPS_NEXT[@]} > 0 )); then
    printf '%s' "${AURADE_TIPS_NEXT[(index / 4) % ${#AURADE_TIPS_NEXT[@]}]}"
    return 0
  fi
  (( ${#AURADE_TIPS[@]} > 0 )) || { printf ''; return 0; }
  pool=$(( index - index / 4 ))
  printf '%s' "${AURADE_TIPS[pool % ${#AURADE_TIPS[@]}]}"
}

# --------------------------------------------------------------------------
# The aurora, in text
# --------------------------------------------------------------------------

#: Density ramp, sparse to solid. ASCII for the same reason the progress bar
#: is ASCII: it is one column wide in every font a virtual console might be
#: using, and a box-drawing character that falls back to a question mark is
#: worse than no picture at all.
AURADE_AURORA_RAMP=' .:-=+*#'

# Three rows of a slow wave, phased by `frame`.
#
# awk rather than bash arithmetic because this needs a sine and bash has no
# floating point. One process per frame at three frames a second is nothing
# next to the pacstrap running underneath it.
#
# Two waves of different wavelength and opposite drift, summed. One wave is a
# ripple; two that disagree is a thing that never quite repeats, which is what
# makes it worth looking at for ten minutes.
aurade_aurora() {
  local frame=${1:-0} width=${2:-56} rows=${3:-3}
  awk -v frame="$frame" -v width="$width" -v rows="$rows" \
      -v ramp="$AURADE_AURORA_RAMP" '
    BEGIN {
      steps = length(ramp)
      middle = (rows - 1) / 2
      thickness = 1.35
      for (y = 0; y < rows; y++) {
        line = ""
        for (x = 0; x < width; x++) {
          # Where the ribbon is at this column. A band that moves, rather than
          # a level that fills from the bottom: filling upward reads as a
          # progress bar, and there is already a progress bar on this screen.
          centre = middle \
            + 0.85 * sin(x * 0.17 + frame * 0.09) \
            + 0.45 * sin(x * 0.061 - frame * 0.052)
          level = 1 - (centre > y ? centre - y : y - centre) / thickness
          if (level < 0) level = 0
          if (level > 1) level = 1
          index_ = int(level * (steps - 1) + 0.5) + 1
          line = line substr(ramp, index_, 1)
        }
        # Trailing spaces are invisible and would only be padding the frame
        # twice, so they come off before the row is handed back.
        sub(/ +$/, "", line)
        print line
      }
    }'
}

# --------------------------------------------------------------------------
# Snake
# --------------------------------------------------------------------------
#
# A state machine with no drawing in it, so that a test can play a whole game
# without a terminal and this file can be read without wondering whether the
# game is somehow reaching the installer. It is not. It has an arena, a body,
# and a piece of food, and its only output is characters.

AURADE_SNAKE_W=0
AURADE_SNAKE_H=0
AURADE_SNAKE_DIR=right
AURADE_SNAKE_BODY=()
AURADE_SNAKE_FOOD=
AURADE_SNAKE_SCORE=0
AURADE_SNAKE_DEAD=0
AURADE_SNAKE_GROW=0

aurade_snake_new() {
  AURADE_SNAKE_W=${1:-40}
  AURADE_SNAKE_H=${2:-8}
  AURADE_SNAKE_DIR=right
  AURADE_SNAKE_SCORE=0
  AURADE_SNAKE_DEAD=0
  AURADE_SNAKE_GROW=0
  local mid_x=$(( AURADE_SNAKE_W / 4 )) mid_y=$(( AURADE_SNAKE_H / 2 ))
  AURADE_SNAKE_BODY=(
    "$(( mid_x + 2 )),$mid_y"
    "$(( mid_x + 1 )),$mid_y"
    "$mid_x,$mid_y"
  )
  aurade_snake_place_food
}

# Anywhere that is not the snake. The bounded retry matters: as the body fills
# the arena, a naive loop that keeps rolling until it misses the snake takes
# unbounded time, and the one place that would show up is the moment somebody
# is about to win.
aurade_snake_place_food() {
  local attempt x y candidate cell taken
  for (( attempt = 0; attempt < 200; attempt++ )); do
    x=$(( RANDOM % AURADE_SNAKE_W ))
    y=$(( RANDOM % AURADE_SNAKE_H ))
    candidate="$x,$y"
    taken=0
    for cell in "${AURADE_SNAKE_BODY[@]}"; do
      [[ $cell != "$candidate" ]] || { taken=1; break; }
    done
    (( taken )) || { AURADE_SNAKE_FOOD=$candidate; return 0; }
  done
  # The arena is full. That is a win, and there is nowhere left to put food.
  AURADE_SNAKE_FOOD=
  return 0
}

# Turning back on yourself is the one input a snake ignores, because it is
# always a mistake rather than a request.
aurade_snake_turn() {
  case $1 in
    up)    [[ $AURADE_SNAKE_DIR == down  ]] || AURADE_SNAKE_DIR=up ;;
    down)  [[ $AURADE_SNAKE_DIR == up    ]] || AURADE_SNAKE_DIR=down ;;
    left)  [[ $AURADE_SNAKE_DIR == right ]] || AURADE_SNAKE_DIR=left ;;
    right) [[ $AURADE_SNAKE_DIR == left  ]] || AURADE_SNAKE_DIR=right ;;
  esac
}

# One tick. Returns 1 once the snake has died, and keeps returning 1.
aurade_snake_step() {
  (( ! AURADE_SNAKE_DEAD )) || return 1
  local head=${AURADE_SNAKE_BODY[0]} x y cell
  x=${head%,*}
  y=${head#*,}
  case $AURADE_SNAKE_DIR in
    up)    y=$(( y - 1 )) ;;
    down)  y=$(( y + 1 )) ;;
    left)  x=$(( x - 1 )) ;;
    right) x=$(( x + 1 )) ;;
  esac
  # The walls are walls. Wrapping would make the game easier and the arena
  # harder to read, and the border is drawn, so it should mean something.
  if (( x < 0 || y < 0 || x >= AURADE_SNAKE_W || y >= AURADE_SNAKE_H )); then
    AURADE_SNAKE_DEAD=1
    return 1
  fi
  # The tail cell is about to move out from under the head unless the snake is
  # growing, so it does not count as a collision.
  local limit=$(( ${#AURADE_SNAKE_BODY[@]} - 1 ))
  (( AURADE_SNAKE_GROW )) && limit=${#AURADE_SNAKE_BODY[@]}
  local i
  for (( i = 0; i < limit; i++ )); do
    cell=${AURADE_SNAKE_BODY[i]}
    [[ $cell != "$x,$y" ]] || { AURADE_SNAKE_DEAD=1; return 1; }
  done

  AURADE_SNAKE_BODY=("$x,$y" "${AURADE_SNAKE_BODY[@]}")
  if [[ -n $AURADE_SNAKE_FOOD && $AURADE_SNAKE_FOOD == "$x,$y" ]]; then
    AURADE_SNAKE_SCORE=$(( AURADE_SNAKE_SCORE + 1 ))
    aurade_snake_place_food
  else
    unset 'AURADE_SNAKE_BODY[-1]'
    AURADE_SNAKE_BODY=("${AURADE_SNAKE_BODY[@]}")
  fi
  AURADE_SNAKE_GROW=0
  return 0
}

# The arena as rows of characters, no border and no padding. Whoever is drawing
# owns the frame.
aurade_snake_rows() {
  local -A cells=()
  local cell first=1 x y row
  for cell in "${AURADE_SNAKE_BODY[@]}"; do
    if (( first )); then
      cells[$cell]='@'
      first=0
    else
      cells[$cell]='o'
    fi
  done
  [[ -z $AURADE_SNAKE_FOOD ]] || cells[$AURADE_SNAKE_FOOD]='*'
  for (( y = 0; y < AURADE_SNAKE_H; y++ )); do
    row=''
    for (( x = 0; x < AURADE_SNAKE_W; x++ )); do
      row+=${cells["$x,$y"]:-.}
    done
    printf '%s\n' "$row"
  done
}
