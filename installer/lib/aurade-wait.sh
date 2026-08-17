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
# The mark
# --------------------------------------------------------------------------
#
# The same A the graphical installer draws, at the only fidelity a virtual
# console has.
#
# It is a letter and it is one continuous stroke, which is the whole idea of
# the mark: the crossbar does not cross, it loops. A plain block A would have
# been easier to draw and would have been a different logo, and a text
# installer that shows a different logo to the graphical one is two products.
#
# Seven rows, because that is the smallest it can be and still keep the loop.
AURADE_MARK=(
'        /\'
'       /  \'
'      /    \'
'     /  __  \'
'    /  /  \  \'
'   /  (____)  \'
'  /__/      \__\'
)

#: Today, as month and day. Injectable, so the seasonal lines below can be
#: tested without waiting for December.
AURADE_TODAY=${AURADE_TODAY:-$(date +%m%d)}

# One line of sky above the mark, which is empty on all but a few days a year.
#
# The rule for these is that somebody who is not looking for them never
# notices, and somebody who happens to install AuraDE on the right day gets a
# small thing that was clearly put there on purpose. An easter egg that
# announces itself is a feature.
aurade_mark_sky() {
  case $AURADE_TODAY in
    # The dark end of the year in the hemisphere most of these machines are
    # in. Sparse, because snow drawn densely in ASCII is static.
    12[2-9]*|123[01]|010[1]) printf '     .   *      .   *' ;;
    # The twenty ninth of February: a day that is not usually there, marked by
    # something crossing a sky that is not usually there either.
    0229) printf '        - - *' ;;
    *) printf '' ;;
  esac
}

# --------------------------------------------------------------------------
# Tips
# --------------------------------------------------------------------------

AURADE_TIPS=()
AURADE_TIPS_NEXT=()
AURADE_TIPS_RARE=()
AURADE_TIPS_LONG=()
AURADE_TIPS_LOADED=0

#: After this many seconds the long lane takes over the tip line and does not
#: give it back. Twenty minutes is well past the point where a normal install
#: has finished, so anybody still reading has started to wonder whether the
#: thing has frozen, and every other tip on the rotation is answering a
#: question they have stopped asking.
AURADE_TIP_LONG_AFTER=${AURADE_TIP_LONG_AFTER:-1200}

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
      long) AURADE_TIPS_LONG+=("$text") ;;
    esac
  done <"$file"
  return 0
}

