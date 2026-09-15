"""Turn Files' own source into the command table this page is measured against.

Files keeps each command as a class under `src/Files.App/Actions` and its
visible text in `Strings/en-US/Resources.resw`. Reading both gives the command
code, the label and description a person actually sees, the category, the
keyboard shortcut and the icon, with nothing retyped in between. Anything
retyped is a thing that goes stale silently, and the whole point of this file
is to be regenerated rather than maintained.

    python3 tools/extract_commands.py            # writes assets/files-commands.json
    python3 tools/extract_commands.py --check    # says whether it is current

The generated file is the parity contract: a gate reads it and asserts the page
registers every command in it, under the same name, with the same label and the
same shortcut.
"""

import json
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
PROTO = os.path.dirname(HERE)
REF = os.environ.get("FILES_REF", "/mnt/build/aurade-work/ref-files")
ACTIONS = os.path.join(REF, "src/Files.App/Actions")
RESW = os.path.join(REF, "src/Files.App/Strings/en-US/Resources.resw")
OUT = os.path.join(PROTO, "assets", "files-commands.json")

#: A class that is not a command: the abstract bases Files shares behaviour
#: through, and the two interfaces.
NOT_A_COMMAND = re.compile(r"^(Base[A-Z]|I$|IToggle$|CloseTabBase$)")

#: The three whose file is the family rather than a command. Each is a real
#: file holding what its many commands share.
FAMILY = {"Layout", "Sort", "Group"}

#: Keys.* names that are not the character they are called. Files uses the
#: Windows virtual key names; these are what a person sees on the key.
KEY_FACE = {
    "Oem3": "`",
    "OemComma": ",",
    "OemPeriod": ".",
    "OemMinus": "-",
    "OemPlus": "+",
    "Oem2": "/",
    "Oem5": "\\",
    "Oem4": "[",
    "Oem6": "]",
    "Oem1": ";",
    "Oem7": "'",
    "Add": "+",
    "Subtract": "-",
    "Back": "Backspace",
    "Escape": "Esc",
    "Menu": "Menu",
    "Mouse4": "Mouse4",
    "Mouse5": "Mouse5",
}

#: Keys.Number1 and Keys.Pad1 are the 1 key. Written out rather than stripped
#: with a regex so a key that merely ends in a digit, F11 say, is left alone.
for _digit in range(10):
    KEY_FACE[f"Number{_digit}"] = str(_digit)
    KEY_FACE[f"Pad{_digit}"] = f"Numpad {_digit}"


def strings():
    """Every visible string Files has, by the name the code refers to it by."""
    out = {}
    for data in ET.parse(RESW).getroot().findall("data"):
        name = data.get("name")
        value = data.findtext("value")
        if name and value is not None:
            out[name] = value
    return out


