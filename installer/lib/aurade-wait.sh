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

# --------------------------------------------------------------------------
# Life
# --------------------------------------------------------------------------
#
# Conway's, as something to watch rather than something to play.
#
# This one earns its place for a reason none of the games do. Some people find
# a game on a screen they are anxious about actively stressful: they do not
# want to be entertained while a disk is being erased, they want the minutes
# to pass. A thing that moves on its own, needs nothing, and cannot be lost is
# the answer for them, and it is the only option here with all three.
#
# It is also thematically right for a screen where something is being built.
#
# The grid wraps at the edges. A bounded grid dies back to a few stable blobs
# in a corner within a minute, which is a screen that has stopped, and the
# whole point is a screen that has not.
AURADE_LIFE_W=0
AURADE_LIFE_H=0
AURADE_LIFE_CELLS=()
AURADE_LIFE_AGE=0

aurade_life_new() {
  local w=${1:-40} h=${2:-12} i
  AURADE_LIFE_W=$w
  AURADE_LIFE_H=$h
  AURADE_LIFE_CELLS=()
  AURADE_LIFE_AGE=0
  # Around a third alive. Sparser than that takes a long time to become
  # interesting and denser than that boils for a while and then collapses.
  for (( i = 0; i < w * h; i++ )); do
    if (( RANDOM % 100 < 32 )); then
      AURADE_LIFE_CELLS+=(1)
    else
      AURADE_LIFE_CELLS+=(0)
    fi
  done
}

aurade_life_step() {
  local w=$AURADE_LIFE_W h=$AURADE_LIFE_H
  (( w > 0 && h > 0 )) || return 0
  local -a next=()
  local x y dx dy nx ny live cell
  for (( y = 0; y < h; y++ )); do
    for (( x = 0; x < w; x++ )); do
      live=0
      for dy in -1 0 1; do
        for dx in -1 0 1; do
          (( dx || dy )) || continue
          # The wrap, which is what keeps this alive for ten minutes.
          nx=$(( (x + dx + w) % w ))
          ny=$(( (y + dy + h) % h ))
          (( ! AURADE_LIFE_CELLS[ny * w + nx] )) || live=$(( live + 1 ))
        done
      done
      cell=${AURADE_LIFE_CELLS[y * w + x]}
      if (( cell )); then
        (( live == 2 || live == 3 )) && next+=(1) || next+=(0)
      else
        (( live == 3 )) && next+=(1) || next+=(0)
      fi
    done
  done
  AURADE_LIFE_CELLS=("${next[@]}")
  AURADE_LIFE_AGE=$(( AURADE_LIFE_AGE + 1 ))
}

# The grid as rows of characters, no border and no padding, the same contract
# the snake arena has: whoever is drawing owns the frame.
aurade_life_rows() {
  local x y row
  for (( y = 0; y < AURADE_LIFE_H; y++ )); do
    row=''
    for (( x = 0; x < AURADE_LIFE_W; x++ )); do
      if (( AURADE_LIFE_CELLS[y * AURADE_LIFE_W + x] )); then row+='#'; else row+=' '; fi
    done
    printf '%s\n' "$row"
  done
}

# --------------------------------------------------------------------------
# Lights Out
# --------------------------------------------------------------------------
#
# Five by five, one action, pure logic and no timing at all. It is the
# smallest thing on this screen that is still a game, and it is the one that
# survives being interrupted best: the board is the whole state, so looking
# away for a minute costs nothing.
#
# The board is generated by starting from solved and pressing random cells,
# which is the only honest way to do it. A random board is solvable slightly
# less than half the time, and handing somebody an impossible puzzle while
# they wait for a disk is not a joke worth making.
AURADE_LIGHTS=()
AURADE_LIGHTS_MOVES=0
AURADE_LIGHTS_X=0
AURADE_LIGHTS_Y=0

