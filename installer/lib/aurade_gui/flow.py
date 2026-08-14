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
        name="graphics",
        title="Checking this computer",
        subtitle=(
            "AuraDE's desktop needs working graphics. This check runs now, "
            "while the disk is still untouched."
        ),
    ),
    Page(
        name="network",
        title="Checking the network",
        subtitle=(
            "Packages are downloaded and verified before anything is written "
            "to the disk, so the connection is checked first."
        ),
    ),
    Page(
        name="language",
        title="Language and keyboard",
        subtitle="These take effect immediately, before you type a password.",
        questions=("locale", "keymap", "timezone"),
    ),
    Page(
        name="disk",
        title="Choose a disk",
        subtitle=(
            "Choose the destination for AuraDE. The erase warning appears "
            "before anything can change."
        ),
        questions=("target",),
    ),
    Page(
        name="account",
        title="Create your account",
        subtitle="Set the computer name and the account you will use to sign in.",
        questions=("hostname", "username", "password"),
    ),
    Page(
        name="encryption",
        title="Disk encryption",
        subtitle="Decide how the installed system protects data at rest.",
        questions=("encrypt", "luks_passphrase"),
    ),
    Page(
        name="advanced",
        title="Advanced options",
        subtitle=(
            "Defaults that work. Change these only if you know why you are "
            "changing them."
        ),
        questions=("snapshot", "repo_url"),
        optional=True,
    ),
)

PAGES_BY_NAME: dict[str, Page] = {page.name: page for page in PAGES}

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
PLANNED = "planned"

#: States that end the session. None of them offers a way back into the flow.
TERMINAL: frozenset[str] = frozenset({DONE, FAILURE, CANCELLED, PLANNED})

#: States that must not be reachable when the installer was started with
#: ``--plan-only``. Asserted by walking the transition graph, not by reading
#: the source: the property that matters is unreachability, and a flag tested
#: in the right place today is one edit away from being tested in the wrong
#: place tomorrow.
DESTRUCTIVE: frozenset[str] = frozenset({GATE, PROGRESS, DONE})


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
            return (DONE, FAILURE)
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

    def finished(self, status: int) -> str:
        self.state = DONE if status == 0 else FAILURE
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
        return ""

    def step_position(self) -> str:
        if self.state != "pages" or not self._visible_pages:
            return ""
        return f"Step {self.page_index + 1} of {len(self._visible_pages)}"


# --------------------------------------------------------------------------
# Wording that has to be exactly right
# --------------------------------------------------------------------------

WELCOME_TITLE = "Install AuraDE"
WELCOME_BODY = (
    "This installs AuraDE on this computer. You will choose a disk, create "
    "an account, and confirm before anything is erased."
)
WELCOME_ASSURANCE = "Nothing is written to any disk until you confirm."

REVIEW_TITLE = "Review"
REVIEW_ASSURANCE = "Nothing has been written to any disk yet."

GATE_TITLE = "Confirm erase"
GATE_BODY = (
    "Everything before this point can be undone. Nothing after it can. The "
    "packages are already downloaded and verified, so the installation will "
    "not need the network again."
)

PROGRESS_TITLE = "Installing"
PROGRESS_FOOTER = "Do not turn off this computer."
PROGRESS_UNINTERRUPTIBLE = "This part cannot be interrupted safely."

DONE_TITLE = "AuraDE is installed"
DONE_BODY = (
    "Remove the installation media and restart. Sign in with the username "
    "and password you chose."
)
DONE_ENCRYPTED = (
    "This disk is encrypted. You will be asked for the disk passphrase each "
    "time the computer starts, before the sign-in screen appears."
)

CANCELLED_TITLE = "Cancelled"
CANCELLED_BODY = (
    "No disk was partitioned, formatted or written to. This computer is "
    "exactly as it was before the installer started."
)

PLANNED_TITLE = "Plan checked"
PLANNED_BODY = (
    "The installer checked this plan against the engine and did not run it. "
    "This session was started in plan-only mode and cannot erase a disk."
)

FAILURE_TITLE = "Install stopped"

#: The failure screen's remediations. There is deliberately no "try that step
#: again": the engine is a linear script with no entry point that starts at a
#: stage, so invoking it again runs ``wipefs`` again. There is also no "open a
#: shell", which the text installer offers and this one cannot - the image
#: carries no terminal emulator, and a button that does nothing on the screen
#: where the user is already stuck is worse than its absence.
FAILURE_ACTIONS: tuple[tuple[str, str], ...] = (
    ("export", "Save a diagnostic report"),
    ("log", "View the full log"),
    ("reboot", "Restart the computer"),
)


def encryption_questions_visible(encrypt_answer: str) -> bool:
    """Kept for symmetry with the shell rule, and never used to decide.

    The renderer asks the model with ``visible`` after any answer that could
    change which questions apply. This helper exists so a test can state the
    expectation in one place and compare it against what the model returns.
    """
    return encrypt_answer == "yes"
