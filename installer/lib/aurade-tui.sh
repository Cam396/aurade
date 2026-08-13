# shellcheck shell=bash
# Hand-rolled ANSI text UI for the AuraDE installer.
#
# No dialog, no whiptail, no gum. The installation image's package list is part
# of its reproducibility and size budget, and a UI toolkit is a poor thing to
# spend either on when the whole interface is eleven screens of framed text.
#
# The alignment rule that shapes this file: width is always computed on plain
# text, before any colour is added. Every earlier attempt at this drifted
# because escape sequences were measured as if they were characters, and the
# right-hand frame of one row landed a column off from the row above it. Here
# `_tui_pad` never sees an escape sequence, and the test suite re-measures the
# rendered output rather than trusting that.
#
# The second rule: the interior is strictly ASCII. Box-drawing characters are
# reliably one column wide; check marks, arrows, bullets and ellipses are not,
# and a double-width glyph in the body pushes the frame out by one column on
# exactly the terminals least able to show it. So the frame may be Unicode and
# the contents may not.
#
# Degradation is three tiers, and the bottom tier is not a courtesy. NO_COLOR,
# TERM=dumb and "output is not a terminal" all land on plain ASCII with no
# escapes at all, which is also the serial console and screen reader path, and
# it has to stay fully operable rather than merely legible.

# Total frame width, and the interior between the two vertical rules.
AURADE_TUI_WIDTH=68
AURADE_TUI_INNER=$(( AURADE_TUI_WIDTH - 2 ))
AURADE_TUI_INDENT=2

# Tier selection. Both variables may be preset by the caller: the test suite
# forces specific combinations, and an operator on a stubborn terminal can
# export AURADE_TUI_FRAME=ascii without arguing with the detector.
_tui_detect() {
  if [[ -z ${AURADE_TUI_COLOR:-} ]]; then
    local colors=0
    if [[ -n ${NO_COLOR:-} ]]; then
      AURADE_TUI_COLOR=none
    elif [[ ${TERM:-dumb} == dumb || -z ${TERM:-} ]]; then
      AURADE_TUI_COLOR=none
    elif [[ ! -t 1 ]]; then
      AURADE_TUI_COLOR=none
    else
      colors=$(tput colors 2>/dev/null || printf '0')
      [[ $colors =~ ^[0-9]+$ ]] || colors=0
      if (( colors >= 256 )); then
        AURADE_TUI_COLOR=256
      elif (( colors >= 8 )); then
        AURADE_TUI_COLOR=16
      else
        AURADE_TUI_COLOR=none
      fi
    fi
  fi
  if [[ -z ${AURADE_TUI_FRAME:-} ]]; then
    if [[ ${TERM:-dumb} == dumb || -z ${TERM:-} ]] || [[ ! -t 1 ]]; then
      AURADE_TUI_FRAME=ascii
    else
      AURADE_TUI_FRAME=unicode
    fi
  fi
}
_tui_detect

# Palette. Each token carries an xterm-256 index and a 16-colour stand-in, so
# the two colour tiers are the same design rather than two designs.
_tui_sgr() {
  local token=$1
  case $AURADE_TUI_COLOR in
    none) return 0 ;;
    256)
      case $token in
        border)  printf '\033[38;5;239m' ;;
        ink)     printf '\033[38;5;253m' ;;
        dim)     printf '\033[38;5;245m' ;;
        accent)  printf '\033[38;5;147m' ;;
        cyan)    printf '\033[38;5;116m' ;;
        ok)      printf '\033[38;5;115m' ;;
        warn)    printf '\033[38;5;215m' ;;
        danger)  printf '\033[38;5;210m' ;;
        bold)    printf '\033[1m' ;;
        reverse) printf '\033[7m' ;;
      esac
      ;;
    16)
      case $token in
        border)  printf '\033[90m' ;;
        ink)     printf '\033[97m' ;;
        dim)     printf '\033[90m' ;;
        accent)  printf '\033[94m' ;;
        cyan)    printf '\033[96m' ;;
        ok)      printf '\033[92m' ;;
        warn)    printf '\033[93m' ;;
        danger)  printf '\033[91m' ;;
        bold)    printf '\033[1m' ;;
        reverse) printf '\033[7m' ;;
      esac
      ;;
  esac
}

_tui_reset() {
  [[ $AURADE_TUI_COLOR == none ]] || printf '\033[0m'
}

_tui_glyph() {
  local part=$1
  if [[ $AURADE_TUI_FRAME == unicode ]]; then
    case $part in
      tl) printf '┌' ;; tr) printf '┐' ;;
      bl) printf '└' ;; br) printf '┘' ;;
      h)  printf '─' ;; v)  printf '│' ;;
      ml) printf '├' ;; mr) printf '┤' ;;
    esac
  else
    case $part in
      tl|tr|bl|br|ml|mr) printf '+' ;;
      h) printf '-' ;;
      v) printf '|' ;;
    esac
  fi
}

