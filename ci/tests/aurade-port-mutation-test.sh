#!/bin/bash
# Prove the port and session suite actually bites.
#
# Two patches shipped earlier in this project that compiled, passed a full
# mutation audit of their own assertions, and did nothing at all on the
# hardware. The lesson was not "write more tests", it was that a test which
# passes when you break the thing it names is not a test. So every assertion
# here is checked by breaking the code it covers and requiring the suite to
# fail, by name.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
CHROME_SRC="${CHROME_SRC:-${REPO}/chromium_dev/src}"
AURADE="${CHROME_SRC}/ui/file_manager/file_manager/aurade"

fail() { printf 'aurade port mutation test: %s\n' "$*" >&2; exit 1; }
[ -d "$AURADE" ] || fail "the aurade sources are not at $AURADE (set CHROME_SRC)"

AURADE="$AURADE" python3 - <<'PYEOF'
import os
import atexit
import signal
import subprocess
import sys

A = os.environ["AURADE"]

# suite, label, file, the code to break, what to replace it with, and the test
# that must then fail by name. The suite matters: keyboard, ARIA and recycling
# are invisible to the node suite, which has no DOM at all.
UNIT = ["bash", os.path.join(A, "tests/run.sh")]
DOM = ["python3", os.path.join(A, "tests/harness/dom.py")]

MUTATIONS = [
    (UNIT, "the session drops its buffered replay, reopening the list/watch race",
     "session/navigation_session.ts",
     """      listed = true;
      for (const event of buffered) {
        if (event.revision > this.revision) {
          this.applyChange(event);
        }
      }""",
     "      listed = true;",
     "a change that lands during the listing is not lost"),

    (UNIT, "the session stops cancelling the navigation it is replacing",
     "session/navigation_session.ts",
     "    this.controller?.abort();\n    const controller = new AbortController();",
     "    const controller = new AbortController();",
     "navigating again abandons the first listing"),

    (UNIT, "the session stops pruning the selection when an entry is removed",
     "session/navigation_session.ts",
     """        for (const key of gone) {
          this.selection.delete(key);
        }""",
     "        void gone;",
     "a removed entry drops out of the selection"),

    (UNIT, "a range selection collapses to the single item clicked",
     "session/navigation_session.ts",
     """        this.selection = new Set(
            this.entries.slice(lo, hi + 1).map(entry => entry.key));""",
     "        this.selection = new Set([key]);",
     "a range selection is resolved over indices"),

    (UNIT, "the backend stops honouring the abort signal while listing",
     "port/mock_backend.ts",
     """      if (options.signal?.aborted) {
        return;
      }
      const slice = all.slice(i, i + size);""",
     "      const slice = all.slice(i, i + size);",
     "stops listing when the caller aborts"),

    (UNIT, "the backend stops advancing the revision when something changes",
     "port/mock_backend.ts",
     """  private bump(key: FileKey): number {
    const next = (this.revisions.get(key) ?? 1) + 1;""",
     """  private bump(key: FileKey): number {
    const next = (this.revisions.get(key) ?? 1);""",
     "the revision advances between a listing and a later change"),

    (UNIT, "the backend returns every metadata field regardless of the request",
     "port/mock_backend.ts",
     """      const picked: Record<string, unknown> = {};
      for (const field of fields) {
        if (field in node.metadata) {
          picked[field] = (node.metadata as Record<string, unknown>)[field];
        }
      }
      out.set(key, picked as Metadata);""",
     "      void fields;\n      out.set(key, {...node.metadata, mimeType: 'text/plain'});",
     "returns metadata in one batch, limited to the fields asked for"),
]

