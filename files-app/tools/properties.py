"""Every caption Files' Properties window has, against this page's.

The list comes from `assets/files-properties.json`, which
`tools/extract_properties.py` generates from the reference's own XAML and
from the factory that orders the navigation list.

    python3 tools/properties.py            # the gap, page by page
    python3 tools/properties.py --all      # every caption, with its state

This reads the built page's markup, so it is a claim about what was rendered
into `v3.html` rather than about the running window; panes that fill
themselves at runtime are read by the gate rather than here. The enforcing
count is `properties-carry-the-reference-captions` in verify_all.py.
"""

import html as _html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROTO = os.path.dirname(HERE)
TABLE = os.path.join(PROTO, "assets", "files-properties.json")
BUILT = os.path.join(PROTO, "v3.html")

#: Captions that are about Windows rather than about a file, with what each
#: one is. Counted apart from the gap, the same way tools/settings.py counts
#: its two: a number that can never reach its total stops being a
#: measurement, and a row silently dropped stops being a decision.
NOT_HERE = {
    "general:Unblock downloaded file": "the Windows mark of the web",
    "general:Compress contents": "NTFS per file compression",
    "compatibility:*": "Windows compatibility shims",
    "signatures:Version:": "an Authenticode certificate field",
    "signatures:Issued by:": "an Authenticode certificate field",
    "signatures:Issued to:": "an Authenticode certificate field",
    "signatures:Valid from:": "an Authenticode certificate field",
    "signatures:Valid to:": "an Authenticode certificate field",
    "shortcut:Run as administrator": "the Windows elevation prompt",
    "shortcut:Start window": "a Windows .lnk field",
    "general:Security": "the expander holding the unblock checkbox",
    "library:Locations:": "a Windows Library, which this platform has no"
                          " equivalent of",
    "library:No locations": "a Windows Library, which this platform has no"
                            " equivalent of",
}

#: Captions this platform could carry and does not yet, with what each one
#: needs. Kept apart from NOT_HERE because the two mean opposite things: one
#: is a decision and the other is a queue, and folding them together turns
#: work still to do into work that will never be done.
NOT_YET = {}

#: An attribute that carries a caption a person reads.
ATTRS = re.compile(r'(?:placeholder|aria-label|title|value)="([^"]*)"')


def table():
    with open(TABLE, encoding="utf-8") as fh:
        return json.load(fh)


def excused(page, caption):
    """Why this caption is not counted, and which of the two reasons it is."""
    why = NOT_HERE.get(f"{page}:*") or NOT_HERE.get(f"{page}:{caption}")
    if why:
        return "not here", why
    why = NOT_YET.get(f"{page}:{caption}")
    return ("not yet", why) if why else None


def pane(page, pid):
    """The markup of one properties pane, out of the built page."""
    at = page.find(f'id="ptab-{pid}"')
    if at < 0:
        return None
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


def said(markup):
    """Everything a person can read in a piece of markup, as one string."""
    words = _html.unescape(re.sub(r"<[^>]+>", " ", markup))
    attrs = _html.unescape(" ".join(ATTRS.findall(markup)))
    return " ".join((words + " " + attrs).split()).lower()


def main():
    data = table()
    built = open(BUILT, encoding="utf-8").read() if os.path.exists(BUILT) else ""
    total = held = 0
    apart, queued = [], []
    for item in data["nav"]:
        pid = item["page"]
        want = data["properties"].get(pid, {}).get("captions", [])
        markup = pane(built, pid) if built else None
        here = said(markup) if markup is not None else ""
        gap, mine = [], 0
        for caption in want:
            why = excused(pid, caption)
            if why:
                (apart if why[0] == "not here" else queued).append(
                    (pid, caption, why[1]))
                continue
            total += 1
            mine += 1
            if caption.rstrip(":").lower() in here:
                held += 1
                if "--all" in sys.argv:
                    print(f"{'held':>7}  {pid:<14}{caption}")
            else:
                gap.append(caption)
        if markup is None:
            print(f"\n{item['label']}: no pane on this page,"
                  f" {mine} captions in the reference")
        elif gap and "--all" not in sys.argv:
            print(f"\n{item['label']} ({len(gap)} of {mine} missing)")
            for caption in gap:
                print(f"  {caption}")

    print(f"\n{held} of {total} properties captions, {total - held} to go")
    if queued:
        print(f"{len(queued)} more this platform could carry and does not"
              " yet:")
        for pid, caption, why in queued:
            print(f"  {pid}: {caption}  ({why})")
    if apart:
        print(f"{len(apart)} are about Windows rather than about a file, and"
              " are counted apart:")
        for pid, caption, why in apart:
            print(f"  {pid}: {caption}  ({why})")
    print("the enforcing count is the properties gate,"
          " which reads the rendered window")
    return 0


if __name__ == "__main__":
    sys.exit(main())
