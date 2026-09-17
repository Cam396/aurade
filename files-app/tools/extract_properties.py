"""Turn Files' Properties window into the table this page is measured against.

Files builds the window as a navigation list and one page per entry, and
decides which entries an item gets in
`PropertiesNavigationItemsFactory.Initialize`. Reading the factory gives the
pages in the order the list shows them; reading each page's XAML gives the
captions a person actually sees on it. Nothing is retyped in between.

    python3 tools/extract_properties.py            # writes assets/files-properties.json
    python3 tools/extract_properties.py --check    # says whether it is current
"""

import json
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
PROTO = os.path.dirname(HERE)
REF = os.environ.get("FILES_REF", os.path.join(PROTO, "ref-files"))
PAGES = os.path.join(REF, "src/Files.App/Views/Properties")
FACTORY = os.path.join(
    REF, "src/Files.App/Data/Factories/PropertiesNavigationItemsFactory.cs")
RESW = os.path.join(REF, "src/Files.App/Strings/en-US/Resources.resw")
OUT = os.path.join(PROTO, "assets", "files-properties.json")

#: The window itself, and the page reached from a button on another page
#: rather than from the navigation list.
NOT_IN_THE_LIST = {"MainPropertiesPage", "SecurityAdvancedPage"}

#: An attribute whose value a person reads. `Content` covers a button's
#: caption, `PlaceholderText` the grey text in an empty box.
CAPTION_ATTRS = ("Text", "Header", "Content", "PlaceholderText")

RESOURCE = re.compile(r"\{helpers:ResourceString\s+Name=([^},\s]+)")

#: One line of the factory: the page, its caption and its icon.
NAV_ROW = re.compile(
    r"CreateNavigationItem\(\s*PropertiesNavigationViewItemType\.(\w+)\s*,"
    r"\s*Strings\.(\w+)\.GetLocalizedResource\(\)\s*,"
    r'\s*"([^"]+)"')

#: The order is the order they are added in, which is not the order they are
#: created in: Signatures is made last and shown second.
NAV_ADD = re.compile(
    r"propertiesNavigationItems\.Add\((\w+)Item\)")
NAV_VAR = re.compile(
    r"var (\w+)Item = CreateNavigationItem\(\s*"
    r"PropertiesNavigationViewItemType\.(\w+)")

WORDS = None


def strings():
    out = {}
    for data in ET.parse(RESW).getroot().findall("data"):
        name, value = data.get("name"), data.findtext("value")
        if name and value is not None:
            out[name] = value
    return out


def spoken(raw):
    found = RESOURCE.search(raw or "")
    if not found:
        return None
    key = found.group(1).replace("/", ".")
    return WORDS.get(key) or WORDS.get(key.replace(".", "_")) or key


def local(el):
    return el.tag.split("}")[-1]


#: `var securityItemEnabled = ...;`, which is the factory's own answer to
#: "does this item get this page". Kept as the reference's words rather than
#: as a verdict, the way the command table keeps `IsExecutable`: what this
#: page can honour and what it cannot stays visible.
NAV_WHEN = re.compile(r"var (\w+)ItemEnabled\s*=\s*(.*?);", re.S)

#: The two pages whose rule is written as a plain test rather than as a
#: variable, and the two branches that answer for a whole kind of item.
NAV_PLAIN = re.compile(
    r"if \(!(\w+)\)\s*propertiesNavigationItems\.Remove\((\w+)Item\);")
ONE_ITEM = "else if (item is ListedItem listedItem)"
A_DRIVE = "else if (item is DriveItem)"


def conditions(text):
    """When each page appears, for one item, in the reference's own words."""
    at = text.find(ONE_ITEM)
    end = text.find(A_DRIVE)
    if at < 0 or end < 0:
        return {}, []
    branch = text[at:end]
    out = {}
    for name, cond in NAV_WHEN.findall(branch):
        #: `hash` names the hashes page, and nothing else shortens its name.
        key = "hashes" if name == "hash" else name.lower()
        out[key] = " ".join(cond.split())
    for test, item in NAV_PLAIN.findall(branch):
        out.setdefault(item.lower(), test)
    gone = re.findall(r"propertiesNavigationItems\.Remove\((\w+)Item\)",
                      text[end:])
    return out, sorted({g.lower() for g in gone})


def navigation():
    """The pages, in the order the list shows them."""
    text = open(FACTORY, encoding="utf-8-sig").read()
    label, glyph = {}, {}
    for kind, key, icon in NAV_ROW.findall(text):
        label[kind] = WORDS.get(key, key)
        glyph[kind] = icon
    when, not_on_a_drive = conditions(text)
    var_kind = dict(NAV_VAR.findall(text))
    out = []
    for var in NAV_ADD.findall(text):
        kind = var_kind.get(var)
        if not kind:
            continue
        page = kind.lower()
        out.append({"page": page, "label": label.get(kind),
                    "glyph": glyph.get(kind),
                    "when": when.get(page),
                    "onADrive": page not in not_on_a_drive})
    return out


def captions(path):
    """Every caption on one page, in the order XAML writes them.

    Deduplicated, because a caption written once as a header and once inside
    a template is one caption as far as a person is concerned, and the page
    that draws it here draws it once.
    """
    out = []
    for el in ET.parse(path).getroot().iter():
        for attr in CAPTION_ATTRS:
            said = spoken(el.get(attr))
            if said and said not in out:
                out.append(said)
    return out


def collect():
    global WORDS
    WORDS = strings()
    pages = {}
    for name in sorted(os.listdir(PAGES)):
        if not name.endswith(".xaml"):
            continue
        stem = name[:-len(".xaml")]
        key = stem[:-len("Page")] if stem.endswith("Page") else stem
        pages[key.lower()] = {
            "inTheList": stem not in NOT_IN_THE_LIST,
            "captions": captions(os.path.join(PAGES, name)),
        }
    return pages


def main():
    pages = collect()
    nav = navigation()
    total = sum(len(p["captions"]) for p in pages.values())
    payload = {
        "//": "Generated by tools/extract_properties.py from the Files"
              " reference. Do not edit: regenerate.",
        "source": "files-community/Files, src/Files.App/Views/Properties",
        "pages": len(pages),
        "count": total,
        "nav": nav,
        "properties": pages,
    }
    text = json.dumps(payload, indent=1, ensure_ascii=False) + "\n"

    if "--check" in sys.argv:
        current = open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        if current == text:
            print(f"current: {total} captions over {len(pages)} pages")
            return 0
        print(f"stale: regenerate tools/extract_properties.py"
              f" ({total} captions over {len(pages)} pages)")
        return 1

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(text)
    print(f"{total} captions over {len(pages)} pages written to"
          f" {os.path.relpath(OUT, PROTO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
