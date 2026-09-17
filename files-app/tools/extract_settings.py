"""Turn Files' own settings pages into the table this page is measured against.

Files writes every settings row in XAML, as a `SettingsCard` or a
`SettingsExpander` holding more of them, and gives each one a header, an
optional description, an icon and one control. Reading the markup gives the
rows in the order a person scrolls past them, with the text they actually
see and the setting each control is bound to, and nothing retyped in between.

    python3 tools/extract_settings.py            # writes assets/files-settings.json
    python3 tools/extract_settings.py --check    # says whether it is current

The generated file is the parity contract: a gate reads it and asserts the
settings page carries the same rows, under the same headers, in the same
order, with the same kind of control.
"""

import json
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
PROTO = os.path.dirname(HERE)
REF = os.environ.get("FILES_REF", os.path.join(PROTO, "ref-files"))
PAGES = os.path.join(REF, "src/Files.App/Views/Settings")
RESW = os.path.join(REF, "src/Files.App/Strings/en-US/Resources.resw")
VIEW_MODEL = os.path.join(
    REF, "src/Files.App/ViewModels/Settings/SettingsPageViewModel.cs")
OUT = os.path.join(PROTO, "assets", "files-settings.json")

#: The shell that holds the others, and the one page that is a dialog rather
#: than a page of settings.
NOT_A_PAGE = {"SettingsPage", "ToolbarCustomizationPage"}

#: What a row is. Everything else in these files is layout.
ROW_TAGS = {"SettingsCard", "SettingsExpander"}

#: A child element that is a property of its parent rather than the parent's
#: control: `<SettingsCard.HeaderIcon>` is how XAML writes an attribute whose
#: value is an element.
PROPERTY_CHILD = re.compile(r"^(SettingsCard|SettingsExpander)\.")

#: The controls a row can hold, in the order they are asked about, because a
#: row can hold a panel holding one. The name on the left is Files' element
#: and the name on the right is what kind of control it is.
CONTROLS = {
    "ToggleSwitch": "switch",
    "ComboBoxEx": "select",
    "ComboBox": "select",
    "Button": "button",
    "HyperlinkButton": "link",
    "NumberBox": "number",
    "TextBox": "text",
    "Slider": "slider",
    "CheckBox": "check",
    "ToggleButton": "toggle",
    "RadioButtons": "radio",
    "ColorPicker": "color",
    "ItemsRepeater": "list",
    "ListView": "list",
    "TextBlock": "label",
    "ProgressRing": "progress",
    "InfoBar": "info",
}

#: `{helpers:ResourceString Name=Thing}`, and the `/Content` suffix XAML uses
#: for a uid, which the resource file writes with a dot.
RESOURCE = re.compile(r"\{helpers:ResourceString\s+Name=([^},\s]+)")

#: `{x:Bind ViewModel.Thing, Mode=TwoWay}`. The property is the setting.
BIND = re.compile(r"\{x:Bind\s+ViewModel\.([A-Za-z0-9_]+)")


def strings():
    out = {}
    for data in ET.parse(RESW).getroot().findall("data"):
        name, value = data.get("name"), data.findtext("value")
        if name and value is not None:
            out[name] = value
    return out


WORDS = None


def spoken(raw):
    """The text a person reads, out of a XAML attribute value."""
    if not raw:
        return None
    found = RESOURCE.search(raw)
    if not found:
        #: A description bound to a view model property has no text here to
        #: read. Kept as the binding rather than dropped, so a row with a
        #: live description is still a row.
        bound = BIND.search(raw)
        return f"={bound.group(1)}" if bound else (raw or None)
    key = found.group(1).replace("/", ".")
    return WORDS.get(key) or WORDS.get(key.replace(".", "_")) or key


def local(el):
    return el.tag.split("}")[-1]


#: Which attribute holds the setting, asked in this order. A combo box binds
#: its list to one property and its selection to another, and the setting is
#: the selection: reading whichever binding came first in the file reported
#: the Language row as bound to AppLanguages, which is the list of languages
#: rather than the chosen one.
BOUND_BY = ("IsOn", "IsChecked", "SelectedItem", "SelectedIndex", "Value",
            "Text", "Command", "ItemsSource")


def bound_to(node):
    """The setting a control changes."""
    for attr in BOUND_BY:
        found = BIND.search(node.get(attr) or "")
        if found:
            return found.group(1)
    for value in node.attrib.values():
        found = BIND.search(value)
        if found:
            return found.group(1)
    return None


