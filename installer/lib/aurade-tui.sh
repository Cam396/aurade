# shellcheck shell=bash
# Hand-rolled ANSI text UI for the AuraDE installer.
# Width is measured before colour escapes are added. The content stays ASCII so
# terminals, console readers, and braille displays see the same layout.

# Frame width. The layout grows from 68 to 100 columns, then stays centered.
# Tests can pin the terminal dimensions for reproducible output.
AURADE_TUI_WIDTH=${AURADE_TUI_WIDTH:-}
AURADE_TUI_COLUMNS=${AURADE_TUI_COLUMNS:-}
AURADE_TUI_INDENT=2

#: Whether the caller fixed these, in which case a resize must not move them.
#: A test that pins a width and then gets a different one because the machine
#: running it has a wide terminal is a test measuring the terminal.
_TUI_COLUMNS_PINNED=0
_TUI_WIDTH_PINNED=0
[[ -z $AURADE_TUI_COLUMNS ]] || _TUI_COLUMNS_PINNED=1
[[ -z $AURADE_TUI_WIDTH ]]   || _TUI_WIDTH_PINNED=1

# Work out the frame from the terminal. Called once at startup, and again
# every time the terminal changes size under us.
tui_measure() {
  if (( ! _TUI_COLUMNS_PINNED )); then
    AURADE_TUI_COLUMNS=$(tput cols 2>/dev/null || printf '')
    [[ $AURADE_TUI_COLUMNS =~ ^[0-9]+$ ]] || AURADE_TUI_COLUMNS=${COLUMNS:-80}
    (( AURADE_TUI_COLUMNS >= 40 )) || AURADE_TUI_COLUMNS=80
  fi
  if (( ! _TUI_WIDTH_PINNED )); then
    # 68 for anything up to a standard terminal, 88 when there is room to read
    # comfortably, 100 at the top. Past that the measure stops growing and the
    # margins take the rest, which is what a page does.
    if   (( AURADE_TUI_COLUMNS >= 108 )); then AURADE_TUI_WIDTH=100
    elif (( AURADE_TUI_COLUMNS >= 94 ));  then AURADE_TUI_WIDTH=88
    else AURADE_TUI_WIDTH=68
    fi
    (( AURADE_TUI_WIDTH <= AURADE_TUI_COLUMNS )) || AURADE_TUI_WIDTH=$AURADE_TUI_COLUMNS
  fi
  AURADE_TUI_INNER=$(( AURADE_TUI_WIDTH - 2 ))
  #: Left margin that centres the frame in the terminal. Printed before every
  #: row rather than by moving the cursor, so the output stays a plain stream
  #: that can be piped, captured and diffed.
  AURADE_TUI_MARGIN=$(( (AURADE_TUI_COLUMNS - AURADE_TUI_WIDTH) / 2 ))
  (( AURADE_TUI_MARGIN >= 0 )) || AURADE_TUI_MARGIN=0
  tui_measure_panes
}

# Filled in below, once plain mode is known. Declared here so the first call
# to `tui_measure` has something to call.
tui_measure_panes() { :; }

tui_measure

# Two panes are decided further down, once plain mode is known, because plain
# mode has no columns at all.

# How many rows there are to spend.
#
# The width is fixed, because a frame that changes shape between screens reads
# as two programs. The height is not something this can fix by choosing: a
# virtual console is whatever the firmware left it as, and the progress screen
# now has more it would like to draw than fits on the short ones. So it is
# measured, and the screen spends what it has.
#
# Preset by the tests, and pinned to a known value there, so that a screen
# rendered on a build machine with a tall terminal and a screen rendered in CI
# are the same screen.
# Plain mode: the same screens with the drawing taken out.
#
# A refreshable braille display renders the frame character by character. Every
# `|`, every `+`, every rule, every pad space is a cell under somebody's
# fingers, forever, and the frame is 68 columns wide on a display that is
# commonly 40. The colour tiers already fall back to plain ASCII, which fixes
# nothing here: plain ASCII box drawing is still box drawing.
#
# So this is not a degraded tier below `none`. It is a different rendering of
# the same screens: no frame, no padding, no art, no games, one thing per line,
# leading indentation stripped because indentation is visual structure and this
# is not being looked at.
#
# It is not a downgrade and it is not a different product. Same words, same
# flow, same order.
#: High contrast for the text installer, the counterpart of the graphical
#: front end's high contrast sheets. Off unless asked for.
AURADE_TUI_CONTRAST=${AURADE_TUI_CONTRAST:-0}

AURADE_TUI_PLAIN=${AURADE_TUI_PLAIN:-}
if [[ -z $AURADE_TUI_PLAIN ]]; then
  AURADE_TUI_PLAIN=0
  # `brltty` running is the strongest signal there is: somebody has a braille
  # display attached right now. `TERM=dumb` is the other one, and it is what a
  # serial console and several screen reader setups report.
  # espeakup is listed here for the same reason brltty is, arrived at
  # differently: it reads the console text straight out of the framebuffer, so
  # every rule and every pad space is spoken as punctuation. Braille wants the
  # drawing gone because it costs cells; speech wants it gone because it gets
  # read out. One rendering answers both.
  if [[ ${TERM:-dumb} == dumb ]] ||
     pgrep -x brltty >/dev/null 2>&1 ||
     pgrep -x espeakup >/dev/null 2>&1; then
    AURADE_TUI_PLAIN=1
  fi
fi
# Plain implies no colour. Escape sequences are not cells, but a reader that
# hits them mid-line has to skip them, and there is nothing for them to do.
(( ! AURADE_TUI_PLAIN )) || AURADE_TUI_COLOR=none

