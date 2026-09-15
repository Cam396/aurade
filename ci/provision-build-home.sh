#!/bin/bash
# Give the build machine's home the shape the development build expects.
#
# build_v3.py builds its demo catalogue from the home of whoever runs it, and
# the static half of verify_all.py drives that catalogue: it resizes columns on
# real rows, opens a context menu on a real file, and walks history through real
# folders. A home with nothing in it builds a page with no rows, and about
# twenty gates then fail on `document.querySelector('.cell')` being null, which
# reads like twenty separate bugs and is one empty directory.
#
# That dependency was never written down. It survived only as whatever had
# accumulated in root's home, and when that home was wiped on 2026-09-14 the
# suite went from green to twenty-six failures with nothing to say why. Ship
# mode is unaffected either way: AURADE_SHIP builds from an empty temporary
# home on purpose, and a gate proves the shipped page carries nothing of this
# machine.
set -euo pipefail

HOME_DIR="${1:-$HOME}"
[ -n "$HOME_DIR" ] || { echo "no home to provision" >&2; exit 2; }
mkdir -p "$HOME_DIR"

python3 - "$HOME_DIR" <<'PY'
import os, sys
home = sys.argv[1]
try:
    from PIL import Image
except ImportError:
    Image = None

top = [
    ("note.txt",     "A note worth reading.\nSecond line.\n"),
    ("code.py",      'name = "has # inside"  # real comment\ndef go(n=512):\n    return n\n'),
    ("readme.md",    "# Readme\n\nSome **markdown** for the preview.\n"),
    ("data.json",    '{"key": "value", "n": 42}\n'),
    ("table.csv",    "col_a,col_b\n1,2\n3,4\n"),
]
folders = {
    "Desktop":   [("shortcut-notes.txt", "desktop note\n"), ("plan.md", "# Plan\n\n- one\n- two\n")],
    "Documents": [("report.txt", "a report\n"), ("budget.csv", "item,cost\npen,2\n"), ("notes.md", "# Notes\n")],
    "Downloads": [("installer.bin", "x" * 4096), ("page.html", "<h1>hi</h1>\n"), ("data.json", '{"a":1}\n')],
    "Music":     [("track-one.txt", "not really audio\n"), ("track-two.txt", "nor this\n")],
    "Videos":    [("clip-notes.txt", "about a clip\n"),
                  ("subtitles.srt", "1\n00:00:01,000 --> 00:00:02,000\nhi\n")],
    "Pictures":  [("caption.txt", "about the photo\n")],
}

for name, body in top:
    with open(os.path.join(home, name), "w") as fh:
        fh.write(body)
with open(os.path.join(home, "archive-sample.bin"), "wb") as fh:
    fh.write(os.urandom(200_000))

for d, files in folders.items():
    p = os.path.join(home, d)
    os.makedirs(p, exist_ok=True)
    for name, body in files:
        with open(os.path.join(p, name), "w") as fh:
            fh.write(body)
    #: A folder needs a picture in it for the thumbnail gates to have anything
    #: to hide, and the list needs more than one row for a bulk rename to be a
    #: bulk rename.
    if Image:
        Image.new("RGB", (400, 300), (100, 140, 180)).save(os.path.join(p, "preview.png"))

if Image:
    Image.new("RGB", (640, 480), (70, 120, 200)).save(os.path.join(home, "photo.png"))
    Image.new("RGB", (320, 240), (200, 120, 70)).save(os.path.join(home, "shot.png"))
    Image.new("RGB", (800, 600), (30, 30, 30)).save(os.path.join(home, "wallpaper.jpg"), "JPEG")
else:
    print("  Pillow is missing: the picture gates will have nothing to work on",
          file=sys.stderr)

print("provisioned %s: %d entries" % (home, len(os.listdir(home))))
PY
