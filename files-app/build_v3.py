#!/usr/bin/env python3
"""Generate proto/v3.html: the Files window, rebuilt for AuraDE.

Geometry and icon geometry come from files-community/Files (MIT / MPL-2.0),
read out of the checkout at ref-files. Nothing here is Microsoft artwork.
"""
import hashlib, json, os, re, icons, sidebar, localfs, sources
#: The name matters: `_html` is taken at the bottom of this file by the
#: rendered page, and importing the module under it makes `esc` fail only
#: on the second build.
from html import escape as _escape
import datetime as _dt

ROOT = os.path.dirname(os.path.abspath(__file__))
ICONS = json.load(open(f"{ROOT}/assets/files-icons.json"))

# Commands are extracted from the reference data and checked by the parity gate.
FILES_COMMANDS = json.load(
    open(f"{ROOT}/assets/files-commands.json"))["commands"]
COMMAND_TABLE_JSON = json.dumps(FILES_COMMANDS, separators=(",", ":"),
                                ensure_ascii=False)

# Map reference command names to local actions.
COMMAND_ACTS = {
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

# Commands whose Windows meaning has no counterpart here. Each keeps its row
# in the palette and says why, because a command that is missing and one that
# cannot apply are different facts and the person reading should be able to
# tell them apart.
COMMAND_NOT_HERE = {
    "InstallInfDriver":
        "A .inf is a Windows driver package. Drivers on this system are kernel"
        " modules, which are installed by the package manager rather than from"
        " a file manager.",
    "SetAsLockscreenBackground":
        "This desktop draws the lock screen from the wallpaper, so there is no"
        " separate lock screen image. Set as desktop background covers both.",
}


# When a command can run, in the reference's own words and then in this
# page's. Files states the condition for most of its commands as
# `IsExecutable`, and the context menus lean on it: a row the factory gives no
# visibility of its own is shown exactly while its command is executable, and
# hidden the rest of the time. `tools/extract_commands.py` keeps that
# expression, and this turns the parts of it that mean something here into a
# predicate.
#
# Only the parts. The conditions are C# against Files' own view models, so
# most of what they say cannot be asked here. What is not recognised is
# treated as unknown rather than as true, and the predicate that comes out
# asks whether the condition could hold rather than whether it does: a row is
# shown unless the reference's own words rule it out. That is the safe
# direction. Reading an unknown term as true is not safe, because the term may
# sit under a `!`: `!context.HasSelection` read that way says Format needs a
# selection, when it needs there not to be one, and the row disappears from
# the only menu it belongs to.
COMMAND_WHEN = [
    (r"[A-Za-z_]\w*\.PageType\s+is\s+not\s+ContentPageTypes\.RecycleBin",
     "!inTrash()"),
    (r"[A-Za-z_]\w*\.PageType\s*!=\s*ContentPageTypes\.RecycleBin", "!inTrash()"),
    (r"[A-Za-z_]\w*\.PageType\s+is\s+ContentPageTypes\.RecycleBin", "inTrash()"),
    (r"[A-Za-z_]\w*\.PageType\s*==\s*ContentPageTypes\.RecycleBin", "inTrash()"),
    (r"[A-Za-z_]\w*\.PageType\s+is\s+not\s+ContentPageTypes\.Home", "!atHome()"),
    (r"[A-Za-z_]\w*\.PageType\s*!=\s*ContentPageTypes\.Home", "!atHome()"),
    (r"[A-Za-z_]\w*\.SelectedItems\.Count\s*(?:is|==)\s*1\b", "picked() === 1"),
    (r"[A-Za-z_]\w*\.SelectedItems\.Count\s*>\s*1\b", "picked() > 1"),
    (r"[A-Za-z_]\w*\.SelectedItem\s+is\s+not\s+null", "picked() === 1"),
    (r"[A-Za-z_]\w*\.HasSelection\b", "picked() > 0"),
    (r"[A-Za-z_]\w*\.IsMultiPaneA(?:vailable|ctive)\b", "dual()"),
    (r"[A-Za-z_]\w*\.CanExecuteGitAction\b", "inRepo()"),
    (r"[A-Za-z_]\w*\.CanCreateItem\b", "!atHome()"),
    (r"[A-Za-z_]\w*\.HasItem\b", "!atHome()"),
]

#: `!=` is not a negation and `=>` opens a lambda. Both appear inside these
#: conditions, and both would be read as an operator they are not.
COMMAND_WHEN_NOT_OPERATORS = [("!=", "\u2260"), ("=>", "\u21d2")]

COMMAND_WHEN_TOKENS = re.compile(r"\s*(&&|\|\||[!()]|[^\s&|!()]+)")

#: A term this page cannot ask about. It is neither true nor false, and the
#: two halves of the pair below are what survives of it: it could be true, and
#: it is not known to be.
MAYBE = ("true", "false")


def _and(left, right):
    if "false" in (left, right):
        return "false"
    parts = [p for p in (left, right) if p != "true"]
    #: `&&` binds tighter than `||`, so a piece that holds an `||` has to keep
    #: its own brackets. Without them `a && (b && c) || !b` is read as
    #: `(a && b && c) || !b`, which is a different condition and one that says
    #: Properties is available on Home.
    parts = [f"({p})" if "||" in p else p for p in parts]
    return " && ".join(parts) if parts else "true"


def _or(left, right):
    if "true" in (left, right):
        return "true"
    parts = [p for p in (left, right) if p != "false"]
    return " || ".join(f"({p})" for p in parts) if parts else "false"


def _not(pair):
    """Kleene's negation: what could be true is what is not known to be."""
    could, known = pair
    flip = {"true": "false", "false": "true"}
    return (flip.get(known, f"!({known})"), flip.get(could, f"!({could})"))


def command_when(expr):
    """The reference's condition as a predicate this page can run.

    Two answers are carried through the walk, not one: whether the condition
    could hold, and whether it is known to hold. A term with no meaning here
    is (could, not known), and negating it gives back the same pair, which is
    the whole point. What comes out is the first of the two.
    """
    if not expr:
        return ""
    text = expr
    known = []
    for pattern, means in COMMAND_WHEN:
        def stand_in(_found, means=means):
            known.append(means)
            return f" \u00ab{len(known) - 1}\u00bb "
        text = re.sub(pattern, stand_in, text)
    if not known:
        return ""
    for old, new in COMMAND_WHEN_NOT_OPERATORS:
        text = text.replace(old, new)
    words = COMMAND_WHEN_TOKENS.findall(text)
    at = 0

    def factor():
        nonlocal at
        if at < len(words) and words[at] == "!":
            at += 1
            return _not(factor())
        if at < len(words) and words[at] == "(":
            at += 1
            value = disjunction()
            if at < len(words) and words[at] == ")":
                at += 1
            return value
        def call():
            #: A call carries its arguments: `Drives.FirstOrDefault(x => ...)`
            #: is one term this page cannot ask about, not a term beside a
            #: condition of its own.
            nonlocal at
            while at < len(words) and words[at] == "(":
                depth = 0
                while at < len(words):
                    depth += (1 if words[at] == "(" else
                              (-1 if words[at] == ")" else 0))
                    at += 1
                    if depth == 0:
                        break

        word = words[at] if at < len(words) else ""
        at += 1
        call()
        found = re.fullmatch(r"\u00ab(\d+)\u00bb", word)
        if found:
            return (known[int(found.group(1))],) * 2
        #: Words with no operator between them are one term. `context.ShellPage
        #: is not null` is four words and one question, and reading it as one
        #: word ends the walk there and throws away every condition after the
        #: `&&` that follows: Rename, Rotate and Open file location all lost
        #: theirs that way, silently, and became commands that are always on.
        while at < len(words) and words[at] not in ("&&", "||", ")") \
                and not re.fullmatch(r"\u00ab\d+\u00bb", words[at]):
            at += 1
            call()
        return MAYBE

    def conjunction():
        nonlocal at
        value = factor()
        while at < len(words) and words[at] == "&&":
            at += 1
            right = factor()
            value = (_and(value[0], right[0]), _and(value[1], right[1]))
        return value

    def disjunction():
        nonlocal at
        value = conjunction()
        while at < len(words) and words[at] == "||":
            at += 1
            right = conjunction()
            value = (_or(value[0], right[0]), _or(value[1], right[1]))
        return value

    try:
        could = disjunction()[0]
    except (IndexError, RecursionError):
        return ""
    return "" if could == "true" else could


# What a toggle is on for, in the reference's vocabulary and then in this
# page's. Files says which value each toggle sets in a property of its own
# (`protected override SortOption SortOption => SortOption.Name;`), and its
# `IsOn` compares the current setting against it. The two vocabularies differ,
# so the pairing is written down; the list of which commands are toggles, and
# of what, is not.
COMMAND_ON = {
    "SortOption": ("window.__sortState.fieldName", {
        "Name": "Name",
        "DateModified": "Date modified",
        "DateCreated": "Date created",
        "Size": "Size",
        "FileType": "Type",
        "SyncStatus": "Sync status",
        "FileTag": "Tag",
        "Path": "Path",
        "OriginalFolder": "Original folder",
        "DateDeleted": "Date deleted",
    }),
    "GroupOption": ("window.__groupBy()", {
        "None": "None",
        "Name": "Name",
        "DateModified": "Date modified",
        "DateCreated": "Date created",
        "DateDeleted": "Date deleted",
        "Size": "Size",
        "FileType": "Type",
        "SyncStatus": "Sync status",
        "FileTag": "Tag",
        "OriginalFolder": "Original folder",
        "FolderPath": "Folder path",
    }),
    "GroupByDateUnit": ("window.__groupUnit()", {
        "Year": "year", "Month": "month", "Day": "day",
    }),
    "LayoutTypes": ("window.__mode()", {
        "Details": "details", "List": "list", "Cards": "cards",
        "Grid": "grid", "Columns": "columns", "Adaptive": "adaptive",
    }),
    "SortDirection": ("window.__sortState.dir", {
        "Ascending": 1, "Descending": -1,
    }),
    "GroupDirection": ("window.__groupDir()", {
        "Ascending": 1, "Descending": -1,
    }),
}


def command_on(toggles):
    """The test for whether a toggle is currently on, or nothing."""
    parts = []
    for kind, value in sorted((toggles or {}).items()):
        reads, names = COMMAND_ON.get(kind, (None, {}))
        if not reads or value not in names:
            #: A setting this page does not keep. Saying nothing is better
            #: than a check mark that never moves.
            return ""
        parts.append(f"{reads} === {json.dumps(names[value])}")
    return " && ".join(parts)


def command_runs():
    """The commands that set more than one thing, and what each of them sets.

    Grouping by a date is a field and a unit together, and the two directions
    are one setting with two values, so there is no single page action to
    point a `cmdAct` at. Which commands these are is not written down: it
    falls out of what each one says it toggles.
    """
    out = {}
    fields = COMMAND_ON["GroupOption"][1]
    units = COMMAND_ON["GroupByDateUnit"][1]
    ways = COMMAND_ON["GroupDirection"][1]
    for code, spec in FILES_COMMANDS.items():
        if code in COMMAND_ACTS:
            continue
        marks = spec.get("toggles") or {}
        field = fields.get(marks.get("GroupOption", ""))
        unit = units.get(marks.get("GroupByDateUnit", ""))
        way = ways.get(marks.get("GroupDirection", ""))
        if field and unit:
            out[code] = f"setGrouping({json.dumps(field)}, {json.dumps(unit)})"
        elif field:
            out[code] = f"setGrouping({json.dumps(field)}, null)"
        elif unit:
            out[code] = f"setGrouping(null, {json.dumps(unit)})"
        elif way is not None:
            out[code] = f"setGroupWay({way})"
    return out


def command_registrations():
    """The `cmdAct` and `cmd` calls, generated from the tables above."""
    lines = []
    for code in sorted(COMMAND_ACTS):
        known = FILES_COMMANDS.get(code) or {}
        parts = []
        when = command_when(known.get("executable"))
        if when:
            parts.append(f"enabled: () => {when}")
        on = command_on(known.get("toggles"))
        if on:
            parts.append(f"on: () => {on}")
        spec = f", {{{', '.join(parts)}}}" if parts else ""
        lines.append(f"  cmdAct({json.dumps(code)}, "
                     f"{json.dumps(COMMAND_ACTS[code])}{spec});")
    for code, does in sorted(command_runs().items()):
        on = command_on((FILES_COMMANDS.get(code) or {}).get("toggles"))
        said = f", on: () => {on}" if on else ""
        lines.append(f"  cmd({json.dumps(code)}, "
                     f"{{run: () => {does}{said}}});")
    for code in sorted(COMMAND_NOT_HERE):
        lines.append(f"  cmd({json.dumps(code)}, "
                     f"{{unavailable: {json.dumps(COMMAND_NOT_HERE[code])}}});")
    return "\n".join(lines)


COMMAND_REGISTRATIONS = command_registrations()

LAYER = {"Base": "var(--ico-base)", "Alt": "var(--ico-alt)",
         "Accent": "var(--ico-accent)", "AccentContrast": "var(--ico-contrast)"}


def ico(name, px=16, cls="", accent=False):
    e = ICONS[name]
    size = e.get("IconSize", "16")
    layers = e.get("layers") or [{"type": "Base", "d": e.get("FilledIconData", "")}]
    def fill(t):
        if not accent:
            return LAYER.get(t, LAYER["Base"])
        return "var(--ico-contrast)" if t == "AccentContrast" else "var(--ico-accent)"
    paths = "".join(f'<path fill="{fill(l["type"])}" d="{l["d"]}"/>'
                    for l in layers if l.get("d"))
    c = f' class="{cls}"' if cls else ""
    return (f'<svg{c} width="{px}" height="{px}" viewBox="0 0 {size} {size}" '
            f'fill-rule="nonzero" aria-hidden="true">{paths}</svg>')


#: Files writes its visible strings in ICU message format, so a description
#: arrives as "Copy selected {0, plural, one {item} other {items}}". The
#: palette has no count to fill in, so the plural form is the one to show:
#: "Copy selected items" reads as a command, "Copy selected {0, plural..." does
#: not. `{0}` stands in for a program's name, and no program has been chosen.
def esc(text):
    """A string from the reference, safe in markup and in an attribute."""
    return _escape(str(text or ""), quote=True)


ICU_PLURAL = re.compile(r"\{\d+,\s*plural,.*?other\s*\{([^}]*)\}\s*\}")


def plain(text, standin="an editor"):
    """One of Files' strings as a person reads it."""
    if not text:
        return ""
    return ICU_PLURAL.sub(r"\1", text).replace("{0}", standin).strip()


CAP_MIN = '<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><rect y="4.5" width="10" height="1" fill="currentColor"/></svg>'
CAP_MAX = '<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><rect x="0.5" y="0.5" width="9" height="9" fill="none" stroke="currentColor" stroke-width="1"/></svg>'
CAP_CLS = '<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1"><path d="M0.5 0.5l9 9M9.5 0.5l-9 9"/></svg>'
TAB_CLS = '<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1"><path d="M1 1l8 8M9 1L1 9"/></svg>'
CHEVRON_DOWN = ('<svg class="caret" width="8" height="8" viewBox="0 0 8 8" fill="none" '
                'stroke="currentColor" stroke-width="1.2" stroke-linecap="round" '
                'stroke-linejoin="round" aria-hidden="true"><path d="M1.5 2.75L4 5.25L6.5 2.75"/></svg>')
CHEVRON_RIGHT = ('<svg class="csep" width="8" height="8" viewBox="0 0 8 8" fill="none" '
                 'stroke="currentColor" stroke-width="1.2" stroke-linecap="round" '
                 'stroke-linejoin="round" aria-hidden="true"><path d="M2.75 1.5L5.25 4L2.75 6.5"/></svg>')


# --- artwork, from icons.py -----------------------------------------------
# The set is pluggable. icons.py owns the drawn glyphs, the extension table and
# the readers for any icon theme installed on the machine; this file only picks
# one to render with and hands the rest to the page so the user can switch
# without a rebuild. Nothing here is Microsoft artwork.
ICON_SET = os.environ.get("AURADE_ICON_SET", icons.DEFAULT_SET)
ART, ART_SM = icons.load(ICON_SET)
ICON_SETS = icons.all_sets()
ICON_SET_JSON = json.dumps({name: {"title": title, "note": note}
                            for name, title, note in icons.available()})
#: The same extension table the server side renders from, handed to the live
#: renderer so both ends name a file the same thing.
ART_FOR_EXT_JSON = json.dumps({k: list(v) for k, v in icons.ART_BY_EXT.items()})
#: (key, label) per category, for the Icons settings page's contact sheet.
ICON_KEYS_JSON = json.dumps([[k, v[0]] for k, v in icons.CATEGORIES.items()])
#: About page facts. Baked at build time so the page never states a version
#: it cannot support. The system line is read live from the backend instead,
#: because the build host is not the target.
BUILD_DATE = __import__("datetime").date.today().isoformat()
BUILD_ID = hashlib.sha256(b"".join(open(f, "rb").read() for f in sources.files())).hexdigest()[:12]
FILES_VER = "0.2"
AURADE_VER = "152.1660893"


_ART_N = [0]


def art_svg(key, small=False):
    """One glyph, with its internal ids made unique to this copy.

    Every inline copy of a glyph carries its own defs, so they have to carry
    their own ids too. See icons.uniquify for what goes wrong when they do not.
    """
    _ART_N[0] += 1
    return icons.uniquify((ART_SM if small else ART)[key], _ART_N[0])




#: The empty shelf. Drawn here rather than taken from the reference, which
#: ships its own EmptyShelf art: a board with room on it, and two things
#: already set down, so the picture says what the pane is for before the text
#: does. One colour, inherited, so it reads in both themes.
SHELF_ART = (
    '<svg class="shelf-art" viewBox="0 0 64 44" aria-hidden="true" '
    'fill="none" stroke="currentColor" stroke-width="1.5" '
    'stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M6 30h52" />'
    '<path d="M12 30v8M52 30v8" />'
    '<rect x="15" y="14" width="15" height="16" rx="2" />'
    '<rect x="34" y="20" width="15" height="10" rx="2" />'
    '<path d="M20 8v-3M27 10l2-3M14 11l-2-3" opacity=".55" />'
    '</svg>')

#: The Customization tab's contact sheet. The reference lists the icons found
#: inside a picked DLL; there is no such file here, so it lists the glyphs the
#: app draws, which is the same offer made out of what this platform has.
ICON_LABELS = {k: v[0] for k, v in icons.CATEGORIES.items()}
CUST_GRID = "\n".join(
    '              <button class="cust-ico" data-icon="%s" title="%s" '
    'aria-label="%s">%s</button>' % (key, label, label, art_svg(key, True))
    for key, label in ICON_LABELS.items())


# --------------------------------------------------- port shapes to a view ----
# Everything below turns EntryDto plus Metadata into the tuples the templates
# already consume. It is the only place that knows both vocabularies, which is
# the point: swapping localfs for the real FilesBackendPort should not reach
# past this function.

_ART_BY_EXT = icons.ART_BY_EXT


def _human_size(n):
    if n is None:
        return ""
    if n < 1024:
        return f"{n} B"
    for unit in ("KB", "MB", "GB", "TB"):
        n /= 1024.0
        if n < 1024:
            return f"{n:.1f} {unit}"
    return f"{n:.1f} PB"


#: What every date reads as in ship mode.
#:
#: The shipped page opens on a folder made for the build, so each date in it
#: is a placeholder that the live layer replaces on first paint. Left alone
#: it would be the minute the package was built, read in the build machine's
#: own time zone, and two builds of the same sources would not match. A
#: packager that set SOURCE_DATE_EPOCH has already said what the release's
#: date is; without one this is a date, in UTC, and not a clock.
SHIP_EPOCH = int(os.environ.get("SOURCE_DATE_EPOCH") or 946684800)


def _when(ms):
    if not ms:
        return ""
    if SHIP:
        return _dt.datetime.fromtimestamp(
            SHIP_EPOCH, _dt.timezone.utc).strftime("%-d %b %Y %H:%M")
    d = _dt.datetime.fromtimestamp(ms / 1000.0)
    return d.strftime("%-d %b %Y %H:%M")


_HASH_BUDGET = 20
_HASH_MAX_BYTES = 1024 * 1024
_PREVIEW_BUDGET = 40
_PREVIEW_MAX_BYTES = 4096
_PREVIEW_MAX_CHARS = 1500
_PREVIEW_CACHE = {}
_TEXT_EXTS = frozenset({
    ".txt", ".log", ".md", ".markdown", ".py", ".js", ".ts",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".conf",
    ".cfg", ".sh", ".css", ".html", ".xml", ".xaml",
    ".csv", ".svg",
})


#: Baked thumbnails. A static page carries its own pixels, so both ends are
#: capped: the file we will open, the box we scale into, and how many go into
#: one page. 192 covers the 96px grid box at 2x and reads well enough in the
#: info pane, and JPEG at 78 keeps one under about 10KB.
_THUMB_BUDGET = 24
_THUMB_MAX_BYTES = 24 * 1024 * 1024
_THUMB_BOX = 192
_THUMB_QUALITY = 78
_THUMB_CACHE = {}
_THUMB_EXTS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif",
    ".ico", ".avif",
})
#: Baked pages and frames go through the backend's converters, which a static
#: build has no way to call, so the export offers pictures only. Live mode
#: fills these in on demand instead.


