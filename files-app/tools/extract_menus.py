"""Turn Files' context menu builders into the menu tables this page is measured against.

Files builds seven context menus, all the same shape: a list of
`ContextMenuFlyoutItemViewModel`, each row naming a command or carrying its own
text, some rows holding a list of their own, and every row carrying the
condition under which it is shown.

    python3 tools/extract_menus.py            # writes assets/files-menus.json
    python3 tools/extract_menus.py --check    # says whether it is current

The generated file is the contract: `build_v3.py` builds the menus out of it
and gates in verify_all.py read the built menus back.

The content page's list serves two menus. `itemsSelected` is what separates
them, so a row shown only when nothing is selected belongs to the background
menu, one shown only when something is belongs to the menu over a file, and a
row that never mentions it belongs to both. The widget and sidebar menus are
each one menu, so nothing is split.
"""

import json
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
PROTO = os.path.dirname(HERE)
REF = os.environ.get("FILES_REF", "/mnt/build/aurade-work/ref-files")
RESW = os.path.join(REF, "src/Files.App/Strings/en-US/Resources.resw")
COMMANDS = os.path.join(PROTO, "assets", "files-commands.json")
OUT = os.path.join(PROTO, "assets", "files-menus.json")

APP = "src/Files.App"
WIDGETS = f"{APP}/ViewModels/UserControls/Widgets"

#: Every context menu Files builds, and the function that builds it. The
#: content page's is first because it is the one that serves two menus.
SOURCES = [
    ("content", f"{APP}/Data/Factories/ContentPageContextFlyoutFactory.cs",
     "GetBaseItemMenuItems"),
    ("drive", f"{WIDGETS}/DrivesWidgetViewModel.cs", "GetItemMenuItems"),
    ("quickaccess", f"{WIDGETS}/QuickAccessWidgetViewModel.cs", "GetItemMenuItems"),
    ("recent", f"{WIDGETS}/RecentFilesWidgetViewModel.cs", "GetItemMenuItems"),
    ("filetags", f"{WIDGETS}/FileTagsWidgetViewModel.cs", "GetItemMenuItems"),
    ("network", f"{WIDGETS}/NetworkLocationsWidgetViewModel.cs", "GetItemMenuItems"),
    ("sidebar", f"{APP}/ViewModels/UserControls/SidebarViewModel.cs",
     "GetLocationItemMenuItems"),
]

#: The two menus Files writes in XAML rather than building in C#. The shapes
#: are the same three, spelled as elements, and a row names its command the
#: same way.
XAML_SOURCES = [
    ("home", f"{APP}/Views/HomePage.xaml", "HomePageContextMenu"),
    ("tab", f"{APP}/UserControls/TabBar/TabBar.xaml", "TabFlyout"),
]

XAML_ROWS = {"MenuFlyoutItem", "MenuFlyoutItemWithThemedIcon",
             "ToggleMenuFlyoutItem", "ToggleMenuFlyoutItemWithThemedIcon"}
XAML_SUBS = {"MenuFlyoutSubItem"}
XAML_SEPS = {"MenuFlyoutSeparator"}

#: A row is one of these three constructions. The third, `new()`, is C#
#: letting the list's own type say what is being built, and the widget menus
#: use it for most of their rows: a walk that looks only for the type's name
#: reads a menu of nine rows as a menu of one.
ROW = re.compile(
    r"\bnew\b\s*"
    r"(ContextMenuFlyoutItemViewModelBuilder|ContextMenuFlyoutItemViewModel)?"
    r"\s*(?=[({])")

NAMES = r"(?:Commands|ModifiableCommands|CommandManager)"

#: A row whose text is a literal `Placeholder` is a slot Files fills at run
#: time from the Windows shell. There is no row to match, so it is recorded as
#: a placeholder rather than as a menu entry.
PLACEHOLDER = "Placeholder"

