"""The arcade, for the graphical front end.

Ten minutes is a long time to watch a bar move. The text installer has had
somewhere to put those minutes for a while now: a picker, two things to read,
one thing to watch, and eleven games. The graphical one had a snake, which is
one sixteenth of it, and the person waiting on the graphical one is waiting
exactly as long.

This is the other fifteen sixteenths. Same rules, same names, same order in
the picker, because two front ends that offer different games are two
products and the one you happened to boot decides which you get.

Two constraints shaped the file, and they are the reason it looks like this:

**No ``gi`` import anywhere in here.** Every game is a state machine that can
be played to its end by a test on a machine with no display, no compositor and
no toolkit, which is how the rules get checked at all. ``installer/tests`` runs
on machines with none of those.

**The painters take a Cairo context they did not create.** That keeps drawing
in the same file as the rules it draws, so a change to a board shape cannot
leave the picture behind, and it still costs no import: a context is a handed
in object, and ``cairo`` itself is never named here.

Nothing in this file reads the journal, runs a command, or has any route to
the engine. The worst a bug in here can do is draw badly.
"""

from __future__ import annotations

import random
import time

from .wait import Snake as SnakeRules

# --------------------------------------------------------------------------
# What the picker offers
# --------------------------------------------------------------------------
#
# The order is the text installer's, and the reasoning is the text
# installer's: the two options that ask nothing of anybody come first, so
# somebody who finds a game on a screen they are anxious about actively
# stressful meets them before the eleven that are games, and does not have to
# press past a snake to reach the reading.
#
# ``tips`` and ``bible`` are not games and are not in this file. They are
# faces the window already had, and they are named here so that one list is
# the whole menu rather than the menu being assembled in two places.
CHOICES: tuple[tuple[str, str], ...] = (
    ("tips", "Read something about this system"),
    ("bible", "Read the Bible"),
    ("life", "Something moving, that needs nothing"),
    ("type", "Test your typing, and your keyboard"),
    ("nono", "Solve a nonogram"),
    ("sudoku", "Solve a sudoku"),
    ("2048", "Play 2048"),
    ("mines", "Play minesweeper"),
    ("lights", "Play lights out"),
    ("fifteen", "Play the fifteen puzzle"),
    ("soko", "Play sokoban"),
    ("c4", "Play connect 4"),
    ("maze", "Play a maze, made just now"),
    ("word", "Play a word guess"),
    ("snake", "Play snake"),
    ("ttt", "Play tic-tac-toe"),
)

#: The picker entries that are not in this file. The window owns these.
NOT_GAMES = ("tips", "bible")


def label_for(ident: str) -> str:
    for key, text in CHOICES:
        if key == ident:
            return text
    return ident


# --------------------------------------------------------------------------
# Drawing, the small amount of it that every board needs
# --------------------------------------------------------------------------
#
# Cairo's own text API rather than Pango, which would mean importing gi and
# would put this file out of reach of a test with no display. A board is
# digits, single letters and a handful of short words, which is exactly the
# case the toy API covers without complaint.

#: Cairo's font enums, by value, so that ``cairo`` does not have to be
#: imported to name them. These three have been stable since 2005 and are part
#: of the ABI, not an implementation detail.
_SLANT_NORMAL = 0
_WEIGHT_NORMAL = 0
_WEIGHT_BOLD = 1

_TAU = 6.283185307179586


def rounded(cr, x: float, y: float, w: float, h: float, r: float) -> None:
    """A rounded rectangle as a path, left current so the caller can choose."""
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -_TAU / 4, 0)
    cr.arc(x + w - r, y + h - r, r, 0, _TAU / 4)
    cr.arc(x + r, y + h - r, r, _TAU / 4, _TAU / 2)
    cr.arc(x + r, y + r, r, _TAU / 2, _TAU * 3 / 4)
    cr.close_path()


def text_at(cr, s: str, cx: float, cy: float, size: float,
            bold: bool = False, mono: bool = False) -> None:
    """One short string, centred on a point.

    Centred on the ink rather than on the font's line box, because a board
    cell holding "8" and a board cell holding "128" have to look like they are
    on the same row, and the line box would centre the baseline instead.
    """
    if not s:
        return
    cr.select_font_face("monospace" if mono else "sans-serif", _SLANT_NORMAL,
                        _WEIGHT_BOLD if bold else _WEIGHT_NORMAL)
    cr.set_font_size(size)
    extents = cr.text_extents(s)
    cr.move_to(cx - extents.width / 2 - extents.x_bearing,
               cy - extents.height / 2 - extents.y_bearing)
    cr.show_text(s)


def text_left(cr, s: str, x: float, cy: float, size: float,
              bold: bool = False, mono: bool = False) -> float:
    """One string from a left edge. Returns the width it took."""
    if not s:
        return 0.0
    cr.select_font_face("monospace" if mono else "sans-serif", _SLANT_NORMAL,
                        _WEIGHT_BOLD if bold else _WEIGHT_NORMAL)
    cr.set_font_size(size)
    extents = cr.text_extents(s)
    cr.move_to(x - extents.x_bearing, cy - extents.height / 2 - extents.y_bearing)
    cr.show_text(s)
    return extents.x_advance


def fit(columns: float, rows: float, width: float, height: float,
        cap: float) -> tuple[float, float, float]:
    """A square cell that fits, and the corner to start drawing from.

    Every board here is a grid, every grid has to sit in whatever the card
    gives it, and doing that arithmetic in twelve places is twelve chances to
    get it slightly different. One cell size, centred, and the caller draws.

    The window works the same sum out before it draws the frame, from the
    same ``cells`` and ``max_cell`` the board declares, which is what makes
    the frame hug the board rather than being a white field with a small
    picture floating in the middle of it. Change one and change the other.
    """
    size = min(width / max(columns, 1e-6), height / max(rows, 1e-6), cap)
    size = max(size, 4.0)
    left = (width - size * columns) / 2
    top = (height - size * rows) / 2
    return size, left, top


class Game:
    """What the window needs from anything it can put on the waiting card.

    Deliberately small. The window knows how to give a game keys, a tick and a
    rectangle, and knows nothing else about any of them, which is what keeps
    adding the twelfth game from touching the eleven before it.
    """

    #: Picker id, matching ``CHOICES``.
    ident = ""
    #: What the keys do, in one line, under the board. Every game says this,
    #: because a board somebody cannot work out how to touch is a picture.
    keys = ""
    #: Milliseconds between ticks, or zero for a game that only moves when a
    #: key is pressed. Most of these are zero, which is the whole reason they
    #: are on a screen that redraws while a disk is being written.
    tick_ms = 0
    #: Read aloud when the board takes focus, for anybody who cannot see it.
    description = ""
    #: The board's shape, in cells, including any room its clues need outside
    #: the grid. ``None`` means "take the whole card", which is what the two
    #: games that grow with the window and the two that are mostly words all
    #: want. The window reads this to size the frame it draws behind the
    #: board, so a board that lies about its shape gets a frame that does not
    #: fit it.
    #:
    #: Called `grid` and not `cells` because two of the games in this file
    #: keep their own board in a list called `cells`, and an instance
    #: attribute quietly shadowing a class one turned Life into a blank card
    #: and a division by zero in the window's draw handler.
    grid: tuple[float, float] | None = None
    #: How large one cell is allowed to get. Without a cap, a four by four
    #: board on a wide card becomes four enormous squares.
    max_cell = 40.0

    def press(self, key: str) -> bool:
        """One key. Returns True when something changed and the board needs
        redrawing, False to hand the key back to the window."""
        return False

    def tick(self) -> bool:
        """One frame of a game that moves on its own."""
        return False

    # -- motion ------------------------------------------------------------
    #
    # Separate from `tick`, and the difference is the whole point. `tick` is
    # the game moving: the snake takes a step, Life computes a generation, and
    # it happens on the game's own slow clock whether or not anybody is
    # watching. This is a tile arriving, a counter falling, a square sliding
    # into a gap, and it happens at frame rate for a fraction of a second
    # after a key and then stops.
    #
    # Keeping them apart is what lets the window run a frame clock only while
    # something is actually moving. A board that animated on the same timer it
    # thinks on would be thirty wakeups a second for ten minutes on a machine
    # that is busy writing a filesystem.

    def animating(self) -> bool:
        """Whether something is mid-motion and needs another frame."""
        return False

    def frame(self, seconds: float) -> bool:
        """Advance the motion by this much wall clock. True if it changed."""
        return False

    def status(self) -> str:
        """The line beside the board. Score, moves, or what just happened."""
        return ""

    def paint(self, cr, width: float, height: float, ink: dict) -> None:
        """Draw into a rectangle whose origin the caller has already set."""


# --------------------------------------------------------------------------
# Life
# --------------------------------------------------------------------------
#
# Conway's, as something to watch rather than something to play, and first in
# the picker after the reading for a reason that is not about Conway. Some
# people do not want to be entertained while a disk is being erased. They want
# the minutes to pass. A thing that moves on its own, needs nothing, and
# cannot be lost is the only option here with all three.
#
# The grid wraps. A bounded one dies back to a few stable blobs in a corner
# inside a minute, which is a screen that has stopped, and the entire point is
# a screen that has not.


class Life(Game):
    ident = "life"
    keys = "Nothing to press. R for a new one."
    tick_ms = 220
    description = "Conway's Life, running on its own. Nothing to do."

    def __init__(self, width: int = 44, height: int = 22,
                 seed: int | None = None) -> None:
        self.width = max(8, width)
        self.height = max(6, height)
        self.random = random.Random(seed)
        self.reset()

    def reset(self) -> None:
        # Around a third alive. Sparser takes a long time to become
        # interesting; denser boils for a while and then collapses.
        self.cells = [1 if self.random.randrange(100) < 32 else 0
                      for _ in range(self.width * self.height)]
        self.age = 0

    def resize(self, width: int, height: int) -> None:
        if (width, height) == (self.width, self.height):
            return
        self.width, self.height = max(8, width), max(6, height)
        self.reset()

    def tick(self) -> bool:
        w, h, cells = self.width, self.height, self.cells
        nxt = [0] * (w * h)
        for y in range(h):
            up = ((y - 1) % h) * w
            mid = y * w
            down = ((y + 1) % h) * w
            for x in range(w):
                left = (x - 1) % w
                right = (x + 1) % w
                live = (cells[up + left] + cells[up + x] + cells[up + right] +
                        cells[mid + left] + cells[mid + right] +
                        cells[down + left] + cells[down + x] + cells[down + right])
                if cells[mid + x]:
                    nxt[mid + x] = 1 if live in (2, 3) else 0
                else:
                    nxt[mid + x] = 1 if live == 3 else 0
        self.cells = nxt
        self.age += 1
        return True

    def press(self, key: str) -> bool:
        if key in ("r", "R"):
            self.reset()
            return True
        return False

    def status(self) -> str:
        alive = sum(self.cells)
        return f"Generation {self.age}. {alive} alive."

    def paint(self, cr, width, height, ink) -> None:
        cell, left, top = fit(self.width, self.height, width, height, 24.0)
        # Round, not square. A grid of squares at this size reads as a
        # spreadsheet; a grid of dots reads as something alive, which is the
        # only thing this is for.
        radius = cell * 0.34
        cr.set_source_rgb(*ink["accent"])
        for y in range(self.height):
            for x in range(self.width):
                if not self.cells[y * self.width + x]:
                    continue
                cr.arc(left + (x + 0.5) * cell, top + (y + 0.5) * cell,
                       radius, 0, _TAU)
                cr.fill()


