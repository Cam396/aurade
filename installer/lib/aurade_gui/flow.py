"""Page order, wording, and what each button actually does.

No GTK import anywhere in this file. The rules that decide whether a
destructive step is reachable, what a back button does, and what a screen
promises are exactly the rules worth testing, and a test that needs a display
server to run is a test that does not run on the machine that builds the
image.

The shape follows the text installer's ``main_flow``: a state machine rather
than a straight line, because "back" has to be able to go back, and because
``--plan-only`` has to be a state with no transition to a destructive one
rather than a flag someone checks just before the destructive call.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Page:
    """One screenful of the flow.

    ``questions`` names ids from the shared manifest. It is never a place to
    invent a question: an id here that the manifest does not carry is a bug
    the page test catches, and a manifest id missing from every page is the
    same bug pointing the other way.
    """

    name: str
    title: str
    subtitle: str
    questions: tuple[str, ...] = ()
    optional: bool = False


PAGES: tuple[Page, ...] = (
    Page(
        name="readiness",
        title="A quick look at this computer",
        # No subtitle. The verdict under it is the answer, and a page that
        # says the same thing twice before saying anything is a page nobody
        # finishes reading.
        subtitle="",
    ),
    Page(
        name="network",
        title="Get online",
        subtitle="The package list is checked before the disk changes.",
    ),
    Page(
        name="language",
        title="Language and keyboard",
        subtitle="Both take effect now, so your password is typed on the right layout.",
        questions=("locale", "keymap", "timezone"),
    ),
    Page(
        name="disk",
        title="Choose a disk",
        subtitle=(
            "Everything on the disk you pick is erased. Nothing happens until "
            "you confirm it by name."
        ),
        # The four after `target` are the advanced storage controls. They are
        # on this page rather than on the advanced page at the end because
        # they are all answers about the disk in front of you, and a layout
        # choice made four screens after the disk was picked is a choice made
        # about a disk you have stopped looking at.
        questions=("target", "layout", "filesystem", "swap", "swap_size"),
    ),
    Page(
        name="account",
        title="Make yourself an account",
        subtitle="This is who you will sign in as.",
        questions=("hostname", "username", "password"),
    ),
    Page(
        name="encryption",
        title="Disk encryption",
        subtitle="Your files stay unreadable to anyone without the passphrase.",
        questions=("encrypt", "luks_passphrase"),
    ),
    Page(
        name="advanced",
        title="Advanced options",
        subtitle="These already have answers that work.",
        questions=("snapshot", "repo_url"),
        optional=True,
    ),
)

PAGES_BY_NAME: dict[str, Page] = {page.name: page for page in PAGES}

#: Pages whose content is a board of cards or rows rather than prose, and which
#: therefore get the wider measure. Everything not named here stays narrow.
PAGE_WIDTHS: dict[str, int] = {
    "readiness": 940,
    "network": 820,
    "disk": 820,
}

#: Page names in the order the flow walks them.
PAGE_ORDER: tuple[str, ...] = tuple(page.name for page in PAGES)


def page_for_question(question: str) -> Page | None:
    for page in PAGES:
        if question in page.questions:
            return page
    return None


def grouped_questions() -> tuple[str, ...]:
    """Every question any page shows, in page order."""
    return tuple(q for page in PAGES for q in page.questions)


# --------------------------------------------------------------------------
# States
# --------------------------------------------------------------------------

WELCOME = "welcome"
REVIEW = "review"
GATE = "gate"
PROGRESS = "progress"
DONE = "done"
FAILURE = "failure"
CANCELLED = "cancelled"
STOPPED = "stopped"
PLANNED = "planned"

def engages(state: str) -> bool:
    """Whether leaving this state is a commitment the renderer chain must keep.

    The launcher walks a list of ways to draw, and stops walking it the moment
    the front end reports `engaged`, because after that there are answers on
    the screen that restarting under a different renderer would throw away.

    The welcome screen is the one state where that is not true. Nothing has
    been answered on it, no network has been joined, and a restart would
    discard nothing at all. Reporting it there cost the whole client list at
    the worst possible moment: leaving the welcome page is the first animation
    the process draws, so it is the single most likely place for a graphics
    stack to take the process down, and that is exactly the failure the rest of
    the list exists to recover from. What happened instead was a console, one
    keypress into somebody's install.

    A rule and not a condition written inline, because the inline version is
    one line in a GTK callback that no test without a display can reach.
    """
    return state != WELCOME


#: States that end the session. None of them offers a way back into the flow.
TERMINAL: frozenset[str] = frozenset({DONE, FAILURE, CANCELLED, STOPPED, PLANNED})

#: States that must not be reachable when the installer was started with
#: ``--plan-only``. Asserted by walking the transition graph, not by reading
#: the source: the property that matters is unreachability, and a flag tested
#: in the right place today is one edit away from being tested in the wrong
#: place tomorrow.
DESTRUCTIVE: frozenset[str] = frozenset({GATE, PROGRESS, DONE, STOPPED})


@dataclass
class Flow:
    """Where the installer is, and where it may go from here.

    ``show_advanced`` is set when the user opens the advanced page. Skipping
    it is safe because every advanced question has a working default, which
    the shared manifest guarantees and its own test enforces.
    """

    plan_only: bool = False
    show_advanced: bool = False
    state: str = WELCOME
    page_index: int = 0
    _visible_pages: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self._visible_pages:
            self._visible_pages = self._compute_pages()

    # -- page visibility ---------------------------------------------------

    def _compute_pages(self) -> tuple[str, ...]:
        return tuple(
            page.name
            for page in PAGES
            if not page.optional or self.show_advanced
        )

    def set_show_advanced(self, show: bool) -> None:
        current = self.current_page
        self.show_advanced = show
        self._visible_pages = self._compute_pages()
        if current in self._visible_pages:
            self.page_index = self._visible_pages.index(current)
        else:
            self.page_index = min(self.page_index, len(self._visible_pages) - 1)

    @property
    def pages(self) -> tuple[str, ...]:
        return self._visible_pages

    @property
    def current_page(self) -> str:
        if not self._visible_pages:
            return ""
        index = max(0, min(self.page_index, len(self._visible_pages) - 1))
        return self._visible_pages[index]

    # -- transitions -------------------------------------------------------

    def transitions(self, state: str | None = None) -> tuple[str, ...]:
        """Every state reachable in one step. The graph, stated once.

        ``pages`` is collapsed into a single node here: which page is showing
        does not change which *states* exist, and the reachability question
        this answers is about states.
        """
        state = self.state if state is None else state
        if state == WELCOME:
            return ("pages", CANCELLED)
        if state == "pages":
            return ("pages", WELCOME, REVIEW, CANCELLED)
        if state == REVIEW:
            if self.plan_only:
                return ("pages", PLANNED, FAILURE, CANCELLED)
            return ("pages", GATE, FAILURE, CANCELLED)
        if state == GATE:
            # Only in a session that may erase. In plan-only mode nothing
            # returns GATE above, so this branch is unreachable there.
            return (REVIEW, PROGRESS, CANCELLED)
        if state == PROGRESS:
            # Stopping is only reachable while the shared reversibility
            # boundary says nothing has been written, and it lands in its own
            # state rather than in FAILURE, because a run the user ended on
            # purpose is not a run that broke.
            return (DONE, FAILURE, STOPPED)
        return ()

    def reachable(self, start: str = WELCOME) -> frozenset[str]:
        """Every state reachable from ``start``, by walking the graph."""
        seen: set[str] = set()
        queue = [start]
        while queue:
            state = queue.pop()
            if state in seen:
                continue
            seen.add(state)
            queue.extend(self.transitions(state))
        return frozenset(seen)

    # -- movement ----------------------------------------------------------

    def begin(self) -> str:
        self.state = "pages"
        self.page_index = 0
        return self.state

    def forward(self) -> str:
        """Advance one step. Never crosses the erase gate on its own."""
        if self.state == WELCOME:
            return self.begin()
        if self.state == "pages":
            if self.page_index + 1 < len(self._visible_pages):
                self.page_index += 1
                return self.state
            self.state = REVIEW
            return self.state
        if self.state == REVIEW:
            self.state = PLANNED if self.plan_only else GATE
            return self.state
        return self.state

    def back(self) -> str:
        if self.state == "pages":
            if self.page_index > 0:
                self.page_index -= 1
                return self.state
            self.state = WELCOME
            return self.state
        if self.state == REVIEW:
            # Reopens the last page rather than the first, because "back" from
            # a summary means the thing just above it.
            self.state = "pages"
            self.page_index = max(0, len(self._visible_pages) - 1)
            return self.state
        if self.state == GATE:
            self.state = REVIEW
            return self.state
        return self.state

    def cancel(self) -> str:
        if self.state in TERMINAL or self.state == PROGRESS:
            return self.state
        self.state = CANCELLED
        return self.state

    def plan_failed(self) -> str:
        self.state = FAILURE
        return self.state

    def confirmed(self) -> str:
        """The one transition that leads to an erase.

        Refuses outright in plan-only mode. That refusal is a second line of
        defence and not the guarantee: the guarantee is that ``GATE`` is not
        reachable at all, which ``reachable()`` shows.
        """
        if self.plan_only:
            raise RuntimeError("plan-only sessions cannot reach the erase gate")
        if self.state != GATE:
            raise RuntimeError(f"cannot confirm an erase from {self.state}")
        self.state = PROGRESS
        return self.state

    def finished(self, status: int, cause: str = "") -> str:
        if status == 0:
            self.state = DONE
        elif cause == "cancelled":
            self.state = STOPPED
        else:
            self.state = FAILURE
        return self.state

    def jump_to_page(self, name: str) -> str:
        """Open one page directly, which is what a review row is for.

        Walking back through four screens to fix a typo in a hostname is the
        kind of thing that makes people accept a wrong answer instead. Every
        row on the review screen goes straight to the page that set it.
        """
        if name not in self._visible_pages:
            if name == "advanced":
                self.set_show_advanced(True)
            if name not in self._visible_pages:
                return self.state
        self.state = "pages"
        self.page_index = self._visible_pages.index(name)
        return self.state

    # -- what the buttons say ----------------------------------------------
    #
    # A back button labelled "Back" on a screen that quits is the graphical
    # form of a footer that offers `esc back` and cancels, and it is read at
    # the moment the user is least sure. The label and the action come from
    # the same place so they cannot disagree.

    def back_action(self) -> str:
        """``quit``, ``back``, or ``""`` when no back control is offered."""
        if self.state == WELCOME:
            return "quit"
        if self.state == "pages":
            return "quit" if self.page_index == 0 else "back"
        if self.state in (REVIEW, GATE):
            return "back"
        return ""

    def back_label(self) -> str:
        return {"quit": "Quit", "back": "Back"}.get(self.back_action(), "")

    def forward_label(self) -> str:
        if self.state == WELCOME:
            return "Get started"
        if self.state == "pages":
            last = self.page_index + 1 >= len(self._visible_pages)
            return "Review" if last else "Next"
        if self.state == REVIEW:
            return "Check the plan" if self.plan_only else "Continue"
        if self.state == GATE:
            return "Erase and install"
        if self.state == DONE:
            return "Restart"
        return ""

    def step_position(self) -> str:
        if self.state != "pages" or not self._visible_pages:
            return ""
        return f"Step {self.page_index + 1} of {len(self._visible_pages)}"


# --------------------------------------------------------------------------
# Wording that has to be exactly right
# --------------------------------------------------------------------------

WELCOME_TITLE = "Let's set up AuraDE"
WELCOME_BODY = "A few questions, then AuraDE takes it from here."
WELCOME_ASSURANCE = "Nothing is written to any disk until you confirm."

#: What the credit line in the corner offers. Said as an invitation rather
#: than as an instruction, because nothing depends on anybody taking it up.
WALLPAPER_HINT = "Show a different photograph"
#: What the caption itself does now. The picture changes from inside the card
#: rather than from the caption, so the caption opens and no longer swaps.
WALLPAPER_CARD_HINT = "Read about this photograph"

#: The card that appears when the caption is pointed at or focused.
WALLPAPER_CARD_ELSEWHERE = "there"
WALLPAPER_CARD_HERE = "here"
#: Said instead of a time when the picture is not of anywhere, so there is no
#: clock to read. Nothing is invented to fill the space.
WALLPAPER_CARD_NOWHERE = "Not anywhere in particular."

#: The Bible, offered quietly on the welcome page and nowhere else.
#:
#: A small button at the bottom, and no explanation attached to it. Somebody
#: who wants it knows what it is, and somebody who does not want it should be
#: able to walk past without the installer having made a point.
#: Said when the two secret fields disagree, and said on leaving the second
#: one rather than on pressing Continue.
#:
#: It does not say which character differs, or how far in, or which of the two
#: is longer. Anything that narrows it down is a hint about a secret, printed
#: on a screen that might have somebody standing behind it, and the person who
#: typed it does not need the hint anyway: they need to type it again.
SECRET_MISMATCH = "These two do not match."

BIBLE_BUTTON = "Read the Bible"
BIBLE_TITLE = "The Bible"
BIBLE_EDITION = "King James Version, with the Apocrypha"
BIBLE_BOOK = "Book"
BIBLE_CHAPTER = "Chapter"

#: The readiness page's verdict line, keyed by the model's verdict. It is the
#: first sentence of the installer that is about *this* computer rather than
#: about the product, so it says what happens next rather than restating the
#: findings listed under it.
READINESS_VERDICTS: dict[str, tuple[str, str]] = {
    "ok": (
        "Ready when you are",
        "Nothing on this computer has been touched.",
    ),
    "attention": (
        "Almost ready",
        "This will install. What is below is worth sorting out first.",
    ),
    "blocked": (
        "One thing to fix first",
        "AuraDE cannot install until this changes.",
    ),
}

READINESS_DETAILS = "Details"

#: Shown when the model cannot be reached for a readiness report at all. The
#: page still has to say something, and "no findings" would read as "all clear".
READINESS_UNKNOWN = (
    "These checks could not run. The install still stops before erasing "
    "anything if it hits a problem later."
)

STORAGE_TITLE = "Storage options"
STORAGE_SUBTITLE = "The defaults are what AuraDE is built for."

REVIEW_TITLE = "Here is what will happen"
REVIEW_ASSURANCE = "Nothing has been written to any disk yet."

GATE_TITLE = "Confirm erase"
GATE_BODY = (
    "Everything up to here can be undone. Nothing after it can.\n\n"
    "The package list and archive are checked first. On low memory computers, "
    "packages download after the new system is formatted. If a download fails, "
    "the install stops with an incomplete system on the new disk."
)

PROGRESS_TITLE = "Making this computer yours"
#: Two footers, and which one is showing is the answer to the only question
#: somebody hovering over the power button has. Before the reversibility
#: boundary, turning the machine off costs them a download. After it, it costs
#: them the disk. A warning displayed at a moment it does not apply to is a
#: warning that gets believed less at the moment it does.
PROGRESS_FOOTER = "Do not turn off this computer."
PROGRESS_FOOTER_SAFE = "Nothing has been written to any disk yet."
PROGRESS_UNINTERRUPTIBLE = "This part cannot be interrupted safely."

#: The pacing line, assembled from three pieces so that the two front ends can
#: build the same sentence out of the same parts. Deliberately a range and not
#: a countdown: an estimate that turns out wrong is remembered longer than the
#: install it was wrong about.
PROGRESS_PACING = "Usually %s."
PROGRESS_ELAPSED_ONE = "1 minute so far."
PROGRESS_ELAPSED = "%d minutes so far."

#: The step count, which is also the disclosure that opens into the full list.
PROGRESS_STEPS = "Steps"
PROGRESS_STEP_IDLE = "Getting ready"


def progress_steps(done: int, pending: int) -> str:
    """"6 done, 4 to go", and the singular cases, and the ends.

    Written out rather than assembled from fragments because "1 steps done" is
    the kind of thing that survives review and then sits on the screen for the
    length of an install.
    """
    if not done and not pending:
        return PROGRESS_STEPS
    if not pending:
        return "All steps done"
    if not done:
        return "1 step to go" if pending == 1 else f"{pending} steps to go"
    finished = "1 done" if done == 1 else f"{done} done"
    left = "1 to go" if pending == 1 else f"{pending} to go"
    return f"{finished}, {left}"


#: The card underneath, which is either something to read or something to do.
#:
#: The line beside each board is the board's own, and lives with the game in
#: `arcade.py` rather than here. A score is not copy about installing AuraDE;
#: it is a game saying what just happened, and putting fourteen of those in
#: this file would bury the twenty strings that are about the install.
#: Typed into the erase gate's confirmation field. It declines and clears the
#: field, which is stricter than ignoring it, and nothing about the gate is
#: weakened by it: the token is unchanged, the comparison is unchanged, and
#: there is no path from here to the button.
GATE_NOT_TODAY = "Not today."

#: The characters worth typing into the keyboard check, which are the ones
#: that move between layouts. Letters mostly stay put and punctuation does
#: not, and punctuation is what a good disk passphrase is full of. Word for
#: word what the text installer puts under its own keyboard check.
KEYCHECK_MOVERS = r'These move around between layouts:  @  #  "  |  \  /  y  z'

#: The status area, top right. Three facts every other computer puts in a
#: corner and this one did not have anywhere.
#:
#: Each has a spoken form as well as a drawn one, and the spoken form is a
#: sentence rather than the same glyph read out: "82 percent, on battery" is
#: an answer, and "battery, 82 percent" is a label being read to somebody.
STATUS_CLOCK = "The time"
STATUS_CLOCK_IS = "The time is %s."
STATUS_BATTERY_NAME = "Battery"
STATUS_BATTERY = "%d percent, on battery."
STATUS_BATTERY_CHARGING = "%d percent, plugged in and charging."
STATUS_BATTERY_LOW = (
    "%d percent, on battery, and low. Installing takes about ten minutes, "
    "and losing power part way through leaves a disk that is neither the old "
    "system nor the new one. Plug it in."
)
STATUS_NET_NAME = "Network"
STATUS_NET_WIRED = "Connected by cable."
STATUS_NET_WIFI = "Connected by Wi-Fi."
STATUS_NET_NO_ROUTE = (
    "A network is attached but there is no route out, so nothing can be "
    "downloaded yet."
)
STATUS_NET_NONE = "Not connected to any network."
#: Beside the icon when there is no connection. Two characters rather than a
#: sentence, because it sits next to a clock in a top bar, and the sentence is
#: what the tooltip and the screen reader get.
STATUS_NET_SHORT = "off"

#: The download meter, during either package download stage. Word for word
#: what the text installer says in plain mode, because both front ends watch
#: the same file.
PROGRESS_DOWNLOAD = "Downloading at %s"


def rate_label(per_second: int) -> str:
    """Bytes per second, in the units a person would use.

    The same three tiers and the same one decimal place as `tui_rate` in
    `lib/aurade-tui.sh`, and deliberately the same rounding: this number is
    drawn beside the same sparkline in both front ends, and one of them saying
    4.2 MB/s while the other says 4.3 is two products.
    """
    if not isinstance(per_second, int) or per_second < 0:
        return ""
    if per_second >= 1048576:
        whole, tenth = divmod(per_second, 1048576)
        return f"{whole}.{tenth * 10 // 1048576} MB/s"
    if per_second >= 1024:
        whole, tenth = divmod(per_second, 1024)
        return f"{whole}.{tenth * 10 // 1024} kB/s"
    return f"{per_second} B/s"


WAIT_PICKER = "What to do while this runs"
WAIT_PICKER_WHY = (
    "Something to read, something to watch, or one of thirteen games. "
    "Nothing here affects the installation."
)
WAIT_ARENA = "The waiting card"
WAIT_ARENA_IDLE = (
    "Nothing is playing. The list beside this has things to read and games "
    "to play while the installation runs."
)

DONE_TITLE = "You are all set"
DONE_RESTART = "Restart"
DONE_PLAY = "Keep playing"
DONE_BODY = (
    "Take out the installation media and restart. Sign in with the username "
    "and password you chose."
)
#: The two facts people forget within a minute of the install finishing, and
#: the two they need in the next thirty seconds. Word for word what the text
#: installer says, because two front ends phrasing the same fact differently
#: is two products.
DONE_SIGN_IN = "Sign in as"
DONE_COMPUTER = "This computer"

DONE_ENCRYPTED = (
    "Your disk is encrypted. This computer asks for the disk passphrase "
    "before the sign-in screen, every time it starts. That is the passphrase "
    "you set here, not your account password."
)

STOPPED_TITLE = "Stopped, and nothing was written"
STOPPED_BODY = (
    "No disk was partitioned, formatted or written to. This computer is "
    "exactly as it was."
)

CANCELLED_TITLE = "Cancelled"
CANCELLED_BODY = (
    "No disk was partitioned, formatted or written to. This computer is "
    "exactly as it was."
)

PLANNED_TITLE = "The plan checks out"
PLANNED_BODY = (
    "It was checked against the engine and not run. This session started in "
    "plan-only mode, so it cannot erase a disk however far you take it."
)

FAILURE_TITLE = "Install stopped"

#: The failure screen's remediations. There is deliberately no "try that step
#: again": the engine is a linear script with no entry point that starts at a
#: stage, so invoking it again runs ``wipefs`` again. There is also no "open a
#: shell", which the text installer offers and this one cannot - the image
#: carries no terminal emulator, and a button that does nothing on the screen
#: where the user is already stuck is worse than its absence.
FAILURE_ACTIONS: tuple[tuple[str, str], ...] = (
    ("export", "Save a report"),
    ("log", "See the full log"),
    ("reboot", "Restart"),
)


def encryption_questions_visible(encrypt_answer: str) -> bool:
    """Kept for symmetry with the shell rule, and never used to decide.

    The renderer asks the model with ``visible`` after any answer that could
    change which questions apply. This helper exists so a test can state the
    expectation in one place and compare it against what the model returns.
    """
    return encrypt_answer == "yes"