#: Rows that reach their command through a view model rather than naming it.
#: The widget and sidebar menus do it for most of their rows, and the
#: indirection cannot be followed from here, so the pairs are written down.
#: Each one below is a row whose own text names the command it ends at, which
#: is how they were checked: the Quick access widget's pin row is captioned
#: `Strings.PinFolderToSidebar`, so `PinToSidebarCommand` is that command.
#:
#: The ones left out have no command in Files' table at all. Eject, Create
#: library, Restore libraries, Reorder sidebar items, Map network drive, Hide
#: section, Remove from recent and Clear all are the widgets' and the
#: sidebar's own, so those rows keep their caption and reach nothing.
VIEW_MODEL_COMMANDS = {
    "CreateNewFileCommand": "CreateFile",
    "OpenPropertiesCommand": "OpenProperties",
    "OpenFileLocationCommand": "OpenFileLocation",
    "PinToSidebarCommand": "PinFolderToSidebar",
    "PinItemCommand": "PinFolderToSidebar",
    "UnpinFromSidebarCommand": "UnpinFolderFromSidebar",
    "UnpinItemCommand": "UnpinFolderFromSidebar",
}


def strings():
    out = {}
    for data in ET.parse(RESW).getroot().findall("data"):
        name, value = data.get("name"), data.findtext("value")
        if name and value is not None:
            out[name] = value
    return out


def labels():
    """What each command is called, so `Text = Commands.X.Label` can be read."""
    if not os.path.exists(COMMANDS):
        return {}
    with open(COMMANDS, encoding="utf-8") as fh:
        table = json.load(fh)["commands"]
    return {name: entry.get("label") for name, entry in table.items()}


def closing(text, at):
    """The index just past the bracket that closes the one at `at`.

    A walk and not a regex, because these lists nest six deep and a label can
    hold a brace of its own. Strings, characters and line comments are stepped
    over so a bracket inside one is not counted.
    """
    pairs = {"{": "}", "[": "]", "(": ")"}
    want = pairs[text[at]]
    depth = 0
    i = at
    while i < len(text):
        c = text[i]
        if c == '"':
            verbatim = text[max(0, i - 2):i].find("@") >= 0
            i += 1
            while i < len(text) and text[i] != '"':
                i += 1 if verbatim else (2 if text[i] == "\\" else 1)
        elif c == "'":
            i += 3 if text[i + 1] == "\\" else 2
            continue
        elif c == "/" and text[i:i + 2] == "//":
            i = text.find("\n", i)
            if i < 0:
                return len(text)
            continue
        elif c in pairs:
            depth += 1
        elif c in "}])":
            depth -= 1
            if depth == 0:
                if c != want:
                    raise ValueError(f"expected {want}, found {c} at {i}")
                return i + 1
        i += 1
    raise ValueError("unclosed bracket")


def skip_space(text, i):
    """Past whitespace and comments, which sit between `new X` and its brace."""
    while i < len(text):
        if text[i].isspace():
            i += 1
        elif text[i:i + 2] == "//":
            nl = text.find("\n", i)
            i = len(text) if nl < 0 else nl + 1
        else:
            return i
    return i


