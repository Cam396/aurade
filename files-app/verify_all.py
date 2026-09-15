#!/usr/bin/env python3
"""One-command verification for the proto Files export.

Runs: render, static gates (syntax, no Trusted Types sinks, no em/en
dashes), live CDP assertions against real Chrome covering every pass so
far (menus, navigation, five views, footer, properties, settings, icons,
sorting, selection), and screenshots for both themes.

Usage:  python3 verify_all.py
Exit 0 only when every check passes. Cleans up its own processes.
"""
import ast
import base64
import datetime as _dt
import json
import os
import pwd
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

import localfs
import sources

ROOT = os.path.dirname(os.path.abspath(__file__))
HTTP_PORT = 8901
CDP_PORT = 19333
CHROME = "/opt/google/chrome/chrome"
TIMEOUT = 25

try:
    import websocket
except ImportError:
    print("FAIL suite needs the websocket module")
    sys.exit(1)

failures = []


def menu_table():
    """Files' nine context menus, as tools/extract_menus.py read them."""
    with open(os.path.join(ROOT, "assets", "files-menus.json"),
              encoding="utf-8") as fh:
        return json.load(fh)["menus"]


def properties_table():
    """Files' Properties window, as tools/extract_properties.py read it."""
    with open(os.path.join(ROOT, "assets", "files-properties.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def properties_wanted():
    """Every caption the Properties window should carry, page by page.

    The ones this platform does not have and the ones it does not have yet
    are named in tools/properties.py, beside the list they excuse, and are
    left out here.
    """
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import properties as _p
    data = properties_table()
    out = {}
    for item in data["nav"]:
        page = item["page"]
        said = [c for c in data["properties"].get(page, {}).get("captions", [])
                if not _p.excused(page, c)]
        if said:
            out[page] = said
    return out


def dialogs_table():
    """Files' dialogs, as tools/extract_dialogs.py read them."""
    with open(os.path.join(ROOT, "assets", "files-dialogs.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def dialogs_wanted():
    """Every string each built dialog should carry, by this page's id.

    The ones this platform has no equivalent of and the ones it could carry
    and does not yet are named in tools/dialogs.py, beside the list they
    excuse, and are left out here.
    """
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import dialogs as _d
    data = dialogs_table()
    out = {}
    for name, shown in sorted(data["shown"].items()):
        if name in _d.NOT_HERE or name in _d.NOT_YET:
            continue
        did = _d.SAME.get(name)
        if not did:
            continue
        said = [c for c in _d.wanted(name, shown)
                if f"{name}:{c}" not in _d.CAPTION_NOT_HERE
                and f"{name}:{c}" not in _d.CAPTION_NOT_YET]
        if said:
            out[did] = said
    return out


def settings_table():
    """Files' settings pages, as tools/extract_settings.py read them."""
    with open(os.path.join(ROOT, "assets", "files-settings.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def settings_wanted():
    """What each of the reference's settings is called on this page.

    The pairs live in tools/settings.py, beside the list they map, and the
    ones that are about Windows rather than about a file manager are named
    there too and left out here.
    """
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import settings as _s
    data = settings_table()
    out = []
    for item in data["nav"]:
        for row in _s.flat(data["settings"][item["page"]]["rows"]):
            name = row.get("setting")
            if not row.get("control") or not name or name in _s.NOT_HERE:
                continue
            here = _s.SAME.get(name)
            out.append(here if here else f"!{name} has no name here")
    return sorted(set(out))


#: Which of the reference's menus each of this page's menus is, and which
#: side of the content page's one list it takes.
MENUS_DRAWN = [
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


def menu_side(row, side):
    return side is None or row.get("side", "both") in (side, "both")


def menu_commands(rows, side, top=True):
    """Every command the reference puts in one menu, in the order it puts them.

    The primary commands come first because the reference draws them as the
    row of buttons above the list, and so does the page. Counted the same way
    on both sides: what is compared is the sequence of command names, read out
    of the generated table here and out of the rendered DOM there.
    """
    out = []
    if top:
        out = [row["command"] for row in rows
               if row.get("primary") and menu_side(row, side)]
    for row in rows:
        if not menu_side(row, side) or row.get("separator"):
            continue
        if top and row.get("primary"):
            continue
        if row.get("command") and not row.get("items"):
            out.append(row["command"])
        out += menu_commands(row.get("items") or [], side, False)
    return out


def menu_submenus(rows, side):
    """Each submenu and the commands directly inside it, outermost first."""
    out = []
    for row in rows:
        if not menu_side(row, side) or not row.get("items"):
            continue
        kids = [k for k in row["items"] if menu_side(k, side)]
        out.append([row.get("label") or row.get("command"),
                    [k["command"] for k in kids
                     if k.get("command") and not k.get("items")]])
        out += menu_submenus(kids, side)
    return out


def check(name, got, want):
    ok = got == want
    print(("PASS" if ok else "FAIL"), name,
          "" if ok else f"want={want} got={got}")
    if not ok:
        failures.append(name)


def free(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) != 0


def run(cmd, **kw):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True,
                          text=True, timeout=120, **kw)


def main():
    print("== render ==")
    # A page the build will never write, planted before it runs. The sweep
    # that clears a page out of site/ when its folder leaves the export has
    # nothing to sweep on an ordinary run, so deleting the sweep changed
    # nothing any gate could see: this is the case that makes it visible.
    _planted = os.path.join(ROOT, "site", "p_no_export_writes_this.html")
    os.makedirs(os.path.join(ROOT, "site"), exist_ok=True)
    with open(_planted, "w", encoding="utf-8") as _fh:
        _fh.write("<!-- left behind by an export that no longer has it -->\n")
    os.utime(_planted, (0, 0))
    r = run([sys.executable, "build_v3.py"])
    print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "")
    check("render-exit", r.returncode, 0)

    print("== static gates ==")
    src = open(os.path.join(ROOT, "build_v3.py")).read()
    # The page's script and stylesheet are files of their own under js/ and
    # css/, so a gate that reads the builder's source reads all of it.
    page_src = sources.text()
    try:
        ast.parse(src)
        check("syntax", True, True)
    except SyntaxError as e:
        check("syntax", str(e), "")
    check("sinks", len(re.findall(
        r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|srcdoc|new Function",
        re.sub(r"(?m)^[ \t]*#.*$", "", page_src))), 0)
    # Every script file parses on its own. The bundle is what runs, but a
    # brace that opens in one file and closes in the next is a cut in the
    # wrong place, and this is where it shows.
    _bad_js = []
    for _f in sources.js():
        _r = subprocess.run(["node", "--check", _f], capture_output=True, text=True)
        if _r.returncode != 0:
            _bad_js.append(os.path.basename(_f))
    check("js-files-parse-alone", _bad_js, [])
    for f in ("build_v3.py", "sidebar.py", "v3.html", "GOAL.md"):
        p = os.path.join(ROOT, f)
        if os.path.exists(p):
            check(f"no-dashes-{f}", len(re.findall(r"\u2014|\u2013",
                                                   open(p).read())), 0)
    check("no-dashes-css-js", [os.path.basename(f) for f in sources.css() + sources.js()
                               if re.search(r"\u2014|\u2013", open(f).read())], [])
    html = open(os.path.join(ROOT, "v3.html")).read()
    check("modals-present",
          all(k in html for k in ('id="props"', 'id="settings-page"',
                                  'id="ctx-file"', 'id="hist-menu"',
                                  'class="list"', 'class="cards"',
                                  'class="columns"')), True)
    # Every inline copy of a glyph carries its own defs, so it has to carry its
    # own ids. A duplicate makes url(#fg) resolve to whichever copy came first,
    # and when that one sits in a hidden subtree the gradient paints nothing.
    # Scoped to art svgs so a JS comment mentioning an id cannot trip it, and
    # template content is dropped because it is inert.
    body = re.sub(r"(?s)<template\b.*?</template>", "", html)
    art_ids = []
    for svg in re.findall(r"(?s)<svg[^>]*class=\"art\".*?</svg>", body):
        art_ids += re.findall(r'id="([^"]+)"', svg)
    check("art-ids-unique", len(art_ids) - len(set(art_ids)), 0)
    check("art-ids-present", len(art_ids) > 20, True)

    # Every page under site/ came out of this build. A page named after a
    # folder that has left the export used to stay on disk and be served
    # like any other, and one had been there for four passes, built by code
    # that predates half of what these checks assert. Asked as an age rather
    # than as a list, so it needs no second copy of how a page is named.
    _built = os.path.getmtime(os.path.join(ROOT, "v3.html"))
    _left_over = sorted(
        name for name in os.listdir(os.path.join(ROOT, "site"))
        if name.endswith(".html")
        and os.path.getmtime(os.path.join(ROOT, "site", name)) < _built - 5)
    check("no-page-outlives-the-build", _left_over, [])
    check("the-build-sweeps-a-page-that-left-the-export",
          os.path.exists(_planted), False)

    # The Network locations widget says what this machine has mounted and
    # nothing else. Read from /proc/self/mountinfo rather than through
    # localfs.network_mounts(), which reads /proc/mounts: a different file in
    # a different format, so a mistake in the reader is a disagreement here
    # rather than two matching wrong answers. The claim is the negative one,
    # which needs no copy of the network filesystem list: a card that points
    # at nothing mounted, or at a filesystem that lives on this machine, is
    # an invented network location.
    _local_fs = {"ext2", "ext3", "ext4", "btrfs", "xfs", "f2fs", "vfat",
                 "exfat", "ntfs3", "ntfs", "tmpfs", "overlay", "squashfs",
                 "proc", "sysfs", "devtmpfs", "ramfs"}
    _mounted = {}
    with open("/proc/self/mountinfo", encoding="utf-8") as _fh:
        for _line in _fh:
            _fields = _line.split()
            if "-" not in _fields:
                continue
            _at = _fields.index("-")
            _mounted[_fields[4]] = _fields[_at + 1]
    _cards = sorted(set(re.findall(
        r'wnet-card" data-path="file://([^"]*)"', html)))
    check("network-widget-shows-only-what-is-mounted-elsewhere",
          [[p, _mounted.get(p, "nothing is mounted there")] for p in _cards
           if _mounted.get(p, "") in _local_fs or p not in _mounted],
          [])
    # And when there is nothing to show it says so, the way the reference
    # does, rather than leaving an empty box. Exactly one of the two, so the
    # check means something on a machine with shares and on one without.
    _bar = 'class="winfobar"' in html
    check("network-widget-draws-cards-or-says-there-are-none",
          [bool(_cards), _bar], [bool(_cards), not _cards])

    # Attribute order is not fixed any more: icons.py stamps data-art onto the
    # glyph before the class. The gate is still that every row icon is a 16x16
    # art svg, and the lookahead now asserts the class rather than assuming
    # where it sits.
    vbs = set(re.findall(
        r'class="ricobox"><svg\b(?=[^>]*class="art")[^>]*viewBox="([^"]+)"',
        html))
    check("art-16-server", vbs, {"0 0 16 16"})

    # The command table is generated from the reference. If it has gone stale
    # the parity number below is measured against yesterday's Files, which is
    # worse than not measuring it.
    _set = run([sys.executable, "tools/extract_settings.py", "--check"])
    check("settings-table-current", _set.returncode, 0)

    _prp = run([sys.executable, "tools/extract_properties.py", "--check"])
    check("properties-table-current", _prp.returncode, 0)

    _dlg = run([sys.executable, "tools/extract_dialogs.py", "--check"])
    check("dialog-table-current", _dlg.returncode, 0)

    _gen = run([sys.executable, "tools/extract_commands.py", "--check"])
    check("command-table-current", _gen.returncode, 0)

    # And the menu table beside it, for the same reason: every context menu
    # is built from it, so a stale table is a menu that quietly stops being
    # the reference's.
    _gen = run([sys.executable, "tools/extract_menus.py", "--check"])
    check("menu-table-current", _gen.returncode, 0)

    # A second ruler for the menus, and the only one here that the generator
    # cannot move. Every other menu check compares the built page against
    # assets/files-menus.json, and both of those come out of
    # tools/extract_menus.py: a mistake in the walk changes the table and the
    # page together and the comparison still passes. These captions were read
    # out of the reference source by eye. The rows are the ones the walk is
    # most likely to lose: C#'s target typed `new()`, which is how the widget
    # menus write most of their rows, and the rows that reach their command
    # through a view model rather than naming it.
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import menus as _menus
    _by_eye = {
        "ctx-recent": ["Open with", "Remove this item", "Clear all items",
                       "Open file location", "Send to", "Loading..."],
        "ctx-drive": ["Open in new pane", "Split vertically",
                      "Split horizontally", "Pin to Sidebar",
                      "Unpin from Sidebar", "Eject", "Turn on BitLocker",
                      "Manage BitLocker"],
        "ctx-qa": ["Open in new pane", "Split vertically",
                   "Split horizontally", "Pin to Sidebar",
                   "Unpin from Sidebar", "Send to"],
        "ctx-side": ["Create new library", "Restore default libraries",
                     "Reorder sidebar items", "Hide this section", "Eject",
                     "Manage tags"],
        "ctx-file": ["Open in new pane", "Set as", "Compress", "Extract",
                     "Send to"],
        "ctx-bg": ["Layout", "Sort by", "Group by", "New", "Date modified"],
        "ctx-home": ["Widgets", "Quick access", "Drives",
                     "Network locations", "Tags", "Recent files",
                     "Split pane", "Split vertically", "Split horizontally"],
        "ctx-tab": ["Move tab to new window"],
        #: Both of these are written entirely with target typed `new()`, and
        #: both reach three of their commands through a view model property
        #: rather than by naming a command, so they are the two the walk is
        #: most likely to read as empty.
        "ctx-filetags": ["Open in new pane", "Split vertically",
                         "Split horizontally", "Open with",
                         "Open file location", "Pin to Sidebar",
                         "Unpin from Sidebar", "Send to", "Properties",
                         "Loading..."],
        "ctx-network": ["Open in new pane", "Split vertically",
                        "Split horizontally", "Pin to Sidebar",
                        "Unpin from Sidebar", "Eject", "Turn on BitLocker",
                        "Manage BitLocker", "Loading..."],
    }
    # The same second ruler for the Properties window, and for the same
    # reason: the caption gate below compares the built window against
    # assets/files-properties.json, and an extractor that read fewer
    # attributes would shrink the table and the comparison would still pass.
    # A contract that can quietly get smaller is not a contract. These were
    # read out of the reference's XAML by hand.
    _props_by_eye = {
        "general": ["Item Name", "More details", "Type:", "Location:",
                    "Size:", "Created:", "Attributes", "Read-only",
                    "Hidden", "Uncompressed size:", "Change album cover",
                    "Remove album cover"],
        "security": ["Group or user names", "Full control", "Modify",
                     "Read", "Write", "Advanced permissions"],
        "hashes": ["Algorithm", "Hash value", "Calculating...",
                   "Enter a hash to compare", "Compare a file"],
        "shortcut": ["Shortcut type:", "Destination:", "Arguments:",
                     "Start in:", "Open file location"],
        "customization": ["Choose a custom folder icon", "Restore default",
                          "Browse"],
        "details": ["Loading...",
                    "Some properties may contain personal information."],
        "signatures": ["No signature was found.", "Details"],
    }
    _props_gone = {}
    for _page, _want in _props_by_eye.items():
        _markup = _menus.slice_of(f"ptab-{_page}") or ""
        _said = re.sub(r"<[^>]+>", " ", _markup)
        _said += " " + " ".join(re.findall(
            r'(?:placeholder|aria-label|title)="([^"]*)"', _markup))
        _said = " ".join(_said.split()).lower()
        _missing = [w for w in _want
                    if w.rstrip(":").lower() not in _said]
        if _missing:
            _props_gone[_page] = _missing
    check("properties-hold-the-captions-read-by-eye", _props_gone, {})

    # The same list against the generated table, which is the half the page
    # cannot answer for. The page is written by hand, so it keeps its
    # captions whatever the extractor does; the table is what
    # properties-carry-the-reference-captions measures the page against, and
    # an extractor that read fewer of XAML's caption attributes shrank the
    # table by twenty seven captions with every gate still green. A contract
    # that can quietly get smaller is not a contract, so the hand read list
    # binds the generated one too, and exactly, since both are the
    # reference's own strings.
    _table_gone = {}
    _table_pages = properties_table()["properties"]
    for _page, _want in _props_by_eye.items():
        _said = set(_table_pages.get(_page, {}).get("captions", []))
        _gone = [w for w in _want if w not in _said]
        if _gone:
            _table_gone[_page] = _gone
    check("properties-table-holds-the-captions-read-by-eye", _table_gone, {})

    _absent = {}
    for _menu, _want in _by_eye.items():
        _seen = set(_menus.captions(_menu))
        _gone = [w for w in _want if w not in _seen]
        if _gone:
            _absent[_menu] = _gone
    check("context-menus-hold-the-rows-read-by-eye", _absent, {})

    # The same second ruler for the dialogs: strings the reference sets from
    # code rather than in XAML, which the extractor cannot see, read out of
    # FileSystemDialogViewModel and the resources by hand. Against the
    # generated table where the extractor should have seen them, and against
    # the page for the rest.
    # The placeholders are in here on purpose: they come from a different
    # attribute than the labels, and an extractor that stopped reading that
    # attribute would drop every one of them and still match its own table.
    _dialogs_by_eye_table = {
        "createarchive": ["Create archive", "Name", "Enter a name", "Format",
                          "Compression level", "Splitting size",
                          "Encryption", "Password"],
        "decompressarchive": ["Extract archive", "Path", "Browse",
                              "Archive password", "Password",
                              "Open destination folder when complete"],
        "filesystemoperation": ["Generate new name", "Replace existing",
                                "Skip", "Apply this action to all conflicting items",
                                "Permanently delete"],
        "bulkrename": ["Bulk rename", "Name", "Enter a name"],
        "addbranch": ["Create branch", "Name", "Enter a name", "Based on",
                      "Switch to new branch"],
        "createshortcut": ["Create a new shortcut",
                           "Enter the location of the item:", "Browse",
                           "Enter an item name"],
    }
    _dlg_table = dialogs_table()["shown"]
    _dlg_table_gone = {}
    for _name, _want in _dialogs_by_eye_table.items():
        _have = set(_dlg_table.get(_name, {}).get("captions", []))
        _have.add(_dlg_table.get(_name, {}).get("title"))
        _have.update(_dlg_table.get(_name, {}).get("buttons", []))
        _gone = [w for w in _want if w not in _have]
        if _gone:
            _dlg_table_gone[_name] = _gone
    check("dialog-table-holds-the-captions-read-by-eye", _dlg_table_gone, {})

    # A shortcut written into the page by hand has to be one the reference
    # actually declares. The table is the source for every shortcut the
    # registry binds, but a menu row's caption is still typed, and a caption
    # that says Ctrl+K for a command Files gives Ctrl+L to is worse than no
    # caption at all.
    _page = sources.text()
    _typed = set(re.findall(
        r"\b((?:Ctrl|Alt|Shift)\+(?:(?:Ctrl|Alt|Shift)\+)*[A-Za-z0-9]+)\b",
        _page))
    _declared = {k for v in json.load(open(
        os.path.join(ROOT, "assets", "files-commands.json"),
        encoding="utf-8"))["commands"].values() for k in v["hotkeys"]}
    #: Prose rather than a shortcut: the settings page explains range
    #: selection as "Shift+Arrow", which is not one key combination.
    check("no-invented-shortcuts",
          sorted(_typed - _declared - {"Shift+Arrow"}), [])

    # The shipped pair, built the way the SWA will carry it: files.html with
    # a <script src>, files.js beside it, and nothing about this machine in
    # either. The builder's home is a temporary folder that must not be
    # named, the start is `~`, and no path of this box, no user and no
    # host name may appear. The sidebar and the widgets that the static
    # export draws from this machine's volumes are drawn live instead.
    _ship = os.path.join(ROOT, "ship")
    shutil.rmtree(_ship, ignore_errors=True)
    try:
        _r = run([sys.executable, "build_v3.py"], env=dict(os.environ, AURADE_SHIP=_ship))
        check("ship-build-exit", _r.returncode, 0)
        _sh = open(os.path.join(_ship, "files.html"), encoding="utf-8").read() \
            if os.path.exists(os.path.join(_ship, "files.html")) else ""
        _sj = open(os.path.join(_ship, "files.js"), encoding="utf-8").read() \
            if os.path.exists(os.path.join(_ship, "files.js")) else ""
        _both = _sh + _sj
        _leaks = sorted(set(re.findall(
            r"/(?:root|home/[^/\"'<\s]+|mnt/[^\"'<\s]+|tmp/[^\"'<\s]+)", _both)))
        #: The user's name as a path element (root's is in the path check
        #: above, and "root" is a word this page uses for other things),
        #: and the host name anywhere.
        _me = pwd.getpwuid(os.getuid()).pw_name
        _who = ([_me] if re.search(r"/(?:home|Users)/" + re.escape(_me) + r"\b", _both) else []) + \
               [h for h in [os.uname().nodename] if len(h) > 2 and h in _both]
        check("ship-page-carries-nothing-of-this-machine",
              [_leaks, _who, re.findall(r"<script[^>]*>", _sh),
               _sh.count('data-path="~"') >= 1, "aurade-ship-home" in _both],
              [[], [], ['<script src="files.js">'], True, False])
        _r = subprocess.run(["node", "--check", os.path.join(_ship, "files.js")],
                            capture_output=True, text=True) if _sj else None
        check("ship-script-parses", _r.returncode if _r else "no files.js", 0)
        # The rules that make the page fill its frame belong to the shipped
        # page and to nothing else: the prototype has to keep drawing a
        # window on a desktop, which is the only way the shadow and the
        # corner are judged against the reference screenshot.
        _v3 = open(os.path.join(ROOT, "v3.html"), encoding="utf-8").read()
        check("ship-rules-are-only-in-the-shipped-page",
              [_sh.count("/* ---- shipped ---- */"),
               _v3.count("/* ---- shipped ---- */")], [1, 0])
        # Every date in the shipped page is a placeholder for a folder made
        # for the build, so none of them may be the build's own clock: that
        # is the build minute and the build machine's time zone in a released
        # file, and two builds of one set of sources that differ. Built with
        # a date named, every date reads as that date and no other.
        _when_dir = os.path.join(ROOT, "ship-dated")
        shutil.rmtree(_when_dir, ignore_errors=True)
        _stamp = 1700000000
        _r2 = run([sys.executable, "build_v3.py"],
                  env=dict(os.environ, AURADE_SHIP=_when_dir,
                           SOURCE_DATE_EPOCH=str(_stamp)))
        _dated = "".join(
            open(os.path.join(_when_dir, n), encoding="utf-8").read()
            for n in ("files.html", "files.js")
            if os.path.exists(os.path.join(_when_dir, n)))
        _want = _dt.datetime.fromtimestamp(
            _stamp, _dt.timezone.utc).strftime("%-d %b %Y %H:%M")
        _read = set(re.findall(r"\b\d{1,2} [A-Z][a-z]{2} \d{4} \d{2}:\d{2}", _dated))
        check("the-shipped-page-carries-no-clock",
              [_r2.returncode, sorted(_read - {_want}), _want in _read],
              [0, [], True])
        shutil.rmtree(_when_dir, ignore_errors=True)
    finally:
        pass

    if failures:
        print(f"{len(failures)} static failures, skipping live checks")
        return 1

    print("== live checks ==")
    if not free(HTTP_PORT) or not free(CDP_PORT):
        print("FAIL ports busy, refusing to start servers")
        return 1
    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(HTTP_PORT)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Without a profile of its own, headless Chrome makes one under /tmp and
    # leaves it there whenever it is stopped rather than closed. A hundred and
    # seventy of them held 19 GB of tmpfs after one night of mutation runs.
    profile = tempfile.mkdtemp(prefix="verify-chrome-")
    chrome = subprocess.Popen(
        [CHROME, "--headless=new", "--no-sandbox", "--disable-gpu",
         f"--user-data-dir={profile}",
         "--remote-allow-origins=*",
         f"--remote-debugging-port={CDP_PORT}",
         "--window-size=1280,900",
         f"http://127.0.0.1:{HTTP_PORT}/v3.html"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws_url = None
        for _ in range(30):
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{CDP_PORT}/json/list",
                        timeout=5) as resp:
                    for t in json.load(resp):
                        if (f"127.0.0.1:{HTTP_PORT}" in t.get("url", "")
                                and t.get("type") == "page"):
                            ws_url = t["webSocketDebuggerUrl"]
                if ws_url:
                    break
            except Exception:
                pass
            time.sleep(1)
        if not ws_url:
            print("FAIL no debuggable page")
            return 1
        ws = websocket.create_connection(ws_url, timeout=TIMEOUT)
        seq = [0]
        deadline = time.monotonic() + 240

        def ev(expr):
            seq[0] += 1
            ws.send(json.dumps({"id": seq[0], "method": "Runtime.evaluate",
                                "params": {"expression": "(" + expr + ")()",
                                           "awaitPromise": True,
                                           "returnByValue": True}}))
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError("cdp deadline")
                try:
                    msg = json.loads(ws.recv())
                except Exception as e:
                    return f"RECV:{e}"
                if msg.get("id") == seq[0]:
                    if "exceptionDetails" in msg["result"]:
                        #: The description carries the error and its stack, and
                        #: it sits at the end of the envelope, so dumping the
                        #: envelope and cutting at a couple of hundred
                        #: characters reported every failure as the word
                        #: "TypeError" and nothing else. Lead with it.
                        _d = msg["result"]["exceptionDetails"]
                        _e = (_d.get("exception") or {})
                        _why = (_e.get("description") or _d.get("text") or "")
                        return "EXC:" + " ".join(str(_why).split())[:600]
                    return msg["result"]["result"].get("value")

        def go(url):
            seq[0] += 1
            ws.send(json.dumps({"id": seq[0], "method": "Page.navigate",
                                "params": {"url": url}}))
            while True:
                msg = json.loads(ws.recv())
                if msg.get("id") == seq[0]:
                    break
            for _ in range(30):
                if ev("() => typeof window.__mode") == "function":
                    break
                time.sleep(1)

        def shot(path):
            seq[0] += 1
            ws.send(json.dumps({"id": seq[0],
                                "method": "Page.captureScreenshot",
                                "params": {"format": "png"}}))
            while True:
                msg = json.loads(ws.recv())
                if msg.get("id") == seq[0]:
                    with open(os.path.join(ROOT, path), "wb") as fh:
                        fh.write(base64.b64decode(msg["result"]["data"]))
                    return True
            return False

        home = f"http://127.0.0.1:{HTTP_PORT}/v3.html"
        for _ in range(30):
            if ev("() => typeof window.__mode") == "function":
                break
            time.sleep(1)
        sub = ev("() => { const a = document.querySelector('.cell[href]');"
                 " return a ? a.href : null; }")
        if sub:
            go(sub)
            check("crumb-flyout-opens",
                  ev("() => { const b = document.querySelector('.cchev');"
                     " if (!b) return 'NO-CHEVRON'; b.click();"
                     " const m = b.parentElement.querySelector('.menu');"
                     " return [m.hidden, m.querySelectorAll('.mi').length > 0]; }"),
                  [False, True])
            check("tab-ctx-opens",
                  ev("() => { document.querySelector('.tab').dispatchEvent("
                     "new MouseEvent('contextmenu', {bubbles: true, clientX: 200, clientY: 20}));"
                     " return document.getElementById('ctx-tab').hidden; }"),
                  False)
            check("history-records",
                  ev("() => JSON.parse(sessionStorage.getItem('aurade-trail') || '[]').length >= 1"),
                  True)
            # Column resize. The header cell and the body cell of a column
            # read one custom property, so the test that matters is that both
            # move together: two numbers kept equal by hand drift the moment
            # one render path is missed.
            check("cols-resize",
                  ev("() => { const b = document.getElementById('settings-back');"
             " if (b && !document.getElementById('settings-page').hidden)"
             " b.click();"
             " window.__doAct('lay-details');"
             " const hdr = () => Math.round(document.querySelector('.dh-when')"
             ".getBoundingClientRect().width);"
             " const cell = () => Math.round(document.querySelector("
             "'.row .c-when').getBoundingClientRect().width);"
             " const g = document.querySelector('.dh-grip[data-grip=\"when\"]');"
             " if (!g) return ['no-grip'];"
             " const before = [hdr(), cell()];"
             " const r = g.getBoundingClientRect();"
             " const o = {bubbles: true, clientX: r.left + 4,"
             " clientY: r.top + 8, pointerId: 1};"
             " g.dispatchEvent(new PointerEvent('pointerdown', o));"
             " document.dispatchEvent(new PointerEvent('pointermove',"
             " Object.assign({}, o, {clientX: r.left + 84})));"
             " document.dispatchEvent(new PointerEvent('pointerup', o));"
             " const after = [hdr(), cell()];"
             " const saved = window.__getPref('columns.widths');"
             " g.dispatchEvent(new MouseEvent('dblclick', {bubbles: true}));"
             " const reset = [hdr(), cell()];"
             " window.__doAct('lay-grid');"
             " document.dispatchEvent(new KeyboardEvent('keydown',"
             " {key: 'Escape', bubbles: true}));"
             " return [document.querySelectorAll('.dh-grip').length,"
             " before[0] === before[1], after[0] === after[1],"
             " after[0] - before[0], saved.when, reset[0], reset[1]]; }"),
                  [6, True, True, 80, 280, 200, 200])
            # Grid sizes. One step changes three numbers, and the size has to
            # outlive a trip through another layout: it is a modifier on the
            # grid, not a layout of its own.
            check("grid-sizes",
                  ev("() => { const b = document.getElementById('settings-back');"
             " if (b && !document.getElementById('settings-page').hidden)"
             " b.click();"
             " window.__doAct('lay-grid');"
             " const w = () => Math.round(document.querySelector('.cell')"
             ".getBoundingClientRect().width);"
             " const art = () => Math.round(document.querySelector("
             "'.cell .art, .cell .thumbimg').getBoundingClientRect().width);"
             " const sizes = ['small', 'medium', 'large'].map(s => {"
             " window.__gridSize.set(s); return [w(), art()]; });"
             " window.__doAct('lay-grid-small');"
             " const viaMenu = [document.documentElement"
             ".getAttribute('data-gridsize'), w()];"
             " window.__doAct('lay-details'); window.__doAct('lay-grid');"
             " const survives = document.documentElement"
             ".getAttribute('data-gridsize');"
             " window.__gridSize.set('medium');"
             " document.dispatchEvent(new KeyboardEvent('keydown',"
             " {key: 'Escape', bubbles: true}));"
             " return [sizes, viaMenu, survives, w()]; }"),
                  [[[92, 44], [120, 66], [168, 98]], ["small", 92], "small", 120])
            go(home)

        # The static export has no backend to ask, so its git area has to be
        # exactly what the build baked in: blanking it would replace a fact
        # with nothing, since the export is one folder and that folder's
        # branch is still true for it. The served HTML is compared against the
        # live DOM, so this holds whether or not the build host is in a repo.
        page = open(os.path.join(ROOT, "v3.html"), encoding="utf-8").read()
        mw = re.search(r'id="git-wrap"([^>]*)>', page)
        baked_hidden = bool(mw) and "hidden" in mw.group(1)
        mb = re.search(r'id="git-branch">([^<]*)<', page)
        baked_branch = mb.group(1) if mb else ""

        round1 = [
            ("new-menu-opens",
             "() => { document.querySelector('.twrap > .tbtn').click();"
             " return document.getElementById('m-new').hidden; }", False),
            ("ctx-file-opens",
             "() => { document.querySelector('.cell').dispatchEvent("
             "new MouseEvent('contextmenu', {bubbles: true, clientX: 400, clientY: 300}));"
             " return document.getElementById('ctx-file').hidden; }", False),
            ("file-click-selects",
             "() => { const f = Array.from(document.querySelectorAll('.cell'))"
             ".find(c => c.tagName !== 'A'); f.click();"
             " return [document.querySelectorAll('.cell.sel').length,"
             " document.getElementById('st-sel').textContent]; }",
             [1, "1 item selected"]),
            ("ctrl-a-selects-all",
             "() => { document.dispatchEvent(new KeyboardEvent('keydown',"
             " {key: 'a', ctrlKey: true, bubbles: true}));"
             " return document.querySelectorAll('.cell.sel').length; }",
             ev("() => document.querySelectorAll('.grid .cell').length")),
            # The palette is the whole command table now, not nineteen rows
            # with a lookup of their own, so what is checked is that it holds
            # every command and that typing narrows it to one. Every word has
            # to appear rather than any of them: "sort" alone matches
            # nineteen commands and is no use to anyone, while "sort name"
            # has to land on exactly the one.
            # The keyboard. Files gives seventy one of its commands a
            # shortcut and some of them two, and they are in the generated
            # table, so the key, the menu row and the palette all come from
            # one line of the reference. What is asserted is the parse, since
            # that is where a shortcut table goes wrong: the reference names
            # the face of a key and a browser reports a code, and with shift
            # held the 3 key reports "#" rather than "3", so a table written
            # against `key` would miss Ctrl+Shift+3 entirely.
            ("shortcuts-come-from-the-table",
             "() => { const h = window.__hotkeys();"
             " const faces = Array.from(new Set(window.__unboundHotkeys()"
             ".map(p => p[1]))).sort();"
             " return [Object.keys(h).length > 65, h['CKeyC'], h['CSKeyN'],"
             "  h['CSDigit3'], h['CEqual'], h['CSKeyE'], faces]; }",
             [True, "CopyItem", "CreateFolder", "LayoutCards",
              "LayoutIncreaseSize", "DecompressArchiveHereSmart",
              #: The four the reference names that a page cannot listen for:
              #: two mouse buttons and the browser's own navigation keys.
              ["GoBack", "GoForward", "Mouse4", "Mouse5"]]),
            # End to end, on the shortcut that only works because the match is
            # on the code: with shift held there is no "3" to match against.
            ("a-shortcut-runs-its-command",
             "() => { document.getElementById('palette').hidden = true;"
             " document.dispatchEvent(new KeyboardEvent('keydown',"
             "  {code: 'Digit3', key: '#', ctrlKey: true, shiftKey: true,"
             "   bubbles: true, cancelable: true}));"
             " const on = window.__mode();"
             " document.dispatchEvent(new KeyboardEvent('keydown',"
             "  {code: 'Digit4', key: '$', ctrlKey: true, shiftKey: true,"
             "   bubbles: true, cancelable: true}));"
             #: The mode and not the container's `hidden`: on Home every
             #: layout container is hidden whatever the command did, which is
             #: how the two view switch checks came to pass against a palette
             #: that ran nothing.
             " return [on, window.__mode()]; }",
             ["cards", "grid"]),
            # A shortcut with no modifier belongs to whoever is typing. Read
            # off defaultPrevented rather than off what the command did, so
            # the check is about the guard and has no side effect to undo.
            ("a-bare-shortcut-does-not-fire-while-someone-is-typing",
             "() => { const make = () => new KeyboardEvent('keydown',"
             "  {code: 'F5', key: 'F5', bubbles: true, cancelable: true});"
             " const i = document.getElementById('finput');"
             " const typed = make(); i.dispatchEvent(typed);"
             " const loose = make(); document.body.dispatchEvent(loose);"
             " return [typed.defaultPrevented, loose.defaultPrevented]; }",
             [False, True]),
            # Any element that names a command runs it. That one branch is
            # what the status bar's git flyout goes through and what anything
            # added later will go through, so it is checked with a layout
            # command, which has an answer and nothing to undo.
            ("a-named-command-runs-from-the-markup",
             "() => { window.__setLayout('grid');"
             " const el = document.createElement('div');"
             " el.setAttribute('data-command', 'LayoutCards');"
             " document.body.appendChild(el); el.click();"
             " const got = window.__mode(); el.remove();"
             " window.__setLayout('grid');"
             " return got; }",
             "cards"),
            # The reference's GitNetworkActions: the button that shows how far
            # ahead and behind the branch is opens a flyout of Pull, Push and
            # Sync, each with its own glyph. Three and not six, because three
            # is what StatusBar.xaml has.
            ("git-network-flyout",
             "() => { const menu = document.getElementById('m-git-net');"
             " if (!menu) return 'no flyout';"
             " const inWrap = !!(menu.parentElement &&"
             "  menu.parentElement.classList.contains('twrap'));"
             " return [inWrap, menu.hidden,"
             "  Array.from(menu.querySelectorAll('.mi')).map(r =>"
             "   [r.getAttribute('data-command'),"
             "    r.querySelector('.mi-t').textContent,"
             "    !!r.querySelector('svg path')])]; }",
             [True, True, [["GitPull", "Pull", True], ["GitPush", "Push", True],
                           ["GitSync", "Sync", True]]]),
            # Measured, not counted. The search box carried flex:1 inside a
            # column, so it grew to fill the dialog and the list of commands
            # got what was left. A rule that says height:30px is not a box
            # that is 30 pixels tall.
            # A shortcut asks the command whether it can run before running
            # it. Asserted by making one command say no and pressing its key:
            # `defaultPrevented` looked like the obvious signal and is not,
            # because other handlers on the page take keys of their own and
            # set it for their own reasons.
            ("a-shortcut-asks-the-command-first",
             "() => { document.getElementById('palette').hidden = true;"
             " window.__setLayout('grid');"
             " const c = window.__commands.get('LayoutCards');"
             " const own = c.enabled;"
             " const press = () => document.dispatchEvent("
             "  new KeyboardEvent('keydown', {code: 'Digit3', key: '#',"
             "   ctrlKey: true, shiftKey: true, bubbles: true, cancelable: true}));"
             " c.enabled = () => false; press();"
             " const refused = window.__mode();"
             " c.enabled = () => true; press();"
             " const ran = window.__mode();"
             " c.enabled = own; window.__setLayout('grid');"
             " return [refused, ran]; }",
             ["grid", "cards"]),
            ("palette-box-is-the-height-it-says",
             "() => { document.getElementById('btn-palette').click();"
             " const i = document.getElementById('pal-input');"
             " const l = document.getElementById('pal-list');"
             " const ib = i.getBoundingClientRect();"
             " const lb = l.getBoundingClientRect();"
             " return [Math.round(ib.height), lb.height > ib.height * 4]; }",
             [30, True]),
            # And the dialog is as tall as what is in it. The scrim is a flex
            # row, whose default stretches a child to full height, so the
            # palette sat at its 380 pixel cap with four rows in it.
            ("palette-is-as-tall-as-its-rows",
             "() => { const i = document.getElementById('pal-input');"
             " const box = document.querySelector('.pal');"
             " const type = t => { i.value = t;"
             "  i.dispatchEvent(new Event('input', {bubbles: true}));"
             "  return Math.round(box.getBoundingClientRect().height); };"
             " const many = type('');"
             " const few = type('sort name');"
             " type('');"
             " return [many, few < many, few < 120]; }",
             [380, True, True]),
            # NavigationToolbarViewModel skips a command that is not
            # executable rather than drawing it greyed, so this does too. The
            # row stays in the markup, which is what keeps the parity count
            # honest; it is left out of the list. The floor matters as much as
            # the ceiling: a predicate that went wrong everywhere would empty
            # the palette, and an empty palette is not a passing check.
            ("palette-leaves-out-what-cannot-run",
             "() => { document.getElementById('palette').hidden = true;"
             " window.__clearSelection();"
             " document.getElementById('btn-palette').click();"
             " const rows = Array.from(document.querySelectorAll('.pcmd'));"
             " const showing = rows.filter(r => r.style.display !== 'none');"
             " const off = rows.filter(r => r.getAttribute('data-state') === 'off');"
             " const na = rows.filter(r => r.getAttribute('data-state') === 'na');"
             " return [showing.length > 100, showing.length < rows.length,"
             "  off.length > 0,"
             #: The two with no counterpart keep their row and stay in the
             #: list, because the row is there to say why.
             "  na.every(r => r.style.display !== 'none')]; }",
             [True, True, True, True]),
            # The reference splits the title into three Runs and bolds the one
            # that matched what was typed.
            ("palette-bolds-what-matched",
             "() => { const i = document.getElementById('pal-input');"
             " i.value = 'cards view';"
             " i.dispatchEvent(new Event('input', {bubbles: true}));"
             " const row = document.querySelector('.pcmd[data-code=\"LayoutCards\"]');"
             " const b = row ? row.querySelector('.mi-t b') : null;"
             " const out = [row ? row.querySelector('.mi-t').textContent : 'no row',"
             "  b ? b.textContent : 'not bolded'];"
             " document.getElementById('palette').hidden = true;"
             " return out; }",
             ["Switch to cards view", "cards"]),
            ("palette-lists-every-command",
             "() => { document.getElementById('btn-palette').click();"
             " const rows = document.querySelectorAll('.pcmd').length;"
             " const known = Object.keys(window.__commandStates()).length;"
             " return [rows, rows === known]; }",
             #: The number comes from the generated table, so it moves when
             #: the reference does and is never a figure typed in twice.
             [len(json.load(open(os.path.join(ROOT, "assets",
                                              "files-commands.json"),
                                 encoding="utf-8"))["commands"]), True]),
            ("palette-filters",
             "() => { const i = document.getElementById('pal-input');"
             " i.value = 'sort name';"
             " i.dispatchEvent(new Event('input', {bubbles: true}));"
             " const shown = Array.from(document.querySelectorAll('.pcmd'))"
             ".filter(c => c.style.display !== 'none');"
             " return [shown.length,"
             "  shown.length ? shown[0].getAttribute('data-code') : '',"
             "  shown.length ? shown[0].classList.contains('hot') : false]; }",
             [1, "SortByName", True]),
            # Each row carries the command's own glyph, drawn at build time
            # from the same artwork the menus use. A palette of bare text is
            # the thing this replaced.
            ("palette-rows-carry-their-glyph",
             "() => { const rows = Array.from"
             "(document.querySelectorAll('.pcmd'));"
             " const drawn = rows.filter(r => r.querySelector('svg')).length;"
             " const first = rows.find(r => r.getAttribute('data-code')"
             " === 'CopyItem');"
             " return [drawn > 60, drawn < rows.length,"
             "  !!(first && first.querySelector('svg path')),"
             "  !!(first && first.querySelector('.pc-key'))]; }",
             [True, True, True, True]),
            # A command with no counterpart here keeps its row and says why,
            # because missing and cannot-apply are different facts.
            ("palette-says-why-a-command-cannot-apply",
             "() => { const na = Array.from"
             "(document.querySelectorAll('.pcmd[data-state=\"na\"]'))"
             ".map(r => [r.getAttribute('data-code'),"
             "  (r.getAttribute('title') || '').length > 40]);"
             " na.sort();"
             " return na; }",
             [["InstallInfDriver", True], ["SetAsLockscreenBackground", True]]),
            ("pane-opens",
             "() => { document.getElementById('palette').hidden = true;"
             " document.getElementById('btn-pane').click();"
             " return document.getElementById('infopane').hidden; }", False),
            ("escape-clears",
             "() => { document.dispatchEvent(new KeyboardEvent('keydown',"
             " {key: 'Escape', bubbles: true}));"
             " return document.querySelectorAll('.cell.sel').length; }", 0),
            # Clearing has to reach the layouts that are not on screen. It did
            # not: the clear went through the visible container while the
            # switch reads across all five, so Ctrl+A, Escape, then details
            # showed everything selected again.
            ("a-cleared-selection-does-not-come-back-in-another-layout",
             "() => { const hw = document.getElementById('home-widgets');"
             " if (hw) hw.hidden = true; window.__setLayout('grid');"
             " document.dispatchEvent(new KeyboardEvent('keydown',"
             "  {key: 'a', ctrlKey: true, bubbles: true}));"
             " const all = document.querySelectorAll('.grid .cell.sel').length;"
             " document.dispatchEvent(new KeyboardEvent('keydown',"
             "  {key: 'Escape', bubbles: true}));"
             " const here = document.querySelectorAll('.grid .cell.sel').length;"
             " window.__setLayout('details');"
             " const there = document.querySelectorAll('.dbody .row.sel').length;"
             " window.__setLayout('grid');"
             " return [all > 1, here, there]; }",
             [True, 0, 0]),
            # Both of these used to read the container's `hidden`, which on
            # Home is true whatever the palette did, and to compare the tile
            # and cell counts against numbers measured before the click, which
            # match when nothing happens. A mutation that stopped the palette
            # running anything passed both. What is asserted now is which row
            # the filter picked and what layout the click produced, neither of
            # which has an answer when the click does nothing.
            ("cards-view-switch",
             "() => { document.getElementById('btn-palette').click();"
             " const i = document.getElementById('pal-input'); i.value = 'cards view';"
             " i.dispatchEvent(new Event('input', {bubbles: true}));"
             " const row = Array.from(document.querySelectorAll('.pcmd'))"
             ".find(c => c.style.display !== 'none');"
             " const code = row ? row.getAttribute('data-code') : 'no row';"
             " if (row) row.click();"
             " return [code, window.__mode()]; }",
             ["LayoutCards", "cards"]),
            ("columns-view-switch",
             "() => { document.getElementById('btn-palette').click();"
             " const i = document.getElementById('pal-input'); i.value = 'columns view';"
             " i.dispatchEvent(new Event('input', {bubbles: true}));"
             " const row = Array.from(document.querySelectorAll('.pcmd'))"
             ".find(c => c.style.display !== 'none');"
             " const code = row ? row.getAttribute('data-code') : 'no row';"
             " if (row) row.click();"
             " return [code, window.__mode()]; }",
             ["LayoutColumns", "columns"]),
            ("props-opens-folder",
             "() => { const g = Array.from(document.querySelectorAll('[data-act]'))"
             ".find(x => x.getAttribute('data-act') === 'lay-grid'); g.click();"
             " const b = Array.from(document.querySelectorAll('[data-act]'))"
             ".find(x => x.getAttribute('data-act') === 'ctx-props'); b.click();"
             " return [!document.getElementById('props').hidden,"
             " document.querySelector('[data-gk=\"Name\"]').textContent]; }",
             None),
            ("props-file-hash",
             "() => { document.getElementById('props').hidden = true;"
             " const f = Array.from(document.querySelectorAll('.cell'))"
             ".find(c => c.tagName !== 'A' && c.getAttribute('data-md5'));"
             " if (!f) return 'NO-HASHED-FILE'; f.click();"
             " const b = Array.from(document.querySelectorAll('[data-act]'))"
             ".find(x => x.getAttribute('data-act') === 'ctx-props'); b.click();"
             " return [document.querySelector('[data-gk=\"Name\"]').textContent"
             " === f.getAttribute('data-n'),"
             " document.getElementById('h-md5').textContent === f.getAttribute('data-md5'),"
             " document.getElementById('h-sha256').textContent.length === 64]; }",
             None),
            ("hash-compare",
             "() => { const v = document.getElementById('h-sha1').textContent;"
             " const i = document.getElementById('hash-input'); i.value = v;"
             " document.getElementById('hash-compare').click();"
             " const r = document.getElementById('hash-result');"
             " const ok = [r.hidden, r.textContent.indexOf('Hashes match') === 0];"
             " i.value = 'deadbeef'; document.getElementById('hash-compare').click();"
             " return [ok, document.getElementById('hash-result').textContent]; }",
             [[False, True], "Hashes do not match."]),
            ("footer-size-sums",
             "() => { document.getElementById('props').hidden = true;"
             " document.dispatchEvent(new KeyboardEvent('keydown',"
             " {key: 'Escape', bubbles: true}));"
             " const cells = Array.from(document.querySelectorAll('.cell'))"
             ".filter(c => c.tagName !== 'A' && parseInt(c.getAttribute('data-sb')) > 0).slice(0, 2);"
             " cells[0].click();"
             " cells[1].dispatchEvent(new MouseEvent('click', {bubbles: true, ctrlKey: true}));"
             " return [!document.getElementById('st-size').hidden,"
             " document.getElementById('st-sel').textContent,"
             " document.getElementById('st-size').textContent.length > 0]; }",
             [True, "2 items selected", True]),
             ("settings-theme-switch",
              "() => { document.getElementById('side-settings').click();"
              " const open = !document.getElementById('settings-page').hidden"
              " && document.getElementById('filearea').hidden;"
              " Array.from(document.querySelectorAll('.mi[data-theme]'))"
              ".find(x => x.getAttribute('data-theme') === 'light').click();"
              " const isLight = document.documentElement.dataset.theme === 'light';"
              " Array.from(document.querySelectorAll('.mi[data-theme]'))"
              ".find(x => x.getAttribute('data-theme') === 'dark').click();"
              " const isDark = !document.documentElement.dataset.theme;"
              " document.getElementById('settings-back').click();"
              " return [open, isLight, isDark,"
              " document.getElementById('settings-page').hidden,"
              " !document.getElementById('filearea').hidden]; }",
              [True, True, True, True, True]),
             # Every setting Files has, against the rendered settings
             # page. The names differ between the two, so tools/settings.py
             # writes the pairs down; what is asked here is that each of the
             # reference's settings reaches a control a person can use, read
             # off the DOM rather than out of the builder, because a regex
             # over the builder has now failed to keep up with it twice.
             ("settings-carry-the-reference-settings",
              "() => { document.getElementById('side-settings').click();"
              " const navs = Array.from(document.querySelectorAll("
              "'#settings-page .snav-btn'));"
              " navs.forEach(n => n.click());"
              " const have = new Set();"
              " document.querySelectorAll('#settings-page [data-pref]')"
              ".forEach(c => have.add(c.getAttribute('data-pref')));"
              " document.querySelectorAll('#settings-page [id]')"
              ".forEach(c => have.add('#' + c.id));"
              " document.getElementById('settings-back').click();"
              " const want = " + json.dumps(settings_wanted()) + ";"
              " return want.filter(w => !have.has(w)); }",
              []),
             # Files lists its settings pages in one order. This page adds
             # two of its own, Icons and Toolbar, so what is asked is that
             # the reference's nine are all there and none of them has moved
             # relative to another.
             ("settings-nav-holds-the-reference-pages-in-order",
              "() => Array.from(document.querySelectorAll("
              "'#settings-page .snav-btn .snav-lbl')).map(l => l.textContent)"
              ".filter(t => " + json.dumps(
                  [i["label"] for i in settings_table()["nav"]])
              + ".indexOf(t) >= 0)",
              [i["label"] for i in settings_table()["nav"]]),
             # The Properties window's navigation list, in the order
             # PropertiesNavigationItemsFactory adds its items. Two of the
             # nine are a Windows Library and Windows compatibility shims
             # and are not drawn, so what is asked is that the seven that
             # apply are all there and none has moved relative to another.
             ("properties-nav-holds-the-reference-pages-in-order",
              "() => Array.from(document.querySelectorAll("
              "'#props .ptab')).map(b => b.getAttribute('data-ptab'))",
              [i["page"] for i in properties_table()["nav"]
               if i["page"] not in ("library", "compatibility")]),
             # And every caption the reference puts on those pages, read off
             # the rendered window rather than the markup: two of them are
             # written by script when the window opens.
             ("properties-carry-the-reference-captions",
              "() => { const want = "
              + json.dumps(properties_wanted()) + ";"
              " const gone = [];"
              " Object.keys(want).forEach(page => {"
              "  const pane = document.getElementById('ptab-' + page);"
              "  if (!pane) { gone.push(page + ': no pane'); return; }"
              "  const said = (pane.textContent + ' '"
              "   + Array.from(pane.querySelectorAll('[placeholder],[title],"
              "[aria-label]')).map(e => (e.getAttribute('placeholder') || '')"
              "   + ' ' + (e.getAttribute('title') || '') + ' '"
              "   + (e.getAttribute('aria-label') || '')).join(' '))"
              "   .replace(/\\s+/g, ' ').toLowerCase();"
              "  want[page].forEach(c => {"
              "   if (said.indexOf(c.replace(/:$/, '').toLowerCase()) < 0)"
              "    gone.push(page + ': ' + c); });"
              " });"
              " return gone; }",
              []),
             ("settings-nav",
              "() => { document.getElementById('side-settings').click();"
              " const navs = Array.from(document.querySelectorAll('#settings-page .snav-btn'));"
              " const ok = navs.map(n => { n.click();"
              " const pane = document.getElementById('spane-' + n.getAttribute('data-snav'));"
              " return pane && !pane.hidden; });"
              " document.getElementById('settings-back').click();"
              " return [navs.length, ok.every(Boolean)]; }",
              [11, True]),
             # The nav shipped icon only for a while: the buttons carried the
            # container's class, so its flex-direction:column applied to each
            # button and squeezed the label to two pixels inside a 36px row.
            # Counting rows and panes did not notice, because both were fine.
            # This measures the label the way a person sees it.
            ("settings-nav-labels",
             "() => { document.getElementById('side-settings').click();"
             " const rows = Array.from(document.querySelectorAll("
             "'#settings-page .snav-btn'));"
             " const bad = rows.filter(r => {"
             " const l = r.querySelector('.snav-lbl');"
             " const i = r.querySelector('.snav-ico');"
             " if (!l || !i || !l.textContent.trim()) return true;"
             " const lb = l.getBoundingClientRect();"
             " const ib = i.getBoundingClientRect();"
             " return lb.width < 24 || lb.height < 10 || lb.left < ib.right; })"
             ".map(r => r.getAttribute('data-snav'));"
             " const names = rows.map(r => r.querySelector('.snav-lbl')"
             ".textContent);"
             " const dir = getComputedStyle(rows[0]).flexDirection;"
             " const sel = document.querySelector('#settings-page .snav-btn.on');"
             " const pill = sel ? getComputedStyle(sel, '::before').display"
             " : 'none';"
             " document.getElementById('settings-back').click();"
             " return [bad, dir, pill, names]; }",
             [[], "row", "block",
              ["General", "Appearance", "Icons", "Toolbar", "Layout",
               "Files & folders", "Actions", "Tags", "Developer tools",
               "Advanced", "About"]]),
            ("settings-pref-acts",
              "() => { window.__setPref('showStatusbar', false);"
              " const hid = document.querySelector('.status').hidden;"
              " window.__setPref('showStatusbar', true);"
              " const back = !document.querySelector('.status').hidden;"
              " const cell = Array.from(document.querySelectorAll('.grid .cell'))"
              ".find(c => (c.getAttribute('data-n') || '').indexOf('.') > 0"
              " && c.getAttribute('data-k') !== 'Folder');"
              " const lbl = cell.querySelector('.cname,.rname,.lname,.wcard-name,.lbl');"
              " const full = cell.getAttribute('data-n');"
              " window.__setPref('showExt', false);"
              " const stem = lbl.textContent;"
              " window.__setPref('showExt', true);"
              " return [hid, back, stem !== full && full.startsWith(stem),"
              " lbl.textContent === full]; }",
              [True, True, True, True]),
            # The chooser: switching sets has to change what is on screen, and
            # switching back has to restore it exactly. Comparing the rendered
            # markup rather than a set name is what makes this fail if the
            # reskin silently no-ops or clobbers the library it clones from.
            ("iconset-switch",
             "() => { const norm = s => s.replace(/__c?\\d+/g, '');"
             " const one = () => norm(document.querySelector('.thumb svg')"
             ".outerHTML);"
             " const other = Object.keys(window.__iconSets)"
             ".find(k => k !== 'aurade');"
             " if (!other) return ['no-other-set'];"
             " const a = one(); window.__applyIconSet(other);"
             " const b = one(); window.__applyIconSet('aurade');"
             " const c = one();"
             " return [a !== b, a === c,"
             " document.querySelectorAll('#artlib [data-set]').length > 0]; }",
             [True, True, True]),
            # Every copy of a glyph carries its own defs, so it has to carry its
            # own ids. A duplicate makes url(#fg) resolve to whichever copy came
            # first, and a folder loses its face when that one is hidden.
            ("iconset-ids-unique",
             "() => { const ids = Array.from(document.querySelectorAll('[id]'))"
             ".map(e => e.id);"
             " const dupes = ids.filter((v, i) => ids.indexOf(v) !== i);"
             " return [ids.length > 100, dupes.slice(0, 3)]; }",
             [True, []]),
            # The Icons page. It has to open, draw one cell per category with a
            # real glyph in it, and its chooser has to be the thing that
            # changes the file list, not a second copy of the setting that
            # only redraws its own sheet.
            ("settings-icons-page",
             "() => { document.getElementById('side-settings').click();"
             " const nav = document.querySelector('[data-snav=\"icons\"]');"
             " if (!nav) return ['no-nav']; nav.click();"
             " const pane = document.getElementById('spane-icons');"
             " if (!pane || pane.hidden) return ['no-pane'];"
             " const cells = pane.querySelectorAll('.iconsheet-cell');"
             " const drawn = Array.from(cells).filter("
             "c => c.querySelector('.iconsheet-art svg')).length;"
             " const named = Array.from(cells).map("
             "c => c.querySelector('.iconsheet-lbl').textContent);"
             " const sel = pane.querySelector('select[data-pref=\"iconSet\"]');"
             " const other = Object.keys(window.__iconSets)"
             ".find(k => k !== 'aurade');"
             " const norm = s => s.replace(/__c?\\d+/g, '');"
             " const one = () => norm(document.querySelector('.thumb svg')"
             ".outerHTML);"
             " document.getElementById('settings-back').click();"
             " const before = one();"
             " document.getElementById('side-settings').click(); nav.click();"
             " sel.value = other; sel.dispatchEvent(new Event('change'));"
             " const still = pane.querySelectorAll('.iconsheet-art svg').length;"
             " document.getElementById('settings-back').click();"
             " const after = one();"
             " document.getElementById('side-settings').click(); nav.click();"
             " sel.value = 'aurade'; sel.dispatchEvent(new Event('change'));"
             " document.getElementById('settings-back').click();"
             " return [cells.length, drawn === cells.length,"
             " named.indexOf('Folder'), !!sel, still === drawn,"
             " other ? before !== after : true, one() === before]; }",
             [29, True, 0, True, True, True, True]),
            # The About page. It has to state a version it can support, and the
            # three things hidden in the mark have to actually be there: seven
            # clicks, shift-click, and the konami code.
            ("about-page",
             "() => { document.getElementById('side-settings').click();"
             " document.querySelector('[data-snav=\"about\"]').click();"
             " const p = document.getElementById('spane-about');"
             " if (!p || p.hidden) return ['no-pane'];"
             " const ver = p.querySelector('.about-hero-d').textContent;"
             " const mark = p.querySelector('.aurade-mark');"
             " const img = p.querySelector('.mark-img');"
             " const fields = p.querySelectorAll('.mark-field').length;"
             " const btn = p.querySelector('.about-mark-btn');"
             " const cred = p.querySelector('.about-credits');"
             " const note = p.querySelector('.about-note');"
             " const shut = cred.hidden;"
             " for (let i = 0; i < 6; i++) btn.click();"
             " const six = cred.hidden;"
             " btn.click();"
             " const seven = !cred.hidden;"
             " btn.dispatchEvent(new MouseEvent('click',"
             " {bubbles: true, shiftKey: true}));"
             " const guides = mark.classList.contains('bloom-on');"
             " btn.dispatchEvent(new MouseEvent('click',"
             " {bubbles: true, shiftKey: true}));"
             " const guidesOff = !mark.classList.contains('bloom-on');"
             " const K = ['ArrowUp','ArrowUp','ArrowDown','ArrowDown',"
             "'ArrowLeft','ArrowRight','ArrowLeft','ArrowRight','b','a'];"
             " K.forEach(k => document.dispatchEvent("
             "new KeyboardEvent('keydown', {key: k, bubbles: true})));"
             " const libs = p.querySelectorAll('.lib-card').length;"
             " document.getElementById('settings-back').click();"
             " return [shut, six, seven, guides, guidesOff,"
             " !!img && img.src.indexOf('data:image/png') === 0, fields,"
             " mark.classList.contains('aurora-on'), !note.hidden,"
             " ver.indexOf('AuraDE Files 0.2') === 0,"
             " ver.indexOf('Build ') > 0, libs]; }",
             [True, True, True, True, True, True, 3, True, True, True,
              True, 7]),
            # Toolbar customization. The two lists have to be real (icons
            # cloned, not blanks), the ends of the added list have to be the
            # only disabled arrows, and removing a button has to take it off
            # the bar rather than only off the list. Ends on Reset so the
            # checks after it see the toolbar it shipped with.
            ("settings-toolbar-page",
             "() => { document.getElementById('side-settings').click();"
             " const nav = document.querySelector('[data-snav=\"toolbar\"]');"
             " if (!nav) return ['no-nav']; nav.click();"
             " const p = document.getElementById('spane-toolbar');"
             " if (!p || p.hidden) return ['no-pane'];"
             " const rows = () => Array.from("
             "p.querySelectorAll('#tb-added .tb-row'));"
             " const avail = () => p.querySelectorAll('#tb-avail .tb-row').length;"
             " const prev = () => p.querySelectorAll('.tb-preview-btn').length;"
             " const n0 = rows().length, a0 = avail(), v0 = prev();"
             " const icons = p.querySelectorAll('.tb-row-ico svg').length;"
             " const ups = rows().map(r => r.querySelectorAll('.tb-row-btn')[0].disabled);"
             " const downs = rows().map(r => r.querySelectorAll('.tb-row-btn')[1].disabled);"
             " const arrows = [ups.filter(Boolean).length, downs.filter(Boolean).length,"
             " ups[0], downs[downs.length - 1]];"
             " const second = rows()[1].querySelector('.tb-row-lbl').textContent;"
             " rows()[0].querySelectorAll('.tb-row-btn')[1].click();"
             " const swapped = rows()[0].querySelector('.tb-row-lbl').textContent;"
             " const gone = rows()[1].dataset.tbrow;"
             " rows()[1].querySelector('.tb-row-rm').click();"
             " const n1 = rows().length, a1 = avail();"
             " const onBar = !!document.querySelector("
             "'.toolbar [data-tb=\"' + gone + '\"]:not([hidden])');"
             " const s = p.querySelector('#tb-search');"
             " s.value = 'refresh'; s.dispatchEvent(new Event('input'));"
             " const filtered = avail();"
             " s.value = ''; s.dispatchEvent(new Event('input'));"
             " p.querySelector('#tb-reset').click();"
             " const n2 = rows().length;"
             " document.getElementById('settings-back').click();"
             " return [n0, a0, v0, icons === n0 + a0, arrows,"
             " swapped === second, n1 === n0 - 1, a1 === a0 + 1,"
             " onBar, filtered, n2]; }",
             [14, 8, 14, True, [1, 1, True, True], True, True, True,
              False, 1, 14]),
            ("art-16-live",
             "() => { const svgs = Array.from(document.querySelectorAll("
             "'.rows .ricobox svg, .list .ricobox svg'));"
             " return [svgs.length > 0,"
             " svgs.every(s => s.getAttribute('viewBox') === '0 0 16 16')]; }",
             [True, True]),
            ("props-file-tabs",
             "() => { const cells = Array.from(document.querySelectorAll('.cell'))"
             ".filter(c => c.tagName !== 'A'); cells[0].click();"
             " document.querySelector('.toolbar [data-act=\"ctx-props\"]').click();"
             # Each nav row is its own height and they sit together at the
             # top. .ptab carries flex:1 for the tab strip it was written
             # for, and in this column that stretched three tabs across the
             # whole dialog while every count and hidden check stayed true.
             " const rows = Array.from(document"
             ".querySelectorAll('.dlg-nav .ptab')).filter(t => !t.hidden)"
             ".map(t => t.getBoundingClientRect());"
             " const spans = rows.map(r => Math.round(r.height));"
             " const gaps = rows.slice(1).map((r, i) =>"
             " Math.round(r.top - rows[i].bottom));"
             " return [!document.getElementById('props').hidden,"
             " !document.querySelector('[data-ptab=\"details\"]').hidden,"
             " !document.querySelector('[data-ptab=\"hashes\"]').hidden,"
             " spans.every(h => h === 32), gaps.every(g => g === 2)]; }",
             [True, True, True, True, True]),
             ("preview-restores",
              "() => { document.getElementById('props').hidden = true;"
              " document.dispatchEvent(new KeyboardEvent('keydown',"
              " {key: 'Escape', bubbles: true}));"
              " const before = document.getElementById('ipart').innerHTML;"
              " const cells = Array.from(document.querySelectorAll('.cell'))"
              ".filter(c => c.tagName !== 'A'); cells[0].click();"
              " document.getElementById('btn-pane').click();"
              " const during = document.getElementById('ipart').innerHTML;"
              " document.dispatchEvent(new KeyboardEvent('keydown',"
              " {key: 'Escape', bubbles: true}));"
              " return [during !== before,"
              " document.getElementById('ipart').innerHTML === before]; }",
              [True, True]),
             ("preview-text-shows",
              "() => { const pane = document.getElementById('infopane');"
              " if (pane.hidden) document.getElementById('btn-pane').click();"
              " document.querySelector('[data-itab=\"preview\"]').click();"
              " const cells = Array.from(document.querySelectorAll('.grid .cell'))"
              ".filter(c => (c.getAttribute('data-pv') || '').length > 0);"
              " if (!cells.length) return ['NO-PV-CELL'];"
              " cells[0].click();"
              " const box = document.getElementById('ipreview-text');"
              " return [!box.hidden, box.textContent.length > 0,"
              " cells[0].getAttribute('data-pv').indexOf(box.textContent.slice(0, 20)) !== -1]; }",
              [True, True, True]),
             ("git-static-keeps-baked",
              "() => { const w = document.getElementById('git-wrap');"
              " const b = document.getElementById('git-branch');"
              " return [!!w, w ? w.hidden : null, b ? b.textContent : null,"
              " document.documentElement.getAttribute('data-git')]; }",
              [True, baked_hidden, baked_branch, None]),
             # The Shelf. Structure and behaviour together, because the pane
             # is only right if it is the reference's width, its rows are the
             # reference's height, and the three states it has (empty,
             # populated, something picked) each show what belongs to them.
             ("shelf-pane",
              "() => { const on = window.__shelf.toggle(true);"
              " const pane = document.getElementById('shelf');"
              " const w = Math.round(pane.getBoundingClientRect().width);"
              " const emptyArt = document.querySelector('.shelf-art');"
              " const artBox = emptyArt.getBoundingClientRect();"
              " const added = window.__shelf.add(["
              " {path: '/tmp/a.txt', name: 'a.txt'},"
              " {path: '/tmp/pics', kind: 'File folder'},"
              " {path: '/tmp/a.txt'}]);"
              " const rows = Array.from(document.querySelectorAll('.shelf-item'));"
              " const names = rows.map(r => r.querySelector('.shelf-name')"
              ".textContent).join(',');"
              " const icons = rows.every(r => !!r.querySelector('.shelf-ico svg'));"
              " const h = Math.round(rows[0].getBoundingClientRect().height);"
              " const state = [document.getElementById('shelf-empty').hidden,"
              " document.getElementById('shelf-foot').hidden,"
              " document.getElementById('shelf-batch-wrap').hidden];"
              " rows[0].click();"
              " const afterPick = document.getElementById"
              "('shelf-batch-wrap').hidden;"
              " window.__shelf.clear();"
              " const cleared = [document.querySelectorAll('.shelf-item').length,"
              " document.getElementById('shelf-empty').hidden,"
              " document.getElementById('shelf-foot').hidden];"
              " window.__shelf.toggle(false);"
              " return [on, w, added, names, icons, h, state, afterPick,"
              " cleared, artBox.width > 40 && artBox.height > 20,"
              " document.getElementById('shelf').hidden]; }",
              [True, 240, 2, "a.txt,pics", True, 36, [True, False, True],
               False, [0, False, True], True, True]),
             # A pressed toolbar button paints its glyph in the on-accent
             # colour. Filling every layer with one flat colour is what turned
             # the details pane button into a solid block, so what is asserted
             # is that the layers stay apart, not that the fill changed.
             ("toolbar-pressed-layers",
              "() => { const b = document.getElementById('btn-pane');"
              " const fills = () => new Set(Array.from("
              "b.querySelectorAll('svg path'))"
              ".map(p => getComputedStyle(p).fill));"
              " b.setAttribute('aria-pressed', 'false');"
              " const off = fills();"
              " b.setAttribute('aria-pressed', 'true');"
              " const on = fills();"
              " const bg = getComputedStyle(b).backgroundColor;"
              " b.setAttribute('aria-pressed', 'false');"
              # A translucent fill is the backing layer surviving. Without one
              # the frame, the panel and the backing are a single solid shape,
              # and base and accent legitimately share a colour here, so the
              # count alone would not say it.
              " const soft = Array.from(on).some(f =>"
              " f.indexOf('rgba') === 0 || f.indexOf('/') !== -1);"
              " return [off.size, on.size >= 2, soft,"
              " bg !== 'rgba(0, 0, 0, 0)']; }",
              [3, True, True, True]),
             ("preview-hides-for-folder",
              "() => { document.dispatchEvent(new KeyboardEvent('keydown',"
              " {key: 'Escape', bubbles: true}));"
              " const box = document.getElementById('ipreview-text');"
              " return [box.hidden, box.textContent === '']; }",
              [True, True]),
            ("selection-transfers",
             "() => { const g = Array.from(document.querySelectorAll('[data-act]'))"
             ".find(x => x.getAttribute('data-act') === 'lay-grid'); g.click();"
             " const cells = Array.from(document.querySelectorAll('.grid .cell'))"
             ".filter(c => c.tagName !== 'A'); cells[0].click();"
             " const name = cells[0].getAttribute('data-n');"
             " Array.from(document.querySelectorAll('[data-act]'))"
             ".find(x => x.getAttribute('data-act') === 'lay-details').click();"
             " const kept = Array.from(document.querySelectorAll('.dbody .row.sel'))"
             ".map(r => r.getAttribute('data-n'));"
             " return [kept.indexOf(name) !== -1,"
             " document.getElementById('st-sel').textContent]; }",
             [True, "1 item selected"]),
             ("kbd-arrows",
              "() => { const hw = document.getElementById('home-widgets');"
              " if (hw) hw.hidden = true; window.__setLayout('grid');"
              " document.querySelectorAll('.grid .cell.sel').forEach(x => x.classList.remove('sel'));"
              #: With the code as well as the key, which is what a real
              #: keyboard sends and what the shortcut table matches on.
              " const kd = k => document.dispatchEvent(new KeyboardEvent('keydown',"
              " {key: k, code: k, bubbles: true}));"
              " kd('Escape');"
              " kd('ArrowDown');"
              " const a = document.querySelector('.kbd')?.getAttribute('data-n');"
              " kd('ArrowRight');"
              " const b = document.querySelector('.kbd')?.getAttribute('data-n');"
              " kd('ArrowLeft');"
              " const c = document.querySelector('.kbd')?.getAttribute('data-n');"
              " return [!!a, !!b && b !== a, c === a,"
              " document.querySelectorAll('.grid .cell.sel').length]; }",
              [True, True, True, 1]),
             ("kbd-type",
              "() => { const items = Array.from(document.querySelectorAll('.grid .cell'))"
              ".filter(c => c.offsetParent !== null && c.style.display !== 'none');"
              " const seed = items.find(c => c.tagName !== 'A').getAttribute('data-n') || '';"
              " document.dispatchEvent(new KeyboardEvent('keydown',"
              " {key: seed[0], bubbles: true}));"
              " const want = items.find(c => ((c.getAttribute('data-n') || '')"
              ".toLowerCase().startsWith(seed[0].toLowerCase()))).getAttribute('data-n');"
              " return document.querySelector('.kbd')?.getAttribute('data-n') === want; }",
              True),
             ("kbd-details-down",
              "() => { window.__setLayout('details');"
              " document.dispatchEvent(new KeyboardEvent('keydown',"
              " {key: 'ArrowDown', bubbles: true}));"
              " const a = document.querySelector('.kbd')?.getAttribute('data-n');"
              " document.dispatchEvent(new KeyboardEvent('keydown',"
              " {key: 'ArrowDown', bubbles: true}));"
              " const b = document.querySelector('.kbd')?.getAttribute('data-n');"
              " return [!!a, !!b && b !== a,"
              " document.querySelectorAll('.rows .row.sel').length]; }",
              [True, True, 1]),
             ("name-dialog-rename",
              "() => { window.__setLayout('grid');"
              " const cell = Array.from(document.querySelectorAll('.grid .cell'))"
              ".find(c => c.tagName !== 'A' && c.getAttribute('data-k') !== 'Folder');"
              " cell.click();"
              " document.dispatchEvent(new KeyboardEvent('keydown',"
              " {key: 'F2', bubbles: true}));"
              " const open = !document.getElementById('namedlg').hidden;"
              " const inp = document.getElementById('namedlg-input');"
              " inp.value = 'renamed-by-suite.txt';"
              " document.getElementById('namedlg-ok').click();"
              " return [open, cell.getAttribute('data-n'),"
              " document.getElementById('namedlg').hidden]; }",
              [True, 'renamed-by-suite.txt', True]),
             ("name-dialog-rejects",
              "() => { const cell = Array.from(document.querySelectorAll('.grid .cell'))"
              ".find(c => c.tagName !== 'A' && c.getAttribute('data-k') !== 'Folder');"
              " cell.click();"
              " document.dispatchEvent(new KeyboardEvent('keydown',"
              " {key: 'F2', bubbles: true}));"
              " const inp = document.getElementById('namedlg-input');"
              " inp.value = 'bad/name?.txt';"
              " document.getElementById('namedlg-ok').click();"
              " const err = !document.getElementById('namedlg-err').hidden"
              " && !document.getElementById('namedlg').hidden;"
              " document.dispatchEvent(new KeyboardEvent('keydown',"
              " {key: 'Escape', bubbles: true}));"
              " return [err, document.getElementById('namedlg').hidden,"
              " cell.getAttribute('data-n')]; }",
              [True, True, 'renamed-by-suite.txt']),
             ("submenu-no-fake-group",
              "() => document.querySelectorAll('[data-sort-group=\"group-field\"]').length",
              0),
             # Choosing a field is choosing a field. Files' SortOption setter
             # writes the option and leaves the direction as the person left
             # it, so a descending list stays descending when the column
             # changes, and the field, the attribute and the kind of compare
             # all move together.
             ("submenu-sort-created",
              "() => { window.__runCommand('SortDescending');"
              " document.querySelector("
              "'#ctx-bg [data-command=\"SortByDateCreated\"]').click();"
              " const s = window.__sortState;"
              " const first = [s.fieldName, s.attr, s.numeric, s.dir];"
              " document.querySelector("
              "'#ctx-bg [data-command=\"SortByName\"]').click();"
              " return first.concat([s.fieldName, s.attr, s.dir]); }",
              ['Date created', 'data-ms', True, -1, 'Name', 'data-n', -1]),
             ("submenu-openloc",
              "() => !!document.querySelector("
              "'#ctx-file [data-command=\"OpenFileLocation\"]')",
              True),
             # New shortcut is the reference's CreateShortcutDialog: the
             # location and the name in one dialog, whose Create button is
             # greyed until both are filled, and a name with no .lnk on it,
             # because that is a Windows shortcut file and this makes a link.
             ("submenu-newshortcut",
              "() => (async () => {"
              " const w = ms => new Promise(r => setTimeout(r, ms));"
              " window.__doAct('newshortcut'); await w(50);"
              " const d = document.getElementById('dlg-createshortcut');"
              " const open = !d.hidden;"
              " const go = d.querySelector('[data-dlg=\"primary\"]');"
              " const greyed = go.disabled;"
              " const type = (id, v) => { const b = document.getElementById(id);"
              "  b.value = v; b.dispatchEvent(new Event('input', {bubbles: true})); };"
              " type('cs-path', '/root'); type('cs-name', 'link-by-suite');"
              " const ready = !go.disabled;"
              " go.click(); await w(50);"
              " const made = Array.from(document.querySelectorAll('.grid .cell'))"
              ".some(c => c.getAttribute('data-n') === 'link-by-suite');"
              " return [open, greyed, ready, made, d.hidden]; })()",
              [True, True, True, True, True]),
             # New is AddItemDialog in the reference, and what is picked
             # there is what gets made: AddItemAction.ExecuteAsync.
             ("new-opens-the-item-dialog",
              "() => (async () => {"
              " const w = ms => new Promise(r => setTimeout(r, ms));"
              " window.__runCommand('AddItem'); await w(50);"
              " const d = document.getElementById('dlg-additem');"
              " const open = !d.hidden;"
              " const rows = Array.from(d.querySelectorAll('[data-pick]'))"
              ".map(b => b.getAttribute('data-pick'));"
              " d.querySelector('[data-pick=\"folder\"]').click(); await w(50);"
              " const asked = !document.getElementById('namedlg').hidden"
              " && document.getElementById('namedlg-title').textContent;"
              " document.dispatchEvent(new KeyboardEvent('keydown',"
              " {key: 'Escape', bubbles: true}));"
              " return [open, rows, d.hidden, asked]; })()",
              [True, ['folder', 'file', 'shortcut'], True, 'New folder']),
             # Rename with more than one item selected is Bulk rename, whose
             # button is greyed for an empty name and for one with a dot in
             # it, and which gives every item the typed name plus its own
             # extension: RenameAction, BulkRenameDialogViewModel.
             ("rename-more-than-one-is-a-bulk-rename",
              "() => (async () => {"
              " const w = ms => new Promise(r => setTimeout(r, ms));"
              " window.__setLayout('grid');"
              " const cells = Array.from(document.querySelectorAll('.grid .cell'))"
              ".filter(c => c.tagName !== 'A' && c.getAttribute('data-k') !== 'Folder'"
              " && /\\./.test(c.getAttribute('data-n') || '')).slice(0, 2);"
              " if (cells.length < 2) return 'fewer than two files';"
              " cells[0].click(); cells[1].classList.add('sel');"
              " window.__doAct('rename'); await w(50);"
              " const d = document.getElementById('dlg-bulkrename');"
              " const open = !d.hidden;"
              " const go = d.querySelector('[data-dlg=\"primary\"]');"
              " const empty = go.disabled;"
              " const box = document.getElementById('br-name');"
              " const type = v => { box.value = v;"
              "  box.dispatchEvent(new Event('input', {bubbles: true})); };"
              " type('with.dot'); const dotted = go.disabled;"
              " type('bulk-by-suite'); const ready = !go.disabled;"
              " const exts = cells.map(c => c.getAttribute('data-n').slice("
              "  c.getAttribute('data-n').lastIndexOf('.')));"
              " go.click(); await w(50);"
              " const names = cells.map(c => c.getAttribute('data-n'));"
              " return [open, empty, dotted, ready, d.hidden,"
              "  names[0] === 'bulk-by-suite' + exts[0],"
              "  names[1] === 'bulk-by-suite' + exts[1]]; })()",
              [True, True, True, True, True, True, True]),
             # Delete asks through FilesystemOperationDialog, with the
             # reference's title and line, Cancel leaves the item and Delete
             # takes it. It was confirm(), twice in a row, on one path and
             # nothing at all on the other.
             ("delete-asks-through-the-operation-dialog",
              "() => (async () => {"
              " const w = ms => new Promise(r => setTimeout(r, ms));"
              " window.__setLayout('grid');"
              " const cell = Array.from(document.querySelectorAll('.grid .cell'))"
              ".find(c => c.tagName !== 'A' && c.getAttribute('data-k') !== 'Folder');"
              " const name = cell.getAttribute('data-n');"
              " cell.click(); window.__runCommand('DeleteItem'); await w(80);"
              " const d = document.getElementById('dlg-fsop');"
              " const asked = [!d.hidden,"
              "  document.getElementById('dlg-fsop-t').textContent,"
              "  document.getElementById('fsop-what').textContent,"
              "  d.querySelector('[data-dlg=\"primary\"]').textContent,"
              "  !document.getElementById('fsop-perm-row').hidden,"
              "  document.getElementById('fsop-permanent').checked];"
              " d.querySelector('[data-dlg=\"close\"]').click(); await w(80);"
              " const still = !!cell.parentElement;"
              " cell.click(); window.__runCommand('DeleteItem'); await w(80);"
              " d.querySelector('[data-dlg=\"primary\"]').click(); await w(80);"
              " return asked.concat([still, !!cell.parentElement, d.hidden]); })()",
              [True, 'Delete item', 'One item will be deleted', 'Delete',
               True, False, True, False, True]),
             # A command works on the selection, as in the reference, where
             # a right click selects first. This page kept the item under
             # the last right click and let it win: right click A, select B,
             # Delete, and the dialog named one item and A went. And the
             # menu's own Delete row was taken for the item, so it asked
             # about "item" and deleted nothing.
             ("a-command-reaches-the-selection-not-the-last-right-click",
              "() => (async () => {"
              " const w = ms => new Promise(r => setTimeout(r, ms));"
              " window.__setLayout('grid');"
              " const cells = Array.from(document.querySelectorAll('.grid .cell'))"
              ".filter(c => c.tagName !== 'A' && c.getAttribute('data-k') !== 'Folder');"
              " if (cells.length < 2) return 'fewer than two files';"
              " const [a, b] = cells;"
              " const names = () => Array.from(document.querySelectorAll('#fsop-rows .cdlg-lbl'))"
              ".map(r => r.textContent);"
              " a.dispatchEvent(new MouseEvent('contextmenu', {bubbles: true, clientX: 400, clientY: 300}));"
              " await w(30);"
              " document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));"
              " b.click(); await w(30);"
              " window.__runCommand('DeleteItem'); await w(80);"
              " const d = document.getElementById('dlg-fsop');"
              " const askedB = [!d.hidden, names()];"
              " d.querySelector('[data-dlg=\"primary\"]').click(); await w(80);"
              " const bGone = !b.parentElement && !!a.parentElement;"
              " a.dispatchEvent(new MouseEvent('contextmenu', {bubbles: true, clientX: 400, clientY: 300}));"
              " await w(30);"
              " const row = document.querySelector('#ctx-file [data-command=\"DeleteItem\"]');"
              " row.click(); await w(80);"
              " const askedA = [!d.hidden, names()];"
              " d.querySelector('[data-dlg=\"primary\"]').click(); await w(80);"
              " return [askedB[0], askedB[1].length, bGone, askedA[0], askedA[1].length,"
              "  !a.parentElement, askedB[1][0] === b.getAttribute('data-n'),"
              "  askedA[1][0] === a.getAttribute('data-n')]; })()",
              [True, 1, True, True, 1, True, True, True]),
             # Reorder sidebar items, from the sidebar's own menu row, which
             # was drawn and reached nothing: the pinned rows in a dialog,
             # dragged into an order, and Save puts the sidebar in it and
             # keeps it for the next load.
             ("reorder-sidebar-items-through-the-dialog",
              "() => (async () => {"
              " const w = ms => new Promise(r => setTimeout(r, ms));"
              " const before = window.__pinned.rows().map(r => r.name);"
              " const row = document.querySelector("
              "  '#ctx-side [data-act=\"sidebar-reorder\"]');"
              " window.__doAct('sidebar-reorder'); await w(80);"
              " const d = document.getElementById('dlg-reorder');"
              " const items = Array.from(d.querySelectorAll('#reorder-rows [data-key]'));"
              " const listed = items.map(i => i.textContent);"
              " items[0].parentNode.appendChild(items[0]);"
              " d.querySelector('[data-dlg=\"primary\"]').click(); await w(80);"
              " const after = window.__pinned.rows().map(r => r.name);"
              " const kept = JSON.parse(localStorage.getItem('aurade_pinned_order') || '[]');"
              " return [!!row, d.hidden, listed.length === before.length,"
              "  listed.join() === before.join(),"
              "  after.join() === before.slice(1).concat(before[0]).join(),"
              "  kept.length === before.length]; })()",
              [True, True, True, True, True, True]),
             # A dialog's select with no options is a caption with nothing
             # behind it. The format and level boxes shipped that way once,
             # with the text of a Python expression where the options should
             # have been, and every caption gate stayed green.
             ("dialog-selects-hold-options",
              "() => Array.from(document.querySelectorAll('.cdlg-body select'))"
              ".filter(s => !s.options.length && !s.hasAttribute('data-fills'))"
              ".map(s => s.id)",
              []),
            # Both context menus are generated from assets/files-menus.json,
            # so what is worth asserting is that the generating worked: the
            # commands the reference puts in each menu, in its order, are the
            # commands the page put there. Read off the rendered DOM rather
            # than the source, because the source is not what a person opens.
            # When a command can run is read out of the reference's own
            # `IsExecutable` and turned into a predicate, so it is worth
            # asking the predicates directly rather than only through the
            # menus: Home is where the answers differ most, and Properties is
            # the one whose condition is a disjunction inside a conjunction,
            # which is the shape that goes wrong when the brackets are lost.
            ("a-command-knows-when-it-cannot-run",
             #: Home is put on rather than navigated to, because by this
             #: point in the round the page is wherever the gates before it
             #: left it, and what is being asked about is the predicate.
             "() => { window.__clearSelection();"
             " const hw = document.getElementById('home-widgets');"
             " const was = hw.hidden; hw.hidden = false;"
             " const can = c => window.__commands.get(c).enabled();"
             " const out = [can('OpenClassicProperties'), can('CreateFolder'),"
             "  can('FormatDrive'), can('CopyItem'), can('LayoutColumns')];"
             " hw.hidden = was; return out; }",
             #: On Home there is no folder to make anything in, no drive to
             #: format and nothing selected to copy, and Columns is the one
             #: that only asks not to be in the recycle bin.
             [False, False, False, False, True]),
            # The Home menu's widget list is the only place a widget can be
            # turned off, and each row is bound to a setting rather than to a
            # command, so the rows gate above says nothing about them. Two
            # kinds here on purpose: Drives goes through the preference
            # store, Tags through the section itself.
            ("home-menu-turns-a-widget-off-and-on",
             "() => { const go = (w) => {"
             "  const row = document.querySelector("
             "   '#ctx-home [data-widget=\"' + w + '\"]');"
             "  const sec = document.getElementById('wsec-' + w);"
             "  const ck = document.getElementById('ck-w-' + w);"
             "  if (!row || !sec || !ck) return ['no row for ' + w];"
             "  row.click();"
             "  const off = [sec.hidden, ck.classList.contains('on')];"
             "  row.click();"
             "  return off.concat([sec.hidden, ck.classList.contains('on')]);"
             " }; return go('drives').concat(go('tags'))"
             "  .concat(go('network')); }",
             #: Hidden and unchecked after the first click, back after the
             #: second, all three ways round. Network is the one that was
             #: drawn and did nothing, because the page had no section for it.
             [True, False, False, True, True, False, False, True,
              True, False, False, True]),
            # Files lists its widgets in one order in HomeViewModel and the
            # same order in the Home menu. This page had Recent files above
            # File tags and no network section at all, which no count could
            # see: five sections against five toggles still reads as five.
            ("home-shows-the-widgets-in-the-reference-order",
             "() => Array.from(document.querySelectorAll("
             "'#home-widgets .wsec')).map(s => s.getAttribute('data-widget'))",
             ["quickaccess", "drives", "network", "tags", "recent"]),
            # A menu nobody can open is not a menu. Both of these were in the
            # table and in nothing else for eight passes, and the rows gates
            # would have passed on them the moment they were built, because
            # those read the markup rather than reaching it. This one asks
            # the dispatcher, which is the part that was missing.
            ("widget-cards-open-their-own-menu",
             "() => { const hw = document.getElementById('home-widgets');"
             " const was = hw.hidden; hw.hidden = false;"
             " const shown = () => Array.from("
             "  document.querySelectorAll('.ctx'))"
             "  .filter(m => !m.hidden).map(m => m.id);"
             " const hit = (sel) => { const el = document.querySelector(sel);"
             "  if (!el) return 'no ' + sel;"
             "  el.dispatchEvent(new MouseEvent('contextmenu',"
             "   {bubbles: true, clientX: 200, clientY: 200}));"
             "  const out = shown();"
             "  document.dispatchEvent(new KeyboardEvent('keydown',"
             "   {key: 'Escape', bubbles: true}));"
             "  return out.join(',') || 'nothing opened'; };"
             " const out = [hit('.wnet-card'), hit('.wtag-item'),"
             "  hit('.wcard-drive'), hit('.wcard-folder'),"
             "  hit('.wrecent-row')];"
             " hw.hidden = was; return out; }",
             #: One menu each, and the five are five different menus: a card
             #: that falls through to the drive menu is the failure this is
             #: for.
             ["ctx-network", "ctx-filetags", "ctx-drive", "ctx-qa",
              "ctx-recent"]),
            ("context-menu-over-a-file-carries-the-reference-rows",
             "() => Array.from(document.querySelectorAll("
             "'#ctx-file [data-command]')).map(r =>"
             " r.getAttribute('data-command'))",
             menu_commands(menu_table()["content"], "item")),
            ("context-menu-over-the-background-carries-the-reference-rows",
             "() => Array.from(document.querySelectorAll("
             "'#ctx-bg [data-command]')).map(r =>"
             " r.getAttribute('data-command'))",
             menu_commands(menu_table()["content"], "background")),
            # And the four the widgets and the sidebar open, which Files
            # builds the same way in five view models. Every one of them is
            # generated from the same table by the same walk, so what is
            # checked is the same thing: the reference's commands, in the
            # reference's order, read off the page that was built.
        ] + [
            (f"context-menu-{key}-carries-the-reference-rows",
             "() => Array.from(document.querySelectorAll("
             f"'#{menu} [data-command]')).map(r =>"
             " r.getAttribute('data-command'))",
             menu_commands(menu_table()[key], side))
            for menu, key, side in MENUS_DRAWN if side is None
        ] + [
            # Every row in the tab menu reaches something. Six are commands
            # and one, Move tab to new window, is a handler of Files' own
            # with no command behind it, so it is the row most easily left
            # drawn and dead.
            ("context-menu-tab-rows-all-reach-something",
             "() => Array.from(document.querySelectorAll('#ctx-tab .mi'))"
             ".map(r => r.getAttribute('data-command')"
             "  || r.getAttribute('data-act')"
             "  || ('reaches nothing: ' + r.querySelector('.mi-t').textContent))",
             ["NewTab", "DuplicateSelectedTab", "tab-movewin",
              "CloseTabsToTheLeftSelected", "CloseTabsToTheRightSelected",
              "CloseOtherTabsSelected", "ReopenClosedTab"]),
            # Order alone would pass with every row flattened into one list,
            # and Sort by holding thirteen rows is most of what the menu is.
            ("context-menu-nests-like-the-reference",
             "() => Array.from(document.querySelectorAll('#ctx-bg .mi-sub'))"
             ".map(s => [s.querySelector('.mi .mi-t').textContent,"
             "  Array.from(s.querySelectorAll("
             "   ':scope > .ctx-sub > .mi[data-command]'))"
             "  .map(r => r.getAttribute('data-command'))])",
             [[label, kids] for label, kids
              in menu_submenus(menu_table()["content"], "background")]),
            # The rows Files fills from the Windows shell. They hold their
            # place and stay out of sight: a row that says Loading for ever is
            # worse than no row.
            ("context-menu-shell-slots-stay-out-of-sight",
             "() => Array.from(document.querySelectorAll("
             "'#ctx-file [data-slot]')).map(r =>"
             " [r.getAttribute('data-slot'), r.hidden])",
             [["openwith-overflow", True], ["sendto-overflow", True],
              ["bitlocker-on", True], ["bitlocker-manage", True],
              ["overflow-separator", True], ["item-overflow", True]]),
            # `ContextMenuFlyoutItemViewModelBuilder` gives a row no visibility
            # of its own unless the factory states one, and then shows it only
            # while the command can run. Opening the background menu with
            # nothing selected is the case where that decides the menu: Cut
            # goes, and Paste stays and goes grey, because the factory states
            # Paste's visibility and says nothing about Cut's.
        ]
        # The background context menu belongs to a folder. Home answers a
        # right click with the Home menu, which is a different menu with
        # different rows, so the gates that open the background menu run on a
        # folder page and the rest of round1 stays where it was.
        in_a_folder = [
            # A settings row that stores a preference and changes nothing is
            # the same defect as a menu row that reaches nothing, and the
            # rows gate above cannot see it: it asks whether a control with
            # that name exists. This one flips each setting and looks at the
            # page. The list grows as each one is wired; a setting that is
            # only stored is named in GOAL.md rather than counted here.
            ("settings-that-change-the-page-do",
             "() => { const set = window.__setPref;"
             " const was = k => window.__getPref(k);"
             " const out = [];"
             " const keep = {};"
             " const flip = (k, v, read) => { keep[k] = was(k); set(k, v);"
             "  out.push(read()); };"
             " flip('showThumbnails', false, () =>"
             "  document.documentElement.classList.contains('no-thumbs'));"
             " flip('showToolbar', false, () =>"
             "  document.querySelector('.toolbar').hidden);"
             " flip('showShelfBtn', false, () =>"
             "  document.getElementById('btn-shelf').hidden);"
             " flip('showStatusbar', false, () =>"
             "  document.querySelector('.status').hidden);"
             " flip('sortBy', 'Size', () => window.__sortState.fieldName);"
             " flip('sortDesc', true, () => window.__sortState.dir);"
             " flip('groupByProperty', 'Type', () =>"
             "  document.querySelectorAll('.group-header').length > 0);"
             " Object.keys(keep).forEach(k => set(k, keep[k]));"
             " out.push(document.documentElement.classList"
             "  .contains('no-thumbs'));"
             " out.push(document.querySelector('.toolbar').hidden);"
             " return out; }",
             #: Each one takes hold, and every one of them lets go again.
             [True, True, True, True, "Size", -1, True, False, False]),
            # And the same five in a folder, where four of the five change
            # their answer.
            ("a-command-knows-when-it-can",
             "() => { window.__clearSelection();"
             " const can = c => window.__commands.get(c).enabled();"
             " const empty = [can('OpenClassicProperties'), can('CreateFolder'),"
             "  can('FormatDrive'), can('CopyItem')];"
             " document.querySelector('.cell').click();"
             " return empty.concat([can('FormatDrive'), can('CopyItem')]); }",
             #: Format is the one that wants nothing selected, so it is the
             #: one that goes the other way when something is.
             [True, True, True, False, False, True]),
            ("context-menu-leaves-out-what-cannot-run",
             "() => { window.__clearSelection();"
             " document.getElementById('filearea').dispatchEvent("
             "  new MouseEvent('contextmenu',"
             "   {bubbles: true, clientX: 300, clientY: 300}));"
             " const menu = document.getElementById('ctx-bg');"
             " const at = (sel) => menu.querySelector(sel);"
             " const out = [menu.hidden,"
             "  at('[data-command=\"CutItem\"]').hidden,"
             "  at('[data-command=\"CopyItem\"]').hidden,"
             "  at('[data-command=\"PasteItemToSelection\"]').hidden,"
             "  at('[data-command=\"CreateFolder\"]').hidden,"
             "  at('[data-command=\"FormatDrive\"]').hidden,"
             "  at('[data-command=\"RotateLeft\"]').hidden,"
             "  at('[data-command=\"RotateLeft\"]').classList.contains('dis')];"
             " document.dispatchEvent(new KeyboardEvent('keydown',"
             "  {key: 'Escape', bubbles: true}));"
             " return out; }",
             #: The menu is open, Cut and Copy are gone because there is
             #: nothing to cut, Paste stays because the reference states its
             #: visibility outright, New folder stays because a folder can be
             #: made in a folder, and Format stays because it is the one row
             #: here that needs there to be no selection rather than one.
             #: Rotate is the case the two halves of the rule differ on: it
             #: cannot run with nothing selected, and the reference states its
             #: visibility outright, so it keeps its place and goes grey where
             #: Cut, which the reference says nothing about, goes.
             [False, True, True, False, False, False, False, True]),
            # And the other way round. The same row over a file, where the
            # command can run: shown, and not grey.
            ("context-menu-brings-back-what-can-run",
             "() => { const cell = document.querySelector('.cell');"
             " cell.click();"
             " cell.dispatchEvent(new MouseEvent('contextmenu',"
             "  {bubbles: true, clientX: 300, clientY: 300}));"
             " const at = (code) => document.querySelector("
             "  '#ctx-file [data-command=\"' + code + '\"]');"
             " const cut = at('CutItem');"
             " const out = [cut.hidden, cut.classList.contains('dis'),"
             "  at('FormatDrive').hidden];"
             " document.dispatchEvent(new KeyboardEvent('keydown',"
             "  {key: 'Escape', bubbles: true}));"
             " return out; }",
             #: And Format goes, for the same reason it stayed: something is
             #: selected now, and its condition is that nothing is.
             [False, False, True]),
            # A separator earns its place by having something on both sides of
            # it. Files asks the same question in AddSeparatorIfNeeded, and
            # without asking it a menu that hid a whole block shows two rules
            # with nothing between them.
            ("context-menu-separator-earns-its-place",
             "() => { document.querySelector('.cell').dispatchEvent("
             "  new MouseEvent('contextmenu',"
             "   {bubbles: true, clientX: 300, clientY: 300}));"
             " const m = document.getElementById('ctx-file');"
             " const seen = Array.from(m.children).filter(e => !e.hidden)"
             "  .map(e => e.classList.contains('msep') ? '-' : 'row');"
             " const doubled = seen.some((v, i) => v === '-'"
             "  && seen[i + 1] === '-');"
             " const out = [seen[0], seen[seen.length - 1], doubled];"
             " document.dispatchEvent(new KeyboardEvent('keydown',"
             "  {key: 'Escape', bubbles: true}));"
             " return out; }",
             ["row", "row", False]),
            # And the case that needs making, because the menus as they stand
            # never produce it: a block that goes leaves two separators
            # against each other. Close pane is the only row in the first
            # block of the background menu, so taking it out is the whole
            # block going. Its condition and its attribute go back afterwards.
            ("context-menu-separator-goes-when-its-block-does",
             "() => { const menu = document.getElementById('ctx-bg');"
             " const row = menu.querySelector("
             "  '[data-command=\"CloseActivePane\"]');"
             " const known = window.__commands.get('CloseActivePane');"
             " const was = known.enabled;"
             " row.removeAttribute('data-keep');"
             " known.enabled = () => false;"
             " document.getElementById('filearea').dispatchEvent("
             "  new MouseEvent('contextmenu',"
             "   {bubbles: true, clientX: 300, clientY: 300}));"
             " const seen = Array.from(menu.children).filter(e => !e.hidden)"
             "  .map(e => e.classList.contains('msep') ? '-' : 'row');"
             " const out = [row.hidden, seen[0],"
             "  seen.some((v, i) => v === '-' && seen[i + 1] === '-')];"
             " known.enabled = was;"
             " row.setAttribute('data-keep', '');"
             " document.dispatchEvent(new KeyboardEvent('keydown',"
             "  {key: 'Escape', bubbles: true}));"
             " return out; }",
             #: The row is gone, the menu still opens on a row rather than a
             #: rule, and the two separators that were around the row have
             #: become one.
             [True, "row", False]),
            # A toggle draws a check when it is on, the way WinUI draws one,
            # and the check follows the command rather than the click: sorting
            # from anywhere at all has to move it.
            ("context-menu-toggle-shows-its-state",
             "() => { const open = () =>"
             "  document.getElementById('filearea').dispatchEvent("
             "   new MouseEvent('contextmenu',"
             "    {bubbles: true, clientX: 300, clientY: 300}));"
             " const on = (code) => document.querySelector("
             "  '#ctx-bg [data-command=\"' + code + '\"] .ck')"
             "  .classList.contains('on');"
             " window.__runCommand('SortByName'); open();"
             " const first = [on('SortByName'), on('SortBySize')];"
             " window.__runCommand('SortBySize'); open();"
             " const out = first.concat([on('SortByName'), on('SortBySize')]);"
             " document.dispatchEvent(new KeyboardEvent('keydown',"
             "  {key: 'Escape', bubbles: true}));"
             " return out; }",
             [True, False, False, True]),
            # And the check follows the whole setting, not the last click. A
            # date is grouped by a field and by a unit, and Files marks the
            # unit rows against both: grouping by created and then by month
            # leaves Month on under Date created and off under Date modified.
            ("context-menu-toggle-reads-the-whole-setting",
             "() => { window.__runCommand('GroupByDateCreatedMonth');"
             " document.getElementById('filearea').dispatchEvent("
             "  new MouseEvent('contextmenu',"
             "   {bubbles: true, clientX: 300, clientY: 300}));"
             " const on = (code) => document.querySelector("
             "  '#ctx-bg [data-command=\"' + code + '\"] .ck')"
             "  .classList.contains('on');"
             " const out = [on('GroupByDateCreatedMonth'),"
             "  on('GroupByDateCreatedYear'),"
             "  on('GroupByDateModifiedMonth'),"
             "  window.__groupBy(), window.__groupUnit()];"
             " document.dispatchEvent(new KeyboardEvent('keydown',"
             "  {key: 'Escape', bubbles: true}));"
             " window.__runCommand('GroupByNone');"
             " return out; }",
             [True, False, False, "Date created", "month"]),
            # And they do what they say. Four of these seven had a row and
            # nothing behind it: Reopen and Close to the right were answered
            # only by a listener that watched for a click on a row carrying a
            # page action, so neither worked from the palette or a shortcut,
            # and Close to the left and Move to a new window were answered by
            # nobody at all.
            ("tab-commands-do-what-the-menu-says",
             "() => { const n = () => document.querySelectorAll('.tab').length;"
             " while (n() > 1) window.__runCommand('CloseSelectedTab');"
             " window.__runCommand('NewTab'); window.__runCommand('NewTab');"
             " window.__runCommand('NewTab');"
             " const four = n();"
             " window.__runCommand('CloseTabsToTheLeftSelected');"
             " const afterLeft = n();"
             " window.__runCommand('ReopenClosedTab');"
             " const afterReopen = n();"
             " window.__runCommand('NewTab');"
             " window.__runCommand('CloseTabsToTheRightSelected');"
             " return [four, afterLeft, afterReopen, n()]; }",
             #: Four tabs, the newest in front. Closing to the left of it
             #: leaves one, reopening the last closed makes two, and a new
             #: one makes three with nothing to its right to close.
             [4, 1, 2, 3]),
        ]
        for name, expr, want in round1:
            if want is None:
                if name == "props-opens-folder":
                    want = [True, ev(
                        "() => document.querySelector('.tname').textContent")]
                elif name == "props-file-hash":
                    got = ev(expr)
                    if got == "NO-HASHED-FILE":
                        check(name, got, "HAS-HASHED-FILE")
                    else:
                        check(name, got, [True, True, True])
                    continue
            check(name, ev(expr), want)

        # Every dialog Files has, opened and read. The table is generated
        # from src/Files.App/Dialogs; each of the reference's strings has to
        # be on the dialog once it is open, in its text, its placeholders or
        # its labels. tools/dialogs.py reads the markup for the same answer;
        # this asks the dialog that actually opens, which is the one that can
        # be missing a control the markup has, or hidden by the code that
        # fills it. The excused ones are named in tools/dialogs.py.
        _dlg_gone = {}
        for _did, _want in dialogs_wanted().items():
            _said = ev("() => (async () => {"
                       " const w = ms => new Promise(r => setTimeout(r, ms));"
                       " const p = window.__dialog.open(" + json.dumps(_did) + ");"
                       " await w(30);"
                       " const d = document.getElementById(" + json.dumps(_did) + ");"
                       " if (!d || d.hidden) return null;"
                       " const bits = [d.textContent];"
                       " d.querySelectorAll('[placeholder],[aria-label],[title]')"
                       "  .forEach(el => bits.push(el.getAttribute('placeholder') || '',"
                       "   el.getAttribute('aria-label') || '', el.getAttribute('title') || ''));"
                       " d.querySelectorAll('option').forEach(o => bits.push(o.textContent));"
                       " window.__dialog.close('close'); await p;"
                       " return bits.join(' ').replace(/\\s+/g, ' ').toLowerCase(); })()")
            if not isinstance(_said, str):
                _dlg_gone[_did] = ["did not open"] + _want
                continue
            _missing = [w for w in _want if w.rstrip(":").lower() not in _said]
            if _missing:
                _dlg_gone[_did] = _missing
        check("dialogs-carry-the-reference-captions", _dlg_gone, {})

        print("== keyboard nav ==")
        before = ev("() => document.querySelector('.tname').textContent")
        ev("() => { const f = Array.from(document.querySelectorAll('.cell'))"
           ".find(c => c.getAttribute('data-k') === 'Folder');"
           " if (f) { f.click(); }"
           " document.dispatchEvent(new KeyboardEvent('keydown',"
           " {key: 'Enter', code: 'Enter', bubbles: true})); return true; }")
        moved = False
        for _ in range(30):
            time.sleep(1)
            cur = ev("() => document.querySelector('.tname') &&"
                     " document.querySelector('.tname').textContent")
            if cur and cur != before:
                moved = True
                break
        check("kbd-enter-nav", moved, True)
        ev("() => { document.dispatchEvent(new KeyboardEvent('keydown',"
           " {key: 'Backspace', bubbles: true})); return true; }")
        restored = False
        for _ in range(30):
            time.sleep(1)
            cur = ev("() => document.querySelector('.tname') &&"
                     " document.querySelector('.tname').textContent")
            if cur == before:
                restored = True
                break
        check("kbd-backspace-up", restored, True)

        print("== screenshots ==")

        if sub:
            go(sub)
            for name, expr, want in in_a_folder:
                check(name, ev(expr), want)

        # A picture actually goes away. The gate above watches the class land
        # on the root element, and a mutation that deleted the rule that
        # class drives walked straight past it: the class is not the effect.
        # Only a couple of the built pages have a real thumbnail on them, so
        # which page to ask is found here rather than assumed, and finding
        # none is itself the answer.
        _with_a_picture = None
        for _name in sorted(os.listdir(os.path.join(ROOT, "site"))):
            if not _name.endswith(".html"):
                continue
            with open(os.path.join(ROOT, "site", _name),
                      encoding="utf-8") as _fh:
                if 'class="thumbimg"' in _fh.read():
                    _with_a_picture = _name
                    break
        if not _with_a_picture:
            check("thumbnails-off-hides-the-picture",
                  "no built page has a picture on it", "a page with one")
        else:
            go(f"http://127.0.0.1:{HTTP_PORT}/site/{_with_a_picture}")
            check("thumbnails-off-hides-the-picture",
                  ev("() => { const p = () =>"
                     "  document.querySelector('.thumb .thumbimg');"
                     " if (!p()) return 'no picture on this page';"
                     " const was = window.__getPref('showThumbnails');"
                     " const on = getComputedStyle(p()).display !== 'none';"
                     " window.__setPref('showThumbnails', false);"
                     " const off = getComputedStyle(p()).display;"
                     " const glyph = !!p().parentElement"
                     "  .querySelector('.art');"
                     " window.__setPref('showThumbnails', was);"
                     " const back = getComputedStyle(p()).display !== 'none';"
                     " return [on, off, glyph, back]; }"),
                  #: On to start with, gone when the switch is off, a glyph
                  #: underneath it rather than an empty square, and back.
                  [True, "none", True, True])

        go(home)
        ev("() => { document.documentElement.removeAttribute('data-theme');"
           " return true; }")
        shot("v3-dark.png")
        ev("() => { document.documentElement.dataset.theme = 'light';"
           " return true; }")
        shot("v3-light.png")
        ev("() => { document.documentElement.removeAttribute('data-theme');"
           " const g = Array.from(document.querySelectorAll('[data-act]'))"
           ".find(x => x.getAttribute('data-act') === 'lay-details');"
           " g.click(); return true; }")
        shot("v3-dark-details.png")
        ev("() => { document.documentElement.dataset.theme = 'light';"
           " return true; }")
        shot("v3-light-details.png")
        ev("() => { document.documentElement.removeAttribute('data-theme');"
           " const cells = Array.from(document.querySelectorAll('.cell'))"
           ".filter(c => c.tagName !== 'A'); cells[0].click();"
           " document.querySelector('.toolbar [data-act=\"ctx-props\"]').click();"
           " const det = document.querySelector('[data-ptab=\"details\"]');"
           " if (det) det.click(); return true; }")
        shot("v3-dark-props.png")

        # Mica. The materials are the one thing in this program whose whole
        # job is how it looks, so this is checked in pixels rather than in
        # custom properties: a variable can be perfectly set while the
        # backdrop is painted over by an opaque surface, which is exactly what
        # the sidebar did until --sidebar-bg was named too.
        ev("() => { document.documentElement.removeAttribute('data-theme');"
           " document.getElementById('settings-back') &&"
           " document.getElementById('settings-back').click();"
           " window.__mica.material('Solid'); return true; }")
        shot("mica-solid.png")
        ev("() => { window.__mica.material('Mica'); return true; }")
        shot("mica-mica.png")
        ev("() => { window.__mica.material('Acrylic'); return true; }")
        shot("mica-acrylic.png")
        ev("() => { window.__mica.material('Mica'); return true; }")
        # Sample points come from the elements, not from a guess: the suite's
        # viewport is not the one these were eyeballed at, and a point that
        # lands on the wrong surface tests nothing.
        pts = ev("() => { const r = s => { const e ="
                 " document.querySelector(s); if (!e) return null;"
                 " const b = e.getBoundingClientRect();"
                 " return [Math.round(b.left + b.width * 0.55),"
                 " Math.round(b.top + b.height / 2)]; };"
                 " return {bar: r('.titlebar'), side: r('.sidebar')}; }")
        try:
            from PIL import Image
            def px(name, pt):
                with Image.open(os.path.join(ROOT, name)) as im:
                    return im.convert("RGB").getpixel(tuple(pt))
            bar = [px("mica-%s.png" % m, pts["bar"])
                   for m in ("solid", "mica", "acrylic")]
            side = [px("mica-%s.png" % m, pts["side"])
                    for m in ("solid", "mica", "acrylic")]
            def lift(a, b):
                return sum(b) - sum(a)
            check("mica-paints-pixels",
                  [bar[0] == side[0],
                   lift(bar[0], bar[1]) > 12,
                   lift(bar[1], bar[2]) > 12,
                   lift(side[0], side[1]) > 12,
                   lift(side[1], side[2]) > 12,
                   bar[1] != side[1]],
                  [True, True, True, True, True, True])
        except ImportError:
            print("SKIP mica-paints-pixels (no Pillow)")

        print("== live backend checks ==")
        scratch = tempfile.mkdtemp(prefix="verify-live-")
        open(os.path.join(scratch, "note.txt"), "w").write("live data")
        # A hash inside a string literal and a real comment on the same line.
        # A highlighter that scans for keywords and comments separately gets
        # this wrong, which is the whole reason the tokenizer is one pass.
        open(os.path.join(scratch, "code.py"), "w").write(
            'name = "has # inside"  # real comment\n'
            'def go(n=512):\n    return n\n')
        # An HTML document carrying everything the sanitizer has to refuse:
        # a script, a stylesheet, a frame, a javascript: link and a
        # javascript: image, next to the markup that has to survive.
        open(os.path.join(scratch, "page.html"), "w").write(
            "<html><head><title>Report</title>"
            "<style>p{color:red}</style>"
            "<scr" + "ipt>window.PWNED = 1;</scr" + "ipt></head><body>"
            "<h1>Quarterly</h1>"
            # A second script and stylesheet, in the body this time: the head
            # is never walked, so a head-only fixture proves nothing about
            # the tags the copier is supposed to refuse.
            "<style>div{color:blue}</style>"
            "<scr" + "ipt>window.PWNED = 1;</scr" + "ipt>"
            "<p>Revenue was <b>up</b>, see "
            "<a href=\'javascript:window.PWNED=2\'>this</a> and "
            "<a href=\'https://example.com/q\'>the filing</a>.</p>"
            "<iframe src=\'https://evil.example\'></iframe>"
            "<table><tr><td>North</td><td>412</td></tr></table>"
            "<img src=\'javascript:3\'>"
            "</body></html>\n")
        # Rich text with a font table to skip, a bold run, an italic run,
        # two paragraphs and a hex escape.
        open(os.path.join(scratch, "doc.rtf"), "w").write(
            "{\\rtf1\\ansi{\\fonttbl{\\f0 Consolas;}}"
            "\\b Heading\\b0  and \\i slanted\\i0 \\par "
            "Second paragraph \\'41\\'42}\n")
        # A repository with one of each state the column has to name: a
        # tracked file that changed, a file git has never seen, and a change
        # one level down, which the folder above it has to report as its own.
        repo = os.path.join(scratch, "repo")
        have_git = shutil.which("git") is not None
        if have_git:
            os.makedirs(os.path.join(repo, "deep"))

            def _git(*args):
                return subprocess.run(
                    ["git", "-c", "user.email=verify@example.invalid",
                     "-c", "user.name=verify", "-c", "commit.gpgsign=false"]
                    + list(args), cwd=repo, capture_output=True, text=True)

            open(os.path.join(repo, "tracked.txt"), "w").write("one\n")
            open(os.path.join(repo, "deep", "inner.txt"), "w").write("a\n")
            _git("init", "-q", "-b", "main")
            _git("add", "-A")
            _git("commit", "-qm", "first")
            _git("branch", "feature")
            open(os.path.join(repo, "tracked.txt"), "w").write("two\n")
            open(os.path.join(repo, "fresh.txt"), "w").write("new\n")
            open(os.path.join(repo, "deep", "inner.txt"), "w").write("b\n")
        # A symlink, a broken symlink and a .desktop launcher: the three
        # shapes the Shortcut tab has to tell apart, plus a plain file that
        # must not get the tab at all.
        os.symlink("/etc/hostname", os.path.join(scratch, "good.link"))
        os.symlink("/nope/missing", os.path.join(scratch, "bad.link"))
        open(os.path.join(scratch, "term.desktop"), "w").write(
            "[Desktop Entry]\nType=Application\nName=Terminal\n"
            "Exec=/usr/bin/xterm -e bash\nPath=/tmp\n")
        # A PDF and a video: neither is an image, and both have to come back
        # from the one thumbnail endpoint anyway.
        have_pdf = have_vid = False
        try:
            from PIL import Image as _PILImg2, ImageDraw as _PILDraw
            _pdf = _PILImg2.new("RGB", (612, 792), "white")
            _PILDraw.Draw(_pdf).rectangle([60, 60, 552, 200], fill=(40, 90, 160))
            _pdf.save(os.path.join(scratch, "doc.pdf"), "PDF", resolution=72)
            have_pdf = shutil.which("pdftoppm") is not None
        except Exception:
            have_pdf = False
        if shutil.which("ffmpeg"):
            _r = subprocess.run(
                ["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi",
                 "-i", "testsrc=size=320x240:rate=10:duration=2",
                 "-pix_fmt", "yuv420p", "-y",
                 os.path.join(scratch, "clip.mp4")],
                capture_output=True, timeout=90)
            have_vid = _r.returncode == 0
        # Two folders that should not look the same: one of photographs, one
        # of source. Adaptive is only meaningful if it tells them apart.
        pics = os.path.join(scratch, "pics")
        srcd = os.path.join(scratch, "src")
        os.makedirs(pics, exist_ok=True)
        os.makedirs(srcd, exist_ok=True)
        for _i in range(4):
            open(os.path.join(srcd, f"m{_i}.py"), "w").write("def go():\n    pass\n")
        # A real image, so the thumbnail path is exercised end to end rather
        # than against a fixture that only looks like one.
        try:
            from PIL import Image as _PILImage
            _PILImage.new("RGB", (600, 400), (30, 90, 160)).save(
                os.path.join(scratch, "shot.png"))
            for _i in range(4):
                _PILImage.new("RGB", (120, 90), (20 * _i, 80, 150)).save(
                    os.path.join(pics, f"p{_i}.png"))
            have_pil = True
        except Exception:
            have_pil = False
        env = dict(os.environ)
        env["XDG_DATA_HOME"] = os.path.join(scratch, "xdg-data")
        env["AURADE_WALLPAPER"] = os.path.join(scratch, "shot.png")
        # Its own keyring, so signing a file here never touches the one this
        # machine actually uses and the check has something to check against.
        # Beside the scratch tree rather than inside it: a directory in there
        # is a row in the listing, and the gates that count rows would be
        # counting the test's own furniture.
        _keyring = tempfile.mkdtemp(prefix="verify-gnupg-")
        os.chmod(_keyring, 0o700)
        env["GNUPGHOME"] = _keyring
        # Which backend answers the API gates. The Python one is still the
        # default; AURADE_BACKEND=rust runs the replacement instead, so the
        # same gates prove both rather than one suite per backend.
        _rust = os.environ.get("AURADE_BACKEND", "").strip().lower() == "rust"
        _rust_bin = os.environ.get(
            "AURADE_BACKEND_BIN",
            "/mnt/build/aurade-work/auradefs/target/release/auradefs")
        if _rust and not os.path.exists(_rust_bin):
            print(f"FAIL AURADE_BACKEND=rust but {_rust_bin} is not built")
            raise SystemExit(2)
        _argv = ([_rust_bin, "--port", "8902"] if _rust
                 else [sys.executable, "backend.py"])
        backend = subprocess.Popen(
            _argv, env=env,
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(20):
                try:
                    with urllib.request.urlopen(
                            "http://127.0.0.1:8902/api/health",
                            timeout=3) as resp:
                        if json.load(resp).get("ok"):
                            break
                except Exception:
                    pass
                time.sleep(1)
            go(home)
            for _ in range(30):
                if ev("() => !!window.__livePath"):
                    break
                time.sleep(1)
            # Parity, as a number the suite holds rather than a claim in a
            # note. Every command Files has must be registered here under the
            # same name, and be either runnable or explicitly marked as having
            # no counterpart on this platform, with the reason kept.
            _table = json.load(open(os.path.join(
                ROOT, "assets", "files-commands.json")))["commands"]
            _states = ev("() => window.__commandStates ? "
                         "window.__commandStates() : null")
            _states = _states if isinstance(_states, dict) else {}
            _absent = sorted(set(_table) - set(_states))
            _stubs = sorted(k for k, v in _states.items() if v == "stub")
            _unknown = sorted(set(_states) - set(_table))
            _ready = sum(1 for v in _states.values() if v == "ready")
            _na = sum(1 for v in _states.values() if v == "unavailable")
            print(f"     commands: {_ready} ready, {_na} not on this platform,"
                  f" {len(_absent)} missing of {len(_table)}")
            check("commands-registered",
                  [len(_absent), len(_stubs), len(_unknown)],
                  [0, 0, 0])
            # And the shape of one, so a registry that is present but empty
            # cannot pass the count above.
            check("commands-carry-their-reference-text",
                  ev("() => { const c = window.__commands"
                     " && window.__commands.get('CopyItem');"
                     " return c ? [c.label, c.category, c.hotkeys[0],"
                     " typeof c.run] : 'no CopyItem'; }"),
                  ["Copy", "FileSystem", "Ctrl+C", "function"])

            check("live-upgrade",
                  ev("() => [document.body.getAttribute('data-live'),"
                     " typeof window.__liveOp]"), ["1", "function"])
            # Entering live mode asks the backend what it can do before the
            # first list is drawn, so a row that depends on the answer, Create
            # branch under the branch flyout, is right from the start. It was
            # asked lazily, by Properties or Compress, and until one of those
            # happened to run the git rows were greyed. Read before any gate
            # here asks for it, which is what makes this the gate that sees a
            # lazy ask.
            # Waited for by a point in the boot rather than by a clock. The
            # places paint runs immediately after the ask in enterLive, so
            # painted without capabilities is exactly the lazy ask this gate
            # exists to catch, while a three second budget was only ever
            # measuring how busy the machine was.
            check("live-mode-asks-what-the-backend-can-do-first",
                  ev("() => (async () => {"
                     " const w = ms => new Promise(r => setTimeout(r, ms));"
                     " for (let i = 0; i < 300 &&"
                     "  !(window.__places && window.__places.painted); i++)"
                     "   await w(100);"
                     " const c = window.__caps;"
                     " return [!!c, !!(c && Array.isArray(c.names) && c.names.length > 0),"
                     "  !!(c && Array.isArray(c.levels) && c.levels.length > 0)]; })()"),
                  # The Python backend names no capabilities and no levels,
                  # so against it the answer is only that the question was
                  # asked; the Rust one answers both.
                  [True, _rust, _rust])
            # The order the static gate saved is the order the sidebar came
            # back in after the page was loaded again.
            check("pinned-order-survives-a-load",
                  ev("() => (async () => {"
                     " const w = ms => new Promise(r => setTimeout(r, ms));"
                     " for (let i = 0; i < 100 && !(window.__places && window.__places.painted); i++) await w(100);"
                     " const rows = window.__pinned.rows().map(r => r.name);"
                     " return rows[rows.length - 1]; })()"), "Desktop")
            check("live-nav",
                  ev("() => (async () => { await window.__live.render(" +
                     json.dumps(scratch) + "); return window.__live.path; })()"),
                  scratch)
            # The scratch directory gained shot.png for the thumbnail checks,
            # so the expectation is both files, sorted, not just the note.
            # The sidebar is redrawn from /api/volumes when live mode
            # starts, so a page built on one machine shows the volumes of the
            # one it runs on. Home first, from the backend's own root; the
            # sections the reference has; every row a volume the backend
            # listed; and the window's idea of Home is the backend's.
            check("sidebar-is-the-backends",
                  ev("() => (async () => {"
                     " const w = ms => new Promise(r => setTimeout(r, ms));"
                     " for (let i = 0; i < 100 && !(window.__places && window.__places.painted); i++) await w(100);"
                     " const vols = (await (await fetch(window.__api + '/api/volumes')).json()).volumes;"
                     " const sys = await (await fetch(window.__api + '/api/system')).json();"
                     " const rows = Array.from(document.querySelectorAll('.slist .srow.item[data-root]'));"
                     " const roots = new Set(vols.map(v => v.root));"
                     " const home = vols.find(v => v.purpose === 'home');"
                     " const heads = Array.from(document.querySelectorAll('.slist .sgrp > .srow.head .lbl')).map(e => e.textContent);"
                     " const drives = rows.filter(r => r.getAttribute('data-kind') === 'drive');"
                     " return [rows.length > 0 && rows[0].getAttribute('data-root') === (home && home.root),"
                     "  heads, rows.filter(r => r.getAttribute('data-kind') !== 'drive' || !r.closest('.skids .sgrp'))"
                     "   .every(r => roots.has(r.getAttribute('data-root')) || r.closest('.sgrp[data-sec]:not([data-sec=\"Pinned\"]):not([data-sec=\"Drives\"]) .skids')),"
                     "  drives.length > 0 && drives.every(d => Number(d.getAttribute('data-total')) > 0),"
                     "  window.__homePath() === sys.home, window.__isHome(sys.home)]; })()"),
                  [True, ["Pinned", "Drives", "Network", "Tags"], True, True, True, True])
            check("home-widgets-are-the-backends",
                  ev("() => (async () => {"
                     " const vols = (await (await fetch(window.__api + '/api/volumes')).json()).volumes;"
                     " const rec = (await (await fetch(window.__api + '/api/recent?limit=20')).json()).recent || [];"
                     " const qa = Array.from(document.querySelectorAll('.wcards-qa .wcard-folder')).map(c => c.getAttribute('data-n'));"
                     " const want = ['desktop','downloads','documents','pictures','music','videos']"
                     "  .map(p => vols.find(v => v.purpose === p)).filter(Boolean).map(v => v.label);"
                     " const cards = Array.from(document.querySelectorAll('.wcards-drives .wcard-drive'));"
                     " const subs = cards.map(c => c.querySelector('.wd-sub').textContent);"
                     " const rows = document.querySelectorAll('.wrecent-list .wrecent-row').length;"
                     " return [JSON.stringify(qa) === JSON.stringify(want) || [qa, want],"
                     "  cards.length > 0, subs.every(t => / free of /.test(t) || t === 'Ready'),"
                     "  cards.every(c => vols.some(v => v.root === c.getAttribute('data-path'))),"
                     "  rows === rec.length || [rows, rec.length],"
                     "  !!document.querySelector('.wcards-net .winfobar, .wcards-net .wnet-card'),"
                     "  window.__places.painted]; })()"),
                  [True, True, True, True, True, True, True])
            check("live-list",
                  sorted(ev("() => Array.from("
                            "document.querySelectorAll('.grid .cell'))"
                            ".map(c => c.getAttribute('data-n'))")),
                  sorted(["note.txt", "code.py", "pics", "src", "good.link",
                          "bad.link", "term.desktop", "page.html", "doc.rtf"]
                         + (["repo"] if have_git else [])
                         + (["shot.png"] if have_pil else [])
                         + (["doc.pdf"] if have_pdf else [])
                         + (["clip.mp4"] if have_vid else [])))
            # Navigating in live mode has to leave Home. It did not: the
            # list was built into a hidden container while the breadcrumb
            # named the folder and the widgets stayed on screen, and every
            # gate below this one read text off rows with a zero width box.
            # Nothing asserted here is a count, because counting is what
            # missed it.
            check("live-leaves-home",
                  ev("() => (async () => {"
                     " const w = ms => new Promise(r => setTimeout(r, ms));"
                     " await window.__live.render(" + json.dumps(scratch) +
                     "); await w(700);"
                     " const hw = document.getElementById('home-widgets');"
                     " const view = document.querySelector("
                     "'.grid:not([hidden]), .rows:not([hidden]),"
                     " .list:not([hidden]), .cards:not([hidden]),"
                     " .columns:not([hidden])');"
                     " const vb = view ? view.getBoundingClientRect()"
                     "  : {width: 0, height: 0};"
                     # The first [data-p] in the document is a sidebar row.
                     # What has to have a size is a row inside the view.
                     " const cell = view ? view.querySelector('[data-p]')"
                     "  : null;"
                     " const cb = cell ? cell.getBoundingClientRect()"
                     "  : {width: 0, height: 0};"
                     " const act = document.querySelector('.srow.item.active');"
                     " return [hw.hidden, !!view, vb.width > 400,"
                     "  vb.height > 200, cb.width > 40, cb.height > 8,"
                     "  act ? (act.textContent || '').trim() : 'none']; })()"),
                  [True, True, True, True, True, True, "none"])
            with urllib.request.urlopen(
                    "http://127.0.0.1:8902/api/preview?path=" +
                    os.path.join(scratch, "note.txt"),
                    timeout=3) as resp:
                pv = json.load(resp)
            check("live-preview",
                  [pv.get("binary"), pv.get("text")], [False, "live data"])
            # The About page reads the system rather than assuming it,
            # and the whole module aliases its imports, so a bare os.
            # in a new handler is a NameError at request time and only
            # a request finds it.
            with urllib.request.urlopen(
                    "http://127.0.0.1:8902/api/system", timeout=10) as resp:
                sysinfo = json.load(resp)
            # The wallpaper the backdrop samples. Pointed at a known file so
            # the check does not depend on what this machine's desktop is set
            # to, and asserts the sample is small: the whole point of 64
            # pixels wide is that a backdrop costs kilobytes, not megabytes.
            with urllib.request.urlopen(
                    "http://127.0.0.1:8902/api/wallpaper", timeout=15) as resp:
                wall = json.load(resp)
            check("api-wallpaper",
                  [wall.get("found"), wall.get("sample_width"),
                   bool(wall.get("bytes")) and wall["bytes"] < 20000,
                   str(wall.get("uri", ""))[:15]],
                  [True, 64, True, "data:image/jpeg"])
            _capabilities = sysinfo.get("capabilities") or []

            # The one route the Security tab reads. Asked of both backends,
            # because the tab used to invent three Windows principals and
            # neither backend was ever asked anything. Compared against this
            # machine's own stat rather than against a recorded answer.
            _probe = os.path.join(ROOT, "assets", "files-commands.json")
            _own = {}
            try:
                with urllib.request.urlopen(
                        "http://127.0.0.1:8902/api/props?path="
                        + urllib.parse.quote(_probe), timeout=10) as _resp:
                    _own = json.load(_resp)
            except Exception as _err:
                _own = {"error": str(_err)}
            _st = os.stat(_probe)
            _bits = _st.st_mode & 0o7777

            def _spoken(mode):
                out = ""
                for shift in (6, 3, 0):
                    three = (mode >> shift) & 7
                    out += "r" if three & 4 else "-"
                    out += "w" if three & 2 else "-"
                    out += "x" if three & 1 else "-"
                return out

            check("api-props-reports-this-machine",
                  [_own.get("uid"), _own.get("gid"), _own.get("mode"),
                   _own.get("symbolic"),
                   _own.get("user") == pwd.getpwuid(_st.st_uid).pw_name],
                  [_st.st_uid, _st.st_gid, _bits, _spoken(_bits), True])

            check("api-system",
                  [bool(sysinfo.get("os")), bool(sysinfo.get("kernel")),
                   bool(sysinfo.get("arch"))],
                  [True, True, True])
            req = urllib.request.Request(
                "http://127.0.0.1:8902/api/thumb-cache/clear", method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                cache = json.load(resp)
            check("api-thumb-cache-clear",
                  [isinstance(cache.get("removed"), int),
                   cache.get("removed") >= 0,
                   cache.get("path", "").endswith("thumbnails")],
                  [True, True, True])
            # File tags, end to end. The xattr is the truth for one
            # file, the index answers "what is tagged Blue", and neither
            # is allowed to drift: the check reads the tags back off the
            # file after writing them through the index route.
            tagged = os.path.join(scratch, "code.py")
            def tagpost(payload):
                r = urllib.request.Request(
                    "http://127.0.0.1:8902/api/tags",
                    data=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST")
                with urllib.request.urlopen(r, timeout=10) as resp:
                    return json.load(resp)
            set1 = tagpost({"path": tagged,
                            "tags": ["Blue", "Red", "Blue", "no,pe", ""]})
            with urllib.request.urlopen(
                    "http://127.0.0.1:8902/api/tags?path=" + tagged,
                    timeout=10) as resp:
                read1 = json.load(resp)
            with urllib.request.urlopen(
                    "http://127.0.0.1:8902/api/tags/all", timeout=10) as resp:
                all1 = json.load(resp)
            with urllib.request.urlopen(
                    "http://127.0.0.1:8902/api/tags/list?tag=Blue",
                    timeout=10) as resp:
                list1 = json.load(resp)
            onfile = localfs.xattr_list(tagged).get("user.xdg.tags", "")
            # A tagged file that goes away has to leave the index with it,
            # or the sidebar counts drift up forever and opening a tag lists
            # things that are not there.
            doomed = os.path.join(scratch, "doomed.txt")
            with open(doomed, "w", encoding="utf-8") as fh:
                fh.write("here for a moment")
            tagpost({"path": doomed, "tags": ["Purple"]})
            with urllib.request.urlopen(
                    "http://127.0.0.1:8902/api/tags/all", timeout=10) as resp:
                withdoomed = sorted(json.load(resp).get("tags", {}).keys())
            os.unlink(doomed)
            with urllib.request.urlopen(
                    "http://127.0.0.1:8902/api/tags/all", timeout=10) as resp:
                pruned = sorted(json.load(resp).get("tags", {}).keys())
            tagpost({"path": tagged, "tags": []})
            with urllib.request.urlopen(
                    "http://127.0.0.1:8902/api/tags/all", timeout=10) as resp:
                all2 = json.load(resp)
            check("tags-store",
                  [set1.get("tags"), read1.get("tags"), onfile,
                   sorted(all1.get("tags", {}).keys()),
                   [e["name"] for e in list1.get("entries", [])],
                   withdoomed, pruned, all2.get("tags")],
                  [["Blue", "Red"], ["Blue", "Red"], "Blue,Red",
                   ["Blue", "Red"], ["code.py"],
                   ["Blue", "Purple", "Red"], ["Blue", "Red"], {}])
            # The tag UI. A tag has to reach three places from one click:
            # the dots on the item, the count in the sidebar, and the check in
            # the menu. Opening the tag has to list only what carries it, and
            # clearing it has to take the section away again.
            # The store gate just wrote tags through the API, and the
            # watcher answers that with a redraw; a read that lands in the
            # middle of it finds no row at all. Wait for the row first.
            tagui = ev("() => (async () => {"
                       " const w = ms => new Promise(r => setTimeout(r, ms));"
                       " const find = () => Array.from(document.querySelectorAll("
                       "'.cell[data-p]')).map(r => r.getAttribute('data-p'))"
                       ".find(x => x && x.indexOf('code.py') > 0);"
                       " let p = find();"
                       " for (let i = 0; i < 40 && !p; i++) { await w(100); p = find(); }"
                       " if (!p) return 'no code.py row';"
                       " await window.__tags.toggle(p, 'Blue');"
                       " await window.__tags.toggle(p, 'Green');"
                       " const cell = document.querySelector("
                       "'.cell[data-p=\"' + p + '\"]');"
                       " const dots = cell ? cell.querySelectorAll("
                       "'.tagdots .tagdot').length : -1;"
                       " const attr = cell ? cell.getAttribute('data-tags') : null;"
                       " const sb = Array.from(document.querySelectorAll("
                       "'[data-tagopen]')).map(r => r.getAttribute('data-tagopen'));"
                       " const open1 = !document.querySelector("
                       "'.sgrp[data-sec=\"Tags\"]').classList.contains('shut');"
                       " window.__tags.fillSub(p);"
                       " const checks = Array.from(document.querySelectorAll("
                       "'#sub-tags .mi-tagck')).filter(c => c.textContent).length;"
                       " await window.__tags.openTag('Green');"
                       " await new Promise(r => setTimeout(r, 250));"
                       " const listed = Array.from(document.querySelectorAll("
                       "'.cell[data-p]')).map(c => c.getAttribute('data-n'));"
                       " await window.__tags.toggle(p, 'Blue');"
                       " await window.__tags.toggle(p, 'Green');"
                       " const sb2 = document.querySelectorAll("
                       "'[data-tagopen]').length;"
                       " const shut = document.querySelector("
                       "'.sgrp[data-sec=\"Tags\"]').classList.contains('shut');"
                       " return [dots, attr, sb, open1, checks, listed, sb2,"
                       " shut]; })()")
            check("tags-ui", tagui,
                  [2, "Blue,Green", ["Blue", "Green"], True, 2,
                   ["code.py"], 0, True])

            if have_pil:
                with urllib.request.urlopen(
                        "http://127.0.0.1:8902/api/thumb?path=" +
                        os.path.join(scratch, "shot.png"), timeout=10) as resp:
                    th = json.load(resp)
                # Scaled into the box, not passed through: a 600x400 source
                # must come back no wider than 512 and must say what it was.
                check("thumb-image",
                      [th.get("supported"), th.get("width"),
                       th.get("thumb_width") <= 512,
                       str(th.get("uri", ""))[:11]],
                      [True, 600, True, "data:image/"])
                with urllib.request.urlopen(
                        "http://127.0.0.1:8902/api/thumb?path=" +
                        os.path.join(scratch, "note.txt"), timeout=10) as resp:
                    th2 = json.load(resp)
                # A text file is not an error, it is an answer, and it has to
                # be the cheap answer: without the extension guard PIL is asked
                # to decode it and fails, which reports supported=False just the
                # same. The reason is what tells the two apart.
                check("thumb-refuses-text",
                      [th2.get("supported"), th2.get("reason")],
                      [False, "not an image"])
                # The picture has to survive the rebuild that live mode does on
                # every navigation, which is where it was lost the first time.
                ev("() => (async () => { await window.__live.render(" +
                   json.dumps(scratch) + "); return 1; })()")
                check("preview-code-tokens",
                      ev("() => (async () => {"
                         " const w = ms => new Promise(r => setTimeout(r, ms));"
                         " await window.__live.render(" + json.dumps(scratch) +
                         "); await w(400);"
                         " document.getElementById('btn-pane').click();"
                         " await w(300);"
                         " const t = Array.from(document"
                         ".querySelectorAll('.infopane-tab'));"
                         " if (t.length > 1) t[1].click(); await w(200);"
                         " const c = Array.from(document"
                         ".querySelectorAll('.grid .cell'))"
                         ".find(x => x.getAttribute('data-n') === 'code.py');"
                         " if (!c) return 'no cell'; c.click(); await w(900);"
                         " const box = document.getElementById('ipreview-text');"
                         " const line = box.querySelector('.pv-line');"
                         " if (!line) return 'no lines';"
                         " const str = line.querySelector('.tok-str');"
                         " const com = line.querySelector('.tok-com');"
                         " return [box.querySelectorAll('.tok-kw').length > 0,"
                         " str ? str.textContent : '',"
                         " com ? com.textContent : '']; })()"),
                      [True, '"has # inside"', "# real comment"])
                check("thumb-survives-rebuild",
                      ev("() => { const c = Array.from(document"
                         ".querySelectorAll('.grid .cell'))"
                         ".find(x => x.getAttribute('data-n') === 'shot.png');"
                         " if (!c) return 'no cell';"
                         " const i = c.querySelector('img.thumbimg');"
                         " return [!!i, i ? i.src.slice(0, 11) : '']; }"),
                      [True, "data:image/"])
            check("live-preview-shows",
                  ev("() => { const c = Array.from(document.querySelectorAll('.grid .cell'))"
                     ".find(x => x.getAttribute('data-n') === 'note.txt');"
                     " c.click();"
                     " return new Promise(res => { const t0 = Date.now();"
                     " const iv = setInterval(() => {"
                     " const b = document.getElementById('ipreview-text');"
                     " if ((!b.hidden && b.textContent.length > 0) || Date.now() - t0 > 9000)"
                     " { clearInterval(iv); res([!b.hidden, b.textContent]); } }, 250); }); }"),
                  [True, "live data"])
            # HTML and rich text previews. The HTML half is a security
            # check as much as a rendering one: the fixture carries a script,
            # a stylesheet, a frame and two javascript: URLs, and the pane is
            # only correct if the markup arrives without any of them. Height
            # is asserted because a box that parsed perfectly and laid out to
            # nothing still shows the reader an empty pane.
            check("preview-html-rtf",
                  ev("() => (async () => {"
                     " const w = ms => new Promise(r => setTimeout(r, ms));"
                     " const pick = async n => {"
                     "  const c = Array.from(document"
                     ".querySelectorAll('.grid .cell'))"
                     ".find(x => x.getAttribute('data-n') === n);"
                     "  if (!c) return null; c.click(); await w(900);"
                     "  return document.querySelector("
                     "'#ipreview-text .preview-rich-box'); };"
                     " const h = await pick('page.html');"
                     " if (!h) return 'no html box';"
                     " const hrefs = Array.from(h.querySelectorAll('a'))"
                     ".map(a => a.getAttribute('href') || '');"
                     " const html = ["
                     "  typeof window.PWNED,"
                     "  h.querySelectorAll('script,style,iframe,form').length,"
                     "  hrefs.join('|'),"
                     "  h.querySelectorAll('img').length,"
                     "  h.textContent.indexOf('North') !== -1,"
                     "  h.textContent.indexOf('PWNED') === -1 &&"
                     "   h.textContent.indexOf('color:') === -1,"
                     "  h.querySelectorAll('h1,table,td').length,"
                     "  h.getBoundingClientRect().height > 20,"
                     # A rendered document has to read as one. The pane is
                     # monospace for plain text, and leaving it that way is
                     # how the first version shipped.
                     "  getComputedStyle(h).fontFamily.indexOf('mono') === -1,"
                     # Both directions, because a rule that colours every
                     # anchor plainly passes the first half on its own.
                     "  getComputedStyle(h.querySelector('a:not([href])'))"
                     "   .color === getComputedStyle(h).color,"
                     "  getComputedStyle(h.querySelector('a[href]'))"
                     "   .color !== getComputedStyle(h).color];"
                     " const r = await pick('doc.rtf');"
                     " if (!r) return 'no rtf box';"
                     " const ps = r.querySelectorAll('.pv-p');"
                     " const st = r.querySelector('strong');"
                     " const em = r.querySelector('em');"
                     " const rtf = [ps.length,"
                     "  st ? st.textContent : '', em ? em.textContent : '',"
                     "  r.querySelectorAll('strong').length,"
                     "  r.querySelectorAll('em').length,"
                     "  r.textContent.indexOf('Consolas') === -1,"
                     "  r.textContent.indexOf('AB') !== -1,"
                     "  ps.length ? ps[0].getBoundingClientRect().height > 8"
                     "   : false];"
                     " return [html, rtf]; })()"),
                  [["undefined", 0, "|https://example.com/q", 0, True, True,
                    4, True, True, True, True],
                   [2, "Heading", "slanted", 1, 1, True, True, True]])
            check("live-mkdir",
                  ev("() => { window.__liveOp('newfolder');"
                     " const i = document.getElementById('ninput');"
                     " i.value = 'sub';"
                     " i.dispatchEvent(new KeyboardEvent('keydown',"
                     " {key: 'Enter', code: 'Enter', bubbles: true}));"
                     " return true; }") and ev(
                  "() => new Promise(res => { const t0 = Date.now();"
                  " const iv = setInterval(() => {"
                  " const names = Array.from(document.querySelectorAll('.grid .cell'))"
                  ".map(c => c.getAttribute('data-n'));"
                  " if (names.indexOf('sub') !== -1 || Date.now() - t0 > 9000"
                  ") { clearInterval(iv); res(names.indexOf('sub') !== -1); } }, 250); })") and
                  os.path.isdir(os.path.join(scratch, "sub")), True)
            # The seam asks the same question the command does now, so the
            # gate answers it the way a person would.
            check("live-trash",
                  ev("() => { Array.from(document.querySelectorAll('.grid .cell'))"
                     ".find(c => c.getAttribute('data-n') === 'note.txt').click();"
                     " window.__liveOp('trash');"
                     " setTimeout(() => { const go = document.querySelector("
                     "'#dlg-fsop [data-dlg=\"primary\"]'); if (go) go.click(); }, 400);"
                     " return true; }") and ev(
                  "() => new Promise(res => { const t0 = Date.now();"
                  " const iv = setInterval(() => {"
                  " const names = Array.from(document.querySelectorAll('.grid .cell'))"
                  ".map(c => c.getAttribute('data-n'));"
                  " if (names.indexOf('note.txt') === -1 || Date.now() - t0 > 9000"
                  ") { clearInterval(iv); res(names.indexOf('note.txt') === -1); } }, 250); })") and
                  not os.path.lexists(os.path.join(scratch, "note.txt")), True)
            if have_pdf:
                with urllib.request.urlopen(
                        "http://127.0.0.1:8902/api/thumb?path=" +
                        os.path.join(scratch, "doc.pdf"), timeout=45) as resp:
                    tp = json.load(resp)
                # The page is rendered, not the file passed through: a PDF has
                # no pixels of its own and the kind says which converter ran.
                check("thumb-pdf-page",
                      [tp.get("supported"), tp.get("kind"),
                       tp.get("thumb_width", 0) <= 512,
                       str(tp.get("uri", ""))[:11]],
                      [True, "pdf", True, "data:image/"])
            if have_vid:
                with urllib.request.urlopen(
                        "http://127.0.0.1:8902/api/thumb?path=" +
                        os.path.join(scratch, "clip.mp4"), timeout=45) as resp:
                    tv = json.load(resp)
                check("thumb-video-frame",
                      [tv.get("supported"), tv.get("kind"),
                       str(tv.get("uri", ""))[:11]],
                      [True, "video", "data:image/"])
            # One extension table. A second copy maintained by hand is how live
            # mode ended up calling a PDF a File.
            check("live-kind-matches-table",
                  ev("() => (async () => {"
                     " const w = ms => new Promise(r => setTimeout(r, ms));"
                     " await window.__live.render(" + json.dumps(scratch) +
                     "); await w(500);"
                     " const k = {};"
                     " document.querySelectorAll('.grid .cell').forEach("
                     "c => k[c.getAttribute('data-n')] ="
                     " c.getAttribute('data-k'));"
                     " return [k['doc.pdf'] || '', k['code.py'] || '']; })()"),
                  ["PDF document" if have_pdf else "", "Python"])
            check("props-shortcut-tab",
                  ev("() => (async () => {"
                     " const w = ms => new Promise(r => setTimeout(r, ms));"
                     " await window.__live.render(" + json.dumps(scratch) +
                     "); await w(500);"
                     " const pick = n => Array.from(document"
                     ".querySelectorAll('.grid .cell'))"
                     ".find(x => x.getAttribute('data-n') === n);"
                     " const open = async n => { const c = pick(n);"
                     " if (!c) return 'missing ' + n; c.click(); await w(120);"
                     " document.querySelector"
                     "('.toolbar [data-act=\"ctx-props\"]').click();"
                     " await w(600);"
                     " const tab = document.querySelector"
                     "('#props [data-ptab=\"shortcut\"]');"
                     " const out = [tab && !tab.hidden,"
                     " (document.getElementById('lnk-kind')||{}).textContent,"
                     " (document.getElementById('lnk-target')||{}).textContent,"
                     " !(document.getElementById('lnk-note')||{}).hidden];"
                     " document.getElementById('props').hidden = true;"
                     " await w(120); return out; };"
                     " const a = await open('good.link');"
                     " const b = await open('bad.link');"
                     " const c = await open('term.desktop');"
                     # note.txt is gone by now, the trash check took it.
                     " const d = await open('code.py');"
                     " return [a, b, c, Array.isArray(d) ? d[0] : d]; })()"),
                  [[True, "Symbolic link", "/etc/hostname", False],
                   [True, "Symbolic link", "/nope/missing", True],
                   [True, "Application shortcut", "/usr/bin/xterm", True],
                   False])
            # The Customization tab. The reference offers it for a folder or
            # a shortcut and never for a plain file, and picking an icon has
            # to reach three places: the row on screen, the folder on disk,
            # and the dialog when it is opened again. The viewBox is what
            # proves the art actually changed: folder art is 48x40 and the
            # file glyphs are 40x48, so a row that kept its own icon reads
            # differently from one that took the chosen one.
            def _icon_xattr():
                try:
                    return os.getxattr(pics, "user.aurade.icon").decode()
                except OSError:
                    return ""

            _cust_helpers = (
                " const w = ms => new Promise(r => setTimeout(r, ms));"
                " const vb = n => { const c = Array.from(document"
                ".querySelectorAll('.grid .cell'))"
                ".find(x => x.getAttribute('data-n') === n);"
                "  const s = c && c.querySelector('.thumb svg');"
                "  return s ? s.getAttribute('viewBox') : 'none'; };"
                " const open = async n => { const c = Array.from(document"
                ".querySelectorAll('.grid .cell'))"
                ".find(x => x.getAttribute('data-n') === n);"
                "  if (!c) return 'missing ' + n; c.click(); await w(120);"
                "  document.querySelector"
                "('.toolbar [data-act=\"ctx-props\"]').click();"
                "  await w(600); return true; };"
                " const shut = async () => {"
                "  document.getElementById('props').hidden = true;"
                "  await w(120); };")
            check("props-customization-set",
                  ev("() => (async () => {" + _cust_helpers +
                     " await window.__live.render(" + json.dumps(scratch) +
                     "); await w(600);"
                     " const before = vb('pics');"
                     " const opened = await open('pics');"
                     " if (opened !== true) return opened;"
                     " const tab = document.querySelector"
                     "('#props [data-ptab=\"customization\"]');"
                     " if (!tab || tab.hidden) return 'tab hidden for a folder';"
                     " tab.click(); await w(120);"
                     " const pane = document.getElementById"
                     "('ptab-customization');"
                     " const btn = document.querySelector"
                     "('#cust-grid .cust-ico[data-icon=\"py\"]');"
                     " if (!btn) return 'no py glyph';"
                     " const cell = btn.getBoundingClientRect();"
                     " btn.click(); await w(700);"
                     " const chosen = ["
                     "  document.getElementById('cust-path').value,"
                     "  btn.classList.contains('on'),"
                     "  document.getElementById('cust-restore').disabled,"
                     "  cell.width > 40 && cell.height > 40,"
                     "  pane.getBoundingClientRect().height > 100];"
                     " await shut();"
                     " await window.__live.render(" + json.dumps(scratch) +
                     "); await w(700);"
                     " return [chosen, before, vb('pics')]; })()"),
                  [["Built in icon: py", True, False, True, True],
                   "0 0 48 40", "0 0 40 48"])
            # The tab writes to the folder, not to a preference. Read from
            # outside the browser, so this says the icon is on the folder and
            # not merely on the screen.
            check("props-customization-xattr", _icon_xattr(), "glyph:py")
            check("props-customization-restore",
                  ev("() => (async () => {" + _cust_helpers +
                     " const opened = await open('pics');"
                     " if (opened !== true) return opened;"
                     " document.querySelector"
                     "('#props [data-ptab=\"customization\"]').click();"
                     " await w(300);"
                     " const reopened = document.getElementById"
                     "('cust-path').value;"
                     " document.getElementById('cust-restore').click();"
                     " await w(700);"
                     " const cleared = document.getElementById"
                     "('cust-path').value;"
                     " await shut();"
                     " await window.__live.render(" + json.dumps(scratch) +
                     "); await w(700);"
                     " const restored = vb('pics');"
                     " const other = await open('code.py'); await w(300);"
                     " if (other !== true) return other;"
                     " const fileTab = document.querySelector"
                     "('#props [data-ptab=\"customization\"]');"
                     " const hiddenForFile = !fileTab || fileTab.hidden;"
                     " await shut();"
                     " return [reopened, cleared, restored, hiddenForFile];"
                     " })()"),
                  ["Built in icon: py", "Default icon", "0 0 48 40", True])
            check("props-customization-cleared", _icon_xattr(), "")
            # Git. The reference shows a repository in the status bar and in
            # the details columns, and shows neither outside one. All three
            # claims are checked here, plus the rollup: a change one level
            # down has to be reported by the folder that holds it, because
            # that folder is the row the person is looking at.
            if have_git:
                check("git-live",
                      ev("() => (async () => {"
                         " const w = ms => new Promise(r => setTimeout(r, ms));"
                         " window.__setLayout('details');"
                         " await window.__live.render(" + json.dumps(repo) +
                         "); await w(900);"
                         " const wrap = document.getElementById('git-wrap');"
                         " const rows = {};"
                         " document.querySelectorAll('.dbody [data-p]')"
                         ".forEach(r => { const c = r.querySelector('.c-git');"
                         "  rows[r.getAttribute('data-n')] ="
                         "   c ? c.textContent : 'no cell'; });"
                         " const head = document.querySelector('.dh-git');"
                         " const hb = head ? head.getBoundingClientRect()"
                         "  : {width: 0};"
                         " const inRepo = ["
                         "  !wrap.hidden,"
                         "  document.getElementById('git-branch').textContent,"
                         "  document.documentElement.getAttribute('data-git'),"
                         "  Math.round(hb.width) > 40,"
                         "  rows['tracked.txt'] || '', rows['fresh.txt'] || '',"
                         "  rows['deep'] || ''];"
                         " await window.__live.render(" + json.dumps(scratch) +
                         "); await w(900);"
                         " const h2 = document.querySelector('.dh-git');"
                         " const outside = [wrap.hidden,"
                         "  document.documentElement.getAttribute('data-git'),"
                         "  h2 ? Math.round(h2.getBoundingClientRect().width)"
                         "   : -1];"
                         " window.__setLayout('grid'); await w(400);"
                         " return [inRepo, outside]; })()"),
                      [[True, "main", "1", True,
                        "Modified", "Untracked", "Modified"],
                       [True, "0", 0]])

                def _head():
                    return _git("rev-parse", "--abbrev-ref",
                                "HEAD").stdout.strip()

                # Switching branches. Local only, and the reference's flyout
                # does the same. What is asserted is the repository's own
                # answer as well as the status bar's, because the bar showing
                # a name is not the same as the tree being on it.
                check("git-checkout",
                      ev("() => (async () => {"
                         " const w = ms => new Promise(r => setTimeout(r, ms));"
                         " await window.__live.render(" + json.dumps(repo) +
                         "); await w(700);"
                         " const before = document.getElementById"
                         "('git-branch').textContent;"
                         " const ok = await window.__git.checkout('feature');"
                         " await w(900);"
                         " const after = document.getElementById"
                         "('git-branch').textContent;"
                         " const marked = Array.from(document"
                         ".querySelectorAll('#m-git .mi'))"
                         ".filter(m => m.querySelector('.ck.on'))"
                         ".map(m => m.textContent.trim());"
                         " const same = await window.__git.checkout('feature');"
                         " return [before, ok, after, marked, same]; })()"),
                      ["main", True, "feature", ["feature"], False])
                check("git-checkout-head", _head(), "feature")

                # A branch name goes to git as an argument, so a name that is
                # really an option has to be refused here rather than run.
                # The status code is what separates the two: a refusal is 400
                # and a git failure is 409, and both would return false to
                # the page.
                def _checkout_code(branch):
                    r = urllib.request.Request(
                        "http://127.0.0.1:8902/api/git/checkout",
                        data=json.dumps({"path": repo,
                                         "branch": branch}).encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST")
                    try:
                        with urllib.request.urlopen(r, timeout=10) as resp:
                            return resp.status
                    except urllib.error.HTTPError as e:
                        return e.code
                check("git-checkout-rejects",
                      [_checkout_code("--all"), _checkout_code("a b"),
                       _checkout_code("no-such-branch-here")],
                      [400, 400, 409])
                _git("checkout", "-q", "main")

                # The remote half. A clone reaches a network in general; what
                # runs here is a repository on this machine over file://,
                # which is the same code with the same transport check in
                # front of it, so the routes are exercised without the suite
                # depending on anything outside the box.
                #
                # Asked of the backend rather than switched on by hand: these
                # run against whichever backend offers the capability, and
                # start running by themselves the day the other one does.
                def _post(route, payload, seconds=60):
                    r = urllib.request.Request(
                        "http://127.0.0.1:8902" + route,
                        data=json.dumps(payload).encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST")
                    try:
                        with urllib.request.urlopen(r, timeout=seconds) as resp:
                            return resp.status, json.load(resp)
                    except urllib.error.HTTPError as e:
                        return e.code, {}

                if "git-remote" not in _capabilities:
                    print("     git remote: not offered by this backend, "
                          "skipping the six routes")
                else:
                    # git's ext:: transport hands the rest of the address to a
                    # shell, and an address can come from a page, so this is a
                    # gate and not a preference. Both halves matter: the refusal,
                    # and that nothing ran.
                    _proof = os.path.join(scratch, "the-transport-ran")
                    _evil = "ext::sh -c 'touch " + _proof + "'"
                    _code, _ = _post("/api/git/clone",
                                     {"url": _evil,
                                      "into": os.path.join(scratch, "no-clone")})
                    time.sleep(0.4)
                    check("git-refuses-a-transport-that-runs-a-command",
                          [_code, os.path.exists(_proof)], [501, False])

                    _into = os.path.join(scratch, "cloned")
                    _code, _cloned = _post("/api/git/clone",
                                           {"url": "file://" + repo, "into": _into})
                    check("git-clone-brings-the-commits",
                          [_code,
                           os.path.isdir(os.path.join(_into, ".git")),
                           os.path.exists(os.path.join(_into, "tracked.txt"))],
                          [200, True, True])

                    # A commit on the other side, then a pull that has to move the
                    # branch, put the file on disk and stop saying it is behind.
                    open(os.path.join(repo, "pulled.txt"), "w").write("two\n")
                    _git("add", "pulled.txt")
                    _git("commit", "-qm", "second")
                    _code, _pulled = _post("/api/git/pull", {"path": _into})
                    check("git-pull-fast-forwards",
                          [_code, _pulled.get("moved"),
                           os.path.exists(os.path.join(_into, "pulled.txt")),
                           _pulled.get("behind")],
                          [200, True, True, 0])
                    # Again with nothing new. An answer, not a merge commit.
                    check("git-pull-with-nothing-new-does-not-commit",
                          _post("/api/git/pull", {"path": _into})[1].get("moved"),
                          False)

                    # And a repository where there was not one, which has to
                    # refuse the second time rather than write over the first.
                    _fresh = os.path.join(scratch, "fresh-repo")
                    os.makedirs(_fresh, exist_ok=True)
                    check("git-init-once",
                          [_post("/api/git/init", {"path": _fresh})[0],
                           os.path.isdir(os.path.join(_fresh, ".git")),
                           _post("/api/git/init", {"path": _fresh})[0]],
                          [200, True, 409])

            if "apps" not in _capabilities:
                print("     launcher pin: not offered by this backend, skipping")
            else:
                # Pin to Start, in the shape this desktop has one: a desktop entry
                # in the applications directory, which the launcher and the search
                # both already read. The escaping is the part worth a gate,
                # because a folder's name reaches an Exec line.
                def _post_any(route, payload):
                    r = urllib.request.Request(
                        "http://127.0.0.1:8902" + route,
                        data=json.dumps(payload).encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST")
                    try:
                        with urllib.request.urlopen(r, timeout=20) as resp:
                            return resp.status, json.load(resp)
                    except urllib.error.HTTPError as e:
                        return e.code, {}

                _pinme = os.path.join(scratch, "Pin Me")
                os.makedirs(_pinme, exist_ok=True)
                _code, _pin = _post_any("/api/pin-to-launcher", {"path": _pinme})
                _entry = _pin.get("entry", "")
                _text = (open(_entry, encoding="utf-8").read()
                         if _entry and os.path.exists(_entry) else "")
                check("launcher-pin-writes-a-desktop-entry",
                      [_code,
                       _text.startswith("[Desktop Entry]\n"),
                       'Exec=xdg-open "' + _pinme + '"' in _text,
                       #: Every key on its own line with nothing before it. An
                       #: entry written with the source's indentation still in it
                       #: parses as nothing at all.
                       [l for l in _text.splitlines()[1:] if l.startswith(" ")]],
                      [200, True, True, []])
                #: A name that would end the Exec line and start a key of its own.
                _nasty = os.path.join(scratch, "evil\nExec=sh -c id\nX=")
                try:
                    os.makedirs(_nasty, exist_ok=True)
                    _made = True
                except OSError:
                    _made = False
                if _made:
                    check("launcher-pin-refuses-a-name-that-writes-its-own-keys",
                          _post_any("/api/pin-to-launcher", {"path": _nasty})[0],
                          400)
                check("launcher-unpin-removes-the-entry",
                      [_post_any("/api/unpin-from-launcher", {"path": _pinme})[0],
                       os.path.exists(_entry) if _entry else "no entry",
                       _post_any("/api/unpin-from-launcher", {"path": _pinme})[0]],
                      [200, False, 404])
            # The shelf's drop and its one destructive action. A synthetic
            # drop carries the same payload a real drag sets, so what is
            # tested is the handler rather than a helper, and the file is
            # checked on disk afterwards because the shelf is the only place
            # in the app that deletes something it is not looking at.
            victim = os.path.join(scratch, "shelfme.txt")
            open(victim, "w").write("temporary\n")
            check("shelf-drop-batch",
                  ev("() => (async () => {"
                     " const w = ms => new Promise(r => setTimeout(r, ms));"
                     " await window.__live.render(" + json.dumps(scratch) +
                     "); await w(700);"
                     " window.__shelf.clear();"
                     " window.__shelf.toggle(true);"
                     " const pane = document.getElementById('shelf');"
                     " const dt = new DataTransfer();"
                     " dt.setData('application/x-aurade-files', JSON.stringify("
                     "[{name: 'shelfme.txt', path: " + json.dumps(victim) +
                     ", kind: 'Text'}]));"
                     " pane.dispatchEvent(new DragEvent('drop', {dataTransfer:"
                     " dt, bubbles: true, cancelable: true}));"
                     " await w(300);"
                     " const dropped = window.__shelf.items().map(i => i.name);"
                     " window.__shelf.select(" + json.dumps(victim) + ");"
                     " const picked = window.__shelf.selected().length;"
                     " const n = await window.__shelf.batch('delete');"
                     " await w(900);"
                     " const left = window.__shelf.items().length;"
                     " const listed = Array.from(document"
                     ".querySelectorAll('[data-n]'))"
                     ".some(c => c.getAttribute('data-n') === 'shelfme.txt');"
                     " window.__shelf.toggle(false);"
                     " return [dropped, picked, n, left, listed]; })()"),
                  [["shelfme.txt"], 1, 1, 0, False])
            check("shelf-batch-deleted", os.path.lexists(victim), False)
            if have_pil:
                # Adaptive is the reference's sixth layout: a rule, not a
                # view. Picking a real layout has to switch the rule off, which
                # is what IsAdaptiveLayoutOverridden does there.
                check("layout-adaptive",
                      ev("() => (async () => {"
                         " const w = ms => new Promise(r => setTimeout(r, ms));"
                         " window.__setLayout('adaptive');"
                         " await window.__live.render(" + json.dumps(pics) +
                         "); await w(500); const a = window.__mode();"
                         " await window.__live.render(" + json.dumps(srcd) +
                         "); await w(500); const b = window.__mode();"
                         " window.__setLayout('list');"
                         " await window.__live.render(" + json.dumps(pics) +
                         "); await w(500);"
                         " return [a, b, window.__mode(),"
                         " window.__isAdaptive()]; })()"),
                      ["grid", "details", "list", False])
            # layout-adaptive above leaves the view in list mode, and the
            # grid keeps its old rows while hidden. Clicking one of those
            # selects a row nobody can see, which is exactly the state the
            # page now refuses to act on, so the layout is put back first.
            ev("() => { window.__setLayout('grid'); return 1; }")
            _arc_helpers = (
                " const w = ms => new Promise(r => setTimeout(r, ms));"
                " const pick = n => Array.from(document"
                ".querySelectorAll('.grid .cell'))"
                ".find(x => x.getAttribute('data-n') === n && "
                "(x.offsetWidth || x.offsetHeight));"
                # The context menus carry the reference's command name
                # now rather than this page's act name, so an act with no
                # button or row of its own is reached the way the menus
                # reach it: through the registry, which is also what
                # decides whether it can run at all.
                " const act = a => {"
                "  const el = document.querySelector('[data-act=\"' + a + '\"]');"
                "  if (el) { el.click(); return true; }"
                "  const found = Array.from(window.__commands.entries())"
                "   .find(pair => pair[1].act === a);"
                "  return found ? window.__runCommand(found[0]) : false; };")
            # Ownership and permissions are the same question on either
            # backend, and both answer /api/props and /api/chmod, so these
            # run against whichever one is up rather than only the Rust one.
            # They were written inside the Rust-only branch and a mutation
            # that stopped the Security tab asking the backend at all passed
            # the suite, because the default run never reached them.
            # The Security tab shows this machine's permissions. It used
            # to list SYSTEM, Administrators and Users with every box
            # ticked, about a file it had never looked at, while the
            # backend has had ownership, mode bits and POSIX ACLs behind
            # /api/props the whole time and nothing asked.
            _perm_file = os.path.join(scratch, "perm.txt")
            open(_perm_file, "w").write("who may read this\n")
            os.chmod(_perm_file, 0o640)
            _owner = pwd.getpwuid(os.stat(_perm_file).st_uid).pw_name
            check("security-tab-shows-the-real-owner",
                  ev("() => (async () => {" + _arc_helpers +
                     " await window.__live.render(" + json.dumps(scratch) +
                     "); await w(500);"
                     " const c = pick('perm.txt');"
                     " if (!c) return 'missing perm.txt';"
                     " c.click(); await w(120);"
                     " document.querySelector"
                     "('.toolbar [data-act=\"ctx-props\"]').click();"
                     " await w(1400);"
                     " const said = document.getElementById('sec-owner')"
                     "  .textContent;"
                     " const mode = document.getElementById('sec-mode')"
                     "  .textContent.replace(/\\s+/g, ' ').trim();"
                     " const who = Array.from(document.querySelectorAll("
                     "  '#sec-users .sec-user')).map(u => u.textContent);"
                     " const ticked = Array.from(document.querySelectorAll("
                     "  '#sec-perms .sec-perm-row')).filter(r =>"
                     "   !r.hidden && r.querySelector('input').checked)"
                     "  .map(r => r.getAttribute('data-perm'));"
                     " document.getElementById('props').hidden = true;"
                     " return [said.split(' ')[0], mode, who.length,"
                     "  ticked]; })()"),
                  #: The owner this machine reports, the mode as the
                  #: backend spells it, three principals rather than
                  #: three Windows groups, and 0640 lighting up exactly
                  #: Modify, Read and Write for the owner.
                  [_owner, "rw-r----- 640", 3,
                   ["modify", "read", "write"]])
            # And writing goes through to the file, not just to the box.
            check("security-tab-writes-the-mode",
                  ev("() => (async () => {" + _arc_helpers +
                     " const c = pick('perm.txt');"
                     " if (!c) return 'missing perm.txt';"
                     " c.click(); await w(120);"
                     " document.querySelector"
                     "('.toolbar [data-act=\"ctx-props\"]').click();"
                     " await w(1400);"
                     " const row = document.querySelector("
                     "  '#sec-perms [data-perm=\"write\"] input');"
                     " row.checked = false;"
                     " row.dispatchEvent(new Event('change',"
                     "  {bubbles: true}));"
                     " await w(900);"
                     " const mode = document.getElementById('sec-mode')"
                     "  .textContent.replace(/\\s+/g, ' ').trim();"
                     " document.getElementById('props').hidden = true;"
                     " return mode; })()"),
                  "r--r----- 440")
            check("security-tab-writes-the-mode-on-disk",
                  oct(os.stat(_perm_file).st_mode)[-3:], "440")

            # Bulk rename on disk. Three files, one name: each keeps its own
            # extension, and the second .txt is numbered the way Windows and
            # both backends number a taken name, rather than refused. The
            # Python backend used to make renamed.txt.1 of it, which loses
            # the extension, and disagreed with the Rust one about what the
            # same file is called.
            for _n in ("bulk-a.txt", "bulk-b.txt", "bulk-c.md"):
                with open(os.path.join(scratch, _n), "w") as _fh:
                    _fh.write(_n + "\n")
            check("bulk-rename-keeps-the-extensions-on-disk",
                  ev("() => (async () => {" + _arc_helpers +
                     " await window.__live.render(" + json.dumps(scratch) +
                     "); await w(500);"
                     " const a = pick('bulk-a.txt'), b = pick('bulk-b.txt'),"
                     "  c = pick('bulk-c.md');"
                     " if (!a || !b || !c) return 'missing files';"
                     " a.click(); b.classList.add('sel'); c.classList.add('sel');"
                     " window.__doAct('rename'); await w(200);"
                     " const d = document.getElementById('dlg-bulkrename');"
                     " if (d.hidden) return 'no dialog';"
                     " const box = document.getElementById('br-name');"
                     " box.value = 'renamed';"
                     " box.dispatchEvent(new Event('input', {bubbles: true}));"
                     " d.querySelector('[data-dlg=\"primary\"]').click();"
                     " await w(1500);"
                     " return Array.from(document.querySelectorAll('.grid .cell'))"
                     "  .map(x => x.getAttribute('data-n'))"
                     "  .filter(n => /^(renamed|bulk-)/.test(n)).sort(); })()"),
                  ["renamed (2).txt", "renamed.md", "renamed.txt"])
            check("bulk-rename-on-disk",
                  sorted(n for n in os.listdir(scratch)
                         if n.startswith(("renamed", "bulk-"))),
                  ["renamed (2).txt", "renamed.md", "renamed.txt"])

            # One rename onto a name that is taken is refused, which is the
            # reference's FailIfExists, rather than answered by inventing a
            # third name: both files are still there and nothing new is.
            check("a-rename-onto-a-taken-name-is-refused",
                  ev("() => (async () => {" + _arc_helpers +
                     " await window.__live.render(" + json.dumps(scratch) +
                     "); await w(500);"
                     " const c = pick('renamed.md'); if (!c) return 'missing';"
                     " c.click(); window.__doAct('rename'); await w(200);"
                     " const row = document.getElementById('nrow');"
                     " const box = document.getElementById('ninput');"
                     " if (!row || row.hidden) return 'no name row';"
                     " if (!box) return 'no name box';"
                     " box.value = 'renamed.txt';"
                     " box.dispatchEvent(new KeyboardEvent('keydown',"
                     "  {key: 'Enter', bubbles: true}));"
                     " await w(1200);"
                     " return Array.from(document.querySelectorAll('.grid .cell'))"
                     "  .map(x => x.getAttribute('data-n'))"
                     "  .filter(n => /^renamed/.test(n)).sort(); })()"),
                  ["renamed (2).txt", "renamed.md", "renamed.txt"])
            check("a-rename-onto-a-taken-name-is-refused-on-disk",
                  sorted(n for n in os.listdir(scratch) if n.startswith("renamed")),
                  ["renamed (2).txt", "renamed.md", "renamed.txt"])

            # New shortcut against a backend: a link on disk, at the name
            # that was typed, pointing where the dialog was told. This
            # reached nothing at all before: doAct handed it to the live
            # layer and the live layer had no branch for it.
            check("new-shortcut-makes-a-link",
                  ev("() => (async () => {" + _arc_helpers +
                     " await window.__live.render(" + json.dumps(scratch) +
                     "); await w(500);"
                     " window.__doAct('newshortcut'); await w(200);"
                     " const d = document.getElementById('dlg-createshortcut');"
                     " if (d.hidden) return 'no dialog';"
                     " const type = (id, v) => { const b = document.getElementById(id);"
                     "  b.value = v; b.dispatchEvent(new Event('input', {bubbles: true})); };"
                     " type('cs-path', " + json.dumps(os.path.join(scratch, "code.py")) + ");"
                     " type('cs-name', 'code-link');"
                     " d.querySelector('[data-dlg=\"primary\"]').click();"
                     " await w(1200);"
                     " return Array.from(document.querySelectorAll('.grid .cell'))"
                     "  .some(x => x.getAttribute('data-n') === 'code-link'); })()"),
                  True)
            _link = os.path.join(scratch, "code-link")
            check("new-shortcut-makes-a-link-on-disk",
                  [os.path.islink(_link),
                   os.readlink(_link) if os.path.islink(_link) else None],
                  [True, os.path.join(scratch, "code.py")])

            # Extract is the reference's DecompressArchiveDialog: the path
            # box holds <folder>/<archive stem> before anything is typed,
            # what is typed is where the files land, and Open destination
            # folder when complete goes there. The password box is there
            # too, and taking one for an archive that has no lock is not an
            # error, which is why the box is not greyed without a probe.
            import zipfile as _zipfile
            with _zipfile.ZipFile(os.path.join(scratch, "plain.zip"), "w") as _z:
                _z.writestr("inside.txt", "from the zip\n")
            check("extract-asks-for-the-path",
                  ev("() => (async () => {" + _arc_helpers +
                     " await window.__live.render(" + json.dumps(scratch) +
                     "); await w(500);"
                     " const c = pick('plain.zip'); if (!c) return 'no plain.zip';"
                     " c.click(); await w(120);"
                     " if (!act('extract')) return 'no extract command';"
                     " await w(600);"
                     " const d = document.getElementById('dlg-extract');"
                     " if (d.hidden) return 'no dialog';"
                     " const box = document.getElementById('ex-path');"
                     " const pathShown = !box.closest('.cdlg-card').hidden;"
                     " const suggested = box.value;"
                     " box.value = " + json.dumps(os.path.join(scratch, "typed-here")) + ";"
                     " document.getElementById('ex-open').checked = true;"
                     " d.querySelector('[data-dlg=\"primary\"]').click();"
                     " await w(2500);"
                     " return [pathShown, suggested, d.hidden, window.__livePath]; })()"),
                  [True, os.path.join(scratch, "plain"), True,
                   os.path.join(scratch, "typed-here")])

            def _typed_here():
                try:
                    with open(os.path.join(scratch, "typed-here", "inside.txt"),
                              encoding="utf-8") as _fh:
                        return _fh.read()
                except OSError:
                    return sorted(os.listdir(scratch))
            check("extract-lands-where-it-was-typed", _typed_here(),
                  "from the zip\n")
            #: Back where the rest of the gates expect to be.
            ev("() => window.__live.render(" + json.dumps(scratch) + ")")

            # Delete against a backend, through the command rather than the
            # test seam: the question first, Cancel leaves the file, Delete
            # sends it to the trash. The row used to vanish from the list
            # with the file still on the disk, because an engine that only
            # ever redrew the screen answered the command before the live
            # layer saw it.
            with open(os.path.join(scratch, "doomed.txt"), "w") as _fh:
                _fh.write("gone soon\n")
            check("delete-through-the-command-reaches-the-disk",
                  ev("() => (async () => {" + _arc_helpers +
                     " await window.__live.render(" + json.dumps(scratch) +
                     "); await w(500);"
                     " const c = pick('doomed.txt'); if (!c) return 'missing';"
                     " c.click(); window.__runCommand('DeleteItem'); await w(300);"
                     " const d = document.getElementById('dlg-fsop');"
                     " const asked = !d.hidden;"
                     " d.querySelector('[data-dlg=\"close\"]').click(); await w(300);"
                     " const kept = !!pick('doomed.txt');"
                     " pick('doomed.txt').click();"
                     " window.__runCommand('DeleteItem'); await w(300);"
                     " d.querySelector('[data-dlg=\"primary\"]').click();"
                     " await w(1500);"
                     " return [asked, kept, !!pick('doomed.txt')]; })()"),
                  [True, True, False])
            check("delete-through-the-command-reaches-the-disk-on-disk",
                  os.path.lexists(os.path.join(scratch, "doomed.txt")), False)

            # Paste onto a taken name asks through the same dialog, with the
            # reference's title and line and one choice per taken name, and
            # the choice is what happens: Replace existing replaces, and the
            # item with a free name comes across as it is. The rule went out
            # in the body of the request, which the Python backend did not
            # read, so every Replace was a second copy until it did.
            os.makedirs(os.path.join(scratch, "into"), exist_ok=True)
            with open(os.path.join(scratch, "into", "clash.txt"), "w") as _fh:
                _fh.write("the old one, which is longer\n")
            with open(os.path.join(scratch, "clash.txt"), "w") as _fh:
                _fh.write("new\n")
            with open(os.path.join(scratch, "free.txt"), "w") as _fh:
                _fh.write("free\n")
            check("paste-asks-about-a-taken-name",
                  ev("() => (async () => {" + _arc_helpers +
                     " await window.__live.render(" + json.dumps(scratch) +
                     "); await w(500);"
                     " const a = pick('clash.txt'), b = pick('free.txt');"
                     " if (!a || !b) return 'missing';"
                     " a.click(); b.classList.add('sel');"
                     " window.__runCommand('CopyItem'); await w(200);"
                     " await window.__live.render(" +
                     json.dumps(os.path.join(scratch, "into")) + "); await w(500);"
                     " window.__runCommand('PasteItem'); await w(900);"
                     " const d = document.getElementById('dlg-fsop');"
                     " const asked = [!d.hidden,"
                     "  document.getElementById('dlg-fsop-t').textContent,"
                     "  document.getElementById('fsop-what').textContent,"
                     "  Array.from(d.querySelectorAll('#fsop-rows .cdlg-lbl'))"
                     "   .map(l => l.textContent),"
                     "  document.getElementById('fsop-all').value,"
                     "  d.querySelector('[data-dlg=\"primary\"]').textContent];"
                     " const sel = d.querySelector('#fsop-rows select');"
                     " sel.value = 'replace';"
                     " sel.dispatchEvent(new Event('change', {bubbles: true}));"
                     " asked.push(document.getElementById('fsop-all').value);"
                     " d.querySelector('[data-dlg=\"primary\"]').click();"
                     " await w(3000);"
                     " return asked; })()"),
                  [True, "Conflicting file names",
                   "There is one conflicting file name, and one outgoing item",
                   ["clash.txt"], "keep-both", "Continue", "replace"])

            # An item that cannot go into an archive is named before anything
            # starts, in the reference's CompressSkippedItemsDialog: Skip goes
            # on to Create archive with the rest, Cancel stops. A link whose
            # far end is gone is the case, and both listings say which rows
            # those are now.
            check("compress-asks-before-leaving-a-broken-link-out",
                  ev("() => (async () => {" + _arc_helpers +
                     " await window.__live.render(" + json.dumps(scratch) +
                     "); await w(500);"
                     " const a = pick('code.py'), b = pick('bad.link');"
                     " if (!a || !b) return 'missing';"
                     " const marked = b.getAttribute('data-broken');"
                     " a.click(); b.classList.add('sel');"
                     " if (!act('compress')) return 'no compress command';"
                     " await w(900);"
                     " const sk = document.getElementById('dlg-compress-skipped');"
                     " const asked = [marked, !sk.hidden,"
                     "  Array.from(sk.querySelectorAll('#skipped-names div'))"
                     "   .map(x => x.textContent),"
                     "  sk.querySelector('[data-dlg=\"primary\"]').textContent];"
                     " sk.querySelector('[data-dlg=\"close\"]').click(); await w(300);"
                     " const ca = document.getElementById('dlg-createarchive');"
                     " asked.push(ca.hidden);"
                     " a.click(); b.classList.add('sel');"
                     " act('compress'); await w(900);"
                     " sk.querySelector('[data-dlg=\"primary\"]').click(); await w(600);"
                     " asked.push(!ca.hidden, document.getElementById('arc-note').textContent);"
                     " ca.querySelector('[data-dlg=\"close\"]').click();"
                     " return asked; })()"),
                  ["1", True, ["bad.link"], "Skip", True, True, "1 item"])

            def _into():
                out = {}
                for n in sorted(os.listdir(os.path.join(scratch, "into"))):
                    with open(os.path.join(scratch, "into", n), encoding="utf-8") as _fh:
                        out[n] = _fh.read()
                return out
            check("paste-replaced-what-was-chosen", _into(),
                  {"clash.txt": "new\n", "free.txt": "free\n"})
            ev("() => window.__live.render(" + json.dumps(scratch) + ")")

            # The name of a conflicting row can be typed over, which is the
            # reference's NameEdit box: a tap on the name of a row set to
            # Generate new name turns it into a box, an empty name or one
            # another row lands under greys Continue, and what is typed is
            # the name the item lands under, with the old file left alone
            # and no numbered copy made. Both backends take the name.
            os.makedirs(os.path.join(scratch, "into2"), exist_ok=True)
            with open(os.path.join(scratch, "into2", "clash2.txt"), "w") as _fh:
                _fh.write("old two\n")
            with open(os.path.join(scratch, "clash2.txt"), "w") as _fh:
                _fh.write("new two\n")
            check("paste-lands-under-the-typed-name",
                  ev("() => (async () => {" + _arc_helpers +
                     " await window.__live.render(" + json.dumps(scratch) +
                     "); await w(500);"
                     " const a = pick('clash2.txt'); if (!a) return 'missing';"
                     " a.click(); window.__runCommand('CopyItem'); await w(200);"
                     " await window.__live.render(" +
                     json.dumps(os.path.join(scratch, "into2")) + "); await w(500);"
                     " window.__runCommand('PasteItem'); await w(900);"
                     " const d = document.getElementById('dlg-fsop');"
                     " if (d.hidden) return 'no dialog';"
                     " const row = d.querySelector('#fsop-rows .cdlg-conflict');"
                     " const lbl = row.querySelector('.cdlg-editable');"
                     " if (!lbl) return 'the name is not editable';"
                     " lbl.click(); await w(50);"
                     " const box = row.querySelector('.cdlg-namebox');"
                     " if (!box) return 'no box';"
                     " const was = box.value;"
                     " const go = d.querySelector('[data-dlg=\"primary\"]');"
                     " const enter = () => box.dispatchEvent(new KeyboardEvent('keydown',"
                     "  {key: 'Enter', bubbles: true, cancelable: true}));"
                     " box.value = ''; enter(); await w(50);"
                     " const refused = [!!row.querySelector('.cdlg-namebox.bad'), go.disabled];"
                     " box.value = 'typed.txt'; enter(); await w(50);"
                     " const shown = row.querySelector('.cdlg-lbl').textContent;"
                     " const ready = !go.disabled;"
                     " go.click(); await w(3000);"
                     " return [was, refused, shown, ready, d.hidden]; })()"),
                  ["clash2.txt", [True, True], "typed.txt", True, True])

            def _into2():
                out = {}
                for n in sorted(os.listdir(os.path.join(scratch, "into2"))):
                    with open(os.path.join(scratch, "into2", n), encoding="utf-8") as _fh:
                        out[n] = _fh.read()
                return out
            check("paste-lands-under-the-typed-name-on-disk", _into2(),
                  {"clash2.txt": "old two\n", "typed.txt": "new two\n"})
            ev("() => window.__live.render(" + json.dumps(scratch) + ")")

            # The Extract dialog's Encoding row, for a zip whose names were
            # written without the UTF-8 flag. The reference shows it only for
            # such an archive, IsArchiveEncodingUndetermined, and a chosen
            # code page is what the names are read in: the Japanese name of
            # this hand written zip lands on the disk as itself rather than
            # as the CP437 mojibake every zip tool makes of it untold.
            import struct as _struct
            import zlib as _zlib

            def _legacy_zip(name, content, utf8_flag=False):
                crc = _zlib.crc32(content) & 0xFFFFFFFF
                flags = 0x800 if utf8_flag else 0
                local = (_struct.pack("<IHHHHHIIIHH", 0x04034b50, 20, flags, 0,
                                      0, 0x21, crc, len(content), len(content),
                                      len(name), 0) + name + content)
                central = (_struct.pack("<IHHHHHHIIIHHHHHII", 0x02014b50, 20,
                                        20, flags, 0, 0, 0x21, crc,
                                        len(content), len(content), len(name),
                                        0, 0, 0, 0, 0, 0) + name)
                end = _struct.pack("<IHHHHIIH", 0x06054b50, 0, 0, 1, 1,
                                   len(central), len(local), 0)
                return local + central + end
            _jp = "日本語のファイル名を持つ文書です.txt"
            with open(os.path.join(scratch, "legacy.zip"), "wb") as _fh:
                _fh.write(_legacy_zip(_jp.encode("shift_jis"), b"content"))
            import zipfile as _zipfile
            with _zipfile.ZipFile(os.path.join(scratch, "plain.zip"), "w") as _zf:
                _zf.writestr("plain.txt", "plain")
            _detected = ("Japanese (Shift-JIS) (detected)" if _rust
                         else "Default")
            check("extract-asks-the-encoding-only-when-the-names-are-in-question",
                  ev("() => (async () => {" + _arc_helpers +
                     " await window.__live.render(" + json.dumps(scratch) +
                     "); await w(500);"
                     " const open = async (file) => {"
                     "  const c = pick(file); if (!c) return 'no ' + file;"
                     "  c.click(); await w(120);"
                     "  if (!act('extract')) return 'no extract command';"
                     "  await w(1500);"
                     "  const d = document.getElementById('dlg-extract');"
                     "  return d.hidden ? 'no dialog' : d; };"
                     " const d = await open('legacy.zip');"
                     " if (typeof d === 'string') return d;"
                     " const card = document.getElementById('ex-encoding-card');"
                     " const box = document.getElementById('ex-encoding');"
                     " const opts = Array.from(box.options).map(o => o.textContent);"
                     " const asked = [!card.hidden, opts[0], opts.length,"
                     "  opts.indexOf('Default') >= 0, opts.indexOf('Japanese (Shift-JIS)') >= 0];"
                     " box.value = 'shift_jis';"
                     " document.getElementById('ex-path').value = " +
                     json.dumps(os.path.join(scratch, "legacy-out")) + ";"
                     " d.querySelector('[data-dlg=\"primary\"]').click();"
                     " await w(2500);"
                     " asked.push(d.hidden);"
                     " await window.__live.render(" + json.dumps(scratch) +
                     "); await w(500);"
                     " const d2 = await open('plain.zip');"
                     " if (typeof d2 === 'string') return d2;"
                     " asked.push(document.getElementById('ex-encoding-card').hidden);"
                     " d2.querySelector('[data-dlg=\"secondary\"]').click(); await w(200);"
                     " return asked; })()"),
                  [True, _detected, 18 if _rust else 17, True, True, True, True])
            check("extract-read-the-names-in-the-chosen-encoding",
                  os.path.exists(os.path.join(scratch, "legacy-out", _jp)),
                  True)
            ev("() => window.__live.render(" + json.dumps(scratch) + ")")

            # The General tab's icon is the item's own, in the reference's
            # 56px card, and the album cover flyout over it is offered for
            # a sound or video file, not for .avi, and not for anything
            # else. A PNG drawn here, a track from ffmpeg, two names that
            # are only names, and a zip whose files add up to a number.
            import zlib as _zlib
            import struct as _struct

            def _png(path, rgb, w=8, h=8):
                raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

                def chunk(kind, data):
                    return (_struct.pack(">I", len(data)) + kind + data +
                            _struct.pack(">I", _zlib.crc32(kind + data) & 0xffffffff))
                with open(path, "wb") as fh:
                    fh.write(b"\x89PNG\r\n\x1a\n"
                             + chunk(b"IHDR", _struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                             + chunk(b"IDAT", _zlib.compress(raw))
                             + chunk(b"IEND", b""))
            _art = os.path.join(scratch, "art.png")
            _png(_art, (220, 20, 20))
            _song = os.path.join(scratch, "silence.mp3")
            _ffmpeg = shutil.which("ffmpeg")
            if _ffmpeg:
                subprocess.run([_ffmpeg, "-nostdin", "-loglevel", "error", "-f", "lavfi",
                                "-i", "anullsrc=r=8000:cl=mono", "-t", "0.5", _song],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=60)
            if not os.path.exists(_song):
                open(_song, "wb").close()
            for _n in ("clip.mp4", "clip.avi"):
                open(os.path.join(scratch, _n), "wb").close()
            import zipfile as _zipfile
            with _zipfile.ZipFile(os.path.join(scratch, "packed.zip"), "w") as _z:
                _z.writestr("one.txt", "a" * 1000)
                _z.writestr("two.txt", "b" * 2345)
                _z.writestr("sub/", "")
            _open_props = (
                " const openProps = async n => {"
                "  await window.__live.render(" + json.dumps(scratch) + "); await w(500);"
                "  const c = pick(n); if (!c) return 'missing ' + n;"
                "  c.click(); await w(120);"
                "  document.querySelector('.toolbar [data-act=\"ctx-props\"]').click();"
                "  await w(1400); return true; };"
                " const closeProps = async () => {"
                "  document.getElementById('props').hidden = true; await w(150); };"
                " const paths = svg => svg ? Array.from(svg.querySelectorAll('path'))"
                "  .map(p => p.getAttribute('d') || '').join('|') : '';"
                " const coverOf = async n => (await fetch(window.__api"
                "  + '/api/album-cover?path=' + encodeURIComponent("
                + json.dumps(scratch) + " + '/' + n))).json();")
            check("props-icon-is-the-items-own-and-the-cover-flyout-knows-its-files",
                  ev("() => (async () => {" + _arc_helpers + _open_props +
                     " const look = async n => {"
                     "  const a = await openProps(n); if (a !== true) return a;"
                     "  const card = document.getElementById('props-icon');"
                     "  const art = document.getElementById('props-icon-art');"
                     "  const wrap = document.getElementById('props-cover-wrap');"
                     "  const g = card.getBoundingClientRect();"
                     "  const mine = paths(art.querySelector('svg'));"
                     "  const rows = paths(pick(n).querySelector('.thumb svg, .ricobox svg'));"
                     "  const out = [Math.round(g.width), Math.round(g.height),"
                     "   mine.length > 20 && mine === rows, !wrap.hidden,"
                     "   Array.from(document.querySelectorAll('#m-cover .mi'))"
                     "    .map(r => r.textContent.trim())];"
                     "  await closeProps(); return out; };"
                     " return [await look('silence.mp3'), await look('clip.mp4'),"
                     "  await look('clip.avi'), await look('code.py')]; })()"),
                  [[56, 56, True, True, ["Change album cover", "Remove album cover"]],
                   [56, 56, True, True, ["Change album cover", "Remove album cover"]],
                   [56, 56, True, False, ["Change album cover", "Remove album cover"]],
                   [56, 56, True, False, ["Change album cover", "Remove album cover"]]])

            # The row FileProperties fills for a browsable archive: the
            # files inside, summed, in the long form the Size row uses.
            check("props-uncompressed-size-of-an-archive",
                  ev("() => (async () => {" + _arc_helpers + _open_props +
                     " const a = await openProps('packed.zip'); if (a !== true) return a;"
                     " const row = document.getElementById('prow-uncompressed');"
                     " const first = [!row.hidden, row.querySelector('.pk').textContent,"
                     "  row.querySelector('.pv').textContent];"
                     " await closeProps();"
                     " const b = await openProps('code.py'); if (b !== true) return b;"
                     " const second = row.hidden;"
                     " await closeProps();"
                     " return [first, second]; })()"),
                  [[True, "Uncompressed size:", "3.3 KB (3,345 bytes)"], True])

            # The commands that only the Rust backend answers. Skipped rather
            # than failed against the Python one, because the page asks what
            # the backend can do and offers what is there: a gate that ran
            # against both would be testing the wrong thing on one of them.
            if _rust:
                # Something big enough and repetitive enough that Store and
                # Normal cannot produce the same file. code.py is a few dozen
                # bytes and a zip of it is larger than it either way, so a gate
                # over that one says nothing about whether the level box works.
                _bulk = os.path.join(scratch, "bulk.txt")
                _words = ["alpha", "beta", "gamma", "delta", "epsilon",
                          "zeta", "eta", "theta"]
                _seed = 7
                _lines = []
                while sum(len(x) for x in _lines) < 200 * 1024:
                    _row = ["%06d" % len(_lines)]
                    for _ in range(8):
                        _seed = (_seed * 6364136223846793005 + 1) % (1 << 64)
                        _row.append(_words[(_seed >> 33) % len(_words)])
                    _lines.append(" ".join(_row) + "\n")
                with open(_bulk, "w", encoding="utf-8") as _fh:
                    _fh.write("".join(_lines))

                # Create archive: a real archive on disk, with the level and
                # the password the boxes were set to. It was a bar across the
                # window and is the reference's dialog now, so the geometry
                # below asks the dialog rather than the row.
                check("live-compress-options",
                      ev("() => (async () => {" + _arc_helpers +
                         " await window.__live.render(" + json.dumps(scratch) +
                         "); await w(500);"
                         " const c = pick('bulk.txt'); if (!c) return 'no bulk.txt';"
                         " c.click(); await w(120);"
                         " if (!act('compress')) return 'no compress command';"
                         " await w(400);"
                         " const row = document.getElementById('dlg-createarchive');"
                         " if (!row || row.hidden) return 'the dialog did not open';"
                         " const geom = row.getBoundingClientRect();"
                         " document.getElementById('arc-name').value = 'gated';"
                         " const fmt = document.getElementById('arc-format');"
                         " fmt.value = '7z';"
                         " fmt.dispatchEvent(new Event('change', {bubbles: true}));"
                         " await w(60);"
                         " const pw = document.getElementById('arc-password');"
                         " const lockedFor7z = pw.disabled;"
                         " fmt.value = 'tar.gz';"
                         " fmt.dispatchEvent(new Event('change', {bubbles: true}));"
                         " await w(60);"
                         " const lockedForTar = pw.disabled;"
                         " fmt.value = 'zip';"
                         " fmt.dispatchEvent(new Event('change', {bubbles: true}));"
                         " await w(60);"
                         " pw.value = 'hunter2';"
                         " document.getElementById('arc-level').value = 'store';"
                         " document.querySelector('#dlg-createarchive"
                         " [data-dlg=\"primary\"]').click();"
                         " await w(2500);"
                         " return [geom.width > 200, geom.height > 20,"
                         " lockedFor7z, lockedForTar, pw.disabled,"
                         " document.getElementById('dlg-createarchive').hidden]; })()"),
                      [True, True, False, True, False, True])
                _gated = os.path.join(scratch, "gated.zip")
                check("live-compress-wrote-an-archive",
                      [os.path.exists(_gated),
                       os.path.getsize(_gated) > 0 if os.path.exists(_gated) else False],
                      [True, True])
                # Store means store. Deflate at any other setting takes this
                # payload to about a sixth of its size, so an archive that is
                # not smaller than the source is one where the level box
                # reached the codec.
                check("live-compress-honoured-the-level",
                      os.path.exists(_gated) and
                      os.path.getsize(_gated) >= os.path.getsize(_bulk),
                      True)
                # And the password reached the file. A zip leaves names in
                # clear whatever the password, so the content is what is read.
                def _zip_is_encrypted(path):
                    try:
                        import zipfile
                        with zipfile.ZipFile(path) as z:
                            info = z.infolist()[0]
                            # bit 0 of the general purpose flag
                            return bool(info.flag_bits & 0x1)
                    except Exception as exc:
                        return "error " + str(exc)
                check("live-compress-encrypted", _zip_is_encrypted(_gated), True)

                # An archive that is locked asks for its password through
                # the same dialog with the path row put away, which is what
                # BaseDecompressArchiveAction does for the three shortcuts.
                # A wrong password asks again and says what the backend said;
                # the right one opens the archive. It was window.prompt.
                check("extract-here-asks-for-the-password",
                      ev("() => (async () => {" + _arc_helpers +
                         " await window.__live.render(" + json.dumps(scratch) +
                         "); await w(500);"
                         " const c = pick('gated.zip'); if (!c) return 'no gated.zip';"
                         " c.click(); await w(120);"
                         " if (!act('extract-child')) return 'no extract command';"
                         " await w(1800);"
                         " const d = document.getElementById('dlg-extract');"
                         " if (d.hidden) return 'no dialog';"
                         " const pathHidden = document.getElementById('ex-path')"
                         "  .closest('.cdlg-card').hidden;"
                         " const pw = document.getElementById('ex-password');"
                         " pw.value = 'wrong';"
                         " d.querySelector('[data-dlg=\"primary\"]').click();"
                         " await w(1800);"
                         " const again = !d.hidden;"
                         " const said = document.getElementById('ex-note').textContent;"
                         " pw.value = 'hunter2';"
                         " d.querySelector('[data-dlg=\"primary\"]').click();"
                         " await w(2500);"
                         " return [pathHidden, again, said.length > 0, d.hidden]; })()"),
                      [True, True, True, True])
                check("extract-here-opened-the-archive",
                      os.path.exists(os.path.join(scratch, "gated", "bulk.txt")),
                      True)

                # Splitting into numbered parts. The box is only offered for
                # 7z, so the gate watches it appear and disappear as the
                # format changes, and then compresses with it set.
                _split_note = os.path.join(scratch, "note.txt")
                with open(_split_note, "w", encoding="utf-8") as _fh:
                    _fh.write("one line and a newline\n")
                check("live-compress-split-options",
                      ev("() => (async () => {" + _arc_helpers +
                         " await window.__live.render(" + json.dumps(scratch) +
                         "); await w(500);"
                         " const c = pick('note.txt'); if (!c) return 'no note.txt';"
                         " c.click(); await w(120);"
                         " if (!act('compress')) return 'no compress command';"
                         " await w(400);"
                         " const box = document.getElementById('arc-split');"
                         " if (!box) return 'no split box';"
                         " const fmt = document.getElementById('arc-format');"
                         " const at = async v => { fmt.value = v;"
                         "  fmt.dispatchEvent(new Event('change', {bubbles: true}));"
                         "  await w(60); return box.disabled; };"
                         " const hiddenForZip = await at('zip');"
                         " const hiddenForTar = await at('tar.gz');"
                         " const hiddenFor7z = await at('7z');"
                         " const sizes = Array.from(box.options).map(o => o.value);"
                         " document.getElementById('arc-name').value = 'parted';"
                         " box.value = '10m';"
                         " document.querySelector('#dlg-createarchive"
                         " [data-dlg=\"primary\"]').click();"
                         " await w(3000);"
                         " return [hiddenForZip, hiddenForTar, hiddenFor7z,"
                         " sizes[0], sizes.length,"
                         " document.getElementById('dlg-createarchive').hidden]; })()"),
                      [True, True, False, "none", 12, True])
                # What is on disk is the set, not the archive: the name that
                # was typed is gone and .001 stands in its place. That is the
                # difference between the size reaching the backend and being
                # read off the form and dropped.
                _parted = os.path.join(scratch, "parted.7z")
                check("live-compress-split-wrote-parts",
                      [os.path.exists(_parted + ".001"),
                       os.path.exists(_parted),
                       os.path.getsize(_parted + ".001") > 0
                       if os.path.exists(_parted + ".001") else False],
                      [True, False, True])
                # And the set opens as one archive through its first part.
                # Into a child folder rather than here, so what comes out is a
                # file that was not there before: extracting over the original
                # would pass whether or not a byte was written.
                check("live-compress-split-extracts",
                      ev("() => (async () => {" + _arc_helpers +
                         " await window.__live.render(" + json.dumps(scratch) +
                         "); await w(500);"
                         " const c = pick('parted.7z.001');"
                         " if (!c) return 'no parted.7z.001';"
                         " c.click(); await w(120);"
                         " if (!act('extract-child')) return 'no extract command';"
                         " await w(2500); return true; })()"),
                      True)
                def _split_round_trip():
                    # Named for the archive, not for the piece: parted.7z.001
                    # is one part of parted.7z and unpacks into parted.
                    out = os.path.join(scratch, "parted", "note.txt")
                    if not os.path.exists(out):
                        return sorted(os.listdir(scratch))
                    with open(out, encoding="utf-8") as fh:
                        return fh.read()
                check("live-compress-split-round-trip", _split_round_trip(),
                      "one line and a newline\n")

                # Dictionary size, Word size and CPU threads, with the two
                # memory lines: the reference's CreateArchiveDialog has them
                # for 7z, greyed for anything else, IsEnabled bound to
                # CanSplit. The lists and the estimate are the backend's own.
                check("compress-lzma-boxes-follow-the-format",
                      ev("() => (async () => {" + _arc_helpers +
                         " await window.__live.render(" + json.dumps(scratch) +
                         "); await w(500);"
                         " const c = pick('bulk.txt'); if (!c) return 'no bulk.txt';"
                         " c.click(); await w(120);"
                         " if (!act('compress')) return 'no compress command';"
                         " await w(600);"
                         " const row = document.getElementById('dlg-createarchive');"
                         " if (!row || row.hidden) return 'the dialog did not open';"
                         " const g = id => document.getElementById(id);"
                         " const fmt = g('arc-format');"
                         " const set = (el, v) => { el.value = v;"
                         "  el.dispatchEvent(new Event('change', {bubbles: true})); };"
                         " const state = () => [g('arc-dict').disabled, g('arc-word').disabled,"
                         "  g('arc-threads').disabled, g('arc-memory').hidden];"
                         " set(fmt, 'zip'); await w(400);"
                         " const forZip = state();"
                         " set(fmt, '7z'); await w(600);"
                         " const for7z = state();"
                         " const lines = [g('arc-mem-est').textContent, g('arc-mem-avail').textContent];"
                         " const lists = [g('arc-dict').options.length, g('arc-word').options.length,"
                         "  g('arc-dict').options[1].textContent, g('arc-dict').options[13].textContent,"
                         "  g('arc-word').options[7].textContent];"
                         " const threads = [Number(g('arc-threads').max) >= 1,"
                         "  g('arc-threads').value === g('arc-threads').max];"
                         " set(g('arc-dict'), '65536'); await w(600);"
                         " const small = g('arc-mem-est').textContent;"
                         " set(g('arc-dict'), '16777216'); await w(600);"
                         " const big = g('arc-mem-est').textContent;"
                         " row.querySelector('[data-dlg=\"close\"]').click(); await w(200);"
                         " return [forZip, for7z, lines.map(t => t.split(':')[0]), lists, threads,"
                         "  small !== big, /\\d/.test(small)]; })()"),
                      [[True, True, True, True], [False, False, False, False],
                       ["Estimated memory usage", "Available memory"],
                       [14, 8, "64 KB", "1.0 GB", "273"], [True, True],
                       True, True])

                # And each knob reaches the codec. A block of noise written
                # twice compresses to about half with a dictionary that can
                # see back to the first copy and not at all with one that
                # cannot; a match finder told to stop at 8 bytes writes a
                # different stream from one told to look for 273; and chunks
                # compressed on two threads are a different stream from one.
                import random as _random
                _rng = _random.Random(11)
                _block = bytes(_rng.getrandbits(8) for _ in range(96 * 1024))
                with open(os.path.join(scratch, "twice.bin"), "wb") as _fh:
                    _fh.write(_block + _block)
                with open(os.path.join(scratch, "big.txt"), "w", encoding="utf-8") as _fh:
                    _fh.write("".join(_lines) * 16)
                _arc_go = (
                    #: The bodies the page posts to /api/compress, so a gate can
                    #: say what was sent rather than infer it from the archive.
                    #: A mutation that sent one thread for every archive once
                    #: escaped: the two archives still differed byte for byte.
                    " if (!window.__sentArc) { window.__sentArc = [];"
                    "  const realFetch = window.fetch;"
                    "  window.fetch = function (url, init) {"
                    "   try { if (String(url).indexOf('/api/compress') >= 0 && init && init.body) {"
                    "    window.__sentArc.push(JSON.parse(init.body)); } } catch (e) {}"
                    "   return realFetch.apply(this, arguments); }; }"
                    " const sentArc = () => window.__sentArc.splice(0).map(b => ["
                    "  (b.paths || []).map(p => p.split('/').pop()),"
                    "  b.dictionary === undefined ? null : b.dictionary,"
                    "  b.word_size === undefined ? null : b.word_size,"
                    "  b.threads === undefined ? null : b.threads]);"
                    " const arc = async (file, name, set) => {"
                    "  await window.__live.render(" + json.dumps(scratch) + "); await w(400);"
                    "  const c = pick(file); if (!c) return 'no ' + file;"
                    "  c.click(); await w(100);"
                    "  if (!act('compress')) return 'no compress command';"
                    "  await w(400);"
                    "  const row = document.getElementById('dlg-createarchive');"
                    "  if (!row || row.hidden) return 'the dialog did not open';"
                    "  document.getElementById('arc-name').value = name;"
                    "  const put = (id, v) => { const el = document.getElementById(id);"
                    "   el.value = String(v);"
                    "   el.dispatchEvent(new Event('change', {bubbles: true})); };"
                    "  put('arc-format', '7z'); await w(300);"
                    "  put('arc-level', 'normal');"
                    "  for (const [id, v] of Object.entries(set)) put(id, v);"
                    "  await w(300);"
                    "  const greyed = ['arc-dict', 'arc-word', 'arc-threads']"
                    "   .filter(id => document.getElementById(id).disabled);"
                    "  row.querySelector('[data-dlg=\"primary\"]').click();"
                    "  await w(3500);"
                    "  return [row.hidden, greyed]; };")
                # One pair a call: the socket allows a call twenty five
                # seconds, and six archives in one would not fit.
                #: Each gate answers with the two dialogs' outcomes and then
                #: the two bodies: the file each archive holds and the three
                #: knobs as sent. Auto is sent as nothing at all, so a knob the
                #: gate did not set reads null, or the value the previous pair
                #: left in the box, which the dialog keeps the way the
                #: reference keeps its settings.
                for _gate, _pair, _sent in [
                    ("compress-dictionary-was-sent",
                     " out.push(await arc('twice.bin', 'dict-small', {'arc-dict': 65536, 'arc-threads': 1}));"
                     " out.push(await arc('twice.bin', 'dict-big', {'arc-dict': 1048576, 'arc-threads': 1}));",
                     [[["twice.bin"], 65536, None, 1], [["twice.bin"], 1048576, None, 1]]),
                    ("compress-word-size-was-sent",
                     " out.push(await arc('bulk.txt', 'word-8', {'arc-word': 8, 'arc-threads': 1}));"
                     " out.push(await arc('bulk.txt', 'word-273', {'arc-word': 273, 'arc-threads': 1}));",
                     [[["bulk.txt"], 1048576, 8, 1], [["bulk.txt"], 1048576, 273, 1]]),
                    ("compress-threads-were-sent",
                     " out.push(await arc('big.txt', 'one-thread', {'arc-dict': 65536, 'arc-threads': 1}));"
                     " out.push(await arc('big.txt', 'two-threads', {'arc-dict': 65536, 'arc-threads': 2}));",
                     [[["big.txt"], 65536, 273, 1], [["big.txt"], 65536, 273, 2]]),
                ]:
                    check(_gate,
                          ev("() => (async () => {" + _arc_helpers + _arc_go +
                             " sentArc(); const out = [];" + _pair +
                             " out.push(sentArc()); return out; })()"),
                          [[True, []]] * 2 + [_sent])

                def _size(name):
                    p = os.path.join(scratch, name)
                    return os.path.getsize(p) if os.path.exists(p) else None

                check("compress-dictionary-reaches-the-codec",
                      [_size("dict-small.7z") is not None and
                       _size("dict-big.7z") is not None and
                       _size("dict-small.7z") > _size("dict-big.7z") * 1.5,
                       _size("dict-big.7z") is not None and
                       _size("dict-big.7z") < 120 * 1024],
                      [True, True])
                check("compress-word-size-reaches-the-codec",
                      _size("word-8.7z") is not None and
                      _size("word-273.7z") is not None and
                      _size("word-8.7z") != _size("word-273.7z"),
                      True)
                #: Sizes, not bytes. The 7z entry records the file's access
                #: time, and on a relatime mount the first archive's read
                #: updates it, so two archives of the same file with the same
                #: knobs differ byte for byte and a bytes gate passed with
                #: threads ignored. A stream cut into chunks for a second
                #: thread is a different length from one that was not.
                check("compress-threads-reach-the-codec",
                      _size("one-thread.7z") is not None and
                      _size("two-threads.7z") is not None and
                      _size("one-thread.7z") != _size("two-threads.7z"),
                      True)
                # What came out of two threads still extracts to what went in.
                check("compress-two-threads-still-round-trips",
                      ev("() => (async () => {" + _arc_helpers +
                         " await window.__live.render(" + json.dumps(scratch) +
                         "); await w(500);"
                         " const c = pick('two-threads.7z'); if (!c) return 'no archive';"
                         " c.click(); await w(120);"
                         " if (!act('extract-child')) return 'no extract command';"
                         " await w(4000);"
                         " return true; })()"),
                      True)

                def _round_trip():
                    p = os.path.join(scratch, "two-threads", "big.txt")
                    if not os.path.exists(p):
                        return "missing"
                    return open(p, encoding="utf-8").read() == "".join(_lines) * 16
                check("compress-two-threads-round-trip-on-disk", _round_trip(), True)
                ev("() => window.__live.render(" + json.dumps(scratch) + ")")

                # The Status Center card, filled from the job rather than from
                # a timer. The prototype's version invented its numbers: a
                # copy that had not started claimed 28.4 MB/s against a total
                # of ten megabytes an item. These are the bytes the backend
                # says it moved, so the gate compares them with the file.
                _bulk_kb = round(os.path.getsize(_bulk) / 1024)
                check("live-job-reports-real-progress",
                      ev("() => (async () => {" + _arc_helpers +
                         " if (!window.StatusCenter) return 'no status center';"
                         " await window.__live.render(" + json.dumps(scratch) +
                         "); await w(500);"
                         " window.StatusCenter.clearCompleted();"
                         " const before = window.StatusCenter.getTasks().length;"
                         " const c = pick('bulk.txt'); if (!c) return 'no bulk.txt';"
                         " c.click(); await w(120);"
                         " if (!act('ctx-zip')) return 'no zip command';"
                         " await w(4000);"
                         " const tasks = window.StatusCenter.getTasks();"
                         " const mine = tasks[tasks.length - 1];"
                         " if (!mine) return 'no task was made';"
                         " const st = mine.getState();"
                         " const shape = /^([0-9.]+) KB of ([0-9.]+) KB$/"
                         "  .exec(st.processedBytes || '');"
                         " return [before, tasks.length, st.title, st.state,"
                         " st.progress, st.isPausable,"
                         " shape ? Math.round(parseFloat(shape[1])) : st.processedBytes,"
                         " shape ? Math.round(parseFloat(shape[2])) : st.processedBytes];"
                         " })()"),
                      [0, 1, "Compressing to bulk.zip", "Successful", 100,
                       False, _bulk_kb, _bulk_kb])

                # The Signatures tab. Files reads Authenticode there; the
                # nearest true thing here is a detached OpenPGP signature, so
                # the fixture is a real one, made with a key in the scratch
                # keyring rather than in anybody's own.
                def _sign_fixture():
                    import shutil as _sh
                    if not _sh.which("gpg"):
                        return "gpg is not installed"
                    quiet = dict(os.environ, GNUPGHOME=_keyring)
                    made = subprocess.run(
                        ["gpg", "--batch", "--pinentry-mode", "loopback",
                         "--passphrase", "", "--quick-generate-key",
                         "AuraDE Suite <suite@aurade.invalid>",
                         "ed25519", "sign", "0"],
                        env=quiet, capture_output=True, text=True, timeout=120)
                    if made.returncode != 0:
                        return "gpg key: " + made.stderr.strip()[-120:]
                    target = os.path.join(scratch, "signed.txt")
                    with open(target, "w", encoding="utf-8") as fh:
                        fh.write("a file worth signing\n")
                    signed = subprocess.run(
                        ["gpg", "--batch", "--pinentry-mode", "loopback",
                         "--passphrase", "", "--detach-sign",
                         "--output", target + ".sig", target],
                        env=quiet, capture_output=True, text=True, timeout=120)
                    if signed.returncode != 0:
                        return "gpg sign: " + signed.stderr.strip()[-120:]
                    return True
                _signable = _sign_fixture()
                if _signable is not True:
                    print("skip signatures gates: " + str(_signable))
                else:
                    _sig_probe = (
                        "() => (async () => {" + _arc_helpers +
                        " const open = async n => { const c = pick(n);"
                        "  if (!c) return 'missing ' + n; c.click(); await w(120);"
                        "  document.querySelector"
                        "('.toolbar [data-act=\"ctx-props\"]').click();"
                        "  await w(1600); return true; };"
                        " const shut = async () => {"
                        "  document.getElementById('props').hidden = true;"
                        "  await w(120); };"
                        " const tab = () => document.querySelector"
                        "('#props [data-ptab=\"signatures\"]');"
                        " const txt = id => (document.getElementById(id) || {})"
                        ".textContent;"
                        " await window.__live.render(" + json.dumps(scratch) +
                        "); await w(600);"
                        " const plain = await open('code.py');"
                        " if (plain !== true) return plain;"
                        " const hiddenForPlain = tab().hidden;"
                        " await shut();"
                        " const one = await open('signed.txt');"
                        " if (one !== true) return one;"
                        " const shown = !tab().hidden;"
                        " const out = [hiddenForPlain, shown, txt('sig-status'),"
                        " txt('sig-signer'), txt('sig-file'),"
                        " (txt('sig-detail') || '').indexOf('Good signature') >= 0];"
                        " await shut(); return out; })()")
                    check("props-signatures",
                          ev(_sig_probe),
                          [True, True,
                           "Signed, by a key you have marked as trusted",
                           "AuraDE Suite <suite@aurade.invalid>",
                           "signed.txt.sig", True])
                    # And a file that has changed since it was signed says so,
                    # rather than showing the same green line with a stale
                    # answer behind it.
                    with open(os.path.join(scratch, "signed.txt"),
                              "w", encoding="utf-8") as _fh:
                        _fh.write("a file worth signing, edited\n")
                    check("props-signatures-notices-a-change",
                          ev("() => (async () => {" + _arc_helpers +
                             " const shut = () => {"
                             "  document.getElementById('props').hidden = true; };"
                             " shut();"
                             " await window.__live.render(" + json.dumps(scratch) +
                             "); await w(600);"
                             " const c = pick('signed.txt');"
                             " if (!c) return 'no signed.txt';"
                             " c.click(); await w(120);"
                             " document.querySelector"
                             "('.toolbar [data-act=\"ctx-props\"]').click();"
                             " await w(1600);"
                             " const tab = document.querySelector"
                             "('#props [data-ptab=\"signatures\"]');"
                             " const note = document.getElementById('sig-note');"
                             " const out = [!tab.hidden,"
                             " document.getElementById('sig-status').textContent,"
                             " !note.hidden];"
                             " shut(); return out; })()"),
                          [True, "The signature does not match this file", True])

                # Turning a picture, from the menu, all the way to the file.
                # Its own fixture, and a lopsided one: shot.png is a single
                # flat colour, so a gate over it cannot tell a turn to the
                # left from a turn to the right, or from no turn at all.
                _turn = os.path.join(scratch, "turn.png")
                if have_pil:
                    from PIL import Image as _RotImg
                    _lop = _RotImg.new("RGB", (4, 6))
                    _lop.putdata([((x * 60) % 256, (y * 40) % 256,
                                   ((x + 1) * (y + 1) * 7) % 256)
                                  for y in range(6) for x in range(4)])
                    _lop.save(_turn)
                    _want = _lop.transpose(_RotImg.ROTATE_270)  # clockwise
                    check("live-rotate",
                          ev("() => (async () => {" + _arc_helpers +
                             " await window.__live.render(" + json.dumps(scratch) +
                             "); await w(600);"
                             " const c = pick('turn.png'); if (!c) return 'no turn.png';"
                             " c.click(); await w(120);"
                             " if (!act('rotate-right')) return 'no rotate command';"
                             " await w(1800); return true; })()"),
                          True)
                    with _RotImg.open(_turn) as _got:
                        _got = _got.convert("RGB")
                        check("live-rotate-turned-the-file",
                              [_got.size, _got.tobytes() == _want.tobytes()],
                              [(6, 4), True])

                # The Details tab, filled from the file rather than from the
                # page: a section that stays hidden for a text file and opens
                # for a picture. The size is read now rather than written
                # down, because the rotate gate above has already turned it.
                def _shot_dims():
                    if not have_pil:
                        return ""
                    from PIL import Image as _DimImg
                    with _DimImg.open(os.path.join(scratch, "shot.png")) as im:
                        return f"{im.size[0]} x {im.size[1]}"
                # shot.png is untouched by the turn above, so this says the
                # dimensions come from the file rather than from anything the
                # page remembered.
                check("props-details-sections",
                      ev("() => (async () => {" + _arc_helpers +
                         " const open = async n => { const c = pick(n);"
                         "  if (!c) return 'missing ' + n; c.click(); await w(120);"
                         "  document.querySelector"
                         "('.toolbar [data-act=\"ctx-props\"]').click();"
                         "  await w(1400); return true; };"
                         " const shut = async () => {"
                         "  document.getElementById('props').hidden = true;"
                         "  await w(120); };"
                         " await window.__live.render(" + json.dumps(scratch) +
                         "); await w(500);"
                         " const a = await open('code.py');"
                         " if (a !== true) return a;"
                         " const textCam = document.getElementById('det-camera').hidden;"
                         " await shut();"
                         " const b = await open('shot.png');"
                         " if (b !== true) return b;"
                         " const picCam = document.getElementById('det-camera').hidden;"
                         " const dims = document.querySelector"
                         "('[data-detk=\"Dimensions\"]').textContent;"
                         " await shut();"
                         " return [textCam, picCam, dims]; })()"),
                      [True, False, _shot_dims()])

                # A selection left behind in a layout that is no longer
                # showing. Files keeps all five layout containers rendered and
                # hides the four that are not current, and the hidden ones keep
                # their .sel classes, so a query across all of them returns
                # rows nobody can see. That was the wrong set to compress and
                # the wrong file for the properties dialog to describe.
                check("stale-selection-in-a-hidden-layout",
                      ev("() => (async () => {" + _arc_helpers +
                         " window.__setLayout('grid');"
                         " await window.__live.render(" + json.dumps(scratch) +
                         "); await w(600);"
                         " const shot = pick('shot.png');"
                         " if (!shot) return 'no shot.png'; shot.click(); await w(150);"
                         " const selectedInGrid = document.querySelectorAll"
                         "('.grid .sel').length;"
                         # Switched, not re-rendered. A render rebuilds all
                         # five containers and clears them; changing layout
                         # only changes which one is showing, which is what a
                         # person does with the toolbar and what leaves the
                         # selection sitting in a container they can no longer
                         # see.
                         " window.__setLayout('list'); await w(400);"
                         " const gridStillHolds = document.querySelectorAll"
                         "('.grid .sel').length;"
                         " const gridIsHidden = !document.querySelector('.grid')"
                         ".getBoundingClientRect().height;"
                         " const row = Array.from(document.querySelectorAll('.list .lrow'))"
                         ".find(x => x.getAttribute('data-n') === 'code.py');"
                         " if (!row) return 'no code.py row';"
                         " row.click(); await w(150);"
                         " if (!act('ctx-zip')) return 'no zip command';"
                         " await w(2500);"
                         " document.querySelector"
                         "('.toolbar [data-act=\"ctx-props\"]').click();"
                         " await w(1400);"
                         " const cam = document.getElementById('det-camera').hidden;"
                         " const dims = document.querySelector"
                         "('[data-detk=\"Dimensions\"]').textContent;"
                         " document.getElementById('props').hidden = true;"
                         " window.__setLayout('grid'); await w(200);"
                         " return [selectedInGrid, gridStillHolds, gridIsHidden,"
                         " cam, dims]; })()"),
                      # The grid keeps its selection and is not on screen; the
                      # dialog is about code.py, so no camera section and no
                      # dimensions.
                      [1, 1, True, True, ""])

                def _zip_names(path):
                    try:
                        import zipfile
                        with zipfile.ZipFile(path) as z:
                            return sorted(z.namelist())
                    except Exception as exc:
                        return "error " + str(exc)
                # And the archive that command wrote holds one file, not the
                # invisible one as well.
                check("stale-selection-not-compressed",
                      _zip_names(os.path.join(scratch, "code.zip")), ["code.py"])

                # The two boxes on the General tab, and the folder's own
                # .hidden file as the proof they did something.
                check("props-attributes",
                      ev("() => (async () => {" + _arc_helpers +
                         " const open = async n => { const c = pick(n);"
                         "  if (!c) return 'missing ' + n; c.click(); await w(120);"
                         "  document.querySelector"
                         "('.toolbar [data-act=\"ctx-props\"]').click();"
                         "  await w(1400); return true; };"
                         " await window.__live.render(" + json.dumps(scratch) +
                         "); await w(500);"
                         " const a = await open('code.py');"
                         " if (a !== true) return a;"
                         " const ro = document.getElementById('prop-readonly');"
                         " const hid = document.getElementById('prop-hidden');"
                         " const started = [ro.checked, hid.checked];"
                         " ro.checked = true;"
                         " ro.dispatchEvent(new Event('change', {bubbles: true}));"
                         " await w(900);"
                         " hid.checked = true;"
                         " hid.dispatchEvent(new Event('change', {bubbles: true}));"
                         " await w(900);"
                         " document.getElementById('props').hidden = true;"
                         " return [started, ro.checked, hid.checked]; })()"),
                      [[False, False], True, True])

                def _hidden_list():
                    try:
                        with open(os.path.join(scratch, ".hidden")) as fh:
                            return fh.read()
                    except OSError:
                        return ""
                check("props-attributes-on-disk",
                      [_hidden_list().strip(),
                       oct(os.stat(os.path.join(scratch, "code.py")).st_mode)[-3:]],
                      ["code.py", "444"])

                # Inside the Rust-only region: the Python backend has no tag
                # writer, and the page offers the flyout on the reference's
                # word rather than the backend's.
                check("ffmpeg-is-here-for-the-cover-gates", bool(_ffmpeg), True)
                # Change album cover: the flyout, the picker with the
                # reference's four file types, the picked picture as the
                # icon before anything is written, and the write on Apply.
                check("album-cover-changed-through-the-flyout",
                      ev("() => (async () => {" + _arc_helpers + _open_props +
                         " const before = (await coverOf('silence.mp3')).cover;"
                         " const a = await openProps('silence.mp3'); if (a !== true) return a;"
                         " document.getElementById('props-cover-btn').click(); await w(150);"
                         " const menuShown = !document.getElementById('m-cover').hidden;"
                         " document.querySelector('#m-cover .mi[data-cover=\"change\"]').click();"
                         " await w(900);"
                         " const pk = document.getElementById('dlg-picker');"
                         " const pickerShown = !pk.hidden;"
                         " const types = Array.from(document.querySelectorAll('#pk-filter option'))"
                         "  .map(o => o.textContent);"
                         " const filterShown = !document.getElementById('pk-filter-card').hidden;"
                         " const names = Array.from(document.querySelectorAll('#pk-list .cdlg-item'))"
                         "  .map(b => b.textContent.trim());"
                         " const row = Array.from(document.querySelectorAll('#pk-list .cdlg-item'))"
                         "  .find(b => b.textContent.trim() === 'art.png');"
                         " if (!row) return ['no art.png in the picker', names];"
                         " row.click(); await w(100);"
                         " pk.querySelector('[data-dlg=\"primary\"]').click(); await w(800);"
                         " const preview = !!document.querySelector('#props-icon-art .thumbimg');"
                         " const untouched = (await coverOf('silence.mp3')).cover;"
                         " document.getElementById('props-apply').click(); await w(1800);"
                         " const after = await coverOf('silence.mp3');"
                         " const stayed = !document.getElementById('props').hidden;"
                         " await closeProps();"
                         " return [before, menuShown, pickerShown, filterShown, types,"
                         "  names.indexOf('bulk.txt') < 0, names.indexOf('art.png') >= 0,"
                         "  preview, untouched, after.cover, after.mime, stayed]; })()"),
                      [False, True, True, True,
                       ["Image Files (*.bmp;*.jpg;*.jpeg;*.png)", "Bitmap Files (*.bmp)",
                        "JPEG (*.jpg;*.jpeg)", "PNG (*.png)"],
                       True, True, True, False, True, "image/png", True])

                def _holds_art():
                    try:
                        return open(_art, "rb").read()[8:] in open(_song, "rb").read()
                    except OSError:
                        return "unreadable"
                check("album-cover-changed-on-disk", _holds_art(), True)
                # And the row in the list shows the cover, the way the
                # reference shows a track's art as its thumbnail.
                check("a-sound-file-row-shows-its-cover",
                      ev("() => (async () => {" + _arc_helpers +
                         " await window.__live.render(" + json.dumps(scratch) +
                         "); await w(1500);"
                         " const c = pick('silence.mp3'); if (!c) return 'missing';"
                         " const img = c.querySelector('.thumbimg');"
                         " return [!!img, img ? img.src.slice(0, 14) : '']; })()"),
                      [True, "data:image/png"])
                # Cancel forgets the choice; Remove and OK strip the cover.
                check("album-cover-cancel-forgets-and-remove-strips",
                      ev("() => (async () => {" + _arc_helpers + _open_props +
                         " let a = await openProps('silence.mp3'); if (a !== true) return a;"
                         " const shown = !!document.querySelector('#props-icon-art .thumbimg');"
                         " document.getElementById('props-cover-btn').click(); await w(150);"
                         " document.querySelector('#m-cover .mi[data-cover=\"remove\"]').click();"
                         " await w(300);"
                         " const plain = !document.querySelector('#props-icon-art .thumbimg');"
                         " document.getElementById('props-cancel').click(); await w(900);"
                         " const kept = (await coverOf('silence.mp3')).cover;"
                         " a = await openProps('silence.mp3'); if (a !== true) return a;"
                         " document.getElementById('props-cover-btn').click(); await w(150);"
                         " document.querySelector('#m-cover .mi[data-cover=\"remove\"]').click();"
                         " await w(300);"
                         " document.getElementById('props-ok').click(); await w(1800);"
                         " const now = (await coverOf('silence.mp3')).cover;"
                         " return [shown, plain, kept, now]; })()"),
                      [True, True, True, False])
                check("album-cover-removed-on-disk", _holds_art(), False)

                if have_git:
                    # Create branch, through the reference's AddBranchDialog
                    # from the branch flyout: a name, what it is based on,
                    # and Switch to new branch on by default. The backend has
                    # had /api/git/branch the whole time and nothing opened
                    # it. The flyout's row is offered on the backend's word,
                    # which enterLive now asks for up front: until it did,
                    # every git command sat greyed until Properties or
                    # Compress happened to ask first.
                    check("create-branch-through-the-dialog",
                          ev("() => (async () => {" + _arc_helpers +
                             " await window.__live.render(" + json.dumps(repo) +
                             "); await w(1200);"
                             " const was = document.getElementById('git-branch').textContent;"
                             " document.getElementById('git-branch-btn').click();"
                             " await w(200);"
                             " const menu = document.getElementById('m-git');"
                             " const rows = Array.from(menu.querySelectorAll('.mi'))"
                             "  .map(m => m.textContent.trim());"
                             " const add = menu.querySelector('[data-git=\"new-branch\"]');"
                             " if (!add) return ['no Create branch row', rows];"
                             " add.click(); await w(300);"
                             " const d = document.getElementById('dlg-addbranch');"
                             " const go = d.querySelector('[data-dlg=\"primary\"]');"
                             " const seen = [!d.hidden, rows[0],"
                             "  document.getElementById('ab-from').value,"
                             "  document.getElementById('ab-switch').checked,"
                             "  go.disabled];"
                             " const box = document.getElementById('ab-name');"
                             " box.value = 'topic';"
                             " box.dispatchEvent(new Event('input', {bubbles: true}));"
                             " seen.push(!go.disabled);"
                             " go.click(); await w(2500);"
                             " seen.push(was, document.getElementById('git-branch').textContent);"
                             " return seen; })()"),
                          [True, "Create branch", "main", True, True, True,
                           "main", "topic"])
                    check("create-branch-on-disk",
                          sorted(l.strip("* ").strip() for l in
                                 _git("branch", "--list").stdout.splitlines()),
                          ["feature", "main", "topic"])
                    # Clone repo is the reference's one box dialog, and Clone
                    # is greyed until there is an address in it. The backend
                    # refuses an address that is not a remote, so what is
                    # asserted here is the asking, not a network.
                    check("clone-asks-for-the-address",
                          ev("() => (async () => {" + _arc_helpers +
                             " await window.__live.render(" + json.dumps(scratch) +
                             "); await w(500);"
                             " window.__runCommand('GitClone'); await w(300);"
                             " const d = document.getElementById('dlg-clonerepo');"
                             " const go = d.querySelector('[data-dlg=\"primary\"]');"
                             " const seen = [!d.hidden,"
                             "  document.getElementById('dlg-clonerepo-t').textContent,"
                             "  go.disabled];"
                             " const box = document.getElementById('cr-url');"
                             " box.value = 'https://example.invalid/some/repo.git';"
                             " box.dispatchEvent(new Event('input', {bubbles: true}));"
                             " seen.push(!go.disabled);"
                             " d.querySelector('[data-dlg=\"close\"]').click();"
                             " await w(100);"
                             " seen.push(d.hidden);"
                             " return seen; })()"),
                          [True, "Clone repo", True, True, True])

            # The Files SWA enforces Trusted Types, and the one place this
            # page hands a string to an HTML parser is the HTML preview. A
            # plain page never enforces anything, so a copy of the page is
            # loaded under the SWA's own two directives, with its policy
            # list cut to the one name the preview is allowed to take, and
            # the preview has to come out whole. Last, because it leaves the
            # window on another page.
            # A shipped page is given a frame and has to fill it. The
            # prototype is a 1180 by 800 window floating on a desktop, and
            # shipped into a smaller frame that box is centred, so the top
            # of it, the tab strip and the toolbar, is clipped away with
            # nothing to scroll to. Geometry, not the presence of a rule:
            # the window has to measure the viewport and the first tab has
            # to be on screen.
            go(f"http://127.0.0.1:{HTTP_PORT}/ship/files.html")
            check("the-shipped-window-fills-its-frame",
                  ev("() => { const w = document.querySelector('.win');"
                     " if (!w) return 'no window';"
                     " const r = w.getBoundingClientRect();"
                     " const t = document.querySelector('#tabstrip .tab');"
                     " const tr = t ? t.getBoundingClientRect() : null;"
                     " return [Math.round(r.width) === window.innerWidth,"
                     "  Math.round(r.height) === window.innerHeight,"
                     "  Math.round(r.top), Math.round(r.left),"
                     "  getComputedStyle(w).borderRadius,"
                     "  getComputedStyle(document.body).overflow,"
                     "  !!tr && tr.top >= 0 && tr.bottom <= window.innerHeight,"
                     # The frame already carries minimise, maximise and
                     # close. A second set inside it is the page claiming a
                     # title bar it does not own.
                     "  document.querySelectorAll('.caption b').length > 0 &&"
                     "   getComputedStyle(document.querySelector('.caption'))"
                     "    .display === 'none']; }"),
                  [True, True, 0, 0, "0px", "hidden", True, True])

            _tt_meta = ('<meta http-equiv="Content-Security-Policy" '
                        'content="require-trusted-types-for \'script\'; '
                        'trusted-types parse-html-subset">')
            _tt_src = open(os.path.join(ROOT, "v3.html")).read()
            open(os.path.join(ROOT, "v3-tt.html"), "w").write(
                _tt_src.replace('<meta charset="utf-8">',
                                '<meta charset="utf-8">' + _tt_meta, 1))
            go(f"http://127.0.0.1:{HTTP_PORT}/v3-tt.html")
            for _ in range(30):
                if ev("() => !!window.__livePath"):
                    break
                time.sleep(1)
            check("html-preview-under-trusted-types",
                  ev("() => (async () => {"
                     " const w = ms => new Promise(r => setTimeout(r, ms));"
                     " const enforced = (() => { try {"
                     "  new DOMParser().parseFromString('<p>x</p>', 'text/html');"
                     "  return false; } catch (e) { return true; } })();"
                     " await window.__live.render(" + json.dumps(scratch) +
                     "); await w(500);"
                     " const t = Array.from(document"
                     ".querySelectorAll('.infopane-tab'));"
                     " if (t.length > 1) t[1].click(); await w(200);"
                     " const c = Array.from(document"
                     ".querySelectorAll('.grid .cell'))"
                     ".find(x => x.getAttribute('data-n') === 'page.html');"
                     " if (!c) return 'no cell'; c.click(); await w(900);"
                     " const h = document.querySelector("
                     "'#ipreview-text .preview-rich-box');"
                     " if (!h) return [enforced, 'no html box'];"
                     " return [enforced, typeof window.PWNED,"
                     "  h.querySelectorAll('h1,table,td').length,"
                     "  h.querySelectorAll('script,style,iframe').length,"
                     "  h.textContent.indexOf('North') !== -1]; })()"),
                  [True, "undefined", 4, 0, True])

            # The shipped page under the SWA's own Content Security Policy.
            # chrome://file-manager writes no connect-src of its own, so
            # Chromium patch 0089 writes one, and this is that directive
            # verbatim. What it has to allow is the service, which lives on
            # loopback at another port, so `self` does not cover it: only
            # the loopback source does. Both directions, because a page that
            # reaches the service under a policy that permits everything has
            # proved nothing about this policy.
            _swa_connect = ("connect-src http://127.0.0.1:* chrome://resources"
                            " chrome://theme chrome://image blob: data: 'self';")
            _narrow = _swa_connect.replace("http://127.0.0.1:* ", "")
            _ship_html = open(os.path.join(ROOT, "ship", "files.html"),
                              encoding="utf-8").read()
            for _leaf, _rule in (("files-swa.html", _swa_connect),
                                 ("files-swa-narrow.html", _narrow)):
                open(os.path.join(ROOT, "ship", _leaf), "w").write(
                    _ship_html.replace(
                        '<meta charset="utf-8">',
                        '<meta charset="utf-8"><meta http-equiv='
                        '"Content-Security-Policy" content="' + _rule + '">',
                        1))
            _reach = ("() => fetch(window.__api + '/api/health')"
                      ".then(r => r.status).catch(e => 'ERR')")
            go(f"http://127.0.0.1:{HTTP_PORT}/ship/files-swa.html")
            _allowed = ev(_reach)
            go(f"http://127.0.0.1:{HTTP_PORT}/ship/files-swa-narrow.html")
            _refused = ev(_reach)
            check("the-shipped-page-reaches-the-service-under-the-swa-policy",
                  [_allowed, _refused], [200, "ERR"])

        finally:
            backend.terminate()
            backend.wait()
            shutil.rmtree(scratch, ignore_errors=True)
            # The keyring made for the signature gates. It holds a private key,
            # so it goes whether or not the run got that far.
            shutil.rmtree(_keyring, ignore_errors=True)
        ws.close()
    finally:
        chrome.terminate()
        server.terminate()
        chrome.wait()
        server.wait()
        shutil.rmtree(profile, ignore_errors=True)
        shutil.rmtree(os.path.join(ROOT, "ship"), ignore_errors=True)

    print(f"== {len(failures)} failures ==")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
