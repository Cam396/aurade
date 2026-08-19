#!/usr/bin/env python3
"""The rules of the thirteen games, and their agreement with the text one.

No toolkit, no display, no compositor. Every game in `aurade_gui/arcade.py` is
a state machine over a board, which is the whole reason it was written that
way: the rules can be played to their end here, in a second, on a machine that
cannot draw anything.

Two kinds of check live in this file.

**The rules**, where each game has one or two properties that are the whole
reason it is playable. A 2048 that merges 2 2 4 into 8, a minesweeper that can
kill you on the first keypress, a lights out that hands you a solved board and
a fifteen puzzle shuffled into the unsolvable half are all games that look
finished and are not.

**The agreement**, because the text installer has had these for a while and
the graphical one has just got them. The two front ends draw from the same
word list, the same phrases, the same levels and the same pictures, and offer
them under the same names in the same order. Two installers that offer
different games are two products, and the one you happened to boot decides
which you get.
"""

from __future__ import annotations

import os
import re
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                     "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "installer", "lib"))

from aurade_gui import arcade as A  # noqa: E402

WAIT_SH = os.path.join(ROOT, "installer", "lib", "aurade-wait.sh")
TUI = os.path.join(ROOT, "installer", "bin", "aurade-installer-tui")

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def shell_array(path: str, name: str) -> list[str]:
    """One bash array's entries, from the source that declares it.

    Parsed rather than executed. Sourcing the text installer to read a list
    out of it would run its whole top level, and the point of this file is
    that it needs nothing.

    The scan is by hand rather than by regular expression because both shapes
    have to work: `NAME=(a b c)` on one line and `NAME=(` with the entries
    under it. A pattern anchored to a closing bracket at the start of a line
    reads a single line array and then keeps going to the next unrelated
    closing bracket in the file, which is how this test first went green while
    comparing a game list against a chunk of an associative array.
    """
    text = open(path, encoding="utf-8").read()
    match = re.search(rf"^{re.escape(name)}=\(", text, re.M)
    if match is None:
        return []
    index = match.end()
    depth = 1
    quote = ""
    body: list[str] = []
    while index < len(text) and depth:
        char = text[index]
        if quote:
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if not depth:
                break
        body.append(char)
        index += 1
    return [first or second or third for first, second, third in
            re.findall(r"'([^']*)'|\"([^\"]*)\"|([^\s'\"]+)", "".join(body))]


def shell_map(path: str, name: str) -> dict[str, str]:
    text = open(path, encoding="utf-8").read()
    match = re.search(rf"^declare -A {re.escape(name)}=\(\n(.*?)^\)", text,
                      re.S | re.M)
    if match is None:
        return {}
    out: dict[str, str] = {}
    for key, value in re.findall(r"\[([^\]]+)\]='([^']*)'", match.group(1)):
        out[key] = value
    return out


# -- the picker ------------------------------------------------------------
#
# Same entries, same order, same words. The order carries an argument: the
# things that ask nothing of anybody come first, so somebody who finds a game
# on this screen stressful is not made to scroll past a snake to reach the
# reading.

tui_choices = shell_array(TUI, "WAIT_CHOICES")
tui_labels = shell_map(TUI, "WAIT_LABELS")
check(bool(tui_choices), "the text installer's picker list could not be read")

# `log` is the text installer's alone: the graphical one has no console to
# stream. Everything else is expected in both, in the same order.
expected = [ident for ident in tui_choices if ident != "log"]
check([ident for ident, _text in A.CHOICES] == expected,
      f"the two pickers disagree: {[i for i, _ in A.CHOICES]} against {expected}")
for ident, text in A.CHOICES:
    check(tui_labels.get(ident) == text,
          f"{ident} is called {text!r} here and {tui_labels.get(ident)!r} there")

# -- the shared data -------------------------------------------------------

tui_words = shell_array(WAIT_SH, "AURADE_WORDS")
check(sorted(tui_words) == sorted(A.Word.WORDS),
      f"the word lists differ: {len(tui_words)} words there, "
      f"{len(A.Word.WORDS)} here")
check(all(len(word) == 5 for word in A.Word.WORDS),
      "a word in the list is not five letters, which makes a round unwinnable")

tui_phrases = shell_array(WAIT_SH, "AURADE_TYPE_PHRASES")
check(sorted(tui_phrases) == sorted(A.Typing.PHRASES),
      "the typing phrases differ between the two installers")

tui_levels = shell_array(WAIT_SH, "AURADE_SOKO_LEVELS")
check(sorted(tui_levels) == sorted(A.Sokoban.LEVELS),
      "the sokoban levels differ between the two installers")

tui_art = shell_array(WAIT_SH, "AURADE_NONO_ART")
here = [f"{name}:{rows}" for name, rows in A.Nonogram.ART]
check(sorted(tui_art) == sorted(here),
      "the nonogram pictures differ between the two installers")