def rows(body, source):
    """Each row constructed at this level of the list, in order.

    Three spellings, and each of them optionally carries an initialiser:

        new ContextMenuFlyoutItemViewModelBuilder(Commands.X).Build()
        new ContextMenuFlyoutItemViewModelBuilder(Commands.X) { .. }.Build()
        new ContextMenuFlyoutItemViewModel() { .. }
        new ContextMenuFlyoutItemViewModel { .. }
        new() { .. }

    The parentheses being optional is the trap: looking for the next `(` when
    there is none walks into the following row and swallows it, which is how
    SortAscending went missing the first time this was written.
    """
    out = []
    i = 0
    while True:
        found = ROW.search(body, i)
        if not found:
            return out
        kind = found.group(1)
        command = None
        after = found.end()
        if kind == "ContextMenuFlyoutItemViewModelBuilder":
            call = body[after:closing(body, after)]
            named = re.match(rf"\(\s*{NAMES}\.(\w+)", call)
            command = named.group(1) if named else None
            after = closing(body, after)
        elif body[after] == "(":
            after = closing(body, after)
        after = skip_space(body, after)
        if after >= len(body) or body[after] != "{":
            #: No initialiser: a builder with nothing but `.Build()`.
            out.append({"command": command})
            i = after + 1
            continue
        end = closing(body, after)
        init = body[after:end]
        #: A row's own text is read from its own properties. Everything a row
        #: holds is inside one pair of braces, children included, so a
        #: separator among the children would otherwise be read as the parent
        #: being a separator, and the parent's label would be thrown away.
        own = without_children(init)
        out.append({
            "command": command,
            "separator": "ContextMenuFlyoutItemType.Separator" in own,
            #: One row builds its caption with the section's name in it, so
            #: the resource is inside a `string.Format` rather than assigned
            #: straight across. Without the second spelling the sidebar's
            #: Hide section row comes out with no text at all.
            "labelKey": (first(own, r"Text\s*=\s*Strings\.(\w+)\.GetLocalized")
                         or first(own, r"Text\s*=\s*string\.Format\(\s*"
                                       r"Strings\.(\w+)\.GetLocalized")),
            "labelOf": first(own, rf"Text\s*=\s*{NAMES}\.(\w+)\.Label"),
            "literal": first(own, r'Text\s*=\s*"([^"]*)"'),
            "tag": first(own, r'Tag\s*=\s*"([^"]+)"'),
            #: A row that runs a view model's command rather than a named one.
            "command2": VIEW_MODEL_COMMANDS.get(
                first(own, r"Command\s*=\s*(?:commandsViewModel\.)?(\w+Command)\b")
                or ""),
            #: A plain row can name a command too, and pass it an argument:
            #: the two halves of Open in new pane are one command told which
            #: way to split. The argument is kept, because a row that runs the
            #: command without it is a row that splits the wrong way.
            "command3": first(own, rf"Command\s*=\s*{NAMES}\.(\w+)"),
            "parameter": first(own, r"CommandParameter\s*=\s*[\w.]*?(\w+)\s*,"),
            #: A primary row is drawn as an icon button in the row across the
            #: top of the menu rather than as a line of its own.
            "primary": re.search(r"IsPrimary\s*=\s*true", own) is not None,
            "glyph": (first(own, r'ThemedIconStyle\s*=\s*"([^"]+)"')
                      or first(own, rf'ThemedIconStyle\s*=\s*{NAMES}\.(\w+)\.Glyph')),
            "show": show(own),
            "items": children(init, source),
        })
        i = end


def first(text, pattern):
    found = re.search(pattern, text)
    return found.group(1) if found else None


def show(init):
    """The visibility expression, on one line.

    A builder spells it `IsVisible` and a plain row spells it `ShowItem`, and
    either can run over several lines, so it runs to the comma that ends the
    initialiser property rather than to the end of the line.
    """
    found = re.search(r"(?:ShowItem|IsVisible)\s*=\s*(.+?),?\s*\n\s*(?:\w+\s*=|\})",
                      init, re.S)
    return " ".join(found.group(1).split()) if found else None


def without_children(init):
    """A row's initialiser with its `Items` list taken out."""
    found = re.search(r"Items\s*=\s*(?://[^\n]*\n\s*)*\[", init)
    if found:
        at = init.index("[", found.end() - 1)
        return init[:found.start()] + init[closing(init, at):]
    return init


def children(init, source):
    """What a submenu holds.

    Written either as an `Items = [ ... ]` list or, for New, as a call to the
    function that builds it. Both are followed, because a submenu whose rows
    are not read is a submenu reported as empty.
    """
    found = re.search(r"Items\s*=\s*(?://[^\n]*\n\s*)*\[", init)
    if found:
        at = init.index("[", found.end() - 1)
        return rows(init[at + 1:closing(init, at) - 1], source)
    called = re.search(r"Items\s*=\s*(Get\w+)\(", init)
    if called:
        return rows(body_of(source, called.group(1)), source)
    return []


def body_of(source, name):
    """The list the named function returns."""
    at = re.search(rf"\b{name}\s*\(", source)
    if not at:
        raise ValueError(f"no function named {name}")
    start = source.index("new List<ContextMenuFlyoutItemViewModel>()", at.end())
    brace = source.index("{", start
                         + len("new List<ContextMenuFlyoutItemViewModel>()") - 1)
    return source[brace + 1:closing(source, brace) - 1]


#: `!=` is not a negation and `=>` opens a lambda. Both appear inside these
#: conditions, and both would be read as an operator they are not.
NOT_OPERATORS = [("!=", "≠"), ("=>", "⇒")]

TOKENS = re.compile(r"\s*(&&|\|\||[!()]|[^\s&|!()]+)")

#: Three values rather than two. Everything but `itemsSelected` is a term this
#: reader cannot evaluate, and a term that is unknown stays unknown when it is
#: negated. Taking it as true instead makes `!isRecycleBin` false, which reads
#: as a row that can never be shown and hides Rotate from both menus.
UNKNOWN = None