# --------------------------------------------------------------------------
# Snake
# --------------------------------------------------------------------------
#
# The rules already existed, in ``wait.py``, and they are tested there. This
# is the same object wearing the interface the picker hands keys to, rather
# than a second snake that agrees with the first until somebody edits one.


class SnakeGame(Game):
    ident = "snake"
    keys = "Arrows or WASD to steer."
    tick_ms = 150
    description = "Snake. Arrow keys to steer."

    #: The score at which the body stops being two colours and starts running
    #: the brand gradient. Nobody arrives here by accident, and anybody who
    #: decides to try gets there before the install finishes.
    GRADIENT_AT = 10

    TURNS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0),
             "w": (0, -1), "s": (0, 1), "a": (-1, 0), "d": (1, 0),
             "W": (0, -1), "S": (0, 1), "A": (-1, 0), "D": (1, 0)}

    def __init__(self, width: int = 28, height: int = 14,
                 seed: int | None = None) -> None:
        self.rules = SnakeRules(width, height, seed)

    def resize(self, width: int, height: int) -> None:
        if width == self.rules.width and height == self.rules.height:
            return
        self.rules = SnakeRules(width, height)

    @property
    def dead(self) -> bool:
        return self.rules.dead

    def tick(self) -> bool:
        self.rules.step()
        return True

    def press(self, key: str) -> bool:
        if key in self.TURNS:
            self.rules.turn(self.TURNS[key])
            return True
        if self.rules.dead:
            self.rules.reset()
            return True
        return False

    def status(self) -> str:
        if self.rules.dead:
            return f"Score {self.rules.score}. Any key to start again."
        return f"Score {self.rules.score}"

    def paint(self, cr, width, height, ink) -> None:
        rules = self.rules
        cell, left, top = fit(rules.width, rules.height, width, height, 26.0)
        if rules.food is not None:
            cr.set_source_rgb(*ink["warm"])
            fx, fy = rules.food
            cr.arc(left + (fx + 0.5) * cell, top + (fy + 0.5) * cell,
                   cell * 0.32, 0, _TAU)
            cr.fill()
        earned = rules.score >= self.GRADIENT_AT
        head, tail = ink["accent"], ink["warm"]
        count = max(len(rules.body) - 1, 1)
        for index, (x, y) in enumerate(rules.body):
            if earned:
                mix = index / count
                colour = tuple(head[i] + (tail[i] - head[i]) * mix for i in range(3))
            else:
                colour = head if index == 0 else ink["accent2"]
            cr.set_source_rgb(*colour)
            rounded(cr, left + x * cell + 1, top + y * cell + 1,
                    cell - 2, cell - 2, cell * 0.3)
            cr.fill()


# --------------------------------------------------------------------------
# The typing test
# --------------------------------------------------------------------------
#
# The keyboard layout check wearing a game's clothes, which is why it earns
# its place twice over: somebody who plays this for two minutes has proved
# their layout is right far more thoroughly than the field after the layout
# question can, and they were going to be sitting here anyway.
#
# The phrases are chosen for coverage rather than for wit. Between them they
# use every letter and the punctuation that moves between layouts, which is
# the punctuation a disk passphrase is made of.


class Typing(Game):
    ident = "type"
    keys = "Type it. Backspace to fix. Enter for another."
    description = ("A typing test, which is also a keyboard layout check. "
                   "Type the phrase shown.")

    PHRASES = (
        "The quick brown fox jumps over the lazy dog.",
        "Pack my box with five dozen liquid jars.",
        "How vexingly quick daft zebras jump!",
        "Sphinx of black quartz, judge my vow.",
        "Waltz, bad nymph, for quick jigs vex.",
    )

    def __init__(self, seed: int | None = None) -> None:
        self.random = random.Random(seed)
        self.reset()

    def reset(self) -> None:
        self.target = self.random.choice(self.PHRASES)
        self.typed = ""
        self.wrong = 0
        self.started = 0.0

    def press(self, key: str) -> bool:
        if key == "backspace":
            self.typed = self.typed[:-1]
            return True
        if key == "enter":
            self.reset()
            return True
        if len(key) != 1 or not key.isprintable():
            return False
        if len(self.typed) >= len(self.target):
            return True
        if not self.started:
            self.started = time.monotonic()
        # Wrong characters are counted and kept, not rejected. A test that
        # refuses the wrong key tells somebody their layout is fine by making
        # it impossible to demonstrate that it is not, which is the opposite
        # of what this is for.
        if key != self.target[len(self.typed)]:
            self.wrong += 1
        self.typed += key
        return True

    def done(self) -> bool:
        return len(self.typed) >= len(self.target)

    def seconds(self) -> float:
        if not self.started:
            return 0.0
        return time.monotonic() - self.started

    def status(self) -> str:
        if not self.typed:
            return "Type the line above."
        if self.done():
            elapsed = max(self.seconds(), 0.001)
            words = len(self.target) / 5 / (elapsed / 60)
            if self.wrong:
                return (f"{words:.0f} words a minute, {self.wrong} wrong. "
                        "Enter for another.")
            return f"{words:.0f} words a minute, all correct. Enter for another."
        if self.wrong:
            return f"{self.wrong} wrong so far."
        return "No mistakes so far."

    def paint(self, cr, width, height, ink) -> None:
        size = min(20.0, width / (len(self.target) * 0.62))
        line = size * 1.9
        top = height / 2 - line
        cr.select_font_face("monospace", _SLANT_NORMAL, _WEIGHT_NORMAL)
        cr.set_font_size(size)
        advance = cr.text_extents("M").x_advance
        left = (width - advance * len(self.target)) / 2

        # The phrase, then what was typed under it, character above character.
        # A wrong character is drawn in the error colour and underlined, so
        # that the mistake survives the colour being taken away, which is the
        # rule every screen in this product is held to.
        cr.set_source_rgb(*ink["dim"])
        for index, char in enumerate(self.target):
            text_at(cr, char, left + (index + 0.5) * advance, top, size, mono=True)
        for index, char in enumerate(self.typed):
            want = self.target[index] if index < len(self.target) else ""
            good = char == want
            cr.set_source_rgb(*(ink["ink"] if good else ink["bad"]))
            x = left + (index + 0.5) * advance
            text_at(cr, char, x, top + line, size, mono=True)
            if not good:
                cr.rectangle(x - advance / 2 + 1, top + line + size * 0.75,
                             advance - 2, max(1.0, size * 0.09))
                cr.fill()
        # The caret, so the eye knows where it is in a line of forty.
        if not self.done():
            cr.set_source_rgb(*ink["accent"])
            x = left + len(self.typed) * advance
            cr.rectangle(x, top + line - size * 0.6, max(1.5, advance * 0.09), size * 1.2)
            cr.fill()


# --------------------------------------------------------------------------
# Nonogram
# --------------------------------------------------------------------------
#
# Picross, and the one thing on this screen that rewards a ten minute window
# rather than being interrupted by one. Pure logic, no timing, every step of
# it deduction rather than guessing.
#
# The pictures are drawn by hand rather than generated. A random grid gives
# clues that are technically solvable and no satisfaction at all, because the
# reward for finishing a nonogram is seeing what it was, and a random one is
# never anything.


