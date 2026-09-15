"""Every command Files has, against every command this page has.

The list comes from `assets/files-commands.json`, which
`tools/extract_commands.py` generates from the reference source. Nothing here
is written down twice: regenerate that file and this number moves with it.

Run it:

    python3 tools/commands.py            # the summary and what is missing
    python3 tools/commands.py --all      # every command, with its state
    python3 tools/commands.py --json     # for another tool to read
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROTO = os.path.dirname(HERE)
REF = os.environ.get("FILES_REF", "/mnt/build/aurade-work/ref-files")
TABLE = os.path.join(PROTO, "assets", "files-commands.json")
#: The builder and its css/ and js/ files, read together.
sys.path.insert(0, PROTO)
import sources  # noqa: E402
BUILT = os.path.join(PROTO, "v3.html")

#: A class that is not a command. Files shares behaviour between commands
#: through abstract bases, and an interface file is not a command either.
NOT_A_COMMAND = re.compile(r"^(Base[A-Z]|I$|IToggle$|CloseTabBase$)")

#: The three that name a family rather than a command: Layout, Sort and Group
#: are folders of commands, and each has a file of the same name holding what
#: they share.
FAMILY = {"Layout", "Sort", "Group"}


def reference():
    """Every command Files has, as generated from its own source."""
    with open(TABLE, encoding="utf-8") as fh:
        return json.load(fh)["commands"]


def page_commands():
    """Every command the page offers, by the name it uses in the markup.

    Both the builder and what it built. Registrations are generated now, out
    of what each command says about itself, so a name like GroupByYear never
    appears in build_v3.py at all: it is computed and written into the page.
    Reading only the source reported seventeen of those as missing.
    """
    text = sources.text()
    if os.path.exists(BUILT):
        text += open(BUILT, encoding="utf-8").read()
    acts = set(re.findall(r'data-act="([^"]+)"', text))
    #: A command the live layer intercepts is offered whether or not a menu row
    #: carries it, and one listed as a live act is wired to the backend.
    live = set()
    block = re.search(r"const LIVE_ACTS = \[(.*?)\];", text, re.S)
    if block:
        live = set(re.findall(r"'([^']+)'", block.group(1)))
    #: The ones the static prototype answers itself, which is a command that
    #: works on the page and does not reach a backend.
    handled = set(re.findall(r"case '([a-z0-9-]+)':", text))
    #: And the registry. Not by matching the call: registrations are written
    #: as `cmd(...)`, as `cmdAct(...)`, as generated lines with the other
    #: quote character, and as arrays a `forEach` walks, and a regex that
    #: chases those spellings goes stale the next time one is added, quietly
    #: reporting a registered command as missing. A command's name appears in
    #: this file for exactly one reason, so a quoted occurrence of it is the
    #: thing being looked for.
    #:
    #: This makes the count a claim about the source rather than about the
    #: running page, which is why it is not the number that matters. The
    #: `commands-registered` gate in verify_all.py asks the live registry what
    #: it holds and fails the suite on the answer. This is the tool for
    #: finding what to write next.
    quoted = set(re.findall(r"""['"]([A-Za-z][A-Za-z0-9]{2,})['"]""", text))
    registered = quoted & set(reference())
    return acts, live, handled, registered