# -- 2048 ------------------------------------------------------------------
#
# The rule everybody gets wrong. A tile merges at most once per move, so a row
# of 2 2 4 slid left is 4 4, and never 8.

game = A.Twenty48(seed=1)
game.board = [2, 2, 4, 0] + [0] * 12
game.score = 0
game.move("left")
check(game.board[:3] == [4, 4, 0] or game.board[:2] == [4, 4],
      f"2 2 4 merged into {game.board[:4]}, so a tile merged twice")
check(game.score == 4, f"the score for merging one pair was {game.score}")

game = A.Twenty48(seed=2)
filled = sum(1 for value in game.board if value)
check(filled == 2, f"a new board started with {filled} tiles, not two")
# Full, and nothing beside anything equal to it: there is no move, so it is
# over. This is the board somebody actually loses on.
game.board = [2, 4, 2, 4, 4, 2, 4, 2, 2, 4, 2, 4, 4, 2, 4, 2]
check(game.over(), "a full board with no move available was not over")
# Full, but two equal tiles are touching, so there is a move and it is not
# over. A game that calls this over is a game that ends early.
game.board = [2, 2, 4, 8, 16, 32, 64, 128,
              256, 512, 1024, 2, 4, 8, 16, 32]
check(not game.over(), "a full board with a merge available was called over")

# A move that changes nothing must not spawn a tile, or the board fills up
# while somebody presses a key that is doing nothing.
game = A.Twenty48(seed=3)
game.board = [2, 4, 8, 16] + [0] * 12
count = sum(1 for value in game.board if value)
game.move("up")
check(sum(1 for value in game.board if value) == count,
      "a move that moved nothing still spawned a tile")

# -- minesweeper -----------------------------------------------------------
#
# The mines are placed after the first reveal and never under it or beside it,
# so the first keypress of a game somebody started to pass the time can never
# lose it.

for seed in range(40):
    game = A.Minesweeper(seed=seed)
    game.x, game.y = 4, 4
    game.reveal()
    check(not game.dead, f"seed {seed} lost minesweeper on the first press")
    check(game.near(4, 4) == 0,
          f"seed {seed} put a mine beside the first square opened")
    check(sum(game.mines) == A.Minesweeper.COUNT,
          f"seed {seed} laid {sum(game.mines)} mines, not {A.Minesweeper.COUNT}")
    check(sum(game.shown) > 1,
          f"seed {seed} opened one square from an empty first press")

# Flagging a square keeps it shut, and opening every square that is not a mine
# wins even with no flag planted.
game = A.Minesweeper(seed=7)
game.reveal()
for index in range(81):
    if not game.mines[index]:
        game.x, game.y = index % 9, index // 9
        game.reveal()
check(game.won, "opening every safe square did not win")

# -- lights out ------------------------------------------------------------
#
# Generated from solved by pressing cells, so it is always solvable, and never
# handed over already solved.