def control_of(el):
    """What the row holds, and which setting it is bound to.

    The first control found anywhere under the row but not inside another
    row: a `SettingsExpander`'s own combo box sits directly under it, and its
    children live under `SettingsExpander.Items`.
    """
    stack = [c for c in el if not PROPERTY_CHILD.match(local(c))]
    while stack:
        node = stack.pop(0)
        kind = CONTROLS.get(local(node))
        if kind:
            return kind, bound_to(node)
        #: Never walk into another row. Nothing in these files nests one
        #: outside an Items block, and a walk that could would report a
        #: child's switch as its parent's control.
        stack += [c for c in node
                  if local(c) not in ROW_TAGS
                  and not PROPERTY_CHILD.match(local(c))]
    return None, None


def rows_under(el, depth=0):
    """Every settings row under an element, in the order XAML writes them."""
    out = []
    for child in el:
        name = local(child)
        if name in ROW_TAGS:
            out.append(row_of(child, depth))
            continue
        #: A row's own property elements hold its icon and its children, and
        #: `row_of` reads those itself.
        if PROPERTY_CHILD.match(name):
            continue
        out += rows_under(child, depth)
    return out


def row_of(el, depth):
    kind, bound = control_of(el)
    items = []
    for child in el:
        if local(child).endswith(".Items"):
            items += rows_under(child, depth + 1)
    return {
        "header": spoken(el.get("Header")),
        "description": spoken(el.get("Description")),
        "expander": local(el) == "SettingsExpander",
        "control": kind,
        "setting": bound,
        "items": items,
    }


def page_title(root):
    """The heading the page draws above its first row."""
    for el in root.iter():
        if local(el) == "TextBlock" and "Subtitle" in (el.get("Style") or ""):
            return spoken(el.get("Text"))
    return None


#: How Files builds its settings sidebar: one line per page, in the order it
#: shows them, with the caption and the icon each carries. Read from the view
#: model rather than from a list here, because the order is a thing that
#: changes and a list here would agree with yesterday's Files for ever.
NAV_ROW = re.compile(
    r"CreateNavigationItem\(\s*SettingsPageKind\.(\w+)\s*,"
    r'\s*"[^"]*"\s*,\s*Strings\.(\w+)\.GetLocalizedResource\(\)\s*,'
    r'\s*"([^"]+)"')


def navigation():
    """The settings pages, in the order the sidebar lists them."""
    text = open(VIEW_MODEL, encoding="utf-8-sig").read()
    out = []
    for page, key, glyph in NAV_ROW.findall(text):
        stem = page[:-len("Page")] if page.endswith("Page") else page
        out.append({"page": stem.lower(), "label": WORDS.get(key, key),
                    "glyph": glyph})
    return out


def collect():
    global WORDS
    WORDS = strings()
    pages = {}
    for name in sorted(os.listdir(PAGES)):
        if not name.endswith(".xaml"):
            continue
        stem = name[:-len(".xaml")]
        if stem in NOT_A_PAGE:
            continue
        root = ET.parse(os.path.join(PAGES, name)).getroot()
        key = stem[:-len("Page")] if stem.endswith("Page") else stem
        pages[key.lower()] = {
            "title": page_title(root),
            "rows": rows_under(root),
        }
    return pages


def count(pages):
    def walk(rows):
        return sum(1 + walk(r["items"]) for r in rows)
    return sum(walk(p["rows"]) for p in pages.values())


def main():
    pages = collect()
    nav = navigation()
    payload = {
        "//": "Generated by tools/extract_settings.py from the Files"
              " reference. Do not edit: regenerate.",
        "source": "files-community/Files, src/Files.App/Views/Settings",
        "pages": len(pages),
        "count": count(pages),
        "nav": nav,
        "settings": pages,
    }
    text = json.dumps(payload, indent=1, ensure_ascii=False) + "\n"

    if "--check" in sys.argv:
        current = open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        if current == text:
            print(f"current: {count(pages)} rows over {len(pages)} pages")
            return 0
        print(f"stale: regenerate tools/extract_settings.py"
              f" ({count(pages)} rows over {len(pages)} pages)")
        return 1

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(text)
    print(f"{count(pages)} rows over {len(pages)} pages written to"
          f" {os.path.relpath(OUT, PROTO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
