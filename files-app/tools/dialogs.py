"""Every dialog Files shows, against this page's.

The list comes from `assets/files-dialogs.json`, which
`tools/extract_dialogs.py` generates from the reference's own XAML: the
title, the text on each button and the captions inside.

    python3 tools/dialogs.py            # the gap, dialog by dialog
    python3 tools/dialogs.py --all      # every caption, with its state

This reads the built page's markup, so it is a claim about what was rendered
into `v3.html`. A dialog that builds itself when it opens is read by the
gate rather than here. The enforcing count is
`dialogs-carry-the-reference-captions` in verify_all.py.
"""

import html as _html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROTO = os.path.dirname(HERE)
TABLE = os.path.join(PROTO, "assets", "files-dialogs.json")
BUILT = os.path.join(PROTO, "v3.html")

#: What each of Files' dialogs is called here. Written down because the two
#: names cannot be derived from one another, and kept beside the list it maps
#: so a rename shows up as a miss rather than silently.
SAME = {
    "additem": "dlg-additem",
    "bulkrename": "dlg-bulkrename",
    "compressskippeditems": "dlg-compress-skipped",
    "createarchive": "dlg-createarchive",
    "createshortcut": "dlg-createshortcut",
    "decompressarchive": "dlg-extract",
    "dynamic": "dlg-dynamic",
    "filesystemoperation": "dlg-fsop",
    "filetoolarge": "dlg-toolarge",
    "reordersidebaritems": "dlg-reorder",
    "addbranch": "dlg-addbranch",
    "clonerepo": "dlg-clonerepo",
}

#: Dialogs that are about Windows rather than about a file manager, with
#: what each one is. Counted apart from the gap, the same way
#: tools/properties.py counts its own: a number that can never reach its
#: total stops being a measurement.
NOT_HERE = {
    "credential": "the Windows credential prompt for an SMB share; this app"
                  " mounts nothing and asks the system for no password",
}

#: Dialogs this platform could carry and does not yet, with what each one
#: needs. Kept apart from NOT_HERE because the two mean opposite things: one
#: is a decision and the other is a queue.
NOT_YET = {
    "elevateconfirm": "nothing here can re-run an operation with elevated"
                      " rights: the daemon runs as the user and there is no"
                      " polkit action behind it",
    "githublogin": "no OAuth client of our own, and a borrowed one is not"
                   " authorization",
}

#: Captions inside a dialog this page does carry that it cannot fill yet.
#: Same two reasons, one line lower down.
CAPTION_NOT_HERE = {}
#: Empty since pass nineteen: the LZMA2 knobs reach the 7z encoder through
#: /api/compress, the Extract dialog's Encoding reaches the zip reader, and
#: the conflict dialog's Custom is both the Apply to all reading and the
#: name typed over a row.
CAPTION_NOT_YET = {}

#: An attribute that carries a caption a person reads.
ATTRS = re.compile(r'(?:placeholder|aria-label|title|value)="([^"]*)"')


def table():
    with open(TABLE, encoding="utf-8") as fh:
        return json.load(fh)


def dialog(page, did):
    """The markup of one dialog, out of the built page."""
    at = page.find(f'id="{did}"')
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


def wanted(name, shown):
    """The strings one dialog puts in front of a person, title first."""
    out = []
    if shown.get("title"):
        out.append(shown["title"])
    out += list(shown.get("buttons") or [])
    out += list(shown.get("captions") or [])
    return out


def main():
    data = table()
    built = open(BUILT, encoding="utf-8").read() if os.path.exists(BUILT) else ""
    total = held = 0
    apart, queued, nowhere = [], [], []
    for name in sorted(data["shown"]):
        shown = data["shown"][name]
        if name in NOT_HERE:
            apart.append((name, NOT_HERE[name]))
            continue
        if name in NOT_YET:
            queued.append((name, NOT_YET[name]))
            continue
        did = SAME.get(name)
        markup = dialog(built, did) if (built and did) else None
        here = said(markup) if markup is not None else ""
        gap = []
        for caption in wanted(name, shown):
            key = f"{name}:{caption}"
            if key in CAPTION_NOT_HERE:
                apart.append((key, CAPTION_NOT_HERE[key]))
                continue
            if key in CAPTION_NOT_YET:
                queued.append((key, CAPTION_NOT_YET[key]))
                continue
            total += 1
            if caption.rstrip(":").lower() in here:
                held += 1
                if "--all" in sys.argv:
                    print(f"{'held':>7}  {name:<22}{caption}")
            else:
                gap.append(caption)
        if markup is None:
            print(f"\n{name}: no dialog on this page,"
                  f" {len(gap)} strings in the reference")
            nowhere.append(name)
        elif gap and "--all" not in sys.argv:
            print(f"\n{name} ({len(gap)} missing)")
            for caption in gap:
                print(f"  {caption}")

    print(f"\n{held} of {total} dialog strings, {total - held} to go")
    if nowhere:
        print(f"{len(nowhere)} dialogs are not built at all: "
              + ", ".join(nowhere))
    if queued:
        print(f"{len(queued)} this platform could carry and does not yet:")
        for what, why in queued:
            print(f"  {what}  ({why})")
    if apart:
        is_are = "is" if len(apart) == 1 else "are"
        print(f"{len(apart)} {is_are} about Windows rather than about a file"
              " manager, and counted apart:")
        for what, why in apart:
            print(f"  {what}  ({why})")
    print("the enforcing count is the dialogs gate, which opens each one")
    return 0


if __name__ == "__main__":
    sys.exit(main())