_aurade_lights_press() {
  local x=$1 y=$2 i
  for i in "$x,$y" "$(( x - 1 )),$y" "$(( x + 1 )),$y" "$x,$(( y - 1 ))" "$x,$(( y + 1 ))"; do
    local cx=${i%,*} cy=${i#*,}
    (( cx >= 0 && cx < 5 && cy >= 0 && cy < 5 )) || continue
    AURADE_LIGHTS[cy * 5 + cx]=$(( ! AURADE_LIGHTS[cy * 5 + cx] ))
  done
}

aurade_lights_new() {
  local i
  AURADE_LIGHTS=()
  for (( i = 0; i < 25; i++ )); do AURADE_LIGHTS+=(0); done
  AURADE_LIGHTS_MOVES=0
  AURADE_LIGHTS_X=2
  AURADE_LIGHTS_Y=2
  # Six presses from solved. Enough to look like a puzzle, few enough that it
  # is finishable inside the wait it exists to fill.
  for (( i = 0; i < 6; i++ )); do
    _aurade_lights_press "$(( RANDOM % 5 ))" "$(( RANDOM % 5 ))"
  done
  # A generated board that happens to come out solved is not a puzzle.
  aurade_lights_won && aurade_lights_new
  return 0
}

aurade_lights_move() {
  case $1 in
    up)    (( AURADE_LIGHTS_Y > 0 )) && AURADE_LIGHTS_Y=$(( AURADE_LIGHTS_Y - 1 )) || true ;;
    down)  (( AURADE_LIGHTS_Y < 4 )) && AURADE_LIGHTS_Y=$(( AURADE_LIGHTS_Y + 1 )) || true ;;
    left)  (( AURADE_LIGHTS_X > 0 )) && AURADE_LIGHTS_X=$(( AURADE_LIGHTS_X - 1 )) || true ;;
    right) (( AURADE_LIGHTS_X < 4 )) && AURADE_LIGHTS_X=$(( AURADE_LIGHTS_X + 1 )) || true ;;
  esac
  return 0
}

aurade_lights_toggle() {
  _aurade_lights_press "$AURADE_LIGHTS_X" "$AURADE_LIGHTS_Y"
  AURADE_LIGHTS_MOVES=$(( AURADE_LIGHTS_MOVES + 1 ))
}

aurade_lights_won() {
  local cell
  for cell in "${AURADE_LIGHTS[@]}"; do
    (( ! cell )) || return 1
  done
  return 0
}

# Rows of characters. The cursor is drawn as brackets around a cell rather
# than as a colour, so it is still visible with the colour gone.
aurade_lights_rows() {
  local x y row lit left right
  for (( y = 0; y < 5; y++ )); do
    row=''
    for (( x = 0; x < 5; x++ )); do
      if (( AURADE_LIGHTS[y * 5 + x] )); then lit='O'; else lit='.'; fi
      left=' '; right=' '
      if (( x == AURADE_LIGHTS_X && y == AURADE_LIGHTS_Y )); then left='['; right=']'; fi
      row+="$left$lit$right"
    done
    printf '%s\n' "$row"
  done
}

# --------------------------------------------------------------------------
# The fifteen puzzle
# --------------------------------------------------------------------------
#
# Arrows only, and everybody already knows it, which is the same argument that
# put 2048 on this screen. It renders in sixteen cells and has no clock.
#
# Shuffled by making legal moves from the solved board rather than by
# permuting the tiles. Half of all permutations of a fifteen puzzle cannot be
# solved, and the parity rule that decides which half is not something to
# explain to somebody waiting for an install.
AURADE_FIFTEEN=()
AURADE_FIFTEEN_HOLE=15
AURADE_FIFTEEN_MOVES=0

aurade_fifteen_new() {
  local i last=''
  AURADE_FIFTEEN=()
  for (( i = 1; i <= 15; i++ )); do AURADE_FIFTEEN+=("$i"); done
  AURADE_FIFTEEN+=(0)
  AURADE_FIFTEEN_HOLE=15
  AURADE_FIFTEEN_MOVES=0
  local n direction
  for (( n = 0; n < 120; n++ )); do
    # Never immediately undoing the move just made, or a hundred and twenty
    # shuffles average out to about six.
    while true; do
      case $(( RANDOM % 4 )) in
        0) direction=up ;; 1) direction=down ;;
        2) direction=left ;; *) direction=right ;;
      esac
      [[ $direction != "$last" ]] || continue
      break
    done
    if aurade_fifteen_slide "$direction"; then
      case $direction in
        up) last=down ;; down) last=up ;;
        left) last=right ;; right) last=left ;;
      esac
    fi
  done
  AURADE_FIFTEEN_MOVES=0
  return 0
}

# The direction names the tile's travel, not the hole's, because that is what
# somebody pressing an arrow means by it.
aurade_fifteen_slide() {
  local hole=$AURADE_FIFTEEN_HOLE from
  local hx=$(( hole % 4 )) hy=$(( hole / 4 ))
  case $1 in
    up)    (( hy < 3 )) || return 1; from=$(( hole + 4 )) ;;
    down)  (( hy > 0 )) || return 1; from=$(( hole - 4 )) ;;
    left)  (( hx < 3 )) || return 1; from=$(( hole + 1 )) ;;
    right) (( hx > 0 )) || return 1; from=$(( hole - 1 )) ;;
    *) return 1 ;;
  esac
  AURADE_FIFTEEN[hole]=${AURADE_FIFTEEN[from]}
  AURADE_FIFTEEN[from]=0
  AURADE_FIFTEEN_HOLE=$from
  AURADE_FIFTEEN_MOVES=$(( AURADE_FIFTEEN_MOVES + 1 ))
  return 0
}