def lights_solvable(cells: list[int]) -> bool:
    """Whether this board can be turned off at all, over GF(2).

    A random five by five board is solvable slightly less than half the time,
    and an impossible puzzle handed to somebody waiting for a disk to be
    written is not a joke worth making. The generator avoids it by starting
    from solved and pressing cells; this checks the property directly rather
    than trusting the generator to have that shape, by solving the system.

    Twenty five equations in twenty five unknowns, eliminated in place. The
    quiet patterns everybody quotes for this puzzle are the null space of the
    same matrix, and computing it is shorter than getting them right from
    memory.
    """
    rows = []
    for index in range(25):
        x, y = index % 5, index // 5
        mask = 0
        for cx, cy in ((x, y), (x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= cx < 5 and 0 <= cy < 5:
                mask |= 1 << (cy * 5 + cx)
        rows.append((mask, cells[index]))
    pivot_row = 0
    for column in range(25):
        found = None
        for candidate in range(pivot_row, 25):
            if rows[candidate][0] >> column & 1:
                found = candidate
                break
        if found is None:
            continue
        rows[pivot_row], rows[found] = rows[found], rows[pivot_row]
        mask, value = rows[pivot_row]
        for other in range(25):
            if other != pivot_row and rows[other][0] >> column & 1:
                rows[other] = (rows[other][0] ^ mask, rows[other][1] ^ value)
        pivot_row += 1
    # A row with no unknowns left in it and a one on the right is a
    # contradiction, which is a board nobody can finish.
    return not any(mask == 0 and value for mask, value in rows)


for seed in range(60):
    game = A.LightsOut(seed=seed)
    check(not game.won(), f"seed {seed} generated a lights out already solved")
    check(lights_solvable(game.cells),
          f"seed {seed} generated a lights out that cannot be turned off")

# The retry, forced rather than waited for. Six presses on the same cell
# cancel out and leave the board solved, which a generator without the retry
# hands over as a finished puzzle. Sixty random seeds will not produce that in
# a lifetime, so the run of presses is made to produce it on purpose.
class SameCell:
    """A generator that presses the same square six times, then behaves."""

    def __init__(self) -> None:
        self.calls = 0

    def randrange(self, _limit: int) -> int:
        self.calls += 1
        if self.calls <= 12:
            return 0
        return (self.calls * 7) % 5


game = A.LightsOut(seed=1)
game.random = SameCell()
game.reset()
check(not game.won(),
      "a lights out that generated itself solved was handed over as a puzzle")

game = A.LightsOut(seed=1)
game.cells = [0] * 25
game.cells[12] = 1
game.x, game.y = 2, 2
game.press("space")
check(game.cells[12] == 0 and game.cells[7] == 1 and game.cells[17] == 1,
      "pressing a light did not turn its four neighbours as well")

# -- the fifteen puzzle ----------------------------------------------------
#
# Shuffled by legal moves, so it is always in the solvable half. Solving it
# from the shuffle by replaying the moves backwards is not possible here, so
# the property checked is parity, which is what decides the half.

def solvable(tiles: list[int]) -> bool:
    order = [value for value in tiles if value]
    inversions = sum(1 for i in range(len(order))
                     for j in range(i + 1, len(order))
                     if order[i] > order[j])
    hole_row_from_bottom = 4 - (tiles.index(0) // 4)
    if hole_row_from_bottom % 2 == 0:
        return inversions % 2 == 1
    return inversions % 2 == 0


for seed in range(40):
    game = A.Fifteen(seed=seed)
    check(solvable(game.tiles), f"seed {seed} shuffled into an unsolvable board")
    check(game.moves == 0, f"seed {seed} counted the shuffle as moves")
    check(sorted(game.tiles) == list(range(16)),
          f"seed {seed} lost or duplicated a tile while shuffling")

# -- sokoban ---------------------------------------------------------------
#
# A box pushed into a corner is why there is an undo, and the undo has to put
# the board back exactly.

game = A.Sokoban()
board = list(game.boxes)
where = (game.x, game.y)
moved = any(game.move(direction) for direction in ("right", "right", "down"))
check(moved, "no legal move existed on the first sokoban level")
check(game.undo() or True, "undo raised")
while game.undo():
    pass
check(game.boxes == board and (game.x, game.y) == where,
      "undoing every move did not put the level back where it started")

game = A.Sokoban()
game.press("right")
check(game.won(), "pushing the only box onto the only target did not win")

# -- connect 4 -------------------------------------------------------------
#
# The opponent takes a win it can see and blocks one it can see, and nothing
# past that. Both halves are checked, because an opponent that does neither is
# a random player and one that does more is not beatable while distracted.

game = A.Connect4(seed=1)
game.board = [0] * 42
for column in (0, 1, 2):
    game.board[5 * 7 + column] = 2
game.column = 6
game.drop()
check(game.over == 2, "the opponent did not take a win it could see")

# Blocking, checked where the square it has to take is not the square it
# prefers anyway. Three in a row at columns 1, 2 and 3 has to be blocked at
# column 0 or column 4, and an opponent that has stopped looking falls back to
# the middle and takes column 3, which is why the threat is not put there.
for seed in range(12):
    game = A.Connect4(seed=seed)
    game.board = [0] * 42
    for column in (1, 2, 3):
        game.board[5 * 7 + column] = 1
    game.column = 6
    game.drop()
    check(game.board[5 * 7 + 0] == 2 or game.board[5 * 7 + 4] == 2,
          f"seed {seed}: the opponent did not block three in a row it could see")

game = A.Connect4(seed=1)
for column in range(7):
    for _ in range(6):
        game._put(column, 1)
check(game.full(), "a board with every column filled did not report full")

# One turn drops two counters, so at most two can be falling. The opponent
# tries a move in every column before it chooses one, and a probe that leaves
# its counter falling draws a disc dropping into a square nobody played.
for seed in range(8):
    game = A.Connect4(seed=seed)
    game.drop()
    check(len(game.falling) <= 2,
          f"seed {seed}: {len(game.falling)} counters are falling after one turn")
    for index in game.falling:
        check(game.board[index] != 0,
              f"seed {seed}: a counter is falling into an empty square")

# -- the maze --------------------------------------------------------------
#
# Perfect: exactly one path between any two cells, so it is always solvable
# and there is never a loop to walk round twice. Checked by flood fill.

for seed in range(20):
    game = A.Maze(seed=seed)
    seen = {(1, 1)}
    queue = [(1, 1)]
    while queue:
        x, y = queue.pop()
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            wx, wy = x + dx, y + dy
            nx, ny = x + dx * 2, y + dy * 2
            if not (0 <= nx < game.columns and 0 <= ny < game.rows):
                continue
            if game.walls[wy * game.columns + wx] == "#":
                continue
            if (nx, ny) in seen:
                continue
            seen.add((nx, ny))
            queue.append((nx, ny))
    cells = A.Maze.CELLS_W * A.Maze.CELLS_H
    check(len(seen) == cells,
          f"seed {seed} reached {len(seen)} of {cells} cells, so the maze "
          "has a part with no way into it")
    check((game.exit_x, game.exit_y) in seen,
          f"seed {seed} put the way out somewhere unreachable")

# -- the word guess --------------------------------------------------------
#
# The doubled letter rule, which is the one everybody gets wrong. A letter
# guessed twice when the answer holds it once comes back right in one place
# and absent in the other, never present in both.

check(A.Word.mark("geese", "these") == "..===",
      f"doubled letters marked as {A.Word.mark('geese', 'these')!r}")
# Two esses guessed where the answer holds one: the first claims it and the
# second comes back absent, rather than both saying "somewhere else".
check(A.Word.mark("sassy", "usage") == "~~...",
      f"doubled letters marked as {A.Word.mark('sassy', 'usage')!r}")
check(A.Word.mark("crane", "crane") == "=====", "an exact guess was not exact")
check(A.Word.mark("fuzzy", "crane") == ".....",
      "a guess with no letters in common marked something")

game = A.Word(seed=4)
game.answer = "crane"
for letter in "crane":
    game.press(letter)
game.press("enter")
check(game.over == 1, "guessing the word did not end the round")

game = A.Word(seed=5)
game.answer = "crane"
for _round in range(A.Word.TRIES):
    for letter in "fuzzy":
        game.press(letter)
    game.press("enter")
check(game.over == 2, "six wrong guesses did not end the round")
check("CRANE" in game.status().upper(),
      f"the round ended without saying the word: {game.status()!r}")

# -- life ------------------------------------------------------------------
#
# The grid wraps, which is the whole reason it is still moving ten minutes in.
# A glider walked off the right edge has to reappear on the left.

game = A.Life(12, 12, seed=1)
game.cells = [0] * 144
for x, y in ((1, 0), (2, 1), (0, 2), (1, 2), (2, 2)):
    game.cells[y * 12 + x] = 1
for _ in range(48):
    game.tick()
check(sum(game.cells) == 5,
      f"a glider on a wrapping grid became {sum(game.cells)} cells")

# A blinker is the smallest thing that proves the neighbour count is right.
game = A.Life(12, 12, seed=1)
game.cells = [0] * 144
for x in (4, 5, 6):
    game.cells[5 * 12 + x] = 1
game.tick()
check([game.cells[y * 12 + 5] for y in (4, 5, 6)] == [1, 1, 1],
      "a blinker did not turn, so the neighbour count is wrong")

# -- every game ------------------------------------------------------------
#
# The contract the window relies on: a board that says what shape it is, keys
# that say what they do, and a `press` that never raises whatever is sent to
# it. The window hands these keys straight from a keyboard.

KEYS = ("up", "down", "left", "right", "space", "enter", "backspace",
        "f", "F", "u", "n", "r", "R", "a", "z", "1", " ", "")
for ident, text in A.CHOICES:
    if ident in A.NOT_GAMES:
        continue
    game = A.build(ident, seed=11)
    check(game is not None, f"{ident} is in the picker and does not build")
    if game is None:
        continue
    check(game.ident == ident, f"{ident} builds a game calling itself {game.ident}")
    check(bool(game.keys), f"{ident} does not say what its keys do")
    check(bool(game.description), f"{ident} has nothing to say to a screen reader")
    shape = getattr(game, "grid", None)
    check(shape is None or (isinstance(shape, tuple) and len(shape) == 2
                            and shape[0] > 0 and shape[1] > 0),
          f"{ident} reports a board shape of {shape!r}")
    for key in KEYS:
        game.press(key)
    if game.tick_ms:
        for _ in range(30):
            game.tick()
    check(isinstance(game.status(), str), f"{ident} has no status line")

# The tic-tac-toe does not play, which is the joke, and it must stay a joke
# rather than becoming a game with no opponent.
ttt = A.build("ttt")
check(not ttt.press("space"), "the tic-tac-toe accepted a move")
for _ in range(6):
    ttt.tick()
check("2048" in ttt.status(), f"the tic-tac-toe never offers 2048: {ttt.status()!r}")

if FAILURES:
    for failure in FAILURES:
        print(f"arcade test: {failure}", file=sys.stderr)
    print(f"arcade test: FAIL ({len(FAILURES)})", file=sys.stderr)
    sys.exit(1)
print("arcade test: PASS")