def _thumb_for(pkey, nb, name):
    """One image as a data URI, or "" for everything else.

    Returns "" rather than raising for a corrupt or undecodable file, because
    a missing thumbnail is a normal outcome and the caller falls back to the
    drawn glyph. Budgeted, because a Pictures directory would otherwise put a
    hundred images into one page.
    """
    global _THUMB_BUDGET
    try:
        ext = os.path.splitext(name)[1].lower()
    except Exception:
        return ""
    if ext not in _THUMB_EXTS:
        return ""
    if not isinstance(nb, int) or nb <= 0 or nb > _THUMB_MAX_BYTES:
        return ""
    try:
        path = localfs.key_path(pkey) if pkey else ""
    except Exception:
        return ""
    if not path:
        return ""
    if path in _THUMB_CACHE:
        return _THUMB_CACHE[path]
    if _THUMB_BUDGET <= 0:
        return ""
    try:
        from PIL import Image
    except ImportError:
        _THUMB_BUDGET = 0
        return ""
    try:
        import base64 as _b64
        import io as _io
        with Image.open(path) as im:
            im.draft("RGB", (_THUMB_BOX, _THUMB_BOX))
            im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
            im.thumbnail((_THUMB_BOX, _THUMB_BOX), Image.LANCZOS)
            buf = _io.BytesIO()
            if im.mode == "RGB":
                im.save(buf, "JPEG", quality=_THUMB_QUALITY, optimize=True)
                mime = "image/jpeg"
            else:
                im.save(buf, "PNG", optimize=True)
                mime = "image/png"
    except Exception:
        _THUMB_CACHE[path] = ""
        return ""
    _THUMB_BUDGET -= 1
    uri = ("data:" + mime + ";base64,"
           + _b64.b64encode(buf.getvalue()).decode("ascii"))
    _THUMB_CACHE[path] = uri
    return uri


def _stat_extra(path):
    try:
        st = os.stat(path)
        return (_when(int(st.st_ctime * 1000)), _when(int(st.st_atime * 1000)),
                st.st_blocks * 512)
    except OSError:
        return ("", "", -1)


def _hashes_for(path, nb):
    global _HASH_BUDGET
    if _HASH_BUDGET <= 0 or not isinstance(nb, int):
        return ("", "", "")
    if nb <= 0 or nb > _HASH_MAX_BYTES:
        return ("", "", "")
    try:
        import hashlib as _hl
        md5, sha1, sha256 = _hl.md5(), _hl.sha1(), _hl.sha256()
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(65536)
                if not chunk:
                    break
                md5.update(chunk)
                sha1.update(chunk)
                sha256.update(chunk)
        _HASH_BUDGET -= 1
        return (md5.hexdigest(), sha1.hexdigest(), sha256.hexdigest())
    except OSError:
        return ("", "", "")


def _preview_for(pkey, nb, name):
    global _PREVIEW_BUDGET
    if _PREVIEW_BUDGET <= 0:
        return ""
    try:
        ext = os.path.splitext(name)[1].lower()
    except Exception:
        return ""
    if ext not in _TEXT_EXTS:
        return ""
    if not isinstance(nb, int) or nb <= 0 or nb > 10 * 1024 * 1024:
        return ""
    try:
        path = localfs.key_path(pkey) if pkey else ""
    except Exception:
        return ""
    if not path or path in _PREVIEW_CACHE:
        return _PREVIEW_CACHE.get(path, "")
    try:
        with open(path, "rb") as fh:
            head = fh.read(_PREVIEW_MAX_BYTES)
    except OSError:
        _PREVIEW_CACHE[path] = ""
        return ""
    if b"\x00" in head:
        _PREVIEW_CACHE[path] = ""
        return ""
    try:
        text = head.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        try:
            text = head.decode("utf-8", errors="replace")
            if text.count("\ufffd") > len(text) // 10:
                _PREVIEW_CACHE[path] = ""
                return ""
        except Exception:
            _PREVIEW_CACHE[path] = ""
            return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for _dash in ("\u2014", "\u2013", "\u2012"):
        text = text.replace(_dash, "-")
    if len(text) > _PREVIEW_MAX_CHARS:
        text = text[:_PREVIEW_MAX_CHARS]
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(
        ">", "&gt;").replace('"', "&quot;").replace("\n", "&#10;")
    _PREVIEW_BUDGET -= 1
    _PREVIEW_CACHE[path] = text
    return text


def rows_from_port(page, meta):
    out = []
    for e in page["entries"]:
        m = meta.get(e["key"], {})
        ms = m.get("modificationTime") or 0
        nb = m.get("size")
        real = localfs.key_path(e["key"])
        created, accessed, ob = _stat_extra(real)
        if e["isDirectory"]:
            out.append((e["name"], "folder", "Folder",
                        _when(ms), "", e["key"], e["key"], ms, -1,
                        created, accessed, ob, "", "", ""))
            continue
        ext = os.path.splitext(e["name"])[1].lower()
        art, kind = _ART_BY_EXT.get(ext, ("txt", "File"))
        # A file carries no nav key here because nothing can navigate to one
        # yet, but it keeps its file key so Copy path still names a real path.
        md5, sha1, sha256 = _hashes_for(real, nb)
        out.append((e["name"], art, kind, _when(ms),
                    _human_size(nb), None, e["key"], ms,
                    nb if isinstance(nb, int) else -1,
                    created, accessed, ob, md5, sha1, sha256))
    return out


# The directory the export opens on. Override with AURADE_PROTO_DIR, which is
# the whole reason for reading real data: a curated list hides long names,
# empty folders and thousand file directories.
# Home, because that is the folder Files opens on and the one with something
# worth clicking in it.
# Ship mode: AURADE_SHIP=<dir> writes the page for chrome://file-manager
# into that directory rather than the screenshot loop's v3.html. Nothing
# about this machine goes in. Home is an empty folder made for the build, so
# there are no volumes, no network mounts, no catalogue and no rows; the live
# layer fills all of it from the daemon at run time, and the window starts on
# `~`, which the daemon resolves to whoever is running it. The script cannot
# be inline there, since the SWA's script-src is 'self', so the page is
# written as files.html with a <script src="files.js"> and files.js beside it.
SHIP = os.environ.get("AURADE_SHIP", "")
if SHIP:
    import tempfile as _tempfile
    HOME_DIR = _tempfile.mkdtemp(prefix="aurade-ship-home-")
else:
    HOME_DIR = os.path.expanduser("~")
TARGET_START = HOME_DIR if SHIP else os.environ.get("AURADE_PROTO_DIR", HOME_DIR)

TARGET = TARGET_START
LIST_ERROR = None
ITEMS = []
EMPTY_STATE = ""
CRUMBS = []
SELECTED_INDEX = None
SELECTED_NAME = None
_TARGET_ROOT = None
IS_HOME = False
CATALOG_JSON = "{}"


def set_target(path):
    """Point every global the page template reads at one directory.

    The template is a single f-string that reads module state, so navigation is
    this function plus a loop, not a rewrite of the view.
    """
    global TARGET, LIST_ERROR, ITEMS, EMPTY_STATE, CRUMBS
    global SELECTED_NAME, _TARGET_ROOT, HOME_WIDGETS, _HASH_BUDGET, IS_HOME
    global _PREVIEW_BUDGET, _PREVIEW_CACHE
    TARGET = path
    LIST_ERROR = None
    HOME_WIDGETS = ""
    _HASH_BUDGET = 20
    _PREVIEW_BUDGET = 40
    _PREVIEW_CACHE = {}
    IS_HOME = (os.path.abspath(path) == HOME_DIR)
    try:
        page = localfs.list_dir(path)
        meta = localfs.metadata([e["key"] for e in page["entries"]])
        ITEMS = rows_from_port(page, meta)
        if IS_HOME:
            HOME_WIDGETS = home_page_html()
    except OSError as err:
        # Distinguishing "could not read" from "nothing here" is the whole point.
        LIST_ERROR = ("Location unavailable",
                      f"{err.strerror or type(err).__name__}.")
        ITEMS = []
    # Nothing is selected, because nothing has clicked anything. A status bar
    # that says "1 item selected" over an unselected list is the kind of small
    # lie that makes a mockup read as fake.
    SELECTED_NAME = (ITEMS[SELECTED_INDEX][0]
                     if SELECTED_INDEX is not None and ITEMS else None)
    _TARGET_ROOT = _place_for(localfs.as_file_key(path), VOLUMES)
    CRUMBS = _crumbs_for(path)
    if LIST_ERROR:
        EMPTY_STATE = ('<div class="statemsg"><div class="stateglyph">'
                       + ico("Status.Warning", 32) + '</div>'
                       + f'<div class="statetitle">{LIST_ERROR[0]}</div>'
                       + f'<div class="statebody">{LIST_ERROR[1]}</div></div>')
    elif not ITEMS:
        EMPTY_STATE = ('<div class="statemsg"><div class="statebody">'
                       'This folder is empty.</div></div>')
    else:
        EMPTY_STATE = ""


# ---------------------------------------------------------------- sidebar ----
#: Shipped, the only volume is Home itself, so the trail reads Home and
#: the sidebar has its one row; the live layer replaces the sidebar with
#: what the daemon lists as soon as it answers.
VOLUMES = ([{"id": "local_root:home", "root": localfs.as_file_key(HOME_DIR),
             "label": "Home", "kind": "system", "removable": False,
             "readOnly": False, "capacity": {"total": 0, "free": 0},
             "purpose": "home", "totalBytes": 0, "usedBytes": 0, "freeBytes": 0}]
           if SHIP else localfs.volumes(HOME_DIR))
#: The network locations this machine has mounted. Files gives them a
#: widget of their own between Drives and File tags, and a context menu
#: of their own; read here rather than filtered out of VOLUMES, because
#: a network mount is deliberately not a drive.
NETWORK = [] if SHIP else localfs.network_mounts()
# The place the file area is showing, so the sidebar highlights it only when the
# two actually agree. Highlighting Home while displaying something else is the
# same class of lie as the status bar claiming a selection that is not there.
def _place_for(target_key, volumes):
    best = None
    for v in volumes:
        root = v["root"]
        if target_key == root or target_key.startswith(root.rstrip("/") + "/"):
            if best is None or len(root) > len(best):
                best = root
    return best


def _drive_children(volume):
    """The top-level folders of a drive, so its chevron expands onto something
    real. Only directories that exist and can be read, capped, because a
    sidebar is not a listing."""
    path = localfs.key_path(volume["root"])
    try:
        names = sorted(
            (e.name for e in os.scandir(path)
             if not e.name.startswith(".") and e.is_dir(follow_symlinks=False)),
            key=str.lower)
    except OSError:
        return []
    return [(name, localfs.as_file_key(os.path.join(path, name)))
            for name in names[:12]]


def sidebar_html():
    return sidebar.render(VOLUMES, _TARGET_ROOT, href_for, _drive_children)


def sb_glyphs_html():
    """The sidebar's glyphs and the widgets' small icons, once each, in a
    template the live layer clones from when it redraws the sidebar and the
    Home widgets from what the daemon lists. A shipped page has no static
    rows to borrow them from."""
    spans = [f'<span data-g="{k}">{sidebar.glyph(k)}</span>'
             for k in sorted(sidebar.GLYPH)]
    spans += [f'<span data-g="chev">{sidebar.CHEVRON}</span>',
              f'<span data-g="trail-pin">{sidebar.PIN}</span>',
              f'<span data-g="trail-eject">{sidebar.EJECT}</span>',
              f'<span data-g="ico-pin">{ico("Actions.Pinned.12", 12)}</span>',
              f'<span data-g="ico-settings">{ico("Settings", 14)}</span>',
              f'<span data-g="ico-info">{ico("Info", 16)}</span>',
              f'<span data-g="ico-open">{ico("OpenInWindow", 12)}</span>']
    return '<template id="sb-glyphs">' + "".join(spans) + '</template>'


def sidebar_foot():
    return ('<div class="sfoot"><div class="sfdiv"></div>'
            '<div class="srow item" id="side-settings" title="Settings">'
            + ico("Settings") + '<span class="lbl">Settings</span></div></div>')


# ------------------------------------------------------------------- grid ----
CHK_SVG = ('<svg width="18" height="18" viewBox="0 0 18 18">'
           '<rect x="1" y="1" width="16" height="16" rx="4" class="chk-bg"/>'
           '<path class="chk-tick" d="M4.5 9l3 3 6-6" fill="none" stroke="white" '
           'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>')


def glyph_for(v, px=16):
    import sidebar as _sb
    return _sb.glyph(_sb._glyph_for(v), px)


def artlib_html():
    """Every icon set the machine can offer, all in the DOM at once.

    The page clones art out of here rather than fetching it, so shipping all of
    the sets is what makes the chooser instant. The active set is unqualified so
    that every existing `#artlib [data-thumb=KEY]` query keeps working untouched;
    the others carry data-set and are picked up only when the user switches.
    """
    import sidebar as _sb
    out = ['<div id="artlib" hidden>']
    for key in ART:
        out.append(f'<div data-thumb="{key}">{art_svg(key)}</div>')
    for key in ART_SM:
        out.append(f'<div data-rico="{key}">{art_svg(key, True)}</div>')
    for sname, (big, small) in ICON_SETS.items():
        if sname == ICON_SET:
            continue
        for key, svg in big.items():
            _ART_N[0] += 1
            out.append(f'<div data-set="{sname}" data-thumb="{key}">'
                       f'{icons.uniquify(svg, _ART_N[0])}</div>')
        for key, svg in small.items():
            _ART_N[0] += 1
            out.append(f'<div data-set="{sname}" data-rico="{key}">'
                       f'{icons.uniquify(svg, _ART_N[0])}</div>')
    out.append(f'<div data-ico="Omnibar.Path">{ico("Omnibar.Path", 16)}</div>')
    out.append(f'<div data-ico="Folder">{ico("Folder", 16)}</div>')
    out.append(f'<div data-ico="Drive">{_sb.glyph("drive", 16)}</div>')
    out.append(f'<div data-ico="Home">{glyph_for({"purpose":"home","kind":"home"}, 16)}</div>')
    out.append(f'<div data-ico="Csep">{CHEVRON_RIGHT}</div>')
    out.append(f'<div data-ico="Close">{TAB_CLS}</div>')
    return "".join(out) + "</div>"


def templates_html():
    return (
        '<template id="tpl-tab"><div class="tab" tabindex="-1">'
        '<span class="tico"></span><span class="tname"></span>'
        f'<span class="x" title="Close tab (Ctrl+W)">{TAB_CLS}</span>'
        '</div></template>'
        '<template id="tpl-cell"><div class="cell" tabindex="-1">'
        '<div class="thumb"></div><div class="cname"></div></div></template>'
        '<template id="tpl-tile"><div class="tile" tabindex="-1">'
        '<div class="thumb"></div><div class="cname"></div>'
        '<div class="tsub"></div></div></template>'
        '<template id="tpl-lrow"><div class="lrow"><span class="rico">'
        '<span class="ricobox"></span></span><span class="lname"></span>'
        "</div></template>"
        '<template id="tpl-row"><div class="row"><div class="c-name">'
        '<span class="rico"><span class="ricobox"></span>'
        f'<span class="rchk">{CHK_SVG}</span></span>'
        '<span class="rname"></span></div><div class="c-tag"></div>'
        '<div class="c-git"></div>'
        '<div class="c-when"></div>'
        '<div class="c-kind"></div><div class="c-size"></div></div></template>'
        '<template id="tpl-crow"><div class="crow"><span class="rico">'
        '<span class="ricobox"></span></span><span class="lname"></span>'
        "</div></template>"
    )


def _data_attrs(name, kind, when, size, pkey, ms, nb,
                created, accessed, ob, md5, sha1, sha256):
    q = name.replace('"', "&quot;")
    try:
        p = localfs.key_path(pkey) if pkey else ""
    except Exception:
        p = ""
    p = p.replace('"', "&quot;")
    h = ""
    if md5:
        h = f' data-md5="{md5}" data-sha1="{sha1}" data-sha256="{sha256}"'
    pv = ""
    th = ""
    if kind != "Folder":
        pv = _preview_for(pkey, nb, name)
        th = _thumb_for(pkey, nb, name)
    if pv:
        h += f' data-pv="{pv}"'
    if th:
        h += f' data-th="{th}"'
    obn = ob if isinstance(ob, int) else -1
    return (f' data-n="{q}" data-k="{kind}" data-w="{when}" data-s="{size}"'
            f' data-p="{p}" data-ms="{ms or 0}" data-sb="{nb if isinstance(nb, int) else -1}"'
            f' data-c="{created}" data-a="{accessed}" data-ob="{obn}"' + h)


def _thumb_box(art, pkey, nb, name):
    """What goes inside `.thumb`: the picture over the glyph.

    Both, always, with the picture stacked on top. A data URI that fails to
    decode in some browser leaves a file icon behind rather than an empty
    box, which is what the comment here used to claim while the code
    returned one or the other; and turning thumbnails off is then a matter
    of hiding the picture rather than of rebuilding the list.
    """
    uri = _thumb_for(pkey, nb, name)
    if not uri:
        return art_svg(art)
    return (f'{art_svg(art)}'
            f'<img class="thumbimg" src="{uri}" alt="" loading="lazy"'
            f' decoding="async">')


def grid_html():
    out = []
    for i, (name, art, kind, when, size, key, pkey, ms, nb,
              created, accessed, ob, md5, sha1, sha256) in enumerate(ITEMS):
        sel = " sel" if name == SELECTED_NAME else ""
        href = href_for(key)
        tag, attrs, close = "div", ' tabindex="-1"', "</div>"
        if href:
            tag, attrs, close = "a", f' href="{href}"', "</a>"
        elif key:
            attrs += ' title="Not part of this export"'
            sel += " nolink"
        attrs += _data_attrs(name, kind, when, size, pkey, ms, nb,
                     created, accessed, ob, md5, sha1, sha256)
        out.append(
            f'<{tag} class="cell{sel}"{attrs}><div class="thumb">{_thumb_box(art, pkey, nb, name)}</div>'
            f'<div class="cname" title="{name}">{name}</div>{close}')
    return "\n".join(out)


#: Column widths live in custom properties so the header cell and the body
#: cell of a column are always the same width by construction, rather than by
#: two numbers that have to be kept equal.
GRIP = '<span class="dh-grip" data-grip="{k}" title="Drag to resize, double click to reset"></span>'