#: What each of Files' commands is called here, where the two names differ.
#: Written down because the names cannot be derived from one another, and kept
#: beside the list it maps so a rename shows up as a miss rather than silently.
SAME = {
    # FileSystem
    "CopyItem": "copy",
    "CutItem": "cut",
    "PasteItem": "paste",
    "PasteItemToSelection": "paste-folder",
    "DeleteItem": "trash",
    "DeleteItemPermanently": "delete",
    "Rename": "rename",
    "CreateFolder": "newfolder",
    "CreateFile": "newfile",
    "CreateShortcut": "newshortcut",
    "CreateShortcutFromDialog": "newshortcut",
    "CopyPath": "ctx-copypath",
    "CopyItemPath": "ctx-copypath",
    "FormatDrive": "format-drive",
    "FormatDriveFromHome": "format-drive",
    "FormatDriveFromSidebar": "format-drive",

    # Content
    "CompressIntoZip": "ctx-zip",
    "CompressIntoSevenZip": "compress-7z",
    "CompressIntoArchive": "compress",
    "DecompressArchive": "extract",
    "DecompressArchiveHere": "extract-here",
    "DecompressArchiveHereSmart": "extract-smart",
    "DecompressArchiveToChildFolder": "extract-child",
    "RotateLeft": "rotate-left",
    "RotateRight": "rotate-right",
    "RefreshItems": "ctx-refresh",
    "ShareItem": "share",
    "SelectAll": "sel-all",
    "ClearSelection": "sel-clear",
    "InvertSelection": "sel-inv",
    "RemoveTags": "ctx-tags",

    # Open
    "OpenItem": "ctx-open",
    "OpenProperties": "ctx-props",
    "OpenClassicProperties": "ctx-props",
    "OpenFileLocation": "ctx-openloc",
    "OpenStorageSense": "storage-sense",
    "OpenStorageSenseFromHome": "storage-sense",
    "OpenStorageSenseFromSidebar": "storage-sense",

    # Navigation
    "NavigateUp": "ctx-up",
    "OpenInNewTab": "ctx-opentab",
    "OpenInNewTabFromHome": "ctx-opentab",
    "OpenInNewTabFromSidebar": "ctx-opentab",
    "OpenInNewWindow": "ctx-openwin",
    "OpenInNewWindowFromHome": "ctx-openwin",
    "OpenInNewWindowFromSidebar": "ctx-openwin",
    "NewTab": "tab-new",
    "DuplicateSelectedTab": "tab-dup",
    "ReopenClosedTab": "tab-reopen",
    "CloseSelectedTab": "tab-close",
    "CloseOtherTabsSelected": "tab-close-others",
    "CloseTabsToTheLeftSelected": "tab-close-left",
    "CloseTabsToTheRightSelected": "tab-close-right",

    # Display
    "LayoutDetails": "lay-details",
    "LayoutList": "lay-list",
    "LayoutGrid": "lay-grid",
    "LayoutColumns": "lay-columns",
    "LayoutCards": "lay-cards",
    "LayoutAdaptive": "lay-adaptive",
    "LayoutIncreaseSize": "lay-grid-large",
    "LayoutDecreaseSize": "lay-grid-small",
    "SortByName": "sort-name",
    "SortByDateModified": "sort-date",
    "SortByDateCreated": "sort-created",
    "SortBySize": "sort-size",
    "SortByType": "sort-type",
    "SortAscending": "sort-asc",
    "SortDescending": "sort-desc",
    "GroupByNone": "group-none",
    "GroupByName": "group-name",
    "GroupByDateModified": "group-date",
    "GroupBySize": "group-size",
    "GroupByType": "group-type",

    # Sidebar and Global
    "PinFolderToSidebar": "ctx-pin",
    "Undo": "undo",
}


def main():
    ref = reference()
    acts, live, handled, registered = page_commands()
    have = acts | live | handled

    rows = []
    for command in sorted(ref):
        info = ref[command]
        mapped = SAME.get(command)
        if command in registered:
            state = "registered"
        elif mapped and mapped in live:
            state = "live"
        elif mapped and mapped in have:
            state = "page"
        else:
            state = "missing"
        rows.append({**info, "as": mapped, "state": state})

    if "--json" in sys.argv:
        json.dump(rows, sys.stdout, indent=2)
        print()
        return 0

    done = [r for r in rows if r["state"] != "missing"]
    gap = [r for r in rows if r["state"] == "missing"]
    if "--all" in sys.argv:
        for r in rows:
            keys = f"  [{r['hotkeys'][0]}]" if r["hotkeys"] else ""
            print(f"{r['state']:>11}  {r['category']:<11} {r['command']:<32}"
                  f"{r['label'] or ''}{keys}")
    else:
        by_area = {}
        for r in gap:
            by_area.setdefault(r["category"], []).append(r)
        for area in sorted(by_area):
            print(f"\n{area} ({len(by_area[area])} missing)")
            for r in sorted(by_area[area], key=lambda x: x["command"]):
                keys = f"  [{r['hotkeys'][0]}]" if r["hotkeys"] else ""
                print(f"  {r['command']:<34}{r['label'] or ''}{keys}")

    print(f"\n{len(done)} of {len(rows)} commands, {len(gap)} to go")
    print("the enforcing count is the commands-registered gate, "
          "which asks the running page")
    return 0


if __name__ == "__main__":
    sys.exit(main())