# Two panes, when the frame is wide enough that neither of them ends up
# cramped.
#
# The split only exists at the top measure. At 88 columns a second column
# would make two narrow columns out of one comfortable one, which is worse
# than what it replaced, so the answer there is no. Plain mode never splits:
# columns are a thing for an eye that moves sideways, and reading a line of
# braille or listening to it goes in one direction only.
#
# The interior divides as left pane, space, rule, space, right pane. The rule
# is a real column rather than a wider gap, because two columns of text with
# only whitespace between them read as one ragged column, which is the failure
# this layout exists to avoid.
AURADE_TUI_TWOPANE=0
AURADE_TUI_PANE_LEFT=0
AURADE_TUI_PANE_RIGHT=0

# Redefined now that plain mode is known. `tui_measure` calls this, so a
# resize recomputes the split along with everything else.
tui_measure_panes() {
  AURADE_TUI_TWOPANE=0
  AURADE_TUI_PANE_LEFT=0
  AURADE_TUI_PANE_RIGHT=0
  (( ! AURADE_TUI_PLAIN )) || return 0
  (( AURADE_TUI_WIDTH >= 100 )) || return 0
  AURADE_TUI_TWOPANE=1
  # Slightly under half to the left, because the left pane holds labels and
  # short values and the right holds prose, and prose is the half that gets
  # better with more room.
  AURADE_TUI_PANE_LEFT=$(( (AURADE_TUI_INNER * 46) / 100 ))
  AURADE_TUI_PANE_RIGHT=$(( AURADE_TUI_INNER - AURADE_TUI_PANE_LEFT - 3 ))
}
tui_measure_panes

AURADE_TUI_HEIGHT=${AURADE_TUI_HEIGHT:-}
if [[ -z $AURADE_TUI_HEIGHT ]]; then
  AURADE_TUI_HEIGHT=$(tput lines 2>/dev/null || printf '')
  [[ $AURADE_TUI_HEIGHT =~ ^[0-9]+$ ]] || AURADE_TUI_HEIGHT=${LINES:-24}
  (( AURADE_TUI_HEIGHT >= 10 )) || AURADE_TUI_HEIGHT=24
fi

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
      # Truecolor is not in terminfo. `tput colors` reports 256 on terminals
      # that have done 24 bit for years, because the capability was never
      # added, so the only reliable signal is the one terminals agreed on
      # among themselves.
      if [[ ${COLORTERM:-} == truecolor || ${COLORTERM:-} == 24bit ]] &&
         (( colors >= 256 )); then
        AURADE_TUI_COLOR=true
      elif (( colors >= 256 )); then
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
    elif [[ ${TERM:-} == linux ]]; then
      # The virtual console, whose font is a few hundred glyphs. The straight
      # box drawing is in it, which is why the frame is safe there at all. The
      # rounded corners are not, and a corner that falls back to a blank is a
      # frame with four holes in it.
      AURADE_TUI_FRAME=unicode
    else
      AURADE_TUI_FRAME=rounded
    fi
  fi
}
_tui_detect

# Palette. Each token carries an xterm-256 index and a 16-colour stand-in, so
# the two colour tiers are the same design rather than two designs.
# Repaint the console's own palette in the brand's colours.
#
# The Linux virtual console reports eight colours and means it: `tput colors`
# says 8, there is no 256 tier to reach for and no truecolor, and this is the
# terminal the installer actually runs on. So the brand arrives there by a
# different route than a terminal emulator: the console's sixteen palette
# entries are not fixed, they are registers, and OSC P rewrites them.
#
# `\033]P<slot><rrggbb>` where slot is one hex digit. After this the ordinary
# 16 colour tier is drawing the exact colours the graphical front end draws,
# on a framebuffer console, with no 256 colour support anywhere in sight.
#
# Only on the Linux console. The sequence is that console's own extension and
# an emulator that does not know it will print the payload as text, which is
# why this is gated on TERM rather than attempted and hoped for.
#
# Restored on exit, because the palette outlives the process: a console left
# with a lilac "blue" is a console every later program draws wrongly on.
AURADE_TUI_PALETTE_SET=0

tui_palette_apply() {
  [[ ${TERM:-} == linux ]] || return 0
  [[ -t 1 ]] || return 0
  (( ! AURADE_TUI_PALETTE_SET )) || return 0
  # Slot, colour. These are `tokens.scheme(True)` again, the same values the
  # truecolor tier uses, mapped onto the slots the 16 colour tier names.
  printf '\033]P8434653'   # bright black  -> outline_variant  (border, dim)
  printf '\033]PFe0e2e9'   # bright white  -> on_surface       (ink)
  printf '\033]PCd1bcff'   # bright blue   -> primary          (accent)
  printf '\033]PE87d0ef'   # bright cyan   -> tertiary         (cyan)
  printf '\033]PAbec5e5'   # bright green  -> secondary        (ok)
  printf '\033]PDfabc52'   # bright yellow -> warning          (warn)
  printf '\033]P9feb4ab'   # bright red    -> error            (danger)
  AURADE_TUI_PALETTE_SET=1
}

tui_palette_reset() {
  (( AURADE_TUI_PALETTE_SET )) || return 0
  printf '\033]R'
  AURADE_TUI_PALETTE_SET=0
}

# The terminal's own title bar.
#
# This is the real answer to a ten minute wait. A percentage in a tab or a
# taskbar means somebody can go and do something else and glance back, which
# is what they wanted the whole time. Costs one escape sequence per stage.
#
# Not on the Linux console: OSC 0 is not an extension it has, and the payload
# would be printed across the screen. That console gets the brand a different
# way, in `tui_palette_apply`, which is the sequence it does understand.
AURADE_TUI_TITLE_SET=0
tui_title() {
  local text=${1-}
  [[ -t 1 ]] || return 0
  (( ! AURADE_TUI_PLAIN )) || return 0
  case ${TERM:-dumb} in linux|dumb|'') return 0 ;; esac
  printf '\033]0;%s\007' "$text"
  AURADE_TUI_TITLE_SET=1
}

