"""Every row Files puts in a context menu, against every row this page puts there.

The list comes from `assets/files-menus.json`, which `tools/extract_menus.py`
generates from `ContentPageContextFlyoutFactory.cs`. Nothing here is written
down twice: regenerate that file and this moves with it.

    python3 tools/menus.py            # the two menus, side by side
    python3 tools/menus.py --tree     # the reference's list, as it nests

The enforcing count is the pair of gates in verify_all.py that read the
rendered menus out of a real browser. This is the tool for reading them.
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROTO = os.path.dirname(HERE)
TABLE = os.path.join(PROTO, "assets", "files-menus.json")
BUILT = os.path.join(PROTO, "v3.html")


def table():
    with open(TABLE, encoding="utf-8") as fh:
        return json.load(fh)["menus"]


def on_side(row, side):
    return side is None or row.get("side", "both") in (side, "both")


def wanted(rows, side, top=True):
    """Every command the reference puts in one menu, in the order it puts them."""
    out = []
    if top:
        out = [r["command"] for r in rows if r.get("primary") and on_side(r, side)]
    for row in rows:
        if not on_side(row, side) or row.get("separator"):
            continue
        if top and row.get("primary"):
            continue
        if row.get("command") and not row.get("items"):
            out.append(row["command"])
        out += wanted(row.get("items") or [], side, False)
    return out


def slice_of(menu_id):
    """The markup of one menu, out of the built page."""
    if not os.path.exists(BUILT):
        return None
    page = open(BUILT, encoding="utf-8").read()
    at = page.index(f'id="{menu_id}"')
    depth, i = 0, page.index(">", at) + 1
    start = i
    while True:
        found = re.compile(r"</?div\b").search(page, i)
        if not found:
            break
        depth += 1 if found.group(0) == "<div" else -1
        i = found.end()
        if depth < 0:
            break
    return page[start:i]


def built(menu_id):
    """Every command the built page put in one menu, in the order it put them."""
    html = slice_of(menu_id)
    return None if html is None else re.findall(r'data-command="([^"]+)"', html)


def captions(menu_id):
    """Every caption the built page shows in one menu, in order."""
    html = slice_of(menu_id)
    return [] if html is None else re.findall(r'<span class="mi-t">([^<]*)</span>',
                                              html)


def tree(rows, side, depth=0):
    for row in rows:
        if not on_side(row, side):
            continue
        if row.get("separator"):
            name = "-" * 20
        elif row.get("placeholder") or row.get("tag"):
            name = f"[{row.get('tag') or 'shell'}] {row.get('label') or ''}"
        else:
            name = row.get("command") or f'"{row.get("label")}"'
        mark = " *" if row.get("primary") else ""
        print(f"{'  ' * depth}{name}{mark}")
        tree(row.get("items") or [], side, depth + 1)


#: Which of the reference's menus each of this page's menus is, and which
#: side of the content page's one list it takes. All nine of them, in the
#: order the table holds them.
DRAWN = [
    ("ctx-file", "content", "item"),
    ("ctx-bg", "content", "background"),
    ("ctx-drive", "drive", None),
    ("ctx-qa", "quickaccess", None),
    ("ctx-recent", "recent", None),
    ("ctx-filetags", "filetags", None),
    ("ctx-network", "network", None),
    ("ctx-side", "sidebar", None),
    ("ctx-home", "home", None),
    ("ctx-tab", "tab", None),
]


def main():
    menus = table()
    if "--tree" in sys.argv:
        for menu, key, side in DRAWN:
            print(f"\n=== #{menu} ({key}{'' if side is None else ' ' + side}) ===")
            tree(menus[key], side)
        return 0

    for menu, key, side in DRAWN:
        rows = menus[key]
        want, got = wanted(rows, side), built(menu)
        print(f"\n#{menu}: {len(want)} commands in the reference")
        if got is None:
            print("  no v3.html yet: run python3 build_v3.py")
            continue
        if got == want:
            print(f"  the page has the same {len(got)}, in the same order")
            continue
        missing = [c for c in want if c not in got]
        extra = [c for c in got if c not in want]
        print(f"  the page has {len(got)}")
        if missing:
            print(f"  missing: {', '.join(missing)}")
        if extra:
            print(f"  not in the reference: {', '.join(extra)}")
        if not missing and not extra:
            print("  the same commands, in a different order")
    absent = [k for k in table() if k not in {key for _m, key, _s in DRAWN}]
    if absent:
        print(f"\nin the reference and not drawn here: {', '.join(absent)}"
              " (no card to open them over yet)")
    print("\nthe enforcing count is the context-menu gates,"
          " which read the rendered menus")
    return 0


if __name__ == "__main__":
    sys.exit(main())