aurade_fifteen_won() {
  local i
  for (( i = 0; i < 15; i++ )); do
    (( AURADE_FIFTEEN[i] == i + 1 )) || return 1
  done
  return 0
}

aurade_fifteen_rows() {
  local x y row cell
  for (( y = 0; y < 4; y++ )); do
    row=''
    for (( x = 0; x < 4; x++ )); do
      cell=${AURADE_FIFTEEN[y * 4 + x]}
      if (( cell )); then
        row+=$(printf '%4s' "$cell")
      else
        row+='    '
      fi
    done
    printf '%s\n' "$row"
  done
}

# --------------------------------------------------------------------------
# Minesweeper
# --------------------------------------------------------------------------
#
# A grid, a cursor and two actions, with no clock anywhere in it. Nine by nine
# with ten mines, which is the beginner board everybody has already played.
#
# The mines are placed after the first reveal, not before, and never under it.
# Losing on the first keypress of a game somebody started to pass the time is
# the single most annoying thing this screen could do, and the fix is three
# lines. Every implementation that gets this wrong got it wrong by placing
# first because that is the obvious order.
AURADE_MINE_W=9
AURADE_MINE_H=9
AURADE_MINE_COUNT=10
AURADE_MINES=()
AURADE_MINE_SHOWN=()
AURADE_MINE_FLAG=()
AURADE_MINE_X=4
AURADE_MINE_Y=4
AURADE_MINE_STARTED=0
AURADE_MINE_DEAD=0
AURADE_MINE_WON=0

aurade_mines_new() {
  local i
  AURADE_MINES=(); AURADE_MINE_SHOWN=(); AURADE_MINE_FLAG=()
  for (( i = 0; i < AURADE_MINE_W * AURADE_MINE_H; i++ )); do
    AURADE_MINES+=(0); AURADE_MINE_SHOWN+=(0); AURADE_MINE_FLAG+=(0)
  done
  AURADE_MINE_X=$(( AURADE_MINE_W / 2 ))
  AURADE_MINE_Y=$(( AURADE_MINE_H / 2 ))
  AURADE_MINE_STARTED=0
  AURADE_MINE_DEAD=0
  AURADE_MINE_WON=0
}

# Mines everywhere except the cell just opened and the ring around it, so the
# first reveal always opens something.
_aurade_mines_place() {
  local safe_x=$1 safe_y=$2 placed=0 x y index
  while (( placed < AURADE_MINE_COUNT )); do
    x=$(( RANDOM % AURADE_MINE_W ))
    y=$(( RANDOM % AURADE_MINE_H ))
    (( x < safe_x - 1 || x > safe_x + 1 || y < safe_y - 1 || y > safe_y + 1 )) || continue
    index=$(( y * AURADE_MINE_W + x ))
    (( ! AURADE_MINES[index] )) || continue
    AURADE_MINES[index]=1
    placed=$(( placed + 1 ))
  done
  AURADE_MINE_STARTED=1
}

aurade_mines_near() {
  local x=$1 y=$2 dx dy nx ny near=0
  for dy in -1 0 1; do
    for dx in -1 0 1; do
      (( dx || dy )) || continue
      nx=$(( x + dx )); ny=$(( y + dy ))
      (( nx >= 0 && nx < AURADE_MINE_W && ny >= 0 && ny < AURADE_MINE_H )) || continue
      (( ! AURADE_MINES[ny * AURADE_MINE_W + nx] )) || near=$(( near + 1 ))
    done
  done
  printf '%s' "$near"
}