# Put it back to nothing on the way out, the same courtesy as the palette. A
# terminal left claiming to be installing an operating system, half an hour
# after the installer exited, is a small lie that outlives the program.
tui_title_reset() {
  (( AURADE_TUI_TITLE_SET )) || return 0
  printf '\033]0;\007'
  AURADE_TUI_TITLE_SET=0
}

_tui_sgr() {
  local token=$1
  # High contrast: bright white on the default ground for everything that is
  # text, and bold for the things that were carrying meaning in colour.
  #
  # Not a fourth colour tier and not "the same palette but brighter". The
  # normal tiers separate `dim` from `ink` by about two steps of grey, which is
  # the separation somebody turns this on because they cannot see. So the
  # distinction stops being carried by shade at all: everything readable goes
  # to white, and what was a colour becomes a weight.
  if (( AURADE_TUI_CONTRAST )); then
    case $token in
      border)  printf '\033[1;37m' ;;
      dim)     printf '\033[0;37m' ;;
      ink)     printf '\033[1;37m' ;;
      accent|cyan|ok|warn|danger) printf '\033[1;37m' ;;
      bold)    printf '\033[1m' ;;
      reverse) printf '\033[7m' ;;
    esac
    return 0
  fi
  case $AURADE_TUI_COLOR in
    none) return 0 ;;
    # The exact colours the graphical front end draws, rather than the nearest
    # of 256. These are `tokens.scheme(dark)`, copied as literals because the
    # text installer cannot import Python and a second approximation of the
    # brand is the thing this tier exists to remove.
    #
    # The frame border is `outline_variant` and the accents are `primary` and
    # `tertiary`, which is lilac and aqua: the two ends of the mark's own
    # gradient. One product, two renderings, same colours.
    true)
      case $token in
        border)  printf '\033[38;2;67;70;83m' ;;
        ink)     printf '\033[38;2;224;226;233m' ;;
        dim)     printf '\033[38;2;194;198;213m' ;;
        accent)  printf '\033[38;2;209;188;255m' ;;
        cyan)    printf '\033[38;2;135;208;239m' ;;
        ok)      printf '\033[38;2;190;197;229m' ;;
        warn)    printf '\033[38;2;250;188;82m' ;;
        danger)  printf '\033[38;2;254;180;171m' ;;
        bold)    printf '\033[1m' ;;
        reverse) printf '\033[7m' ;;
      esac
      ;;
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

# True for the tiers that can draw box characters at all, whichever corners
# they use. Anything that asks "is this a unicode terminal" has to accept both
# of them, and forgetting one is how the rounded tier silently loses the
# braille progress bar.
tui_frame_unicode() {
  case $AURADE_TUI_FRAME in
    unicode|rounded) return 0 ;;
    *) return 1 ;;
  esac
}

_tui_glyph() {
  local part=$1
  if [[ $AURADE_TUI_FRAME == rounded ]]; then
    case $part in
      tl) printf '╭' ;; tr) printf '╮' ;;
      bl) printf '╰' ;; br) printf '╯' ;;
      h)  printf '─' ;; v)  printf '│' ;;
      ml) printf '├' ;; mr) printf '┤' ;;
      tt) printf '┬' ;; bt) printf '┴' ;;
    esac
  elif [[ $AURADE_TUI_FRAME == unicode ]]; then
    case $part in
      tl) printf '┌' ;; tr) printf '┐' ;;
      bl) printf '└' ;; br) printf '┘' ;;
      h)  printf '─' ;; v)  printf '│' ;;
      ml) printf '├' ;; mr) printf '┤' ;;
      tt) printf '┬' ;; bt) printf '┴' ;;
    esac
  else
    case $part in
      tl|tr|bl|br|ml|mr|tt|bt) printf '+' ;;
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

# The frame's horizontal rules, run as a gradient from the mark's lilac to its
# aqua when the terminal can draw one.
#
# These are the same two colours the mark's own stroke runs between and the
# same two the graphical front end draws its hairline with, so the two
# installers are recognisably one product rather than two that share a name.
#
# Only at the truecolor tier. In 256 colours the ramp between these two tones
# is four or five steps and reads as banding rather than as a gradient, and
# banding looks like a rendering fault. The other tiers keep the flat border
# they had, which is not a consolation prize: a flat hairline is what the
# design was before this and it looked deliberate.
#
# Every character is its own escape sequence, which is why this is confined to
# three rules a screen rather than used anywhere in the body. Three rules of a
# hundred columns is a few kilobytes a redraw, which a local terminal does not
# notice. A serial console would, and never sees it: those report vt220 and
# land on the 16 colour tier.
AURADE_TUI_GRADIENT_FROM='209 188 255'
AURADE_TUI_GRADIENT_TO='135 208 239'

# The colour this far along the gradient, as an escape sequence.
_tui_gradient_at() {
  local i=$1 last=$2
  local -a from=() to=()
  read -r -a from <<<"$AURADE_TUI_GRADIENT_FROM"
  read -r -a to <<<"$AURADE_TUI_GRADIENT_TO"
  (( last > 0 )) || last=1
  (( i <= last )) || i=$last
  printf '\033[38;2;%d;%d;%dm' \
    "$(( from[0] + (to[0] - from[0]) * i / last ))" \
    "$(( from[1] + (to[1] - from[1]) * i / last ))" \
    "$(( from[2] + (to[2] - from[2]) * i / last ))"
}

# True when the frame should be drawn as a gradient rather than flat.
_tui_gradient() {
  [[ $AURADE_TUI_COLOR == true ]] || return 1
  (( AURADE_TUI_INNER >= 8 )) || return 1
  return 0
}