DOM_MUTATIONS = [
    (DOM, "the list stops telling a screen reader how many items there are",
     "ui/file_list.ts",
     "    this.viewport.setAttribute('aria-setsize', String(entries.length));",
     "",
     "the list tells a screen reader what it is and how big it is"),

    (DOM, "rows stop carrying a position, so \"item 4 of 20\" becomes nothing",
     "ui/file_list.ts",
     "      row.setAttribute('aria-posinset', String(index + 1));",
     "",
     "the list tells a screen reader what it is and how big it is"),

    (DOM, "a row's accessible name falls back to its columns",
     "ui/file_row.ts",
     """  row.setAttribute(
      'aria-label',""",
     """  row.setAttribute(
      'data-aurade-unused-label',""",
     "every row carries a name that reads as a sentence, not as cells"),

    (DOM, "shift and an arrow moves the selection instead of extending it",
     "ui/file_list.ts",
     "    this.selectIndex(next, extend ? 'range' : 'replace');",
     "    this.selectIndex(next, 'replace');",
     "shift and an arrow extends the selection rather than moving it"),

    (DOM, "control A selects only what happens to be rendered",
     "ui/file_list.ts",
     """    for (let i = 0; i < this.entries.length; i++) {
      this.selection.add(i);
    }""",
     """    for (let i = 0; i < Math.min(this.entries.length, 12); i++) {
      this.selection.add(i);
    }""",
     "control A selects everything, including what is not rendered"),

    (DOM, "page keys move by one row rather than by a viewport",
     "ui/file_list.ts",
     "    const page = Math.max(1, Math.floor(this.viewport.clientHeight / this.rowHeight) - 1);",
     "    const page = 1;",
     "page keys move by a viewport rather than by one"),

    (DOM, "rows are appended rather than recycled",
     "ui/file_list.ts",
     """    while (this.pool.length > count) {
      this.pool.pop()!.remove();
    }""",
     "",
     "a short directory after a long one leaves no rows behind"),

    (DOM, "the empty state stops saying which emptiness this is",
     "ui/file_list.ts",
     "    const copy = emptyCopy(this.emptyReason, this.emptySubject);",
     "    const copy = {title: 'No files.', detail: undefined};",
     "the empty state replaces the rows and is announced"),
]


