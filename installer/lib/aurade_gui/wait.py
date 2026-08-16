"""The ten minutes in the middle, for the graphical front end.

The text installer has all of this already, in ``lib/aurade-wait.sh``. This is
the same two things in Python: the tips, read from the same file so that the
two installers cannot tell one person something different from the other, and
a snake with the same rules.

Standard library only, and no ``gi`` import, so the rotation and the game can
both be played through by a test on a machine with no display. Nothing here
reads the journal or can reach the engine. The worst a bug in this file can do
is draw badly.
"""

from __future__ import annotations

import os
import random

#: Where the tips live. Installed next to the shell library that also reads
#: them; the source tree copy is the fallback for running from a checkout.
TIPS_PATHS = (
    "/usr/local/lib/aurade/aurade-tips",
    os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
                 "aurade-tips"),
)

#: One rotation in this many is a rare one. Set to 0 to switch the lane off,
#: which is what a test that needs a fixed sequence does.
RARITY = 40

#: Milliseconds one tip stays on screen. Long enough to read two lines without
#: hurrying, short enough that the card never looks like it has stopped.
TIP_INTERVAL_MS = 9000

#: Milliseconds of crossfade between one tip and the next.
TIP_FADE_MS = 320


def _read(path: str) -> dict[str, list[str]]:
    lanes: dict[str, list[str]] = {"tip": [], "next": [], "rare": []}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if not line or line.startswith("#") or "\t" not in line:
                continue
            lane, text = line.split("\t", 1)
            if lane in lanes and text:
                lanes[lane].append(text)
    return lanes


class Tips:
    """The rotation, with the same shape as the shell one.

    In order rather than at random, because random repeats and a repeat on a
    screen somebody is staring at reads as a screen that has frozen. Every
    fourth turn comes from the ``next`` lane, so what to do after the restart
    keeps coming back around without crowding out everything else. The rare
    lane is the exception and is genuinely random, because something that turns
    up on a schedule is not a surprise the second time.
    """

    def __init__(self, path: str | None = None, rarity: int = RARITY) -> None:
        self.rarity = rarity
        self.lanes: dict[str, list[str]] = {"tip": [], "next": [], "rare": []}
        for candidate in ([path] if path else TIPS_PATHS):
            if candidate and os.path.isfile(candidate):
                try:
                    self.lanes = _read(candidate)
                except OSError:
                    continue
                break

    def __bool__(self) -> bool:
        return bool(self.lanes["tip"])

    def at(self, index: int) -> str:
        rare = self.lanes["rare"]
        if rare and self.rarity > 0 and random.randrange(self.rarity) == 0:
            return random.choice(rare)
        after = self.lanes["next"]
        if index % 4 == 3 and after:
            return after[(index // 4) % len(after)]
        pool = self.lanes["tip"]
        if not pool:
            return ""
        return pool[(index - index // 4) % len(pool)]


class Snake:
    """The same game the text installer has, on a grid of the caller's size.

    A state machine with no drawing in it, so a test can play a whole game
    without a window. Walls are walls; wrapping would make the game easier and
    the arena harder to read, and the border is drawn, so it should mean
    something.
    """

    def __init__(self, width: int = 24, height: int = 12,
                 seed: int | None = None) -> None:
        self.width = max(6, width)
        self.height = max(4, height)
        self.random = random.Random(seed)
        self.reset()

    def reset(self) -> None:
        x = self.width // 4
        y = self.height // 2
        self.body: list[tuple[int, int]] = [(x + 2, y), (x + 1, y), (x, y)]
        self.direction = (1, 0)
        self.pending: tuple[int, int] | None = None
        self.score = 0
        self.dead = False
        self.place_food()

    def place_food(self) -> None:
        # Bounded retry. As the body fills the arena a loop that keeps rolling
        # until it misses the snake takes unbounded time, and the one place
        # that would show is the moment somebody is about to win.
        taken = set(self.body)
        for _ in range(200):
            spot = (self.random.randrange(self.width),
                    self.random.randrange(self.height))
            if spot not in taken:
                self.food: tuple[int, int] | None = spot
                return
        self.food = None

    def turn(self, direction: tuple[int, int]) -> None:
        # Turning back on yourself is the one input a snake ignores, because it
        # is always a mistake rather than a request. Compared against the
        # direction actually travelled, not the one queued, so two fast presses
        # cannot fold the snake into itself.
        current = self.direction
        if (direction[0], direction[1]) == (-current[0], -current[1]):
            return
        self.pending = direction

    def step(self) -> bool:
        """Advance one tick. Returns False once the snake has died."""
        if self.dead:
            return False
        if self.pending is not None:
            self.direction = self.pending
            self.pending = None
        head = (self.body[0][0] + self.direction[0],
                self.body[0][1] + self.direction[1])
        if not (0 <= head[0] < self.width and 0 <= head[1] < self.height):
            self.dead = True
            return False
        # The tail cell moves out from under the head unless the snake is
        # growing, so it does not count as a collision.
        eating = self.food is not None and head == self.food
        occupied = self.body if eating else self.body[:-1]
        if head in occupied:
            self.dead = True
            return False
        self.body.insert(0, head)
        if eating:
            self.score += 1
            self.place_food()
        else:
            self.body.pop()
        return True