_tui_rule() {
  local i last
  if ! _tui_gradient; then
    for (( i = 0; i < AURADE_TUI_INNER; i++ )); do _tui_glyph h; done
    return 0
  fi
  # The corners count as the two ends of the run, so the interpolation is
  # across the whole width of the frame and not just its interior. A gradient
  # that restarts inside the corners has a seam at each end.
  last=$(( AURADE_TUI_INNER + 1 ))
  for (( i = 0; i < AURADE_TUI_INNER; i++ )); do
    _tui_gradient_at "$(( i + 1 ))" "$last"
    _tui_glyph h
  done
}

# The colour for the corner at each end of a rule. Flat border everywhere the
# gradient is off, so callers do not have to know which tier they are on.
_tui_edge_left()  { if _tui_gradient; then _tui_gradient_at 0 "$(( AURADE_TUI_INNER + 1 ))"; else _tui_sgr border; fi; }
_tui_edge_right() { if _tui_gradient; then _tui_gradient_at "$(( AURADE_TUI_INNER + 1 ))" "$(( AURADE_TUI_INNER + 1 ))"; else _tui_sgr border; fi; }

# In plain mode the top and bottom edges are nothing at all, and the separator
# is one blank line: the break between header and body is real structure and
# survives, the 68 dashes drawing it are not.
#: The left margin, printed rather than moved to. A frame drawn with cursor
#: positioning cannot be piped into a file and diffed, and every render test
#: in this suite does exactly that.
_tui_margin() { (( AURADE_TUI_MARGIN <= 0 )) || printf '%*s' "$AURADE_TUI_MARGIN" ''; }

tui_top()    { (( ! AURADE_TUI_PLAIN )) || return 0
               _tui_margin; _tui_edge_left; _tui_glyph tl; _tui_rule
               _tui_edge_right; _tui_glyph tr; _tui_reset; printf '\n'; }
tui_sep()    { (( ! AURADE_TUI_PLAIN )) || { printf '\n'; return 0; }
               _tui_margin; _tui_edge_left; _tui_glyph ml; _tui_rule
               _tui_edge_right; _tui_glyph mr; _tui_reset; printf '\n'; }
tui_bottom() { (( ! AURADE_TUI_PLAIN )) || return 0
               _tui_margin; _tui_edge_left; _tui_glyph bl; _tui_rule
               _tui_edge_right; _tui_glyph br; _tui_reset; printf '\n'; }