def rows_html():
    out = [
        '<div class="dheader">'
        '<div class="dh-col dh-name" data-dh="Name"><input type="checkbox" id="dh-selall" aria-label="Select all" title="Select all (Ctrl+A)"><span>Name</span>'
        '<svg class="dh-sort" width="8" height="5" viewBox="0 0 8 5" aria-hidden="true" hidden><path d="M4 0l4 5H0z" fill="currentColor"/></svg>' + GRIP.format(k='name') + '</div>'
        '<div class="dh-col dh-tag" data-dh="Tag"><span>Tag</span><svg class="dh-sort" width="8" height="5" viewBox="0 0 8 5" aria-hidden="true" hidden><path d="M4 0l4 5H0z" fill="currentColor"/></svg>' + GRIP.format(k='tag') + '</div>'
        '<div class="dh-col dh-git" data-dh="Git"><span>Git</span><svg class="dh-sort" width="8" height="5" viewBox="0 0 8 5" aria-hidden="true" hidden><path d="M4 0l4 5H0z" fill="currentColor"/></svg>' + GRIP.format(k='git') + '</div>'
        '<div class="dh-col dh-when" data-dh="Date modified"><span>Date modified</span><svg class="dh-sort" width="8" height="5" viewBox="0 0 8 5" aria-hidden="true" hidden><path d="M4 0l4 5H0z" fill="currentColor"/></svg>' + GRIP.format(k='when') + '</div>'
        '<div class="dh-col dh-kind" data-dh="Type"><span>Type</span><svg class="dh-sort" width="8" height="5" viewBox="0 0 8 5" aria-hidden="true" hidden><path d="M4 0l4 5H0z" fill="currentColor"/></svg>' + GRIP.format(k='kind') + '</div>'
        '<div class="dh-col dh-size" data-dh="Size"><span>Size</span><svg class="dh-sort" width="8" height="5" viewBox="0 0 8 5" aria-hidden="true" hidden><path d="M4 0l4 5H0z" fill="currentColor"/></svg>' + GRIP.format(k='size') + '</div>'
        '</div>'
        '<div class="dbody">'
    ]
    for name, art, kind, when, size, key, pkey, ms, nb, \
            created, accessed, ob, md5, sha1, sha256 in ITEMS:
        sel = " sel" if name == SELECTED_NAME else ""
        href = href_for(key)
        tag, attrs, close = "div", "", "</div>"
        if href:
            tag, attrs, close = "a", f' href="{href}"', "</a>"
        elif key:
            attrs, sel = ' title="Not part of this export"', sel + " nolink"
        attrs += _data_attrs(name, kind, when, size, pkey, ms, nb,
                     created, accessed, ob, md5, sha1, sha256)
        out.append(
            f'<{tag} class="row{sel}"{attrs}><div class="c-name"><span class="rico">'
            f'<span class="ricobox">{art_svg(art, True)}</span><span class="rchk">{CHK_SVG}</span></span>'
            f'<span>{name}</span></div><div class="c-tag"></div>'
            f'<div class="c-git"></div>'
            f'<div class="c-when">{when}</div>'
            f'<div class="c-kind">{kind}</div><div class="c-size">{size}</div>{close}')
    out.append('</div>')
    return "\n".join(out)


# --------------------------------------------- details pane and widgets -----
# InfoPane.xaml has Details and Preview tabs bound to ToggleDetailsPane and
# TogglePreviewPane; the details list shows the selected item file details and
# the preview presenter shows PreviewPaneContent per file type. HomePage.xaml
# hosts QuickAccess, Drives, NetworkLocations, FileTags and RecentFiles
# widgets. Below is the static export of those three surfaces, fed only by
# localfs volumes and directory metadata, so nothing is invented.
HOME_WIDGETS = ""

def _drow(k, v):
    return (f'<div class="drow"><span class="k">{k}</span>'
            f'<span class="v" data-dk="{k}">{v}</span></div>')

def details_html():
    label = CRUMBS[-1][0] if CRUMBS else TARGET
    try:
        st = os.stat(TARGET)
        when = _when(int(st.st_mtime * 1000))
    except OSError:
        when = ""
    try:
        created = _when(int(os.stat(TARGET).st_ctime * 1000))
    except OSError:
        created = ""
    # The heading carries the name, so there is no Name row: the running app
    # prints the icon, the name, then Item count, Date Modified, Date Created,
    # Item Path and Tags, and closes with a Properties button.
    return "".join([
        f'<div class="iphead"><div class="iphead-art">{art_svg("folder")}</div>'
        f'<div class="iphead-name" data-dk="Name">{label}</div></div>',
        _drow("Item count", f"{len(ITEMS)} items"),
        _drow("Date Modified", when),
        _drow("Date Created", created),
        _drow("Item Path", TARGET),
        '<div class="drow"><span class="k">Tags</span></div>',
        '<div class="ipbtns">'
        f'<button class="btn-dlg" data-act="ctx-tags">{ico("TagEdit", 16)}'
        '<span>Edit tags</span></button>'
        f'<button class="btn-dlg" data-act="ctx-props">{ico("Properties", 16)}'
        '<span>Properties</span></button></div>',
    ])

def preview_html():
    label = CRUMBS[-1][0] if CRUMBS else TARGET
    return (f'<div class="ipreview-art" id="ipart">{art_svg("folder")}</div>'
            f'<img class="ipreview-img" id="ipreview-img" alt="" hidden>'
            f'<div class="ipreview-text" id="ipreview-text" hidden></div>'
            f'<div class="drow"><span class="k">Name</span>'
            f'<span class="v" data-pk="Name">{label}</span></div>'
            f'<div class="drow"><span class="k">Type</span>'
            f'<span class="v" data-pk="Type">Folder</span></div>')


def _props_row(k, v):
    return (f'<div class="drow"><span class="k">{k}</span>'
            f'<span class="v" data-gk="{k}">{v}</span></div>')


def props_general_html():
    # GeneralPage.xaml names these rows: ItemType, Location, SizeLabel,
    # SizeOnDiskLabel, Created, Modified, Accessed.
    label = CRUMBS[-1][0] if CRUMBS else TARGET
    ap = os.path.abspath(TARGET)
    try:
        st = os.stat(ap)
        created = _when(int(st.st_ctime * 1000))
        modified = _when(int(st.st_mtime * 1000))
        accessed = _when(int(st.st_atime * 1000))
        ob = _human_size(st.st_blocks * 512)
    except OSError:
        created = modified = accessed = ""
        ob = ""
    ndirs = sum(1 for r in ITEMS if r[1] == "folder")
    return "".join([
        _props_row("Name", label),
        _props_row("Type", "Folder"),
        _props_row("Location", os.path.dirname(ap)),
        _props_row("Size", f"{len(ITEMS)} items"),
        _props_row("Size on disk", ob),
        _props_row("Created", created),
        _props_row("Modified", modified),
        _props_row("Accessed", accessed),
    ])

def props_details_html():
    # Matches Files DetailsPage.xaml: Expander sections (Description, Origin, File)
    # with 140px property names, selectable values, and Clear all properties button.
    label = CRUMBS[-1][0] if CRUMBS else TARGET
    ap = os.path.abspath(TARGET)
    try:
        st = os.stat(ap)
        created = _when(int(st.st_ctime * 1000))
        modified = _when(int(st.st_mtime * 1000))
        accessed = _when(int(st.st_atime * 1000))
        mode_str = oct(st.st_mode)[-3:]
        owner = str(st.st_uid)
        size_str = f"{len(ITEMS)} items"
    except OSError:
        created = modified = accessed = ""
        mode_str = "755"
        owner = ""
        size_str = ""

    def row(name, val, key):
        return (f'<div class="det-row"><span class="det-name">{name}</span>'
                f'<span class="det-val" data-detk="{key}">{val}</span></div>')

    def sec(title, rows):
        return (f'<details class="det-sec" open>'
                f'<summary class="det-head"><span>{title}</span>'
                f'<svg class="det-arr" width="8" height="8" viewBox="0 0 8 8" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1.5 2.75L4 5.25L6.5 2.75"/></svg>'
                f'</summary>'
                f'<div class="det-body">{"".join(rows)}</div></details>')

    file_rows = [
        row("Name", label, "Name"),
        row("Item type", "Folder", "Type"),
        row("Folder path", os.path.dirname(ap), "Location"),
        row("Size", size_str, "Size"),
        row("Date created", created, "Created"),
        row("Date modified", modified, "Modified"),
        row("Date accessed", accessed, "Accessed"),
        row("Attributes", mode_str, "Attributes"),
        row("Owner", owner, "Owner"),
    ]
    desc_rows = [
        row("Title", "", "Title"),
        row("Subject", "", "Subject"),
        row("Tags", "", "Tags"),
        row("Categories", "", "Categories"),
        row("Comments", "", "Comments"),
    ]
    origin_rows = [
        row("Authors", owner, "Authors"),
        row("Date acquired", "", "Acquired"),
        row("Copyright", "", "Copyright"),
    ]
    # The camera and the media sections stay out of the way until there is
    # something to put in them: a folder of text files should not show a row
    # for an aperture. Filled by the live layer from /api/details.
    camera_rows = [
        row("Dimensions", "", "Dimensions"),
        row("Camera", "", "Camera"),
        row("Lens", "", "Lens"),
        row("Date taken", "", "Taken"),
        row("Exposure", "", "Exposure"),
        row("F-stop", "", "Aperture"),
        row("ISO speed", "", "Iso"),
        row("Focal length", "", "FocalLength"),
        row("Location", "", "Gps"),
    ]
    media_rows = [
        row("Length", "", "Duration"),
        row("Frame size", "", "FrameSize"),
        row("Frame rate", "", "FrameRate"),
        row("Data rate", "", "Bitrate"),
        row("Video codec", "", "VideoCodec"),
        row("Audio codec", "", "AudioCodec"),
        row("Channels", "", "Channels"),
        row("Sample rate", "", "SampleRate"),
    ]
    camera = ('<div id="det-camera" hidden>'
              + sec("Camera", camera_rows) + '</div>')
    media = ('<div id="det-media" hidden>'
             + sec("Audio and video", media_rows) + '</div>')
    footer = ('<div class="det-footer">'
              '<button class="det-clear" id="props-clear-btn">Clear all properties</button>'
              '</div>')
    return (sec("Description", desc_rows) + sec("Origin", origin_rows)
            + camera + media + sec("File", file_rows) + footer)


def home_page_html():
    import sidebar as _sb
    # 1. Quick access widget (QuickAccessWidget.xaml)
    # UniformGridLayout: Max 6 columns, min item width 100, min item height 72, spacing 8.
    qa_cards = []
    for v in VOLUMES:
        p = v.get("purpose")
        if p in ("desktop", "documents", "downloads", "music", "pictures", "videos"):
            href = href_for(v["root"])
            tag = f'a href="{href}"' if href else "div"
            label = v["label"]
            g = _sb.glyph(_sb._glyph_for(v), 32)
            pin_ico = ico("Actions.Pinned.12", 12)
            qa_cards.append(
                f'<{tag} class="wcard wcard-folder" data-path="{v["root"]}" data-n="{label}" '
                f'data-kind="Folder" tabindex="-1">'
                f'<span class="wcard-pin" title="Pinned">{pin_ico}</span>'
                f'<div class="wcard-ico">{g}</div>'
                f'<div class="wcard-name">{label}</div>'
                f'</{"a" if href else "div"}>'
            )

    # 2. Drives widget (DrivesWidget.xaml)
    # UniformGridLayout: min item width 240, min item height 72, spacing 8.
    drive_cards = []
    for v in VOLUMES:
        if v.get("purpose") in ("home", None) and v.get("kind") in ("system", "removable"):
            if v["root"] == "file:///root" and any(x["root"] == "file:///" for x in VOLUMES):
                continue
            cap = v.get("capacity") or {}
            total = cap.get("total", 0)
            free = cap.get("free", 0)
            used = max(0, total - free)
            pct = int((used / total) * 100) if total > 0 else 0
            total_str = _human_size(total)
            free_str = _human_size(free)
            space_txt = f"{free_str} free of {total_str}" if total > 0 else "Ready"
            g = _sb.glyph(_sb._glyph_for(v), 32)
            href = href_for(v["root"])
            tag = f'a href="{href}"' if href else "div"
            st_icon = ico("Settings", 14)
            drive_cards.append(
                f'<{tag} class="wcard wcard-drive" data-path="{v["root"]}" data-n="{v["label"]}" data-kind="drive" '
                f'data-total="{total}" data-free="{free}" data-used="{used}" data-pct="{pct}" data-fs="ext4" tabindex="-1">'
                f'<div class="wd-icon">{g}</div>'
                f'<div class="wd-info">'
                f'<div class="wd-name">{v["label"]}</div>'
                f'<div class="wd-bar"><div class="wd-fill" style="width:{pct}%"></div></div>'
                f'<div class="wd-sub">{space_txt}</div>'
                f'</div>'
                f'<button class="wd-storage" title="Open Storage Sense" data-act="storage-sense">{st_icon}</button>'
                f'</{"a" if href else "div"}>'
            )

    # 3. Recent files widget (RecentFilesWidget.xaml). A demo list for the
    # screenshot loop, and nothing when shipped: the live layer fills it.
    recent_items = [] if SHIP else [
        ("build_v3.py", os.path.join(ROOT, "build_v3.py"), "py"),
        ("sidebar.py", os.path.join(ROOT, "sidebar.py"), "py"),
        ("README.md", os.path.join(ROOT, "README.md"), "md"),
        ("localfs.py", os.path.join(ROOT, "localfs.py"), "py"),
        ("v3.html", os.path.join(ROOT, "v3.html"), "cfg"),
    ]
    recent_rows = []
    for rname, rpath, rext in recent_items:
        art_ico = art_svg(rext if rext in ART_SM else "txt", True)
        recent_rows.append(
            f'<div class="wrecent-row" data-p="{rpath}" data-n="{rname}" data-k="File" tabindex="-1">'
            f'<span class="wrecent-ico">{art_ico}</span>'
            f'<span class="wrecent-name">{rname}</span>'
            f'<span class="wrecent-path">{rpath}</span>'
            f'</div>'
        )

    # 4. File tags widget (FileTagsWidget.xaml). Demo groups for the
    # screenshot loop; shipped, the tags are the daemon's, drawn live.
    tag_colors = [] if SHIP else [
        ("Blue", "var(--pl-blue)", [("Documents", os.path.join(HOME_DIR, "Documents")), ("files-app", ROOT)]),
        ("Green", "var(--pl-green)", [("Projects", os.path.dirname(ROOT)), ("Pictures", os.path.join(HOME_DIR, "Pictures"))]),
        ("Orange", "var(--pl-amber)", [("Notes", os.path.join(HOME_DIR, "Desktop", "notes.txt")), ("Downloads", os.path.join(HOME_DIR, "Downloads"))]),
        ("Purple", "var(--pl-violet)", [("Videos", os.path.join(HOME_DIR, "Videos")), ("Assets", os.path.join(ROOT, "assets"))]),
    ]
    tag_cards = []
    tag_open_ico = ico("OpenInWindow", 12)
    for tname, tcol, tfiles in tag_colors:
        file_items = []
        for fn, fp in tfiles:
            file_items.append(
                f'<div class="wtag-item" data-p="{fp}" data-n="{fn}">'
                f'<span class="wtag-item-ico">{art_svg("folder", True)}</span>'
                f'<span class="wtag-item-name">{fn}</span>'
                f'</div>'
            )
        tag_cards.append(
            f'<div class="wtag-card">'
            f'<div class="wtag-h">'
            f'<div class="wtag-title"><span class="wtag-dot" style="background:{tcol}"></span><span>{tname}</span></div>'
            f'<button class="wtag-open" title="Open all tagged items">{tag_open_ico}</button>'
            f'</div>'
            f'<div class="wtag-items">{"".join(file_items)}</div>'
            f'</div>'
        )

    # 5. Network locations widget (NetworkLocationsWidget.xaml). Drive shaped
    # cards, one per mounted share, with no space bar: the reference draws its
    # bar only for a location that reported its size, and asking a share for
    # its size is the thing that hangs when the far end has gone away.
    net_cards = []
    for v in NETWORK:
        g = _sb.glyph("network", 32)
        href = href_for(v["root"])
        tag = f'a href="{href}"' if href else "div"
        net_cards.append(
            f'<{tag} class="wcard wnet-card" data-path="{v["root"]}" '
            f'data-n="{v["label"]}" data-kind="network" '
            f'data-protocol="{v["protocol"]}" tabindex="-1">'
            f'<div class="wd-icon">{g}</div>'
            f'<div class="wd-info">'
            f'<div class="wd-name">{esc(v["label"])}</div>'
            f'<div class="wd-sub">{esc(v["source"])} ({v["protocol"]})</div>'
            f'</div>'
            f'</{"a" if href else "div"}>')
    if not net_cards:
        #: What the reference shows instead: an InfoBar, not an empty box.
        net_cards.append(
            '<div class="winfobar" role="status">'
            f'{ico("Info", 16)}'
            '<span>No network locations were found.</span>'
            '<button class="winfobar-btn" data-act="toggle-widget" '
            'data-widget="network">Disable</button></div>')

    chev = ('<svg class="wchev" width="12" height="12" viewBox="0 0 12 12" fill="none" '
            'stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M2.5 4.5l3.5 3.5 3.5-3.5"/></svg>')
    more = ico("More", 16)

    def expander(wid, title, body_html):
        return (
            f'<div class="wsec" id="wsec-{wid}" data-widget="{wid}">'
            f'<div class="wsec-h" data-wid="{wid}">'
            f'<button class="wsec-btn" title="Toggle section">{chev}<span>{title}</span></button>'
            f'<button class="wsec-more" title="More options" data-wid="{wid}">{more}</button>'
            f'</div>'
            f'<div class="wsec-body" id="wbody-{wid}">{body_html}</div>'
            f'</div>'
        )

    #: HomeViewModel.ReloadWidgets' order, which is also the order its menu
    #: lists them in: Quick access, Drives, Network locations, File tags,
    #: Recent files. This page had Recent above File tags and no network
    #: section at all.
    sections = [
        expander("quickaccess", "Quick access", f'<div class="wcards wcards-qa">{"".join(qa_cards)}</div>'),
        expander("drives", "Drives", f'<div class="wcards wcards-drives">{"".join(drive_cards)}</div>'),
        expander("network", "Network locations", f'<div class="wcards wcards-net">{"".join(net_cards)}</div>'),
        expander("tags", "File tags", f'<div class="wtags-grid">{"".join(tag_cards)}</div>'),
        expander("recent", "Recent files", f'<div class="wrecent-list">{"".join(recent_rows)}</div>'),
    ]

    return f'<div class="widgets-page home-widgets" id="home-widgets">{"".join(sections)}</div>'



def _sw(key):
    return (f'<button class="sw" data-pref="{key}" role="switch" '
            f'aria-checked="false" title="Toggle"><span class="knob"></span></button>')


def _ssel(key, options):
    opts = "".join(f'<option value="{v}">{l}</option>' for v, l in options)
    return f'<select class="ssel" data-pref="{key}">{opts}</select>'


def _card(head, desc, ctrl):
    return (f'<div class="scard"><div class="scard-t">'
            f'<div class="scard-h">{head}</div>'
            f'<div class="scard-d">{desc}</div></div>'
            f'<div class="scard-c">{ctrl}</div></div>')


def _sec(title):
    return f'<div class="ssec">{title}</div>'