def tokens(expression):
    for old, new in NOT_OPERATORS:
        expression = expression.replace(old, new)
    return TOKENS.findall(expression)


def tri_not(value):
    return UNKNOWN if value is UNKNOWN else not value


def tri_and(left, right):
    if left is False or right is False:
        return False
    return UNKNOWN if UNKNOWN in (left, right) else True


def tri_or(left, right):
    if left is True or right is True:
        return True
    return UNKNOWN if UNKNOWN in (left, right) else False


def can_show(expression, selected):
    """Whether a row can appear with, or without, something selected.

    Answered by reading the condition rather than by looking for a substring
    in it. `(!itemsSelected || areAllItemsFolders) && ...` shows in both menus
    and a substring test calls it the background's, and `itemsSelected && x`
    and `x && !itemsSelected` are the same shape spelled two ways. The
    question is whether the condition is false for this value of
    `itemsSelected` alone.
    """
    if not expression:
        return True
    words = tokens(expression)
    at = 0

    def factor():
        nonlocal at
        if at < len(words) and words[at] == "!":
            at += 1
            return tri_not(factor())
        if at < len(words) and words[at] == "(":
            at += 1
            value = disjunction()
            if at < len(words) and words[at] == ")":
                at += 1
            return value
        word = words[at] if at < len(words) else ""
        at += 1
        #: A method call carries its arguments: `selectedItems.All(x => ...)`
        #: is one term, not a term beside a condition of its own.
        while at < len(words) and words[at] == "(":
            depth = 0
            while at < len(words):
                depth += (1 if words[at] == "(" else
                          (-1 if words[at] == ")" else 0))
                at += 1
                if depth == 0:
                    break
        if word == "itemsSelected":
            return selected
        if word in ("true", "false"):
            return word == "true"
        return UNKNOWN

    def conjunction():
        nonlocal at
        value = factor()
        while at < len(words) and words[at] == "&&":
            at += 1
            value = tri_and(value, factor())
        return value

    def disjunction():
        nonlocal at
        value = conjunction()
        while at < len(words) and words[at] == "||":
            at += 1
            value = tri_or(value, conjunction())
        return value

    try:
        return disjunction() is not False
    except (IndexError, RecursionError):
        #: An unreadable condition is reported as showing everywhere rather
        #: than quietly dropping a row from one of the two menus.
        return True


def side(expression):
    """Which of the content page's two menus a row belongs to."""
    here = can_show(expression, False)
    there = can_show(expression, True)
    if here and there:
        return "both"
    return "background" if here else "item"


def clean(items, words, named, split):
    out = []
    for row in items:
        label = (words.get(row.get("labelKey") or "")
                 or named.get(row.get("labelOf") or "")
                 or row.get("literal"))
        entry = {
            "command": (row.get("command") or row.get("command2")
                        or row.get("command3")),
            #: What the row is called in the reference's own resources, kept
            #: for the rows that have no command: it is the only stable name
            #: they have, and a caption is not one.
            "key": row.get("labelKey") if not (
                row.get("command") or row.get("command2")
                or row.get("command3")) else None,
            "setting": row.get("setting"),
            "parameter": row.get("parameter"),
            "label": None if label == PLACEHOLDER else label,
            "placeholder": label == PLACEHOLDER,
            "separator": bool(row.get("separator")),
            "primary": bool(row.get("primary")),
            "tag": row.get("tag"),
            "glyph": row.get("glyph"),
            "show": row.get("show"),
            "side": side(row.get("show")) if split else None,
            "items": clean(row.get("items") or [], words, named, split),
        }
        out.append({k: v for k, v in entry.items() if v not in (None, [], False)})
    return out


def local(tag):
    """An element's name without the namespace it was declared in."""
    return tag.rsplit("}", 1)[-1]


def bound(value, pattern):
    """What a `{x:Bind ...}` or `{helpers:ResourceString ...}` points at."""
    if not value:
        return None
    found = re.search(pattern, value)
    return found.group(1) if found else None