# One framed row. `text` is plain and already carries its own indentation; the
# colour token is applied to the whole span after the width is settled.
_tui_plain_emit() {
  local text=${1-}
  text=${text#"${text%%[![:space:]]*}"}
  text=${text%"${text##*[![:space:]]}"}
  while [[ $text == *"  "* ]]; do text=${text//  / }; done
  printf '%s\n' "$text"
}

tui_line() {
  local text=${1-} token=${2:-ink}
  if (( AURADE_TUI_CAPTURE )); then
    # Being captured into a column. The text is kept unpadded and the token
    # alongside it, because the width it will be padded to is the pane's, not
    # the frame's, and the colour has to survive to be applied to that half of
    # the row on its own.
    TUI_CAPTURED+=("$text")
    TUI_CAPTURED_TOKEN+=("$token")
    return 0
  fi
  if (( AURADE_TUI_PLAIN )); then
    # Leading indentation is visual structure and costs a braille cell each;
    # trailing padding is worse, because it is cells with nothing in them.
    # A row that is only whitespace becomes a genuine blank line, which is the
    # one piece of spacing worth keeping.
    # Leading indentation is visual structure and costs a cell each, trailing
    # padding is cells with nothing in them, and interior padding is a column
    # being lined up for an eye that is not there. Seven printf formats across
    # the progress screen and the disk table pad to a column; collapsing here
    # fixes all of them at once and leaves those formats honest about what
    # they are for, which is looking.
    _tui_plain_emit "$text"
    return 0
  fi
  _tui_margin
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
  if (( AURADE_TUI_PLAIN )); then
    # Two separate facts, so two lines. Padded apart on one line they are a
    # long run of blank cells between two words.
    [[ -z $left ]]  || _tui_plain_emit "$left"
    [[ -z $right ]] || _tui_plain_emit "$right"
    return 0
  fi
  gap=$(( AURADE_TUI_INNER - indent - ${#left} - ${#right} - indent ))
  (( gap >= 1 )) || gap=1
  tui_line "$(printf '%*s%s%*s%s' "$indent" '' "$left" "$gap" '' "$right")" "$token"
}

# --------------------------------------------------------------------------
# Two panes
# --------------------------------------------------------------------------
#
# A list on the left and what the selected line means on the right, which is
# the shape lazygit and btop use and the reason they are legible at a glance.
#
# The whole mechanism is one redirection. Every drawing function in this file
# ends at `tui_line`, so making that one function collect rows instead of
# printing them is enough to make wrapping, fields, notes and menu rows all
# compose into a narrower column without a single one of them knowing there is
# such a thing as a pane. The interior width is narrowed for the duration,
# because that is the number they all wrap against.
#
# What this deliberately does not do is lay out the two panes as one grid.
# They are rendered independently and then set beside each other, so a change
# to either side cannot move the other, and a pane that runs longer than its
# neighbour just leaves blank rows rather than pushing anything.

#: Rows collected instead of printed, with the colour token each was drawn
#: with, because a captured row is coloured when it is placed rather than when
#: it is written.
AURADE_TUI_CAPTURE=0
TUI_CAPTURED=()
TUI_CAPTURED_TOKEN=()
_TUI_PANE_INNER=0
_TUI_PANE_SIDE=''
_TUI_PANE_L_TEXT=()
_TUI_PANE_L_TOKEN=()
_TUI_PANE_R_TEXT=()
_TUI_PANE_R_TOKEN=()

# tui_pane_begin left|right
tui_pane_begin() {
  _TUI_PANE_SIDE=$1
  TUI_CAPTURED=()
  TUI_CAPTURED_TOKEN=()
  AURADE_TUI_CAPTURE=1
  _TUI_PANE_INNER=$AURADE_TUI_INNER
  case $1 in
    left)  AURADE_TUI_INNER=$AURADE_TUI_PANE_LEFT ;;
    right) AURADE_TUI_INNER=$AURADE_TUI_PANE_RIGHT ;;
  esac
}

tui_pane_end() {
  AURADE_TUI_CAPTURE=0
  AURADE_TUI_INNER=$_TUI_PANE_INNER
  case $_TUI_PANE_SIDE in
    left)
      _TUI_PANE_L_TEXT=(${TUI_CAPTURED[@]+"${TUI_CAPTURED[@]}"})
      _TUI_PANE_L_TOKEN=(${TUI_CAPTURED_TOKEN[@]+"${TUI_CAPTURED_TOKEN[@]}"})
      ;;
    right)
      _TUI_PANE_R_TEXT=(${TUI_CAPTURED[@]+"${TUI_CAPTURED[@]}"})
      _TUI_PANE_R_TOKEN=(${TUI_CAPTURED_TOKEN[@]+"${TUI_CAPTURED_TOKEN[@]}"})
      ;;
  esac
  _TUI_PANE_SIDE=''
  TUI_CAPTURED=()
  TUI_CAPTURED_TOKEN=()
}

# One row with a pane on each side of a rule.
_tui_split() {
  local left=${1-} right=${2-} ltoken=${3:-ink} rtoken=${4:-dim}
  _tui_margin
  _tui_sgr border; _tui_glyph v; _tui_reset
  _tui_sgr "$ltoken"; _tui_pad "$left" "$AURADE_TUI_PANE_LEFT"; _tui_reset
  _tui_sgr border; printf ' '; _tui_glyph v; printf ' '; _tui_reset
  _tui_sgr "$rtoken"; _tui_pad "$right" "$AURADE_TUI_PANE_RIGHT"; _tui_reset
  _tui_sgr border; _tui_glyph v; _tui_reset
  printf '\n'
}

# The rule above and below the split, with a tee where the divider meets it.
# A divider that starts and stops in open space looks like a drawing mistake;
# a tee is the difference between a layout and two lists that happen to be
# next to each other.
tui_pane_rule() {
  local part=${1:-tt} i
  (( AURADE_TUI_TWOPANE )) || { tui_sep; return 0; }
  _tui_margin
  _tui_sgr border
  _tui_glyph ml
  for (( i = 0; i < AURADE_TUI_PANE_LEFT + 1; i++ )); do _tui_glyph h; done
  _tui_glyph "$part"
  for (( i = AURADE_TUI_PANE_LEFT + 2; i < AURADE_TUI_INNER; i++ )); do _tui_glyph h; done
  _tui_glyph mr
  _tui_reset
  printf '\n'
}

# Set the two captured panes side by side and clear them.
tui_pane_flush() {
  local i rows=${#_TUI_PANE_L_TEXT[@]}
  (( ${#_TUI_PANE_R_TEXT[@]} <= rows )) || rows=${#_TUI_PANE_R_TEXT[@]}
  for (( i = 0; i < rows; i++ )); do
    _tui_split "${_TUI_PANE_L_TEXT[i]-}" "${_TUI_PANE_R_TEXT[i]-}" \
               "${_TUI_PANE_L_TOKEN[i]:-ink}" "${_TUI_PANE_R_TOKEN[i]:-dim}"
  done
  _TUI_PANE_L_TEXT=(); _TUI_PANE_L_TOKEN=()
  _TUI_PANE_R_TEXT=(); _TUI_PANE_R_TOKEN=()
}

# Split a string into words without pathname expansion.
#
# `for word in $text` is the idiomatic way to do this and it is wrong here:
# unquoted expansion globs, so a string containing * or ? is replaced by the
# filenames it happens to match. Every string this file renders comes from
# somewhere a glob character can appear - a journal message, a device path, a
# failure detail - and the first time it happened, an export error turned into
# a listing of the repository root.
TUI_WORDS=()
_tui_words() {
  local had_noglob=1
  [[ -o noglob ]] || had_noglob=0
  set -f
  # shellcheck disable=SC2206  # deliberate word splitting, globbing disabled
  TUI_WORDS=( $1 )
  (( had_noglob )) || set +f
}

# Both wrappers below are greedy on whole words, and a word longer than the
# column has nowhere to break. Left alone it is emitted whole and runs straight
# through the right-hand frame, which is not hypothetical: `lsblk` reports disk
# models with underscores instead of spaces, and a by-id device path is one
# unbroken token about seventy characters long. Both of those are rendered on
# the erase gate, next to the serial number somebody is checking against a
# sticker, which is the last screen in the product that should look broken.
#
# So an over-long word is cut at the column. Losing a character boundary is
# ugly; losing the frame is a bug.
_tui_chunk() {
  local word=$1 limit=$2
  (( limit > 0 )) || limit=1
  printf '%s' "${word:0:limit}"
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
  _tui_words "$text"
  for word in "${TUI_WORDS[@]}"; do
    # `limit` shrinks after the first row when a hang indent is in play, so it
    # is re-read on every pass rather than captured once.
    while (( ${#word} > limit )); do
      [[ -z $line ]] || { _emit "$line"; line=''; }
      _emit "$(_tui_chunk "$word" "$limit")"
      word=${word:limit}
    done
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
  if (( AURADE_TUI_PLAIN )); then
    # The column exists so a reader comparing a serial number against a sticker
    # has stable columns to scan. Nobody scans a braille line, they read it, so
    # the pair goes back to being a pair.
    tui_wrap "$label: $value" "$token"
    return 0
  fi
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
  _tui_words "$value"
  for word in "${TUI_WORDS[@]}"; do
    while (( ${#word} > limit )); do
      [[ -z $line ]] || { _field_emit "$line"; line=''; }
      _field_emit "$(_tui_chunk "$word" "$limit")"
      word=${word:limit}
    done
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
#: Braille cells at eight levels of fill, empty to full.
#:
#: A braille cell is two columns of four dots, so filling it left to right
#: gives eight steps inside a single character. At thirty four cells that is
#: 272 positions instead of 34, and the difference is visible: the bar moves
#: continuously instead of jumping a whole cell at a time, which is what makes
#: a progress bar look like it is measuring something.
#:
#: Never in plain mode. On an actual refreshable braille display these are not
#: a picture of anything, they are eight random dot patterns under a finger.
#:
#: And never on the Linux virtual console, which is where this installer
#: mostly runs. Its fonts carry a few hundred glyphs and the box drawing is
#: among them, which is why the frame is safe there; the braille block is not,
#: and a bar drawn out of missing glyphs is a row of blanks. The frame tier
#: cannot answer this on its own, because that console is a unicode tier that
#: happens to have a very small font.
AURADE_TUI_BRAILLE=(' ' '⡀' '⡄' '⡆' '⡇' '⣇' '⣧' '⣷' '⣿')

tui_bar() {
  local pct=$1 label=${2:-} width=${3:-34} filled i bar='' indent
  local eighths partial
  [[ $pct =~ ^[0-9]+$ ]] || pct=0
  (( pct <= 100 )) || pct=100
  if (( AURADE_TUI_PLAIN )); then
    # Thirty four cells of hash and dash say the same thing as two words, and
    # take thirty two cells longer to say it.
    tui_line "$(printf '%s percent. %s' "$pct" "$label")"
    return 0
  fi
  if tui_frame_unicode && [[ ${TERM:-} != linux ]]; then
    # Eighths of a cell, so the last partial cell is drawn at the level it has
    # actually reached rather than rounded away.
    eighths=$(( pct * width * 8 / 100 ))
    filled=$(( eighths / 8 ))
    partial=$(( eighths % 8 ))
    for (( i = 0; i < width; i++ )); do
      if (( i < filled )); then
        bar+=${AURADE_TUI_BRAILLE[8]}
      elif (( i == filled )); then
        bar+=${AURADE_TUI_BRAILLE[partial]}
      else
        bar+=${AURADE_TUI_BRAILLE[0]}
      fi
    done
  else
    filled=$(( pct * width / 100 ))
    for (( i = 0; i < width; i++ )); do
      if (( i < filled )); then bar+='#'; else bar+='-'; fi
    done
  fi
  indent=$(( AURADE_TUI_INDENT * 3 ))
  tui_line "$(printf '%*s[%s]  %s' "$indent" '' "$bar" "$label")" cyan
}

# Eight heights of one cell, for the shape of a series over time.
AURADE_TUI_SPARK=('▁' '▂' '▃' '▄' '▅' '▆' '▇' '█')
# The same shape where a terminal has no block elements. Chosen for visual
# weight rather than for character height, because at one cell per sample the
# eye reads density long before it reads where the ink sits in the cell.
AURADE_TUI_SPARK_ASCII=('_' '.' '-' '=' '#')

# A sparkline of a series, scaled to its own maximum.
#
# Relative scaling is the point: what a download meter is for is telling a
# steady line from a collapsing one, and a series drawn against some absolute
# ceiling is flat at the bottom on every connection that is not a leased line.
# The cost is that the height alone says nothing about magnitude, which is why
# every caller prints the current value next to it. Shape here, number there.
tui_spark() {
  local -a values=("$@") ramp
  local value max=0 levels index out='' clean
  (( ${#values[@]} > 0 )) || return 0
  if tui_frame_unicode && [[ ${TERM:-} != linux ]]; then
    ramp=("${AURADE_TUI_SPARK[@]}")
  else
    ramp=("${AURADE_TUI_SPARK_ASCII[@]}")
  fi
  levels=${#ramp[@]}
  clean=()
  for value in "${values[@]}"; do
    [[ $value =~ ^[0-9]+$ ]] || continue
    clean+=("$value")
    (( value <= max )) || max=$value
  done
  (( ${#clean[@]} > 0 )) || return 0
  for value in "${clean[@]}"; do
    if (( max == 0 )); then
      # Nothing has arrived yet. A flat line at the floor is the truth; a
      # divide by zero is a stack trace on somebody's install screen.
      index=0
    else
      index=$(( value * (levels - 1) / max ))
    fi
    out+=${ramp[index]}
  done
  printf '%s' "$out"
}

# Bytes per second, in the units somebody reading a download meter thinks in.
# Powers of two, because that is what the file sizes it is derived from are,
# and one decimal place, because two is noise on a number that changes every
# second.
tui_rate() {
  local rate=$1
  [[ $rate =~ ^[0-9]+$ ]] || { printf ''; return 0; }
  if (( rate >= 1048576 )); then
    printf '%d.%d MB/s' "$(( rate / 1048576 ))" "$(( rate % 1048576 * 10 / 1048576 ))"
  elif (( rate >= 1024 )); then
    printf '%d.%d kB/s' "$(( rate / 1024 ))" "$(( rate % 1024 * 10 / 1024 ))"
  else
    printf '%d B/s' "$rate"
  fi
}

# Screen chrome. Every screen is header / body / footer, and the header and
# footer are always present, so the user always knows where they are and what
# keys do something.
# The optional last argument is the rule that closes the header and opens the
# footer. `split` gives it the tee that meets the divider between two panes,
# and falls back to the plain rule wherever there is only one column, so a
# screen can ask for it without first working out whether it got one.
tui_header() {
  local right=${1:-} rule=${2:-plain}
  tui_top
  tui_pair 'AuraDE' "$right" accent
  case $rule in
    split) tui_pane_rule tt ;;
    *)     tui_sep ;;
  esac
}

tui_footer() {
  local left=${1:-} right=${2:-} rule=${3:-plain} hint='?  help'
  # `?  help` joins the footer wherever there is room for it, and is silently
  # left off where there is not.
  #
  # Two conditions, both of which matter. It is only offered on screens where
  # the key does something: a field collecting a passphrase turns the help key
  # off, because a question mark is a character there, and a footer offering a
  # key that does nothing is worse than a footer that says less. And it is
  # only offered when it fits, because it goes on the right hand end, which is
  # the end the frame clips, and the thing already sitting there is `esc back`
  # which is what somebody stuck on a screen actually needs.
  if (( ${HELP_KEY:-0} )) && [[ -n $right ]] &&
     (( ${#left} + ${#hint} + 4 + ${#right} + 2 * AURADE_TUI_INDENT <= AURADE_TUI_INNER )); then
    right="$hint    $right"
  fi
  case $rule in
    split) tui_pane_rule bt ;;
    *)     tui_sep ;;
  esac
  tui_pair "$left" "$right" dim
  tui_bottom
}

# Sound, as a pattern rather than a pitch.
#
# If you cannot see the screen and an install takes ten minutes, a sound at the
# end is not decoration: it is the only thing that tells you it is over rather
# than stuck. The same is true if you can see the screen and went to make tea.
#
# The terminal bell, deliberately, and no audio files. `espeakup` implies an
# audio path exists but a bare virtual console with no sound card does not, and
# a completion tone that depends on a sound stack is a completion tone that is
# missing on exactly the hardware most likely to be installing from a console.
# The bell is what a terminal has always had.
#
# Distinguished by count, because a bell has one pitch: one for finished, three
# for stopped. Two things somebody can tell apart across a room without
# looking, which is the whole requirement.
#
# Written to the terminal rather than to stdout, so it never lands in a render
# a test is measuring, and skipped entirely when there is no terminal.
tui_bell() {
  local count=${1:-1} i
  (( ! ${AURADE_TUI_QUIET:-0} )) || return 0
  [[ -t 1 ]] || return 0
  for (( i = 0; i < count; i++ )); do
    printf '\a' >&2
    (( i + 1 == count )) || sleep 0.15
  done
}

tui_clear() {
  # Not in plain mode. Wiping the screen throws away what a reader may still be
  # working through, and there is no cursor addressing to put it back.
  (( ! AURADE_TUI_PLAIN )) || { printf '\n'; return 0; }
  [[ $AURADE_TUI_COLOR == none ]] && return 0
  [[ -t 1 ]] || return 0
  printf '\033[H\033[2J'
}

# Step counter as a coarse bar for the header. Stays ASCII for the same reason
# the body does.
tui_steps() {
  local current=$1 total=$2 i out=''
  if (( AURADE_TUI_PLAIN )); then
    # Nothing. The bar is the visual companion to the words "Step 4 of 9"
    # printed beside it, and saying "step 4 of 9" here made the header say it
    # twice. A drawn thing whose prose already exists does not need a plain
    # translation, it needs to go.
    return 0
  fi
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
# Resizing the terminal mid install used to leave the frame in pieces until
# the next screen, because the width was measured once at startup and never
# again.
#
# Catching it is not where the difficulty is. Every screen here is drawn by a
# loop that blocks on a key, and that key is read inside a command
# substitution, and a subshell does not inherit its parent's traps: the parent
# cannot see the signal until the read it is waiting on returns, which is
# after the next keypress, which is far too late to be a redraw.
#
# So the trap is armed here, inside the subshell doing the reading, where it
# does interrupt the read. The interrupted read reports `redraw`, which is a
# key name the screens already understand, and the parent remeasures when it
# sees one. No caller learns a new concept.
# The rest of an escape sequence, read one byte at a time and stopped by the
# byte that ends it.
#
# A fixed length read cannot do this and the fixed length read that was here
# is why F1 did not work at a real terminal. An arrow is two bytes after the
# escape, F1 is two on one terminal and four on another, and reading exactly
# two every time turned F1 into `esc` plus a stray byte, which is to say it
# went back a screen. `tui_decode_key` knew all three forms and was tested on
# all three; nothing that read a terminal ever called it.
_tui_read_escape() {
  local seq=$'\033' byte
  IFS= read -rsn1 -t 0.05 byte || { printf '%s' "$seq"; return 0; }
  seq+=$byte
  case $byte in
    # SS3, which is what most emulators send for the function keys: exactly
    # one more byte, and it may well be a letter, so the loop below would stop
    # before reading it.
    O) IFS= read -rsn1 -t 0.05 byte && seq+=$byte
       printf '%s' "$seq"; return 0 ;;
    '[') ;;
    *) printf '%s' "$seq"; return 0 ;;
  esac
  while IFS= read -rsn1 -t 0.05 byte; do
    seq+=$byte
    case $byte in [A-Za-z~]) break ;; esac
    (( ${#seq} < 12 )) || break
  done
  printf '%s' "$seq"
}

# Bracketed paste, which is both a courtesy and a safety measure.
#
# The courtesy: typing ERASE:/dev/nvme0n1 by hand is a real motor and
# cognitive load, and somebody who wants to paste it should be able to.
#
# The safety is the less obvious half and is the reason this is turned on
# rather than left alone. Without it a terminal delivers a paste as ordinary
# keystrokes, so pasting a line that ends in a newline types the token and
# then presses enter, and the confirmation screen submits itself. With it, the
# terminal wraps the paste in markers, everything between them is data, and
# the newline that came along with the copied line is not a decision.
#
# So the gate ends up harder to pass by accident than it was, which is the
# only direction that screen is allowed to move.
# The mouse, which a terminal will report if asked and which nothing here was
# asking for.
#
# Two modes, together: 1000 turns on button reporting, and 1006 asks for it in
# the extended encoding, which is the one that does not break past column 223.
# The old encoding packs coordinates into single bytes, so a click on the
# right of a wide terminal arrives as a control character.
#
# Off in plain mode, where there is nothing to point at, and off when output
# is not a terminal, where the request would simply be printed.
AURADE_TUI_MOUSE_SET=0
tui_mouse_on() {
  [[ -t 1 ]] || return 0
  (( ! AURADE_TUI_PLAIN )) || return 0
  printf '\033[?1000h\033[?1006h'
  AURADE_TUI_MOUSE_SET=1
}

tui_mouse_off() {
  (( AURADE_TUI_MOUSE_SET )) || return 0
  printf '\033[?1006l\033[?1000l'
  AURADE_TUI_MOUSE_SET=0
}

AURADE_TUI_PASTE_SET=0
tui_paste_on() {
  [[ -t 1 ]] || return 0
  (( ! AURADE_TUI_PLAIN )) || return 0
  printf '\033[?2004h'
  AURADE_TUI_PASTE_SET=1
}

tui_paste_off() {
  (( AURADE_TUI_PASTE_SET )) || return 0
  printf '\033[?2004l'
  AURADE_TUI_PASTE_SET=0
}

# Everything between the paste markers, as one string.
#
# Control characters come out. A newline at the end of a paste is the line
# ending the text was copied with, not an instruction, and a tab in the middle
# of a device path is a copy that went slightly wrong rather than an answer.
# Bounded, because the other end of this is a terminal and a paste is however
# much somebody had on their clipboard.
_tui_read_paste() {
  local text='' byte
  while IFS= read -rsn1 -t 5 byte; do
    text+=$byte
    if [[ ${text: -6} == $'\033[201~' ]]; then
      text=${text%$'\033[201~'}
      break
    fi
    (( ${#text} < 4096 )) || break
  done
  text=${text//[$'\001'-$'\037']/}
  printf '%s' "$text"
}

_TUI_RESIZED=0
tui_read_key() {
  local key
  if [[ -n ${AURADE_TUI_KEYS:-} ]]; then
    IFS= read -r key <&"${_TUI_KEYFD:-0}" || return 1
    printf '%s' "$key"
    return 0
  fi
  _TUI_RESIZED=0
  trap '_TUI_RESIZED=1' WINCH
  if ! IFS= read -rsn1 key; then
    (( ! _TUI_RESIZED )) || { printf 'redraw'; return 0; }
    return 1
  fi
  [[ $key != $'\033' ]] || key=$(_tui_read_escape)
  key=$(tui_decode_key "$key")
  # A paste is not a keystroke, so it comes back as its own thing carrying
  # what was pasted. Screens that collect text add it to what they have;
  # every other screen sees a key name longer than one character and ignores
  # it, which is exactly what should happen when somebody pastes into a menu.
  if [[ $key == paste-start ]]; then
    printf 'paste:%s' "$(_tui_read_paste)"
    return 0
  fi
  printf '%s' "$key"
}

# A key if one is already waiting, and otherwise nothing, after `timeout`.
#
# This is what makes the progress screen able to animate and to hand keystrokes
# to a game without ever blocking on the person watching an install. It is also
# a fix for something that was quietly wrong: for the whole of a ten minute
# install, nothing read standard input at all. Anything typed in that time sat
# in the terminal buffer and was delivered to whatever screen came next, so a
# few bored presses of return during pacstrap could arrive at the failure menu
# and choose something. Draining input is the point, and the game is what the
# drained input is spent on.
#
# Returns 1 when nothing was pressed, so a caller can tell "no key" from a key.
tui_poll_key() {
  local timeout=${1:-0.12} key
  if [[ -n ${AURADE_TUI_KEYS:-} ]]; then
    IFS= read -r -t "$timeout" key <&"${_TUI_KEYFD:-0}" || return 1
    printf '%s' "$key"
    return 0
  fi
  [[ -t 0 ]] || { sleep "$timeout"; return 1; }
  _TUI_RESIZED=0
  trap '_TUI_RESIZED=1' WINCH
  if ! IFS= read -rsn1 -t "$timeout" key; then
    (( ! _TUI_RESIZED )) || { printf 'redraw'; return 0; }
    return 1
  fi
  [[ $key != $'\033' ]] || key=$(_tui_read_escape)
  tui_decode_key "$key"
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
    # F1, in the three sequences terminals actually send for it: xterm and
    # most emulators, the linux virtual console, and the numbered form.
    #
    # It has to be decoded before the catch-all below, which folds every
    # unrecognised escape into `esc`. Without this, pressing F1 did not do
    # nothing: it went back a screen.
    $'\033OP'|$'\033[[A'|$'\033[11~') printf 'f1' ;;
    $'\033OQ'|$'\033[[B'|$'\033[12~') printf 'f2' ;;
    $'\033OR'|$'\033[[C'|$'\033[13~') printf 'f3' ;;
    # The opening marker of a bracketed paste. Decoded here, ahead of the
    # catch-all, for the same reason the function keys are: folded into `esc`
    # it would take a screen back and then type the pasted text into whatever
    # screen it landed on.
    $'\033[200~') printf 'paste-start' ;;
    # A mouse report in the extended encoding: button, column, row, then M for
    # a press and m for a release.
    #
    # Only the wheel is turned into anything. Buttons 64 and 65 are wheel up
    # and wheel down, and they become the arrow keys every screen already
    # understands, which is the entire feature: a long list of keyboard
    # layouts scrolls the way every other list on the machine scrolls.
    #
    # Ordinary clicks decode to nothing on purpose. A click carries a position
    # and this program's screens do not record where they drew anything, so
    # acting on one would mean guessing which row was meant. On the screen
    # where that guess would be worst, somebody is choosing a disk.
    $'\033[<'*[Mm])
      case $1 in
        $'\033[<64;'*M) printf 'up' ;;
        $'\033[<65;'*M) printf 'down' ;;
        *) printf 'mouse' ;;
      esac
      ;;
    $'\033'*) printf 'esc' ;;
    *) printf '%s' "$1" ;;
  esac
}