def _actions_rows():
    pairs = [
        ("Ctrl+T", "New tab"), ("Ctrl+W", "Close tab"),
        ("Ctrl+F", "Search"), ("Ctrl+A", "Select all"),
        ("F5", "Refresh"), ("F2", "Rename"),
        ("Delete", "Move to trash"), ("Alt+Up", "Go to parent folder"),
        ("Backspace", "Go to parent folder"), ("Enter", "Open folder"),
        ("Arrow keys", "Move selection"), ("Shift+Arrow", "Extend selection"),
        ("Type letters", "Jump to the first matching name"),
        ("Escape", "Close dialog or clear selection"),
    ]
    return "".join(
        f'<div class="sact"><span class="skey">{k}</span>'
        f'<span class="sdo">{d}</span></div>' for k, d in pairs)


def settings_pages():
    # Mirrors SettingsPage.xaml. Tags is omitted: file tags need xattr
    # persistence this export does not have, and every control here acts.
    theme_rows = (
        '<div class="mhead">Theme</div>'
        '<div class="mi" data-theme="dark"><span class="mi-ic">'
        '<span class="ck" id="ck-dark"></span></span>'
        '<span class="mi-t">Dark</span></div>'
        '<div class="mi" data-theme="light"><span class="mi-ic">'
        '<span class="ck" id="ck-light"></span></span>'
        '<span class="mi-t">Light</span></div>'
    )
    about_rows = "".join(
        f'<div class="drow"><span class="k">{k}</span>'
        f'<span class="v">{v}</span></div>' for k, v in [
            ("App", "AuraDE Files"),
            ("Version", "Static export"),
            ("Pages", f"{PAGE_TOTAL} pages"),
            ("Views", "Grid, Details, List, Cards, Columns"),
            ("Themes", "Dark, Light")])
    return [
        ("general", "General", "".join([
            _sec("Startup"),
            _card("On startup",
                  "Which folder the window shows first.",
                  _ssel("startup", [("home", "Open home"),
                                    ("last", "Continue where you left off")])),
            _sec("Home widgets"),
            _card("Quick access",
                  "Pinned folder cards on the home page.",
                  _sw("widgets.qa")),
            _card("Drives",
                  "Drive cards on the home page.",
                  _sw("widgets.drives")),
            _card("Recent files",
                  "Recently opened files on the home page.",
                  _sw("widgets.recent")),
        ])),
        ("appearance", "Appearance", "".join([
            theme_rows,
            _sec("Window chrome"),
            _card("Show status bar",
                  "Item counts and selection size at the bottom.",
                  _sw("showStatusbar")),
            _card("Show status center button",
                  "File operation history in the toolbar.",
                  _sw("showSCBtn")),
            _card("Show details pane button",
                  "Details and preview toggle in the toolbar.",
                  _sw("showPaneBtn")),
        ])),
        ("layout", "Layout", "".join([
            _sec("Default view"),
            _card("Layout",
                  "View used when a folder opens without a saved one.",
                  _ssel("defLayout", [("grid", "Grid"), ("details", "Details"),
                                       ("list", "List"), ("cards", "Cards"),
                                       ("columns", "Columns")])),
            _sec("Sorting and grouping"),
            _card("Sort by",
                  "Property new folders sort on.",
                  _ssel("sortBy", [("Name", "Name"),
                                    ("Date modified", "Date modified"),
                                    ("Date created", "Date created"),
                                    ("Size", "Size"), ("Type", "Type")])),
            _card("Sort descending",
                  "Reverse the sort order.",
                  _sw("sortDesc")),
            _card("Group folders",
                  "Where folders sit relative to files.",
                  _ssel("groupBy", [("first", "Folders first"),
                                     ("last", "Files first"),
                                     ("together", "Mixed together")])),
        ])),
        ("folders", "Folders", "".join([
            _card("Show hidden items",
                  "Dotfiles in live folders backed by the service.",
                  _sw("showHidden")),
            _card("Show file extensions",
                  "Hide extensions in names when off.",
                  _sw("showExt")),
            _card("Single-click to open",
                  "Open folders with one click instead of two.",
                  _sw("singleClick")),
            _card("Open folders in new tab",
                  "Every folder opens in its own tab.",
                  _sw("openNewTab")),
            _card("Confirm before deleting",
                  "Ask before moving items to trash.",
                  _sw("confirmDelete")),
            _card("Double-click empty space goes up",
                  "Double-clicking background opens the parent.",
                  _sw("dblclickUp")),
        ])),
        ("actions", "Actions", "".join([
            _sec("Keyboard shortcuts"),
            _actions_rows(),
        ])),
        ("advanced", "Advanced", "".join([
            _card("Export settings",
                  "Download every preference as JSON.",
                  '<button class="btn-dlg" id="btn-prefs-export">Export</button>'),
            _card("Import settings",
                  "Restore preferences from a JSON file.",
                  '<button class="btn-dlg" id="btn-prefs-import">Import</button>'
                  '<input type="file" id="prefs-file" accept="application/json" hidden>'),
            _card("Clear local data",
                  "Forget preferences, history and the saved theme.",
                  '<button class="btn-dlg" id="btn-prefs-clear">Clear</button>'),
        ])),
        ("devtools", "DevTools", "".join([
            _card("Download diagnostics",
                  "Preferences, counts and the current view as JSON.",
                  '<button class="btn-dlg" id="btn-diag">Download</button>'),
        ])),
        ("about", "About", "".join([
            about_rows,
            _sec("Links"),
            _card("Open GitHub repo",
                  "AuraDE source and releases.",
                  '<button class="btn-dlg" id="btn-link-repo">Open</button>'),
            _card("Report an issue",
                  "Bug reports and feature requests.",
                  '<button class="btn-dlg" id="btn-link-issues">Open</button>'),
        ])),
    ]


# settings_dialog() lived here. It rendered the page that render() in the
# script then cleared and rebuilt, so it was generated and thrown away on
# every load. settings_pages() above is still the table it read.


# --------------------------------------------------- footer git status -----
# StatusBar.xaml shows GitNetworkActions, GitBranch and OpenInIDE buttons only
# when a branch is known, and the encoding selector only on zip pages. There
# are no zip pages in this export, so the footer grows a branch button exactly
# when TARGET sits inside a real git repo, and nothing otherwise.
_GIT_CACHE = {}

def _git_info(path):
    ap = os.path.abspath(path)
    if ap in _GIT_CACHE:
        return _GIT_CACHE[ap]
    root, branch, cur = ap, "", ""
    while True:
        head = os.path.join(root, ".git", "HEAD")
        if os.path.isfile(head):
            try:
                with open(head) as fh:
                    line = fh.read().strip()
                if line.startswith("ref:"):
                    branch = line.split("/")[-1]
                else:
                    branch = line[:12]
                cur = root
            except OSError:
                pass
            break
        parent = os.path.dirname(root)
        if parent == root:
            break
        root = parent
    status, branches = "", []
    if cur:
        import subprocess as _sp
        try:
            out = _sp.run(["git", "-C", cur, "status", "-sb",
                           "--untracked-files=no"], capture_output=True,
                          text=True, timeout=5).stdout.splitlines()
            if out and out[0].startswith("## "):
                head = out[0][3:]
                ahead, behind = "", ""
                if "ahead " in head:
                    ahead = head.split("ahead ")[1].split("]")[0].split(",")[0]
                if "behind " in head:
                    behind = head.split("behind ")[1].split("]")[0].split(",")[0]
                bits = [b for b in
                        ([f"ahead {ahead}"] if ahead else []) +
                        ([f"behind {behind}"] if behind else [])]
                status = ", ".join(bits)
        except Exception:
            pass
        try:
            out = _sp.run(["git", "-C", cur, "branch", "--format=%(refname:short)"],
                          capture_output=True, text=True, timeout=5).stdout.splitlines()
            branches = [b.strip().lstrip("* ") for b in out if b.strip()][:20]
        except Exception:
            pass
    info = (branch, status, branches)
    _GIT_CACHE[ap] = info
    return info


def git_html():
    """The status bar's git area.

    Always emitted, and hidden when there is nothing to say, because in live
    mode the folder decides whether there is: the export is built from one
    directory, the app walks into many.
    """
    branch, status, branches = _git_info(TARGET)
    rows = []
    for b in branches:
        mark = " on" if b == branch else ""
        rows.append(f'<div class="mi"><span class="mi-ic">'
                    f'<span class="ck{mark}"></span></span>'
                    f'<span class="mi-t">{b}</span></div>')
    menu = "".join(rows) if rows else mi_dis("No branches")
    hide = "" if branch else " hidden"
    stat_hide = "" if status else " hidden"
    #: The reference's GitNetworkActions: the same button that shows how far
    #: ahead and behind the branch is opens a flyout of Pull, Push and Sync.
    #: Three and not six, because that is what StatusBar.xaml has; fetch,
    #: init and clone live in the palette and the menus, as they do there.
    net = "".join(
        f'<div class="mi" data-command="{code}">'
        f'<span class="mi-ic">{ico(glyph)}</span>'
        f'<span class="mi-t">{esc(FILES_COMMANDS[code]["label"])}</span></div>'
        for code, glyph in [("GitPull", "Git.Pull"), ("GitPush", "Git.Push"),
                            ("GitSync", "Git.Sync")])
    return (f'<span class="git-wrap" id="git-wrap"{hide}>'
            f'<span class="div"></span>'
            f'<span class="twrap">'
            f'<button class="sbtn" id="git-status-btn" title="{status}"'
            f'{stat_hide}>{ico("Git")}<span>{status}</span></button>'
            f'<div class="menu" id="m-git-net" hidden>{net}</div></span>'
            f'<span class="div" id="git-status-div"{stat_hide}></span>'
            f'<span class="twrap">'
            f'<button class="sbtn" id="git-branch-btn" title="Manage branches">'
            f'{ico("Git.Branch")}<span id="git-branch">{branch}</span></button>'
            f'<div class="menu" id="m-git" hidden>{menu}</div></span></span>')


def list_html():
    out = []
    for name, art, kind, when, size, key, pkey, ms, nb, \
            created, accessed, ob, md5, sha1, sha256 in ITEMS:
        sel = " sel" if name == SELECTED_NAME else ""
        href = href_for(key)
        tag, attrs, close = "div", ' tabindex="-1"', "</div>"
        if href:
            tag, attrs, close = "a", f' href="{href}"', "</a>"
        elif key:
            attrs += ' title="Not part of this export"'
        attrs += _data_attrs(name, kind, when, size, pkey, ms, nb,
                     created, accessed, ob, md5, sha1, sha256)
        out.append(
            f'<{tag} class="lrow{sel}"{attrs}><span class="rico">'
            f'<span class="ricobox">{art_svg(art, True)}</span></span>'
            f'<span class="lname" title="{name}">{name}</span>{close}')
    return "\n".join(out)


def cards_html():
    out = []
    for name, art, kind, when, size, key, pkey, ms, nb, \
            created, accessed, ob, md5, sha1, sha256 in ITEMS:
        sel = " sel" if name == SELECTED_NAME else ""
        href = href_for(key)
        tag, attrs, close = "div", ' tabindex="-1"', "</div>"
        if href:
            tag, attrs, close = "a", f' href="{href}"', "</a>"
        elif key:
            attrs += ' title="Not part of this export"'
        attrs += _data_attrs(name, kind, when, size, pkey, ms, nb,
                     created, accessed, ob, md5, sha1, sha256)
        out.append(
            f'<{tag} class="tile{sel}"{attrs}><div class="thumb">{_thumb_box(art, pkey, nb, name)}</div>'
            f'<div class="cname" title="{name}">{name}</div>'
            f'<div class="tsub">{kind}</div>{close}')
    return "\n".join(out)


def columns_html():
    # Miller columns: one column per recent ancestor level showing that
    # folder's subfolders with the trail entry selected, plus the current
    # entries in the last column. Every row is a real link or an honestly
    # marked dead end, same as everywhere else.
    chain = CRUMBS[-3:]
    out = ['<div class="cols">']
    for i, (label, key) in enumerate(chain):
        last = i == len(chain) - 1
        try:
            page = localfs.list_dir(localfs.key_path(key))
        except OSError:
            continue
        out.append(f'<div class="col"><div class="col-h">{label}</div>')
        if last:
            for name, art, kind, when, size, key_, pkey, ms, nb, \
                    created, accessed, ob, md5, sha1, sha256 in ITEMS:
                sel = " sel" if name == SELECTED_NAME else ""
                href = href_for(key_)
                tag, attrs, close = "div", "", "</div>"
                if href:
                    tag, attrs, close = "a", f' href="{href}"', "</a>"
                elif key_:
                    attrs = ' title="Not part of this export"'
                attrs += _data_attrs(name, kind, when, size, pkey, ms, nb,
                     created, accessed, ob, md5, sha1, sha256)
                out.append(
                    f'<{tag} class="crow{sel}"{attrs}><span class="rico">'
                    f'<span class="ricobox">{art_svg(art, True)}</span></span>'
                    f'<span class="lname" title="{name}">{name}</span>{close}')
        else:
            nextkey = chain[i + 1][1]
            subs = sorted((e for e in page["entries"] if e["isDirectory"]),
                          key=lambda e: e["name"].lower())[:40]
            for e in subs:
                href = href_for(e["key"])
                sel = " sel" if e["key"] == nextkey else ""
                tag, attrs, close = "div", "", "</div>"
                if href:
                    tag, attrs, close = "a", f' href="{href}"', "</a>"
                else:
                    attrs = ' title="Not part of this export"'
                attrs += _data_attrs(e["name"], "Folder", "", "", e["key"], 0, -1,
                                         "", "", -1, "", "", "")
                out.append(
                    f'<{tag} class="crow{sel}"{attrs}><span class="rico">'
                    f'<span class="ricobox">{art_svg("folder", True)}</span></span>'
                    f'<span class="lname" title="{e["name"]}">{e["name"]}</span>{close}')
        out.append('</div>')
    out.append('</div>')
    return "".join(out)


TOOLBAR_LEFT = [("New.Item", "New", True), None,
                ("Cut", "Cut", False), ("Copy", "Copy", False),
                ("Paste", "Paste", False), ("Rename", "Rename", False),
                ("Share", "Share", False), ("Delete", "Delete", False),
                ("Properties", "Properties", False)]
TOOLBAR_RIGHT = [("Filter", False), ("SelectMode", True), ("Sorting", True),
                 ("IconLayout.Grid.28", True), ("PanelRight", False),
                 ("Shelf", False)]

# ------------------------------------------------------------ menus ---------
# Menu contents sourced from the Files XAML so the labels match the app.
# Toolbar.xaml: SelectAllMFI / InvertSelectionMFI / ClearSelectionMFI sit in
# the SelectionOptions flyout; SortBy* / SortAscending / SortDescending plus
# GroupBy* / GroupAscending / GroupDescending plus SortFoldersFirst /
# SortFilesFirst / SortFilesAndFoldersTogether sit in the ArrangementOptions
# flyout; Details / List / Cards / Grid / Columns radios sit in LayoutFlyout;
# the New group is the dynamic NewItemCommandGroup (Folder, File, Shortcut);
# the filearea menu order follows ContentPageContextFlyoutFactory.cs
# (Open, Open with, Open in new tab, Open in new window, Cut, Copy, Paste,
# Copy path, Create shortcut, Rename, Share, Delete, Properties,
# Open parent folder, Pin to sidebar).
def mi(icon, label, attrs="", key=""):
    pic = ico(icon) if icon else '<span class="mi-ic"></span>'
    acc = f'<span class="shortcut">{key}</span>' if key else ""
    return (f'<div class="mi" {attrs}>{pic}<span class="mi-t">{label}</span>'
            f'{acc}</div>')

def mi_dis(label):
    return (f'<div class="mi dis" title="Not part of this export">'
            f'<span class="mi-ic"></span><span class="mi-t">{label}</span></div>')

def mi_off(icon, label):
    # Present but not yet wired: visible, disabled, never dead-clickable.
    # No data-act on purpose, so the click dispatcher cannot fire it.
    pic = ico(icon) if icon else '<span class="mi-ic"></span>'
    return (f'<div class="mi dis" title="Not yet wired">'
            f'{pic}<span class="mi-t">{label}</span></div>')

def mi_hidden(act, label):
    # Placeholder host kept hidden until a backend or overflow shows it.
    return (f'<div class="mi" data-act="{act}" hidden>'
            f'<span class="mi-ic"></span><span class="mi-t">{label}</span></div>')

NEW_MENU = "".join([
    mi("New.Folder", "Folder",
       'data-act=\"newfolder\" data-live title=\"Needs backend\"', "Ctrl+Shift+N"),
    mi("New.File", "File", 'data-act=\"newfile\" data-live title=\"Needs backend\"'),
    mi("Shortcut", "Shortcut", 'data-act="newshortcut"'),
    '<div class="msep"></div>',
    mi_off("Zip", "Compressed (zipped) Folder"),
    mi_off("New.File", "Text Document"),
])

SELECT_MENU = "".join([
    mi("SelectAll", "Select all", 'data-act="sel-all"'),
    mi("SelectInvert", "Invert selection", 'data-act="sel-inv"'),
    mi("SelectNone", "Clear selection", 'data-act="sel-clear"'),
])

def _checkrows(names, checked=0, group=""):
    out = []
    for i, n in enumerate(names):
        mark = " on" if i == checked else ""
        grp = f' data-sort-group="{group}"' if group else ""
        out.append(f'<div class="mi"{grp} data-sort="{n}">'
                   f'<span class="mi-ic"><span class="ck{mark}"></span></span>'
                   f'<span class="mi-t">{n}</span></div>')
    return "".join(out)

SORT_MENU = (
    '<div class="mi sub"><span class="mi-ic"></span>'
    '<span class="mi-t">Sort by</span><span class="mi-arrow"></span>'
    '<div class="menu sub">'
    + _checkrows(["Name", "Date modified", "Date created", "Size", "Type", "Tag"], 0, "sort-field")
    + '<div class="msep"></div>'
    + _checkrows(["Ascending", "Descending"], 0, "sort-dir")
    + "</div></div>"
    + '<div class="msep"></div>'
    + _checkrows(["Folders first", "Files first", "Files and folders together"], 0, "sort-folder")
)

LAYOUT_MENU = (
    '<div class="mhead">Layout</div>'
    + mi("IconLayout.Details.28", "Details", 'data-act="lay-details"')
    + mi("IconLayout.List.28", "List", 'data-act="lay-list"')
    + mi("IconLayout.Tiles.28", "Cards", 'data-act="lay-cards"')
    + mi("IconLayout.Grid.28", "Grid, small", 'data-act="lay-grid-small"')
    + mi("IconLayout.Grid.28", "Grid, medium", 'data-act="lay-grid"')
    + mi("IconLayout.Grid.28", "Grid, large", 'data-act="lay-grid-large"')
    + mi("IconLayout.Columns.28", "Columns", 'data-act="lay-columns"')
    + '<div class="msep"></div>'
    + mi("IconLayout.Auto", "Adaptive", 'data-act="lay-adaptive"')
)

def mi_sub(icon, label, sub_html, sub_id=""):
    """A row that opens a submenu. An empty icon name leaves the column blank
    rather than reaching into the library for a glyph that is not there."""
    chev = ('<svg class="mchev" width="10" height="10" viewBox="0 0 10 10" fill="none" '
            'stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M3.5 1.5l3.5 3.5-3.5 3.5"/></svg>')
    pic = ico(icon, 16) if icon else '<span class="mi-ic"></span>'
    return (f'<div class="mi-sub">'
            f'<div class="mi">{pic}<span class="mi-t">{label}</span>{chev}</div>'
            f'<div class="ctx-sub"{f" id={sub_id!r}" if sub_id else ""}>'
            f'{sub_html}</div></div>')

CTX_FILE_TAGS_SUB = "".join([
    mi_off("Tag", "Blue"),
    mi_off("Tag", "Green"),
    mi_off("Tag", "Orange"),
    mi_off("Tag", "Purple"),
    mi_off("Tag", "Red"),
    mi_off("Tag", "Yellow"),
])

