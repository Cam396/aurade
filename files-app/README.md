# The Files window

This is the source of the window the Files app shows on AuraDE. It builds to
two files, `files.html` and `files.js`, which `ci/build-files-page.sh` writes
and which the `chromiumos-ash` package places into Chromium's `resources.pak`
as the Files app's page. Nothing here is compiled into Chromium: the page is a
resource, so it is built with the package rather than with the browser.

## Building

    ci/build-files-page.sh <output directory>

The output is deterministic. Two builds of the same sources are byte for byte
the same file, which is what lets the package test compare them.

The script builds in ship mode, which differs from a developer build in three
ways that matter for a release. It reads an empty temporary home rather than
the build machine's, so no path, user name, host name or volume of the machine
that built the package reaches the page. It emits `css/99-ship.css`, which
fills the frame and hides the page's own window buttons, because in the app
the frame is Ash's. And it writes the script to a file of its own rather than
inline, because the Files data source's script-src is `'self'`.

`AURADE_FILES_PAGE_SCRIPT` names the path the script tag asks for. It has to
be the path the script resource is served at inside the pak, which is not the
name of the file on disk and is not recorded anywhere in the pak. Getting it
wrong gives a page that draws perfectly and runs nothing.

## Layout

`build_v3.py` is the builder: the markup is a Python f string, generated from
the contracts in `assets/`, and the page's stylesheet and script are held
verbatim in `css/` and `js/`, one file per section, spliced in at the markers
`/*@@NAME@@*/`, `__BUILD("NAME")` and `@@NAME@@`. `sources.py` names every
source file, so a reader that walks the sources cannot miss one. `icons.py`,
`sidebar.py` and `localfs.py` are the glyph library, the places list and the
builder's view of a filesystem.

The script has three scopes: the layout switcher, the window, and the live
layer that talks to the service. They are separate closures. Crossing from one
to another goes through `window.__*` or it is a runtime error.

## Where it came from

The window follows the Files app for Windows, https://github.com/files-community/Files,
which is MIT licensed in `src/Files.App` and MPL-2.0 in `src/Files.App.Controls`.
The captions, the command set, the menus and the settings are modelled on it.
None of its art is here. The Windows shell icons, and the OneDrive, iCloud and
Google Drive marks, are not Files' to give away and are not ours either: every
folder, file type and place glyph in `icons.py` is drawn fresh.