def classes(text, keep_bases=False):
    """Each command class in a file, with the text belonging to it.

    By class rather than by file: `GroupAction.cs` holds twenty six commands
    and `LayoutAction.cs` holds eight, so walking file names finds a fraction
    of what is there and quietly reports the rest as parity. A class runs to
    the start of the next one, which keeps one class's shortcut from being
    read as every class's shortcut.
    """
    marks = [(m.start(), m.group(1))
             for m in re.finditer(r"\bclass\s+([A-Za-z0-9_]+)Action\b", text)]
    out = []
    for i, (at, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        #: The declaration, not the file: `abstract` sits a few words before
        #: the class keyword, and looking further back would read the previous
        #: class's modifier.
        abstract = "abstract" in text[max(0, at - 120):at]
        if abstract and not keep_bases:
            continue
        out.append((name, text[at:end], abstract))
    return out


def first(text, pattern, group=1):
    found = re.search(pattern, text)
    return found.group(group) if found else None


def statement(text, at):
    """From `at` to the semicolon that ends the expression starting there.

    A walk and not a regex: these conditions carry lambdas, string literals
    and collection expressions, and every one of them can hold a semicolon
    that does not end anything.
    """
    depth = 0
    i = at
    while i < len(text):
        c = text[i]
        if c == '"':
            #: A verbatim string, `@"..."` or `$@"..."`, treats the backslash
            #: as a backslash. Reading one as an escape runs past the closing
            #: quote and swallows the rest of the class: FormatDrive's
            #: condition came back with three more members attached to it.
            verbatim = text[max(0, i - 2):i].find("@") >= 0
            i += 1
            while i < len(text) and text[i] != '"':
                i += 1 if verbatim else (2 if text[i] == "\\" else 1)
            if verbatim and text[i:i + 2] == '""':
                i += 2
                while i < len(text) and text[i] != '"':
                    i += 1
        elif c == "'":
            i += 3 if text[i + 1] == "\\" else 2
            continue
        elif c == "/" and text[i:i + 2] == "//":
            i = text.find("\n", i)
            if i < 0:
                return len(text)
            continue
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == ";" and depth == 0:
            return i
        i += 1
    return len(text)


def executable(body):
    """The condition under which a command can run, as one line.

    Files calls it `IsExecutable`, and the menus lean on it: a context menu
    row with no visibility of its own is shown exactly while this is true. It
    is kept as the reference's own words rather than as a verdict, so what
    this page can honour and what it cannot stays visible.
    """
    found = re.search(r"\bbool IsExecutable\b", body)
    if not found:
        return None
    arrow = body.find("=>", found.end())
    brace = body.find("{", found.end())
    #: A property with a body rather than an expression. Only one command has
    #: one, and its condition is not something to guess at from a getter.
    if arrow < 0 or (0 <= brace < arrow):
        return None
    text = body[arrow + 2:statement(body, arrow + 2)]
    return " ".join(text.split()) or None


#: What a toggle is a toggle of. A sort command is on while the list is
#: sorted its way, and which way that is comes from a property of its own
#: rather than from the condition: `protected override SortOption SortOption
#: => SortOption.Name;`. Kept so the check beside a menu row can follow the
#: state the reference says it follows.
TOGGLE_OF = ("SortOption", "GroupOption", "GroupByDateUnit", "LayoutTypes")


def toggles(body):
    """Which value of which setting this command turns on, if it is a toggle."""
    out = {}
    for kind in TOGGLE_OF:
        found = re.search(
            rf"\b{kind}\s+\w+\s*(?:=>|\n\s*=>)\s*\w+\.(\w+)\s*;", body)
        if found:
            out[kind] = found.group(1)
    #: Ascending and Descending have no property to override: each says in its
    #: own `IsOn` which direction it is. Read only from a toggle, so
    #: ToggleSortDirection, which flips the direction rather than setting one,
    #: is not read as the command that turns Descending on.
    if "IToggleAction" in body:
        for found in re.finditer(
                r"\.(SortDirection|GroupDirection|GroupByDateUnit)"
                r"\s+is\s+\w+\.(\w+)", body):
            out.setdefault(found.group(1), found.group(2))
    return out or None


def hotkeys(text):
    """Every shortcut the class declares, as a person would write them.

    Files gives some commands more than one: a `HotKey` and a `SecondHotKey`,
    and sometimes a media key as well. All of them are kept, because a table
    that lists one of two is a table that says a working shortcut is missing.
    """
    out = []
    for found in re.finditer(r"(Second|Third|Media)?HotKey\s*=>\s*new\(([^)]*)\)", text):
        keys, mods = [], []
        for part in [p.strip() for p in found.group(2).split(",") if p.strip()]:
            if part.startswith("Keys."):
                key = part[len("Keys."):]
                keys.append(KEY_FACE.get(key, key))
            elif part.startswith("KeyModifiers."):
                for mod in part[len("KeyModifiers."):].split("|"):
                    mod = mod.strip()
                    #: Files writes a pair as one word, CtrlShift and CtrlAlt.
                    for piece in re.findall(r"[A-Z][a-z]+", mod) or [mod]:
                        if piece not in ("None",):
                            mods.append(piece)
        if keys:
            out.append("+".join(mods + keys))
    #: Same shortcut written twice is one shortcut.
    seen, unique = set(), []
    for key in out:
        if key not in seen:
            seen.add(key)
            unique.append(key)
    return unique


def collect():
    words = strings()
    found = {}
    bases = {}
    for root, _dirs, files in os.walk(ACTIONS):
        for name in sorted(files):
            if not name.endswith(".cs"):
                continue
            text = open(os.path.join(root, name), encoding="utf-8-sig").read()
            area = os.path.relpath(root, ACTIONS).split(os.sep)[0]
            for command, body, abstract in classes(text, keep_bases=True):
                read = {
                    "command": command,
                    "category": area,
                    "labelKey": first(
                        body,
                        r"Label\s*=>\s*(?:.*\n\s*)?Strings\.(\w+)\.GetLocalized")
                    or first(body, r"Strings\.(\w+)\.GetLocalized"),
                    "descriptionKey": first(
                        body,
                        r"Description\s*=>\s*(?:.*\n\s*)?Strings\.(\w+)\.GetLocalized"),
                    "hotkeys": hotkeys(body),
                    "executable": executable(body),
                    "toggles": toggles(body),
                    "glyph": first(body, r'themedIconStyle:\s*"([^"]+)"'),
                    "toggle": "IToggleAction" in body,
                    "base": first(body, r"class\s+\w+Action\s*:\s*(\w+)Action"),
                }
                #: An abstract class is a base whatever it is called, and a
                #: base is not a command however concrete its name looks.
                if abstract or NOT_A_COMMAND.match(command) or command in FAMILY:
                    bases[command] = read
                else:
                    found[command] = read

    #: A command that says nothing about itself says it on the base it derives
    #: from: `OpenInNewTabAction` carries no label because
    #: `BaseOpenInNewTabAction` carries it for all three of them.
    for entry in found.values():
        seen = set()
        parent = entry["base"]
        while parent and parent not in seen:
            seen.add(parent)
            up = bases.get(parent) or found.get(parent)
            if not up:
                break
            for field in ("labelKey", "descriptionKey", "glyph", "executable",
                          "toggles"):
                if not entry[field]:
                    entry[field] = up[field]
            if not entry["hotkeys"]:
                entry["hotkeys"] = up["hotkeys"]
            entry["toggle"] = entry["toggle"] or up["toggle"]
            parent = up["base"]

    #: C# reaches a resource named `Thing.Label` as `Strings.Thing_Label`,
    #: because a dot is not legal in an identifier. Without translating back,
    #: the New command comes out with no label at all.
    def spoken(key):
        if not key:
            return None
        if key in words:
            return words[key]
        return words.get(key.replace("_", "."), None)

    for entry in found.values():
        entry["label"] = spoken(entry.pop("labelKey"))
        entry["description"] = spoken(entry.pop("descriptionKey"))
        entry.pop("base", None)
    return dict(sorted(found.items()))


def main():
    table = collect()
    payload = {
        "//": "Generated by tools/extract_commands.py from the Files reference."
              " Do not edit: regenerate.",
        "source": "files-community/Files, src/Files.App/Actions",
        "count": len(table),
        "commands": table,
    }
    text = json.dumps(payload, indent=1, ensure_ascii=False) + "\n"

    if "--check" in sys.argv:
        current = open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        if current == text:
            print(f"current: {len(table)} commands")
            return 0
        print(f"stale: regenerate tools/extract_commands.py ({len(table)} commands)")
        return 1

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(text)
    missing = [c for c, v in table.items() if not v["label"]]
    print(f"{len(table)} commands written to {os.path.relpath(OUT, PROTO)}")
    if missing:
        print(f"{len(missing)} with no label: {', '.join(missing[:8])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