# ------------------------------------------------- the context menus --------
# Files builds one list for both context menus and shows a row when the row's
# own condition holds. `assets/files-menus.json` is that list, read out of
# ContentPageContextFlyoutFactory.cs by tools/extract_menus.py, and the two
# menus below are the one list seen from the two sides Files sees it from: a
# row that needs a selection belongs to the menu over a file, a row that needs
# there not to be one belongs to the menu over the background, and most rows
# belong to both. Order, nesting and the row that runs across the top are the
# reference's, not a judgement, and none of it is written down twice.
#
# What is left to decide when the menu opens is whether each command can run,
# which is the same question `ContextMenuFlyoutItemViewModelBuilder` asks:
# a row with no condition of its own appears only while its command is
# executable, and a row with one stays and goes grey. `dressMenu` answers it.

MENUS = json.load(open(f"{ROOT}/assets/files-menus.json"))["menus"]

#: The art a row is drawn with, where neither table names one this page has.
#: Files gives a row either a themed icon of its own or a Segoe glyph, and
#: neither is ours: the Segoe font is not redistributable and the themed art
#: belongs to Files. So the glyphs are this page's, and which one goes with
#: which row is written here rather than guessed from the label, because
#: guessing puts the folder icon on "Format" the first time a label changes.
MENU_ART = {
    "Layout": "IconLayout.Grid.28",
    "LayoutDetails": "IconLayout.Details.28",
    "LayoutList": "IconLayout.List.28",
    "LayoutCards": "IconLayout.Tiles.28",
    "LayoutGrid": "IconLayout.Grid.28",
    "LayoutColumns": "IconLayout.Columns.28",
    "LayoutAdaptive": "IconLayout.Auto",
    "Sort by": "Sorting",
    "Group by": "Grouping",
    "Date modified": "Grouping",
    "Date created": "Grouping",
    "Date deleted": "Grouping",
    "RefreshItems": "Refresh",
    "New": "New.Folder",
    "CreateFolder": "New.Folder",
    "File": "New.File",
    "CreateShortcutFromDialog": "Shortcut",
    "OpenWith": "OpenWith",
    "OpenFileLocation": "NavUp",
    "OpenParentFolder": "NavUp",
    "Open in new pane": "OpenInPaneVertical",
    "Split vertically": "OpenInPaneVertical",
    "Split horizontally": "OpenInPaneHorizontal",
    "OpenInOtherPane": "MoveTo",
    "Set as": "SetWallpaper.16",
    "SetAsWallpaperBackground": "SetWallpaper.16",
    "SetAsLockscreenBackground": "Status.Locked",
    "SetAsSlideshowBackground": "SetSlideshow.16",
    "SetAsAppBackground": "Settings.General.BackdropMaterial",
    "RunAsAdmin": "RunAs.Elevated",
    "RunAsAnotherUser": "RunAs.User",
    "Compress": "Zip",
    "Extract": "Actions.Extracting",
    "DecompressArchive": "Actions.Extracting",
    "DecompressArchiveHere": "Actions.Extracting",
    "DecompressArchiveHereSmart": "Actions.Extracting",
    "DecompressArchiveToChildFolder": "Actions.Extracting",
    "Send to": "CopyTo",
    "Turn on BitLocker": "Status.Locked",
    "Manage BitLocker": "Status.Locked",
    "EditInNotepad": "New.File",
    "OpenTerminal": "OpenInTerminal",
    "OpenStorageSense": "Settings",
    "FormatDrive": "Settings.General.Edit",
    "Loading...": "More",
    # The widget and sidebar menus. Several are the same command reached from
    # a different place, and Files gives each place its own command, so each
    # is named rather than matched on a prefix.
    "Eject": "Actions.Eject",
    "FormatDriveFromHome": "Settings.General.Edit",
    "FormatDriveFromSidebar": "Settings.General.Edit",
    "OpenStorageSenseFromHome": "Settings",
    "OpenStorageSenseFromSidebar": "Settings",
    "OpenTerminalFromHome": "OpenInTerminal",
    "OpenTerminalFromSidebar": "OpenInTerminal",
    "OpenInOtherPaneFromHome": "MoveTo",
    "OpenInOtherPaneFromSidebar": "MoveTo",
    "OpenSettingsFile": "Settings",
    "Clear all items": "Actions.Delete",
    "Remove this item": "Delete",
    "Create new library": "Properties.Library",
    "Restore default libraries": "RestoreDeleted",
    "Reorder sidebar items": "MoveTo",
    "Hide this section": "PanelLeftClose",
}
for _field in ("Name", "DateModified", "DateCreated", "Type", "Size",
               "SyncStatus", "Tag", "Path", "OriginalFolder", "DateDeleted"):
    MENU_ART[f"SortBy{_field}"] = "Sorting"
MENU_ART["SortAscending"] = MENU_ART["SortDescending"] = "Sorting"
for _field in ("None", "Name", "Type", "Size", "SyncStatus", "Tag",
               "OriginalFolder", "FolderPath", "DateModifiedYear",
               "DateModifiedMonth", "DateModifiedDay", "DateCreatedYear",
               "DateCreatedMonth", "DateCreatedDay", "DateDeletedYear",
               "DateDeletedMonth", "DateDeletedDay"):
    MENU_ART[f"GroupBy{_field}"] = "Grouping"
MENU_ART["GroupAscending"] = MENU_ART["GroupDescending"] = "Grouping"

#: Which widget each of the Home menu's toggles turns off. Files names them
#: after the settings property; this page names its sections after the thing
#: in them, and all five line up.
MENU_WIDGET = {
    "ShowQuickAccessWidget": "quickaccess",
    "ShowDrivesWidget": "drives",
    "ShowNetworkLocationsWidget": "network",
    "ShowFileTagsWidget": "tags",
    "ShowRecentFilesWidget": "recent",
}

#: The one row in any of these menus that Files answers with a handler of its
#: own rather than with a command. Keyed on the resource name, because that is
#: the only stable name such a row has.
MENU_ROW_ACTS = {
    "HorizontalMultitaskingControlMoveTabToNewWindow.Text": "tab-movewin",
    "ReorderSidebarItemsDialogText": "sidebar-reorder",
}

#: The rows Files fills from the Windows shell. They keep their place and stay
#: hidden: a row that says "Loading..." for ever is worse than no row, and the
#: shell that would fill it is not here. Each keeps a stable name so the day a
#: backend can answer, the row is already in the right place. A name and not
#: an id, because the same slot stands in more than one menu and an id may
#: only be used once on a page.
MENU_SLOT = {
    "OpenWithOverflow": "openwith-overflow",
    "SendToOverflow": "sendto-overflow",
    "TurnOnBitLockerPlaceholder": "bitlocker-on",
    "ManageBitLockerPlaceholder": "bitlocker-manage",
    "OverflowSeparator": "overflow-separator",
    "ItemOverflow": "item-overflow",
}


def menu_name(row):
    """What a row is called.

    Its own text when it has any, and its command's label otherwise. The two
    halves of Open in new pane are the same command under two names, so a row
    that takes the command's label would read "Open in new pane" twice.
    """
    if row.get("label"):
        #: One caption is a format string with the section's name in it, and
        #: the row is drawn before there is a section to name.
        return plain(row["label"], standin="this")
    spec = FILES_COMMANDS.get(row.get("command") or "") or {}
    return plain(spec.get("label")) or row.get("command") or ""


def menu_art(row):
    """The glyph for a row, or nothing when this page has no art for it."""
    name = MENU_ART.get(row.get("command") or menu_name(row))
    if not name:
        spec = FILES_COMMANDS.get(row.get("command") or "") or {}
        name = (row.get("glyph") or spec.get("glyph") or "")
        name = name.replace("App.ThemedIcons.", "")
    return name if name in ICONS else ""


def menu_key(row):
    """The shortcut printed down the right of a row.

    A bare Enter is left off, as the reference leaves it off: every list
    answers Enter, and printing it on Open prints it on every menu there is.
    """
    keys = (FILES_COMMANDS.get(row.get("command") or "") or {}).get("hotkeys") or []
    return "" if not keys or keys[0] == "Enter" else keys[0]


def menu_side(row, side):
    """Whether a row belongs to the menu being built.

    Only the content page's list serves two menus, so every other menu passes
    no side at all and every row in it belongs.
    """
    return side is None or row.get("side", "both") in (side, "both")


def menu_rows(rows, side, top=True):
    out = []
    for row in rows:
        if not menu_side(row, side):
            continue
        slot = MENU_SLOT.get(row.get("tag") or "")
        if row.get("separator"):
            mark = f' data-slot="{slot}" hidden' if slot else ""
            out.append(f'<div class="msep"{mark}></div>')
            continue
        #: The bar across the top holds these, so they are not also rows.
        if top and row.get("primary"):
            continue
        name = esc(menu_name(row))
        art = ico(menu_art(row)) if menu_art(row) else '<span class="mi-ic"></span>'
        kids = row.get("items") or []
        if slot:
            out.append(f'<div class="mi" data-slot="{slot}" hidden>'
                       f'<span class="mi-ic"></span>'
                       f'<span class="mi-t">{name}</span></div>')
            continue
        if kids:
            out.append(mi_sub(menu_art(row), name, menu_rows(kids, side, False)))
            continue
        code = row.get("command")
        if not code and row.get("setting"):
            #: A row bound to a setting rather than to a command. The Home
            #: menu's widget list is five of them, and each is the only place
            #: its widget can be turned off.
            which = MENU_WIDGET.get(row["setting"])
            if not which:
                out.append(mi_off(menu_art(row), name))
                continue
            out.append(f'<div class="mi" data-act="toggle-widget" '
                       f'data-widget="{which}">'
                       f'<span class="mck on" id="ck-w-{which}">{CHK_SVG}</span>'
                       f'<span class="mi-t">{name}</span></div>')
            continue
        if not code and MENU_ROW_ACTS.get(row.get("key")):
            #: A row Files answers with a handler of its own rather than with
            #: a command. There is one, and it is named by its resource key
            #: rather than by its caption, because a caption is not a name.
            out.append(mi(menu_art(row), name,
                          f'data-act="{MENU_ROW_ACTS[row["key"]]}"'))
            continue
        if not code:
            #: A row with neither a command nor children is a slot the shell
            #: fills. It is drawn, and it does nothing, and it says so.
            out.append(mi_off(menu_art(row), name))
            continue
        key = menu_key(row)
        #: A row whose visibility Files states outright keeps its place and
        #: goes grey; one that has none is drawn only while it can run. The
        #: two are told apart at run time by this attribute alone.
        keep = " data-keep" if row.get("show") else ""
        toggle = " data-toggle" if (FILES_COMMANDS.get(code) or {}).get("toggle") else ""
        #: A toggle is drawn the way WinUI draws one: a check in the icon
        #: column when it is on, and nothing there when it is not. It does not
        #: also carry the command's glyph, because the column holds one thing.
        if toggle:
            art = '<span class="mi-ic"><span class="ck"></span></span>' 
        arg = f' data-arg="{esc(row["parameter"])}"' if row.get("parameter") else ""
        acc = f'<span class="shortcut">{esc(key)}</span>' if key else ""
        out.append(f'<div class="mi" data-command="{esc(code)}"{keep}{toggle}{arg}>'
                   f'{art}<span class="mi-t">{name}</span>{acc}</div>')
    return "".join(out)


def menu_bar(rows, side=None):
    """The row of icon buttons across the top.

    `IsPrimary` in the reference: commands drawn as buttons rather than as
    lines, and not repeated further down the list. Every one of the seven
    menus has some, from two in the sidebar's to seven in the file menu's.
    """
    btns = []
    for row in rows:
        if not (row.get("primary") and menu_side(row, side)):
            continue
        code = row["command"]
        name = menu_name(row)
        key = menu_key(row)
        tip = f"{name} ({key})" if key else name
        keep = " data-keep" if row.get("show") else ""
        btns.append(f'<button class="ctx-bbtn" data-command="{esc(code)}"{keep} '
                    f'title="{esc(tip)}">{ico(menu_art(row))}</button>')
    if not btns:
        return ""
    return f'<div class="ctx-bar">{"".join(btns)}</div><div class="msep"></div>'


CTX_FILE_TAGS_SUB = "".join([
    mi_off("Tag", "Blue"),
    mi_off("Tag", "Green"),
    mi_off("Tag", "Orange"),
    mi_off("Tag", "Purple"),
    mi_off("Tag", "Red"),
    mi_off("Tag", "Yellow"),
])

#: This page's own, and the only row in either menu that is not the
#: reference's. Files edits tags from the properties window and the sidebar;
#: this export has a working tag store and a submenu that drives it, so the
#: row stays and is named here rather than blending into the generated list.
CTX_FILE_EXTRA = mi_sub("TagEdit", "Edit tags", CTX_FILE_TAGS_SUB, "sub-tags")

CTX_FILE = (menu_bar(MENUS["content"], "item")
            + menu_rows(MENUS["content"], "item") + CTX_FILE_EXTRA)

CTX_BG = (menu_bar(MENUS["content"], "background")
          + menu_rows(MENUS["content"], "background"))


def whole_menu(key):
    """One of the menus that is not split in two, built the same way."""
    return menu_bar(MENUS[key]) + menu_rows(MENUS[key], None)


# The four that have somewhere to open. Files builds them in the widget view
# models and in the sidebar, in the same shape as the content page's, so they
# are read by the same walk and drawn by the same one.
CTX_DRIVE = whole_menu("drive")
CTX_QA = whole_menu("quickaccess")
CTX_RECENT = whole_menu("recent")
CTX_NETWORK = whole_menu("network")
CTX_FILETAGS = whole_menu("filetags")
CTX_SIDE = whole_menu("sidebar")
# Files writes these two in XAML rather than building them in C#, so
# tools/extract_menus.py reads them out of HomePage.xaml and TabBar.xaml. The
# Home menu was three rows short here: the network locations widget had no
# toggle, and Split pane and Close active pane were missing entirely.
CTX_HOME = whole_menu("home")
CTX_TAB = whole_menu("tab")


# Sidebar pane-background menu: 7 visibility toggles, wired via
# data-act="toggle-sidepane" plus data-pane. No submenus, no separators.
CTX_SIDE_BG = "".join([
    mi("FavoritePin", "Pinned", 'data-act="toggle-sidepane" data-pane="pinned"'),
    mi("Properties.Library", "Libraries", 'data-act="toggle-sidepane" data-pane="libraries"'),
    mi("Folder", "Drives", 'data-act="toggle-sidepane" data-pane="drives"'),
    mi("Status.Cloud", "Cloud drives", 'data-act="toggle-sidepane" data-pane="clouddrives"'),
    mi("Status.Available", "Network", 'data-act="toggle-sidepane" data-pane="network"'),
    mi("OpenInTerminal", "WSL", 'data-act="toggle-sidepane" data-pane="wsl"'),
    mi("Tag", "File tags", 'data-act="toggle-sidepane" data-pane="filetags"'),
])

PALETTE_CMDS = [
    ("New.Folder", "New folder"),
    ("Cut", "Cut"),
    ("Copy", "Copy"),
    ("Paste", "Paste"),
    ("Rename", "Rename"),
    ("Share", "Share"),
    ("Delete", "Delete"),
    ("SelectAll", "Select all"),
    ("Sorting", "Sort by name"),
    ("Grouping", "Group by none"),
    ("IconLayout.Details.28", "Switch to details view"),
    ("IconLayout.List.28", "Switch to list view"),
    ("IconLayout.Tiles.28", "Switch to cards view"),
    ("IconLayout.Columns.28", "Switch to columns view"),
    ("IconLayout.Grid.28", "Switch to grid view"),
    ("Filter", "Toggle filter"),
    ("PanelRight", "Toggle details pane"),
    ("Refresh", "Refresh"),
    ("Properties", "Properties"),
    ("Settings", "Settings"),
]

def palette_html():
    """Every command, as the palette's rows.

    Rendered here rather than built by the page so each row carries its real
    glyph: `ico` has the artwork and the page does not, and an icon assembled
    at runtime would need a sink the page is not allowed to use.

    The description is the first line and the label is not, which looks
    backwards until you see the list: eleven commands are called "Name" and
    the only thing that tells them apart is "Sort items by name" against
    "Group items by name". Files' own palette reads the same way.
    """
    rows = []
    for code, spec in sorted(
            FILES_COMMANDS.items(),
            key=lambda kv: (plain(kv[1].get("description")) or
                            plain(kv[1].get("label")) or kv[0]).lower()):
        label = plain(spec.get("label")) or code
        said = plain(spec.get("description")) or label
        glyph = (spec.get("glyph") or "").replace("App.ThemedIcons.", "")
        art = ico(glyph) if glyph in ICONS else '<span class="pc-noico"></span>'
        keys = spec.get("hotkeys") or []
        key = (f'<span class="pc-key">{esc(keys[0])}</span>' if keys else "")
        #: `data-cmd` stays the searchable text and keeps its old name: the
        #: filter reads it, and so do the checks that drive the palette.
        #: The label, the code and the category are searchable but not shown.
        #: The reference's row is three columns, icon, title and shortcut, and
        #: a chip repeating the category on every row is not one of them.
        find = f"{said} {label} {code} {spec.get('category', '')}"
        rows.append(
            f'<div class="pcmd" data-cmd="{esc(find)}" data-code="{esc(code)}" '
            f'data-title="{esc(said)}" role="option" tabindex="-1">{art}'
            f'<span class="mi-t">{esc(said)}</span>'
            f'{key}</div>')
    return "".join(rows)



# ---------------------------------------------------- toolbar catalog -------
#: Every button that can sit on the toolbar, and which ones do by default.
#: The reference lets a person add, remove and reorder these, so the list has
#: to be data rather than markup.
TOOLBAR_CATALOG = [
    ("new",        "New.Item",             "New",              True),
    ("cut",        "Cut",                  "Cut",              True),
    ("copy",       "Copy",                 "Copy",             True),
    ("paste",      "Paste",                "Paste",            True),
    ("rename",     "Rename",               "Rename",           True),
    ("share",      "Share",                "Share",            True),
    ("delete",     "Delete",               "Delete",           True),
    ("properties", "Properties",           "Properties",       True),
    ("filter",     "Filter",               "Filter",           True),
    ("selectmode", "SelectMode",           "Selection",        True),
    ("sorting",    "Sorting",              "Sort",             True),
    ("layout",     "IconLayout.Grid.28",   "Layout",           True),
    ("pane",       "PanelRight",           "Preview pane",     True),
    ("refresh",    "Refresh",              "Refresh",          False),
    ("back",       "NavBack",              "Back",             False),
    ("forward",    "NavForward",           "Forward",          False),
    ("copypath",   "CopyAsPath",           "Copy path",        False),
    ("selectall",  "SelectAll",            "Select all",       False),
    ("compress",   "Zip",                  "Compress",         False),
    ("terminal",   "OpenInTerminal",       "Open in terminal", False),
    ("pin",        "FavoritePin",          "Pin to sidebar",   False),
    ("shelf",      "Shelf",                "Shelf",            True),
]
TOOLBAR_CATALOG_JSON = json.dumps(
    [{"id": i, "label": lab, "on": on} for i, _k, lab, on in TOOLBAR_CATALOG])
TOOLBAR_DEFAULT_JSON = json.dumps([i for i, _k, _l, on in TOOLBAR_CATALOG if on])

#: The tags a fresh install starts with. The settings page keeps the live list
#: in localStorage; this is what the file list falls back to before it exists.
TAG_DEFAULTS = [
    {"id": "tag-blue", "name": "Blue", "color": "#3584e4"},
    {"id": "tag-green", "name": "Green", "color": "#33d17a"},
    {"id": "tag-orange", "name": "Orange", "color": "#ff7800"},
    {"id": "tag-purple", "name": "Purple", "color": "#9141ac"},
    {"id": "tag-red", "name": "Red", "color": "#e01b24"},
    {"id": "tag-yellow", "name": "Yellow", "color": "#f6d32d"},
]
TAG_DEFAULTS_JSON = json.dumps(TAG_DEFAULTS)