def xaml_rows(node):
    """Each row under a XAML menu, in the order the file has them."""
    out = []
    for child in node:
        name = local(child.tag)
        #: `MenuFlyoutSubItem.Icon` is a property written as an element, not a
        #: row of its own.
        if "." in name:
            continue
        if name in XAML_SEPS:
            out.append({"separator": True})
            continue
        if name not in XAML_ROWS | XAML_SUBS:
            continue
        held = child.attrib
        out.append({
            "command": bound(held.get("Command"), rf"{NAMES}\.(\w+)"),
            #: `{helpers:ResourceString Name=Thing/Text}` is the resource
            #: `Thing.Text`: the slash is how XAML spells the dot.
            "labelKey": (bound(held.get("Text"),
                               r"ResourceString\s+Name=([\w/]+)") or "").replace(
                                   "/", ".") or None,
            "labelOf": bound(held.get("Text"), rf"{NAMES}\.(\w+)\.Label"),
            "literal": (held.get("Text")
                        if held.get("Text") and "{" not in held.get("Text")
                        else None),
            "glyph": bound(held.get("ThemedIconStyle"),
                           rf"{NAMES}\.(\w+)\.ThemedIconStyle"),
            #: A toggle bound to a setting rather than to a command. The Home
            #: menu's widget list is five of them, and each one is the only
            #: place that widget can be turned off.
            "setting": bound(held.get("IsChecked"), r"ViewModel\.(\w+)"),
            #: `x:Load` is how XAML says a row is only there under a
            #: condition, and it reads like every other condition here.
            "show": bound(held.get(f"{{{XAML_NS}}}Load"), r"x:Bind\s+(.+?),")
            or bound(held.get(f"{{{XAML_NS}}}Load"), r"x:Bind\s+(.+?)\}}"),
            "items": xaml_rows(child) if name in XAML_SUBS else [],
        })
    return out


XAML_NS = "http://schemas.microsoft.com/winfx/2006/xaml"


def xaml_menu(path, name):
    """The menu in a XAML file with this `x:Name` or `x:Key`."""
    tree = ET.parse(os.path.join(REF, path)).getroot()
    for node in tree.iter():
        held = node.attrib
        if (held.get(f"{{{XAML_NS}}}Name") == name
                or held.get(f"{{{XAML_NS}}}Key") == name):
            return node
    raise ValueError(f"no menu named {name} in {path}")


def collect():
    words, named = strings(), labels()
    menus = {}
    for key, path, function in SOURCES:
        source = open(os.path.join(REF, path), encoding="utf-8-sig").read()
        menus[key] = clean(rows(body_of(source, function), source),
                           words, named, key == "content")
    for key, path, name in XAML_SOURCES:
        menus[key] = clean(xaml_rows(xaml_menu(path, name)), words, named, False)
    return menus


def flatten(items, into=None):
    into = [] if into is None else into
    for row in items:
        if row.get("command"):
            into.append(row["command"])
        flatten(row.get("items") or [], into)
    return into


def unnamed(items, path=()):
    """Rows that carry neither a command nor a label, which would be a miss."""
    bad = []
    for n, row in enumerate(items):
        if not (row.get("command") or row.get("label")
                or row.get("separator") or row.get("placeholder")):
            bad.append(" > ".join(path + (str(n),)))
        bad += unnamed(row.get("items") or [],
                       path + (row.get("command") or row.get("label") or "?",))
    return bad


def main():
    menus = collect()
    blank = []
    for key, rows_ in menus.items():
        blank += [f"{key}: {where}" for where in unnamed(rows_)]
    if blank:
        print(f"{len(blank)} rows read with no command and no label: "
              f"{', '.join(blank[:6])}", file=sys.stderr)
        return 2
    payload = {
        "//": "Generated by tools/extract_menus.py from the Files reference."
              " Do not edit: regenerate.",
        "sources": {key: path for key, path, _f in SOURCES},
        "rows": {key: len(rows_) for key, rows_ in menus.items()},
        "commands": {key: len(flatten(rows_)) for key, rows_ in menus.items()},
        "menus": menus,
    }
    text = json.dumps(payload, indent=1, ensure_ascii=False) + "\n"

    if "--check" in sys.argv:
        current = open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        if current == text:
            print("current: " + ", ".join(
                f"{k} {v}" for k, v in payload["commands"].items()))
            return 0
        print("stale: run python3 tools/extract_menus.py")
        return 1

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(text)
    for key in menus:
        print(f"{key}: {payload['commands'][key]} commands"
              f" in {payload['rows'][key]} top level rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