# Opening an empty cell opens its neighbours too, which is the whole game.
# Iterative rather than recursive: bash recursion at eighty deep is slow
# enough to be visible on a screen redrawing eight times a second.
_aurade_mines_open() {
  local -a queue=("$1,$2")
  local item x y index near dx dy nx ny
  while (( ${#queue[@]} )); do
    item=${queue[0]}
    queue=("${queue[@]:1}")
    x=${item%,*}; y=${item#*,}
    index=$(( y * AURADE_MINE_W + x ))
    (( ! AURADE_MINE_SHOWN[index] )) || continue
    (( ! AURADE_MINE_FLAG[index] )) || continue
    AURADE_MINE_SHOWN[index]=1
    near=$(aurade_mines_near "$x" "$y")
    (( near == 0 )) || continue
    for dy in -1 0 1; do
      for dx in -1 0 1; do
        (( dx || dy )) || continue
        nx=$(( x + dx )); ny=$(( y + dy ))
        (( nx >= 0 && nx < AURADE_MINE_W && ny >= 0 && ny < AURADE_MINE_H )) || continue
        queue+=("$nx,$ny")
      done
    done
  done
}

aurade_mines_reveal() {
  local index=$(( AURADE_MINE_Y * AURADE_MINE_W + AURADE_MINE_X ))
  (( ! AURADE_MINE_DEAD && ! AURADE_MINE_WON )) || return 0
  (( ! AURADE_MINE_FLAG[index] )) || return 0
  (( AURADE_MINE_STARTED )) || _aurade_mines_place "$AURADE_MINE_X" "$AURADE_MINE_Y"
  if (( AURADE_MINES[index] )); then
    AURADE_MINE_DEAD=1
    return 0
  fi
  _aurade_mines_open "$AURADE_MINE_X" "$AURADE_MINE_Y"
  # Explicitly, because `aurade_mines_check` reports "not won yet" as a
  # non-zero status and this function would otherwise hand that to its caller
  # as a failure. Under errexit that is not a subtle bug: it ends the program
  # on the first move of a game.
  aurade_mines_check || true
  return 0
}

aurade_mines_flag() {
  local index=$(( AURADE_MINE_Y * AURADE_MINE_W + AURADE_MINE_X ))
  (( ! AURADE_MINE_DEAD && ! AURADE_MINE_WON )) || return 0
  (( ! AURADE_MINE_SHOWN[index] )) || return 0
  AURADE_MINE_FLAG[index]=$(( ! AURADE_MINE_FLAG[index] ))
  return 0
}

# Won when every cell that is not a mine has been opened. Flags are not part
# of it: a board can be finished without planting one, and requiring them
# would be inventing a rule.
aurade_mines_check() {
  local i
  for (( i = 0; i < AURADE_MINE_W * AURADE_MINE_H; i++ )); do
    (( AURADE_MINES[i] || AURADE_MINE_SHOWN[i] )) || return 1
  done
  AURADE_MINE_WON=1
  return 0
}

aurade_mines_move() {
  case $1 in
    up)    (( AURADE_MINE_Y > 0 )) && AURADE_MINE_Y=$(( AURADE_MINE_Y - 1 )) || true ;;
    down)  (( AURADE_MINE_Y < AURADE_MINE_H - 1 )) && AURADE_MINE_Y=$(( AURADE_MINE_Y + 1 )) || true ;;
    left)  (( AURADE_MINE_X > 0 )) && AURADE_MINE_X=$(( AURADE_MINE_X - 1 )) || true ;;
    right) (( AURADE_MINE_X < AURADE_MINE_W - 1 )) && AURADE_MINE_X=$(( AURADE_MINE_X + 1 )) || true ;;
  esac
  return 0
}

aurade_mines_rows() {
  local x y row index cell near left right
  for (( y = 0; y < AURADE_MINE_H; y++ )); do
    row=''
    for (( x = 0; x < AURADE_MINE_W; x++ )); do
      index=$(( y * AURADE_MINE_W + x ))
      if (( AURADE_MINE_DEAD && AURADE_MINES[index] )); then
        cell='*'
      elif (( AURADE_MINE_FLAG[index] )); then
        cell='F'
      elif (( ! AURADE_MINE_SHOWN[index] )); then
        cell='#'
      else
        near=$(aurade_mines_near "$x" "$y")
        (( near )) && cell=$near || cell='.'
      fi
      left=' '; right=' '
      if (( x == AURADE_MINE_X && y == AURADE_MINE_Y )); then left='['; right=']'; fi
      row+="$left$cell$right"
    done
    printf '%s\n' "$row"
  done
}