#: The mark, from installer/assets/aurade-mark.png, the same artwork the
#: greeter and the installer paint. It is a raster, so it is embedded at the
#: size the About page draws it at rather than shipped full size.
MARK_URI = "data:image/png;base64," + open(f"{ROOT}/assets/aurade-mark-160.b64").read().strip()
#: A stand-in wallpaper sample so the Mica backdrop is visible in the static
#: export, where there is no backend to ask what the desktop is set to. Live
#: mode replaces it with the real one. It is one of the installer's own
#: pictures, used here as a developer backdrop and not offered to anyone as a
#: desktop wallpaper, which is what its own README asks.
MICA_SAMPLE_URI = ("data:image/jpeg;base64,"
                   + open(f"{ROOT}/assets/mica-sample.b64").read().strip())
#: The three aurora fields, role colour and position, lifted from the greeter's
#: brand.py so the bloom behind the mark is the product's own light and not a
#: gradient invented next to it.
AURORA_DARK = json.dumps([["#553586", 18, 12], ["#014d64", 86, 30],
                          ["#404660", 55, 95]])
AURORA_LIGHT = json.dumps([["#e7deff", 18, 12], ["#baeaff", 86, 30],
                           ["#dae2fe", 55, 95]])


def tbicons_html():
    """A hidden library of the toolbar glyphs, cloned by the settings page."""
    cells = "".join(
        f'<span data-tbico="{i}">{ico(k, 16)}</span>'
        for i, k, _l, _on in TOOLBAR_CATALOG)
    return f'<div id="tbicons" hidden aria-hidden="true">{cells}</div>'


def toolbar_html():
    new_btn = (f'<div class="twrap" data-tb="new"><button class="tbtn wide" data-menu="m-new" '
               f'title="New">{ico("New.Item")}<span>New</span>{CHEVRON_DOWN}</button>'
               f'<div class="menu" id="m-new" hidden>{NEW_MENU}</div></div>')
    left = [new_btn, '<span class="tsep"></span>']
    for key, label, primary in TOOLBAR_LEFT[2:]:
        act = ""
        title = label
        live = {"Cut": "cut", "Copy": "copy", "Paste": "paste",
                "Rename": "rename", "Delete": "trash"}
        if label == "Properties":
            act = ' data-act="ctx-props"'
        elif label in live:
            act = f' data-act="{live[label]}" data-live'
            title = label + " (needs backend)"
        elif label in ("Share",):
            act = ' data-act="ctx-dis"'
            title = label + " (not in this export)"
        left.append(f'<button class="tbtn" data-tb="{label.lower()}" '
                    f'title="{title}"{act}>{ico(key)}</button>')
    right = []
    fly = {"SelectMode": ("m-sel", SELECT_MENU, "Selection options"),
           "Sorting": ("m-sort", SORT_MENU, "Sort"),
           "IconLayout.Grid.28": (None, LAYOUT_MENU, "Layout")}
    for key, has_flyout in TOOLBAR_RIGHT:
        px = 16
        if key == "Filter":
            right.append(f'<button class="tbtn" data-tb="filter" id="btn-filter" '
                         f'title="Filter" aria-pressed="false">{ico(key, px)}</button>')
            continue
        if key == "PanelRight":
            right.append(f'<button class="tbtn" data-tb="pane" id="btn-pane" '
                         f'title="Details pane" aria-pressed="false">{ico(key, px)}</button>')
            continue
        if key == "Shelf":
            right.append(f'<button class="tbtn" data-tb="shelf" id="btn-shelf" '
                         f'title="Shelf" aria-pressed="false">{ico(key, px)}</button>')
            continue
        mid, menu, title = fly[key]
        chev = CHEVRON_DOWN if has_flyout else ""
        if "IconLayout" in key:
            body = (f'<span class="lay lay-grid">{ico("IconLayout.Grid.28", px)}</span>'
                    f'<span class="lay lay-details" hidden>'
                    f'{ico("IconLayout.Details.28", px)}</span>'
                    f'<span class="lay lay-list" hidden>'
                    f'{ico("IconLayout.List.28", px)}</span>'
                    f'<span class="lay lay-cards" hidden>'
                    f'{ico("IconLayout.Tiles.28", px)}</span>'
                    f'<span class="lay lay-cols" hidden>'
                    f'{ico("IconLayout.Columns.28", px)}</span>')
            right.append(
                f'<div class="twrap" data-tb="layout">'
                f'<button id="btn-layout" title="{title}" '
                f'class="tbtn split">{body}{chev}</button>'
                f'<div class="menu" id="m-layout" hidden>{menu}</div></div>')
        else:
            tbid = "selectmode" if key == "SelectMode" else "sorting"
            right.append(
                f'<div class="twrap" data-tb="{tbid}">'
                f'<button title="{title}" '
                f'class="tbtn split">{ico(key, px)}{chev}</button>'
                f'<div class="menu" id="{mid}" hidden>{menu}</div></div>')
    hidden_attr = ' hidden' if IS_HOME else ''
    return (f'<div class="tbgroup" id="tb-context"{hidden_attr}>' + "".join(left) + '</div>'
            '<div class="tbgroup right">' + "".join(right) + '</div>')


# ------------------------------------------------------------- navigation ----
# A static export is still a real navigation model: one page per directory,
# linked. The point is that Cameron can click through the prototype instead of
# being sent screenshots of it.

PAGES_DIR = os.environ.get("AURADE_PROTO_PAGES", f"{ROOT}/site")
MAX_PAGES = int(os.environ.get("AURADE_PROTO_MAX_PAGES", "300"))
# How deep to crawl from the start directory and from home. Every other volume
# root gets exactly one page, so a sidebar click always lands somewhere real
# without the export walking all of /usr.
DEEP = int(os.environ.get("AURADE_PROTO_DEPTH", "2"))

PAGE_SET = set()
HREF_PREFIX = ""
PAGE_TOTAL = 0
# Dark is the default because the window was designed dark first. Light is a
# whole export rather than a runtime toggle, because a runtime toggle is UI that
# Files does not have and this is meant to be a copy of Files.
THEME = ""


def page_name(key):
    return "p_" + hashlib.sha1(key.encode()).hexdigest()[:12] + ".html"


def href_for(key):
    """A link, or None when there is no page. None is the honest answer: an
    anchor that goes nowhere reads as a bug."""
    if not key or key not in PAGE_SET:
        return None
    return HREF_PREFIX + page_name(key)


def _crumbs_for(path):
    """(label, key) from the deepest volume that contains this path, so the
    trail reads "Home > Documents" the way Files shows it and not as a raw
    POSIX path.

    Pinned folders are excluded from the choice of base. Desktop and Documents
    are volumes in the sidebar sense, but treating one as the start of the trail
    collapses "Home > Documents" to "Documents", which loses the trail and with
    it the only way back up short of the sidebar.
    """
    ap = os.path.abspath(path)
    roots = [v for v in VOLUMES
             if v.get("purpose") in (None, "home") and v["kind"] != "trash"]
    root = _place_for(localfs.as_file_key(ap), roots)
    vol = next((v for v in roots if v["root"] == root), None)
    base = localfs.key_path(root) if vol else "/"
    out = [(vol["label"] if vol else "/", localfs.as_file_key(base))]
    rel = os.path.relpath(ap, base)
    if rel != ".":
        acc = base
        for part in rel.split(os.sep):
            acc = os.path.join(acc, part)
            out.append((part, localfs.as_file_key(acc)))
    return out


def _crumb_kids(key, is_root=False):
    try:
        page = localfs.list_dir(localfs.key_path(key))
    except OSError:
        return ""
    rows = []
    if is_root:
        qa_heads = []
        for v in VOLUMES:
            if v.get("purpose") in ("desktop", "documents", "downloads",
                                     "music", "pictures", "videos"):
                href = href_for(v["root"])
                label = v["label"]
                if href:
                    qa_heads.append(f'<a class="mi" href="{href}">'
                                    f'<span class="mi-ic"></span>'
                                    f'<span class="mi-t">{label}</span></a>')
        if qa_heads:
            rows.append('<div class="mhead">Quick access</div>')
            rows.extend(qa_heads)
        drv_heads = []
        for v in VOLUMES:
            if v.get("purpose") in ("home", None) and v.get("kind") in ("system", "removable"):
                href = href_for(v["root"])
                label = v["label"]
                if href:
                    drv_heads.append(f'<a class="mi" href="{href}">'
                                     f'<span class="mi-ic"></span>'
                                     f'<span class="mi-t">{label}</span></a>')
        if drv_heads:
            rows.append('<div class="mhead">Drives</div>')
            rows.extend(drv_heads)
        if rows:
            rows.append('<div class="msep"></div>')
    for e in page["entries"]:
        if not e["isDirectory"]:
            continue
        name = e["name"].replace('"', "&quot;")
        href = href_for(e["key"])
        if href:
            rows.append(f'<a class="mi" href="{href}"><span class="mi-ic"></span>'
                        f'<span class="mi-t">{name}</span></a>')
        else:
            rows.append(f'<div class="mi dis" title="Not part of this export">'
                        f'<span class="mi-ic"></span><span class="mi-t">{name}</span></div>')
        if len(rows) >= 40:
            break
    return "".join(rows)


def _crumb_glyph():
    """The place icon for the volume the trail starts at."""
    if not CRUMBS:
        return ico("Omnibar.Path")
    root = CRUMBS[0][1]
    vol = next((v for v in VOLUMES if v["root"] == root), None)
    if vol is None:
        return ico("Omnibar.Path")
    return sidebar.glyph(sidebar._glyph_for(vol))


def crumbs_html():
    out = []
    for i, (label, key) in enumerate(CRUMBS):
        last = i == len(CRUMBS) - 1
        if i == 0 and label == "Home":
            inner = _crumb_glyph()
        else:
            inner = (_crumb_glyph() if i == 0 else "") + f"<span>{label}</span>"
        href = None if last else href_for(key)
        cls = "crumb last" if last else "crumb"
        try:
            datap = f' data-p="{localfs.key_path(key)}"' if key else ""
        except Exception:
            datap = ""
        if href:
            out.append(f'<a class="{cls}" href="{href}"{datap}>{inner}</a>')
        else:
            out.append(f'<span class="{cls}"{datap}>{inner}</span>')
        kids = _crumb_kids(key, is_root=(i == 0))
        if kids:
            out.append(f'<span class="cwrap"><button class="cchev" '
                       f'title="Show child folders">{CHEVRON_RIGHT}</button>'
                       f'<div class="menu" hidden>{kids}</div></span>')
        else:
            out.append(CHEVRON_RIGHT)
    return "".join(out)


def nav_html():
    up = href_for(CRUMBS[-2][1]) if len(CRUMBS) > 1 else None
    # Back and forward are real browser history, which is exactly what they mean
    # here. Whether they are live is only knowable at load, so the script greys
    # them rather than the generator guessing.
    out = [f'<button class="nbtn off" id="nav-back" title="Back">{ico("NavBack")}</button>',
           f'<button class="nbtn off" id="nav-fwd" title="Forward">{ico("NavForward")}</button>']
    if up:
        out.append(f'<a class="nbtn" href="{up}" title="Up">{ico("NavUp")}</a>')
    else:
        out.append(f'<span class="nbtn off" title="Up">{ico("NavUp")}</span>')
    out.append(f'<button class="nbtn" id="nav-refresh" title="Refresh">{ico("Refresh")}</button>')
    return "".join(out)


def discover(seeds):
    """Breadth first from (key, depth budget) seeds. Bounded, because a
    filesystem is not. A directory that never gets popped never gets a page and
    therefore never gets a link, which is the boundary being honest."""
    # The export's own output directories are skipped, or the prototype ends up
    # showing a folder full of its own pages.
    skip = {localfs.as_file_key(f"{ROOT}/site"),
            localfs.as_file_key(f"{ROOT}/site-light")}
    seen, order, queue = set(skip), [], list(seeds)
    # The deepest budget any route has offered a directory, updated when it is
    # queued and read when it is popped. Without this a volume seed sitting
    # ahead of the queue claims a folder at depth 0 and its children are never
    # crawled, so Downloads gets a page and nothing inside it does.
    best = {}
    for k, b in seeds:
        best[k] = max(best.get(k, -1), b)
    while queue and len(order) < MAX_PAGES:
        key, _queued = queue.pop(0)
        if key in seen:
            continue
        seen.add(key)
        order.append(key)
        budget = best.get(key, 0)
        if budget <= 0:
            continue
        try:
            page = localfs.list_dir(localfs.key_path(key))
        except OSError:
            continue  # renders as Location unavailable, and has no children
        for e in page["entries"]:
            if e["isDirectory"] and e["key"] not in seen:
                best[e["key"]] = max(best.get(e["key"], -1), budget - 1)
                queue.append((e["key"], budget - 1))
    return order


#: Files draws every one of its dialogs the same way: a ContentDialog with a
#: title, a body and up to three buttons along the bottom, in the order
#: Primary, Secondary, Close, with the primary one accented. There are fifteen
#: of them in src/Files.App/Dialogs and assets/files-dialogs.json is generated
#: from that folder, so a dialog built through here carries the reference's
#: own strings rather than a retyping of them.
def content_dialog(did, title, body, primary=None, secondary=None,
                   close=None):
    foot = []
    if primary:
        foot.append('<button class="btn-primary" data-dlg="primary">'
                    f'{primary}</button>')
    if secondary:
        foot.append('<button class="btn-dlg" data-dlg="secondary">'
                    f'{secondary}</button>')
    if close:
        foot.append(f'<button class="btn-dlg" data-dlg="close">{close}</button>')
    return (
        f'<div class="scrim mid" id="{did}" hidden>\n'
        f'  <div class="dlg cdlg" role="dialog" aria-modal="true"'
        f' aria-labelledby="{did}-t">\n'
        f'    <div class="cdlg-title" id="{did}-t">{title}</div>\n'
        f'    <div class="cdlg-body">\n{body}\n    </div>\n'
        f'    <div class="dlg-footer">{"".join(foot)}</div>\n'
        f'  </div>\n'
        f'</div>\n')


# The page's stylesheet and script live in css/ and js/, one file per
# section, in the order the names sort. They hold the text exactly as it is
# emitted, so braces and backslashes are what CSS and JavaScript expect and
# not the doubled forms an f-string needs. A value the builder computes is a
# marker in the file: /*@@NAME@@*/ in CSS, and in JavaScript __BUILD("NAME")
# where a value lands in code or @@NAME@@ where it lands inside a string.
# Each is valid in its own language, and all are replaced here.
def page_css(sidebar_css_tones):
    values = {"sidebar_css": sidebar.css(), "sidebar_css_tones": sidebar_css_tones}
    # The ship rules are last and are only for the ship build: they turn the
    # floating 1180 by 800 mockup into a page that fills whatever frame it
    # was given. The file is still a source, so BUILD_ID and the static
    # gates read it either way.
    files = [f for f in sources.css()
             if SHIP or os.path.basename(f) != "99-ship.css"]
    text = "".join(open(f).read() for f in files)
    return re.sub(r"/\*@@(\w+)@@\*/", lambda m: values[m.group(1)], text)


def page_js():
    # Three scopes. The 0x files are the layout switcher; the 1x and 2x files
    # are the window, one closure, because the menus, tabs, views, dialogs,
    # settings and commands read each other's names; the 3x files are the
    # live layer, one closure of its own, which reaches the window only
    # through window.__* bridges. The builder writes each closure's opening
    # and closing lines, so every file parses on its own.
    parts, scope = [], None
    for f in sources.js():
        leaf = os.path.basename(f)
        here = ("window" if "10" <= leaf[:2] < "30"
                else "live" if "30" <= leaf[:2] < "40" else None)
        if here != scope:
            if scope:
                parts.append("})();\n")
            if here:
                parts.append("(() => {\n")
            scope = here
        parts.append(open(f).read())
    if scope:
        parts.append("})();\n")
    g = globals()
    text = "".join(parts)
    text = re.sub(r'__BUILD\("(\w+)"\)', lambda m: g[m.group(1)], text)
    return re.sub(r"@@(\w+)@@", lambda m: g[m.group(1)], text)