class Nonogram(Game):
    ident = "nono"
    keys = "Arrows to move. Space to fill, again to rule out."
    description = ("A nonogram. Arrow keys to move, space to fill a square "
                   "or rule it out.")
    grid = (11.4, 10.9)
    max_cell = 30.0

    ART = (
        ("heart", ".##..##.:########:########:########:.######.:..####..:...##...:........"),
        ("cat", "#......#:##....##:########:#.#..#.#:########:.######.:..#..#..:........"),
        ("key", "..####..:.#....#.:.#....#.:..####..:...##...:...####.:...##...:...###.."),
        ("up", "...##...:..####..:.######.:########:...##...:...##...:...##...:...##..."),
        ("wave", "........:..##....:.####.#.:########:########:.######.:..####..:........"),
        ("die", "########:#......#:#.##...#:#......#:#...##.#:#......#:#......#:########"),
        ("sun", "...##...:..####..:.######.:########:.######.:..####..:...##...:........"),
        ("house", "....#...:...###..:..#####.:########:##..#..#:##..#..#:########:........"),
        ("smile", ".######.:#......#:#.#..#.#:#......#:#.#..#.#:#..##..#:.#....#.:..####.."),
        ("flower", "...##...:...##...:..####..:.######.:...##...:..####..:.#....#.:#......#"),
        ("rocket", "...##...:..####..:..####..:.######.:########:...##...:..#..#..:.#....#."),
        ("star", "...#....:..###...:.#####..:#######.:.#####..:..###...:...#....:........"),
        ("tree", "...##...:..####..:.######.:########:..####..:.######.:...##...:...##..."),
        ("mug", "........:######..:#....###:#....#.#:#....###:######..:.####...:........"),
        ("boat", "....#...:...##...:..###...:.####...:....#...:........:########:.######."),
        ("bell", "...##...:..####..:..####..:.######.:.######.:########:........:...##..."),
        ("letter", "........:########:##....##:#.#..#.#:#..##..#:#......#:########:........"),
        ("anchor", "...##...:...##...:.######.:...##...:#..##..#:#..##..#:##....##:.######."),
        ("disk", "########:#..##..#:#..##..#:#......#:#.####.#:#.#..#.#:#.####.#:########"),
        ("battery", "........:...##...:########:##.##.##:##.##.##:##.##.##:########:........"),
    )
    WIDTH = 8
    HEIGHT = 8

    def __init__(self, seed: int | None = None) -> None:
        self.random = random.Random(seed)
        self.reset()

    def reset(self) -> None:
        self.name, rows = self.random.choice(self.ART)
        self.solution = []
        for row in rows.split(":"):
            for x in range(self.WIDTH):
                self.solution.append(1 if row[x:x + 1] == "#" else 0)
        # 0 unknown, 1 filled, 2 ruled out.
        self.marks = [0] * (self.WIDTH * self.HEIGHT)
        self.x = 0
        self.y = 0

    @staticmethod
    def runs(cells: list[int]) -> list[int]:
        out: list[int] = []
        run = 0
        for cell in cells:
            if cell:
                run += 1
            elif run:
                out.append(run)
                run = 0
        if run:
            out.append(run)
        return out or [0]

    def row_clue(self, y: int) -> list[int]:
        return self.runs(self.solution[y * self.WIDTH:(y + 1) * self.WIDTH])

    def col_clue(self, x: int) -> list[int]:
        return self.runs([self.solution[y * self.WIDTH + x]
                          for y in range(self.HEIGHT)])

    def won(self) -> bool:
        for index, filled in enumerate(self.solution):
            if filled and self.marks[index] != 1:
                return False
            if not filled and self.marks[index] == 1:
                return False
        return True

    def press(self, key: str) -> bool:
        if key == "up":
            self.y = max(0, self.y - 1)
        elif key == "down":
            self.y = min(self.HEIGHT - 1, self.y + 1)
        elif key == "left":
            self.x = max(0, self.x - 1)
        elif key == "right":
            self.x = min(self.WIDTH - 1, self.x + 1)
        elif key in ("space", "enter"):
            index = self.y * self.WIDTH + self.x
            # Unknown, filled, ruled out, and back. One key rather than two,
            # because two keys on a grid means remembering which is which.
            self.marks[index] = (self.marks[index] + 1) % 3
        elif key in ("r", "R"):
            self.reset()
        else:
            return False
        return True

    def status(self) -> str:
        if self.won():
            return f"Solved. It is a {self.name}."
        filled = sum(1 for mark in self.marks if mark == 1)
        return f"{filled} filled."

    def paint(self, cr, width, height, ink) -> None:
        # The clues need room outside the grid, three cells of it on the left
        # and two above, so the grid is drawn into what is left rather than
        # into the whole rectangle.
        pad_x = self.grid[0] - self.WIDTH
        pad_y = self.grid[1] - self.HEIGHT
        cell, left, top = fit(self.grid[0], self.grid[1], width, height,
                              self.max_cell)
        left += cell * pad_x
        top += cell * pad_y
        size = cell * 0.42

        cr.set_source_rgb(*ink["dim"])
        for y in range(self.HEIGHT):
            clue = " ".join(str(n) for n in self.row_clue(y))
            cr.select_font_face("sans-serif", _SLANT_NORMAL, _WEIGHT_NORMAL)
            cr.set_font_size(size)
            extents = cr.text_extents(clue)
            cr.move_to(left - cell * 0.35 - extents.x_advance,
                       top + (y + 0.5) * cell + size * 0.36)
            cr.show_text(clue)
        for x in range(self.WIDTH):
            clue = self.col_clue(x)
            for depth, number in enumerate(reversed(clue)):
                text_at(cr, str(number), left + (x + 0.5) * cell,
                        top - cell * (0.42 + depth * 0.58), size)

        for y in range(self.HEIGHT):
            for x in range(self.WIDTH):
                mark = self.marks[y * self.WIDTH + x]
                cx, cy = left + x * cell, top + y * cell
                if mark == 1:
                    cr.set_source_rgb(*ink["accent"])
                    rounded(cr, cx + 1, cy + 1, cell - 2, cell - 2, cell * 0.18)
                    cr.fill()
                else:
                    cr.set_source_rgb(*ink["board"])
                    rounded(cr, cx + 1, cy + 1, cell - 2, cell - 2, cell * 0.18)
                    cr.fill_preserve()
                    cr.set_source_rgb(*ink["edge"])
                    cr.set_line_width(1)
                    cr.stroke()
                if mark == 2:
                    # Ruled out is a cross rather than a shade, because a
                    # shade at this size is a fill somebody has to squint at.
                    cr.set_source_rgb(*ink["dim"])
                    cr.set_line_width(max(1.0, cell * 0.08))
                    inset = cell * 0.3
                    cr.move_to(cx + inset, cy + inset)
                    cr.line_to(cx + cell - inset, cy + cell - inset)
                    cr.move_to(cx + cell - inset, cy + inset)
                    cr.line_to(cx + inset, cy + cell - inset)
                    cr.stroke()
        cursor(cr, left + self.x * cell, top + self.y * cell, cell, ink)


def cursor(cr, x: float, y: float, cell: float, ink: dict) -> None:
    """Where the keys will land, on any board that has a cursor.

    Drawn outside the cell rather than over it, so the cell's own state is
    never hidden by the thing pointing at it. Two pixels, in the accent, and
    the same shape on every board here so that moving between games does not
    mean learning where you are twice.
    """
    cr.set_source_rgb(*ink["accent"])
    cr.set_line_width(2)
    rounded(cr, x - 1, y - 1, cell + 2, cell + 2, cell * 0.22)
    cr.stroke()


# --------------------------------------------------------------------------
# 2048
# --------------------------------------------------------------------------
#
# The best fit that exists for this screen, and it is not close. Four keys, no
# timing, a grid that renders exactly, and everybody already knows the rules,
# so there is nothing to explain on a screen nobody came here to read.
#
# It is also satisfying in the particular low stakes way a waiting screen
# wants: you can stop mid move, look at the install, and come back without
# having lost anything.


