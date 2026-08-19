"""The graphical flow's rules, checked without a display.

Three properties are worth more than the rest and each is asserted by
construction rather than by reading the source:

  every question in the shared manifest is on exactly one page, so a question
  added to the manifest cannot be silently dropped by the renderer that was
  supposed to ask it;

  a plan-only session cannot reach the erase gate - not "checks a flag before
  erasing", but has no path through the transition graph that arrives there;

  every back control's label is produced by the same call that decides what it
  does, so a button saying "Back" on a screen that quits is not expressible.

The manifest half of the first property needs the shell, so it is checked in
gui_bridge_test.py where a model process is running. Here the page table is
checked against itself: no duplicates, no unknown ids, no empty pages.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "lib"))

from aurade_gui import flow as F  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def equal(got: object, want: object, message: str) -> None:
    if got != want:
        FAILURES.append(f"{message}: expected {want!r}, got {got!r}")


# -- pages -------------------------------------------------------------------

seen: dict[str, str] = {}
for page in F.PAGES:
    check(bool(page.title), f"page {page.name} has no title")
    # A subtitle is optional and an empty one is a decision, not an omission:
    # the readiness page's verdict says the same sentence louder, one line
    # further down, and saying it twice before saying anything is how a page
    # stops being read. What is not optional is that a page says something.
    check(page.subtitle != page.title,
          f"page {page.name} repeats its title as its subtitle")
    for question in page.questions:
        check(
            question not in seen,
            f"question {question} appears on both {seen.get(question)} and {page.name}",
        )
        seen[question] = page.name

equal(len(F.PAGE_ORDER), len(set(F.PAGE_ORDER)), "page names are not unique")
equal(
    F.page_for_question("target").name if F.page_for_question("target") else None,
    "disk",
    "the disk question is not on the disk page",
)
check(F.page_for_question("nonexistent") is None, "an unknown question found a page")

# The advanced page is the only optional one, and it must stay optional: the
# whole reason advanced questions may be skipped is that every one of them has
# a working default.
optional = [page.name for page in F.PAGES if page.optional]
equal(optional, ["advanced"], "the set of optional pages changed")


# -- reachability ------------------------------------------------------------

full = F.Flow(plan_only=False)
reachable_full = full.reachable()
for state in (F.GATE, F.PROGRESS, F.DONE):
    check(state in reachable_full, f"a normal session cannot reach {state}")

planning = F.Flow(plan_only=True)
reachable_plan = planning.reachable()
for state in sorted(F.DESTRUCTIVE):
    check(
        state not in reachable_plan,
        f"a plan-only session can reach {state}: {sorted(reachable_plan)}",
    )
check(F.PLANNED in reachable_plan, "a plan-only session cannot reach the planned state")
equal(planning.transitions(F.PLANNED), (), "the planned state has an exit")

# The same property stated the other way: the one call that starts an erase
# refuses outright in a plan-only session, wherever it is called from.
planning.state = F.GATE
try:
    planning.confirmed()
except RuntimeError:
    pass
else:
    FAILURES.append("a plan-only session confirmed an erase")

# And in a normal session it refuses from anywhere except the gate.
walk = F.Flow(plan_only=False)
walk.state = F.REVIEW
try:
    walk.confirmed()
except RuntimeError:
    pass
else:
    FAILURES.append("an erase was confirmed from the review screen")


# -- navigation truthfulness -------------------------------------------------

nav = F.Flow(plan_only=False)
equal(nav.state, F.WELCOME, "the flow did not start at the welcome screen")
equal(nav.back_action(), "quit", "the welcome screen offers something other than quit")
equal(nav.back_label(), "Quit", "the welcome screen's back label is not Quit")

nav.forward()
equal(nav.state, "pages", "the welcome screen did not lead to the pages")
equal(nav.current_page, "readiness",
      "the first page is not the readiness check")
equal(nav.back_action(), "quit", "the first page offers back with nowhere to go")
equal(nav.back_label(), "Quit", "the first page's back label is not Quit")

nav.forward()
equal(nav.current_page, "network", "the second page is not the network check")
equal(nav.back_action(), "back", "a later page does not offer back")
equal(nav.back_label(), "Back", "a later page's back label is not Back")
nav.back()
equal(nav.current_page, "readiness",
      "back from the second page did not go back")

# Walking to the end of the pages reaches review; back from review reopens the
# last page rather than the first.
while nav.state == "pages":
    nav.forward()
equal(nav.state, F.REVIEW, "walking the pages did not reach review")
equal(nav.forward_label(), "Continue", "the review screen's button is mislabelled")
nav.back()
equal(nav.state, "pages", "back from review left the pages")
equal(nav.current_page, F.PAGES[-2].name, "back from review did not reopen the last page")

nav.state = F.GATE
equal(nav.back_action(), "back", "the erase gate does not offer a way back")
equal(nav.forward_label(), "Erase and install", "the gate's button is mislabelled")
nav.back()
equal(nav.state, F.REVIEW, "back from the erase gate did not return to review")

# The progress screen offers nothing, because nothing is read there. A cancel
# control after the erase gate would advertise an exit that does not exist.
nav.state = F.PROGRESS
equal(nav.back_action(), "", "the progress screen offers a back control")
equal(nav.forward_label(), "", "the progress screen offers a forward control")
equal(nav.cancel(), F.PROGRESS, "the progress screen could be cancelled")

# Stated as a graph property as well as a label one, because "no cancel after
# the erase gate" is really "nothing downstream of the gate leads back to a
# screen that says nothing was written".
equal(
    set(nav.transitions(F.PROGRESS)),
    {F.DONE, F.FAILURE, F.STOPPED},
    "the progress screen leads somewhere other than finished, failed or stopped",
)
equal(
    nav.reachable(F.PROGRESS),
    frozenset({F.PROGRESS, F.DONE, F.FAILURE, F.STOPPED}),
    "a screen upstream of the erase gate is reachable once installing has begun",
)

# Stopping is an outcome, not a failure. A run the user ended on purpose gets
# its own screen, and only when the engine reported that as the cause.
end = F.Flow(plan_only=False)
end.state = F.PROGRESS
equal(end.finished(143, "cancelled"), F.STOPPED, "a stopped run was called a failure")
end.state = F.PROGRESS
equal(end.finished(1, "unexpected_exit"), F.FAILURE, "a crash was called a stop")
end.state = F.PROGRESS
equal(end.finished(0), F.DONE, "a clean install did not finish")
end.state = F.PROGRESS
equal(end.finished(0, "cancelled"), F.DONE, "a clean install was called a stop")

for terminal in sorted(F.TERMINAL):
    end = F.Flow()
    end.state = terminal
    equal(end.back_action(), "", f"the {terminal} screen offers a back control")
    equal(end.transitions(), (), f"the {terminal} screen has an exit")
    equal(end.cancel(), terminal, f"the {terminal} screen could be cancelled")


# -- the advanced page -------------------------------------------------------

adv = F.Flow(plan_only=False)
check("advanced" not in adv.pages, "the advanced page is shown before it is asked for")
adv.begin()
adv.page_index = adv.pages.index("encryption")
adv.set_show_advanced(True)
check("advanced" in adv.pages, "opening advanced options did not add the page")
equal(
    adv.current_page,
    "encryption",
    "opening advanced options moved the user off the page they were on",
)

# Turning it back off must not strand the flow past the end of the list.
adv.page_index = adv.pages.index("advanced")
adv.set_show_advanced(False)
check(adv.current_page in adv.pages, "hiding the advanced page left an invalid page")


# -- jumping straight to an answer from the review screen --------------------
#
# Walking back through four pages to fix one typo is how people talk
# themselves into accepting a wrong answer, so every review row goes directly
# to the page that set it.

jump = F.Flow(plan_only=False)
jump.begin()
jump.state = F.REVIEW
equal(jump.jump_to_page("account"), "pages", "a review row did not open a page")
equal(jump.current_page, "account", "a review row opened the wrong page")
equal(jump.back_action(), "back", "a jumped-to page offers no way back")

# An advanced row is reachable even though the advanced page is not in the
# walk until it has been asked for.
jump.state = F.REVIEW
jump.set_show_advanced(False)
check("advanced" not in jump.pages, "the advanced page is shown unasked")
jump.jump_to_page("advanced")
equal(jump.current_page, "advanced", "an advanced review row could not be opened")
check("advanced" in jump.pages, "jumping to advanced did not reveal the page")

jump.state = F.REVIEW
equal(jump.jump_to_page("nonexistent"), F.REVIEW, "an unknown page was opened")


# -- plan-only labels --------------------------------------------------------

po = F.Flow(plan_only=True)
po.state = F.REVIEW
equal(po.forward_label(), "Check the plan", "plan-only mode promises an install")
equal(po.forward(), F.PLANNED, "plan-only review did not lead to the planned state")


# -- failure actions ---------------------------------------------------------

keys = [key for key, _ in F.FAILURE_ACTIONS]
equal(len(keys), len(set(keys)), "a failure action is listed twice")
check("retry" not in keys, "the failure screen offers a retry that would erase again")
check("shell" not in keys, "the failure screen offers a shell the image cannot open")
check("export" in keys, "the failure screen cannot save a diagnostic report")


# --- what counts as having started ------------------------------------------
#
# The launcher stops trying other ways to draw the moment the front end reports
# `engaged`, because after that there are answers on screen that restarting
# would throw away. Every state has that property except the one where nothing
# has been done yet.
#
# This is worth a test of its own because getting it wrong is silent and
# expensive. Reporting on the welcome screen made the first Continue the end of
# the renderer chain, and leaving the welcome screen is the first animation the
# process draws, so a graphics stack that takes the process down there put the
# user on a console one keypress in with three untried candidates left.
check(not F.engages(F.WELCOME),
      "leaving the welcome screen is treated as a commitment, and nothing has been answered on it")
for _state in ("pages", F.REVIEW, F.GATE, F.PROGRESS):
    check(F.engages(_state),
          f"leaving {_state} is not treated as a commitment, and a restart there would discard answers")

if FAILURES:
    for failure in FAILURES:
        print(f"test-gui-flow: {failure}", file=sys.stderr)
    sys.exit(1)
print("installer GUI flow test: PASS")