# The sidebar is our own markup rather than a shadow tree we style from
# outside, which is the whole reason its selected state can be asserted at all.
# These are the ways it would quietly stop being usable.
SIDEBAR_MUTATIONS = [
    (DOM, "the sidebar landmark loses its name",
     "ui/sidebar.ts",
     "    this.nav.setAttribute('aria-label', 'Places');\n",
     "",
     "the sidebar is a navigation landmark with a name"),

    (DOM, "a group of places is no longer tied to its heading",
     "ui/sidebar.ts",
     "      list.setAttribute('aria-labelledby', id);\n",
     "",
     "each group is a list that says which group it is"),

    (DOM, "a drive you can pull out is filed with the ones you cannot",
     "ui/sidebar.ts",
     """    const fixed = volumes.filter(place => !place.volume?.removable);
    const removable = volumes.filter(place => place.volume?.removable);""",
     """    const fixed = volumes;
    const removable: Place[] = [];""",
     "removable media is separated from what is bolted in"),

    (DOM, "changing where you are does not redraw where you are",
     "ui/sidebar.ts",
     """    this.selected = key;
    this.render();""",
     "    this.selected = key;",
     "where you are is announced as current"),

    (DOM, "arrowing past the last place wraps to the first",
     "ui/sidebar.ts",
     "      case 'ArrowDown': next = at < 0 ? 0 : Math.min(buttons.length - 1, at + 1); break;",
     "      case 'ArrowDown': next = at < 0 ? 0 : (at + 1) % buttons.length; break;",
     "arrow keys stop at the ends rather than wrapping"),

    (DOM, "every place becomes its own tab stop",
     "ui/sidebar.ts",
     "    button.tabIndex = place === this.tabStop() ? 0 : -1;",
     "    button.tabIndex = 0;",
     "tab reaches the sidebar once, not once per place"),

    (DOM, "free space is left to the bar alone",
     "ui/sidebar.ts",
     """      text.textContent =
          `${formatSize(capacity.free)} free of ${formatSize(capacity.total)}`;""",
     "      text.textContent = '';",
     "capacity is a sentence, not only a bar"),

    (DOM, "the capacity bar is read out as well as the sentence",
     "ui/sidebar.ts",
     "      bar.setAttribute('aria-hidden', 'true');\n",
     "",
     "the bar is not read out twice"),

    (DOM, "a drive with no room left looks like one with plenty",
     "ui/sidebar.ts",
     "      if (used >= 0.98) {",
     "      if (used >= 1.5) {",
     "a drive with no room left says so in colour as well as words"),

    (DOM, "a count of one is announced as items",
     "ui/sidebar.ts",
     "          `${place.label}, ${place.badge} ${place.badge === 1 ? 'item' : 'items'}`);",
     "          `${place.label}, ${place.badge} items`);",
     "one gathered item is not"),

    (DOM, "an empty basket is drawn as a zero",
     "ui/sidebar.ts",
     "    if (place.badge !== undefined && place.badge > 0) {",
     "    if (place.badge !== undefined) {",
     "an empty basket shows no badge at all"),

    (DOM, "a drive label is parsed as markup",
     "ui/sidebar.ts",
     "    label.textContent = place.label;",
     "    label.innerHTML = place.label;",
     "a drive named by its owner cannot inject markup"),
    (DOM, "the sidebar drops out of the tab order when nothing is current",
     "ui/sidebar.ts",
     """    return this.places.find(place => place.key === this.selected) ??
        this.places[0];""",
     "    return this.places.find(place => place.key === this.selected);",
     "the sidebar stays reachable when you are somewhere it does not list"),

    (DOM, "two sidebars emit the same heading ids",
     "ui/sidebar.ts",
     """      const id = `aurade-group-${this.instance}-` +
          group.title.replace(/\\s+/g, '-').toLowerCase();""",
     """      const id = 'aurade-group-' +
          group.title.replace(/\\s+/g, '-').toLowerCase();""",
     "two sidebars on one page do not share heading ids"),]


# The shell is the first thing that talks to the port rather than being handed
# data, so these are the ways the seam stops holding.
SHELL_MUTATIONS = [
    (UNIT, "the window opens on whatever the backend listed first",
     "ui/places.ts",
     """  return places.find(place => place.kind === 'volume') ??
      places.find(place => place.kind === 'network') ?? places[0];""",
     "  return places[0];",
     "the window opens on a drive, not on Recent"),

    (UNIT, "a cloud mount is filed as a disk in the machine",
     "ui/places.ts",
     "const ELSEWHERE = new Set(['drive', 'provided', 'android', 'crostini']);",
     "const ELSEWHERE = new Set<string>([]);",
     "a cloud, a phone and a container are not this computer"),

    (UNIT, "a basket is offered whether or not there is one",
     "ui/places.ts",
     "  if (basketCount !== undefined && basketKey !== undefined) {",
     "  if (basketKey !== undefined) {",
     "the basket appears only when there is one"),

    (UNIT, "the mapping throws the capacity away",
     "ui/places.ts",
     """    kind: placeKindFor(volume),
    volume,
  }));""",
     """    kind: placeKindFor(volume),
  }));""",
     "the capacity survives the mapping"),

    (DOM, "metadata is fetched for the directory rather than the screen",
     "ui/shell.ts",
     "    const wanted = this.entries.slice(first, first + count)",
     "    const wanted = this.entries.slice(0)",
     "a huge directory does not stat every entry to fill one screen"),

    (DOM, "a window that cannot read its places comes up blank and silent",
     "ui/shell.ts",
     """      this.say('The places on this computer could not be read.');
      return;""",
     "      return;",
     "places that cannot be read say so instead of a blank frame"),

    (DOM, "a folder that was refused is reported as empty",
     "ui/shell.ts",
     "  return error.code === 'not-found' ? 'gone' : 'unreadable';",
     "  return 'empty';",
     "a folder that cannot be read does not claim to be empty"),

    (DOM, "the marker claims you are at the drive from three folders down",
     "ui/shell.ts",
     "    this.sidebar.setSelected(trail.length === 1 ? here.key : null);",
     "    this.sidebar.setSelected(trail[0]!.key);",
     "opening a folder takes the marker off the drive you left"),

    (DOM, "nothing in the sidebar is ever marked",
     "ui/shell.ts",
     "    this.sidebar.setSelected(trail.length === 1 ? here.key : null);",
     "    this.sidebar.setSelected(null);",
     "choosing a place shows what is in it"),

    (DOM, "a mild notice interrupts the screen reader",
     "ui/shell.ts",
     "    this.notice.setAttribute('role', 'status');",
     "    this.notice.setAttribute('role', 'alert');",
     "the notice is announced without interrupting"),

    (DOM, "somebody elses drive is filed under this computer",
     "ui/sidebar.ts",
     """    if (elsewhere.length) {
      out.push({title: 'Elsewhere', places: elsewhere});
    }""",
     "",
     "somebody elses drive is not filed as part of this computer"),

    (DOM, "the empty state cannot be hidden again",
     "ui/tokens.css",
     ".aurade-empty[hidden] { display: none; }\n",
     "",
     "a folder with files in it does not also say it is empty"),
]


