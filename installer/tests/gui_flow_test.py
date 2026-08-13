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
    check(bool(page.subtitle), f"page {page.name} has no subtitle")
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
equal(nav.current_page, "graphics", "the first page is not the graphics check")
equal(nav.back_action(), "quit", "the first page offers back with nowhere to go")
equal(nav.back_label(), "Quit", "the first page's back label is not Quit")

nav.forward()
equal(nav.current_page, "network", "the second page is not the network check")
equal(nav.back_action(), "back", "a later page does not offer back")
equal(nav.back_label(), "Back", "a later page's back label is not Back")
nav.back()
equal(nav.current_page, "graphics", "back from the second page did not go back")

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
    {F.DONE, F.FAILURE},
    "the progress screen leads somewhere other than finished or failed",
)
equal(
    nav.reachable(F.PROGRESS),
    frozenset({F.PROGRESS, F.DONE, F.FAILURE}),
    "a screen upstream of the erase gate is reachable once installing has begun",
)

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


if FAILURES:
    for failure in FAILURES:
        print(f"test-gui-flow: {failure}", file=sys.stderr)
    sys.exit(1)
print("installer GUI flow test: PASS")