def render_page():
  sidebar_css_tones = sidebar.TONES.strip()
  return f"""<meta charset="utf-8">{THEME}<title>AuraDE Files</title>
<style>
{page_css(sidebar_css_tones)}</style>

<div class="win" data-path="{'~' if SHIP else TARGET}">
  <div class="titlebar">
    <div class="tabs" id="tabstrip">
      <div class="tab active" data-tab-id="1"><span class="tico">{glyph_for({"purpose":"home","kind":"home"}, 16) if IS_HOME else ico("Folder", 16)}</span><span class="tname">{CRUMBS[-1][0]}</span><span class="x" title="Close tab (Ctrl+W)">{TAB_CLS}</span></div>
      <button class="newtab" id="btn-newtab" title="New tab (Ctrl+T)"><svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.25" stroke-linecap="round"><path d="M6 1.5v9M1.5 6h9"/></svg></button>
    </div>
    <div class="caption"><b>{CAP_MIN}</b><b>{CAP_MAX}</b><b>{CAP_CLS}</b></div>
  </div>

  <div class="addressbar">
    <div class="nav">{nav_html()}</div>
    <div class="omnibar" tabindex="0" id="omnibar">
      <div class="crumbs" id="crumbs">{crumbs_html()}</div>
      <input class="opath" id="opath" hidden placeholder="Enter a path"
             aria-label="Address" autocomplete="off" spellcheck="false">
      <input class="osearch" id="osearch" hidden placeholder="Search"
             aria-label="Search" autocomplete="off" spellcheck="false">
      <div class="omodes">
        <span class="osep"></span>
        <button class="omode" id="btn-palette" title="Command Palette">{ico("Omnibar.Commands")}</button>
        <span class="osep"></span>
        <button class="omode" id="btn-search" title="Search" aria-pressed="false">{ico("Omnibar.Search")}</button>
      </div>
    </div>
    <div class="scwrap"><button class="nbtn" id="btn-sc" title="Status Center" aria-pressed="false">{ico("StatusCenter")}</button>
      <div class="scfly" id="sc-fly" hidden>
        <div class="schead"><span>Status Center</span><span class="sp"></span></div>
        <div class="scempty">No file operations</div>
      </div>
    </div>
  </div>

  <div class="body">
    <aside class="sidebar"><div class="slist">
{sidebar_html()}
    </div>{sidebar_foot()}</aside>

    <div class="content">
      <div class="toolbar">{toolbar_html()}</div>
      <div class="frow" id="frow" hidden>
        <input id="finput" placeholder="Filter" aria-label="Filter"
               autocomplete="off" spellcheck="false">
      </div>
      <div class="frow" id="nrow" hidden>
        <input id="ninput" placeholder="Name" aria-label="Name"
               autocomplete="off" spellcheck="false">
      </div>
      <div class="filearea" id="filearea">
        {HOME_WIDGETS if IS_HOME else ""}
        {EMPTY_STATE if not IS_HOME else ""}
        <div class="grid" {"hidden" if IS_HOME else ""}>
{grid_html()}
        </div>
        <div class="rows" hidden>
{rows_html()}
        </div>
        <div class="list" hidden>
{list_html()}
        </div>
        <div class="cards" hidden>
{cards_html()}
        </div>
        <div class="columns" hidden>
{columns_html()}
        </div>
      </div>
      <!-- The settings page builds itself. This markup used to carry a whole
           second implementation, header, nav and nine panes, which the script
           below cleared and rebuilt on load: 11kB generated into every page and
           destroyed before anyone saw it. The host element is what render()
           needs; the contents are its business. -->
      <div class="settingspage" id="settings-page" hidden></div>
      <div class="status">
        <span id="st-count">{len(ITEMS)} items</span>
        <span class="div" id="st-div" hidden></span><span id="st-sel" hidden></span>
        <span class="div" id="st-sizediv" hidden></span><span id="st-size" hidden></span>
        <span class="spacer"></span>
        {git_html()}
      </div>
    </div>
    <aside class="shelf" id="shelf" hidden aria-label="Shelf">
      <div class="shelf-head">
        <div class="shelf-title">Shelf</div>
        <div class="shelf-div"></div>
      </div>
      <div class="shelf-empty" id="shelf-empty">
        {SHELF_ART}
        <p>Drag items here to keep them while you look around. Nothing is
        copied or moved until you ask for it.</p>
      </div>
      <div class="shelf-list" id="shelf-list" role="list"></div>
      <div class="shelf-foot" id="shelf-foot" hidden>
        <div class="shelf-div"></div>
        <button class="shelf-link" id="shelf-clear">Clear items</button>
        <div class="twrap" id="shelf-batch-wrap" hidden>
          <button class="shelf-link" id="shelf-batch">Batch action</button>
          <div class="menu shelf-menu" id="m-shelf" hidden>
            <div class="mi" data-shelf-op="copy"><span class="mi-ic">{ico("Copy")}</span><span class="mi-t">Copy</span></div>
            <div class="mi" data-shelf-op="cut"><span class="mi-ic">{ico("Cut")}</span><span class="mi-t">Cut</span></div>
            <div class="mi" data-shelf-op="delete"><span class="mi-ic">{ico("Delete")}</span><span class="mi-t">Delete</span></div>
          </div>
        </div>
      </div>
    </aside>
    <aside class="infopane" id="infopane" hidden aria-label="Details pane">
      <div class="itabs">
        <button class="itab on" data-itab="details">Details</button>
        <button class="itab" data-itab="preview">Preview</button>
      </div>
      <div class="ipane" id="ipane-details">{details_html()}</div>
      <div class="ipane" id="ipane-preview" hidden>{preview_html()}</div>
    </aside>
  </div>

</div>
<div class="ctx" id="ctx-file" hidden>{CTX_FILE}</div>
<div class="ctx" id="ctx-drive" hidden>{CTX_DRIVE}</div>
<div class="ctx" id="ctx-qa" hidden>{CTX_QA}</div>
<div class="ctx" id="ctx-recent" hidden>{CTX_RECENT}</div>
<div class="ctx" id="ctx-network" hidden>{CTX_NETWORK}</div>
<div class="ctx" id="ctx-filetags" hidden>{CTX_FILETAGS}</div>
{artlib_html()}{sb_glyphs_html()}
{tbicons_html()}
{templates_html()}<div class="ctx" id="ctx-bg" hidden>{CTX_BG}</div>
<div class="ctx" id="ctx-home" hidden>{CTX_HOME}</div>
<div class="ctx" id="ctx-side" hidden>{CTX_SIDE}</div>
<div class="ctx" id="ctx-side-bg" hidden>{CTX_SIDE_BG}</div>
<div class="ctx" id="ctx-tab" hidden>{CTX_TAB}</div>
<div class="ctx" id="hist-menu" hidden><a class="mi hist-tpl" hidden><span class="mi-ic"></span><span class="mi-t"></span></a></div>
<div class="scrim" id="palette" hidden>
  <div class="pal" role="dialog" aria-label="Command palette">
    <input id="pal-input" placeholder="Type a command" aria-label="Type a command"
           autocomplete="off" spellcheck="false">
    <div class="plist" id="pal-list">{palette_html()}</div>
  </div>
</div>
<div class="scrim" id="props" hidden>
  <div class="dlg win-props" role="dialog" aria-modal="true" aria-label="Properties">
    <div class="dlg-titlebar">
      <button class="dlg-back" id="props-back" title="Back" disabled>{ico("NavBack", 16)}</button>
      <div class="dlg-title" id="props-title">Properties</div>
      <button class="dlg-close" id="props-close" title="Close">{TAB_CLS}</button>
    </div>
    <div class="dlg-body-wrap">
      <div class="dlg-nav">
        <button class="ptab on" data-ptab="general">{ico("Properties", 16)}<span>General</span></button>
        <button class="ptab" data-ptab="signatures" hidden>{ico("Properties.Signatures", 16)}<span>Signatures</span></button>
        <button class="ptab" data-ptab="security">{ico("Settings.General.Privacy", 16)}<span>Security</span></button>
        <button class="ptab" data-ptab="hashes">{ico("Settings.General.Edit", 16)}<span>Hashes</span></button>
        <button class="ptab" data-ptab="shortcut" hidden>{ico("Properties.Shortcut", 16)}<span>Shortcut</span></button>
        <button class="ptab" data-ptab="details">{ico("IconLayout.Details.28", 16)}<span>Details</span></button>
        <button class="ptab" data-ptab="customization" hidden>{ico("Properties.CustomizeFolder", 16)}<span>Customization</span></button>
      </div>
      <div class="dlg-main">
        <div class="ptab-content" id="ptab-general">
          <div id="pgen-file">
            <div class="pheader-row">
              <div class="picon pcard" id="props-icon">
                <span class="picon-art" id="props-icon-art">{art_svg("folder", True)}</span>
                <div class="twrap pcover-wrap" id="props-cover-wrap" hidden>
                  <button class="pcover-btn" id="props-cover-btn" type="button" title="More options..." aria-label="More options..."><span class="pcover-dot">{ico("More", 12)}</span></button>
                  <div class="menu" id="m-cover" hidden>
                    {mi("Settings.General.Edit", "Change album cover", 'data-cover="change"')}
                    {mi("Delete", "Remove album cover", 'data-cover="remove"')}
                  </div>
                </div>
              </div>
              <input class="pname-input" id="props-name-input" value="{CRUMBS[-1][0]}" aria-label="Item Name" placeholder="Item Name">
              <span class="pv" data-gk="Name" hidden>{CRUMBS[-1][0]}</span>
            </div>
            <div class="psep"></div>
            <details class="pmore" id="pgen-more" open>
              <summary class="pmore-h">More details</summary>
            <div class="prows">
              <div class="prow"><span class="pk">Type:</span><span class="pv" data-gk="Type">File folder</span></div>
              <div class="prow" id="prow-openswith" hidden><span class="pk">Opens with:</span><span class="pv">Text Editor <button class="btn-sm" id="btn-openswith">Change...</button></span></div>
              <div class="psep"></div>
              <div class="prow"><span class="pk">Location:</span><span class="pv" data-gk="Location">{'~' if SHIP else HOME_DIR}</span></div>
              <div class="prow"><span class="pk">Size:</span><span class="pv" data-gk="Size">4.0 KB</span></div>
              <div class="prow"><span class="pk">Size on disk:</span><span class="pv" data-gk="Size on disk">4.0 KB</span></div>
              <div class="prow" id="prow-uncompressed" hidden><span class="pk">Uncompressed size:</span><span class="pv" data-gk="Uncompressed size"></span></div>
              <div class="prow" id="prow-contains"><span class="pk">Contains:</span><span class="pv" data-gk="Contains"></span></div>
              <div class="psep"></div>
              <div class="prow"><span class="pk">Created:</span><span class="pv" data-gk="Created"></span></div>
              <div class="prow"><span class="pk">Modified:</span><span class="pv" data-gk="Modified"></span></div>
              <div class="prow"><span class="pk">Accessed:</span><span class="pv" data-gk="Accessed"></span></div>
              <div class="psep"></div>
              <div class="prow"><span class="pk">Attributes:</span>
                <label class="pcheck"><input type="checkbox" id="prop-readonly"> Read-only</label>
                <label class="pcheck"><input type="checkbox" id="prop-hidden"> Hidden</label>
              </div>
            </div>
            </details>
          </div>
          <div id="pgen-drive" hidden>
            <div class="pheader-row pdrive-header">
              <div class="picon pdrive-icon" id="props-drive-icon">{glyph_for({"purpose":"drive","kind":"system"}, 48)}</div>
              <div class="pdrive-header-info">
                <input class="pname-input" id="props-drive-label" value="System (/)" aria-label="Drive Label">
                <div class="pdrive-header-sub"><span id="pdrive-type">Local Fixed Disk</span> &bull; <span id="pdrive-fs">ext4</span></div>
              </div>
            </div>
            <div class="psep"></div>
            <div class="pdisk-card">
              <div class="pdisk-ring-wrap">
                <svg class="pdisk-ring" width="64" height="64" viewBox="0 0 64 64" aria-hidden="true">
                  <circle class="pdisk-ring-bg" cx="32" cy="32" r="26" stroke-width="6" fill="none" />
                  <circle class="pdisk-ring-fill" id="pdrive-ring-fill" cx="32" cy="32" r="26" stroke-width="6" fill="none"
                          stroke-dasharray="163.36" stroke-dashoffset="122.52" stroke-linecap="round"
                          transform="rotate(-90 32 32)" />
                  <text class="pdisk-ring-txt" id="pdrive-pct-txt" x="32" y="32" text-anchor="middle" dominant-baseline="central">25%</text>
                </svg>
              </div>
              <div class="pdisk-info">
                <div class="pdisk-row">
                  <div class="pdisk-row-left">
                    <span class="pdisk-dot pdisk-dot-used"></span>
                    <span class="pdisk-label">Used space</span>
                  </div>
                  <div class="pdisk-row-right">
                    <span class="pdisk-gb" id="pdrive-used-gb">240.6 GB</span>
                    <span class="pdisk-bytes" id="pdrive-used">258,358,911,488 bytes</span>
                  </div>
                </div>
                <div class="pdisk-row">
                  <div class="pdisk-row-left">
                    <span class="pdisk-dot pdisk-dot-free"></span>
                    <span class="pdisk-label">Free space</span>
                  </div>
                  <div class="pdisk-row-right">
                    <span class="pdisk-gb" id="pdrive-free-gb">766.2 GB</span>
                    <span class="pdisk-bytes" id="pdrive-free">822,742,265,344 bytes</span>
                  </div>
                </div>
                <div class="pdisk-sep"></div>
                <div class="pdisk-row pdisk-row-cap">
                  <div class="pdisk-row-left">
                    <span class="pdisk-label pdisk-label-cap">Capacity</span>
                  </div>
                  <div class="pdisk-row-right">
                    <span class="pdisk-gb" id="pdrive-cap-gb">1006.9 GB</span>
                    <span class="pdisk-bytes" id="pdrive-cap">1,081,101,176,832 bytes</span>
                  </div>
                </div>
              </div>
            </div>
            <div class="pdrive-actions-list">
              <button type="button" class="pdrive-action-card" id="btn-drive-cleanup">
                <div class="pdrive-action-icon">{ico("Settings", 20)}</div>
                <div class="pdrive-action-text">
                  <div class="pdrive-action-title">Cleanup your drive contents</div>
                  <div class="pdrive-action-desc">Free up disk space by deleting temporary files</div>
                </div>
                <svg class="pdrive-action-chev" width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4.5 2.5L8 6L4.5 9.5"/></svg>
              </button>
              <button type="button" class="pdrive-action-card" id="btn-drive-format">
                <div class="pdrive-action-icon">{ico("Settings.General.Edit", 20)}</div>
                <div class="pdrive-action-text">
                  <div class="pdrive-action-title">Format drive</div>
                  <div class="pdrive-action-desc">Format this drive and configure file system</div>
                </div>
                <svg class="pdrive-action-chev" width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4.5 2.5L8 6L4.5 9.5"/></svg>
              </button>
            </div>
          </div>
        </div>
        <div class="ptab-content" id="ptab-details" hidden>
          <div class="pdet-loading" id="pdet-loading">Loading...</div>
          {props_details_html()}
          <div class="pdet-warn">Some properties may contain personal information.</div>
        </div>
        <div class="ptab-content" id="ptab-hashes" hidden>
          <div class="hash-box">
            <div class="hrowline">
              <input id="hash-input" placeholder="Enter a hash to compare" aria-label="Enter a hash to compare" autocomplete="off" spellcheck="false">
              <button class="hcopy" id="hash-compare">Compare</button>
              <button class="hcopy" id="hash-compare-file">Compare a file</button>
            </div>
            <div class="hmatch" id="hash-result" hidden></div>
          </div>
          <div class="hrow hrow-h"><span class="k">Algorithm</span><span class="v">Hash value</span><span></span></div>
          <div class="hrow"><span class="k">CRC32</span><span class="v" id="h-crc32"></span><button class="hcopy" data-copy="h-crc32">Copy</button></div>
          <div class="hrow"><span class="k">MD5</span><span class="v" id="h-md5"></span><button class="hcopy" data-copy="h-md5">Copy</button></div>
          <div class="hrow"><span class="k">SHA-1</span><span class="v" id="h-sha1"></span><button class="hcopy" data-copy="h-sha1">Copy</button></div>
          <div class="hrow"><span class="k">SHA-256</span><span class="v" id="h-sha256"></span><button class="hcopy" data-copy="h-sha256">Copy</button></div>
          <div class="hrow"><span class="k">SHA-384</span><span class="v" id="h-sha384"></span><button class="hcopy" data-copy="h-sha384">Copy</button></div>
          <div class="hrow"><span class="k">SHA-512</span><span class="v" id="h-sha512"></span><button class="hcopy" data-copy="h-sha512">Copy</button></div>
          <div class="hrow hrow-calc" id="h-calc" hidden><span class="k">Calculating...</span><span class="v"></span><span></span></div>
          <div class="hnote" id="h-note"></div>
        </div>
        <div class="ptab-content" id="ptab-signatures" hidden>
          <div class="prows">
            <div class="prow"><span class="pk">Status:</span>
              <span class="pv" id="sig-status"></span></div>
            <div class="prow"><span class="pk">Signed by:</span>
              <span class="pv" id="sig-signer"></span></div>
            <div class="prow"><span class="pk">Key:</span>
              <span class="pv" id="sig-key"></span></div>
            <div class="prow"><span class="pk">Signature:</span>
              <span class="pv" id="sig-file"></span></div>
          </div>
          <div class="sig-none" id="sig-none" hidden>No signature was found.</div>
          <div class="psep"></div>
          <div class="lnk-note" id="sig-note" hidden></div>
          <div class="sig-h" id="sig-detail-h" hidden>Details</div>
          <div class="sig-detail" id="sig-detail"></div>
        </div>
        <div class="ptab-content" id="ptab-shortcut" hidden>
          <div class="prows">
            <div class="prow"><span class="pk">Shortcut type:</span>
              <span class="pv" id="lnk-kind"></span></div>
            <div class="prow"><span class="pk">Destination:</span>
              <span class="pv" id="lnk-target"></span></div>
            <div class="prow"><span class="pk">Arguments:</span>
              <span class="pv" id="lnk-args"></span></div>
            <div class="prow"><span class="pk">Start in:</span>
              <span class="pv" id="lnk-wd"></span></div>
            <div class="prow"><span class="pk">Resolves to:</span>
              <span class="pv" id="lnk-resolved"></span></div>
          </div>
          <div class="psep"></div>
          <div class="lnk-note" id="lnk-note" hidden></div>
          <div class="pbtns">
            <button class="btn-sm" id="lnk-open">Open file location</button>
          </div>
        </div>
        <div class="ptab-content" id="ptab-customization" hidden>
          <div class="cust-card">
            <div class="cust-head">
              <span class="cust-title">Choose a custom folder icon</span>
              <button class="btn-sm" id="cust-restore" disabled>Restore default</button>
            </div>
            <div class="psep"></div>
            <div class="cust-row">
              <input class="cust-path" id="cust-path" readonly aria-label="Icon in use" value="Default icon">
              <button class="btn-sm" id="cust-browse">Browse</button>
            </div>
            <div class="cust-file-row" id="cust-file-row" hidden>
              <input class="cust-file" id="cust-file" placeholder="/path/to/icon.png" aria-label="Path of an image file">
              <button class="btn-sm" id="cust-file-apply">Apply</button>
            </div>
            <div class="cust-note" id="cust-note" hidden></div>
            <div class="cust-grid" id="cust-grid">
{CUST_GRID}
            </div>
          </div>
        </div>
        <!-- The Security tab. Files draws Windows access control lists here;
             this platform has POSIX mode bits and POSIX ACLs, which is the
             same three by three grid drawn differently, so the shape is the
             reference's and the contents are this machine's. It used to list
             SYSTEM, Administrators and Users with every box ticked, about a
             file it had never looked at. -->
        <div class="ptab-content" id="ptab-security" hidden>
          <div class="prows">
            <div class="prow"><span class="pk">Owner:</span>
              <span class="pv" id="sec-owner"></span>
              <button class="btn-sm" id="sec-change-owner" disabled
                title="Changing the owner needs a privilege this app does not ask for">Change</button></div>
          </div>
          <div class="psep"></div>
          <div class="sec-desc">Group or user names:</div>
          <div class="sec-users-box" id="sec-users"></div>
          <div class="sec-empty" id="sec-empty" hidden>No groups or users have permission to access this object. However, the owner of this object can assign permissions.</div>
          <div class="sec-desc">Permissions for <span id="sec-who">the owner</span>:</div>
          <div class="sec-perms-table" id="sec-perms">
            <div class="sec-perm-h"><span>Permissions</span><span>Allow</span><span>Deny</span></div>
            <div class="sec-perm-row" data-perm="full"><span>Full control</span><input type="checkbox" aria-label="Full control allow"><input type="checkbox" disabled aria-label="Full control deny" title="POSIX mode bits grant; they do not deny"></div>
            <div class="sec-perm-row" data-perm="modify"><span>Modify</span><input type="checkbox" aria-label="Modify allow"><input type="checkbox" disabled aria-label="Modify deny" title="POSIX mode bits grant; they do not deny"></div>
            <div class="sec-perm-row" data-perm="readexec"><span>Read and execute</span><input type="checkbox" aria-label="Read and execute allow"><input type="checkbox" disabled aria-label="Read and execute deny" title="POSIX mode bits grant; they do not deny"></div>
            <div class="sec-perm-row" data-perm="list" hidden><span>List directory contents</span><input type="checkbox" aria-label="List directory contents allow"><input type="checkbox" disabled aria-label="List directory contents deny" title="POSIX mode bits grant; they do not deny"></div>
            <div class="sec-perm-row" data-perm="read"><span>Read</span><input type="checkbox" aria-label="Read allow"><input type="checkbox" disabled aria-label="Read deny" title="POSIX mode bits grant; they do not deny"></div>
            <div class="sec-perm-row" data-perm="write"><span>Write</span><input type="checkbox" aria-label="Write allow"><input type="checkbox" disabled aria-label="Write deny" title="POSIX mode bits grant; they do not deny"></div>
          </div>
          <div class="pbtns">
            <button class="btn-sm" id="sec-advanced">Advanced permissions</button>
            <span class="sec-mode" id="sec-mode"></span>
          </div>
          <div class="sec-note" id="sec-note" hidden></div>
          <div class="sec-acl" id="sec-acl" hidden></div>
        </div>
      </div>
    </div>
    <div class="dlg-footer">
      <button class="btn-primary" id="props-ok">OK</button>
      <button class="btn-dlg" id="props-cancel">Cancel</button>
      <button class="btn-dlg" id="props-apply">Apply</button>
    </div>
  </div>
</div>
<div class="scrim" id="storage-sense" hidden>
  <div class="dlg win-storage" role="dialog" aria-modal="true" aria-label="Storage Sense">
    <div class="dlg-titlebar">
      <div class="dlg-title">Storage - System (/)</div>
      <button class="dlg-close" id="storage-close" title="Close">{TAB_CLS}</button>
    </div>
    <div class="dlg-content-pad">
      <div class="storage-summary">
        <div class="storage-head">
          <div class="storage-title">Local Fixed Disk (/)</div>
          <div class="storage-space">748 GB free of 1006 GB</div>
        </div>
        <div class="storage-multi-bar">
          <div class="sm-part sm-sys" style="width:14%" title="System: 14.2 GB"></div>
          <div class="sm-part sm-apps" style="width:9%" title="Apps: 8.8 GB"></div>
          <div class="sm-part sm-temp" style="width:2%" title="Temp: 2.1 GB"></div>
          <div class="sm-part sm-docs" style="width:4%" title="Documents: 45.3 GB"></div>
        </div>
      </div>
      <div class="storage-list">
        <div class="storage-cat"><span class="sc-dot sm-sys"></span><span class="sc-name">System & OS</span><span class="sc-val">14.2 GB</span></div>
        <div class="storage-cat"><span class="sc-dot sm-apps"></span><span class="sc-name">Installed Apps & Packages</span><span class="sc-val">8.8 GB</span></div>
        <div class="storage-cat"><span class="sc-dot sm-temp"></span><span class="sc-name">Temporary & Cached Files</span><span class="sc-val" id="sc-temp-val">2.1 GB</span></div>
        <div class="storage-cat"><span class="sc-dot sm-docs"></span><span class="sc-name">User Documents & Media</span><span class="sc-val">45.3 GB</span></div>
      </div>
      <div class="storage-actions">
        <button class="btn-primary" id="btn-storage-clean">Clean now (Free up 2.1 GB)</button>
        <span class="storage-clean-status" id="storage-status" hidden>Temporary files cleaned successfully.</span>
      </div>
    </div>
    <div class="dlg-footer">
      <button class="btn-primary" id="storage-ok">Close</button>
    </div>
  </div>
</div>
<div class="scrim" id="format-drive" hidden>
  <div class="dlg win-format" role="dialog" aria-modal="true" aria-label="Format Drive">
    <div class="dlg-titlebar">
      <div class="dlg-title" id="format-title">Format Drive</div>
      <button class="dlg-close" id="format-close" title="Close">{TAB_CLS}</button>
    </div>
    <div class="dlg-content-pad">
      <div class="fmt-field">
        <label>Capacity:</label>
        <div class="fmt-val" id="format-cap">1,081,101,176,832 bytes (1.00 TB)</div>
      </div>
      <div class="fmt-field">
        <label for="fmt-fs">File system:</label>
        <select class="fmt-select" id="fmt-fs">
          <option value="ext4" selected>ext4 (Default)</option>
          <option value="ntfs">NTFS</option>
          <option value="fat32">FAT32</option>
          <option value="exfat">exFAT</option>
        </select>
      </div>
      <div class="fmt-field">
        <label for="fmt-cluster">Allocation unit size:</label>
        <select class="fmt-select" id="fmt-cluster">
          <option value="4096" selected>4096 bytes</option>
          <option value="8192">8192 bytes</option>
          <option value="16384">16 kilobytes</option>
        </select>
      </div>
      <div class="fmt-field">
        <label for="fmt-label">Volume label:</label>
        <input class="fmt-input" id="fmt-label" value="AuraStorage">
      </div>
      <div class="fmt-options">
        <label class="pcheck"><input type="checkbox" id="fmt-quick" checked> Quick Format</label>
      </div>
      <div class="fmt-progress" id="fmt-prog-wrap" hidden>
        <div class="fmt-pbar"><div class="fmt-pfill" id="fmt-pfill"></div></div>
        <div class="fmt-status" id="fmt-status">Formatting...</div>
      </div>
    </div>
    <div class="dlg-footer">
      <button class="btn-primary" id="btn-format-start">Start</button>
      <button class="btn-dlg" id="btn-format-cancel">Close</button>
    </div>
  </div>
</div>
<div class="scrim" id="namedlg" hidden>
  <div class="dlg ndlg" role="dialog" aria-modal="true" aria-label="Name">
    <div class="dlg-head"><span id="namedlg-title">Rename</span><span class="sp"></span>
      <button class="nbtn" id="namedlg-x" title="Close">{TAB_CLS}</button></div>
    <div class="ndlg-body">
      <input id="namedlg-input" aria-label="Name" autocomplete="off" spellcheck="false">
      <div class="ndlg-err" id="namedlg-err" hidden></div>
    </div>
    <div class="dlg-footer">
      <button class="btn-primary" id="namedlg-ok">Rename</button>
      <button class="btn-dlg" id="namedlg-cancel">Cancel</button>
    </div>
  </div>
</div>
{content_dialog(
    "dlg-dynamic", "Files",
    '      <div class="cdlg-note" id="dlg-dynamic-text"></div>',
    primary="Yes", close="Cancel")}
{content_dialog(
    "dlg-additem", "Create a new item",
    '      <div class="cdlg-note">Choose a type for this new item below</div>\n'
    '      <div class="cdlg-list" id="additem-list">\n'
    f'        <button class="cdlg-item" data-pick="folder">{ico("New.Folder", 20)}'
    '<span>Folder<span class="cdlg-sub">An empty folder</span></span></button>\n'
    f'        <button class="cdlg-item" data-pick="file">{ico("New.File", 20)}'
    '<span>File<span class="cdlg-sub">An empty file</span></span></button>\n'
    f'        <button class="cdlg-item" data-pick="shortcut">{ico("Shortcut", 20)}'
    '<span>Shortcut<span class="cdlg-sub">A link to another item</span>'
    '</span></button>\n'
    '      </div>',
    close="Cancel")}
{content_dialog(
    "dlg-createshortcut", "Create a new shortcut",
    '      <div class="cdlg-note">Create shortcuts to local or network'
    ' programs, files, folders, computers or Internet addresses.</div>\n'
    '      <div class="cdlg-card col">\n'
    '        <div class="cdlg-row">\n'
    '          <input type="text" id="cs-path" class="cdlg-grow"'
    ' placeholder="Enter the location of the item:"'
    ' aria-label="Enter the location of the item:"'
    ' autocomplete="off" spellcheck="false">\n'
    '          <button class="btn-dlg browse" id="cs-browse">Browse</button>\n'
    '        </div>\n'
    '        <div class="cdlg-row">\n'
    '          <input type="text" id="cs-name" class="cdlg-grow"'
    ' placeholder="Enter an item name" aria-label="Enter an item name"'
    ' autocomplete="off" spellcheck="false">\n'
    '        </div>\n'
    '      </div>\n'
    '      <div class="cdlg-err" id="cs-err" hidden></div>',
    primary="Create", close="Cancel")}
{content_dialog(
    "dlg-createarchive", "Create archive",
    '      <div class="cdlg-card">\n'
    '        <span class="cdlg-lbl">Name</span>\n'
    '        <input type="text" id="arc-name" class="cdlg-grow"'
    ' placeholder="Enter a name" aria-label="Name"'
    ' autocomplete="off" spellcheck="false">\n'
    '      </div>\n'
    '      <div class="cdlg-card col">\n'
    '        <div class="cdlg-row"><span class="cdlg-lbl">Format</span>\n'
    '          <select id="arc-format" aria-label="Format">'
    '<option value="zip">zip</option><option value="7z">7z</option><option value="tar.gz">tar.gz</option><option value="tar.xz">tar.xz</option><option value="tar.zst">tar.zst</option><option value="tar">tar</option></select></div>\n'
    '        <div class="cdlg-row">'
    '<span class="cdlg-lbl">Compression level</span>\n'
    '          <select id="arc-level" aria-label="Compression level">'
    '<option value="ultra">Ultra</option><option value="high">High</option><option value="normal" selected>Normal</option><option value="low">Low</option><option value="fast">Fast</option><option value="store">Store</option></select></div>\n'
    '        <div class="cdlg-row">'
    '<span class="cdlg-lbl">Splitting size</span>\n'
    '          <select id="arc-split" aria-label="Splitting size">'
    '<option value="none">Do not split</option></select></div>\n'
    '        <div class="cdlg-row">'
    '<span class="cdlg-lbl">Dictionary size</span>\n'
    '          <select id="arc-dict" aria-label="Dictionary size">'
    '<option value="">Auto</option></select></div>\n'
    '        <div class="cdlg-row">'
    '<span class="cdlg-lbl">Word size</span>\n'
    '          <select id="arc-word" aria-label="Word size">'
    '<option value="">Auto</option></select></div>\n'
    '        <div class="cdlg-row">'
    '<span class="cdlg-lbl">CPU threads</span>\n'
    '          <input type="number" id="arc-threads" class="cdlg-num"'
    ' aria-label="CPU threads" min="1" max="1" value="1"></div>\n'
    '      </div>\n'
    '      <details class="cdlg-exp" id="arc-encryption">\n'
    '        <summary>Encryption</summary>\n'
    '        <div class="cdlg-row"><span class="cdlg-lbl">Password</span>\n'
    '          <input type="password" id="arc-password"'
    ' placeholder="Password" aria-label="Password"'
    ' autocomplete="new-password"></div>\n'
    '      </details>\n'
    '      <div class="cdlg-card col" id="arc-memory" hidden>\n'
    '        <div class="cdlg-note" id="arc-mem-est"></div>\n'
    '        <div class="cdlg-note" id="arc-mem-avail"></div>\n'
    '      </div>\n'
    '      <div class="cdlg-note" id="arc-note"></div>',
    primary="Create", close="Cancel")}
{content_dialog(
    "dlg-extract", "Extract archive",
    '      <div class="cdlg-card col">\n'
    '        <div class="cdlg-row"><span class="cdlg-lbl">Path</span></div>\n'
    '        <div class="cdlg-row">\n'
    '          <input type="text" id="ex-path" class="cdlg-grow"'
    ' aria-label="Path" autocomplete="off" spellcheck="false">\n'
    '          <button class="btn-dlg browse" id="ex-browse">Browse</button>\n'
    '        </div>\n'
    '      </div>\n'
    '      <div class="cdlg-card">\n'
    '        <span class="cdlg-lbl">Archive password</span>\n'
    '        <input type="password" id="ex-password"'
    ' placeholder="Password" aria-label="Password"'
    ' autocomplete="new-password">\n'
    '      </div>\n'
    '      <div class="cdlg-card" id="ex-encoding-card" hidden>\n'
    '        <span class="cdlg-lbl">Encoding</span>\n'
    '        <select id="ex-encoding" aria-label="Encoding">'
    '<option value="">Default</option></select>\n'
    '      </div>\n'
    '      <label class="cdlg-row pcheck">'
    '<input type="checkbox" id="ex-open">'
    '<span class="cdlg-lbl">Open destination folder when complete</span>'
    '</label>\n'
    '      <div class="cdlg-note" id="ex-note"></div>',
    primary="Extract", secondary="Cancel")}
{content_dialog(
    "dlg-fsop", "Files",
    '      <div class="cdlg-note" id="fsop-what"></div>\n'
    '      <div class="cdlg-list" id="fsop-rows"></div>\n'
    '      <div class="cdlg-row" id="fsop-all-row">\n'
    '        <span class="cdlg-lbl">'
    'Apply this action to all conflicting items</span>\n'
    '        <select id="fsop-all" aria-label='
    '"Apply this action to all conflicting items">'
    '<option value="">Custom</option>'
    '<option value="keep-both">Generate new name</option>'
    '<option value="replace">Replace existing</option>'
    '<option value="skip">Skip</option></select>\n'
    '      </div>\n'
    '      <label class="cdlg-row pcheck" id="fsop-perm-row" hidden>'
    '<input type="checkbox" id="fsop-permanent">'
    '<span class="cdlg-lbl">Permanently delete</span></label>',
    primary="Continue", close="Cancel")}
{content_dialog(
    "dlg-compress-skipped", "Some items can&#39;t be compressed",
    '      <div class="cdlg-names" id="skipped-names"></div>',
    primary="Skip", close="Cancel")}
{content_dialog(
    "dlg-toolarge",
    "The following items are too large to be copied to this drive",
    '      <div class="cdlg-names" id="toolarge-names"></div>',
    primary="OK")}
{content_dialog(
    "dlg-reorder", "Reorder sidebar items",
    '      <div class="cdlg-list" id="reorder-rows"></div>',
    primary="Save", close="Cancel")}
{content_dialog(
    "dlg-addbranch", "Create branch",
    '      <div class="cdlg-card">\n'
    '        <span class="cdlg-lbl">Name</span>\n'
    '        <input type="text" id="ab-name" class="cdlg-grow"'
    ' placeholder="Enter a name" aria-label="Name"'
    ' autocomplete="off" spellcheck="false">\n'
    '      </div>\n'
    '      <div class="cdlg-card">\n'
    '        <span class="cdlg-lbl">Based on</span>\n'
    '        <select id="ab-from" aria-label="Based on" data-fills="1"></select>\n'
    '      </div>\n'
    '      <label class="cdlg-row pcheck">'
    '<input type="checkbox" id="ab-switch" checked>'
    '<span class="cdlg-lbl">Switch to new branch</span></label>\n'
    '      <div class="cdlg-err" id="ab-err" hidden></div>',
    primary="Create", close="Cancel")}
{content_dialog(
    "dlg-clonerepo", "Clone repo",
    '      <div class="cdlg-card">\n'
    '        <span class="cdlg-lbl">Repository URL</span>\n'
    '        <input type="text" id="cr-url" class="cdlg-grow"'
    ' aria-label="Repository URL" autocomplete="off" spellcheck="false">\n'
    '      </div>\n'
    '      <div class="cdlg-err" id="cr-err" hidden></div>',
    primary="Clone", close="Cancel")}
{content_dialog(
    "dlg-picker", "Select a folder",
    '      <div class="cdlg-row">\n'
    '        <button class="btn-dlg" id="pk-up" title="Up">Up</button>\n'
    '        <input type="text" id="pk-path" class="cdlg-grow"'
    ' aria-label="Path" autocomplete="off" spellcheck="false">\n'
    '      </div>\n'
    '      <div class="cdlg-list" id="pk-list"></div>\n'
    '      <div class="cdlg-card" id="pk-filter-card" hidden>\n'
    '        <span class="cdlg-lbl">File type</span>\n'
    '        <select id="pk-filter" aria-label="File type" data-fills="1"></select>\n'
    '      </div>',
    primary="Select", close="Cancel")}
{content_dialog(
    "dlg-bulkrename", "Bulk rename",
    '      <div class="cdlg-card">\n'
    '        <span class="cdlg-lbl">Name</span>\n'
    '        <input type="text" id="br-name" class="cdlg-grow"'
    ' placeholder="Enter a name" aria-label="Name"'
    ' autocomplete="off" spellcheck="false">\n'
    '      </div>\n'
    '      <div class="cdlg-err" id="br-err" hidden></div>',
    primary="Rename", close="Cancel")}
<script>
{page_js()}</script>
"""