class Twenty48(Game):
    ident = "2048"
    keys = "Arrows to slide. R for a new board."
    description = "2048. Arrow keys to slide the tiles together."
    grid = (4.0, 4.0)
    max_cell = 64.0

    #: The tile colours, by value. Two ramps rather than one: everything up to
    #: 64 is the neutral surface getting warmer, and 128 upward is the brand
    #: accent getting stronger, so the board says how well it is going from
    #: across the room.
    #: How long a tile takes to arrive, and how long a merge takes to settle.
    #: Both short. This is a board acknowledging a keypress, not an effect.
    POP_SECONDS = 0.14
    MERGE_SECONDS = 0.18

    def __init__(self, seed: int | None = None) -> None:
        self.random = random.Random(seed)
        self.reset()

    def reset(self) -> None:
        self.board = [0] * 16
        self.score = 0
        self.won = False
        #: Cell index to how far through its arrival it is, in seconds.
        self.popping: dict[int, float] = {}
        self.merging: dict[int, float] = {}
        self.spawn()
        self.spawn()

    def spawn(self) -> bool:
        free = [i for i, value in enumerate(self.board) if value == 0]
        if not free:
            return False
        # Nine times in ten a 2, which is the standard distribution and the
        # reason the game is winnable at all.
        where = self.random.choice(free)
        self.board[where] = 2 if self.random.randrange(10) else 4
        self.popping[where] = 0.0
        return True

    def _line(self, cells: list[int]) -> bool:
        """Collapse one line of four toward index 0. True if anything moved.

        Written once and used for all four directions by handing it the
        indices in the right order, because four nearly identical loops is
        four places for the merge rule to drift. A tile merges at most once
        per move, which is the rule everybody gets wrong: 2 2 4 does not
        become 8.
        """
        packed = [self.board[i] for i in cells if self.board[i]]
        out: list[int] = []
        merges: set[int] = set()
        index = 0
        while index < len(packed):
            if index + 1 < len(packed) and packed[index] == packed[index + 1]:
                value = packed[index] * 2
                merges.add(len(out))
                out.append(value)
                self.score += value
                if value == 2048:
                    self.won = True
                index += 2
            else:
                out.append(packed[index])
                index += 1
        out += [0] * (4 - len(out))
        moved = False
        for position, target in enumerate(cells):
            if self.board[target] != out[position]:
                self.board[target] = out[position]
                moved = True
            if position in merges:
                self.merging[target] = 0.0
        return moved

    def move(self, direction: str) -> bool:
        moved = False
        self.popping.clear()
        self.merging.clear()
        for r in range(4):
            if direction == "left":
                cells = [r * 4 + c for c in range(4)]
            elif direction == "right":
                cells = [r * 4 + 3 - c for c in range(4)]
            elif direction == "up":
                cells = [c * 4 + r for c in range(4)]
            else:
                cells = [(3 - c) * 4 + r for c in range(4)]
            if self._line(cells):
                moved = True
        # A tile only appears when something actually moved. Spawning on a
        # move that did nothing is how a board fills up while somebody presses
        # a key that is doing nothing, which reads as the game cheating.
        if moved:
            self.spawn()
        return moved

    def over(self) -> bool:
        if any(value == 0 for value in self.board):
            return False
        for r in range(4):
            for c in range(4):
                index = r * 4 + c
                if c < 3 and self.board[index] == self.board[index + 1]:
                    return False
                if r < 3 and self.board[index] == self.board[index + 4]:
                    return False
        return True

    def press(self, key: str) -> bool:
        if key in ("up", "down", "left", "right"):
            if self.over():
                return True
            self.move(key)
            return True
        if key in ("r", "R"):
            self.reset()
            return True
        return False

    def animating(self) -> bool:
        return bool(self.popping or self.merging)

    def frame(self, seconds: float) -> bool:
        if not self.animating():
            return False
        for store, limit in ((self.popping, self.POP_SECONDS),
                             (self.merging, self.MERGE_SECONDS)):
            for index in list(store):
                store[index] += seconds
                if store[index] >= limit:
                    del store[index]
        return True

    def status(self) -> str:
        if self.won:
            return f"Score {self.score}. You made 2048."
        if self.over():
            return f"Score {self.score}. No moves left. R to start again."
        return f"Score {self.score}"

    def paint(self, cr, width, height, ink) -> None:
        cell, left, top = fit(4, 4, width, height, self.max_cell)
        gap = cell * 0.06
        for index, value in enumerate(self.board):
            x = left + (index % 4) * cell
            y = top + (index // 4) * cell
            if value == 0:
                cr.set_source_rgb(*ink["board"])
            elif value < 128:
                # Toward the warm accent as the value climbs, so a board that
                # is going well looks different from one that is not.
                mix = min(1.0, (value.bit_length() - 1) / 7.0)
                cr.set_source_rgb(*blend(ink["board"], ink["warm"], mix * 0.75))
            else:
                mix = min(1.0, (value.bit_length() - 7) / 5.0)
                cr.set_source_rgb(*blend(ink["accent2"], ink["accent"], mix))
            # A tile arrives rather than appears, and a merge settles rather
            # than swaps. Both are scale about the tile's own centre, which is
            # the one transform that cannot push a tile outside its cell.
            scale = 1.0
            if index in self.popping:
                scale = 0.4 + 0.6 * min(1.0, self.popping[index] / self.POP_SECONDS)
            elif index in self.merging:
                progress = min(1.0, self.merging[index] / self.MERGE_SECONDS)
                # Out and back, so the tile that just doubled is the one the
                # eye lands on without anything having to be coloured.
                scale = 1.0 + 0.16 * (1.0 - abs(progress * 2 - 1)) ** 2
            inset = gap + (cell - gap * 2) * (1.0 - scale) / 2
            rounded(cr, x + inset, y + inset, cell - inset * 2, cell - inset * 2,
                    cell * 0.16)
            cr.fill()
            if not value:
                continue
            label = str(value)
            # The number shrinks as it gets longer, which is what keeps 1024
            # inside the same tile that held 2.
            size = cell * (0.44 if len(label) < 3 else 0.34 if len(label) < 4 else 0.27)
            cr.set_source_rgb(*(ink["on_accent"] if value >= 128 else ink["ink"]))
            text_at(cr, label, x + cell / 2, y + cell / 2, size * scale, bold=True)


#: Every colour a board may ask the window for. Named here rather than only
#: in the window, so that a test can hand a board a palette without knowing
#: how the window builds one, and so that a painter reaching for a colour
#: nobody supplies fails in a test rather than on somebody's install.
INK_KEYS = ("board", "edge", "ink", "dim", "accent", "accent2", "warm",
            "good", "on_accent", "on_warm", "on_good", "bad")


def blend(first: tuple, second: tuple, amount: float) -> tuple:
    amount = max(0.0, min(1.0, amount))
    return tuple(first[i] + (second[i] - first[i]) * amount for i in range(3))


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
# first, because that is the obvious order.


class Minesweeper(Game):
    ident = "mines"
    keys = "Arrows to move. Space to open, F to flag."
    description = ("Minesweeper. Arrow keys to move, space to open a square, "
                   "F to flag one.")
    grid = (9.0, 9.0)
    max_cell = 34.0

    WIDTH = 9
    HEIGHT = 9
    COUNT = 10

    def __init__(self, seed: int | None = None) -> None:
        self.random = random.Random(seed)
        self.reset()

    def reset(self) -> None:
        size = self.WIDTH * self.HEIGHT
        self.mines = [0] * size
        self.shown = [0] * size
        self.flags = [0] * size
        self.x = self.WIDTH // 2
        self.y = self.HEIGHT // 2
        self.started = False
        self.dead = False
        self.won = False

    def _place(self, safe_x: int, safe_y: int) -> None:
        placed = 0
        while placed < self.COUNT:
            x = self.random.randrange(self.WIDTH)
            y = self.random.randrange(self.HEIGHT)
            if abs(x - safe_x) <= 1 and abs(y - safe_y) <= 1:
                continue
            index = y * self.WIDTH + x
            if self.mines[index]:
                continue
            self.mines[index] = 1
            placed += 1
        self.started = True

    def near(self, x: int, y: int) -> int:
        total = 0
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if not dx and not dy:
                    continue
                nx, ny = x + dx, y + dy
                if 0 <= nx < self.WIDTH and 0 <= ny < self.HEIGHT:
                    total += self.mines[ny * self.WIDTH + nx]
        return total

    def _open(self, x: int, y: int) -> None:
        # Iterative rather than recursive. Opening an empty cell opens its
        # neighbours too, which is the whole game, and on a full board that is
        # eighty frames deep.
        queue = [(x, y)]
        while queue:
            cx, cy = queue.pop(0)
            index = cy * self.WIDTH + cx
            if self.shown[index] or self.flags[index]:
                continue
            self.shown[index] = 1
            if self.near(cx, cy):
                continue
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if not dx and not dy:
                        continue
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < self.WIDTH and 0 <= ny < self.HEIGHT:
                        queue.append((nx, ny))

    def reveal(self) -> None:
        if self.dead or self.won:
            return
        index = self.y * self.WIDTH + self.x
        if self.flags[index]:
            return
        if not self.started:
            self._place(self.x, self.y)
        if self.mines[index]:
            self.dead = True
            return
        self._open(self.x, self.y)
        self.check()

    def check(self) -> bool:
        # Won when every cell that is not a mine has been opened. Flags are
        # not part of it: a board can be finished without planting one, and
        # requiring them would be inventing a rule.
        for index in range(self.WIDTH * self.HEIGHT):
            if not self.mines[index] and not self.shown[index]:
                return False
        self.won = True
        return True

    def press(self, key: str) -> bool:
        if key == "up":
            self.y = max(0, self.y - 1)
        elif key == "down":
            self.y = min(self.HEIGHT - 1, self.y + 1)
        elif key == "left":
            self.x = max(0, self.x - 1)
        elif key == "right":
            self.x = min(self.WIDTH - 1, self.x + 1)
        elif key in ("space", "enter"):
            if self.dead or self.won:
                self.reset()
            else:
                self.reveal()
        elif key in ("f", "F"):
            index = self.y * self.WIDTH + self.x
            if not self.dead and not self.won and not self.shown[index]:
                self.flags[index] = 0 if self.flags[index] else 1
        elif key in ("r", "R"):
            self.reset()
        else:
            return False
        return True

    def status(self) -> str:
        if self.dead:
            return "That was a mine. Space to start again."
        if self.won:
            return "Cleared. Space to start again."
        left = self.COUNT - sum(self.flags)
        return f"{left} mines left" if left != 1 else "1 mine left"

    def paint(self, cr, width, height, ink) -> None:
        cell, left, top = fit(self.WIDTH, self.HEIGHT, width, height, self.max_cell)
        for y in range(self.HEIGHT):
            for x in range(self.WIDTH):
                index = y * self.WIDTH + x
                cx, cy = left + x * cell, top + y * cell
                shown = self.shown[index] or (self.dead and self.mines[index])
                cr.set_source_rgb(*(ink["board"] if shown
                                    else blend(ink["edge"], ink["dim"], 0.22)))
                rounded(cr, cx + 1, cy + 1, cell - 2, cell - 2, cell * 0.16)
                cr.fill()
                if self.dead and self.mines[index]:
                    cr.set_source_rgb(*ink["bad"])
                    cr.arc(cx + cell / 2, cy + cell / 2, cell * 0.24, 0, _TAU)
                    cr.fill()
                elif self.flags[index]:
                    cr.set_source_rgb(*ink["warm"])
                    cr.move_to(cx + cell * 0.34, cy + cell * 0.22)
                    cr.line_to(cx + cell * 0.34, cy + cell * 0.78)
                    cr.set_line_width(max(1.0, cell * 0.07))
                    cr.stroke()
                    cr.move_to(cx + cell * 0.34, cy + cell * 0.24)
                    cr.line_to(cx + cell * 0.7, cy + cell * 0.38)
                    cr.line_to(cx + cell * 0.34, cy + cell * 0.52)
                    cr.close_path()
                    cr.fill()
                elif self.shown[index]:
                    count = self.near(x, y)
                    if count:
                        cr.set_source_rgb(*number_ink(count, ink))
                        text_at(cr, str(count), cx + cell / 2, cy + cell / 2,
                                cell * 0.5, bold=True)
        cursor(cr, left + self.x * cell, top + self.y * cell, cell, ink)


def number_ink(count: int, ink: dict) -> tuple:
    """The classic minesweeper ramp, in this product's palette.

    Colour is the only thing carrying the count on a real board, and this one
    is no different, which is why the digit is drawn as well. Nobody has to
    tell one blue from another to play; the colours are there because a board
    where every number looks the same is much slower to read.
    """
    if count <= 1:
        return ink["accent2"]
    if count == 2:
        return ink["good"]
    if count == 3:
        return ink["bad"]
    if count == 4:
        return ink["accent"]
    return ink["warm"]


# --------------------------------------------------------------------------
# Lights Out
# --------------------------------------------------------------------------
#
# Five by five, one action, pure logic and no timing at all. The smallest
# thing on this screen that is still a game, and the one that survives being
# interrupted best: the board is the whole state, so looking away for a minute
# costs nothing.
#
# The board is generated by starting from solved and pressing random cells,
# which is the only honest way to do it. A random board is solvable slightly
# less than half the time, and handing somebody an impossible puzzle while
# they wait for a disk is not a joke worth making.


class LightsOut(Game):
    ident = "lights"
    keys = "Arrows to move. Space to press."
    description = "Lights out. Arrow keys to move, space to press a light."
    grid = (5.0, 5.0)
    max_cell = 50.0

    def __init__(self, seed: int | None = None) -> None:
        self.random = random.Random(seed)
        self.reset()

    def reset(self) -> None:
        for _ in range(12):
            self.cells = [0] * 25
            self.moves = 0
            self.x = 2
            self.y = 2
            # Six presses from solved. Enough to look like a puzzle, few
            # enough that it is finishable inside the wait it exists to fill.
            for _press in range(6):
                self._press(self.random.randrange(5), self.random.randrange(5))
            # A generated board that happens to come out solved is not a
            # puzzle. Bounded, because a loop that retries until it is happy
            # is a loop that can be wrong forever.
            if not self.won():
                return

    def _press(self, x: int, y: int) -> None:
        for cx, cy in ((x, y), (x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= cx < 5 and 0 <= cy < 5:
                self.cells[cy * 5 + cx] ^= 1

    def won(self) -> bool:
        return not any(self.cells)

    def press(self, key: str) -> bool:
        if key == "up":
            self.y = max(0, self.y - 1)
        elif key == "down":
            self.y = min(4, self.y + 1)
        elif key == "left":
            self.x = max(0, self.x - 1)
        elif key == "right":
            self.x = min(4, self.x + 1)
        elif key in ("space", "enter"):
            if self.won():
                self.reset()
            else:
                self._press(self.x, self.y)
                self.moves += 1
        elif key in ("r", "R"):
            self.reset()
        else:
            return False
        return True

    def status(self) -> str:
        if self.won():
            move = "move" if self.moves == 1 else "moves"
            return f"All out, in {self.moves} {move}. Space for another."
        lit = sum(self.cells)
        return f"{lit} still lit" if lit != 1 else "1 still lit"

    def paint(self, cr, width, height, ink) -> None:
        cell, left, top = fit(5, 5, width, height, self.max_cell)
        gap = cell * 0.08
        for y in range(5):
            for x in range(5):
                lit = self.cells[y * 5 + x]
                cx, cy = left + x * cell, top + y * cell
                cr.set_source_rgb(*(ink["warm"] if lit else ink["board"]))
                cr.arc(cx + cell / 2, cy + cell / 2, cell / 2 - gap, 0, _TAU)
                cr.fill_preserve()
                cr.set_source_rgb(*ink["edge"])
                cr.set_line_width(1)
                cr.stroke()
        cursor(cr, left + self.x * cell, top + self.y * cell, cell, ink)


# --------------------------------------------------------------------------
# The fifteen puzzle
# --------------------------------------------------------------------------
#
# Arrows only, and everybody already knows it, which is the same argument that
# put 2048 on this screen.
#
# Shuffled by making legal moves from the solved board rather than by
# permuting the tiles. Half of all permutations of a fifteen puzzle cannot be
# solved, and the parity rule that decides which half is not something to
# explain to somebody waiting for an install.


class Fifteen(Game):
    ident = "fifteen"
    keys = "Arrows to slide a tile into the gap."
    description = "The fifteen puzzle. Arrow keys slide a tile into the gap."
    grid = (4.0, 4.0)
    max_cell = 62.0

    def __init__(self, seed: int | None = None) -> None:
        self.random = random.Random(seed)
        self.reset()

    #: How long one tile takes to cross one cell.
    SLIDE_SECONDS = 0.11

    def reset(self) -> None:
        self.tiles = list(range(1, 16)) + [0]
        self.hole = 15
        self.moves = 0
        #: Where the tile that just moved came from, and how far through it is.
        self.sliding: tuple[int, int, float] | None = None
        last = ""
        for _ in range(120):
            while True:
                direction = self.random.choice(("up", "down", "left", "right"))
                # Never immediately undoing the move just made, or a hundred
                # and twenty shuffles average out to about six.
                if direction != last:
                    break
            if self.slide(direction):
                last = {"up": "down", "down": "up",
                        "left": "right", "right": "left"}[direction]
        self.moves = 0

    def slide(self, direction: str) -> bool:
        # The direction names the tile's travel, not the hole's, because that
        # is what somebody pressing an arrow means by it.
        hx, hy = self.hole % 4, self.hole // 4
        if direction == "up":
            if hy >= 3:
                return False
            source = self.hole + 4
        elif direction == "down":
            if hy <= 0:
                return False
            source = self.hole - 4
        elif direction == "left":
            if hx >= 3:
                return False
            source = self.hole + 1
        elif direction == "right":
            if hx <= 0:
                return False
            source = self.hole - 1
        else:
            return False
        self.tiles[self.hole] = self.tiles[source]
        self.tiles[source] = 0
        self.sliding = (self.hole, source, 0.0)
        self.hole = source
        self.moves += 1
        return True

    def won(self) -> bool:
        return all(self.tiles[i] == i + 1 for i in range(15))

    def press(self, key: str) -> bool:
        if key in ("up", "down", "left", "right"):
            self.slide(key)
            return True
        if key in ("r", "R"):
            self.reset()
            return True
        return False

    def animating(self) -> bool:
        return self.sliding is not None

    def frame(self, seconds: float) -> bool:
        if self.sliding is None:
            return False
        arrived, came_from, age = self.sliding
        age += seconds
        if age >= self.SLIDE_SECONDS:
            self.sliding = None
        else:
            self.sliding = (arrived, came_from, age)
        return True

    def status(self) -> str:
        if self.won():
            move = "move" if self.moves == 1 else "moves"
            return f"Solved in {self.moves} {move}."
        return f"{self.moves} moves" if self.moves != 1 else "1 move"

    def paint(self, cr, width, height, ink) -> None:
        cell, left, top = fit(4, 4, width, height, self.max_cell)
        gap = cell * 0.06
        for index, value in enumerate(self.tiles):
            if not value:
                continue
            x = left + (index % 4) * cell
            y = top + (index // 4) * cell
            # The tile that just moved is drawn part way between where it was
            # and where it is, so a board of sixteen squares says which one
            # went where.
            if self.sliding is not None and self.sliding[0] == index:
                _at, came_from, age = self.sliding
                left_over = 1.0 - min(1.0, age / self.SLIDE_SECONDS)
                x -= (index % 4 - came_from % 4) * cell * left_over
                y -= (index // 4 - came_from // 4) * cell * left_over
            # A tile already home is drawn in the accent, which turns the
            # board into its own progress bar without a word being written.
            home = value == index + 1
            cr.set_source_rgb(*(ink["accent"] if home else ink["board"]))
            rounded(cr, x + gap, y + gap, cell - gap * 2, cell - gap * 2, cell * 0.16)
            cr.fill()
            cr.set_source_rgb(*(ink["on_accent"] if home else ink["ink"]))
            text_at(cr, str(value), x + cell / 2, y + cell / 2, cell * 0.4, bold=True)


# --------------------------------------------------------------------------
# Sokoban
# --------------------------------------------------------------------------
#
# Arrows only, no clock, and levels, which is what earns it a place on a list
# where anything needing input latency was ruled out. Push a box onto a
# target.
#
# A box against a wall with a target elsewhere is stuck, so there is an undo,
# because a puzzle you can permanently ruin on move three while half watching
# a progress bar is a puzzle that makes the wait worse.


class Sokoban(Game):
    ident = "soko"
    keys = "Arrows to push. U to undo. N for the next level."
    description = ("Sokoban. Arrow keys to push a box onto a target, "
                   "U to undo.")
    max_cell = 42.0

    LEVELS = (
        "#######|#     #|# @$. #|#     #|#######",
        "#######|#  .  #|#  $  #|# @   #|#     #|#######",
        "########|#  ..  #|#  $$  #|#      #|#  @   #|#      #|########",
    )

    def __init__(self, level: int = 0, seed: int | None = None) -> None:
        self.level = 0
        self.load(level)

    def load(self, level: int) -> None:
        if not 0 <= level < len(self.LEVELS):
            level = 0
        self.level = level
        rows = self.LEVELS[level].split("|")
        self.height = len(rows)
        self.width = max(len(row) for row in rows)
        self.static: list[str] = []
        self.boxes: list[int] = []
        self.moves = 0
        self.undo_stack: list[tuple[int, int, list[int]]] = []
        self.x = self.y = 0
        for y, row in enumerate(rows):
            for x in range(self.width):
                # A short row is floor to its right rather than a ragged edge.
                cell = row[x:x + 1] or " "
                if cell == "#":
                    self.static.append("#")
                    self.boxes.append(0)
                elif cell == ".":
                    self.static.append(".")
                    self.boxes.append(0)
                elif cell == "$":
                    self.static.append(" ")
                    self.boxes.append(1)
                elif cell == "*":
                    self.static.append(".")
                    self.boxes.append(1)
                elif cell in ("@", "+"):
                    self.static.append("." if cell == "+" else " ")
                    self.boxes.append(0)
                    self.x, self.y = x, y
                else:
                    self.static.append(" ")
                    self.boxes.append(0)

    @property
    def grid(self) -> tuple[float, float]:  # type: ignore[override]
        return float(self.width), float(self.height)

    def move(self, direction: str) -> bool:
        offsets = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
        if direction not in offsets:
            return False
        dx, dy = offsets[direction]
        nx, ny = self.x + dx, self.y + dy
        if not (0 <= nx < self.width and 0 <= ny < self.height):
            return False
        here = ny * self.width + nx
        if self.static[here] == "#":
            return False
        if self.boxes[here]:
            bx, by = nx + dx, ny + dy
            if not (0 <= bx < self.width and 0 <= by < self.height):
                return False
            beyond = by * self.width + bx
            if self.static[beyond] == "#" or self.boxes[beyond]:
                return False
            # The whole board before the push, so undo is one snapshot rather
            # than a replay. A board this size costs nothing to keep.
            self.undo_stack.append((self.x, self.y, list(self.boxes)))
            self.boxes[here] = 0
            self.boxes[beyond] = 1
        else:
            self.undo_stack.append((self.x, self.y, list(self.boxes)))
        self.x, self.y = nx, ny
        self.moves += 1
        return True

    def undo(self) -> bool:
        if not self.undo_stack:
            return False
        self.x, self.y, self.boxes = self.undo_stack.pop()
        self.moves = max(0, self.moves - 1)
        return True

    def won(self) -> bool:
        return all(not box or self.static[i] == "."
                   for i, box in enumerate(self.boxes))

    def press(self, key: str) -> bool:
        if key in ("up", "down", "left", "right"):
            self.move(key)
            return True
        if key in ("u", "U", "backspace"):
            self.undo()
            return True
        if key in ("n", "N", "enter", "space"):
            self.load((self.level + 1) % len(self.LEVELS))
            return True
        if key in ("r", "R"):
            self.load(self.level)
            return True
        return False

    def status(self) -> str:
        if self.won():
            move = "move" if self.moves == 1 else "moves"
            return (f"Level {self.level + 1} solved in {self.moves} {move}. "
                    "N for the next one.")
        move = "move" if self.moves == 1 else "moves"
        return (f"Level {self.level + 1} of {len(self.LEVELS)}. "
                f"{self.moves} {move}.")

    def paint(self, cr, width, height, ink) -> None:
        cell, left, top = fit(self.width, self.height, width, height,
                              self.max_cell)
        for y in range(self.height):
            for x in range(self.width):
                index = y * self.width + x
                cx, cy = left + x * cell, top + y * cell
                what = self.static[index]
                if what == "#":
                    # Darker than the floor by enough to read as solid. At the
                    # container tone they were a slightly different white and
                    # the level looked like a grid rather than a room.
                    cr.set_source_rgb(*blend(ink["edge"], ink["dim"], 0.5))
                    rounded(cr, cx + 1, cy + 1, cell - 2, cell - 2, cell * 0.14)
                    cr.fill()
                    continue
                cr.set_source_rgb(*ink["board"])
                cr.rectangle(cx + 1, cy + 1, cell - 2, cell - 2)
                cr.fill()
                if what == ".":
                    # The target, drawn as a ring rather than a fill, so a box
                    # standing on it still reads as a box on a target.
                    cr.set_source_rgb(*ink["good"])
                    cr.set_line_width(max(1.0, cell * 0.07))
                    cr.arc(cx + cell / 2, cy + cell / 2, cell * 0.22, 0, _TAU)
                    cr.stroke()
        for index, box in enumerate(self.boxes):
            if not box:
                continue
            x, y = index % self.width, index // self.width
            home = self.static[index] == "."
            cr.set_source_rgb(*(ink["good"] if home else ink["warm"]))
            rounded(cr, left + x * cell + cell * 0.16, top + y * cell + cell * 0.16,
                    cell * 0.68, cell * 0.68, cell * 0.12)
            cr.fill()
        cr.set_source_rgb(*ink["accent"])
        cr.arc(left + (self.x + 0.5) * cell, top + (self.y + 0.5) * cell,
               cell * 0.3, 0, _TAU)
        cr.fill()


# --------------------------------------------------------------------------
# Connect 4
# --------------------------------------------------------------------------
#
# Seven columns and two keys, which is the whole reason it is on the list: no
# timing, no pointer and no chord, and it plays fine on a screen somebody is
# half watching.
#
# The opponent is deliberately weak. It takes a win it can see and blocks one
# it can see, and past that it prefers the middle and picks at random. It does
# not look two moves ahead, which is the difference between an opponent that
# is beatable while distracted and one that is not beatable at all. Losing
# every game to an installer is not a way to spend ten minutes.


class Connect4(Game):
    ident = "c4"
    keys = "Left and right to aim. Space to drop."
    description = ("Connect 4. Left and right to choose a column, "
                   "space to drop a counter.")
    grid = (7.0, 7.0)
    max_cell = 44.0

    def __init__(self, seed: int | None = None) -> None:
        self.random = random.Random(seed)
        self.reset()

    #: How long a counter takes to fall the height of the board. Seven
    #: hundredths of a second per row is fast enough not to be a wait and slow
    #: enough that the column it went down is unmistakable.
    DROP_PER_ROW = 0.07

    def reset(self) -> None:
        self.board = [0] * 42
        self.column = 3
        self.over = 0
        self.last: int | None = None
        #: Cell index to how far it still has to fall, in rows.
        self.falling: dict[int, float] = {}

    def _line(self, player: int, x: int, y: int, dx: int, dy: int) -> bool:
        for step in range(4):
            cx, cy = x + dx * step, y + dy * step
            if not (0 <= cx < 7 and 0 <= cy < 6):
                return False
            if self.board[cy * 7 + cx] != player:
                return False
        return True

    def wins(self, player: int) -> bool:
        for y in range(6):
            for x in range(7):
                if (self._line(player, x, y, 1, 0) or self._line(player, x, y, 0, 1)
                        or self._line(player, x, y, 1, 1)
                        or self._line(player, x, y, 1, -1)):
                    return True
        return False

    def _put(self, column: int, player: int) -> int | None:
        for y in range(5, -1, -1):
            if self.board[y * 7 + column] == 0:
                self.board[y * 7 + column] = player
                # It fell from above the board, so the distance is the row it
                # landed in plus the aiming row it started in.
                self.falling[y * 7 + column] = float(y) + 1.0
                return y * 7 + column
        return None

    def _take(self, column: int) -> None:
        for y in range(6):
            if self.board[y * 7 + column] != 0:
                self.board[y * 7 + column] = 0
                # And the fall it was going to make. The opponent tries a move
                # in every column before choosing one, and without this every
                # move it considered left a counter falling into a square it
                # had already taken back.
                self.falling.pop(y * 7 + column, None)
                return

    def full(self) -> bool:
        return all(self.board[column] != 0 for column in range(7))

    def _reply(self) -> None:
        for column in range(7):
            if self._put(column, 2) is None:
                continue
            if self.wins(2):
                return
            self._take(column)
        for column in range(7):
            if self._put(column, 1) is None:
                continue
            threat = self.wins(1)
            self._take(column)
            if threat and self._put(column, 2) is not None:
                return
        # The middle is worth more than the edges in this game, and preferring
        # it is the one piece of strategy in here.
        for column in (3, 2, 4, 1, 5, 0, 6):
            if self.random.randrange(4) and self._put(column, 2) is not None:
                return
        for column in (3, 2, 4, 1, 5, 0, 6):
            if self._put(column, 2) is not None:
                return

    def drop(self) -> bool:
        if self.over:
            return False
        landed = self._put(self.column, 1)
        if landed is None:
            return False
        self.last = landed
        if self.wins(1):
            self.over = 1
            return True
        if self.full():
            self.over = 3
            return True
        self._reply()
        if self.wins(2):
            self.over = 2
        elif self.full():
            self.over = 3
        return True

    def animating(self) -> bool:
        return bool(self.falling)

    def frame(self, seconds: float) -> bool:
        if not self.falling:
            return False
        step = seconds / self.DROP_PER_ROW
        for index in list(self.falling):
            self.falling[index] -= step
            if self.falling[index] <= 0:
                del self.falling[index]
        return True

    def press(self, key: str) -> bool:
        if key == "left":
            self.column = max(0, self.column - 1)
        elif key == "right":
            self.column = min(6, self.column + 1)
        elif key in ("space", "enter", "down"):
            if self.over:
                self.reset()
            else:
                self.drop()
        elif key in ("r", "R"):
            self.reset()
        else:
            return False
        return True

    def status(self) -> str:
        if self.over == 1:
            return "You win. Space for another."
        if self.over == 2:
            return "It got four. Space for another."
        if self.over == 3:
            return "Board full. Space for another."
        return "Your turn."

    def paint(self, cr, width, height, ink) -> None:
        cell, left, top = fit(7, 7, width, height, self.max_cell)
        # The aiming row, above the board, drawn as a counter waiting rather
        # than as an arrow. It is the piece that is about to fall.
        if not self.over:
            cr.set_source_rgb(*ink["accent"])
            cr.arc(left + (self.column + 0.5) * cell, top + cell * 0.5,
                   cell * 0.3, 0, _TAU)
            cr.fill()
        board_top = top + cell
        cr.set_source_rgb(*ink["board"])
        rounded(cr, left, board_top, cell * 7, cell * 6, cell * 0.2)
        cr.fill()
        for y in range(6):
            for x in range(7):
                counter = self.board[y * 7 + x]
                cx = left + (x + 0.5) * cell
                cy = board_top + (y + 0.5) * cell
                # A counter still falling is drawn where it has got to, and
                # the hole it will land in is drawn empty underneath it.
                falling = self.falling.get(y * 7 + x, 0.0)
                if falling > 0:
                    cr.set_source_rgb(*ink["edge"])
                    cr.arc(cx, cy, cell * 0.36, 0, _TAU)
                    cr.fill()
                    cy -= falling * cell
                if counter == 1:
                    cr.set_source_rgb(*ink["accent"])
                elif counter == 2:
                    cr.set_source_rgb(*ink["warm"])
                else:
                    cr.set_source_rgb(*ink["edge"])
                cr.arc(cx, cy, cell * 0.36, 0, _TAU)
                cr.fill()
                # The counter that just landed gets a ring, because on a board
                # of forty two identical discs the move somebody just made is
                # otherwise impossible to find.
                if self.last == y * 7 + x and counter:
                    cr.set_source_rgb(*ink["ink"])
                    cr.set_line_width(max(1.0, cell * 0.05))
                    cr.arc(cx, cy, cell * 0.36, 0, _TAU)
                    cr.stroke()


# --------------------------------------------------------------------------
# A maze, generated fresh every time
# --------------------------------------------------------------------------
#
# Arrows only, no clock, and never the same twice, which is the one thing a
# generated puzzle has over a hand written one: there is no solution to look
# up and no level to have already done.
#
# Carved by depth first search with an explicit stack, which produces a
# perfect maze: exactly one path between any two cells, so it is always
# solvable and never has a loop to go round twice.


class Maze(Game):
    ident = "maze"
    keys = "Arrows to walk. R for a new maze."
    description = "A maze. Arrow keys to walk to the way out."
    max_cell = 22.0

    CELLS_W = 9
    CELLS_H = 5

    def __init__(self, seed: int | None = None) -> None:
        self.random = random.Random(seed)
        self.reset()

    def reset(self) -> None:
        w, h = self.CELLS_W, self.CELLS_H
        self.columns = w * 2 + 1
        self.rows = h * 2 + 1
        # Every character of the maze, walls included. Not called `grid`,
        # because that name belongs to the board shape every game here
        # declares, and an instance attribute shadowing it is a blank card.
        self.walls = ["#"] * (self.columns * self.rows)
        visited = [0] * (w * h)
        visited[0] = 1
        self.walls[self.columns + 1] = " "
        stack = [0]
        while stack:
            top = stack[-1]
            cx, cy = top % w, top // w
            options = [0, 1, 2, 3]
            self.random.shuffle(options)
            carved = False
            for direction in options:
                nx, ny = cx, cy
                if direction == 0:
                    ny -= 1
                elif direction == 1:
                    nx += 1
                elif direction == 2:
                    ny += 1
                else:
                    nx -= 1
                if not (0 <= nx < w and 0 <= ny < h):
                    continue
                if visited[ny * w + nx]:
                    continue
                # Open the cell and the wall between it and where we came from.
                self.walls[(ny * 2 + 1) * self.columns + (nx * 2 + 1)] = " "
                self.walls[(cy + ny + 1) * self.columns + (cx + nx + 1)] = " "
                visited[ny * w + nx] = 1
                stack.append(ny * w + nx)
                carved = True
                break
            if not carved:
                stack.pop()
        self.x = 1
        self.y = 1
        self.moves = 0
        self.trail = {(1, 1)}

    @property
    def grid(self) -> tuple[float, float]:  # type: ignore[override]
        return float(self.columns), float(self.rows)

    @property
    def exit_x(self) -> int:
        return self.CELLS_W * 2 - 1

    @property
    def exit_y(self) -> int:
        return self.CELLS_H * 2 - 1

    def move(self, direction: str) -> bool:
        offsets = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
        if direction not in offsets:
            return False
        dx, dy = offsets[direction]
        wx, wy = self.x + dx, self.y + dy
        if not (0 <= wx < self.columns and 0 <= wy < self.rows):
            return False
        if self.walls[wy * self.columns + wx] == "#":
            return False
        self.x += dx * 2
        self.y += dy * 2
        self.moves += 1
        # The trail is what makes a maze on a screen readable at all: without
        # it every corridor looks the same and you walk the same dead end
        # three times.
        self.trail.add((wx, wy))
        self.trail.add((self.x, self.y))
        return True

    def won(self) -> bool:
        return self.x == self.exit_x and self.y == self.exit_y

    def press(self, key: str) -> bool:
        if key in ("up", "down", "left", "right"):
            if self.won():
                self.reset()
            else:
                self.move(key)
            return True
        if key in ("r", "R", "enter", "space"):
            self.reset()
            return True
        return False

    def status(self) -> str:
        if self.won():
            move = "move" if self.moves == 1 else "moves"
            return f"Out, in {self.moves} {move}. R for another."
        return f"{self.moves} moves" if self.moves != 1 else "1 move"

    def paint(self, cr, width, height, ink) -> None:
        cell, left, top = fit(self.columns, self.rows, width, height,
                              self.max_cell)
        cr.set_source_rgb(*ink["edge"])
        for y in range(self.rows):
            for x in range(self.columns):
                if self.walls[y * self.columns + x] == "#":
                    cr.rectangle(left + x * cell, top + y * cell, cell, cell)
        cr.fill()
        cr.set_source_rgb(*blend(ink["board"], ink["accent"], 0.25))
        for x, y in self.trail:
            cr.rectangle(left + x * cell + cell * 0.25, top + y * cell + cell * 0.25,
                         cell * 0.5, cell * 0.5)
        cr.fill()
        cr.set_source_rgb(*ink["good"])
        cr.arc(left + (self.exit_x + 0.5) * cell, top + (self.exit_y + 0.5) * cell,
               cell * 0.34, 0, _TAU)
        cr.fill()
        cr.set_source_rgb(*ink["accent"])
        cr.arc(left + (self.x + 0.5) * cell, top + (self.y + 0.5) * cell,
               cell * 0.36, 0, _TAU)
        cr.fill()


# --------------------------------------------------------------------------
# A five letter word guess
# --------------------------------------------------------------------------
#
# Six tries at a five letter word. Letters, backspace and enter, which is the
# whole input model, and no clock anywhere in it.
#
# Two decisions worth writing down, and they are the text installer's, because
# a word game that is stricter in one front end than the other is a word game
# somebody will think is broken.
#
# **A guess is not checked against a dictionary.** The usual rule is that a
# guess has to be a real word, and enforcing that needs a word list of tens of
# thousands rather than the six hundred here. With a short list the rule stops
# meaning "that is not a word" and starts meaning "that is not a word I know",
# which is a worse thing to be told while waiting for a disk to be written.
#
# **The result is marked as well as coloured.** A tick under a letter in the
# right place, a dot under one that is in the word somewhere else, nothing
# under one that is not there at all. Colour says the same thing faster for
# anybody who can see it, and nothing here depends on it.


class Word(Game):
    ident = "word"
    keys = "Type five letters. Enter to guess."
    description = ("A word guess. Type five letters and press Enter. "
                   "Six tries.")
    grid = (5.0, 6.0)
    max_cell = 48.0

    TRIES = 6
    WORDS = (
    "about", "above", "actor", "acute", "admit", "adopt", "after", "again", "agent", "agree", "ahead", "alarm",
    "album", "alert", "alike", "alive", "allow", "alone", "along", "alter", "among", "anger", "angle", "angry",
    "ankle", "apart", "apple", "apply", "arena", "argue", "arise", "armor", "aroma", "array", "arrow", "aside",
    "asset", "audio", "audit", "avoid", "awake", "award", "aware", "badly", "baker", "basic", "basin", "batch",
    "beach", "began", "begin", "begun", "being", "below", "bench", "birth", "black", "blade", "blame", "blank",
    "blast", "blend", "bless", "blind", "block", "blood", "board", "boost", "booth", "bound", "brain", "brand",
    "brass", "brave", "bread", "break", "breed", "brick", "bride", "brief", "bring", "broad", "broke", "brown",
    "brush", "build", "built", "bunch", "burnt", "burst", "cabin", "cable", "candy", "canal", "cargo", "carry",
    "carve", "catch", "cause", "cease", "chain", "chair", "chalk", "charm", "chart", "chase", "cheap", "check",
    "chess", "chest", "chief", "child", "chill", "china", "chose", "civil", "claim", "clean", "clear", "clerk",
    "click", "cliff", "climb", "clock", "close", "cloth", "cloud", "coach", "coast", "could", "count", "court",
    "cover", "crack", "craft", "crash", "cream", "crime", "cross", "crowd", "crown", "crude", "curve", "cycle",
    "daily", "dance", "dated", "dealt", "death", "debut", "delay", "dense", "depth", "doing", "doubt", "dozen",
    "draft", "drain", "drama", "drawn", "dream", "dress", "dried", "drift", "drink", "drive", "drove", "dying",
    "eager", "eagle", "early", "earth", "eight", "elder", "elect", "empty", "enemy", "enjoy", "enter", "entry",
    "equal", "error", "event", "every", "exact", "exist", "extra", "faith", "false", "fault", "favor", "feast",
    "fence", "fever", "field", "fifth", "fight", "final", "first", "flame", "flash", "fleet", "flesh", "float",
    "flood", "floor", "flour", "fluid", "focus", "force", "forge", "forth", "forty", "forum", "found", "frame",
    "fresh", "front", "frost", "fruit", "fully", "funny", "giant", "given", "glass", "globe", "glory", "grace",
    "grade", "grain", "grand", "grant", "grape", "grasp", "grass", "grave", "great", "green", "greet", "grief",
    "gross", "group", "grown", "guard", "guess", "guest", "guide", "habit", "happy", "harsh", "haste", "heart",
    "heavy", "hedge", "hello", "hence", "hobby", "honey", "honor", "horse", "hotel", "house", "human", "humor",
    "ideal", "image", "imply", "index", "inner", "input", "issue", "ivory", "joint", "judge", "juice", "knife",
    "knock", "known", "label", "labor", "large", "laser", "later", "laugh", "layer", "learn", "lease", "least",
    "leave", "legal", "lemon", "level", "light", "limit", "linen", "liver", "lobby", "local", "lodge", "logic",
    "loose", "lower", "loyal", "lucky", "lunar", "lunch", "magic", "major", "maker", "maple", "march", "match",
    "maybe", "mayor", "meant", "medal", "media", "mercy", "merit", "metal", "meter", "midst", "might", "minor",
    "minus", "mixed", "model", "money", "month", "moral", "motor", "mount", "mouse", "mouth", "movie", "music",
    "naked", "nerve", "never", "newly", "night", "noble", "noise", "north", "noted", "novel", "nurse", "occur",
    "ocean", "offer", "often", "onion", "order", "other", "ought", "ounce", "outer", "owner", "paint", "panel",
    "paper", "party", "pause", "peace", "pearl", "phase", "phone", "photo", "piano", "piece", "pilot", "pitch",
    "place", "plain", "plane", "plant", "plate", "point", "polar", "porch", "pound", "power", "press", "price",
    "pride", "prime", "print", "prior", "prize", "probe", "proof", "proud", "prove", "pulse", "punch", "pupil",
    "purse", "queen", "query", "quest", "queue", "quick", "quiet", "quite", "quota", "radio", "raise", "rally",
    "range", "rapid", "ratio", "reach", "ready", "realm", "rebel", "refer", "reign", "relax", "relay", "renew",
    "reply", "rider", "ridge", "right", "rigid", "rival", "river", "roast", "robot", "rocky", "roman", "rough",
    "round", "route", "royal", "rural", "saint", "salad", "sales", "sauce", "scale", "scene", "scope", "score",
    "sense", "serve", "seven", "shade", "shaft", "shall", "shape", "share", "sharp", "sheep", "sheet", "shelf",
    "shell", "shift", "shine", "shirt", "shock", "shoot", "shore", "short", "shown", "sight", "silly", "since",
    "siren", "sixth", "skill", "slate", "sleep", "slide", "slope", "small", "smart", "smell", "smile", "smoke",
    "snake", "solar", "solid", "solve", "sound", "south", "space", "spare", "spark", "speak", "speed", "spell",
    "spend", "spent", "spice", "spine", "spite", "split", "spoke", "sport", "spray", "squad", "stack", "staff",
    "stage", "stair", "stake", "stamp", "stand", "stare", "start", "state", "steam", "steel", "steep", "steer",
    "stern", "stick", "stiff", "still", "stock", "stone", "stood", "store", "storm", "story", "stove", "strap",
    "straw", "strip", "stuck", "study", "stuff", "style", "sugar", "suite", "sunny", "super", "sweep", "sweet",
    "swift", "swing", "sword", "table", "taken", "tally", "taste", "teach", "tempo", "tenth", "thank", "theft",
    "their", "theme", "there", "thick", "thief", "thing", "think", "third", "those", "three", "throw", "thumb",
    "tiger", "tight", "timer", "title", "toast", "today", "token", "tooth", "topic", "torch", "total", "touch",
    "tough", "tower", "trace", "track", "trade", "trail", "train", "trait", "trash", "treat", "trend", "trial",
    "tribe", "trick", "tried", "tripe", "trust", "truth", "twice", "twist", "ultra", "uncle", "under", "union",
    "unite", "unity", "until", "upper", "upset", "urban", "usage", "usual", "vague", "valid", "value", "vapor",
    "vault", "venue", "verse", "video", "vigor", "villa", "vinyl", "virus", "visit", "vital", "vivid", "vocal",
    "voice", "voter", "wagon", "waist", "waste", "watch", "water", "weigh", "weird", "whale", "wheat", "wheel",
    "where", "which", "while", "white", "whole", "whose", "widow", "width", "witch", "woman", "world", "worry",
    "worse", "worth", "would", "wound", "wrist", "write", "wrong", "wrote", "yield", "young", "youth",
    )

    def __init__(self, seed: int | None = None) -> None:
        self.random = random.Random(seed)
        self.reset()

    def reset(self) -> None:
        self.answer = self.random.choice(self.WORDS)
        self.guesses: list[str] = []
        self.marks: list[str] = []
        self.typed = ""
        self.over = 0

    @staticmethod
    def mark(guess: str, answer: str) -> str:
        """One guess against the answer.

        Two passes, and the second one is the reason. A letter guessed twice
        when the answer holds it once must come back right in one place and
        absent in the other, so exact matches are taken out of the pool before
        anything else is allowed to claim a letter. One pass marks both of
        them present and tells somebody there are two of a letter when there
        is one.
        """
        marks = ["?"] * 5
        used = [False] * 5
        for i in range(5):
            if guess[i] == answer[i]:
                marks[i] = "="
                used[i] = True
        for i in range(5):
            if marks[i] != "?":
                continue
            for j in range(5):
                if used[j] or answer[j] != guess[i]:
                    continue
                used[j] = True
                marks[i] = "~"
                break
            if marks[i] == "?":
                marks[i] = "."
        return "".join(marks)

    def press(self, key: str) -> bool:
        if self.over and key in ("enter", "space"):
            self.reset()
            return True
        if self.over:
            return False
        if key == "backspace":
            self.typed = self.typed[:-1]
            return True
        if key == "enter":
            if len(self.typed) != 5:
                return True
            marks = self.mark(self.typed, self.answer)
            self.guesses.append(self.typed)
            self.marks.append(marks)
            self.typed = ""
            if marks == "=====":
                self.over = 1
            elif len(self.guesses) >= self.TRIES:
                self.over = 2
            return True
        if len(key) == 1 and key.isalpha() and len(self.typed) < 5:
            self.typed += key.lower()
            return True
        return False

    def status(self) -> str:
        if self.over == 1:
            tries = len(self.guesses)
            return (f"Got it in {tries}. Enter for another."
                    if tries != 1 else "Got it in one. Enter for another.")
        if self.over == 2:
            return f"It was {self.answer.upper()}. Enter for another."
        left = self.TRIES - len(self.guesses)
        return f"{left} tries left" if left != 1 else "1 try left"

    def paint(self, cr, width, height, ink) -> None:
        cell, left, top = fit(5, self.TRIES, width, height, self.max_cell)
        gap = cell * 0.06
        for row in range(self.TRIES):
            guess = ""
            marks = ""
            if row < len(self.guesses):
                guess, marks = self.guesses[row], self.marks[row]
            elif row == len(self.guesses) and not self.over:
                guess = self.typed
            for column in range(5):
                x = left + column * cell
                y = top + row * cell
                letter = guess[column:column + 1]
                mark = marks[column:column + 1]
                if mark == "=":
                    fill = ink["good"]
                elif mark == "~":
                    fill = ink["warm"]
                elif mark == ".":
                    fill = ink["edge"]
                else:
                    fill = ink["board"]
                cr.set_source_rgb(*fill)
                rounded(cr, x + gap, y + gap, cell - gap * 2, cell - gap * 2,
                        cell * 0.16)
                cr.fill()
                if not mark:
                    cr.set_source_rgb(*ink["edge"])
                    cr.set_line_width(1)
                    rounded(cr, x + gap, y + gap, cell - gap * 2, cell - gap * 2,
                            cell * 0.16)
                    cr.stroke()
                if letter:
                    cr.set_source_rgb(*(ink["on_good"] if mark == "="
                                        else ink["on_warm"] if mark == "~"
                                        else ink["ink"]))
                    text_at(cr, letter.upper(), x + cell / 2, y + cell / 2 - cell * 0.05,
                            cell * 0.42, bold=True)
                # The mark under the letter, so the result survives the colour
                # being taken away. A bar for the right place, a dot for the
                # right letter somewhere else, nothing for absent.
                if mark == "=":
                    cr.set_source_rgb(*ink["on_good"])
                    cr.rectangle(x + cell * 0.36, y + cell * 0.78, cell * 0.28,
                                 max(1.5, cell * 0.06))
                    cr.fill()
                elif mark == "~":
                    cr.set_source_rgb(*ink["on_warm"])
                    cr.arc(x + cell / 2, y + cell * 0.8, max(1.5, cell * 0.05),
                           0, _TAU)
                    cr.fill()


# --------------------------------------------------------------------------
# Tic-tac-toe, which does not play
# --------------------------------------------------------------------------
#
# Last in the picker, and the only entry here that is not what it says it is.
# It thinks for a moment, declines, and offers you 2048 instead.
#
# Nothing is weakened by it and nothing is hidden behind it: it is a game that
# was never going to be interesting, spending its place on the list on a joke
# instead. An easter egg that announces itself is a feature, so this one does
# not announce itself; it is simply the last thing in a list somebody had to
# scroll to reach.


class Sudoku(Game):
    """Nine by nine, and the answer is the only one there is.

    The puzzles are data rather than something generated at the moment of
    play. A generator has to be trusted; a fixed set can be checked, and the
    test proves on every run that each of these has exactly one solution.
    That matters more here than in any other game on this card: a sudoku with
    two answers is a sudoku that tells somebody they are wrong when they are
    not, which is a worse way to spend an install than not playing at all.

    No solver ships with the game either. Because the answer is unique, a full
    grid with nothing repeated in any row, column or box is the answer, so the
    game can say whether somebody has finished without being told beforehand.
    """

    ident = "sudoku"
    keys = "Arrows to move. 1 to 9 to write, 0 to rub out."
    description = ("Sudoku. Arrow keys to move, one to nine to write a "
                   "number, zero to rub it out.")
    grid = (9.0, 9.0)
    max_cell = 34.0

    PUZZLES = (
        ("gentle1", ".7.9.21..2187..3.4596..47.29.7....4..6.....2..4....8.16.94..5187.4..9236..12.5.7."),
        ("gentle2", ".7.8..5..5.2..9.76.8.57..348...1....326.8.715....5...323..98.5.16.3..9.8..8..7.2."),
        ("steady3", "48.......925.4..73.7158.....34....2....756....1....58.....6813.16..9.748.......62"),
        ("steady4", "...4.1..5.....8317...3.2.84.4.....68..65.31..92.....7.36.7.9...8941.....2..6.4..."),
        ("steady5", "..6..5.175....19...12...5..2..7....976.2.8.311....4..6..4...19...51....863.9..7.."),
        ("firm6", "7.35.8..........7.9.5.7.8...47.92.3.....5.....3.61.75...8.6.4.3.6..........2.51.8"),
        ("firm7", ".81..96..2.3..6....7...5.....7..314...8.5.7...367..9.....8...1....4..5.7..25..38."),
        ("firm8", "...4..5232.........5...168.3...4..7...6.1.9...9..2...5.781...9.........8931..8..."),
    )
    SIZE = 9

    def __init__(self, seed: int | None = None) -> None:
        self.random = random.Random(seed)
        self.reset()

    def reset(self) -> None:
        self.name, text = self.random.choice(self.PUZZLES)
        self.cells = [0 if ch == "." else int(ch) for ch in text]
        self.given = [ch != "." for ch in text]
        self.x = 0
        self.y = 0
        self.moves = 0
        # Start where somebody can actually type, so the first keypress does
        # something. Landing the cursor on a given and having 5 do nothing
        # reads as a broken board rather than as a rule.
        for index, fixed in enumerate(self.given):
            if not fixed:
                self.x, self.y = index % self.SIZE, index // self.SIZE
                break

    # -- the rules ---------------------------------------------------------

    def peers(self, index: int) -> list[int]:
        """Every square that may not repeat this one's number."""
        size = self.SIZE
        row, column = index // size, index % size
        box_row, box_column = (row // 3) * 3, (column // 3) * 3
        found = set()
        for step in range(size):
            found.add(row * size + step)
            found.add(step * size + column)
        for dy in range(3):
            for dx in range(3):
                found.add((box_row + dy) * size + box_column + dx)
        found.discard(index)
        return sorted(found)

    def conflicts(self) -> set:
        """Squares repeating a number somewhere they may not.

        Shown rather than prevented. A board that refuses the keypress leaves
        somebody pressing a key that does nothing and wondering which of the
        three rules they broke; a board that marks both squares red tells them
        exactly where the argument is.
        """
        bad = set()
        for index, value in enumerate(self.cells):
            if not value:
                continue
            for peer in self.peers(index):
                if self.cells[peer] == value:
                    bad.add(index)
                    bad.add(peer)
        return bad

    def won(self) -> bool:
        return all(self.cells) and not self.conflicts()

    def press(self, key: str) -> bool:
        size = self.SIZE
        if key == "up":
            self.y = max(0, self.y - 1)
        elif key == "down":
            self.y = min(size - 1, self.y + 1)
        elif key == "left":
            self.x = max(0, self.x - 1)
        elif key == "right":
            self.x = min(size - 1, self.x + 1)
        elif key in ("r", "R"):
            self.reset()
        elif key in ("space", "enter") and self.won():
            self.reset()
        elif key in ("0", "space", "backspace", "delete"):
            index = self.y * size + self.x
            if not self.given[index] and self.cells[index]:
                self.cells[index] = 0
                self.moves += 1
        elif key in ("1", "2", "3", "4", "5", "6", "7", "8", "9"):
            index = self.y * size + self.x
            if not self.given[index]:
                value = int(key)
                # The same number again rubs it out, so one key both writes
                # and corrects and nobody has to find the other one.
                self.cells[index] = 0 if self.cells[index] == value else value
                self.moves += 1
        else:
            return False
        return True

    def status(self) -> str:
        if self.won():
            move = "move" if self.moves == 1 else "moves"
            return f"Solved, in {self.moves} {move}. Space for another."
        bad = len(self.conflicts())
        if bad:
            return f"{bad} squares argue" if bad != 1 else "1 square argues"
        left = sum(1 for value in self.cells if not value)
        return f"{left} to place" if left != 1 else "1 to place"

    def paint(self, cr, width, height, ink) -> None:
        size = self.SIZE
        cell, left, top = fit(size, size, width, height, self.max_cell)
        bad = self.conflicts()
        # One background for the whole board.
        #
        # The numbers that came with the puzzle are told apart by their weight
        # and their colour, not by a tinted square behind them. Shading every
        # given turns a nine by nine grid into a mosaic and buries the thing
        # that actually has to be visible, which is the three by three boxes.
        cr.set_source_rgb(*ink["board"])
        cr.rectangle(left, top, size * cell, size * cell)
        cr.fill()
        for y in range(size):
            for x in range(size):
                index = y * size + x
                value = self.cells[index]
                if not value:
                    continue
                cx, cy = left + x * cell, top + y * cell
                if index in bad:
                    colour = ink["bad"]
                elif self.given[index]:
                    colour = ink["ink"]
                else:
                    colour = ink["accent"]
                cr.set_source_rgb(*colour)
                text_at(cr, str(value), cx + cell / 2, cy + cell / 2,
                        cell * 0.62, bold=self.given[index])
        # The lines last, so nothing painted into a cell covers them, and the
        # box boundaries heavier than the rest, because a sudoku whose boxes
        # are not obvious is nine unrelated puzzles.
        for step in range(size + 1):
            heavy = step % 3 == 0
            cr.set_source_rgb(*(ink["ink"] if heavy
                                else blend(ink["board"], ink["edge"], 0.55)))
            cr.set_line_width(2.5 if heavy else 1.0)
            cr.move_to(left + step * cell, top)
            cr.line_to(left + step * cell, top + size * cell)
            cr.stroke()
            cr.move_to(left, top + step * cell)
            cr.line_to(left + size * cell, top + step * cell)
            cr.stroke()
        cursor(cr, left + self.x * cell, top + self.y * cell, cell, ink)


class TicTacToe(Game):
    ident = "ttt"
    keys = "Nothing to press."
    description = "Tic-tac-toe. It is thinking."
    tick_ms = 900

    THINKING = "Thinking."
    STRANGE = "A strange game."
    ONLY_MOVE = "The only winning move is not to play."
    OFFER = "How about a nice game of 2048?"

    def __init__(self, seed: int | None = None) -> None:
        self.frames = 0

    def tick(self) -> bool:
        self.frames += 1
        return True

    def press(self, key: str) -> bool:
        return False

    def status(self) -> str:
        return self.OFFER if self.frames > 3 else self.THINKING

    def paint(self, cr, width, height, ink) -> None:
        cell, left, top = fit(3, 3.9, width, height, 56.0)
        cr.set_source_rgb(*ink["edge"])
        cr.set_line_width(max(1.5, cell * 0.05))
        for step in (1, 2):
            cr.move_to(left + step * cell, top + cell * 0.1)
            cr.line_to(left + step * cell, top + cell * 2.9)
            cr.move_to(left + cell * 0.1, top + step * cell)
            cr.line_to(left + cell * 2.9, top + step * cell)
        cr.stroke()
        if self.frames > 3:
            cr.set_source_rgb(*ink["dim"])
            text_at(cr, self.STRANGE, width / 2, top + cell * 3 + 22, 15)
            cr.set_source_rgb(*ink["accent"])
            text_at(cr, self.ONLY_MOVE, width / 2, top + cell * 3 + 44, 15)


# --------------------------------------------------------------------------
# The registry
# --------------------------------------------------------------------------

GAMES: dict[str, type[Game]] = {
    "life": Life,
    "type": Typing,
    "nono": Nonogram, "sudoku": Sudoku,
    "2048": Twenty48,
    "mines": Minesweeper,
    "lights": LightsOut,
    "fifteen": Fifteen,
    "soko": Sokoban,
    "c4": Connect4,
    "maze": Maze,
    "word": Word,
    "snake": SnakeGame,
    "ttt": TicTacToe,
}


def build(ident: str, seed: int | None = None) -> Game | None:
    """One game by name, or nothing for a picker entry that is not a game."""
    factory = GAMES.get(ident)
    if factory is None:
        return None
    try:
        return factory(seed=seed)  # type: ignore[call-arg]
    except TypeError:
        return factory()