# --------------------------------------------------------------------------
# Nonogram
# --------------------------------------------------------------------------
#
# Picross, in text, and the one thing on this screen that rewards a ten minute
# window rather than being interrupted by one. Pure logic, no timing, and
# every step of it is deduction rather than guessing.
#
# The pictures are drawn by hand rather than generated. A random grid produces
# clues that are technically solvable and give no satisfaction at all, because
# the reward for finishing a nonogram is seeing what it was, and a random one
# is never anything. Eight by eight, which is small enough to finish while a
# disk is being written and large enough to be a picture.
# One picture per line, a row of the grid between each colon, so that the
# pictures are legible in the source. A wall of dots on one line is not, and
# the whole point of these is that somebody drew them.
AURADE_NONO_ART=(
  'heart:.##..##.:########:########:########:.######.:..####..:...##...:........'
  'cat:#......#:##....##:########:#.#..#.#:########:.######.:..#..#..:........'
  'key:..####..:.#....#.:.#....#.:..####..:...##...:...####.:...##...:...###..'
  'up:...##...:..####..:.######.:########:...##...:...##...:...##...:...##...'
  'wave:........:..##....:.####.#.:########:########:.######.:..####..:........'
  'die:########:#......#:#.##...#:#......#:#...##.#:#......#:#......#:########'
)
AURADE_NONO_W=8
AURADE_NONO_H=8
AURADE_NONO_SOLUTION=()
AURADE_NONO_MARKS=()
AURADE_NONO_X=0
AURADE_NONO_Y=0
AURADE_NONO_NAME=

aurade_nono_new() {
  local entry rows row x y
  local -a _nono_rows=()
  entry=${AURADE_NONO_ART[RANDOM % ${#AURADE_NONO_ART[@]}]}
  AURADE_NONO_NAME=${entry%%:*}
  rows=${entry#*:}
  AURADE_NONO_SOLUTION=()
  AURADE_NONO_MARKS=()
  IFS=':' read -r -a _nono_rows <<<"$rows"
  for (( y = 0; y < AURADE_NONO_H; y++ )); do
    row=${_nono_rows[y]}
    for (( x = 0; x < AURADE_NONO_W; x++ )); do
      if [[ ${row:x:1} == '#' ]]; then
        AURADE_NONO_SOLUTION+=(1)
      else
        AURADE_NONO_SOLUTION+=(0)
      fi
      # 0 unknown, 1 filled, 2 ruled out
      AURADE_NONO_MARKS+=(0)
    done
  done
  AURADE_NONO_X=0
  AURADE_NONO_Y=0
  return 0
}

# The runs of filled cells along one line, which is what a clue is.
_aurade_nono_runs() {
  local -n _cells=$1
  local out='' run=0 cell
  for cell in "${_cells[@]}"; do
    if (( cell )); then
      run=$(( run + 1 ))
    elif (( run )); then
      out+="$run "
      run=0
    fi
  done
  (( ! run )) || out+="$run "
  [[ -n $out ]] || out='0 '
  printf '%s' "${out% }"
}

aurade_nono_row_clue() {
  local y=$1 x
  local -a cells=()
  for (( x = 0; x < AURADE_NONO_W; x++ )); do
    cells+=("${AURADE_NONO_SOLUTION[y * AURADE_NONO_W + x]}")
  done
  _aurade_nono_runs cells
}

aurade_nono_col_clue() {
  local x=$1 y
  local -a cells=()
  for (( y = 0; y < AURADE_NONO_H; y++ )); do
    cells+=("${AURADE_NONO_SOLUTION[y * AURADE_NONO_W + x]}")
  done
  _aurade_nono_runs cells
}

aurade_nono_move() {
  case $1 in
    up)    (( AURADE_NONO_Y > 0 )) && AURADE_NONO_Y=$(( AURADE_NONO_Y - 1 )) || true ;;
    down)  (( AURADE_NONO_Y < AURADE_NONO_H - 1 )) && AURADE_NONO_Y=$(( AURADE_NONO_Y + 1 )) || true ;;
    left)  (( AURADE_NONO_X > 0 )) && AURADE_NONO_X=$(( AURADE_NONO_X - 1 )) || true ;;
    right) (( AURADE_NONO_X < AURADE_NONO_W - 1 )) && AURADE_NONO_X=$(( AURADE_NONO_X + 1 )) || true ;;
  esac
  return 0
}

# Unknown, filled, ruled out, and back. One key rather than two, because two
# keys on a grid means remembering which is which.
aurade_nono_cycle() {
  local index=$(( AURADE_NONO_Y * AURADE_NONO_W + AURADE_NONO_X ))
  AURADE_NONO_MARKS[index]=$(( (AURADE_NONO_MARKS[index] + 1) % 3 ))
  return 0
}

# Solved when every filled cell is filled. Cells ruled out are not checked:
# they are the player's notes, not their answer, and finishing a picture
# without using them is a legitimate way to play.
aurade_nono_won() {
  local i
  for (( i = 0; i < AURADE_NONO_W * AURADE_NONO_H; i++ )); do
    if (( AURADE_NONO_SOLUTION[i] )); then
      (( AURADE_NONO_MARKS[i] == 1 )) || return 1
    else
      (( AURADE_NONO_MARKS[i] != 1 )) || return 1
    fi
  done
  return 0
}