def build_site(write_v3=True):
    global PAGE_SET, HREF_PREFIX, PAGE_TOTAL, CATALOG_JSON
    start = localfs.as_file_key(os.path.abspath(TARGET_START))
    home = localfs.as_file_key(HOME_DIR)
    seeds = [(start, DEEP), (home, DEEP)]
    seeds += [(v["root"], 0) for v in VOLUMES]
    order = discover(seeds)
    PAGE_SET = set(order)
    PAGE_TOTAL = len(order)
    HREF_PREFIX = ""

    catalog = {}
    for key in order:
        p = localfs.key_path(key)
        try:
            pg = localfs.list_dir(p)
            mt = localfs.metadata([e['key'] for e in pg['entries']])
            itms = rows_from_port(pg, mt)
            crmbs = _crumbs_for(p)
            is_h = (os.path.abspath(p) == HOME_DIR)
            catalog[p] = {
                'path': p,
                'name': crmbs[-1][0] if crmbs else 'Folder',
                'isHome': is_h,
                'crumbs': crmbs,
                'href': href_for(key) or '',
                'items': [
                    {'name': x[0], 'art': x[1], 'kind': x[2], 'size': x[4],
                     'when': x[3], 'path': localfs.key_path(x[6]),
                     'ms': x[7], 'bytes': x[8], 'href': href_for(x[5]) or '',
                     'th': _thumb_for(x[6], x[8], x[0])}
                    for x in itms
                ]
            }
        except Exception:
            pass
    CATALOG_JSON = json.dumps(catalog)

    os.makedirs(PAGES_DIR, exist_ok=True)
    written = {"index.html"}
    for key in order:
        set_target(localfs.key_path(key))
        written.add(page_name(key))
        with open(os.path.join(PAGES_DIR, page_name(key)), "w") as fh:
            fh.write(render_page())
    # One obvious door into the export.
    set_target(localfs.key_path(start))
    with open(os.path.join(PAGES_DIR, "index.html"), "w") as fh:
        fh.write(render_page())
    #: A page named after a folder that is no longer in the export stays on
    #: disk for ever and is served like any other. One had been there since
    #: September the sixth, built by code four passes old, and a check that
    #: picked a page out of this directory measured it.
    for stale in sorted(os.listdir(PAGES_DIR)):
        if stale.endswith(".html") and stale not in written:
            os.remove(os.path.join(PAGES_DIR, stale))
            print(f"removed {stale}, which is not in the export any more")

    # v3.html stays where it has always been so the screenshot loop keeps
    # working, and its links reach into site/ so it is not a dead end. Only the
    # first pass writes it, or the light pass would silently retheme it.
    html = ""
    if write_v3:
        HREF_PREFIX = os.path.relpath(PAGES_DIR, ROOT) + "/"
        set_target(localfs.key_path(start))
        html = render_page()
        with open(f"{ROOT}/v3.html", "w") as fh:
            fh.write(html)
    return order, html


LIGHT = '<script>document.documentElement.dataset.theme="light"</script>'

def build_ship(out):
    """files.html and files.js under `out`, for the SWA. See SHIP above."""
    global PAGE_SET, HREF_PREFIX, PAGE_TOTAL, CATALOG_JSON
    PAGE_SET, HREF_PREFIX, PAGE_TOTAL, CATALOG_JSON = set(), "", 0, "{}"
    set_target(HOME_DIR)
    html = render_page()
    # The build home is a temporary folder that exists nowhere else, and the
    # trail, the Home card and the info pane name it as the start. Shipped,
    # the start is `~`, which the daemon resolves for whoever opens the page.
    html = html.replace(localfs.as_file_key(HOME_DIR), "~").replace(HOME_DIR, "~")
    assert html.count("<script>") == 1 and html.count("</script>") == 1
    a = html.index("<script>\n") + len("<script>\n")
    b = html.index("</script>")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "files.js"), "w") as fh:
        fh.write(html[a:b])
    # Where the script sits is a property of the place the pair is going.
    # Beside the page by default, which is what a folder or a plain server
    # gives; inside resources.pak it takes over the rollup's own path, and
    # the tag has to say so or the page loads without a script at all.
    src = os.environ.get("AURADE_SHIP_SCRIPT", "files.js")
    with open(os.path.join(out, "files.html"), "w") as fh:
        fh.write(html[:a - len("<script>\n")]
                 + f'<script src="{src}"></script>'
                 + html[b + len("</script>"):])
    # Nothing of this machine: the build home is empty and named nowhere.
    for leaf in ("files.html", "files.js"):
        text = open(os.path.join(out, leaf)).read()
        assert HOME_DIR not in text, f"{leaf} names the build home"
    return len(html)


if __name__ == "__main__" and SHIP:
    _n = build_ship(SHIP)
    print(f"wrote files.html and files.js under {SHIP}, {_n} bytes")
    import shutil as _shutil
    _shutil.rmtree(HOME_DIR, ignore_errors=True)
elif __name__ == "__main__":
    _order, _html = build_site()
    print(f"wrote v3.html {len(_html)} bytes, and {len(_order)} pages "
          f"under {PAGES_DIR}")
    THEME, PAGES_DIR = LIGHT, PAGES_DIR + "-light"
    _order, _ = build_site(write_v3=False)
    print(f"wrote {len(_order)} light pages under {PAGES_DIR}")
