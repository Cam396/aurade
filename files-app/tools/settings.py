"""Every setting Files has, against every setting this page has.

The list comes from `assets/files-settings.json`, which
`tools/extract_settings.py` generates from the reference's own settings XAML
and from the view model that orders its pages. Nothing here is written down
twice: regenerate that file and this moves with it.

    python3 tools/settings.py            # the gap, page by page
    python3 tools/settings.py --all      # every setting, with its state
    python3 tools/settings.py --tree     # the reference's rows, as they nest

This reads the builder's source, which makes it a claim about build_v3.py
rather than about the running page: the same trap the command table fell into
twice, where a regex over a page could not keep up with the page. It is the
tool for finding what to write next. The enforcing count is the
`settings-carries-the-reference-settings` gate in verify_all.py, which asks
the rendered settings page.
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROTO = os.path.dirname(HERE)
TABLE = os.path.join(PROTO, "assets", "files-settings.json")
#: The builder and its css/ and js/ files, read together.
sys.path.insert(0, PROTO)
import sources  # noqa: E402

#: What each of Files' settings is called here. Written down because the two
#: names cannot be derived from one another, and kept beside the list it maps
#: so a rename shows up as a miss rather than silently.
#:
#: A setting with no entry is one this page does not have. A wrong entry is
#: worse than no entry, so a row whose nearest thing here is a different
#: setting is left out: the reference's shelf pane toggle is not this page's
#: preview pane button, however similar the two read.
SAME = {
    # General
    "SelectedAppLanguageIndex": "language",
    "SelectedDateTimeFormatIndex": "dateFormat",
    "SelectedStartupSettingIndex": "startup",
    "OpenTabInExistingInstance": "startupExistingInstance",
    "AlwaysSwitchToNewlyOpenedTab": "alwaysSwitchNewTab",
    "ShowQuickAccessWidget": "widgets.qa",
    "ShowDrivesWidget": "widgets.drives",
    "ShowNetworkLocationsWidget": "widgets.network",
    "ShowFileTagsWidget": "widgets.tags",
    "ShowRecentFilesWidget": "widgets.recent",
    "AlwaysOpenDualPaneInNewTab": "dualPaneNewTab",
    "SelectedShellPaneArrangementType": "dualPaneSplit",
    "ShowOpenInNewTab": "contextMenu.openInNewTab",
    "ShowOpenInNewWindow": "contextMenu.openInNewWindow",
    "ShowOpenInNewPane": "contextMenu.openInNewPane",
    "ShowCopyPath": "contextMenu.copyPath",
    "ShowCreateFolderWithSelection": "contextMenu.createFolderWithSelection",
    "ShowCreateAlternateDataStream": "contextMenu.createAlternateDataStream",
    "ShowCreateShortcut": "contextMenu.createShortcut",
    "ShowPinToSideBar": "contextMenu.pinToSidebar",
    "ShowCompressionOptions": "contextMenu.compressionOptions",
    "ShowSendToMenu": "contextMenu.sendTo",
    "ShowOpenTerminal": "contextMenu.openTerminal",
    "ShowEditTagsMenu": "contextMenu.editTags",
    "MoveShellExtensionsToSubMenu": "contextMenuOverflow",
    "EnableSmoothScrolling": "smoothScrolling",
    "SelectedTabScrollDirectionIndex": "reverseTabScroll",

    # Appearance
    "SelectedThemeIndex": "theme",
    "SelectedBackdropMaterial": "backdropMaterial",
    "AppThemeBackgroundImageOpacity": "bgImageOpacity",
    "SelectedImageStretchType": "bgImageFit",
    "SelectedImageVerticalAlignmentType": "bgImageVAlign",
    "SelectedImageHorizontalAlignmentType": "bgImageHAlign",
    "SelectedAppThemeFontFamilyOption": "fontFamily",
    "ShowTabActions": "showTabActions",
    "ShowToolbar": "showToolbar",
    "ShowShelfPaneToggleButton": "showShelfBtn",
    "SelectedStatusCenterVisibilityOption": "showSCBtn",
    "ShowStatusBar": "showStatusbar",

    # Layout
    "SyncFolderPreferencesAcrossDirectories": "syncFolderPrefs",
    "SelectedDefaultLayoutModeIndex": "defLayout",
    "SelectedDefaultSortingIndex": "sortBy",
    "SortInDescendingOrder": "sortDesc",
    "SelectedDefaultSortPriorityIndex": "groupBy",
    "SelectedDefaultGroupingIndex": "groupByProperty",
    "GroupInDescendingOrder": "groupByDesc",
    "SelectedDefaultGroupByDateUnitIndex": "groupByDateUnit",
    "AutoSizeColumnsInDetailsLayout": "columns.autoSize",
    "ShowFileTagColumn": "columns.tag",
    "ShowSizeColumn": "columns.size",
    "ShowTypeColumn": "columns.type",
    "ShowDateColumn": "columns.dateModified",
    "ShowDateCreatedColumn": "columns.dateCreated",

    # Files and folders
    "ShowHiddenItems": "showHidden",
    "ShowDotFiles": "showDotFiles",
    "ShowProtectedSystemFiles": "showSystemFiles",
    "ShowFileExtensions": "showExt",
    "ShowThumbnails": "showThumbnails",
    "ShowCheckboxesWhenSelectingItems": "showCheckboxes",
    "SelectedOpenFilesWithSingleClickOption": "singleClickFiles",
    "SelectedOpenFoldersWithSingleClickOption": "singleClickFolders",
    "SelectedOpenFoldersInColumnsViewWithSingleClickOption":
        "singleClickColumns",
    "OpenFoldersNewTab": "openNewTab",
    "SelectedDeleteConfirmationPolicyIndex": "confirmDeletePolicy",
    "ShowFileExtensionWarning": "warnExtensionChange",
    "SelectFilesOnHover": "selectOnHover",
    "DoubleClickToGoUp": "dblclickUp",
    "ScrollToPreviousFolderWhenNavigatingUp": "scrollToPreviousFolder",
    "SizeUnitFormat": "sizeFormat",
    "CalculateFolderSizes": "calcFolderSizes",

    # Tags
    "AddTagCommand": "#btn-add-tag",

    # Developer tools
    "SelectedOpenInIDEOption": "statusIde",
    "ConnectToGitHubCommand": "#btn-gh-connect",
    "RemoveCredentialsCommand": "#btn-gh-disconnect",

    # Advanced
    "OpenOnWindowsStartup": "openOnStartup",
    "LeaveAppRunning": "leaveRunningInBackground",
    "ShowSystemTrayIcon": "showTrayIcon",
    "IsSetAsDefaultFileManager": "expReplaceExplorer",
    "IsSetAsOpenFileDialog": "expReplaceOpenDialog",
    "EnableThumbnailCache": "thumbnailCache",
    "ThumbnailCacheSizeLimit": "thumbnailCacheSizeMb",
    "ClearThumbnailCacheCommand": "#btn-clear-thumbs",
    "ShowFlattenOptions": "contextMenu.flattenOptions",
}

#: The rows that are about Windows rather than about a file manager, with
#: what each one is. Counted apart from the gap rather than inside it: a
#: number that can never reach its total stops being a measurement, and a
#: row silently dropped stops being a decision. If any of these grows an
#: equivalent here, it moves up into SAME.
NOT_HERE = {
    "ShowPinToStart": "the Windows Start Menu",
    "AreAlternateStreamsVisible": "NTFS alternate data streams",
}


def table():
    with open(TABLE, encoding="utf-8") as fh:
        return json.load(fh)


def flat(rows):
    """Every row, outermost first, the way a person scrolls past them."""
    out = []
    for row in rows:
        out.append(row)
        out += flat(row["items"])
    return out


def page_keys():
    """Every settings key the builder writes, however it writes it.

    Not by matching one call: a row is written as `createSwitch('k', ...)`,
    as `createSelect`, and as an object in an array a loop walks, and a regex
    that chases those spellings goes stale the next time one is added. The
    thirteen context menu toggles were reported as missing for exactly that
    reason.
    """
    text = sources.text()
    keys = set()
    for pattern in (
            r"create(?:Switch|Select|Slider|NumberInput|Number|Color|Text)"
            r"\('([^']+)'",
            r"key: '([^']+)'",
            r"getPref\('([^']+)'",
            r"setPref\('([^']+)'"):
        keys |= set(re.findall(pattern, text))
    #: A row that runs something rather than setting something has no key.
    #: It is named by the id of the button that runs it, so the id is what
    #: SAME points at, written with a leading hash to keep the two kinds of
    #: name from ever being confused for one another.
    keys |= {"#" + i for i in re.findall(r"id: '([^']+)'", text)}
    return keys


def show(rows, depth=0):
    for row in rows:
        kind = f"  <{row['control']}>" if row["control"] else ""
        print(f"{'  ' * depth}{row['header']}{kind}")
        show(row["items"], depth + 1)


def main():
    data = table()
    pages, nav = data["settings"], data["nav"]

    if "--tree" in sys.argv:
        for item in nav:
            print(f"\n=== {item['label']} ({item['page']}) ===")
            show(pages[item["page"]]["rows"])
        return 0

    keys = page_keys()
    total = held = 0
    unmapped, elsewhere = [], []
    for item in nav:
        rows = [r for r in flat(pages[item["page"]]["rows"])
                if r["control"] and r["setting"]]
        gap = []
        for row in rows:
            if row["setting"] in NOT_HERE:
                elsewhere.append(row["setting"])
                continue
            total += 1
            here = SAME.get(row["setting"])
            if here and here in keys:
                held += 1
                if "--all" in sys.argv:
                    print(f"{'held':>7}  {item['page']:<11}"
                          f"{row['setting']:<44}{here}")
            else:
                gap.append(row)
                if here:
                    unmapped.append((row["setting"], here))
        if gap and "--all" not in sys.argv:
            print(f"\n{item['label']} ({len(gap)} of {len(rows)} missing)")
            for row in gap:
                print(f"  {row['setting']:<44}{row['header']}")

    if unmapped:
        print("\nmapped to a key this page does not have:")
        for name, here in unmapped:
            print(f"  {name} -> {here}")

    print(f"\n{held} of {total} settings, {total - held} to go")
    if elsewhere:
        print(f"{len(elsewhere)} more are about Windows rather than about a"
              " file manager, and are counted apart:")
        for name in elsewhere:
            print(f"  {name}: {NOT_HERE[name]}")
    print("the enforcing count is the settings gate,"
          " which asks the rendered page")
    return 0


if __name__ == "__main__":
    sys.exit(main())