# The line for somebody who has been watching this for twenty minutes.
#
# It replaces the rotation rather than joining it. At that point the useful
# thing to say is not another fact about Btrfs, it is that this is still
# running, because the question they now have is whether it has stopped.
aurade_tip_long() {
  local elapsed=${1:-0}
  aurade_tips_load
  (( elapsed >= AURADE_TIP_LONG_AFTER )) || { printf ''; return 0; }
  (( ${#AURADE_TIPS_LONG[@]} > 0 )) || { printf ''; return 0; }
  printf '%s' "${AURADE_TIPS_LONG[0]}"
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
#: While this is above zero the ribbon swings harder and the wave is faster.
#: It is set by typing a word at the progress screen, counted down a frame at
#: a time, and it does nothing else.
AURADE_AURORA_BLOOM=0

# A shooting star, when there happens to be one.
#
# The aurora is a wave, and a wave is restful and completely predictable after
# about thirty seconds of watching it. This is the thing that is not: it
# crosses once, it takes about a second, and then there is not another one for
# a while.
#
# Rare on purpose. At one in fifty-five frames it turns up roughly every seven
# seconds, which over a ten minute install is often enough to be worth
# glancing up for and seldom enough that it never becomes the screen's
# heartbeat. Something that arrives on a schedule is not a surprise twice.
#: Column of the head and the row it is on. A negative column means there is
#: no star at the moment, which is nearly always.
AURADE_STAR_X=-1
AURADE_STAR_Y=0

#: One frame in this many starts one. Zero switches them off, which is what
#: the render tests and reduced motion both do.
AURADE_STAR_RARITY=${AURADE_STAR_RARITY:-55}

#: Head first, then the tail it leaves behind it.
AURADE_STAR_TRAIL='*--..'

aurade_star_step() {
  local width=${1:-56} rows=${2:-3}
  if (( AURADE_STAR_X >= 0 )); then
    AURADE_STAR_X=$(( AURADE_STAR_X + 5 ))
    # It descends across the whole crossing rather than travelling flat. On
    # three rows that is the difference between a shooting star and an
    # underline.
    AURADE_STAR_Y=$(( (AURADE_STAR_X * rows) / (width + 8) ))
    (( AURADE_STAR_Y < rows )) || AURADE_STAR_Y=$(( rows - 1 ))
    (( AURADE_STAR_X <= width + 6 )) || AURADE_STAR_X=-1
    return 0
  fi
  (( AURADE_STAR_RARITY > 0 )) || return 0
  (( RANDOM % AURADE_STAR_RARITY == 0 )) || return 0
  AURADE_STAR_X=0
  AURADE_STAR_Y=0
  return 0
}

aurade_aurora() {
  local frame=${1:-0} width=${2:-56} rows=${3:-3}
  local bloom=0
  (( AURADE_AURORA_BLOOM <= 0 )) || bloom=1
  awk -v frame="$frame" -v width="$width" -v rows="$rows" -v bloom="$bloom" \
      -v ramp="$AURADE_AURORA_RAMP" \
      -v star_x="$AURADE_STAR_X" -v star_y="$AURADE_STAR_Y" \
      -v trail="$AURADE_STAR_TRAIL" '
    BEGIN {
      steps = length(ramp)
      middle = (rows - 1) / 2
      thickness = bloom ? 2.1 : 1.35
      swing = bloom ? 1.7 : 1.0
      for (y = 0; y < rows; y++) {
        line = ""
        for (x = 0; x < width; x++) {
          # Where the ribbon is at this column. A band that moves, rather than
          # a level that fills from the bottom: filling upward reads as a
          # progress bar, and there is already a progress bar on this screen.
          centre = middle \
            + 0.85 * swing * sin(x * 0.17 + frame * 0.09 * swing) \
            + 0.45 * swing * sin(x * 0.061 - frame * 0.052 * swing)
          level = 1 - (centre > y ? centre - y : y - centre) / thickness
          if (level < 0) level = 0
          if (level > 1) level = 1
          index_ = int(level * (steps - 1) + 0.5) + 1
          line = line substr(ramp, index_, 1)
        }
        # The star is written over the wave rather than added to it, so it
        # reads as being in front. Done here, while every row is still exactly
        # `width` characters, because the trailing trim below would otherwise
        # have to be undone to place anything.
        if (star_x >= 0 && star_y == y) {
          for (i = 0; i < length(trail); i++) {
            px = star_x - i
            if (px < 0 || px >= width) continue
            line = substr(line, 1, px) substr(trail, i + 1, 1) substr(line, px + 2)
          }
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

# --------------------------------------------------------------------------
# 2048
# --------------------------------------------------------------------------
#
# The best fit that exists for this screen, and it is not close.
#
# Four keys, no timing, and a 4x4 grid that renders exactly in a terminal.
# Everybody already knows the rules, so there is nothing to explain on a screen
# nobody came here to read. And it is satisfying in the particular low stakes
# way a waiting screen wants: you can stop mid-move, look at the install, and
# come back without having lost anything.
#
# The constraint that ruled out the obvious alternatives is that this screen
# redraws on a fixed tick. Anything needing input latency is out, which is why
# there is no Tetris here: a laggy Tetris is worse than no Tetris.
#
# The board is a flat 16 cell array, row major. A shell has no 2D arrays and
# faking one with name references costs more than the index arithmetic does.
AURADE_2048_BOARD=()
AURADE_2048_SCORE=0
AURADE_2048_WON=0
AURADE_2048_MOVED=0

aurade_2048_new() {
  local i
  AURADE_2048_BOARD=()
  for (( i = 0; i < 16; i++ )); do AURADE_2048_BOARD+=(0); done
  AURADE_2048_SCORE=0
  AURADE_2048_WON=0
  aurade_2048_spawn
  aurade_2048_spawn
}

# A new tile in a free cell. Nine times in ten a 2, which is the standard
# distribution and the reason the game is winnable at all.
aurade_2048_spawn() {
  local free=() i
  for (( i = 0; i < 16; i++ )); do
    (( AURADE_2048_BOARD[i] != 0 )) || free+=("$i")
  done
  (( ${#free[@]} )) || return 1
  i=${free[RANDOM % ${#free[@]}]}
  if (( RANDOM % 10 )); then
    AURADE_2048_BOARD[i]=2
  else
    AURADE_2048_BOARD[i]=4
  fi
}

# Collapse one line of four toward index 0.
#
# Written once and used for all four directions by handing it the indices in
# the right order, because four nearly identical loops is four places for the
# merge rule to drift. A tile merges at most once per move, which is the rule
# everybody gets wrong: 2 2 4 does not become 8.
_aurade_2048_line() {
  local -n _cells=$1
  local packed=() i value merged=0
  for i in "${_cells[@]}"; do
    (( AURADE_2048_BOARD[i] != 0 )) || continue
    packed+=("${AURADE_2048_BOARD[i]}")
  done
  local out=() n=${#packed[@]}
  i=0
  while (( i < n )); do
    if (( i + 1 < n && packed[i] == packed[i+1] )); then
      value=$(( packed[i] * 2 ))
      out+=("$value")
      AURADE_2048_SCORE=$(( AURADE_2048_SCORE + value ))
      (( value != 2048 )) || AURADE_2048_WON=1
      i=$(( i + 2 ))
    else
      out+=("${packed[i]}")
      i=$(( i + 1 ))
    fi
  done
  while (( ${#out[@]} < 4 )); do out+=(0); done
  for (( i = 0; i < 4; i++ )); do
    if (( AURADE_2048_BOARD[_cells[i]] != out[i] )); then
      AURADE_2048_MOVED=1
      AURADE_2048_BOARD[_cells[i]]=${out[i]}
    fi
  done
}

aurade_2048_move() {
  local direction=$1 r c line
  AURADE_2048_MOVED=0
  for (( r = 0; r < 4; r++ )); do
    line=()
    for (( c = 0; c < 4; c++ )); do
      case $direction in
        left)  line+=($(( r * 4 + c ))) ;;
        right) line+=($(( r * 4 + 3 - c ))) ;;
        up)    line+=($(( c * 4 + r ))) ;;
        down)  line+=($(( (3 - c) * 4 + r ))) ;;
      esac
    done
    _aurade_2048_line line
  done
  # A tile only appears when something actually moved. Spawning on a move that
  # did nothing is how a board fills up while somebody is pressing a key that
  # is doing nothing, which reads as the game cheating.
  (( ! AURADE_2048_MOVED )) || aurade_2048_spawn
}

# Over when the board is full and no neighbours match.
aurade_2048_over() {
  local i r c
  for (( i = 0; i < 16; i++ )); do
    (( AURADE_2048_BOARD[i] != 0 )) || return 1
  done
  for (( r = 0; r < 4; r++ )); do
    for (( c = 0; c < 4; c++ )); do
      i=$(( r * 4 + c ))
      (( c == 3 )) || ! (( AURADE_2048_BOARD[i] == AURADE_2048_BOARD[i+1] )) || return 1
      (( r == 3 )) || ! (( AURADE_2048_BOARD[i] == AURADE_2048_BOARD[i+4] )) || return 1
    done
  done
  return 0
}