# Back, forward, up, and the way sideways.
TOOLBAR_MUTATIONS = [
    (UNIT, "going somewhere new keeps the branch you left",
     "ui/history.ts",
     "    this.entries.length = this.index + 1;\n",
     "",
     "going somewhere new discards the branch you left"),

    (UNIT, "arriving where you already are counts as a step",
     "ui/history.ts",
     """    if (here && here.length === trail.length &&
        here[here.length - 1]!.key === trail[trail.length - 1]!.key) {""",
     "    if (false) {",
     "arriving where you already are is not a step"),

    (UNIT, "up walks off the top of a root",
     "ui/history.ts",
     "    return trail.length > 1 ? trail.slice(0, -1) : null;",
     "    return trail.slice(0, -1);",
     "up removes the last step and stops at a root"),

    (UNIT, "clicking a crumb lands one level short of it",
     "ui/history.ts",
     "    return trail.slice(0, level + 1);",
     "    return trail.slice(0, level);",
     "clicking a crumb cuts the trail there"),

    (UNIT, "a sibling is appended as a child",
     "ui/history.ts",
     "    return [...trail.slice(0, -1), visit];",
     "    return [...trail, visit];",
     "stepping sideways replaces the last step rather than adding one"),

    (DOM, "the deepest folder gets no chevron of its own",
     "ui/path_bar.ts",
     """    if (this.trail.length) {
      this.list.appendChild(this.renderChevron(this.trail.length - 1));
    }""",
     "",
     "a chevron says which folder it is about to list"),

    (DOM, "an open chevron is not announced as open",
     "ui/path_bar.ts",
     "    chevron.setAttribute('aria-expanded', 'true');\n",
     "",
     "a chevron lists what else is in that folder"),

    (DOM, "the popover offers files as places to go",
     "ui/shell.ts",
     """        if (entry.isDirectory) {
          found.push({key: entry.key, label: entry.name});
        }""",
     "        found.push({key: entry.key, label: entry.name});",
     "a chevron lists what else is in that folder"),

    (DOM, "a sibling is opened as a child of where you are",
     "ui/path_bar.ts",
     "    const base = History.truncate(this.trail, level);",
     "    const base = this.trail;",
     "choosing a sibling steps sideways rather than deeper"),

    (DOM, "escape drops focus on the document",
     "ui/path_bar.ts",
     "    chevron?.focus();\n",
     "",
     "escape closes the popover and gives focus back"),

    (DOM, "a popover with nothing in it opens blank",
     "ui/path_bar.ts",
     "      message.textContent = 'No other folders here.';",
     "      message.textContent = '';",
     "a folder with nothing beside it says so rather than opening empty"),

    (DOM, "the crumb you are standing on is not marked",
     "ui/path_bar.ts",
     "      button.setAttribute('aria-current', 'page');\n",
     "",
     "the crumb you are standing on is not a link to elsewhere"),

    (DOM, "up is offered from the root of a drive",
     "ui/shell.ts",
     "      up: this.trail.length > 1,",
     "      up: true,",
     "there is nowhere to go back to when the window opens"),

    # Deliberately absent: replacing step() with go(). It is an equivalent
    # mutant. NavigationSession's history refuses to record a trail ending
    # where you already are, so recording during a back is a no op and no test
    # can tell the two apart. Excluded rather than left escaping, because an
    # escape should always mean a test is missing.

    (DOM, "the toolbar buttons are pictures with no names",
     "ui/toolbar.ts",
     "  element.setAttribute('aria-label', label);\n",
     "",
     "the glyph buttons have names, not just pictures"),

    (DOM, "the popover goes back inside the path bar, which clips",
     "ui/tokens.css",
     """.aurade-toolbar {
  align-items: center;
  /* The containing block for a sibling popover, which cannot live inside the
     path bar because that clips. */
  position: relative;""",
     """.aurade-toolbar {
  align-items: center;""",
     "the popover is actually on screen and not clipped away"),
]