# Pad plain text to an exact column count. Truncates rather than overflowing:
# a body line that runs long is a wrapping bug, and a broken frame hides it
# less usefully than a clipped word does.
_tui_pad() {
  local text=$1 width=$2 length=${#1}
  if (( length > width )); then
    printf '%s' "${text:0:width}"
  else
    printf '%s%*s' "$text" "$((width - length))" ''
  fi
}

_tui_rule() {
  local i
  for (( i = 0; i < AURADE_TUI_INNER; i++ )); do _tui_glyph h; done
}

tui_top()    { _tui_sgr border; _tui_glyph tl; _tui_rule; _tui_glyph tr; _tui_reset; printf '\n'; }
tui_sep()    { _tui_sgr border; _tui_glyph ml; _tui_rule; _tui_glyph mr; _tui_reset; printf '\n'; }
tui_bottom() { _tui_sgr border; _tui_glyph bl; _tui_rule; _tui_glyph br; _tui_reset; printf '\n'; }

# One framed row. `text` is plain and already carries its own indentation; the
# colour token is applied to the whole span after the width is settled.
tui_line() {
  local text=${1-} token=${2:-ink}
  _tui_sgr border; _tui_glyph v; _tui_reset
  _tui_sgr "$token"
  _tui_pad "$text" "$AURADE_TUI_INNER"
  _tui_reset
  _tui_sgr border; _tui_glyph v; _tui_reset
  printf '\n'
}

tui_blank() { tui_line '' ink; }

# Left text and right text on one row, with the gap between them absorbing the
# slack. Used for the header (title / step counter) and the footer (key hints /
# status), which is where a one-column error is most visible.
tui_pair() {
  local left=${1-} right=${2-} token=${3:-ink} indent=$AURADE_TUI_INDENT gap
  gap=$(( AURADE_TUI_INNER - indent - ${#left} - ${#right} - indent ))
  (( gap >= 1 )) || gap=1
  tui_line "$(printf '%*s%s%*s%s' "$indent" '' "$left" "$gap" '' "$right")" "$token"
}

# Greedy word wrap. Emits whole rows, so callers never compute a width.
#
# `hang` indents every line after the first, which is what a marked note needs:
# without it the continuation of a `! ...` warning starts under the marker and
# reads as a second, unmarked sentence.
tui_wrap() {
  local text=$1 token=${2:-ink} indent=${3:-$AURADE_TUI_INDENT} hang=${4:-}
  local line='' word first=1 current=$indent limit
  [[ -n $hang ]] || hang=$indent
  limit=$(( AURADE_TUI_INNER - indent - AURADE_TUI_INDENT ))
  (( limit > 0 )) || limit=1
  _emit() {
    tui_line "$(printf '%*s%s' "$current" '' "$1")" "$token"
    if (( first )); then
      first=0
      current=$hang
      limit=$(( AURADE_TUI_INNER - hang - AURADE_TUI_INDENT ))
      (( limit > 0 )) || limit=1
    fi
  }
  for word in $text; do
    if [[ -z $line ]]; then
      line=$word
    elif (( ${#line} + 1 + ${#word} <= limit )); then
      line+=" $word"
    else
      _emit "$line"
      line=$word
    fi
  done
  [[ -z $line ]] || _emit "$line"
  unset -f _emit
}

# A marked note: one ASCII marker, then text whose continuation lines hang
# under the text rather than under the marker.
tui_note() {
  local marker=$1 text=$2 token=${3:-ink}
  tui_wrap "$marker $text" "$token" "$AURADE_TUI_INDENT" \
    "$(( AURADE_TUI_INDENT + ${#marker} + 1 ))"
}

# A label/value table. The label column is fixed so values line up down the
# screen; this is the disk identity block on the erase gate, where a reader
# comparing a serial number against a sticker needs the columns stable.
#
# The value wraps into its own column rather than being truncated. Two of the
# places this is used - the failed-stage detail and the graphics diagnosis -
# carry exactly the sentence the user needs in order to act, and clipping it at
# the frame is how that sentence gets lost.
#
# The separating space is printed explicitly rather than relying on the label
# column's padding, so a label longer than the column still has one.
AURADE_TUI_LABEL=16
tui_field() {
  local label=$1 value=$2 token=${3:-ink}
  local indent=$(( AURADE_TUI_INDENT * 2 )) column limit line='' word first=1
  column=$(( indent + AURADE_TUI_LABEL + 1 ))
  limit=$(( AURADE_TUI_INNER - column - AURADE_TUI_INDENT ))
  (( limit > 0 )) || limit=1
  _field_emit() {
    if (( first )); then
      tui_line "$(printf '%*s%-*s %s' "$indent" '' "$AURADE_TUI_LABEL" "$label" "$1")" "$token"
      first=0
    else
      tui_line "$(printf '%*s%s' "$column" '' "$1")" "$token"
    fi
  }
  for word in $value; do
    if [[ -z $line ]]; then
      line=$word
    elif (( ${#line} + 1 + ${#word} <= limit )); then
      line+=" $word"
    else
      _field_emit "$line"
      line=$word
    fi
  done
  if [[ -n $line ]] || (( first )); then
    _field_emit "$line"
  fi
  unset -f _field_emit
}

# Menu row. The marker is ASCII on purpose; `>` is one column everywhere.
# Text starts one indent inside the body text so a list reads as a list, and
# the selected and unselected rows put their text in the same column.
tui_item() {
  local selected=$1 text=$2 token=${3:-ink} marker='   '
  if [[ $selected == yes ]]; then
    marker='  >'
    [[ $token != ink ]] || token=accent
  fi
  tui_line "$(printf '%s %s' "$marker" "$text")" "$token"
}

# Fixed-width progress bar, ASCII cells. Width is a constant rather than a
# fraction of the frame so that the bar does not shift as the label beside it
# changes length.
tui_bar() {
  local pct=$1 label=${2:-} width=${3:-34} filled i bar='' indent
  [[ $pct =~ ^[0-9]+$ ]] || pct=0
  (( pct <= 100 )) || pct=100
  filled=$(( pct * width / 100 ))
  for (( i = 0; i < width; i++ )); do
    if (( i < filled )); then bar+='#'; else bar+='-'; fi
  done
  indent=$(( AURADE_TUI_INDENT * 3 ))
  tui_line "$(printf '%*s[%s]  %s' "$indent" '' "$bar" "$label")" cyan
}

# Screen chrome. Every screen is header / body / footer, and the header and
# footer are always present, so the user always knows where they are and what
# keys do something.
tui_header() {
  local right=${1:-}
  tui_top
  tui_pair 'AuraDE' "$right" accent
  tui_sep
}

tui_footer() {
  local left=${1:-} right=${2:-}
  tui_sep
  tui_pair "$left" "$right" dim
  tui_bottom
}

tui_clear() {
  [[ $AURADE_TUI_COLOR == none ]] && return 0
  [[ -t 1 ]] || return 0
  printf '\033[H\033[2J'
}

# Step counter as a coarse bar for the header. Stays ASCII for the same reason
# the body does.
tui_steps() {
  local current=$1 total=$2 i out=''
  for (( i = 1; i <= total; i++ )); do
    if (( i <= current )); then out+='*'; else out+='-'; fi
  done
  printf '[%s]' "$out"
}

# Key input, normalised to names. Arrow keys arrive as multi-byte escape
# sequences and a bare ESC arrives as the same first byte, so the continuation
# read is given a short timeout: without it, pressing escape blocks until the
# next keypress and the UI appears frozen.
#
# AURADE_TUI_KEYS lets the flow tests supply key names directly. It is a seam
# for driving the state machine, not a way to skip decoding: the decoder below
# is exercised separately against raw byte sequences.
tui_read_key() {
  local key rest
  if [[ -n ${AURADE_TUI_KEYS:-} ]]; then
    IFS= read -r key <&"${_TUI_KEYFD:-0}" || return 1
    printf '%s' "$key"
    return 0
  fi
  IFS= read -rsn1 key || return 1
  case $key in
    '')      printf 'enter'; return 0 ;;
    $'\t')   printf 'tab'; return 0 ;;
    $'\177'|$'\b') printf 'backspace'; return 0 ;;
    ' ')     printf 'space'; return 0 ;;
    $'\033') ;;
    *)       printf '%s' "$key"; return 0 ;;
  esac
  if ! IFS= read -rsn2 -t 0.05 rest; then
    printf 'esc'
    return 0
  fi
  case $rest in
    '[A') printf 'up' ;;
    '[B') printf 'down' ;;
    '[C') printf 'right' ;;
    '[D') printf 'left' ;;
    *)    printf 'esc' ;;
  esac
}

# Decode a raw byte string to a key name. Same mapping as tui_read_key, split
# out so it can be tested without a terminal.
tui_decode_key() {
  case $1 in
    '') printf 'enter' ;;
    $'\t') printf 'tab' ;;
    $'\177'|$'\b') printf 'backspace' ;;
    ' ') printf 'space' ;;
    $'\033[A') printf 'up' ;;
    $'\033[B') printf 'down' ;;
    $'\033[C') printf 'right' ;;
    $'\033[D') printf 'left' ;;
    $'\033') printf 'esc' ;;
    $'\033'*) printf 'esc' ;;
    *) printf '%s' "$1" ;;
  esac
}