MUTATIONS = MUTATIONS + DOM_MUTATIONS + SIDEBAR_MUTATIONS + SHELL_MUTATIONS + TOOLBAR_MUTATIONS

# Every anchor is checked before anything is touched. A run that is killed
# rather than returned from skips the finally below and leaves a mutation in
# the tree, and the next run then measures already broken source: the page key
# mutation did exactly that, and reported itself and its neighbour as escapes
# rather than as the dirty tree it was. Failing loudly here turns a silent
# wrong answer into a refusal.
dirty = []
for _, label, relative, old, _, _ in MUTATIONS:
    hits = open(os.path.join(A, relative)).read().count(old)
    if hits != 1:
        dirty.append("  %-60s anchor found %d times in %s" % (label, hits, relative))
if dirty:
    print("aurade port mutation test: the tree is not in a state worth mutating.")
    print("\n".join(dirty))
    print("An anchor that is missing usually means a killed run left its "
          "mutation behind. Check the file before trusting any earlier result.")
    sys.exit(1)

# A SIGTERM, the usual way a run this long gets stopped, would otherwise skip
# the restore for whichever mutation is live at the time.
in_flight = {}


def restore_all(*_):
    for path, text in in_flight.items():
        open(path, "w").write(text)
    in_flight.clear()


atexit.register(restore_all)
for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
    signal.signal(sig, lambda *_: (restore_all(), sys.exit(2)))

caught = 0
escaped = []
for suite, label, relative, old, new, expected in MUTATIONS:
    path = os.path.join(A, relative)
    original = open(path).read()
    in_flight[path] = original
    open(path, "w").write(original.replace(old, new, 1))
    try:
        run = subprocess.run(suite, capture_output=True, text=True,
                             timeout=300)
        output = run.stdout + run.stderr
        if run.returncode != 0 and expected in output:
            print("  caught      %s" % label)
            caught += 1
        elif run.returncode != 0:
            escaped.append("%s: the suite failed, but not via '%s'"
                           % (label, expected))
        else:
            escaped.append("%s: NOT CAUGHT" % label)
    finally:
        open(path, "w").write(original)
        in_flight.pop(path, None)

for line in escaped:
    print("  escaped     %s" % line)
print("aurade port mutation test: %d caught, %d escaped"
      % (caught, len(escaped)))
sys.exit(1 if escaped else 0)
PYEOF
rc=$?
[ "$rc" -eq 0 ] || fail "a mutation went uncaught"
echo "aurade port mutation test: PASS"
